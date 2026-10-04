"""AUT-1 WP5 stage 2b, W1: the per-fill legs and the census legs O, F and R6 (plan r12 3.11.2).

Every function is a pure function over one ``AuditInputs`` value (``capture_audit_input_types``):
no I/O, no clock, no randomness. The one lazy read is ``BootEvidence.stream()``, which the host
supplies; a boot's stream is read at most once per call, and only for what leg B and the exit
recompute of leg D need. A host failure inside it propagates (the host maps it to an error cause).

* ``audit_fills``: legs L, D, B, I, E, P and S for every fill of the audited UTC day with
  ``ts_event >= epoch_start_ns``; an earlier fill is ``unattributed`` and runs no leg.
* ``leg_o``: r8's order census, reading ``OrderInitialized``, with the ``TrySubmit`` classification
  (``linked`` / ``refused_after_trysubmit`` / ``never_submitted``, else ``trysubmit_unlinked``).
* ``leg_f``: r8's fill census.
* ``leg_r6``: the resolved fraction of the refusal records' frame references; never fails a day.
* ``tape_marks``: r8's hourly Depth10 best ask for every held base slug (corroboration for leg P).

Choices the plan leaves open, each pinned by a test:

* Leg B's tape comparison reads ``TapeIndex.lookup`` rows in the WP2-R4 frame-body shape (depth:
  ``{ts_event, bids, asks}``; quote: ``{ask, bid, ts_event}``); extra columns are ignored, zero-size
  depth levels are dropped, numbers compare as decimals. An absent tape frame is INFO; a present
  but unequal one is FAIL (WP0-R9).
* "``artefact_sha256`` resolves" is read as a lowercase 64-hex sha256: ``AuditInputs`` carries no
  artefact store to resolve it against.
* ``registry_seq == 0`` once the resolver is live (``AuditInputs.resolver_live``) fails leg D.
* Leg I keys ``fill_by_fingerprint`` on the UTC day of the intent, taken from the link's
  ``ts_ns`` (``record_fill`` derives it from ``intent_created_ns``), never the fill's own day.
* Station lookups in ``std_offsets`` accept the city code (``LAX``) or the ICAO id (``KLAX``).
* The R6 threshold is ``R6_BASELINE`` itself (0.923 is already the WP0-R9 baseline less 1 pp).

Non-writer, no ``breezy.adapters`` import.
"""

import datetime as dt
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Any, Final

from breezy.analysis.capture_audit_fill_support import (
    FAIL,
    HOUR_NS,
    INFO,
    NS,
    PASS,
    PENDING,
    AuditContext,
    build_index,
    climate_day_end_ns,
    fail,
    fill_event,
    in_day,
    info,
    leg_result,
    make_finding,
    offset_of,
    skipped,
    utc_day,
    yes_instrument,
)
from breezy.analysis.capture_audit_input_types import AuditInputs, BootEvidence, ExecFill
from breezy.analysis.capture_audit_model import (
    R6_BASELINE,
    SETTLEMENT_ALERT_H,
    SETTLEMENT_PENDING_H,
    AuditInputError,
    FillAudit,
    Finding,
    Leg,
    LegResult,
    TapeMark,
    is_guard_entry_veto,
)
from breezy.analysis.capture_forecast_ref import ForecastRefStatus, resolve_forecast_ref
from breezy.domain.exec_intent import intent_fingerprint, utc_day_for_ns
from breezy.domain.instrument_leg import (
    leg_of_symbol,
    symbol_of_instrument_id,
)
from breezy.persistence.autonomy.capture_ids import (
    compute_decision_id,
    compute_exit_decision_id,
    parse_forecast_ref,
    parse_frame_ref,
)
from breezy.persistence.autonomy.capture_reader import (
    CaptureStream,
    DecisionView,
    FrameSource,
    JoinStatus,
    OrderLinkView,
    join_fills_to_decisions,
    resolve_frame_ref,
)
from breezy.persistence.autonomy.net_position import LegFill, UnknownSide, net_signed_qty
from breezy.persistence.exit_tags import (
    EXIT_CLIENT_ORDER_ID_TAG_PREFIX,
    EXIT_FAMILY_TAG_PREFIX,
    EXIT_POSITION_TAG_PREFIX,
    EXIT_RULE_TAG_PREFIX,
)

