"""ARM D1 producer: durable fills + settlement truth -> ``derived/maker-loss-stop/latest.json``.

Fixture-only (R6): a throwaway exec-state sqlite, an injected CLI-final reader, a venue-settlement
file. No network, no catalog, no node. The last block drives the REAL ``LossStopProbe``.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest

from breezy.adapters.polymarket_us.exec.client import FILL_KEY_PREFIX, DurableFillRecord
from breezy.domain.weather_bucket_facts import WeatherBucketFacts
from breezy.runtime.health import LoggingAlertSink
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import (
    CURRENT_INTENT_KEY,
    SubmitIntent,
    SubmitIntentState,
)
from breezy.strategy.forecast_quantile_ladder import loss_stop_probe as lsp
from breezy.strategy.forecast_quantile_ladder.loss_stop_probe import LossStopProbe
from breezy.strategy.no_ladder_maker import harm_stop as hsm
from breezy.strategy.no_ladder_maker import venue_settlement
from breezy.strategy.no_ladder_maker.cli_final import registry_std_offset_hours
from breezy.strategy.no_ladder_maker.harm_stop import maker_loss_stop_artefact_path
from breezy.strategy.no_ladder_maker.venue_settlement import VENUE_SCHEMA
from scripts.analysis import maker_loss_stop_producer as producer

NOW: Final = datetime(2026, 10, 25, 12, 40, tzinfo=UTC)
STATIONS: Final = frozenset({"nyc"})
#: ``lt79f`` is "tmax <= 78": a NO leg wins at 85 and loses at 70
HIGH_TMAX, LOW_TMAX = 85, 70


def _slug(day: int, city: str = "nyc") -> str:
    return f"tc-temp-{city}high-2026-09-{day:02d}-lt79f"


def _record(
    day: int,
    *,
    order: str | None = None,
    city: str = "nyc",
    trade_id: str | None = None,
    bid: str = "0.86",
    qty: str = "1",
    leg: str = "^no",
    ts_event: int | None = None,
) -> DurableFillRecord:
    oid = order or f"ORD-{city}-{day}"
    return DurableFillRecord(
        venue_order_id=oid,
        client_order_id=f"O-{oid}",
        instrument_id=f"{_slug(day, city)}{leg}.POLYMARKET_US",
        order_side="BUY",
        cumulative_qty=Decimal(qty),
        cumulative_cost=Decimal(bid) * Decimal(qty),
        cumulative_fee=Decimal("0.01"),
        fee_reconciled=True,
        ts_event=1_790_000_000_000_000_000 + day if ts_event is None else ts_event,
        venue_fee_raw="0.01",
        trade_id=trade_id or f"POLL-{oid}",
        order_qty=Decimal(qty),
    )


class _World:
    """A throwaway exec state, venue-settlement file and CLI finals."""

    def __init__(self, tmp: Path) -> None:
        self.db = tmp / "state" / "exec.sqlite"
        self.db.parent.mkdir()
        self.store = SqliteStateStore(self.db)
        self.derived = tmp / "derived" / "maker-loss-stop"
        self.venue_path = tmp / "venue_settlements.json"
        self.venue: dict[str, bool] = {}
        self.cli: dict[tuple[str, str], int] = {}
        self.offset: float | None = -5.0

    def fill(self, record: DurableFillRecord) -> None:
        self.store.set(f"{FILL_KEY_PREFIX}{record.venue_order_id}", record.to_bytes())

    def settle(self, day: int, *, yes: bool, tmax: int | None, city: str = "nyc") -> None:
        self.venue[_slug(day, city)] = yes
        if tmax is not None:
            self.cli[(city.upper(), f"2026-09-{day:02d}")] = tmax

    def win(self, day: int) -> None:
        self.fill(_record(day))
        self.settle(day, yes=False, tmax=HIGH_TMAX)

    def lose(self, day: int, *, order: str | None = None, bid: str = "0.86") -> None:
        self.fill(_record(day, order=order, bid=bid))
        self.settle(day, yes=True, tmax=LOW_TMAX)

    def cli_reader(self, facts: WeatherBucketFacts) -> int | None:
        return self.cli.get((facts.settlement_station, facts.climate_day.isoformat()))

    def write_venue(self, fetched_at: datetime, *, complete: bool = True) -> None:
        """The collector's file: by default complete and fetched ``fetched_at``."""
        body = {
            "schema": VENUE_SCHEMA,
            "source": "activities",
            "fetched_at": fetched_at.isoformat().replace("+00:00", "Z"),
            "complete": complete,
            "yes_resolved": self.venue,
        }
        self.venue_path.write_text(json.dumps(body))

    def run(
        self,
        *,
        now: datetime = NOW,
        stations: frozenset[str] = STATIONS,
        fetched_at: datetime | None = None,
        complete: bool = True,
        write_file: bool = True,
        get_fill_not_before_ns: int | None = None,
    ) -> producer.Outcome:
        if write_file:
            self.write_venue(fetched_at or now, complete=complete)
        kwargs: dict[str, Any] = {}
        if get_fill_not_before_ns is not None:
            kwargs["get_fill_not_before_ns"] = get_fill_not_before_ns
        return producer.produce(
            state_db=self.db,
            derived_dir=self.derived,
            venue_settlements=self.venue_path,
            family_stations=stations,
            cli_reading=self.cli_reader,
            now=now,
            std_offset_hours=lambda station: self.offset,
            **kwargs,
        )

    def artefact(self) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads((self.derived / "latest.json").read_text())
        return loaded


