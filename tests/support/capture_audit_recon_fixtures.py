"""Fixtures of the reconciliation legs (AUT-1 WP5 stage 2b, W2; design S2-R15: own fixtures file).

Three kinds of builder:

* **Log renderers** that emit REAL ``SHADOW_DECISION`` lines. A decision line is built by the real
  ``ForecastQuantileLadderStrategy._shadow_log_line`` and printed as the strategy prints it
  (``f"SHADOW_DECISION {line!r}"``, inside Nautilus's ANSI-wrapped log format); the ``TrySubmit``
  line has the dict shape of ``_emit_decision_outcome``.
* ``analyse``: writes lines to a real file and runs the real ``scan_node_log`` with the W2 sinks.
* ``run_scenario``: the ORACLE. It drives the real ``FqCaptureAdapter`` (with its real on-change
  filter) and the real ``EvalSeqCounter`` on a generated decision sequence, and returns the log
  lines the node would have written next to the records the adapter published.
"""

import datetime as dt
import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, cast

from breezy.analysis.capture_audit_input_types import (
    AuditInputs,
    BootEvidence,
    FunnelCount,
    FunnelRow,
    LogMarkers,
)
from breezy.analysis.capture_audit_log_markers import MarkerParser
from breezy.analysis.capture_audit_model import LegOutcome, LegResult
from breezy.analysis.capture_audit_replay import BootReplay
from breezy.analysis.capture_node_log import NodeLogScan, scan_node_log
from breezy.persistence.autonomy.capture_ids import EvalSeqCounter
from breezy.persistence.autonomy.capture_publish import CapturePublisher
from breezy.persistence.autonomy.capture_reader import C1View, DecisionView, _decision_view
from breezy.persistence.autonomy.capture_records import DecisionRecord
from breezy.persistence.autonomy.veto import VetoReason
from breezy.strategy.autonomy_capture.guarded_strategy import FollowUp, decision_follow_up
from breezy.strategy.forecast_quantile_ladder.capture_adapter import (
    CaptureContext,
    FqCaptureAdapter,
)
from breezy.strategy.forecast_quantile_ladder.decision import (
    NotDPlus1,
    NotExecutable,
    Refuse,
    Take,
)
from breezy.strategy.forecast_quantile_ladder.strategy import ForecastQuantileLadderStrategy
from tests.support.capture_audit_fixtures import (
    DAY,
    FAMILY_ID,
    INSTANCE_ID,
    NS,
    make_boot,
    make_inputs,
)
from tests.support.capture_guard_fakes import RecordingStream, build_depth, build_quote, identity
from tests.support.capture_node_log_fixtures import ANSI_ERROR, ANSI_OFF, ANSI_ON, write_log

__all__ = [
    "COMPONENT",
    "DAY_END_NS",
    "DAY_START_NS",
    "INSTANCE_B",
    "MS",
    "Analysis",
    "Scenario",
    "T",
    "analyse",
    "boot_for",
    "causes",
    "decision_text",
    "dv",
    "failing",
    "funnel_row",
    "inputs_for",
    "instance_line",
    "log_ts",
    "refuse_line",
    "refuse_view",
    "refused_text",
    "run_scenario",
    "take_for",
    "try_submit_text",
    "views_of",
]

DAY_START_NS: Final[int] = (
    int(dt.datetime(DAY.year, DAY.month, DAY.day, tzinfo=dt.UTC).timestamp()) * NS
)
DAY_END_NS: Final[int] = DAY_START_NS + 86_400 * NS
INSTANCE_B: Final[str] = "7b1f0c5e-0000-4000-8000-00000000b00b"
COMPONENT: Final[str] = "BREEZY-L001.FORECAST-QUANTILE-LADDER"
CLIMATE_DAY: Final[dt.date] = DAY + dt.timedelta(days=1)


