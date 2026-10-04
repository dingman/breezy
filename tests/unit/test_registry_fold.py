"""ARCH-0 seam 6b: the structural ``fold`` and the ``transitions`` constants and admissibility.

``fold`` is pure: states per family, pending pairs, the ACTIVATE window [16:40Z, LAUNCH) and the
lapse at LAUNCH. SWAP_CANCEL voiding, freezes, tallies and drill episodes are seam 7a/7b.
``transitions`` holds the closed kind tables and ``rows_admissible``, the one predicate that
compares a stage's kind sets against rows.
"""

from __future__ import annotations

import ast
import itertools
from dataclasses import FrozenInstanceError, replace
from datetime import date
from pathlib import Path
from typing import Any, Final

import pytest

import breezy.persistence.autonomy.transitions as transitions_mod
from breezy.persistence.autonomy import schemas
from breezy.persistence.autonomy.chain import genesis, transition_hash, verify_venue_chain
from breezy.persistence.autonomy.fold import (
    FoldInvalid,
    FoldResult,
    PairStatus,
    PairView,
    fold,
)
from breezy.persistence.autonomy.schemas import (
    AdmissibilityResult,
    DecidedBy,
    FoldInvalidReason,
    Kind,
    RefusalReason,
    StagePolicy,
    State,
    TransitionRow,
    WriterMode,
)
from breezy.persistence.autonomy.transitions import (
    ALLOWED,
    KIND_MASK,
    PAIR_KINDS,
    RESTRICTIVE_KINDS,
    WIDENING_KINDS,
    is_widening,
    rows_admissible,
    transition_id,
)
from tests.support.entry_points import SRC_DIR
from tests.unit.autonomy_blocks_kinds_floor import FLOOR_KIND_VOCABULARY

VENUE = "polymarket_us"
INCUMBENT = "pm_us_crh_fq_v1"
CHILD = "pm_us_crh_fq_v1_r0001"
OTHER = "pm_us_crh_v4"
SHA_B = "b" * 64
INVOCATION = "00000000-0000-4000-8000-000000000001"
DAY = "2026-10-10"
SEC = 10**9
UNIX_ORDINAL = date(1970, 1, 1).toordinal()
AUTONOMY_DIR: Final[Path] = SRC_DIR / "breezy" / "persistence" / "autonomy"


def at(day: str, hhmm: str = "00:00", extra_ns: int = 0) -> int:
    """Epoch nanoseconds of ``day`` ``hhmm`` UTC plus ``extra_ns`` (an independent calculation)."""
    hours, minutes = (int(p) for p in hhmm.split(":"))
    days = date.fromisoformat(day).toordinal() - UNIX_ORDINAL
    return (days * 86_400 + hours * 3_600 + minutes * 60) * SEC + extra_ns


LAUNCH = at(DAY, "16:50")
STOP = at(DAY, "16:40")
PRIOR_DAY = "2026-10-09"


class Chain:
    """Builds unsealed rows in chain order with correct family priors and increasing ts."""

    def __init__(self, venue: str = VENUE) -> None:
        self.venue = venue
        self.rows: list[TransitionRow] = []
        self._last_seq: dict[str, int] = {}
        self._ts = at(PRIOR_DAY, "12:00")

    def add(
        self, kind: Kind, to: State, *, family: str, frm: State | None = None,
        ts: int | None = None, **extra: Any,
    ) -> TransitionRow:  # fmt: skip
        if ts is None:
            self._ts += SEC
            ts = self._ts
        assert ts >= self._ts - SEC, "builder ts must not decrease"
        self._ts = max(self._ts, ts)
        base: dict[str, Any] = {
            "venue": self.venue,
            "family_id": family,
            "family_prior_seq": self._last_seq.get(family, 0),
            "from_state": frm,
            "to_state": to,
            "kind": kind,
            "decided_by": DecidedBy.ENGINE,
            "invocation_id": INVOCATION,
            "engine_code_sha": SHA_B,
            "expected_prior_seq": len(self.rows),
            "ts_ns": ts,
            "transition_id": "a" * 64,
        }
        base.update(extra)
        draft = TransitionRow(**base)
        row = replace(draft, transition_id=draft.computed_transition_id())
        self.rows.append(row)
        self._last_seq[family] = len(self.rows)
        return row

    def seed(self) -> None:
        """INCUMBENT CHAMPION; CHILD minted then nominated to CHALLENGER."""
        self.add(Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT)
        self.add(Kind.MINT, State.SHADOW, family=CHILD)
        self.add(Kind.PROMOTE, State.CHALLENGER, family=CHILD, frm=State.SHADOW)

    def promote_pair(
        self, *, day: str = DAY, outgoing: str = INCUMBENT, partner: Kind = Kind.SUPERSEDE
    ) -> tuple[TransitionRow, TransitionRow]:
        head = self.add(
            Kind.PROMOTE, State.CHAMPION, family=CHILD, frm=State.CHALLENGER,
            effective_launch_date=day,
        )  # fmt: skip
        out_from = State.CHAMPION if partner is Kind.SUPERSEDE else State.HALTED
        tail = self.add(
            partner, State.CHALLENGER, family=outgoing, frm=out_from,
            paired_transition_id=head.transition_id, effective_launch_date=day,
        )  # fmt: skip
        return head, tail

    def activate(self, head: TransitionRow, *, ts: int, family: str | None = None) -> TransitionRow:
        return self.add(
            Kind.ACTIVATE, State.CHALLENGER, family=family or head.family_id,
            frm=State.CHALLENGER, ts=ts, paired_transition_id=head.transition_id,
            effective_launch_date=head.effective_launch_date,
        )  # fmt: skip


