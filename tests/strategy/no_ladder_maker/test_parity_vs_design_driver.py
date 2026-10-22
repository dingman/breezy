"""ARM C3: the ported maker decision core posts exactly what the design driver posts (sharp arm).

The fixture (`scripts/analysis/maker_parity_fixture_extract.py`) holds, per station-day, the
simulator's input events, the pinned NBP rows and the episodes the DRIVER's own replay produced
on the full tape (Delta = 0, +600 s, -600 s). Two runs are made here over the same events:

* the script side: Stage 0 `PNoStore` + `maker_stage0_adapter` selector, under the sharp arm's
  `rule_override`, exactly as `maker_design_nobid` wires them;
* the port side: `breezy.strategy.no_ladder_maker` (`PNoStore.from_source`, `build_selector`,
  `SHARP_V1`) wrapped into the simulator's selector protocol, with NO module global overridden.

Both are held to the fixture's stored driver episodes. The simulator is the Stage 0 one on both
sides (it is not part of the port); only the decision core differs. An episode's expire is not a
simulator field, so it is derived from the port's `gtd_expire_ns` and held to the simulator's
clock-cut end of that episode. That check proves clock-cut consistency (min(permit end, next UTC
midnight)) only; hard-cancel parity is proven by `test_hard_cancel_*`, including the synthetic
case where the window does reach D 09:00 LST.

R10 asked for LAX/SFO fixtures "spanning 17:00Z". That is unsatisfiable: no posting window spans
D 09:00 LST (17:00Z on D for LAX/SFO; the permit ends D 02:50Z), per plan_r3_delta.md
R10-ERRATUM. The fixtures carry the CANCEL_HARD cut in their clock stream instead.

P_MIN / E_MIN sensitivity is NOT exercised here (the fixture days do not discriminate them); it is
covered by the grids in test_rule_port_equivalence.py: `test_b_max_and_decide_bid_grid`,
`test_b_max_none_and_lowest_cent_region_matches_original`, `test_b_max_equality_boundary_needs_eps`
and `test_ladder_plan_select_and_k1_grid`.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from breezy.persistence.nbp_derived_store import (
    DerivedNbpRow,
    partition_path,
    read_partition,
    write_partition,
)
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import (
    LiveCalibration,
    load_live_calibration,
)
from breezy.strategy.ladder_ev.quantile_density import Rung
from breezy.strategy.no_ladder_maker import params as p
from breezy.strategy.no_ladder_maker import pno, pno_store, rule, selector
from breezy.strategy.no_ladder_maker import records as t
from scripts.analysis import maker_parity_fixture_extract as fx
from scripts.analysis import maker_stage0_adapter as s_adapter
from scripts.analysis import maker_stage0_fill_events as s_events
from scripts.analysis import maker_stage0_pno as s_pno
from scripts.analysis import maker_stage0_rule as s_rule
from scripts.analysis.maker_design_config import ARMS
from scripts.analysis.maker_design_nobid import rule_override
from scripts.analysis.maker_stage0_events_build import (
    CutSpec,
    DataEvents,
    clock_events,
    merge_events,
    replay_station_day,
)
from scripts.analysis.maker_stage0_fill import simulate_station_day
from scripts.analysis.maker_stage0_frozen import LAST_ALLOWED_DAY, SEALED_DAY
from scripts.analysis.maker_stage0_inputs import MAKER_STATIONS
from scripts.analysis.maker_stage0_runio import theta_for_day
from scripts.analysis.maker_stage0_schedule import primary_schedule

REPO = Path(__file__).resolve().parents[3]
FIXTURE = REPO / "tests" / "fixtures" / "maker_parity" / "sharp_v1_parity.json.gz"
CALIBRATION = (
    REPO / "deploy" / "families" / "artefacts" / "nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json"
)
CALIBRATION_SHA256 = "9c0b6d6e66a587c1b4e14e5f95ff5cedb3c7195f62f8ad4238191fdd75923a5e"
#: sha256 of the committed fixture file; a re-extraction changes it and must change this line.
FIXTURE_SHA256 = "c5b5fe5704e445d6a6988d06d3703a7d41ec0d532b79df443f0faebb5d9350f4"

NS = 10**9
DELTAS_NS = (0, 600 * NS, -600 * NS)
SHARP = p.SHARP_V1
CLOCK_ENDS = frozenset({"GTD_EXPIRY", "CANCEL_PROCESS", "CANCEL_HARD"})
#: 09:00 local STANDARD time as UTC, by station (the hard cancel's wall clock)
HARD_CANCEL_UTC_HOUR = {"LAX": 17, "SFO": 17, "MDW": 15, "MIA": 14}
STD_OFFSET = {"LAX": -8, "SFO": -8, "MDW": -6, "MIA": -5}


@dataclass(frozen=True)
class Case:
    raw: dict[str, Any]
    events: tuple[Any, ...]
    rows: tuple[DerivedNbpRow, ...]

    @property
    def station(self) -> str:
        return str(self.raw["station"])

    @property
    def day(self) -> dt.date:
        return dt.date.fromisoformat(self.raw["day"])

    @property
    def instruments(self) -> list[str]:
        return list(self.raw["instruments"])


@pytest.fixture(scope="module")
def doc() -> dict[str, Any]:
    return fx.load_fixture(FIXTURE)


@pytest.fixture(scope="module")
def cases(doc: dict[str, Any]) -> dict[str, Case]:
    return {c["id"]: Case(c, fx.case_events(c), fx.case_rows(c)) for c in doc["cases"]}


@pytest.fixture(scope="module")
def calibration() -> LiveCalibration:
    return load_live_calibration(str(CALIBRATION), expected_sha256=CALIBRATION_SHA256)


def _case_ids() -> list[str]:
    try:
        return [c["id"] for c in fx.load_fixture(FIXTURE)["cases"]]
    except (OSError, ValueError, KeyError):
        return ["fixture-missing"]


# --- fixture hygiene ---------------------------------------------------------------------


def test_fixture_is_the_pinned_file_and_small() -> None:
    blob = FIXTURE.read_bytes()
    assert len(blob) < fx.MAX_FIXTURE_BYTES == 200_000
    assert hashlib.sha256(blob).hexdigest() == FIXTURE_SHA256


def test_fixture_respects_the_data_fence(doc: dict[str, Any], cases: dict[str, Case]) -> None:
    sealed = SEALED_DAY
    second_look = LAST_ALLOWED_DAY + dt.timedelta(days=1)
    second_look_ns = (
        int(dt.datetime.combine(second_look, dt.time(0), tzinfo=dt.UTC).timestamp()) * NS
    )
    assert doc["fence"] == {"last_allowed_day": "2026-10-13", "sealed_day": "2026-10-01"}
    for case in cases.values():
        assert case.station in MAKER_STATIONS
        assert case.day <= LAST_ALLOWED_DAY and case.day != sealed
        assert all(ev.ts_ns < second_look_ns for ev in case.events)
        assert all(r.available_at_ns < second_look_ns for r in case.rows)
        assert all(cut[0] < second_look_ns + 2 * 86_400 * NS for cut in case.raw["cuts"])
        assert "truth" not in case.raw and "settlement" not in case.raw


def test_fixture_covers_the_mechanical_criteria(cases: dict[str, Case]) -> None:
    by_station = {c.station for c in cases.values()}
    assert {"LAX", "SFO"} <= by_station
    assert any(c.station == "SFO" and "fill_day" in c.raw["roles"] for c in cases.values())
    late = [c for c in cases.values() if "late_listed" in c.raw["roles"]]
    assert late
    for case in late:  # the port's own listing test agrees with the census instant
        assert rule.listed_in_time(case.raw["first_seen_ns"], case.day) is False
        assert s_rule.listed_in_time(case.raw["first_seen_ns"], case.day) is False
    for case in cases.values():
        assert {int(k) for k in case.raw["expected"]} == set(DELTAS_NS)


# --- the 09:00 LST hard cancel (R10) -----------------------------------------------------


@pytest.mark.parametrize("station", sorted(HARD_CANCEL_UTC_HOUR))
def test_hard_cancel_matches_the_simulators_cut_for_every_station(station: str) -> None:
    for day in (dt.date(2026, 9, 18), dt.date(2026, 9, 21), dt.date(2026, 10, 13)):
        ported = rule.hard_cancel_ns(day, STD_OFFSET[station], SHARP)
        original = s_rule.hard_cancel_ns(day, STD_OFFSET[station])
        stamp = dt.datetime.fromtimestamp(ported / NS, tz=dt.UTC)
        assert ported == original
        assert (stamp.date(), stamp.hour, stamp.minute) == (day, HARD_CANCEL_UTC_HOUR[station], 0)


def test_fixture_clock_carries_the_ported_hard_cancel(cases: dict[str, Case]) -> None:
    seen: set[str] = set()
    for case in cases.values():
        hard = [c for c in case.raw["cuts"] if c[1] == "CANCEL_HARD"]
        assert len(hard) == 1
        offset = int(pno_store.site(case.station).offset_hours)
        assert offset == STD_OFFSET[case.station]
        assert hard[0][0] == rule.hard_cancel_ns(case.day, offset, SHARP)
        assert hard[0][2] is False
        seen.add(case.station)
    assert {"LAX", "SFO"} <= seen


def test_hard_cancel_is_after_the_permit_window_so_it_never_binds_the_expire(
    cases: dict[str, Case],
) -> None:
    """Finding, pinned: D 09:00 LST lies after the permit end (D 02:50Z) on every maker station.

    `gtd_expire_ns` is therefore min(permit end, next UTC midnight) for any booking inside the
    window, in the simulator and in the port alike.
    """
    for case in cases.values():
        sched = primary_schedule(case.day)
        hard = next(c[0] for c in case.raw["cuts"] if c[1] == "CANCEL_HARD")
        assert hard > sched.window_end_ns
        booked = sched.window_start_ns + 1
        assert rule.gtd_expire_ns(booked, hard, sched.window_end_ns) == (
            (booked // (86_400 * NS) + 1) * 86_400 * NS
        )


# --- the two runs ------------------------------------------------------------------------


class _Source:
    def __init__(self, root: Path) -> None:
        self._root = root

    def partition_path(self, cycle_date: dt.date, hour: int) -> Path:
        return partition_path(self._root, cycle_date, hour)

    def read_partition(self, path: Path) -> Sequence[DerivedNbpRow]:
        return read_partition(path)


def _write_nbp(case: Case, root: Path) -> None:
    by_cycle: dict[tuple[dt.date, int], list[DerivedNbpRow]] = {
        (dt.date.fromisoformat(d), int(h)): [] for d, h in case.raw["nbp"]["partitions"]
    }
    for row in case.rows:
        stamp = dt.datetime.fromtimestamp(row.cycle_runtime_ns // NS, tz=dt.UTC)
        by_cycle[(stamp.date(), stamp.hour)].append(row)
    for (date, hour), rows in by_cycle.items():
        write_partition(rows, partition_path(root, date, hour))


def _ladder(instruments: Sequence[str]) -> tuple[list[Rung], dict[str, float]]:
    rungs: list[Rung] = []
    edges: dict[str, float] = {}
    for instrument in instruments:
        facts = bucket_facts_from_instrument_id(instrument)
        assert facts is not None
        rungs.append(Rung(rung_id=instrument, lo=facts.lower_f, hi=facts.upper_f))
        edges[instrument] = float("-inf") if facts.lower_f is None else float(facts.lower_f)
    return rungs, edges


def _cuts(case: Case) -> list[CutSpec]:
    return [CutSpec(ts, reason, resume) for ts, reason, resume in case.raw["cuts"]]


def _data(case: Case) -> DataEvents:
    books = frozenset(
        e.payload.rung_id for e in case.events if isinstance(e.payload, s_events.DepthFrame)
    )
    return DataEvents(case.events, 0, books)


def _script_run(
    case: Case, delta_ns: int, root: Path, cal: LiveCalibration
) -> tuple[s_events.StationDayResult, list[s_events.ForecastVector]]:
    """The design driver's wiring (`_replay_arm`), at the given recorder offset."""
    arm = ARMS["sharp"]
    rungs, edges = _ladder(case.instruments)
    key = (case.station, case.day)
    store = s_pno.PNoStore.from_root(
        root, stations=[case.station], days=[case.day], calibration=cal, ladders={key: rungs}
    )
    shas = dict(sorted(store.consumed_cycles()))
    vectors: list[s_events.ForecastVector] = []
    for release in s_pno.release_instants(store, case.station, case.day, stress="none"):
        served = s_pno.classify_p_no(store, case.station, case.day, release + 1, stress="none")
        if isinstance(served, s_pno.AbstainReason):
            continue
        vectors.append(
            s_events.ForecastVector(
                available_at_ns=release,
                p_yes_point=served.p_yes_point_live,
                p_yes_upper={k: b.upper for k, b in served.bounds.items()},
                cycle_runtime_ns=served.vector.cycle_runtime_ns,
                raw_sha256=shas.get(served.vector.cycle_runtime_ns, ""),
                nbm_era=served.vector.model_version,
            )
        )
    tracker = s_adapter.WantTracker()
    picker = s_adapter.build_selector(
        s_adapter.SelectorConfig(
            store=store, station=case.station, day=case.day, stress="none", delta_ns=delta_ns,
            theta=case.raw["theta"], lower_edges_f=edges,
        ),
        tracker,
    )  # fmt: skip
    with rule_override(
        arm.b_cap, arm.max_rungs, p_min=arm.p_min, e_min=arm.e_min, b_floor=arm.b_floor
    ):
        replay = replay_station_day(
            _data(case), clock_events(_cuts(case), vectors), selector=picker, tracker=tracker,
            station=case.station, day=case.day, unit_hypothesis=case.raw["unit"],
            live_from_ns=case.raw["live_from_ns"], delta_ns=delta_ns,
        )  # fmt: skip
    return replay.result, vectors


