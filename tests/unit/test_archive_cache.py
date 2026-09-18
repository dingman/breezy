"""Durable IEM archive cache: manifest is truth, writes are atomic, no network."""

from __future__ import annotations

import ast
import fcntl
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_execution_egress_firewall_guard import find_execution_egress_modules

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_MODULE = REPO_ROOT / "src" / "breezy" / "persistence" / "archive_cache.py"
LAYOUT_MODULE = REPO_ROOT / "src" / "breezy" / "persistence" / "archive_layout.py"
REQUEST_MODULE = REPO_ROOT / "src" / "breezy" / "persistence" / "archive_request.py"

_BANNED_HTTP_ROOTS = frozenset(
    {
        "httpx",
        "requests",
        "urllib",
        "urllib3",
        "http",
        "aiohttp",
        "socket",
        "ssl",
        "ftplib",
        "smtplib",
        "telnetlib",
        "xmlrpc",
        "webbrowser",
    }
)
_DOWNSAMPLE_NAMES = frozenset(
    {"downsample", "resample", "interpolate", "upsample", "decimate"}
)
_HOSTNAME_RE = __import__("re").compile(
    r"(?i)(?://)|(?:(?:[a-z0-9-]+\.)+(?:com|edu|org|net|gov|io)\b)|mesonet\.agron\.iastate\.edu"
)


class _Clock:
    def __init__(self, ns: int = 1_704_067_200_000_000_000) -> None:
        self.ns = ns

    def timestamp_ns(self) -> int:
        return self.ns


def _csv(*rows: str, header: str = "station,valid,tmpf") -> bytes:
    return (header + "\n" + "\n".join(rows) + "\n").encode("utf-8")


def _request(**overrides: Any) -> Any:
    from breezy.persistence.archive_cache import ArchiveRequest

    payload: dict[str, Any] = {
        "source": "iem-asos-1min",
        "station": "KNYC",
        "product": "asos-1min",
        "window_start": 1_704_067_200_000_000_000,
        "window_end": 1_735_689_600_000_000_000,
        "model": None,
    }
    payload.update(overrides)
    return ArchiveRequest(**payload)


class _Cache:
    def __init__(self, inner: Any, fetch_calls: list[Any]) -> None:
        self._inner = inner
        self._fetch_calls = fetch_calls

    def get_or_fetch(self, request: Any) -> Any:
        return self._inner.get_or_fetch(request)

    def covered(self) -> Any:
        return self._inner.covered()

    def read(self, request: Any) -> Any:
        return self._inner.read(request)


def _cache(
    tmp_path: Path,
    fetch: Callable[[Any], bytes] | None = None,
    *,
    clock: _Clock | None = None,
) -> _Cache:
    from breezy.persistence.archive_cache import ArchiveCache

    calls: list[Any] = []

    def _fetch(request: Any) -> bytes:
        calls.append(request)
        if fetch is not None:
            return fetch(request)
        return _csv(f"{request.station},2024-01-01 00:00,32.0")

    return _Cache(ArchiveCache(root=tmp_path, fetch=_fetch, clock=clock or _Clock()), calls)


def _source_dir(root: Path, request: Any) -> Path:
    return root / str(request.source)


def _payload_path(root: Path, request: Any) -> Path:
    return _source_dir(root, request) / f"{request.cache_key()}.csv"


def _manifest_path(root: Path, request: Any) -> Path:
    return _source_dir(root, request) / "coverage.json"


def _lock_path(root: Path, request: Any) -> Path:
    return _source_dir(root, request) / "coverage.json.lock"


def _hold_lock(lock_path: Path) -> int:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fd


def _release(fd: int) -> None:
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


def _ast_modules() -> list[tuple[Path, ast.AST]]:
    parsed: list[tuple[Path, ast.AST]] = []
    for path in (CACHE_MODULE, LAYOUT_MODULE, REQUEST_MODULE):
        parsed.append((path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))))
    return parsed


def test_a_hit_never_fetches(tmp_path: Path) -> None:
    request = _request()
    cache = _cache(tmp_path)
    cache.get_or_fetch(request)
    cache._fetch_calls.clear()

    body = cache.get_or_fetch(request)

    assert cache._fetch_calls == []
    assert body == _csv(f"{request.station},2024-01-01 00:00,32.0")


def test_a_miss_fetches_exactly_once(tmp_path: Path) -> None:
    request = _request()
    cache = _cache(tmp_path)

    cache.get_or_fetch(request)

    assert len(cache._fetch_calls) == 1


