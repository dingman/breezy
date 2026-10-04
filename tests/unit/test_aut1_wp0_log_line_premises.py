"""AUT-1 WP0 premises, V-14 items 8, 11, 12: supervisor spawn lines, SHADOW_DECISION, disposal line.

Shared helpers live in ``aut1_premises_support`` (WP0-R10).
"""

import ast
import datetime as dt
import logging
import re
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final

import pytest
from nautilus_trader.common.actor import Actor
from nautilus_trader.common.component import TestClock
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from tests.unit.aut1_premises_support import (
    NS,
    NT_ROOT,
    SRC_DIR,
    _iso_ns,
)

# ---------------------------------------------------------------------------
# V-14  fill_by_fingerprint <day>; supervisor spawn lines; one SHADOW_DECISION; disposal line
# ---------------------------------------------------------------------------


@pytest.fixture
def supervisor_logger_restored() -> Iterator[logging.Logger]:
    from breezy.runtime import trade_supervisor

    log = trade_supervisor.logger
    saved = (list(log.handlers), log.level, log.propagate)
    yield log
    for handler in list(log.handlers):
        if handler not in saved[0]:
            handler.close()
            log.removeHandler(handler)
    log.handlers[:] = saved[0]
    log.setLevel(saved[1])
    log.propagate = saved[2]


#: ``~/.local/share/breezy/logs/breezy-trade-supervisor.log``: a retained, recorded line.
RECORDED_SUPERVISOR_LAUNCHED: Final[str] = (
    "2026-10-03T16:50:45Z INFO breezy.runtime.trade_supervisor launched pid=529436"
)
_SUPERVISOR_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z INFO breezy\.runtime\.trade_supervisor "
    r"(?P<event>[a-z_]+)(?P<fields>( \w+=\S+)*)$"
)


