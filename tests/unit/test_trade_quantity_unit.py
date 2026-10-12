"""MAKER S1 WP2: the ``TRADE_QUANTITY_UNIT`` evidence crosscheck.

Plan r3 WP2 (``docs/plans/backlog/MAKER_2026-10-12/S1_preconditions_plan_r3.md``). The pure core
(``breezy.analysis.trade_quantity_unit``) is exercised on hand-built fills and prints; the script
(``scripts/analysis/trade_quantity_unit_crosscheck.py``) is exercised against a fixture exec-state
store written through the production fill writer (L-42): ``DurableFillRecord.to_bytes`` under the
real ``FILL_KEY_PREFIX`` via ``SqliteStateStore`` (``tests.support.aut2_fixtures.seed_fills``).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from breezy.analysis import trade_quantity_unit as tqu
from breezy.analysis.trade_quantity_unit import (
    ClearanceRefused,
    Fill,
    OwnFillMatch,
    Print,
    classify_trade_quantity_unit,
    inversion_verdict,
    keep_decision,
    match_fill,
    predicted_size,
)
from tests.support.aut2_fixtures import durable_fill, seed_fills

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "analysis" / "trade_quantity_unit_crosscheck.py"
_DECLARATION = _REPO / "docs" / "evidence" / "RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md"

_SLUG = "tc-temp-laxhigh-2026-10-02-gte89lt90f"
_YES = f"{_SLUG}.POLYMARKET_US"
_NO = f"{_SLUG}^no.POLYMARKET_US"
_T0 = 1_790_870_525_000_000_000  # inside the capture era, post-freeze climate day
_S = 1_000_000_000
_D = Decimal


def _fill(
    *,
    leg: str = "NO",
    cost: str = "0.12",
    qty: str = "1",
    ts: int = _T0,
    trade_id: str | None = "CV44TMZW4YHR",
    reconciled: bool = True,
    station: str = "LAX",
    day: dt.date = dt.date(2026, 10, 2),
    venue_order_id: str = "vo-1",
) -> Fill:
    return Fill(
        venue_order_id=venue_order_id,
        instrument_id=_NO if leg == "NO" else _YES,
        order_side="BUY",
        qty=_D(qty),
        cost=_D(cost),
        ts_event_ns=ts,
        trade_id=trade_id,
        fee_reconciled=reconciled,
        station=station,
        climate_day=day,
    )


def _print(side: str, price: str, size: str, ts: int = _T0, trade_id: str = "P1") -> Print:
    return Print(
        ts_ns=ts,
        side=side,
        price=_D(price),
        size=_D(size),
        instrument_id=_YES,
        trade_id=trade_id,
    )


def _no_match(size: str, cost: str = "0.12") -> OwnFillMatch:
    return match_fill(_fill(cost=cost), [_print("SELLER", str(_D(1) - _D(cost)), size)])


def _yes_match(size: str, cost: str = "0.35") -> OwnFillMatch:
    return match_fill(_fill(leg="YES", cost=cost), [_print("BUYER", cost, size)])


# -- predicted_size / match_fill ----------------------------------------------------------------


def test_no_leg_fill_separates_all_three_hypotheses() -> None:
    probe = _no_match("1")
    assert probe.print_price_yes == _D("0.88")
    assert [predicted_size(h, probe) for h in tqu.UNIT_HYPOTHESES] == [
        _D(1),
        _D("0.88"),
        _D("0.12"),
    ]
    sizes: dict[str, Callable[[str], str]] = {
        "CONTRACTS": lambda cost: "1",
        "USD_NOTIONAL_YES": lambda cost: str(_D(1) - _D(cost)),
        "USD_NOTIONAL_TAKER": lambda cost: cost,
    }
    for hypothesis, size_for in sizes.items():
        pair = [_no_match(size_for("0.12")), _no_match(size_for("0.20"), cost="0.20")]
        verdict, surviving, _ = classify_trade_quantity_unit(pair)
        assert (verdict, surviving) == (hypothesis, frozenset({hypothesis}))


def test_yes_only_matches_resolve_contracts_but_not_usd_split() -> None:
    contracts = [_yes_match("1"), _yes_match("1", cost="0.20")]
    assert classify_trade_quantity_unit(contracts)[:2] == ("CONTRACTS", frozenset({"CONTRACTS"}))
    usd = [_yes_match("0.35"), _yes_match("0.2", cost="0.20")]
    verdict, surviving, _ = classify_trade_quantity_unit(usd)
    assert verdict == "BRACKETED_USD"
    assert surviving == tqu.USD_BRACKET


def test_usd_pair_surviving_is_bracketed_not_unresolved() -> None:
    verdict, surviving, reason = classify_trade_quantity_unit(
        [_yes_match("0.35"), _yes_match("0.35")]
    )
    assert verdict == "BRACKETED_USD"
    assert surviving == frozenset({"USD_NOTIONAL_YES", "USD_NOTIONAL_TAKER"})
    assert reason


def test_contracts_not_excluded_is_unresolved() -> None:
    # a YES fill at cost 1 predicts (1, 1, 1): every hypothesis survives
    pair = [_yes_match("1", cost="1"), _yes_match("1", cost="1")]
    verdict, surviving, _ = classify_trade_quantity_unit(pair)
    assert verdict == "UNRESOLVED"
    assert surviving == frozenset(tqu.UNIT_HYPOTHESES)


def test_two_candidates_make_a_match_not_count() -> None:
    two = match_fill(
        _fill(),
        [
            _print("SELLER", "0.88", "0.12", trade_id="A"),
            _print("SELLER", "0.88", "0.12", ts=_T0 + _S, trade_id="B"),
        ],
    )
    assert two.candidate_count == 2
    assert not tqu.is_counted(two)
    verdict, _, reason = classify_trade_quantity_unit([two, _no_match("0.12", cost="0.20")])
    assert verdict == "UNRESOLVED"
    assert "counted" in reason


def test_disagreeing_matches_are_unresolved() -> None:
    verdict, surviving, reason = classify_trade_quantity_unit(
        [_no_match("0.12"), _no_match("1", cost="0.20")]
    )
    assert verdict == "UNRESOLVED"
    assert surviving == frozenset()
    assert "contradict" in reason


def test_fewer_than_two_counted_matches_are_unresolved() -> None:
    assert classify_trade_quantity_unit([])[0] == "UNRESOLVED"
    one = classify_trade_quantity_unit([_no_match("0.12")])
    assert one[0] == "UNRESOLVED"
    assert one[1] == frozenset({"USD_NOTIONAL_TAKER"})


def test_summed_match_never_counts() -> None:
    summed = match_fill(
        _fill(leg="YES", cost="0.12", qty="2"),  # cumulative cost 0.12 for 2 contracts: unit 0.06
        [
            _print("BUYER", "0.06", "1", trade_id="A"),
            _print("BUYER", "0.06", "1", ts=_T0 + _S, trade_id="B"),
        ],
    )
    assert summed.summed
    assert not tqu.is_counted(summed)
    verdict, _, _ = classify_trade_quantity_unit([summed, _no_match("0.12")])
    assert verdict == "UNRESOLVED"
    assert tqu.counted_matches([summed, _no_match("0.12")]) == [_no_match("0.12")]


def test_cumulative_multi_print_order_routes_to_summed() -> None:
    # a cumulative record (qty 2) whose two clips print size 1 each: no single print explains it,
    # the same-side same-price sum (2 == CONTRACTS) does
    match = match_fill(
        _fill(leg="YES", cost="0.24", qty="2"),
        [
            _print("BUYER", "0.12", "1", trade_id="A"),
            _print("BUYER", "0.12", "1", ts=_T0 + 2 * _S, trade_id="B"),
        ],
    )
    assert match.summed is True
    assert match.candidate_count == 2
    assert match.print_size == _D(2)
    assert tqu.consistent_hypotheses(match) == frozenset({"CONTRACTS"})
    # a multi-quantity order with one clip in window is also never a counted single print
    lone = match_fill(
        _fill(leg="YES", cost="0.24", qty="2"),
        [_print("BUYER", "0.12", "1", trade_id="A")],
    )
    assert lone.summed is True
    assert not tqu.is_counted(lone)


def test_match_selection_is_by_side_price_and_time_never_size() -> None:
    prints = [
        _print("SELLER", "0.88", "7", trade_id="in"),
        _print("SELLER", "0.88", "0.12", ts=_T0 + 6 * _S, trade_id="late"),  # outside +-5 s
        _print("BUYER", "0.88", "0.12", trade_id="wrong-side"),
        _print("SELLER", "0.87", "0.12", trade_id="wrong-price"),
    ]
    match = match_fill(_fill(), prints)
    assert match.candidate_count == 1
    assert match.print_size == _D(7)  # the size never selected anything
    assert [p.trade_id for p in tqu.candidates_of(_fill(), prints)] == ["in"]
    other_book = Print(
        ts_ns=_T0,
        side="SELLER",
        price=_D("0.88"),
        size=_D("1"),
        instrument_id="tc-other.POLYMARKET_US",
        trade_id="x",
    )
    assert match_fill(_fill(), [other_book]).candidate_count == 0


# -- inversion ----------------------------------------------------------------------------------


def test_inversion_contradicted_needs_zero_candidates_and_an_anti_candidate() -> None:
    fill = _fill()
    holds = match_fill(fill, [_print("SELLER", "0.88", "0.12")])
    no_print = match_fill(fill, [])
    anti_only = match_fill(fill, [_print("BUYER", "0.88", "0.12")])
    unflipped = match_fill(fill, [_print("SELLER", "0.12", "0.12")])
    both = match_fill(
        fill, [_print("SELLER", "0.88", "0.12"), _print("BUYER", "0.88", "0.12", trade_id="Q")]
    )
    assert inversion_verdict(holds) == "HOLDS"
    assert inversion_verdict(no_print) == "NO_PRINT"
    assert inversion_verdict(anti_only) == "CONTRADICTED"
    assert inversion_verdict(unflipped) == "CONTRADICTED"
    assert inversion_verdict(both) == "HOLDS"  # a candidate exists: not a contradiction


# -- keep rules ---------------------------------------------------------------------------------


def _clear(station: str, day: dt.date) -> None:
    return None


def test_resolver_and_unreconciled_fills_are_refused() -> None:
    cases = {
        "NULL_TRADE_ID": _fill(trade_id=None),
        "RESOLVER_TRADE_ID": _fill(trade_id="GET-CFJ485874TMM"),
        "UNRECONCILED_FEE": _fill(reconciled=False),
        "PRE_CAPTURE": _fill(ts=tqu.TRADE_CAPTURE_START_NS - 1),
        "STATION_OUT_OF_SCOPE": _fill(station="NYC"),
        "NOT_A_BUY": Fill(**{**_fill().__dict__, "order_side": "SELL"}),
    }
    for reason, fill in cases.items():
        decision = keep_decision(fill, _clear)
        assert (decision.kept, decision.reason) == (False, reason)
    assert keep_decision(_fill(ts=tqu.TRADE_CAPTURE_START_NS), _clear).kept is True
    assert tqu.TRADE_CAPTURE_START_NS == 1_789_635_600_000_000_000
    for station in ("LAX", "MDW", "MIA", "SFO"):
        assert keep_decision(_fill(station=station), _clear).kept is True


def test_post_freeze_fill_refused_without_declaration() -> None:
    seen: list[tuple[str, dt.date]] = []

    def clearance(station: str, day: dt.date) -> None:
        seen.append((station, day))
        if day > dt.date(2026, 9, 25):
            raise ClearanceRefused("no declaration")

    post = keep_decision(_fill(), clearance)
    assert (post.kept, post.reason) == (False, "FIREWALL_REFUSED")
    pre = keep_decision(_fill(day=dt.date(2026, 9, 21)), clearance)
    assert pre.kept is True
    # refused-for-other-reasons fills never reach the firewall (no read of an uncovered day)
    seen.clear()
    keep_decision(_fill(trade_id=None), clearance)
    assert seen == []


def test_pure_module_stays_exec_free() -> None:
    code = (
        "import sys, breezy.analysis.trade_quantity_unit;"
        "print('breezy.adapters.polymarket_us.exec' in sys.modules)"
    )
    done = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONPATH": str(_REPO / "src")},
    )
    assert done.stdout.strip() == "False"


def test_parse_print_is_strict() -> None:
    good = {
        "ts_ns": 5,
        "side": "BUYER",
        "price": "0.35",
        "size": "1",
        "instrument_id": _YES,
        "trade_id": "T",
    }
    parsed = tqu.parse_print(good)
    assert parsed.price == _D("0.35") and parsed.side == "BUYER"
    for bad in (
        {**good, "side": "NONE"},
        {**good, "extra": 1},
        {k: v for k, v in good.items() if k != "size"},
        {**good, "price": "nan"},
    ):
        with pytest.raises(ValueError):
            tqu.parse_print(bad)


# -- the script -----------------------------------------------------------------------------------


def _load_script() -> ModuleType:
    name = "trade_quantity_unit_crosscheck"
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _declaration(tmp_path: Path, trade_ids: list[str]) -> Path:
    rows = "\n".join(f"| {t} | LAX | 2026-10-02 | NO | 0.1200 |" for t in trade_ids)
    path = tmp_path / "declaration.md"
    path.write_text(
        "## 6. Per-fill list\n\nKept (2):\n\n| tradeId | station | climate day | leg | price |\n"
        f"|---|---|---|---|---|\n{rows}\n\nExcluded (1):\n\n"
        "| tradeId | station |\n|---|---|\n| null | SFO |\n",
        encoding="utf-8",
    )
    return path


def _seed(tmp_path: Path) -> Path:
    db = tmp_path / "exec_polymarket_us.sqlite"
    seed_fills(
        db,
        [
            durable_fill(
                venue_order_id="vo-a",
                instrument_id=_NO,
                cost=_D("0.12"),
                ts_event=_T0,
                trade_id="TRADEA",
            ),
            durable_fill(
                venue_order_id="vo-b",
                instrument_id=_NO,
                cost=_D("0.20"),
                ts_event=_T0 + 60 * _S,
                trade_id="TRADEB",
            ),
            durable_fill(
                venue_order_id="vo-c",
                instrument_id=_NO,
                cost=_D("0.30"),
                ts_event=_T0 + 120 * _S,
                trade_id="GET-vo-c",
            ),
        ],
    )
    return db


def _prints_file(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    path = tmp_path / "prints.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def _print_row(side: str, price: str, size: str, ts: int, trade_id: str) -> dict[str, object]:
    return {
        "ts_ns": ts,
        "side": side,
        "price": price,
        "size": size,
        "instrument_id": _YES,
        "trade_id": trade_id,
    }


def _run(
    script: ModuleType, args: list[str], clearance: Callable[[str, dt.date], None] | None = _clear
) -> int:
    return int(script.main(args, clearance=clearance))


def test_script_end_to_end_resolves_a_unit_from_a_fixture_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _load_script()
    db = _seed(tmp_path)
    prints = _prints_file(
        tmp_path,
        [
            _print_row("SELLER", "0.88", "0.12", _T0 + _S, "P-A"),
            _print_row("SELLER", "0.80", "0.20", _T0 + 61 * _S, "P-B"),
        ],
    )
    decl = _declaration(tmp_path, ["TRADEA", "TRADEB"])
    code = _run(script, ["--db", str(db), "--prints", str(prints), "--declaration", str(decl)])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["verdict"] == "USD_NOTIONAL_TAKER"
    assert out["surviving"] == ["USD_NOTIONAL_TAKER"]
    assert out["s2_stop"] is False and out["s3_stop"] is False
    assert {f["trade_id"] for f in out["fills"]} == {"TRADEA", "TRADEB"}
    assert {f["inversion"] for f in out["fills"]} == {"HOLDS"}
    assert [r["reason"] for r in out["refused"]] == ["RESOLVER_TRADE_ID"]


def test_script_flags_s3_when_only_an_anti_candidate_prints(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _load_script()
    db = _seed(tmp_path)
    prints = _prints_file(tmp_path, [_print_row("BUYER", "0.88", "0.12", _T0, "P-A")])
    decl = _declaration(tmp_path, ["TRADEA", "TRADEB"])
    code = _run(script, ["--db", str(db), "--prints", str(prints), "--declaration", str(decl)])
    out = json.loads(capsys.readouterr().out)
    assert out["s3_stop"] is True and out["s2_stop"] is True
    assert code == script.EXIT_STOP


def test_script_exits_nonzero_with_a_diff_when_the_derived_set_differs_from_the_pin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _load_script()
    db = _seed(tmp_path)
    prints = _prints_file(tmp_path, [])
    decl = _declaration(tmp_path, ["TRADEA", "TRADEZZ"])
    code = _run(script, ["--db", str(db), "--prints", str(prints), "--declaration", str(decl)])
    captured = capsys.readouterr()
    assert code == script.EXIT_PIN_MISMATCH != 0
    assert captured.out == ""  # never proceeds to a verdict
    assert "TRADEB" in captured.err and "TRADEZZ" in captured.err


def test_script_default_declaration_is_the_committed_pinned_list(tmp_path: Path) -> None:
    script = _load_script()
    pinned = script.read_pinned_trade_ids(_DECLARATION)
    assert len(pinned) == 28
    assert {"CMRYWHC1AW1E", "CXSH6TQ0AYHR"} <= pinned
    assert not ({"null", "GET-CFJ485874TMM", "CGW7YF5SEVAY"} & pinned)
    # production default for --declaration: a fixture store that is not the 28 fills must mismatch
    db = _seed(tmp_path)
    prints = _prints_file(tmp_path, [])
    assert _run(script, ["--db", str(db), "--prints", str(prints)]) == script.EXIT_PIN_MISMATCH


def test_crosscheck_opens_exec_db_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _load_script()
    db = _seed(tmp_path)
    prints = _prints_file(tmp_path, [])
    decl = _declaration(tmp_path, ["TRADEA", "TRADEB"])
    targets: list[str] = []
    real_connect = sqlite3.connect

    def spy(target: str, **kwargs: Any) -> Any:
        targets.append(str(target))
        return real_connect(target, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", spy)
    _run(script, ["--db", str(db), "--prints", str(prints), "--declaration", str(decl)])
    capsys.readouterr()
    exec_opens = [t for t in targets if db.as_posix() in t]
    assert exec_opens, "the exec store was never opened"
    assert all(t.startswith("file:") and t.endswith("?mode=ro") for t in exec_opens)
    ro = real_connect(exec_opens[0], uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            ro.execute("INSERT INTO state (key, value) VALUES ('k', X'00')")
    finally:
        ro.close()


_CENSUS = "breezy.analysis.maker_tape_census"


def _stub_census(
    monkeypatch: pytest.MonkeyPatch, *, accept_sha: str | None, seen: list[str]
) -> None:
    """A stand-in for WP1's module with the two names the script binds."""
    stub = ModuleType(_CENSUS)

    class FirewallRefused(Exception):
        pass

    def require_firewall_clearance(station: str, day: dt.date, sha: str | None) -> str:
        seen.append(str(sha))
        if day > dt.date(2026, 9, 25) and sha != accept_sha:
            raise FirewallRefused("declaration sha256 mismatch")
        return "SEARCH_DECLARED"

    stub.FirewallRefused = FirewallRefused  # type: ignore[attr-defined]
    stub.require_firewall_clearance = require_firewall_clearance  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, _CENSUS, stub)


