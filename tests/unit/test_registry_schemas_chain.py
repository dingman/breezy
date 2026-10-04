"""ARCH-0 seam 6a: ``schemas`` (closed enums and records) and ``chain`` (the per-venue hash chain).

``schemas`` is pyarrow-free and imports only ``wire``, ``canonical`` and ``rollback_journal``.
``chain`` imports ``canonical`` and ``schemas``. The chain is one per venue: genesis
``sha256(b"registry/v1|" + venue)``, ``transition_hash = sha256(canonical_row || prev)``.
"""

from __future__ import annotations

import ast
import hashlib
import re
import typing
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest

import breezy.persistence.autonomy.chain as chain_mod
import breezy.persistence.autonomy.schemas as schemas_mod
from breezy.persistence import live_orders_gate
from breezy.persistence.autonomy import paths, pins
from breezy.persistence.autonomy.canonical import sha256_hex
from breezy.persistence.autonomy.chain import (
    ChainBroken,
    VerifiedVenueChain,
    canonical_row,
    genesis,
    seq_is_verified_prefix,
    transition_hash,
    verify_against_export,
    verify_extension,
    verify_venue_chain,
)
from breezy.persistence.autonomy.rollback_journal import JournalHead
from breezy.persistence.autonomy.schemas import (
    AdmissibilityResult,
    CauseClass,
    CauseCode,
    DecidedBy,
    ExportTrailer,
    FoldInvalidReason,
    Kind,
    LiveOrdersRefusal,
    ManifestFacts,
    RefusalReason,
    StagePolicy,
    State,
    TransitionRow,
    UnreadableReason,
    WriterMode,
    compute_transition_id,
)
from breezy.persistence.autonomy.wire import WireRefusalReason, WireRefused
from tests.support.entry_points import SRC_DIR

VENUE = "polymarket_us"
FAMILY = "pm_us_crh_fq_v1"
T0 = 1_791_100_800 * 10**9
SHA_A = "a" * 64
SHA_B = "b" * 64
INVOCATION = "00000000-0000-4000-8000-000000000001"
SCHEMAS_PATH: Final[Path] = SRC_DIR / "breezy" / "persistence" / "autonomy" / "schemas.py"
CHAIN_PATH: Final[Path] = SRC_DIR / "breezy" / "persistence" / "autonomy" / "chain.py"
AUTONOMY_PREFIX: Final = "breezy.persistence.autonomy."


def _row(**over: Any) -> TransitionRow:
    base: dict[str, Any] = {
        "venue": VENUE,
        "family_id": FAMILY,
        "family_prior_seq": 0,
        "from_state": None,
        "to_state": State.CHAMPION,
        "kind": Kind.BOOTSTRAP,
        "transition_id": SHA_A,
        "decided_by": DecidedBy.ENGINE,
        "invocation_id": INVOCATION,
        "engine_code_sha": SHA_B,
        "expected_prior_seq": 0,
        "ts_ns": T0,
        "lineage_root_family_id": FAMILY,
    }
    base.update(over)
    return TransitionRow(**base)


def _with_id(row: TransitionRow) -> TransitionRow:
    return replace(row, transition_id=row.computed_transition_id())


def _sealed_chain(n: int, venue: str = VENUE) -> list[TransitionRow]:
    """``n`` rows of one family linked from the venue genesis, ts increasing."""
    rows: list[TransitionRow] = []
    prev = genesis(venue)
    for i in range(1, n + 1):
        unsealed = _with_id(
            _row(venue=venue, family_prior_seq=i - 1, ts_ns=T0 + i, expected_prior_seq=i - 1)
        )
        sealed = replace(unsealed, seq=i, venue_seq=i, prev_transition_hash=prev)
        sealed = replace(sealed, transition_hash=transition_hash(sealed, prev))
        rows.append(sealed)
        prev = sealed.transition_hash or ""
    return rows


def _rehash(rows: list[TransitionRow], *, fix_ids: bool = True) -> list[TransitionRow]:
    """Recompute every link (and id) so only the deliberately broken property remains."""
    out: list[TransitionRow] = []
    prev = genesis(rows[0].venue)
    for row in rows:
        fixed = _with_id(row) if fix_ids else row
        fixed = replace(fixed, prev_transition_hash=prev, transition_hash=None)
        fixed = replace(fixed, transition_hash=transition_hash(fixed, prev))
        out.append(fixed)
        prev = fixed.transition_hash or ""
    return out


# --- genesis, canonical_row, transition_hash -------------------------------------------------


def test_genesis_is_sha256_of_registry_prefix_and_venue() -> None:
    expected = hashlib.sha256(b"registry/v1|polymarket_us").hexdigest()
    assert genesis(VENUE) == expected
    assert genesis("kalshi") != expected


def test_genesis_refuses_a_bad_venue() -> None:
    with pytest.raises(WireRefused):
        genesis("../x")


def test_canonical_row_hashes_venue_and_venue_seq() -> None:
    base = _sealed_chain(2)[1]
    reference = canonical_row(base)
    assert canonical_row(replace(base, venue="other_venue")) != reference
    assert canonical_row(replace(base, venue_seq=7)) != reference
    assert b'"venue":"polymarket_us"' in reference
    assert b'"venue_seq":2' in reference


def test_canonical_row_excludes_seq_and_both_hash_columns() -> None:
    base = _sealed_chain(2)[1]
    reference = canonical_row(base)
    assert canonical_row(replace(base, seq=99)) == reference
    assert canonical_row(replace(base, prev_transition_hash=SHA_A)) == reference
    assert canonical_row(replace(base, transition_hash=SHA_B)) == reference
    for key in (b'"seq"', b'"prev_transition_hash"', b'"transition_hash"'):
        assert key not in reference