__all__ = ["audit_fills", "leg_f", "leg_o", "leg_r6", "tape_marks"]

#: Pinned equal to ``guarded_strategy.REASON_SUBMITTED`` / ``REASON_INSTRUMENT_VANISHED`` by the
#: tests (that module pulls Nautilus, so it is not imported here).
REASON_SUBMITTED: Final[str] = "submitted"
REASON_INSTRUMENT_VANISHED: Final[str] = "instrument_vanished_after_trysubmit"

_KIND_TAKE: Final[str] = "Take"
_KIND_TRY_SUBMIT: Final[str] = "TrySubmit"
_KIND_EXIT: Final[str] = "Exit"
_KIND_REFUSE: Final[str] = "Refuse"
_REFUSAL_KINDS: Final[frozenset[str]] = frozenset({_KIND_REFUSE, "NotExecutable", "NotDPlus1"})
_SELL: Final[str] = "SELL"
_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}")
_ORDER_DAY_RE: Final[re.Pattern[str]] = re.compile(r"^O-(\d{8})-")
_METRIC_R6_FRACTION: Final[str] = "refusal_frame_ref_resolved_frac"
_FRAME_LEVEL_KEYS: Final[frozenset[str]] = frozenset({"bids", "asks"})

# -- audit_fills -----------------------------------------------------------------------------


def audit_fills(inp: AuditInputs) -> tuple[FillAudit, ...]:
    """Legs L, D, B, I, E, P and S for every audited fill, in fill order.

    Audited: the exec fills stamped on the audited UTC day. A fill before ``epoch_start_ns`` (or
    any fill when there is no epoch) is ``unattributed``: no legs, one cause."""
    fills = tuple(f for f in inp.exec.fills if utc_day(f.ts_event, "fill") == inp.day)
    if not fills:
        return ()
    ctx = AuditContext(inp, build_index(inp), tape_marks)
    epoch_ns = inp.epoch.epoch_start_ns if inp.epoch is not None else None
    attributed = tuple(f for f in fills if epoch_ns is not None and f.ts_event >= epoch_ns)
    joins = {
        id(fill): join
        for fill, join in zip(
            attributed,
            join_fills_to_decisions(ctx.index.view, map(fill_event, attributed)),
            strict=True,
        )
    }
    return tuple(
        _audit_one(ctx, fill, joins[id(fill)]) if id(fill) in joins else _unattributed(inp, fill)
        for fill in fills
    )


def _unattributed(inp: AuditInputs, fill: ExecFill) -> FillAudit:
    return FillAudit(
        fill.client_order_id,
        fill.trade_id or "",
        inp.family_id,
        "live",
        False,
        False,
        (),
        ("unattributed",),
    )


def _audit_one(ctx: AuditContext, fill: ExecFill, join: Any) -> FillAudit:
    link: OrderLinkView | None = join.link
    ident = fill.client_order_id
    leg_l = _leg_l(fill, join.status)
    tagged = link if leg_l.outcome is PASS else None
    unambiguous = None if join.status is JoinStatus.LINK_CONFLICT else link
    leg_e, via_resolver = _leg_e(ctx, fill)
    legs = (
        leg_l,
        _leg_d(ctx, fill, tagged) if tagged else skipped(Leg.D, "no_usable_link", ident),
        _leg_b(ctx, fill, tagged) if tagged else skipped(Leg.B, "no_usable_link", ident),
        _leg_i(ctx, fill, unambiguous) if unambiguous else skipped(Leg.I, "no_usable_link", ident),
        leg_e,
        _leg_p(ctx, fill, via_resolver),
        _leg_s(ctx, fill, link),
    )
    records = _records(ctx, link)
    first = records[0][1] if records else None
    return FillAudit(
        client_order_id=ident,
        trade_id=fill.trade_id or "",
        family_id=first.family_id if first is not None else ctx.inp.family_id,
        source=link.source if link is not None else "live",
        drill=any(d.drill for _, d in records),
        attributed=True,
        legs=legs,
        causes=_causes(legs, via_resolver),
    )


