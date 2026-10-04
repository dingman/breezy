"""AUT-1 ``CaptureGuardedStrategy``: the capture guard on every order a strategy submits.

Plan r12 section 3.6 (r8 section 3.5 tests re-targeted to the publisher). LIBRARY ONLY in WP2:
nothing composes it into the live node, and FQ's live strategy is not re-based on it until WP7.

``submit_order`` / ``submit_order_list`` run, per order:

1. **Exit** (a SELL carrying ``exit_rule=``): write its ``FrameCopy`` then its ``DecisionRecord``,
   flush, then ``super()``. An exit is NEVER refused. A missing tag or a failed publish or flush is
   an ``exit_capture_gap`` detector event plus a CRITICAL, and the order still goes.
2. **Untagged SELL**: an ``untagged_sell`` detector event plus a CRITICAL, then ``super()`` (SELLs
   reduce risk; the audit fails the fill as ``untagged_order``).
3. **BUY tag check**: exactly one ``breezy:decision_id=`` tag of 32 lowercase hex characters, else
   refuse ``capture_untagged`` (no ``super()``, so the order never reaches the cache).
4. **Health**: ``publisher.health.ok`` False refuses ``capture_gap``.
5. **Flush**: ``publisher.flush_for_submit()`` False refuses a BUY ``capture_gap``.

A refusal logs ``CAPTURE_REFUSED``, offers a CRITICAL through the outbox, and records an
``EntryVeto`` when the tag names a Take of this boot (else a ``DetectorEvent``). The exit exemption
is SELL-only: a BUY that carries exit tags still needs a decision tag. A ``capture_gap`` refusal is
NOT a Take-path record: its ``EntryVeto`` cites the Take's frame by reference (kind and ``ts_event``
copied from the Take) and never publishes a ``FrameCopy`` (r8-final MEDIUM).

This module is family-agnostic: it imports nothing from any composition kind's package.
"""

import re
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, fields
from typing import Any, Final, Protocol

from nautilus_trader.model.enums import OrderSide
from nautilus_trader.trading.strategy import Strategy

from breezy.persistence.autonomy.canonical import canonical_json, sha256_hex
from breezy.persistence.autonomy.capture_alerts import CAPTURE_ALERT_SEVERITIES
from breezy.persistence.autonomy.capture_ids import (
    compute_exit_decision_id,
    compute_orphan_decision_id,
)
from breezy.persistence.autonomy.capture_publish import CapturePublisher
from breezy.persistence.autonomy.capture_records import (
    DECISION_SCHEMA,
    DETECTOR_SCHEMA,
    FRAME_COPY_SCHEMA,
    NULL_STR,
    SOURCES,
    DecisionRecord,
    DetectorEvent,
    FrameCopy,
    make_record,
)
from breezy.persistence.autonomy.veto import VetoReason
from breezy.persistence.exit_tags import (
    DECISION_ID_TAG_PREFIX,
    EXIT_CLIENT_ORDER_ID_TAG_PREFIX,
    EXIT_FAMILY_TAG_PREFIX,
    EXIT_POSITION_TAG_PREFIX,
    EXIT_RULE_TAG_PREFIX,
)

__all__ = [
    "KNOWN_TAKES_CAP",
    "AlertOutbox",
    "CaptureGuardedStrategy",
    "CaptureIdentity",
    "FollowUp",
    "decision_follow_up",
]

#: This boot's Takes the guard remembers, to join a refusal to its Take. O(Takes per day), bounded.
KNOWN_TAKES_CAP: Final[int] = 4096

REASON_CAPTURE_UNTAGGED: Final[str] = VetoReason.CAPTURE_UNTAGGED.value
REASON_CAPTURE_GAP: Final[str] = VetoReason.CAPTURE_GAP.value
REASON_EXIT: Final[str] = "exit"

DETECTOR_CAPTURE_WRITER_HEALTH: Final[str] = "capture_writer_health"
STATE_DISAGREE: Final[str] = "DISAGREE"
CAUSE_EXIT_CAPTURE_GAP: Final[str] = "exit_capture_gap"
CAUSE_UNTAGGED_SELL: Final[str] = "untagged_sell"
CAUSE_UNTAGGED_BUY: Final[str] = "untagged_buy"
CAUSE_ORDER_LIST_REFUSED: Final[str] = "capture_order_list_refused"
REFUSED_EVENT: Final[str] = "CAPTURE_REFUSED"

