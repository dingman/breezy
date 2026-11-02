"""S2 synthetic/stub-only contracts; no venue calls or registered look."""

from __future__ import annotations

import ast
import datetime as dt
import json
import subprocess
import sys
from decimal import Decimal
from email.message import Message
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPSHandler, Request, build_opener, install_opener

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/analysis"))
if TYPE_CHECKING:
    from scripts.analysis import k1_cheap_open_settlement as k1
    from scripts.analysis import k1_kalshi_prior as kp
    from scripts.analysis import kalshi_s0 as s
else:
    import k1_cheap_open_settlement as k1
    import k1_kalshi_prior as kp
    import kalshi_s0 as s

from tests.unit import test_polymarket_us_readonly_guard as guard


class Stub:
    _base_url = kp.API_BASE

    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, Any]] = []

    def get_json(self, path: str, params: Any = None) -> Any:
        self.calls.append((path, params))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def http(code: int) -> HTTPError:
    return HTTPError(kp.API_BASE + "/secret", code, "private URL", Message(), None)


def row(**changes: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "series_ticker": "KXHIGHNY",
        "ticker": "KXHIGHNY-25JUL02-T90",
        "climate_day": "2025-07-02",
        "status": "finalized",
        "result": "no",
        "open_time": "2025-07-01T14:00:00Z",
        "settlement_ts": 1751547600,
        "candlesticks": [
            {"end_period_ts": 1751382000, "yes_bid": {"close": "0.02"}},
            {"end_period_ts": 1751468400, "yes_bid": {"close_dollars": "0.03"}},
            {"end_period_ts": 1751493600, "yes_bid": {"close": "0.01"}},
        ],
    }
    value.update(changes)
    return value


def population(excess: str = "-0.98", n: int = 30, days: int = 5) -> list[Any]:
    return [
        s.Observation(
            side, "pre", f"S{i}", f"2025-07-{i % days + 1:02}", Decimal(excess), excess == "0.02"
        )
        for side in ("HIGH", "LOW")
        for i in range(n)
    ]


def seal(tmp_path: Path, monkeypatch: Any, rows: list[Any]) -> Path:
    monkeypatch.setattr(s, "LST_TABLE", {"KXHIGHNY": ("KNYC", -5)})
    raw = tmp_path / "raw"
    raw.mkdir()
    s.write_exclusive(
        raw / "KXHIGHNY.json",
        json.dumps({"rows": rows, "exclusions": {}, "prereg_sha": s.FROZEN_PREREG_SHA}),
    )
    s.seal_manifest(raw)
    return raw


def test_h1_default_pins_host_pacing_and_retries(monkeypatch: Any) -> None:
    calls = []

    def factory(**kwargs: Any) -> Stub:
        calls.append(kwargs)
        return Stub({})

    monkeypatch.setattr(s, "KalshiHttp", factory)
    s.HostPinnedKalshi.default()
    assert calls == [{"base_url": kp.API_BASE, "min_interval_s": 0.25, "max_retries": 3}]
    bad = Stub()
    bad._base_url = "https://example.invalid"
    with pytest.raises(s.PoisonedInput):
        s.HostPinnedKalshi(bad)


@pytest.mark.parametrize(
    "template", ["https://example.invalid", "markets/extra", "markets\n", "unknown"]
)
def test_h2_templates_full_match(template: str) -> None:
    with pytest.raises(s.PoisonedInput):
        s.HostPinnedKalshi(Stub()).get(template, parts={}, params={})
    assert all(isinstance(v, re_type()) for v in s.ALLOWED_TEMPLATES.values())


def re_type() -> type:
    import re

    return type(re.compile(""))


@pytest.mark.parametrize("value", ["", "../X", "A/../B", "ABC\n", "https://evil", "X" * 65, "a"])
@pytest.mark.parametrize("field", ["ticker", "series"])
def test_h3_poisoned_parts(field: str, value: str) -> None:
    parts = {"series": "KXHIGHNY", "ticker": "ABC"}
    parts[field] = value
    with pytest.raises(s.PoisonedInput):
        s.HostPinnedKalshi(Stub()).get("live_candles", parts=parts, params={})


