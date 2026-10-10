"""EXEC-PAR WP0: the offline viability simulation (a HARD build gate).

Every test names a WP0 item in the plan (``EXEC-PAR-parallel-intents_plan_r5.md`` section 5 WP0).
The simulation is evidence only: it lives in ``docs/evidence/m1v3/exec_parallel_dhat.py`` and
imports the production ``breezy.domain.exec_slots.admit``. The pre-registered M1-v3 window
(climate days on or after 2026-10-07) must never be read, so the first test pins the refusal.
"""

from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import json
import math
import random
import sys
from pathlib import Path
from types import ModuleType
from typing import Protocol, runtime_checkable

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "docs" / "evidence" / "m1v3" / "exec_parallel_dhat.py"
CANDS = REPO / "docs" / "evidence" / "m1v3" / "exec_parallel_dhat_cands.json"
CLIENT = REPO / "src" / "breezy" / "adapters" / "polymarket_us" / "exec" / "client.py"
NS = 10**9
DAY = dt.date(2026, 9, 1)
T0 = int(dt.datetime(2026, 9, 1, 12, tzinfo=dt.UTC).timestamp()) * NS


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("exec_parallel_dhat", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["exec_parallel_dhat"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sim() -> ModuleType:
    return _load()


def _cand(sim: ModuleType, offset_s: float, n: int, *, leg: str = "yes") -> object:
    slug = f"wthr-high-sfo-2026-09-01-r{n}"
    symbol = slug if leg == "yes" else f"{slug}^no"
    return sim.Candidate(
        ts_ns=T0 + int(offset_s * NS),
        station="SFO",
        instrument_id=f"{symbol}.POLYMARKET_US",
        no_ask=0.93,
    )


def _arm(sim: ModuleType, **kw: object) -> object:
    base: dict[str, object] = {
        "k": 8,
        "p_amb": 0.0,
        "bucket": 0.02,
        "free_arm": "A",
        "stuck": 0,
        "no_id": False,
        "throttle": False,
        "bound": False,
        "free0": None,
    }
    base.update(kw)
    return sim.Arm(**base)


@runtime_checkable
class _Outcome(Protocol):
    """The result fields of ``simulate_day`` that these tests read."""

    @property
    def admitted(self) -> int: ...

    @property
    def drops(self) -> dict[str, int]: ...

    @property
    def first5s_fraction(self) -> float: ...


def _run(sim: ModuleType, cands: list[object], arm: object, seed: int = 1) -> _Outcome:
    out = sim.simulate_day(tuple(cands), arm, random.Random(seed))
    assert isinstance(out, _Outcome)
    return out


# --------------------------------------------------------------------------- data rule


@pytest.mark.parametrize(
    "bad",
    [dt.date(2026, 10, 7), dt.date(2026, 10, 8), dt.date(2026, 11, 28), dt.date(2027, 1, 1)],
)
def test_refuses_any_input_on_or_after_2026_10_07(sim: ModuleType, bad: dt.date) -> None:
    with pytest.raises(sim.WindowDataRefused):
        sim.refuse_window_day(bad)
    sim.refuse_window_day(dt.date(2026, 10, 6))  # the last pre-window day is allowed
    cutoff_ns = int(dt.datetime(2026, 10, 7, tzinfo=dt.UTC).timestamp()) * NS
    with pytest.raises(sim.WindowDataRefused):
        sim.refuse_window_ns(cutoff_ns)
    sim.refuse_window_ns(cutoff_ns - 1)


def test_refuses_window_dated_paths_candidates_and_extraction_before_any_io(
    sim: ModuleType, tmp_path: Path
) -> None:
    with pytest.raises(sim.WindowDataRefused):
        sim.refuse_window_path(tmp_path / "tape_20261007T120000Z.parquet")
    with pytest.raises(sim.WindowDataRefused):
        sim.refuse_window_path(tmp_path / "cands-2026-10-09.json")
    sim.refuse_window_path(tmp_path / "cands-2026-10-06.json")
    # extraction refuses a window day BEFORE touching the (non-existent) catalog root
    with pytest.raises(sim.WindowDataRefused):
        sim.extract_candidates(dt.date(2026, 8, 30), dt.date(2026, 10, 7), tmp_path / "absent")
    # a candidates file that smuggles a window day is refused on load
    bad = tmp_path / "c.json"
    bad.write_text(json.dumps({"schema": 1, "days": {"2026-10-07": []}}))
    with pytest.raises(sim.WindowDataRefused):
        sim.load_candidates(bad)
    bad.write_text(
        json.dumps(
            {
                "schema": 1,
                "days": {
                    "2026-09-01": [
                        {
                            "ts_ns": int(dt.datetime(2026, 10, 7, 12, tzinfo=dt.UTC).timestamp())
                            * NS,
                            "station": "SFO",
                            "instrument_id": "x.POLYMARKET_US",
                            "no_ask": "0.93",
                        }
                    ]
                },
            }
        )
    )
    with pytest.raises(sim.WindowDataRefused):
        sim.load_candidates(bad)
    assert sim.main(["--cands", str(bad), "--out", str(tmp_path / "o.json")]) == 2
    assert not (tmp_path / "o.json").exists()


def test_extraction_bounds_equal_the_triage_script_bounds(sim: ModuleType) -> None:
    tree = ast.parse((REPO / "docs/evidence/m1v3/stage_minus1_triage_dmix.py").read_text())
    bounds: tuple[dt.date, dt.date] | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Tuple):
            names = [t.id for t in getattr(node.targets[0], "elts", []) if isinstance(t, ast.Name)]
            if names == ["FIRST", "LAST"]:
                dates = [
                    dt.date(
                        *[
                            a.value
                            for a in call.args
                            if isinstance(a, ast.Constant) and isinstance(a.value, int)
                        ]
                    )
                    for call in node.value.elts
                    if isinstance(call, ast.Call)
                ]
                bounds = (dates[0], dates[1])
    assert bounds == (sim.FIRST_DAY, sim.LAST_DAY)
    assert sim.LAST_DAY < sim.CUTOFF_DAY


# --------------------------------------------------------------------------- K=1 reproduction


def test_k1_reproduces_p0_p90_0_491(sim: ModuleType) -> None:
    by_day = sim.load_candidates(CANDS)
    value = sim.k1_p0_p90(by_day, draws=sim.DRAWS)
    assert value == pytest.approx(0.491, abs=0.002)


# --------------------------------------------------------------------------- production admit


def test_simulation_uses_production_admit(sim: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    from breezy.domain import exec_slots

    assert sim.admit is exec_slots.admit
    calls: list[int] = []
    real = exec_slots.admit

    def spy(
        table: exec_slots.SlotTableView,
        slug: str,
        is_exit: bool,
        k: int,
        entry_halted: bool,
        now_ns: int,
    ) -> exec_slots.Admit | exec_slots.Wait:
        calls.append(1)
        result = real(table, slug, is_exit, k, entry_halted, now_ns)
        assert isinstance(result, exec_slots.Admit | exec_slots.Wait)
        return result

    monkeypatch.setattr(sim, "admit", spy)
    cands = [_cand(sim, 0.0, 1), _cand(sim, 0.01, 2), _cand(sim, 5.0, 3)]
    _run(sim, cands, _arm(sim, k=8))
    assert len(calls) == 3


def test_yes_and_no_share_one_slot(sim: ModuleType) -> None:
    assert sim.slug_of("a-b^no.POLYMARKET_US") == sim.slug_of("a-b.POLYMARKET_US") == "a-b"
    out = _run(sim, [_cand(sim, 0.0, 1), _cand(sim, 0.05, 1, leg="no")], _arm(sim, k=8))
    assert out.admitted == 1
    assert out.drops == {"admit:slug_open": 1}


def test_stuck_slot_reduces_effective_k(sim: ModuleType) -> None:
    cands = [_cand(sim, i * 0.01, i) for i in range(4)]
    clean = _run(sim, cands, _arm(sim, k=3, stuck=0))
    stuck = _run(sim, cands, _arm(sim, k=3, stuck=1))
    assert clean.admitted == 3 and clean.drops == {"admit:k_full": 1}
    assert stuck.admitted == 2 and stuck.drops == {"admit:k_full": 2}


# --------------------------------------------------------------------------- the three drop arms


def test_throttle_5_per_s_drop_counted(sim: ModuleType) -> None:
    cands = [_cand(sim, i * 0.05, i) for i in range(7)]
    off = _run(sim, cands, _arm(sim, k=8, throttle=False))
    on = _run(sim, cands, _arm(sim, k=8, throttle=True))
    assert off.admitted == 7 and off.drops == {}
    assert on.admitted == 5 and on.drops == {"throttle": 2}
    # the sliding 1 s window frees up: a 6th order 1.1 s after the first is allowed
    later = [_cand(sim, i * 0.05, i) for i in range(5)] + [_cand(sim, 1.2, 9)]
    assert _run(sim, later, _arm(sim, k=8, throttle=True)).drops == {}


def test_free_balance_arm_a_fill_time(sim: ModuleType) -> None:
    # bucket 0.5 against a free balance of 0.5 budgets: only one fill fits.
    arm = _arm(sim, k=8, bucket=0.50, free_arm="A", free0=0.5)
    in_transit = _run(sim, [_cand(sim, 0.0, 1), _cand(sim, 0.1, 2)], arm)
    # arm A reduces `free` at the fill (0.3 s), so a second order at 0.1 s still passes
    assert in_transit.admitted == 2 and in_transit.drops == {}
    after_fill = _run(sim, [_cand(sim, 0.0, 1), _cand(sim, 0.4, 2)], arm)
    assert after_fill.admitted == 1 and after_fill.drops == {"free_balance": 1}


def test_free_balance_arm_b_ambiguous_holds(sim: ModuleType) -> None:
    cands = [_cand(sim, 0.0, 1), _cand(sim, 1.0, 2)]
    common = {"k": 8, "bucket": 0.50, "p_amb": 1.0, "free0": 0.75}
    a = _run(sim, cands, _arm(sim, free_arm="A", **common))
    b = _run(sim, cands, _arm(sim, free_arm="B", **common))
    # A: the ambiguous order has not filled yet, so the balance is intact (0.75 >= 0.5)
    assert a.admitted == 2 and a.drops == {}
    # B: the ambiguous order holds 0.5 for its stuck lifetime, leaving 0.25 < 0.5
    assert b.admitted == 1 and b.drops == {"free_balance": 1}


def test_ambiguous_bound_drop_counted_per_cost_over_budget_bucket(sim: ModuleType) -> None:
    cands = [_cand(sim, i * 0.1, i) for i in range(4)]
    admitted = {}
    for bucket in (0.02, 0.05, 0.10, 0.25, 0.50):
        out = _run(sim, cands, _arm(sim, k=8, bucket=bucket, p_amb=1.0, bound=True))
        admitted[bucket] = (out.admitted, out.drops.get("ambiguous_bound", 0))
    # f_adm = 0.50: open ambiguous total plus the new cost must stay <= 0.50 budgets
    assert admitted == {0.02: (4, 0), 0.05: (4, 0), 0.10: (4, 0), 0.25: (2, 2), 0.50: (1, 3)}
    # the bound is off when disabled
    off = _run(sim, cands, _arm(sim, k=8, bucket=0.50, p_amb=1.0, bound=False))
    assert off.admitted == 4


def test_stop_rule_uses_worse_free_balance_arm(sim: ModuleType) -> None:
    cells = {
        sim.CellKey(0.10, 4, 0.33, "A", 1, False): sim.CellStat(0.0, 0.0, 0.18, 0.10, 0.25),
        sim.CellKey(0.10, 4, 0.33, "B", 1, False): sim.CellStat(0.0, 0.0, 0.40, 0.30, 0.55),
    }
    assert sim.worse_arm_upper(cells, 0.10, 4, 0.33, 1, False) == pytest.approx(0.55)
    assert sim.smallest_passing_k(cells, 0.10) is None  # A passes, B fails: the stop rule fails


def test_k_reported_per_bucket_no_worst_bucket_fallback(sim: ModuleType) -> None:
    def put(cells: dict[object, object], bucket: float, k: int, upper: float) -> None:
        for arm in ("A", "B"):
            cells[sim.CellKey(bucket, k, 0.33, arm, 1, False)] = sim.CellStat(
                0, 0, upper - 0.1, upper - 0.2, upper
            )

    cells: dict[object, object] = {}
    for k in range(3, 9):
        put(cells, 0.50, k, 0.90)
        put(cells, 0.05, k, 0.60 if k < 5 else 0.20)
    table = sim.smallest_k_per_bucket(cells)
    assert table[0.50] is None
    assert table[0.05] == 5
    assert set(table) == set(sim.BUCKETS)


def test_build_gate_requires_a_bucket_at_or_above_0_05(sim: ModuleType) -> None:
    only_small = {0.02: 3, 0.05: None, 0.10: None, 0.25: None, 0.50: None}
    assert sim.build_gate_verdict(only_small)["verdict"] == "STOP"
    one_mid = {0.02: 3, 0.05: 6, 0.10: None, 0.25: None, 0.50: None}
    verdict = sim.build_gate_verdict(one_mid)
    assert verdict["verdict"] == "PASS" and verdict["passing_buckets"] == [0.05]
    over_k = {0.02: 3, 0.05: None, 0.10: 9, 0.25: None, 0.50: None}
    assert sim.build_gate_verdict(over_k)["verdict"] == "STOP"  # K must be <= 8


def test_per_bucket_order_cost_distribution_reported(sim: ModuleType) -> None:
    cands = tuple(
        sim.Candidate(T0 + i * NS, "SFO", f"s{i}.POLYMARKET_US", 0.90 + 0.01 * (i % 10))
        for i in range(40)
    )
    dist = sim.cost_distribution(cands)
    assert set(dist["usd_per_order"]) >= {"n", "min", "p50", "p90", "max"}
    assert dist["usd_per_order"]["min"] == pytest.approx(0.90)
    for label in ("<=0.02", "0.05", "0.10", "0.25", "0.50"):
        row = dist["by_bucket"][label]
        assert {"cost_over_budget", "cap_over_budget", "implied_budget_usd"} <= set(row)
        assert row["cost_over_budget"]["p50"] == pytest.approx(
            dist["usd_per_order"]["p50"] / row["implied_budget_usd"]
        )
        assert row["cap_over_budget_label"] in {"<=0.02", "0.05", "0.10", "0.25", "0.50", ">0.50"}
    # a 1.00 USD cap against the 0.50-bucket budget exceeds 0.50: the sentinel label
    assert sim.bucket_label(0.75) == ">0.50"
    assert sim.bucket_label(0.50) == "0.50" and sim.bucket_label(0.01) == "<=0.02"
    assert sim.bucket_label(0.26) == "0.50"


# --------------------------------------------------------------------------- statistics


def test_cluster_bootstrap_ci_upper_bound_stop(sim: ModuleType) -> None:
    flat = [0.2] * 30
    assert sim.cluster_bootstrap_ci(flat, 0.9, resamples=200, seed=1) == (
        pytest.approx(0.2),
        pytest.approx(0.2),
        pytest.approx(0.2),
    )
    noisy = [0.0] * 20 + [0.9] * 10  # day-level p90 of 0.9 but resampling spread is large
    point, lo, hi = sim.cluster_bootstrap_ci(noisy, 0.5, resamples=2000, seed=7)
    assert lo <= point <= hi and hi > point
    again = sim.cluster_bootstrap_ci(noisy, 0.5, resamples=2000, seed=7)
    assert again == (point, lo, hi)  # seeded: deterministic
    # the stop rule reads the UPPER bound, not the point estimate
    assert sim.passes_stop_rule(0.28) and sim.passes_stop_rule(0.30)
    assert not sim.passes_stop_rule(0.3001)
    assert not sim.passes_stop_rule(math.nan)


def test_first_5s_budget_fraction_arm(sim: ModuleType) -> None:
    cands = [
        _cand(sim, 0.0, 1),
        _cand(sim, 2.0, 2),
        _cand(sim, 4.9, 3),
        _cand(sim, 5.0, 4),
        _cand(sim, 60.0, 5),
    ]
    out = _run(sim, cands, _arm(sim, k=8, bucket=0.10))
    # three admitted orders land inside the first 5 s of the window, 0.10 budgets each
    assert out.first5s_fraction == pytest.approx(0.30)
    assert out.admitted == 5


def test_draws_are_seeded_and_deterministic(sim: ModuleType) -> None:
    cands = tuple(_cand(sim, i * 0.2, i) for i in range(12))
    arm = _arm(sim, k=3, p_amb=0.33, bucket=0.10, throttle=True, bound=True)
    first = sim.day_stats(cands, arm, DAY, draws=50)
    second = sim.day_stats(cands, arm, DAY, draws=50)
    assert first == second


# --------------------------------------------------------------------------- recorded constants


def _const_value(node: ast.expr) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    assert isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult)
    return _const_value(node.left) * _const_value(node.right)


def _client_constants() -> dict[str, float]:
    wanted = {
        "_RESOLVER_POLL_INTERVAL_SECS",
        "_RESOLVER_ZERO_FILL_MIN_AGE_NS",
        "_RESOLVER_NO_ID_MIN_AGE_NS",
    }
    found: dict[str, float] = {}
    for node in ast.walk(ast.parse(CLIENT.read_text())):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id in wanted
        ):
            assert node.value is not None
            found[node.target.id] = _const_value(node.value)
    assert set(found) == wanted
    return found