_DECISION_ID_RE: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{32}")
_EXIT_PREFIXES: Final[tuple[str, ...]] = (
    EXIT_RULE_TAG_PREFIX,
    EXIT_POSITION_TAG_PREFIX,
    EXIT_FAMILY_TAG_PREFIX,
    EXIT_CLIENT_ORDER_ID_TAG_PREFIX,
)
#: A follow-up record (TrySubmit, EntryVeto, ...) carries no probabilities (r8 field map).
_FOLLOW_UP_NULLED: Final[tuple[str, ...]] = (
    "p_hat",
    "p_hat_raw",
    "p_lower",
    "p_upper",
    "ev_net",
    "margin",
)
_FOLLOW_UP_OWN_FIELDS: Final[frozenset[str]] = frozenset({"kind", "reason", "wall_ns"})
_ORDER_REF_HEX_LEN: Final[int] = 16
_ROLE_EXIT: Final = "exit"
_ROLE_SELL: Final = "untagged_sell"
_ROLE_BUY: Final = "buy"


class AlertOutbox(Protocol):
    """The node outbox's seam (WP1-R1, WP4-R2): ``offer(event, severity, detail) -> accepted``."""

    def offer(self, event: str, severity: str, detail: str) -> bool: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class CaptureIdentity:
    """The per-family, per-boot values every capture record stamps."""

    family_id: str
    node_boot_id: str
    build_sha: str
    registry_seq: int
    drill: bool
    source: str
    artefact_sha256: str
    manifest_sha256: str

    def __post_init__(self) -> None:
        for name in ("family_id", "node_boot_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")
        if self.source not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}, was {self.source!r}")


@dataclass(frozen=True, slots=True, kw_only=True)
class FollowUp:
    """How a Take continues: the ``kind`` (TrySubmit, EntryVeto, Refuse), its ``reason`` and its own
    ``wall_ns``. Every caller passes a constant reason."""

    kind: str
    reason: str
    wall_ns: int


def decision_follow_up(take: Any, outcome: FollowUp) -> DecisionRecord:
    """A record that continues a Take: same id, key, clock and frame reference, the outcome's own
    ``kind``, ``reason`` and ``wall_ns``, and no probabilities. Pure.

    The ``reason=`` read below is an enumerated copy site of the closure lint (WP2-R2).
    """
    carried: dict[str, Any] = {
        f.name: getattr(take, f.name) for f in fields(take) if f.name not in _FOLLOW_UP_OWN_FIELDS
    }
    carried.update({name: NULL_STR for name in _FOLLOW_UP_NULLED})
    return make_record(
        DecisionRecord,
        ts_event=take.eval_ns,
        ts_init=outcome.wall_ns,
        kind=outcome.kind,
        reason=outcome.reason,
        wall_ns=outcome.wall_ns,
        **carried,
    )


@dataclass(frozen=True, slots=True)
class _Plan:
    order: Any
    role: str
    tags: tuple[str, ...]

    @property
    def client_order_id(self) -> str:
        return str(self.order.client_order_id)

    @property
    def order_ref(self) -> str:
        """A short digest that correlates a log or alert line with the order without printing its
        id (ARCH payload hygiene: no order id in a logged or alerted payload)."""
        return sha256_hex(self.client_order_id.encode("utf-8"))[:_ORDER_REF_HEX_LEN]

    @property
    def decision_tag_values(self) -> tuple[str, ...]:
        return _tag_values(self.tags, DECISION_ID_TAG_PREFIX)

    @property
    def tag_is_valid(self) -> bool:
        values = self.decision_tag_values
        return len(values) == 1 and _DECISION_ID_RE.fullmatch(values[0]) is not None


def _tag_values(tags: Sequence[str], prefix: str) -> tuple[str, ...]:
    return tuple(tag[len(prefix) :] for tag in tags if tag.startswith(prefix))


def _exit_values(tags: Sequence[str]) -> tuple[str, str, str, str] | None:
    found = [_tag_values(tags, prefix) for prefix in _EXIT_PREFIXES]
    if any(len(values) != 1 or not values[0] for values in found):
        return None
    rule, position, family, client_order_id = (values[0] for values in found)
    return rule, position, family, client_order_id