def run(chain: Chain, now_ns: int) -> FoldResult:
    result = fold(chain.rows, chain.venue, now_ns)
    assert isinstance(result, FoldResult), result
    return result


def seeded_pair(*, partner: Kind = Kind.SUPERSEDE) -> tuple[Chain, TransitionRow, TransitionRow]:
    chain = Chain()
    chain.seed()
    if partner is Kind.DISPLACED:
        chain.add(Kind.HALT, State.HALTED, family=INCUMBENT, frm=State.CHAMPION)
    head, tail = chain.promote_pair(partner=partner)
    return chain, head, tail


# --- plain states --------------------------------------------------------------------------


def test_fold_of_no_rows_has_no_families_and_no_pairs() -> None:
    result = run(Chain(), LAUNCH)
    assert dict(result.states) == {}
    assert result.pairs == ()
    assert result.head_venue_seq == 0
    assert result.venue == VENUE


def test_fold_applies_immediate_rows_in_chain_order() -> None:
    chain = Chain()
    chain.seed()
    result = run(chain, at(DAY, "00:00"))
    assert dict(result.states) == {INCUMBENT: State.CHAMPION, CHILD: State.CHALLENGER}
    assert result.head_venue_seq == 3


@pytest.mark.parametrize(
    ("kind", "frm", "to", "expected"),
    [
        (Kind.DEMOTE, State.CHAMPION, State.HALTED, State.HALTED),
        (Kind.HALT, State.CHAMPION, State.HALTED, State.HALTED),
        (Kind.ATTEST, State.CHAMPION, State.CHAMPION, State.CHAMPION),
        (Kind.HWM_RESET, State.CHAMPION, State.CHAMPION, State.CHAMPION),
    ],
)
def test_champion_row_kinds_move_or_keep_state(
    kind: Kind, frm: State, to: State, expected: State
) -> None:
    chain = Chain()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT)
    chain.add(kind, to, family=INCUMBENT, frm=frm)
    assert run(chain, LAUNCH).states[INCUMBENT] is expected


def test_resume_and_retire_follow_halt() -> None:
    chain = Chain()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT)
    chain.add(Kind.DEMOTE, State.HALTED, family=INCUMBENT, frm=State.CHAMPION)
    assert run(chain, LAUNCH).states[INCUMBENT] is State.HALTED
    chain.add(Kind.RESUME, State.CHAMPION, family=INCUMBENT, frm=State.HALTED)
    assert run(chain, LAUNCH).states[INCUMBENT] is State.CHAMPION
    chain.add(Kind.HALT, State.HALTED, family=INCUMBENT, frm=State.CHAMPION)
    chain.add(Kind.RETIRE, State.RETIRED, family=INCUMBENT, frm=State.HALTED)
    assert run(chain, LAUNCH).states[INCUMBENT] is State.RETIRED


def test_same_state_rows_never_change_state_of_a_different_current_state() -> None:
    """An ATTEST naming CHAMPION for a halted family is validate's to refuse; fold keeps HALTED."""
    chain = Chain()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT)
    chain.add(Kind.DEMOTE, State.HALTED, family=INCUMBENT, frm=State.CHAMPION)
    chain.add(Kind.ATTEST, State.CHAMPION, family=INCUMBENT, frm=State.CHAMPION)
    assert run(chain, LAUNCH).states[INCUMBENT] is State.HALTED


