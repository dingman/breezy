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
from breezy.persistence.autonomy import pins, schemas
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
    is_widening_row,
    rows_admissible,
    transition_id,
)
from tests.support.entry_points import SRC_DIR
from tests.unit.autonomy_blocks_kinds_floor import FLOOR_KIND_VOCABULARY
from tests.unit.registry_manifest_density import introducer_columns

VENUE = "polymarket_us"
INCUMBENT = "pm_us_crh_fq_v1"
CHILD = "pm_us_crh_fq_v1_r0001"
OTHER = "pm_us_crh_v4"
SHA_B = "b" * 64
#: The manifest an introducing row of these families carries unless a test names one (the same
#: shas the validate tests cite when they bind a later row, E-24).
DEFAULT_MANIFEST: Final = {INCUMBENT: "1" * 64, CHILD: "2" * 64}
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
            "venue_seq": len(self.rows) + 1,
            "ts_ns": ts,
            "transition_id": "a" * 64,
        }
        if kind in (Kind.BOOTSTRAP, Kind.ROOT_ADMIT):  # a root names itself (E-14; A7b-R3)
            base["lineage_root_family_id"] = family
        elif kind is Kind.MINT:
            base["lineage_root_family_id"] = INCUMBENT
        base.update(extra)
        if kind in (Kind.BOOTSTRAP, Kind.MINT):  # E-24: the manifest pins the row's artefact
            base.update(introducer_columns(family, base, DEFAULT_MANIFEST.get(family)))
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
        member_effects=((CHILD, State.CHAMPION), (INCUMBENT, State.CHALLENGER)),
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
    first = chain.add(Kind.PROMOTE, State.CHAMPION, family=CHILD, frm=State.CHALLENGER,
                      effective_launch_date=PRIOR_DAY)  # fmt: skip
    chain.add(Kind.SUPERSEDE, State.CHALLENGER, family=INCUMBENT, frm=State.CHAMPION,
              paired_transition_id=first.transition_id,
              effective_launch_date=PRIOR_DAY)  # fmt: skip
    chain.activate(first, ts=at(PRIOR_DAY, "16:45"))
    assert run(chain, at(DAY, "00:00")).states[CHILD] is State.CHAMPION
    chain.add(Kind.DEMOTE, State.HALTED, family=CHILD, frm=State.CHAMPION, ts=at(DAY, "10:00"))
    back = chain.add(Kind.ROLLBACK, State.CHAMPION, family=INCUMBENT, frm=State.CHALLENGER,
                     effective_launch_date=DAY, ts=at(DAY, "16:45", 0))  # fmt: skip
    chain.add(Kind.DISPLACED, State.CHALLENGER, family=CHILD, frm=State.HALTED,
              paired_transition_id=back.transition_id, effective_launch_date=DAY,
              ts=at(DAY, "16:45", 1))  # fmt: skip
    chain.activate(back, ts=at(DAY, "16:45", 2))
    before = run(chain, at(DAY, "16:44"))
    assert before.states[CHILD] is State.HALTED
    assert before.states[INCUMBENT] is State.CHALLENGER
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
    """Invalid-chain pin: ``validate`` refuses a RESUME while a pair is pending (7c). Were one
    written, it applies at its own instant, before the pair's LAUNCH, not by chain position."""
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
    to = State.SHADOW if kind is Kind.MINT else State.CHAMPION
    date_ = DAY if kind is Kind.ROOT_ADMIT else None
    chain.add(kind, to, family=INCUMBENT, effective_launch_date=date_)
    assert isinstance(fold(chain.rows, VENUE, LAUNCH), FoldResult)