@pytest.fixture
def world(tmp_path: Path) -> _World:
    return _World(tmp_path)


def test_zero_fills_writes_pass(world: _World) -> None:
    outcome = world.run()
    assert outcome.result.verdict.value == "PASS"
    body = world.artefact()
    assert body["schema"] == lsp.SCHEMA and body["verdict"] == "PASS"
    assert body["counts"] == {
        "fills": 0,
        "wins": 0,
        "losses": 0,
        "n": 0,
        "unresolved": 0,
        "pending": 0,
    }
    assert body["triggers"] == []


def test_the_artefact_is_in_the_probes_exact_format(world: _World) -> None:
    world.win(1)
    world.run()
    body = world.artefact()
    assert body["as_of"] == "2026-10-25T12:40:00Z"
    assert body["digest"] == lsp.compute_digest(
        verdict=body["verdict"],
        as_of=body["as_of"],
        c2_hwm=body["c2_hwm"],
        truth_sha=body["truth_sha"],
    )
    path = world.derived / "latest.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not stat.S_IMODE(path.parent.stat().st_mode) & (stat.S_IWGRP | stat.S_IWOTH)
    assert path.stat().st_mtime == pytest.approx(NOW.timestamp(), abs=1)
    assert [p.name for p in path.parent.iterdir()] == ["latest.json"], "no temp file left behind"


def test_wins_only_pass_with_counts(world: _World) -> None:
    for d in (1, 2, 3, 4):
        world.win(d)
    assert world.run().result.verdict.value == "PASS"
    assert world.artefact()["counts"]["wins"] == 4


def test_the_third_distinct_station_day_loss_fails_t1(world: _World) -> None:
    for d in (1, 2):
        world.lose(d)
    world.win(5)
    assert "T1" not in world.run(now=NOW - timedelta(days=1)).result.triggers
    (
        world.derived / "latest.json"
    ).unlink()  # the interim T2 FAIL is sticky; start the next look clean
    world.lose(3)
    world.run()
    body = world.artefact()
    assert body["verdict"] == "FAIL" and "T1" in body["triggers"]
    assert body["counts"]["losses"] == 3


def test_two_legs_on_one_station_day_lose_once(world: _World) -> None:
    world.lose(1)
    world.lose(1, order="ORD-second-leg")
    world.lose(2)
    world.win(3)
    world.run()
    body = world.artefact()
    assert body["counts"]["losses"] == 2
    assert "T1" not in body["triggers"]


def test_t2_fails_on_the_cp_bound_at_n_3(world: _World) -> None:
    world.win(1)
    world.lose(2, bid="0.86")
    world.lose(3, bid="0.86")
    world.run()
    body = world.artefact()
    # cost = 0.86 + max(0.01, 0.01) = 0.87 > the n=3, W=1 upper bound 0.86465
    assert body["verdict"] == "FAIL" and body["triggers"] == ["T2"]


def test_t3_fails_on_cumulative_pnl(world: _World) -> None:
    for d in (1, 2):
        world.win(d)
    for d in (3, 4):
        world.lose(d, bid="0.86")
    world.run()
    assert world.artefact()["triggers"] == ["T3"]


def test_a_missing_venue_settlement_counts_as_a_loss(world: _World) -> None:
    for d in (1, 2, 3):
        world.fill(_record(d))  # no venue settlement, no CLI final
    outcome = world.run()
    assert outcome.result.unresolved == 3
    assert world.artefact()["verdict"] == "FAIL"
    assert "T1" in world.artefact()["triggers"]


def test_a_missing_cli_final_counts_as_a_loss(world: _World) -> None:
    for d in (1, 2, 3):
        world.fill(_record(d))
        world.settle(d, yes=False, tmax=None)
    assert world.run().result.unresolved == 3


def test_a_venue_cli_mismatch_counts_as_a_loss_even_when_the_venue_says_win(world: _World) -> None:
    for d in (1, 2, 3):
        world.fill(_record(d))
        world.settle(d, yes=False, tmax=LOW_TMAX)  # CLI says the rung hit; venue says it did not
    assert world.run().result.unresolved == 3


def test_a_qty_not_1_fill_is_a_loss(world: _World) -> None:
    for d in (1, 2, 3):
        world.fill(_record(d, qty="2"))
        world.settle(d, yes=False, tmax=HIGH_TMAX)
    assert world.run().result.losses == 3