# --- pending pairs, the ACTIVATE window and the lapse -------------------------------------


def test_pair_is_pending_before_launch_and_changes_no_state() -> None:
    chain, head, tail = seeded_pair()
    result = run(chain, LAUNCH - 1)
    assert result.states[INCUMBENT] is State.CHAMPION
    assert result.states[CHILD] is State.CHALLENGER
    (pair,) = result.pairs
    assert pair == PairView(
        head_transition_id=head.transition_id,
        head_kind=Kind.PROMOTE,
        incoming_family_id=CHILD,
        member_transition_ids=(head.transition_id, tail.transition_id),
        effective_launch_date=DAY,
        launch_ns=LAUNCH,
        activate_transition_id=None,
        status=PairStatus.PENDING,
    )


def test_activated_pair_takes_effect_exactly_at_launch() -> None:
    chain, head, _tail = seeded_pair()
    activate = chain.activate(head, ts=at(DAY, "16:45"))
    before = run(chain, LAUNCH - 1)
    assert before.pairs[0].status is PairStatus.PENDING
    assert before.pairs[0].activate_transition_id == activate.transition_id
    assert before.states[CHILD] is State.CHALLENGER
    after = run(chain, LAUNCH)
    assert after.pairs[0].status is PairStatus.EFFECTIVE
    assert after.states[CHILD] is State.CHAMPION
    assert after.states[INCUMBENT] is State.CHALLENGER


def test_pair_without_activate_lapses_at_launch_and_leaves_the_incumbent() -> None:
    chain, _head, _tail = seeded_pair()
    result = run(chain, LAUNCH)
    assert result.pairs[0].status is PairStatus.LAPSED
    assert result.states[INCUMBENT] is State.CHAMPION
    assert result.states[CHILD] is State.CHALLENGER
    later = run(chain, at("2026-10-12", "09:00"))
    assert later.pairs[0].status is PairStatus.LAPSED
    assert later.states[INCUMBENT] is State.CHAMPION


@pytest.mark.parametrize(
    ("ts", "valid"),
    [
        (STOP - 1, False),
        (STOP, True),
        (LAUNCH - 1, True),
        (LAUNCH, False),
        (at(DAY, "17:00"), False),
        (at(PRIOR_DAY, "16:45"), False),  # right clock time, wrong day
    ],
    ids=["one_ns_before_stop", "at_stop", "one_ns_before_launch", "at_launch", "1700", "prior_day"],
)
def test_activate_counts_only_inside_stop_to_launch_window(ts: int, valid: bool) -> None:
    chain, head, _tail = seeded_pair()
    chain.activate(head, ts=ts)
    pair = run(chain, LAUNCH + 1).pairs[0]
    assert (pair.status is PairStatus.EFFECTIVE) is valid
    assert (pair.activate_transition_id is not None) is valid


def test_activate_for_another_family_or_unknown_pair_is_ignored() -> None:
    chain, head, _tail = seeded_pair()
    chain.activate(head, ts=at(DAY, "16:45"), family=INCUMBENT)
    stray = replace(head, transition_id="c" * 64)  # a head id no chain row carries
    chain.activate(stray, ts=at(DAY, "16:46"))
    pair = run(chain, LAUNCH).pairs[0]
    assert pair.status is PairStatus.LAPSED
    assert pair.activate_transition_id is None


def test_first_valid_activate_is_the_one_recorded() -> None:
    chain, head, _tail = seeded_pair()
    first = chain.activate(head, ts=at(DAY, "16:44"))
    chain.activate(head, ts=at(DAY, "16:46"))
    assert run(chain, LAUNCH).pairs[0].activate_transition_id == first.transition_id


def test_displaced_partner_returns_a_halted_incumbent_to_challenger() -> None:
    chain, head, _tail = seeded_pair(partner=Kind.DISPLACED)
    chain.activate(head, ts=at(DAY, "16:45"))
    assert run(chain, LAUNCH - 1).states[INCUMBENT] is State.HALTED
    result = run(chain, LAUNCH)
    assert result.states[INCUMBENT] is State.CHALLENGER
    assert result.states[CHILD] is State.CHAMPION


def test_partner_naming_no_head_never_takes_effect() -> None:
    chain = Chain()
    chain.seed()
    chain.add(
        Kind.SUPERSEDE, State.CHALLENGER, family=INCUMBENT, frm=State.CHAMPION,
        paired_transition_id="d" * 64, effective_launch_date=DAY,
    )  # fmt: skip
    result = run(chain, at("2026-10-12", "09:00"))
    assert result.states[INCUMBENT] is State.CHAMPION
    assert result.pairs == ()