def test_supervisor_spawn_sites_and_their_log_lines(
    tmp_path: Path, supervisor_logger_restored: logging.Logger
) -> None:
    """V-14 item 11. There are FOUR ``ports.spawn`` call sites, not r8's three. Only
    ``_do_launch`` (``launched pid=<n>``) and ``_launch_boot_retry_child``
    (``boot_retry_launched pid=<n>``) log the pid; ``_do_relaunch_check`` logs ``relaunching
    attempt=<n>`` and the new site in ``_do_midday_watch`` logs ``midday_relaunching phase=...
    attempt=<n>``, both BEFORE the spawn and with no pid. The real ``log_decision`` through the
    supervisor's own formatter renders a line matching the recorded journal text.

    MUTATION (red, source edit in the worktree, reverted): renaming ``"launched"`` to
    ``"started"`` at the ``_do_launch`` site breaks both the AST map and the rendered line.
    """
    from breezy.runtime import trade_supervisor

    tree = ast.parse(Path(trade_supervisor.__file__).read_text(encoding="utf-8"))
    sites: dict[str, tuple[int, list[str]]] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
        spawns = [c for c in calls if isinstance(c.func, ast.Attribute) and c.func.attr == "spawn"]
        if not spawns:
            continue
        events = sorted(
            c.args[0].value
            for c in calls
            if isinstance(c.func, ast.Name)
            and c.func.id == "log_decision"
            and c.args
            and isinstance(c.args[0], ast.Constant)
            and c.args[0].value
            in {"launched", "relaunching", "boot_retry_launched", "midday_relaunching"}
        )
        sites[fn.name] = (len(spawns), events)
    assert sites == {
        "_do_launch": (1, ["launched"]),
        "_do_relaunch_check": (1, ["relaunching"]),
        "_launch_boot_retry_child": (1, ["boot_retry_launched"]),
        "_do_midday_watch": (1, ["midday_relaunching"]),
    }

    trade_supervisor.configure_supervisor_logging(tmp_path)
    trade_supervisor.log_decision("launched", pid=529436)
    trade_supervisor.log_decision("boot_retry_launched", pid=7)
    for handler in supervisor_logger_restored.handlers:
        handler.flush()
    lines = trade_supervisor.supervisor_log_path(tmp_path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    for line, event in zip(lines, ("launched", "boot_retry_launched"), strict=True):
        match = _SUPERVISOR_LINE_RE.fullmatch(line)
        assert match is not None and match["event"] == event
        assert re.fullmatch(r" pid=\d+", match["fields"])
    recorded = _SUPERVISOR_LINE_RE.fullmatch(RECORDED_SUPERVISOR_LAUNCHED)
    assert recorded is not None and recorded["event"] == "launched"


_FQ_DAY: Final[dt.date] = dt.date(2026, 10, 1)
_FQ_OFFSET: Final[float] = -5.0
_FQ_NOW_NS: Final[int] = _iso_ns("2026-09-30T12:00:00.000000000Z")


def _build_fq_strategy(
    *, permit_expires_at_ns: int | None, sink: Callable[[Any], None], shadow_only: bool = True
) -> Any:
    """A real ``ForecastQuantileLadderStrategy`` (the construction ``tests/strategy/
    forecast_quantile_ladder/test_strategy.py`` uses), with a no-forecast quantile actor."""
    from breezy.strategy.forecast_quantile_ladder.calibration_artefact import LiveCalibration
    from breezy.strategy.forecast_quantile_ladder.config import ForecastQuantileLadderConfig
    from breezy.strategy.forecast_quantile_ladder.strategy import ForecastQuantileLadderStrategy
    from breezy.strategy.ladder_ev.config import LadderEvConfig
    from breezy.strategy.ladder_ev.forecast_subscriber import ForecastQuantileStateActor
    from breezy.strategy.ladder_ev.location_correction import CorrectionForm
    from breezy.strategy.ladder_ev.quantile_density import CdfMethod, EmosParams

    clock = TestClock()
    clock.set_time(_FQ_NOW_NS)
    actor = ForecastQuantileStateActor(
        stations=("KMIA",), std_utc_offset_hours={"KMIA": _FQ_OFFSET}
    )
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=clock,
    )
    actor.start()
    identity = EmosParams(a=0.0, gamma=0.0, delta=1.0)
    calibration = LiveCalibration(
        sha256="a" * 64,
        cdf_method=CdfMethod.NORMAL,
        correction_form=CorrectionForm.NONE,
        linear_coefficients=None,
        month_offsets={},
        point_by_version={"": identity},
        draws_by_version={"": (identity,)},
    )
    strategy = ForecastQuantileLadderStrategy(
        ForecastQuantileLadderConfig(
            stations=("KMIA",),
            calibration_artefact_path="/tmp/unused.json",
            calibration_artefact_sha256="a" * 64,
            shadow_only=shadow_only,
        ),
        quantile_actor=actor,
        calibration=calibration,
        ladder_cfg=LadderEvConfig(),
        bounds_provider=lambda **kwargs: None,  # type: ignore[arg-type]
        order_submission_permit=(
            None
            if permit_expires_at_ns is None
            else SimpleNamespace(expires_at_ns=permit_expires_at_ns)
        ),
        shadow_decision_sink=sink,
    )
    strategy.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=clock,
    )
    return strategy