def test_a_yes_leg_maker_fill_is_not_scored_as_a_win(world: _World) -> None:
    for d in (1, 2, 3):
        world.fill(_record(d, leg=""))
        world.settle(d, yes=False, tmax=HIGH_TMAX)
    assert world.run().result.unresolved == 3


def test_a_get_fill_holds_and_removes_a_stale_pass(world: _World) -> None:
    world.win(1)
    assert world.run().result.verdict.value == "PASS"
    assert (world.derived / "latest.json").exists()
    world.fill(_record(2, trade_id="GET-ORD-nyc-2"))
    outcome = world.run()
    assert outcome.result.verdict.value == "HOLD"
    assert outcome.action == "removed"
    assert not (world.derived / "latest.json").exists(), "HOLD must not leave a PASS standing"


def test_an_open_ambiguous_family_intent_holds(world: _World) -> None:
    world.win(1)
    intent = SubmitIntent(
        intent_id="a" * 32,
        fingerprint="b" * 64,
        created_ns=1,
        state=SubmitIntentState.OPEN,
        retired_ns=None,
        retirement_reason=None,
        slug=_slug(2),
    )
    world.store.set(CURRENT_INTENT_KEY, intent.to_bytes())
    outcome = world.run()
    assert outcome.result.verdict.value == "HOLD"
    assert "open_ambiguous_family_intent" in outcome.result.hold_reasons


def test_an_out_of_family_open_intent_does_not_hold(world: _World) -> None:
    world.win(1)
    intent = SubmitIntent(
        intent_id="a" * 32,
        fingerprint="b" * 64,
        created_ns=1,
        state=SubmitIntentState.OPEN,
        retired_ns=None,
        retirement_reason=None,
        slug=_slug(2, "lax"),
    )
    world.store.set(CURRENT_INTENT_KEY, intent.to_bytes())
    assert world.run().result.verdict.value == "PASS"


def test_an_open_intent_without_a_slug_cannot_be_attributed_and_holds(world: _World) -> None:
    world.win(1)
    intent = SubmitIntent(
        intent_id="a" * 32,
        fingerprint="b" * 64,
        created_ns=1,
        state=SubmitIntentState.OPEN,
        retired_ns=None,
        retirement_reason=None,
    )
    world.store.set(CURRENT_INTENT_KEY, intent.to_bytes())
    assert world.run().result.verdict.value == "HOLD"


def test_an_unreadable_state_db_holds(world: _World, tmp_path: Path) -> None:
    outcome = producer.produce(
        state_db=tmp_path / "absent.sqlite",
        derived_dir=world.derived,
        venue_settlements=world.venue_path,
        family_stations=STATIONS,
        cli_reading=world.cli_reader,
        now=NOW,
    )
    assert outcome.result.verdict.value == "HOLD"
    assert "state_db_unreadable" in outcome.result.hold_reasons


def test_a_corrupt_fill_record_holds(world: _World) -> None:
    world.store.set(f"{FILL_KEY_PREFIX}BAD", b"{not json")
    assert "fill_record_corrupt" in world.run().result.hold_reasons


def test_other_families_fills_and_stations_are_ignored(world: _World) -> None:
    world.fill(_record(1, city="lax", trade_id="GET-x"))
    world.fill(_record(1, city="lax"))  # a POLL fill on an out-of-family station
    world.fill(_record(2, trade_id="7d9a1c52-0000-4000-8000-000000000001"))  # create-path (taker)
    outcome = world.run()
    assert outcome.result.verdict.value == "PASS" and outcome.result.fills == 0


def test_no_state_db_write_and_no_fee_reconciled_filter(world: _World) -> None:
    unreconciled = _record(1)
    object.__setattr__(unreconciled, "fee_reconciled", False)
    world.fill(unreconciled)
    world.settle(1, yes=True, tmax=LOW_TMAX)
    before = world.db.read_bytes()
    assert world.run().result.fills == 1, "an unreconciled fill is still scored"
    assert world.db.read_bytes() == before, "the producer reads the state DB read-only"


def test_a_fail_is_sticky_and_a_later_pass_never_overwrites_it(world: _World) -> None:
    for d in (1, 2, 3):
        world.lose(d)
    world.run()
    assert world.artefact()["verdict"] == "FAIL"
    # the losses are later 'resolved' as wins (e.g. a corrected settlement): still FAIL
    for d in (1, 2, 3):
        world.settle(d, yes=False, tmax=HIGH_TMAX)
    later = world.run(now=NOW + timedelta(days=1))
    assert later.action == "sticky_fail_kept"
    assert world.artefact()["verdict"] == "FAIL"
    assert world.artefact()["as_of"] == "2026-10-25T12:40:00Z"


def test_a_hold_never_removes_a_fail(world: _World) -> None:
    for d in (1, 2, 3):
        world.lose(d)
    world.run()
    world.fill(_record(9, trade_id="GET-ORD-nyc-9"))
    assert world.run().action == "sticky_fail_kept"
    assert world.artefact()["verdict"] == "FAIL"


