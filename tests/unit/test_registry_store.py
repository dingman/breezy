"""ARCH-0 seam 6e: ``registry_store`` (DDL, append-only triggers, writer, ``append``/``_append``).

Reader, exports and ``newest_export`` are seam 6f. ``test_family_artefact_binding_immutable`` is
not here: its subject is unspecified and its code (a ``validate`` rule) lands in seams 7c and 7d, so
the placement STOP rule applies (reported to the coordinator).

The store's manifest reader is a fixture here (E-24: each introducing row's manifest pins that
row's artefact). The repo-only and roots behaviour of the real reader is proven by the replay and
parity tests, not by this file.
"""

from __future__ import annotations

import ast
import logging
import os
import sqlite3
import stat
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest

import breezy.persistence.autonomy.registry_shape as shape
import breezy.persistence.autonomy.registry_store as rs
from breezy.persistence.autonomy import chain, pins, stage_policy, transitions
from breezy.persistence.autonomy.chain import verify_venue_chain
from breezy.persistence.autonomy.paths import AutonomyPaths, ShadowPaths
from breezy.persistence.autonomy.registry_store import (
    AdmissionPending,
    CasMismatch,
    ClockRefused,
    KindRefused,
    ModeNotConcrete,
    NominationRequiresPolicy,
    PartialReplay,
    RegistryRefused,
    RegistryStore,
    RowRefused,
    RuleSetPending,
    StageNotCanonical,
    StoreUnavailable,
    WideningNotEnabled,
    check_row_shape,
)
from breezy.persistence.autonomy.schemas import (
    AdmissibilityResult,
    CauseClass,
    CauseCode,
    DecidedBy,
    FoldInvalidReason,
    Kind,
    ManifestFacts,
    RefusalReason,
    StagePolicy,
    State,
    TransitionRow,
    WriterMode,
)
from breezy.persistence.autonomy.wire import WireRefusalReason, WireRefused
from tests.support.autonomy_policy_scan import find_predicate_reads
from tests.support.entry_points import SRC_DIR
from tests.unit.registry_manifest_density import (
    default_manifest,
    density_facts,
    density_of,
    introducer_columns,
)

VENUE = "polymarket_us"
OTHER_VENUE = "kalshi"
FAMILY = "pm_us_crh_fq_v1"
CHILD = "pm_us_crh_child"
SEC = 10**9
NOW = 1_790_000_000 * SEC
LAUNCH_DAY = "2026-12-01"
SHA_B = "b" * 64
SHA_P = "c" * 64
INVOCATION = "00000000-0000-4000-8000-000000000001"
MODULE_PATH: Final = SRC_DIR / "breezy" / "persistence" / "autonomy" / "registry_store.py"
OPEN_STAGE = StagePolicy(
    enabled_widening_kinds=frozenset(Kind), admission_implemented=frozenset(Kind)
)

_LINEAGE = shape.LINEAGE_REQUIRED
_PAIR_CITING = shape.PAIR_CITING


@pytest.fixture(autouse=True)
def _manifests_pin_their_rows_artefact(monkeypatch: pytest.MonkeyPatch) -> None:
    """The store reads a manifest at every BOOTSTRAP and MINT (E-24); here a row's manifest is a
    registered fixture whose density pin is that row's artefact."""

    def reader(family_id: str, manifest_sha256: str, **_bound: object) -> ManifestFacts | None:
        return density_facts(family_id, manifest_sha256, d0=LAUNCH_DAY, composition=COMPOSITION)

    monkeypatch.setattr(rs, "read_manifest_facts", reader)


def fill(kind: Kind, frm: State | None, to: State) -> dict[str, Any]:
    """The kind-specific columns that make a ``(kind, frm, to)`` row shape-valid."""
    extra: dict[str, Any] = {}
    if kind in _LINEAGE:
        extra["lineage_root_family_id"] = FAMILY
    if kind in _PAIR_CITING:
        extra["paired_transition_id"] = SHA_P
    if kind is Kind.ATTEST:
        extra["attest_valid_until_ns"] = NOW + SEC
    if kind is Kind.SWAP_CANCEL:
        extra["voids_transition_ids"] = (SHA_P,)
    if kind is Kind.HWM_RESET:
        extra.update(hwm_from=0, hwm_to=1, carried_counters="{}")
    if kind is Kind.PROMOTE and frm is State.SHADOW and to is State.CHALLENGER:
        extra.update(
            k_life=1, alpha_k=Decimal("0.01"), n_min_eff=10, n_cap=20, nomination_feasible=True
        )
    return extra


def mk(
    kind: Kind,
    to: State,
    *,
    frm: State | None = None,
    family: str = FAMILY,
    fps: int = 0,
    ts: int = NOW,
    expected: int = 0,
    venue: str = VENUE,
    **over: Any,
) -> TransitionRow:
    base: dict[str, Any] = {
        "venue": venue,
        "family_id": family,
        "family_prior_seq": fps,
        "from_state": frm,
        "to_state": to,
        "kind": kind,
        "transition_id": "a" * 64,
        "decided_by": DecidedBy.ENGINE,
        "invocation_id": INVOCATION,
        "engine_code_sha": SHA_B,
        "expected_prior_seq": expected,
        "ts_ns": ts,
        **fill(kind, frm, to),
    }
    if kind in (Kind.BOOTSTRAP, Kind.ROOT_ADMIT):
        base["lineage_root_family_id"] = family  # a root names itself (E-14; fold 7b)
    base.update(over)
    if kind in (
        Kind.BOOTSTRAP,
        Kind.ROOT_ADMIT,
        Kind.MINT,
    ):  # E-24: the manifest pins the row's artefact
        base.update(introducer_columns(family, base))
    draft = TransitionRow(**base)
    return replace(draft, transition_id=draft.computed_transition_id())


def bootstrap(family: str = FAMILY, *, expected: int = 0, ts: int = NOW, venue: str = VENUE) -> Any:
    return mk(Kind.BOOTSTRAP, State.CHAMPION, family=family, expected=expected, ts=ts, venue=venue)


def demote(*, fps: int = 1, expected: int = 1, ts: int = NOW + SEC) -> TransitionRow:
    return mk(Kind.DEMOTE, State.HALTED, frm=State.CHAMPION, fps=fps, expected=expected, ts=ts)


def with_columns(row: TransitionRow, **columns: Any) -> TransitionRow:
    return replace(row, **columns)


def demote_with(**columns: Any) -> TransitionRow:
    return with_columns_id(demote(), **columns)


def with_columns_id(row: TransitionRow, **columns: Any) -> TransitionRow:
    changed = replace(row, **columns)
    return replace(changed, transition_id=changed.computed_transition_id())


@pytest.fixture
def store(tmp_path: Path) -> RegistryStore:
    root = tmp_path / "data"
    root.mkdir(mode=0o700)
    return RegistryStore.initialise(AutonomyPaths(root), repo_root=tmp_path / "repo")


def put_bootstrap(store: RegistryStore, **kw: Any) -> rs.AppendResult:
    return store.append(
        [bootstrap(**kw)], expected_prior_seq=kw.get("expected", 0), mode=WriterMode.BOOTSTRAP,
        now_ns=NOW,
    )  # fmt: skip


SHA_A = "d" * 64


def seed_retired(
    family: str = "pm_us_crh_v4", *, expected: int = 0, ts: int = NOW
) -> TransitionRow:
    """A BOOTSTRAP seed row that is RETIRED: a second genesis row that adds no sender (E-6, 7d)."""
    return mk(Kind.BOOTSTRAP, State.RETIRED, family=family, expected=expected, ts=ts)


def child_row(
    kind: Kind, frm: State | None, to: State, *, fps: int, seq: int, **over: Any
) -> TransitionRow:
    """CHILD's row at chain position ``seq + 1`` (``seq`` rows are stored), bound to ``SHA_A``."""
    return mk(
        kind, to, frm=frm, family=CHILD, fps=fps, expected=seq, ts=NOW + seq * SEC,
        artefact_sha256=SHA_A, **over,
    )  # fmt: skip


COMPOSITION = "forecast_quantile_ladder"


def pair_rows() -> tuple[TransitionRow, TransitionRow]:
    """A pending drill pair: CHILD's DRILL_PROMOTE head (seq 4) and FAMILY's SUPERSEDE (seq 5)."""
    head = child_row(
        Kind.DRILL_PROMOTE, State.CHALLENGER, State.CHAMPION, fps=3, seq=3,
        effective_launch_date=LAUNCH_DAY, drill=True,
        manifest_sha256=default_manifest(CHILD, SHA_A),
    )  # fmt: skip
    tail = mk(
        Kind.SUPERSEDE, State.CHALLENGER, frm=State.CHAMPION, fps=1, expected=3, ts=NOW + 3 * SEC,
        paired_transition_id=head.transition_id, effective_launch_date=LAUNCH_DAY,
    )  # fmt: skip
    return head, tail


