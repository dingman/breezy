"""FU-13b stage 2: the read-only capital-flow puller
(``scripts/venue/polymarket_us_capital_flow_pull.py``).

Authority: ``docs/plans/backlog/NIGHT_2026-09-26/FU-13b_plan_r2_2026-09-26.md``
Test Strategy section, AC8/AC9/AC10, round-2 review binding amendments.

Every test is offline: the venue call is a real
:class:`~breezy.adapters.polymarket_us.http.PolymarketUSHttpClient` wired to a
recording double transport (never the shared, credentialed production client
-- ``build_production_client`` is never exercised here, mirroring
``test_polymarket_us_http.py``'s own doubles). Nothing in this module can
reach a venue host.
"""

from __future__ import annotations

import ast
import calendar
import datetime as dt
import importlib.util
import json
import logging
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from nacl.signing import SigningKey

from breezy.adapters.polymarket_us.credentials import PolymarketUSCredentials
from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient
from breezy.adapters.polymarket_us.secure import RedactedSecureString
from breezy.adapters.polymarket_us.signing import Ed25519RequestSigner
from breezy.adapters.polymarket_us.transport import VenueResponse
from breezy.persistence.external_capital_flows import (
    STATUS_INCOMPLETE,
    STATUS_OK,
    read_latest_snapshot,
)
from tests.unit.test_execution_egress_firewall_guard import find_execution_egress_modules
from tests.unit.test_polymarket_us_readonly_guard import find_sdk_import_violations

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "venue" / "polymarket_us_capital_flow_pull.py"
_SCRIPT_RELATIVE = "scripts/venue/polymarket_us_capital_flow_pull.py"
_ACTIVITY_LITERAL = "/v1/portfolio/activities"
_API_BASE = "https://api.example.invalid"
_GATEWAY_BASE = "https://gateway.example.invalid"
_KEY_ID = "11111111-2222-3333-4444-555555555555"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "polymarket_us_capital_flow_pull", _SCRIPT_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def puller() -> ModuleType:
    return _load_module()


# --------------------------------------------------------------------------
# Doubles -- real client, real signer, fake transport (never a fake client)
# --------------------------------------------------------------------------


def _secret_b64() -> str:
    import base64

    return base64.b64encode(bytes(SigningKey.generate())).decode("ascii")


def _signer() -> Ed25519RequestSigner:
    from nautilus_trader.common.component import TestClock

    clock = TestClock()
    clock.set_time(1_700_000_000_000 * 1_000_000)
    return Ed25519RequestSigner(
        PolymarketUSCredentials(
            key_id=RedactedSecureString(_KEY_ID),
            secret_key=RedactedSecureString(_secret_b64()),
        ),
        clock=clock,
    )


class _RecordingLogger:
    """A :class:`~breezy.adapters.polymarket_us.http.SupportsVenueLog` double
    that records to a plain list -- NEVER prints and NEVER goes through the
    stdlib ``logging`` module, so it cannot itself leak into ``capfd`` or
    ``caplog``. Production never uses this: it is the seam that isolates
    ``http.py``'s own request/response log line from this module's tests."""

    def __init__(self) -> None:
        self.records: list[str] = []

    def debug(self, message: str) -> None:
        self.records.append(message)

    def info(self, message: str) -> None:
        self.records.append(message)

    def warning(self, message: str) -> None:
        self.records.append(message)

    def error(self, message: str) -> None:
        self.records.append(message)


