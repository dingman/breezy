"""AUD-02 A0: fee-drift evidence pull -- unit tests with an injected fake
HTTP layer. No network. See
``docs/plans/backlog/AUDIT_2026-09-21/AUD-02-COMPLETION-PLAN-2026-09-25.md``
Section 2 "A0".
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import sys
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from breezy.adapters.polymarket_us.provider import MARKET_LIST_PATH
from breezy.strategy.current_rung_hold.fee_drift_probe import MARKET_BY_SLUG_PATH

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "venue" / "fee_drift_evidence_pull.py"


def _load_pull_module() -> ModuleType:
    """Loaded the way the repo loads its other ``scripts/venue/`` modules
    (see ``test_polymarket_us_shape_capture.py``): ``scripts/`` carries no
    ``__init__.py``, so this is a file-path import, not a package import.
    """
    spec = importlib.util.spec_from_file_location("breezy_fee_drift_evidence_pull", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pull = _load_pull_module()

COMPLETE_DAY_THRESHOLD: Decimal = pull.COMPLETE_DAY_THRESHOLD
MARKET_LIST_QUOTA_KEY: str = pull.MARKET_LIST_QUOTA_KEY
PER_SLUG_QUOTA_KEY: str = pull.PER_SLUG_QUOTA_KEY
MAX_FALLBACK_PER_SLUG_CALLS: int = pull.MAX_FALLBACK_PER_SLUG_CALLS
MAX_LIST_PAGES: int = pull.MAX_LIST_PAGES
LIST_QUERY_ACTIVE: bool = pull.LIST_QUERY_ACTIVE
LIST_QUERY_CLOSED: bool = pull.LIST_QUERY_CLOSED
LIST_QUERY_ARCHIVED: bool = pull.LIST_QUERY_ARCHIVED
PROTECTED_WINDOW_END_UTC = pull.PROTECTED_WINDOW_END_UTC
PROTECTED_WINDOW_START_UTC = pull.PROTECTED_WINDOW_START_UTC
is_protected_window = pull.is_protected_window
list_weather_markets = pull.list_weather_markets
pull_slug = pull.pull_slug
run_once = pull.run_once
worst_case_runtime_secs = pull.worst_case_runtime_secs


class _FakePublicClient:
    """Records every call; serves canned list pages and per-slug responses."""

    def __init__(
        self,
        *,
        list_pages: list[Mapping[str, Any]] | None = None,
        slug_responses: dict[str, Mapping[str, Any] | BaseException] | None = None,
    ) -> None:
        self._list_pages = list(list_pages or [])
        self._slug_responses = dict(slug_responses or {})
        self.list_calls: list[tuple[Mapping[str, Any] | None, str]] = []
        self.slug_calls: list[tuple[str, str]] = []

    async def get_public(
        self, path: str, *, query: Mapping[str, Any] | None = None, quota_key: str
    ) -> Mapping[str, Any]:
        if path == MARKET_LIST_PATH:
            index = len(self.list_calls)
            self.list_calls.append((query, quota_key))
            return self._list_pages[index]
        self.slug_calls.append((path, quota_key))
        slug = path.rsplit("/", 1)[-1]
        response = self._slug_responses[slug]
        if isinstance(response, BaseException):
            raise response
        return response


def _weather_market(
    slug: str, *, taker: str | None = None, maker: str | None = None
) -> dict[str, Any]:
    market: dict[str, Any] = {"slug": slug, "id": 1}
    if taker is not None:
        market["feeCoefficient"] = taker
    if maker is not None:
        market["makerCommissionsBasisPoints"] = maker
    return market


def _market_payload(*, taker: str | None = None, maker: str | None = None) -> dict[str, Any]:
    market: dict[str, Any] = {}
    if taker is not None:
        market["feeCoefficient"] = taker
    if maker is not None:
        market["makerCommissionsBasisPoints"] = maker
    return {"market": market}


# ---------------------------------------------------------------------------
# --user-agent validation (2026-09-25 follow-up): the systemd unit now
# substitutes this value from ``${BREEZY_USER_AGENT}`` via EnvironmentFile,
# so an unset variable reaches argparse as an EMPTY string, not a missing
# argument -- argparse's own ``required=True`` never catches that case. This
# guards the empty/whitespace-only case explicitly, with a clear message,
# per the script's own help text ("never a generic placeholder").
# ---------------------------------------------------------------------------


def test_parse_args_rejects_an_empty_user_agent(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        pull._parse_args(["--user-agent", ""])
    assert exc_info.value.code != 0
    assert "user-agent" in capsys.readouterr().err.lower()


def test_parse_args_rejects_a_whitespace_only_user_agent(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        pull._parse_args(["--user-agent", "   "])
    assert exc_info.value.code != 0
    assert "user-agent" in capsys.readouterr().err.lower()


def test_parse_args_accepts_a_real_contactable_user_agent() -> None:
    args = pull._parse_args(
        ["--user-agent", "breezy-fee-drift-evidence-pull/1 (contact ops@example.com)"]
    )
    assert args.user_agent == "breezy-fee-drift-evidence-pull/1 (contact ops@example.com)"


# ---------------------------------------------------------------------------
# pagination to eof
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pagination_pages_to_eof_and_stops_on_a_short_page() -> None:
    page_one_slugs = [f"tc-temp-nychigh-2026-09-2{i}-gte72f" for i in range(3)]
    client = _FakePublicClient(
        list_pages=[
            {"markets": [_weather_market(slug) for slug in page_one_slugs]},
            {"markets": [_weather_market("tc-temp-nychigh-2026-09-24-gte72f")]},
        ]
    )
    raw_pages, weather_markets = await list_weather_markets(client, limit=3)

    assert len(raw_pages) == 2
    assert [call[0]["offset"] for call in client.list_calls] == [0, 3]
    assert all(call[1] == MARKET_LIST_QUOTA_KEY for call in client.list_calls)
    assert len(weather_markets) == 4


@pytest.mark.asyncio
async def test_pagination_filters_out_non_weather_slugs() -> None:
    client = _FakePublicClient(
        list_pages=[
            {
                "markets": [
                    _weather_market("tc-temp-nychigh-2026-09-21-gte72f"),
                    {"slug": "some-sports-market-2026", "id": 2},
                ]
            }
        ]
    )
    _raw_pages, weather_markets = await list_weather_markets(client, limit=10)

    assert [m["slug"] for m in weather_markets] == ["tc-temp-nychigh-2026-09-21-gte72f"]


@pytest.mark.asyncio
async def test_pagination_raises_when_it_never_returns_a_short_page() -> None:
    client = _FakePublicClient(
        list_pages=[{"markets": [_weather_market("tc-temp-nychigh-2026-09-21-gte72f")]}] * 3
    )
    with pytest.raises(RuntimeError, match="page cap"):
        await list_weather_markets(client, limit=1, max_pages=2)


# ---------------------------------------------------------------------------
# per-slug pull: missing slug / missing field / maker+taker separation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_slug_get_is_recorded_with_a_reason_never_dropped() -> None:
    client = _FakePublicClient(
        slug_responses={"tc-temp-nychigh-2026-09-21-gte72f": ConnectionError("boom")}
    )
    result = await pull_slug(client, "tc-temp-nychigh-2026-09-21-gte72f")

    assert result.ok is False
    assert result.taker_fee_coefficient is None
    assert "boom" in result.reason


@pytest.mark.asyncio
async def test_a_missing_fee_coefficient_field_is_recorded_with_a_reason() -> None:
    client = _FakePublicClient(
        slug_responses={"tc-temp-nychigh-2026-09-21-gte72f": _market_payload()}
    )
    result = await pull_slug(client, "tc-temp-nychigh-2026-09-21-gte72f")

    assert result.ok is False
    assert result.taker_fee_coefficient is None
    assert "feeCoefficient" in result.reason


@pytest.mark.asyncio
async def test_taker_and_maker_fields_are_recorded_separately_from_the_wire() -> None:
    client = _FakePublicClient(
        slug_responses={
            "tc-temp-nychigh-2026-09-21-gte72f": _market_payload(taker="0.06", maker="-125")
        }
    )
    result = await pull_slug(client, "tc-temp-nychigh-2026-09-21-gte72f")

    assert result.ok is True
    assert result.taker_fee_coefficient == "0.06"
    assert result.maker_fee_wire == "-125"


@pytest.mark.asyncio
async def test_maker_field_absent_on_the_wire_is_recorded_as_none_not_fabricated() -> None:
    """B-7: absent means absent -- never backfilled from the documented
    MAKER_FEE_COEFFICIENT constant or a parsed Instrument's flat field."""
    client = _FakePublicClient(
        slug_responses={"tc-temp-nychigh-2026-09-21-gte72f": _market_payload(taker="0.06")}
    )
    result = await pull_slug(client, "tc-temp-nychigh-2026-09-21-gte72f")

    assert result.ok is True
    assert result.taker_fee_coefficient == "0.06"
    assert result.maker_fee_wire is None