def test_rollback_pair_with_activate_in_one_transaction() -> None:
    chain = Chain()
    chain.seed()
    chain.add(Kind.PROMOTE, State.CHAMPION, family=CHILD, frm=State.CHALLENGER,
              effective_launch_date=PRIOR_DAY)  # fmt: skip
    # incumbent is the rollback target: CHALLENGER after the earlier supersede, here set directly
    chain.add(Kind.SUPERSEDE, State.CHALLENGER, family=INCUMBENT, frm=State.CHAMPION,
              paired_transition_id=chain.rows[-1].transition_id,
              effective_launch_date=PRIOR_DAY)  # fmt: skip
    chain.activate(chain.rows[-2], ts=at(PRIOR_DAY, "16:45"))
    assert run(chain, at(DAY, "00:00")).states[CHILD] is State.CHAMPION
    chain.add(Kind.DEMOTE, State.HALTED, family=CHILD, frm=State.CHAMPION)
    back = chain.add(Kind.ROLLBACK, State.CHAMPION, family=INCUMBENT, frm=State.CHALLENGER,
                     effective_launch_date=DAY)  # fmt: skip
    chain.add(Kind.DISPLACED, State.CHALLENGER, family=CHILD, frm=State.HALTED,
              paired_transition_id=back.transition_id, effective_launch_date=DAY)  # fmt: skip
    chain.activate(back, ts=at(DAY, "16:45"))
    result = run(chain, LAUNCH)
    assert result.states[INCUMBENT] is State.CHAMPION
    assert result.states[CHILD] is State.CHALLENGER
    assert [p.status for p in result.pairs] == [PairStatus.EFFECTIVE, PairStatus.EFFECTIVE]


def test_root_admit_introduces_a_shadow_family_that_activates_at_launch() -> None:
    chain = Chain()
    chain.add(Kind.BOOTSTRAP, State.RETIRED, family=OTHER)
    head = chain.add(Kind.ROOT_ADMIT, State.CHAMPION, family=INCUMBENT, effective_launch_date=DAY)
    assert run(chain, LAUNCH - 1).states[INCUMBENT] is State.SHADOW
    chain.add(Kind.ACTIVATE, State.SHADOW, family=INCUMBENT, frm=State.SHADOW,
              ts=at(DAY, "16:45"), paired_transition_id=head.transition_id,
              effective_launch_date=DAY)  # fmt: skip
    after = run(chain, LAUNCH)
    assert after.states[INCUMBENT] is State.CHAMPION
    assert after.pairs[0].head_kind is Kind.ROOT_ADMIT
    assert after.pairs[0].member_transition_ids == (head.transition_id,)


def test_lapsed_root_admit_leaves_the_family_in_shadow() -> None:
    chain = Chain()
    chain.add(Kind.ROOT_ADMIT, State.CHAMPION, family=INCUMBENT, effective_launch_date=DAY)
    result = run(chain, LAUNCH)
    assert result.states[INCUMBENT] is State.SHADOW
    assert result.pairs[0].status is PairStatus.LAPSED


def test_rows_apply_by_effective_instant_not_chain_position() -> None:
    """A RESUME written after a pending DISPLACED pair, but before LAUNCH, applies first."""
    chain = Chain()
    chain.seed()
    chain.add(Kind.HALT, State.HALTED, family=INCUMBENT, frm=State.CHAMPION)
    head = chain.add(Kind.PROMOTE, State.CHAMPION, family=CHILD, frm=State.CHALLENGER,
                     effective_launch_date=DAY)  # fmt: skip
    chain.add(Kind.DISPLACED, State.CHALLENGER, family=INCUMBENT, frm=State.HALTED,
              paired_transition_id=head.transition_id, effective_launch_date=DAY)  # fmt: skip
    chain.activate(head, ts=at(DAY, "16:45"))
    chain.add(Kind.RESUME, State.CHAMPION, family=INCUMBENT, frm=State.HALTED, ts=at(DAY, "16:46"))
    result = run(chain, LAUNCH)
    assert result.states[INCUMBENT] is State.CHALLENGER  # RESUME (16:46) then DISPLACED (16:50)