def test_missing_firewall_module_exits_5_with_a_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _load_script()
    real_import = importlib.import_module

    def fail_for_census(name: str, package: str | None = None) -> ModuleType:
        if name == _CENSUS:
            raise ModuleNotFoundError(f"No module named '{_CENSUS}'")
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", fail_for_census)
    db = _seed(tmp_path)
    prints = _prints_file(tmp_path, [])
    decl = _declaration(tmp_path, ["TRADEA", "TRADEB"])
    code = _run(
        script,
        ["--db", str(db), "--prints", str(prints), "--declaration", str(decl)],
        clearance=None,
    )
    captured = capsys.readouterr()
    assert code == script.EXIT_NO_FIREWALL == 5
    assert captured.out == ""
    assert _CENSUS in captured.err


def test_declaration_sha256_is_forwarded_and_a_mismatch_is_refused_before_matching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _load_script()
    db = _seed(tmp_path)
    prints = _prints_file(tmp_path, [_print_row("SELLER", "0.88", "0.12", _T0, "P-A")])
    decl = _declaration(tmp_path, ["TRADEA", "TRADEB"])
    argv = ["--db", str(db), "--prints", str(prints), "--declaration", str(decl)]
    sha = hashlib.sha256(decl.read_bytes()).hexdigest()

    seen: list[str] = []
    _stub_census(
        monkeypatch, accept_sha="0" * 64, seen=seen
    )  # the pinned hash is some other file's
    code = _run(script, argv, clearance=None)
    captured = capsys.readouterr()
    assert set(seen) == {sha}  # the hash of the declaration bytes reached the firewall
    assert code == script.EXIT_PIN_MISMATCH  # post-freeze fills refused, so nothing is matched
    assert captured.out == ""  # no result JSON
    assert "TRADEA" in captured.err

    seen.clear()
    _stub_census(monkeypatch, accept_sha=sha, seen=seen)
    code = _run(script, argv, clearance=None)
    out = json.loads(capsys.readouterr().out)
    assert set(seen) == {sha}
    assert code in (script.EXIT_OK, script.EXIT_STOP)
    assert {f["trade_id"] for f in out["fills"]} == {"TRADEA", "TRADEB"}