def _facts(family_id: str, manifest_sha256: str) -> ManifestFacts:
    return ManifestFacts(
        family_id=family_id, manifest_sha256=manifest_sha256, d0_climate_day=LAUNCH_DAY,
        trial_id_prefix=f"{COMPOSITION}/trial/{family_id}/", composition_kind=COMPOSITION,
        density_artefact_sha256=density_of(manifest_sha256),
    )  # fmt: skip


def drill_child_store(store: RegistryStore, *, with_pair: bool = True) -> None:
    """FAMILY CHAMPION; CHILD drill-admitted (CHALLENGER); optionally a pending DRILL_PROMOTE pair.

    No shipped-stage write can make a CHALLENGER or a pair (nominations, DRILL_ADMIT and the pair
    kinds are not admitted), so the fixture opens the stage for its own setup rows only; the
    writes the tests make afterwards use the shipped stage. Three rows without the pair, five with.
    """
    store._manifests = _facts
    boot = mk(Kind.BOOTSTRAP, State.CHAMPION, artefact_sha256=SHA_A)
    store.append([boot], expected_prior_seq=0, mode=WriterMode.BOOTSTRAP, now_ns=NOW)
    head, tail = pair_rows()
    batches = [
        [child_row(Kind.MINT, None, State.SHADOW, fps=0, seq=1)],
        [child_row(Kind.DRILL_ADMIT, State.SHADOW, State.CHALLENGER, fps=2, seq=2)],
    ]
    if with_pair:
        batches.append([head, tail])
    for seq, batch in enumerate(batches, start=1):
        store._append(
            batch, expected_prior_seq=min(3, seq), mode=WriterMode.DAILY,
            now_ns=batch[-1].ts_ns, stage=OPEN_STAGE, _fixture_stage=True,
        )  # fmt: skip


def raw(store: RegistryStore) -> sqlite3.Connection:
    return sqlite3.connect(store._db)


def stored(store: RegistryStore) -> list[tuple[Any, ...]]:
    conn = raw(store)
    try:
        return conn.execute(
            "SELECT seq, venue, venue_seq, kind FROM transitions ORDER BY seq"
        ).fetchall()
    finally:
        conn.close()


def sealed_copy(store: RegistryStore, **over: Any) -> TransitionRow:
    """The first stored row, re-labelled; raw-insert material for trigger tests."""
    conn = raw(store)
    try:
        record = conn.execute(rs._SELECT_ROWS + " ORDER BY seq LIMIT 1").fetchone()
    finally:
        conn.close()
    return replace(rs._from_db(record), seq=None, **over)


def raw_insert(store: RegistryStore, row: TransitionRow, sql: str = rs._INSERT_ROW) -> None:
    conn = store._open()
    try:
        conn.execute(sql, rs._to_db(row))
    finally:
        conn.close()


# ---------------------------------------------------------------------------------------------
# DDL and initialisation
# ---------------------------------------------------------------------------------------------

AUT5_COLUMNS: Final = (
    "seq", "venue", "venue_seq", "transition_id", "family_id", "family_prior_seq",
    "paired_transition_id", "from_state", "to_state", "kind", "cause_verdict_ids",
    "cause_code", "halt_cause_class", "trigger_cause_class", "voids_transition_ids",
    "manifest_sha256", "artefact_sha256", "lineage_root_family_id", "attest_valid_until_ns",
    "k_life", "alpha_k", "n_min_eff", "n_cap", "nomination_feasible", "hwm_from", "hwm_to",
    "carried_counters", "drill", "drill_clause_sha256", "policy_ruling_id",
    "policy_ruling_sha256", "decided_by", "invocation_id", "engine_code_sha",
    "expected_prior_seq", "effective_launch_date", "ts_ns", "prev_transition_hash",
    "transition_hash",
)  # fmt: skip


def test_ddl_has_exactly_the_aut5_columns_and_constraints(store: RegistryStore) -> None:
    assert rs.COLUMNS == AUT5_COLUMNS
    conn = raw(store)
    try:
        info = conn.execute("PRAGMA table_info(transitions)").fetchall()
        assert tuple(r[1] for r in info) == AUT5_COLUMNS
        not_null = {r[1] for r in info if r[3]}
        assert {"venue", "venue_seq", "transition_id", "to_state", "kind"} <= not_null
        indexes = conn.execute("PRAGMA index_list(transitions)").fetchall()
        uniques = {
            tuple(c[2] for c in conn.execute(f"PRAGMA index_info({i[1]})")) for i in indexes if i[2]
        }
        assert uniques == {("venue", "venue_seq"), ("transition_id",)}
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert tables == {"transitions", "meta"}  # no derived caches (AUT-5 WP4)
    finally:
        conn.close()


def test_initialise_sets_identity_modes_and_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir(mode=0o700)
    paths = AutonomyPaths(root)
    first = RegistryStore.initialise(paths, repo_root=tmp_path / "repo")
    conn = raw(first)
    try:
        assert conn.execute("PRAGMA application_id").fetchone() == (0x42524759,)
        assert conn.execute("PRAGMA user_version").fetchone() == (1,)
        assert conn.execute("SELECT schema FROM meta").fetchall() == [("registry/v1",)]
    finally:
        conn.close()
    assert stat.S_IMODE(os.stat(root / "registry").st_mode) == 0o700
    assert stat.S_IMODE(os.stat(first._db).st_mode) == 0o600
    put_bootstrap(first)
    again = RegistryStore.initialise(paths, repo_root=tmp_path / "repo")  # re-init changes nothing
    assert len(stored(again)) == 1


def test_initialise_completes_an_empty_file_left_by_a_crash(tmp_path: Path) -> None:
    root = tmp_path / "data"
    (root / "registry").mkdir(parents=True, mode=0o700)
    (root / "registry" / "registry.sqlite").touch(mode=0o600)
    s = RegistryStore.initialise(AutonomyPaths(root), repo_root=tmp_path / "repo")
    assert put_bootstrap(s).head_venue_seq == 1


def test_initialise_refuses_a_foreign_database(tmp_path: Path) -> None:
    root = tmp_path / "data"
    (root / "registry").mkdir(parents=True, mode=0o700)
    foreign = sqlite3.connect(root / "registry" / "registry.sqlite")
    foreign.execute("CREATE TABLE other (x)")
    foreign.commit()
    foreign.close()
    with pytest.raises(StoreUnavailable):
        RegistryStore.initialise(AutonomyPaths(root), repo_root=tmp_path / "repo")


def test_shadow_paths_get_the_same_layout_in_their_own_root(tmp_path: Path) -> None:
    root = tmp_path / "shadow"
    root.mkdir(mode=0o700)
    s = RegistryStore.initialise(ShadowPaths(root), repo_root=tmp_path / "repo")
    assert put_bootstrap(s).replayed is False
    assert s._db == root / "registry" / "registry.sqlite"