def _causes(legs: Sequence[LegResult], via_resolver: bool) -> tuple[str, ...]:
    ordered: dict[str, None] = {}
    for result in legs:
        for finding in result.findings:
            if finding.outcome is FAIL:
                ordered.setdefault(finding.cause)
    if via_resolver:
        ordered.setdefault("fill_via_resolver")
    return tuple(ordered)


def _records(
    ctx: AuditContext, link: OrderLinkView | None
) -> tuple[tuple[BootEvidence, DecisionView], ...]:
    return ctx.index.decisions.get(link.decision_id, ()) if link is not None else ()


# -- leg L -----------------------------------------------------------------------------------

_L_CAUSES: Final[Mapping[JoinStatus, str]] = {
    JoinStatus.NO_LINK: "no_order_link",
    JoinStatus.LINK_CONFLICT: "link_conflict",
    JoinStatus.UNTAGGED_ORDER: "untagged_order",
}


def _leg_l(fill: ExecFill, status: JoinStatus) -> LegResult:
    cause = _L_CAUSES.get(status)
    findings = [fail(Leg.L, cause, fill.client_order_id)] if cause else []
    return leg_result(Leg.L, findings)


# -- leg D -----------------------------------------------------------------------------------


def _leg_d(ctx: AuditContext, fill: ExecFill, link: OrderLinkView) -> LegResult:
    records = _records(ctx, link)
    is_exit = any(d.kind == _KIND_EXIT for _, d in records) or (
        not records and fill.order_side == _SELL
    )
    findings = (_exit_findings if is_exit else _entry_findings)(ctx, fill, link, records)
    return leg_result(Leg.D, findings)


def _entry_findings(
    ctx: AuditContext,
    fill: ExecFill,
    link: OrderLinkView,
    records: tuple[tuple[BootEvidence, DecisionView], ...],
) -> list[Finding]:
    ident = link.decision_id
    take = next((d for _, d in records if d.kind == _KIND_TAKE), None)
    findings: list[Finding] = []
    if take is None:
        findings.append(fail(Leg.D, "take_missing", ident))
    else:
        if _recomputed_id(take) != take.decision_id:
            findings.append(fail(Leg.D, "decision_id_mismatch", ident))
        if ctx.inp.resolver_live and take.registry_seq == 0:
            findings.append(fail(Leg.D, "registry_seq_zero", ident))
    if not any(d.kind == _KIND_TRY_SUBMIT and d.reason == REASON_SUBMITTED for _, d in records):
        findings.append(fail(Leg.D, "trysubmit_missing", ident))
    return findings


def _recomputed_id(take: DecisionView) -> str:
    return compute_decision_id(
        take.family_id,
        take.manifest_sha256,
        take.artefact_sha256,
        take.station,
        take.climate_day,
        take.rung_id,
        take.side,
        take.eval_ns,
        take.eval_seq,
    )


