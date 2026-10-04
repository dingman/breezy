"""AUT-1 WP5 stage 2b W3 and 2c: the audit's per-log scan cache and the scan deadline.

Split out of ``test_capture_audit_inputs.py`` (S2-R43). Same REAL data root as that file
(``tests/support/capture_audit_w3_fixtures.py``). The cache is an optimisation, never evidence: an
entry that is unreadable, undecodable, for another key or from another reducer is a miss.
"""

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis import capture_audit_cache as cache
from breezy.analysis import capture_audit_host as host
from breezy.analysis import capture_audit_inputs as inputs
from breezy.analysis.capture_audit_input_types import LogMarkers, ReplayResult
from breezy.analysis.capture_node_log_markers import CaptureEpochStartLine
from breezy.persistence.autonomy.single_read import SingleReadRefused, open_root
from tests.support import capture_audit_w3_fixtures as w3
from tests.support.capture_node_log_fixtures import REAL_TAKE

DAY = w3.DAY


# -- the per-log cache (S2-R6) -----------------------------------------------------------------


def _scans(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, list[Path]]:
    scans: list[Path] = []
    root = w3.full_world(tmp_path, monkeypatch, scans=scans)
    return root, scans


def test_cache_miss_scans_once_and_a_second_gather_hits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, scans = _scans(tmp_path, monkeypatch)
    first = w3.gather(root)
    assert (
        len(scans) == 1 and len(list((root / "cache" / "capture_audit").glob("scan_*.json"))) == 1
    )
    host._BUS_OUTCOMES.clear()
    w3.plant_snapshot(root)
    second = w3.gather(root)
    assert len(scans) == 1  # a hit: the log is not scanned again
    assert second.boots[0].scan == first.boots[0].scan