# --- introduction ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "frm", "to"),
    [
        (Kind.ROLLBACK, State.CHALLENGER, State.CHAMPION),
        (Kind.RESUME, State.HALTED, State.CHAMPION),
        (Kind.PROMOTE, State.SHADOW, State.CHALLENGER),
        (Kind.ACTIVATE, State.CHALLENGER, State.CHALLENGER),
        (Kind.DRILL_ADMIT, State.SHADOW, State.CHALLENGER),
    ],
)
def test_family_introduced_by_other_kind_is_invalid(kind: Kind, frm: State, to: State) -> None:
    chain = Chain()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT)
    chain.add(kind, to, family=CHILD, frm=frm)
    result = fold(chain.rows, VENUE, LAUNCH)
    assert result == FoldInvalid(FoldInvalidReason.FAMILY_INTRODUCED_BY_OTHER_KIND)


@pytest.mark.parametrize("kind", [Kind.BOOTSTRAP, Kind.MINT, Kind.ROOT_ADMIT])
def test_introducing_kinds_are_accepted(kind: Kind) -> None:
    chain = Chain()
    chain.add(kind, State.SHADOW if kind is Kind.MINT else State.CHAMPION, family=INCUMBENT)
    assert isinstance(fold(chain.rows, VENUE, LAUNCH), FoldResult)


# --- input contract, purity, immutability --------------------------------------------------


def test_fold_refuses_a_foreign_venue_row() -> None:
    chain = Chain(venue="kalshi")
    chain.seed()
    with pytest.raises(ValueError, match="venue"):
        fold(chain.rows, VENUE, LAUNCH)


def test_fold_refuses_a_non_row() -> None:
    with pytest.raises(TypeError, match="TransitionRow"):
        fold([{"kind": "MINT"}], VENUE, 0)  # type: ignore[list-item]


@pytest.mark.parametrize("bad", [-1, True, 1.5, "0", None])
def test_fold_refuses_a_bad_clock(bad: object) -> None:
    chain = Chain()
    chain.seed()
    with pytest.raises(ValueError, match="now_ns"):
        fold(chain.rows, VENUE, bad)  # type: ignore[arg-type]


def test_fold_refuses_a_malformed_venue() -> None:
    with pytest.raises(ValueError):
        fold([], "../x", 0)


def test_fold_is_deterministic_and_does_not_touch_its_input() -> None:
    chain, head, _tail = seeded_pair()
    chain.activate(head, ts=at(DAY, "16:45"))
    snapshot = tuple(chain.rows)
    first, second = run(chain, LAUNCH), run(chain, LAUNCH)
    assert first == second
    assert tuple(chain.rows) == snapshot


def test_fold_accepts_any_sequence_and_iterates_it_once() -> None:
    chain = Chain()
    chain.seed()
    assert run(chain, LAUNCH) == fold(tuple(chain.rows), VENUE, LAUNCH)


def test_results_are_frozen_and_states_are_read_only() -> None:
    chain = Chain()
    chain.seed()
    result = run(chain, LAUNCH)
    with pytest.raises(FrozenInstanceError):
        result.now_ns = 0  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.states[INCUMBENT] = State.RETIRED  # type: ignore[index]
    view = PairView(
        head_transition_id="a" * 64, head_kind=Kind.PROMOTE, incoming_family_id=CHILD,
        member_transition_ids=(), effective_launch_date=DAY, launch_ns=0,
        activate_transition_id=None, status=PairStatus.PENDING,
    )  # fmt: skip
    with pytest.raises(FrozenInstanceError):
        view.status = PairStatus.LAPSED  # type: ignore[misc]


def test_fold_over_a_verified_chain_matches_the_unsealed_rows() -> None:
    chain, head, _tail = seeded_pair()
    chain.activate(head, ts=at(DAY, "16:45"))
    sealed: list[TransitionRow] = []
    prev = genesis(VENUE)
    for i, row in enumerate(chain.rows, start=1):
        link = replace(row, seq=i, venue_seq=i, prev_transition_hash=prev)
        link = replace(link, transition_hash=transition_hash(link, prev))
        sealed.append(link)
        prev = link.transition_hash or ""
    verified = verify_venue_chain(sealed, VENUE)
    assert fold(verified.rows, VENUE, LAUNCH) == run(chain, LAUNCH)


def test_fold_module_imports_only_schemas_and_pins() -> None:
    assert _internal_imports("fold.py") == {"schemas", "pins"}


def test_fold_hardcodes_the_pins_schedule_not_literals() -> None:
    source = (AUTONOMY_DIR / "fold.py").read_text(encoding="utf-8")
    for literal in ("16:40", "16:50", "17:00"):
        assert literal not in source