@pytest.mark.asyncio
async def test_per_slug_reads_are_budgeted_under_the_instruments_quota_key() -> None:
    client = _FakePublicClient(
        slug_responses={"tc-temp-nychigh-2026-09-21-gte72f": _market_payload(taker="0.06")}
    )
    await pull_slug(client, "tc-temp-nychigh-2026-09-21-gte72f")

    assert client.slug_calls == [
        (MARKET_BY_SLUG_PATH.format(slug="tc-temp-nychigh-2026-09-21-gte72f"), PER_SLUG_QUOTA_KEY)
    ]


# ---------------------------------------------------------------------------
# protected window
# ---------------------------------------------------------------------------


def test_protected_window_boundaries() -> None:
    assert is_protected_window(dt.datetime(2026, 9, 25, 16, 35, tzinfo=dt.UTC)) is True
    assert is_protected_window(dt.datetime(2026, 9, 25, 23, 59, tzinfo=dt.UTC)) is True
    assert is_protected_window(dt.datetime(2026, 9, 26, 0, 0, tzinfo=dt.UTC)) is True
    assert is_protected_window(dt.datetime(2026, 9, 26, 1, 14, tzinfo=dt.UTC)) is True
    assert is_protected_window(dt.datetime(2026, 9, 26, 1, 15, tzinfo=dt.UTC)) is False
    assert is_protected_window(dt.datetime(2026, 9, 25, 16, 34, tzinfo=dt.UTC)) is False
    assert PROTECTED_WINDOW_START_UTC.hour == 16 and PROTECTED_WINDOW_START_UTC.minute == 35
    assert PROTECTED_WINDOW_END_UTC.hour == 1 and PROTECTED_WINDOW_END_UTC.minute == 15


