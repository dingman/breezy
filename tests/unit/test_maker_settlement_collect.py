"""ARM D1 S-COL: the read-only settlement collector (``scripts/venue/maker_settlement_collect.py``).

Recorded fixtures only. The venue call is the REAL ``PolymarketUSHttpClient`` and signer over a
recording double transport (the pattern of the capital-flow puller's tests); nothing here reaches
a venue host. The resolution rows are the 2026-09-05 SFO capture; the YES-paid-out case is a
named synthetic mutation of it.
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest

from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient
from breezy.domain.weather_bucket_facts import WeatherBucketFacts
from breezy.strategy.no_ladder_maker.harm_stop import maker_loss_stop_artefact_path
from breezy.strategy.no_ladder_maker.venue_settlement import VENUE_SCHEMA, read_venue_yes
from tests.unit.test_execution_egress_firewall_guard import find_execution_egress_modules
from tests.unit.test_polymarket_us_capital_flow_pull import (
    _KEY_ID,
    _client,
    _RecordingTransport,
    _venue_response,
)
from tests.unit.test_polymarket_us_readonly_guard import find_sdk_import_violations

_REPO: Final[Path] = Path(__file__).resolve().parents[2]
_SCRIPT: Final[Path] = _REPO / "scripts" / "venue" / "maker_settlement_collect.py"
_SCRIPT_RELATIVE: Final[str] = "scripts/venue/maker_settlement_collect.py"
_CAPTURE: Final[Path] = (
    _REPO / "docs/evidence/venue/polymarket_us/AMBIGUOUS_ORDER_2026-09-05_SFO/activities_p0.json"
)
NYC: Final[str] = "tc-temp-nychigh-2026-08-09-gte94lt95f"
SFO: Final[str] = "tc-temp-sfohigh-2026-08-08-gte74lt75f"
NOW: Final[datetime] = datetime(2026, 10, 25, 12, 50, tzinfo=UTC)
#: CLI finals by (station ICAO token, day): the rung gte94lt95 / gte74lt75 does NOT contain these
OUTSIDE: Final[int] = 60


@pytest.fixture(scope="module")
def collector() -> ModuleType:
    spec = importlib.util.spec_from_file_location("maker_settlement_collect", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _page() -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(_CAPTURE.read_text())["payload"]
    return payload


def _only_resolutions(page: dict[str, Any]) -> dict[str, Any]:
    kept = [a for a in page["activities"] if a["type"] == "ACTIVITY_TYPE_POSITION_RESOLUTION"]
    return {"activities": kept, "eof": True}


def _reader(value: int | None = OUTSIDE) -> Any:
    def read(facts: WeatherBucketFacts) -> int | None:
        return value

    return read


def _paths(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "catalog" / "quote_tape" / "polymarket_us"
    return root, maker_loss_stop_artefact_path(root).parent / "venue_settlements.json"


def _client_for(*pages: dict[str, Any]) -> tuple[PolymarketUSHttpClient, _RecordingTransport]:
    transport = _RecordingTransport([_venue_response(p) for p in pages])
    return _client(transport), transport


def _run(
    collector: ModuleType,
    tmp_path: Path,
    client: PolymarketUSHttpClient,
    *,
    stations: tuple[str, ...] = ("nyc", "sfo"),
    reader: Any = None,
) -> int:
    root, _ = _paths(tmp_path)
    argv = ["--catalog-root", str(root)]
    for station in stations:
        argv += ["--station", station]
    code: int = collector.main(
        argv, env={}, client=client, cli_reading=reader or _reader(), now=NOW
    )
    return code


def test_the_recorded_capture_is_written_as_maker_venue_settlement_v1(
    collector: ModuleType, tmp_path: Path
) -> None:
    client, transport = _client_for(_page())
    assert _run(collector, tmp_path, client) == 0
    _, path = _paths(tmp_path)
    body = json.loads(path.read_text())
    assert body["schema"] == VENUE_SCHEMA == "maker_venue_settlement/v1"
    assert body["source"] == "activities"
    assert body["fetched_at"] == "2026-10-25T12:50:00Z"
    assert body["yes_resolved"] == {NYC: False, SFO: False}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o755
    assert [p.name for p in path.parent.iterdir()] == ["venue_settlements.json"]
    assert read_venue_yes(path) == {NYC: False, SFO: False}
    assert len(transport.calls) == 1 and transport.calls[0]["url"].startswith("https://")


def test_only_the_family_stations_are_kept(collector: ModuleType, tmp_path: Path) -> None:
    client, _ = _client_for(_page())
    assert _run(collector, tmp_path, client, stations=("sfo",)) == 0
    assert read_venue_yes(_paths(tmp_path)[1]) == {SFO: False}


def _synthetic_long_winner(row: dict[str, Any]) -> None:
    """SYNTHETIC: the market pays YES and the long holder's recorded PnL is a win."""
    resolution = row["positionResolution"]
    for side in resolution["market"]["marketSides"]:
        side["price"] = "1" if side["long"] else "0"
    resolution["afterPosition"]["realized"]["value"] = "0.8100"