def test_canonical_row_covers_every_other_column() -> None:
    """Changing any one remaining column changes the bytes (nothing is silently unhashed)."""
    base = replace(_sealed_chain(1)[0], policy_ruling_id="RULING_y", policy_ruling_sha256=SHA_B)
    reference = canonical_row(base)
    variants: dict[str, Any] = {
        "family_id": "other_family",
        "family_prior_seq": 5,
        "paired_transition_id": SHA_A,
        "from_state": State.SHADOW,
        "to_state": State.RETIRED,
        "kind": Kind.MINT,
        "cause_verdict_ids": (SHA_A,),
        "cause_code": CauseCode.VERDICT_FAIL,
        "halt_cause_class": CauseClass.TERMINAL,
        "trigger_cause_class": CauseClass.DRILL,
        "voids_transition_ids": (SHA_A,),
        "manifest_sha256": SHA_A,
        "artefact_sha256": SHA_A,
        "lineage_root_family_id": "other_root",
        "attest_valid_until_ns": 5,
        "k_life": 1,
        "alpha_k": Decimal("0.01"),
        "n_min_eff": 3,
        "n_cap": 4,
        "nomination_feasible": True,
        "hwm_from": 1,
        "hwm_to": 2,
        "carried_counters": '{"mints":[]}',
        "drill": True,
        "drill_clause_sha256": SHA_A,
        "policy_ruling_id": "RULING_x",
        "policy_ruling_sha256": SHA_A,
        "decided_by": DecidedBy.OPERATOR_CLI,
        "invocation_id": "00000000-0000-4000-8000-000000000002",
        "engine_code_sha": SHA_A,
        "expected_prior_seq": 9,
        "effective_launch_date": "2026-10-05",
        "ts_ns": T0 + 99,
        "transition_id": SHA_B,
    }
    for name, value in variants.items():
        assert canonical_row(replace(base, **{name: value})) != reference, name


def test_transition_hash_is_sha256_of_canonical_row_then_prev() -> None:
    row = _sealed_chain(1)[0]
    prev = genesis(VENUE)
    assert transition_hash(row, prev) == sha256_hex(canonical_row(row) + prev.encode("ascii"))
    assert transition_hash(row, SHA_A) != transition_hash(row, prev)


# --- transition_id (Y9) ----------------------------------------------------------------------


def test_transition_id_excludes_expected_prior_seq() -> None:
    a = _row(expected_prior_seq=0)
    b = _row(expected_prior_seq=41)
    assert a.computed_transition_id() == b.computed_transition_id()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("venue", "kalshi"),
        ("family_id", "other_family"),
        ("family_prior_seq", 3),
        ("from_state", State.SHADOW),
        ("to_state", State.RETIRED),
        ("kind", Kind.MINT),
        ("cause_verdict_ids", (SHA_A,)),
        ("paired_transition_id", SHA_A),
        ("policy_ruling_sha256", SHA_A),
    ],
)
def test_transition_id_includes_each_y9_field(field: str, value: Any) -> None:
    base = _row(policy_ruling_id="RULING_y", policy_ruling_sha256=SHA_B)
    assert replace(base, **{field: value}).computed_transition_id() != base.computed_transition_id()


def test_transition_id_sorts_cause_verdict_ids() -> None:
    forward = _row(cause_verdict_ids=(SHA_A, SHA_B))
    backward = _row(cause_verdict_ids=(SHA_B, SHA_A))
    assert forward.computed_transition_id() == backward.computed_transition_id()


def test_compute_transition_id_matches_row_method_and_is_hex() -> None:
    row = _row(
        cause_verdict_ids=(SHA_B, SHA_A), policy_ruling_id="RULING_x", policy_ruling_sha256=SHA_A
    )
    direct = compute_transition_id(
        venue=row.venue,
        family_id=row.family_id,
        family_prior_seq=row.family_prior_seq,
        from_state=row.from_state,
        to_state=row.to_state,
        kind=row.kind,
        cause_verdict_ids=row.cause_verdict_ids,
        paired_transition_id=row.paired_transition_id,
        policy_ruling_sha256=row.policy_ruling_sha256,
    )
    assert direct == row.computed_transition_id()
    assert re.fullmatch(r"[0-9a-f]{64}", direct)


# --- verify_venue_chain ----------------------------------------------------------------------


def test_verify_venue_chain_accepts_a_valid_chain() -> None:
    rows = _sealed_chain(3)
    verified = verify_venue_chain(rows, VENUE)
    assert isinstance(verified, VerifiedVenueChain)
    assert verified.venue == VENUE
    assert verified.rows == tuple(rows)
    assert verified.head_venue_seq == 3
    assert verified.head_hash == rows[-1].transition_hash


def test_verify_venue_chain_accepts_the_empty_chain_at_genesis() -> None:
    verified = verify_venue_chain([], VENUE)
    assert verified.rows == ()
    assert verified.head_venue_seq == 0
    assert verified.head_hash == genesis(VENUE)


def _gap(rows: list[TransitionRow]) -> list[TransitionRow]:
    return [rows[0], replace(rows[1], venue_seq=3), rows[2]]


def _starts_at_two(rows: list[TransitionRow]) -> list[TransitionRow]:
    return [replace(r, venue_seq=i + 2) for i, r in enumerate(rows)]


def _renumbered(rows: list[TransitionRow]) -> list[TransitionRow]:
    return [rows[0], replace(rows[1], venue_seq=1), rows[2]]


def _foreign_venue(rows: list[TransitionRow]) -> list[TransitionRow]:
    return [rows[0], replace(rows[1], venue="kalshi"), rows[2]]