@pytest.mark.asyncio
async def test_run_once_inside_the_protected_window_pulls_nothing_and_marks_incomplete(
    tmp_path: Path,
) -> None:
    client = _FakePublicClient(list_pages=[{"markets": []}])
    now = dt.datetime(2026, 9, 25, 18, 0, tzinfo=dt.UTC)

    result = await run_once(client=client, output_root=tmp_path, now=now)

    assert result.complete is False
    assert "protected window" in result.reason
    assert client.list_calls == []
    assert client.slug_calls == []
    incomplete_path = tmp_path / "2026-09-25" / "incomplete.json"
    assert incomplete_path.exists()
    assert json.loads(incomplete_path.read_text())["date"] == "2026-09-25"


# ---------------------------------------------------------------------------
# manifest / full run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_once_writes_artifacts_with_a_sha256_manifest(tmp_path: Path) -> None:
    slugs = [f"tc-temp-nychigh-2026-09-{20 + i}-gte72f" for i in range(4)]
    client = _FakePublicClient(
        list_pages=[{"markets": [_weather_market(slug) for slug in slugs]}],
        slug_responses={
            slugs[0]: _market_payload(taker="0.06", maker="-125"),
            slugs[1]: _market_payload(taker="0.06"),
            slugs[2]: _market_payload(),  # missing field -> failed
            slugs[3]: ConnectionError("timeout"),  # transport failure -> failed
        },
    )
    now = dt.datetime(2026, 9, 25, 10, 0, tzinfo=dt.UTC)

    result = await run_once(client=client, output_root=tmp_path, now=now, list_limit=10)

    day_dir = tmp_path / "2026-09-25"
    assert result.output_dir == day_dir
    assert result.markets_listed == 4
    assert result.ok_count == 2
    assert result.complete is False  # 2/4 = 50% < 95%
    assert result.taker_values_observed == frozenset({"0.06"})
    assert result.maker_values_observed == frozenset({"-125"})

    manifest = json.loads((day_dir / "manifest.sha256.json").read_text())
    assert set(manifest) == {"slugs.json", "summary.json"}
    for filename, digest in manifest.items():
        contents = (day_dir / filename).read_text(encoding="utf-8")
        assert hashlib.sha256(contents.encode("utf-8")).hexdigest() == digest

    summary = json.loads((day_dir / "summary.json").read_text())
    assert summary["ok_count"] == 2
    assert summary["failed_count"] == 2
    assert {entry["slug"] for entry in summary["failed_slugs"]} == {slugs[2], slugs[3]}