def test_multi_contract_fill_matches_at_the_venue_tick() -> None:
    # cumulative cost 0.35 over 3 contracts: average 0.11666..., the tick price is 0.12
    fill = _fill(leg="YES", cost="0.35", qty="3")
    match = match_fill(fill, [_print("BUYER", "0.12", "3")])
    assert match.candidate_count == 1
    assert match.print_price_yes == _D("0.12")
    assert inversion_verdict(match) == "HOLDS"
    assert tqu.is_counted(match)  # size 3 == fill_qty: CONTRACTS, explained by one print


def test_zero_quantity_fill_is_refused_not_a_crash() -> None:
    decision = keep_decision(_fill(qty="0"), _clear)
    assert (decision.kept, decision.reason) == (False, "ZERO_QTY")


def test_counted_matches_carry_their_match_basis(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _load_script()
    db = _seed(tmp_path)
    prints = _prints_file(tmp_path, [_print_row("SELLER", "0.88", "0.12", _T0 + _S, "P-A")])
    decl = _declaration(tmp_path, ["TRADEA", "TRADEB"])
    _run(script, ["--db", str(db), "--prints", str(prints), "--declaration", str(decl)])
    rows = {r["trade_id"]: r for r in json.loads(capsys.readouterr().out)["fills"]}
    assert rows["TRADEA"]["counted"] is True
    assert rows["TRADEA"]["match_basis"] == "unique_candidate_in_window"
    assert rows["TRADEB"]["counted"] is False
    assert rows["TRADEB"]["match_basis"] is None