def _to_port(ctx: s_events.DecisionContext) -> t.DecisionContext:
    books = {
        r: t.DepthFrame(rung_id=f.rung_id, ts_ns=f.ts_ns, yes_bids=f.yes_bids, yes_asks=f.yes_asks)
        for r, f in ctx.books.items()
    }
    return t.DecisionContext(now_ns=ctx.now_ns, books=books, live_bids=ctx.live_bids, held=ctx.held)


def _from_port(decision: t.Decision) -> s_events.Decision:
    return s_events.Decision(
        desired=tuple(s_events.Desired(d.rung_id, d.bid_cents) for d in decision.desired),
        drop_reason=decision.drop_reason,
        forecast_valid=decision.forecast_valid,
        dropped=dict(decision.dropped),
    )


def _port_run(
    case: Case,
    delta_ns: int,
    root: Path,
    cal: LiveCalibration,
    params: p.MakerRuleParams = SHARP,
) -> tuple[s_events.StationDayResult, list[s_events.ForecastVector], list[CutSpec]]:
    """The ported package only: nothing in `maker_stage0_rule`/`_adapter`/`_pno` is consulted."""
    rungs, edges = _ladder(case.instruments)
    key = (case.station, case.day)
    store = pno.PNoStore.from_source(
        _Source(root), stations=[case.station], days=[case.day], calibration=cal,
        ladders={key: rungs},
    )  # fmt: skip
    shas = dict(sorted(store.consumed_cycles()))
    vectors: list[s_events.ForecastVector] = []
    for release in pno.release_instants(store, case.station, case.day, stress="none"):
        served = pno.classify_p_no(
            store, case.station, case.day, release + 1, stress="none", stale_h=params.stale_h
        )
        if isinstance(served, pno.AbstainReason):
            continue
        vectors.append(
            s_events.ForecastVector(
                available_at_ns=release,
                p_yes_point=served.p_yes_point_live,
                p_yes_upper={k: b.upper for k, b in served.bounds.items()},
                cycle_runtime_ns=served.vector.cycle_runtime_ns,
                raw_sha256=shas.get(served.vector.cycle_runtime_ns, ""),
                nbm_era=served.vector.model_version,
            )
        )
    tracker = selector.WantTracker()
    ported = selector.build_selector(
        selector.SelectorConfig(
            store=store, station=case.station, day=case.day, stress="none", delta_ns=delta_ns,
            theta=case.raw["theta"], lower_edges_f=edges, params=params,
        ),
        tracker,
    )  # fmt: skip

    def picker(ctx: s_events.DecisionContext, /) -> s_events.Decision:
        return _from_port(ported(_to_port(ctx)))

    sched = primary_schedule(case.day)
    offset = int(pno_store.site(case.station).offset_hours)
    cuts = [
        CutSpec(c.instant_ns, *reason)
        for c, reason in zip(
            sched.cuts,
            (("GTD_EXPIRY", True), ("CANCEL_PROCESS", False), ("CANCEL_PROCESS", False)),
            strict=True,
        )
    ]
    cuts.append(CutSpec(rule.hard_cancel_ns(case.day, offset, params), "CANCEL_HARD", False))
    events = merge_events(_data(case), clock_events(cuts, vectors))
    result = simulate_station_day(
        events, picker, station=case.station, climate_day=case.day.isoformat(),
        unit_hypothesis=case.raw["unit"], live_from_ns=case.raw["live_from_ns"],
        delta_ns=delta_ns, max_rungs=params.max_rungs,
    )  # fmt: skip
    return result, vectors, cuts