def test_an_unmanifested_payload_is_a_miss(tmp_path: Path) -> None:
    request = _request()
    payload = _payload_path(tmp_path, request)
    payload.parent.mkdir(parents=True)
    payload.write_bytes(_csv("KNYC,2024-01-01 00:00,99.0"))
    cache = _cache(tmp_path)

    cache.get_or_fetch(request)

    assert len(cache._fetch_calls) == 1


def test_coverage_comes_from_the_manifest_not_the_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request()
    cache = _cache(tmp_path)
    cache.get_or_fetch(request)

    def explode(self: Path) -> Any:
        raise AssertionError("coverage must not list the directory")

    monkeypatch.setattr(Path, "iterdir", explode)

    covered = cache.covered()

    assert request.cache_key() in covered


def test_a_matched_key_with_a_mismatched_recorded_window_is_manifest_corruption(
    tmp_path: Path,
) -> None:
    from breezy.persistence.archive_cache import ArchiveCacheManifestError

    request = _request()
    cache = _cache(tmp_path)
    cache.get_or_fetch(request)
    manifest_path = _manifest_path(tmp_path, request)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = payload["entries"][request.cache_key()]
    entry["window_start"] = int(entry["window_start"]) + 1
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ArchiveCacheManifestError):
        cache.get_or_fetch(request)


