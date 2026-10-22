"""ARM B2 slug selection: the 2026-10-22 NO_ELIGIBLE_SLUGS refusal, offline, RED-first.

The real run read one listing page, handed it to a STRICT weather parser, and that parser raises
on any weather market of a city outside the settlement registry (Philadelphia is listed; the
registry has five cities). The raise was swallowed, so no slug was ever a candidate and nothing
said why. These tests pin the production-parity discovery, the paging, the value-free
diagnostics and the read-only ``--select-only`` mode.
"""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from typing import Any

import pytest

from breezy.adapters.polymarket_us import provider as production
from breezy.adapters.polymarket_us.config import PolymarketUSMarketDiscoveryConfig
from tests.unit import b2_control_fakes as fk

RUN_DATE = "2026-10-22"
SUPERVISOR_ONLY = (
    "breezy-trade-supervisor.service loaded active running Breezy daily trade-node supervisor\n"
)
SLUG_PHL = "tc-temp-phlhigh-2026-10-22-lt56f"
CITY_CODES = PolymarketUSMarketDiscoveryConfig().city_codes


@pytest.fixture(scope="module")
def ctl() -> Any:
    return fk.load_control()


def _deps(ctl: Any, rig: fk.Rig, tmp_path: Path) -> Any:
    return ctl.Deps(
        today_utc=lambda: RUN_DATE,
        list_units=lambda: SUPERVISOR_ONLY,
        probe_node=lambda: None,
        load_env=lambda: {"POLYMARKET_US_USER_AGENT": "ua"},
        build_session=lambda _env: rig.session,
        sleep=rig.venue.sleep,
        evidence_dir=tmp_path / "b2",
        stamp=lambda: "20261022T120000Z",
    )


def _unregistered_city_market() -> dict[str, Any]:
    """A fixture-shaped weather market of a listed city the settlement registry lacks."""
    market = fk.market_payload(fk.SLUG_X)
    market["slug"] = SLUG_PHL
    market["question"] = "Highest temperature in Philadelphia on October 22?"
    for side in market["marketSides"]:
        side["identifier"] = SLUG_PHL
    return market


def _non_weather_market() -> dict[str, Any]:
    market = fk.market_payload(fk.SLUG_X)
    market.update({"slug": "btc-above-100k-2026-10-22", "question": "Will BTC close above 100k?"})
    return market


def _mixed_page() -> dict[str, Any]:
    page = fk.markets_page(fk.SLUG_X, fk.SLUG_Y, fk.SLUG_Z)
    page["markets"] = [_unregistered_city_market(), _non_weather_market(), *page["markets"]]
    return page


# ------------------------------------------------------------------- root cause (RED)


def test_an_unregistered_listed_city_does_not_blank_the_candidates(ctl: Any) -> None:
    picked = ctl.select_probe_slugs(_mixed_page(), city_codes=CITY_CODES, now_ns=fk.START_NS)
    assert picked is not None
    assert picked.slugs == (fk.SLUG_X, fk.SLUG_Y)


def test_candidates_equal_the_production_discovery_on_the_recorded_climate_page(ctl: Any) -> None:
    page = json.loads((fk.RAW / "markets_categories_climate.json").read_text(encoding="utf-8"))
    assert ctl._candidates(page, CITY_CODES) == list(
        production.discovery_candidate_slugs(page, city_codes=CITY_CODES)
    )


def test_candidates_equal_the_production_provider_path_on_a_mixed_page(ctl: Any) -> None:
    page = _mixed_page()
    accepted, sightings = production._weather_market_payloads(
        page, CITY_CODES, collect_unregistered=True
    )
    assert [s.slug for s in sightings] == [SLUG_PHL]
    assert ctl._candidates(page, CITY_CODES) == [m["slug"] for m in accepted]


def test_one_malformed_market_is_counted_and_does_not_hide_the_others(ctl: Any) -> None:
    page = _mixed_page()
    page["markets"].insert(0, {"slug": "Tc Temp ?bad", "question": "x"})
    counts: dict[str, int] = {}
    candidates = ctl._candidates(page, CITY_CODES, reasons=counts)
    assert candidates == [fk.SLUG_X, fk.SLUG_Y, fk.SLUG_Z]
    assert counts["PAYLOAD_REJECTED"] == 1
    assert counts["UNREGISTERED_CITY"] == 1
    assert counts["NOT_WEATHER"] == 1


# --------------------------------------------------------------------- diagnostics


