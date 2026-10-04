"""ARCH-0 seam 7e: ``hwm`` (the registry high-water mark; AC 16, A5-R2 monotone write decision).

The exec-store HWM is tri-state (Absent, Present, Unreadable), checked against the verified chain
at the HWM's own ``venue_seq`` (not only the head), absence-refusing, and monotone on write.
``hwm`` holds the pure parts; the store binding (``write_monotone``) belongs to AUT-5a.
"""

from __future__ import annotations

import ast
import itertools
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any, Final

import pytest

from breezy.persistence.autonomy import hwm as hwm_mod
from breezy.persistence.autonomy.canonical import canonical_json
from breezy.persistence.autonomy.chain import (
    VerifiedVenueChain,
    genesis,
    transition_hash,
    verify_venue_chain,
)
from breezy.persistence.autonomy.hwm import (
    REGISTRY_HWM_KEY_PREFIX,
    Hwm,
    HwmAbsent,
    HwmPresent,
    HwmUnreadable,
    HwmWriteDecision,
    hwm_check,
    hwm_key,
    hwm_reading_from_bytes,
    next_hwm,
    write_monotone_decision,
)
from breezy.persistence.autonomy.schemas import (
    DecidedBy,
    Kind,
    RefusalReason,
    State,
    TransitionRow,
)
from breezy.persistence.autonomy.wire import WireRefusalReason, WireRefused
from breezy.runtime.trade_supervisor_core import CONTINUOUS_FAMILY_HALT_KEY_PREFIX
from breezy.strategy.current_rung_hold import trial_day_latch
from tests.support.entry_points import SRC_DIR

VENUE = "polymarket_us"
OTHER_VENUE = "kalshi"
FAMILY = "pm_us_crh_fq_v1"
T0 = 1_791_100_800 * 10**9
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
INVOCATION = "00000000-0000-4000-8000-000000000001"
HWM_PATH: Final[Path] = SRC_DIR / "breezy" / "persistence" / "autonomy" / "hwm.py"


def _chain(n: int, venue: str = VENUE) -> VerifiedVenueChain:
    """``n`` sealed rows of one family linked from the venue genesis."""
    rows: list[TransitionRow] = []
    prev = genesis(venue)
    for i in range(1, n + 1):
        unsealed = TransitionRow(
            venue=venue,
            family_id=FAMILY,
            family_prior_seq=i - 1,
            from_state=None,
            to_state=State.CHAMPION,
            kind=Kind.BOOTSTRAP,
            transition_id=SHA_A,
            decided_by=DecidedBy.ENGINE,
            invocation_id=INVOCATION,
            engine_code_sha=SHA_B,
            expected_prior_seq=i - 1,
            ts_ns=T0 + i,
            lineage_root_family_id=FAMILY,
        )
        unsealed = replace(unsealed, transition_id=unsealed.computed_transition_id())
        sealed = replace(unsealed, seq=i, venue_seq=i, prev_transition_hash=prev)
        sealed = replace(sealed, transition_hash=transition_hash(sealed, prev))
        rows.append(sealed)
        prev = sealed.transition_hash or ""
    return verify_venue_chain(rows, venue)


def _hwm_at(chain: VerifiedVenueChain, venue_seq: int, export_seq: int = 0) -> Hwm:
    return Hwm(
        venue=chain.venue,
        venue_seq=venue_seq,
        chain_head=chain.rows[venue_seq - 1].transition_hash or "",
        export_seq=export_seq,
    )


def _present(hwm: Hwm) -> HwmPresent:
    reading = hwm_reading_from_bytes(hwm.to_bytes())
    assert isinstance(reading, HwmPresent)
    return reading


def _raw_hwm(**over: Any) -> Hwm:
    """An ``Hwm`` built around the constructor's domain checks (to drive ``hwm_check`` rule 3)."""
    base: dict[str, Any] = {"venue": VENUE, "venue_seq": 1, "chain_head": SHA_A, "export_seq": 0}
    base.update(over)
    hwm = object.__new__(Hwm)
    for name, value in base.items():
        object.__setattr__(hwm, name, value)
    return hwm


