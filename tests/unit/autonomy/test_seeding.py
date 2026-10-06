"""AUT-4 WP2: derived resampling seeds (r11 §3.1, K7)."""

from __future__ import annotations

import datetime as dt
import hashlib

import pytest

from breezy.analysis.autonomy import seeding
from breezy.settlement import roi_bound

_SUBJECT = "ab" * 32
_DAY = dt.date(2026, 10, 6)


def test_seed_matches_the_pinned_formula() -> None:
    blob = b"\x1f".join([_SUBJECT.encode(), b"2026-10-06", b"fs_a_permutation"])
    expected = roi_bound.SEED ^ int(hashlib.sha256(blob).hexdigest()[:8], 16)
    assert seeding.derive_seed(_SUBJECT, _DAY, "fs_a_permutation") == expected


def test_same_slot_recompute_bit_identical() -> None:
    first = [seeding.derive_seed(_SUBJECT, _DAY, r) for r in seeding.ROLES]
    again = [seeding.derive_seed(_SUBJECT, _DAY, r) for r in seeding.ROLES]
    assert first == again


def test_seed_differs_by_subject_slot_and_role() -> None:
    base = seeding.derive_seed(_SUBJECT, _DAY, "fs_a_permutation")
    assert seeding.derive_seed("cd" * 32, _DAY, "fs_a_permutation") != base
    assert seeding.derive_seed(_SUBJECT, _DAY + dt.timedelta(days=1), "fs_a_permutation") != base
    assert seeding.derive_seed(_SUBJECT, _DAY, "fs_b_ev_signflip") != base
    assert len({seeding.derive_seed(_SUBJECT, _DAY, r) for r in seeding.ROLES}) == len(
        seeding.ROLES
    )


def test_role_is_closed_literal() -> None:
    assert set(seeding.ROLES) == {
        "screen_brier_bootstrap",
        "fs_a_permutation",
        "fs_b_ev_signflip",
        "fs_c_calibration_bootstrap",
    }
    with pytest.raises(ValueError):
        seeding.derive_seed(_SUBJECT, _DAY, "anything_else")


@pytest.mark.parametrize("bad", ["", "AB" * 32, "ab" * 31, "zz" * 32])
def test_subject_must_be_a_lowercase_sha256(bad: str) -> None:
    with pytest.raises(ValueError):
        seeding.derive_seed(bad, _DAY, "fs_a_permutation")


def test_slot_date_must_be_a_date() -> None:
    with pytest.raises(TypeError):
        seeding.derive_seed(_SUBJECT, "2026-10-06", "fs_a_permutation")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        seeding.derive_seed(_SUBJECT, dt.datetime(2026, 10, 6, tzinfo=dt.UTC), "fs_a_permutation")