def _decreasing_ts(rows: list[TransitionRow]) -> list[TransitionRow]:
    return [rows[0], replace(rows[1], ts_ns=rows[0].ts_ns - 1), rows[2]]


def _wrong_family_prior_seq(rows: list[TransitionRow]) -> list[TransitionRow]:
    return [rows[0], rows[1], replace(rows[2], family_prior_seq=0)]


def _family_prior_seq_skips_a_row(rows: list[TransitionRow]) -> list[TransitionRow]:
    return [rows[0], replace(rows[1], family_prior_seq=5), rows[2]]


@pytest.mark.parametrize(
    "corrupt",
    [
        _gap,
        _starts_at_two,
        _renumbered,
        _foreign_venue,
        _decreasing_ts,
        _wrong_family_prior_seq,
        _family_prior_seq_skips_a_row,
    ],
    ids=[
        "gap",
        "starts_at_two",
        "renumbered",
        "foreign_venue",
        "decreasing_ts",
        "wrong_family_prior_seq",
        "family_prior_seq_skips_a_row",
    ],
)
def test_verify_venue_chain_requires_contiguous_seq_single_venue_monotone_ts(
    corrupt: Any,
) -> None:
    # Every link is recomputed after the corruption, so the hash check cannot be what refuses it.
    broken = _rehash(corrupt(_sealed_chain(3)))
    with pytest.raises(ChainBroken) as caught:
        verify_venue_chain(broken, VENUE)
    assert caught.value.reason is RefusalReason.CHAIN_BROKEN


def test_chain_tracks_family_prior_seq_per_family() -> None:
    """A second family's first row names 0, not the venue's previous row (ARCH l.417)."""
    first = _with_id(_row(ts_ns=T0 + 1))
    other = _with_id(
        _row(family_id="pm_us_crh_v4", family_prior_seq=0, ts_ns=T0 + 2, expected_prior_seq=1)
    )
    again = _with_id(_row(family_prior_seq=1, ts_ns=T0 + 3, expected_prior_seq=2))
    rows = _rehash([first, other, again])
    rows = [replace(r, seq=i + 1, venue_seq=i + 1) for i, r in enumerate(rows)]
    rows = _rehash(rows)
    assert verify_venue_chain(rows, VENUE).head_venue_seq == 3
    wrong = _rehash([first, other, replace(again, family_prior_seq=2)])
    wrong = _rehash([replace(r, seq=i + 1, venue_seq=i + 1) for i, r in enumerate(wrong)])
    with pytest.raises(ChainBroken) as caught:
        verify_venue_chain(wrong, VENUE)
    assert caught.value.venue_seq == 3


def test_verify_venue_chain_refuses_a_stored_transition_id_that_is_not_the_computed_one() -> None:
    rows = _sealed_chain(3)
    rows[1] = replace(rows[1], transition_id=SHA_A)
    rows = _rehash(rows, fix_ids=False)  # links and hashes are consistent; only the id lies
    with pytest.raises(ChainBroken) as caught:
        verify_venue_chain(rows, VENUE)
    assert caught.value.venue_seq == 2


def test_verify_venue_chain_allows_equal_timestamps() -> None:
    rows = _sealed_chain(3)
    same = _rehash([rows[0], replace(rows[1], ts_ns=rows[0].ts_ns), rows[2]])
    assert verify_venue_chain(same, VENUE).head_venue_seq == 3


def test_verify_venue_chain_refuses_an_edited_field() -> None:
    rows = _sealed_chain(3)
    rows[1] = replace(rows[1], family_prior_seq=17)  # hash left stale
    with pytest.raises(ChainBroken):
        verify_venue_chain(rows, VENUE)


def test_verify_venue_chain_refuses_a_broken_prev_link() -> None:
    rows = _sealed_chain(3)
    forged = replace(rows[1], prev_transition_hash=SHA_A)
    rows[1] = replace(forged, transition_hash=transition_hash(forged, SHA_A))
    with pytest.raises(ChainBroken):
        verify_venue_chain(rows, VENUE)


def test_verify_venue_chain_refuses_first_row_not_linked_to_genesis() -> None:
    rows = _sealed_chain(2)
    forged = replace(rows[0], prev_transition_hash=SHA_A)
    rows[0] = replace(forged, transition_hash=transition_hash(forged, SHA_A))
    with pytest.raises(ChainBroken):
        verify_venue_chain(rows, VENUE)


def test_verify_venue_chain_refuses_an_unsealed_row() -> None:
    rows = _sealed_chain(2)
    rows[1] = replace(
        rows[1], seq=None, venue_seq=None, prev_transition_hash=None, transition_hash=None
    )
    with pytest.raises(ChainBroken):
        verify_venue_chain(rows, VENUE)


def test_verify_venue_chain_refuses_a_venue_argument_that_disagrees() -> None:
    with pytest.raises(ChainBroken):
        verify_venue_chain(_sealed_chain(2), "kalshi")


def test_verify_venue_chain_refuses_a_non_row_member() -> None:
    with pytest.raises(ChainBroken):
        verify_venue_chain([_sealed_chain(1)[0], object()], VENUE)  # type: ignore[list-item]


def test_chain_broken_names_the_failing_venue_seq() -> None:
    rows = _sealed_chain(3)
    rows[2] = replace(rows[2], family_prior_seq=17)
    with pytest.raises(ChainBroken) as caught:
        verify_venue_chain(rows, VENUE)
    assert caught.value.venue_seq == 3


# --- verify_extension, seq_is_verified_prefix, verify_against_export --------------------------