class _RecordingTransport:
    """Replays ``responses`` in order, repeating the last one past the end --
    convenient for a page-cap test that must be asked for MAX_PAGES pages
    without enumerating that many canned responses."""

    def __init__(self, responses: list[VenueResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def get(self, url: str, *, headers: Mapping[str, str], quota_key: str) -> VenueResponse:
        self.calls.append({"url": url, "headers": dict(headers), "quota_key": quota_key})
        index = min(len(self.calls) - 1, len(self._responses) - 1)
        return self._responses[index]


def _client(
    transport: _RecordingTransport, *, logger: _RecordingLogger | None = None
) -> PolymarketUSHttpClient:
    return PolymarketUSHttpClient(
        transport=transport,
        signer=_signer(),
        api_base_url=_API_BASE,
        gateway_base_url=_GATEWAY_BASE,
        logger=logger or _RecordingLogger(),
    )


def _venue_response(payload: dict[str, Any], *, status: int = 200) -> VenueResponse:
    return VenueResponse(status=status, headers={}, body=json.dumps(payload).encode("utf-8"))


def _activity(
    activity_type: str = "ACTIVITY_TYPE_REFERRAL_BONUS", **overrides: Any
) -> dict[str, Any]:
    balance_change = {
        "status": overrides.get("status", "ACCOUNT_BALANCE_CHANGE_STATUS_COMPLETED"),
        "amount": {
            "currency": overrides.get("currency", "USD"),
            "value": overrides.get("amount", "25.00"),
        },
        "createTime": overrides.get("create_time", "2026-09-13T00:00:00Z"),
        "transactionId": overrides.get("transaction_id", "txn-sentinel-1"),
    }
    return {"type": activity_type, "accountBalanceChange": balance_change}


def _page(
    *, activities: list[dict[str, Any]], eof: bool, next_cursor: str | None = None
) -> dict[str, Any]:
    page: dict[str, Any] = {"activities": activities, "eof": eof}
    if next_cursor is not None:
        page["nextCursor"] = next_cursor
    return page


# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------


def test_paginates_to_eof(puller: ModuleType, tmp_path: Path) -> None:
    transport = _RecordingTransport(
        [
            _venue_response(
                _page(activities=[_activity()], eof=False, next_cursor="page-2-cursor")
            ),
            _venue_response(_page(activities=[], eof=True)),
        ]
    )
    client = _client(transport)

    status, pages, records, path = puller.pull_and_write(client, tmp_path, pulled_at_ns=123)

    assert pages == 2
    assert status == STATUS_OK
    assert records == 1
    assert path.is_file()
    # The second request carries the cursor the first page handed back.
    assert "cursor=page-2-cursor" in transport.calls[1]["url"]
    assert "cursor" not in transport.calls[0]["url"]


def test_page_cap_marks_incomplete(puller: ModuleType, tmp_path: Path) -> None:
    transport = _RecordingTransport(
        [_venue_response(_page(activities=[_activity()], eof=False, next_cursor="same-cursor"))]
    )
    client = _client(transport)

    status, pages, records, _path = puller.pull_and_write(client, tmp_path, pulled_at_ns=456)

    assert pages == puller.MAX_PAGES
    assert status == STATUS_INCOMPLETE
    assert records == puller.MAX_PAGES
    evidence = read_latest_snapshot(tmp_path)
    assert evidence.status == STATUS_INCOMPLETE
    expected_create_ts_ns = calendar.timegm(
        dt.datetime(2026, 9, 13, tzinfo=dt.UTC).timetuple()
    ) * 1_000_000_000
    assert evidence.covered_from_ns == expected_create_ts_ns


# --------------------------------------------------------------------------
# Venue failure -- writes nothing, exits non-zero
# --------------------------------------------------------------------------


def test_5xx_writes_nothing_exit_nonzero(puller: ModuleType, tmp_path: Path) -> None:
    transport = _RecordingTransport([_venue_response({}, status=503)])
    client = _client(transport)

    exit_code = puller.main(client=client, directory=tmp_path)

    assert exit_code != 0
    assert list(tmp_path.iterdir()) == []


def test_error_line_has_class_only(
    puller: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = _RecordingTransport([_venue_response({}, status=503)])
    client = _client(transport)

    exit_code = puller.main(client=client, directory=tmp_path)

    assert exit_code != 0
    out = capsys.readouterr().out.strip()
    assert out == f"{puller.SUMMARY_PREFIX} status=ERROR error=VenueStatusError"
    # No status code, no URL, no message text -- the class name only.
    assert "503" not in out
    assert _API_BASE not in out


# --------------------------------------------------------------------------
# AC9 -- one stdout line, no sensitive payload, fd-level AND logging-level
# --------------------------------------------------------------------------


def test_stdout_is_one_summary_line_fd_level(
    puller: ModuleType,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = _RecordingTransport(
        [
            _venue_response(
                _page(activities=[_activity(transaction_id="txn-should-never-leak")], eof=True)
            )
        ]
    )
    client = _client(transport)

    with caplog.at_level(logging.DEBUG):
        exit_code = puller.main(client=client, directory=tmp_path)

    assert exit_code == 0
    out = capfd.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0].startswith(f"{puller.SUMMARY_PREFIX} status=OK pages=1 records=1 path=")
    for forbidden in ("cursor=", "25.00", "txn-should-never-leak", "amount"):
        assert forbidden not in out

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    for forbidden in ("cursor=", "25.00", "txn-should-never-leak"):
        assert forbidden not in log_text


# --------------------------------------------------------------------------
# AC8 -- read-only surface: no SDK, no exec/, no permit fns, one literal
# --------------------------------------------------------------------------


def _imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
    return modules


#: Every module the puller may import, pinned (mirrors
#: ``test_polymarket_us_private_shape_probe.py``'s own allowlist discipline)
#: -- a future import cannot arrive without a paired, reviewed edit here.
_PERMITTED_IMPORTS = frozenset(
    {
        "__future__",
        "asyncio",
        "sys",
        "time",
        "collections.abc",
        "pathlib",
        "typing",
        "nautilus_trader.common.component",
        "breezy.adapters.polymarket_us.account_activity",
        "breezy.adapters.polymarket_us.factories",
        "breezy.adapters.polymarket_us.http",
        "breezy.adapters.polymarket_us.transport",
        "breezy.persistence.external_capital_flows",
    }
)

_BARRED_PERMIT_CALLEES = ("assert_live_order_submission_permitted", "issue_live_trading_permit")


def test_imports_allowlist_no_sdk_no_exec(puller: ModuleType) -> None:
    source = _SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=_SCRIPT_RELATIVE)
    modules = _imported_modules(tree)

    unexpected = sorted(modules - _PERMITTED_IMPORTS)
    assert unexpected == [], (
        "puller imports a module outside the pinned allowlist; add it to "
        f"_PERMITTED_IMPORTS only after reading it: {unexpected}"
    )

    # No SDK import (barrier B5's own detector, applied directly).
    assert find_sdk_import_violations(_SCRIPT_RELATIVE, source) == []

    # No `exec/` import -- any module whose dotted path contains an `exec`
    # segment (e.g. `breezy.adapters.polymarket_us.exec.client`).
    exec_touching = sorted(m for m in modules if "exec" in m.split("."))
    assert exec_touching == [], f"puller imports an exec/ module: {exec_touching}"

    # No permit-function REFERENCE anywhere in the code (B6/B7 siblings) --
    # an AST name/attribute scan, so this module's own docstring is free to
    # NAME the barred callees (as it does, to document that it avoids them)
    # without tripping a plain substring search.
    referenced = sorted(
        node.id if isinstance(node, ast.Name) else node.attr
        for node in ast.walk(tree)
        if (isinstance(node, ast.Name) and node.id in _BARRED_PERMIT_CALLEES)
        or (isinstance(node, ast.Attribute) and node.attr in _BARRED_PERMIT_CALLEES)
    )
    assert referenced == [], f"puller references barred callee(s): {referenced}"


def test_activities_literal_in_exactly_one_src_or_scripts_module() -> None:
    hits: list[str] = []
    for root in ("src", "scripts"):
        base = _REPO_ROOT / root
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            relative = path.relative_to(_REPO_ROOT).as_posix()
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=relative)
            if any(
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value == _ACTIVITY_LITERAL
                for node in ast.walk(tree)
            ):
                hits.append(relative)
    assert hits == ["src/breezy/adapters/polymarket_us/account_activity.py"]


def test_not_an_execution_egress_module() -> None:
    found_paths = {violation.path for violation in find_execution_egress_modules()}
    assert _SCRIPT_RELATIVE not in found_paths


# --------------------------------------------------------------------------
# Same-directory rule (round-2 review binding amendment 2)
# --------------------------------------------------------------------------


def _load_report_module() -> ModuleType:
    path = _REPO_ROOT / "scripts" / "analysis" / "portfolio_roi_report.py"
    spec = importlib.util.spec_from_file_location("portfolio_roi_report", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_puller_dir_matches_report_dir_rule(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from breezy.persistence.external_capital_flows import default_capital_flows_dir

    monkeypatch.setenv("BREEZY_LIVE_TALLY_OUTPUT_DIR", str(tmp_path))
    report = _load_report_module()

    assert default_capital_flows_dir() == report._default_output_dir() / "capital_flows"