@pytest.mark.parametrize(
    ("kind", "frm"),
    [
        (Kind.PROMOTE, State.CHALLENGER),
        (Kind.DRILL_PROMOTE, State.CHALLENGER),
        (Kind.ROLLBACK, State.CHALLENGER),
        (Kind.ROOT_ADMIT, None),
    ],
)
def test_head_without_launch_date_is_invalid(kind: Kind, frm: State | None) -> None:
    """A6b-R2 / E-16 (c): a ->CHAMPION head is always pending until LAUNCH."""
    chain = Chain()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT)
    if frm is not None:
        chain.add(Kind.MINT, State.SHADOW, family=CHILD)
        chain.add(Kind.PROMOTE, State.CHALLENGER, family=CHILD, frm=State.SHADOW)
    chain.add(kind, State.CHAMPION, family=CHILD, frm=frm)
    assert fold(chain.rows, VENUE, LAUNCH) == FoldInvalid(
        FoldInvalidReason.HEAD_MISSING_LAUNCH_DATE
    )


def test_immediate_rows_after_the_clock_are_not_applied() -> None:
    """LOW-4: a row written after ``now_ns`` has not happened yet."""
    chain = Chain()
    chain.add(Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT, ts=at(DAY, "10:00"))
    chain.add(Kind.DEMOTE, State.HALTED, family=INCUMBENT, frm=State.CHAMPION, ts=at(DAY, "11:00"))
    assert run(chain, at(DAY, "10:30")).states[INCUMBENT] is State.CHAMPION
    assert run(chain, at(DAY, "11:00")).states[INCUMBENT] is State.HALTED


def test_head_venue_seq_is_the_sealed_last_venue_seq() -> None:
    chain = Chain()
    chain.seed()
    sealed = [replace(r, venue_seq=r.venue_seq + 10) for r in chain.rows if r.venue_seq]
    assert fold(sealed, VENUE, LAUNCH).head_venue_seq == 13  # type: ignore[union-attr]


def test_fold_refuses_unsealed_rows() -> None:
    """LOW-5: ``head_venue_seq`` needs sealed rows; an unsealed last row raises ``ValueError``."""
    chain = Chain()
    chain.seed()
    unsealed = [*chain.rows[:-1], replace(chain.rows[-1], venue_seq=None)]
    with pytest.raises(ValueError, match="venue_seq"):
        fold(unsealed, VENUE, LAUNCH)


def test_activate_window_follows_the_pins_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    """The window is read from ``pins`` at call time: moving STOP and LAUNCH moves the window."""
    monkeypatch.setattr(pins, "SCHEDULE_STOP_UTC", "16:30")
    monkeypatch.setattr(pins, "SCHEDULE_LAUNCH_UTC", "16:55")
    chain, head, _tail = seeded_pair()
    chain.activate(head, ts=at(DAY, "16:35"))
    shifted = at(DAY, "16:55")
    assert run(chain, shifted - 1).pairs[0].status is PairStatus.PENDING
    assert run(chain, shifted).pairs[0].status is PairStatus.EFFECTIVE
    assert run(chain, shifted).pairs[0].launch_ns == shifted


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


def test_fold_module_imports_only_schemas_pins_and_its_tallies() -> None:
    """Seam 7d (A7d-R4) moved the pair handling and its ``pins`` reads to ``fold_pairs``."""
    assert _internal_imports("fold.py") == {"schemas", "fold_pairs", "fold_tallies"}
    assert _internal_imports("fold_pairs.py") == {"schemas", "pins"}


def test_fold_tallies_imports_only_schemas_and_the_wire_helpers() -> None:
    assert _internal_imports("fold_tallies.py") == {"schemas", "wire"}


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


def test_allowed_is_the_arch_plus_a4_r6_table_exactly() -> None:
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
    """``validate`` is the one added import: the sibling module ``transitions`` re-exports (7c)."""
    assert _internal_imports("transitions.py") == {"schemas", "fold", "validate"}


def test_validate_module_imports_only_pins_schemas_fold_and_verdict() -> None:
    """``validate`` must not import ``transitions`` (a cycle) or ``registry_shape`` (which does).

    Seam 7d adds ``validate_ii`` (its rules) and ``fold_tallies`` (the ``carried_counters`` shape).
    """
    assert _internal_imports("validate.py") == {
        "schemas", "pins", "fold", "verdict", "validate_ii", "fold_tallies",
    }  # fmt: skip
    # ``validate_ii`` holds the check context and never imports ``validate`` (an import cycle).
    assert _internal_imports("validate_ii.py") == {
        "schemas", "pins", "fold", "fold_tallies", "verdict",
    }  # fmt: skip


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