def test_verify_extension_appends_to_a_verified_chain() -> None:
    rows = _sealed_chain(4)
    base = verify_venue_chain(rows[:2], VENUE)
    extended = verify_extension(base, rows[2:])
    assert extended.rows == tuple(rows)
    assert extended.head_hash == rows[-1].transition_hash


def test_verify_extension_refuses_a_row_that_does_not_link() -> None:
    rows = _sealed_chain(4)
    base = verify_venue_chain(rows[:2], VENUE)
    with pytest.raises(ChainBroken):
        verify_extension(base, rows[3:])  # skips venue_seq 3


def test_verify_extension_with_no_rows_is_the_same_chain() -> None:
    base = verify_venue_chain(_sealed_chain(2), VENUE)
    assert verify_extension(base, []) == base


def test_seq_is_verified_prefix() -> None:
    rows = _sealed_chain(3)
    chain = verify_venue_chain(rows, VENUE)
    assert seq_is_verified_prefix(chain, 2, rows[1].transition_hash or "") is True
    assert seq_is_verified_prefix(chain, 3, rows[2].transition_hash or "") is True
    assert seq_is_verified_prefix(chain, 2, rows[2].transition_hash or "") is False
    assert seq_is_verified_prefix(chain, 4, rows[2].transition_hash or "") is False
    assert seq_is_verified_prefix(chain, 0, genesis(VENUE)) is True
    assert seq_is_verified_prefix(chain, 0, SHA_A) is False
    assert seq_is_verified_prefix(chain, -1, genesis(VENUE)) is False


def _trailer(chain: VerifiedVenueChain, upto: int, *, venue: str = VENUE) -> ExportTrailer:
    head = genesis(venue) if upto == 0 else chain.rows[upto - 1].transition_hash
    return ExportTrailer(
        venue=venue, venue_seq=upto, chain_head=head or "", export_seq=1, evidence_journal_heads=()
    )


def test_verify_against_export_accepts_a_prefix_and_the_whole_chain() -> None:
    chain = verify_venue_chain(_sealed_chain(3), VENUE)
    for upto in (0, 1, 2, 3):
        assert verify_against_export(chain, _trailer(chain, upto)) is None


def test_verify_against_export_refuses_a_disagreeing_prefix() -> None:
    chain = verify_venue_chain(_sealed_chain(3), VENUE)
    forged = replace(_trailer(chain, 2), chain_head=SHA_A)
    assert verify_against_export(chain, forged) is RefusalReason.EXPORT_PREFIX_MISMATCH


def test_verify_against_export_refuses_a_chain_shorter_than_the_export() -> None:
    full = verify_venue_chain(_sealed_chain(3), VENUE)
    short = verify_venue_chain(list(full.rows[:2]), VENUE)
    assert verify_against_export(short, _trailer(full, 3)) is RefusalReason.EXPORT_PREFIX_MISMATCH


def test_verify_against_export_refuses_a_foreign_venue_trailer() -> None:
    chain = verify_venue_chain(_sealed_chain(2), VENUE)
    foreign = _trailer(chain, 1, venue="kalshi")
    assert verify_against_export(chain, foreign) is RefusalReason.EXPORT_PREFIX_MISMATCH


# --- TransitionRow wire and domain ------------------------------------------------------------


def test_transition_row_wire_roundtrip_keeps_every_column() -> None:
    row = _row(
        seq=4,
        venue_seq=4,
        prev_transition_hash=SHA_A,
        transition_hash=SHA_B,
        kind=Kind.PROMOTE,
        from_state=State.SHADOW,
        to_state=State.CHALLENGER,
        cause_verdict_ids=(SHA_A, SHA_B),
        k_life=1,
        alpha_k=Decimal("0.0125"),
        n_min_eff=500,
        n_cap=900,
        nomination_feasible=True,
        carried_counters='{"mints":[1,2]}',
        effective_launch_date="2026-10-05",
    )
    wire = row.to_wire()
    assert wire["alpha_k"] == "0.0125"
    assert wire["kind"] == "PROMOTE"
    assert wire["carried_counters"] == {"mints": [1, 2]}
    assert TransitionRow.from_wire(wire) == row
    assert TransitionRow.from_wire(wire).to_wire() == wire


def test_transition_row_wire_has_the_exact_c5_column_set() -> None:
    assert set(_row().to_wire()) == {
        "seq", "venue", "venue_seq", "transition_id", "family_id", "family_prior_seq",
        "paired_transition_id", "from_state", "to_state", "kind", "cause_verdict_ids",
        "cause_code", "halt_cause_class", "trigger_cause_class", "voids_transition_ids",
        "manifest_sha256", "artefact_sha256", "lineage_root_family_id", "attest_valid_until_ns",
        "k_life", "alpha_k", "n_min_eff", "n_cap", "nomination_feasible", "hwm_from", "hwm_to",
        "carried_counters", "drill", "drill_clause_sha256", "policy_ruling_id",
        "policy_ruling_sha256", "decided_by", "invocation_id", "engine_code_sha",
        "expected_prior_seq", "effective_launch_date", "ts_ns", "prev_transition_hash",
        "transition_hash",
    }  # fmt: skip


def test_transition_row_from_wire_refuses_missing_and_unknown_keys() -> None:
    wire = _row().to_wire()
    short = {k: v for k, v in wire.items() if k != "kind"}
    with pytest.raises(WireRefused) as missing:
        TransitionRow.from_wire(short)
    assert missing.value.reason is WireRefusalReason.MISSING_KEY
    with pytest.raises(WireRefused) as unknown:
        TransitionRow.from_wire({**wire, "extra": 1})
    assert unknown.value.reason is WireRefusalReason.UNKNOWN_KEY