def test_cache_key_covers_name_size_mtime_and_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MUTATION: the cache key without size."""
    root, _ = _scans(tmp_path, monkeypatch)
    (log,) = (root / "logs").iterdir()
    log.write_bytes(log.read_bytes() + b"\n" * 70_000)  # longer than the 64 KiB hashed head
    base = cache.log_key(log)
    stat0 = log.stat()
    log.write_bytes(log.read_bytes() + b"x")  # one byte longer, same head and (restored) mtime
    os.utime(log, ns=(stat0.st_mtime_ns, stat0.st_mtime_ns))
    assert cache.log_key(log) != base  # size
    log.write_bytes(log.read_bytes()[:-1])
    os.utime(log, ns=(stat0.st_mtime_ns, stat0.st_mtime_ns))
    assert cache.log_key(log) == base
    os.utime(log, ns=(stat0.st_mtime_ns + 1, stat0.st_mtime_ns + 1))
    assert cache.log_key(log) != base  # mtime
    os.utime(log, ns=(stat0.st_mtime_ns, stat0.st_mtime_ns))
    head = bytearray(log.read_bytes())
    head[10] ^= 1
    log.write_bytes(bytes(head))
    os.utime(log, ns=(stat0.st_mtime_ns, stat0.st_mtime_ns))
    assert cache.log_key(log) != base  # head


def test_a_log_that_grew_is_scanned_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, scans = _scans(tmp_path, monkeypatch)
    w3.gather(root)
    (log,) = (root / "logs").iterdir()
    stat0 = log.stat()
    log.write_bytes(log.read_bytes() + b"2026-10-03T22:59:00.0Z [INFO] x: plain line\n")
    os.utime(log, ns=(stat0.st_mtime_ns, stat0.st_mtime_ns))  # only the SIZE differs
    host._BUS_OUTCOMES.clear()
    w3.plant_snapshot(root)
    w3.gather(root)
    assert len(scans) == 2


def test_a_running_log_is_never_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = w3.make_root(tmp_path)
    scans: list[Path] = []
    w3.install(monkeypatch, root, scans=scans)
    (root / "logs").joinpath(f"breezy-trade-{w3.LOG_STAMP}.log").write_bytes(
        w3.write_node_log(root).read_bytes().replace(b"DISPOSED", b"RUNNING ")
    )
    w3.write_exec_store(root, {})
    w3.gather(root)
    assert not list((root / "cache" / "capture_audit").glob("scan_*.json"))


@pytest.mark.parametrize("damage", [b"", b"{", b'{"v": "other"}', b'{"v": "scan-cache/1"}'])
def test_a_damaged_cache_entry_is_a_miss_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: bytes
) -> None:
    root, scans = _scans(tmp_path, monkeypatch)
    w3.gather(root)
    (entry,) = (root / "cache" / "capture_audit").glob("scan_*.json")
    entry.write_bytes(damage)
    host._BUS_OUTCOMES.clear()
    w3.plant_snapshot(root)
    assert w3.gather(root).boots and len(scans) == 2


def test_the_cache_codec_round_trips_every_cached_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    w3.install(monkeypatch, root)
    line = CaptureEpochStartLine(5, 6, w3.FAMILY, 7)
    w3.FakeMarkers.planted = {(w3.INSTANCE, DAY): LogMarkers(capture_epoch_start=(line,))}
    replay = ReplayResult(
        admitted_total=2, admitted_by_kind={"Take": 1, "TrySubmit": 1}, mismatch_samples=("a",)
    )
    w3.FakeReplay.planted = {(w3.INSTANCE, DAY): replay}
    path = w3.write_node_log(root, decisions=[REAL_TAKE])
    result = inputs._scan_one(path)
    decoded = cache._decode_result(cache.encode_result(result, "k"), "k")
    assert decoded is not None
    assert (
        decoded.scan == result.scan and decoded.scan.entry_lines
    )  # DecisionLine, TakeInputs, dates
    assert dict(decoded.replay) == dict(result.replay) == {(w3.INSTANCE, DAY): replay}
    assert dict(decoded.markers) == dict(result.markers)


def test_write_scan_cache_is_private_atomic_and_refuses_a_bad_key(tmp_path: Path) -> None:
    root = w3.make_root(tmp_path)
    key = "ab" * 32
    inputs.write_scan_cache(root, key, b"one")
    inputs.write_scan_cache(root, key, b"two")  # a replace, never a second file
    (entry,) = (root / "cache" / "capture_audit").iterdir()
    assert entry.read_bytes() == b"two" and stat.S_IMODE(entry.stat().st_mode) == 0o600
    assert stat.S_IMODE(entry.parent.stat().st_mode) == 0o700
    for bad in ("../x", "AB" * 32, "ab" * 31, ""):
        with pytest.raises(ValueError):
            inputs.write_scan_cache(root, bad, b"x")


def test_the_exec_snapshot_and_the_scan_cache_share_the_one_audit_cache_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = _scans(tmp_path, monkeypatch)
    w3.gather(root)
    assert {p.name for p in (root / "cache").iterdir()} == {"capture_audit", "capture_audit_bus"}


# -- the deadline (S2-R6) ----------------------------------------------------------------------


def test_the_deadline_sink_checks_the_clock_every_65536_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    monkeypatch.setattr(inputs, "MONOTONIC", lambda: clock[0])
    token = inputs.DEADLINE.set(10.0)
    try:
        sink = inputs._DeadlineSink()
        clock[0] = 99.0  # past the deadline, but the sink only looks every 65,536 events
        for _ in range(65_535):
            sink.feed(object())
        with pytest.raises(inputs.ScanDeadline):
            sink.feed(object())
    finally:
        inputs.DEADLINE.reset(token)


def test_no_deadline_means_unlimited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inputs, "MONOTONIC", lambda: 1e12)
    sink = inputs._DeadlineSink()
    for _ in range(65_536):
        sink.feed(object())


def test_a_scan_stopped_by_the_deadline_is_scan_deadline_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    monkeypatch.setattr(inputs, "_DEADLINE_CHECK_EVERY", 1)
    monkeypatch.setattr(inputs, "MONOTONIC", lambda: 50.0)
    token = inputs.DEADLINE.set(10.0)
    try:
        with pytest.raises(inputs.ScanDeadline):
            w3.gather(root)
    finally:
        inputs.DEADLINE.reset(token)


def test_a_cached_log_is_served_even_after_the_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, scans = _scans(tmp_path, monkeypatch)
    w3.gather(root)
    host._BUS_OUTCOMES.clear()
    w3.plant_snapshot(root)
    monkeypatch.setattr(inputs, "MONOTONIC", lambda: 50.0)
    token = inputs.DEADLINE.set(10.0)
    try:
        with pytest.raises(inputs.ScanDeadline):  # the per-boot check stops new work first
            w3.gather(root)
    finally:
        inputs.DEADLINE.reset(token)
    assert len(scans) == 1


# -- the key covers the reducer code (S2-R28) --------------------------------------------------

_REDUCER_FILES = (
    "capture_node_log.py",
    "capture_node_log_io.py",
    "capture_audit_replay.py",
    "capture_audit_log_markers.py",
    "capture_audit_cache.py",
)


def _fake_source_dir(tmp_path: Path) -> Path:
    for name in (*_REDUCER_FILES, "capture_audit_inputs.py"):
        (tmp_path / name).write_bytes(name.encode())
    return tmp_path


@pytest.mark.parametrize("name", _REDUCER_FILES)
def test_a_changed_reducer_source_changes_the_source_hash(tmp_path: Path, name: str) -> None:
    """MUTATION: drop any one reducer glob from ``_REDUCER_GLOBS``."""
    source = _fake_source_dir(tmp_path)
    before = cache.reducer_source_hash_of(source)
    (source / name).write_bytes(b"changed")
    assert cache.reducer_source_hash_of(source) != before


def test_a_module_that_is_not_a_reducer_does_not_move_the_source_hash(tmp_path: Path) -> None:
    source = _fake_source_dir(tmp_path)
    before = cache.reducer_source_hash_of(source)
    (source / "capture_audit_inputs.py").write_bytes(b"changed")
    assert cache.reducer_source_hash_of(source) == before


def test_a_new_node_log_module_joins_the_source_hash(tmp_path: Path) -> None:
    source = _fake_source_dir(tmp_path)
    before = cache.reducer_source_hash_of(source)
    (source / "capture_node_log_new.py").write_bytes(b"x")
    assert cache.reducer_source_hash_of(source) != before


def test_the_real_reducer_modules_are_all_hashed() -> None:
    real = Path(cache.__file__).resolve().parent
    names = {p.name for p in real.glob("capture_node_log*.py")}
    assert {"capture_node_log.py", "capture_node_log_sinks.py"} <= names
    for name in _REDUCER_FILES[2:]:
        assert (real / name).is_file()
    assert cache.reducer_source_hash() == cache.reducer_source_hash_of(real)


def test_the_source_hash_is_computed_once_per_process() -> None:
    cache.reducer_source_hash.cache_clear()
    cache.reducer_source_hash()
    cache.reducer_source_hash()
    assert cache.reducer_source_hash.cache_info().misses == 1


def test_a_changed_reducer_changes_log_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = tmp_path / "breezy-trade-x.log"
    log.write_bytes(b"line\n")
    monkeypatch.setattr(cache, "reducer_source_hash", lambda: "a" * 64)
    before = cache.log_key(log)
    monkeypatch.setattr(cache, "reducer_source_hash", lambda: "b" * 64)
    assert cache.log_key(log) != before


# -- entries bind their key (S2-R29) -----------------------------------------------------------


def _entry_for(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Any]:
    root = w3.full_world(tmp_path, monkeypatch)
    result = inputs._scan_one(inputs._listed_logs(root)[0])
    return root, root / "cache" / "capture_audit", result


def test_an_entry_read_under_another_key_is_a_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MUTATION: drop the key comparison in ``_decode_result``."""
    root, directory, result = _entry_for(tmp_path, monkeypatch)
    key, other = "ab" * 32, "cd" * 32
    cache.write_scan_cache(root, key, cache.encode_result(result, key))
    (directory / f"scan_{other}.json").write_bytes((directory / f"scan_{key}.json").read_bytes())
    assert cache.read_scan_cache(root, key) is not None
    assert cache.read_scan_cache(root, other) is None  # copied under another name: not its key


