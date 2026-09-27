"""EDGE-3: per-family continuous-rung-hold halt (plan r2, r2 final amendment
BINDING).

Every fixture is built through the REAL writer path (`open_trial_day_latch`
bound to a real, opened `SubmitIntentLatch`) or through the verbatim fixture
bytes at `tests/fixtures/family_halt/legacy_v4_halt_2026-09-24.bin` (L-42) --
never an invented byte string standing in for the live legacy halt.

Plan §6.1: tests 1-14.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.strategy.current_rung_hold.trial_day_latch import (
    _HALT_CLEARED_MARKER,
    CONTINUOUS_TRIAL_KEY_PREFIX,
    FAMILY_HALT_CLEARED_KEY_PREFIX,
    FAMILY_HALT_KEY_PREFIX,
    FAMILY_ID_PATTERN,
    HALT_CLEARED_KEY_PREFIX,
    LEGACY_FAMILY_HALT_KEY,
    LEGACY_HALT_ATTRIBUTED_FAMILY_ID,
    LEGACY_HALT_PINNED_SHA256,
    FamilyHaltReading,
    TrialDayLatchError,
    classify_legacy,
    decode_family_halt_state,
    family_halt_key,
    open_trial_day_latch,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "family_halt"
    / "legacy_v4_halt_2026-09-24.bin"
)
V4 = LEGACY_HALT_ATTRIBUTED_FAMILY_ID
OTHER_FAMILY = "pm_us_crh_other"
NOW_NS = 1_800_000_000_000_000_000


def _fixture_bytes() -> bytes:
    return FIXTURE_PATH.read_bytes()


def _committed_keys(store_path: Path) -> set[str]:
    conn = sqlite3.connect(store_path)
    try:
        return {row[0] for row in conn.execute("SELECT key FROM state")}
    finally:
        conn.close()


def _committed_value(store_path: Path, key: str) -> bytes | None:
    conn = sqlite3.connect(store_path)
    try:
        row = conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()
    return row[0] if row is not None else None


def _write_raw(store_path: Path, key: str, raw: bytes | None) -> None:
    store = SqliteStateStore(store_path)
    try:
        if raw is not None:
            store.set(key, raw)
    finally:
        store.close()


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


# ---------------------------------------------------------------------------
# 1. test_every_halt_writer_writes_only_its_per_family_key
# ---------------------------------------------------------------------------


def _call_record_duplicate_fill(latch) -> None:
    latch.record_duplicate_fill(
        "SFO",
        "2026-09-04",
        venue_order_id="ord-1",
        qty=Decimal(1),
        fill_px=Decimal("0.40"),
        fee=Decimal("0.01"),
        ts_ns=NOW_NS,
    )


def _call_record_ambiguous_exit(latch) -> None:
    latch.record_ambiguous_exit(position_id="P-1", reason="order_rejected:test", ts_ns=NOW_NS)


def _call_record_policy_halt(latch) -> None:
    latch.record_policy_halt(reason="policy halt for test", evidence_sha256="0" * 64, ts_ns=NOW_NS)


@pytest.mark.parametrize(
    "writer",
    [
        pytest.param(_call_record_duplicate_fill, id="record_duplicate_fill"),
        pytest.param(_call_record_ambiguous_exit, id="record_ambiguous_exit"),
        pytest.param(_call_record_policy_halt, id="record_policy_halt"),
    ],
)
def test_every_halt_writer_writes_only_its_per_family_key(store_path: Path, writer) -> None:
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        latch = open_trial_day_latch(
            intent_latch,
            key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
            family_id=OTHER_FAMILY,
        )
        assert latch.is_family_halted() is False
        writer(latch)
        assert latch.is_family_halted() is True

    keys = _committed_keys(store_path)
    assert family_halt_key(OTHER_FAMILY) in keys
    assert LEGACY_FAMILY_HALT_KEY not in keys
    assert not any(
        k.startswith(FAMILY_HALT_KEY_PREFIX) and k != family_halt_key(OTHER_FAMILY) for k in keys
    )


# ---------------------------------------------------------------------------
# 2. test_halt_on_family_a_does_not_halt_family_b
# ---------------------------------------------------------------------------


def test_halt_on_family_a_does_not_halt_family_b(store_path: Path) -> None:
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        latch_a = open_trial_day_latch(
            intent_latch,
            key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
            family_id="pm_us_crh_a",
        )
        latch_b = open_trial_day_latch(
            intent_latch,
            key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
            family_id="pm_us_crh_b",
        )
        _call_record_duplicate_fill(latch_a)
        assert latch_a.is_family_halted() is True
        assert latch_b.is_family_halted() is False

    keys = _committed_keys(store_path)
    assert family_halt_key("pm_us_crh_a") in keys
    assert family_halt_key("pm_us_crh_b") not in keys


# ---------------------------------------------------------------------------
# 3. test_unpinned_legacy_value_halts_every_family
# ---------------------------------------------------------------------------


def _flip_one_byte(raw: bytes) -> bytes:
    return bytes([raw[0] ^ 0xFF]) + raw[1:]


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(_flip_one_byte(_fixture_bytes()), id="pinned_bytes_flipped_one_byte"),
        pytest.param(b'{"v":1}', id="valid_json_wrong_shape"),
        pytest.param(b"", id="empty_bytes"),
        pytest.param(b"\xff\xfe\x00garbage-not-utf8", id="corrupt_bytes"),
    ],
)
def test_unpinned_legacy_value_halts_every_family(raw: bytes) -> None:
    for family_id in (V4, OTHER_FAMILY):
        reading = decode_family_halt_state(family_id, raw, None)
        assert reading.halted is True, family_id
        assert reading.source == "legacy_halts_all", family_id
        assert reading.legacy == "halts_all", family_id


# ---------------------------------------------------------------------------
# 4. test_pinned_legacy_bytes_halt_v4_only
# ---------------------------------------------------------------------------


def test_pinned_legacy_bytes_halt_v4_only() -> None:
    pinned = _fixture_bytes()

    v4_reading = decode_family_halt_state(V4, pinned, None)
    assert v4_reading == FamilyHaltReading(
        halted=True,
        source="legacy_attributed",
        legacy="attributable_to_v4",
    )

    other_reading = decode_family_halt_state(OTHER_FAMILY, pinned, None)
    assert other_reading == FamilyHaltReading(
        halted=False,
        source="none",
        legacy="attributable_to_v4",
    )


# ---------------------------------------------------------------------------
# 5. test_absent_or_cleared_legacy_halts_no_family
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "legacy_raw",
    [pytest.param(None, id="absent"), pytest.param(_HALT_CLEARED_MARKER, id="cleared")],
)
def test_absent_or_cleared_legacy_halts_no_family(legacy_raw: bytes | None) -> None:
    for family_id in (V4, OTHER_FAMILY):
        reading = decode_family_halt_state(family_id, legacy_raw, None)
        assert reading.halted is False, family_id
        assert reading.source == "none", family_id


# ---------------------------------------------------------------------------
# 6. test_fixture_bytes_hash_to_the_full_64_hex_pin_and_are_259_bytes
# ---------------------------------------------------------------------------


def test_fixture_bytes_hash_to_the_full_64_hex_pin_and_are_259_bytes() -> None:
    raw = _fixture_bytes()
    assert len(raw) == 259
    assert len(LEGACY_HALT_PINNED_SHA256) == 64
    assert hashlib.sha256(raw).hexdigest() == LEGACY_HALT_PINNED_SHA256
    assert classify_legacy(raw) == "attributable_to_v4"


# ---------------------------------------------------------------------------
# 7. test_family_halt_key_rejects_...
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_id",
    [
        pytest.param("", id="empty"),
        pytest.param("..", id="dotdot"),
        pytest.param("a/b", id="slash"),
        pytest.param("~x", id="tilde"),
        pytest.param("a^b", id="caret"),
        pytest.param("a:b", id="colon"),
        pytest.param("a\x00b", id="nul"),
        pytest.param("a\nb", id="newline"),
        pytest.param("x" * 65, id="65_chars"),
    ],
)
def test_family_halt_key_rejects_empty_dotdot_slash_tilde_caret_colon_nul_newline_and_65_char_ids(
    bad_id: str,
) -> None:
    assert FAMILY_ID_PATTERN.fullmatch(bad_id) is None
    with pytest.raises(ValueError):
        family_halt_key(bad_id)
    with pytest.raises(ValueError):
        decode_family_halt_state(bad_id, None, None)


def test_family_halt_key_accepts_a_valid_64_char_id() -> None:
    valid = "x" * 64
    assert family_halt_key(valid) == f"{FAMILY_HALT_KEY_PREFIX}{valid}"


# ---------------------------------------------------------------------------
# 8. test_unbound_latch_raises_on_every_halt_method
# ---------------------------------------------------------------------------


def test_unbound_latch_raises_on_every_halt_method(store_path: Path) -> None:
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
        assert latch.family_id is None

        with pytest.raises(TrialDayLatchError):
            latch.is_family_halted()
        with pytest.raises(TrialDayLatchError):
            latch.family_halt_state()
        with pytest.raises(TrialDayLatchError):
            _call_record_duplicate_fill(latch)
        with pytest.raises(TrialDayLatchError):
            _call_record_ambiguous_exit(latch)
        with pytest.raises(TrialDayLatchError):
            _call_record_policy_halt(latch)
        with pytest.raises(TrialDayLatchError):
            latch.clear_family_halt(reason="x" * 20, evidence_sha256="0" * 64, ts_ns=NOW_NS)


# ---------------------------------------------------------------------------
# AM-3 class-C (3 new tests): an unbound latch fails CLOSED, never open.
# ---------------------------------------------------------------------------


def test_unbound_latch_is_family_halted_raises_rather_than_reports_unhalted(
    store_path: Path,
) -> None:
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
        with pytest.raises(TrialDayLatchError):
            latch.is_family_halted()


def test_unbound_latch_record_policy_halt_raises_rather_than_silently_no_ops(
    store_path: Path,
) -> None:
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
        with pytest.raises(TrialDayLatchError):
            _call_record_policy_halt(latch)
    assert _committed_keys(store_path) == set()


def test_unbound_latch_record_duplicate_fill_raises_rather_than_silently_no_ops(
    store_path: Path,
) -> None:
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
        with pytest.raises(TrialDayLatchError):
            _call_record_duplicate_fill(latch)
    # The duplicate-fill bucket is written before the halt in the source,
    # but the family-id check runs first (`_require_family_id` precedes the
    # bucket write) -- nothing at all is committed.
    assert _committed_keys(store_path) == set()


def test_a_veto_built_from_an_unbound_latch_fails_closed_never_allows(store_path: Path) -> None:
    """AM-3: "a veto built from an unbound latch fails CLOSED. It must deny,
    never allow." -- the veto delegates straight to `is_family_halted()`,
    so an unbound latch's veto raises rather than ever returning `None`
    (the "allow" value)."""
    from breezy.strategy.current_rung_hold.composition import family_halt_submit_veto

    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
        veto = family_halt_submit_veto(latch)
        with pytest.raises(TrialDayLatchError):
            result = veto()
            assert result != "family_halt"  # unreachable if it raises, as required


# ---------------------------------------------------------------------------
# 9. test_clear_v4_writes_audit_then_per_family_then_legacy_last_and_leaves_other_families
# ---------------------------------------------------------------------------


def test_clear_v4_writes_audit_then_per_family_then_legacy_last_and_leaves_other_families(
    store_path: Path,
) -> None:
    pinned = _fixture_bytes()
    _write_raw(store_path, LEGACY_FAMILY_HALT_KEY, pinned)
    # v4 is ALSO independently halted through its own per-family key (e.g. a
    # duplicate fill recorded before this legacy pin existed), on top of the
    # pinned legacy attribution -- seeded directly, since once the legacy
    # key already halts v4, the idempotent writer path never writes a
    # SECOND per-family halt (`record_duplicate_fill` only writes if
    # `is_family_halted()` was False, and here it is already True via
    # `legacy_attributed`).
    _write_raw(
        store_path,
        family_halt_key(V4),
        json.dumps({"v": 1, "reason": "duplicate_fill", "familyId": V4}).encode("utf-8"),
    )

    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        v4_latch = open_trial_day_latch(
            intent_latch,
            key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
            family_id=V4,
        )
        other_latch = open_trial_day_latch(
            intent_latch,
            key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
            family_id=OTHER_FAMILY,
        )
        _call_record_duplicate_fill(other_latch)
        assert v4_latch.is_family_halted() is True
        assert other_latch.is_family_halted() is True

        v4_latch.clear_family_halt(
            reason="new A1-class ruling retires v4",
            evidence_sha256="a" * 64,
            ts_ns=NOW_NS,
        )
        assert v4_latch.is_family_halted() is False
        assert other_latch.is_family_halted() is True, "other families are untouched"

    keys = _committed_keys(store_path)
    audit_keys = [k for k in keys if k.startswith(f"{FAMILY_HALT_CLEARED_KEY_PREFIX}{V4}/")]
    assert len(audit_keys) == 1
    audit = json.loads(_committed_value(store_path, audit_keys[0]).decode("utf-8"))
    assert audit["familyId"] == V4
    assert audit["legacySha256"] == hashlib.sha256(pinned).hexdigest()

    assert _committed_value(store_path, family_halt_key(V4)) == _HALT_CLEARED_MARKER
    assert _committed_value(store_path, LEGACY_FAMILY_HALT_KEY) == _HALT_CLEARED_MARKER
    assert _committed_value(store_path, family_halt_key(OTHER_FAMILY)) is not None
    assert _committed_value(store_path, family_halt_key(OTHER_FAMILY)) != _HALT_CLEARED_MARKER


# ---------------------------------------------------------------------------
# 10. test_clear_v4_interrupted_before_the_legacy_write_leaves_v4_halted_and_rerun_converges
# ---------------------------------------------------------------------------


def test_clear_v4_interrupted_before_the_legacy_write_leaves_v4_halted_and_rerun_converges(
    store_path: Path,
) -> None:
    pinned = _fixture_bytes()
    # Simulate the crash point: the per-family key has already been cleared,
    # but the legacy write never landed.
    _write_raw(store_path, LEGACY_FAMILY_HALT_KEY, pinned)
    _write_raw(store_path, family_halt_key(V4), _HALT_CLEARED_MARKER)

    reading = decode_family_halt_state(V4, pinned, _HALT_CLEARED_MARKER)
    assert reading.halted is True
    assert reading.source == "legacy_attributed"

    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        v4_latch = open_trial_day_latch(
            intent_latch,
            key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
            family_id=V4,
        )
        assert v4_latch.is_family_halted() is True, "still halted through the pinned legacy"
        v4_latch.clear_family_halt(
            reason="rerun after an interrupted clear",
            evidence_sha256="b" * 64,
            ts_ns=NOW_NS + 1,
        )
        assert v4_latch.is_family_halted() is False, "the rerun converges"

    assert _committed_value(store_path, LEGACY_FAMILY_HALT_KEY) == _HALT_CLEARED_MARKER


# ---------------------------------------------------------------------------
# 11. test_clear_non_v4_family_never_touches_the_pinned_legacy_value
# ---------------------------------------------------------------------------


def test_clear_non_v4_family_never_touches_the_pinned_legacy_value(store_path: Path) -> None:
    pinned = _fixture_bytes()
    _write_raw(store_path, LEGACY_FAMILY_HALT_KEY, pinned)

    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        other_latch = open_trial_day_latch(
            intent_latch,
            key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
            family_id=OTHER_FAMILY,
        )
        _call_record_duplicate_fill(other_latch)
        other_latch.clear_family_halt(
            reason="cleared a non-v4 family's own halt",
            evidence_sha256="c" * 64,
            ts_ns=NOW_NS,
        )
        assert other_latch.is_family_halted() is False

    assert _committed_value(store_path, LEGACY_FAMILY_HALT_KEY) == pinned
    assert classify_legacy(_committed_value(store_path, LEGACY_FAMILY_HALT_KEY)) == (
        "attributable_to_v4"
    )


# ---------------------------------------------------------------------------
# 12. test_clear_family_refuses_while_legacy_halts_all_and_writes_nothing
# ---------------------------------------------------------------------------


def test_clear_family_refuses_while_legacy_halts_all_and_writes_nothing(store_path: Path) -> None:
    corrupt = b"not-the-pinned-payload"
    _write_raw(store_path, LEGACY_FAMILY_HALT_KEY, corrupt)

    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        latch = open_trial_day_latch(
            intent_latch,
            key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
            family_id=OTHER_FAMILY,
        )
        before = _committed_keys(store_path)
        with pytest.raises(TrialDayLatchError):
            latch.clear_family_halt(
                reason="attempted clear during an unattributable legacy halt",
                evidence_sha256="d" * 64,
                ts_ns=NOW_NS,
            )
        after = _committed_keys(store_path)
    assert before == after
    assert _committed_value(store_path, LEGACY_FAMILY_HALT_KEY) == corrupt


# ---------------------------------------------------------------------------
# 13. test_clear_legacy_refuses_absent_cleared_and_pinned_and_clears_only_unpinned
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "legacy_raw",
    [
        pytest.param(None, id="absent"),
        pytest.param(_HALT_CLEARED_MARKER, id="cleared"),
        pytest.param(_fixture_bytes(), id="pinned"),
    ],
)
def test_clear_legacy_refuses_absent_cleared_and_pinned(
    store_path: Path,
    legacy_raw: bytes | None,
) -> None:
    _write_raw(store_path, LEGACY_FAMILY_HALT_KEY, legacy_raw)

    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
        with pytest.raises(TrialDayLatchError):
            latch.clear_legacy_family_halt(
                reason="attempted --legacy clear",
                evidence_sha256="e" * 64,
                ts_ns=NOW_NS,
            )
    assert _committed_value(store_path, LEGACY_FAMILY_HALT_KEY) == legacy_raw


def test_clear_legacy_clears_only_an_unpinned_value(store_path: Path) -> None:
    corrupt = b"an-unattributable-legacy-value"
    _write_raw(store_path, LEGACY_FAMILY_HALT_KEY, corrupt)

    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
        latch.clear_legacy_family_halt(
            reason="operator evidence: legacy value was stale test data",
            evidence_sha256="f" * 64,
            ts_ns=NOW_NS,
        )

    assert _committed_value(store_path, LEGACY_FAMILY_HALT_KEY) == _HALT_CLEARED_MARKER
    audit_keys = [k for k in _committed_keys(store_path) if k.startswith(HALT_CLEARED_KEY_PREFIX)]
    assert len(audit_keys) == 1
    audit = json.loads(_committed_value(store_path, audit_keys[0]).decode("utf-8"))
    assert audit["legacySha256"] == hashlib.sha256(corrupt).hexdigest()


# ---------------------------------------------------------------------------
# 14. test_pre_edge3_one_arg_decoder_ignores_per_family_keys
# ---------------------------------------------------------------------------


def _pre_edge3_decode_family_halt(raw: bytes | None) -> bool:
    """The removed rule, restated locally: `raw is not None and raw !=
    CLEARED` over the LEGACY key alone -- exactly what a not-yet-reverted
    (pre-EDGE-3) production build still does. Pinned here, never imported
    from production, so this test survives EDGE-3's own removal of the
    one-arg decoder (§8.4 rollback hazard)."""
    return raw is not None and raw != _HALT_CLEARED_MARKER


def test_pre_edge3_one_arg_decoder_ignores_per_family_keys(store_path: Path) -> None:
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        latch = open_trial_day_latch(
            intent_latch,
            key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
            family_id=OTHER_FAMILY,
        )
        _call_record_duplicate_fill(latch)
        assert latch.is_family_halted() is True, "current code sees the per-family halt"

    # Old code reads ONLY the legacy key -- which this store never wrote to.
    legacy_raw = _committed_value(store_path, LEGACY_FAMILY_HALT_KEY)
    assert legacy_raw is None
    assert _pre_edge3_decode_family_halt(legacy_raw) is False, (
        "the rollback hazard: reverted code would see this family as NOT halted"
    )
