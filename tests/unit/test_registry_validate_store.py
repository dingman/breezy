"""ARCH-0 seam 7c: the store-side ``validate`` rules (d0, trial prefix, the E-5 per-day cap).

The plan names these ``[store]`` tests because the store enforces them on append. Until seam 7d
wires ``validate`` into ``RegistryStore.append`` (ruling A6e-R2) they are pinned at ``validate``
itself, the function the store will call. The first →CHAMPION row of a family binds its manifest's
``d0_climate_day`` and ``trial_id_prefix`` (U1); ROLLBACK, RESUME and ROOT_ADMIT are exempt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import pytest

import breezy.persistence.autonomy.transitions as tm
from breezy.persistence.autonomy.schemas import (
    CauseCode,
    Kind,
    ManifestFacts,
    ManifestFactsReader,
    RefusalReason,
    State,
)
from tests.unit.test_registry_fold import CHILD, DAY, INCUMBENT, Chain, at, run
from tests.unit.test_registry_fold_effects import NEXT_DAY
from tests.unit.test_registry_fold_validate import (
    CHILD_MAN,
    DAY_NS,
    HOUR_NS,
    INC_ART,
    INC_MAN,
    RESTORE_TS,
    champion_chain,
    exhaust,
    failed_close_chain,
    probe,
    restore,
    rule_of,
)

if TYPE_CHECKING:
    from breezy.persistence.autonomy.validate import Refusal

KIND: Final = "forecast_quantile_ladder"
SECOND = "pm_us_crh_fq_v1_r0002"
SECOND_MAN: Final = "4" * 64
THIRD_DAY: Final = "2026-10-12"
NOW: Final = at(DAY, "16:00")


class Manifests:
    """A manifest reader over a table; other keys read as ``None``; ``banned`` is never read."""

    def __init__(self, banned: frozenset[str] = frozenset()) -> None:
        self.table: dict[tuple[str, str], ManifestFacts | None] = {}
        self.banned = banned
        self.reads: list[str] = []

    def add(
        self, family: str, sha: str, d0: str, *, prefix: str | None = None, kind: str = KIND
    ) -> None:
        self.table[(family, sha)] = ManifestFacts(
            family_id=family, manifest_sha256=sha, d0_climate_day=d0,
            trial_id_prefix=prefix or f"{kind}/trial/{family}/", composition_kind=kind,
        )  # fmt: skip

    def __call__(self, family_id: str, manifest_sha256: str) -> ManifestFacts | None:
        assert family_id not in self.banned, f"the d0 rule read {family_id}"
        self.reads.append(family_id)
        return self.table.get((family_id, manifest_sha256))


def nominated() -> Chain:
    chain = champion_chain()
    chain.add(Kind.PROMOTE, State.CHALLENGER, family=CHILD, frm=State.SHADOW)
    return chain


def first_promote(
    reader: ManifestFactsReader,
    *,
    kind: Kind = Kind.PROMOTE,
    day: str = DAY,
    sha: str | None = CHILD_MAN,
    chain: Chain | None = None,
    **extra: Any,
) -> Refusal | None:
    extra.setdefault("artefact_sha256", INC_ART)
    return probe(
        chain or nominated(), NOW, kind, State.CHAMPION, family=CHILD, frm=State.CHALLENGER,
        effective_launch_date=day, manifest_sha256=sha, manifests=reader, **extra,
    )  # fmt: skip


def reader_for(d0: str, **kwargs: Any) -> Manifests:
    reader = Manifests()
    reader.add(CHILD, CHILD_MAN, d0, **kwargs)
    return reader


@pytest.mark.parametrize("facet", ["store"])
def test_child_d0_and_trial_prefix_pinned(facet: str) -> None:
    assert facet == "store"
    for kind in (Kind.PROMOTE, Kind.DRILL_PROMOTE):
        assert first_promote(reader_for(DAY), kind=kind) is None  # d0 equal to the launch date
        assert first_promote(reader_for(NEXT_DAY), kind=kind) is None

        early = first_promote(reader_for("2026-10-09"), kind=kind)
        assert early is not None and (early.rule.value, early.reason) == (
            "first_champion_d0", RefusalReason.D0_BREACH,
        )  # fmt: skip

        for bad in (
            f"{KIND}/trial/{SECOND}/",  # another child's id
            f"other_kind/trial/{CHILD}/",  # another composition kind
            f"{KIND}/trial/{CHILD}",  # no trailing slash
        ):
            refused = first_promote(reader_for(DAY, prefix=bad), kind=kind)
            assert refused is not None and refused.reason is RefusalReason.TRIAL_PREFIX_MISMATCH


def test_first_champion_row_needs_readable_manifest_facts_for_its_own_sha() -> None:
    unreadable = first_promote(Manifests())
    assert unreadable is not None and unreadable.reason is RefusalReason.MANIFEST_UNREADABLE
    no_sha = first_promote(reader_for(DAY), sha=None)
    assert no_sha is not None and no_sha.reason is RefusalReason.MANIFEST_UNREADABLE

    mismatched = Manifests()
    mismatched.table[(CHILD, CHILD_MAN)] = ManifestFacts(
        family_id=INCUMBENT, manifest_sha256=CHILD_MAN, d0_climate_day=DAY,
        trial_id_prefix=f"{KIND}/trial/{INCUMBENT}/", composition_kind=KIND,
    )  # fmt: skip
    wrong_family = first_promote(mismatched)
    assert (
        wrong_family is not None and wrong_family.reason is RefusalReason.MANIFEST_IDENTITY_MISMATCH
    )


def second_child_chain() -> Chain:
    """CHILD took effect (SUPERSEDE of INCUMBENT at DAY 16:50); SECOND is a nominated sibling."""
    chain = nominated()
    head, _tail = chain.promote_pair(day=DAY)
    chain.activate(head, ts=at(DAY, "16:45"))
    chain.add(Kind.MINT, State.SHADOW, family=SECOND, manifest_sha256=SECOND_MAN)
    chain.add(Kind.PROMOTE, State.CHALLENGER, family=SECOND, frm=State.SHADOW)
    return chain


def second_promote(reader: Manifests, *, day: str = THIRD_DAY) -> Refusal | None:
    return probe(
        second_child_chain(), at(DAY, "18:00"), Kind.PROMOTE, State.CHAMPION, family=SECOND,
        frm=State.CHALLENGER, effective_launch_date=day, manifest_sha256=SECOND_MAN,
        manifests=reader,
    )  # fmt: skip


def test_d0_must_exceed_every_earlier_child_d0_in_the_lineage() -> None:
    def reader(second_d0: str, earlier_d0: str) -> Manifests:
        facts = Manifests(banned=frozenset({INCUMBENT}))  # a root's committed d0 is never read
        facts.add(SECOND, SECOND_MAN, second_d0)
        facts.add(CHILD, CHILD_MAN, earlier_d0)
        return facts

    assert second_promote(reader("2026-10-13", NEXT_DAY)) is None
    equal = second_promote(reader(THIRD_DAY, THIRD_DAY))
    assert equal is not None and (equal.rule.value, equal.reason) == (
        "first_champion_d0", RefusalReason.D0_BREACH,
    )  # fmt: skip
    below = second_promote(reader(THIRD_DAY, "2026-10-13"))
    assert below is not None and below.reason is RefusalReason.D0_BREACH

    unreadable = Manifests(banned=frozenset({INCUMBENT}))
    unreadable.add(SECOND, SECOND_MAN, THIRD_DAY)  # the earlier child's facts cannot be read
    refused = second_promote(unreadable)
    assert refused is not None and refused.reason is RefusalReason.MANIFEST_UNREADABLE


def test_d0_rule_ignores_an_earlier_child_that_never_took_effect() -> None:
    chain = nominated()  # CHILD was nominated only: never CHAMPION
    chain.add(Kind.MINT, State.SHADOW, family=SECOND, manifest_sha256=SECOND_MAN)
    chain.add(Kind.PROMOTE, State.CHALLENGER, family=SECOND, frm=State.SHADOW)
    reader = Manifests(banned=frozenset({CHILD}))
    reader.add(SECOND, SECOND_MAN, THIRD_DAY)

    refused = probe(
        chain, NOW, Kind.PROMOTE, State.CHAMPION, family=SECOND, frm=State.CHALLENGER,
        effective_launch_date=THIRD_DAY, manifest_sha256=SECOND_MAN, manifests=reader,
    )  # fmt: skip

    assert refused is None


def test_root_admit_exempt_from_d0_rule() -> None:
    chain = Chain()
    never = Manifests(banned=frozenset({INCUMBENT, CHILD, SECOND}))

    refused = probe(
        chain, NOW, Kind.ROOT_ADMIT, State.CHAMPION, family=INCUMBENT, frm=None,
        effective_launch_date=DAY, manifest_sha256=INC_MAN, manifests=never,
    )  # fmt: skip

    assert refused is None
    assert never.reads == []


def test_rollback_and_a_repeat_promote_of_a_former_champion_are_exempt() -> None:
    chain = champion_chain()  # INCUMBENT has been CHAMPION since its BOOTSTRAP
    never = Manifests(banned=frozenset({INCUMBENT, CHILD}))
    rollback = probe(
        chain, NOW, Kind.ROLLBACK, State.CHAMPION, family=INCUMBENT, frm=State.CHALLENGER,
        effective_launch_date=DAY, manifest_sha256=INC_MAN, manifests=never,
    )  # fmt: skip
    repromote = probe(
        chain, NOW, Kind.PROMOTE, State.CHAMPION, family=INCUMBENT, frm=State.CHALLENGER,
        effective_launch_date=DAY, manifest_sha256=INC_MAN, manifests=never,
    )  # fmt: skip

    assert (rollback, repromote) == (None, None)


def test_a_restorative_resume_is_exempt_from_the_d0_rule() -> None:
    assert restore(failed_close_chain()) is None  # ``restore`` reads no manifest facts at all


# --- E-5 per-venue per-day cap and the drill child --------------------------------------------


def test_drill_close_restore_at_most_one_per_venue_per_day() -> None:
    day_ago = RESTORE_TS - DAY_NS  # exactly one day: no longer counted

    def with_restores(*instants: int) -> Refusal | None:
        chain = failed_close_chain()
        exhaust(chain, drill_close_restores=instants)
        return restore(chain)

    refused = with_restores(RESTORE_TS - HOUR_NS)
    assert refused is not None and (refused.rule.value, refused.reason) == (
        "restore_daily_cap", RefusalReason.ENGINE_INCONSISTENCY,
    )  # fmt: skip
    assert with_restores(day_ago + 1) is not None
    assert with_restores(day_ago) is None
    assert with_restores() is None


def test_a_second_restore_in_one_batch_is_refused() -> None:
    chain = failed_close_chain()
    prior = run(chain, RESTORE_TS)
    rows = [
        chain.add(
            Kind.RESUME,
            State.CHAMPION,
            family=INCUMBENT,
            frm=State.HALTED,
            ts=RESTORE_TS,
            cause_code=CauseCode.DRILL_CLOSE_RESTORE,
            manifest_sha256=INC_MAN,
            artefact_sha256=INC_ART,
        )
        for _ in range(2)
    ]

    refused = tm.first_refusal(prior, rows, manifests=Manifests())

    assert refused is not None and (refused.rule.value, refused.row_index) == (
        "restore_daily_cap",
        1,
    )


def test_drill_close_restore_refused_for_drill_child() -> None:
    chain = failed_close_chain(drill_halt_child=True)
    assert run(chain, RESTORE_TS).families[CHILD].drill_child

    refused = restore(chain, family=CHILD, manifest_sha256=CHILD_MAN, artefact_sha256=INC_ART)

    assert rule_of(refused) == "restore_drill_child"