def test_transition_row_from_wire_refuses_a_non_canonical_decimal() -> None:
    wire = _row(alpha_k=Decimal("0.5")).to_wire()
    wire["alpha_k"] = "0.50"
    with pytest.raises(WireRefused) as caught:
        TransitionRow.from_wire(wire)
    assert caught.value.reason is WireRefusalReason.BAD_VALUE


def test_transition_row_refuses_a_float_quantity() -> None:
    with pytest.raises(WireRefused) as caught:
        _row(alpha_k=0.5)
    assert caught.value.reason is WireRefusalReason.WRONG_TYPE


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("venue", "Bad Venue", WireRefusalReason.BAD_VALUE),
        ("family_id", "../x", WireRefusalReason.BAD_VALUE),
        ("transition_id", "xyz", WireRefusalReason.BAD_VALUE),
        ("family_prior_seq", True, WireRefusalReason.BOOL_AS_INT),
        ("family_prior_seq", -1, WireRefusalReason.BAD_VALUE),
        ("ts_ns", -1, WireRefusalReason.BAD_VALUE),
        ("expected_prior_seq", "0", WireRefusalReason.WRONG_TYPE),
        ("drill", 1, WireRefusalReason.WRONG_TYPE),
        ("nomination_feasible", 1, WireRefusalReason.WRONG_TYPE),
        ("kind", "PROMOTE", WireRefusalReason.WRONG_TYPE),
        ("to_state", "CHAMPION", WireRefusalReason.WRONG_TYPE),
        ("cause_verdict_ids", [SHA_A], WireRefusalReason.WRONG_TYPE),
        ("cause_verdict_ids", ("nope",), WireRefusalReason.BAD_VALUE),
        ("invocation_id", "not-a-uuid", WireRefusalReason.BAD_VALUE),
        ("engine_code_sha", "", WireRefusalReason.BAD_VALUE),
        ("policy_ruling_sha256", "abc", WireRefusalReason.BAD_VALUE),
        ("effective_launch_date", "2026-13-40", WireRefusalReason.BAD_VALUE),
        ("effective_launch_date", "2026-1-5", WireRefusalReason.BAD_VALUE),
        ("cause_verdict_ids", (SHA_A, SHA_A), WireRefusalReason.BAD_VALUE),
        ("voids_transition_ids", (SHA_B, SHA_B), WireRefusalReason.BAD_VALUE),
        ("policy_ruling_id", "RULING_x", WireRefusalReason.BAD_VALUE),
        ("policy_ruling_sha256", SHA_A, WireRefusalReason.BAD_VALUE),
        ("carried_counters", "{not json", WireRefusalReason.MALFORMED_JSON),
        ("carried_counters", '{"a": 1}', WireRefusalReason.BAD_VALUE),  # not canonical bytes
        ("carried_counters", '{"a":1.5}', WireRefusalReason.FLOAT_TOKEN),
    ],
)
def test_transition_row_construction_refuses_bad_domain(
    field: str, value: Any, reason: WireRefusalReason
) -> None:
    with pytest.raises(WireRefused) as caught:
        _row(**{field: value})
    assert caught.value.reason is reason


@pytest.mark.parametrize("name", ["family_prior_seq", "expected_prior_seq"])
def test_prior_seq_columns_are_required_with_no_default(name: str) -> None:
    base: dict[str, Any] = {
        "venue": VENUE,
        "family_id": FAMILY,
        "to_state": State.CHAMPION,
        "kind": Kind.BOOTSTRAP,
        "transition_id": SHA_A,
        "decided_by": DecidedBy.ENGINE,
        "invocation_id": INVOCATION,
        "engine_code_sha": SHA_B,
        "ts_ns": T0,
        "family_prior_seq": 0,
        "expected_prior_seq": 0,
    }
    TransitionRow(**base)
    del base[name]
    with pytest.raises(TypeError):
        TransitionRow(**base)


def test_policy_ruling_pair_is_both_empty_or_both_set() -> None:
    assert _row().policy_ruling_id == ""  # the C5 fallback pair
    assert (
        _row(policy_ruling_id="RULING_x", policy_ruling_sha256=SHA_A).policy_ruling_sha256 == SHA_A
    )


def test_transition_row_is_frozen_and_slotted() -> None:
    row = _row()
    with pytest.raises(FrozenInstanceError):
        row.venue = "x"  # type: ignore[misc]
    assert not hasattr(row, "__dict__")


# --- closed enums ----------------------------------------------------------------------------


def _values(enum_cls: Any) -> set[str]:
    return {m.value for m in enum_cls}


def test_state_and_kind_sets_are_exactly_arch() -> None:
    assert _values(State) == {"SHADOW", "CHALLENGER", "CHAMPION", "HALTED", "RETIRED"}
    assert _values(Kind) == {
        "BOOTSTRAP", "MINT", "PROMOTE", "DRILL_ADMIT", "DRILL_PROMOTE", "ROLLBACK", "ROOT_ADMIT",
        "SUPERSEDE", "DISPLACED", "ACTIVATE", "SWAP_CANCEL", "TARGET_INELIGIBLE", "ATTEST",
        "DEMOTE", "HALT", "RESUME", "RETIRE", "HWM_RESET",
    }  # fmt: skip


def test_cause_class_writer_mode_and_decided_by_sets_are_exactly_arch() -> None:
    assert _values(CauseClass) == {
        "RECOVERABLE_MODEL", "RECOVERABLE_INFRA", "DRILL", "TERMINAL", "INTEGRITY",
        "ROLLBACK_FAILED",
    }  # fmt: skip
    assert _values(WriterMode) == {"DAILY", "INTRADAY", "PRELAUNCH", "BOOTSTRAP", "OPERATOR_CLI"}
    assert _values(DecidedBy) == {"engine", "operator_cli"}