def _internal_imports(filename: str) -> set[str]:
    tree = ast.parse((AUTONOMY_DIR / filename).read_text(encoding="utf-8"))
    prefix = "breezy.persistence.autonomy."
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith(prefix):
                found.add(node.module.removeprefix(prefix))
            elif node.module == "breezy.persistence.autonomy":
                found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            found.update(
                alias.name.removeprefix(prefix)
                for alias in node.names
                if alias.name.startswith(prefix)
            )
    return found


# --- transitions: closed tables ------------------------------------------------------------

_S, _CH, _CP, _H, _R = (State.SHADOW, State.CHALLENGER, State.CHAMPION, State.HALTED, State.RETIRED)
#: The ARCH C5 "Allowed transitions" table, written out independently of ``transitions``.
EXPECTED_ALLOWED: Final[dict[Kind, set[tuple[State | None, State]]]] = {
    Kind.BOOTSTRAP: {(None, _CP), (None, _R), (None, _S)},
    Kind.MINT: {(None, _S)},
    Kind.PROMOTE: {(_S, _CH), (_CH, _CP)},
    Kind.DRILL_ADMIT: {(_S, _CH)},
    Kind.DRILL_PROMOTE: {(_CH, _CP)},
    Kind.ROLLBACK: {(_CH, _CP)},
    Kind.ROOT_ADMIT: {(_S, _CP), (None, _CP)},
    Kind.SUPERSEDE: {(_CP, _CH)},
    Kind.DISPLACED: {(_H, _CH)},
    Kind.ACTIVATE: {(_CH, _CH), (_S, _S)},
    Kind.SWAP_CANCEL: {(_CH, _CH)},
    Kind.TARGET_INELIGIBLE: {(_CH, _CH)},
    Kind.ATTEST: {(_CP, _CP)},
    Kind.DEMOTE: {(_CP, _H)},
    Kind.HALT: {(_CP, _H)},
    Kind.RESUME: {(_H, _CP)},
    Kind.RETIRE: {(_H, _R), (_S, _R), (_CH, _R)},
    Kind.HWM_RESET: {(s, s) for s in State},
}
#: AUT-5 r7 3.2 ``KIND_MASK`` literal.
EXPECTED_MASK: Final[dict[WriterMode, set[Kind]]] = {
    WriterMode.INTRADAY: {Kind.DEMOTE, Kind.HALT, Kind.SWAP_CANCEL, Kind.TARGET_INELIGIBLE,
                          Kind.ATTEST},
    WriterMode.PRELAUNCH: {Kind.ACTIVATE, Kind.SWAP_CANCEL, Kind.TARGET_INELIGIBLE, Kind.RESUME,
                           Kind.ROLLBACK, Kind.SUPERSEDE, Kind.DISPLACED, Kind.ROOT_ADMIT,
                           Kind.DEMOTE, Kind.HALT},
    WriterMode.DAILY: {Kind.MINT, Kind.PROMOTE, Kind.DRILL_ADMIT, Kind.DRILL_PROMOTE,
                       Kind.ROLLBACK, Kind.SUPERSEDE, Kind.DISPLACED, Kind.SWAP_CANCEL,
                       Kind.TARGET_INELIGIBLE, Kind.DEMOTE, Kind.HALT, Kind.RETIRE},
    WriterMode.BOOTSTRAP: {Kind.BOOTSTRAP},
    WriterMode.OPERATOR_CLI: {Kind.HWM_RESET, Kind.DEMOTE, Kind.HALT, Kind.SWAP_CANCEL,
                              Kind.RETIRE},
}  # fmt: skip
EXPECTED_WIDENING: Final = {
    Kind.PROMOTE, Kind.DRILL_PROMOTE, Kind.ROLLBACK, Kind.RESUME, Kind.ROOT_ADMIT,
    Kind.ACTIVATE, Kind.SUPERSEDE, Kind.DISPLACED, Kind.DRILL_ADMIT,
}  # fmt: skip


def test_allowed_is_the_arch_table_exactly() -> None:
    assert {k: set(v) for k, v in ALLOWED.items()} == EXPECTED_ALLOWED
    assert all(isinstance(v, frozenset) for v in ALLOWED.values())


def test_allowed_names_every_kind_and_is_read_only() -> None:
    assert set(ALLOWED) == set(Kind)
    with pytest.raises(TypeError):
        ALLOWED[Kind.MINT] = frozenset()  # type: ignore[index]