@pytest.mark.parametrize(
    "params",
    [
        {"cursor": ""},
        {"cursor": "x&y"},
        {"cursor": "x" * 1025},
        {"series_ticker": "../X"},
        {"status": "settled"},
        {"limit": 0},
        {"limit": 1001},
        {"limit": True},
        {"start_ts": -1},
        {"end_ts": "1"},
        {"period_interval": 1},
        {"start_ts": 2, "end_ts": 1},
    ],
)
def test_h4_poisoned_params(params: dict[str, Any]) -> None:
    with pytest.raises(s.PoisonedInput):
        s.HostPinnedKalshi(Stub()).get("live_markets", parts={}, params=params)


def test_h5_params_are_forwarded_for_urlencode() -> None:
    stub = Stub({})
    params = {"cursor": "a+/=_-", "limit": 1000, "series_ticker": "KXHIGHNY"}
    s.HostPinnedKalshi(stub).get("live_markets", parts={}, params=params)
    assert stub.calls == [("markets", params)]
    assert "a%2B%2F%3D_-" in urlencode(stub.calls[0][1])


@pytest.mark.parametrize("code", [401, 403])
def test_h6_auth_refusal_has_no_url_or_exception_chain(code: int) -> None:
    error = RuntimeError("URL secret")
    error.__cause__ = http(code)
    with pytest.raises(s.KalshiRefused) as caught:
        s.HostPinnedKalshi(Stub(error)).get("live_markets", parts={}, params={})
    assert str(caught.value) == f"HTTP {code}"
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    "error,kind",
    [
        (http(404), "Absent"),
        (http(429), "Miss"),
        (http(503), "Miss"),
        (URLError("URL secret"), "Miss"),
        (http(302), "RedirectRefused"),
        (http(400), "KalshiRefused"),
        (ValueError("URL secret"), "KalshiRefused"),
    ],
)
def test_h7_errors_sanitized(error: Exception, kind: str) -> None:
    with pytest.raises(getattr(s, kind)) as caught:
        s.HostPinnedKalshi(Stub(error)).get("live_markets", parts={}, params={})
    assert "secret" not in str(caught.value)
    assert caught.value.__context__ is None and caught.value.__cause__ is None


def test_h8_no_redirect_opener_and_main_install(monkeypatch: Any) -> None:
    class Redirect(HTTPSHandler):
        def https_open(self, req: Request) -> Any:
            from email.message import Message
            from io import BytesIO
            from urllib.response import addinfourl

            headers = Message()
            headers["Location"] = "https://example.invalid/escape"
            response: Any = addinfourl(BytesIO(b""), headers, req.full_url, 302)
            response.msg = "Found"
            return response

    opener = build_opener(s._NoRedirect(), Redirect())
    install_opener(opener)
    try:
        getter = kp.KalshiHttp(base_url=kp.API_BASE, min_interval_s=0.25, max_retries=3)
        with pytest.raises(s.RedirectRefused):
            s.HostPinnedKalshi(getter).get("live_markets", parts={}, params={})
    finally:
        install_opener(build_opener())
    installed: list[Any] = []
    monkeypatch.setattr(s, "install_opener", installed.append)
    monkeypatch.setattr(s, "run_command", lambda args: 0)
    assert s.main(["s0", "audit"]) == 0
    assert any(isinstance(h, s._NoRedirect) for h in installed[0].handlers)
    handler: Any = s._NoRedirect()
    assert handler.redirect_request(None, None, 302, "", {}, "") is None


def test_h9_five_misses_and_reset() -> None:
    streak = s.MissStreak()
    for _ in range(4):
        streak.observe(s.Miss())
    streak.observe(s.Absent())
    for _ in range(4):
        streak.observe(s.Miss())
    streak.observe({})
    for _ in range(4):
        streak.observe(s.Miss())
    with pytest.raises(s.Incomplete, match="INCOMPLETE"):
        streak.observe(s.Miss())