def _exit_findings(
    ctx: AuditContext,
    fill: ExecFill,
    link: OrderLinkView,
    records: tuple[tuple[BootEvidence, DecisionView], ...],
) -> list[Finding]:
    ident = link.decision_id
    exit_record = next(((b, d) for b, d in records if d.kind == _KIND_EXIT), None)
    if exit_record is None:
        return [fail(Leg.D, "exit_record_missing", ident)]
    findings: list[Finding] = []
    if ctx.inp.resolver_live and exit_record[1].registry_seq == 0:
        findings.append(fail(Leg.D, "registry_seq_zero", ident))
    boot = ctx.index.link_boot.get(link.client_order_id, exit_record[0])
    values = _exit_tag_values(ctx.streams.get(boot), link.client_order_id)
    if values is None:
        findings.append(fail(Leg.D, "exit_id_unrecomputable", ident))
    else:
        recomputed = compute_exit_decision_id(*values)
        if recomputed != link.decision_id or recomputed != exit_record[1].decision_id:
            findings.append(fail(Leg.D, "exit_id_mismatch", ident))
    return findings


def _exit_tag_values(
    stream: CaptureStream, client_order_id: str
) -> tuple[str, str, str, str] | None:
    """The four exit tag values of the order's native ``OrderInitialized`` row, else None."""
    for row in stream.order_initialized:
        if row.get("client_order_id") != client_order_id:
            continue
        try:
            tags = json.loads(row["tags"]) if row.get("tags") else []
        except (TypeError, ValueError):
            return None
        if not isinstance(tags, list):
            return None
        found = [
            next((t.removeprefix(p) for t in tags if isinstance(t, str) and t.startswith(p)), None)
            for p in (
                EXIT_RULE_TAG_PREFIX,
                EXIT_POSITION_TAG_PREFIX,
                EXIT_FAMILY_TAG_PREFIX,
                EXIT_CLIENT_ORDER_ID_TAG_PREFIX,
            )
        ]
        if any(v is None for v in found):
            return None
        rule, position, family, coid = (str(v) for v in found)
        return rule, position, family, coid
    return None


# -- leg B -----------------------------------------------------------------------------------


def _leg_b(ctx: AuditContext, fill: ExecFill, link: OrderLinkView) -> LegResult:
    records = _records(ctx, link)
    ident = link.decision_id
    exit_record = next(((b, d) for b, d in records if d.kind == _KIND_EXIT), None)
    take = next(((b, d) for b, d in records if d.kind == _KIND_TAKE), None)
    anchor = exit_record or take
    if anchor is None:
        return skipped(Leg.B, "no_take_record", ident)
    boot, head = anchor
    findings: list[Finding] = []
    if any(not _SHA256_RE.fullmatch(d.artefact_sha256) for _, d in records):
        findings.append(fail(Leg.B, "artefact_unresolved", ident))
    if exit_record is None:
        if any(not (d.depth_ref or d.quote_ref) for _, d in records):
            findings.append(fail(Leg.B, "frame_kind_missing", ident))
        findings.extend(_frame_findings(ctx, boot, head))
        findings.extend(_forecast_findings(ctx, boot, head))
    elif not any(c.decision_id == ident for c in ctx.streams.get(boot).frame_copies):
        findings.append(fail(Leg.B, "frame_copy_missing", ident))
    return leg_result(Leg.B, findings)


def _frame_findings(ctx: AuditContext, boot: BootEvidence, take: DecisionView) -> list[Finding]:
    ref = take.depth_ref or take.quote_ref
    ident = take.decision_id
    if not ref:
        return []  # reported as ``frame_kind_missing``
    resolved = resolve_frame_ref(ctx.streams.get(boot), ident, ref)
    if resolved.source is not FrameSource.COPY:
        return [fail(Leg.B, "frame_copy_missing", ident)]
    parsed = parse_frame_ref(ref)
    row = ctx.inp.tape.lookup(*parsed) if parsed is not None else None
    if row is None:
        return [info(Leg.B, "tape_frame_absent", ident, ref)]
    if not _frames_equal(resolved.body, row):
        return [fail(Leg.B, "frame_copy_mismatch", ident, ref)]
    return []