def test_hold_constants_match_exec_client_source_ast(sim: ModuleType) -> None:
    const = _client_constants()
    poll = const["_RESOLVER_POLL_INTERVAL_SECS"]
    zero_fill_s = const["_RESOLVER_ZERO_FILL_MIN_AGE_NS"] / NS
    no_id_s = const["_RESOLVER_NO_ID_MIN_AGE_NS"] / NS
    assert sim.hold_constants_from_client_source(CLIENT) == {
        "poll_s": poll,
        "zero_fill_min_age_s": zero_fill_s,
        "no_id_min_age_s": no_id_s,
    }
    assert sim.HOLD_AMB_FAST_S == poll  # accept-fill discovered on the first poll
    assert sim.HOLD_AMB_SLOW_S >= zero_fill_s + poll  # zero-fill floor plus one poll
    assert sim.NO_ID_HOLD_S == no_id_s + poll
    sim.assert_hold_constants_current(CLIENT)
    assert sim.HOLD_FILL_S == 0.3


def test_caps_read_only_bucket_label_only_never_printed_or_assigned(
    sim: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    # off by default: the flag is absent, the reader is never called
    assert sim.parse_args([]).caps_bucket_reader is None
    reads: list[int] = []

    def fake_reader() -> str:
        reads.append(1)
        return "0.10"

    assert sim.caps_bucket_label(fake_reader) == "0.10"
    assert reads == [1]
    assert capsys.readouterr().out == ""  # the helper prints nothing
    # a reader that leaks a number (not a ladder label) is rejected without echoing it
    with pytest.raises(sim.CapsReadRefused) as err:
        sim.caps_bucket_label(lambda: "123.45")
    assert "123.45" not in str(err.value)
    # source-level: no operator_controls import, no value-bearing names in the script
    source = SCRIPT.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all("operator_controls" not in a.name for a in node.names)
        if isinstance(node, ast.ImportFrom):
            assert "operator_controls" not in (node.module or "")
    assert "max_daily_budget" not in source and "max_per_position" not in source


def test_positions_feed_lag_bound_measured_or_300s_default(sim: ModuleType) -> None:
    assert sim.positions_feed_lag_bound(None) == 300.0
    assert sim.positions_feed_lag_bound([]) == 300.0
    assert sim.positions_feed_lag_bound([12.0, 80.5, 41.2]) == 80.5
    with pytest.raises(ValueError):
        sim.positions_feed_lag_bound([5.0, -1.0])
    with pytest.raises(ValueError):
        sim.positions_feed_lag_bound([math.nan])