def test_every_evaluation_emits_one_shadow_decision_line() -> None:
    """V-14 item 12 (``strategy.py:535-581``). Each ``evaluate_snapshot`` call hands exactly ONE
    record to the shadow sink and goes through ``_emit_shadow_decision``, the only writer of the
    ``SHADOW_DECISION`` log text, for each non-Take ``Decision`` variant reached with the real
    ``evaluate`` (no permit, not D+1, no forecast). FINDING: a ``Take`` that reaches
    ``_maybe_submit`` with ``shadow_only=False`` emits a SECOND record (``kind=TrySubmit``), so the
    line count per Take evaluation is 2, not 1. The ``Take`` branch of ``_shadow_log_line`` is
    covered by ``test_strategy.py``.

    MUTATION (red, source edit in the worktree, reverted): a second ``_emit_shadow_decision``
    call in ``evaluate_snapshot`` makes the per-call count 2.
    """
    from breezy.strategy.forecast_quantile_ladder.decision import SidedAsk
    from breezy.strategy.ladder_ev.quantile_density import Rung

    ladder = (Rung("lt", None, 77), Rung("i0", 78, 79), Rung("i1", 80, 81), Rung("gte", 82, None))
    open_permit = _FQ_NOW_NS + 10 * 3_600 * NS
    cases = [
        ("NotExecutable", None, _FQ_DAY),
        ("NotDPlus1", open_permit, _FQ_DAY + dt.timedelta(days=3)),
        ("Refuse", open_permit, _FQ_DAY),
    ]
    for kind, permit, climate_day in cases:
        records: list[Any] = []
        strategy = _build_fq_strategy(permit_expires_at_ns=permit, sink=records.append)
        emitted: list[Any] = []
        original = strategy._emit_shadow_decision
        strategy._emit_shadow_decision = lambda line, o=original, e=emitted: (
            e.append(line),
            o(line),
        )[1]
        strategy.evaluate_snapshot(
            now_ns=_FQ_NOW_NS,
            std_utc_offset_hours=_FQ_OFFSET,
            station="KMIA",
            climate_day=climate_day,
            ladder=ladder,
            rung_id="i1",
            ask=SidedAsk(side="yes", instrument_id="KMIA-premise-i1.POLY_US", price=0.30),
            fee_coefficient=0.0695,
            slippage_floor_prob=0.01,
            h_hours=6.0,
        )
        assert [r["kind"] for r in records] == [kind]
        assert len(emitted) == 1
    # FINDING: a Take adds a SECOND SHADOW_DECISION record. With ``shadow_only=False``,
    # ``_maybe_submit`` -> ``_emit_decision_outcome`` writes one ``TrySubmit`` record through the
    # same sink and the same log line (``strategy.py:630-660``, ``:688-701``).
    from breezy.strategy.forecast_quantile_ladder.decision import Take

    live_records: list[Any] = []
    live = _build_fq_strategy(
        permit_expires_at_ns=None, sink=live_records.append, shadow_only=False
    )
    take = Take(
        instrument_id="KMIA-premise-i1.POLY_US",
        station="KMIA",
        climate_day=_FQ_DAY,
        side="yes",
        rung_id="i1",
        qty=1,
        ev_net=0.1,
        p_hat=0.2,
        p_lower=0.17,
        p_upper=0.23,
    )
    live._maybe_submit(take, limit_price=Decimal("0.30"))
    assert [(r["kind"], r["reason"]) for r in live_records] == [
        ("TrySubmit", "phase0_permit_absent")
    ]
    source = (
        SRC_DIR / "breezy" / "strategy" / "forecast_quantile_ladder" / "strategy.py"
    ).read_text(encoding="utf-8")
    assert source.count('self.log.info(f"SHADOW_DECISION {line!r}")') == 1
    assert (
        source.count("self._emit_shadow_decision(") == 2
    )  # evaluate_snapshot + _emit_decision_outcome


#: ``breezy-trade-20261002T200526Z.log`` line 70915: the retained disposal line, ANSI stripped.
RECORDED_DISPOSED_LINE: Final[str] = (
    "2026-10-02T20:55:21.478676119Z [INFO] BREEZY-L001.FORECAST-QUANTILE-LADDER: DISPOSED"
)
_DISPOSED_RE: Final[re.Pattern[str]] = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{9}Z \[INFO\] (?P<component>\S+): DISPOSED$"
)


def test_nautilus_disposal_line_text_is_component_colon_disposed() -> None:
    """V-14 item 8. Disposing a Nautilus component logs ``<component id>: DISPOSED`` at INFO
    (``component.pyx:2202`` logs the FSM state name), the same text the retained node log holds.

    MUTATION (red): a regex expecting ``DISPOSING`` (the transient state) matches neither line.
    """
    from tests.support.nautilus_log_capture import capture_nautilus_logs

    read = capture_nautilus_logs()
    clock = TestClock()
    actor = Actor()
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=clock,
    )
    actor.start()
    actor.stop()
    actor.dispose()
    disposed = [line for line in read() if line.endswith(": DISPOSED")]
    assert len(disposed) == 1
    live = _DISPOSED_RE.fullmatch(re.sub(r"\x1b\[[0-9;]*m", "", disposed[0]))
    assert live is not None and live["component"].endswith(actor.id.value)
    recorded = _DISPOSED_RE.fullmatch(RECORDED_DISPOSED_LINE)
    assert recorded is not None and recorded["component"].endswith("FORECAST-QUANTILE-LADDER")
    source = (NT_ROOT / "common" / "component.pyx").read_text(encoding="utf-8")
    assert 'self._log.info(f"{self._fsm.state_string_c()}")' in source
