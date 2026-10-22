"""ARM B2 -- the maker positive-control script, offline (no venue contact).

Authority: ``ARM_MAKER_SHARP_2026-10-21/plan_r1.md`` row B2, ``plan_r2_delta.md`` D3,
``plan_r3_delta.md`` R7 + R13, ``S4_exec_resting_order_path_plan_r4_delta.md`` section 2 WP6.

Every test drives the real script over :mod:`tests.unit.b2_control_fakes`: the real
``PolymarketUSHttpClient`` and ``PolymarketUSWriteTransport`` run over an in-memory venue.
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import stat
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from tests.unit import b2_control_fakes as fk

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "venue" / "polymarket_us_maker_positive_control.py"
CORE_PATH = REPO_ROOT / "scripts" / "venue" / "_maker_control_core.py"
RUN_DATE = "2026-10-22"

SUPERVISOR_ONLY = (
    "breezy-trade-supervisor.service loaded active running Breezy daily trade-node supervisor\n"
)


@pytest.fixture(scope="module")
def ctl() -> Any:
    return fk.load_control()


def _deps(
    ctl: Any,
    rig: fk.Rig,
    tmp_path: Path,
    *,
    today: str = RUN_DATE,
    units: str = SUPERVISOR_ONLY,
    calls: list[str] | None = None,
) -> Any:
    log = calls if calls is not None else []

    def list_units() -> str:
        log.append("list_units")
        return units

    def probe_node() -> None:
        log.append("probe_node")

    def load_env() -> dict[str, str]:
        log.append("load_env")
        return {"POLYMARKET_US_USER_AGENT": "ua"}

    def build_session(_env: Any) -> Any:
        log.append("build_session")
        return rig.session

    return ctl.Deps(
        today_utc=lambda: today,
        list_units=list_units,
        probe_node=probe_node,
        load_env=load_env,
        build_session=build_session,
        sleep=rig.venue.sleep,
        evidence_dir=tmp_path / "b2",
        stamp=lambda: "20261022T120000Z",
    )


# ------------------------------------------------------------------------ constants


def test_budget_constants_are_the_spec_values(ctl: Any) -> None:
    assert (ctl.MAX_CREATES, ctl.MAX_CANCELS, ctl.MAX_GETS) == (4, 3, 40)
    assert ctl.PROBE_PRICE == Decimal("0.01")
    assert ctl.PROBE_QUANTITY == 1
    assert ctl.GTD_CEILING_SECS == 600
    assert ctl.REST_GTD_SECS < ctl.GTD_CEILING_SECS
    assert ctl.SHORT_GTD_SECS < ctl.REST_GTD_SECS


def test_the_worst_case_get_plan_fits_the_budget(ctl: Any) -> None:
    # activities, markets, preflight, 2x A confirm, A' + B confirm, foreign check,
    # post cancel-all confirms, expiry polls, final clean check
    worst = 3 + 3 * 5 + 1 + 2 * ctl.CONFIRM_POLLS + ctl.EXPIRY_POLLS + 1
    assert worst <= ctl.MAX_GETS


def test_the_worst_case_cancels_fit_the_budget_including_cleanup(ctl: Any) -> None:
    # cancel A (1) + cleanup of A' and B (2)
    assert 1 + 2 <= ctl.MAX_CANCELS


# --------------------------------------------------------------------------- budget


def test_budget_refuses_the_call_past_each_ceiling(ctl: Any) -> None:
    budget = ctl.Budget()
    for _ in range(ctl.MAX_CREATES):
        budget.spend_create()
    with pytest.raises(ctl.BudgetExhausted):
        budget.spend_create()
    for _ in range(ctl.MAX_CANCELS):
        budget.spend_cancel()
    with pytest.raises(ctl.BudgetExhausted):
        budget.spend_cancel()
    for _ in range(ctl.MAX_GETS):
        budget.spend_get()
    with pytest.raises(ctl.BudgetExhausted):
        budget.spend_get()
    assert (budget.creates, budget.cancels, budget.gets) == (4, 3, 40)


def test_an_exhausted_create_budget_sends_no_further_post(ctl: Any) -> None:
    rig = fk.Rig(ctl, budget=ctl.Budget(max_creates=0))
    asyncio.run(rig.session.list_markets())
    with pytest.raises(ctl.BudgetExhausted):
        asyncio.run(rig.session.rest("A", fk.SLUG_X, ctl.REST_GTD_SECS))
    assert rig.post_client.calls == []


def test_an_exhausted_cancel_budget_sends_no_further_post(ctl: Any) -> None:
    rig = fk.Rig(ctl, budget=ctl.Budget(max_cancels=0))
    with pytest.raises(ctl.BudgetExhausted):
        asyncio.run(rig.session.retract_order("OWNORDER0001", fk.SLUG_X))
    with pytest.raises(ctl.BudgetExhausted):
        asyncio.run(rig.session.cancel_slugs([fk.SLUG_X]))
    assert rig.post_client.calls == []


def test_an_exhausted_get_budget_sends_no_further_get(ctl: Any) -> None:
    rig = fk.Rig(ctl, budget=ctl.Budget(max_gets=1))
    asyncio.run(rig.session.get_open_orders())
    with pytest.raises(ctl.BudgetExhausted):
        asyncio.run(rig.session.get_open_orders())
    with pytest.raises(ctl.BudgetExhausted):
        asyncio.run(rig.session.get_order("OWNORDER0001"))
    assert rig.venue.requests == [("GET", "/v1/orders/open")]


def test_a_run_with_a_tiny_get_budget_stops_calling_and_exits_nonzero(ctl: Any) -> None:
    rig = fk.Rig(ctl, budget=ctl.Budget(max_gets=6))
    result = rig.run()
    assert result.exit_code != 0
    assert rig.budget.gets <= 6
    assert sum(1 for m, _ in rig.venue.requests if m == "GET") <= 6 + rig.budget.aux_gets
    assert rig.venue.alive_own() == []  # best-effort cleanup still cancelled by id


# --------------------------------------------------------------------------- GTD cap


def test_a_gtd_beyond_the_ceiling_is_refused_before_any_post(ctl: Any) -> None:
    rig = fk.Rig(ctl)
    asyncio.run(rig.session.list_markets())
    with pytest.raises(ValueError, match="GTD"):
        asyncio.run(rig.session.rest("A", fk.SLUG_X, ctl.GTD_CEILING_SECS + 1))
    assert rig.post_client.calls == []


def test_every_posted_body_is_gtd_within_ten_minutes_of_now(ctl: Any) -> None:
    rig = fk.Rig(ctl)
    result = rig.run()
    assert result.exit_code == 0
    creates = [b for p, b in rig.posts() if p == "/v1/orders"]
    assert len(creates) == 3
    for body in creates:
        expire_ns = fk._parse_utc(body["goodTillTime"])
        assert (
            fk.START_NS < expire_ns <= fk.START_NS + 600 * fk.NS + 120 * fk.NS
        )  # run drifts <2min


def test_the_send_time_ceiling_check_catches_a_body_that_drifted_past_it(ctl: Any) -> None:
    body = {"goodTillTime": "2026-10-22T12:11:00Z"}
    now_ns = fk._parse_utc("2026-10-22T12:00:00Z")
    with pytest.raises(ValueError, match="GTD"):
        ctl.assert_gtd_within_ceiling(body, now_ns=now_ns)
    ctl.assert_gtd_within_ceiling({"goodTillTime": "2026-10-22T12:10:00Z"}, now_ns=now_ns)
    with pytest.raises(ValueError, match="GTD"):
        ctl.assert_gtd_within_ceiling({"goodTillTime": "2026-10-22T11:59:59Z"}, now_ns=now_ns)
    with pytest.raises(ValueError, match="GTD"):
        ctl.assert_gtd_within_ceiling({}, now_ns=now_ns)


# ------------------------------------------------------------------ happy-path run


def test_the_full_sequence_passes_s1_s2_s6_and_leaves_the_account_clean(ctl: Any) -> None:
    rig = fk.Rig(ctl)
    result = rig.run()
    doc = result.document
    assert result.exit_code == 0
    assert doc["outcome"] == "PASS"
    assert doc["verdicts"] == {"S-1": "PASS", "S-2": "PASS", "S-6": "PASS"}
    assert doc["final_account_clean"] is True
    assert rig.venue.alive_all() == []
    assert doc["counts"] == {
        "creates": 3,
        "cancels": 2,
        "gets": rig.budget.gets,
        "aux_gets": rig.budget.aux_gets,
    }
    assert rig.budget.gets <= ctl.MAX_GETS
    assert set(doc["order_ids"]) == {"A", "A_prime", "B"}
    assert len(set(doc["order_ids"].values())) == 3


def test_the_sequence_order_is_rest_cancel_rerest_scoped_cancel_all_then_expiry(
    ctl: Any,
) -> None:
    rig = fk.Rig(ctl)
    rig.run()
    writes = [(p, b) for p, b in rig.posts()]
    kinds = [
        "create" if p == "/v1/orders" else "cancel-all" if p.endswith("/open/cancel") else "cancel"
        for p, _ in writes
    ]
    assert kinds == ["create", "cancel", "create", "create", "cancel-all"]


def test_bodies_are_the_resting_body_built_by_submit_chain(ctl: Any) -> None:
    rig = fk.Rig(ctl)
    rig.run()
    creates = [b for p, b in rig.posts() if p == "/v1/orders"]
    for body in creates:
        assert set(body) == ctl.submit_chain.RESTING_ORDER_BODY_KEYS
        assert body["outcomeSide"] == "OUTCOME_SIDE_NO"
        assert body["action"] == "ORDER_ACTION_BUY"
        assert body["quantity"] == 1
        assert body["tif"] == "TIME_IN_FORCE_GOOD_TILL_DATE"
        assert body["price"]["value"] == "0.99"  # BUY NO at 0.01 is the YES-side complement
        assert "synchronousExecution" not in body and "maxBlockTime" not in body
        assert "participateDontInitiate" not in body


def test_a_and_a_prime_rest_on_x_and_b_on_y_with_a_short_b_gtd(ctl: Any) -> None:
    rig = fk.Rig(ctl)
    result = rig.run()
    creates = [b for p, b in rig.posts() if p == "/v1/orders"]
    slugs = [b["marketSlug"] for b in creates]
    assert slugs[0] == slugs[1] == result.document["slugs"][0]
    assert slugs[2] == result.document["slugs"][1] != slugs[0]
    a_gtd = fk._parse_utc(creates[1]["goodTillTime"])
    b_gtd = fk._parse_utc(creates[2]["goodTillTime"])
    assert b_gtd < a_gtd


def test_per_order_cancel_body_is_exactly_the_market_slug(ctl: Any) -> None:
    rig = fk.Rig(ctl)
    result = rig.run()
    cancels = [(p, b) for p, b in rig.posts() if p.startswith("/v1/order/")]
    assert len(cancels) == 1
    path, body = cancels[0]
    assert path == f"/v1/order/{result.document['order_ids']['A']}/cancel"
    assert body == {"marketSlug": result.document["slugs"][0]}


def test_cancel_all_is_slug_scoped_to_exactly_x(ctl: Any) -> None:
    rig = fk.Rig(ctl)
    result = rig.run()
    assert rig.venue.cancel_all_bodies == [{"slugs": [result.document["slugs"][0]]}]
    assert rig.venue.account_wide_cancel_attempts == 0


def test_b_is_alive_after_the_scoped_cancel_all_and_expires_by_gtd(ctl: Any) -> None:
    rig = fk.Rig(ctl)
    result = rig.run()
    details = result.document["details"]
    assert details["s2_a_prime_state"] == "ORDER_STATE_CANCELED"
    assert details["s2_b_state_after_cancel_all"] == "ORDER_STATE_NEW"
    assert details["s6_final_state"] == "ORDER_STATE_EXPIRED"
    assert details["gtd_tif_echoed"] is True


def test_siblings_of_one_event_are_preferred_for_the_two_slugs(ctl: Any) -> None:
    rig = fk.Rig(ctl)
    result = rig.run()
    assert result.document["slugs_share_event"] is True
    assert result.document["slugs"] == [fk.SLUG_Y, fk.SLUG_X] or set(result.document["slugs"]) == {
        fk.SLUG_X,
        fk.SLUG_Y,
    }


def test_only_the_post_verbs_signed_are_the_three_write_paths(ctl: Any) -> None:
    rig = fk.Rig(ctl)
    rig.run()
    assert {m for m, _ in rig.write_signer.signed} == {"POST"}
    for _, path in rig.write_signer.signed:
        assert path == "/v1/orders" or path == "/v1/orders/open/cancel" or path.endswith("/cancel")


# ------------------------------------------------------------------ slug selection


def test_select_probe_slugs_excludes_low_closed_and_non_daily_markets(ctl: Any) -> None:
    payload = fk.markets_page(
        fk.SLUG_LOW, fk.SLUG_CLOSED, fk.SLUG_X, fk.SLUG_Z, closed=frozenset({fk.SLUG_CLOSED})
    )
    chosen = ctl.select_probe_slugs(payload, city_codes=("nyc", "mia", "lax"), now_ns=fk.START_NS)
    assert chosen is not None
    assert set(chosen.slugs) == {fk.SLUG_X, fk.SLUG_Z}
    assert chosen.share_event is False


def test_select_probe_slugs_returns_none_with_fewer_than_two_eligible(ctl: Any) -> None:
    payload = fk.markets_page(fk.SLUG_X, fk.SLUG_LOW)
    now = fk.START_NS
    assert ctl.select_probe_slugs(payload, city_codes=("nyc",), now_ns=now) is None
    assert ctl.select_probe_slugs({"markets": "nope"}, city_codes=("nyc",), now_ns=now) is None
    assert ctl.select_probe_slugs({}, city_codes=("nyc",), now_ns=now) is None


def test_no_eligible_slugs_means_no_write_and_a_nonzero_exit(ctl: Any) -> None:
    rig = fk.Rig(ctl, fk.FakeVenue(markets=fk.markets_page(fk.SLUG_X)))
    result = rig.run()
    assert result.exit_code != 0
    assert rig.post_client.calls == []
    assert result.document["failure"] == "NO_ELIGIBLE_SLUGS"


# ------------------------------------------------------------- S-2 and foreign orders


def test_s2_is_skipped_and_no_cancel_all_sent_when_a_foreign_order_appears(
    ctl: Any,
) -> None:
    venue = fk.FakeVenue()
    venue.foreign_after_creates = 3  # appears after B rests
    rig = fk.Rig(ctl, venue)
    result = rig.run()
    doc = result.document
    assert venue.cancel_all_bodies == []
    assert doc["verdicts"]["S-2"] == "SKIPPED_FOREIGN_ORDER"
    assert doc["verdicts"]["S-1"] == "PASS"
    assert doc["verdicts"]["S-6"] == "PASS"
    # A' was cancelled per order instead; the foreign order is untouched
    assert doc["counts"]["cancels"] == 2
    assert venue.alive_own() == []
    assert len(venue.alive_all()) == 1  # the foreign one
    assert doc["final_account_clean"] is False
    assert result.exit_code != 0  # the account is not clean at the end: reported, not hidden


def test_an_unreadable_open_orders_list_is_treated_as_foreign_for_s2(ctl: Any) -> None:
    class Flaky(fk.FakeVenue):
        def handle_get(self, url: str) -> Any:
            # run_control (no preflight here) reads the open-orders list once: the S-2 check
            if url.endswith("/v1/orders/open") and not self.requests_for_open():
                self.requests.append(("GET", "/v1/orders/open"))
                return fk._resp(200, b"not json")
            return super().handle_get(url)

        def requests_for_open(self) -> list[tuple[str, str]]:
            return [r for r in self.requests if r == ("GET", "/v1/orders/open")]

    rig = fk.Rig(ctl, Flaky())
    result = rig.run()
    assert result.document["verdicts"]["S-2"] == "SKIPPED_FOREIGN_ORDER"
    assert rig.venue.cancel_all_bodies == []


def test_s2_fails_when_the_cancel_all_leaks_onto_the_other_slug(ctl: Any) -> None:
    venue = fk.FakeVenue()
    venue.leak_cancel_all = True
    rig = fk.Rig(ctl, venue)
    result = rig.run()
    assert result.document["verdicts"]["S-2"] == "FAIL"
    assert result.document["verdicts"]["S-6"] == "NOT_RUN"
    assert result.exit_code != 0
    assert venue.alive_own() == []


def test_s2_fails_when_the_cancel_all_is_refused(ctl: Any) -> None:
    venue = fk.FakeVenue()
    venue.fail_cancel_all = True
    rig = fk.Rig(ctl, venue)
    result = rig.run()
    assert result.document["verdicts"]["S-2"] == "FAIL"
    assert result.exit_code != 0
    assert venue.alive_own() == []  # cleanup cancelled A' and B by id
    assert result.document["cleanup"]["cancelled"]


# ------------------------------------------------------------------- S-6 and cleanup


def test_s6_fails_when_b_never_expires_within_the_poll_budget_and_cleanup_cancels_it(
    ctl: Any,
) -> None:
    venue = fk.FakeVenue()
    venue.never_expire = True
    rig = fk.Rig(ctl, venue)
    result = rig.run()
    assert result.document["verdicts"]["S-6"] == "FAIL"
    assert result.exit_code != 0
    assert venue.alive_own() == []
    assert rig.budget.gets <= ctl.MAX_GETS
    assert rig.budget.cancels <= ctl.MAX_CANCELS


def test_a_venue_expiry_lag_inside_the_poll_window_still_passes(ctl: Any) -> None:
    venue = fk.FakeVenue()
    venue.expiry_lag_s = 90
    rig = fk.Rig(ctl, venue)
    assert rig.run().document["verdicts"]["S-6"] == "PASS"


def test_a_failed_create_cancels_every_own_order_by_id_and_exits_nonzero(ctl: Any) -> None:
    venue = fk.FakeVenue()
    venue.fail_create_nth = 3  # B
    rig = fk.Rig(ctl, venue)
    result = rig.run()
    assert result.exit_code != 0
    assert venue.alive_own() == []
    cancels = [p for p, _ in rig.posts() if p.startswith("/v1/order/")]
    assert len(cancels) == 2  # A earlier, then A' in cleanup
    assert rig.venue.account_wide_cancel_attempts == 0
    assert venue.cancel_all_bodies == []  # cleanup never uses the account-scoped verb
    assert result.document["cleanup"]["cancelled"]
    assert result.document["verdicts"]["S-6"] == "NOT_RUN"


def test_an_exception_mid_sequence_still_cleans_up_by_id(ctl: Any) -> None:
    venue = fk.FakeVenue()
    venue.raise_on_cancel_all = RuntimeError("boom")
    rig = fk.Rig(ctl, venue)
    result = rig.run()
    assert result.exit_code != 0
    assert venue.alive_own() == []
    assert result.document["failure"] == "RuntimeError"


def test_a_cancelled_run_cleans_up_then_propagates(ctl: Any) -> None:
    venue = fk.FakeVenue()
    venue.raise_on_cancel_all = asyncio.CancelledError()
    rig = fk.Rig(ctl, venue)
    with pytest.raises(asyncio.CancelledError):
        rig.run()
    assert venue.alive_own() == []


def test_a_200_create_with_no_valid_id_falls_back_to_cancelling_probe_slug_orders(
    ctl: Any,
) -> None:
    venue = fk.FakeVenue()
    original = venue._create

    def weird(payload: Any) -> Any:
        resp = original(payload)
        return fk._json(200, {"unexpected": True}) if resp.status == 200 else resp

    venue._create = weird  # type: ignore[method-assign]
    rig = fk.Rig(ctl, venue)
    result = rig.run()
    assert result.exit_code != 0
    assert venue.alive_own() == []


# -------------------------------------------------------------- empty-slug cancel-all


@pytest.mark.parametrize(
    "bad",
    [[], [""], ["x\n"], [fk.SLUG_X, fk.SLUG_X], "tc-temp", None, (), [fk.SLUG_X + "\n"]],
)
def test_no_empty_or_malformed_slug_cancel_all_is_constructible(ctl: Any, bad: Any) -> None:
    rig = fk.Rig(ctl)
    with pytest.raises((ValueError, TypeError)):
        asyncio.run(rig.session.cancel_slugs(bad))
    assert rig.post_client.calls == []
    assert rig.venue.account_wide_cancel_attempts == 0


def _tree() -> ast.Module:
    return ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))


def _both_trees() -> list[ast.Module]:
    return [_tree(), ast.parse(CORE_PATH.read_text(encoding="utf-8"))]


def _both_sources() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8") + CORE_PATH.read_text(encoding="utf-8")


def test_the_script_has_exactly_one_cancel_all_call_site_and_it_guards_emptiness() -> None:
    sites: list[tuple[str, ast.Call]] = []
    for fn in ast.walk(_tree()):
        if isinstance(fn, ast.AsyncFunctionDef | ast.FunctionDef):
            for node in ast.walk(fn):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "post_cancel_all"
                ):
                    sites.append((fn.name, node))
    assert [name for name, _ in sites] == ["cancel_slugs"]
    ((_, call),) = sites
    assert [k.arg for k in call.keywords] == ["headers", "slugs"]
    slugs_arg = next(k.value for k in call.keywords if k.arg == "slugs")
    assert isinstance(slugs_arg, ast.Name) and slugs_arg.id == "checked"
    fn = next(
        n
        for n in ast.walk(_tree())
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "cancel_slugs"
    )
    text = ast.unparse(fn)
    assert "if not checked" in text or "not slugs" in text


def test_the_script_never_imports_or_names_the_legacy_probe_or_its_cancel_all() -> None:
    for node in (n for tree in _both_trees() for n in ast.walk(tree)):
        if isinstance(node, ast.ImportFrom | ast.Import):
            names = [a.name for a in node.names] + [getattr(node, "module", None) or ""]
            for name in names:
                assert "write_signing_probe" not in name
                assert "_signed_post_cancel_all" not in name
        if isinstance(node, ast.Name | ast.Attribute):
            ident = node.id if isinstance(node, ast.Name) else node.attr
            assert ident != "_signed_post_cancel_all"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "write_signing_probe" not in node.value
    assert "_signed_post_cancel_all" not in _both_sources()


def test_no_literal_empty_slugs_payload_exists_in_the_script() -> None:
    for node in (n for tree in _both_trees() for n in ast.walk(tree)):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and key.value == "slugs":
                    assert not (isinstance(value, ast.List) and not value.elts)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "/v1/orders/open/cancel" not in node.value


# --------------------------------------------------------------------- preconditions


def _assert_nothing_sent(rig: fk.Rig) -> None:
    assert rig.post_client.calls == []
    assert rig.venue.requests == []


def test_a_wrong_run_date_refuses_before_any_io(ctl: Any, tmp_path: Path) -> None:
    rig = fk.Rig(ctl)
    calls: list[str] = []
    code = asyncio.run(ctl.run("2026-10-21", _deps(ctl, rig, tmp_path, calls=calls)))
    assert code == 2
    assert calls == []
    _assert_nothing_sent(rig)
    assert not (tmp_path / "b2").exists()


@pytest.mark.parametrize("bad", ["", "2026-1-22", "20261022", "2026-10-22 ", "2026-10-22\n", "x"])
def test_a_malformed_run_date_refuses_before_any_io(ctl: Any, tmp_path: Path, bad: str) -> None:
    rig = fk.Rig(ctl)
    calls: list[str] = []
    assert asyncio.run(ctl.run(bad, _deps(ctl, rig, tmp_path, calls=calls))) == 2
    assert calls == []
    _assert_nothing_sent(rig)


def test_an_active_trade_node_refuses_before_any_venue_contact(ctl: Any, tmp_path: Path) -> None:
    units = SUPERVISOR_ONLY + "breezy-trade-node-20261022.service loaded active running node\n"
    rig = fk.Rig(ctl)
    assert asyncio.run(ctl.run(RUN_DATE, _deps(ctl, rig, tmp_path, units=units))) == 2
    _assert_nothing_sent(rig)


@pytest.mark.parametrize("state", ["active", "activating", "reloading", "deactivating"])
def test_every_live_unit_state_counts_as_an_active_node(ctl: Any, state: str) -> None:
    with pytest.raises(ctl.Refusal):
        ctl.assert_no_trade_node(f"breezy-trade-node.service loaded {state} running x\n")


def test_the_supervisor_alone_and_an_empty_listing_are_accepted(ctl: Any) -> None:
    ctl.assert_no_trade_node(SUPERVISOR_ONLY)
    ctl.assert_no_trade_node("")
    ctl.assert_no_trade_node("breezy-trade-node.service loaded inactive dead x\n")
    ctl.assert_no_trade_node("breezy-trade-node.service loaded failed failed x\n")


def test_an_unparseable_unit_listing_fails_closed(ctl: Any) -> None:
    with pytest.raises(ctl.Refusal):
        ctl.assert_no_trade_node("garbage\n")


def test_a_systemctl_failure_refuses(ctl: Any, tmp_path: Path) -> None:
    rig = fk.Rig(ctl)
    deps = _deps(ctl, rig, tmp_path)

    def boom() -> str:
        raise ctl.Refusal("SYSTEMCTL_FAILED")

    deps = ctl.Deps(**{**deps.__dict__, "list_units": boom})
    assert asyncio.run(ctl.run(RUN_DATE, deps)) == 2
    _assert_nothing_sent(rig)


def test_a_non_empty_open_orders_list_refuses_before_any_write(ctl: Any, tmp_path: Path) -> None:
    venue = fk.FakeVenue()
    venue.add_foreign_order()
    rig = fk.Rig(ctl, venue)
    assert asyncio.run(ctl.run(RUN_DATE, _deps(ctl, rig, tmp_path))) == 2
    assert rig.post_client.calls == []
    assert not (tmp_path / "b2").exists()


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (500, b"{}"),
        (200, b"not json"),
        (200, b'{"orders": "x"}'),
        (200, b"{}"),
        (401, b"{}"),
        (200, b'{"orders": []}'),  # R5: a listing without eof is not a complete listing
        (200, b'{"orders": [], "eof": false}'),
    ],
)
def test_an_unreadable_or_failed_preflight_refuses(
    ctl: Any, tmp_path: Path, status: int, body: bytes
) -> None:
    venue = fk.FakeVenue()
    venue.open_orders_status = status
    venue.open_orders_body_override = body
    rig = fk.Rig(ctl, venue)
    assert asyncio.run(ctl.run(RUN_DATE, _deps(ctl, rig, tmp_path))) == 2
    assert rig.post_client.calls == []


def test_the_happy_path_through_run_writes_evidence_and_exits_zero(
    ctl: Any, tmp_path: Path
) -> None:
    rig = fk.Rig(ctl)
    assert asyncio.run(ctl.run(RUN_DATE, _deps(ctl, rig, tmp_path))) == 0
    files = list((tmp_path / "b2").glob("*.json"))
    assert len(files) == 1
    assert stat.S_IMODE(files[0].stat().st_mode) == 0o600


def test_the_cli_requires_the_run_date_flag(ctl: Any) -> None:
    with pytest.raises(SystemExit) as excinfo:
        ctl.parse_args([])
    assert excinfo.value.code != 0
    assert ctl.parse_args(["--run-date", RUN_DATE]).run_date == RUN_DATE


# ------------------------------------------------------------------------ credentials


def _env_file(directory: Path, *, key_in: Path | None = None, mode: int = 0o600) -> Path:
    key = (key_in or directory) / "polymarket_us_secret.key"
    key.write_text("k", encoding="utf-8")
    key.chmod(0o600)
    env = directory / "polymarket.env"
    env.write_text(
        f"POLYMARKET_US_KEY_ID=abc\nPOLYMARKET_US_SECRET_KEY_FILE={key}\n"
        "POLYMARKET_US_USER_AGENT=ua\n# comment\n\n",
        encoding="utf-8",
    )
    env.chmod(mode)
    return env


def test_credentials_load_only_from_the_config_directory_file(
    ctl: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    env_path = _env_file(config_dir)
    monkeypatch.setenv("POLYMARKET_US_KEY_ID", "FROM-PROCESS-ENV")
    loaded = ctl.load_env_file(env_path, config_dir=config_dir)
    assert loaded["POLYMARKET_US_KEY_ID"] == "abc"
    assert loaded["POLYMARKET_US_USER_AGENT"] == "ua"


def test_a_secret_key_file_outside_the_config_directory_refuses(ctl: Any, tmp_path: Path) -> None:
    config_dir, elsewhere = tmp_path / "cfg", tmp_path / "elsewhere"
    config_dir.mkdir()
    elsewhere.mkdir()
    env_path = _env_file(config_dir, key_in=elsewhere)
    with pytest.raises(ctl.Refusal):
        ctl.load_env_file(env_path, config_dir=config_dir)


def test_an_env_file_outside_the_config_directory_or_with_loose_mode_refuses(
    ctl: Any, tmp_path: Path
) -> None:
    config_dir, elsewhere = tmp_path / "cfg", tmp_path / "elsewhere"
    config_dir.mkdir()
    elsewhere.mkdir()
    with pytest.raises(ctl.Refusal):
        ctl.load_env_file(_env_file(elsewhere), config_dir=config_dir)
    loose = _env_file(config_dir, mode=0o644)
    with pytest.raises(ctl.Refusal):
        ctl.load_env_file(loose, config_dir=config_dir)
    with pytest.raises(ctl.Refusal):
        ctl.load_env_file(config_dir / "missing.env", config_dir=config_dir)


def test_a_symlinked_secret_key_into_the_config_directory_from_outside_refuses(
    ctl: Any, tmp_path: Path
) -> None:
    config_dir, elsewhere = tmp_path / "cfg", tmp_path / "elsewhere"
    config_dir.mkdir()
    elsewhere.mkdir()
    real = elsewhere / "real.key"
    real.write_text("k", encoding="utf-8")
    real.chmod(0o600)
    link = config_dir / "polymarket_us_secret.key"
    os.symlink(real, link)
    env = config_dir / "polymarket.env"
    env.write_text(
        f"POLYMARKET_US_KEY_ID=a\nPOLYMARKET_US_SECRET_KEY_FILE={link}\n", encoding="utf-8"
    )
    env.chmod(0o600)
    with pytest.raises(ctl.Refusal):
        ctl.load_env_file(env, config_dir=config_dir)


# --------------------------------------------------------------------------- evidence

_EVIDENCE_TOP_KEYS = {
    "schema",
    "run_date",
    "started_at",
    "finished_at",
    "constants",
    "counts",
    "slugs",
    "slugs_share_event",
    "order_ids",
    "steps",
    "quote_guard",
    "licenses",
    "fill_detected",
    "verdicts",
    "details",
    "activities",
    "cleanup",
    "final_account_clean",
    "outcome",
    "failure",
}


def test_the_evidence_document_has_the_closed_schema(ctl: Any) -> None:
    doc = fk.Rig(ctl).run().document
    assert set(doc) == _EVIDENCE_TOP_KEYS
    assert doc["schema"] == ctl.EVIDENCE_SCHEMA
    assert doc["constants"]["max_creates"] == 4
    assert doc["constants"]["max_cancels"] == 3
    assert doc["constants"]["max_gets"] == 40
    assert doc["constants"]["price"] == "0.01"
    assert doc["constants"]["gtd_ceiling_secs"] == 600
    for step in doc["steps"]:
        assert set(step) == {"n", "op", "url", "status", "keys"}


def test_the_evidence_carries_no_credential_header_signature_or_raw_body(
    ctl: Any, tmp_path: Path
) -> None:
    rig = fk.Rig(ctl)
    asyncio.run(ctl.run(RUN_DATE, _deps(ctl, rig, tmp_path)))
    text = next((tmp_path / "b2").glob("*.json")).read_text(encoding="utf-8")
    for forbidden in (
        fk.KEY_ID_SENTINEL,
        fk.SIGNATURE_SENTINEL,
        "X-PM",
        "x-pm",
        "Signature",
        "Authorization",
        "0.99",  # a raw price value from a body is not a recorded key name
    ):
        assert forbidden not in text, forbidden
    assert "?" not in text  # no query strings anywhere: urls pass through redact_url


def test_recorded_urls_are_redacted_and_carry_no_query_values(ctl: Any) -> None:
    rig = fk.Rig(ctl)
    doc = rig.run().document
    urls = [s["url"] for s in doc["steps"]]
    assert urls
    assert all(
        u.startswith(("https://api.example.invalid", "https://gateway.example.invalid"))
        for u in urls
    )
    assert all("limit=" not in u or "limit=REDACTED" in u or "?" not in u for u in urls)


def test_the_key_name_capture_of_the_async_rest_response_and_first_get(ctl: Any) -> None:
    doc = fk.Rig(ctl).run().document
    ops = {s["op"]: s for s in doc["steps"]}
    assert ops["rest_A"]["keys"] == ["id"]
    first_get = ops["get_A_1"]
    assert "order" in first_get["keys"] or "order.state" in first_get["keys"]
    assert "order.goodTillTime" in first_get["keys"]
    assert "order.state" in first_get["keys"]


def test_key_paths_emits_names_only_never_values(ctl: Any) -> None:
    paths = ctl.key_paths({"a": {"b": 1, "c": [{"d": "SECRET"}, {"e": 2}]}, "f": "VALUE"})
    assert paths == ["a", "a.b", "a.c", "a.c[].d", "a.c[].e", "f"]
    assert ctl.key_paths(["x"]) == []
    assert ctl.key_paths({"a": {"b": {"c": {"d": {"e": 1}}}}}) == ["a", "a.b", "a.b.c", "a.b.c.d"]


def test_evidence_files_are_written_exclusively_at_mode_0600(ctl: Any, tmp_path: Path) -> None:
    doc = fk.Rig(ctl).run().document
    old = os.umask(0o000)
    try:
        path = ctl.write_evidence(doc, tmp_path / "ev", stamp="20261022T120000Z")
    finally:
        os.umask(old)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text(encoding="utf-8"))["schema"] == ctl.EVIDENCE_SCHEMA
    with pytest.raises(FileExistsError):
        ctl.write_evidence(doc, tmp_path / "ev", stamp="20261022T120000Z")


def test_write_evidence_refuses_a_document_with_an_unknown_key_or_a_secret_shape(
    ctl: Any, tmp_path: Path
) -> None:
    doc = fk.Rig(ctl).run().document
    with pytest.raises(ValueError, match="schema"):
        ctl.write_evidence({**doc, "extra": 1}, tmp_path / "ev", stamp="s1")
    leaky = {**doc, "failure": "-----BEGIN PRIVATE KEY-----"}
    with pytest.raises(ValueError, match="secret"):
        ctl.write_evidence(leaky, tmp_path / "ev", stamp="s2")


def test_a_failed_run_still_writes_evidence_with_the_failure(ctl: Any, tmp_path: Path) -> None:
    venue = fk.FakeVenue()
    venue.fail_create_nth = 1
    rig = fk.Rig(ctl, venue)
    assert asyncio.run(ctl.run(RUN_DATE, _deps(ctl, rig, tmp_path))) == 1
    doc = json.loads(next((tmp_path / "b2").glob("*.json")).read_text(encoding="utf-8"))
    assert doc["outcome"] == "FAIL"
    assert doc["verdicts"]["S-1"] == "FAIL"


# ------------------------------------------------------------------ activities capture

_PR_ROW = {
    "type": "ACTIVITY_TYPE_POSITION_RESOLUTION",
    "positionResolution": {
        "marketSlug": "tc-temp-nychigh-2026-10-01-lt79f",
        "beforePosition": {"netPosition": "5", "cost": {"value": "123.45", "currency": "USD"}},
        "afterPosition": {"netPosition": "0", "expired": True},
        "updateTime": "2026-10-02T00:00:00Z",
        "tradeId": "TRADEID98765",
        "side": "LONG",
    },
}
_TRADE_ROW = {
    "type": "ACTIVITY_TYPE_TRADE",
    "trade": {"id": "TRADE000001", "price": {"value": "0.55"}, "state": "TRADE_STATE_CLEARED"},
}


def test_activity_capture_records_key_paths_and_enum_tokens_only(ctl: Any) -> None:
    page = {"activities": [_PR_ROW, _TRADE_ROW], "nextCursor": "CURSORSECRET", "eof": True}
    cap = ctl.capture_activity_shape(page)
    assert cap["top_level_keys"] == ["activities", "eof", "nextCursor"]
    assert cap["activity_types_seen"] == [
        "ACTIVITY_TYPE_POSITION_RESOLUTION",
        "ACTIVITY_TYPE_TRADE",
    ]
    pr = cap["position_resolution"]
    assert pr["rows"] == 1
    assert "positionResolution.beforePosition.cost.value" in pr["key_paths"]
    assert "positionResolution.afterPosition.expired" in pr["key_paths"]
    assert pr["enum_values"]["type"] == ["ACTIVITY_TYPE_POSITION_RESOLUTION"]
    text = json.dumps(cap)
    for secret in (
        "123.45",
        "TRADEID98765",
        "tc-temp-nychigh",
        "CURSORSECRET",
        "2026-10-02",
        "LONG",
    ):
        assert secret not in text, secret


def test_activity_capture_handles_empty_missing_and_malformed_pages(ctl: Any) -> None:
    pages: list[Any] = [{}, {"activities": []}, {"activities": "x"}, {"activities": [None, 3, "s"]}]
    for page in pages:
        cap = ctl.capture_activity_shape(page)
        assert cap["position_resolution"]["rows"] == 0
    assert ctl.capture_activity_shape(None)["status"] == "UNREADABLE"


def test_the_run_records_the_activity_feed_shape_and_survives_its_failure(ctl: Any) -> None:
    venue = fk.FakeVenue()
    venue.activities_page = {"activities": [_PR_ROW], "eof": True}
    doc = fk.Rig(ctl, venue).run().document
    assert doc["activities"]["position_resolution"]["rows"] == 1
    assert doc["activities"]["http_status"] == 200

    venue = fk.FakeVenue()
    venue.activities_status = 500
    result = fk.Rig(ctl, venue).run()
    assert result.document["activities"]["http_status"] == 500
    assert result.exit_code == 0  # the feed is informational for D1, never gating


# --------------------------------------------------------------------- misc invariants


def test_allow_short_is_untouched_and_no_cap_values_are_named() -> None:
    source = _both_sources()
    for token in ("allow_short", "max_daily_budget", "MAX_PER_POSITION", "BREEZY_ORDERS_ENABLED"):
        assert token not in source
    for flag in ("SLUG_SCOPED_CANCEL_ALL_VERIFIED", "GTD_EXPIRY_VERIFIED"):
        assert f"{flag} =" not in source and f"{flag}:" not in source  # never flips them


def test_the_script_does_not_mutate_any_verified_constant_in_src() -> None:
    for node in (n for tree in _both_trees() for n in ast.walk(tree)):
        if isinstance(node, ast.Assign | ast.AugAssign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                ident = t.attr if isinstance(t, ast.Attribute) else getattr(t, "id", "")
                assert not str(ident).endswith("_VERIFIED")