# ---------------------------------------------------------------------------------------------
# Record, key and decoder
# ---------------------------------------------------------------------------------------------


def test_hwm_key_is_prefix_plus_venue() -> None:
    assert REGISTRY_HWM_KEY_PREFIX == "autonomy/registry_hwm/"
    assert hwm_key(VENUE) == "autonomy/registry_hwm/polymarket_us"
    for bad in ("", "Bad", "a/b", "a" * 33, None, 3):
        with pytest.raises(WireRefused):
            hwm_key(bad)  # type: ignore[arg-type]


def test_autonomy_exec_keys_disjoint_from_halt_prefixes() -> None:
    halt_prefixes = (
        CONTINUOUS_FAMILY_HALT_KEY_PREFIX,
        trial_day_latch.FAMILY_HALT_KEY_PREFIX,
        trial_day_latch.FAMILY_HALT_CLEARED_KEY_PREFIX,
        trial_day_latch.HALT_CLEARED_KEY_PREFIX,
        trial_day_latch.LEGACY_FAMILY_HALT_KEY,
    )
    assert REGISTRY_HWM_KEY_PREFIX.startswith("autonomy/")
    for prefix in halt_prefixes:
        assert not prefix.startswith("autonomy/")
        assert not hwm_key(VENUE).startswith(prefix)
        assert not prefix.startswith(REGISTRY_HWM_KEY_PREFIX)


@pytest.mark.parametrize(
    "bad",
    [
        {"venue_seq": 0},
        {"venue_seq": -1},
        {"export_seq": -1},
        {"venue_seq": True},
        {"export_seq": False},
        {"venue_seq": "1"},
        {"venue": "Bad Venue"},
        {"chain_head": "A" * 64},
        {"chain_head": SHA_A[:-1]},
        {"chain_head": None},
    ],
)
def test_hwm_domain_refused_at_construction(bad: dict[str, object]) -> None:
    kwargs: dict[str, Any] = {
        "venue": VENUE,
        "venue_seq": 1,
        "chain_head": SHA_A,
        "export_seq": 0,
    }
    kwargs.update(bad)
    with pytest.raises(WireRefused):
        Hwm(**kwargs)


def test_hwm_wire_round_trips_and_is_frozen() -> None:
    hwm = Hwm(venue=VENUE, venue_seq=3, chain_head=SHA_A, export_seq=2)
    assert hwm.to_wire() == {
        "venue": VENUE,
        "venue_seq": 3,
        "chain_head": SHA_A,
        "export_seq": 2,
    }
    assert Hwm.from_wire(hwm.to_wire()) == hwm
    assert hwm.to_bytes() == canonical_json(hwm.to_wire())
    with pytest.raises(FrozenInstanceError):
        hwm.venue_seq = 4  # type: ignore[misc]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda w: {k: v for k, v in w.items() if k != "export_seq"},
        lambda w: {**w, "extra": 1},
        lambda w: {**w, "export_seq": True},
        lambda w: {**w, "venue_seq": 1.0},
        lambda w: {**w, "chain_head": 7},
    ],
)
def test_hwm_from_wire_is_exact(mutate: Any) -> None:
    wire = Hwm(venue=VENUE, venue_seq=3, chain_head=SHA_A, export_seq=2).to_wire()
    with pytest.raises(WireRefused):
        Hwm.from_wire(mutate(wire))


def test_hwm_reading_from_bytes_maps_none_to_absent_and_garbage_to_unreadable() -> None:
    assert isinstance(hwm_reading_from_bytes(None), HwmAbsent)
    hwm = Hwm(venue=VENUE, venue_seq=3, chain_head=SHA_A, export_seq=2)
    reading = hwm_reading_from_bytes(hwm.to_bytes())
    assert reading == HwmPresent(hwm)
    garbage: list[Any] = [
        b"",
        b"\xff\xfe",
        b"not json",
        b"[]",
        b'{"venue":"polymarket_us"}',
        b'{"venue":"polymarket_us","venue_seq":0,"chain_head":"'
        + SHA_A.encode()
        + b'","export_seq":0}',
        b'{"venue":"polymarket_us","venue_seq":1.5,"chain_head":"'
        + SHA_A.encode()
        + b'","export_seq":0}',
        b'{"venue":"polymarket_us","venue_seq":1,"venue_seq":2,"chain_head":"'
        + SHA_A.encode()
        + b'","export_seq":0}',
        "a str is not bytes",
        7,
    ]
    for raw in garbage:
        got = hwm_reading_from_bytes(raw)
        assert isinstance(got, HwmUnreadable), raw
        assert got.detail  # a closed code, never the payload
        assert "polymarket" not in got.detail