@pytest.mark.asyncio
async def test_a_complete_day_meets_the_95_percent_threshold_exactly(tmp_path: Path) -> None:
    slugs = [f"tc-temp-nychigh-2026-09-{i:02d}-gte72f" for i in range(1, 21)]  # 20 slugs
    responses: dict[str, Any] = {
        slug: _market_payload(taker="0.06") for slug in slugs[:19]
    }
    responses[slugs[19]] = _market_payload()  # 1 failure -> 19/20 = 95%
    client = _FakePublicClient(
        list_pages=[{"markets": [_weather_market(slug) for slug in slugs]}],
        slug_responses=responses,
    )
    now = dt.datetime(2026, 9, 25, 10, 0, tzinfo=dt.UTC)

    result = await run_once(client=client, output_root=tmp_path, now=now, list_limit=100)

    assert result.ok_count == 19
    assert result.markets_listed == 20
    assert COMPLETE_DAY_THRESHOLD == Decimal("0.95")
    assert result.complete is True


# ---------------------------------------------------------------------------
# same-day re-run (code review fix): manifest must always match disk exactly,
# and a protected-window run must never downgrade an existing real record.
# ---------------------------------------------------------------------------

_SAME_DAY_SLUG = "tc-temp-nychigh-2026-09-25-gte72f"


def _one_slug_complete_client() -> _FakePublicClient:
    return _FakePublicClient(
        list_pages=[{"markets": [_weather_market(_SAME_DAY_SLUG)]}],
        slug_responses={_SAME_DAY_SLUG: _market_payload(taker="0.06", maker="-125")},
    )


def _assert_manifest_matches_disk(day_dir: Path) -> None:
    manifest = json.loads((day_dir / "manifest.sha256.json").read_text(encoding="utf-8"))
    on_disk = {
        p.name
        for p in day_dir.iterdir()
        if p.name not in {"manifest.sha256.json", "skipped_downgrade.json"}
        and not p.name.startswith(".")
    }
    assert set(manifest) == on_disk, (manifest, on_disk)
    for filename, digest in manifest.items():
        contents = (day_dir / filename).read_text(encoding="utf-8")
        assert hashlib.sha256(contents.encode("utf-8")).hexdigest() == digest


