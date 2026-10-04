"""ARCH-0 seam 7d: ``RegistryStore.append`` runs ``transitions.validate`` (AC 10 step 9; A6e-R2).

The store hands ``validate`` the fold of the rows already written and its bound manifest reader,
and a refusal rolls the whole batch back with the closed reason. Row builders come from
``test_registry_store``; the BOOTSTRAP and MINT rules are exercised through a real store here, the
rule-level cases are in ``test_registry_validate_ii``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import breezy.persistence.autonomy.registry_store as rs
from breezy.persistence.autonomy import pins, transitions
from breezy.persistence.autonomy.fold import FoldResult
from breezy.persistence.autonomy.paths import AutonomyPaths
from breezy.persistence.autonomy.registry_store import RegistryStore, ValidateRefused
from breezy.persistence.autonomy.schemas import (
    Kind,
    ManifestFacts,
    RefusalReason,
    State,
    WriterMode,
)
from tests.unit.test_registry_store import (
    CHILD,
    COMPOSITION,
    FAMILY,
    NOW,
    OPEN_STAGE,
    OTHER_VENUE,
    SEC,
    SHA_A,
    drill_child_store,
    mk,
    pair_rows,
    seed_retired,
    stored,
)

HOUR = 3_600 * SEC
SEED_FAMILIES = tuple(name for name, _state in pins.BOOTSTRAP_SEED)


@pytest.fixture
def store(tmp_path: Path) -> RegistryStore:
    root = tmp_path / "data"
    root.mkdir(mode=0o700)
    return RegistryStore.initialise(AutonomyPaths(root), repo_root=tmp_path / "repo")


def genesis(*, venue: str = "polymarket_us") -> list[Any]:
    """The whole seed in one genesis batch: fq_v1 CHAMPION, the other three RETIRED."""
    return [
        mk(
            Kind.BOOTSTRAP, State[state], family=name, venue=venue, ts=NOW,
            artefact_sha256=SHA_A if state == "CHAMPION" else None,
        )
        for name, state in pins.BOOTSTRAP_SEED
    ]  # fmt: skip


def put(store: RegistryStore, rows: list[Any], *, seq: int = 0, mode: WriterMode) -> Any:
    return store.append(rows, expected_prior_seq=seq, mode=mode, now_ns=rows[-1].ts_ns)


# --- E-6: BOOTSTRAP is the seed's genesis and nothing else --------------------------------------


def test_bootstrap_seed_genesis_only(store: RegistryStore) -> None:
    rows = genesis()
    assert len(rows) == len(SEED_FAMILIES) == 4
    result = put(store, rows, mode=WriterMode.BOOTSTRAP)
    assert [r.family_id for r in result.rows] == list(SEED_FAMILIES)
    assert result.head_venue_seq == 4


@pytest.mark.parametrize(
    ("family", "to", "why"),
    [
        ("pm_us_crh_v9", State.RETIRED, "a family outside the seed"),
        (FAMILY, State.RETIRED, "a seed family in a state other than its seed state"),
        ("pm_us_crh_v4", State.CHAMPION, "a RETIRED seed family as CHAMPION"),
        (FAMILY, State.SHADOW, "no BOOTSTRAP root: ROOT_ADMIT introduces roots"),
    ],
)
def test_bootstrap_outside_the_seed_is_refused_and_writes_nothing(
    store: RegistryStore, family: str, to: State, why: str
) -> None:
    row = mk(Kind.BOOTSTRAP, to, family=family)
    with pytest.raises(ValidateRefused) as info:
        put(store, [row], mode=WriterMode.BOOTSTRAP)
    assert info.value.reason is RefusalReason.ENGINE_INCONSISTENCY, why
    assert stored(store) == []


def test_store_refuses_second_bootstrap_per_venue(store: RegistryStore) -> None:
    put(
        store,
        [mk(Kind.BOOTSTRAP, State.CHAMPION, artefact_sha256=SHA_A)],
        mode=WriterMode.BOOTSTRAP,
    )
    later = seed_retired(expected=1, ts=NOW + SEC)  # a real seed family, but the chain is not empty
    with pytest.raises(ValidateRefused):
        put(store, [later], seq=1, mode=WriterMode.BOOTSTRAP)
    assert len(stored(store)) == 1

    other = mk(Kind.BOOTSTRAP, State.CHAMPION, venue=OTHER_VENUE)  # each venue has its own genesis
    assert put(store, [other], mode=WriterMode.BOOTSTRAP).head_venue_seq == 1


# --- Z3: one MINT per lineage per day -----------------------------------------------------------


def test_store_refuses_a_second_counted_mint_in_a_day(store: RegistryStore) -> None:
    put(
        store,
        [mk(Kind.BOOTSTRAP, State.CHAMPION, artefact_sha256=SHA_A)],
        mode=WriterMode.BOOTSTRAP,
    )

    def counted(family: str, art: str, seq: int, ts: int) -> Any:
        return mk(Kind.MINT, State.SHADOW, family=family, expected=seq, ts=ts, artefact_sha256=art)

    first = counted(CHILD, "1" * 64, 1, NOW + SEC)
    assert put(store, [first], seq=1, mode=WriterMode.DAILY).head_venue_seq == 2
    second = counted("pm_us_crh_two", "2" * 64, 2, NOW + 2 * SEC)
    with pytest.raises(ValidateRefused):
        put(store, [second], seq=2, mode=WriterMode.DAILY)
    assert len(stored(store)) == 2

    drill = counted("pm_us_crh_drill", SHA_A, 2, NOW + 3 * SEC)  # a no-new-lineage MINT: free
    assert put(store, [drill], seq=2, mode=WriterMode.DAILY).head_venue_seq == 3
    next_day = counted("pm_us_crh_three", "3" * 64, 3, NOW + SEC + 24 * HOUR)
    assert put(store, [next_day], seq=3, mode=WriterMode.DAILY).head_venue_seq == 4


# --- the wiring ---------------------------------------------------------------------------------


def test_append_hands_validate_the_fold_of_the_prior_rows_and_its_bound_reader(
    store: RegistryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    put(
        store,
        [mk(Kind.BOOTSTRAP, State.CHAMPION, artefact_sha256=SHA_A)],
        mode=WriterMode.BOOTSTRAP,
    )
    seen: list[tuple[FoldResult, list[Any], dict[str, Any]]] = []
    real = transitions.validate

    def spy(prior: FoldResult, rows: Any, **kwargs: Any) -> Any:
        seen.append((prior, list(rows), kwargs))
        return real(prior, rows, **kwargs)

    monkeypatch.setattr(transitions, "validate", spy)
    row = mk(Kind.MINT, State.SHADOW, family=CHILD, expected=1, ts=NOW + SEC)
    put(store, [row], seq=1, mode=WriterMode.DAILY)

    ((prior, rows, kwargs),) = seen
    assert prior.head_venue_seq == 1 and prior.states == {FAMILY: State.CHAMPION}
    assert [r.transition_id for r in rows] == [row.transition_id]
    assert kwargs["mode"] is WriterMode.DAILY and kwargs["now_ns"] == NOW + SEC
    assert kwargs["manifests"] is store._manifests and kwargs["stage"] is not None


def test_a_validate_refusal_rolls_the_batch_back_with_validates_closed_reason(
    store: RegistryStore,
) -> None:
    """A first →CHAMPION row whose manifest prefix is wrong: ``trial_prefix_mismatch``."""

    def wrong_prefix(family_id: str, manifest_sha256: str) -> ManifestFacts:
        return ManifestFacts(
            family_id=family_id, manifest_sha256=manifest_sha256, d0_climate_day="2026-12-01",
            trial_id_prefix=f"{COMPOSITION}/trial/somebody_else/", composition_kind=COMPOSITION,
        )  # fmt: skip

    drill_child_store(store, with_pair=False)  # FAMILY CHAMPION; CHILD a drill-admitted CHALLENGER
    store._manifests = wrong_prefix
    head, tail = pair_rows()
    with pytest.raises(ValidateRefused) as info:
        store._append(
            [head, tail], expected_prior_seq=3, mode=WriterMode.DAILY, now_ns=tail.ts_ns,
            stage=OPEN_STAGE, _fixture_stage=True,
        )  # fmt: skip
    assert info.value.reason is RefusalReason.TRIAL_PREFIX_MISMATCH
    assert isinstance(info.value, rs.RegistryRefused)
    assert len(stored(store)) == 3  # both rows rolled back

    store._manifests = _facts_ok
    result = store._append(
        [head, tail], expected_prior_seq=3, mode=WriterMode.DAILY, now_ns=tail.ts_ns,
        stage=OPEN_STAGE, _fixture_stage=True,
    )  # fmt: skip
    assert result.head_venue_seq == 5  # the same rows with a readable, matching manifest: written


def _facts_ok(family_id: str, manifest_sha256: str) -> ManifestFacts:
    return ManifestFacts(
        family_id=family_id, manifest_sha256=manifest_sha256, d0_climate_day="2026-12-01",
        trial_id_prefix=f"{COMPOSITION}/trial/{family_id}/", composition_kind=COMPOSITION,
    )  # fmt: skip


def test_a_stale_writer_sees_cas_mismatch_before_validate(
    store: RegistryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E-17 d: CAS (and so the retry path) comes before the semantic rules."""
    put(
        store,
        [mk(Kind.BOOTSTRAP, State.CHAMPION, artefact_sha256=SHA_A)],
        mode=WriterMode.BOOTSTRAP,
    )

    def never(*_a: object, **_k: object) -> Any:
        raise AssertionError("validate ran before the CAS check")

    monkeypatch.setattr(transitions, "validate", never)
    stale = mk(Kind.MINT, State.SHADOW, family=CHILD, expected=0, ts=NOW + SEC)
    with pytest.raises(rs.CasMismatch):
        put(store, [stale], seq=0, mode=WriterMode.DAILY)


def test_a_replay_is_a_logged_no_op_that_validate_never_judges(
    store: RegistryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E-17 a: rows already stored are replayed by body; the rules do not run again."""
    row = mk(Kind.BOOTSTRAP, State.CHAMPION, artefact_sha256=SHA_A)
    put(store, [row], mode=WriterMode.BOOTSTRAP)

    def never(*_a: object, **_k: object) -> Any:
        raise AssertionError("a replay must not be judged again")

    monkeypatch.setattr(transitions, "validate", never)
    again = put(store, [row], mode=WriterMode.BOOTSTRAP)
    assert again.replayed is True
    assert len(stored(store)) == 1