class CaptureGuardedStrategy(Strategy):
    """A ``Strategy`` whose every submit passes the capture guard (module docstring)."""

    def __init__(
        self,
        config: Any,
        *,
        capture_publisher: CapturePublisher,
        alert_outbox: AlertOutbox,
        capture_identity: CaptureIdentity,
    ) -> None:
        if not isinstance(capture_publisher, CapturePublisher):
            raise TypeError("capture_publisher must be a CapturePublisher")
        if not callable(getattr(alert_outbox, "offer", None)):
            raise TypeError("alert_outbox must provide offer(event, severity, detail)")
        if not isinstance(capture_identity, CaptureIdentity):
            raise TypeError("capture_identity must be a CaptureIdentity")
        super().__init__(config)
        self._capture_publisher = capture_publisher
        self._capture_outbox = alert_outbox
        self._capture_identity = capture_identity
        self._known_takes: OrderedDict[str, Any] = OrderedDict()
        self.guard_alert_drops = 0

    # -- hooks ---------------------------------------------------------------------------------

    def _capture_key_of(self, instrument_id: Any) -> tuple[str, str, str, str] | None:
        """``(station, climate_day, rung_id, side)`` of an instrument, or ``None`` when unknown. A
        family overrides it from its own instrument context."""
        return None

    def note_take(self, record: Any) -> None:
        """Remember a published Take so a later refusal can name it. Bounded; non-Takes ignored."""
        if getattr(record, "kind", None) != "Take":
            return
        self._known_takes[record.decision_id] = record
        self._known_takes.move_to_end(record.decision_id)
        while len(self._known_takes) > KNOWN_TAKES_CAP:
            self._known_takes.popitem(last=False)

    def known_take_count(self) -> int:
        return len(self._known_takes)

    # -- the guarded sends ----------------------------------------------------------------------

    def submit_order(
        self,
        order: Any,
        position_id: Any = None,
        client_id: Any = None,
        params: Any = None,
    ) -> None:
        if self._admit([order], is_list=False):
            super().submit_order(order, position_id, client_id, params)

    def submit_order_list(
        self,
        order_list: Any,
        position_id: Any = None,
        client_id: Any = None,
        params: Any = None,
    ) -> None:
        if self._admit(list(order_list.orders), is_list=True):
            super().submit_order_list(order_list, position_id, client_id, params)

    # -- steps 1 to 5 ---------------------------------------------------------------------------

    def _admit(self, orders: Sequence[Any], *, is_list: bool) -> bool:
        plans = [self._classify(order) for order in orders]
        refusals = self._buy_refusals(plans)
        if refusals:
            self._refuse(refusals, is_list=is_list)
            return False
        for plan in plans:
            if plan.role == _ROLE_EXIT:
                self._capture_exit(plan)
            elif plan.role == _ROLE_SELL:
                self._flag(plan, CAUSE_UNTAGGED_SELL)
        if not any(plan.role in (_ROLE_BUY, _ROLE_EXIT) for plan in plans):
            return True
        if self._capture_publisher.flush_for_submit():
            return True
        buys = [plan for plan in plans if plan.role == _ROLE_BUY]
        if buys:
            self._refuse([(plan, REASON_CAPTURE_GAP) for plan in buys], is_list=is_list)
            return False
        exit_plan = next(plan for plan in plans if plan.role == _ROLE_EXIT)
        self._flag(exit_plan, CAUSE_EXIT_CAPTURE_GAP)  # an exit is never refused
        return True

    @staticmethod
    def _classify(order: Any) -> _Plan:
        tags = tuple(order.tags or ())
        if order.side != OrderSide.SELL:
            return _Plan(order, _ROLE_BUY, tags)
        is_exit = any(tag.startswith(EXIT_RULE_TAG_PREFIX) for tag in tags)
        return _Plan(order, _ROLE_EXIT if is_exit else _ROLE_SELL, tags)

    def _buy_refusals(self, plans: Sequence[_Plan]) -> list[tuple[_Plan, str]]:
        healthy = self._capture_publisher.health.ok
        refusals: list[tuple[_Plan, str]] = []
        for plan in plans:
            if plan.role != _ROLE_BUY:
                continue
            if not plan.tag_is_valid:
                refusals.append((plan, REASON_CAPTURE_UNTAGGED))
            elif not healthy:
                refusals.append((plan, REASON_CAPTURE_GAP))
        return refusals

    # -- refusals -------------------------------------------------------------------------------

    def _refuse(self, refusals: Sequence[tuple[_Plan, str]], *, is_list: bool) -> None:
        for plan, reason in refusals:
            self._refuse_one(plan, reason)
        if is_list:
            first = refusals[0][0]
            self._flag(first, CAUSE_ORDER_LIST_REFUSED)

    def _refuse_one(self, plan: _Plan, reason: str) -> None:
        self.log.error(f"{REFUSED_EVENT} reason={reason} order_ref={plan.order_ref}")
        self._offer(reason, plan)
        take = self._known_take(plan)
        if take is not None:
            now = self.clock.timestamp_ns()
            self._capture_publisher.write(
                decision_follow_up(take, FollowUp(kind="EntryVeto", reason=reason, wall_ns=now))
            )
            return
        cause = CAUSE_UNTAGGED_BUY if reason == REASON_CAPTURE_UNTAGGED else reason
        self._publish_detector(plan, cause)

    def _known_take(self, plan: _Plan) -> Any:
        for value in plan.decision_tag_values:
            take = self._known_takes.get(value)
            if take is not None:
                return take
        return None

    # -- exits and flags ------------------------------------------------------------------------

    def _capture_exit(self, plan: _Plan) -> None:
        values = _exit_values(plan.tags)
        if values is None:
            self._flag(plan, CAUSE_EXIT_CAPTURE_GAP)
            return
        order = plan.order
        decision_id = compute_exit_decision_id(*values)
        now = self.clock.timestamp_ns()
        price = getattr(order, "price", None)
        price_text = str(price) if price is not None else NULL_STR
        copy = make_record(
            FrameCopy,
            ts_event=0,
            ts_init=now,
            schema=FRAME_COPY_SCHEMA,
            decision_id=decision_id,
            frame_kind=NULL_STR,
            instrument=str(order.instrument_id),
            frame_ts_event=0,
            frame_body={"price": price_text},
        )
        record = self._exit_record(plan, decision_id, price_text, now)
        if not (self._capture_publisher.write(copy) and self._capture_publisher.write(record)):
            self._flag(plan, CAUSE_EXIT_CAPTURE_GAP)

    def _exit_record(
        self, plan: _Plan, decision_id: str, price_text: str, now: int
    ) -> DecisionRecord:
        order, ident = plan.order, self._capture_identity
        key = self._key_of(order.instrument_id) or (NULL_STR,) * 4
        station, climate_day, rung_id, side = key
        return make_record(
            DecisionRecord,
            ts_event=order.ts_init,
            ts_init=now,
            schema=DECISION_SCHEMA,
            decision_id=decision_id,
            family_id=ident.family_id,
            node_boot_id=ident.node_boot_id,
            build_sha=ident.build_sha,
            registry_seq=ident.registry_seq,
            drill=ident.drill,
            source=ident.source,
            kind="Exit",
            reason=REASON_EXIT,
            eval_ns=order.ts_init,
            eval_seq=0,
            wall_ns=now,
            station=station,
            climate_day=climate_day,
            rung_id=rung_id,
            side=side,
            instrument=str(order.instrument_id),
            ask_px=price_text,
            frame_kind=NULL_STR,
            frame_ts_event=0,
            artefact_sha256=ident.artefact_sha256,
            manifest_sha256=ident.manifest_sha256,
        )

    def _key_of(self, instrument_id: Any) -> tuple[str, str, str, str] | None:
        try:
            return self._capture_key_of(instrument_id)
        except Exception:  # noqa: BLE001 - a family hook can never break a submit
            return None

    def _flag(self, plan: _Plan, cause: str) -> None:
        """A guard cause that does not refuse: a detector event plus a CRITICAL."""
        self._offer(cause, plan)
        self._publish_detector(plan, cause, orphan=cause == CAUSE_UNTAGGED_SELL)

    # -- detector events and alerts -----------------------------------------------------------

    def _observation(self, plan: _Plan, cause: str, *, orphan: bool = False) -> dict[str, str]:
        obs = {
            "cause": cause,
            "client_order_id": plan.client_order_id,
            "instrument": str(plan.order.instrument_id),
        }
        if orphan:
            obs["orphan_decision_id"] = compute_orphan_decision_id(
                self._capture_identity.family_id, plan.client_order_id
            )
        return obs

    def _publish_detector(self, plan: _Plan, cause: str, *, orphan: bool = False) -> None:
        ident = self._capture_identity
        now = self.clock.timestamp_ns()
        observation = self._observation(plan, cause, orphan=orphan)
        self._capture_publisher.write(
            make_record(
                DetectorEvent,
                ts_event=now,
                ts_init=now,
                schema=DETECTOR_SCHEMA,
                detector=DETECTOR_CAPTURE_WRITER_HEALTH,
                observation_sha256=sha256_hex(canonical_json(observation)),
                state=STATE_DISAGREE,
                node_boot_id=ident.node_boot_id,
                drill=ident.drill,
                source=ident.source,
            )
        )

    def _offer(self, cause: str, plan: _Plan) -> None:
        detail = (
            f"cause={cause} family={self._capture_identity.family_id} order_ref={plan.order_ref}"
        )
        try:
            accepted = self._capture_outbox.offer(
                REFUSED_EVENT, CAPTURE_ALERT_SEVERITIES[REFUSED_EVENT], detail
            )
        except Exception:  # noqa: BLE001 - an outbox failure is counted, never raised
            accepted = False
        if not accepted:
            self.guard_alert_drops += 1
            self.log.error(f"CAPTURE_REFUSED_ALERT_UNDELIVERED cause={cause}")