def test_append_on_an_uninitialised_root_creates_nothing(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir(mode=0o700)
    s = RegistryStore(AutonomyPaths(root), repo_root=tmp_path / "repo")
    with pytest.raises(StoreUnavailable):
        put_bootstrap(s)
    assert list(root.iterdir()) == []


def test_symlinked_database_file_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "data"
    (root / "registry").mkdir(parents=True, mode=0o700)
    target = tmp_path / "elsewhere.sqlite"
    target.touch()
    (root / "registry" / "registry.sqlite").symlink_to(target)
    s = RegistryStore(AutonomyPaths(root), repo_root=tmp_path / "repo")
    with pytest.raises(StoreUnavailable):
        put_bootstrap(s)


def test_append_refuses_a_database_whose_schema_drifted(store: RegistryStore) -> None:
    conn = raw(store)
    conn.execute("DROP TRIGGER transitions_no_update")
    conn.commit()
    conn.close()
    with pytest.raises(StoreUnavailable):
        put_bootstrap(store)
    assert stored(store) == []


def test_store_binds_the_callers_repo_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "data"
    root.mkdir(mode=0o700)
    repo = tmp_path / "repo"
    s = RegistryStore.initialise(AutonomyPaths(root), repo_root=repo)
    monkeypatch.chdir(tmp_path)
    keywords = s._manifests.keywords  # type: ignore[attr-defined]
    assert keywords["repo_root"] == repo
    assert keywords["paths"] == AutonomyPaths(root)
    with pytest.raises(ValueError):
        RegistryStore(AutonomyPaths(root), repo_root=Path("relative"))


def test_module_never_derives_a_location_from_file_or_cwd() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not ({"__file__"} & names)
    assert not ({"cwd", "getcwd", "home", "environ"} & attrs)


# ---------------------------------------------------------------------------------------------
# Row <-> database
# ---------------------------------------------------------------------------------------------


def test_every_column_round_trips_through_the_database(store: RegistryStore) -> None:
    full = mk(
        Kind.PROMOTE, State.CHALLENGER, frm=State.SHADOW, family=CHILD, fps=0,
        cause_verdict_ids=(SHA_P, SHA_B), cause_code=CauseCode.VERDICT_FAIL,
        voids_transition_ids=(), manifest_sha256=SHA_B, artefact_sha256=SHA_P,
        drill=True, drill_clause_sha256=SHA_B, policy_ruling_id="ruling-1",
        policy_ruling_sha256=SHA_P, carried_counters='{"a":{"b":1}}', hwm_from=3, hwm_to=4,
        effective_launch_date=LAUNCH_DAY, trigger_cause_class=None, nomination_feasible=False,
        alpha_k=Decimal(0), seq=None,
    )  # fmt: skip
    sealed = replace(full, venue_seq=1, prev_transition_hash=chain.genesis(VENUE))
    sealed = replace(sealed, transition_hash=chain.transition_hash(sealed, chain.genesis(VENUE)))
    raw_insert(store, sealed)
    conn = raw(store)
    try:
        back = rs._from_db(conn.execute(rs._SELECT_ROWS).fetchone())
    finally:
        conn.close()
    assert back == replace(sealed, seq=1)


# ---------------------------------------------------------------------------------------------
# Column rules
# ---------------------------------------------------------------------------------------------


def test_registry_transition_table_is_exact(store: RegistryStore) -> None:
    """Every (kind, from, to) combination is accepted by the column rules iff ALLOWED says so."""
    accepted = 0
    for kind in Kind:
        for frm in (None, *State):
            for to in State:
                row = mk(kind, to, frm=frm)
                allowed = (frm, to) in transitions.ALLOWED[kind]
                if allowed:
                    check_row_shape(row)
                    accepted += 1
                else:
                    with pytest.raises(RowRefused, match="transition pair not allowed"):
                        check_row_shape(row)
    assert accepted == sum(len(pairs) for pairs in transitions.ALLOWED.values())
    # And the store itself writes nothing for a refused pair.
    with pytest.raises(RowRefused, match="transition pair not allowed"):
        store.append(
            [mk(Kind.DEMOTE, State.CHAMPION, frm=State.CHAMPION)], expected_prior_seq=0,
            mode=WriterMode.INTRADAY, now_ns=NOW,
        )  # fmt: skip
    assert stored(store) == []


@pytest.mark.parametrize(
    "case",
    [pytest.param("columns_required", id="columns_required")],
)
def test_nomination_columns_required_and_read_by_k_check(case: str, store: RegistryStore) -> None:
    nomination = mk(Kind.PROMOTE, State.CHALLENGER, frm=State.SHADOW, family=CHILD)
    check_row_shape(nomination)
    for field in shape.NOMINATION_FIELDS:
        with pytest.raises(RowRefused):
            check_row_shape(with_columns(nomination, **{field: None}))
    elsewhere = mk(Kind.PROMOTE, State.CHAMPION, frm=State.CHALLENGER, family=CHILD)
    check_row_shape(elsewhere)
    for field, value in (("k_life", 1), ("alpha_k", Decimal(0)), ("nomination_feasible", True)):
        with pytest.raises(RowRefused):
            check_row_shape(with_columns(elsewhere, **{field: value}))
    # A complete nomination passes the column rules; its k-checks are AUT-5a's, so it is refused.
    with pytest.raises(NominationRequiresPolicy) as info:
        store.append(
            [replace(nomination, transition_id=nomination.computed_transition_id())],
            expected_prior_seq=0, mode=WriterMode.DAILY, now_ns=NOW,
        )  # fmt: skip
    assert info.value.reason is RefusalReason.ADMISSION_PENDING


def test_e16_activate_cites_its_pair_and_other_kinds_do_not() -> None:
    activate = mk(Kind.ACTIVATE, State.CHALLENGER, frm=State.CHALLENGER)
    check_row_shape(activate)
    with pytest.raises(RowRefused):
        check_row_shape(replace(activate, paired_transition_id=None))
    with pytest.raises(RowRefused):
        check_row_shape(replace(demote(), paired_transition_id=SHA_P))


@pytest.mark.parametrize(
    "field,value",
    [
        ("lineage_root_family_id", None),
        ("attest_valid_until_ns", 5),
        ("voids_transition_ids", (SHA_P,)),
        ("cause_code", CauseCode.VERDICT_FAIL),
        ("trigger_cause_class", CauseClass.DRILL),
        ("hwm_from", 1),
    ],
)
def test_column_rules_refuse_stray_or_missing_columns(field: str, value: Any) -> None:
    if field == "lineage_root_family_id":
        base = bootstrap()
    elif field == "cause_code":
        base = mk(Kind.ATTEST, State.CHAMPION, frm=State.CHAMPION)
    else:
        base = demote()
    with pytest.raises(RowRefused):
        check_row_shape(with_columns(base, **{field: value}))


def test_resume_may_carry_only_the_drill_close_restore_cause() -> None:
    resume = mk(
        Kind.RESUME, State.CHAMPION, frm=State.HALTED, cause_code=CauseCode.DRILL_CLOSE_RESTORE
    )
    check_row_shape(resume)
    with pytest.raises(RowRefused):
        check_row_shape(replace(resume, cause_code=CauseCode.VERDICT_FAIL))
    halt = mk(
        Kind.HALT, State.HALTED, frm=State.CHAMPION, cause_code=CauseCode.ROLLBACK_FAILED,
        trigger_cause_class=CauseClass.DRILL,
    )  # fmt: skip
    check_row_shape(halt)


# ---------------------------------------------------------------------------------------------
# Append: CAS, replay, chain
# ---------------------------------------------------------------------------------------------


def test_registry_cas_and_idempotent_replay(
    store: RegistryStore, caplog: pytest.LogCaptureFixture
) -> None:
    first = put_bootstrap(store)
    assert (first.head_venue_seq, first.replayed, first.rows[0].seq) == (1, False, 1)
    with caplog.at_level(logging.INFO, logger=rs.__name__):
        again = put_bootstrap(store)
    assert again.replayed is True and again.rows == first.rows and again.head_venue_seq == 1
    assert "replay" in caplog.text
    assert len(stored(store)) == 1
    # A stale writer (CAS 0 while the head is 1) is refused and writes nothing.
    stale = mk(Kind.MINT, State.SHADOW, family=CHILD, expected=0)
    with pytest.raises(CasMismatch) as info:
        store.append([stale], expected_prior_seq=0, mode=WriterMode.DAILY, now_ns=NOW)
    assert info.value.reason is RefusalReason.ENGINE_INCONSISTENCY
    ok = replace(stale, expected_prior_seq=1)
    result = store.append(
        [replace(ok, transition_id=ok.computed_transition_id())], expected_prior_seq=1,
        mode=WriterMode.DAILY, now_ns=NOW + SEC,
    )  # fmt: skip
    assert result.head_venue_seq == 2


def test_registry_hash_chain_and_triggers(store: RegistryStore) -> None:
    put_bootstrap(store)
    store.append([demote()], expected_prior_seq=1, mode=WriterMode.INTRADAY, now_ns=NOW + SEC)
    conn = raw(store)
    try:
        rows = [rs._from_db(r) for r in conn.execute(rs._SELECT_VENUE, (VENUE,))]
        assert verify_venue_chain(rows, VENUE).head_venue_seq == 2
        assert rows[0].prev_transition_hash == chain.genesis(VENUE)
        assert rows[1].prev_transition_hash == rows[0].transition_hash
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        assert names == {
            "transitions_no_update",
            "transitions_no_delete",
            "transitions_insert_guard",
        }
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE transitions SET family_id = 'x' WHERE seq = 1")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM transitions WHERE seq = 1")
    finally:
        conn.close()
    assert len(stored(store)) == 2


def test_chain_is_per_venue(store: RegistryStore) -> None:
    put_bootstrap(store)
    other = mk(Kind.BOOTSTRAP, State.CHAMPION, venue=OTHER_VENUE)
    result = store.append([other], expected_prior_seq=0, mode=WriterMode.BOOTSTRAP, now_ns=NOW)
    assert result.rows[0].venue_seq == 1
    assert result.rows[0].prev_transition_hash == chain.genesis(OTHER_VENUE)
    assert [r[2] for r in stored(store)] == [1, 1]