def _forecast_findings(ctx: AuditContext, boot: BootEvidence, take: DecisionView) -> list[Finding]:
    ident = take.decision_id
    parsed = parse_forecast_ref(take.forecast_input_ref)
    if parsed is None:
        return [fail(Leg.B, "forecast_ref_missing", ident)]
    station, cycle_ns, available_at_ns = parsed
    offset = offset_of(ctx.inp, station)
    if offset is None:
        return [fail(Leg.B, "std_offset_unknown", ident, station)]
    resolution = resolve_forecast_ref(
        ctx.streams.get(boot), station, cycle_ns, available_at_ns, std_utc_offset_hours=offset
    )
    if resolution.status is not ForecastRefStatus.RESOLVED:
        return [fail(Leg.B, "forecast_ref_unresolved", ident, resolution.reason)]
    return []


def _same_number(a: Any, b: Any) -> bool:
    try:
        return Decimal(str(a)) == Decimal(str(b))
    except InvalidOperation:
        return str(a) == str(b)


def _levels(levels: Any) -> tuple[tuple[Decimal, Decimal], ...] | None:
    """Positive-size ``(price, size)`` levels as decimals, or None when not a level list."""
    try:
        pairs = tuple((Decimal(str(p)), Decimal(str(s))) for p, s in levels)
    except (TypeError, ValueError, InvalidOperation):
        return None
    return tuple(pair for pair in pairs if pair[1] > 0)


def _frames_equal(copy_body: Mapping[str, Any] | None, row: Mapping[str, Any]) -> bool:
    """Every key of the copy's body equals the tape row's value (extra row columns are ignored)."""
    if not isinstance(copy_body, Mapping) or not copy_body:
        return False
    for key, want in copy_body.items():
        if key not in row:
            return False
        got = row[key]
        if key in _FRAME_LEVEL_KEYS:
            want_levels = _levels(want)
            if want_levels is None or want_levels != _levels(got):
                return False
        elif not _same_number(got, want):
            return False
    return True


# -- leg I -----------------------------------------------------------------------------------


def _leg_i(ctx: AuditContext, fill: ExecFill, link: OrderLinkView) -> LegResult:
    """``intent_fingerprint`` recomputed from the projected link, under the intent's UTC day."""
    ident = fill.client_order_id
    fingerprint = intent_fingerprint(
        SimpleNamespace(
            instrument_id=link.instrument_id,
            side=link.side,
            quantity=link.qty,
            price=link.px,
            time_in_force=link.time_in_force,
            client_order_id=link.client_order_id,
        )
    )
    try:
        day = utc_day_for_ns(link.ts_ns).isoformat()
    except ValueError:
        return leg_result(
            Leg.I, [fail(Leg.I, "intent_link_mismatch", ident, "intent day unusable")]
        )
    indexed = ctx.inp.exec.fill_by_fingerprint.get(f"{day}:{fingerprint}")
    named = {
        f.venue_order_id_sha256
        for f in ctx.inp.exec.fills
        if f.client_order_id == link.client_order_id
    }
    if indexed is None or (named and indexed not in named):
        return leg_result(Leg.I, [fail(Leg.I, "intent_link_mismatch", ident)])
    return leg_result(Leg.I, [])


# -- legs E and P ----------------------------------------------------------------------------


def _leg_e(ctx: AuditContext, fill: ExecFill) -> tuple[LegResult, bool]:
    """A native filled event with the same trade id, or a resolver context naming the order.

    The second value is True when only the resolver path proves the fill (``fill_via_resolver``)."""
    node = bool(fill.trade_id) and fill.trade_id in ctx.index.filled_trades
    resolver = any(r.client_order_id == fill.client_order_id for r in ctx.inp.exec.resolvers)
    if node or resolver:
        return leg_result(Leg.E, []), not node
    return leg_result(Leg.E, [fail(Leg.E, "no_filled_event", fill.client_order_id)]), False


