"""FQ loss response F2 FQ-TRUTH: the IEM AFOS CLI fetch and its revision cache.

Plan: ``docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/FQ-LOSS-RESPONSE_plan_r3.md``
section "F2 FQ-TRUTH" and FQ-R18. Everything here runs against injected transports or
``respx``; ``tests/conftest.py`` blocks sockets, so a regression that reached the network
fails instead of spending a request. Cache roots are ``tmp_path`` only.
"""

from __future__ import annotations

import ast
import asyncio
import datetime as dt
import fcntl
import hashlib
import importlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Final
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

from breezy.ingest.probe_transport import RequestBudget

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SCRIPT_PATH: Final[Path] = REPO_ROOT / "scripts/archive/iem_cli_fetch.py"
NYC_PRODUCT: Final[Path] = REPO_ROOT / "tests/fixtures/nws/nyc_final_2026-08-21/product.txt"
SENTINEL: Final[str] = "SENTINEL-VENUE-CREDENTIAL-VALUE"
WINDOW_START: Final[dt.date] = dt.date(2026, 8, 18)
TEST_UA: Final[str] = "breezy-truth-fetch-TESTONLY"

for _sibling in ("analysis", "venue"):
    _path = str(REPO_ROOT / "scripts" / _sibling)
    if _path not in sys.path:
        sys.path.insert(0, _path)


