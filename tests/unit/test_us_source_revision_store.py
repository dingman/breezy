"""F13-C1 S1: append-only revision store (H4, R17, R28, R32)."""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import signal
import threading
from pathlib import Path
from typing import Any

import pytest

from breezy.persistence import us_source_revision_store as store_module
from breezy.persistence.archive_cache import MANIFEST_VERSION, ArchiveCache, CoverageEntry
from breezy.persistence.us_source_request import (
    lamp_live_request,
    normalised_request,
    pfm_afos_request,
)
from breezy.persistence.us_source_revision_store import (
    AppendOutcome,
    RevisionPayloadRefusedError,
    RevisionStoreBusyError,
    RevisionStoreError,
    UsSourceRevisionStore,
)

RUN_TS = 1_790_000_000_000_000_000
SOURCE = "us-pfm-afos"
BASE = "pfm"
V0 = b"station,valid,tmax\nKSFO,2026-10-06,71\n"
V1 = b"station,valid,tmax\nKSFO,2026-10-06,72\n"
V2 = b"station,valid,tmax\nKSFO,2026-10-06,73\n"


class _Clock:
    def timestamp_ns(self) -> int:
        return RUN_TS + 7


def _store(root: Path, **kwargs: Any) -> UsSourceRevisionStore:
    return UsSourceRevisionStore(root, _Clock(), **kwargs)


def _append(store: UsSourceRevisionStore, payload: bytes, run_ts: int = RUN_TS) -> Any:
    return store.append_if_new(
        source=SOURCE, station="KSFO", run_ts_ns=run_ts, model="MTR", payload=payload
    )


def _revisions(store: UsSourceRevisionStore) -> tuple[tuple[int, str], ...]:
    return store.revisions(SOURCE, "KSFO", RUN_TS, BASE)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _append_product(store: UsSourceRevisionStore, index: int) -> Any:
    """One distinct issuance. Different ``run_ts`` so each product is its own cache key."""
    payload = f"station,valid,tmax\nKSFO,2026-10-06,{index}\n".encode()
    return store.append_if_new(
        source=SOURCE,
        station="KSFO",
        run_ts_ns=RUN_TS + index * 1_000_000_000,
        model="MTR",
        payload=payload,
    )