def test_a_nomination_is_admitted_at_an_empty_stage() -> None:
    """A6b-R1: SHADOW to CHALLENGER sends nothing, so no stage flag gates it."""
    chain = Chain()
    chain.add(Kind.PROMOTE, _CH, family=CHILD, frm=_S)
    assert rows_admissible(chain.rows, stage=_stage(set(), set())) == AdmissibilityResult(1, None)


def test_a_promotion_to_champion_is_gated_and_follows_the_nomination() -> None:
    chain = Chain()
    chain.add(Kind.PROMOTE, _CH, family=CHILD, frm=_S)
    chain.add(Kind.PROMOTE, _CP, family=CHILD, frm=_CH, effective_launch_date=DAY)
    result = rows_admissible(chain.rows, stage=_stage(set(), set()))
    assert result == AdmissibilityResult(1, RefusalReason.WIDENING_KIND_NOT_ENABLED)


def test_is_widening_row_decides_promote_by_target_state_only() -> None:
    chain = Chain()
    nomination = chain.add(Kind.PROMOTE, _CH, family=CHILD, frm=_S)
    promotion = chain.add(Kind.PROMOTE, _CP, family=CHILD, frm=_CH, effective_launch_date=DAY)
    admit = chain.add(Kind.DRILL_ADMIT, _CH, family=OTHER, frm=_S)
    assert not is_widening_row(nomination)
    assert is_widening_row(promotion)
    assert is_widening_row(admit)  # only PROMOTE is split by target state (A6b-R1)
    assert is_widening(Kind.PROMOTE)  # the kind set stays whole for the pins subset check


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


_STAGE_NAMES: Final = frozenset({
    "enabled_widening_kinds", "admission_implemented", "ENABLED_WIDENING_KINDS",
    "_ADMISSION_IMPLEMENTED", "rows_admissible", "is_widening_row", "WIDENING_KINDS", "StageView",
    "StagePolicy",
})  # fmt: skip


def _stage_names_in(source: str) -> set[str]:
    tree = ast.parse(source)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    return names & _STAGE_NAMES


@pytest.mark.parametrize("case", ["transitions", "fold"])
def test_admissibility_predicate_shared(case: str) -> None:
    """One predicate: ``rows_admissible`` equals an oracle; ``fold`` never compares stage sets."""
    if case == "fold":
        source = (AUTONOMY_DIR / "fold.py").read_text(encoding="utf-8")
        assert _stage_names_in(source) == set()
        for planted in (
            "def f(stage):\n    return stage.enabled_widening_kinds\n",
            "from breezy.persistence.autonomy.transitions import rows_admissible\n",
            "from breezy.persistence.autonomy.schemas import StagePolicy\n",
            "x = ENABLED_WIDENING_KINDS\n",
        ):
            assert _stage_names_in(planted), planted  # positive control
        return
    chain = Chain()
    chain.add(Kind.PROMOTE, _CH, family=CHILD, frm=_S)
    assert rows_admissible(chain.rows, stage=_stage(set(), set())).reason is None
    kinds = list(Kind)
    enabled = {Kind.RESUME, Kind.PROMOTE, Kind.ACTIVATE}
    implemented = {Kind.RESUME, Kind.ACTIVATE}
    for batch in itertools.permutations(kinds, 2):
        rows = _rows(*batch)
        expected: AdmissibilityResult = AdmissibilityResult(len(rows), None)
        for i, row in enumerate(rows):
            if row.kind not in EXPECTED_WIDENING or (
                row.kind is Kind.PROMOTE and row.to_state is not _CP
            ):
                continue
            if row.kind not in enabled:
                expected = AdmissibilityResult(i, RefusalReason.WIDENING_KIND_NOT_ENABLED)
            elif row.kind not in implemented:
                expected = AdmissibilityResult(i, RefusalReason.ADMISSION_PENDING)
            else:
                continue
            break
        assert rows_admissible(rows, stage=_stage(enabled, implemented)) == expected, batch