def test_kind_mask_is_the_aut5_literal_exactly() -> None:
    assert {m: set(k) for m, k in KIND_MASK.items()} == EXPECTED_MASK
    assert set(KIND_MASK) == set(WriterMode)


def test_every_kind_is_writable_by_some_mode() -> None:
    assert set().union(*KIND_MASK.values()) == set(Kind)


def test_widening_kinds_are_the_aut5_literal() -> None:
    assert set(WIDENING_KINDS) == EXPECTED_WIDENING
    assert isinstance(WIDENING_KINDS, frozenset)


def test_widening_kinds_agree_with_the_independent_floor_vocabulary() -> None:
    assert {k.value for k in WIDENING_KINDS} | {"HWM_RESET"} == set(FLOOR_KIND_VOCABULARY)


def test_restrictive_kinds_never_overlap_widening_and_are_always_maskable() -> None:
    assert set(RESTRICTIVE_KINDS) == {
        Kind.DEMOTE, Kind.HALT, Kind.SWAP_CANCEL, Kind.TARGET_INELIGIBLE,
    }  # fmt: skip
    assert not (RESTRICTIVE_KINDS & WIDENING_KINDS)
    for mode in (WriterMode.INTRADAY, WriterMode.OPERATOR_CLI):
        assert not (KIND_MASK[mode] & WIDENING_KINDS), mode


def test_neutral_kinds_are_in_neither_set() -> None:
    neutral = set(Kind) - WIDENING_KINDS - RESTRICTIVE_KINDS
    assert neutral == {Kind.BOOTSTRAP, Kind.MINT, Kind.ATTEST, Kind.RETIRE, Kind.HWM_RESET}


def test_is_widening_matches_the_set_for_every_kind() -> None:
    for kind in Kind:
        assert is_widening(kind) is (kind in EXPECTED_WIDENING)


def test_pair_kinds_are_the_heads_partners_and_activate() -> None:
    assert set(PAIR_KINDS) == {
        Kind.PROMOTE, Kind.DRILL_PROMOTE, Kind.ROLLBACK, Kind.ROOT_ADMIT,
        Kind.SUPERSEDE, Kind.DISPLACED, Kind.ACTIVATE,
    }  # fmt: skip
    assert PAIR_KINDS <= WIDENING_KINDS


def test_admission_implemented_ships_empty_and_typed() -> None:
    assert transitions_mod._ADMISSION_IMPLEMENTED == frozenset()
    assert isinstance(transitions_mod._ADMISSION_IMPLEMENTED, frozenset)


def test_transition_id_is_the_schemas_function() -> None:
    assert transition_id is schemas.compute_transition_id
    chain = Chain()
    row = chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT)
    assert row.transition_id == transition_id(
        venue=VENUE, family_id=INCUMBENT, family_prior_seq=0, from_state=None,
        to_state=State.CHAMPION, kind=Kind.BOOTSTRAP, cause_verdict_ids=(),
        paired_transition_id=None, policy_ruling_sha256="",
    )  # fmt: skip


def test_transitions_module_imports_only_schemas_and_fold() -> None:
    assert _internal_imports("transitions.py") == {"schemas", "fold"}


# --- rows_admissible -----------------------------------------------------------------------


def _stage(enabled: set[Kind], implemented: set[Kind]) -> StagePolicy:
    return StagePolicy(frozenset(enabled), frozenset(implemented))


def _rows(*kinds: Kind) -> list[TransitionRow]:
    chain = Chain()
    for kind in kinds:
        chain.add(kind, _CP, family=INCUMBENT)
    return chain.rows


def test_rows_admissible_stops_at_first_refused_widening_row() -> None:
    rows = _rows(Kind.DEMOTE, Kind.ATTEST, Kind.RESUME, Kind.PROMOTE, Kind.HALT)
    result = rows_admissible(rows, stage=_stage(set(), set()))
    assert result == AdmissibilityResult(2, RefusalReason.WIDENING_KIND_NOT_ENABLED)
    assert rows[: result.admitted] == rows[:2]


def test_rows_admissible_reports_nothing_refused_for_an_empty_or_restrictive_batch() -> None:
    stage = _stage(set(), set())
    assert rows_admissible([], stage=stage) == AdmissibilityResult(0, None)
    rows = _rows(Kind.DEMOTE, Kind.HALT, Kind.ATTEST, Kind.RETIRE, Kind.HWM_RESET)
    assert rows_admissible(rows, stage=stage) == AdmissibilityResult(5, None)


