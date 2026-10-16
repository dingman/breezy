"""MAKER-S2 second look, unit C6b: the ``window-text`` cross-check producer.

Plan: ``docs/plans/backlog/MAKER_2026-10-12/S2_second_look_plan_r3.md`` section C6b and
``S2_second_look_plan_r3_delta_coordinator.md`` section 1 (text design). Every fetch here
goes through a fake transport; ``tests/conftest.py`` blocks sockets. Cache roots are
``tmp_path`` only.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import fcntl
import hashlib
import importlib
import importlib.util
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
FIXTURES: Final[Path] = REPO_ROOT / "tests/fixtures/nws"
LAX_PRODUCT: Final[Path] = FIXTURES / "lax_final_2026-08-21/product.txt"
SFO_PRODUCT: Final[Path] = FIXTURES / "sfo_final_2026-08-21/product.txt"
START: Final[dt.date] = dt.date(2026, 9, 29)
END: Final[dt.date] = dt.date(2026, 10, 3)
NOON_1016: Final[int] = int(dt.datetime(2026, 10, 16, 12, tzinfo=dt.UTC).timestamp() * 1e9)

for _sibling in ("analysis", "venue", "archive"):
    _path = str(REPO_ROOT / "scripts" / _sibling)
    if _path not in sys.path:
        sys.path.insert(0, _path)


@pytest.fixture(scope="module")
def fetch() -> ModuleType:
    spec = importlib.util.spec_from_file_location("breezy_script_iem_cli_fetch_c6b", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def study() -> ModuleType:
    return importlib.import_module("settlement_alignment_study")


def lax_body(days: list[dt.date], *, tmax: int = 83, product: Path = LAX_PRODUCT) -> str:
    """An IEM AFOS text body of CLI FINAL products (LAX by default), one per climate day."""
    template = product.read_text(encoding="utf-8")
    chunks: list[str] = []
    for day in days:
        following = day + dt.timedelta(days=1)
        text = (
            template.replace("AUGUST 21 2026", day.strftime("%B %-d %Y").upper())
            .replace("AUGUST 22 2026", following.strftime("%B %-d %Y").upper())
            .replace(
                "SAT AUG 22 2026",
                f"{following.strftime('%a').upper()} {following.strftime('%b %-d %Y').upper()}",
            )
            .replace(
                "MAXIMUM         83" if product == LAX_PRODUCT else "MAXIMUM         68",
                f"MAXIMUM         {tmax:2d}",
            )
        )
        chunks.append("\x01" + text + "\x03")
    return "".join(chunks)


def span(first: dt.date, last: dt.date) -> list[dt.date]:
    return [first + dt.timedelta(days=n) for n in range((last - first).days + 1)]


class RealContractFetcher:
    """A fake that honours the real text seam: bytes in, strict UTF-8 decode, ``FetchedText`` out.

    A fake handing back arbitrary objects would pass while the live transport (text-only,
    ``src/breezy/ingest/http.py`` strict decode) raised, which is the exact defect the delta
    closed. Bodies are therefore held as BYTES and decoded here.
    """

    def __init__(self, fetch: ModuleType, body: bytes, *, status: int = 200) -> None:
        self._fetch = fetch
        self._body = body
        self._status = status
        self.urls: list[str] = []
        self.lock_held_during_fetch: list[bool] = []
        self.lock_path: Path | None = None

    async def fetch_cli_text(self, url: str) -> Any:
        self.urls.append(url)
        if self.lock_path is not None:
            with self.lock_path.open("a") as probe:
                try:
                    fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    self.lock_held_during_fetch.append(True)
                else:
                    fcntl.flock(probe.fileno(), fcntl.LOCK_UN)
                    self.lock_held_during_fetch.append(False)
        return self._fetch.FetchedText(
            status_code=self._status, text=self._body.decode("utf-8", errors="strict")
        )


def clock_at(hour: int, minute: int) -> Any:
    when = dt.datetime(2026, 10, 16, hour, minute, tzinfo=dt.UTC)
    return lambda: int(when.timestamp() * 1e9)


def window_argv(
    cache: Path,
    *cities: str,
    min_final: dt.date = END,
    start: dt.date = START,
    end: dt.date = END,
) -> list[str]:
    argv = ["window-text", "--cache-dir", str(cache)]
    for city in cities:
        argv += ["--city", city]
    return [
        *argv,
        "--start",
        start.isoformat(),
        "--end",
        end.isoformat(),
        "--min-final-day",
        min_final.isoformat(),
    ]


def expected_path(study: ModuleType, window_text: ModuleType, cache: Path, city: str) -> Path:
    url = window_text.text_window_url(city, START, END, 3_000)
    path: Path = study.cache_path_for_url(cache, url, ".txt")
    return path


@pytest.fixture
def window_text() -> ModuleType:
    return importlib.import_module("settlement_text_window")


@pytest.fixture
def cache(tmp_path: Path) -> Path:
    path = tmp_path / "cache"
    path.mkdir()
    return path


def test_window_text_writes_url_hashed_txt_and_sidecar_under_lock(
    fetch: ModuleType,
    study: ModuleType,
    window_text: ModuleType,
    cache: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = lax_body(span(START, END))
    fetcher = RealContractFetcher(fetch, body.encode("utf-8"))
    fetcher.lock_path = cache / "afos-cli" / ".lock"
    revisions = importlib.import_module("iem_cli_revisions")
    events: list[tuple[str, str]] = []
    real_flock, real_replace = fcntl.flock, os.replace

    def spy_flock(fd: Any, operation: int) -> None:
        events.append(("flock", str(operation)))
        real_flock(fd, operation)

    def spy_replace(src: Any, dst: Any) -> None:
        events.append(("replace", Path(dst).name))
        real_replace(src, dst)

    monkeypatch.setattr(revisions.fcntl, "flock", spy_flock)
    monkeypatch.setattr(revisions.os, "replace", spy_replace)

    code = fetch.main(window_argv(cache, "LAX"), clock=clock_at(12, 0), fetcher=fetcher)

    assert code == 0
    target = expected_path(study, window_text, cache, "LAX")
    assert target.read_bytes() == body.encode("utf-8")
    query = parse_qs(urlsplit(fetcher.urls[0]).query)
    assert query["fmt"] == ["text"] and query["limit"] == ["3000"] and query["pil"] == ["CLILAX"]
    assert fetcher.urls == [window_text.text_window_url("LAX", START, END, 3_000)]
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    sidecar = cache.with_suffix(".sha256")
    assert sidecar.read_text(encoding="utf-8") == f"{digest}  {target.name}\n"
    # The lock was held while the (fake) network call ran, and taken before any replace.
    assert fetcher.lock_held_during_fetch == [True]
    assert events[0] == ("flock", str(fcntl.LOCK_EX | fcntl.LOCK_NB))
    replaced = [name for kind, name in events if kind == "replace"]
    assert replaced == [target.name, sidecar.name]
    assert [p.name for p in cache.rglob("*") if ".tmp-" in p.name] == []


def test_window_text_refuses_overwrite(
    fetch: ModuleType, study: ModuleType, window_text: ModuleType, cache: Path
) -> None:
    target = expected_path(study, window_text, cache, "LAX")
    target.write_bytes(b"prior committed bytes")
    fetcher = RealContractFetcher(fetch, lax_body(span(START, END)).encode("utf-8"))

    code = fetch.main(window_argv(cache, "LAX"), clock=clock_at(12, 0), fetcher=fetcher)

    assert code == 2
    assert target.read_bytes() == b"prior committed bytes"
    assert fetcher.urls == []
    assert not cache.with_suffix(".sha256").exists()


def test_window_text_respects_launch_window(
    fetch: ModuleType, cache: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fetcher = RealContractFetcher(fetch, lax_body(span(START, END)).encode("utf-8"))

    code = fetch.main(window_argv(cache, "LAX"), clock=clock_at(16, 45), fetcher=fetcher)

    assert code == fetch.EXIT_LAUNCH_WINDOW == 6
    assert "launch window" in capsys.readouterr().err
    assert fetcher.urls == []
    assert list(cache.iterdir()) == []
    assert not cache.with_suffix(".sha256").exists()


@pytest.mark.parametrize("cities", [("NYC",), ("LAX", "NYC"), ("ZZZ",), ()])
def test_window_text_refuses_non_maker_city(
    fetch: ModuleType, cache: Path, cities: tuple[str, ...]
) -> None:
    fetcher = RealContractFetcher(fetch, lax_body(span(START, END)).encode("utf-8"))

    code = fetch.main(window_argv(cache, *cities), clock=clock_at(12, 0), fetcher=fetcher)

    assert code == 2
    assert fetcher.urls == []
    assert list(cache.iterdir()) == []


def test_window_text_rejects_short_window_and_writes_nothing(
    fetch: ModuleType,
    study: ModuleType,
    window_text: ModuleType,
    cache: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    short = RealContractFetcher(fetch, lax_body(span(START, dt.date(2026, 10, 1))).encode())

    code = fetch.main(window_argv(cache, "LAX"), clock=clock_at(12, 0), fetcher=short)

    assert code == 3
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1 and "2026-10-01" in err[0] and "2026-10-03" in err[0]
    assert not expected_path(study, window_text, cache, "LAX").exists()
    assert not cache.with_suffix(".sha256").exists()
    assert [p.name for p in cache.rglob("*.txt")] == []
    # The same URL can be retried once the window is complete (R9 next-day retry).
    full = RealContractFetcher(fetch, lax_body(span(START, END)).encode("utf-8"))
    assert fetch.main(window_argv(cache, "LAX"), clock=clock_at(12, 0), fetcher=full) == 0
    assert full.urls == short.urls


def test_window_text_one_short_city_writes_no_city(
    fetch: ModuleType,
    study: ModuleType,
    window_text: ModuleType,
    cache: Path,
) -> None:
    class PerCity(RealContractFetcher):
        async def fetch_cli_text(self, url: str) -> Any:
            days = span(START, END if "CLILAX" in url else dt.date(2026, 10, 1))
            product = LAX_PRODUCT if "CLILAX" in url else SFO_PRODUCT
            self._body = lax_body(days, product=product).encode("utf-8")
            return await super().fetch_cli_text(url)

    fetcher = PerCity(fetch, b"")

    code = fetch.main(window_argv(cache, "LAX", "SFO"), clock=clock_at(12, 0), fetcher=fetcher)

    assert code == 3
    assert not expected_path(study, window_text, cache, "LAX").exists()
    assert not cache.with_suffix(".sha256").exists()


def test_window_text_fake_transport_mirrors_real_text_contract(
    fetch: ModuleType, study: ModuleType, window_text: ModuleType, cache: Path
) -> None:
    async def _instant(_seconds: float) -> None:
        return None

    def transport() -> Any:
        return fetch.IemCliTransport(
            budget=RequestBudget(limit=4),
            pacer=fetch.IemPacer(clock=lambda: 1, sleeper=_instant),
            user_agent="breezy-truth-fetch-TESTONLY",
            clock=lambda: NOON_1016,
            check_proxy_env=False,
        )

    body = lax_body(span(START, END)).encode("utf-8")
    fake = RealContractFetcher(fetch, body)
    assert isinstance(asyncio.run(fake.fetch_cli_text("u")), fetch.FetchedText)

    # The REAL transport (text-only accept, strict decode) serves the same bytes the fake does.
    with respx.mock:
        route = respx.route().mock(return_value=httpx.Response(200, content=body))
        code = fetch.main(window_argv(cache, "LAX"), clock=clock_at(12, 0), fetcher=transport())
        assert code == 0 and route.call_count == 1
        request = route.calls[0].request
        assert request.headers["accept"] == "text/plain"
        assert parse_qs(request.url.query.decode())["fmt"] == ["text"]
    assert expected_path(study, window_text, cache, "LAX").read_bytes() == body

    # A zip-like (non UTF-8) body fails on the live path; so it must here, writing nothing.
    other = cache.parent / "cache2"
    other.mkdir()
    with respx.mock:
        respx.route().mock(
            return_value=httpx.Response(200, content=b"PK\x03\x04\xff\xfe\x00binary-zip-bytes")
        )
        code = fetch.main(window_argv(other, "LAX"), clock=clock_at(12, 0), fetcher=transport())
    assert code == 1
    assert not other.with_suffix(".sha256").exists()
    assert [p for p in other.rglob("*.txt")] == []