def _load_script(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"breezy_script_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def fetch() -> ModuleType:
    return _load_script(SCRIPT_PATH)


@pytest.fixture(scope="module")
def study() -> ModuleType:
    return importlib.import_module("settlement_alignment_study")


def nyc_spec(fetch: ModuleType) -> Any:
    return next(spec for spec in fetch.load_sites() if spec.city == "NYC")


def cli_body(days: list[dt.date], *, tmax: int = 85) -> str:
    """An IEM AFOS text body of NYC CLI FINAL products, one per climate day."""
    template = NYC_PRODUCT.read_text(encoding="utf-8")
    chunks: list[str] = []
    for day in days:
        following = day + dt.timedelta(days=1)
        text = (
            template.replace("AUGUST 21 2026", day.strftime("%B %-d %Y").upper())
            .replace("AUG 22 2026", following.strftime("%b %-d %Y").upper())
            .replace("SAT", following.strftime("%a").upper())
            .replace("MAXIMUM         79", f"MAXIMUM         {tmax:2d}")
        )
        chunks.append("\x01" + text + "\x03")
    return "".join(chunks)


def days(first: int, last: int) -> list[dt.date]:
    return [dt.date(2026, 8, d) for d in range(first, last + 1)]


class FakeFetcher:
    """Serves one body per fetch call and records every URL it was asked for."""

    def __init__(self, fetch: ModuleType, *texts: str, status: int = 200) -> None:
        self._fetch = fetch
        self._texts = list(texts)
        self._status = status
        self.urls: list[str] = []

    async def fetch_cli_text(self, url: str) -> Any:
        self.urls.append(url)
        text = self._texts.pop(0) if len(self._texts) > 1 else self._texts[0]
        return self._fetch.FetchedText(status_code=self._status, text=text)


def run_fetch(
    fetch: ModuleType,
    cache: Path,
    fetcher: Any,
    fetch_date: dt.date,
    **kwargs: Any,
) -> Any:
    return asyncio.run(
        fetch.fetch_all(
            store=fetch.RevisionStore(cache),
            sites=[nyc_spec(fetch)],
            fetcher=fetcher,
            fetch_date=fetch_date,
            window_start=WINDOW_START,
            **kwargs,
        )
    )


def tree_digest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


async def _instant(_seconds: float) -> None:
    return None


# ---------------------------------------------------------------------------
# Egress
# ---------------------------------------------------------------------------


@respx.mock
def test_fetch_get_only_to_iem_host(fetch: ModuleType, tmp_path: Path) -> None:
    route = respx.route().mock(return_value=httpx.Response(200, text=cli_body(days(18, 20))))
    transport = fetch.IemCliTransport(
        budget=RequestBudget(limit=4),
        pacer=fetch.IemPacer(clock=lambda: 1, sleeper=_instant),
        user_agent=TEST_UA,
        clock=lambda: 1_790_000_000_000_000_000,
        check_proxy_env=False,
    )

    outcomes = run_fetch(fetch, tmp_path, transport, dt.date(2026, 8, 22))

    assert [o.status for o in outcomes] == ["committed"]
    assert route.call_count == 1
    request = route.calls[0].request
    assert request.method == "GET"
    assert request.url.scheme == "https"
    assert request.url.host in fetch.IEM_ALLOWED_HOSTS
    assert request.url.path == "/cgi-bin/afos/retrieve.py"
    assert parse_qs(request.url.query.decode())["pil"] == ["CLINYC"]

    # Every other origin, scheme, port or path is refused before a socket would open.
    refused = (
        "https://evil.example.com/cgi-bin/afos/retrieve.py?pil=CLINYC",
        "http://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py?pil=CLINYC",
        "https://mesonet.agron.iastate.edu:8443/cgi-bin/afos/retrieve.py?pil=CLINYC",
        "https://mesonet.agron.iastate.edu.evil.example/cgi-bin/afos/retrieve.py?pil=CLINYC",
        "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?pil=CLINYC",
        "https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py?pil=AFDOKX",
    )
    for url in refused:
        with pytest.raises(fetch.NonIemUrlError):
            fetch.require_afos_cli_url(url)
        with pytest.raises(fetch.NonIemUrlError):
            asyncio.run(transport.fetch_cli_text(url))
    assert route.call_count == 1

    # The inherited constructor refuses any allowlist but the IEM one.
    with pytest.raises(ValueError, match="IEM_ALLOWED_HOSTS"):
        fetch.PacedIemTransport(
            budget=RequestBudget(limit=1),
            pacer=fetch.IemPacer(clock=lambda: 1),
            user_agent=TEST_UA,
            clock=lambda: 1,
            max_body_bytes=1024,
            accept="text/plain",
            allowed_hosts=frozenset({"evil.example.com"}),
        )


def test_fetch_targets_every_registered_venue_station(fetch: ModuleType, tmp_path: Path) -> None:
    sites = fetch.load_sites()
    fetcher = FakeFetcher(fetch, "not a cli product")

    outcomes = asyncio.run(
        fetch.fetch_all(
            store=fetch.RevisionStore(tmp_path),
            sites=sites,
            fetcher=fetcher,
            fetch_date=dt.date(2026, 8, 22),
            window_start=WINDOW_START,
        )
    )

    pils = sorted(parse_qs(urlsplit(u).query)["pil"][0] for u in fetcher.urls)
    assert pils == sorted(f"CLI{spec.site.cli_location}" for spec in sites)
    assert len(sites) >= 5
    assert {o.status for o in outcomes} == {"rejected_bad_body"}


def test_fetch_reads_no_venue_or_operator_env(
    fetch: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    docstring = ast.get_docstring(tree, clean=False)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"environ", "getenv", "environb"}, node.lineno
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value == docstring:
                continue
            lowered = node.value.lower()
            for forbidden in (".env", "polymarket_us_", "api_key", "secret", "credential"):
                assert forbidden not in lowered, (forbidden, node.lineno)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = node.module if isinstance(node, ast.ImportFrom) else ""
            names = [module or ""] + [alias.name for alias in node.names]
            assert not any("polymarket_us" in name for name in names), node.lineno

    for name in ("POLYMARKET_US_API_KEY", "POLYMARKET_US_ACCOUNT_NUMBER", "BREEZY_USER_AGENT"):
        monkeypatch.setenv(name, SENTINEL)
    with respx.mock:
        route = respx.route().mock(return_value=httpx.Response(200, text=cli_body(days(18, 20))))
        transport = fetch.IemCliTransport(
            budget=RequestBudget(limit=2),
            pacer=fetch.IemPacer(clock=lambda: 1, sleeper=_instant),
            user_agent=TEST_UA,
            clock=lambda: 1_790_000_000_000_000_000,
        )
        run_fetch(fetch, tmp_path, transport, dt.date(2026, 8, 22))
    sent = route.calls[0].request
    assert SENTINEL not in str(sent.url) + str(dict(sent.headers))
    assert sent.headers["user-agent"] == TEST_UA


# ---------------------------------------------------------------------------
# Single writer, atomic flocked writes
# ---------------------------------------------------------------------------


def test_fetch_is_single_cache_writer(fetch: ModuleType, study: ModuleType, tmp_path: Path) -> None:
    owners = [
        path.relative_to(REPO_ROOT).as_posix()
        for root in ("scripts", "src")
        for path in sorted((REPO_ROOT / root).rglob("*.py"))
        if fetch.AFOS_CACHE_SUBDIR in path.read_text(encoding="utf-8")
    ]
    assert owners == ["scripts/archive/iem_cli_fetch.py"]

    # The dataset reads the cache and leaves every byte of it untouched.
    cache = tmp_path / "cache"
    run_fetch(fetch, cache, FakeFetcher(fetch, cli_body(days(18, 20))), dt.date(2026, 8, 22))
    before = tree_digest(cache)
    fetch.build_dataset(
        store=fetch.RevisionStore(cache),
        sites=[nyc_spec(fetch)],
        as_of=dt.date(2026, 8, 22),
        output_dir=tmp_path / "out",
        window_start=WINDOW_START,
    )
    assert tree_digest(cache) == before


def test_cache_write_is_flocked_atomic_rename(
    fetch: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[tuple[str, str]] = []
    real_flock = fcntl.flock
    real_replace = os.replace

    def spy_flock(fd: Any, operation: int) -> None:
        events.append(("flock", str(operation)))
        real_flock(fd, operation)

    def spy_replace(src: Any, dst: Any) -> None:
        events.append(("replace", Path(dst).name))
        assert Path(src).parent == Path(dst).parent
        assert Path(src).name.startswith(".")  # a temp sibling, never the final name
        real_replace(src, dst)

    monkeypatch.setattr(fetch.fcntl, "flock", spy_flock)
    monkeypatch.setattr(fetch.os, "replace", spy_replace)

    run_fetch(fetch, tmp_path, FakeFetcher(fetch, cli_body(days(18, 20))), dt.date(2026, 8, 22))

    kinds = [kind for kind, _ in events]
    assert events[0] == ("flock", str(fcntl.LOCK_EX | fcntl.LOCK_NB))
    replaced = [name for kind, name in events if kind == "replace"]
    assert len(replaced) == 2 and replaced[0].endswith(".txt") and replaced[1].endswith(".json")
    assert kinds.index("replace") > 0
    leftovers = [p.name for p in (tmp_path / "afos-cli").rglob("*") if ".tmp-" in p.name]
    assert leftovers == []

    # A second writer is refused, fetches nothing, writes nothing.
    monkeypatch.undo()
    before = tree_digest(tmp_path)
    second = FakeFetcher(fetch, cli_body(days(18, 21)))
    with (tmp_path / "afos-cli" / ".lock").open("a") as holder:
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(fetch.CacheLockedError):
            run_fetch(fetch, tmp_path, second, dt.date(2026, 8, 23))
    assert second.urls == []
    assert tree_digest(tmp_path) == before


# ---------------------------------------------------------------------------
# Revisions
# ---------------------------------------------------------------------------


def test_refetch_window_picks_latest_revision(fetch: ModuleType, tmp_path: Path) -> None:
    first = FakeFetcher(fetch, cli_body(days(18, 20), tmax=85))
    second = FakeFetcher(fetch, cli_body(days(18, 21), tmax=88))
    run_fetch(fetch, tmp_path, first, dt.date(2026, 8, 22))
    run_fetch(fetch, tmp_path, second, dt.date(2026, 8, 23))

    store = fetch.RevisionStore(tmp_path)
    latest = store.latest_valid("NYC")

    assert latest.fetch_date == dt.date(2026, 8, 23)
    assert latest.label_days == tuple(days(18, 21))
    # Day-bounded URLs: the window end moves with the fetch date, so the URLs differ.
    one, two = (parse_qs(urlsplit(f.urls[0]).query) for f in (first, second))
    assert one["sdate"] == two["sdate"] and one["edate"] != two["edate"]
    assert one["fmt"] == ["text"]

    # A latest revision whose body no longer matches its sha is skipped, not trusted.
    latest.body_path.write_bytes(latest.body_path.read_bytes() + b"tamper")
    fallback = store.latest_valid("NYC")
    assert fallback.fetch_date == dt.date(2026, 8, 22)
    assert fallback.label_days == tuple(days(18, 20))


def test_bad_body_never_becomes_latest(fetch: ModuleType, tmp_path: Path) -> None:
    good = cli_body(days(18, 21))
    run_fetch(fetch, tmp_path, FakeFetcher(fetch, good), dt.date(2026, 8, 22))
    store = fetch.RevisionStore(tmp_path)
    valid = store.latest_valid("NYC")
    snapshot = {p: d for p, d in tree_digest(tmp_path).items() if not p.endswith("rejected.jsonl")}

    unparseable = "<html>502 Bad Gateway</html>"
    outcomes = run_fetch(fetch, tmp_path, FakeFetcher(fetch, unparseable), dt.date(2026, 8, 23))
    assert [o.status for o in outcomes] == ["rejected_bad_body"]
    assert store.latest_valid("NYC") == valid

    shrunk = cli_body(days(18, 19))  # parses, but covers fewer climate days than `valid`
    outcomes = run_fetch(fetch, tmp_path, FakeFetcher(fetch, shrunk), dt.date(2026, 8, 24))
    assert [o.status for o in outcomes] == ["rejected_coverage_reduced"]
    assert store.latest_valid("NYC") == valid

    # No marker, body or temp file was added; both rejections are logged with their sha.
    after = {p: d for p, d in tree_digest(tmp_path).items() if not p.endswith("rejected.jsonl")}
    assert after == snapshot
    log = (tmp_path / "afos-cli" / "NYC" / "rejected.jsonl").read_text().splitlines()
    shas = [json.loads(line)["body_sha256"] for line in log]
    assert shas == [
        hashlib.sha256(unparseable.encode()).hexdigest(),
        hashlib.sha256(shrunk.encode()).hexdigest(),
    ]

    # A non-2xx never becomes a revision either.
    http_fail = run_fetch(
        fetch, tmp_path, FakeFetcher(fetch, good, status=503), dt.date(2026, 8, 25)
    )
    assert [o.status for o in http_fail] == ["http_error"]
    assert store.latest_valid("NYC") == valid


def test_body_sha_recorded_and_catalog_disagreement_flagged(
    fetch: ModuleType, tmp_path: Path
) -> None:
    body = cli_body(days(18, 20), tmax=85)
    agree = {("NYC", day): 85 for day in days(18, 20)}
    disagree = {**agree, ("NYC", dt.date(2026, 8, 19)): 80}

    def marker(cache: Path) -> dict[str, Any]:
        path = next((cache / "afos-cli" / "NYC").glob("*.json"))
        return dict(json.loads(path.read_text()))

    for name, catalog in (("a", agree), ("d", disagree), ("n", None)):
        run_fetch(
            fetch,
            tmp_path / name,
            FakeFetcher(fetch, body),
            dt.date(2026, 8, 22),
            catalog_tmax=catalog,
        )

    ok, bad, none = marker(tmp_path / "a"), marker(tmp_path / "d"), marker(tmp_path / "n")
    assert bad["body_sha256"] == hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert ok["catalog_check"]["disagreement"] is False
    assert ok["catalog_check"]["compared_days"] == 3
    assert bad["catalog_check"]["disagreement"] is True
    assert bad["catalog_check"]["disagreements"] == [
        {"climate_day": "2026-08-19", "cli_tmax_f": 85, "catalog_tmax_f": 80}
    ]
    assert none["catalog_check"]["status"] == "unavailable"
    assert none["catalog_check"]["disagreement"] is False
    stored = (tmp_path / "d" / "afos-cli" / "NYC" / bad["body_file"]).read_bytes()
    assert hashlib.sha256(stored).hexdigest() == bad["body_sha256"]


# ---------------------------------------------------------------------------
# Legacy writers
# ---------------------------------------------------------------------------


class _ExplodingClient:
    def __init__(self) -> None:
        self.calls = 0

    def get(self, url: str, *, timeout: float) -> httpx.Response:
        self.calls += 1
        raise AssertionError(f"network reached for {url}")


class _AsosClient:
    def get(self, url: str, *, timeout: float) -> httpx.Response:
        return httpx.Response(200, text="asos,rows\n", request=httpx.Request("GET", url))


def test_legacy_writers_cache_read_only_for_afos_cli(study: ModuleType, tmp_path: Path) -> None:
    from datetime import date

    cache = tmp_path / "legacy-cache"
    zip_url = study.afos_url("NYC", date(2026, 8, 1), date(2026, 8, 2), limit=500)
    text_url = zip_url.replace("fmt=zip", "fmt=text")
    client = _ExplodingClient()

    with pytest.raises(study.AfosCliCacheMissError):
        study.fetch_text_cached(client, cache, text_url, 0.0)
    with pytest.raises(study.AfosCliCacheMissError):
        study.fetch_bytes_cached(client, cache, zip_url, 0.0, suffix=".zip")
    assert client.calls == 0
    assert not cache.exists()  # not even a mkdir

    # A hit is still served, from either helper.
    cache.mkdir()
    study.cache_path_for_url(cache, text_url).write_text("held text", encoding="utf-8")
    study.cache_path_for_url(cache, zip_url, suffix=".zip").write_bytes(b"held zip")
    assert study.fetch_text_cached(client, cache, text_url, 0.0) == "held text"
    assert study.fetch_bytes_cached(client, cache, zip_url, 0.0, suffix=".zip") == b"held zip"

    # Non-AFOS URLs keep the legacy fetch-and-cache behaviour.
    asos = study.asos_url("NYC", date(2026, 8, 1), date(2026, 8, 2))
    assert not study.is_afos_cli_url(asos)
    assert study.fetch_text_cached(_AsosClient(), cache, asos, 0.0) == "asos,rows\n"
    assert study.cache_path_for_url(cache, asos).read_text(encoding="utf-8") == "asos,rows\n"


def test_afos_cli_url_predicate_scope(study: ModuleType) -> None:
    pil = "https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py?pil={}&fmt=zip"
    assert study.is_afos_cli_url(pil.format("CLINYC"))
    assert not study.is_afos_cli_url(pil.format("AFDOKX"))
    assert not study.is_afos_cli_url("https://example.com/other.py?pil=CLINYC")