def test_every_listed_market_lands_in_exactly_one_reason_or_is_eligible(ctl: Any) -> None:
    def variant(slug: str, **changes: Any) -> dict[str, Any]:
        market = fk.market_payload(slug)
        market.update(changes)
        return market

    markets = [
        fk.market_payload("tc-temp-nychigh-2026-10-23-lt56f"),  # eligible
        variant("tc-temp-nychigh-2026-10-23-lt57f", orderPriceMinTickSize=0.1),
        variant("tc-temp-nychigh-2026-10-23-lt58f", minimumTradeQty="5"),
        variant("tc-temp-nychigh-2026-10-23-lt59f", hidden=True),
        variant("tc-temp-nychigh-2026-10-23-lt60f", active=False),
        variant("tc-temp-nychigh-2026-10-23-lt61f", status="MARKET_STATUS_HALTED"),
        variant("tc-temp-nychigh-2026-10-23-lt62f", endDate="not a date"),
        variant("tc-temp-nychigh-2026-10-23-lt63f", endDate="2026-10-14T18:00:00Z"),
        variant("tc-temp-nychigh-2026-10-23-lt64f", archived=True),
        fk.market_payload(fk.SLUG_LOW),
    ]
    counts: dict[str, int] = {}
    eligible, _ = ctl.eligible_probe_slugs(
        {"markets": markets},
        candidates=[m["slug"] for m in markets],
        is_daily_high=ctl.submit_chain.is_daily_high_slug,
        is_resolved=ctl._is_resolved,
        now_ns=fk.START_NS,
        reasons=counts,
    )
    assert eligible == ["tc-temp-nychigh-2026-10-23-lt56f"]
    assert counts == {
        "TICK_NOT_ONE_CENT": 1,
        "MIN_QTY_ABOVE_ONE_OR_UNREADABLE": 1,
        "HIDDEN": 1,
        "INACTIVE": 1,
        "NOT_OPEN": 1,
        "CLOSE_UNREADABLE": 1,
        "CLOSE_TOO_SOON": 1,
        "RESOLVED": 1,
        "NOT_DAILY_HIGH": 1,
    }


def test_the_evidence_selection_block_is_value_free(ctl: Any, tmp_path: Path) -> None:
    venue = fk.FakeVenue(markets=_mixed_page())
    rig = fk.Rig(ctl, venue)
    result = rig.run()
    selection = result.document["selection"]
    assert selection["markets_seen"] == 5
    assert selection["pages"] == 1
    assert selection["excluded_by_reason"]["UNREGISTERED_CITY"] == 1
    assert selection["excluded_by_reason"]["NOT_WEATHER"] == 1
    text = json.dumps({k: v for k, v in selection.items() if k != "chosen"})
    assert "tc-temp" not in text and "btc" not in text and "phl" not in text.lower()
    assert set(selection["chosen"]) <= {fk.SLUG_X, fk.SLUG_Y}


def test_a_refusal_still_carries_the_diagnostics(ctl: Any, tmp_path: Path) -> None:
    rig = fk.Rig(ctl, fk.FakeVenue(markets={"markets": [_unregistered_city_market()]}))
    exit_code = asyncio.run(ctl.run(RUN_DATE, _deps(ctl, rig, tmp_path)))
    assert exit_code == 1
    (path,) = list((tmp_path / "b2").glob("*.json"))
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["failure"] == "NO_ELIGIBLE_SLUGS"
    assert document["selection"]["markets_seen"] == 1
    assert document["selection"]["excluded_by_reason"] == {"UNREGISTERED_CITY": 1}


# ------------------------------------------------------------------------- paging


def _two_page_rig(ctl: Any) -> fk.Rig:
    venue = fk.FakeVenue()
    venue.markets_pages = {
        0: fk.markets_page(
            fk.SLUG_CLOSED, fk.SLUG_LOW, fk.SLUG_Z, closed=frozenset({fk.SLUG_CLOSED, fk.SLUG_Z})
        ),
        3: fk.markets_page(fk.SLUG_X, fk.SLUG_Y),
    }
    return fk.Rig(ctl, venue, discovery=PolymarketUSMarketDiscoveryConfig(limit=3))


def test_listing_follows_offsets_until_a_short_page_like_production(ctl: Any) -> None:
    rig = _two_page_rig(ctl)
    reading = asyncio.run(rig.session.list_markets())
    assert [m["slug"] for m in reading.payload["markets"]] == [
        fk.SLUG_CLOSED,
        fk.SLUG_LOW,
        fk.SLUG_Z,
        fk.SLUG_X,
        fk.SLUG_Y,
    ]
    assert rig.session.list_pages == 2
    assert [u.split("offset=")[1].split("&")[0] for u in rig.venue.markets_urls] == ["0", "3"]
    assert rig.budget.gets == 1 and rig.budget.aux_gets == 1