def _rows(case: Case, episodes: Sequence[s_events.Episode]) -> list[list[Any]]:
    index = {r: i for i, r in enumerate(case.instruments)}
    return [
        [e.t0_ns, index[e.rung_id], e.bid_cents, e.end_ns, e.end_reason, e.refused_reason,
         e.filled_ns_base, e.filled_ns_stress]
        for e in episodes
    ]  # fmt: skip


def _posted(rows: Sequence[Sequence[Any]]) -> list[tuple[int, int, int]]:
    return [(r[0], r[1], r[2]) for r in rows if r[5] is None]


# --- parity ------------------------------------------------------------------------------


@pytest.mark.parametrize("delta_ns", DELTAS_NS, ids=lambda d: f"delta{d // NS:+d}s")
@pytest.mark.parametrize("case_id", _case_ids())
def test_port_posts_exactly_what_the_driver_posts(
    case_id: str,
    delta_ns: int,
    cases: dict[str, Case],
    calibration: LiveCalibration,
    tmp_path: Path,
) -> None:
    case = cases[case_id]
    assert case.raw["theta"] == theta_for_day(case.day)
    _write_nbp(case, tmp_path / "nbp")
    expected = case.raw["expected"][str(delta_ns)]
    assert _posted(expected), "a fixture with nothing posted proves nothing"

    script, script_vectors = _script_run(case, delta_ns, tmp_path / "nbp", calibration)
    port, port_vectors, port_cuts = _port_run(case, delta_ns, tmp_path / "nbp", calibration)

    assert _rows(case, script.episodes) == expected  # the fixture still is the driver's output
    assert port_cuts == _cuts(case)
    assert port_vectors == script_vectors
    assert _posted(_rows(case, port.episodes)) == _posted(expected)  # (t0, rung, price)
    assert _rows(case, port.episodes) == expected
    assert [e.to_dict() for e in port.episodes] == [e.to_dict() for e in script.episodes]
    assert port.summary == script.summary

    shift = abs(delta_ns)
    permit_end = primary_schedule(case.day).window_end_ns
    hard = rule.hard_cancel_ns(case.day, int(pno_store.site(case.station).offset_hours), SHARP)
    for ep in port.episodes:
        if ep.refused_reason is not None:
            continue
        expire = rule.gtd_expire_ns(ep.t0_ns + shift, hard, permit_end)
        if ep.end_reason in CLOCK_ENDS:
            assert ep.end_ns + shift == expire, "clock-cut consistency (not hard-cancel parity)"
        else:
            assert ep.end_ns + shift <= expire, "clock-cut consistency (not hard-cancel parity)"