def test_cause_code_equals_the_pins_literal() -> None:
    assert _values(CauseCode) == set(pins.CAUSE_CODES)


def test_refusal_reason_set_is_exactly_the_plan() -> None:
    assert _values(RefusalReason) == {
        "registry_unreadable", "empty_chain", "chain_broken", "clock_invalid", "clock_before_head",
        "hwm_unreadable", "hwm_absent", "hwm_regressed", "export_unreadable",
        "export_prefix_mismatch", "widening_kind_not_enabled", "admission_pending",
        "replay_invalid", "replay_cause_unresolved", "replay_artefact_mismatch",
        "engine_inconsistency", "no_sender", "paths_role_mismatch", "stage_not_canonical",
        "family_not_introduced", "root_lineage_mismatch", "engine_code_unpinned",
        "engine_code_revoked", "manifest_unreadable", "manifest_invalid", "manifest_draft",
        "manifest_unpinned", "prereg_ineligible", "manifest_sha_mismatch",
        "manifest_identity_mismatch", "kind_not_live_gate_routed", "artefact_unreadable",
        "artefact_sha_mismatch", "root_record_mismatch", "child_root_mismatch",
        "child_not_equal_root", "root_not_lineage_allowlisted", "ruling_not_policy",
        "ruling_refused", "no_live_orders_ruling", "d0_breach", "trial_prefix_mismatch",
    }  # fmt: skip


def test_unreadable_reason_set_is_exactly_the_reader_table() -> None:
    assert _values(UnreadableReason) == {
        "busy",
        "hot_journal",
        "schema_mismatch",
        "io",
        "sqlite_error",
    }


def test_fold_invalid_reason_set() -> None:
    assert _values(FoldInvalidReason) == {
        "family_introduced_by_other_kind",
        "root_lineage_mismatch",
    }


def test_live_orders_refusal_mirrors_live_orders_reason() -> None:
    mirrored = set(typing.get_args(live_orders_gate.LiveOrdersReason))
    assert len(mirrored) == 7
    assert _values(LiveOrdersRefusal) == mirrored


def test_local_patterns_equal_paths_patterns() -> None:
    for name in ("VENUE_RE", "FAMILY_RE", "JOURNAL_KIND_RE"):
        local, original = getattr(schemas_mod, name), getattr(paths, name)
        assert (local.pattern, local.flags) == (original.pattern, original.flags), name


# --- ExportTrailer ---------------------------------------------------------------------------


def _trailer_wire() -> dict[str, object]:
    return {
        "schema": "registry_export/v1",
        "venue": VENUE,
        "venue_seq": 3,
        "chain_head": SHA_A,
        "export_seq": 2,
        "evidence_journal_heads": {"probe": {"seq": 4, "sha256": SHA_B}},
    }


def test_export_trailer_roundtrips() -> None:
    trailer = ExportTrailer.from_wire(_trailer_wire())
    assert trailer.evidence_journal_heads == (("probe", JournalHead(seq=4, sha256=SHA_B)),)
    assert trailer.to_wire() == _trailer_wire()


def test_export_trailer_to_wire_sorts_journal_kinds() -> None:
    trailer = ExportTrailer(
        venue=VENUE,
        venue_seq=1,
        chain_head=SHA_A,
        export_seq=0,
        evidence_journal_heads=(("zz", JournalHead(1, SHA_A)), ("aa", JournalHead(2, SHA_B))),
    )
    assert list(typing.cast(dict[str, object], trailer.to_wire()["evidence_journal_heads"])) == [
        "aa",
        "zz",
    ]


@pytest.mark.parametrize(
    ("key", "value", "reason"),
    [
        ("schema", "registry/v1", WireRefusalReason.UNKNOWN_SCHEMA),
        ("venue", "Bad", WireRefusalReason.BAD_VALUE),
        ("venue_seq", True, WireRefusalReason.BOOL_AS_INT),
        ("venue_seq", -1, WireRefusalReason.BAD_VALUE),
        ("chain_head", "xyz", WireRefusalReason.BAD_VALUE),
        ("export_seq", -1, WireRefusalReason.BAD_VALUE),
        ("evidence_journal_heads", [], WireRefusalReason.WRONG_TYPE),
        (
            "evidence_journal_heads",
            {"../x": {"seq": 1, "sha256": SHA_A}},
            WireRefusalReason.BAD_VALUE,
        ),
        (
            "evidence_journal_heads",
            {"probe": {"seq": 0, "sha256": SHA_A}},
            WireRefusalReason.BAD_VALUE,
        ),
        (
            "evidence_journal_heads",
            {"probe": {"seq": 1, "sha256": "x"}},
            WireRefusalReason.BAD_VALUE,
        ),
        ("evidence_journal_heads", {"probe": {"seq": 1}}, WireRefusalReason.MISSING_KEY),
    ],
)
def test_export_trailer_from_wire_refuses_bad_values(
    key: str, value: object, reason: WireRefusalReason
) -> None:
    wire = _trailer_wire()
    wire[key] = value
    with pytest.raises(WireRefused) as caught:
        ExportTrailer.from_wire(wire)
    assert caught.value.reason is reason