@pytest.mark.asyncio
async def test_complete_then_protected_same_day_never_downgrades_the_record(
    tmp_path: Path,
) -> None:
    complete_now = dt.datetime(2026, 9, 25, 10, 0, tzinfo=dt.UTC)
    first = await run_once(
        client=_one_slug_complete_client(), output_root=tmp_path, now=complete_now
    )
    day_dir = tmp_path / "2026-09-25"
    assert first.complete is True
    _assert_manifest_matches_disk(day_dir)

    protected_client = _FakePublicClient()
    # Same UTC date (2026-09-25), inside [16:35Z, 24:00) -- the protected window.
    protected_now = dt.datetime(2026, 9, 25, 20, 0, tzinfo=dt.UTC)
    second = await run_once(client=protected_client, output_root=tmp_path, now=protected_now)

    # The protected-window run must never issue any GET.
    assert protected_client.list_calls == []
    assert protected_client.slug_calls == []
    # Downgrade policy: the returned facts are the EXISTING complete record's,
    # not a fresh "incomplete" verdict.
    assert second.complete is True
    assert "downgrade refused" in second.reason
    assert (day_dir / "slugs.json").exists()
    assert (day_dir / "summary.json").exists()
    assert not (day_dir / "incomplete.json").exists()
    _assert_manifest_matches_disk(day_dir)

    sidecar = json.loads((day_dir / "skipped_downgrade.json").read_text(encoding="utf-8"))
    assert sidecar["date"] == "2026-09-25"


@pytest.mark.asyncio
async def test_protected_then_complete_same_day_upgrades_cleanly(tmp_path: Path) -> None:
    protected_now = dt.datetime(2026, 9, 25, 20, 0, tzinfo=dt.UTC)
    first = await run_once(client=_FakePublicClient(), output_root=tmp_path, now=protected_now)
    day_dir = tmp_path / "2026-09-25"
    assert first.complete is False
    assert (day_dir / "incomplete.json").exists()
    _assert_manifest_matches_disk(day_dir)

    complete_now = dt.datetime(2026, 9, 25, 10, 0, tzinfo=dt.UTC)
    second = await run_once(
        client=_one_slug_complete_client(), output_root=tmp_path, now=complete_now
    )

    assert second.complete is True
    assert not (day_dir / "incomplete.json").exists()
    assert (day_dir / "slugs.json").exists()
    assert (day_dir / "summary.json").exists()
    _assert_manifest_matches_disk(day_dir)


# ---------------------------------------------------------------------------
# runtime fix (2026-09-25 live TimeoutStartSec failure): fee fields come off
# the list response directly; per-slug GETs are a bounded fallback only.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_query_is_scoped_to_the_currently_tradable_universe() -> None:
    client = _FakePublicClient(list_pages=[{"markets": []}])
    await list_weather_markets(client, limit=10)

    query, _quota_key = client.list_calls[0]
    assert query["active"] is LIST_QUERY_ACTIVE
    assert query["closed"] is LIST_QUERY_CLOSED
    assert query["archived"] is LIST_QUERY_ARCHIVED


@pytest.mark.asyncio
async def test_a_listed_fee_coefficient_needs_no_per_slug_get_at_all(tmp_path: Path) -> None:
    """The actual fix: when every list entry already carries `feeCoefficient`,
    `run_once` issues ZERO per-slug GETs. This is exactly the shape of the
    real gateway response measured 2026-09-25 (0 missing across 4353
    markets) -- the prior design's unconditional per-slug GET is what timed
    out the first live run."""
    cities = ["nyc", "lax", "chi", "hou", "phx"]
    slugs = [
        f"tc-temp-{city}high-2026-09-{day:02d}-gte72f"
        for city in cities
        for day in range(1, 11)
    ]
    client = _FakePublicClient(
        list_pages=[
            {"markets": [_weather_market(slug, taker="0.0695") for slug in slugs]}
        ],
    )
    now = dt.datetime(2026, 9, 25, 10, 0, tzinfo=dt.UTC)

    result = await run_once(client=client, output_root=tmp_path, now=now, list_limit=100)

    assert client.slug_calls == []  # the fix: no per-slug GET issued
    assert result.markets_listed == 50
    assert result.ok_count == 50
    assert result.complete is True
    assert result.taker_values_observed == frozenset({"0.0695"})