def test_an_entry_without_a_key_is_a_miss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _root, _directory, result = _entry_for(tmp_path, monkeypatch)
    body = json.loads(cache.encode_result(result, "k"))
    assert cache._decode_result(json.dumps(body).encode(), "k") is not None
    del body["key"]
    assert cache._decode_result(json.dumps(body).encode(), "k") is None


# -- cache-read failures are misses (S2-R30) ---------------------------------------------------


def test_a_deeply_nested_entry_is_a_miss_not_a_crash() -> None:
    assert cache._decode_result(b"[" * 200_000, "k") is None


def test_an_overflowing_entry_is_a_miss_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    def overflow(_value: Any) -> Any:
        raise OverflowError("too large")

    monkeypatch.setattr(cache, "_dec", overflow)
    raw = json.dumps({"v": cache.CODEC_VERSION, "key": "k", "scan": 1}).encode()
    assert cache._decode_result(raw, "k") is None


def test_a_root_the_single_read_layer_refuses_is_a_miss(tmp_path: Path) -> None:
    key = "ab" * 32
    assert cache.read_scan_cache(tmp_path / "missing", key) is None
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "link").symlink_to(real)  # a root that is a symlink is refused (O_NOFOLLOW)
    with pytest.raises(SingleReadRefused):
        open_root(tmp_path / "link")
    assert cache.read_scan_cache(tmp_path / "link", key) is None
