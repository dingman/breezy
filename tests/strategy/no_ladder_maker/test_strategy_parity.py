"""ARM C2: the live STRATEGY posts exactly what the design driver posts (sharp arm, Delta = 0).

C3 (``test_parity_vs_design_driver``) proved the ported decision CORE equals the driver. This
replays the same C3 fixture through the real ``NoLadderMakerStrategy`` -- real selector over a real
``LiveNbpFeed`` store, real native GTD timers, real ``plan_actions`` -- and holds the orders it
puts on the wire to the fixture's stored driver episodes: ``(t0, rung, price)`` of every posted
rest, and the GTD expire of each rest whose end is a clock cut.

What drives it (no new harness, no production seam): the fixture's recorded events are fed to the
strategy's own handlers in simulator order on a ``TestClock`` -- ``OrderBookDepth10`` for every
depth frame, ``ForecastPoint`` for every pinned NBP row at its availability instant (rows available
before the window opens are replayed at boot), and the driver's own fill instants. The venue is a
double that acknowledges instantly (``FakeVenue``). A Nautilus ``BacktestEngine`` run was not
used: it would need the fixture re-encoded as catalog Depth10 and ForecastPoint data plus a matching
engine, and the simulator's fills (queue position from prints) are not an engine behaviour -- the
fills here are the driver's, injected at their recorded instants.

Documented, conservative departure the replay could expose: the live book cannot tell "exactly ten
ask levels" from "ten displayed, more beyond", so a rest whose NO level lies past the deepest of
ten displayed ask levels is refused (``TRUNCATED_FRAME``) where the recorder knew the truth.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pytest
from nautilus_trader.model.identifiers import InstrumentId

from breezy.adapters.polymarket_us.symbology import sibling_instrument_id
from breezy.domain.forecast_point import ForecastPoint
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import (
    LiveCalibration,
    load_live_calibration,
)
from breezy.strategy.no_ladder_maker.ladder_state import frame_from_levels
from scripts.analysis import maker_parity_fixture_extract as fx
from scripts.analysis import maker_stage0_fill_events as s_events
from tests.strategy.no_ladder_maker.maker_strategy_support import FakeVenue, Harness, depth

REPO: Final[Path] = Path(__file__).resolve().parents[3]
FIXTURE: Final[Path] = REPO / "tests" / "fixtures" / "maker_parity" / "sharp_v1_parity.json.gz"
CALIBRATION: Final[Path] = (
    REPO / "deploy" / "families" / "artefacts" / "nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json"
)
CALIBRATION_SHA256: Final[str] = "9c0b6d6e66a587c1b4e14e5f95ff5cedb3c7195f62f8ad4238191fdd75923a5e"
NS: Final[int] = 10**9
CLOCK_ENDS: Final = frozenset({"GTD_EXPIRY", "CANCEL_PROCESS"})
# timeline ranks at equal ts (simulator Kind order): fills (prints) < depth < forecast release
_FILL, _DEPTH, _NBP = 0, 1, 2


def _case_ids() -> list[str]:
    try:
        return [c["id"] for c in fx.load_fixture(FIXTURE)["cases"]]
    except (OSError, ValueError, KeyError):
        return ["fixture-missing"]


@pytest.fixture(scope="module")
def doc() -> dict[str, Any]:
    return fx.load_fixture(FIXTURE)


@pytest.fixture(scope="module")
def calibration() -> LiveCalibration:
    return load_live_calibration(str(CALIBRATION), expected_sha256=CALIBRATION_SHA256)


def _depth_10(frame: s_events.DepthFrame, yes: InstrumentId) -> Any:
    def side(levels: tuple[tuple[int, int], ...], *, descending: bool) -> list[tuple[str, int]]:
        ordered = sorted(levels, reverse=descending)
        return [(f"{price / 100:.2f}", size) for price, size in ordered]

    return depth(
        yes,
        ts_ns=frame.ts_ns,
        bids=side(frame.yes_bids, descending=True),
        asks=side(frame.yes_asks, descending=False),
    )


def _forecast_point(row: Any) -> ForecastPoint:
    return ForecastPoint(
        station=row.station,
        model="NBM_NBP",
        model_version=row.nbm_version_era.removeprefix("v"),
        variable=row.variable,
        cycle_runtime_ns=row.cycle_runtime_ns,
        valid_start_ns=row.valid_start_ns,
        valid_end_ns=row.valid_end_ns,
        value_f=row.value_f,
        issuance_seq=0,
        measured_publication_lag_ns=row.available_at_ns - row.cycle_runtime_ns,
        available_at_ns=row.available_at_ns,
        ingested_at_ns=row.available_at_ns,
    )


def _timeline(case: dict[str, Any], events: Any, rows: Any, start_ns: int) -> list[tuple[Any, ...]]:
    """Everything that happens once the window is open, in simulator order."""
    timeline: list[tuple[Any, ...]] = []
    for event in events:
        if isinstance(event.payload, s_events.DepthFrame) and event.ts_ns >= start_ns:
            timeline.append((event.ts_ns, _DEPTH, len(timeline), event.payload))
    for row in rows:
        if row.available_at_ns >= start_ns:
            timeline.append((row.available_at_ns, _NBP, len(timeline), row))
    for ep in case["expected"]["0"]:
        if ep[6] is not None:  # the driver's fill instant for this rung (injected, not simulated)
            timeline.append((ep[6], _FILL, len(timeline), case["instruments"][ep[1]]))
    return sorted(timeline, key=lambda item: item[:3])


def _boot_state(h: Harness, events: Any, rows: Any, start_ns: int) -> None:
    """What the node already knows when the window opens: the last book of each rung and every
    vector published before it. Applied without a decision, as the simulator does (its first
    decision is the first event at or after the window start)."""
    ladder = h.ladder
    last: dict[str, s_events.DepthFrame] = {}
    for event in events:
        if isinstance(event.payload, s_events.DepthFrame) and event.ts_ns < start_ns:
            last[event.payload.rung_id] = event.payload
    for rung_id, frame in last.items():
        ladder.books[rung_id] = frame_from_levels(
            rung_id,
            frame.ts_ns,
            [_Level(p / 100, s) for p, s in frame.yes_bids],
            [_Level(p / 100, s) for p, s in frame.yes_asks],
        )
    for row in rows:
        if row.available_at_ns < start_ns:
            h.strategy._feed.push(_forecast_point(row), arrival_ns=start_ns)


@dataclass(frozen=True)
class _Level:
    price: float
    size: int


def _replay(case: dict[str, Any], calibration: LiveCalibration) -> tuple[Harness, FakeVenue]:
    events, rows = fx.case_events(case), fx.case_rows(case)
    yes_ids = [InstrumentId.from_str(i) for i in case["instruments"]]
    start = case["live_from_ns"]
    h = Harness(
        stations=(case["station"],),
        instrument_ids=yes_ids,
        now_ns=start,
        day=dt.date.fromisoformat(case["day"]),
        permit_expires_at_ns=case["permit_end_ns"],
        calibration=calibration,
        theta=case["theta"],
    )
    venue = FakeVenue(h)
    by_id = {str(i): i for i in yes_ids}
    _boot_state(h, events, rows, start)
    for ts, rank, _seq, payload in _timeline(case, events, rows, start):
        h.advance_to(ts)
        venue.pump()
        if rank == _DEPTH:
            h.strategy.on_order_book_depth(_depth_10(payload, by_id[payload.rung_id]))
        elif rank == _NBP:
            h.strategy.on_data(_forecast_point(payload))
            h.advance_to(ts + 1)  # the 1 ns NBP release alert
        else:
            assert venue.fill_open(sibling_instrument_id(by_id[payload])), "a fill needs a rest"
        venue.pump()
    h.advance_to(case["permit_end_ns"] + 1)
    venue.pump()
    return h, venue


def _expected_posts(case: dict[str, Any]) -> list[tuple[int, int, int]]:
    return sorted((r[0], r[1], r[2]) for r in case["expected"]["0"] if r[5] is None)


def _actual_posts(case: dict[str, Any], venue: FakeVenue) -> list[tuple[int, int, int]]:
    index = {
        str(sibling_instrument_id(InstrumentId.from_str(i))): n
        for n, i in enumerate(case["instruments"])
    }
    return sorted((t0, index[no], cents) for t0, no, cents, _ in venue.posts)


@pytest.mark.parametrize("case_id", _case_ids())
def test_the_strategy_posts_exactly_the_drivers_rests_at_delta_zero(
    case_id: str, doc: dict[str, Any], calibration: LiveCalibration
) -> None:
    case = next(c for c in doc["cases"] if c["id"] == case_id)
    expected = _expected_posts(case)
    assert expected, "a fixture with nothing posted proves nothing"
    _h, venue = _replay(case, calibration)
    assert _actual_posts(case, venue) == expected


@pytest.mark.parametrize("case_id", _case_ids())
def test_each_rests_gtd_expire_is_the_drivers_clock_cut(
    case_id: str, doc: dict[str, Any], calibration: LiveCalibration
) -> None:
    case = next(c for c in doc["cases"] if c["id"] == case_id)
    _h, venue = _replay(case, calibration)
    index = {
        str(sibling_instrument_id(InstrumentId.from_str(i))): n
        for n, i in enumerate(case["instruments"])
    }
    expires = {(t0, index[no], cents): expire for t0, no, cents, expire in venue.posts}
    checked = 0
    for ep in case["expected"]["0"]:
        if ep[5] is None and ep[4] in CLOCK_ENDS:
            assert expires[(ep[0], ep[1], ep[2])] == ep[3], ep
            checked += 1
    assert checked >= 1, "no clock-cut episode in the fixture: the expire check proved nothing"


@pytest.mark.parametrize("case_id", _case_ids())
def test_nothing_rests_after_the_permit_window_closes(
    case_id: str, doc: dict[str, Any], calibration: LiveCalibration
) -> None:
    case = next(c for c in doc["cases"] if c["id"] == case_id)
    _h, venue = _replay(case, calibration)
    assert venue.unfiltered_open_orders() == []
    assert max(expire for *_, expire in venue.posts) <= case["permit_end_ns"]
    assert all(t0 < case["permit_end_ns"] for t0, *_ in venue.posts)