def _leg_p(ctx: AuditContext, fill: ExecFill, via_resolver: bool) -> LegResult:
    """A node position mark at or after the fill, a tape mark, or ``fill_via_resolver``."""
    if via_resolver:
        return leg_result(Leg.P, [])
    if any(ts >= fill.ts_event for ts in ctx.index.mark_ts.get(fill.instrument_id, ())):
        return leg_result(Leg.P, [])
    day_start = int(dt.datetime.combine(ctx.inp.day, dt.time(0), tzinfo=dt.UTC).timestamp()) * NS
    yes = yes_instrument(fill.instrument_id)
    if any(
        m.instrument_id == yes
        and m.best_ask is not None
        and day_start + m.hour * HOUR_NS >= fill.ts_event
        for m in ctx.tape_marks()
    ):
        return leg_result(Leg.P, [])
    return leg_result(Leg.P, [fail(Leg.P, "no_position_mark", fill.client_order_id)])


# -- leg S -----------------------------------------------------------------------------------


def _leg_s(ctx: AuditContext, fill: ExecFill, link: OrderLinkView | None) -> LegResult:
    records = _records(ctx, link)
    if not records:
        return skipped(Leg.S, "no_decision_record", fill.client_order_id)
    record = next((d for _, d in records if d.kind == _KIND_TAKE), records[0][1])
    subject = f"{record.station}:{record.climate_day}"
    if any(
        s.station == record.station and s.climate_day == record.climate_day
        for s in ctx.inp.settlements
    ):
        return leg_result(Leg.S, [])
    try:
        day = dt.date.fromisoformat(record.climate_day)
    except ValueError:
        return leg_result(Leg.S, [fail(Leg.S, "climate_day_invalid", subject)])
    offset = offset_of(ctx.inp, record.station)
    if offset is None:
        return leg_result(Leg.S, [fail(Leg.S, "std_offset_unknown", subject)])
    age_ns = ctx.inp.now_ns - climate_day_end_ns(day, offset)
    if age_ns < SETTLEMENT_PENDING_H * HOUR_NS:
        return leg_result(Leg.S, [make_finding(Leg.S, PENDING, "settlement_pending", subject)])
    findings = [fail(Leg.S, "settlement_missing", subject, f"ended_h_ago={age_ns // HOUR_NS}")]
    if age_ns >= SETTLEMENT_ALERT_H * HOUR_NS:
        findings.append(fail(Leg.S, "settlement_missing_alert_due", subject))
    return leg_result(Leg.S, findings)


# -- leg O -----------------------------------------------------------------------------------


def _order_dated_on(client_order_id: str, day: dt.date) -> bool:
    """A D-dated client order id; an id that carries no date is checked, never skipped."""
    match = _ORDER_DAY_RE.match(client_order_id)
    return match is None or match.group(1) == f"{day:%Y%m%d}"


def _log_order_ids(inp: AuditInputs) -> list[str]:
    return [
        line.client_order_id
        for boot in inp.boots
        for line in (*boot.markers.order_submitted, *boot.markers.order_denied)
        if hasattr(line, "client_order_id")
    ]


def leg_o(inp: AuditInputs) -> LegResult:
    """r8's order census, reading ``OrderInitialized``; classifies each ``TrySubmit(submitted)``."""
    streamed = {link.client_order_id for b in inp.boots for link in b.c1.order_links}
    findings = _census_findings(inp, streamed)
    linked_by_decision: dict[str, set[str]] = defaultdict(set)
    for boot in inp.boots:
        for link in boot.c1.order_links:
            linked_by_decision[link.decision_id].add(link.client_order_id)
    evidence = (
        {o.client_order_id for o in inp.exec.orders}
        | {r.client_order_id for r in inp.exec.resolvers}
        | {f.client_order_id for f in inp.exec.fills}
        | {e.client_order_id for b in inp.boots for e in b.c1.lifecycle_events}
        | set(_log_order_ids(inp))
    )
    refused = {
        d.decision_id
        for b in inp.boots
        for d in b.c1.decisions
        if is_guard_entry_veto(d.kind, d.reason)
        or (d.kind == _KIND_REFUSE and d.reason == REASON_INSTRUMENT_VANISHED)
    }
    for boot in inp.boots:
        seen: set[str] = set()
        for decision in boot.c1.decisions:
            if decision.kind != _KIND_TRY_SUBMIT or decision.reason != REASON_SUBMITTED:
                continue
            if decision.decision_id in seen:
                continue
            seen.add(decision.decision_id)
            finding = _classify_trysubmit(
                decision.decision_id, boot.ended, linked_by_decision, evidence, refused
            )
            if finding is not None:
                findings.append(finding)
    return leg_result(Leg.O, findings)


