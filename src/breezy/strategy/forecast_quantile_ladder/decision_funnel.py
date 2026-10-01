"""FQ-S11: in-process decision-funnel aggregator for `forecast_quantile_ladder`.

Plan `FQ_GO_LIVE_PLAN_2026-10-01.md` S11: a per-(station, side, kind, reason)
count of every decision `ForecastQuantileLadderStrategy.evaluate_snapshot`
emits (through its existing `shadow_decision_sink`), plus the `try_submit`
guard outcome, flushed as one JSONL summary row every 15 minutes and once
more at `on_stop`, via a native Nautilus `Actor` clock timer -- the SAME
`clock.set_timer`/`cancel_timer` pattern already used by `NbmQuantileActor`/
`NwsIngestActor`/`FeeDriftProbeActor` (never a bespoke scheduler).

Counts only -- never a price, a P&L figure, or a per-decision list.
``decision_log_fields`` (``decision.py``) never emits a price/P&L field for
anything but a ``Take``'s own ``ev_net``/``p_hat``/``p_lower``/``p_upper``,
and this module never reads those fields: :meth:`FqDecisionCounts.record_line`
only ever reads ``station``/``side``/``kind``/``reason``.

The vocabulary is OPEN, not a closed enum: a ``reason`` string this module
has never seen before (e.g. a refusal reason a sibling slice adds later,
such as ``opposite_side_latched``) is counted under its own name
automatically, never dropped and never a crash. A fresh process boot starts
a fresh (empty) counter, so memory is bounded by the small
(station x side x kind x reason) key space, never by the number of
decisions evaluated that day -- there is no per-decision list anywhere in
this module.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Final

from nautilus_trader.common.actor import Actor

__all__ = [
    "DEFAULT_FLUSH_INTERVAL_SECONDS",
    "FqDecisionCounts",
    "FqDecisionFunnelActor",
]

logger = logging.getLogger(__name__)

#: S11: "flushes 1 JSONL summary row per 15 min".
DEFAULT_FLUSH_INTERVAL_SECONDS: Final[int] = 15 * 60

_TIMER_NAME: Final[str] = "fq-decision-funnel-flush"


class FqDecisionCounts:
    """Pure, dependency-free ``(station, side, kind, reason) -> count`` map.

    No I/O, no Nautilus import -- :class:`FqDecisionFunnelActor` is the only
    caller that touches a clock or a filesystem. ``record``/``record_line``
    never raise on an unrecognised ``reason``: the vocabulary is open by
    design (module docstring).
    """

    def __init__(self) -> None:
        self._counts: dict[tuple[str, str, str, str], int] = {}

    def record(self, *, station: str, side: str, kind: str, reason: str = "") -> None:
        key = (station, side, kind, reason)
        self._counts[key] = self._counts.get(key, 0) + 1

    def record_line(self, line: Mapping[str, object]) -> None:
        """Adapts one ``ShadowDecisionLogLine``-shaped mapping (or the
        synthetic ``kind="TrySubmit"`` line
        ``ForecastQuantileLadderStrategy._emit_decision_outcome`` builds)
        into one :meth:`record` call.

        ``reason`` is absent on a ``Take`` line by design
        (``decision_log_fields`` carries no ``reason`` field for ``Take``)
        -- recorded as the empty string, its own distinct, stable key, never
        conflated with a real reason string.
        """
        self.record(
            station=str(line.get("station") or ""),
            side=str(line.get("side") or ""),
            kind=str(line.get("kind") or ""),
            reason=str(line.get("reason") or ""),
        )

    def snapshot(self) -> tuple[dict[str, object], ...]:
        """Sorted, JSON-ready rows -- deterministic flush output. Every row
        carries exactly ``station``/``side``/``kind``/``reason``/``count`` --
        never a price or P&L field."""
        return tuple(
            {"station": station, "side": side, "kind": kind, "reason": reason, "count": count}
            for (station, side, kind, reason), count in sorted(self._counts.items())
        )

    def total(self) -> int:
        return sum(self._counts.values())


def _write_flush_row(path: Path, row: Mapping[str, object]) -> None:
    """Append one JSONL line, mode 0600 -- mirrors
    ``current_rung_hold.diagnostics_summary.DiagnosticsSummarySink.append``'s
    own mkdir/open('a')/chmod shape. Never raises: a write failure here must
    not take down the strategy process it is only observing (L-16's own
    stance, applied to this sidecar)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(dict(row), sort_keys=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.write("\n")
        path.chmod(0o600)
    except OSError:
        logger.exception("FqDecisionFunnelActor: failed to flush %s", path)


class FqDecisionFunnelActor(Actor):
    """Owns ONE :class:`FqDecisionCounts` and flushes it on a native clock timer.

    Composed ONCE per boot (``forecast_quantile_ladder.composition``), and
    shared by every per-station ``ForecastQuantileLadderStrategy`` through
    its :attr:`counts` -- the composition root wires each strategy's
    ``shadow_decision_sink`` to ``counts.record_line`` directly. The output
    path is fixed for the process's lifetime at ``fq_funnel_<boot
    day>.jsonl`` under ``output_dir``, the SAME sibling-directory convention
    ``current_rung_hold.composition._decisions_dir`` already uses (a sibling
    of the quote-tape catalog root, never nested under it).
    """

    def __init__(
        self,
        *,
        output_dir: Path,
        counts: FqDecisionCounts | None = None,
        flush_interval_seconds: int = DEFAULT_FLUSH_INTERVAL_SECONDS,
    ) -> None:
        super().__init__()
        self._output_dir = output_dir
        self.counts = counts if counts is not None else FqDecisionCounts()
        self._flush_interval = timedelta(seconds=flush_interval_seconds)
        self._timer_armed = False
        self._boot_day: str | None = None

    @property
    def output_path(self) -> Path | None:
        if self._boot_day is None:
            return None
        return self._output_dir / f"fq_funnel_{self._boot_day}.jsonl"

    def on_start(self) -> None:
        self._boot_day = self.clock.utc_now().date().isoformat()
        self.clock.set_timer(
            name=_TIMER_NAME,
            interval=self._flush_interval,
            callback=self._on_timer,
        )
        self._timer_armed = True

    def on_stop(self) -> None:
        if self._timer_armed:
            try:
                self.clock.cancel_timer(_TIMER_NAME)
            except (KeyError, ValueError):  # pragma: no cover - defensive
                logger.debug("timer %s was already cancelled", _TIMER_NAME)
            self._timer_armed = False
        self._flush(final=True)

    def _on_timer(self, event: object) -> None:
        self._flush(final=False)

    def _flush(self, *, final: bool) -> None:
        path = self.output_path
        if path is None:  # pragma: no cover - defensive: flush before on_start
            return
        row = {
            "ts_ns": self.clock.timestamp_ns(),
            "boot_day": self._boot_day,
            "final": final,
            "counts": list(self.counts.snapshot()),
        }
        _write_flush_row(path, row)
