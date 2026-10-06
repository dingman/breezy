"""Composition root for ``breezy-trade`` (shadow-mode ``current_rung_hold``).

Owns the ONE submit-intent latch opener for the process lifetime: opens
``SqliteStateStore`` + ``open_submit_intent_latch`` exactly once, on the
main thread, inside an ``ExitStack`` that unwinds on every exit path, and
injects the same opened latch into (a) the strategy factory via
``open_trial_day_latch`` and (b) the exec client via
``PolymarketUSExecClientConfig.submit_intent_latch``. The exec client never
opens its own latch.

``orders_enabled`` is never set from env and is never passed to the config.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import re
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, TextIO

from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.identifiers import ClientId
from nautilus_trader.trading.strategy import Strategy

from breezy.adapters.polymarket_us.factories import (
    POLYMARKET_US_CLIENT_NAME,
    exec_config_from_env,
    shared_polymarket_us_http_client,
)
from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient
from breezy.adapters.polymarket_us.symbology import instrument_id_to_slug
from breezy.adapters.polymarket_us.transport import QUOTA_KEY_DISCOVERY
from breezy.domain.climate_day import climate_day_for_instant
from breezy.ingest.nbm_quantile_actor import NbmQuantileActor, NbmQuantileActorConfig
from breezy.persistence.family_manifest import (
    FamilyManifest,
    FamilyManifestError,
    load_family_manifest,
)
from breezy.persistence.live_orders_gate import (
    LiveOrdersGateRefusedError,
    live_orders_authorized,
)
from breezy.registry.sites import default_registry
from breezy.runtime import trade_cli
from breezy.runtime.health import AlertPayload, emit_alert, resolve_alert_sink
from breezy.runtime.order_enablement import OrderSubmissionPermit, OrderSubmissionRefused
from breezy.runtime.settings import (
    ORDERS_ENABLED_VAR,
    SENDING_FAMILY_ID_VAR,
    BreezyTradeSettings,
    SettingsError,
    load_trade_settings,
)
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import (
    SubmitIntentLatch,
    SubmitIntentLockError,
    SubmitIntentLockHeld,
    open_submit_intent_latch,
)
from breezy.runtime.trade_cli import EXIT_CONFIG_ERROR, EXIT_RUNTIME_ERROR, NodeFactory, _report
from breezy.strategy.current_rung_hold.composition import (
    build_continuous_rung_hold_strategies,
    build_current_rung_hold_strategies,
    family_halt_submit_veto,
    install_current_rung_hold_refusal_watch,
    make_trial_day_latch_factory,
    phase1_sending_permit,
)
from breezy.strategy.current_rung_hold.config import SUPPORTED_STATIONS
from breezy.strategy.current_rung_hold.continuous_strategy import Phase0PermitForbiddenError
from breezy.strategy.current_rung_hold.fee_drift_probe import (
    FeeDriftProbeActor,
    WireFeeCoefficientError,
    fetch_wire_fee_coefficient,
)
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    TrialDayLatch,
    open_trial_day_latch,
)
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import (
    CalibrationArtefactPinMismatchError,
)
from breezy.strategy.forecast_quantile_ladder.composition import (
    NoTradableForecastInstrumentsError,
    build_forecast_quantile_ladder_strategies,
)
from breezy.strategy.forecast_quantile_ladder.decision_funnel import (
    FqDecisionCounts,
    FqDecisionFunnelActor,
)
from breezy.strategy.forecast_quantile_ladder.persistent_latch import (
    FORECAST_QUANTILE_TRIAL_KEY_PREFIX,
    PersistentQuantileLadderLatch,
)
from breezy.strategy.forecast_quantile_ladder.strategy import ForecastQuantileLadderStrategy

_VENUE = "polymarket_us"

#: WP-11b (active-family registry, cardinality-1): where every family
#: manifest lives, relative to the process CWD -- `trade_supervisor.py`'s
#: `_launch`/`_relaunch` always set `cwd=str(repo_root)` before spawning
#: this process, the same relative-path convention `deploy/families/*.json`
#: already uses everywhere else (test fixtures, `scripts/analysis/*`'s own
#: `--family-manifest` CLI args, `runtime.settings`'s own load-time
#: validation). Replaces the retired single-family manifest-path module
#: constant this file used to carry -- promoting a revision is now
#: `settings.sending_family_id` + this registry directory, never a source
#: edit (test_promoted_revision_requires_no_src_edit).
_FAMILIES_DIR: Final[Path] = Path("deploy/families")

#: ``AlertPayload.event``/``site``/``severity`` for a refused live-trading
#: permit in ``main()`` -- the ONLY refusal here that continues the run in
#: shadow mode (an ``OrderSubmissionPermit`` refusal a few lines later is
#: FATAL and is not an alert candidate). ``site`` is ``"global"``, matching
#: ``component_health_watch.py``'s convention for a process-wide condition.
LIVE_TRADING_PERMIT_REFUSED_EVENT: Final[str] = "LIVE_TRADING_PERMIT_REFUSED"
LIVE_TRADING_PERMIT_REFUSED_SEVERITY: Final[str] = "WARN"
LIVE_TRADING_PERMIT_REFUSED_SITE: Final[str] = "global"

#: [A-1, 2026-09-25] A plain, non-negative integer only -- same ASCII/
#: anchoring discipline as ``safety.py``'s own ``_MONEY_RE``/``_COUNT_RE``.
_PERMIT_EXPIRY_CEILING_NS_RE: Final = re.compile(r"^[0-9]+\Z")


def _resolve_permit_expiry_ceiling_ns() -> int | None:
    """Read ``PERMIT_EXPIRY_CEILING_NS_ENV_VAR`` (A-1): supervisor-injected
    only, for a mid-day-relaunched child -- never set for the 16:50Z daily
    boot. Absent -> ``None`` (unchanged, unbounded-by-this-mechanism
    behaviour). Present but not a plain non-negative integer -> raises
    ``LiveTradingPermissionError``, refusing the permit through the SAME
    fail-closed path ``main()`` already uses for every other mint
    precondition -- never silently falling back to an unbounded permit.
    """
    from breezy.adapters.polymarket_us.safety import LiveTradingPermissionError
    from breezy.runtime.trade_supervisor_core import PERMIT_EXPIRY_CEILING_NS_ENV_VAR

    raw = os.environ.get(PERMIT_EXPIRY_CEILING_NS_ENV_VAR)
    if raw is None:
        return None
    if not _PERMIT_EXPIRY_CEILING_NS_RE.match(raw):
        raise LiveTradingPermissionError(
            f"{PERMIT_EXPIRY_CEILING_NS_ENV_VAR} is set but is not a plain "
            f"non-negative integer; refusing rather than minting an unbounded permit"
        )
    return int(raw)


#: ``AlertPayload.detail`` is a small closed set of static reasons -- never
#: exception text, never a permit/config value (L-22 shape). ``main()`` has
#: exactly one catch site for ``issue_live_trading_permit``'s
#: ``LiveTradingPermissionError``, and distinguishing WHY it refused
#: (``orders_not_enabled`` / ``permit_expired`` / ``permit_missing``) would
#: mean parsing the exception's message -- not done here. So today this is
#: the one reason ever emitted; the name stays a closed enum for when a
#: second call site needs a different member.
LIVE_TRADING_PERMIT_REFUSED_DETAIL: Final[str] = "permit_missing"


#: ``main()``'s permit-audit lines run BEFORE ``trade_cli.run()`` ever
#: builds a ``TradingNode`` -- and it is that construction which both
#: installs ``runtime.logging_bridge`` on the ``breezy`` namespace AND
#: initialises NautilusTrader's own native logging subsystem (the
#: bridge's target ``Logger`` is a documented no-op until then). Without a
#: handler, an audit line logged prior to that point inherits the stdlib
#: root logger's default (WARNING, no handler), so it is silently
#: discarded -- not queued, not raised, never seen -- regardless of
#: whether the permit it describes was actually minted. That is the root
#: cause of the missing "live-trading permit issued"/"order submission
#: permit not issued" lines: the process's real stdout+stderr ARE
#: captured into the per-launch log file (``trade_supervisor.py::spawn``,
#: ``stdout=log_fh, stderr=STDOUT``), so a plain stdlib handler attached
#: directly here -- independent of Nautilus's own init order -- is
#: sufficient.
#:
#: The audit lines are logged through a DEDICATED logger
#: (``breezy.app.trade.boot``, below), never ``trade_cli.logger``
#: (``breezy.runtime.trade_cli``): ``trade_cli.logger`` is the same logger
#: ``trade_cli.run()`` uses for the whole node's runtime faults
#: (``trade_cli.py:208,222,243,262``), and once ``run()`` installs
#: ``runtime.logging_bridge`` on the ``breezy`` namespace, any handler left
#: attached directly to ``trade_cli.logger`` would print every one of
#: those lines twice for the node's entire life -- once raw, once via the
#: bridge. The dedicated boot logger keeps this handler scoped to the
#: boot-only audit lines and off ``trade_cli.logger`` entirely. Idempotent:
#: safe to call on every ``main()`` invocation.
_BOOT_LOG_FORMAT: Final[str] = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

#: Name of the dedicated boot-audit logger -- deliberately NOT
#: ``trade_cli.logger`` (``breezy.runtime.trade_cli``); see the module
#: note above ``_BOOT_LOG_FORMAT``.
_BOOT_LOGGER_NAME: Final[str] = "breezy.app.trade.boot"
_boot_logger = logging.getLogger(_BOOT_LOGGER_NAME)


def _ensure_boot_logging_visible() -> None:
    """Attach a plain stderr handler to the dedicated boot-audit logger
    (``breezy.app.trade.boot``) so its INFO+ lines reach the process's own
    stdout/stderr from the first line of ``main()``, well before
    ``runtime.logging_bridge``/Nautilus's own logging subsystem exist.
    Never touches ``trade_cli.logger``, the ``breezy`` bridge namespace,
    or the root logger.
    """
    if any(isinstance(h, logging.StreamHandler) for h in _boot_logger.handlers):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_BOOT_LOG_FORMAT))
    _boot_logger.addHandler(handler)
    _boot_logger.setLevel(logging.INFO)


def _composable_stations(manifest: FamilyManifest) -> tuple[str, ...]:
    """Stations this boot may compose, in ``SUPPORTED_STATIONS`` order.

    The manifest is the only source. Anything outside the allow-list refuses
    the boot by name -- it is never dropped. An empty intersection refuses
    too, rather than falling back to the allow-list.
    """
    declared = tuple(manifest.stations)
    declared_set = set(declared)
    unsupported = [station for station in declared if station not in SUPPORTED_STATIONS]
    allowed = tuple(station for station in SUPPORTED_STATIONS if station in declared_set)
    if not allowed:
        message = (
            f"{manifest.family_id}: refusing boot; intersection of stations "
            f"{list(declared)!r} with SUPPORTED_STATIONS {list(SUPPORTED_STATIONS)!r} "
            "is empty"
        )
        if unsupported:
            message += f"; unsupported: {unsupported!r}"
        _boot_logger.error(message)
        raise SettingsError(message)
    if unsupported:
        message = (
            f"{manifest.family_id}: refusing boot; stations {list(declared)!r} "
            f"include values outside SUPPORTED_STATIONS {list(SUPPORTED_STATIONS)!r}; "
            f"unsupported: {unsupported!r}"
        )
        _boot_logger.error(message)
        raise SettingsError(message)
    return allowed


def _today_by_station(stations: Sequence[str]) -> dict[str, dt.date]:
    registry = default_registry()
    now = dt.datetime.now(tz=dt.UTC)
    return {
        station: climate_day_for_instant(
            now, registry.climate_day_window(_VENUE, station).std_utc_offset_hours
        )
        for station in stations
    }


#: AUD-12b: the family-halt reason ``FeeDriftProbeActor`` records via
#: ``TrialDayLatch.record_policy_halt`` on a confirmed DISAGREE. A closed,
#: fixed string -- never a value derived from the observed drift, which
#: goes in ``evidence_sha256`` instead (hashed, per ``AlertPayload``'s own
#: "never a raw upstream value" convention).
_FEE_DRIFT_HALT_REASON: Final[str] = "fee_schedule_drift"


def _representative_fee_drift_slug(strategies: Sequence[Strategy]) -> str | None:
    """The one representative slug AUD-12b's probe checks (§6 item 3: a
    single-slug design, evidence-justified in ``fee_drift_probe.py``'s own
    module docstring).

    Derived from the SAME ``today_by_station``-driven instrument resolution
    ``build_continuous_rung_hold_strategies`` already performed for
    ``strategies`` -- ``strategy.config.instrument_ids`` (the SAME public
    accessor ``strike_ladder.py`` already uses), never a second catalog
    read. The first composed strategy that resolved at least one instrument
    wins; ``None`` only when every station resolved zero, which
    ``build_continuous_rung_hold_strategies`` already refuses earlier for
    the all-zero case -- this is a defensive fallback, not the expected path.
    """
    for strategy in strategies:
        instrument_ids = getattr(strategy.config, "instrument_ids", ())
        if instrument_ids:
            return instrument_id_to_slug(instrument_ids[0])
    return None


def _fq_representative_slug(
    strategies: Sequence[ForecastQuantileLadderStrategy],
) -> str | None:
    """S6's ``slug_fn`` for the ``forecast_quantile_ladder`` fee probe.

    Unlike :func:`_representative_fee_drift_slug` (which reads the FROZEN
    ``strategy.config.instrument_ids`` -- fixed at construction time), this
    reads each strategy's LIVE ``current_yes_instrument_slug()``, which
    reflects whatever the D+1 readiness poll has subscribed so far. Called
    on every fetch (never cached), so a late subscription is picked up.
    """
    for strategy in strategies:
        slug = strategy.current_yes_instrument_slug()
        if slug is not None:
            return slug
    return None


class _FeeVerifiedHolder:
    """EDGE-1 (AM-4): a single, late-bound mutable slot over
    ``FeeDriftProbeActor.is_fee_verified``.

    ``app/trade.py`` composes the strategy (which needs the read-side
    callable AT CONSTRUCTION) BEFORE it constructs ``FeeDriftProbeActor``
    (the existing ``~532``/``~552`` ordering) -- so the callable the
    strategy holds must be indirection over a slot filled in later, never
    the actor object itself passed too early.

    Starts unbound: :meth:`is_fee_verified` then reads as UNVERIFIED
    (``False``) for any ``now_ns``, regardless of the value -- this is the
    correct behaviour both before ``bind`` runs and permanently, when
    :func:`_build_fee_drift_probe` returns ``None`` (no instrument resolved
    for any composed station, AM-3): nothing is tradable in that case
    either way, so a permanent veto is safe and intended, never a bug.
    """

    def __init__(self) -> None:
        self._check: Callable[[int], bool] | None = None

    def bind(self, check: Callable[[int], bool]) -> None:
        self._check = check

    def is_fee_verified(self, now_ns: int) -> bool:
        return self._check is not None and self._check(now_ns)


def _build_fee_drift_probe(
    *,
    strategies: Sequence[Strategy],
    family_halt_latch: TrialDayLatch,
    registered_fee_coefficient: Decimal,
    slug_fn: Callable[[], str | None] | None = None,
) -> tuple[FeeDriftProbeActor, Callable[[Any], None]] | None:
    """Build AUD-12b's fee-drift probe for ``continuous_rung_hold`` only.

    ``slug_fn`` (FQ-S6, finding F6): an optional LAZY slug resolver, called
    on every fetch rather than once at build time. ``forecast_quantile_ladder``
    passes a closure over its composed strategies' own LIVE ``rung_instruments``
    (``ForecastQuantileLadderStrategy.current_yes_instrument_slug``) because a
    D+1 readiness-poll subscription can resolve AFTER this probe is built --
    an eager, once-only slug (the ``continuous_rung_hold`` default below)
    would never see it. When ``slug_fn`` is omitted (every pre-S6 caller,
    i.e. ``continuous_rung_hold``), behaviour is BYTE-IDENTICAL to before:
    the slug is resolved once, here, from ``strategies``, and ``None``
    permanently disables the probe (returns ``None``, logged).

    Returns ``None`` (no probe registered) when no composed strategy
    resolved any tradable instrument AND no ``slug_fn`` was given -- logged,
    never a crashed boot. A caller that passes ``slug_fn`` always gets a
    probe back (it may simply read UNKNOWN until a slug resolves).

    ``registered_fee_coefficient`` is the SENDING family's own
    ``FamilyManifest.taker_fee_coefficient`` (the caller's already-loaded
    ``manifest``, read once, above) -- the EXACT source the composed
    strategies' own ``required_fee_coefficient`` already comes from (see the
    ``continuous_rung_hold`` branch above) and the same one
    ``current_rung_hold/decision.py:342``'s per-order check compares against.
    Passed straight through to :class:`FeeDriftProbeActor` as
    ``documented_fee_coefficient`` -- fee-drift-probe-target ruling,
    2026-09-25: comparing the wire read against the module-level
    ``DOCUMENTED_TAKER_FEE_COEFFICIENT`` instead of the running family's own
    registered theta made the probe DISAGREE forever for any family (e.g.
    ``pm_us_crh_v4``) registered at a different, committed value.

    Every collaborator is the SAME object another already-wired seam uses:

    * ``set_family_halted`` calls ``family_halt_latch.record_policy_halt`` --
      the EXACT ``TrialDayLatch`` handle this branch already opened for
      ``family_halt_submit_veto``'s READ side (``open_trial_day_latch(latch,
      key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)``), never a second open. It can
      only SET the halt (``record_policy_halt``'s own idempotent, additive
      write -- see its docstring); nothing here can clear one.
    * ``wire_fee_fetcher`` reads a ``PolymarketUSHttpClient`` resolved lazily,
      post-``build()``, via the returned ``resolve_client`` callback (bound
      into ``after_build`` by the caller) -- ``shared_polymarket_us_http_client``
      (``factories.py:516``) on the SAME ``PolymarketUSDataClientConfig`` and
      the SAME ``node.kernel.clock`` the live data client itself was built
      with (``live/node_builder.py:184``, ``clock=self._clock``), so this
      reuses the ONE cached transport/rate-limiter rather than opening a
      second one. Before ``resolve_client`` has run (or if no data client is
      found), the fetcher raises :class:`WireFeeCoefficientError` --
      ``probe_once()`` already turns that into a plain ``"UNKNOWN"`` alert,
      never a boot-time crash and never a halt. Resolution is RETRIED on
      every fetch until it first succeeds (never cached as a permanent
      failure): a data client that connects moments after ``build()``
      (reconnect, slow handshake) must not leave the probe UNKNOWN for the
      rest of the process's life.
    """
    resolve_slug: Callable[[], str | None]
    if slug_fn is not None:
        resolve_slug = slug_fn
    else:
        slug = _representative_fee_drift_slug(strategies)
        if slug is None:
            _boot_logger.warning(
                "fee_drift_probe: no instrument resolved for any composed station; "
                "probe not registered"
            )
            return None
        resolve_slug = lambda: slug  # pin the eagerly-resolved slug

    node_holder: dict[str, Any] = {}
    client_holder: dict[str, PolymarketUSHttpClient] = {}

    def _try_resolve_client() -> PolymarketUSHttpClient | None:
        """Best-effort resolve against whatever `node` the last `after_build`
        call handed us. Read-only; never raises -- a missing/renamed
        attribute fails closed to `None` (caller turns that into UNKNOWN),
        never a boot-time or probe-time crash.

        Reaches into `data_engine._clients` -- the SAME private-attribute
        idiom already established at `trade_cli.py`'s own
        `_exec_client_refusal_reader`/`_exec_client_stale_intent_reader`
        (`trade_cli.py:383,406`), guarded here the same way: `getattr` at
        every hop, never a bare attribute chain, so a future Nautilus rename
        degrades to UNKNOWN instead of an unhandled `AttributeError`.
        """
        node = node_holder.get("node")
        if node is None:
            return None
        data_engine = getattr(node.kernel, "data_engine", None)
        clients = getattr(data_engine, "_clients", None)
        client = None if clients is None else clients.get(ClientId(POLYMARKET_US_CLIENT_NAME))
        venue_config = getattr(client, "_venue_config", None)
        if venue_config is None:
            return None
        resolved = shared_polymarket_us_http_client(venue_config, node.kernel.clock)
        client_holder["client"] = resolved
        return resolved

    async def _wire_fee_fetcher() -> Decimal:
        slug = resolve_slug()
        if slug is None:
            raise WireFeeCoefficientError(
                "fee_drift_probe: no instrument resolved for any composed station yet"
            )
        client = client_holder.get("client")
        if client is None:
            client = _try_resolve_client()
        if client is None:
            raise WireFeeCoefficientError(
                "fee_drift_probe: no live read-only http client resolved yet"
            )
        return await fetch_wire_fee_coefficient(client, slug, quota_key=QUOTA_KEY_DISCOVERY)

    def _set_family_halted(wire_fee: Decimal) -> None:
        evidence_sha256 = hashlib.sha256(
            f"fee_drift_probe:slug={resolve_slug()}:wire={wire_fee}".encode()
        ).hexdigest()
        family_halt_latch.record_policy_halt(
            reason=_FEE_DRIFT_HALT_REASON,
            evidence_sha256=evidence_sha256,
            ts_ns=time.time_ns(),
        )

    actor = FeeDriftProbeActor(
        wire_fee_fetcher=_wire_fee_fetcher,
        set_family_halted=_set_family_halted,
        alert_sink=resolve_alert_sink(),
        documented_fee_coefficient=registered_fee_coefficient,
    )

    def _resolve_client(node: Any) -> None:
        node_holder["node"] = node
        if _try_resolve_client() is None:
            _boot_logger.warning(
                "fee_drift_probe: no live data client found post-build; "
                "probe stays UNKNOWN until one resolves"
            )

    return actor, _resolve_client


@dataclass(frozen=True)
class _FamilyComposition:
    """What one ``composition_kind`` builder hands back to ``run``.

    FQ and OMS NETTING: no ``external_order_claims`` is carried here or
    anywhere in the builders (C12) -- FQ fills reconcile under EXTERNAL at
    the next boot.
    """

    strategies: list[Strategy]
    submit_veto: Callable[[], str | None] | None = None
    exit_manifest: FamilyManifest | None = None
    fee_drift_actor: FeeDriftProbeActor | None = None
    fee_drift_resolve_client: Callable[[Any], None] | None = None
    extra_actors: tuple[Any, ...] = ()


def _open_halt_latch_preamble(
    latch: SubmitIntentLatch,
    *,
    family_id: str,
    key_prefix: str,
    alert_on_unattributable_legacy: bool,
) -> tuple[TrialDayLatch, Callable[[], str | None]]:
    """The shared halt-latch preamble: bind a ``TrialDayLatch`` over the SAME
    store/flock ``latch`` already holds (never a second open), log the
    ``family_halt_state`` line, optionally alert on an unattributable legacy
    halt, and return the latch with its ``family_halt_submit_veto``.

    ``key_prefix`` is the family's own durable namespace. Only the
    continuous family alerts on ``legacy == "halts_all"``; the FQ family
    never has, and that is preserved (``alert_on_unattributable_legacy``).
    """
    halt_latch = open_trial_day_latch(latch, key_prefix=key_prefix, family_id=family_id)
    halt_state = halt_latch.family_halt_state()
    _boot_logger.info(
        "family_halt_state family_id=%s halted=%s source=%s legacy=%s",
        family_id,
        halt_state.halted,
        halt_state.source,
        halt_state.legacy,
    )
    if alert_on_unattributable_legacy and halt_state.legacy == "halts_all":
        emit_alert(
            resolve_alert_sink(),
            AlertPayload(
                severity="CRITICAL",
                event="LEGACY_FAMILY_HALT_UNATTRIBUTABLE",
                site="breezy-trade",
                detail=(
                    f"family_id={family_id} source={halt_state.source} legacy={halt_state.legacy}"
                ),
            ),
        )
    return halt_latch, family_halt_submit_veto(halt_latch)


def _compose_current_rung_hold(
    *,
    manifest: FamilyManifest,
    catalog_root: Path,
    today_by_station: dict[str, dt.date],
    latch: SubmitIntentLatch,
    sending_permit: OrderSubmissionPermit | None,
) -> _FamilyComposition:
    """Boot-time composition for ``current_rung_hold`` (moved verbatim from ``run``)."""
    strategies: list[Strategy] = []
    factory = make_trial_day_latch_factory(latch, family_id=manifest.family_id)
    strategies.extend(
        build_current_rung_hold_strategies(
            catalog_root=catalog_root,
            today_by_station=today_by_station,
            trial_day_latch_factory=factory,
            order_submission_permit=sending_permit,
            # The family's REGISTERED cost basis, read off the
            # manifest `run` loaded -- never an environment
            # variable and never a constant here. A different
            # theta is a different estimand, so it can only
            # arrive as a different, committed, sha-changed,
            # REGISTERED family.
            required_fee_coefficient=manifest.taker_fee_coefficient,
        )
    )
    return _FamilyComposition(strategies=strategies)


def _compose_continuous_rung_hold(
    *,
    manifest: FamilyManifest,
    catalog_root: Path,
    today_by_station: dict[str, dt.date],
    latch: SubmitIntentLatch,
    sending_permit: OrderSubmissionPermit | None,
) -> _FamilyComposition:
    """Boot-time composition for ``continuous_rung_hold`` (moved from ``run``)."""
    strategies: list[Strategy] = []
    fee_drift_actor: FeeDriftProbeActor | None = None
    fee_drift_resolve_client: Callable[[Any], None] | None = None
    cont_factory = make_trial_day_latch_factory(
        latch,
        key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
        family_id=manifest.family_id,
    )
    # Item 4 (slice 4 review): the exec client's `_submit_order`
    # consults an injected `submit_veto: Callable[[], str |
    # None]` kwarg (`adapters/polymarket_us/exec/client.py`),
    # evaluated synchronously immediately before the permit
    # spend. `family_halt_submit_veto` wraps a `TrialDayLatch`
    # bound to the SAME shared store/flock `cont_factory` above
    # binds (`open_trial_day_latch` is a plain constructor over
    # `latch.shared_state_binding()`, never a second open), so
    # every veto call is a synchronous, read-only
    # `is_family_halted()` under the intent latch this process
    # already holds for its lifetime -- no fresh open, no await.
    family_halt_latch, submit_veto = _open_halt_latch_preamble(
        latch,
        family_id=manifest.family_id,
        key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
        alert_on_unattributable_legacy=True,
    )
    # Review finding A(1)/A(2): the sending family's own
    # manifest (loaded once, in `run`), threaded into BOTH the
    # position monitor (which evaluates an exit and refuses
    # with `family_not_exit_registered` when the manifest
    # declares no `exit_rule`) and the exec client (which
    # denies with the same manifest-gate reason if anything
    # ever reached it). One load, one object, passed to both --
    # never two independent reads of the same file.
    exit_manifest = manifest
    # EDGE-1 (AM-4): created BEFORE strategy composition -- the
    # composed strategies need the read-side callable at
    # construction, but the probe (whose `is_fee_verified` the
    # holder will forward to) is not built until after them, a
    # few lines below. Binding happens once the probe exists.
    fee_verified_holder = _FeeVerifiedHolder()
    strategies.extend(
        build_continuous_rung_hold_strategies(
            catalog_root=catalog_root,
            today_by_station=today_by_station,
            trial_day_latch_factory=cont_factory,
            order_submission_permit=sending_permit,
            # phase1_sending_permit routes a non-None permit
            # ONLY when phase0_shadow is False (a
            # function-level guarantee -- see its docstring),
            # so lifting the guard is exactly and only
            # conditioned on that permit being present.
            phase0_permit_guard=sending_permit is None,
            exit_manifest=exit_manifest,
            # See `_compose_current_rung_hold`: the theta every station
            # prices against comes from THIS family's manifest.
            required_fee_coefficient=manifest.taker_fee_coefficient,
            # EDGE-1: the live composition root is the ONE
            # caller that ever passes a non-None check (paper
            # replay's ContinuousRungHoldBacktestStrategy never
            # exposes this parameter at all).
            fee_verified_check=fee_verified_holder.is_fee_verified,
        )
    )
    # AUD-12b: unattended fee-schedule drift probe, this
    # composition_kind only (§9: "runs alongside the existing
    # strategy Actors", never folded into their own on_start).
    built_probe = _build_fee_drift_probe(
        strategies=strategies,
        family_halt_latch=family_halt_latch,
        # The sending family's own registered theta -- see the
        # `_compose_current_rung_hold`'s `required_fee_coefficient` comment;
        # never a constant, never an environment variable.
        registered_fee_coefficient=manifest.taker_fee_coefficient,
    )
    if built_probe is not None:
        fee_drift_actor, fee_drift_resolve_client = built_probe
        # EDGE-1 (AM-4): bound only once the probe exists. When
        # `built_probe` is `None` (AM-3: no instrument resolved
        # for any composed station), the holder stays unbound
        # for the rest of this process's life, which reads as
        # permanently unverified -- safe, since nothing is
        # tradable either way.
        fee_verified_holder.bind(fee_drift_actor.is_fee_verified)
    return _FamilyComposition(
        strategies=strategies,
        submit_veto=submit_veto,
        exit_manifest=exit_manifest,
        fee_drift_actor=fee_drift_actor,
        fee_drift_resolve_client=fee_drift_resolve_client,
    )


def _compose_forecast_quantile_ladder(
    *,
    manifest: FamilyManifest,
    catalog_root: Path,
    today_by_station: dict[str, dt.date],
    latch: SubmitIntentLatch,
    sending_permit: OrderSubmissionPermit | None,
    settings: BreezyTradeSettings,
) -> _FamilyComposition:
    """Boot-time composition for ``forecast_quantile_ladder`` (moved from ``run``)."""
    strategies: list[Strategy] = []
    extra_actors: list[Any] = []
    fee_drift_actor: FeeDriftProbeActor | None = None
    fee_drift_resolve_client: Callable[[Any], None] | None = None
    # SL-13 (plan `FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29
    # .md` §7 row SL-13, hypothesis H-FC-NBP-EV-2026-09): this
    # branch is REACHABLE from a production boot. The manifest
    # naming this composition_kind (`deploy/families/pm_us_crh_fq_v1
    # .json`) is REGISTERED, so `load_family_manifest`
    # accepts it. Orders are still shadow-only unless the FQ-S5
    # two-key live-orders gate below passes. Promoting a future
    # manifest is a manifest + env act, never a source edit --
    # exactly WP-11b's own cardinality-1 promotion contract.
    #
    # Same persistent-latch/halt-veto/permit-guard shape as the
    # `_compose_continuous_rung_hold`, reusing its own
    # `open_trial_day_latch`/`family_halt_submit_veto` machinery
    # unchanged -- only the key_prefix (this family's OWN durable
    # namespace) and the latch ADAPTER (`PersistentQuantileLadderLatch`,
    # matching `ForecastQuantileLadderStrategy`'s plain
    # constructor-value `latch`, never a per-station factory --
    # see `forecast_quantile_ladder.composition`'s docstring)
    # differ.
    forecast_halt_latch, submit_veto = _open_halt_latch_preamble(
        latch,
        family_id=manifest.family_id,
        key_prefix=FORECAST_QUANTILE_TRIAL_KEY_PREFIX,
        alert_on_unattributable_legacy=False,
    )
    exit_manifest = manifest
    registry = default_registry()
    station_icaos = tuple(
        registry.settlement_site(_VENUE, station).icao for station in today_by_station
    )
    nbm_actor = NbmQuantileActor(
        NbmQuantileActorConfig(station_icaos=station_icaos),
    )
    # S6 (finding F6): the same EDGE-1 pattern as the
    # `_compose_continuous_rung_hold` -- the composed
    # strategies need the read-side callable AT CONSTRUCTION, but
    # the probe (whose `is_fee_verified` the holder forwards to)
    # cannot be built until AFTER them, below.
    fq_fee_verified_holder = _FeeVerifiedHolder()
    # FQ-S5 (plan D3): the enable path is a two-key gate. This is
    # the ONE place in the whole fq branch that computes a
    # non-literal `shadow_only` -- see the AST guard in
    # `tests/unit/test_shadow_only_false_is_only_the_gate_output
    # .py`, which permits exactly this expression and nowhere
    # else. The repo root is the process CWD, the same
    # convention `_FAMILIES_DIR` above already assumes (the
    # supervisor always sets `cwd=str(repo_root)` before
    # spawning this process).
    repo_root = Path.cwd()
    try:
        live_orders = live_orders_authorized(
            manifest,
            repo_root,
            permit_present=sending_permit is not None,
        )
    except LiveOrdersGateRefusedError as exc:
        _boot_logger.info(
            "fq_live_orders enabled=False family_id=%s ruling=%s reason=%s ruling_sha256=none",
            manifest.family_id,
            manifest.live_orders_ruling,
            exc.reason,
        )
        raise SettingsError(f"fq live-orders gate refused for {manifest.family_id}: {exc}") from exc
    _boot_logger.info(
        "fq_live_orders enabled=%s family_id=%s ruling=%s reason=%s "
        "ruling_sha256=%s calibration_sha256=%s",
        live_orders.enabled,
        manifest.family_id,
        manifest.live_orders_ruling or "none",
        live_orders.reason,
        live_orders.ruling_sha256 or "none",
        manifest.density_artefact_sha256,
    )
    # F6 FQ-BRIDGE (E-28 carve-out; temporary, retired by hand per plan
    # §R8-2): wrap the halt veto in ONE add-only OR -- family halt first,
    # then the loss stop, then parity -- so the SAME callable reaches both
    # the strategies and the exec client. A veto only: it can refuse, never
    # enable. The import is local so the carve-out stays inside this def.
    from breezy.strategy.forecast_quantile_ladder import loss_stop_probe as fq_bridge

    def _fq_bridge_now() -> dt.datetime:
        return dt.datetime.now(tz=dt.UTC)

    def _fq_bridge_set_halt(reason: str, evidence_sha256: str) -> None:
        forecast_halt_latch.record_policy_halt(
            reason=reason, evidence_sha256=evidence_sha256, ts_ns=time.time_ns()
        )

    fq_loss_stop_probe = fq_bridge.LossStopProbe(
        path=fq_bridge.loss_stop_artefact_path(catalog_root),
        clock=_fq_bridge_now,
        set_family_halted=_fq_bridge_set_halt,
        alert_sink=resolve_alert_sink(),
        alert_every_probe=lambda: (
            live_orders.enabled and not forecast_halt_latch.is_family_halted()
        ),
        expected_uid=os.getuid(),
    )
    fq_loss_stop_probe.probe_once()
    fq_parity_cache = (
        fq_bridge.ParityFileCache(
            catalog_root, clock=_fq_bridge_now, expected_uid=os.getuid()
        )
        if manifest.family_id == fq_bridge.PARITY_SUBJECT
        else None
    )
    fq_parity_gate = (
        None
        if fq_parity_cache is None
        else fq_bridge.make_file_parity_gate(
            family_id=manifest.family_id, clock=_fq_bridge_now, cache=fq_parity_cache
        )
    )
    if fq_parity_cache is not None:
        fq_parity_cache.refresh()
    submit_veto = fq_bridge.FqComposedVeto(
        halt_veto=submit_veto,
        loss_stop_veto=fq_loss_stop_probe.veto_reason,
        parity_veto=None if fq_parity_gate is None else fq_parity_gate.veto_reason,
    )
    extra_actors.append(
        fq_bridge.LossStopProbeActor(
            fq_loss_stop_probe,
            refreshers=() if fq_parity_cache is None else (fq_parity_cache.refresh,),
        )
    )
    # FQ-S11: ONE shared in-process decision-funnel aggregator for
    # this boot, flushed every 15 minutes (plus once at on_stop) to
    # the SAME sibling `decisions/` directory
    # `current_rung_hold.composition._decisions_dir` already uses
    # -- a sibling of the quote-tape catalog root, never nested
    # under it. Built here (never inside `build_forecast_
    # quantile_ladder_strategies`, which returns constructed
    # objects only, same convention as `quantile_actor`) and
    # registered via `extra_actors` below.
    fq_decision_counts = FqDecisionCounts()
    fq_funnel_actor = FqDecisionFunnelActor(
        output_dir=catalog_root.parent / "decisions",
        counts=fq_decision_counts,
    )
    try:
        forecast_strategies, quantile_actor = build_forecast_quantile_ladder_strategies(
            catalog_root=catalog_root,
            today_by_station=today_by_station,
            latch=PersistentQuantileLadderLatch(forecast_halt_latch),
            # A single sha-pinned density artefact serves both the
            # per-version point calibration and the per-version
            # bootstrap-draw bounds -- ONE loader
            # (`calibration_artefact.load_live_calibration`), one
            # manifest pin, `density_artefact_path`/
            # `density_artefact_sha256` (SL-13 S2).
            calibration_artefact_path=str(manifest.density_artefact_path),
            calibration_artefact_sha256=manifest.density_artefact_sha256,
            order_submission_permit=sending_permit,
            phase0_permit_guard=sending_permit is None,
            submit_veto=submit_veto,
            fee_verified=fq_fee_verified_holder.is_fee_verified,
            required_fee_coefficient=float(manifest.taker_fee_coefficient),
            shadow_only=not live_orders.enabled,
            decision_counts=fq_decision_counts,
        )
    except (
        NoTradableForecastInstrumentsError,
        # Review item 1 (SL-13 fix-first; SL-13 S2 item 8): every
        # artefact-load failure mode -- a bad sha pin, malformed
        # JSON, or a schema-missing key/wrong-shaped value in an
        # otherwise-parseable payload (including an unknown or
        # 3-element bootstrap-draw shape) -- must fail this ONE
        # composition_kind closed, the same clean EXIT_CONFIG_ERROR
        # path `NoTradableForecastInstrumentsError` already uses,
        # never an unhandled crash. `load_live_calibration` itself
        # already wraps every malformed-payload condition into
        # `CalibrationArtefactPinMismatchError` -- a missing
        # artefact FILE (`FileNotFoundError`) is already an
        # `OSError`, already in the outer `except` tuple below --
        # not repeated here.
        CalibrationArtefactPinMismatchError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
    ) as exc:
        raise SettingsError(
            f"forecast_quantile_ladder composition failed for "
            f"{settings.sending_family_id}: {type(exc).__name__}: {exc}"
        ) from exc
    strategies.extend(forecast_strategies)
    extra_actors.extend([quantile_actor, nbm_actor, fq_funnel_actor])

    # S6 (finding F6): built AFTER the strategies exist, over a
    # LAZY `slug_fn` -- a D+1 readiness-poll subscription that
    # resolves after `build()` is still picked up on the probe's
    # next fetch (see `_build_fee_drift_probe`'s own docstring).
    def _fq_slug_fn(
        fqs: tuple[ForecastQuantileLadderStrategy, ...] = forecast_strategies,
    ) -> str | None:
        return _fq_representative_slug(fqs)

    fq_built_probe = _build_fee_drift_probe(
        strategies=forecast_strategies,
        family_halt_latch=forecast_halt_latch,
        registered_fee_coefficient=manifest.taker_fee_coefficient,
        slug_fn=_fq_slug_fn,
    )
    if fq_built_probe is not None:
        fee_drift_actor, fee_drift_resolve_client = fq_built_probe
        fq_fee_verified_holder.bind(fee_drift_actor.is_fee_verified)
    return _FamilyComposition(
        strategies=strategies,
        submit_veto=submit_veto,
        exit_manifest=exit_manifest,
        fee_drift_actor=fee_drift_actor,
        fee_drift_resolve_client=fee_drift_resolve_client,
        extra_actors=tuple(extra_actors),
    )


def _compose_family(
    manifest: FamilyManifest,
    *,
    settings: BreezyTradeSettings,
    catalog_root: Path,
    today_by_station: dict[str, dt.date],
    latch: SubmitIntentLatch,
    sending_permit: OrderSubmissionPermit | None,
) -> _FamilyComposition:
    """Dispatch composition by ``composition_kind``; unknown and unimplemented
    kinds refuse the boot with a ``SettingsError`` (clean EXIT_CONFIG_ERROR)."""
    if manifest.composition_kind == "current_rung_hold":
        return _compose_current_rung_hold(
            manifest=manifest,
            catalog_root=catalog_root,
            today_by_station=today_by_station,
            latch=latch,
            sending_permit=sending_permit,
        )
    if manifest.composition_kind == "continuous_rung_hold":
        return _compose_continuous_rung_hold(
            manifest=manifest,
            catalog_root=catalog_root,
            today_by_station=today_by_station,
            latch=latch,
            sending_permit=sending_permit,
        )
    if manifest.composition_kind == "forecast_quantile_ladder":
        return _compose_forecast_quantile_ladder(
            manifest=manifest,
            catalog_root=catalog_root,
            today_by_station=today_by_station,
            latch=latch,
            sending_permit=sending_permit,
            settings=settings,
        )
    if manifest.composition_kind == "forecast_ladder":
        # WP-14 has not landed: the strategy this composition_kind
        # names does not exist yet. Refuse to boot rather than
        # silently compose nothing -- an operator who points
        # sending_family_id at a forecast_ladder manifest today
        # gets a clean, logged configuration error, not a
        # zero-strategy node quietly doing nothing.
        raise SettingsError(
            f"composition_kind=forecast_ladder ({settings.sending_family_id}) "
            "cannot boot yet: ForecastLadderStrategy is not implemented"
        )
    raise SettingsError(
        f"{settings.sending_family_id}: unknown composition_kind {manifest.composition_kind!r}"
    )


def run(
    *,
    env: Mapping[str, str] | None = None,
    node_factory: NodeFactory = TradingNode,
    stderr: TextIO | None = None,
    live_trading_permit: object | None = None,
    order_submission_permit: OrderSubmissionPermit | None = None,
) -> int:
    """Load settings; resolve the ONE sending family (if any) against
    ``deploy/families/``; dispatch composition by its ``composition_kind``;
    run the node.

    WP-11b (active-family registry, cardinality-1): there is no module
    constant naming a family here -- ``settings.sending_family_id`` +
    ``deploy/families/{id}.json`` is the only path from boot to a
    composed strategy, so promoting a revision is a manifest + env act,
    never a source edit.
    """
    out = sys.stderr if stderr is None else stderr
    try:
        settings = load_trade_settings(env)
    except SettingsError as exc:
        _report(out, "configuration error", exc, expected=True)
        return EXIT_CONFIG_ERROR

    if settings.sending_family_id is None:
        # AUD-16b: the explicit sentinel line -- a missing line here would be
        # indistinguishable from an old binary that never carried this field.
        _boot_logger.info(
            "boot_family id=none composition_kind=none status=none manifest_sha256=none"
        )
        return trade_cli.run(
            env=env,
            node_factory=node_factory,
            stderr=out,
            live_trading_permit=live_trading_permit,
            settings=settings,
        )

    try:
        exec_client_config = exec_config_from_env(env)
    except SettingsError as exc:
        _report(out, "configuration error", exc, expected=True)
        return EXIT_CONFIG_ERROR

    store_path = Path(str(exec_client_config.state_store_path))
    catalog_root = settings.catalog_root
    if catalog_root is None:
        _report(
            out,
            "configuration error",
            SettingsError("a sending family is on but catalog_root is unset"),
            expected=True,
        )
        return EXIT_CONFIG_ERROR

    try:
        manifest = load_family_manifest(_FAMILIES_DIR / f"{settings.sending_family_id}.json")
        # AUD-16b: attribute this boot to the family + the manifest bytes it
        # actually loaded (sha256 over the raw on-disk file, computed in
        # load_family_manifest before the dataclass is built). Values only
        # from the loaded manifest and settings.sending_family_id -- never an
        # environ mapping, an operator-reserved cap, or exception text.
        # Observability only: nothing may key on this line, and it changes no
        # decision. KNOWN GAP (not silently assumed -- see AUD-16 return):
        # this line cannot precede the permit lines app/trade.py::main logs
        # before it calls run() (the sole production caller); achieving that
        # would require moving manifest resolution into main(), ahead of
        # permit issuance, which is out of this item's scope.
        _boot_logger.info(
            "boot_family id=%s composition_kind=%s status=%s manifest_sha256=%s",
            settings.sending_family_id,
            manifest.composition_kind,
            manifest.status,
            manifest.manifest_sha256,
        )
        if manifest.family_id != settings.sending_family_id:
            raise SettingsError(
                "sending family id does not match manifest family_id: "
                f"{settings.sending_family_id!r} != {manifest.family_id!r}"
            )
        # Manifest stations, not SUPPORTED_STATIONS. The call has to follow
        # the load: the composable set is a property of this manifest.
        today_by_station = _today_by_station(_composable_stations(manifest))
        with ExitStack() as stack:
            store = stack.enter_context(SqliteStateStore(store_path))
            latch = stack.enter_context(open_submit_intent_latch(store, store_path))
            sending_permit = phase1_sending_permit(
                sending_family_id=settings.sending_family_id,
                permit=order_submission_permit,
                phase0_shadow=settings.phase0_shadow,
            )
            composition = _compose_family(
                manifest,
                settings=settings,
                catalog_root=catalog_root,
                today_by_station=today_by_station,
                latch=latch,
                sending_permit=sending_permit,
            )
            strategies = composition.strategies
            submit_veto = composition.submit_veto
            exit_manifest = composition.exit_manifest
            fee_drift_actor = composition.fee_drift_actor
            fee_drift_resolve_client = composition.fee_drift_resolve_client
            extra_actors = composition.extra_actors

            composed = tuple(strategies)
            _boot_logger.info(
                "composed stations %s from family_id=%s",
                ",".join(strategy.order_id_tag for strategy in composed),
                manifest.family_id,
            )

            def _after_build(node: Any) -> None:
                # SL-13: `install_current_rung_hold_refusal_watch` reads
                # `.refusals`/`.diagnostics`/`.position_events`, attributes
                # only `CurrentRungHoldStrategy`/`ContinuousRungHoldStrategy`
                # carry -- a `forecast_quantile_ladder` boot's `composed`
                # tuple holds `ForecastQuantileLadderStrategy` instances only
                # (composition kinds are mutually exclusive per boot), so
                # calling it unconditionally would crash every such boot.
                if manifest.composition_kind in ("current_rung_hold", "continuous_rung_hold"):
                    install_current_rung_hold_refusal_watch(node, composed)

                # AUD-12b: resolved lazily, post-`build()`, because only
                # then does `node.kernel`'s registered data client (and its
                # `PolymarketUSDataClientConfig`) exist to share a transport
                # with -- see `_build_fee_drift_probe`'s own docstring.
                if fee_drift_resolve_client is not None:
                    fee_drift_resolve_client(node)

            return trade_cli.run(
                env=env,
                node_factory=node_factory,
                stderr=out,
                strategies=composed,
                extra_actors=tuple(extra_actors)
                + (() if fee_drift_actor is None else (fee_drift_actor,)),
                submit_intent_latch=latch,
                after_build=_after_build,
                live_trading_permit=live_trading_permit,
                settings=settings,
                exec_client_config=exec_client_config,
                submit_veto=submit_veto,
                exit_manifest=exit_manifest,
                # WP-B2: the kernel order guard re-checks THIS permit's
                # expiry at every submit. `sending_permit`, not
                # `order_submission_permit`, because it is the object the
                # composed strategies were actually given -- Phase 0 hands
                # them `None`, and the guard must agree with them rather than
                # enforce a permit nobody holds.
                order_submission_permit=sending_permit,
            )
    except (
        SettingsError,
        OSError,
        SubmitIntentLockHeld,
        SubmitIntentLockError,
        # A missing/malformed `deploy/families/<id>.json` is a deployment
        # defect, not a crash: the process should refuse to start cleanly
        # (exit 2) rather than take down a live-trading node on a file it
        # should never be missing. (``runtime.settings.load_trade_settings``
        # already validates this at settings-load time, above; this is
        # defense in depth for the second, real-use load.)
        FamilyManifestError,
        # Defense in depth, not the intended path: `phase0_permit_guard=
        # (sending_permit is None)` above makes this unreachable when
        # `phase1_sending_permit`'s own invariant holds. Kept as a
        # fail-closed net for a future mis-wiring -- e.g. a call site that
        # passes a real permit through `build_continuous_rung_hold_strategies`
        # without also flipping `phase0_permit_guard`, or a change to
        # `phase1_sending_permit` that stops guaranteeing that pairing --
        # so such a bug degrades to a clean, logged configuration error
        # rather than an unhandled crash in a live-trading process.
        Phase0PermitForbiddenError,
    ) as exc:
        _report(out, "configuration error", exc, expected=True)
        return EXIT_CONFIG_ERROR


def main() -> int:
    """Console-script entrypoint. Returns the process exit code.

    B7's ONE caller: this is the composition root the ``breezy-trade``
    console script actually enters (``pyproject.toml [project.scripts]``),
    so the live-trading permit is minted here, on the main thread, exactly
    once, and threaded through to ``trade_cli.run`` -- never re-minted, and
    never issued from ``breezy.runtime.trade_cli.main`` (a library
    entrypoint other callers also reach directly).

    B11's ONE caller: ``OrderSubmissionPermit.issue`` is minted here too,
    immediately beside the live-trading permit, when ``BreezyTradeSettings.
    orders_enabled_requested`` is True. Settings are loaded a second time
    here (``run`` loads its own copy) rather than threaded through, because
    this function must decide whether to mint the order-submission permit
    BEFORE ``run`` builds anything -- both loads read the same ``env`` and
    are pure validation, so they agree. A settings load failure here always
    logs one unmistakable line and sets ``settings = None``; ``run``
    performs the SAME load and reports the real configuration error through
    its existing path, so the error is never duplicated or reported twice.
    If ``BREEZY_ORDERS_ENABLED=1`` was requested, the failure is additionally
    FATAL here (``EXIT_RUNTIME_ERROR``) rather than silently degrading to a
    node that can never submit.

    A refusal from ``OrderSubmissionPermit.issue`` is FATAL, unlike a
    live-trading-permit refusal (which degrades to shadow mode): the
    operator explicitly requested the order path
    (``BREEZY_ORDERS_ENABLED=1``) via ``orders_enabled_requested``, so a
    request that cannot be honoured must stop the process loudly rather
    than silently run in shadow mode with the operator's intent unmet. The
    log line names the refusal class only, never a value (L-22 shape).
    """
    from nautilus_trader.common.component import LiveClock

    from breezy.adapters.polymarket_us.safety import (
        LiveTradingPermissionError,
        issue_live_trading_permit,
    )

    _ensure_boot_logging_visible()

    # AUD-16b (coordinator ruling): the FIRST boot log line, before either
    # permit is minted, so a boot that dies at permit mint still carries its
    # family identity. Deliberately minimal -- the raw declared value only,
    # via the same env var settings.py resolves BREEZY_SENDING_FAMILY_ID
    # from (SENDING_FAMILY_ID_VAR); no manifest load, no sha, no validation
    # side effects, never an operator-reserved variable. The validated
    # boot_family line (family_id + manifest_sha256) still logs from run(),
    # once the manifest is actually loaded.
    _boot_logger.info(
        "boot_family_declared id=%s",
        os.environ.get(SENDING_FAMILY_ID_VAR, "none") or "none",
    )

    permit = None
    try:
        permit = issue_live_trading_permit(
            clock=LiveClock(), max_expires_at_ns=_resolve_permit_expiry_ceiling_ns()
        )
    except LiveTradingPermissionError as exc:
        _boot_logger.info("live-trading permit not issued: %s", exc)
        emit_alert(
            resolve_alert_sink(),
            AlertPayload(
                severity=LIVE_TRADING_PERMIT_REFUSED_SEVERITY,
                event=LIVE_TRADING_PERMIT_REFUSED_EVENT,
                site=LIVE_TRADING_PERMIT_REFUSED_SITE,
                detail=LIVE_TRADING_PERMIT_REFUSED_DETAIL,
            ),
        )

    try:
        settings = load_trade_settings()
    except SettingsError as exc:
        settings = None
        if os.environ.get(ORDERS_ENABLED_VAR) == "1":
            # The operator requested the order path
            # (``BREEZY_ORDERS_ENABLED=1``) but settings could not even be
            # validated -- a request that cannot be honoured must stop the
            # process loudly (same "requested but unminted" contract as the
            # ``OrderSubmissionRefused`` branch below), never run a node
            # that can never submit in silence. Substring matches
            # ``trade_supervisor_core.PERMIT_NOT_ISSUED_MARKER`` on purpose,
            # so the daily-relaunch supervisor classifies this exit-1 the
            # same deterministic way it already classifies a refused permit.
            _boot_logger.error(
                "order submission permit not issued: settings load failed (%s)",
                type(exc).__name__,
            )
            return EXIT_RUNTIME_ERROR
        # Orders were never requested (or the raw request can't be told from
        # here): ``run`` performs the SAME load and reports the real
        # configuration error through its existing path, so this is a
        # breadcrumb, not a duplicate report -- but it must never be silent.
        _boot_logger.info(
            "order submission permit not minted: settings load failed (%s)",
            type(exc).__name__,
        )

    order_submission_permit = None
    if settings is not None and settings.orders_enabled_requested:
        try:
            order_submission_permit = OrderSubmissionPermit.issue(
                settings=settings,
                live_trading_permit=permit,
                clock=LiveClock(),
            )
        except OrderSubmissionRefused as exc:
            _boot_logger.info("order submission permit not issued: %s", type(exc).__name__)
            return EXIT_RUNTIME_ERROR
        else:
            # Both permits are minted at this point: ``issue`` above
            # validated ``permit`` is a genuine, unexpired LiveTradingPermit,
            # so its two non-``repr=False`` fields (``issued_at_ns``,
            # ``expires_at_ns``) are the only values this line ever logs --
            # never ``operator_id`` or any of the five other repr=False
            # fields (security R2).
            ttl_s = (permit.expires_at_ns - permit.issued_at_ns) // 1_000_000_000
            _boot_logger.info(
                "live-trading permit issued issued_at_ns=%d expires_at_ns=%d ttl_s=%d",
                permit.issued_at_ns,
                permit.expires_at_ns,
                ttl_s,
            )
    elif settings is not None:
        # ``orders_enabled_requested`` is False: a legitimate shadow-mode
        # boot, not a failure -- but still a silent skip until now. Uses
        # "not minted" (never "not issued") so it never collides with
        # ``trade_supervisor_core.PERMIT_NOT_ISSUED_MARKER``, which must
        # only match a genuine refusal of an actual request.
        _boot_logger.info("order submission permit not minted: orders not requested")

    return run(
        live_trading_permit=permit,
        order_submission_permit=order_submission_permit,
    )