def test_hwm_unreadable_detail_is_a_closed_code() -> None:
    got = hwm_reading_from_bytes(b"not json")
    assert isinstance(got, HwmUnreadable)
    assert got.detail == WireRefusalReason.MALFORMED_JSON.value


def test_hwm_absent_construction_only_in_hwm_module() -> None:
    def calls_hwm_absent(source: str) -> bool:
        return any(
            isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == "HwmAbsent")
                or (isinstance(node.func, ast.Attribute) and node.func.attr == "HwmAbsent")
            )
            for node in ast.walk(ast.parse(source))
        )

    # Planted controls: a bare call and an attribute call are both seen.
    assert calls_hwm_absent("x = HwmAbsent()")
    assert calls_hwm_absent("x = hwm.HwmAbsent()")
    assert not calls_hwm_absent("x = isinstance(r, HwmAbsent)")

    offenders = [
        str(path.relative_to(SRC_DIR))
        for path in sorted(SRC_DIR.rglob("*.py"))
        if path != HWM_PATH and calls_hwm_absent(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
    assert calls_hwm_absent(HWM_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------
# hwm_check
# ---------------------------------------------------------------------------------------------


def test_hwm_check_accepts_a_consistent_reading() -> None:
    chain = _chain(4)
    for seq in (1, 2, 4):
        assert hwm_check(chain, _present(_hwm_at(chain, seq)), newest_export_seq=0) is None


def test_hwm_absent_with_rows_refuses_and_empty_chain_passes() -> None:
    absent = hwm_reading_from_bytes(None)
    assert hwm_check(_chain(1), absent, newest_export_seq=0) is RefusalReason.HWM_ABSENT
    assert hwm_check(_chain(0), absent, newest_export_seq=0) is None


def test_hwm_check_unknown_reading_type_is_unreadable() -> None:
    chain = _chain(2)
    for reading in (object(), None, "x", _hwm_at(chain, 1)):
        assert (
            hwm_check(chain, reading, newest_export_seq=0)  # type: ignore[arg-type]
            is RefusalReason.HWM_UNREADABLE
        )
    unreadable = HwmUnreadable("malformed_json")
    assert hwm_check(chain, unreadable, newest_export_seq=0) is RefusalReason.HWM_UNREADABLE


def test_hwm_check_foreign_venue_is_unreadable() -> None:
    chain = _chain(2)
    foreign = HwmPresent(_raw_hwm(venue=OTHER_VENUE))
    assert hwm_check(chain, foreign, newest_export_seq=0) is RefusalReason.HWM_UNREADABLE


@pytest.mark.parametrize("seq", [0, -1, -100])
def test_hwm_seq_zero_and_negative_refused(seq: int) -> None:
    chain = _chain(2)
    # Construction refuses it...
    with pytest.raises(WireRefused):
        Hwm(venue=VENUE, venue_seq=seq, chain_head=SHA_A, export_seq=0)
    # ...and a value that got around the constructor is unreadable, never an index.
    bypass = HwmPresent(_raw_hwm(venue_seq=seq))
    assert hwm_check(chain, bypass, newest_export_seq=0) is RefusalReason.HWM_UNREADABLE


def test_registry_hwm_refuses_regression() -> None:
    chain = _chain(3)
    ahead = Hwm(venue=VENUE, venue_seq=4, chain_head=SHA_A, export_seq=0)
    assert hwm_check(chain, _present(ahead), newest_export_seq=0) is RefusalReason.HWM_REGRESSED
    # A chain rewound to a shorter, internally valid prefix is a regression.
    shorter = _chain(2)
    seen_at_3 = _hwm_at(chain, 3)
    assert hwm_check(shorter, _present(seen_at_3), newest_export_seq=0) is (
        RefusalReason.HWM_REGRESSED
    )


def test_hwm_mid_chain_hash_mismatch_regressed() -> None:
    chain = _chain(4)
    # Head hash matches the head, but at the HWM's own index (2) the hash is wrong.
    wrong_mid = Hwm(venue=VENUE, venue_seq=2, chain_head=chain.head_hash, export_seq=0)
    assert hwm_check(chain, _present(wrong_mid), newest_export_seq=0) is (
        RefusalReason.HWM_REGRESSED
    )
    forged = Hwm(venue=VENUE, venue_seq=2, chain_head=SHA_C, export_seq=0)
    assert hwm_check(chain, _present(forged), newest_export_seq=0) is RefusalReason.HWM_REGRESSED


def test_hwm_at_head_compares_last_row() -> None:
    chain = _chain(3)
    at_head = _hwm_at(chain, 3)
    assert at_head.chain_head == chain.head_hash
    assert hwm_check(chain, _present(at_head), newest_export_seq=0) is None
    # venue_seq N is rows[N - 1]: the hash of row N+1 never stands for row N.
    off_by_one = Hwm(
        venue=VENUE, venue_seq=2, chain_head=chain.rows[2].transition_hash or "", export_seq=0
    )
    assert hwm_check(chain, _present(off_by_one), newest_export_seq=0) is (
        RefusalReason.HWM_REGRESSED
    )


def test_hwm_export_seq_above_newest_regressed() -> None:
    chain = _chain(2)
    hwm = _hwm_at(chain, 2, export_seq=3)
    assert hwm_check(chain, _present(hwm), newest_export_seq=2) is RefusalReason.HWM_REGRESSED
    assert hwm_check(chain, _present(hwm), newest_export_seq=3) is None
    assert hwm_check(chain, _present(hwm), newest_export_seq=9) is None
    assert hwm_check(chain, _present(_hwm_at(chain, 2, export_seq=0)), newest_export_seq=0) is None


def test_hwm_check_runs_its_rules_in_order() -> None:
    chain = _chain(2)
    # Rule 3 (foreign venue) outranks rule 4 (above head).
    both = HwmPresent(_raw_hwm(venue=OTHER_VENUE, venue_seq=9))
    assert hwm_check(chain, both, newest_export_seq=0) is RefusalReason.HWM_UNREADABLE
    # Rule 4 (above head) outranks rule 6 (export above newest).
    above = HwmPresent(_raw_hwm(venue_seq=9, export_seq=9))
    assert hwm_check(chain, above, newest_export_seq=0) is RefusalReason.HWM_REGRESSED


def test_next_hwm_is_head_and_verified_export() -> None:
    chain = _chain(3)
    got = next_hwm(chain, export_seq=5)
    assert got == Hwm(
        venue=VENUE,
        venue_seq=3,
        chain_head=chain.rows[-1].transition_hash or "",
        export_seq=5,
    )
    assert got.chain_head == chain.head_hash
    assert hwm_check(chain, _present(got), newest_export_seq=5) is None
    assert next_hwm(chain, export_seq=0).export_seq == 0
    assert next_hwm(_chain(1), export_seq=0).venue_seq == 1
    with pytest.raises(WireRefused):
        next_hwm(chain, export_seq=-1)
    with pytest.raises(WireRefused):
        next_hwm(_chain(0), export_seq=0)  # no head to mark


# ---------------------------------------------------------------------------------------------
# write_monotone_decision (A5-R2, security N2)
# ---------------------------------------------------------------------------------------------


def _h(venue_seq: int, export_seq: int, head: str = SHA_A, venue: str = VENUE) -> Hwm:
    return Hwm(venue=venue, venue_seq=venue_seq, chain_head=head, export_seq=export_seq)


W, S, R = HwmWriteDecision.WRITE, HwmWriteDecision.SKIP, HwmWriteDecision.REFUSE

# (rule, current reading, new, expected). Every rule 1-7 of AC 16 is a row; the grid below covers
# the (venue_seq, export_seq) lattice around the stored value.
_RULE_CASES: Final = [
    ("1 absent", hwm_reading_from_bytes(None), _h(5, 5), W),
    ("2 unreadable", HwmUnreadable("malformed_json"), _h(5, 5), R),
    ("2 unknown type", object(), _h(5, 5), R),
    ("2 none", None, _h(5, 5), R),
    ("3 foreign venue", HwmPresent(_h(5, 5)), _h(9, 9, venue=OTHER_VENUE), R),
    ("4 same seq other head", HwmPresent(_h(5, 5)), _h(5, 5, head=SHA_B), R),
    ("4 same seq other head higher export", HwmPresent(_h(5, 5)), _h(5, 9, head=SHA_B), R),
    ("5 identical", HwmPresent(_h(5, 5)), _h(5, 5), S),
    ("5 seq up", HwmPresent(_h(5, 5)), _h(6, 5, head=SHA_B), W),
    ("5 export up", HwmPresent(_h(5, 5)), _h(5, 6), W),
    ("5 both up", HwmPresent(_h(5, 5)), _h(6, 6, head=SHA_B), W),
    ("6 seq down", HwmPresent(_h(5, 5)), _h(4, 5, head=SHA_B), S),
    ("6 export down", HwmPresent(_h(5, 5)), _h(5, 4), S),
    ("6 both down", HwmPresent(_h(5, 5)), _h(4, 4, head=SHA_B), S),
    ("7 seq up export down", HwmPresent(_h(5, 5)), _h(6, 4, head=SHA_B), R),
    ("7 seq down export up", HwmPresent(_h(5, 5)), _h(4, 6, head=SHA_B), R),
]


@pytest.mark.parametrize(
    ("current", "new", "expected"),
    [pytest.param(c, n, e, id=rule) for rule, c, n, e in _RULE_CASES],
)
def test_hwm_write_never_lowers(current: Any, new: Hwm, expected: HwmWriteDecision) -> None:
    assert write_monotone_decision(current, new) is expected


def test_hwm_write_never_lowers_over_the_whole_lattice() -> None:
    """Whatever the decision, a WRITE never lowers either sequence of the stored value."""
    stored = _h(3, 3)
    for vs, es in itertools.product(range(1, 6), range(6)):
        new = _h(vs, es, head=SHA_A if vs == 3 else SHA_B)
        decision = write_monotone_decision(HwmPresent(stored), new)
        if decision is W:
            assert new.venue_seq >= stored.venue_seq
            assert new.export_seq >= stored.export_seq
            assert new != stored
        if (vs, es) == (3, 3):
            assert decision is S
        if (vs - 3) * (es - 3) < 0:
            assert decision is R


def test_write_monotone_decision_is_pure_and_closed() -> None:
    assert {d.value for d in HwmWriteDecision} == {"WRITE", "SKIP", "REFUSE"}
    current = HwmPresent(_h(5, 5))
    first = write_monotone_decision(current, _h(6, 6, head=SHA_B))
    assert write_monotone_decision(current, _h(6, 6, head=SHA_B)) is first
    assert current == HwmPresent(_h(5, 5))


def test_write_monotone_decision_refuses_a_non_hwm_new_value() -> None:
    for bad in (None, object(), {"venue_seq": 9}):
        assert write_monotone_decision(HwmPresent(_h(5, 5)), bad) is R  # type: ignore[arg-type]
        assert write_monotone_decision(hwm_reading_from_bytes(None), bad) is R  # type: ignore[arg-type]


def test_hwm_module_exports_the_planned_surface() -> None:
    assert set(hwm_mod.__all__) == {
        "REGISTRY_HWM_KEY_PREFIX",
        "Hwm",
        "HwmAbsent",
        "HwmPresent",
        "HwmReading",
        "HwmUnreadable",
        "HwmWriteDecision",
        "hwm_check",
        "hwm_key",
        "hwm_reading_from_bytes",
        "next_hwm",
        "write_monotone_decision",
    }