@pytest.mark.parametrize("case", [pytest.param("arch0", id="arch0")])
def test_repeat_supersede_same_family_is_not_replay(case: str, store: RegistryStore) -> None:
    put_bootstrap(store)
    first = mk(
        Kind.SUPERSEDE, State.CHALLENGER, frm=State.CHAMPION, fps=1, expected=1, ts=NOW + SEC
    )
    second = mk(
        Kind.SUPERSEDE, State.CHALLENGER, frm=State.CHAMPION, fps=2, expected=2, ts=NOW + 2 * SEC
    )
    assert first.transition_id != second.transition_id  # the family prior seq is in the Y9 id
    one = store._append(
        [first], expected_prior_seq=1, mode=WriterMode.DAILY, now_ns=NOW + SEC,
        stage=OPEN_STAGE, _fixture_stage=True,
    )  # fmt: skip
    two = store._append(
        [second], expected_prior_seq=2, mode=WriterMode.DAILY, now_ns=NOW + 2 * SEC,
        stage=OPEN_STAGE, _fixture_stage=True,
    )  # fmt: skip
    assert (one.replayed, two.replayed, two.head_venue_seq) == (False, False, 3)


def test_partial_replay_refused(store: RegistryStore) -> None:
    first = bootstrap()
    store.append([first], expected_prior_seq=0, mode=WriterMode.BOOTSTRAP, now_ns=NOW)
    second = bootstrap(CHILD)
    with pytest.raises(PartialReplay):
        store.append([first, second], expected_prior_seq=0, mode=WriterMode.BOOTSTRAP, now_ns=NOW)
    assert len(stored(store)) == 1


def test_store_multirow_append_is_atomic(
    store: RegistryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = bootstrap(), seed_retired()
    real = rs._to_db
    calls: list[int] = []

    def fail_second(row: TransitionRow) -> tuple[object, ...]:
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("injected failure on the second insert")
        return real(row)

    monkeypatch.setattr(rs, "_to_db", fail_second)
    with pytest.raises(RuntimeError):
        store.append([a, b], expected_prior_seq=0, mode=WriterMode.BOOTSTRAP, now_ns=NOW)
    assert stored(store) == []
    monkeypatch.undo()
    result = store.append([a, b], expected_prior_seq=0, mode=WriterMode.BOOTSTRAP, now_ns=NOW)
    assert [r.venue_seq for r in result.rows] == [1, 2]  # and the lock was released


def test_each_appended_row_links_to_the_previous_hash(store: RegistryStore) -> None:
    b = mk(Kind.MINT, State.SHADOW, family=CHILD, ts=NOW + SEC, expected=1)
    first = put_bootstrap(store)
    again = store.append([b], expected_prior_seq=1, mode=WriterMode.DAILY, now_ns=NOW + SEC)
    assert again.rows[0].prev_transition_hash == first.rows[0].transition_hash
    assert again.rows[0].transition_hash != first.rows[0].transition_hash


# ---------------------------------------------------------------------------------------------
# Triggers
# ---------------------------------------------------------------------------------------------


def test_venue_seq_gap_refused_by_trigger(store: RegistryStore) -> None:
    put_bootstrap(store)
    with pytest.raises(sqlite3.IntegrityError, match="venue_seq gap"):
        raw_insert(store, sealed_copy(store, venue_seq=3, transition_id=SHA_P))
    with pytest.raises(sqlite3.IntegrityError, match="venue_seq duplicate"):
        raw_insert(store, sealed_copy(store, venue_seq=1, transition_id=SHA_P))
    raw_insert(store, sealed_copy(store, venue_seq=2, transition_id=SHA_P))
    assert [r[2] for r in stored(store)] == [1, 2]


def test_first_row_venue_seq_must_be_one(store: RegistryStore) -> None:
    put_bootstrap(store)
    other = sealed_copy(store, venue=OTHER_VENUE, transition_id=SHA_P)
    with pytest.raises(sqlite3.IntegrityError, match="venue_seq gap"):
        raw_insert(store, replace(other, venue_seq=5))
    with pytest.raises(sqlite3.IntegrityError, match="venue_seq gap"):
        raw_insert(store, replace(other, venue_seq=2))
    raw_insert(store, replace(other, venue_seq=1))
    assert (OTHER_VENUE, 1) in {(r[1], r[2]) for r in stored(store)}


def test_trigger_refuses_an_existing_seq(store: RegistryStore) -> None:
    put_bootstrap(store)
    with_seq = rs._INSERT_ROW.replace("(venue,", "(seq, venue,", 1).replace(
        "VALUES (", "VALUES (?, ", 1
    )
    row = sealed_copy(store, venue_seq=2, transition_id=SHA_P)
    conn = raw(store)  # recursive_triggers OFF, the SQLite default
    try:
        with pytest.raises(sqlite3.IntegrityError, match="seq exists"):
            conn.execute(with_seq, (1, *rs._to_db(row)))
    finally:
        conn.close()
    assert len(stored(store)) == 1


def test_insert_or_replace_refused(store: RegistryStore) -> None:
    """A6e-R5: on a default connection (no recursive_triggers) REPLACE used to delete the original
    row when the same transition_id arrived at head+1; the insert guard now refuses it."""
    put_bootstrap(store)
    replace_sql = rs._INSERT_ROW.replace("INSERT INTO", "INSERT OR REPLACE INTO")
    colliding_id = sealed_copy(store, venue_seq=2)  # same transition_id, next venue_seq
    conn = raw(store)  # recursive_triggers OFF, the SQLite default
    try:
        assert conn.execute("PRAGMA recursive_triggers").fetchone() == (0,)
        with pytest.raises(sqlite3.IntegrityError, match="transition_id exists"):
            conn.execute(replace_sql, rs._to_db(colliding_id))
        with pytest.raises(sqlite3.IntegrityError, match="venue_seq duplicate"):
            conn.execute(
                replace_sql, rs._to_db(sealed_copy(store, venue_seq=1, transition_id=SHA_P))
            )
    finally:
        conn.close()
    with pytest.raises(sqlite3.IntegrityError, match="transition_id exists"):
        raw_insert(store, colliding_id, replace_sql)  # and under the writer's pragmas
    assert [r[2] for r in stored(store)] == [1]  # the original row survived


def test_plain_insert_of_an_existing_transition_id_is_refused(store: RegistryStore) -> None:
    put_bootstrap(store)
    with pytest.raises(sqlite3.IntegrityError, match="transition_id exists"):
        raw_insert(store, sealed_copy(store, venue_seq=2))


def test_on_conflict_do_update_refused(store: RegistryStore) -> None:
    put_bootstrap(store)
    upsert = rs._INSERT_ROW + " ON CONFLICT (transition_id) DO UPDATE SET family_id = 'x'"
    row = sealed_copy(store, venue_seq=2)
    for conn in (store._open(), raw(store)):
        try:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(upsert, rs._to_db(row))
        finally:
            conn.close()
    conn = raw(store)
    try:
        assert conn.execute("SELECT family_id FROM transitions").fetchall() == [(FAMILY,)]
    finally:
        conn.close()
    assert len(stored(store)) == 1


def test_writer_pragmas_read_back(store: RegistryStore, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = store._open()
    try:
        assert conn.isolation_level is None
        assert conn.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        assert conn.execute("PRAGMA synchronous").fetchone() == (3,)  # A6e-R6: EXTRA
        assert conn.execute("PRAGMA recursive_triggers").fetchone() == (1,)
        assert conn.execute("PRAGMA trusted_schema").fetchone() == (0,)
        conn.execute("BEGIN IMMEDIATE")
        assert conn.in_transaction
        conn.execute("ROLLBACK")
    finally:
        conn.close()
    wrong = (("PRAGMA synchronous = EXTRA", "PRAGMA synchronous", 1),)
    monkeypatch.setattr(rs, "_WRITER_PRAGMAS", wrong)
    with pytest.raises(StoreUnavailable):
        store._open()


def test_a_second_writer_waits_then_is_refused_as_unavailable(
    store: RegistryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rs, "WRITER_BUSY_TIMEOUT_S", 0.05)
    holder = store._open()
    holder.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(rs.StoreBusy) as info:
            put_bootstrap(store)
        assert info.value.reason is RefusalReason.REGISTRY_UNREADABLE
        assert not isinstance(info.value, rs.StoreDrifted)
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert put_bootstrap(store).replayed is False


_BANNED_SQL: Final = ("OR REPLACE", "OR IGNORE", "REPLACE INTO", "EXECUTESCRIPT")


def _sql_problems(source: str) -> list[str]:
    tree = ast.parse(source)
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            upper = " ".join(node.value.upper().split())
            problems += [f"literal {b}" for b in _BANNED_SQL if b in upper]
        elif isinstance(node, ast.Attribute) and node.attr.lower() == "executescript":
            problems.append("executescript")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"execute", "executemany"}
            and node.args
            and isinstance(node.args[0], ast.JoinedStr | ast.BinOp | ast.Call)
        ):
            problems.append("string-built SQL")
    return problems