def test_the_cost_in_the_verdict_is_d5s_with_slip_zero(world: _World) -> None:
    world.win(1)
    outcome = world.run()
    # posted 0.86 + max(booked 0.01, modelled 0.01) = 0.87
    assert outcome.result.w_star == Decimal("0.87")


# -- LossStopProbe consumes the artefact exactly as the FQ file ------------------------------------


def _probe(path: Path, clock: datetime) -> LossStopProbe:
    return LossStopProbe(
        path=path,
        clock=lambda: clock,
        set_family_halted=lambda reason, evidence: None,
        alert_sink=LoggingAlertSink(),
        alert_every_probe=lambda: False,
        expected_uid=os.getuid(),
    )


def _veto(world: _World, *, at: datetime) -> str | None:
    probe = _probe(maker_loss_stop_artefact_path(world.derived.parents[1] / "catalog"), at)
    probe.probe_once()
    return probe.veto_reason()


def test_the_artefact_path_is_derived_maker_loss_stop_latest_json(tmp_path: Path) -> None:
    assert maker_loss_stop_artefact_path(tmp_path / "catalog") == (
        tmp_path / "derived" / "maker-loss-stop" / "latest.json"
    )


def test_a_pass_file_lets_the_probe_through(world: _World) -> None:
    world.win(1)
    world.run()
    assert _veto(world, at=NOW + timedelta(minutes=5)) is None


def test_a_fail_file_makes_the_probe_veto(world: _World) -> None:
    for d in (1, 2, 3):
        world.lose(d)
    world.run()
    assert _veto(world, at=NOW + timedelta(minutes=5)) == lsp.REASON_FAIL


def test_an_absent_file_vetoes(world: _World) -> None:
    assert _veto(world, at=NOW) == lsp.REASON_UNKNOWN


def test_a_hold_vetoes_because_it_leaves_no_file(world: _World) -> None:
    world.win(1)
    world.run()
    world.fill(_record(2, trade_id="GET-ORD-nyc-2"))
    world.run()
    assert _veto(world, at=NOW + timedelta(minutes=5)) == lsp.REASON_UNKNOWN


@pytest.mark.parametrize("hours", [27, 40, 200])
def test_a_stale_file_vetoes(world: _World, hours: int) -> None:
    world.win(1)
    world.run()
    assert _veto(world, at=NOW + timedelta(hours=hours)) == lsp.REASON_STALE


def test_a_forged_digest_vetoes(world: _World) -> None:
    world.win(1)
    world.run()
    path = world.derived / "latest.json"
    body = json.loads(path.read_text())
    body["verdict"] = "PASS" if body["verdict"] != "PASS" else "FAIL"
    path.write_text(json.dumps(body))
    assert _veto(world, at=NOW) == lsp.REASON_UNKNOWN