def test_a_listing_that_never_ends_stops_at_the_page_cap(ctl: Any) -> None:
    venue = fk.FakeVenue()
    full = fk.markets_page(fk.SLUG_X, fk.SLUG_Y)
    venue.markets_pages = {offset: copy.deepcopy(full) for offset in range(0, 40, 2)}
    rig = fk.Rig(ctl, venue, discovery=PolymarketUSMarketDiscoveryConfig(limit=2))
    asyncio.run(rig.session.list_markets())
    assert rig.session.list_pages == ctl.MAX_LIST_PAGES
    assert rig.budget.aux_gets == ctl.MAX_LIST_PAGES - 1


def test_the_paged_listing_selects_the_pair_from_the_second_page(ctl: Any) -> None:
    result = _two_page_rig(ctl).run()
    assert result.document["selection"]["pages"] == 2
    assert result.document["slugs"] == [fk.SLUG_X, fk.SLUG_Y]


# ------------------------------------------------------------------ --select-only


def _select_only(ctl: Any, rig: fk.Rig, tmp_path: Path) -> int:
    rig.post_client.forbid = True
    code: int = asyncio.run(ctl.run(RUN_DATE, _deps(ctl, rig, tmp_path), select_only=True))
    return code


def test_select_only_sends_no_post_and_writes_the_selection(
    ctl: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = fk.Rig(ctl, fk.FakeVenue(markets=_mixed_page()))
    assert _select_only(ctl, rig, tmp_path) == 0
    assert rig.post_client.calls == []
    assert [m for m, _ in rig.venue.requests if m != "GET"] == []
    (path,) = list((tmp_path / "b2").glob("*.json"))
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["counts"]["creates"] == 0 and document["counts"]["cancels"] == 0
    assert document["mode"] == "select_only"
    assert document["outcome"] == "SELECT_ONLY_PAIR_FOUND"
    assert document["verdicts"] == {"S-1": "NOT_RUN", "S-2": "NOT_RUN", "S-6": "NOT_RUN"}
    assert document["licenses"] == {
        "GTD_EXPIRY": False,
        "SLUG_SCOPED_CANCEL_ALL": False,
        "MAKER_COMMISSION_SIGN": False,
    }
    assert document["selection"]["chosen"] == [fk.SLUG_X, fk.SLUG_Y]
    assert rig.venue.quote_reads  # quotes are read-only GETs and were read
    out = capsys.readouterr().out
    assert "B2_SELECT_ONLY" in out and "markets_seen=5" in out and "pair=found" in out
    assert f"slugs={fk.SLUG_X},{fk.SLUG_Y}" in out
    assert "phl" not in out.lower()


def test_select_only_runs_the_preflight_checks_first(ctl: Any, tmp_path: Path) -> None:
    rig = fk.Rig(ctl)
    rig.venue.add_foreign_order()
    rig.post_client.forbid = True
    assert asyncio.run(ctl.run(RUN_DATE, _deps(ctl, rig, tmp_path), select_only=True)) == 2
    assert rig.venue.quote_reads == []
    assert not (tmp_path / "b2").exists()


def test_select_only_with_no_pair_exits_one_and_names_why(
    ctl: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = fk.Rig(ctl, fk.FakeVenue(markets={"markets": [_unregistered_city_market()]}))
    assert _select_only(ctl, rig, tmp_path) == 1
    assert rig.post_client.calls == []
    (path,) = list((tmp_path / "b2").glob("*.json"))
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["outcome"] == "SELECT_ONLY_NO_PAIR"
    assert document["selection"]["excluded_by_reason"] == {"UNREGISTERED_CITY": 1}
    assert "pair=none" in capsys.readouterr().out


def test_select_only_flag_parses_and_defaults_off(ctl: Any) -> None:
    assert ctl.parse_args(["--run-date", RUN_DATE]).select_only is False
    assert ctl.parse_args(["--run-date", RUN_DATE, "--select-only"]).select_only is True


def test_the_full_run_still_posts_when_select_only_is_off(ctl: Any, tmp_path: Path) -> None:
    rig = fk.Rig(ctl, fk.FakeVenue(markets=_mixed_page()))
    assert asyncio.run(ctl.run(RUN_DATE, _deps(ctl, rig, tmp_path))) == 0
    assert rig.post_client.calls != []