def test_store_sql_has_no_replace_or_ignore() -> None:
    assert _sql_problems(MODULE_PATH.read_text(encoding="utf-8")) == []
    ddl = " ".join(sql for _t, _n, sql in rs.DDL_OBJECTS).upper()
    assert "REPLACE" not in ddl and "IGNORE" not in ddl


@pytest.mark.parametrize(
    "planted,expected",
    [
        ("c.execute('INSERT OR REPLACE INTO t VALUES (1)')", "literal OR REPLACE"),
        ("c.execute('insert  or   ignore into t values (1)')", "literal OR IGNORE"),
        ("c.execute('REPLACE INTO t VALUES (1)')", "literal REPLACE INTO"),
        ("c.executescript('select 1')", "executescript"),
        ("c.execute(f'select {x}')", "string-built SQL"),
        ("c.execute('select ' + x)", "string-built SQL"),
        ("c.execute('select {}'.format(x))", "string-built SQL"),
    ],
)
def test_sql_scan_fires_on_every_planted_form(planted: str, expected: str) -> None:
    assert expected in _sql_problems(planted)


def test_sql_scan_accepts_a_constant_statement() -> None:
    assert _sql_problems("S = 'SELECT 1 WHERE a = ?'\nc.execute(S, (1,))\n") == []


# ---------------------------------------------------------------------------------------------
# Mode, mask, stage, admission
# ---------------------------------------------------------------------------------------------


def _first_valid(kind: Kind) -> TransitionRow:
    frm, to = min(transitions.ALLOWED[kind], key=lambda p: (str(p[0]), p[1]))
    return mk(kind, to, frm=frm)


def test_store_enforces_kind_mask_per_mode(store: RegistryStore) -> None:
    refused = 0
    for mode in WriterMode:
        for kind in Kind:
            if kind in transitions.KIND_MASK[mode]:
                continue
            with pytest.raises(KindRefused):
                store._append(
                    [_first_valid(kind)], expected_prior_seq=0, mode=mode, now_ns=NOW,
                    stage=OPEN_STAGE, _fixture_stage=True,
                )  # fmt: skip
            refused += 1
    assert refused == sum(len(Kind) - len(m) for m in transitions.KIND_MASK.values())
    assert stored(store) == []
    # RESUME is not a DAILY kind (P7-9), even under a fully enabled stage.
    assert Kind.RESUME not in transitions.KIND_MASK[WriterMode.DAILY]


def test_mask_admits_each_modes_restrictive_kinds(store: RegistryStore) -> None:
    put_bootstrap(store)
    result = store.append(
        [demote()], expected_prior_seq=1, mode=WriterMode.OPERATOR_CLI, now_ns=NOW + SEC
    )
    assert result.rows[0].kind is Kind.DEMOTE


def test_daily_refuses_widening_before_stage_flag(store: RegistryStore) -> None:
    put_bootstrap(store)
    widening = [
        mk(Kind.PROMOTE, State.CHAMPION, frm=State.CHALLENGER, fps=1, expected=1,
           effective_launch_date=LAUNCH_DAY),
        mk(Kind.DRILL_PROMOTE, State.CHAMPION, frm=State.CHALLENGER, fps=1, expected=1,
           effective_launch_date=LAUNCH_DAY),
        mk(Kind.ROLLBACK, State.CHAMPION, frm=State.CHALLENGER, fps=1, expected=1,
           effective_launch_date=LAUNCH_DAY),
        mk(Kind.SUPERSEDE, State.CHALLENGER, frm=State.CHAMPION, fps=1, expected=1),
        mk(Kind.DISPLACED, State.CHALLENGER, frm=State.HALTED, fps=1, expected=1),
        mk(Kind.DRILL_ADMIT, State.CHALLENGER, frm=State.SHADOW, fps=1, expected=1),
    ]  # fmt: skip
    for row in widening:
        assert row.kind in transitions.KIND_MASK[WriterMode.DAILY]
        with pytest.raises(WideningNotEnabled) as info:
            store.append([row], expected_prior_seq=1, mode=WriterMode.DAILY, now_ns=NOW + SEC)
        assert info.value.reason is RefusalReason.WIDENING_KIND_NOT_ENABLED
    assert len(stored(store)) == 1
    assert stage_policy.STAGE.enabled_widening_kinds == frozenset()


def test_admission_pending_refused_when_enabled_but_unimplemented(store: RegistryStore) -> None:
    put_bootstrap(store)
    promote = mk(
        Kind.PROMOTE, State.CHAMPION, frm=State.CHALLENGER, fps=1, expected=1, ts=NOW + 2 * SEC,
        effective_launch_date=LAUNCH_DAY,
    )  # fmt: skip
    leading_restrictive = demote()
    enabled_only = StagePolicy(
        enabled_widening_kinds=frozenset({Kind.PROMOTE}), admission_implemented=frozenset()
    )
    with pytest.raises(AdmissionPending) as info:
        store._append(
            [leading_restrictive, promote], expected_prior_seq=1, mode=WriterMode.DAILY,
            now_ns=NOW + SEC, stage=enabled_only, _fixture_stage=True,
        )  # fmt: skip
    assert info.value.reason is RefusalReason.ADMISSION_PENDING
    assert len(stored(store)) == 1  # the whole batch is refused, the leading DEMOTE included
    neither = StagePolicy(enabled_widening_kinds=frozenset(), admission_implemented=frozenset())
    with pytest.raises(WideningNotEnabled):
        store._append(
            [promote], expected_prior_seq=1, mode=WriterMode.DAILY, now_ns=NOW + SEC,
            stage=neither, _fixture_stage=True,
        )  # fmt: skip


def test_a_nomination_is_not_widening_so_it_reaches_the_k_check_refusal(
    store: RegistryStore,
) -> None:
    nomination = mk(Kind.PROMOTE, State.CHALLENGER, frm=State.SHADOW, family=CHILD)
    with pytest.raises(NominationRequiresPolicy):
        store.append([nomination], expected_prior_seq=0, mode=WriterMode.DAILY, now_ns=NOW)


def test_hwm_reset_is_refused_until_its_rule_set_lands(store: RegistryStore) -> None:
    put_bootstrap(store)
    reset = mk(Kind.HWM_RESET, State.CHAMPION, frm=State.CHAMPION, fps=1, expected=1, ts=NOW + SEC)
    with pytest.raises(RuleSetPending) as info:
        store.append([reset], expected_prior_seq=1, mode=WriterMode.OPERATOR_CLI, now_ns=NOW + SEC)
    assert info.value.reason is RefusalReason.ADMISSION_PENDING