def test_rows_admissible_refuses_an_enabled_kind_whose_admission_is_unimplemented() -> None:
    rows = _rows(Kind.DEMOTE, Kind.RESUME)
    result = rows_admissible(rows, stage=_stage({Kind.RESUME}, set()))
    assert result == AdmissibilityResult(1, RefusalReason.ADMISSION_PENDING)


def test_rows_admissible_admits_an_enabled_and_implemented_kind() -> None:
    rows = _rows(Kind.RESUME, Kind.DEMOTE)
    stage = _stage({Kind.RESUME}, {Kind.RESUME})
    assert rows_admissible(rows, stage=stage) == AdmissibilityResult(2, None)


def test_not_enabled_is_reported_before_admission_pending() -> None:
    rows = _rows(Kind.PROMOTE)
    assert rows_admissible(rows, stage=_stage(set(), set())).reason is (
        RefusalReason.WIDENING_KIND_NOT_ENABLED
    )


def test_enabling_one_kind_does_not_admit_another() -> None:
    stage = _stage({Kind.RESUME}, {Kind.RESUME})
    result = rows_admissible(_rows(Kind.RESUME, Kind.ROOT_ADMIT), stage=stage)
    assert result == AdmissibilityResult(1, RefusalReason.WIDENING_KIND_NOT_ENABLED)


def test_rows_admissible_gates_every_row_of_a_widening_kind_including_nominations() -> None:
    chain = Chain()
    chain.add(Kind.PROMOTE, _CH, family=CHILD, frm=_S)  # a SHADOW to CHALLENGER nomination
    result = rows_admissible(chain.rows, stage=_stage(set(), set()))
    assert result == AdmissibilityResult(0, RefusalReason.WIDENING_KIND_NOT_ENABLED)


class _ListStage:
    """A StageView that is not a StagePolicy: plain lists, read through the Protocol only."""

    def __init__(self, enabled: list[Kind], implemented: list[Kind]) -> None:
        self.enabled_widening_kinds = enabled
        self.admission_implemented = implemented


def test_rows_admissible_reads_only_the_stage_view_protocol() -> None:
    stage = _ListStage([Kind.PROMOTE], [Kind.PROMOTE])
    assert rows_admissible(_rows(Kind.PROMOTE), stage=stage) == AdmissibilityResult(1, None)


def test_rows_admissible_result_invariant_reason_none_iff_all_admitted() -> None:
    kinds = list(Kind)
    stage_sets = [set(), {Kind.RESUME}, set(WIDENING_KINDS)]
    for batch in itertools.chain(([k] for k in kinds), itertools.combinations(kinds, 2)):
        rows = _rows(*batch)
        for enabled, implemented in itertools.product(stage_sets, stage_sets):
            res = rows_admissible(rows, stage=_stage(enabled, implemented))
            assert (res.reason is None) is (res.admitted == len(rows))
            assert 0 <= res.admitted <= len(rows)


@pytest.mark.parametrize("case", ["transitions", "fold"])
def test_admissibility_predicate_shared(case: str) -> None:
    """One predicate: ``rows_admissible`` equals an oracle; ``fold`` never compares stage sets."""
    if case == "fold":
        tree = ast.parse((AUTONOMY_DIR / "fold.py").read_text(encoding="utf-8"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names |= {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
        assert not names & {
            "enabled_widening_kinds", "admission_implemented", "ENABLED_WIDENING_KINDS",
            "_ADMISSION_IMPLEMENTED", "rows_admissible", "WIDENING_KINDS", "StageView",
            "StagePolicy",
        }  # fmt: skip
        return
    kinds = list(Kind)
    enabled = {Kind.RESUME, Kind.PROMOTE, Kind.ACTIVATE}
    implemented = {Kind.RESUME, Kind.ACTIVATE}
    for batch in itertools.permutations(kinds, 2):
        rows = _rows(*batch)
        expected: AdmissibilityResult = AdmissibilityResult(len(rows), None)
        for i, row in enumerate(rows):
            if row.kind not in EXPECTED_WIDENING:
                continue
            if row.kind not in enabled:
                expected = AdmissibilityResult(i, RefusalReason.WIDENING_KIND_NOT_ENABLED)
            elif row.kind not in implemented:
                expected = AdmissibilityResult(i, RefusalReason.ADMISSION_PENDING)
            else:
                continue
            break
        assert rows_admissible(rows, stage=_stage(enabled, implemented)) == expected, batch