def _manifest_replaces(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    writes: list[str] = []
    real_replace = os.replace

    def spy(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        if Path(dst).name == "coverage.json":
            writes.append(Path(dst).name)
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    return writes


def test_first_payload_is_written_as_revision_zero(tmp_path: Path) -> None:
    store = _store(tmp_path)

    result = _append(store, V0)

    assert result.outcome is AppendOutcome.APPENDED
    assert result.revision == 0
    assert result.request == pfm_afos_request("KSFO", RUN_TS, revision=0)
    assert _revisions(store) == ((0, _sha(V0)),)


def test_identical_repoll_after_revision_appends_nothing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _append(store, V0)
    _append(store, V1)

    again_r0 = _append(store, V0)
    again_r1 = _append(store, V1)

    assert again_r0.outcome is AppendOutcome.UNCHANGED
    assert again_r1.outcome is AppendOutcome.UNCHANGED
    assert _revisions(store) == ((0, _sha(V0)), (1, _sha(V1)))


def test_changed_payload_for_same_key_appends_revision_not_overwrite(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _append(store, V0)

    result = _append(store, V1)

    assert (result.outcome, result.revision) == (AppendOutcome.APPENDED, 1)
    cache = ArchiveCache(tmp_path, fetch=lambda _r: b"unused", clock=_Clock())
    assert cache.read(pfm_afos_request("KSFO", RUN_TS, revision=0)) == V0
    assert cache.read(pfm_afos_request("KSFO", RUN_TS, revision=1)) == V1


def test_revision_written_as_product_suffix_r_n_with_window_start_run_ts(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for payload in (V0, V1, V2):
        _append(store, payload)

    cache = ArchiveCache(tmp_path, fetch=lambda _r: b"", clock=_Clock())
    entries = cache.entries(SOURCE)

    assert sorted(e.product for e in entries) == ["pfm-r0", "pfm-r1", "pfm-r2"]
    assert {(e.window_start, e.window_end) for e in entries} == {(RUN_TS, RUN_TS + 1)}
    assert {e.model for e in entries} == {"MTR"}


def test_n_is_one_plus_highest_existing_revision_not_a_count(tmp_path: Path) -> None:
    store = _store(tmp_path)
    cache = ArchiveCache(tmp_path, fetch=lambda _r: V0, clock=_Clock())
    cache.get_or_fetch(pfm_afos_request("KSFO", RUN_TS, revision=0))
    ArchiveCache(tmp_path, fetch=lambda _r: V1, clock=_Clock()).get_or_fetch(
        pfm_afos_request("KSFO", RUN_TS, revision=4)
    )

    result = _append(store, V2)

    assert result.revision == 5


def test_get_or_fetch_is_the_write_path_never_the_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, bool]] = []
    original = ArchiveCache.get_or_fetch

    def spy(self: ArchiveCache, request: Any) -> bytes:
        calls.append((request.product, self.missing(request)))
        return original(self, request)

    monkeypatch.setattr(ArchiveCache, "get_or_fetch", spy)
    store = _store(tmp_path)

    _append(store, V0)
    _append(store, V0)
    _append(store, V1)
    _append(store, V1)

    assert calls == [("pfm-r0", True), ("pfm-r1", True)]


def test_write_is_refused_when_the_key_exists_but_its_digest_is_not_in_the_set(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _append(store, V0)
    # A store whose digest view cannot see r0 while its key exists is an integrity fault.
    store.revisions = lambda *a, **k: ()  # type: ignore[method-assign]
    with pytest.raises(store_module.RevisionStoreIntegrityError, match="already exists"):
        _append(store, V1)


def test_first_seen_revision_is_the_anchor_revision(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.anchor_revision(SOURCE, "KSFO", RUN_TS, BASE) is None
    for payload in (V0, V1, V2):
        _append(store, payload)

    assert store.anchor_revision(SOURCE, "KSFO", RUN_TS, BASE) == 0
    assert _revisions(store)[0] == (0, _sha(V0))


def test_digest_set_is_scoped_to_station_run_ts_and_base_product(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _append(store, V0)
    store.append_if_new(source=SOURCE, station="KMIA", run_ts_ns=RUN_TS, model="MFL", payload=V1)
    _append(store, V2, run_ts=RUN_TS + 3_600_000_000_000)

    assert store.digests(SOURCE, "KSFO", RUN_TS, BASE) == {_sha(V0)}
    assert store.digests(SOURCE, "KMIA", RUN_TS, BASE) == {_sha(V1)}
    # The same bytes under another station or run_ts are NOT unchanged: they are a new key.
    assert _append(store, V1).outcome is AppendOutcome.APPENDED


def test_normalised_csv_is_excluded_from_the_digest_set_and_n(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _append(store, V0)
    norm = normalised_request(pfm_afos_request("KSFO", RUN_TS, revision=0))
    ArchiveCache(tmp_path, fetch=lambda _r: b"a,b\n1,2\n", clock=_Clock()).get_or_fetch(norm)

    assert _revisions(store) == ((0, _sha(V0)),)
    assert _append(store, V1).revision == 1


def test_other_sources_with_a_matching_base_product_are_not_mixed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append_if_new(
        source="us-lamp-live", station="ALL", run_ts_ns=RUN_TS, model=None, payload=V0
    )
    assert store.digests(SOURCE, "ALL", RUN_TS, BASE) == frozenset()
    assert lamp_live_request(RUN_TS).product == "lamp-lavtxt-r0"


def test_unit_lock_is_collector_lock_never_coverage_json_lock(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.lock_path(SOURCE) == tmp_path / SOURCE / "collector.lock"

    _append(store, V0)

    assert (tmp_path / SOURCE / "collector.lock").exists()
    assert store.lock_path(SOURCE).name != "coverage.json.lock"


def test_overlapping_holder_of_the_unit_lock_is_refused_not_blocked(tmp_path: Path) -> None:
    store = _store(tmp_path)
    lock = store.lock_path(SOURCE)
    lock.parent.mkdir(parents=True)
    with lock.open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RevisionStoreBusyError):
            _append(store, V0)
    assert _revisions(store) == ()


def test_append_does_not_need_the_cache_coverage_lock_to_be_free(tmp_path: Path) -> None:
    """The store lock is a different file: holding it never blocks the cache's own commit."""
    store = _store(tmp_path)
    with store.unit_lock(SOURCE):
        assert _append(store, V0).outcome is AppendOutcome.APPENDED


def test_unit_lock_is_reentrant_inside_one_store_and_released_after(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with store.unit_lock(SOURCE):
        with store.unit_lock(SOURCE):
            pass
        _append(store, V0)
    other = _store(tmp_path)
    with other.unit_lock(SOURCE):
        pass


def test_symlinked_unit_lock_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    (tmp_path / SOURCE).mkdir()
    target = tmp_path / "elsewhere"
    target.write_text("x")
    store.lock_path(SOURCE).symlink_to(target)
    with pytest.raises(store_module.RevisionStoreIntegrityError, match="symlink"):
        _append(store, V0)


def _no_files_written(root: Path) -> bool:
    return not any(p.name.endswith(".csv") or p.name == "coverage.json" for p in root.rglob("*"))


@pytest.mark.parametrize("bad", [b"", b"  \n", b"\xff\xfe\x00bad"])
def test_non_utf8_or_empty_payload_refused_with_no_orphan(tmp_path: Path, bad: bytes) -> None:
    store = _store(tmp_path)
    with pytest.raises(RevisionPayloadRefusedError):
        _append(store, bad)
    assert _no_files_written(tmp_path)


def test_validator_runs_before_the_write_and_a_refusal_leaves_no_orphan(tmp_path: Path) -> None:
    seen: list[bytes] = []

    class _ParseRefused(Exception):
        pass

    def validator(payload: bytes) -> None:
        seen.append(payload)
        raise _ParseRefused("bad row")

    store = _store(tmp_path, validator=validator)
    with pytest.raises(RevisionPayloadRefusedError) as info:
        _append(store, V0)

    assert isinstance(info.value.__cause__, _ParseRefused)
    assert seen == [V0]
    assert _no_files_written(tmp_path)


def test_validator_runs_on_every_poll_but_an_unchanged_repoll_writes_nothing(
    tmp_path: Path,
) -> None:
    calls: list[int] = []
    store = _store(tmp_path, validator=lambda p: calls.append(len(p)))
    _append(store, V0)
    _append(store, V0)
    assert len(calls) == 2  # validated every poll (cheap), written once
    assert _revisions(store) == ((0, _sha(V0)),)


def test_rerun_never_duplicates_payload_or_manifest_entry(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for _ in range(3):
        _append(store, V0)

    payloads = sorted((tmp_path / SOURCE).glob("*.csv"))
    manifest = json.loads((tmp_path / SOURCE / "coverage.json").read_text())
    assert len(payloads) == 1
    assert len(manifest["entries"]) == 1


def test_append_recovers_from_an_orphan_payload_without_a_manifest_entry(tmp_path: Path) -> None:
    request = pfm_afos_request("KSFO", RUN_TS, revision=0)
    orphan = tmp_path / SOURCE / f"{request.cache_key()}.csv"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"half written")

    result = _append(_store(tmp_path), V0)

    assert result.revision == 0
    assert orphan.read_bytes() == V0
    assert len(ArchiveCache(tmp_path, fetch=lambda _r: b"", clock=_Clock()).entries(SOURCE)) == 1


def test_unknown_source_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown US source"):
        _store(tmp_path).append_if_new(
            source="iem-mos", station="KSFO", run_ts_ns=RUN_TS, model=None, payload=V0
        )


def _probe(deviation: float | None):  # type: ignore[no-untyped-def]
    return lambda _payload: deviation


def test_unconfirmed_outlier_not_promoted(tmp_path: Path) -> None:
    store = _store(tmp_path, outlier_probe=_probe(9.0), outlier_threshold_f=5.0)

    result = _append(store, V0)

    assert result.outcome is AppendOutcome.QUARANTINED
    assert result.revision is None
    assert _revisions(store) == ()
    assert _no_files_written(tmp_path)


def test_quarantined_outlier_excluded_from_features_and_counted(tmp_path: Path) -> None:
    deviations = {V0: 0.5, V1: 12.0}
    store = _store(tmp_path, outlier_probe=lambda p: deviations[p], outlier_threshold_f=5.0)
    _append(store, V0)
    _append(store, V1)
    _append(store, V1)

    assert store.digests(SOURCE, "KSFO", RUN_TS, BASE) == {_sha(V0)}
    assert store.quarantined_count(SOURCE, "KSFO", RUN_TS, BASE) == 1
    ledger = (tmp_path / SOURCE / "quarantine.jsonl").read_text().splitlines()
    assert len(ledger) == 1
    row = json.loads(ledger[0])
    assert (row["sha256"], row["deviation_f"], row["station"]) == (_sha(V1), 12.0, "KSFO")


def test_deviation_at_or_below_threshold_is_promoted(tmp_path: Path) -> None:
    store = _store(tmp_path, outlier_probe=_probe(5.0), outlier_threshold_f=5.0)
    assert _append(store, V0).outcome is AppendOutcome.APPENDED


def test_no_comparator_means_not_an_outlier(tmp_path: Path) -> None:
    store = _store(tmp_path, outlier_probe=_probe(None), outlier_threshold_f=5.0)
    assert _append(store, V0).outcome is AppendOutcome.APPENDED


def test_outlier_probe_and_threshold_come_together_and_threshold_is_positive(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="together"):
        _store(tmp_path, outlier_probe=_probe(1.0))
    with pytest.raises(ValueError, match="together"):
        _store(tmp_path, outlier_threshold_f=5.0)
    with pytest.raises(ValueError, match="> 0"):
        _store(tmp_path, outlier_probe=_probe(1.0), outlier_threshold_f=0.0)


def test_corrupt_quarantine_ledger_is_an_integrity_error(tmp_path: Path) -> None:
    store = _store(tmp_path, outlier_probe=_probe(9.0), outlier_threshold_f=5.0)
    _append(store, V0)
    (tmp_path / SOURCE / "quarantine.jsonl").write_text("not json\n")
    with pytest.raises(store_module.RevisionStoreIntegrityError, match="corrupt"):
        store.quarantined_count(SOURCE, "KSFO", RUN_TS, BASE)


def test_revision_store_refusals_are_not_transport_cli_parse_or_cli_sanity_errors() -> None:
    from breezy.ingest.http import TransportError
    from breezy.normalize.cli_parse import CliParseError
    from breezy.normalize.sanity import CliSanityError

    refusals = [
        v
        for v in vars(store_module).values()
        if isinstance(v, type) and issubclass(v, RevisionStoreError)
    ]
    assert len(refusals) >= 4
    for refusal in refusals:
        assert not issubclass(refusal, (TransportError, CliParseError, CliSanityError))
        assert issubclass(refusal, Exception)


def test_validator_store_error_passes_through_unwrapped(tmp_path: Path) -> None:
    def validator(_payload: bytes) -> None:
        raise RevisionStoreBusyError("own refusal")

    with pytest.raises(RevisionStoreBusyError):
        _append(_store(tmp_path, validator=validator), V0)


def test_only_decode_and_csv_errors_are_wrapped_as_payload_refusals(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(RevisionPayloadRefusedError, match="UTF-8 or CSV"):
        _append(store, b"\xff\xfe")
    with pytest.raises(RevisionPayloadRefusedError):
        store.append_if_new(
            source=SOURCE,
            station="KSFO",
            run_ts_ns=RUN_TS,
            model="MTR",
            payload="str",  # type: ignore[arg-type]
        )


def test_a_second_thread_entering_a_locked_instance_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    outcome: list[BaseException | None] = []

    def other_thread() -> None:
        try:
            _append(store, V1)
            outcome.append(None)
        except BaseException as exc:  # noqa: BLE001
            outcome.append(exc)

    with store.unit_lock(SOURCE):
        thread = threading.Thread(target=other_thread)
        thread.start()
        thread.join()
        _append(store, V0)  # the owner thread still re-enters

    assert len(outcome) == 1
    assert isinstance(outcome[0], RevisionStoreBusyError)
    assert _revisions(store) == ((0, _sha(V0)),)


def test_lock_is_released_for_another_thread_after_the_owner_leaves(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _append(store, V0)
    results: list[Any] = []
    thread = threading.Thread(target=lambda: results.append(_append(store, V1)))
    thread.start()
    thread.join()
    assert results[0].outcome is AppendOutcome.APPENDED


@pytest.mark.parametrize(
    "line",
    [
        "{}",
        '{"sha256": "a"}',
        "[1]",
        '{"sha256": 1, "station": "K", "run_ts_ns": 1, "base_product": "pfm"}',
    ],
)
def test_malformed_quarantine_row_is_an_integrity_error_not_a_keyerror(
    tmp_path: Path, line: str
) -> None:
    store = _store(tmp_path, outlier_probe=_probe(9.0), outlier_threshold_f=5.0)
    (tmp_path / SOURCE).mkdir()
    (tmp_path / SOURCE / "quarantine.jsonl").write_text(line + "\n")
    with pytest.raises(store_module.RevisionStoreIntegrityError):
        store.quarantined_count(SOURCE, "KSFO", RUN_TS, BASE)
    with pytest.raises(store_module.RevisionStoreIntegrityError):
        _append(store, V0)


def test_coverage_batch_writes_the_manifest_once_per_batch_not_per_product(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Appending k products in one batch rewrites coverage.json O(1) times, not k."""
    writes = _manifest_replaces(monkeypatch)
    store = _store(tmp_path)
    k = 12
    with store.coverage_batch():
        for index in range(k):
            assert _append_product(store, index).outcome is AppendOutcome.APPENDED
        assert writes == []
        assert list((tmp_path / SOURCE).glob("*.csv"))
        assert not (tmp_path / SOURCE / "coverage.json").exists()
        # The unit lock is not held between products. Another store must still
        # see each key (via the journal) before coverage.json is rewritten.
        other = _store(tmp_path)
        for index in range(k):
            seen = other.revisions(SOURCE, "KSFO", RUN_TS + index * 1_000_000_000, BASE)
            assert len(seen) == 1

    assert writes == ["coverage.json"]
    assert not (tmp_path / SOURCE / "coverage.pending.jsonl").exists()
    manifest = json.loads((tmp_path / SOURCE / "coverage.json").read_text(encoding="utf-8"))
    assert len(manifest["entries"]) == k


def test_coverage_batch_flushes_every_m_products_and_again_on_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert store_module.COVERAGE_FLUSH_EVERY > 1
    monkeypatch.setattr(store_module, "COVERAGE_FLUSH_EVERY", 4)
    writes = _manifest_replaces(monkeypatch)
    store = _store(tmp_path)
    with store.coverage_batch():
        for index in range(5):
            _append_product(store, index)
        assert len(writes) == 1
    assert len(writes) == 2
    manifest = json.loads((tmp_path / SOURCE / "coverage.json").read_text(encoding="utf-8"))
    assert len(manifest["entries"]) == 5


def test_coverage_batch_manifest_bytes_match_per_append_commits(tmp_path: Path) -> None:
    def fill(root: Path, *, batched: bool) -> bytes:
        store = _store(root)
        if batched:
            with store.coverage_batch():
                for index in range(6):
                    _append_product(store, index)
        else:
            for index in range(6):
                _append_product(store, index)
        return (root / SOURCE / "coverage.json").read_bytes()

    assert fill(tmp_path / "plain", batched=False) == fill(tmp_path / "batched", batched=True)


def test_interrupted_coverage_batch_does_not_publish_unflushed_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_replace = os.replace

    def crash(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        if Path(dst).name == "coverage.json":
            raise OSError("crash before manifest commit")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", crash)
    store = _store(tmp_path)
    with pytest.raises(OSError, match="crash before manifest commit"), store.coverage_batch():
        for index in range(4):
            _append_product(store, index)

    manifest = tmp_path / SOURCE / "coverage.json"
    journal = tmp_path / SOURCE / "coverage.pending.jsonl"
    assert not manifest.exists()
    assert journal.is_file()
    assert len(list((tmp_path / SOURCE).glob("*.csv"))) == 4
    fresh = ArchiveCache(tmp_path, fetch=lambda _request: b"", clock=_Clock())
    assert fresh.entries(SOURCE) == ()

    monkeypatch.setattr(os, "replace", real_replace)
    resumed = _store(tmp_path)
    with resumed.coverage_batch():
        for index in range(4):
            # The journal survived, so the digest is already stored. Resume
            # must not allocate another revision, and the batch exit publishes it.
            result = _append_product(resumed, index)
            assert result.outcome is AppendOutcome.UNCHANGED
    assert len(json.loads(manifest.read_text(encoding="utf-8"))["entries"]) == 4
    assert not journal.exists()
    with resumed.coverage_batch():
        for index in range(4):
            assert _append_product(resumed, index).outcome is AppendOutcome.UNCHANGED


def test_coverage_batch_flushes_when_the_batch_raises(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(RuntimeError, match="boom"), store.coverage_batch():
        _append_product(store, 0)
        raise RuntimeError("boom")
    manifest = json.loads((tmp_path / SOURCE / "coverage.json").read_text(encoding="utf-8"))
    assert len(manifest["entries"]) == 1


def test_coverage_batch_does_not_install_a_signal_handler(tmp_path: Path) -> None:
    """SIGTERM and SIGKILL stay the process default. The journal is the crash story."""
    before = signal.getsignal(signal.SIGTERM)
    store = _store(tmp_path)
    with store.coverage_batch():
        during = signal.getsignal(signal.SIGTERM)
        _append_product(store, 0)
    assert during is before
    assert signal.getsignal(signal.SIGTERM) is before
    assert not hasattr(store_module, "_arm_sigterm")


def _journal_entry(key: str, sha: str, body: bytes) -> CoverageEntry:
    return CoverageEntry(
        cache_key=key,
        station="KSFO",
        product="pfm-r0",
        window_start=RUN_TS,
        window_end=RUN_TS + 1,
        rows=1,
        bytes=len(body),
        sha256=sha,
        fetched_at_ns=1,
        model="MTR",
        manifest_version=MANIFEST_VERSION,
    )


def _write_journal(root: Path, source: str, entry: CoverageEntry) -> Path:
    directory = root / source
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "coverage.pending.jsonl"
    line = json.dumps(entry.to_dict(), sort_keys=True, separators=(",", ":"))
    path.write_text(line + "\n", encoding="utf-8")
    return path


def test_second_store_during_open_batch_does_not_double_append_or_miss(
    tmp_path: Path,
) -> None:
    first = _store(tmp_path)
    second = _store(tmp_path)
    with first.coverage_batch():
        assert _append_product(first, 0).outcome is AppendOutcome.APPENDED
        assert _append_product(second, 0).outcome is AppendOutcome.UNCHANGED
        assert _append_product(second, 1).outcome is AppendOutcome.APPENDED
    manifest = json.loads((tmp_path / SOURCE / "coverage.json").read_text(encoding="utf-8"))
    assert len(manifest["entries"]) == 2
    assert len(list((tmp_path / SOURCE).glob("*.csv"))) == 2
    assert not (tmp_path / SOURCE / "coverage.pending.jsonl").exists()


def test_flush_drops_missing_csv_and_sha_mismatch_and_counts_them(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = _store(tmp_path)
    with caplog.at_level(logging.ERROR), store.coverage_batch() as result:
        _append_product(store, 0)
        _append_product(store, 1)
        _append_product(store, 2)
        csvs = sorted((tmp_path / SOURCE).glob("*.csv"))
        csvs[0].unlink()
        csvs[1].write_bytes(b"not-the-bytes-we-hashed\n")
    reasons = sorted(drop.reason for drop in result.dropped)
    assert reasons == ["csv_missing", "sha_mismatch"]
    assert result.flushed == 1
    assert result.stranded == []
    assert not (tmp_path / SOURCE / "coverage.pending.jsonl").exists()
    manifest = json.loads((tmp_path / SOURCE / "coverage.json").read_text(encoding="utf-8"))
    assert len(manifest["entries"]) == 1
    messages = [record.message for record in caplog.records if record.levelno >= logging.ERROR]
    assert any("csv_missing" in message for message in messages)
    assert any("sha_mismatch" in message for message in messages)


def test_torn_trailing_journal_line_is_tolerated_and_counted(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = _store(tmp_path)
    journal = tmp_path / SOURCE / "coverage.pending.jsonl"
    with caplog.at_level(logging.WARNING), store.coverage_batch() as result:
        _append_product(store, 0)
        with journal.open("ab") as handle:
            handle.write(b'{"torn"')
    assert result.flushed == 1
    assert result.dropped == []
    assert not journal.exists()
    warnings = [record.message for record in caplog.records if record.levelno == logging.WARNING]
    assert any("bad_lines=1" in message for message in warnings)


def test_corrupt_middle_journal_line_raises(tmp_path: Path) -> None:
    store = _store(tmp_path)
    journal = tmp_path / SOURCE / "coverage.pending.jsonl"
    with pytest.raises(store_module.RevisionStoreIntegrityError), store.coverage_batch():
        _append_product(store, 0)
        _append_product(store, 1)
        lines = journal.read_text(encoding="utf-8").splitlines()
        journal.write_text(lines[0] + "\n{not-json}\n" + lines[1] + "\n", encoding="utf-8")
    assert journal.is_file()
    assert not (tmp_path / SOURCE / "coverage.json").exists()


def test_flush_retries_lock_leaves_journal_and_keeps_in_flight_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert store_module._COVERAGE_LOCK_ATTEMPTS == 10
    assert store_module._COVERAGE_LOCK_BACKOFF_S == 0.5
    monkeypatch.setattr(store_module, "_COVERAGE_LOCK_ATTEMPTS", 3)
    monkeypatch.setattr(store_module, "_COVERAGE_LOCK_BACKOFF_S", 0.0)
    slept: list[float] = []
    monkeypatch.setattr(
        "breezy.persistence.us_source_revision_store.time.sleep",
        lambda seconds: slept.append(seconds),
    )
    phase = {"flush": False}
    calls = {"n": 0}
    real_acquire = ArchiveCache._acquire_lock

    def counting(self: ArchiveCache, path: Path) -> int:
        if phase["flush"]:
            calls["n"] += 1
        return real_acquire(self, path)

    monkeypatch.setattr(ArchiveCache, "_acquire_lock", counting)
    store = _store(tmp_path)
    journal = tmp_path / SOURCE / "coverage.pending.jsonl"
    held: int | None = None
    try:
        with pytest.raises(RuntimeError, match="in-flight"), store.coverage_batch() as failed:
            _append_product(store, 0)
            held = os.open(tmp_path / SOURCE / "coverage.json.lock", os.O_RDWR)
            fcntl.flock(held, fcntl.LOCK_EX)
            phase["flush"] = True
            raise RuntimeError("in-flight")
        assert calls["n"] == 3
        assert slept == [0.0, 0.0]
        assert failed.stranded == [SOURCE]
        assert journal.is_file()
        assert not (tmp_path / SOURCE / "coverage.json").exists()
    finally:
        if held is not None:
            fcntl.flock(held, fcntl.LOCK_UN)
            os.close(held)

    calls["n"] = 0
    slept.clear()
    phase["flush"] = False
    store = _store(tmp_path)
    held = None
    try:
        with store.coverage_batch() as quiet:
            _append_product(store, 1)
            held = os.open(tmp_path / SOURCE / "coverage.json.lock", os.O_RDWR)
            fcntl.flock(held, fcntl.LOCK_EX)
            phase["flush"] = True
        assert calls["n"] == 3
        assert quiet.stranded == [SOURCE]
        assert journal.is_file()
    finally:
        if held is not None:
            fcntl.flock(held, fcntl.LOCK_UN)
            os.close(held)


def test_flush_continues_to_later_sources_when_one_lock_is_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module, "_COVERAGE_LOCK_ATTEMPTS", 2)
    monkeypatch.setattr(store_module, "_COVERAGE_LOCK_BACKOFF_S", 0.0)
    monkeypatch.setattr(
        "breezy.persistence.us_source_revision_store.time.sleep",
        lambda _seconds: None,
    )
    body = b"station,valid,tmax\nKSFO,2026-10-06,71\n"
    digest = hashlib.sha256(body).hexdigest()
    blocked = _journal_entry("a" * 64, digest, body)
    published = _journal_entry("b" * 64, digest, body)
    _write_journal(tmp_path, "aaa-blocked", blocked)
    ready = _write_journal(tmp_path, "bbb-ready", published)
    (tmp_path / "bbb-ready" / f"{published.cache_key}.csv").write_bytes(body)
    held = os.open(tmp_path / "aaa-blocked" / "coverage.json.lock", os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(held, fcntl.LOCK_EX)
        result = _store(tmp_path)._cache.flush_coverage()
    finally:
        fcntl.flock(held, fcntl.LOCK_UN)
        os.close(held)
    assert result.stranded == ["aaa-blocked"]
    assert result.flushed == 1
    assert not ready.exists()
    assert (tmp_path / "aaa-blocked" / "coverage.pending.jsonl").is_file()
    manifest = json.loads((tmp_path / "bbb-ready" / "coverage.json").read_text(encoding="utf-8"))
    assert published.cache_key in manifest["entries"]


def test_opening_a_source_replays_a_stranded_journal(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _append(store, V0)
    manifest_path = tmp_path / SOURCE / "coverage.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(iter(manifest["entries"].values()))
    manifest_path.unlink()
    journal = tmp_path / SOURCE / "coverage.pending.jsonl"
    journal.write_text(
        json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    fresh = _store(tmp_path)
    assert fresh.revisions(SOURCE, "KSFO", RUN_TS, BASE) == ((0, _sha(V0)),)
    assert not journal.exists()
    assert manifest_path.is_file()
    assert _sha(V0) in manifest_path.read_text(encoding="utf-8")


def test_journal_key_without_csv_is_not_reported_present(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _append(store, V0)
    manifest_path = tmp_path / SOURCE / "coverage.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    key = next(iter(manifest["entries"]))
    entry = manifest["entries"][key]
    (tmp_path / SOURCE / f"{key}.csv").unlink()
    manifest_path.unlink()
    journal = tmp_path / SOURCE / "coverage.pending.jsonl"
    journal.write_text(
        json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    fresh = _store(tmp_path)
    assert fresh.revisions(SOURCE, "KSFO", RUN_TS, BASE) == ()


def test_flush_result_counts_cadence_flushes_and_the_exit_flush(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module, "COVERAGE_FLUSH_EVERY", 4)
    store = _store(tmp_path)
    with store.coverage_batch() as result:
        for index in range(5):
            _append_product(store, index)
    assert result.flushed == 5
    assert result.dropped == []
    assert result.stranded == []
