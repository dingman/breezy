"""ARCH-0 seam 8b review (A8b-R3, A8b-R4): store/replay parity and replay timing.

The store folds the rows already written at the batch's first ``ts_ns`` (the stamp), never at the
caller's clock, so that what it accepted is exactly what the replay accepts: a row stamped
16:49:59 and committed after the 16:50 LAUNCH is judged against a pair that had not yet taken
effect, in the store and in the replay alike.
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

import pytest

from breezy.persistence.autonomy import pins
from breezy.persistence.autonomy import registry_shape as shape
from breezy.persistence.autonomy.chain import VerifiedVenueChain, verify_venue_chain
from breezy.persistence.autonomy.registry_store import RegistryStore, ValidateRefused
from breezy.persistence.autonomy.replay import ReplayInvalid, ReplayOk, replay_full
from breezy.persistence.autonomy.schemas import (
    CauseClass,
    CauseCode,
    Kind,
    State,
    TransitionRow,
    WriterMode,
)
from breezy.persistence.autonomy.transitions import KIND_MASK
from tests.unit.test_registry_fold import CHILD, DAY, INCUMBENT, SEC, VENUE, Chain, at
from tests.unit.test_registry_replay import (
    ART_SHA,
    World,
    seal,
    start,
)
from tests.unit.test_registry_replay_roles import drill_episode
from tests.unit.test_registry_store import OPEN_STAGE

HOUR_NS: Final = 3_600 * SEC
_MODES: Final = (WriterMode.DAILY, WriterMode.PRELAUNCH, WriterMode.BOOTSTRAP)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def batches(rows: Sequence[TransitionRow]) -> list[list[TransitionRow]]:
    """Group rows as the store appended them: a dated head with the partners that cite it."""
    out: list[list[TransitionRow]] = []
    for row in rows:
        head = out[-1][0] if out else None
        if (
            head is not None
            and row.kind in (Kind.SUPERSEDE, Kind.DISPLACED)
            and row.paired_transition_id == head.transition_id
        ):
            out[-1].append(row)
        else:
            out.append([row])
    return out


def shaped(chain: Chain) -> Chain:
    """Name the lineage root on every row whose shape requires it (the builder only does roots)."""
    chain.rows[:] = [
        dataclasses.replace(r, lineage_root_family_id=INCUMBENT)
        if r.kind in shape.LINEAGE_REQUIRED and r.lineage_root_family_id is None
        else r
        for r in chain.rows
    ]
    return chain


def unsealed(row: TransitionRow, expected: int) -> TransitionRow:
    return dataclasses.replace(
        row, seq=None, venue_seq=None, expected_prior_seq=expected,
        prev_transition_hash=None, transition_hash=None,
    )  # fmt: skip


def through_store(
    world: World, chain: Chain, *, delay_ns: int = 0
) -> tuple[list[TransitionRow], str | None]:
    """Append each batch; the rows stored, and the rule of the first refusal (``None``: none)."""
    (world.data / "registry").chmod(0o700)  # the world made it for the child manifest copy
    shaped(chain)
    store = RegistryStore.initialise(world.paths, repo_root=world.repo)
    stored: list[TransitionRow] = []
    for batch in batches(chain.rows):
        mode = next(m for m in _MODES if {r.kind for r in batch} <= KIND_MASK[m])
        try:
            result = store._append(
                [unsealed(r, len(stored)) for r in batch],
                expected_prior_seq=len(stored), mode=mode, now_ns=batch[-1].ts_ns + delay_ns,
                stage=OPEN_STAGE, _fixture_stage=True,
            )  # fmt: skip
        except ValidateRefused as refused:
            return stored, refused.rule.value
        stored.extend(result.rows)
    return stored, None


def replay_rule(world: World, chain: Chain) -> str | None:
    result = replay_full(seal(shaped(chain)), paths=world.paths, repo_root=world.repo)
    if isinstance(result, ReplayOk):
        return None
    assert isinstance(result, ReplayInvalid), result
    return result.rule


def test_a_multi_row_transaction_is_accepted_by_the_store_and_the_replay(world: World) -> None:
    chain = drill_episode(world)  # two pairs: each head with its partner in one transaction
    stored, refused = through_store(world, chain)
    assert refused is None and len(stored) == len(chain.rows)
    verified: VerifiedVenueChain = verify_venue_chain(stored, VENUE)
    assert isinstance(replay_full(verified, paths=world.paths, repo_root=world.repo), ReplayOk)
    assert replay_rule(world, chain) is None


def late_demote(world: World) -> Chain:
    """CHILD's pair is ACTIVATEd for DAY; a DEMOTE of CHILD is stamped 16:49:59, before LAUNCH."""
    chain = drill_episode(world, close=False)
    chain.add(
        Kind.DEMOTE, State.HALTED, family=CHILD, frm=State.CHAMPION, ts=at(DAY, "16:49", 59 * SEC),
        halt_cause_class=CauseClass.RECOVERABLE_MODEL, cause_code=CauseCode.VERDICT_FAIL,
    )  # fmt: skip
    return chain


