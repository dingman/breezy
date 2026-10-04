"""ARCH-0 seam 3a: pins.py literals and the frozen-root-manifest tests (AC 25, AC 31).

Bounds below are an independent literal copy of ARCH 4.5 as amended by E-11
(AUTONOMY_ARCHITECTURE.md:903-940; reviews/ARCH-ERRATA-rev9_2.md E-11, E-14).
The Kind-set check (`test_enabled_widening_kinds_subset_of_widening_kinds`) landed with seam 6b.
"""

from __future__ import annotations

import ast
import datetime as dt
import hashlib
import subprocess
import sys
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

import pytest

from breezy.persistence.autonomy import closure_manifest, pins
from breezy.persistence.autonomy.closure import closure_from_grimp, closure_sha256
from breezy.persistence.autonomy.schemas import Kind
from breezy.persistence.autonomy.transitions import WIDENING_KINDS
from tests.support.entry_points import REPO_ROOT

PKG: Final[str] = "breezy.persistence.autonomy"
PINS_PATH: Final[Path] = Path(pins.__file__)
PINS_REL: Final[str] = "src/breezy/persistence/autonomy/pins.py"
BASE_REF: Final[str] = "origin/feat/data-capture-and-risk"
SCHEDULE_POLL_S: Final[int] = 60  # ARCH G40: the supervisor schedule poll.


def _public(module: Any) -> dict[str, Any]:
    return {n: getattr(module, n) for n in dir(module) if n.isupper()}


# --------------------------------------------------------------------------- shape (AC 25)


def test_pins_imports_nothing_except_typing_and_mappingproxytype() -> None:
    tree = ast.parse(PINS_PATH.read_text(encoding="utf-8"))
    imports = [n for n in ast.walk(tree) if isinstance(n, ast.Import | ast.ImportFrom)]
    for node in imports:
        assert isinstance(node, ast.ImportFrom)
        assert node.level == 0
        if node.module == "typing":
            assert all(a.name == "Final" for a in node.names)
        else:
            assert node.module == "types"
            assert [a.name for a in node.names] == ["MappingProxyType"]


_LITERAL_CALLS: Final[frozenset[str]] = frozenset({"frozenset", "MappingProxyType"})