@pytest.mark.asyncio
async def test_a_listed_entry_missing_fee_falls_back_to_one_per_slug_get(
    tmp_path: Path,
) -> None:
    slug = "tc-temp-nychigh-2026-09-21-gte72f"
    client = _FakePublicClient(
        list_pages=[{"markets": [_weather_market(slug)]}],  # no feeCoefficient on the list entry
        slug_responses={slug: _market_payload(taker="0.06")},
    )
    now = dt.datetime(2026, 9, 25, 10, 0, tzinfo=dt.UTC)

    result = await run_once(client=client, output_root=tmp_path, now=now, list_limit=10)

    assert client.slug_calls == [
        (MARKET_BY_SLUG_PATH.format(slug=slug), PER_SLUG_QUOTA_KEY)
    ]
    assert result.ok_count == 1
    assert result.taker_values_observed == frozenset({"0.06"})


@pytest.mark.asyncio
async def test_fallback_per_slug_gets_are_capped_and_overflow_is_recorded(
    tmp_path: Path,
) -> None:
    n = MAX_FALLBACK_PER_SLUG_CALLS + 5
    slugs = [f"tc-temp-nychigh-2026-09-{i:02d}-gte72f" for i in range(1, n + 1)]
    # None of these list entries carry a fee -> every slug needs the fallback.
    client = _FakePublicClient(
        list_pages=[{"markets": [_weather_market(slug) for slug in slugs]}],
        slug_responses={slug: _market_payload(taker="0.0695") for slug in slugs},
    )
    now = dt.datetime(2026, 9, 25, 10, 0, tzinfo=dt.UTC)

    result = await run_once(client=client, output_root=tmp_path, now=now, list_limit=100)

    assert len(client.slug_calls) == MAX_FALLBACK_PER_SLUG_CALLS
    assert result.markets_listed == n
    assert result.ok_count == MAX_FALLBACK_PER_SLUG_CALLS
    overflow_reasons = {
        s.reason for s in result.slugs if s.reason and "cap" in s.reason
    }
    assert len(overflow_reasons) == 1
    assert str(MAX_FALLBACK_PER_SLUG_CALLS) in next(iter(overflow_reasons))


def test_worst_case_runtime_secs_matches_the_documented_580_seconds() -> None:
    # MAX_LIST_PAGES=50, DEFAULT_DISCOVERY_REQUESTS_PER_MINUTE=6:
    #   (50-6) * (60/6) = 440s
    # MAX_FALLBACK_PER_SLUG_CALLS=20, DEFAULT_INSTRUMENT_REQUESTS_PER_MINUTE=6:
    #   (20-6) * (60/6) = 140s
    # total = 580s
    assert worst_case_runtime_secs() == pytest.approx(580.0)
    assert MAX_LIST_PAGES == 50
    assert MAX_FALLBACK_PER_SLUG_CALLS == 20


def test_worst_case_runtime_secs_is_zero_within_the_burst_allowance() -> None:
    assert worst_case_runtime_secs(max_list_pages=6, max_fallback_calls=6) == 0.0


# ---------------------------------------------------------------------------
# deploy: the shipped unit's TimeoutStartSec must exceed the worst-case bound
# ---------------------------------------------------------------------------

_SERVICE_PATH = REPO_ROOT / "deploy" / "systemd" / "breezy-fee-evidence-pull.service"

#: Comfortable slack beyond the documented worst-case bound (process startup,
#: DNS, TLS handshake, GC pauses -- none of which the pacing formula models).
_TIMEOUT_MARGIN_SECS = 120


def _service_timeout_start_sec() -> int:
    for line in _SERVICE_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("TimeoutStartSec="):
            return int(line.strip().split("=", 1)[1])
    raise AssertionError(f"{_SERVICE_PATH} has no TimeoutStartSec= line")


def test_service_timeout_exceeds_the_worst_case_bound_with_margin() -> None:
    bound = worst_case_runtime_secs()
    timeout = _service_timeout_start_sec()
    assert timeout >= bound + _TIMEOUT_MARGIN_SECS, (
        f"TimeoutStartSec={timeout} does not clear the worst-case bound "
        f"{bound}s plus a {_TIMEOUT_MARGIN_SECS}s margin -- the exact failure "
        "mode of the first live run"
    )