@pytest.mark.parametrize(
    "heads",
    [
        (("probe",),),
        (5,),
        ("ab",),
        (("probe", "x"),),
        (("probe", JournalHead(1, SHA_A), "extra"),),
        "ab",
        [("probe", JournalHead(1, SHA_A))],
        None,
    ],
    ids=[
        "short_pair",
        "int",
        "two_char_str",
        "head_not_a_head",
        "long_pair",
        "str",
        "list",
        "none",
    ],
)
def test_export_trailer_refuses_a_malformed_journal_heads_value(heads: Any) -> None:
    with pytest.raises(WireRefused):
        ExportTrailer(
            venue=VENUE, venue_seq=1, chain_head=SHA_A, export_seq=0, evidence_journal_heads=heads
        )


def test_export_trailer_refuses_duplicate_journal_kinds() -> None:
    pair = ("probe", JournalHead(1, SHA_A))
    with pytest.raises(WireRefused):
        ExportTrailer(
            venue=VENUE,
            venue_seq=1,
            chain_head=SHA_A,
            export_seq=0,
            evidence_journal_heads=(pair, pair),
        )


def test_export_trailer_from_wire_refuses_unknown_and_missing_keys() -> None:
    with pytest.raises(WireRefused) as unknown:
        ExportTrailer.from_wire({**_trailer_wire(), "extra": 1})
    assert unknown.value.reason is WireRefusalReason.UNKNOWN_KEY
    short = {k: v for k, v in _trailer_wire().items() if k != "export_seq"}
    with pytest.raises(WireRefused) as missing:
        ExportTrailer.from_wire(short)
    assert missing.value.reason is WireRefusalReason.MISSING_KEY


# --- StagePolicy, StageView, ManifestFacts, AdmissibilityResult --------------------------------


def test_stage_policy_is_frozen_slotted_and_closed_over_kind() -> None:
    policy = StagePolicy(
        enabled_widening_kinds=frozenset({Kind.RESUME}), admission_implemented=frozenset()
    )
    assert policy.enabled_widening_kinds == frozenset({Kind.RESUME})
    with pytest.raises(FrozenInstanceError):
        policy.enabled_widening_kinds = frozenset()  # type: ignore[misc]
    assert not hasattr(policy, "__dict__")
    with pytest.raises(WireRefused):
        StagePolicy(enabled_widening_kinds=frozenset({"RESUME"}), admission_implemented=frozenset())  # type: ignore[arg-type]
    with pytest.raises(WireRefused):
        StagePolicy(enabled_widening_kinds=frozenset(), admission_implemented=[Kind.RESUME])  # type: ignore[arg-type]


def test_stage_policy_satisfies_the_stage_view_protocol() -> None:
    view: schemas_mod.StageView = StagePolicy(
        enabled_widening_kinds=frozenset(), admission_implemented=frozenset()
    )
    assert view.enabled_widening_kinds == frozenset()
    assert view.admission_implemented == frozenset()


def test_manifest_facts_validates_and_is_frozen() -> None:
    facts = ManifestFacts(
        family_id=FAMILY,
        manifest_sha256=SHA_A,
        d0_climate_day="2026-10-05",
        trial_id_prefix="current_rung_hold/trial/x/",
        composition_kind="current_rung_hold",
    )
    with pytest.raises(FrozenInstanceError):
        facts.family_id = "x"  # type: ignore[misc]
    with pytest.raises(WireRefused):
        ManifestFacts(
            family_id=FAMILY,
            manifest_sha256="short",
            d0_climate_day="2026-10-05",
            trial_id_prefix="p/",
            composition_kind="current_rung_hold",
        )
    with pytest.raises(WireRefused):
        ManifestFacts(
            family_id=FAMILY,
            manifest_sha256=SHA_A,
            d0_climate_day="20261005",
            trial_id_prefix="p/",
            composition_kind="current_rung_hold",
        )


def test_admissibility_result_domain() -> None:
    assert AdmissibilityResult(admitted=3, reason=None).reason is None
    refused = AdmissibilityResult(admitted=1, reason=RefusalReason.ADMISSION_PENDING)
    assert refused.admitted == 1
    AdmissibilityResult(admitted=0, reason=RefusalReason.WIDENING_KIND_NOT_ENABLED)
    with pytest.raises(WireRefused):
        AdmissibilityResult(admitted=-1, reason=None)
    with pytest.raises(WireRefused):
        AdmissibilityResult(admitted=True, reason=None)
    with pytest.raises(WireRefused):
        AdmissibilityResult(admitted=0, reason=RefusalReason.CHAIN_BROKEN)


# --- the pyarrow-free promise ------------------------------------------------------------------

#: Types owned by pyarrow-reaching modules (A4-R1); ``schemas`` must never name them.
PYARROW_REACHING_TYPE_NAMES: Final = frozenset(
    {
        "FamilyBytes",
        "ByteBindingFailure",
        "RootCopyResult",
        "RootCopyIntegrity",
        "ResolvedFamily",
        "ShadowResolution",
        "ResolverRefusal",
        "RegistryStore",
        "RegistryReader",
        "RegistryUnreadable",
    }
)
SCHEMAS_ALLOWED_IMPORTS: Final = frozenset(
    AUTONOMY_PREFIX + name for name in ("wire", "canonical", "rollback_journal")
)
CHAIN_ALLOWED_IMPORTS: Final = frozenset(
    AUTONOMY_PREFIX + name for name in ("canonical", "schemas")
)