def test_crash_before_manifest_commit_leaves_the_key_absent_and_rerun_converges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request()
    real_replace = os.replace

    def crash_on_manifest(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        if Path(dst).name == "coverage.json":
            raise OSError("crash before manifest commit")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", crash_on_manifest)
    cache = _cache(tmp_path)
    with pytest.raises(OSError, match="crash before manifest commit"):
        cache.get_or_fetch(request)

    assert _payload_path(tmp_path, request).is_file()
    assert request.cache_key() not in cache.covered()

    monkeypatch.setattr(os, "replace", real_replace)
    cache._fetch_calls.clear()
    cache.get_or_fetch(request)

    assert request.cache_key() in cache.covered()
    assert len(cache._fetch_calls) == 1


def test_crash_mid_payload_write_leaves_no_final_name_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request()

    def crash_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        raise OSError("crash mid payload write")

    monkeypatch.setattr(os, "replace", crash_replace)
    cache = _cache(tmp_path)
    with pytest.raises(OSError, match="crash mid payload write"):
        cache.get_or_fetch(request)

    source = _source_dir(tmp_path, request)
    finals = list(source.glob("*.csv")) if source.exists() else []
    assert finals == []
    assert request.cache_key() not in cache.covered()


def test_write_uses_fsync_rename_and_directory_fsync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from breezy.persistence import archive_cache as cache_module

    request = _request()
    calls: list[tuple[str, str]] = []
    real_fsync_directory = cache_module.fsync_directory
    real_replace = os.replace
    real_fsync = os.fsync

    def spy_fsync_directory(path: Path) -> None:
        calls.append(("dir_fsync", str(Path(path))))
        real_fsync_directory(path)

    def spy_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        calls.append(("replace", Path(dst).name))
        real_replace(src, dst)

    def spy_fsync(fd: int) -> None:
        calls.append(("fsync", str(fd)))
        real_fsync(fd)

    monkeypatch.setattr(cache_module, "fsync_directory", spy_fsync_directory)
    monkeypatch.setattr(os, "replace", spy_replace)
    monkeypatch.setattr(os, "fsync", spy_fsync)

    _cache(tmp_path).get_or_fetch(request)

    names = [name for op, name in calls if op == "replace"]
    ops = [op for op, _name in calls]
    assert request.cache_key() + ".csv" in names
    assert "coverage.json" in names
    csv_index = next(
        i for i, (op, name) in enumerate(calls) if op == "replace" and name.endswith(".csv")
    )
    manifest_index = next(
        i for i, (op, name) in enumerate(calls) if op == "replace" and name == "coverage.json"
    )
    assert ops[: csv_index + 1].count("fsync") >= 1
    assert any(op == "dir_fsync" for op, _name in calls[csv_index + 1 : manifest_index])
    assert any(op == "fsync" for op, _name in calls[csv_index + 1 : manifest_index + 1])
    assert any(op == "dir_fsync" for op, _name in calls[manifest_index + 1 :])


def test_digest_mismatch_on_read_raises(tmp_path: Path) -> None:
    from breezy.persistence.archive_cache import ArchiveCacheDigestError

    request = _request()
    cache = _cache(tmp_path)
    cache.get_or_fetch(request)
    _payload_path(tmp_path, request).write_bytes(_csv("KNYC,2024-01-01 00:00,99.0"))

    with pytest.raises(ArchiveCacheDigestError):
        cache.read(request)


def test_entry_without_payload_raises(tmp_path: Path) -> None:
    from breezy.persistence.archive_cache import ArchiveCacheMissingPayloadError

    request = _request()
    cache = _cache(tmp_path)
    cache.get_or_fetch(request)
    _payload_path(tmp_path, request).unlink()

    with pytest.raises(ArchiveCacheMissingPayloadError):
        cache.read(request)


def test_malformed_manifest_never_reinitialized(tmp_path: Path) -> None:
    from breezy.persistence.archive_cache import ArchiveCacheManifestError

    request = _request()
    manifest = _manifest_path(tmp_path, request)
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{not json", encoding="utf-8")
    before = manifest.read_bytes()
    cache = _cache(tmp_path)

    with pytest.raises(ArchiveCacheManifestError):
        cache.get_or_fetch(request)

    assert manifest.read_bytes() == before


def test_an_unknown_manifest_version_refuses_and_never_migrates(tmp_path: Path) -> None:
    from breezy.persistence.archive_cache import ArchiveCacheManifestError

    request = _request()
    manifest = _manifest_path(tmp_path, request)
    manifest.parent.mkdir(parents=True)
    original = json.dumps({"manifest_version": 99, "entries": {}})
    manifest.write_text(original, encoding="utf-8")
    cache = _cache(tmp_path)

    with pytest.raises(ArchiveCacheManifestError):
        cache.get_or_fetch(request)

    assert json.loads(manifest.read_text(encoding="utf-8"))["manifest_version"] == 99


def test_row_count_increments_across_two_fetches(tmp_path: Path) -> None:
    bodies = {
        "KNYC": _csv("KNYC,2024-01-01 00:00,32.0", "KNYC,2024-01-01 00:01,33.0"),
        "KORD": _csv(
            "KORD,2024-01-01 00:00,10.0",
            "KORD,2024-01-01 00:01,11.0",
            "KORD,2024-01-01 00:02,12.0",
        ),
    }

    def fetch(request: Any) -> bytes:
        return bodies[request.station]

    cache = _cache(tmp_path, fetch)
    first = _request(station="KNYC")
    second = _request(station="KORD")
    cache.get_or_fetch(first)
    cache.get_or_fetch(second)
    manifest = json.loads(_manifest_path(tmp_path, first).read_text(encoding="utf-8"))
    rows = {
        manifest["entries"][first.cache_key()]["rows"],
        manifest["entries"][second.cache_key()]["rows"],
    }

    assert rows == {2, 3}
    assert 0 not in rows
    assert len(manifest["entries"]) == 2


def test_zero_row_body_is_recorded(tmp_path: Path) -> None:
    cache = _cache(tmp_path, lambda _request: b"")
    request = _request()
    cache.get_or_fetch(request)
    entry = json.loads(_manifest_path(tmp_path, request).read_text(encoding="utf-8"))["entries"][
        request.cache_key()
    ]

    assert entry["rows"] == 0
    assert entry["bytes"] == 0


def test_a_second_committer_refuses_rather_than_merging(tmp_path: Path) -> None:
    from breezy.persistence.archive_cache import ArchiveCacheConcurrentWriterError

    request = _request()
    fd = _hold_lock(_lock_path(tmp_path, request))
    try:
        cache = _cache(tmp_path)
        with pytest.raises(ArchiveCacheConcurrentWriterError):
            cache.get_or_fetch(request)
    finally:
        _release(fd)

    assert request.cache_key() not in cache.covered()
    assert not _manifest_path(tmp_path, request).exists()


def test_a_symlinked_lock_path_refuses(tmp_path: Path) -> None:
    from breezy.persistence.archive_cache import ArchiveCachePathError

    request = _request()
    lock_path = _lock_path(tmp_path, request)
    planted = tmp_path / "planted.lock"
    planted.write_text("", encoding="utf-8")
    lock_path.parent.mkdir(parents=True)
    lock_path.symlink_to(planted)
    cache = _cache(tmp_path)

    with pytest.raises(ArchiveCachePathError, match="symlink"):
        cache.get_or_fetch(request)

    assert lock_path.is_symlink()
    assert planted.stat().st_size == 0


def test_the_cache_root_is_disjoint_from_the_backed_up_archive_dataset(tmp_path: Path) -> None:
    from breezy.persistence.archive_cache import ArchiveCache, ArchiveCachePathError
    from breezy.persistence.archive_layout import BACKED_UP_ARCHIVE_DATASET_DIR

    existed = BACKED_UP_ARCHIVE_DATASET_DIR.exists()
    marker = BACKED_UP_ARCHIVE_DATASET_DIR / ".fc-0a-2-must-not-mkdir"

    def fetch(_request: Any) -> bytes:
        raise AssertionError("construction must not fetch")

    with pytest.raises(ArchiveCachePathError, match="disjoint"):
        ArchiveCache(root=BACKED_UP_ARCHIVE_DATASET_DIR, fetch=fetch, clock=_Clock())

    nested = BACKED_UP_ARCHIVE_DATASET_DIR / "nested-iem-cache"
    with pytest.raises(ArchiveCachePathError, match="disjoint"):
        ArchiveCache(root=nested, fetch=fetch, clock=_Clock())

    if not existed:
        assert not BACKED_UP_ARCHIVE_DATASET_DIR.exists()
    assert not marker.exists()
    # A disjoint tmp_path root is accepted and still does not mkdir at construction.
    ArchiveCache(root=tmp_path / "iem-cache", fetch=fetch, clock=_Clock())
    assert not (tmp_path / "iem-cache").exists()


def test_the_module_has_no_tmp_literal() -> None:
    from breezy.persistence import archive_cache as _archive_cache  # noqa: F401

    tree = ast.parse(CACHE_MODULE.read_text(encoding="utf-8"), filename=str(CACHE_MODULE))
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert not any(value == "/tmp" or value.startswith("/tmp/") for value in literals)


def test_the_module_has_no_http_import() -> None:
    from breezy.persistence import archive_cache as _archive_cache  # noqa: F401

    imported: set[str] = set()
    for _path, tree in _ast_modules():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])
    assert imported.isdisjoint(_BANNED_HTTP_ROOTS)