def _is_literal(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Tuple | ast.Set):
        return all(_is_literal(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return all(k is not None and _is_literal(k) for k in node.keys) and all(
            _is_literal(v) for v in node.values
        )
    if isinstance(node, ast.Call):
        return (
            isinstance(node.func, ast.Name)
            and node.func.id in _LITERAL_CALLS
            and not node.keywords
            and all(_is_literal(a) for a in node.args)
        )
    return False


def test_pins_holds_literals_only() -> None:
    tree = ast.parse(PINS_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Import | ast.ImportFrom):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # module docstring
        assert isinstance(node, ast.AnnAssign), ast.dump(node)
        assert isinstance(node.target, ast.Name) and node.target.id.isupper()
        assert node.value is not None and _is_literal(node.value), node.target.id


def test_pins_has_no_self_heal_constants_and_no_operator_control_names() -> None:
    names = set(_public(pins))
    assert not {n for n in names if n.startswith("SELF_HEAL")}  # E-11
    for forbidden in ("DAILY_BUDGET", "PER_POSITION", "MAX_DAILY"):
        assert not {n for n in names if forbidden in n}, forbidden


def test_empty_pins_at_arch0() -> None:
    assert pins.ENGINE_SOURCE_SHA256 == frozenset()
    assert pins.PRODUCER_SOURCE_SHA256 == {}
    assert isinstance(pins.PRODUCER_SOURCE_SHA256, MappingProxyType)
    assert pins.REVOKED_SOURCE_SHA256 == frozenset()
    assert pins.ENABLED_WIDENING_KINDS == frozenset()
    assert pins.POLICY_RULING_PIN == ()
    assert pins.BOOTSTRAPPED_ROOT_MANIFEST_SHA256 == {}
    assert isinstance(pins.BOOTSTRAPPED_ROOT_MANIFEST_SHA256, MappingProxyType)


def test_literal_collections_have_immutable_types() -> None:
    for name, value in _public(pins).items():
        assert isinstance(value, str | int | bool | tuple | frozenset | MappingProxyType), name


def test_literal_identity_pins() -> None:
    assert pins.LIVE_GATE_ROUTED_KINDS == frozenset({"forecast_quantile_ladder"})
    assert pins.DEMAND_WRITER_PRODUCER_IDS == ("aut6.intraday",)
    assert pins.ROOT_ARTEFACT_COMPONENT == "density_table"
    assert pins.BOOTSTRAP_SEED == (  # ARCH:472 and :737
        ("pm_us_crh_fq_v1", "CHAMPION"),
        ("pm_us_crh_v4", "RETIRED"),
        ("pm_us_crh_cont", "RETIRED"),
        ("pm_us_crh_v2", "RETIRED"),
    )
    assert pins.DEMAND_REASONS == frozenset({"integrity_floor"})
    assert pins.CAUSE_CODES == frozenset(
        {
            "verdict_fail",
            "exec_store_halt_mirror",
            "pair_cause_incoming",
            "pair_cause_outgoing",
            "prelaunch_precheck_failed",
            "engine_inconsistency",
            "infra_budget_exhausted",
            "model_budget_exhausted",
            "rollback_failed",
            "target_integrity",
            "drill_close_restore",
        }
    )


def test_bootstrap_seed_is_one_champion_and_unique_ids() -> None:
    ids = [family for family, _ in pins.BOOTSTRAP_SEED]
    assert len(ids) == len(set(ids))
    assert [s for _, s in pins.BOOTSTRAP_SEED].count("CHAMPION") == 1
    assert {s for _, s in pins.BOOTSTRAP_SEED} == {"CHAMPION", "RETIRED"}  # never HALTED


def test_default_restrictive_class_is_demote_or_halt_with_known_classes() -> None:
    table = pins.DEFAULT_RESTRICTIVE_CLASS
    assert isinstance(table, MappingProxyType)
    assert {a for a, _ in table.values()} == {"DEMOTE", "HALT"}
    assert {c for _, c in table.values()} <= {"RECOVERABLE_INFRA", "RECOVERABLE_MODEL", "TERMINAL"}
    assert table["live.sequential"] == ("HALT", "RECOVERABLE_MODEL")
    assert table["live.kill_clock"] == ("HALT", "TERMINAL")
    assert table["live.drawdown"] == ("HALT", "TERMINAL")
    assert not {"drill.inject", "drill.inject_halt", "DRILL_INJECT", "DRILL_INJECT_HALT"} & set(
        table
    )


def test_halt_reason_class_map_is_exact() -> None:
    # ARCH C5 "Exec-store halt mirror" table (AUTONOMY_ARCHITECTURE.md:699-706), row for row.
    expected: dict[str, str | None] = {
        "duplicate_fill": "INTEGRITY",
        "ambiguous_exit": "INTEGRITY",
        "halts_all": "INTEGRITY",
        "attributable_to_v4": None,
        "policy_halt:fee_schedule_drift": "TERMINAL",
        "policy_halt:*": "TERMINAL",
        "unreadable_or_unknown": "INTEGRITY",
    }
    assert isinstance(pins.HALT_REASON_CLASS_MAP, MappingProxyType)
    assert dict(pins.HALT_REASON_CLASS_MAP) == expected


# --------------------------------------------------------------------------- ceilings (ARCH 4.5)

#: name -> (relation, bound). `<=` is a ceiling, `>=` a floor, `==` an exact pin.
DAMPING: Final[dict[str, tuple[str, int]]] = {
    "RESUME_COOLDOWN_H": (">=", 24),
    "MAX_RECOVERABLE_RESUMES_PER_LINEAGE_14D": ("<=", 2),
    "MAX_INFRA_RESUMES_PER_VENUE_7D": ("<=", 3),
    "MAX_ROLLBACKS_PER_VENUE_30D": ("<=", 2),
    "MAX_SENDER_CHANGES_PER_VENUE_PER_DAY": ("<=", 2),
    "MIN_DAYS_BETWEEN_PROMOTES_PER_LINEAGE": (">=", 14),
    "MAX_NOMINATIONS_PER_LINEAGE_LIFETIME": ("<=", 4),
    "MAX_NOMINATIONS_PER_FORWARD_WINDOW": ("<=", 1),
    "MAX_MINTS_PER_LINEAGE_PER_DAY": ("<=", 1),
    "DRILL_BUDGET_PER_VENUE_30D": ("<=", 1),
}
OTHER: Final[dict[str, tuple[str, int]]] = {
    "ROLLBACK_MIN_DWELL_H": (">=", 24),
    "ROLLBACK_TARGET_MAX_AGE_D": ("<=", 30),
    "RELAUNCH_REQUEST_TTL_S": ("==", 120),
    "MIN_GATE_DECISIONS_CHANGED": (">=", 1),
    "MIN_CALIBRATION_BUCKETS": (">=", 1),
    "BOOTSTRAP_B_MAX": ("==", 524288),  # 2**19, AUT-4 r11 R4-8
    "DEADMAN_HORIZON_H": ("<=", 30),
    "MAX_VERDICT_VALIDITY_H": ("<=", 26),
    "ATTEST_PERIOD_H": ("<=", 6),
    "ATTEST_VERDICT_VALIDITY_H": ("<=", 8),
    "FORWARD_WINDOW_DAYS_MIN": ("==", 28),
    "FORWARD_WINDOW_DAYS_MAX": ("==", 120),
    "POST_STOP_RECONCILE_RUNTIME_S": ("<=", 120),
    "POSTSTOP_POSITIONS_MAX_PAGES": ("<=", 20),
    "ROOT_ADMIT_COOLDOWN_H": (">=", 24),
    "ALERT_DELIVERY_TIMEOUT_S": ("<=", 10),
    "ALERT_OUTBOX_MAX": ("<=", 256),
    "ALERT_OUTBOX_STALE_S": ("<=", 300),
    "HALT_MIRROR_MAX_AGE_S": ("<=", 180),
    "CANARY_RETRY_PERIOD_MIN": ("<=", 60),
    "ENGINE_HEARTBEAT_STALE_S": ("<=", 3600),
    "WATCH_TICK_STALE_S": ("<=", 180),
    "ALERT_CANARY_MAX_AGE_H": ("<=", 26),
    "DEMAND_FILE_MAX_BYTES": ("<=", 4096),
    "DEMAND_FILES_MAX": ("<=", 64),
    "DEMAND_INTEGRITY_RESERVED": (">=", 8),
    "ENGINE_LOCK_MAX_HOLD_S": ("==", 15),
    "WATCH_BUSY_TIMEOUT_MS": ("==", 250),
    "DRILL_CLOSE_RESTORES_PER_VENUE_PER_DAY": ("==", 1),
    "DRAWDOWN_INERT_ALERT_MIN_FILLS": ("==", 10),
    "ROW_TS_MAX_SKEW_S": ("==", 300),
    "EXPORT_FIRST_DUE_H": ("==", 26),
    "INTRADAY_ATTEST_VERDICT_PERIOD_MIN": ("<=", 60),
    "INTRADAY_ENGINE_OFFSET_S": ("==", 150),
}


def _check(name: str, relation: str, bound: int) -> None:
    value = getattr(pins, name)
    assert type(value) is int, name  # no bool, no float
    assert {"<=": value <= bound, ">=": value >= bound, "==": value == bound}[relation], (
        f"{name}={value} violates {relation} {bound}"
    )


@pytest.mark.parametrize("facet", ["ceilings"])
def test_damping_ceilings(facet: str) -> None:
    assert facet == "ceilings"
    for name, (relation, bound) in DAMPING.items():
        _check(name, relation, bound)
    assert pins.MAX_RECOVERABLE_RESUMES_PER_LINEAGE_14D >= 0
    assert pins.DRILL_BUDGET_PER_VENUE_30D == 1  # one drill, ever, per 30 d


def test_pins_ceilings_within_arch_bounds() -> None:
    for name, (relation, bound) in OTHER.items():
        _check(name, relation, bound)
    assert Decimal(pins.ATTEST_MARGIN_H) >= Decimal("0.5")
    assert pins.ALERT_CLAIM_STALE_S >= 3 * pins.ALERT_DELIVERY_TIMEOUT_S
    assert pins.DEMAND_INTEGRITY_RESERVED < pins.DEMAND_FILES_MAX


def test_every_arch_ceiling_constant_exists() -> None:
    expected = (
        set(DAMPING)
        | set(OTHER)
        | {
            "DRILL_MIN_DRAWDOWN_HEADROOM_FRAC",
            "ATTEST_MARGIN_H",
            "ALERT_CLAIM_STALE_S",
            "ROOT_ADMIT_ENABLED_CEILING",
            "DRAWDOWN_INERT_ALERT_CEILING",
            "RELAUNCH_REQUEST_TTL_S",
            "BOOTSTRAP_SEED",
            "DEMAND_WRITER_PRODUCER_IDS",
            "DEFAULT_RESTRICTIVE_CLASS",
        }
    )
    missing = {n for n in expected if not hasattr(pins, n)}
    assert not missing


def test_rollback_dwell_age_and_drill_headroom_ceilings() -> None:
    assert pins.ROLLBACK_MIN_DWELL_H >= 24
    assert pins.ROLLBACK_TARGET_MAX_AGE_D <= 30
    assert isinstance(pins.DRILL_MIN_DRAWDOWN_HEADROOM_FRAC, str)  # decimal string, never a float
    assert Decimal(pins.DRILL_MIN_DRAWDOWN_HEADROOM_FRAC) >= Decimal("0.5")
    assert Decimal(pins.DRILL_MIN_DRAWDOWN_HEADROOM_FRAC) <= 1


@pytest.mark.parametrize("facet", ["pins_invariant"])
def test_attest_cadence_has_no_expiry_gap(facet: str) -> None:
    assert facet == "pins_invariant"
    l_max_h = (
        Decimal(pins.INTRADAY_ATTEST_VERDICT_PERIOD_MIN) / 60
        + Decimal(pins.INTRADAY_ENGINE_OFFSET_S) / 3600
    )
    total = Decimal(pins.ATTEST_PERIOD_H) + l_max_h + Decimal(pins.ATTEST_MARGIN_H)
    assert total <= Decimal(pins.ATTEST_VERDICT_VALIDITY_H)
    assert Decimal(pins.ATTEST_VERDICT_VALIDITY_H) - total >= Decimal("0.4")  # ARCH: >= 0.46 h


def test_request_ttl_covers_two_schedule_polls() -> None:
    assert pins.RELAUNCH_REQUEST_TTL_S >= 2 * SCHEDULE_POLL_S


def _enabled_outside_widening(enabled: frozenset[str]) -> frozenset[str]:
    """Members of ``enabled`` that are not the value of a ``WIDENING_KINDS`` kind."""
    return enabled - {kind.value for kind in WIDENING_KINDS}


def test_enabled_widening_kinds_subset_of_widening_kinds() -> None:
    assert _enabled_outside_widening(pins.ENABLED_WIDENING_KINDS) == frozenset()
    assert pins.ENABLED_WIDENING_KINDS <= {kind.value for kind in Kind}
    # positive controls: a restrictive kind, a neutral kind and a misspelling are all outside
    for planted in ("DEMOTE", "HWM_RESET", "promote", "NOT_A_KIND"):
        assert _enabled_outside_widening(frozenset({"RESUME", planted})) == {planted}


def test_root_admit_ceiling_committed_false() -> None:
    assert pins.ROOT_ADMIT_ENABLED_CEILING is False


def test_root_admit_enabled_requires_ceiling_true() -> None:
    enabled_root_admit = any(str(k).lower() == "root_admit" for k in pins.ENABLED_WIDENING_KINDS)
    assert pins.ROOT_ADMIT_ENABLED_CEILING or not enabled_root_admit


def test_drawdown_inert_ceiling_is_pins_literal_not_policy_key() -> None:  # [pins]
    tree = ast.parse(PINS_PATH.read_text(encoding="utf-8"))
    nodes = {
        n.target.id: n.value
        for n in tree.body
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
    }
    ceiling = nodes["DRAWDOWN_INERT_ALERT_CEILING"]
    assert isinstance(ceiling, ast.Constant) and ceiling.value == "0.5"
    assert pins.DRAWDOWN_INERT_ALERT_CEILING == "0.5"
    assert pins.DRAWDOWN_INERT_ALERT_MIN_FILLS == 10


def test_schedule_constants_equal_supervisor() -> None:
    from breezy.runtime import trade_supervisor_core as sup

    def parse(value: str) -> dt.time:
        return dt.time.fromisoformat(value)

    assert parse(pins.SCHEDULE_STOP_UTC) == sup.STOP_PRIOR_UTC
    assert parse(pins.SCHEDULE_LAUNCH_UTC) == sup.LAUNCH_UTC
    assert parse(pins.SCHEDULE_LAUNCH_WINDOW_END_UTC) == sup.LAUNCH_WINDOW_END_UTC
    assert (pins.SCHEDULE_STOP_UTC, pins.SCHEDULE_LAUNCH_UTC) == ("16:40", "16:50")
    assert pins.SCHEDULE_LAUNCH_WINDOW_END_UTC == "17:00"  # V6


# --------------------------------------------------------------------------- AC 31: frozen roots


def _manifest_mismatches(pin: Mapping[str, str], repo_root: Path) -> list[str]:
    bad: list[str] = []
    for family_id, sha in sorted(pin.items()):
        path = repo_root / "deploy" / "families" / f"{family_id}.json"
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        if digest != sha:
            bad.append(family_id)
    return bad


def test_bootstrapped_root_manifests_unchanged() -> None:
    # Hashes through REPO_ROOT (V29), never an absolute path, so a worktree hashes its own files.
    assert _manifest_mismatches(pins.BOOTSTRAPPED_ROOT_MANIFEST_SHA256, REPO_ROOT) == []


def test_manifest_check_flags_a_wrong_sha_a_missing_file_and_accepts_the_real_one() -> None:
    real = REPO_ROOT / "deploy" / "families" / "pm_us_crh_fq_v1.json"
    good = hashlib.sha256(real.read_bytes()).hexdigest()
    assert _manifest_mismatches({"pm_us_crh_fq_v1": good}, REPO_ROOT) == []
    assert _manifest_mismatches({"pm_us_crh_fq_v1": "0" * 64}, REPO_ROOT) == ["pm_us_crh_fq_v1"]
    assert _manifest_mismatches({"no_such_family": good}, REPO_ROOT) == ["no_such_family"]


def test_manifest_check_reads_the_given_root_not_an_absolute_path(tmp_path: Path) -> None:
    (tmp_path / "deploy" / "families").mkdir(parents=True)
    body = b'{"x": 1}'
    (tmp_path / "deploy" / "families" / "fam.json").write_bytes(body)
    assert _manifest_mismatches({"fam": hashlib.sha256(body).hexdigest()}, tmp_path) == []
    assert _manifest_mismatches({"fam": hashlib.sha256(b"y").hexdigest()}, tmp_path) == ["fam"]


def test_wrong_sha_pin_row_turns_the_real_test_red(monkeypatch: pytest.MonkeyPatch) -> None:
    planted = MappingProxyType({"pm_us_crh_fq_v1": "0" * 64})
    monkeypatch.setattr(pins, "BOOTSTRAPPED_ROOT_MANIFEST_SHA256", planted)
    with pytest.raises(AssertionError):
        test_bootstrapped_root_manifests_unchanged()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


class BaseUnavailable(AssertionError):
    """The append-only base could not be established: a FAIL, never a skip."""


def _git_ok(repo: Path, *args: str) -> str:
    done = _git(repo, *args)
    if done.returncode != 0:
        raise BaseUnavailable(f"git {args[0]} failed")
    return done.stdout.strip()


def _pin_rows_from_source(source: str) -> dict[str, str]:
    tree = ast.parse(source)
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "BOOTSTRAPPED_ROOT_MANIFEST_SHA256"
            and isinstance(node.value, ast.Call)
        ):
            rows = ast.literal_eval(node.value.args[0])
            assert isinstance(rows, dict)
            return {str(k): str(v) for k, v in rows.items()}
    raise BaseUnavailable("pin assignment not found at base")


def _base_pin_rows(repo: Path, *, base_ref: str = BASE_REF) -> dict[str, str]:
    """Rows of the pin at ``git merge-base HEAD <base_ref>``; absent pins.py is empty."""
    _git_ok(repo, "rev-parse", "--verify", base_ref)
    if _git_ok(repo, "rev-parse", "--is-shallow-repository") == "true":
        raise BaseUnavailable("shallow repository: the merge-base is not trustworthy")
    base = _git_ok(repo, "merge-base", "HEAD", base_ref)
    if _git_ok(repo, "ls-tree", base, "--", PINS_REL) == "":
        return {}
    return _pin_rows_from_source(_git_ok(repo, "show", f"{base}:{PINS_REL}"))


def _removed_or_changed(base: Mapping[str, str], current: Mapping[str, str]) -> list[str]:
    return sorted(k for k, v in base.items() if current.get(k) != v)


def test_bootstrapped_root_pin_is_append_only() -> None:
    base = _base_pin_rows(REPO_ROOT)
    current = dict(pins.BOOTSTRAPPED_ROOT_MANIFEST_SHA256)
    assert _removed_or_changed(base, current) == []


def _make_repo(path: Path, *, with_pins: str | None) -> None:
    path.mkdir(parents=True)
    assert _git(path, "init", "-q", "-b", "main").returncode == 0
    (path / "README").write_text("x")
    _git(path, "add", "README")
    assert _git(path, "commit", "-qm", "one").returncode == 0
    ref = ("update-ref", "refs/remotes/origin/feat/data-capture-and-risk", "HEAD")
    assert _git(path, *ref).returncode == 0
    if with_pins is not None:
        target = path / PINS_REL
        target.parent.mkdir(parents=True)
        target.write_text(with_pins)
        _git(path, "add", PINS_REL)
    # Advance HEAD past the base so the merge-base is the earlier commit.
    (path / "README").write_text("y")
    _git(path, "add", "README")
    assert _git(path, "commit", "-qm", "two").returncode == 0


_PIN_SRC = (
    "from types import MappingProxyType\n"
    'BOOTSTRAPPED_ROOT_MANIFEST_SHA256: Final = MappingProxyType({"fam": "' + "a" * 64 + '"})\n'
)


def test_pin_absent_at_base_reads_as_empty(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _make_repo(repo, with_pins=None)
    assert _base_pin_rows(repo) == {}


def test_pin_rows_are_read_from_the_base_commit(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _make_repo(repo, with_pins=None)
    # Commit a pins.py, move the base ref onto it, then advance HEAD.
    target = repo / PINS_REL
    target.parent.mkdir(parents=True)
    target.write_text(_PIN_SRC)
    _git(repo, "add", PINS_REL)
    assert _git(repo, "commit", "-qm", "pins").returncode == 0
    _git(repo, "update-ref", "refs/remotes/origin/feat/data-capture-and-risk", "HEAD")
    (repo / "README").write_text("z")
    _git(repo, "add", "README")
    assert _git(repo, "commit", "-qm", "three").returncode == 0
    base = _base_pin_rows(repo)
    assert base == {"fam": "a" * 64}
    assert _removed_or_changed(base, {"fam": "a" * 64, "new": "b" * 64}) == []  # append is fine
    assert _removed_or_changed(base, {}) == ["fam"]  # removal detected
    assert _removed_or_changed(base, {"fam": "c" * 64}) == ["fam"]  # change detected


def test_unavailable_base_ref_fails_never_skips(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    assert _git(repo, "init", "-q", "-b", "main").returncode == 0
    (repo / "f").write_text("x")
    _git(repo, "add", "f")
    assert _git(repo, "commit", "-qm", "one").returncode == 0
    with pytest.raises(BaseUnavailable):
        _base_pin_rows(repo)


def test_shallow_repository_fails_never_skips(tmp_path: Path) -> None:
    src = tmp_path / "src"
    _make_repo(src, with_pins=None)
    clone = tmp_path / "clone"
    done = subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{src}", str(clone)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    ref = ("update-ref", "refs/remotes/origin/feat/data-capture-and-risk", "HEAD")
    assert _git(clone, *ref).returncode == 0
    assert _git_ok(clone, "rev-parse", "--is-shallow-repository") == "true"
    with pytest.raises(BaseUnavailable):
        _base_pin_rows(clone)


def test_merge_base_failure_fails_never_reads_as_empty(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _make_repo(repo, with_pins=None)
    # A ref that resolves but whose merge-base cannot be computed: unrelated history.
    assert _git(repo, "checkout", "-q", "--orphan", "other").returncode == 0
    (repo / "o").write_text("o")
    _git(repo, "add", "o")
    assert _git(repo, "commit", "-qm", "orphan").returncode == 0
    with pytest.raises(BaseUnavailable):
        _base_pin_rows(repo)  # merge-base of unrelated histories exits non-zero


def test_bootstrapped_root_pin_covers_bootstrap_seed_once_nonempty() -> None:
    assert _seed_gaps(pins.BOOTSTRAPPED_ROOT_MANIFEST_SHA256) == []


def _seed_gaps(pin: Mapping[str, str]) -> list[str]:
    """Seed ids missing from a non-empty pin. An empty pin is the pre-bootstrap state."""
    if not pin:
        return []
    return sorted(family for family, _ in pins.BOOTSTRAP_SEED if family not in pin)


def test_seed_coverage_check_has_teeth() -> None:
    assert _seed_gaps({}) == []
    assert _seed_gaps({"pm_us_crh_fq_v1": "a" * 64}) == [
        "pm_us_crh_cont",
        "pm_us_crh_v2",
        "pm_us_crh_v4",
    ]
    assert _seed_gaps({f: "a" * 64 for f, _ in pins.BOOTSTRAP_SEED}) == []


def test_every_seed_id_has_a_committed_manifest() -> None:
    for family, _ in pins.BOOTSTRAP_SEED:
        assert (REPO_ROOT / "deploy" / "families" / f"{family}.json").is_file(), family


# --- Seam 3b: code-identity pins and the closure manifest (ARCH 4.3; AC 25) ----------------

_MANIFEST_PATH: Final[Path] = Path(closure_manifest.__file__)


def _unpinned_components(
    manifest: Mapping[str, tuple[str, ...]],
    pinned: frozenset[str],
    *,
    src_root: Path,
) -> list[str]:
    """Components whose current closure hash is in no pin set (a reviewed pin is then due)."""
    return sorted(
        c for c in manifest if closure_sha256(c, src_root=src_root, modules=manifest) not in pinned
    )


def _all_pinned() -> frozenset[str]:
    return (
        pins.ENGINE_SOURCE_SHA256
        | frozenset(pins.PRODUCER_SOURCE_SHA256.values())
        | pins.REVOKED_SOURCE_SHA256
    )


def test_code_identity_pins_cover_import_closure() -> None:
    src = REPO_ROOT / "src"
    assert _unpinned_components(closure_manifest.CLOSURE_MODULES, _all_pinned(), src_root=src) == []
    # No pin may be both live and revoked.
    assert pins.ENGINE_SOURCE_SHA256 & pins.REVOKED_SOURCE_SHA256 == frozenset()
    assert set(pins.PRODUCER_SOURCE_SHA256.values()) & pins.REVOKED_SOURCE_SHA256 == frozenset()


def test_pin_coverage_check_has_teeth(tmp_path: Path) -> None:
    root = tmp_path / "src"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_bytes(b"")
    (root / "pkg" / "entry.py").write_bytes(b"X = 1\n")
    manifest = {"pkg.entry": ("pkg", "pkg.entry")}
    digest = closure_sha256("pkg.entry", src_root=root, modules=manifest)
    assert _unpinned_components(manifest, frozenset(), src_root=root) == ["pkg.entry"]
    assert _unpinned_components(manifest, frozenset({digest}), src_root=root) == []
    (root / "pkg" / "entry.py").write_bytes(b"X = 2\n")  # an edit forces a reviewed pin
    assert _unpinned_components(manifest, frozenset({digest}), src_root=root) == ["pkg.entry"]


def _pin_set_from_source(source: str, name: str) -> frozenset[str]:
    for node in ast.parse(source).body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and isinstance(node.value, ast.Call)
        ):
            args = node.value.args
            return frozenset(str(x) for x in ast.literal_eval(args[0])) if args else frozenset()
    raise BaseUnavailable(f"{name} not found at base")


def _base_engine_pins(repo: Path, *, base_ref: str = BASE_REF) -> frozenset[str]:
    _git_ok(repo, "rev-parse", "--verify", base_ref)
    if _git_ok(repo, "rev-parse", "--is-shallow-repository") == "true":
        raise BaseUnavailable("shallow repository: the merge-base is not trustworthy")
    base = _git_ok(repo, "merge-base", "HEAD", base_ref)
    if _git_ok(repo, "ls-tree", base, "--", PINS_REL) == "":
        return frozenset()
    return _pin_set_from_source(_git_ok(repo, "show", f"{base}:{PINS_REL}"), "ENGINE_SOURCE_SHA256")


def _dropped_without_revocation(
    base: frozenset[str], current: frozenset[str], revoked: frozenset[str]
) -> list[str]:
    return sorted(base - current - revoked)


def test_engine_pin_history_retained() -> None:
    base = _base_engine_pins(REPO_ROOT)
    assert (
        _dropped_without_revocation(base, pins.ENGINE_SOURCE_SHA256, pins.REVOKED_SOURCE_SHA256)
        == []
    )


def test_engine_pin_removal_is_only_allowed_by_revocation() -> None:
    a, b = "a" * 64, "b" * 64
    assert _dropped_without_revocation(frozenset({a, b}), frozenset({a, b}), frozenset()) == []
    assert _dropped_without_revocation(frozenset({a}), frozenset({a, b}), frozenset()) == []
    assert _dropped_without_revocation(frozenset({a, b}), frozenset({a}), frozenset()) == [b]
    assert _dropped_without_revocation(frozenset({a, b}), frozenset({a}), frozenset({b})) == []


def test_engine_pin_base_reads_the_base_commit_and_fails_never_skips(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _make_repo(repo, with_pins=None)
    assert _base_engine_pins(repo) == frozenset()  # absent at base reads as empty
    target = repo / PINS_REL
    target.parent.mkdir(parents=True)
    target.write_text(
        "ENGINE_SOURCE_SHA256: Final[frozenset[str]] = frozenset({'" + "a" * 64 + "'})\n"
    )
    _git(repo, "add", PINS_REL)
    assert _git(repo, "commit", "-qm", "pins").returncode == 0
    _git(repo, "update-ref", "refs/remotes/origin/feat/data-capture-and-risk", "HEAD")
    (repo / "README").write_text("z")
    _git(repo, "add", "README")
    assert _git(repo, "commit", "-qm", "three").returncode == 0
    assert _base_engine_pins(repo) == frozenset({"a" * 64})
    with pytest.raises(BaseUnavailable):
        _base_engine_pins(repo, base_ref="origin/does-not-exist")


def _manifest_drift(manifest: Mapping[str, tuple[str, ...]]) -> list[str]:
    return sorted(c for c, mods in manifest.items() if closure_from_grimp(c) != tuple(mods))


def test_closure_manifest_equals_grimp_closure() -> None:
    assert _manifest_drift(closure_manifest.CLOSURE_MODULES) == []
    # Positive controls: a stale list and a list that drops an import are both drift.
    live = closure_from_grimp(f"{PKG}.plugin")
    assert _manifest_drift({f"{PKG}.plugin": live}) == []
    assert _manifest_drift({f"{PKG}.plugin": live[:-1]}) == [f"{PKG}.plugin"]
    assert _manifest_drift({f"{PKG}.plugin": (*live, f"{PKG}.single_read")}) == [f"{PKG}.plugin"]


def _load_regen() -> Any:
    from scripts.ci import regen_closure_manifest

    return regen_closure_manifest


def test_regen_output_is_literal_and_reproducible() -> None:
    regen = _load_regen()
    sample = {
        "zeta.entry": ("zeta", "zeta.entry"),
        "alpha.entry": ("alpha.b", "alpha", "alpha.entry"),
        "empty.entry": (),
    }
    first = regen.render_manifest(sample)
    assert regen.render_manifest(dict(reversed(list(sample.items())))) == first
    # Literal: the module is a docstring, imports and ONE annotated MappingProxyType literal.
    tree = ast.parse(first)
    assigns = [n for n in tree.body if isinstance(n, ast.AnnAssign)]
    assert len(assigns) == 1
    value = assigns[0].value
    assert isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
    assert value.func.id == "MappingProxyType"
    parsed = ast.literal_eval(value.args[0])
    assert parsed == {
        "alpha.entry": ("alpha", "alpha.b", "alpha.entry"),  # sorted
        "empty.entry": (),
        "zeta.entry": ("zeta", "zeta.entry"),
    }
    assert list(parsed) == sorted(parsed)  # keys sorted
    assert not any(isinstance(n, ast.FunctionDef | ast.ClassDef) for n in tree.body)


def test_regen_output_is_ruff_format_stable() -> None:
    regen = _load_regen()
    text = regen.render_manifest({"a.entry": ("a", "a.entry"), "b.entry": ()})
    done = subprocess.run(
        [str(Path(sys.executable).parent / "ruff"), "format", "--stdin-filename", "m.py", "-"],
        input=text,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout == text


def test_committed_manifest_is_exactly_the_regen_output() -> None:
    regen = _load_regen()
    committed = _MANIFEST_PATH.read_text(encoding="utf-8")
    assert regen.render_manifest(closure_manifest.CLOSURE_MODULES) == committed
    # Reproducible from the graph: regenerating from the manifest's own entries changes nothing.
    assert regen.regenerate(list(closure_manifest.CLOSURE_MODULES)) == committed


def test_closure_manifest_module_imports_only_typing_and_mappingproxytype() -> None:
    tree = ast.parse(_MANIFEST_PATH.read_text(encoding="utf-8"))
    imported = {(n.module or "") for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    assert imported <= {"types", "typing"}


def test_regen_check_mode_exits_nonzero_on_drift(tmp_path: Path) -> None:
    regen = _load_regen()
    stale = tmp_path / "closure_manifest.py"
    stale.write_text("# stale\n", encoding="utf-8")
    assert regen.main(["--check", "--target", str(stale)]) == 1
    fresh = tmp_path / "fresh.py"
    fresh.write_text(regen.render_manifest({}), encoding="utf-8")
    assert regen.main(["--check", "--target", str(fresh)]) == 0
    assert regen.main(["--target", str(stale)]) == 0  # write mode rewrites
    assert stale.read_text(encoding="utf-8") == regen.render_manifest({})