def _breezy_imports(source: str) -> set[str]:
    """Every ``breezy`` module a source imports, nested and ``TYPE_CHECKING`` imports included."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names if a.name.startswith("breezy")}
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                raise AssertionError("relative import")
            module = node.module or ""
            if module == "breezy.persistence.autonomy":
                found |= {f"{module}.{a.name}" for a in node.names}
            elif module.startswith("breezy"):
                found.add(module)
    return found


def _named_types(source: str, names: frozenset[str]) -> set[str]:
    """Names from ``names`` used as identifiers, attributes, aliases or string annotations."""
    hit: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name) and node.id in names:
            hit.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in names:
            hit.add(node.attr)
        elif isinstance(node, ast.alias) and node.name.split(".")[-1] in names:
            hit.add(node.name.split(".")[-1])
        elif isinstance(node, ast.arg | ast.AnnAssign | ast.FunctionDef):
            annotations = [
                getattr(node, "annotation", None),
                getattr(node, "returns", None),
            ]
            for ann in annotations:
                if ann is None:
                    continue
                for sub in ast.walk(ann):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        hit |= {n for n in names if re.search(rf"\b{n}\b", sub.value)}
    return hit


def test_schemas_holds_no_pyarrow_reaching_type() -> None:
    source = SCHEMAS_PATH.read_text(encoding="utf-8")
    assert _breezy_imports(source) <= SCHEMAS_ALLOWED_IMPORTS
    assert _named_types(source, PYARROW_REACHING_TYPE_NAMES) == set()
    for name in PYARROW_REACHING_TYPE_NAMES:
        assert not hasattr(schemas_mod, name), name


def test_schemas_import_scan_catches_planted_type_checking_import() -> None:
    planted = (
        SCHEMAS_PATH.read_text(encoding="utf-8")
        + "\nfrom typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n"
        + "    from breezy.persistence.autonomy.family_bytes import FamilyBytes\n"
    )
    assert _breezy_imports(planted) - SCHEMAS_ALLOWED_IMPORTS == {
        "breezy.persistence.autonomy.family_bytes"
    }
    assert _named_types(planted, PYARROW_REACHING_TYPE_NAMES) == {"FamilyBytes"}


def test_schemas_type_scan_catches_a_planted_string_annotation() -> None:
    planted = "def f(x: 'ResolvedFamily | None') -> 'FamilyBytes':\n    return x\n"
    assert _named_types(planted, PYARROW_REACHING_TYPE_NAMES) == {"ResolvedFamily", "FamilyBytes"}


def test_chain_imports_only_canonical_and_schemas() -> None:
    source = CHAIN_PATH.read_text(encoding="utf-8")
    assert _breezy_imports(source) <= CHAIN_ALLOWED_IMPORTS
    assert _breezy_imports(source) >= {AUTONOMY_PREFIX + "canonical", AUTONOMY_PREFIX + "schemas"}


def test_chain_import_scan_catches_a_planted_extra_import() -> None:
    planted = CHAIN_PATH.read_text(encoding="utf-8") + "\nimport breezy.persistence.autonomy.pins\n"
    assert _breezy_imports(planted) - CHAIN_ALLOWED_IMPORTS == {AUTONOMY_PREFIX + "pins"}


def test_chain_exports_the_planned_surface() -> None:
    for name in (
        "genesis",
        "transition_hash",
        "canonical_row",
        "VerifiedVenueChain",
        "verify_venue_chain",
        "verify_extension",
        "seq_is_verified_prefix",
        "verify_against_export",
    ):
        assert hasattr(chain_mod, name), name


#: Hex digests derived outside the code under test (plain ``json`` and ``hashlib`` over a
#: hand-written dict), so a silent change to the encoding fails here.
GOLDEN_GENESIS = "a32f391f69df2eb0835a5ea79b0bfb22bb3930a5a228cc6c18b7adbc17b86f27"
GOLDEN_CANONICAL_ROW_SHA256 = "6ecb8cd363662d68f5dbbd9660191fa29372819d4445122c9e57ac71a503829f"
GOLDEN_TRANSITION_ID = "c6d5306f8e0dd3c1571ef7b882626982fc08f7705283d116e2fbfce200577dd9"


def test_genesis_golden() -> None:
    assert genesis(VENUE) == GOLDEN_GENESIS


def test_canonical_row_golden_digest() -> None:
    row = replace(_row(), seq=1, venue_seq=1, prev_transition_hash=genesis(VENUE))
    assert sha256_hex(canonical_row(row)) == GOLDEN_CANONICAL_ROW_SHA256


def test_compute_transition_id_golden() -> None:
    assert (
        compute_transition_id(
            venue=VENUE,
            family_id=FAMILY,
            family_prior_seq=0,
            from_state=None,
            to_state=State.CHAMPION,
            kind=Kind.BOOTSTRAP,
            cause_verdict_ids=(SHA_B, SHA_A),
            paired_transition_id=None,
            policy_ruling_sha256="",
        )
        == GOLDEN_TRANSITION_ID
    )


def _id_args(**over: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "venue": VENUE,
        "family_id": FAMILY,
        "family_prior_seq": 0,
        "from_state": None,
        "to_state": State.CHAMPION,
        "kind": Kind.BOOTSTRAP,
        "cause_verdict_ids": (),
        "paired_transition_id": None,
        "policy_ruling_sha256": "",
    }
    args.update(over)
    return args


@pytest.mark.parametrize(
    "over",
    [
        {"venue": "Bad Venue"},
        {"family_id": "../x"},
        {"family_prior_seq": True},
        {"family_prior_seq": -1},
        {"from_state": "SHADOW"},
        {"to_state": "CHAMPION"},
        {"kind": "MINT"},
        {"cause_verdict_ids": "abc"},
        {"cause_verdict_ids": ("nope",)},
        {"cause_verdict_ids": (SHA_A, SHA_A)},
        {"paired_transition_id": "x"},
        {"policy_ruling_sha256": "abc"},
    ],
)
def test_compute_transition_id_validates_its_inputs(over: dict[str, Any]) -> None:
    with pytest.raises(WireRefused):
        compute_transition_id(**_id_args(**over))