def test_a_synthetic_yes_paid_out_market_is_written_true_when_the_cli_agrees(
    collector: ModuleType, tmp_path: Path
) -> None:
    page = _only_resolutions(copy.deepcopy(_page()))
    _synthetic_long_winner(page["activities"][0])
    client, _ = _client_for(page)
    assert _run(collector, tmp_path, client, reader=_reader(94)) == 0
    # NYC: venue YES, CLI 94 inside gte94lt95 -> agreed; SFO: venue NO, CLI 94 outside -> agreed
    assert read_venue_yes(_paths(tmp_path)[1]) == {NYC: True, SFO: False}


def test_a_venue_cli_disagreement_is_omitted_never_written(
    collector: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    client, _ = _client_for(_page())
    # the CLI says 94 is inside NYC's rung (YES) but the venue resolved NO; SFO is outside both
    reader = _reader(94)
    assert _run(collector, tmp_path, client, reader=reader) == 0
    assert read_venue_yes(_paths(tmp_path)[1]) == {SFO: False}
    assert "mismatched=1" in capsys.readouterr().out


def test_a_missing_cli_final_keeps_the_resolution_as_unchecked(
    collector: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    client, _ = _client_for(_page())
    assert _run(collector, tmp_path, client, reader=_reader(None)) == 0
    assert read_venue_yes(_paths(tmp_path)[1]) == {NYC: False, SFO: False}
    assert "unchecked=2" in capsys.readouterr().out


def test_an_unreadable_resolution_row_is_omitted_and_counted(
    collector: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    page = copy.deepcopy(_page())
    rows = [a for a in page["activities"] if a["type"].endswith("RESOLUTION")]
    rows[0]["positionResolution"]["market"]["status"] = "MARKET_STATUS_OPEN"
    client, _ = _client_for(page)
    assert _run(collector, tmp_path, client) == 0
    assert read_venue_yes(_paths(tmp_path)[1]) == {SFO: False}
    assert "unreadable=1" in capsys.readouterr().out


def test_pagination_follows_the_cursor_to_eof(collector: ModuleType, tmp_path: Path) -> None:
    first = _only_resolutions(_page())
    second = copy.deepcopy(first)
    first["activities"] = first["activities"][:1]
    first.update(eof=False, nextCursor="page-2")
    second["activities"] = second["activities"][1:]
    client, transport = _client_for(first, second)
    assert _run(collector, tmp_path, client) == 0
    assert read_venue_yes(_paths(tmp_path)[1]) == {NYC: False, SFO: False}
    assert (
        "cursor=page-2" in transport.calls[1]["url"] and "cursor" not in transport.calls[0]["url"]
    )


def test_hitting_the_page_cap_is_incomplete_exits_non_zero_but_still_writes(
    collector: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    page = _only_resolutions(_page())
    page.update(eof=False, nextCursor="again")
    client, transport = _client_for(page)
    assert _run(collector, tmp_path, client) == collector.EXIT_INCOMPLETE != 0
    assert len(transport.calls) == collector.MAX_PAGES
    assert "status=INCOMPLETE" in capsys.readouterr().out
    assert json.loads(_paths(tmp_path)[1].read_text())["complete"] is False


@pytest.mark.parametrize(
    "tail",
    [
        {"eof": False, "nextCursor": ""},
        {"nextCursor": ""},
        {"eof": "true", "nextCursor": ""},
        {"eof": 1, "nextCursor": ""},
        {"eof": None},
    ],
    ids=["eof_false_no_cursor", "eof_absent", "eof_string", "eof_int", "eof_null"],
)
def test_complete_is_set_only_when_eof_is_exactly_true(
    collector: ModuleType, tmp_path: Path, tail: dict[str, Any]
) -> None:
    page = _only_resolutions(_page())
    page.pop("eof")
    page.update(tail)
    client, _ = _client_for(page)
    assert _run(collector, tmp_path, client) == collector.EXIT_INCOMPLETE
    assert json.loads(_paths(tmp_path)[1].read_text())["complete"] is False


def test_a_complete_run_exits_zero_and_writes_complete_true(
    collector: ModuleType, tmp_path: Path
) -> None:
    client, _ = _client_for(_page())
    assert _run(collector, tmp_path, client) == 0
    assert json.loads(_paths(tmp_path)[1].read_text())["complete"] is True


def test_a_5xx_writes_nothing_and_leaves_the_previous_file(
    collector: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    client, _ = _client_for(_page())
    assert _run(collector, tmp_path, client) == 0
    _, path = _paths(tmp_path)
    before = path.read_bytes()
    capsys.readouterr()
    failing = _client(_RecordingTransport([_venue_response({}, status=503)]))
    assert _run(collector, tmp_path, failing) == 1
    assert path.read_bytes() == before
    assert capsys.readouterr().out.strip() == "MAKER_SETTLEMENT status=ERROR error=VenueStatusError"


def test_a_5xx_on_a_first_run_leaves_no_file_and_no_directory(
    collector: ModuleType, tmp_path: Path
) -> None:
    failing = _client(_RecordingTransport([_venue_response({}, status=503)]))
    assert _run(collector, tmp_path, failing) == 1
    assert not _paths(tmp_path)[1].parent.exists()


def test_a_previous_resolution_survives_a_truncated_feed(
    collector: ModuleType, tmp_path: Path
) -> None:
    client, _ = _client_for(_page())
    assert _run(collector, tmp_path, client) == 0
    page = _only_resolutions(_page())
    page["activities"] = page["activities"][:1]  # the feed no longer reaches the SFO row
    client2, _ = _client_for(page)
    assert _run(collector, tmp_path, client2) == 0
    assert read_venue_yes(_paths(tmp_path)[1]) == {NYC: False, SFO: False}


def test_a_resolution_that_flips_against_the_previous_file_is_dropped(
    collector: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    client, _ = _client_for(_page())
    assert _run(collector, tmp_path, client) == 0
    flipped = _only_resolutions(copy.deepcopy(_page()))
    _synthetic_long_winner(flipped["activities"][0])
    client2, _ = _client_for(flipped)
    capsys.readouterr()
    assert _run(collector, tmp_path, client2, reader=_reader(None)) == 0
    assert read_venue_yes(_paths(tmp_path)[1]) == {SFO: False}
    assert "conflicts=1" in capsys.readouterr().out


def test_the_summary_is_one_line_and_carries_no_credential(
    collector: ModuleType, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    client, _ = _client_for(_page())
    assert _run(collector, tmp_path, client) == 0
    captured = capfd.readouterr()
    lines = captured.out.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("MAKER_SETTLEMENT status=OK pages=1 ")
    for text in (captured.out, captured.err):
        assert _KEY_ID not in text and "Authorization" not in text and "X-PM" not in text
        assert "Yes" not in text and "tradeId" not in text


def test_a_missing_catalog_root_is_an_error_without_a_venue_call(
    collector: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    client, transport = _client_for(_page())
    code = collector.main(["--station", "nyc"], env={}, client=client, cli_reading=_reader())
    assert code == 1 and transport.calls == []
    assert "MissingCatalogRoot" in capsys.readouterr().out


def test_the_root_may_come_from_the_node_env_var(collector: ModuleType, tmp_path: Path) -> None:
    root, path = _paths(tmp_path)
    client, _ = _client_for(_page())
    code = collector.main(
        ["--station", "nyc"],
        env={collector.CATALOG_ROOT_ENV: str(root)},
        client=client,
        cli_reading=_reader(),
        now=NOW,
    )
    assert code == 0 and read_venue_yes(path) == {NYC: False}


def test_only_get_requests_reach_the_transport(collector: ModuleType, tmp_path: Path) -> None:
    client, transport = _client_for(_page())
    assert _run(collector, tmp_path, client) == 0
    assert all("/v1/portfolio/activities" in c["url"] for c in transport.calls)
    assert not hasattr(transport, "post")


def test_the_producer_reads_what_the_collector_wrote(collector: ModuleType, tmp_path: Path) -> None:
    from scripts.analysis import maker_loss_stop_producer as producer

    client, _ = _client_for(_page())
    assert _run(collector, tmp_path, client) == 0
    root, path = _paths(tmp_path)
    assert read_venue_yes(path) == {NYC: False, SFO: False}
    assert producer.artefact_path(root).parent == path.parent


# -- structural guards (read-only by construction) -------------------------------------------------

_PERMITTED_IMPORTS: Final[frozenset[str]] = frozenset(
    {
        "__future__",
        "argparse",
        "asyncio",
        "os",
        "sys",
        "collections.abc",
        "dataclasses",
        "datetime",
        "pathlib",
        "typing",
        "nautilus_trader.common.component",
        "breezy.adapters.polymarket_us.account_activity",
        "breezy.adapters.polymarket_us.factories",
        "breezy.adapters.polymarket_us.http",
        "breezy.adapters.polymarket_us.transport",
        "breezy.analysis.labeling.maker_settlement_crosscheck",
        "breezy.strategy.no_ladder_maker.cli_final",
        "breezy.strategy.no_ladder_maker.harm_stop",
        "breezy.strategy.no_ladder_maker.venue_settlement",
    }
)
_BARRED: Final[tuple[str, ...]] = (
    "assert_live_order_submission_permitted",
    "issue_live_trading_permit",
    "PolymarketUSWriteTransport",
    "LiveTradingPermit",
    "OrderSubmissionPermit",
)


def test_the_imports_are_the_pinned_read_only_set_with_no_sdk_exec_or_permit() -> None:
    source = _SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=_SCRIPT_RELATIVE)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    assert sorted(modules - _PERMITTED_IMPORTS) == []
    assert find_sdk_import_violations(_SCRIPT_RELATIVE, source) == []
    assert [m for m in modules if "exec" in m.split(".")] == []
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    }
    assert names.isdisjoint(_BARRED)


def test_only_authenticated_get_is_called_and_no_write_verb_appears() -> None:
    tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "get_authenticated" in attrs
    assert attrs.isdisjoint({"post", "put", "patch", "delete", "request", "post_authenticated"})


def test_the_collector_is_not_an_execution_egress_module() -> None:
    assert _SCRIPT_RELATIVE not in {v.path for v in find_execution_egress_modules()}