def _census_findings(inp: AuditInputs, streamed: set[str]) -> list[Finding]:
    findings = [
        fail(Leg.O, "order_without_order_link", o.client_order_id)
        for o in inp.exec.orders
        if _order_dated_on(o.client_order_id, inp.day) and o.client_order_id not in streamed
    ]
    findings.extend(
        fail(Leg.O, "resolver_without_order_link", r.client_order_id)
        for r in inp.exec.resolvers
        if in_day(r.created_ns, inp.day) and r.client_order_id not in streamed
    )
    findings.extend(
        fail(Leg.O, "log_order_without_order_link", coid)
        for coid in _log_order_ids(inp)
        if coid not in streamed
    )
    return findings


def _classify_trysubmit(
    decision_id: str,
    boot_ended: bool,
    linked_by_decision: Mapping[str, set[str]],
    evidence: set[str],
    refused: set[str],
) -> Finding | None:
    """``linked`` and ``refused_after_trysubmit`` are clean (no finding); ``never_submitted`` is
    INFO; anything else is ``trysubmit_unlinked`` (FAIL once the boot ended, ``order_pending``
    before)."""
    linked = linked_by_decision.get(decision_id)
    if linked:
        if boot_ended and not (linked & evidence):
            return info(Leg.O, "never_submitted", decision_id)
        return None
    if decision_id in refused:
        return None
    if boot_ended:
        return fail(Leg.O, "trysubmit_unlinked", decision_id)
    return make_finding(Leg.O, PENDING, "order_pending", decision_id)


# -- leg F -----------------------------------------------------------------------------------


def leg_f(inp: AuditInputs) -> LegResult:
    """r8's fill census: the day index equals the fill scan, node-log fills are exec fills, and an
    exec fill the node log never saw has a resolver context."""
    day = inp.day
    day_fills = {f.venue_order_id_sha256: f for f in inp.exec.fills if in_day(f.ts_event, day)}
    by_sha = {f.venue_order_id_sha256: f for f in inp.exec.fills}
    indexed = {
        sha
        for sha in inp.exec.fill_by_day.get(day.isoformat(), ())
        if sha not in by_sha or sha in day_fills
    }
    findings = [
        fail(Leg.F, "fill_by_day_mismatch", sha, "in_index" if sha in indexed else "in_scan")
        for sha in sorted(indexed ^ set(day_fills))
    ]
    scanned = [b.scan for b in inp.boots if b.scan is not None]
    if scanned:
        findings.extend(_node_fill_findings(inp, scanned, day_fills))
    return leg_result(Leg.F, findings)