def log_ts(ns: int) -> str:
    """A node-log timestamp (nine fractional digits, ``Z``)."""
    whole = dt.datetime.fromtimestamp(ns // NS, dt.UTC).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{whole}.{ns % NS:09d}Z"


def _wrap(ns: int, message: str, *, level: str = "INFO", component: str = COMPONENT) -> str:
    return f"{ANSI_ON}{log_ts(ns)}{ANSI_OFF} [{level}] {component}: {message}{ANSI_OFF}"


def instance_line(ns: int, instance_id: str = INSTANCE_ID) -> str:
    return _wrap(ns, f"instance_id: {instance_id}", component="BREEZY-L001.TradingNode")


def decision_text(
    log_ns: int,
    decision: Take | Refuse | NotExecutable | NotDPlus1,
    *,
    now_ns: int,
    station: str = "LAX",
    rung_id: str = "93_94",
    side: str = "yes",
    instrument_id: str = "tc-temp-laxhigh-2026-10-04-gte93lt94f.POLYMARKET_US",
    climate_day: dt.date = CLIMATE_DAY,
) -> str:
    """One evaluation's line, built by the strategy's own ``_shadow_log_line``."""
    line = ForecastQuantileLadderStrategy._shadow_log_line(
        cast(Any, None),
        decision,
        now_ns=now_ns,
        station=station,
        climate_day=climate_day,
        rung_id=rung_id,
        side=cast(Any, side),
        instrument_id=instrument_id,
    )
    return _wrap(log_ns, f"SHADOW_DECISION {line!r}")


def take_for(
    *,
    station: str = "LAX",
    rung_id: str = "93_94",
    side: str = "yes",
    instrument_id: str = "tc-temp-laxhigh-2026-10-04-gte93lt94f.POLYMARKET_US",
    climate_day: dt.date = CLIMATE_DAY,
) -> Take:
    return Take(
        instrument_id=instrument_id,
        station=station,
        climate_day=climate_day,
        side=cast(Any, side),
        rung_id=rung_id,
        qty=1,
        ev_net=0.06568776856525851,
        p_hat=0.2538513678202191,
        p_lower=0.2345490185652585,
        p_upper=0.27614249327505075,
    )


def try_submit_text(
    log_ns: int,
    reason: str,
    *,
    station: str = "LAX",
    rung_id: str = "93_94",
    side: str = "yes",
    instrument_id: str = "tc-temp-laxhigh-2026-10-04-gte93lt94f.POLYMARKET_US",
    climate_day: dt.date = CLIMATE_DAY,
) -> str:
    """The line ``ForecastQuantileLadderStrategy._emit_decision_outcome`` logs (its dict shape);
    its ``now_ns`` is the clock at the time, which is also the line's own timestamp."""
    line = {
        "now_ns": log_ns,
        "station": station,
        "climate_day": climate_day,
        "rung_id": rung_id,
        "side": side,
        "instrument_id": instrument_id,
        "kind": "TrySubmit",
        "reason": reason,
    }
    return _wrap(log_ns, f"SHADOW_DECISION {line!r}")


def refused_text(log_ns: int, reason: str = "capture_gap", ref: str = "0123456789abcdef") -> str:
    """``guarded_strategy._refuse_one``'s ``CAPTURE_REFUSED`` line (ERROR level)."""
    return (
        f"{ANSI_ON}{log_ts(log_ns)}{ANSI_OFF} {ANSI_ERROR}[ERROR] {COMPONENT}: "
        f"CAPTURE_REFUSED reason={reason} order_ref={ref}{ANSI_OFF}"
    )


# -- the real scan --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Analysis:
    scan: NodeLogScan
    replay: Mapping[tuple[str, dt.date], Any]
    markers: Mapping[tuple[str, dt.date], LogMarkers]


def analyse(tmp_path: Path, lines: Sequence[str], *, name: str = "n.log") -> Analysis:
    """Write ``lines`` to a node log and run the real ``scan_node_log`` with both W2 sinks."""
    replay, parser = BootReplay(), MarkerParser()
    scan = scan_node_log(write_log(tmp_path / name, *lines), sinks=(replay, parser))
    return Analysis(scan, replay.results(), parser.markers())


def dv(
    kind: str,
    reason: str,
    *,
    eval_ns: int,
    wall_ns: int | None = None,
    eval_seq: int = 0,
    station: str = "LAX",
    rung_id: str = "93_94",
    side: str = "yes",
    climate_day: dt.date = CLIMATE_DAY,
    instrument_id: str = "tc-temp-laxhigh-2026-10-04-gte93lt94f.POLYMARKET_US",
) -> DecisionView:
    """A C1 decision view with only what the legs read varied."""
    return DecisionView(
        schema="decision/v1",
        decision_id="d" * 32,
        family_id=FAMILY_ID,
        node_boot_id=INSTANCE_ID,
        build_sha="c" * 40,
        registry_seq=7,
        drill=False,
        source="live",
        kind=kind,
        reason=reason,
        eval_ns=eval_ns,
        eval_seq=eval_seq,
        wall_ns=eval_ns if wall_ns is None else wall_ns,
        ts_ns=eval_ns if wall_ns is None else wall_ns,
        station=station,
        climate_day=climate_day.isoformat(),
        rung_id=rung_id,
        side=side,
        instrument_id=instrument_id,
        ask_px="0.15",
        depth_ref="",
        quote_ref="",
        p_hat="",
        p_hat_raw="",
        p_lower="",
        p_upper="",
        ev_net="",
        margin="",
        forecast_input_ref="",
        artefact_sha256="a" * 64,
        manifest_sha256="b" * 64,
    )


def boot_for(
    analysis: Analysis,
    decisions: Iterable[DecisionView] = (),
    *,
    instance_id: str = INSTANCE_ID,
    day: dt.date = DAY,
    detector_events: tuple[Any, ...] = (),
    **over: Any,
) -> BootEvidence:
    """A boot whose scan, replay and markers come from ``analysis`` and whose C1 view holds
    ``decisions``."""
    fields: dict[str, Any] = {
        "instance_id": instance_id,
        "scan": analysis.scan,
        "replay": analysis.replay.get((instance_id, day)) or make_boot().replay,
        "markers": analysis.markers.get((instance_id, day), LogMarkers()),
        "c1": C1View(FAMILY_ID, tuple(decisions), (), (), (), detector_events),
        "last_line_ts_ns": analysis.scan.last_line_ts_ns,
    }
    fields.update(over)
    return make_boot(**fields)


def inputs_for(*boots: BootEvidence, **over: Any) -> AuditInputs:
    return make_inputs(boots=tuple(boots), **over)


# -- the oracle -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    """What the node would have logged and what the real adapter published."""

    lines: list[str]
    records: list[DecisionRecord]
    expected_seqs: list[int]


_REFUSALS: Final[tuple[str, ...]] = ("below_margin", "forecast_unavailable", "already_latched")
_SOFT_VETOES: Final[tuple[str, ...]] = (
    VetoReason.FEED_STALE.value,
    VetoReason.RECORDER_STALE.value,
    VetoReason.PERMIT_LAPSED.value,
    VetoReason.REGISTRY_HALTED.value,
)
_N_INSTRUMENTS: Final[int] = 4


class _Driver:
    """The node, in miniature: a real adapter, a real counter, and a log."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.stream = RecordingStream()
        self.publisher = CapturePublisher(self.stream, family_id=identity().family_id)
        self.adapter = FqCaptureAdapter(
            publisher=self.publisher, identity=identity(), recalibration="none"
        )
        self.counter = EvalSeqCounter()
        self.wall = DAY_START_NS + 17 * 3600 * NS
        self.lines: list[str] = [instance_line(self.wall - NS)]
        self.seqs: list[int] = []
        self.last_frame: dict[int, int] = {}

    def tick(self) -> int:
        self.wall += self.rng.randint(1, 40) * 1_000_000
        return self.wall

    @staticmethod
    def keys(index: int) -> dict[str, Any]:
        return {
            "station": "LAX" if index % 2 == 0 else "MDW",
            "rung_id": f"r{index}",
            "side": "yes" if index < 2 else "no",
            "instrument_id": f"tc-temp-x{index}-2026-10-04.POLYMARKET_US",
            "climate_day": CLIMATE_DAY,
        }

    def frame_ts(self, index: int) -> int:
        previous = self.last_frame.get(index)
        if previous is not None and self.rng.random() < 0.12:
            return previous - self.rng.randint(1, 5) * NS  # a late frame: non-monotone
        self.last_frame[index] = self.wall - 2_000_000
        return self.last_frame[index]

    def decide(self, index: int) -> Take | Refuse | NotExecutable | NotDPlus1:
        roll = self.rng.random()
        if roll < 0.25:
            return take_for(**self.keys(index))
        if roll < 0.35:
            return NotExecutable()
        if roll < 0.40:
            return NotDPlus1()
        return Refuse(reason=self.rng.choice(_REFUSALS))

    def evaluate(self, index: int, frame_ts: int, trigger: str) -> None:
        keys = self.keys(index)
        decision = self.decide(index)
        wall = self.tick()
        seq = self.counter.next(keys["instrument_id"], frame_ts)
        ctx = CaptureContext(
            eval_ns=frame_ts,
            eval_seq=seq,
            wall_ns=wall,
            trigger=cast(Any, trigger),
            depth=build_depth(ts_event=frame_ts) if trigger == "depth" else None,
            quote=build_quote(ts_event=frame_ts) if trigger == "quote_tick" else None,
            vector=None,
            ask_px=Decimal("0.15"),
            station=keys["station"],
            climate_day=keys["climate_day"],
            rung_id=keys["rung_id"],
            side=keys["side"],
            instrument_id=keys["instrument_id"],
        )
        self.seqs.append(seq)
        self.adapter.capture(decision, ctx)
        self.lines.append(decision_text(wall, decision, now_ns=frame_ts, **keys))
        if isinstance(decision, Take):
            self.follow(self.adapter.decision_record(decision, ctx), keys)

    def follow(self, take: DecisionRecord, keys: dict[str, Any]) -> None:
        choice = self.rng.randint(0, 5)
        if choice == 0:
            return  # a Take that was never submitted (shadow only)
        if choice in (1, 4):
            self._follow_up(take, keys, "TrySubmit", "submitted")
        if choice == 2:
            reason = self.rng.choice(_SOFT_VETOES)
            for _ in range(self.rng.randint(1, 2)):  # a repeat is suppressed by the filter
                self._follow_up(take, keys, "EntryVeto", reason)
        if choice == 3:
            self._follow_up(take, keys, "TrySubmit", "family_halt")
        if choice == 4:  # the capture guard refuses after the submit: written directly
            wall = self.tick()
            self.publisher.write(
                decision_follow_up(
                    take, FollowUp(kind="EntryVeto", reason="capture_gap", wall_ns=wall)
                )
            )
            self.lines.append(refused_text(wall))

    def _follow_up(
        self, take: DecisionRecord, keys: dict[str, Any], kind: str, reason: str
    ) -> None:
        wall = self.tick()
        self.adapter.follow_up(take, kind=kind, reason=reason, wall_ns=wall)
        self.lines.append(try_submit_text(wall, reason, **keys))


def run_scenario(seed: int, *, steps: int = 80) -> Scenario:
    """The oracle: ``steps`` frames across four instruments, each evaluated by one trigger or by
    a quote and depth twin, with Takes followed by TrySubmit, EntryVeto and guard refusals."""
    driver = _Driver(random.Random(seed))
    rng = driver.rng
    for _ in range(steps):
        index = rng.randrange(_N_INSTRUMENTS)
        frame_ts = driver.frame_ts(index)
        triggers = rng.choice((("depth",), ("quote_tick", "depth"), ("depth", "quote_tick")))
        for trigger in triggers:
            driver.evaluate(index, frame_ts, trigger)
    return Scenario(driver.lines, driver.stream.written_of(DecisionRecord), driver.seqs)


def views_of(records: Iterable[DecisionRecord]) -> list[DecisionView]:
    return [_decision_view(record) for record in records]


T: Final[int] = DAY_START_NS + 17 * 3600 * NS
MS: Final[int] = 1_000_000


def refuse_line(offset_ns: int, reason: str = "below_margin", **keys: Any) -> str:
    """A Refuse evaluation at ``T + offset``: its log timestamp equals its frame clock."""
    return decision_text(T + offset_ns, Refuse(reason=reason), now_ns=T + offset_ns, **keys)


def refuse_view(offset_ns: int, reason: str = "below_margin", seq: int = 0) -> Any:
    return dv("Refuse", reason, eval_ns=T + offset_ns, wall_ns=T + offset_ns, eval_seq=seq)


def causes(result: LegResult, outcome: LegOutcome | None = None) -> list[str]:
    return sorted(f.cause for f in result.findings if outcome is None or f.outcome == outcome)


def failing(result: LegResult) -> list[str]:
    return causes(result, LegOutcome.FAIL)


def funnel_row(ts_ns: int, takes: int, submits: int) -> FunnelRow:
    return FunnelRow(
        ts_ns,
        DAY.isoformat(),
        (
            FunnelCount("LAX", "yes", "Take", "", takes),
            FunnelCount("LAX", "yes", "TrySubmit", "submitted", submits),
        ),
    )