def test_a_row_stamped_before_launch_and_committed_after_is_judged_at_its_stamp(
    world: World,
) -> None:
    """At 16:49:59 CHILD is still CHALLENGER (the pair is pending); a commit at 16:50:30 must
    not see it as CHAMPION. The store and the replay refuse the same row for the same rule."""
    chain = late_demote(world)
    stored, store_rule = through_store(world, chain, delay_ns=31 * SEC)
    assert store_rule == "from_state_mismatch"
    assert len(stored) == len(chain.rows) - 1  # everything before the late row was accepted
    assert replay_rule(world, chain) == store_rule


def test_the_same_row_stamped_after_launch_is_accepted_by_both(world: World) -> None:
    chain = drill_episode(world, close=False)
    chain.add(
        Kind.DEMOTE, State.HALTED, family=CHILD, frm=State.CHAMPION, ts=at(DAY, "17:05"),
        halt_cause_class=CauseClass.RECOVERABLE_MODEL, cause_code=CauseCode.VERDICT_FAIL,
    )  # fmt: skip
    stored, store_rule = through_store(world, chain)
    assert store_rule is None and len(stored) == len(chain.rows)
    assert replay_rule(world, chain) is None


# --- A8b-R4 ------------------------------------------------------------------------------------

ROWS: Final = 2_000
#: Measured on this host: 1.27 s for ``ROWS`` rows (printed by the test); the bound is about 3x.
TIMING_BOUND_S: Final = 4.0


def year_chain(world: World) -> Chain:
    """A root CHAMPION and ``ROWS - 1`` ATTESTs at the cadence: about one year of rows."""
    chain = Chain()
    chain.add(
        Kind.BOOTSTRAP, State.CHAMPION, family=INCUMBENT,
        manifest_sha256=world.root_sha, artefact_sha256=ART_SHA,
    )  # fmt: skip
    ts = at(DAY, "00:00")
    for _ in range(ROWS - 1):
        ts += pins.ATTEST_PERIOD_H * HOUR_NS
        chain.add(
            Kind.ATTEST, State.CHAMPION, family=INCUMBENT, frm=State.CHAMPION, ts=ts,
            attest_valid_until_ns=ts + pins.ATTEST_VERDICT_VALIDITY_H * HOUR_NS,
        )  # fmt: skip
    return chain


def test_replay_of_a_year_of_rows_completes_within_the_pinned_bound(world: World) -> None:
    chain = year_chain(world)
    sealed = seal(chain)
    assert sealed.head_venue_seq == ROWS
    started = time.monotonic()
    result: Any = replay_full(sealed, paths=world.paths, repo_root=world.repo)
    elapsed = time.monotonic() - started
    assert isinstance(result, ReplayOk), result
    print(f"replay of {ROWS} rows: {elapsed:.2f}s")
    assert elapsed < TIMING_BOUND_S


def test_the_store_reads_a_root_manifest_repo_only(world: World) -> None:
    """A8b-R5 L4: after an append the store's reader refuses a registry copy of a root."""
    (world.data / "registry").chmod(0o700)
    store = RegistryStore.initialise(world.paths, repo_root=world.repo)
    root = unsealed(start(world).rows[0], 0)
    store._append(
        [root], expected_prior_seq=0, mode=WriterMode.BOOTSTRAP, now_ns=root.ts_ns,
        stage=OPEN_STAGE, _fixture_stage=True,
    )  # fmt: skip
    assert INCUMBENT in store._roots
    copy = world.data / "registry" / "families" / f"{INCUMBENT}.json"
    copy.write_bytes(world.root_raw)
    copy.chmod(0o444)
    assert store._manifests(INCUMBENT, world.root_sha) is not None  # the repo file serves
    (world.repo / "deploy" / "families" / f"{INCUMBENT}.json").unlink()
    assert store._manifests(INCUMBENT, world.root_sha) is None  # a root has no registry copy
    assert store._manifests(CHILD, world.child_sha) is not None  # a child does