@pytest.mark.parametrize("case_id", _case_ids())
def test_the_parity_check_is_sensitive_to_the_rule_params(
    case_id: str, cases: dict[str, Case], calibration: LiveCalibration, tmp_path: Path
) -> None:
    """Not vacuous: a one-notch change of B_CAP or MAX_RUNGS makes the port diverge."""
    case = cases[case_id]
    _write_nbp(case, tmp_path / "nbp")
    expected = case.raw["expected"]["0"]
    diverged = {}
    for name, over in (("b_cap", {"b_cap": 0.85}), ("max_rungs", {"max_rungs": 1})):
        params = dataclasses.replace(SHARP, **over)
        result, _, _ = _port_run(case, 0, tmp_path / "nbp", calibration, params)
        diverged[name] = _rows(case, result.episodes) != expected
    assert diverged["b_cap"] or diverged["max_rungs"]
    assert diverged["b_cap"], diverged


@pytest.mark.parametrize("station", sorted(HARD_CANCEL_UTC_HOUR))
def test_hard_cancel_binds_the_expire_when_the_window_reaches_it(station: str) -> None:
    """Synthetic: no midnight or permit cut before D 09:00 LST, so the min IS the hard cancel.

    The simulator is driven with `maker_stage0_rule.hard_cancel_ns` as its CANCEL_HARD cut; the
    port's `hard_cancel_ns` and `gtd_expire_ns` must name the same instant and the rest must end
    there with reason CANCEL_HARD.
    """
    day = dt.date(2026, 9, 21)
    offset = STD_OFFSET[station]
    sim_hard = s_rule.hard_cancel_ns(day, offset)
    port_hard = rule.hard_cancel_ns(day, offset, SHARP)
    assert sim_hard == port_hard
    rung = "r"
    first = sim_hard - 3_600 * NS

    def frame(ts: int, seq: int) -> s_events.Event:
        body = s_events.DepthFrame(
            rung_id=rung, ts_ns=ts, yes_bids=((25, 10),), yes_asks=((30, 10),)
        )
        return s_events.Event(ts, s_events.Kind.DEPTH, seq, body)

    def picker(ctx: s_events.DecisionContext, /) -> s_events.Decision:
        return s_events.Decision(desired=(s_events.Desired(rung, 70),), forecast_valid=True)

    vec = s_events.ForecastVector(first - 10 * NS, {rung: 0.01}, {rung: 0.02}, 0, "", "v5.0")
    clock = clock_events([CutSpec(port_hard, "CANCEL_HARD", False)], [vec])
    data = DataEvents((frame(first, 0), frame(first + 60 * NS, 1)), 0, frozenset({rung}))
    result = simulate_station_day(
        merge_events(data, clock), picker, station=station, climate_day=day.isoformat(),
        unit_hypothesis="CONTRACTS", live_from_ns=first - 20 * NS, max_rungs=SHARP.max_rungs,
    )  # fmt: skip
    posted = [e for e in result.episodes if e.refused_reason is None]
    assert posted
    permit_end = sim_hard + 10 * 3_600 * NS  # a window long enough to reach the hard cancel
    for ep in posted:
        assert ep.end_reason == "CANCEL_HARD"
        assert ep.end_ns == port_hard == rule.gtd_expire_ns(ep.t0_ns, port_hard, permit_end)