def _node_fill_findings(
    inp: AuditInputs, scans: Iterable[Any], day_fills: Mapping[str, ExecFill]
) -> list[Finding]:
    exec_coids = {f.client_order_id for f in inp.exec.fills}
    node_coids: set[str] = set()
    truncated = False
    findings: list[Finding] = []
    for scan in scans:
        truncated = truncated or scan.fill_total > len(scan.fills)
        for node_fill in scan.fills:
            if not in_day(node_fill.ts_event, inp.day):
                continue
            node_coids.add(node_fill.client_order_id)
            if node_fill.client_order_id not in exec_coids:
                findings.append(
                    fail(Leg.F, "node_fill_without_exec_fill", node_fill.client_order_id)
                )
    if truncated:
        return [*findings, info(Leg.F, "node_fills_truncated", inp.family_id)]
    resolver_coids = {r.client_order_id for r in inp.exec.resolvers}
    findings.extend(
        fail(Leg.F, "exec_fill_unexplained", f.client_order_id)
        for f in day_fills.values()
        if f.client_order_id not in node_coids and f.client_order_id not in resolver_coids
    )
    return findings


# -- leg R6 ----------------------------------------------------------------------------------


def leg_r6(inp: AuditInputs) -> LegResult:
    """Reference resolution: the resolved fraction of on-change refusal frame references.

    A refusal is a ``Refuse`` / ``NotExecutable`` / ``NotDPlus1`` record (a Take's follow-ups share
    the Take's frame copy). A reference resolves when the tape holds its frame. Below
    ``R6_BASELINE`` the leg is INFO with a finding the audit raises as CRITICAL
    ``CAPTURE_REFUSAL_REFS_UNRESOLVED``; it never fails the day (refusals do not enter a fill's
    join)."""
    total = resolved = 0
    for boot in inp.boots:
        for decision in boot.c1.decisions:
            if decision.kind not in _REFUSAL_KINDS:
                continue
            total += 1
            parsed = parse_frame_ref(decision.depth_ref or decision.quote_ref)
            if parsed is not None and inp.tape.lookup(*parsed) is not None:
                resolved += 1
    if total == 0:
        return leg_result(Leg.R6, [])
    fraction = resolved / total
    if fraction < R6_BASELINE:
        finding = info(
            Leg.R6, "refusal_refs_unresolved", inp.family_id, f"resolved={resolved}/{total}"
        )
        return LegResult(Leg.R6, INFO, (finding,), {_METRIC_R6_FRACTION: fraction})
    return leg_result(Leg.R6, [], **{_METRIC_R6_FRACTION: fraction})


# -- tape marks ------------------------------------------------------------------------------


def _signed_fill(fill: ExecFill) -> LegFill:
    try:
        return LegFill(
            leg=leg_of_symbol(symbol_of_instrument_id(fill.instrument_id)),
            side=fill.order_side,  # type: ignore[arg-type]
            qty=Decimal(fill.cumulative_qty),
            ts_event_ns=fill.ts_event,
        )
    except InvalidOperation as exc:
        raise AuditInputError("exec_record_undecodable", "fill quantity unusable") from exc


def tape_marks(inp: AuditInputs) -> tuple[TapeMark, ...]:
    """The catalog Depth10 best ask at each whole UTC hour of D for every held base slug.

    Held means a non-zero leg-signed net position (a NO holding is a short YES) as of that hour,
    from the exec fills stamped at or before it. Marks are keyed on the YES-leg instrument."""
    day_start = int(dt.datetime.combine(inp.day, dt.time(0), tzinfo=dt.UTC).timestamp()) * NS
    by_slug: dict[str, list[LegFill]] = defaultdict(list)
    for fill in sorted(inp.exec.fills, key=lambda f: f.ts_event):
        by_slug[yes_instrument(fill.instrument_id)].append(_signed_fill(fill))
    marks: list[TapeMark] = []
    for instrument in sorted(by_slug):
        for hour in range(24):
            hour_ns = day_start + hour * HOUR_NS
            try:
                net = net_signed_qty(f for f in by_slug[instrument] if f.ts_event_ns <= hour_ns)
            except UnknownSide as exc:
                raise AuditInputError("exec_record_undecodable", "fill side unusable") from exc
            if net != 0:
                ask = inp.tape.best_ask_at(instrument, hour_ns)
                marks.append(TapeMark(instrument, hour, ask, int(net.to_integral_value())))
    return tuple(marks)