def test_h10_straddler_fallback_404_is_absent() -> None:
    fixture = json.loads((ROOT / "tests/fixtures/kalshi/s0_cases.json").read_text())
    market = fixture["straddler"]
    stub = Stub(http(404), {"candlesticks": []})
    wrapper = s.HostPinnedKalshi(stub)
    assert s.market_candles(wrapper, market) == {"candlesticks": []}
    assert stub.calls[0][0].startswith("historical/")
    assert stub.calls[1][0].startswith("series/")
    wrapper = s.HostPinnedKalshi(Stub(http(404), http(404)))
    with pytest.raises(s.Absent):
        s.market_candles(wrapper, market)
    assert wrapper.streak.count == 0


@pytest.mark.parametrize("rule", range(9))
def test_s1_s9_static_boundaries(rule: int) -> None:
    source = (ROOT / "scripts/analysis/kalshi_s0.py").read_text()
    tree = ast.parse(source)
    nodes = list(ast.walk(tree))
    strings = [n.value for n in nodes if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    attrs = [n.attr for n in nodes if isinstance(n, ast.Attribute)]
    if rule == 0:
        assert not any("/orders" in v for v in strings)
    elif rule == 1:
        assert not set(strings) & {"POST", "PUT", "PATCH", "DELETE"}
    elif rule == 2:
        assert not set(attrs) & {"post", "put", "patch", "delete", "request"}
    elif rule == 3:
        assert not set(attrs) & {"environ", "getenv"}
        assert not any("credential" in v.lower() or "key_file" in v for v in strings[1:])
    elif rule == 4:
        assert not any("https://" in v or "http://" in v for v in strings)
    elif rule == 5:
        code = (
            "import socket,sys,ssl,urllib.request;"
            "socket.socket=lambda *a,**k: (_ for _ in ()).throw(AssertionError());"
            "sys.path.insert(0,sys.argv[1]); import kalshi_s0"
        )
        result = subprocess.run(
            [sys.executable, "-c", code, str(ROOT / "scripts/analysis")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    elif rule == 6:
        assert not any(
            isinstance(n, ast.ImportFrom) and n.module and "iem_cli_fetch" in n.module
            for n in nodes
        )
        assert not any(
            isinstance(n, ast.Import) and any("iem_cli_fetch" in a.name for a in n.names)
            for n in nodes
        )
    elif rule == 7:
        targets = [
            t.id
            for n in nodes
            if isinstance(n, (ast.Assign, ast.AnnAssign))
            for t in (n.targets if isinstance(n, ast.Assign) else [n.target])
            if isinstance(t, ast.Name)
        ]
        assert not any(
            "BREEZY_MAX" in t
            or "budget" in t.lower()
            or "position_cap" in t.lower()
            or "monthly_cap" in t.lower()
            for t in targets
        )
    else:
        path = "scripts/analysis/kalshi_s0.py"
        assert guard.is_venue_touching(path, tree)
        assert guard.find_write_egress_violations(path, source) == []
        assert path not in guard.B4_EXEMPT_PATHS


def test_l1_l3_table_matches_population_and_five_registry_offsets() -> None:
    stations = json.loads(
        (ROOT / "docs/evidence/STRAT_DESIGN_2026-10-31/stations_card_e.json").read_text()
    )
    expected = {
        r[key]: r["icao"] for r in stations for key in ("kalshi_high_series", "kalshi_low_series")
    }
    assert len(s.LST_TABLE) == 48
    assert {k: v[0] for k, v in s.LST_TABLE.items()} == expected
    for series in kp.SERIES_TO_CLI_LOCATION:
        assert s.LST_TABLE[series][1] == kp.offset_hours_for_series(series)
    assert s.local_time(1751468400, "KXHIGHNY").hour == 10
    with pytest.raises(s.UnknownSeries):
        s.local_time(0, "UNKNOWN")


def test_l4_identity_is_series_not_ticker_prefix() -> None:
    assert {o.station for o in s.observations(row(series_ticker="KXHIGHLAX"))} == {"KLAX"}


@pytest.mark.parametrize(
    "opened,valid",
    [
        ("2025-07-01T14:00:00Z", True),
        ("2025-07-01T14:01:00Z", True),
        ("2025-07-02T03:01:00Z", False),
    ],
)
def test_l5_l6_open_hour_and_midnight_exclusion(opened: str, valid: bool) -> None:
    r = row(open_time=opened)
    refs = s.reference_hours(r)
    opening = s.timestamp(opened)
    ceiling = ((opening + 3599) // 3600) * 3600 + 3600
    assert (("pre", ceiling) in refs) == valid


@pytest.mark.parametrize("delta,expected", [(-3600, None), (0, "0.98"), (3600, "raise")])
def test_x1_x3_exact_end(delta: int, expected: str | None) -> None:
    candles = [{"end_period_ts": 10000 + delta, "yes_bid": {"close": "0.02"}}]
    if expected == "raise":
        with pytest.raises(AssertionError):
            s.exact_candle(candles, 10000)
    else:
        found = s.exact_candle(candles, 10000)
        assert (None if found is None else s.no_ask(found)) == (
            None if expected is None else Decimal(expected)
        )


@pytest.mark.parametrize("bid", [None, "0", "1", "NaN", "Infinity", "bad"])
def test_x4_missing_and_degenerate_bid_excluded_counted(bid: Any) -> None:
    r = row()
    for candle in r["candlesticks"]:
        candle["yes_bid"] = {} if bid is None else {"close": bid}
    report = s.audit_rows([r])
    assert report["exclusions"]["no_bid"] == 3
    assert s.observations(r) == []


@pytest.mark.parametrize(
    "bid,kept", [("0.03", True), ("0.01", True), ("0.0099", False), ("0.0350", False)]
)
def test_tail_band_edges(bid: str, kept: bool) -> None:
    r = row()
    for candle in r["candlesticks"]:
        candle["yes_bid"] = {"close": bid}
    assert bool(s.observations(r)) == kept


@pytest.mark.parametrize(
    "status,result,expected",
    [
        ("cancelled", "void", "cancelled"),
        ("finalized", "voided", "void"),
        ("active", "no", "not_finalized"),
        ("finalized", "yes", None),
        (" FINALIZED ", " CANCELED ", "cancelled"),
    ],
)
def test_x5_exclusion_mirrors_card_e(status: str, result: str, expected: str | None) -> None:
    assert s.row_exclusion({"status": status, "result": result}) == expected


def test_x6_holdout_dropped_before_any_nonidentity_read() -> None:
    class Holdout(dict[str, Any]):
        def get(self, key: str, default: Any = None) -> Any:
            assert key in {"ticker", "series_ticker", "climate_day"}
            return super().get(key, default)

        def __getitem__(self, key: str) -> Any:
            assert key in {"ticker", "series_ticker", "climate_day"}
            return super().__getitem__(key)

    assert (
        s.observations(
            Holdout(ticker="X-26JUL01-T1", climate_day="2026-07-01", series_ticker="KXHIGHNY")
        )
        == []
    )


def test_x7_lookahead_and_x8_both_schemas() -> None:
    for ref, settlement, side, stratum in [
        (100, 100, "HIGH", "pre"),
        (1751468401, 1751547600, "HIGH", "pre"),
        (1751468400, 1751547600, "HIGH", "post"),
    ]:
        with pytest.raises(AssertionError):
            s.assert_reference(ref, settlement, dt.date(2025, 7, 2), "KXHIGHNY", side, stratum)
    for schema in ("close", "close_dollars"):
        assert s.no_ask({"yes_bid": {schema: "0.0300"}}) == Decimal("0.9700")
    report = s.audit_rows([row()])
    assert report["cells"]["HIGH_pre"]["n"] == 1
    assert report["stations"]["HIGH_pre"]["KNYC"] == 1
    assert report["cells"]["HIGH_pre"]["misses"] == 0
    r = row()
    r["candlesticks"].pop(1)
    assert s.audit_rows([r])["cells"]["HIGH_pre"]["misses"] == 1


@pytest.mark.parametrize(
    "excess,expected", [("-0.98", "KILL"), ("0.02", "CONTINUE"), ("0", "KILL")]
)
def test_v1_v2_decisions(excess: str, expected: str) -> None:
    assert s.verdict(population(excess))["decision"] == expected


@pytest.mark.parametrize("n,days", [(29, 5), (30, 4)])
def test_v3_v5_adequacy_is_station_days(n: int, days: int) -> None:
    obs = population(n=n, days=days)
    assert s.verdict(obs * 3)["decision"] == "INCONCLUSIVE"
    assert s.verdict(obs * 3)["cells"]["HIGH_pre"]["n"] == n


def test_v4_positive_post_never_rescues_pre() -> None:
    obs = population()
    obs += [s.Observation("HIGH", "post", "S", "2025-07-01", Decimal(1), True)] * 100
    assert s.verdict(obs)["decision"] == "KILL"


def test_v6_weighted_pooled_disagreement() -> None:
    obs = population("0.02")
    obs += [s.Observation("HIGH", "pre", "S0", "2025-07-01", Decimal("-0.98"), False)] * 10
    report = s.verdict(obs)
    assert Decimal(report["cells"]["HIGH_pre"]["weighted_mean"]) < 0
    assert Decimal(report["cells"]["HIGH_pre"]["pooled_mean"]) < 0
    obs = population("0.02")
    obs += [s.Observation("HIGH", "pre", "S0", "2025-07-01", Decimal("-0.98"), False)] * 2
    report = s.verdict(obs)
    assert Decimal(report["cells"]["HIGH_pre"]["weighted_mean"]) < 0
    assert Decimal(report["cells"]["HIGH_pre"]["pooled_mean"]) < 0
    # One losing day repeated enough to dominate pooled, but 29 winning days
    # dominate the equal-weight station-day statistic.
    obs = population("0.03", n=60)
    obs += [s.Observation("HIGH", "pre", "S0", "2025-07-01", Decimal("-0.97"), False)] * 10
    report = s.verdict(obs)
    assert Decimal(report["cells"]["HIGH_pre"]["weighted_mean"]) > 0
    assert Decimal(report["cells"]["HIGH_pre"]["pooled_mean"]) < 0
    assert report["decision"] == "INCONCLUSIVE"


def test_v7_v10_bootstrap_empty_shortcircuit_and_explicit_constants(monkeypatch: Any) -> None:
    calls = []

    def bootstrap(items: Any, **kwargs: Any) -> list[float]:
        assert items
        assert kwargs["iterations"] == 2000 and kwargs["seed"] == 20261102
        assert kwargs["cluster"] == "day"
        calls.append(items)
        return [0.0, 1.0]

    monkeypatch.setattr(s, "bootstrap_cluster_draws", bootstrap)
    assert s.verdict([])["decision"] == "INCONCLUSIVE"
    assert calls == []
    result = s.verdict(population())
    assert len(calls) == 2
    assert result["cells"]["HIGH_pre"]["wilson"] == k1.wilson_interval(0, 30)
    assert result["decision"] == "KILL"


def test_v11_identity_imports_and_no_summary_call(monkeypatch: Any) -> None:
    for name in (
        "break_even_probability",
        "wilson_interval",
        "summarize_stratum",
        "is_pre_climate_day",
    ):
        assert getattr(s, name) is getattr(k1, name)
    monkeypatch.setattr(s, "summarize_stratum", lambda **kw: pytest.fail("gate used summary"))
    monkeypatch.setattr(s, "break_even_probability", lambda **kw: pytest.fail("gate used BE"))
    assert s.verdict(population())["decision"] == "KILL"


@pytest.mark.parametrize("decision", ["KILL", "CONTINUE", "INCONCLUSIVE"])
def test_v12_v13_no_go_only_kill_and_second_look(
    tmp_path: Path, monkeypatch: Any, decision: str
) -> None:
    raw = seal(tmp_path, monkeypatch, [row()])
    monkeypatch.setattr(s, "verdict", lambda obs: {"decision": decision})
    out = tmp_path / "evidence"
    s.write_verdict(raw, out, "2026-11-02")
    md = (out / "S0_2026-11-02.md").read_text()
    assert md.endswith("ADAPTER_DECISION: NO-GO\n") == (decision == "KILL")
    with pytest.raises(FileExistsError):
        s.write_verdict(raw, out, "2026-11-02")


def test_b1_b2_audit_never_reads_result() -> None:
    class Blind(dict[str, Any]):
        def __getitem__(self, key: str) -> Any:
            assert key != "result"
            return super().__getitem__(key)

        def get(self, key: str, default: Any = None) -> Any:
            assert key != "result"
            return super().get(key, default)

    r = Blind(row())
    assert "result" not in s.audit_projection(r)
    assert s.audit_rows([r])["cells"]["HIGH_pre"]["n"] == 1


def test_b3_b4_exclusive_raw_resume_and_manifest(tmp_path: Path, monkeypatch: Any) -> None:
    raw = seal(tmp_path, monkeypatch, [row()])
    before = (raw / "KXHIGHNY.json").read_bytes()
    with pytest.raises(FileExistsError):
        s.write_exclusive(raw / "KXHIGHNY.json", "changed")
    with pytest.raises(FileExistsError):
        s.seal_manifest(raw)
    monkeypatch.setattr(
        s, "statvfs", lambda p: type("Disk", (), {"f_bavail": 20_000_000_000, "f_frsize": 1})()
    )
    assert s.fetch(s.HostPinnedKalshi(Stub()), raw) == 0
    assert (raw / "KXHIGHNY.json").read_bytes() == before
    assert sorted(p.name for p in raw.iterdir()) == ["KXHIGHNY.json", "MANIFEST.sha256"]


def test_b5_b6_manifest_and_prereg_mismatch(tmp_path: Path, monkeypatch: Any) -> None:
    raw = seal(tmp_path, monkeypatch, [row()])
    (raw / "KXHIGHNY.json").write_text("tampered")
    with pytest.raises(s.SealError, match="MANIFEST"):
        s.write_verdict(raw, tmp_path / "evidence", "2026-11-02")
    monkeypatch.setattr(s, "FROZEN_PREREG_SHA", "0" * 64)
    with pytest.raises(s.SealError, match="prereg"):
        s.verify_prereg()


def test_fetch_filters_before_candle_read_and_records_exclusions(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setattr(s, "LST_TABLE", {"KXHIGHNY": ("KNYC", -5)})
    monkeypatch.setattr(
        s, "statvfs", lambda p: type("Disk", (), {"f_bavail": 20_000_000_000, "f_frsize": 1})()
    )
    holdout = {"ticker": "KXHIGHNY-26JUL01-T90"}
    void = row(result="void")
    stub = Stub(
        {"markets": [holdout, void, row()]},
        {"markets": []},
        {"candlesticks": row()["candlesticks"]},
    )
    assert s.fetch(s.HostPinnedKalshi(stub), tmp_path / "raw") == 0
    payload = json.loads((tmp_path / "raw/KXHIGHNY.json").read_text())
    assert len(payload["rows"]) == 1
    assert payload["exclusions"] == {"window": 1, "void": 1}
    assert len(stub.calls) == 3


def test_disk_refusal_and_f19_halt(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(s, "statvfs", lambda p: type("Disk", (), {"f_bavail": 1, "f_frsize": 1})())
    with pytest.raises(s.Incomplete, match="space"):
        s.fetch(s.HostPinnedKalshi(Stub()), tmp_path / "raw")
    r = row()
    r["candlesticks"][0]["end_period_ts"] += 1
    with pytest.raises(s.SemanticsHalt, match="HALT"):
        s.audit_rows([r])


def test_synthetic_fixture_labels_and_cases() -> None:
    payload = json.loads((ROOT / "tests/fixtures/kalshi/s0_cases.json").read_text())
    assert "synthetic" in payload["_provenance"].lower()
    assert s.no_ask(payload["historical"]) == Decimal("0.98")
    assert s.no_ask(payload["live"]) == Decimal("0.97")
    assert s.no_ask(payload["missing_yes_bid"]) is None
    assert s.row_exclusion(payload["void"]) == "void"


def test_open_hour_rounds_up_fractional_seconds() -> None:
    refs = s.reference_hours(row(open_time="2025-07-01T14:00:00.001Z"))
    assert ("pre", 1751385600) in refs
    assert ("pre", 1751382000) not in refs


def test_low_reference_ends_and_window_boundary() -> None:
    r = row(series_ticker="KXLOWTNYC")
    assert s.reference_hours(r) == [("pre", 1751382000), ("pre", 1751410800), ("post", 1751468400)]
    s.assert_reference(
        1751432400, r["settlement_ts"], dt.date(2025, 7, 2), "KXLOWTNYC", "LOW", "pre"
    )
    with pytest.raises(AssertionError):
        s.assert_reference(
            1751432401, r["settlement_ts"], dt.date(2025, 7, 2), "KXLOWTNYC", "LOW", "pre"
        )


def test_http_miss_streak_is_wired_into_transport() -> None:
    client = s.HostPinnedKalshi(Stub(*(http(503) for _ in range(5))))
    for _ in range(4):
        with pytest.raises(s.Miss):
            client.get("live_markets", parts={}, params={})
    with pytest.raises(s.Incomplete, match="INCOMPLETE"):
        client.get("live_markets", parts={}, params={})


def test_failed_series_remains_unsealed_and_resumable(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(s, "LST_TABLE", {"KXHIGHNY": ("KNYC", -5)})
    monkeypatch.setattr(
        s, "statvfs", lambda p: type("Disk", (), {"f_bavail": 20_000_000_000, "f_frsize": 1})()
    )
    stub = Stub({"markets": [row()]}, {"markets": []}, http(503))
    assert s.fetch(s.HostPinnedKalshi(stub), tmp_path) == 2
    assert not (tmp_path / "KXHIGHNY.json").exists()
    assert not (tmp_path / "MANIFEST.sha256").exists()
    stub = Stub({"markets": [row()]}, {"markets": []}, {"candlesticks": row()["candlesticks"]})
    assert s.fetch(s.HostPinnedKalshi(stub), tmp_path) == 0
    assert len(s.load_sealed(tmp_path)[0]["rows"]) == 1


def test_audit_writer_reports_fetch_exclusions(tmp_path: Path, monkeypatch: Any) -> None:
    raw = seal(tmp_path, monkeypatch, [row()])
    payload = json.loads((raw / "KXHIGHNY.json").read_text())
    payload["exclusions"] = {"cancelled": 2, "void": 1, "not_finalized": 3}
    # Build a fresh seal through the production writers, not an edited manifest.
    second = tmp_path / "second"
    s.write_exclusive(second / "KXHIGHNY.json", json.dumps(payload))
    s.seal_manifest(second)
    s.write_audit(second, tmp_path, "2026-11-02")
    text = (tmp_path / "S0_2026-11-02_audit.md").read_text()
    assert '"void": 1' in text and '"not_finalized": 3' in text
    assert '"result"' not in text


def test_manifest_population_and_raw_prereg_are_bound(tmp_path: Path, monkeypatch: Any) -> None:
    raw = seal(tmp_path, monkeypatch, [row()])
    manifest = raw / "MANIFEST.sha256"
    manifest.write_text(manifest.read_text() + manifest.read_text())
    with pytest.raises(s.SealError, match="population"):
        s.load_sealed(raw)
    other = tmp_path / "other"
    s.write_exclusive(other / "KXHIGHNY.json", json.dumps({"rows": [], "prereg_sha": "wrong"}))
    s.seal_manifest(other)
    with pytest.raises(s.SealError, match="prereg"):
        s.load_sealed(other)


def test_failed_verdict_reserves_look_before_outcome_access(
    tmp_path: Path, monkeypatch: Any
) -> None:
    raw = seal(tmp_path, monkeypatch, [row()])

    def fail(obs: Any) -> Any:
        raise ValueError("calculation failed")

    monkeypatch.setattr(s, "verdict", fail)
    evidence = tmp_path / "evidence"
    with pytest.raises(ValueError, match="calculation"):
        s.write_verdict(raw, evidence, "2026-11-02")
    with pytest.raises(FileExistsError):
        s.write_verdict(raw, evidence, "2026-11-02")
