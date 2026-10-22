"""ARM D1 producer: durable fills + settlement truth -> ``derived/maker-loss-stop/latest.json``.

Fixture-only (R6): a throwaway exec-state sqlite, an injected CLI-final reader, a venue-settlement
file. No network, no catalog, no node. The last block drives the REAL ``LossStopProbe``.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, timedelta
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
from breezy.strategy.no_ladder_maker.harm_stop import maker_loss_stop_artefact_path
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
        ts_event=1_790_000_000_000_000_000 + day,
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

    def run(self, *, now: datetime = NOW, stations: frozenset[str] = STATIONS) -> producer.Outcome:
        self.venue_path.write_text(
            json.dumps({"schema": producer.VENUE_SCHEMA, "yes_resolved": self.venue})
        )
        return producer.produce(
            state_db=self.db,
            derived_dir=self.derived,
            venue_settlements=self.venue_path,
            family_stations=stations,
            cli_reading=self.cli_reader,
            now=now,
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
    assert body["counts"] == {"fills": 0, "wins": 0, "losses": 0, "n": 0, "unresolved": 0}
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
    world.venue_path.write_text(
        json.dumps({"schema": producer.VENUE_SCHEMA, "yes_resolved": world.venue})
    )
    argv = [
        "--station", "nyc",
        "--state-db", str(world.db),
        "--data-root", str(world.derived.parents[1]),
        "--venue-settlements", str(world.venue_path),
    ]  # fmt: skip
    assert producer.main(argv) == producer.EXIT_PASS
    printed = json.loads(capsys.readouterr().out)
    assert printed["verdict"] == "PASS" and printed["action"] == "written"
    world.fill(_record(2, trade_id="GET-ORD-nyc-2"))
    assert producer.main(argv) == producer.EXIT_HOLD
    for d in (3, 4, 5):
        world.lose(d)
    world.venue_path.write_text(
        json.dumps({"schema": producer.VENUE_SCHEMA, "yes_resolved": world.venue})
    )
    assert producer.main(argv) == producer.EXIT_FAIL


def test_main_requires_a_state_db(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(producer.STATE_DB_ENV, raising=False)
    assert producer.main(["--station", "nyc"]) == producer.EXIT_ERROR
    assert producer.STATE_DB_ENV in capsys.readouterr().err
