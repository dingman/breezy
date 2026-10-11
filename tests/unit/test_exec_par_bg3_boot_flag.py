"""EXEC-PAR BG-3: the boot-time check on the durable force-K1 flag (spec 1b, K3, N4)."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from breezy.runtime.exec_par_boot_flag import (
    AMENDMENT_DIR,
    FLAG_SET_EVENT,
    ForceK1BootDetail,
    has_valid_amendment_for,
)
from breezy.runtime.exec_par_latch_records import _FORCE_K1_FLAG
from breezy.runtime.exec_par_records import CleanupDemotion, ForceK1Flag
from breezy.runtime.health import AlertPayload
from breezy.runtime.node_config import force_k1_on_durable_flag
from breezy.runtime.submit_intent import SubmitIntentLatch, open_submit_intent_latch

DEMOTION_TS = 1_790_000_000_123_456_789
FLAG = ForceK1Flag(reason="stop_rule_5", ts_ns=5, set_by="breaker")


class _Store:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def set(self, key: str, value: bytes) -> None:
        self.data[key] = value

    def keys_with_prefix(self, prefix: str) -> list[str]:
        return sorted(k for k in self.data if k.startswith(prefix))


class _Sink:
    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


@contextmanager
def _latch(tmp_path: Path, *, k: int, store: _Store | None = None) -> Iterator[SubmitIntentLatch]:
    with open_submit_intent_latch(store or _Store(), tmp_path / "s.db", max_slots=k) as latch:
        yield latch


def _write_amendment(
    repo: Path, n: int, body: str, *, digest: str | None = None, sidecar: bool = True
) -> Path:
    directory = repo / AMENDMENT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"EXEC-PAR-D-PREREG-A{n}.md"
    path.write_text(body, encoding="utf-8")
    if sidecar:
        good = hashlib.sha256(body.encode("utf-8")).hexdigest()
        (directory / f"{path.name}.sha256").write_text(
            f"{digest or good}  {path.name}\n", encoding="utf-8"
        )
    return path


# -- durable flag -----------------------------------------------------------


def test_set_flag_forces_k1_and_alerts(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    sink = _Sink()
    with _latch(tmp_path, k=2) as latch:
        latch.write_force_k1_flag(FLAG)
        with caplog.at_level(logging.ERROR):
            assert force_k1_on_durable_flag(latch, repo_root=tmp_path, alert_sink=sink)
        assert latch.max_slots() == 1
        assert latch.k_forced_reason is not None
        assert "stop_rule_5" in latch.k_forced_reason
    assert [p.event for p in sink.payloads] == [FLAG_SET_EVENT]
    assert sink.payloads[0].detail == ForceK1BootDetail.FLAG_SET.value
    assert sink.payloads[0].severity == "CRITICAL"
    assert FLAG_SET_EVENT == "EXEC_PAR_FORCE_K1_FLAG_SET"
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_unreadable_flag_counts_as_set(tmp_path: Path) -> None:
    store = _Store()
    store.data[_FORCE_K1_FLAG] = b"\xff not a record"
    with _latch(tmp_path, k=3, store=store) as latch:
        assert force_k1_on_durable_flag(latch, repo_root=tmp_path, alert_sink=_Sink())
        assert latch.max_slots() == 1
        assert latch.k_forced_reason is not None


def test_cleared_flag_does_not_force_or_alert(tmp_path: Path) -> None:
    sink = _Sink()
    with _latch(tmp_path, k=2) as latch:
        assert not force_k1_on_durable_flag(latch, repo_root=tmp_path, alert_sink=sink)
        assert latch.max_slots() == 2
        assert latch.k_forced_reason is None
    assert sink.payloads == []


def test_set_flag_at_k1_is_a_noop_for_k(tmp_path: Path) -> None:
    with _latch(tmp_path, k=1) as latch:
        latch.write_force_k1_flag(FLAG)
        force_k1_on_durable_flag(latch, repo_root=tmp_path, alert_sink=_Sink())
        assert latch.max_slots() == 1


def test_a_raising_alert_sink_does_not_block_the_force(tmp_path: Path) -> None:
    class _Boom:
        def emit(self, payload: AlertPayload) -> None:
            raise RuntimeError("sink down")

    with _latch(tmp_path, k=2) as latch:
        latch.write_force_k1_flag(FLAG)
        assert force_k1_on_durable_flag(latch, repo_root=tmp_path, alert_sink=_Boom())
        assert latch.max_slots() == 1


# -- N4 cleanup-demotion pause ---------------------------------------------


def _demote(latch: SubmitIntentLatch, *, to_k: int = 1) -> None:
    latch.write_cleanup_demotion(
        CleanupDemotion(from_k=2, to_k=to_k, ts_ns=DEMOTION_TS, reason="x")
    )


def test_unamended_demotion_forces_k1(tmp_path: Path) -> None:
    sink = _Sink()
    with _latch(tmp_path, k=2) as latch:
        _demote(latch)
        assert force_k1_on_durable_flag(latch, repo_root=tmp_path, alert_sink=sink)
        assert latch.max_slots() == 1
        assert "cleanup_demotion" in (latch.k_forced_reason or "")
    assert sink.payloads == []  # not the durable flag: no flag-set alert


def test_valid_amendment_lifts_the_pause(tmp_path: Path) -> None:
    _write_amendment(tmp_path, 1, f"Re-promotes.\ncleanup_demotion_ts_ns: {DEMOTION_TS}\n")
    with _latch(tmp_path, k=2) as latch:
        _demote(latch)
        assert not force_k1_on_durable_flag(latch, repo_root=tmp_path, alert_sink=_Sink())
        assert latch.max_slots() == 2


def test_hash_mismatch_keeps_the_pause(tmp_path: Path) -> None:
    _write_amendment(tmp_path, 1, f"cleanup_demotion_ts_ns: {DEMOTION_TS}\n", digest="0" * 64)
    with _latch(tmp_path, k=2) as latch:
        _demote(latch)
        assert force_k1_on_durable_flag(latch, repo_root=tmp_path, alert_sink=_Sink())
        assert latch.max_slots() == 1


def test_missing_sha_sibling_keeps_the_pause(tmp_path: Path) -> None:
    _write_amendment(tmp_path, 1, f"cleanup_demotion_ts_ns: {DEMOTION_TS}\n", sidecar=False)
    with _latch(tmp_path, k=2) as latch:
        _demote(latch)
        assert force_k1_on_durable_flag(latch, repo_root=tmp_path, alert_sink=_Sink())


def test_missing_amendment_directory_keeps_the_pause(tmp_path: Path) -> None:
    with _latch(tmp_path, k=2) as latch:
        _demote(latch)
        assert force_k1_on_durable_flag(latch, repo_root=tmp_path / "nope", alert_sink=_Sink())


def test_amendment_for_a_different_record_keeps_the_pause(tmp_path: Path) -> None:
    _write_amendment(tmp_path, 1, f"cleanup_demotion_ts_ns: {DEMOTION_TS + 1}\n")
    with _latch(tmp_path, k=2) as latch:
        _demote(latch)
        assert force_k1_on_durable_flag(latch, repo_root=tmp_path, alert_sink=_Sink())


def test_demotion_to_k_above_one_does_not_force(tmp_path: Path) -> None:
    with _latch(tmp_path, k=2) as latch:
        _demote(latch, to_k=2)
        assert not force_k1_on_durable_flag(latch, repo_root=tmp_path, alert_sink=_Sink())
        assert latch.max_slots() == 2


def test_demotion_at_configured_k1_is_a_noop(tmp_path: Path) -> None:
    with _latch(tmp_path, k=1) as latch:
        _demote(latch)
        assert not force_k1_on_durable_flag(latch, repo_root=tmp_path, alert_sink=_Sink())
        assert latch.k_forced_reason is None


# -- resolver ---------------------------------------------------------------


def test_resolver_accepts_a_valid_referencing_amendment(tmp_path: Path) -> None:
    _write_amendment(tmp_path, 7, f"a\ncleanup_demotion_ts_ns: {DEMOTION_TS}\n")
    assert has_valid_amendment_for(tmp_path, DEMOTION_TS)


def test_resolver_does_not_match_a_digit_substring(tmp_path: Path) -> None:
    _write_amendment(tmp_path, 7, f"cleanup_demotion_ts_ns: {DEMOTION_TS}9\n")
    assert not has_valid_amendment_for(tmp_path, DEMOTION_TS)


def test_resolver_skips_a_bad_amendment_but_finds_a_good_one(tmp_path: Path) -> None:
    _write_amendment(tmp_path, 1, f"cleanup_demotion_ts_ns: {DEMOTION_TS}\n", digest="f" * 64)
    _write_amendment(tmp_path, 2, f"also\ncleanup_demotion_ts_ns: {DEMOTION_TS}\n")
    assert has_valid_amendment_for(tmp_path, DEMOTION_TS)


def test_resolver_treats_an_unreadable_file_as_no_amendment(tmp_path: Path) -> None:
    path = _write_amendment(tmp_path, 1, f"cleanup_demotion_ts_ns: {DEMOTION_TS}\n")
    path.write_bytes(b"\xff\xfe" + str(DEMOTION_TS).encode())  # not utf-8, hash now stale
    assert not has_valid_amendment_for(tmp_path, DEMOTION_TS)


def test_a_demotion_scan_failure_forces_k1_alerts_then_reraises(tmp_path: Path) -> None:
    class _NoScan:
        def __init__(self) -> None:
            self.data: dict[str, bytes] = {}

        def get(self, key: str) -> bytes | None:
            return self.data.get(key)

        def set(self, key: str, value: bytes) -> None:
            self.data[key] = value

    sink = _Sink()
    with open_submit_intent_latch(_NoScan(), tmp_path / "s.db", max_slots=2) as latch:
        with pytest.raises(RuntimeError):
            force_k1_on_durable_flag(latch, repo_root=tmp_path, alert_sink=sink)
        assert latch.max_slots() == 1
        assert latch.k_forced_reason is not None
    assert [(p.severity, p.detail) for p in sink.payloads] == [
        ("CRITICAL", ForceK1BootDetail.DEMOTION_SCAN_FAILED.value)
    ]


def test_a_flag_read_exception_forces_k1_first_then_reraises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = _Sink()
    with _latch(tmp_path, k=2) as latch:

        def boom() -> object:
            raise OSError("db gone")

        monkeypatch.setattr(latch, "read_force_k1_flag", boom)
        with pytest.raises(OSError, match="db gone"):
            force_k1_on_durable_flag(latch, repo_root=tmp_path, alert_sink=sink)
        assert latch.max_slots() == 1
    assert [p.detail for p in sink.payloads] == [ForceK1BootDetail.FLAG_UNREADABLE.value]


def test_unreadable_flag_emits_a_critical_unreadable_alert(tmp_path: Path) -> None:
    store = _Store()
    store.data[_FORCE_K1_FLAG] = b"\xff junk"
    sink = _Sink()
    with _latch(tmp_path, k=2, store=store) as latch:
        assert force_k1_on_durable_flag(latch, repo_root=tmp_path, alert_sink=sink)
    assert [(p.severity, p.event, p.detail) for p in sink.payloads] == [
        (
            "CRITICAL",
            "EXEC_PAR_FORCE_K1_FLAG_UNREADABLE",
            ForceK1BootDetail.FLAG_UNREADABLE.value,
        )
    ]


def test_a_bare_number_in_prose_does_not_unlock(tmp_path: Path) -> None:
    _write_amendment(tmp_path, 1, f"We discuss {DEMOTION_TS} here.\ncleanup_demotion_ts_ns: x\n")
    assert not has_valid_amendment_for(tmp_path, DEMOTION_TS)


def test_the_structured_line_must_stand_alone(tmp_path: Path) -> None:
    _write_amendment(tmp_path, 1, f"see cleanup_demotion_ts_ns: {DEMOTION_TS} above\n")
    assert not has_valid_amendment_for(tmp_path, DEMOTION_TS)


def test_a_missing_amendment_directory_logs_an_error_with_the_root(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR):
        assert not has_valid_amendment_for(tmp_path, DEMOTION_TS)
    assert any(
        r.levelno == logging.ERROR and str(tmp_path) in r.getMessage() for r in caplog.records
    )


# -- repo root is anchored on the module, never the cwd ---------------------


def test_repo_root_is_module_anchored_and_ignores_the_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from breezy.runtime.exec_par_boot_flag import default_repo_root

    monkeypatch.chdir(tmp_path)
    amendments = default_repo_root() / AMENDMENT_DIR
    assert "docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04" in amendments.as_posix()
    assert amendments.is_dir()
    assert not amendments.is_relative_to(tmp_path)


def test_boot_check_without_repo_root_uses_the_anchor_not_the_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A decoy amendment under the cwd must NOT lift the pause.
    _write_amendment(tmp_path, 1, f"cleanup_demotion_ts_ns: {DEMOTION_TS}\n")
    monkeypatch.chdir(tmp_path)
    with _latch(tmp_path, k=2) as latch:
        _demote(latch)
        assert force_k1_on_durable_flag(latch, alert_sink=_Sink())
        assert latch.max_slots() == 1
