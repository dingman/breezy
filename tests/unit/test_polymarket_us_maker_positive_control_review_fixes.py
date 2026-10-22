"""ARM B2 review fixes (PMR Q1-Q5, security R1-R5), offline, RED-first.

Every test drives the real script over :mod:`tests.unit.b2_control_fakes` (no venue contact).
Authority: ``B2_review_followups`` (PMR REQUEST_CHANGES and security REQUEST_CHANGES).
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.unit import b2_control_fakes as fk

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "venue" / "polymarket_us_maker_positive_control.py"
RUN_DATE = "2026-10-22"
SUPERVISOR_ONLY = (
    "breezy-trade-supervisor.service loaded active running Breezy daily trade-node supervisor\n"
)

SLUG_NYC = "tc-temp-nychigh-2026-10-22-{tail}"
SLUG_NYC_NEXT = "tc-temp-nychigh-2026-10-23-{tail}"
SLUG_MIA_NEXT = "tc-temp-miahigh-2026-10-23-{tail}"


@pytest.fixture(scope="module")
def ctl() -> Any:
    return fk.load_control()


def _deps(ctl: Any, rig: fk.Rig, tmp_path: Path, **overrides: Any) -> Any:
    base = ctl.Deps(
        today_utc=lambda: RUN_DATE,
        list_units=lambda: SUPERVISOR_ONLY,
        probe_node=lambda: None,
        load_env=lambda: {"POLYMARKET_US_USER_AGENT": "ua"},
        build_session=lambda _env: rig.session,
        sleep=rig.venue.sleep,
        evidence_dir=tmp_path / "b2",
        stamp=lambda: "20261022T120000Z",
    )
    return ctl.Deps(**{**base.__dict__, **overrides})


def _creates(rig: fk.Rig) -> list[dict[str, Any]]:
    return [body for path, body in rig.posts() if path == "/v1/orders"]


# ------------------------------------------------------------------ Q1 quote guard


@pytest.mark.parametrize("field", ["bid", "last", "current", "settlement"])
def test_q1_a_slug_with_a_near_resolved_price_is_never_rested_on(ctl: Any, field: str) -> None:
    venue = fk.FakeVenue()
    venue.quote_overrides[fk.SLUG_X] = fk.quote_payload(fk.SLUG_X, **{field: "0.9700"})
    rig = fk.Rig(ctl, venue)
    result = rig.run()
    rested = {body["marketSlug"] for body in _creates(rig)}
    assert fk.SLUG_X not in rested
    assert set(result.document["slugs"]) == {fk.SLUG_Y, fk.SLUG_Z}
    assert result.document["slugs_share_event"] is False
    assert result.document["quote_guard"]["excluded"]["HIGH_PRICE"] >= 1


def test_q1_a_price_just_under_the_guard_is_accepted(ctl: Any) -> None:
    venue = fk.FakeVenue()
    venue.quote_overrides[fk.SLUG_X] = fk.quote_payload(fk.SLUG_X, bid="0.9699")
    rig = fk.Rig(ctl, venue)
    assert set(rig.run().document["slugs"]) == {fk.SLUG_X, fk.SLUG_Y}


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        {},
        {"marketData": "x"},
        {"marketData": {"marketSlug": "someone-else", "bestBid": {"value": "0.40"}}},
        {"marketData": {"marketSlug": fk.SLUG_X}},  # no price at all
        {"marketData": {"marketSlug": fk.SLUG_X, "bestBid": {"value": "garbage"}}},
    ],
)
def test_q1_an_unreadable_quote_excludes_the_slug(ctl: Any, payload: Any) -> None:
    venue = fk.FakeVenue()
    venue.quote_overrides[fk.SLUG_X] = payload
    rig = fk.Rig(ctl, venue)
    result = rig.run()
    assert fk.SLUG_X not in result.document["slugs"]
    assert fk.SLUG_X not in {body["marketSlug"] for body in _creates(rig)}
    assert result.document["quote_guard"]["excluded"]["UNREADABLE"] == 1


def test_q1_a_halted_market_state_excludes_the_slug(ctl: Any) -> None:
    venue = fk.FakeVenue()
    venue.quote_overrides[fk.SLUG_X] = fk.quote_payload(fk.SLUG_X, state="MARKET_STATE_HALTED")
    rig = fk.Rig(ctl, venue)
    result = rig.run()
    assert fk.SLUG_X not in result.document["slugs"]
    assert result.document["quote_guard"]["excluded"]["HALTED"] == 1


def test_q1_every_quote_unreadable_refuses_before_any_write(ctl: Any) -> None:
    venue = fk.FakeVenue()
    venue.quote_status = 503
    rig = fk.Rig(ctl, venue)
    result = rig.run()
    assert rig.post_client.calls == []
    assert result.exit_code != 0
    assert result.document["failure"] == "NO_ELIGIBLE_SLUGS"


def test_q1_fewer_than_two_quotable_slugs_refuses_before_any_write(ctl: Any) -> None:
    venue = fk.FakeVenue()
    venue.quote_overrides[fk.SLUG_X] = fk.quote_payload(fk.SLUG_X, bid="0.9900")
    venue.quote_overrides[fk.SLUG_Y] = fk.quote_payload(fk.SLUG_Y, last="0.9900")
    rig = fk.Rig(ctl, venue)
    result = rig.run()
    assert rig.post_client.calls == []
    assert result.document["failure"] == "NO_ELIGIBLE_SLUGS"


def test_q1_the_quote_is_rechecked_immediately_before_each_post(ctl: Any) -> None:
    venue = fk.FakeVenue()
    # the second read of X (the re-check before A) shows a near-resolved bid
    venue.quote_script[fk.SLUG_X] = [
        fk.quote_payload(fk.SLUG_X),
        fk.quote_payload(fk.SLUG_X, bid="0.9800"),
    ]
    rig = fk.Rig(ctl, venue)
    result = rig.run()
    assert rig.post_client.calls == []
    assert result.exit_code != 0
    assert str(result.document["failure"]).startswith("QUOTE_GUARD")
    assert venue.quote_reads.count(fk.SLUG_X) == 2


def test_q1_each_rest_reads_the_quote_of_its_own_slug_first(ctl: Any) -> None:
    rig = fk.Rig(ctl)
    rig.run()
    creates = _creates(rig)
    assert len(creates) == 3
    last_read: str | None = None
    ordinal = 0
    for method, path in rig.venue.requests:
        if method == "GET" and path.endswith("/bbo"):
            last_read = path.split("/")[3]
        elif method == "POST" and path == "/v1/orders":
            assert last_read == creates[ordinal]["marketSlug"]
            ordinal += 1


def test_q1_ranking_prefers_a_middle_rung_over_the_alphabetical_first(ctl: Any) -> None:
    tails = ["lt56f", "gte56lt57f", "gte57lt58f", "gte58lt59f", "gte59f"]
    slugs = [SLUG_NYC.format(tail=t) for t in tails]
    payload = fk.markets_page(*slugs)
    ranked = ctl.ranked_probe_slugs(payload, city_codes=("nyc",), now_ns=fk.START_NS)
    assert sorted(ranked) == sorted(slugs)
    assert ranked[0] == SLUG_NYC.format(tail="gte57lt58f")
    assert ranked[-1] in {slugs[0], slugs[-1]}  # the open-ended tails rank last


def test_q1_ranking_prefers_next_day_markets(ctl: Any) -> None:
    today = [SLUG_NYC.format(tail=t) for t in ("gte56lt57f", "gte57lt58f")]
    nxt = [SLUG_NYC_NEXT.format(tail=t) for t in ("gte56lt57f", "gte57lt58f")]
    payload = fk.markets_page(*today, *nxt)
    ranked = ctl.ranked_probe_slugs(payload, city_codes=("nyc",), now_ns=fk.START_NS_RUN_DAY)
    assert set(ranked[:2]) == set(nxt)


def test_q1_a_fill_seen_at_the_final_check_fails_the_run_and_is_flagged(
    ctl: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    venue = fk.FakeVenue()
    # order A (create ordinal 1): GETs are confirm (1), cancel-confirm (2), final check (3)
    venue.fill_on_get[1] = (3, "ORDER_STATE_PARTIALLY_FILLED")
    rig = fk.Rig(ctl, venue)
    assert asyncio.run(ctl.run(RUN_DATE, _deps(ctl, rig, tmp_path))) == 1
    doc = json.loads(next((tmp_path / "b2").glob("*.json")).read_text(encoding="utf-8"))
    assert doc["outcome"] == "FAIL"
    assert doc["fill_detected"] is True
    assert doc["failure"] == "ORDER_FILLED_DETECTED"
    assert doc["licenses"] == {
        "GTD_EXPIRY": False,
        "SLUG_SCOPED_CANCEL_ALL": False,
        "MAKER_COMMISSION_SIGN": False,
    }
    # reported, never flattened: no write beyond the sequence's own three creates and cancels
    assert [p for p, _ in rig.posts()].count("/v1/orders") == 3
    assert "FILLED" in capsys.readouterr().err


def test_q1_the_final_check_gets_each_own_order(ctl: Any) -> None:
    rig = fk.Rig(ctl)
    result = rig.run()
    ids = list(result.document["order_ids"].values())
    gets = [path for method, path in rig.venue.requests if method == "GET"]
    last_open = max(i for i, p in enumerate(gets) if p == "/v1/orders/open")
    tail = gets[last_open + 1 :]
    assert sorted(tail) == sorted(f"/v1/order/{i}" for i in ids)
    assert result.document["fill_detected"] is False


# ------------------------------------------------------------ Q2 close-time guard


def _market_with_end(slug: str, end: str | None) -> dict[str, Any]:
    market = fk.market_payload(slug)
    if end is None:
        market.pop("endDate", None)
    else:
        market["endDate"] = end
    return market


def _eligible(ctl: Any, market: dict[str, Any], now_ns: int) -> bool:
    payload = {"markets": [market]}
    return bool(ctl.ranked_probe_slugs(payload, city_codes=("nyc",), now_ns=now_ns))


def test_q2_close_time_must_clear_the_gtd_ceiling_plus_fifteen_minutes(ctl: Any) -> None:
    now = fk.START_NS_RUN_DAY
    margin = ctl.GTD_CEILING_SECS + 15 * 60
    assert margin == 1500
    exact = fk._format_utc(now + margin * fk.NS)
    short = fk._format_utc(now + (margin - 1) * fk.NS)
    assert _eligible(ctl, _market_with_end(fk.SLUG_X, exact), now)
    assert not _eligible(ctl, _market_with_end(fk.SLUG_X, short), now)


@pytest.mark.parametrize("end", [None, "", "tomorrow", "2026-10-23T05:00:00+00:00", 5])
def test_q2_a_missing_or_unparseable_close_time_is_excluded(ctl: Any, end: Any) -> None:
    market = _market_with_end(fk.SLUG_X, None)
    if end is not None:
        market["endDate"] = end
    assert not _eligible(ctl, market, fk.START_NS_RUN_DAY)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "MARKET_STATUS_HALTED"),
        ("status", "MARKET_STATUS_SUSPENDED"),
        ("status", None),
        ("ep3Status", "HALTED"),
    ],
)
def test_q2_a_market_not_plainly_open_is_excluded(ctl: Any, field: str, value: Any) -> None:
    market = fk.market_payload(fk.SLUG_X)
    if value is None:
        market.pop(field)
    else:
        market[field] = value
    assert not _eligible(ctl, market, fk.START_NS_RUN_DAY)


def test_q2_an_open_market_far_from_close_is_eligible(ctl: Any) -> None:
    assert _eligible(ctl, fk.market_payload(fk.SLUG_X), fk.START_NS_RUN_DAY)


def test_q2_the_close_time_is_rechecked_before_posting(ctl: Any) -> None:
    rig = fk.Rig(ctl)
    asyncio.run(rig.session.list_markets())
    state = ctl.RunState(run_date=RUN_DATE, started_ns=rig.venue.now_ns)
    end = fk._parse_utc(rig.session._markets[fk.SLUG_X]["endDate"])
    rig.venue.now_ns = end - (ctl.GTD_CEILING_SECS + 14 * 60) * fk.NS  # 14 min of margin left
    with pytest.raises(ctl.StepFailed) as excinfo:
        asyncio.run(ctl._rest(rig.session, state, "A", fk.SLUG_X, ctl.REST_GTD_SECS))
    assert excinfo.value.args[0] == "CLOSE_TOO_SOON"
    assert rig.post_client.calls == []


# --------------------------------------------------------------- Q3 verdict honesty


def test_q3_s2_over_siblings_passes_and_licenses_both_flips(ctl: Any) -> None:
    doc = fk.Rig(ctl).run().document
    assert doc["verdicts"]["S-2"] == "PASS"
    assert doc["slugs_share_event"] is True
    assert doc["licenses"] == {
        "GTD_EXPIRY": True,
        "SLUG_SCOPED_CANCEL_ALL": True,
        "MAKER_COMMISSION_SIGN": False,
    }


def test_q3_s2_over_non_siblings_is_pass_nonsibling_and_licenses_no_scope_flip(
    ctl: Any,
) -> None:
    venue = fk.FakeVenue(markets=fk.markets_page(fk.SLUG_X, fk.SLUG_Z))
    result = fk.Rig(ctl, venue).run()
    doc = result.document
    assert doc["slugs_share_event"] is False
    assert doc["verdicts"]["S-2"] == "PASS_NONSIBLING"
    assert result.exit_code == 0
    assert doc["licenses"]["SLUG_SCOPED_CANCEL_ALL"] is False
    assert doc["licenses"]["GTD_EXPIRY"] is True


def test_q3_a_skipped_s2_licenses_no_scope_flip(ctl: Any) -> None:
    venue = fk.FakeVenue()
    venue.foreign_after_creates = 3
    doc = fk.Rig(ctl, venue).run().document
    assert doc["verdicts"]["S-2"] == "SKIPPED_FOREIGN_ORDER"
    assert doc["licenses"]["SLUG_SCOPED_CANCEL_ALL"] is False


def test_q3_s6_requires_the_pre_expiry_echo_of_tif_and_good_till_time(ctl: Any) -> None:
    venue = fk.FakeVenue()
    venue.echo_gtd_skew_s = 5
    result = fk.Rig(ctl, venue).run()
    assert result.document["verdicts"]["S-6"] == "FAIL"
    assert result.document["failure"] == "S6_GTD_ECHO_MISMATCH"
    assert result.document["details"]["s6_b_gtd_echoed"] is False
    assert result.document["licenses"]["GTD_EXPIRY"] is False
    assert result.exit_code != 0


def test_q3_s6_fails_when_the_echoed_tif_is_not_gtd(ctl: Any) -> None:
    venue = fk.FakeVenue()
    venue.echo_tif = "TIME_IN_FORCE_GOOD_TILL_CANCEL"
    result = fk.Rig(ctl, venue).run()
    assert result.document["verdicts"]["S-6"] == "FAIL"
    assert result.document["licenses"]["GTD_EXPIRY"] is False


def test_q3_s6_fails_when_the_first_expired_observation_is_before_the_sent_time(
    ctl: Any,
) -> None:
    venue = fk.FakeVenue()
    venue.expire_early_s = 30
    result = fk.Rig(ctl, venue).run()
    assert result.document["verdicts"]["S-6"] == "FAIL"
    assert result.document["failure"] == "S6_EXPIRED_EARLY"
    assert result.document["details"]["s6_expiry_not_early"] is False
    assert result.document["licenses"]["GTD_EXPIRY"] is False


def test_q3_a_late_but_correct_expiry_records_both_conditions_true(ctl: Any) -> None:
    venue = fk.FakeVenue()
    venue.expiry_lag_s = 40
    doc = fk.Rig(ctl, venue).run().document
    assert doc["details"]["s6_b_gtd_echoed"] is True
    assert doc["details"]["s6_expiry_not_early"] is True
    assert doc["verdicts"]["S-6"] == "PASS"


# ------------------------------------------------------------ Q4 commission stays False


def test_q4_the_commission_sign_is_never_licensed(ctl: Any) -> None:
    for venue in (fk.FakeVenue(), fk.FakeVenue(markets=fk.markets_page(fk.SLUG_X, fk.SLUG_Z))):
        assert fk.Rig(ctl, venue).run().document["licenses"]["MAKER_COMMISSION_SIGN"] is False
    assert "MAKER_COMMISSION_SIGN_VERIFIED" not in SCRIPT_PATH.read_text(encoding="utf-8")


# ------------------------------------------------------------ Q5 activities capture

_PR_ROW = {
    "type": "ACTIVITY_TYPE_POSITION_RESOLUTION",
    "positionResolution": {
        "marketSlug": "tc-temp-nychigh-2026-10-01-lt79f",
        "beforePosition": {"netPosition": "5", "cost": {"value": "-123.45", "currency": "USD"}},
        "afterPosition": {"netPosition": "0", "expired": True},
        "tradeId": "TRADEID98765",
        "side": "POSITION_SIDE_LONG",
        "outcome": "OUTCOME_SIDE_NO",
    },
}
_TRADE_ROW = {
    "type": "ACTIVITY_TYPE_TRADE",
    "trade": {"id": "TRADE000001", "state": "TRADE_STATE_CLEARED"},
}


def _paged(venue: fk.FakeVenue, *pages: dict[str, Any]) -> None:
    venue.activities_pages = list(pages)


def _page(rows: list[dict[str, Any]], *, eof: bool, cursor: str | None = None) -> dict[str, Any]:
    page: dict[str, Any] = {"activities": rows, "eof": eof}
    if cursor is not None:
        page["nextCursor"] = cursor
    return page


def test_q5_pages_until_a_position_resolution_row_appears(ctl: Any) -> None:
    venue = fk.FakeVenue()
    _paged(
        venue,
        _page([_TRADE_ROW], eof=False, cursor="CURSORONE"),
        _page([_TRADE_ROW], eof=False, cursor="CURSORTWO"),
        _page([_PR_ROW, _PR_ROW], eof=False, cursor="CURSORTHREE"),
        _page([_PR_ROW], eof=True),
    )
    doc = fk.Rig(ctl, venue).run().document
    acts = doc["activities"]
    assert acts["pages"] == 3
    assert acts["stop_reason"] == "FOUND_POSITION_RESOLUTION"
    assert acts["position_resolution"]["rows"] == 2
    assert acts["d1_cases_found"] == 2
    assert len(venue.activity_urls) == 3
    assert "cursor=CURSORONE" in venue.activity_urls[1]
    assert "CURSOR" not in json.dumps(doc)


def test_q5_stops_at_the_page_cap_without_a_resolution_row(ctl: Any) -> None:
    venue = fk.FakeVenue()
    _paged(venue, *[_page([_TRADE_ROW], eof=False, cursor=f"C{i}") for i in range(10)])
    acts = fk.Rig(ctl, venue).run().document["activities"]
    assert acts["pages"] == ctl.ACTIVITIES_MAX_PAGES
    assert len(venue.activity_urls) == ctl.ACTIVITIES_MAX_PAGES
    assert acts["stop_reason"] == "PAGE_CAP"


def test_q5_zero_rows_is_stated_explicitly(ctl: Any) -> None:
    venue = fk.FakeVenue()
    _paged(venue, _page([_TRADE_ROW], eof=True))
    acts = fk.Rig(ctl, venue).run().document["activities"]
    assert acts["stop_reason"] == "EOF"
    assert acts["d1_cases_found"] == 0
    assert acts["position_resolution"]["rows"] == 0
    assert acts["no_position_resolution_rows"] is True


def test_q5_a_failed_first_page_is_recorded_and_not_paged(ctl: Any) -> None:
    venue = fk.FakeVenue()
    venue.activities_status = 500
    result = fk.Rig(ctl, venue).run()
    assert result.document["activities"]["http_status"] == 500
    assert result.document["activities"]["pages"] == 1
    assert result.exit_code == 0
    assert len(venue.activity_urls) == 1


def test_q5_paging_stops_when_the_aux_read_budget_is_spent(ctl: Any) -> None:
    venue = fk.FakeVenue()
    _paged(venue, *[_page([_TRADE_ROW], eof=False, cursor=f"C{i}") for i in range(10)])
    budget = ctl.Budget(max_aux_gets=0)
    result = fk.Rig(ctl, venue, budget=budget).run()
    assert result.document["activities"]["stop_reason"] == "BUDGET"
    assert len(venue.activity_urls) == 1


def test_q5_records_enum_counts_sign_classes_and_row_path_sets_without_values(
    ctl: Any,
) -> None:
    other = json.loads(json.dumps(_PR_ROW))
    other["positionResolution"]["beforePosition"]["netPosition"] = "0"
    other["positionResolution"]["afterPosition"].pop("expired")
    cap = ctl.capture_activity_pages([_page([_PR_ROW, _PR_ROW, other], eof=True)])
    pr = cap["position_resolution"]
    assert pr["rows"] == 3
    assert pr["enum_counts"]["positionResolution.side"] == {"POSITION_SIDE_LONG": 3}
    assert pr["enum_counts"]["positionResolution.outcome"] == {"OUTCOME_SIDE_NO": 3}
    assert pr["sign_classes"]["positionResolution.beforePosition.netPosition"] == ["+", "0"]
    assert pr["sign_classes"]["positionResolution.beforePosition.cost.value"] == ["-"]
    shapes = {tuple(item["key_paths"]): item["count"] for item in pr["row_path_sets"]}
    assert sorted(shapes.values()) == [1, 2]
    text = json.dumps(cap)
    for leaked in ("123.45", "TRADEID98765", "tc-temp-nychigh", "-123", "CURSOR"):
        assert leaked not in text, leaked


def test_q5_the_single_page_capture_keeps_its_shape(ctl: Any) -> None:
    cap = ctl.capture_activity_shape(_page([_PR_ROW], eof=True))
    assert cap["status"] == "OK"
    assert cap["position_resolution"]["rows"] == 1
    assert ctl.capture_activity_shape(None)["status"] == "UNREADABLE"


# ------------------------------------------------------------------ R1 node detection

NODE_ARGV = b"/home/jon/breezy/.venv/bin/python\0/home/jon/breezy/.venv/bin/breezy-trade\0"
SUPERVISOR_ARGV = (
    b"/home/jon/breezy/.venv/bin/python\0/home/jon/breezy/.venv/bin/breezy-trade-supervisor\0"
    b"breezy-trade-supervisor-daily\0"
)


def _proc(root: Path, pid: int, argv: bytes) -> None:
    entry = root / str(pid)
    entry.mkdir(parents=True)
    (entry / "cmdline").write_bytes(argv)


def _probe(ctl: Any, tmp_path: Path, *, units: str = "", **kw: Any) -> None:
    proc = tmp_path / "proc"
    proc.mkdir(exist_ok=True)
    locks = tmp_path / "locks"
    if not locks.exists():
        locks.write_text("", encoding="utf-8")
    env = tmp_path / "breezy-trade.env"
    if not env.exists():
        env.write_text(f"POLYMARKET_US_EXEC_STATE_DB={tmp_path}/store.db\n", encoding="utf-8")
    ctl.probe_trade_node(
        list_node_units=lambda: units,
        proc_root=kw.get("proc_root", proc),
        locks_path=kw.get("locks_path", locks),
        trade_env=kw.get("trade_env", env),
    )


def test_r1_supervisor_active_and_no_node_is_allowed(ctl: Any, tmp_path: Path) -> None:
    _proc(tmp_path / "proc", 100, SUPERVISOR_ARGV)
    _proc(tmp_path / "proc", 101, b"/usr/bin/python3\0scripts/venue/maker_positive_control.py\0")
    _probe(ctl, tmp_path)


def test_r1_supervisor_active_and_a_node_process_refuses(ctl: Any, tmp_path: Path) -> None:
    _proc(tmp_path / "proc", 100, SUPERVISOR_ARGV)
    _proc(tmp_path / "proc", 4242, NODE_ARGV)
    with pytest.raises(ctl.Refusal) as excinfo:
        _probe(ctl, tmp_path)
    assert excinfo.value.code == "TRADE_NODE_PROCESS_PRESENT"


def test_r1_a_hand_launched_node_in_a_scope_is_seen_by_its_process(
    ctl: Any, tmp_path: Path
) -> None:
    _proc(tmp_path / "proc", 5150, NODE_ARGV)
    with pytest.raises(ctl.Refusal):
        _probe(ctl, tmp_path, units="")


def test_r1_a_real_process_whose_argv_ends_in_the_node_entry_is_detected(
    ctl: Any, tmp_path: Path
) -> None:
    script = tmp_path / "breezy-trade"
    script.write_text("#!/bin/sh\nwhile :; do sleep 1; done\n", encoding="utf-8")
    script.chmod(0o700)
    child = subprocess.Popen([str(script)], stdin=subprocess.DEVNULL)
    try:
        with pytest.raises(ctl.Refusal) as excinfo:
            ctl.probe_trade_node(
                list_node_units=lambda: "",
                proc_root=Path("/proc"),
                locks_path=Path("/proc/locks"),
                trade_env=_env(tmp_path),
            )
        assert excinfo.value.code == "TRADE_NODE_PROCESS_PRESENT"
    finally:
        child.terminate()
        child.wait(timeout=10)


def _env(tmp_path: Path) -> Path:
    env = tmp_path / "breezy-trade.env"
    env.write_text(f"POLYMARKET_US_EXEC_STATE_DB={tmp_path}/store.db\n", encoding="utf-8")
    return env


def test_r1_an_unreadable_process_entry_refuses(ctl: Any, tmp_path: Path) -> None:
    broken = tmp_path / "proc" / "77"
    (broken / "cmdline").mkdir(parents=True)  # a directory where the file should be
    with pytest.raises(ctl.Refusal) as excinfo:
        _probe(ctl, tmp_path)
    assert excinfo.value.code == "NODE_PROBE_ERROR"


def test_r1_a_missing_proc_root_refuses(ctl: Any, tmp_path: Path) -> None:
    with pytest.raises(ctl.Refusal) as excinfo:
        _probe(ctl, tmp_path, proc_root=tmp_path / "no-such-proc")
    assert excinfo.value.code == "NODE_PROBE_ERROR"


def _lock_entry(lock_file: Path, pid: int, kind: str = "FLOCK") -> str:
    st = lock_file.stat()
    major, minor = os.major(st.st_dev), os.minor(st.st_dev)
    return f"1: {kind}  ADVISORY  WRITE {pid} {major:02x}:{minor:02x}:{st.st_ino} 0 EOF\n"


def test_r1_a_held_intent_flock_refuses(ctl: Any, tmp_path: Path) -> None:
    (tmp_path / "proc").mkdir()
    lock_file = tmp_path / "store.db.intent.lock"
    lock_file.write_text("", encoding="utf-8")
    (tmp_path / "locks").write_text(_lock_entry(lock_file, 999), encoding="utf-8")
    with pytest.raises(ctl.Refusal) as excinfo:
        _probe(ctl, tmp_path)
    assert excinfo.value.code == "TRADE_NODE_LOCK_HELD"


def test_r1_a_free_or_absent_lock_and_a_posix_entry_do_not_refuse(ctl: Any, tmp_path: Path) -> None:
    (tmp_path / "proc").mkdir()
    _probe(ctl, tmp_path)  # lock file absent: the node never ran here
    lock_file = tmp_path / "store.db.intent.lock"
    lock_file.write_text("", encoding="utf-8")
    (tmp_path / "locks").write_text(_lock_entry(lock_file, 999, kind="POSIX"), encoding="utf-8")
    _probe(ctl, tmp_path)


@pytest.mark.parametrize("missing", ["locks", "env", "env-key"])
def test_r1_an_unreadable_lock_source_refuses(ctl: Any, tmp_path: Path, missing: str) -> None:
    (tmp_path / "proc").mkdir()
    env = _env(tmp_path)
    locks = tmp_path / "locks"
    locks.write_text("", encoding="utf-8")
    if missing == "locks":
        locks = tmp_path / "no-locks"
    elif missing == "env":
        env = tmp_path / "no.env"
    else:
        env.write_text("OTHER=1\n", encoding="utf-8")
    with pytest.raises(ctl.Refusal) as excinfo:
        _probe(ctl, tmp_path, locks_path=locks, trade_env=env)
    assert excinfo.value.code == "NODE_PROBE_ERROR"


@pytest.mark.parametrize(
    "units",
    [
        "breezy-node-handrelaunch-20261022T0100Z.scope loaded active running hand relaunch\n",
        "breezy-node-handrelaunch-20261022T0100Z.service loaded activating start x\n",
        "breezy-trade-node.service loaded active running node\n",
    ],
)
def test_r1_an_active_node_unit_or_scope_refuses(ctl: Any, tmp_path: Path, units: str) -> None:
    (tmp_path / "proc").mkdir()
    with pytest.raises(ctl.Refusal) as excinfo:
        _probe(ctl, tmp_path, units=units)
    assert excinfo.value.code == "TRADE_NODE_UNIT_ACTIVE"


def test_r1_quiet_node_units_other_scopes_and_the_supervisor_do_not_refuse(
    ctl: Any, tmp_path: Path
) -> None:
    (tmp_path / "proc").mkdir()
    units = (
        "breezy-node-handrelaunch-20261021T0100Z.scope loaded inactive dead x\n"
        "breezy-node-old.service loaded failed failed x\n"
        "app-gnome-foo.scope loaded active running Foo\n" + SUPERVISOR_ONLY
    )
    _probe(ctl, tmp_path, units=units)


def test_r1_an_unparseable_unit_listing_refuses(ctl: Any, tmp_path: Path) -> None:
    (tmp_path / "proc").mkdir()
    with pytest.raises(ctl.Refusal):
        _probe(ctl, tmp_path, units="garbage\n")


def test_r1_the_run_refuses_before_any_venue_contact_when_a_node_process_exists(
    ctl: Any, tmp_path: Path
) -> None:
    proc = tmp_path / "proc"
    _proc(proc, 100, SUPERVISOR_ARGV)
    _proc(proc, 4242, NODE_ARGV)

    def probe() -> None:
        _probe(ctl, tmp_path)

    rig = fk.Rig(ctl)
    assert asyncio.run(ctl.run(RUN_DATE, _deps(ctl, rig, tmp_path, probe_node=probe))) == 2
    assert rig.post_client.calls == []
    assert rig.venue.requests == []


def test_r1_the_run_proceeds_when_only_the_supervisor_is_up(ctl: Any, tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    _proc(proc, 100, SUPERVISOR_ARGV)

    def probe() -> None:
        _probe(ctl, tmp_path)

    rig = fk.Rig(ctl)
    assert asyncio.run(ctl.run(RUN_DATE, _deps(ctl, rig, tmp_path, probe_node=probe))) == 0


def test_r1_production_wiring_probes_the_real_node_not_a_no_op(ctl: Any) -> None:
    deps = ctl._production_deps()
    assert deps.probe_node is ctl.probe_production_node


# --------------------------------------------------------- R2 create in doubt


def test_r2_a_5xx_after_the_venue_booked_the_order_is_cleaned_up_by_listing(ctl: Any) -> None:
    venue = fk.FakeVenue()
    venue.create_then_500_nth = 1
    rig = fk.Rig(ctl, venue)
    result = rig.run()
    assert result.exit_code != 0
    assert venue.alive_own() == []
    assert result.document["order_ids"] == {}  # no id was ever learned
    ops = [step["op"] for step in result.document["steps"]]
    assert "cleanup_by_listing" in ops


def test_r2_a_transport_exception_after_the_venue_booked_the_order_is_cleaned_up(
    ctl: Any,
) -> None:
    venue = fk.FakeVenue()
    venue.create_then_raise_nth = 1
    rig = fk.Rig(ctl, venue)
    result = rig.run()
    assert result.exit_code != 0
    assert venue.alive_own() == []
    assert "cleanup_by_listing" in [step["op"] for step in result.document["steps"]]


def test_r2_a_definite_4xx_refusal_does_not_trigger_the_listing_sweep(ctl: Any) -> None:
    rig = fk.Rig(ctl)

    def refuse(_payload: Any) -> Any:
        return fk._json(400, {"code": 3})

    rig.venue._create = refuse  # type: ignore[method-assign,assignment]
    result = rig.run()
    assert result.exit_code != 0
    assert "cleanup_by_listing" not in [s["op"] for s in result.document["steps"]]


# ---------------------------------------------------- R3 signals + usage doc


def test_r3_termination_signals_raise_keyboard_interrupt(ctl: Any) -> None:
    previous = ctl.install_termination_handlers()
    try:
        for sig in (signal.SIGTERM, signal.SIGHUP):
            with pytest.raises(KeyboardInterrupt):
                signal.raise_signal(sig)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def test_r3_a_sigterm_mid_run_still_cleans_up_and_writes_the_evidence(
    ctl: Any, tmp_path: Path
) -> None:
    rig = fk.Rig(ctl)
    polls = {"n": 0}

    async def sleep_then_term(seconds: float) -> None:
        await rig.venue.sleep(seconds)
        polls["n"] += 1
        if polls["n"] == 2:  # inside S-6, B resting
            signal.raise_signal(signal.SIGTERM)

    previous = ctl.install_termination_handlers()
    try:
        with pytest.raises(KeyboardInterrupt):
            asyncio.run(ctl.run(RUN_DATE, _deps(ctl, rig, tmp_path, sleep=sleep_then_term)))
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    assert rig.venue.alive_own() == []
    files = list((tmp_path / "b2").glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding="utf-8"))["outcome"] == "FAIL"


def test_r3_the_script_documents_running_under_a_user_scope() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "systemd-run --user --scope" in text
    assert "install_termination_handlers()" in text  # main installs them


# ------------------------------------------------------------- R4 leftover orders


def test_r4_an_order_that_may_still_rest_is_announced_loudly_and_exits_nonzero(
    ctl: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    venue = fk.FakeVenue()
    venue.fail_cancel_one = True
    rig = fk.Rig(ctl, venue)
    assert asyncio.run(ctl.run(RUN_DATE, _deps(ctl, rig, tmp_path))) == 1
    doc = json.loads(next((tmp_path / "b2").glob("*.json")).read_text(encoding="utf-8"))
    leftover = doc["cleanup"]["leftover"]
    assert leftover and all(i in venue.alive_own() for i in leftover)
    err = capsys.readouterr().err
    for order_id in leftover:
        assert f"order {order_id} may rest; cancel by hand" in err


def test_r4_a_clean_run_announces_nothing(
    ctl: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = fk.Rig(ctl)
    assert asyncio.run(ctl.run(RUN_DATE, _deps(ctl, rig, tmp_path))) == 0
    assert "cancel by hand" not in capsys.readouterr().err


# ------------------------------------------------------------------- R5 hardening


def test_r5_cleanup_by_listing_cancels_only_own_shape_orders(ctl: Any) -> None:
    venue = fk.FakeVenue()
    venue.create_then_500_nth = 3  # B booked, id unknown
    foreign_a = venue.add_foreign_order(fk.SLUG_X)  # same slug, not our shape
    venue.orders[foreign_a]["quantity"] = 5
    foreign_b = venue.add_foreign_order(fk.SLUG_Y)
    venue.orders[foreign_b]["price"] = {"value": "0.50", "currency": "USD"}
    foreign_c = venue.add_foreign_order(fk.SLUG_Y)  # own price and qty but no goodTillTime
    rig = fk.Rig(ctl, venue)
    rig.run()
    assert venue.alive_own() == []
    for order_id in (foreign_a, foreign_b, foreign_c):
        assert venue.orders[order_id]["state"] == "ORDER_STATE_NEW"


def test_r5_id_shaped_keys_are_never_recorded(ctl: Any) -> None:
    payload = {
        "OWNORDER0001": {"state": 1},
        "A1B2C3D4E5F6": 1,
        "0123456789abcdef0123": 1,
        "ab12cdef34gh56ij78kl90": 1,
        "synchronousExecution": 1,
        "orders": [{"id": 1, "marketSlug": 2}],
    }
    paths = ctl.key_paths(payload)
    assert paths == [
        "<key>",
        "<key>.state",
        "orders",
        "orders[].id",
        "orders[].marketSlug",
        "synchronousExecution",
    ]


def test_r5_id_shaped_keys_do_not_become_enum_paths(ctl: Any) -> None:
    cap = ctl.capture_activity_pages(
        [
            {
                "activities": [
                    {
                        "type": "ACTIVITY_TYPE_POSITION_RESOLUTION",
                        "OWNORDER0001": "ORDER_STATE_NEW",
                    }
                ],
                "eof": True,
            }
        ]
    )
    assert "OWNORDER0001" not in json.dumps(cap)


@pytest.mark.parametrize(("payload", "complete"), fk.OPEN_ORDERS_ENVELOPES)
def test_open_orders_completeness_follows_the_exec_rule(
    ctl: Any, payload: Any, complete: bool
) -> None:
    assert (ctl.open_order_ids(payload) is not None) is complete
    assert ctl.open_order_ids({"orders": [{"id": "A1"}]}) == frozenset({"A1"})


@pytest.mark.parametrize("tail", [{"orders": [], "eof": False}, {"orders": [], "nextCursor": "C"}])
def test_the_final_check_treats_an_incomplete_listing_as_unknown(
    ctl: Any, tail: dict[str, Any]
) -> None:
    venue = fk.FakeVenue()
    original = venue.handle_get
    seen = {"open": 0}

    def incomplete_at_the_end(url: str) -> Any:
        if url.endswith("/v1/orders/open"):
            seen["open"] += 1
            if seen["open"] >= 2:  # foreign check passes, the final listing is incomplete
                venue.requests.append(("GET", "/v1/orders/open"))
                return fk._json(200, tail)
        return original(url)

    venue.handle_get = incomplete_at_the_end  # type: ignore[method-assign]
    result = fk.Rig(ctl, venue).run()
    assert result.document["final_account_clean"] is None
    assert result.exit_code != 0


def test_a_preflight_listing_without_eof_is_complete_and_proceeds(ctl: Any, tmp_path: Path) -> None:
    venue = fk.FakeVenue()
    venue.open_orders_body_override = b'{"orders": []}'
    rig = fk.Rig(ctl, venue)
    assert asyncio.run(ctl.run(RUN_DATE, _deps(ctl, rig, tmp_path))) != 2
    assert rig.post_client.calls != []


def test_aux_budget_is_separate_and_bounded(ctl: Any) -> None:
    budget = ctl.Budget()
    assert ctl.MAX_GETS == 40
    for _ in range(ctl.MAX_AUX_GETS):
        budget.spend_aux_get()
    with pytest.raises(ctl.BudgetExhausted):
        budget.spend_aux_get()
    assert budget.gets == 0
    plan = ctl.QUOTE_SCAN_CAP + 3 + 3 + (ctl.ACTIVITIES_MAX_PAGES - 1)
    assert plan <= ctl.MAX_AUX_GETS