def test_the_module_names_no_hostname() -> None:
    from breezy.persistence import archive_cache as _archive_cache  # noqa: F401

    literals: list[str] = []
    for _path, tree in _ast_modules():
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                literals.append(node.value)
    offenders = [value for value in literals if _HOSTNAME_RE.search(value)]
    assert offenders == []


def test_the_module_has_no_downsampling_symbol() -> None:
    from breezy.persistence import archive_cache as _archive_cache  # noqa: F401

    names: set[str] = set()
    tree = ast.parse(CACHE_MODULE.read_text(encoding="utf-8"), filename=str(CACHE_MODULE))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.FunctionDef):
            names.add(node.name)
    assert names.isdisjoint(_DOWNSAMPLE_NAMES)


def test_find_execution_egress_modules_is_unchanged_by_this_item() -> None:
    for module in (
        "breezy.persistence.archive_cache",
        "breezy.persistence.archive_layout",
        "breezy.persistence.archive_request",
    ):
        __import__(module)

    found = [(v.path, v.rule) for v in find_execution_egress_modules()]
    assert found == [
        ("src/breezy/adapters/polymarket_us/exec/__init__.py", "E0"),
        ("src/breezy/adapters/polymarket_us/exec/client.py", "E0"),
        ("src/breezy/adapters/polymarket_us/exec/client.py", "E2"),
        ("src/breezy/adapters/polymarket_us/exec/client.py", "E3"),
        ("src/breezy/adapters/polymarket_us/exec/client.py", "E3"),
        ("src/breezy/adapters/polymarket_us/exec/client.py", "E3"),
        ("src/breezy/adapters/polymarket_us/exec/client.py", "E3"),
        ("src/breezy/adapters/polymarket_us/exec/client.py", "E3"),
        ("src/breezy/adapters/polymarket_us/exec/client.py", "E3"),
        ("src/breezy/adapters/polymarket_us/exec/endpoints.py", "E0"),
        ("src/breezy/adapters/polymarket_us/exec/no_side_keys.py", "E0"),
        ("src/breezy/adapters/polymarket_us/exec/refusals.py", "E0"),
        ("src/breezy/adapters/polymarket_us/exec/reports.py", "E0"),
        ("src/breezy/adapters/polymarket_us/exec/submit_chain.py", "E0"),
        ("src/breezy/adapters/polymarket_us/exec/submit_chain.py", "E1"),
        ("src/breezy/adapters/polymarket_us/factories.py", "E2"),
        ("src/breezy/adapters/polymarket_us/write_transport.py", "E1"),
    ]