def test_main_maps_the_verdict_to_the_exit_code_and_prints_one_json_line(
    world: _World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(producer, "catalog_cli_reader", lambda base: world.cli_reader)
    world.win(1)
    world.write_venue(datetime.now(tz=UTC))
    argv = [
        "--station", "nyc",
        "--state-db", str(world.db),
        "--catalog-root", str(world.derived.parents[1] / "catalog"),
        "--venue-settlements", str(world.venue_path),
    ]  # fmt: skip
    assert producer.main(argv) == producer.EXIT_PASS
    printed = json.loads(capsys.readouterr().out)
    assert printed["verdict"] == "PASS" and printed["action"] == "written"
    floor = producer.family_get_fill_floor_ns(producer.DEFAULT_FAMILY_MANIFEST)
    world.fill(_record(2, trade_id="GET-ORD-nyc-2", ts_event=floor))
    assert producer.main(argv) == producer.EXIT_HOLD
    for d in (3, 4, 5):
        world.lose(d)
    world.write_venue(datetime.now(tz=UTC))
    assert producer.main(argv) == producer.EXIT_FAIL


def test_main_requires_a_state_db(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(producer.STATE_DB_ENV, raising=False)
    assert producer.main(["--station", "nyc"]) == producer.EXIT_ERROR
    assert producer.STATE_DB_ENV in capsys.readouterr().err


# -- review K5: the cost fallback books the modelled fee too -------------------------------------


def test_k5_an_unusable_quantity_books_at_least_the_modelled_minimum_fee() -> None:
    zero = _record(1, qty="0", bid="0.86")
    object.__setattr__(zero, "cumulative_cost", Decimal("0.86"))
    object.__setattr__(zero, "cumulative_fee", Decimal(0))
    with pytest.raises(ValueError, match="positive quantity"):
        hsm.d1_fill_cost(zero)
    assert hsm.d1_fill_cost_conservative(zero) == Decimal("0.87")
    paid = _record(1)
    object.__setattr__(paid, "cumulative_fee", Decimal("0.05"))
    assert hsm.d1_fill_cost_conservative(paid) == hsm.d1_fill_cost(paid) == Decimal("0.91")


# -- review J2: PENDING settlement, end to end ---------------------------------------------------

#: three DIFFERENT station-days with one common settlement deadline (same date, same offset)
J2_STATIONS: Final = frozenset({"nyc", "lax", "sfo"})
J2_DAY: Final = 10
J2_OFFSET: Final = -8.0
J2_DEADLINE: Final = hsm.settlement_deadline(date(2026, 9, J2_DAY), std_utc_offset_hours=J2_OFFSET)


def _three_unresolved(world: _World) -> None:
    world.offset = J2_OFFSET
    for city in sorted(J2_STATIONS):
        world.fill(_record(J2_DAY, city=city))  # no venue settlement, no CLI final


def test_j2_three_unresolved_fills_before_the_deadline_are_pending_and_pass(world: _World) -> None:
    _three_unresolved(world)
    outcome = world.run(now=J2_DEADLINE - timedelta(seconds=1), stations=J2_STATIONS)
    assert outcome.result.verdict.value == "PASS"
    assert (outcome.result.pending, outcome.result.n, outcome.result.fills) == (3, 0, 0)
    assert world.artefact()["verdict"] == "PASS"
    assert world.artefact()["counts"]["pending"] == 3


def test_j2_the_same_fills_one_second_past_the_deadline_fail_t1(world: _World) -> None:
    _three_unresolved(world)
    outcome = world.run(now=J2_DEADLINE + timedelta(seconds=1), stations=J2_STATIONS)
    assert outcome.result.verdict.value == "FAIL" and "T1" in outcome.result.triggers
    assert (outcome.result.pending, outcome.result.losses, outcome.result.unresolved) == (0, 3, 3)


def test_j2_a_resolved_loss_is_scored_before_the_deadline(world: _World) -> None:
    world.offset = J2_OFFSET
    for city in sorted(J2_STATIONS):
        world.fill(_record(J2_DAY, city=city))
        world.settle(J2_DAY, yes=True, tmax=LOW_TMAX, city=city)
    outcome = world.run(now=J2_DEADLINE - timedelta(days=1), stations=J2_STATIONS)
    assert outcome.result.losses == 3 and outcome.result.pending == 0
    assert "T1" in outcome.result.triggers


def test_j2_a_mismatch_is_pending_then_a_loss(world: _World) -> None:
    world.offset = J2_OFFSET
    world.fill(_record(J2_DAY))
    world.settle(J2_DAY, yes=False, tmax=LOW_TMAX)  # venue NO, CLI says the rung hit
    early = world.run(now=J2_DEADLINE - timedelta(seconds=1))
    assert (early.result.pending, early.result.unresolved) == (1, 0)
    late = world.run(now=J2_DEADLINE + timedelta(seconds=1))
    assert (late.result.pending, late.result.unresolved, late.result.losses) == (0, 1, 1)


def test_j2_the_registry_offsets_drive_the_deadline_by_default() -> None:
    for station, offset in (("nyc", -5.0), ("lax", -8.0), ("mdw", -6.0)):
        assert registry_std_offset_hours(station) == offset
    assert registry_std_offset_hours("nowhere") is None


# -- review K3: an unparseable rung is its own station-day --------------------------------------


def _unparseable(n: int) -> DurableFillRecord:
    base = _record(n, order=f"ORD-bad-{n}")
    return DurableFillRecord(
        venue_order_id=base.venue_order_id,
        client_order_id=base.client_order_id,
        instrument_id="tc-temp-nychigh-2026-09-01-zzz^no.POLYMARKET_US",
        order_side="BUY",
        cumulative_qty=Decimal(1),
        cumulative_cost=Decimal("0.86"),
        cumulative_fee=Decimal("0.01"),
        fee_reconciled=True,
        ts_event=base.ts_event,
        venue_fee_raw="0.01",
        trade_id=base.trade_id,
        order_qty=Decimal(1),
    )


def test_k3_unparseable_rungs_do_not_collapse_into_one_station_day(world: _World) -> None:
    for n in (1, 2, 3):
        world.fill(_unparseable(n))
    outcome = world.run()
    assert outcome.result.fills == 3
    assert outcome.result.losses == 3, "each unparseable fill is its own loss"
    assert "T1" in outcome.result.triggers


# -- review K4 / J3 / J4: a standing file we cannot read is sticky; the exit code says FAIL ----


def test_k4_a_corrupt_existing_file_is_never_overwritten_or_removed(world: _World) -> None:
    world.win(1)
    world.derived.mkdir(parents=True)
    path = world.derived / "latest.json"
    path.write_bytes(b"{not json")
    outcome = world.run()
    assert outcome.action == "sticky_fail_kept"
    assert path.read_bytes() == b"{not json"
    world.fill(_record(2, trade_id="GET-ORD-nyc-2"))  # a HOLD must not unlink it either
    assert world.run().action == "sticky_fail_kept"
    assert path.read_bytes() == b"{not json"


@pytest.mark.parametrize("payload", [b"[]", b'{"schema": "other/v9", "verdict": "PASS"}', b""])
def test_k4_a_foreign_or_empty_existing_file_is_sticky(world: _World, payload: bytes) -> None:
    world.win(1)
    world.derived.mkdir(parents=True)
    (world.derived / "latest.json").write_bytes(payload)
    assert world.run().action == "sticky_fail_kept"
    assert (world.derived / "latest.json").read_bytes() == payload


def test_j4_a_standing_fail_exits_fail_even_when_the_new_verdict_is_pass(
    world: _World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(producer, "catalog_cli_reader", lambda base: world.cli_reader)
    for d in (1, 2, 3):
        world.lose(d)
    argv = [
        "--station", "nyc",
        "--state-db", str(world.db),
        "--catalog-root", str(world.derived.parents[1] / "catalog"),
        "--catalog-base", str(world.derived.parents[1]),
        "--venue-settlements", str(world.venue_path),
    ]  # fmt: skip
    world.run()  # the FAIL is on disk
    for d in (1, 2, 3):
        world.settle(d, yes=False, tmax=HIGH_TMAX)  # the losses are later 'resolved' as wins
    world.write_venue(datetime.now(tz=UTC))
    assert producer.main(argv) == producer.EXIT_FAIL


def test_j4_a_standing_corrupt_file_exits_fail(
    world: _World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(producer, "catalog_cli_reader", lambda base: world.cli_reader)
    world.win(1)
    world.derived.mkdir(parents=True)
    (world.derived / "latest.json").write_bytes(b"garbage")
    argv = [
        "--station", "nyc",
        "--state-db", str(world.db),
        "--catalog-root", str(world.derived.parents[1] / "catalog"),
        "--catalog-base", str(world.derived.parents[1]),
        "--venue-settlements", str(world.venue_path),
    ]  # fmt: skip
    assert producer.main(argv) == producer.EXIT_FAIL


# -- review J5: any undecodable fill record is a HOLD -------------------------------------------


@pytest.mark.parametrize(
    "payload", [b"\xff\xfe", b"[]", b"{}", b'{"venue_order_id": 5}', b'{"cumulative_qty": "x"}']
)
def test_j5_any_undecodable_fill_record_holds(world: _World, payload: bytes) -> None:
    world.store.set(f"{FILL_KEY_PREFIX}BAD", payload)
    outcome = world.run()
    assert outcome.result.verdict.value == "HOLD"
    assert "fill_record_corrupt" in outcome.result.hold_reasons


# -- review J6: the producer writes exactly where the probe reads --------------------------------


def test_j6_the_producer_path_is_the_probes_path(tmp_path: Path) -> None:
    catalog_root = tmp_path / "catalog" / "quote_tape" / "polymarket_us"
    assert producer.artefact_path(catalog_root) == maker_loss_stop_artefact_path(catalog_root)


def test_j6_main_writes_where_the_probe_reads(
    world: _World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(producer, "catalog_cli_reader", lambda base: world.cli_reader)
    world.win(1)
    catalog_root = world.derived.parents[1] / "q" / "polymarket_us"
    argv = [
        "--station", "nyc",
        "--state-db", str(world.db),
        "--catalog-root", str(catalog_root),
        "--catalog-base", str(world.derived.parents[1]),
        "--venue-settlements", str(world.venue_path),
    ]  # fmt: skip
    world.write_venue(datetime.now(tz=UTC))
    assert producer.main(argv) == producer.EXIT_PASS
    probe = _probe(maker_loss_stop_artefact_path(catalog_root), datetime.now(tz=UTC))
    probe.probe_once()
    assert probe.veto_reason() is None


def test_j6_main_requires_a_catalog_root(
    world: _World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(producer.CATALOG_ROOT_ENV, raising=False)
    argv = ["--station", "nyc", "--state-db", str(world.db)]
    assert producer.main(argv) == producer.EXIT_ERROR
    assert producer.CATALOG_ROOT_ENV in capsys.readouterr().err


# -- review J7: hardening -------------------------------------------------------------------------


def test_j7_a_state_db_path_with_uri_metacharacters_is_read(tmp_path: Path) -> None:
    odd = tmp_path / "a b#c?d%e"
    odd.mkdir()
    world = _World(odd)
    world.win(1)
    assert world.run().result.fills == 1


def test_j7_removing_a_pass_fsyncs_the_directory(
    world: _World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.win(1)
    world.run()
    world.fill(_record(2, trade_id="GET-ORD-nyc-2"))
    synced: list[bool] = []
    real = os.fsync

    def spy(fd: int) -> None:
        synced.append(stat.S_ISDIR(os.fstat(fd).st_mode))
        real(fd)

    monkeypatch.setattr(os, "fsync", spy)
    assert world.run().action == "removed"
    assert synced == [True]


def test_j7_a_new_derived_directory_is_0755_whatever_the_umask(world: _World) -> None:
    world.win(1)
    old = os.umask(0o077)
    try:
        world.run()
    finally:
        os.umask(old)
    assert stat.S_IMODE(world.derived.stat().st_mode) == 0o755


# -- review D1-F3: the settlement file must be present, complete and fresh ------------------------


def _three_unresolved_past_deadline(world: _World) -> datetime:
    """Three family fills that NO file resolves, long past their settlement deadline."""
    for d in (1, 2, 3):
        world.fill(_record(d))
    return NOW


def test_f3_a_trusted_file_leaves_unresolved_past_deadline_a_loss_and_fails(world: _World) -> None:
    _three_unresolved_past_deadline(world)
    outcome = world.run()
    assert outcome.result.verdict.value == "FAIL" and "T1" in outcome.result.triggers


def test_f3_an_incomplete_file_holds_and_a_partial_page_cannot_latch_a_sticky_fail(
    world: _World,
) -> None:
    _three_unresolved_past_deadline(world)
    outcome = world.run(complete=False)
    assert outcome.result.verdict.value == "HOLD"
    assert "venue_settlement_incomplete" in outcome.result.hold_reasons
    assert outcome.result.unresolved == 0 and outcome.result.losses == 0
    assert outcome.result.pending == 3
    assert not (world.derived / "latest.json").exists(), "no FAIL file, so nothing is sticky"
    # the next COMPLETE run is judged on its own merits: the partial run left nothing behind
    assert world.run().result.verdict.value == "FAIL"


def test_f3_an_incomplete_file_still_scores_the_slugs_it_resolves(world: _World) -> None:
    for d in (1, 2, 3):
        world.lose(d)  # resolved venue YES, CLI agrees: three REAL losses
    outcome = world.run(complete=False)
    assert outcome.result.verdict.value == "FAIL" and outcome.result.losses == 3


def test_f3_a_missing_file_holds_and_a_partial_page_cannot_latch_a_sticky_fail(
    world: _World,
) -> None:
    _three_unresolved_past_deadline(world)
    outcome = world.run(write_file=False)
    assert outcome.result.verdict.value == "HOLD"
    assert "venue_settlement_missing" in outcome.result.hold_reasons
    assert not (world.derived / "latest.json").exists()


@pytest.mark.parametrize(
    "body",
    [
        b"garbage",
        b"[]",
        json.dumps({"schema": "other/v1", "complete": True, "yes_resolved": {}}).encode(),
        json.dumps({"schema": VENUE_SCHEMA, "complete": True, "yes_resolved": {}}).encode(),
        json.dumps(
            {"schema": VENUE_SCHEMA, "complete": True, "fetched_at": "nope", "yes_resolved": {}}
        ).encode(),
        json.dumps(
            {
                "schema": VENUE_SCHEMA,
                "complete": True,
                "fetched_at": "2026-10-25T12:40:00",  # naive: not a usable instant
                "yes_resolved": {},
            }
        ).encode(),
    ],
    ids=["garbage", "not_a_mapping", "foreign_schema", "no_fetched_at", "bad_fetched_at", "naive"],
)
def test_f3_an_unusable_file_holds_as_missing(world: _World, body: bytes) -> None:
    _three_unresolved_past_deadline(world)
    world.venue_path.write_bytes(body)
    outcome = world.run(write_file=False)
    assert outcome.result.verdict.value == "HOLD"
    assert "venue_settlement_missing" in outcome.result.hold_reasons


def test_f3_complete_must_be_exactly_true(world: _World) -> None:
    world.win(1)
    world.write_venue(NOW)
    body = json.loads(world.venue_path.read_text())
    body["complete"] = "true"
    world.venue_path.write_text(json.dumps(body))
    outcome = world.run(write_file=False)
    assert "venue_settlement_incomplete" in outcome.result.hold_reasons


def test_f3_the_staleness_boundary_is_24_hours(world: _World) -> None:
    assert venue_settlement.SETTLEMENT_MAX_AGE == timedelta(hours=24)
    world.win(1)
    fresh = world.run(fetched_at=NOW - venue_settlement.SETTLEMENT_MAX_AGE)
    assert fresh.result.verdict.value == "PASS", "exactly 24 h old is still usable"
    stale = world.run(fetched_at=NOW - venue_settlement.SETTLEMENT_MAX_AGE - timedelta(seconds=1))
    assert stale.result.verdict.value == "HOLD"
    assert "venue_settlement_stale" in stale.result.hold_reasons
    assert not (world.derived / "latest.json").exists(), "HOLD removes the standing PASS"


def test_f3_a_stale_file_cannot_latch_a_sticky_fail_from_unresolved_fills(world: _World) -> None:
    _three_unresolved_past_deadline(world)
    outcome = world.run(fetched_at=NOW - timedelta(days=3))
    assert outcome.result.verdict.value == "HOLD" and outcome.result.pending == 3
    assert not (world.derived / "latest.json").exists()


def test_f3_a_trusted_file_adds_no_settlement_hold_reason(world: _World) -> None:
    world.win(1)
    outcome = world.run()
    assert outcome.result.hold_reasons == ()


# -- review D1-F4: an unknown station offset is a HOLD, not an immediate LOSS ---------------------


def test_f4_an_unknown_station_offset_holds_instead_of_losing(world: _World) -> None:
    world.offset = None
    for d in (1, 2, 3):
        world.fill(_record(d))  # unresolved; with no offset the deadline is unknowable
    outcome = world.run()
    assert outcome.result.verdict.value == "HOLD"
    assert "station_offset_unknown" in outcome.result.hold_reasons
    assert (outcome.result.pending, outcome.result.losses, outcome.result.unresolved) == (3, 0, 0)
    assert not (world.derived / "latest.json").exists()


def test_f4_a_known_offset_adds_no_offset_hold_reason(world: _World) -> None:
    world.win(1)
    assert "station_offset_unknown" not in world.run().result.hold_reasons


# -- GET- fill floor: D-1 16:50Z of the family manifest d0 ---------------------------------------

#: 2026-10-25's posting-window open. A GET- fill strictly before this is not a live-family fill.
_D0_FLOOR_NS: Final = int(datetime(2026, 10, 24, 16, 50, tzinfo=UTC).timestamp()) * 1_000_000_000


def _main_argv(world: _World, manifest: Path) -> list[str]:
    return [
        "--station", "nyc",
        "--state-db", str(world.db),
        "--catalog-root", str(world.derived.parents[1] / "catalog"),
        "--venue-settlements", str(world.venue_path),
        "--family-manifest", str(manifest),
    ]  # fmt: skip


def test_a_get_fill_before_the_floor_passes_and_writes_latest(world: _World) -> None:
    world.fill(_record(1, trade_id="GET-BEFORE", ts_event=_D0_FLOOR_NS - 1))
    outcome = world.run(get_fill_not_before_ns=_D0_FLOOR_NS)
    assert outcome.result.verdict.value == "PASS"
    assert outcome.result.fills == 0
    assert "get_fill" not in outcome.result.hold_reasons
    body = world.artefact()
    assert body["verdict"] == "PASS"
    assert (world.derived / "latest.json").is_file()


@pytest.mark.parametrize(
    "ts_event", [_D0_FLOOR_NS, _D0_FLOOR_NS + 1], ids=["at-bound", "after-bound"]
)
def test_a_get_fill_at_or_after_the_floor_holds_and_removes_a_standing_pass(
    world: _World, ts_event: int
) -> None:
    assert world.run(get_fill_not_before_ns=_D0_FLOOR_NS).result.verdict.value == "PASS"
    assert (world.derived / "latest.json").is_file()
    world.fill(_record(2, trade_id="GET-LIVE", ts_event=ts_event))
    outcome = world.run(get_fill_not_before_ns=_D0_FLOOR_NS)
    assert outcome.result.verdict.value == "HOLD"
    assert "get_fill" in outcome.result.hold_reasons
    assert outcome.action == "removed"
    assert not (world.derived / "latest.json").exists()


def test_the_get_fill_floor_is_d_minus_1_1650z_of_manifest_d0(
    world: _World, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest = tmp_path / "family.json"
    manifest.write_text(json.dumps({"d0_climate_day": "2026-10-25"}))
    assert producer.family_get_fill_floor_ns(manifest) == _D0_FLOOR_NS
    seen: dict[str, int | None] = {}
    real = producer.produce

    def spy(**kwargs: Any) -> producer.Outcome:
        seen["floor"] = kwargs.get("get_fill_not_before_ns")
        return real(**kwargs)

    monkeypatch.setattr(producer, "produce", spy)
    monkeypatch.setattr(producer, "catalog_cli_reader", lambda base: world.cli_reader)
    world.write_venue(datetime.now(tz=UTC))
    assert producer.main(_main_argv(world, manifest)) == producer.EXIT_PASS
    assert seen["floor"] == _D0_FLOOR_NS


def test_a_manifest_without_d0_climate_day_fails_closed(
    world: _World,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(producer, "catalog_cli_reader", lambda base: world.cli_reader)
    world.fill(_record(1, trade_id="GET-OLD", ts_event=1))
    world.write_venue(datetime.now(tz=UTC))
    missing_field = tmp_path / "no-d0.json"
    missing_field.write_text(json.dumps({"family_id": "pm_us_no_maker_sharp_v1"}))
    absent = tmp_path / "missing.json"
    for manifest in (missing_field, absent):
        assert producer.main(_main_argv(world, manifest)) == producer.EXIT_ERROR
        assert not (world.derived / "latest.json").exists()
    err = capsys.readouterr().err
    assert "d0_climate_day" in err