@pytest.mark.parametrize("case", [pytest.param("store", id="store")])
def test_admissibility_predicate_shared(
    case: str, store: RegistryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The store consults ``transitions.rows_admissible`` and keeps no second copy of it."""
    put_bootstrap(store)
    seen: list[Any] = []

    def refuse_everything(rows: Any, *, stage: Any) -> AdmissibilityResult:
        seen.append((tuple(rows), stage))
        return AdmissibilityResult(0, RefusalReason.ADMISSION_PENDING)

    monkeypatch.setattr(transitions, "rows_admissible", refuse_everything)
    with pytest.raises(AdmissionPending):
        store.append([demote()], expected_prior_seq=1, mode=WriterMode.INTRADAY, now_ns=NOW + SEC)
    assert len(seen) == 1 and seen[0][1] is stage_policy.STAGE and seen[0][0][0].kind is Kind.DEMOTE
    monkeypatch.undo()
    store.append([demote()], expected_prior_seq=1, mode=WriterMode.INTRADAY, now_ns=NOW + SEC)
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert find_predicate_reads(str(MODULE_PATH), source, {}) == []


def test_append_refuses_non_canonical_stage(store: RegistryStore) -> None:
    row = bootstrap()
    other = StagePolicy(enabled_widening_kinds=frozenset(), admission_implemented=frozenset())
    assert other == stage_policy.STAGE and other is not stage_policy.STAGE
    with pytest.raises(StageNotCanonical) as info:
        store._append(
            [row], expected_prior_seq=0, mode=WriterMode.BOOTSTRAP, now_ns=NOW, stage=other
        )
    assert info.value.reason is RefusalReason.STAGE_NOT_CANONICAL
    assert stored(store) == []
    store._append(
        [row], expected_prior_seq=0, mode=WriterMode.BOOTSTRAP, now_ns=NOW, stage=other,
        _fixture_stage=True,
    )  # fmt: skip
    assert len(stored(store)) == 1


def test_append_requires_concrete_mode(store: RegistryStore) -> None:
    for bad in ("BOOTSTRAP", None, 1, WriterMode):
        with pytest.raises(ModeNotConcrete):
            store.append([bootstrap()], expected_prior_seq=0, mode=bad, now_ns=NOW)  # type: ignore[arg-type]
    assert stored(store) == []
    assert put_bootstrap(store).head_venue_seq == 1


# ---------------------------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------------------------


def test_row_ts_skew_and_monotonicity_refused(store: RegistryStore) -> None:
    limit = pins.ROW_TS_MAX_SKEW_S * SEC
    assert limit == 300 * SEC
    # A6e-R9: a row stamped after the writer's clock is refused; so is one far in the past.
    for ts in (NOW + 1, NOW - limit - 1):
        with pytest.raises(ClockRefused) as info:
            store.append(
                [bootstrap(ts=ts)], expected_prior_seq=0, mode=WriterMode.BOOTSTRAP, now_ns=NOW
            )
        assert info.value.reason is RefusalReason.CLOCK_INVALID
    low = bootstrap(ts=NOW - limit)
    high = mk(
        Kind.MINT, State.SHADOW, family=CHILD, ts=NOW, expected=1
    )  # exactly now_ns is allowed
    store.append([low], expected_prior_seq=0, mode=WriterMode.BOOTSTRAP, now_ns=NOW)
    store.append([high], expected_prior_seq=1, mode=WriterMode.DAILY, now_ns=NOW)
    behind = mk(Kind.DEMOTE, State.HALTED, frm=State.CHAMPION, fps=1, expected=2, ts=NOW - SEC)
    with pytest.raises(ClockRefused) as info:
        store.append([behind], expected_prior_seq=2, mode=WriterMode.INTRADAY, now_ns=NOW)
    assert info.value.reason is RefusalReason.CLOCK_BEFORE_HEAD
    assert len(stored(store)) == 2


def test_a_future_stamped_row_is_refused_with_clock_invalid(store: RegistryStore) -> None:
    with pytest.raises(ClockRefused) as info:
        store.append(
            [bootstrap(ts=NOW + 1)], expected_prior_seq=0, mode=WriterMode.BOOTSTRAP, now_ns=NOW
        )
    assert info.value.reason is RefusalReason.CLOCK_INVALID
    assert stored(store) == []


def test_a_batch_must_be_monotone_within_itself(store: RegistryStore) -> None:
    a = bootstrap(ts=NOW + 2 * SEC)
    b = bootstrap(CHILD, ts=NOW + SEC)
    with pytest.raises(ClockRefused) as info:
        store.append([a, b], expected_prior_seq=0, mode=WriterMode.BOOTSTRAP, now_ns=NOW + 2 * SEC)
    assert info.value.reason is RefusalReason.CLOCK_BEFORE_HEAD


def test_a_stale_writer_gets_cas_mismatch_not_clock_before_head(store: RegistryStore) -> None:
    """A6e-R8 / E-17 d: CAS runs before the clock check (the retry path is CasMismatch)."""
    put_bootstrap(store)
    stale = demote(ts=NOW + SEC)  # prepared against head 1
    winner = mk(
        Kind.ATTEST,
        State.CHAMPION,
        frm=State.CHAMPION,
        fps=1,
        expected=1,
        ts=NOW + 9 * SEC,
        attest_valid_until_ns=NOW + 10 * SEC,
    )
    store.append([winner], expected_prior_seq=1, mode=WriterMode.INTRADAY, now_ns=NOW + 9 * SEC)
    with pytest.raises(CasMismatch) as info:
        store.append([stale], expected_prior_seq=1, mode=WriterMode.INTRADAY, now_ns=NOW + 9 * SEC)
    assert isinstance(info.value, RegistryRefused)
    assert info.value.reason is RefusalReason.ENGINE_INCONSISTENCY


def test_a_wrong_family_prior_seq_is_refused_as_chain_refused(store: RegistryStore) -> None:
    put_bootstrap(store)
    with pytest.raises(rs.ChainRefused) as info:
        store.append(
            [demote(fps=7)], expected_prior_seq=1, mode=WriterMode.INTRADAY, now_ns=NOW + SEC
        )
    assert isinstance(info.value, RegistryRefused)
    assert info.value.reason is RefusalReason.CHAIN_BROKEN
    assert len(stored(store)) == 1


def test_a_stored_chain_that_does_not_verify_blocks_further_appends(store: RegistryStore) -> None:
    first = put_bootstrap(store).rows[0]
    # A second row that is right in every way except its own hash.
    forged = replace(
        bootstrap(CHILD, expected=1),
        venue_seq=2,
        prev_transition_hash=first.transition_hash,
        transition_hash=SHA_B,
    )
    raw_insert(store, forged)
    with pytest.raises(rs.ChainRefused) as info:
        store.append(
            [demote(expected=2)], expected_prior_seq=2, mode=WriterMode.INTRADAY, now_ns=NOW + SEC
        )
    assert info.value.reason is RefusalReason.CHAIN_BROKEN
    assert "hash" in info.value.detail
    assert len(stored(store)) == 2


def test_no_bare_chain_broken_wire_or_value_error_escapes_append(
    store: RegistryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    put_bootstrap(store)
    for name, error in (
        ("_seal", WireRefused(WireRefusalReason.BAD_VALUE, "x")),
        ("fold", ValueError("x")),
        ("_check_clock", TypeError("x")),
    ):

        def boom(*_a: object, _e: Exception = error, **_k: object) -> None:
            raise _e

        monkeypatch.setattr(rs, name, boom)
        with pytest.raises(RowRefused):
            store.append(
                [demote()], expected_prior_seq=1, mode=WriterMode.INTRADAY, now_ns=NOW + SEC
            )
        monkeypatch.undo()
    assert len(stored(store)) == 1


def test_a_family_first_written_by_a_non_introducing_kind_is_refused(store: RegistryStore) -> None:
    orphan = mk(Kind.DEMOTE, State.HALTED, frm=State.CHAMPION, family=CHILD)
    with pytest.raises(rs.FoldRefused) as info:
        store.append([orphan], expected_prior_seq=0, mode=WriterMode.INTRADAY, now_ns=NOW)
    assert info.value.reason is RefusalReason.FAMILY_NOT_INTRODUCED
    assert stored(store) == []


def test_a_head_without_a_launch_date_is_refused_by_the_fold(store: RegistryStore) -> None:
    put_bootstrap(store)
    head = mk(Kind.ROLLBACK, State.CHAMPION, frm=State.CHALLENGER, fps=1, expected=1, ts=NOW + SEC)
    with pytest.raises(rs.FoldRefused):
        store._append(
            [head], expected_prior_seq=1, mode=WriterMode.DAILY, now_ns=NOW + SEC,
            stage=OPEN_STAGE, _fixture_stage=True,
        )  # fmt: skip


def test_fold_refusals_map_every_fold_invalid_reason() -> None:
    assert set(rs._FOLD_REFUSALS) == set(FoldInvalidReason)
    assert all(isinstance(v, RefusalReason) for v in rs._FOLD_REFUSALS.values())


def test_batch_refusals(store: RegistryStore) -> None:
    good = bootstrap()
    sealed = replace(good, venue_seq=1)
    cases: list[tuple[Any, int, int]] = [
        ([], 0, NOW),
        ([good, good], 0, NOW),
        ([sealed], 0, NOW),
        ([bootstrap(expected=3)], 0, NOW),
        ([bootstrap(), bootstrap(CHILD, venue=OTHER_VENUE)], 0, NOW),
        (["not a row"], 0, NOW),
        ([good], -1, NOW),
        ([good], 0, -1),
        ([good], True, NOW),
    ]
    for rows, expected, now in cases:
        with pytest.raises(RowRefused):
            store.append(rows, expected_prior_seq=expected, mode=WriterMode.BOOTSTRAP, now_ns=now)
    assert stored(store) == []


# ---------------------------------------------------------------------------------------------
# Restrictive writes are never gated on anything that can fail open
# ---------------------------------------------------------------------------------------------


def test_restrictive_rows_consult_no_manifest_policy_or_stage_flag(
    store: RegistryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    put_bootstrap(store)

    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("a restrictive write must not read manifests")

    monkeypatch.setattr(rs, "read_manifest_facts", boom)
    monkeypatch.setattr(store, "_manifests", boom)
    real_validate = transitions.first_refusal
    judged: list[tuple[Kind, ...]] = []

    def spy(prior: Any, rows: Any, **kwargs: Any) -> Any:
        judged.append(tuple(row.kind for row in rows))
        assert kwargs["manifests"] is boom  # the store hands over its (here booby-trapped) reader
        return real_validate(prior, rows, **kwargs)

    monkeypatch.setattr(transitions, "first_refusal", spy)
    result = store.append(
        [demote()], expected_prior_seq=1, mode=WriterMode.INTRADAY, now_ns=NOW + SEC
    )
    assert result.rows[0].kind is Kind.DEMOTE
    assert judged == [(Kind.DEMOTE,)]  # validate ran, and still read no manifest
    assert stage_policy.STAGE.enabled_widening_kinds == frozenset()  # no flag was needed


def test_every_restrictive_kind_is_appendable_with_the_shipped_stage(store: RegistryStore) -> None:
    """DEMOTE, HALT, SWAP_CANCEL and TARGET_INELIGIBLE each append at ``stage_policy.STAGE``.

    ``validate`` (7d) judges them against real states: the CHALLENGER the last two need exists
    only through the fixture's open stage; the writes under test use the shipped one.
    """
    drill_child_store(store)  # seq 1-5 on VENUE
    head, _tail = pair_rows()
    shapes: tuple[tuple[Kind, int, dict[str, Any]], ...] = (
        (Kind.TARGET_INELIGIBLE, 4, {"cause_code": CauseCode.TARGET_INTEGRITY}),
        (Kind.SWAP_CANCEL, 6, {"voids_transition_ids": (head.transition_id,)}),
    )
    for seq, (kind, fps, extra) in enumerate(shapes, start=5):
        row = child_row(kind, State.CHALLENGER, State.CHALLENGER, fps=fps, seq=seq, **extra)
        result = store.append(
            [row], expected_prior_seq=seq, mode=WriterMode.INTRADAY, now_ns=row.ts_ns
        )
        assert result.head_venue_seq == seq + 1
    demote_row = mk(
        Kind.DEMOTE, State.HALTED, frm=State.CHAMPION, fps=5, expected=7, ts=NOW + 7 * SEC
    )
    store.append([demote_row], expected_prior_seq=7, mode=WriterMode.INTRADAY, now_ns=NOW + 7 * SEC)
    other = mk(Kind.BOOTSTRAP, State.CHAMPION, venue=OTHER_VENUE)  # a CHAMPION to HALT
    store.append([other], expected_prior_seq=0, mode=WriterMode.BOOTSTRAP, now_ns=NOW)
    halt = mk(
        Kind.HALT, State.HALTED, frm=State.CHAMPION, fps=1, expected=1, ts=NOW + SEC,
        venue=OTHER_VENUE,
    )  # fmt: skip
    store.append([halt], expected_prior_seq=1, mode=WriterMode.INTRADAY, now_ns=NOW + SEC)
    appended = {r[3] for r in stored(store)}
    assert {k.value for k in transitions.RESTRICTIVE_KINDS} <= appended


def test_a_dataless_directory_listing_shows_only_the_database(store: RegistryStore) -> None:
    put_bootstrap(store)
    names = sorted(p.name for p in store._db.parent.iterdir())
    assert names == ["registry.sqlite"]  # DELETE journal mode leaves no sidecar at rest


# ---------------------------------------------------------------------------------------------
# A6e-R4 / E-17 a: the Y9 no-op applies only when the bodies match
# ---------------------------------------------------------------------------------------------


def test_a_submitted_transition_id_must_equal_the_computed_id(store: RegistryStore) -> None:
    forged = replace(bootstrap(), transition_id=SHA_P)
    with pytest.raises(RowRefused, match="transition_id"):
        store.append([forged], expected_prior_seq=0, mode=WriterMode.BOOTSTRAP, now_ns=NOW)
    assert stored(store) == []


def _swap_cancel(voids: tuple[str, ...]) -> TransitionRow:
    return child_row(
        Kind.SWAP_CANCEL,
        State.CHALLENGER,
        State.CHALLENGER,
        fps=4,
        seq=5,
        voids_transition_ids=voids,
    )


@pytest.mark.parametrize(
    "first,second",
    [
        pytest.param(
            demote_with(cause_code=CauseCode.VERDICT_FAIL),
            demote_with(cause_code=CauseCode.EXEC_STORE_HALT_MIRROR),
            id="cause_code",
        ),
        pytest.param(
            demote_with(halt_cause_class=CauseClass.RECOVERABLE_MODEL),
            demote_with(halt_cause_class=CauseClass.RECOVERABLE_INFRA),
            id="halt_cause_class",
        ),
        pytest.param(
            _swap_cancel((pair_rows()[0].transition_id,)),
            _swap_cancel((pair_rows()[0].transition_id, SHA_B)),
            id="voids_transition_ids",
        ),
    ],
)
def test_replay_differing_in_a_semantic_column_is_refused(
    store: RegistryStore, first: TransitionRow, second: TransitionRow
) -> None:
    if first.kind is Kind.SWAP_CANCEL:
        drill_child_store(store)  # a cancel needs a CHALLENGER to name (7d)
    else:
        put_bootstrap(store)
    seq, now = first.expected_prior_seq, first.ts_ns
    assert first.transition_id == second.transition_id  # the Y9 id does not cover the column
    store.append([first], expected_prior_seq=seq, mode=WriterMode.INTRADAY, now_ns=now)
    with pytest.raises(rs.ReplayMismatch) as info:
        store.append([second], expected_prior_seq=seq, mode=WriterMode.INTRADAY, now_ns=now)
    assert isinstance(info.value, RegistryRefused)
    assert len(stored(store)) == seq + 1


def test_replay_ignores_only_the_excluded_columns(store: RegistryStore) -> None:
    put_bootstrap(store)
    first = demote_with(cause_code=CauseCode.VERDICT_FAIL)
    store.append([first], expected_prior_seq=1, mode=WriterMode.INTRADAY, now_ns=NOW + SEC)
    retry = replace(
        first, ts_ns=NOW + 2 * SEC, invocation_id=INVOCATION.replace("1", "2"), expected_prior_seq=1
    )
    again = store.append(
        [retry], expected_prior_seq=1, mode=WriterMode.INTRADAY, now_ns=NOW + 3 * SEC
    )
    assert again.replayed is True and again.rows[0].ts_ns == NOW + SEC  # the stored row, unchanged


# ---------------------------------------------------------------------------------------------
# A6e-R8: busy vs drifted
# ---------------------------------------------------------------------------------------------


def test_drift_is_not_busy_and_busy_is_not_drift(store: RegistryStore) -> None:
    conn = raw(store)
    conn.execute("DROP TRIGGER transitions_no_delete")
    conn.commit()
    conn.close()
    with pytest.raises(rs.StoreDrifted) as info:
        put_bootstrap(store)
    assert not isinstance(info.value, rs.StoreBusy)
    assert info.value.reason is RefusalReason.REGISTRY_UNREADABLE
    assert issubclass(rs.StoreBusy, StoreUnavailable) and issubclass(
        rs.StoreDrifted, StoreUnavailable
    )


def test_a_missing_or_foreign_database_is_drifted_not_busy(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir(mode=0o700)
    with pytest.raises(rs.StoreDrifted):
        put_bootstrap(RegistryStore(AutonomyPaths(root), repo_root=tmp_path / "repo"))


# ---------------------------------------------------------------------------------------------
# A6e-R10: column rules
# ---------------------------------------------------------------------------------------------


def test_halt_cause_class_belongs_to_demote_and_halt_only() -> None:
    check_row_shape(demote_with(halt_cause_class=CauseClass.RECOVERABLE_INFRA))
    attest = mk(Kind.ATTEST, State.CHAMPION, frm=State.CHAMPION)
    with pytest.raises(RowRefused, match="halt_cause_class"):
        check_row_shape(with_columns(attest, halt_cause_class=CauseClass.DRILL))


def test_swap_cancel_needs_a_non_empty_void_list() -> None:
    check_row_shape(_swap_cancel((SHA_P,)))
    for bad in ((), None):
        with pytest.raises(RowRefused, match="voids_transition_ids"):
            check_row_shape(with_columns(_swap_cancel((SHA_P,)), voids_transition_ids=bad))


def test_cause_code_values_are_validated_per_kind() -> None:
    with pytest.raises(RowRefused, match="cause_code"):
        check_row_shape(demote_with(cause_code=CauseCode.DRILL_CLOSE_RESTORE))
    with pytest.raises(RowRefused, match="cause_code"):
        check_row_shape(demote_with(cause_code=CauseCode.TARGET_INTEGRITY))
    ineligible = mk(
        Kind.TARGET_INELIGIBLE, State.CHALLENGER, frm=State.CHALLENGER,
        cause_code=CauseCode.TARGET_INTEGRITY,
    )  # fmt: skip
    check_row_shape(ineligible)
    with pytest.raises(RowRefused, match="cause_code"):
        check_row_shape(with_columns(ineligible, cause_code=CauseCode.DRILL_CLOSE_RESTORE))


# ---------------------------------------------------------------------------------------------
# A6e-R11
# ---------------------------------------------------------------------------------------------


def test_sqlite_stat_tables_do_not_refuse_writes(store: RegistryStore) -> None:
    put_bootstrap(store)
    conn = raw(store)
    conn.execute("ANALYZE")
    conn.commit()
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    conn.close()
    assert "sqlite_stat1" in names
    store.append([demote()], expected_prior_seq=1, mode=WriterMode.INTRADAY, now_ns=NOW + SEC)
    assert len(stored(store)) == 2


class _RollbackBoom:
    """A connection proxy whose ROLLBACK raises; records close()."""

    def __init__(self, inner: sqlite3.Connection) -> None:
        self._inner = inner
        self.closed = False

    @property
    def in_transaction(self) -> bool:
        return self._inner.in_transaction

    def execute(self, sql: str, *args: Any) -> sqlite3.Cursor:
        if sql == "ROLLBACK":
            raise sqlite3.OperationalError("injected rollback failure")
        return self._inner.execute(sql, *args)

    def close(self) -> None:
        self.closed = True
        self._inner.close()


def test_a_failing_rollback_still_closes_and_the_original_error_survives(
    store: RegistryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    proxies: list[_RollbackBoom] = []
    real_open = store._open

    def open_proxy() -> Any:
        proxies.append(_RollbackBoom(real_open()))
        return proxies[-1]

    def explode(_row: TransitionRow) -> tuple[object, ...]:
        raise RuntimeError("original failure")

    monkeypatch.setattr(store, "_open", open_proxy)
    monkeypatch.setattr(rs, "_to_db", explode)
    with pytest.raises(RuntimeError, match="original failure"):
        put_bootstrap(store)
    assert proxies[0].closed


def test_open_rechecks_file_and_directory_modes(store: RegistryStore) -> None:
    os.chmod(store._db, 0o644)
    with pytest.raises(rs.StoreDrifted):
        put_bootstrap(store)
    os.chmod(store._db, 0o600)
    os.chmod(store._db.parent, 0o755)
    try:
        with pytest.raises(rs.StoreDrifted):
            put_bootstrap(store)
    finally:
        os.chmod(store._db.parent, 0o700)
    assert put_bootstrap(store).replayed is False


def _trigger(name: str, store: RegistryStore, monkeypatch: pytest.MonkeyPatch) -> RegistryRefused:
    """Provoke the named refusal through the public path and return what was raised."""
    put_bootstrap(store)
    ts = NOW + SEC
    batch: list[TransitionRow] = [demote()]
    kwargs: dict[str, Any] = {"expected_prior_seq": 1, "mode": WriterMode.INTRADAY, "now_ns": ts}
    if name == "StageNotCanonical":
        return _raised(
            lambda: store._append(batch, stage=StagePolicy(frozenset(), frozenset()), **kwargs)
        )
    if name in {"WideningNotEnabled", "AdmissionPending"}:
        head = mk(Kind.ROLLBACK, State.CHAMPION, frm=State.CHALLENGER, fps=1, expected=1,
                  ts=ts, effective_launch_date=LAUNCH_DAY)  # fmt: skip
        stage = StagePolicy(
            frozenset({Kind.ROLLBACK}) if name == "AdmissionPending" else frozenset(), frozenset()
        )
        return _raised(
            lambda: store._append(
                [head], stage=stage, _fixture_stage=True, **{**kwargs, "mode": WriterMode.DAILY}
            )
        )
    if name == "NominationRequiresPolicy":
        nom = mk(Kind.PROMOTE, State.CHALLENGER, frm=State.SHADOW, family=CHILD, expected=1, ts=ts)
        return _raised(lambda: store.append([nom], **{**kwargs, "mode": WriterMode.DAILY}))
    if name == "RuleSetPending":
        reset = mk(Kind.HWM_RESET, State.CHAMPION, frm=State.CHAMPION, fps=1, expected=1, ts=ts)
        return _raised(lambda: store.append([reset], **{**kwargs, "mode": WriterMode.OPERATOR_CLI}))
    if name == "PartialReplay":
        store.append(batch, **kwargs)
        other = mk(Kind.ATTEST, State.CHAMPION, frm=State.CHAMPION, fps=2, expected=1, ts=ts)
        return _raised(lambda: store.append([*batch, other], **kwargs))
    if name == "ReplayMismatch":
        store.append([demote_with(cause_code=CauseCode.VERDICT_FAIL)], **kwargs)
        return _raised(
            lambda: store.append(
                [demote_with(cause_code=CauseCode.EXEC_STORE_HALT_MIRROR)], **kwargs
            )
        )
    if name == "KindRefused":
        return _raised(lambda: store.append(batch, **{**kwargs, "mode": WriterMode.BOOTSTRAP}))
    if name == "ModeNotConcrete":
        return _raised(lambda: store.append(batch, **{**kwargs, "mode": "INTRADAY"}))
    if name == "RowRefused":
        return _raised(lambda: store.append([], **kwargs))
    if name == "CasMismatch":
        return _raised(
            lambda: store.append([demote(expected=0)], **{**kwargs, "expected_prior_seq": 0})
        )
    if name == "ClockRefused":
        return _raised(lambda: store.append(batch, **{**kwargs, "now_ns": NOW}))
    if name == "FoldRefused":
        orphan = mk(Kind.DEMOTE, State.HALTED, frm=State.CHAMPION, family=CHILD, expected=1, ts=ts)
        return _raised(lambda: store.append([orphan], **kwargs))
    if name == "ValidateRefused":
        stray = mk(
            Kind.ATTEST,
            State.CHAMPION,
            frm=State.CHAMPION,
            fps=1,
            expected=1,
            ts=ts,
            attest_valid_until_ns=ts + 9 * 3_600 * SEC,
        )  # beyond the validity ceiling
        return _raised(lambda: store.append([stray], **kwargs))
    if name == "ChainRefused":
        return _raised(lambda: store.append([demote(fps=9)], **kwargs))
    if name == "StoreBusy":
        monkeypatch.setattr(rs, "WRITER_BUSY_TIMEOUT_S", 0.05)
        holder = store._open()
        holder.execute("BEGIN IMMEDIATE")
        try:
            return _raised(lambda: store.append(batch, **kwargs))
        finally:
            holder.execute("ROLLBACK")
            holder.close()
    assert name == "StoreDrifted", name
    conn = raw(store)
    conn.execute("DROP TRIGGER transitions_no_update")
    conn.commit()
    conn.close()
    return _raised(lambda: store.append(batch, **kwargs))


def _raised(call: Any) -> RegistryRefused:
    with pytest.raises(RegistryRefused) as info:
        call()
    return info.value


_REFUSAL_REASONS: Final = {
    "StageNotCanonical": RefusalReason.STAGE_NOT_CANONICAL,
    "WideningNotEnabled": RefusalReason.WIDENING_KIND_NOT_ENABLED,
    "AdmissionPending": RefusalReason.ADMISSION_PENDING,
    "NominationRequiresPolicy": RefusalReason.ADMISSION_PENDING,
    "RuleSetPending": RefusalReason.ADMISSION_PENDING,
    "PartialReplay": RefusalReason.ENGINE_INCONSISTENCY,
    "ReplayMismatch": RefusalReason.ENGINE_INCONSISTENCY,
    "KindRefused": RefusalReason.ENGINE_INCONSISTENCY,
    "ModeNotConcrete": RefusalReason.ENGINE_INCONSISTENCY,
    "RowRefused": RefusalReason.ENGINE_INCONSISTENCY,
    "CasMismatch": RefusalReason.ENGINE_INCONSISTENCY,
    "ClockRefused": RefusalReason.CLOCK_INVALID,
    "FoldRefused": RefusalReason.FAMILY_NOT_INTRODUCED,
    "ValidateRefused": RefusalReason.ENGINE_INCONSISTENCY,
    "ChainRefused": RefusalReason.CHAIN_BROKEN,
    "StoreBusy": RefusalReason.REGISTRY_UNREADABLE,
    "StoreDrifted": RefusalReason.REGISTRY_UNREADABLE,
}


def test_every_refusal_class_is_raised_with_its_closed_reason() -> None:
    """The table covers every concrete refusal class (``StoreUnavailable`` is only their base)."""
    classes = {
        n for n, c in vars(rs).items()
        if isinstance(c, type)
        and issubclass(c, RegistryRefused)
        and c not in {RegistryRefused, StoreUnavailable}
    }  # fmt: skip
    assert classes == set(_REFUSAL_REASONS)


@pytest.mark.parametrize("name", sorted(_REFUSAL_REASONS))
def test_each_refusal_is_triggered_and_carries_its_reason(
    name: str, store: RegistryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = _trigger(name, store, monkeypatch)
    assert type(error).__name__ == name
    assert error.reason is _REFUSAL_REASONS[name]
