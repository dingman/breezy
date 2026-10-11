"""EXEC-PAR D-PREREG r4.5 O3: the K>2 ceiling needs a sha-pinned, latest, passing O2 record."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from breezy.runtime import exec_par_promo_record as promo
from breezy.runtime.exec_par_boot_flag import AMENDMENT_DIR
from breezy.runtime.exec_par_promo_record import (
    ICC_V_FLOOR,
    PROMO_RECORD_DIR,
    PromoGuardDetail,
    apply_promo_guard,
    promo_record_problems,
    required_stage,
)
from breezy.runtime.health import AlertPayload
from breezy.runtime.submit_intent import SubmitIntentLatch, open_submit_intent_latch

TODAY = date(2026, 12, 1)


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
def _latch(tmp_path: Path, *, k: int) -> Iterator[SubmitIntentLatch]:
    with open_submit_intent_latch(_Store(), tmp_path / "s.db", max_slots=k) as latch:
        yield latch


def _record(stage: str = "S1", date: str = "2026-11-01", **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "stage": stage,
        "look_date": date,
        "verdict": "PASS",
        "v1": "PASS",
        "v2": "PASS",
        "v3": "PASS",
        "icc_v": 0.5,
        "bound_level": 90,
        "input_snapshot_sha256": "a" * 64,
        "created_ts_ns": 1_790_000_000_000_000_000,
    }
    base.update(over)
    return base


def _put(repo: Path, rec: dict[str, Any], *, pin: int | None = 1, bad_pin: bool = False) -> Path:
    directory = repo / PROMO_RECORD_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"exec_par_bg10_promo_{rec['stage']}_{rec['look_date']}.json"
    raw = json.dumps(rec).encode()
    path.write_bytes(raw)
    if pin is not None:
        digest = "0" * 64 if bad_pin else hashlib.sha256(raw).hexdigest()
        _amend(repo, pin, f"Promotes.\nbg10_promo_record_sha256: {digest}\n")
    return path


def _amend(repo: Path, n: int, body: str, *, digest: str | None = None) -> None:
    directory = repo / AMENDMENT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"EXEC-PAR-D-PREREG-A{n}.md"
    path.write_text(body, encoding="utf-8")
    good = digest or hashlib.sha256(body.encode()).hexdigest()
    (directory / f"{path.name}.sha256").write_text(f"{good}  {path.name}\n", encoding="utf-8")


# -- stage derivation / K boundary ------------------------------------------


@pytest.mark.parametrize(
    ("k", "stage"), [(1, None), (2, None), (3, "S1"), (4, "S1"), (5, "S2"), (6, "S2")]
)
def test_required_stage_follows_the_ramp(k: int, stage: str | None) -> None:
    assert required_stage(k) == stage


def test_k_above_the_ramp_has_no_valid_stage() -> None:
    assert required_stage(7) == "UNRAMPED"


@pytest.mark.parametrize("k", [1, 2])
def test_k_le_2_is_a_no_op_with_zero_reads(
    tmp_path: Path, k: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_: object, **__: object) -> None:
        raise AssertionError("read at K<=2")

    monkeypatch.setattr(Path, "iterdir", boom)
    monkeypatch.setattr(Path, "read_bytes", boom)
    assert promo_record_problems(tmp_path, k, today=TODAY) == []


def test_k3_without_a_record_is_a_problem(tmp_path: Path) -> None:
    assert promo_record_problems(tmp_path, 3, today=TODAY)


def test_k3_with_a_valid_record_passes(tmp_path: Path) -> None:
    _put(tmp_path, _record("S1"))
    assert promo_record_problems(tmp_path, 3, today=TODAY) == []


def test_k6_requires_s2_and_k4_requires_s1(tmp_path: Path) -> None:
    _put(tmp_path, _record("S1"))
    assert promo_record_problems(tmp_path, 4, today=TODAY) == []
    assert promo_record_problems(tmp_path, 6, today=TODAY)
    _put(tmp_path, _record("S2"), pin=2)
    assert promo_record_problems(tmp_path, 6, today=TODAY) == []


# -- validity clauses --------------------------------------------------------


def test_missing_record_directory(tmp_path: Path) -> None:
    assert any("no record" in p for p in promo_record_problems(tmp_path, 4, today=TODAY))


def test_fail_verdict_is_invalid(tmp_path: Path) -> None:
    _put(tmp_path, _record(verdict="FAIL"))
    assert promo_record_problems(tmp_path, 4, today=TODAY)


@pytest.mark.parametrize("key", ["v1", "v2", "v3"])
def test_any_failed_v_is_invalid(tmp_path: Path, key: str) -> None:
    _put(tmp_path, _record(**{key: "FAIL"}))
    assert promo_record_problems(tmp_path, 4, today=TODAY)


def test_icc_below_floor_is_invalid(tmp_path: Path) -> None:
    _put(tmp_path, _record(icc_v=0.4146))
    assert promo_record_problems(tmp_path, 4, today=TODAY)


def test_icc_exactly_at_floor_is_valid(tmp_path: Path) -> None:
    _put(tmp_path, _record(icc_v=ICC_V_FLOOR))
    assert promo_record_problems(tmp_path, 4, today=TODAY) == []


@pytest.mark.parametrize("icc", [None, "0.9", True, float("nan")])
def test_icc_must_be_a_finite_number(tmp_path: Path, icc: object) -> None:
    _put(tmp_path, _record(icc_v=icc))
    assert promo_record_problems(tmp_path, 4, today=TODAY)


def test_wrong_stage_is_invalid(tmp_path: Path) -> None:
    _put(tmp_path, _record("S1"))
    assert promo_record_problems(tmp_path, 6, today=TODAY)


def test_stage_field_must_match_the_filename(tmp_path: Path) -> None:
    path = _put(tmp_path, _record("S1"))
    path.write_bytes(json.dumps(_record("S2")).encode())
    assert promo_record_problems(tmp_path, 4, today=TODAY)


def test_look_date_field_must_match_the_filename(tmp_path: Path) -> None:
    path = _put(tmp_path, _record("S1", "2026-11-01"))
    path.write_bytes(json.dumps(_record("S1", "2026-11-02")).encode())
    assert promo_record_problems(tmp_path, 4, today=TODAY)


def test_later_fail_supersedes_earlier_pass(tmp_path: Path) -> None:
    _put(tmp_path, _record("S1", "2026-11-01"))
    _put(tmp_path, _record("S1", "2026-11-08", verdict="FAIL"), pin=2)
    assert promo_record_problems(tmp_path, 4, today=TODAY)


def test_later_pass_supersedes_earlier_fail(tmp_path: Path) -> None:
    _put(tmp_path, _record("S1", "2026-11-01", verdict="FAIL"))
    _put(tmp_path, _record("S1", "2026-11-08"), pin=2)
    assert promo_record_problems(tmp_path, 4, today=TODAY) == []


def test_unpinned_latest_does_not_fall_back_to_an_older_pinned_pass(tmp_path: Path) -> None:
    _put(tmp_path, _record("S1", "2026-11-01"))
    _put(tmp_path, _record("S1", "2026-11-08"), pin=None)
    assert promo_record_problems(tmp_path, 4, today=TODAY)


def test_unparseable_latest_record_is_invalid(tmp_path: Path) -> None:
    _put(tmp_path, _record("S1", "2026-11-01"))
    bad = tmp_path / PROMO_RECORD_DIR / "exec_par_bg10_promo_S1_2026-11-08.json"
    bad.write_text("{not json", encoding="utf-8")
    assert promo_record_problems(tmp_path, 4, today=TODAY)


def test_unpinned_record_is_invalid(tmp_path: Path) -> None:
    _put(tmp_path, _record(), pin=None)
    assert any("pin" in p for p in promo_record_problems(tmp_path, 4, today=TODAY))


def test_amendment_naming_a_different_sha_is_not_a_pin(tmp_path: Path) -> None:
    _put(tmp_path, _record(), bad_pin=True)
    assert promo_record_problems(tmp_path, 4, today=TODAY)


def test_pin_in_prose_does_not_count(tmp_path: Path) -> None:
    path = _put(tmp_path, _record(), pin=None)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    _amend(tmp_path, 1, f"see bg10_promo_record_sha256: {digest} in prose\n")
    assert promo_record_problems(tmp_path, 4, today=TODAY)


def test_amendment_with_bad_sidecar_sha_is_not_a_pin(tmp_path: Path) -> None:
    path = _put(tmp_path, _record(), pin=None)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    _amend(tmp_path, 1, f"bg10_promo_record_sha256: {digest}\n", digest="0" * 64)
    assert any("pin" in p for p in promo_record_problems(tmp_path, 4, today=TODAY))


def test_record_edited_after_pinning_is_invalid(tmp_path: Path) -> None:
    path = _put(tmp_path, _record(icc_v=0.5))
    path.write_bytes(json.dumps(_record(icc_v=0.9)).encode())
    assert promo_record_problems(tmp_path, 4, today=TODAY)


@pytest.mark.parametrize(
    "over",
    [
        {"bound_level": 80},
        {"input_snapshot_sha256": "xyz"},
        {"created_ts_ns": 0},
        {"created_ts_ns": "1"},
    ],
)
def test_malformed_fields_are_invalid(tmp_path: Path, over: dict[str, Any]) -> None:
    _put(tmp_path, _record(**over))
    assert promo_record_problems(tmp_path, 4, today=TODAY)


def test_missing_field_is_invalid(tmp_path: Path) -> None:
    rec = _record()
    del rec["input_snapshot_sha256"]
    _put(tmp_path, rec)
    assert promo_record_problems(tmp_path, 4, today=TODAY)


# -- BG-3 boot guard ---------------------------------------------------------


def test_boot_guard_forces_k1_and_alerts_critical_when_record_missing(tmp_path: Path) -> None:
    sink = _Sink()
    with _latch(tmp_path, k=4) as latch:
        assert apply_promo_guard(latch, repo_root=tmp_path, alert_sink=sink, today=TODAY)
        assert latch.max_slots() == 1
    assert [(p.severity, p.detail) for p in sink.payloads] == [
        ("CRITICAL", PromoGuardDetail.PROMO_RECORD_INVALID.value)
    ]


def test_boot_guard_keeps_k_with_a_valid_record(tmp_path: Path) -> None:
    _put(tmp_path, _record("S1"))
    sink = _Sink()
    with _latch(tmp_path, k=4) as latch:
        assert not apply_promo_guard(latch, repo_root=tmp_path, alert_sink=sink, today=TODAY)
        assert latch.max_slots() == 4
    assert sink.payloads == []


def test_boot_guard_k2_is_a_no_op(tmp_path: Path) -> None:
    sink = _Sink()
    with _latch(tmp_path, k=2) as latch:
        assert not apply_promo_guard(latch, repo_root=tmp_path, alert_sink=sink, today=TODAY)
        assert latch.max_slots() == 2
    assert sink.payloads == []


def test_boot_guard_k3_without_record_forces(tmp_path: Path) -> None:
    with _latch(tmp_path, k=3) as latch:
        assert apply_promo_guard(latch, repo_root=tmp_path, alert_sink=_Sink(), today=TODAY)
        assert latch.max_slots() == 1


def test_boot_guard_forces_before_re_raising_an_unexpected_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_: object, **__: object) -> list[str]:
        raise RuntimeError("boom")

    monkeypatch.setattr(promo, "promo_record_problems", explode)
    sink = _Sink()
    with _latch(tmp_path, k=4) as latch:
        with pytest.raises(RuntimeError):
            apply_promo_guard(latch, repo_root=tmp_path, alert_sink=sink, today=TODAY)
        assert latch.max_slots() == 1
    assert [(p.severity, p.detail) for p in sink.payloads] == [
        ("CRITICAL", PromoGuardDetail.PROMO_CHECK_FAILED.value)
    ]


def test_node_config_entry_applies_the_promo_guard(tmp_path: Path) -> None:
    from breezy.runtime.node_config import force_k1_on_durable_flag

    with _latch(tmp_path, k=4) as latch:
        assert force_k1_on_durable_flag(latch, repo_root=tmp_path, alert_sink=_Sink())
        assert latch.max_slots() == 1


# -- review fixes ------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "EXEC_PAR_BG10_PROMO_S1_2026-11-08.json",
        "exec_par_bg10_promo_S1_2026-11-8.json",
        "exec_par_bg10_promo_S1_2026-11-08.JSON",
        "exec_par_bg10_promo_S1_2026-13-01.json",
        "exec_par_bg10_promo_S1_2026-11-08.json.bak",
        "exec_par_bg10_promo_.json",
    ],
)
def test_malformed_record_name_blocks_even_with_a_pinned_earlier_pass(
    tmp_path: Path, name: str
) -> None:
    _put(tmp_path, _record("S1", "2026-11-01"))
    (tmp_path / PROMO_RECORD_DIR / name).write_text("{}", encoding="utf-8")
    assert any("malformed" in p for p in promo_record_problems(tmp_path, 4, today=TODAY))


def test_malformed_name_for_another_stage_also_blocks(tmp_path: Path) -> None:
    _put(tmp_path, _record("S1"))
    (tmp_path / PROMO_RECORD_DIR / "exec_par_bg10_promo_S2_2026-99-99.json").write_text("{}")
    assert promo_record_problems(tmp_path, 4, today=TODAY)


def test_unrelated_files_in_the_record_dir_are_ignored(tmp_path: Path) -> None:
    _put(tmp_path, _record("S1"))
    (tmp_path / PROMO_RECORD_DIR / "exec_par_bg10_results.json").write_text("{}")
    assert promo_record_problems(tmp_path, 4, today=TODAY) == []


def test_future_dated_record_is_a_problem(tmp_path: Path) -> None:
    _put(tmp_path, _record("S1", "2026-12-02"))
    assert any("future" in p for p in promo_record_problems(tmp_path, 4, today=TODAY))


def test_record_dated_today_is_valid(tmp_path: Path) -> None:
    _put(tmp_path, _record("S1", "2026-12-01"))
    assert promo_record_problems(tmp_path, 4, today=TODAY) == []


def test_huge_integer_icc_is_a_problem_not_an_exception(tmp_path: Path) -> None:
    path = _put(tmp_path, _record("S1"), pin=None)
    raw = path.read_text().replace('"icc_v": 0.5', '"icc_v": 1' + "0" * 400)
    path.write_text(raw)
    _amend(tmp_path, 1, f"bg10_promo_record_sha256: {hashlib.sha256(raw.encode()).hexdigest()}\n")
    assert promo_record_problems(tmp_path, 4, today=TODAY)


def test_deeply_nested_json_is_a_problem_not_an_exception(tmp_path: Path) -> None:
    path = _put(tmp_path, _record("S1"), pin=None)
    raw = "[" * 100_000 + "]" * 100_000
    path.write_text(raw)
    _amend(tmp_path, 1, f"bg10_promo_record_sha256: {hashlib.sha256(raw.encode()).hexdigest()}\n")
    assert promo_record_problems(tmp_path, 4, today=TODAY)


def test_duplicate_json_keys_are_a_problem(tmp_path: Path) -> None:
    path = _put(tmp_path, _record("S1"), pin=None)
    raw = path.read_text().replace('"verdict": "PASS"', '"verdict": "FAIL", "verdict": "PASS"')
    path.write_text(raw)
    _amend(tmp_path, 1, f"bg10_promo_record_sha256: {hashlib.sha256(raw.encode()).hexdigest()}\n")
    assert any("duplicate" in p for p in promo_record_problems(tmp_path, 4, today=TODAY))


class _RaisingSink:
    def emit(self, payload: AlertPayload) -> None:
        raise OSError("sink down")


def test_a_raising_alert_sink_still_leaves_k_forced(tmp_path: Path) -> None:
    with _latch(tmp_path, k=4) as latch:
        assert apply_promo_guard(latch, repo_root=tmp_path, alert_sink=_RaisingSink(), today=TODAY)
        assert latch.max_slots() == 1


def test_an_earlier_force_makes_the_guard_skip_silently(tmp_path: Path) -> None:
    sink = _Sink()
    with _latch(tmp_path, k=4) as latch:
        latch.force_k1("durable flag")
        assert not apply_promo_guard(latch, repo_root=tmp_path, alert_sink=sink, today=TODAY)
        assert latch.k_forced_reason == "durable flag"
    assert sink.payloads == []
