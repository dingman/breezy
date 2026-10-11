"""TE-2 WP0 (RED): git port, Phase B gates and the reflog pin resolver (plan tests 37-39, 44).

Fakes are paired with the production default path: the real ``SubprocessGit`` over hermetic tmp
repos and the real committed reflog snapshot (L-55).
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import pytest

from scripts.analysis.fq_loss_taxonomy_core import reproduction_gate
from scripts.analysis.fq_loss_taxonomy_inputs import (
    Boot,
    PinConfig,
    PinReason,
    RefusalReason,
    SnapshotShaMismatch,
    SubprocessGit,
    phase_b_refusals,
    pin_label,
    post_hoc_violations,
    refreeze_status,
    resolve_pins,
)
from tests.support.te2_fixtures import git_cmd, sha256_text, tmp_git_repo

_REAL_SNAPSHOT = (
    Path(__file__).resolve().parents[2]
    / "docs/evidence/te2/REFLOG_SNAPSHOT_2026-10-01_to_10-06.txt"
)
_REAL_SNAPSHOT_SHA = "f359e070c2334a31252782fbf949643dfac84bba1c0992fda73b7ef9094e427d"
_P7_BOOT_TIMES = [
    "2026-10-01T15:12:02", "2026-10-01T16:01:58", "2026-10-01T16:50:11", "2026-10-02T16:50:39",
    "2026-10-02T20:05:26", "2026-10-02T20:55:21", "2026-10-03T16:50:45", "2026-10-04T16:50:12",
    "2026-10-05T16:50:40",
]  # fmt: skip
_P7_COMMITS = [
    "60290e9ddd29", "99067d4a9e7a", "99067d4a9e7a", "7dfd1af114c1", "6e99a7ae2dbe",
    "3eb4a1085dbf", "f45f5a6558cd", "c893e13e603e", "4ba7f10cd1f6",
]  # fmt: skip
_P7_NEAR = [False, True, False, False, True, True, False, False, False]
_SNAP_ROWS = [
    ("2026-10-01T13:39:52", "000000000000", "60290e9ddd29"),
    ("2026-10-01T16:01:36", "60290e9ddd29", "99067d4a9e7a"),
    ("2026-10-02T16:00:52", "99067d4a9e7a", "7dfd1af114c1"),
    ("2026-10-02T20:05:01", "7dfd1af114c1", "6e99a7ae2dbe"),
    ("2026-10-02T20:54:53", "6e99a7ae2dbe", "3eb4a1085dbf"),
    ("2026-10-03T15:01:45", "3eb4a1085dbf", "f45f5a6558cd"),
    ("2026-10-04T16:28:31", "f45f5a6558cd", "c893e13e603e"),
    ("2026-10-04T17:11:31", "c893e13e603e", "2be63d85aaaa"),  # carries a rebased 4ac87414
    ("2026-10-04T22:35:21", "2be63d85aaaa", "4ba7f10cd1f6"),
]  # fmt: skip
_TREES = {"60290e9ddd29": "T1", "c893e13e603e": "T3", "4ba7f10cd1f6": "T4"}
_CFG = PinConfig("m", "a", ("src/x",))


class _FakeGit:
    """Dict-backed git. ``porcelain_clean`` asserts it receives exactly the pinned paths."""

    def __init__(
        self,
        blobs: dict[str, str] | None = None,
        *,
        pinned: Iterable[str] = (),
        clean: bool = True,
        ancestors: Any = (),
        bad_blob_commit: str | None = None,
    ) -> None:
        self.blobs, self.pinned, self.clean = blobs or {}, tuple(pinned), clean
        self.ancestors, self.bad = set(ancestors), bad_blob_commit
        self.porcelain_calls: list[tuple[str, ...]] = []

    def head_blob_sha256(self, path: str) -> str:
        return self.blobs[path]

    def porcelain_clean(self, paths: Sequence[str]) -> bool:
        self.porcelain_calls.append(tuple(paths))
        assert tuple(paths) == self.pinned, "the clean check must cover exactly the pinned paths"
        return self.clean

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return (ancestor, descendant) in self.ancestors

    def blob_sha256(self, commit: str, path: str) -> str | None:
        return "bad" if commit == self.bad else {"m": "logged-m", "a": "logged-a"}[path]

    def show_blob(self, commit: str, path: str) -> bytes:
        raise AssertionError("not used")

    def tree_shas(self, commit: str, paths: Sequence[str]) -> tuple[str, ...]:
        return (_TREES.get(commit, "T2"),)

    def log_commits(
        self, paths: Sequence[str], until: str, *, since: str | None = None
    ) -> tuple[str, ...]:
        raise AssertionError("not used")


def _snapshot(path: Path, rows: Sequence[tuple[str, str, str]] = tuple(_SNAP_ROWS)) -> str:
    body = "".join(f"{ts}+00:00 old={old} new={new} commit: x\n" for ts, old, new in rows)
    text = f"# Captured\n# source: .git/logs/HEAD\n{body}# source: .git/logs/refs/heads/b\n{body}"
    path.write_text(text)
    return sha256_text(text)


def _boot(number: int, stamp: str, manifest: str = "logged-m", artefact: str = "logged-a") -> Boot:
    when = dt.datetime.fromisoformat(stamp).replace(tzinfo=dt.UTC)
    return Boot(number, when, manifest, artefact)


def _p7_boots() -> list[Boot]:
    return [_boot(i + 1, t) for i, t in enumerate(_P7_BOOT_TIMES)]


def test_phase_b_refuses_without_head_blob_pins_clean_path_and_ancestor_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pins = {"scripts/a.py": "aa", "scripts/b.py": "bb"}
    good = _FakeGit(pins, pinned=pins, ancestors={("PRE", "HEAD")})

    assert phase_b_refusals(pins, "PRE", good) == ()
    assert good.porcelain_calls == [tuple(pins)]
    drifted = {**pins, "scripts/b.py": "zz"}
    drift = phase_b_refusals(pins, "PRE", _FakeGit(drifted, pinned=pins, ancestors=good.ancestors))
    assert drift == (RefusalReason.HEAD_BLOB_MISMATCH,)
    dirty = _FakeGit(pins, pinned=pins, clean=False, ancestors=good.ancestors)
    assert phase_b_refusals(pins, "PRE", dirty) == (RefusalReason.DIRTY_PINNED_PATH,)
    orphan = phase_b_refusals(pins, "PRE", _FakeGit(pins, pinned=pins))
    assert orphan == (RefusalReason.PREDECLARATION_NOT_ANCESTOR,)
    # production default path: the real SubprocessGit over a hermetic repo
    repo = tmp_path / "repo"
    first, second = tmp_git_repo(repo, ["one", "two"])
    real = SubprocessGit(repo)
    real_pins = {"manifest.json": sha256_text("two"), "extra.py": sha256_text("x = 1\n")}
    dirty_only = (RefusalReason.DIRTY_PINNED_PATH,)

    assert phase_b_refusals(real_pins, first, real) == ()
    assert phase_b_refusals(real_pins, second, real) == ()  # HEAD is its own ancestor
    dangling = git_cmd(repo, "commit-tree", f"{second}^{{tree}}", "-m", "not on main")
    assert phase_b_refusals(real_pins, dangling, real) == (
        RefusalReason.PREDECLARATION_NOT_ANCESTOR,
    )
    stale = {**real_pins, "manifest.json": sha256_text("one")}
    assert phase_b_refusals(stale, first, real) == (RefusalReason.HEAD_BLOB_MISMATCH,)

    def reset() -> None:
        git_cmd(repo, "reset", "-q", "--hard")
        git_cmd(repo, "clean", "-fdq")

    (repo / "manifest.json").write_text("modified, unstaged")
    assert phase_b_refusals(real_pins, first, real) == dirty_only
    reset()
    (repo / "manifest.json").write_text("modified, staged")
    git_cmd(repo, "add", "manifest.json")
    assert phase_b_refusals(real_pins, first, real) == dirty_only
    reset()
    git_cmd(repo, "rm", "--cached", "-q", "extra.py")  # extra.py stays on disk, untracked
    assert phase_b_refusals(real_pins, first, real) == dirty_only
    reset()
    (repo / "other.txt").write_text("dirty, but not a pinned path")
    assert phase_b_refusals(real_pins, first, real) == ()
    reset()
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "elsewhere"))  # inherited GIT_* must be cleared
    assert phase_b_refusals(real_pins, first, real) == ()


def test_refreeze_rule_requires_new_predeclaration_commit(tmp_path: Path) -> None:
    frozen = {"core.py": "aa", "cli.py": "bb"}
    changed = {"core.py": "cc", "cli.py": "bb"}
    fake = _FakeGit(ancestors={("OLD", "NEW")})

    def status(
        head: dict[str, str], new_pins: dict[str, str] | None, new_commit: str | None
    ) -> str:
        return refreeze_status(
            frozen, head, new_pins, old_pre_commit="OLD", new_pre_commit=new_commit, git=fake
        )

    assert status(frozen, None, None) == "OK"
    assert status(changed, None, None) == "REFREEZE_REQUIRED"
    assert status(changed, frozen, "NEW") == "REFREEZE_REQUIRED"  # stale re-pin
    assert status(changed, changed, "NEW") == "REFROZEN"
    assert status(changed, changed, "OLD") == "REFREEZE_REQUIRED"  # matching pins, no new commit
    assert status(changed, changed, None) == "REFREEZE_REQUIRED"
    # production default path: a strict descendant on a real repo
    old, new = tmp_git_repo(tmp_path / "repo", ["old", "new"])
    real = SubprocessGit(tmp_path / "repo")
    dangling = git_cmd(tmp_path / "repo", "commit-tree", f"{old}^{{tree}}", "-m", "side")

    def real_status(new_commit: str) -> str:
        return refreeze_status(
            frozen, changed, changed, old_pre_commit=old, new_pre_commit=new_commit, git=real
        )

    assert real_status(new) == "REFROZEN"
    assert real_status(old) == "REFREEZE_REQUIRED"
    assert real_status(dangling) == "REFREEZE_REQUIRED"


def test_post_hoc_verifier_checks_artefact_commit_is_after_predeclaration(tmp_path: Path) -> None:
    fake = _FakeGit(ancestors={("PRE", "ART")})
    after = (RefusalReason.ARTEFACT_NOT_AFTER_PREDECLARATION,)

    assert post_hoc_violations("PRE", "ART", fake) == ()
    assert post_hoc_violations("PRE", "PRE", _FakeGit(ancestors={("PRE", "PRE")})) == after
    assert post_hoc_violations("ART", "PRE", fake) == after
    # production default path
    pre, art = tmp_git_repo(tmp_path / "repo", ["pre", "art"])
    real = SubprocessGit(tmp_path / "repo")
    assert post_hoc_violations(pre, art, real) == ()
    assert post_hoc_violations(art, pre, real) == after
    assert post_hoc_violations(pre, pre, real) == after


def test_pin_resolver_reads_reflog_snapshot_file_not_live_reflog_and_never_committer_time(
    tmp_path: Path,
) -> None:
    path = tmp_path / "REFLOG.txt"
    digest = _snapshot(path)
    git = _FakeGit()
    boots = _p7_boots()

    pins = resolve_pins(path, digest, boots, git, _CFG)

    assert [
        p.commit for p in pins
    ] == _P7_COMMITS  # boot 8 is c893e13e603e, never the rebased commit
    assert [p.near_boundary for p in pins] == _P7_NEAR
    assert pins[1].state == "UNTESTABLE" and pins[1].reason == PinReason.NEAR_BOUNDARY_TREE_DIFFERS
    assert {p.state for i, p in enumerate(pins) if i != 1} == {"PINNED"}
    both = resolve_pins(path, digest, boots, git, _CFG, reproduces_under=lambda n, c: True)
    assert both[1].commit == "99067d4a9e7a" and both[1].state == "PINNED"
    one_sided = resolve_pins(
        path, digest, boots, git, _CFG, reproduces_under=lambda n, c: c != "60290e9ddd29"
    )
    assert one_sided[1].state == "UNTESTABLE"
    with pytest.raises(SnapshotShaMismatch):
        resolve_pins(path, "0" * 64, boots, git, _CFG)
    early = resolve_pins(path, digest, [_boot(1, "2026-09-30T00:00:00")], git, _CFG)
    assert early[0].commit is None and early[0].state == "UNTESTABLE"
    assert early[0].reason == PinReason.NO_PIN
    bad = resolve_pins(path, digest, boots, _FakeGit(bad_blob_commit="4ba7f10cd1f6"), _CFG)
    assert bad[8].state == "UNTESTABLE" and bad[8].reason == PinReason.CORROBORATION_FAILED
    assert bad[7].state == "PINNED"
    assert reproduction_gate([None] * 3 + [True] * 22).passed is False  # UNTESTABLE = non-match
    assert reproduction_gate([None] * 2 + [True] * 23).passed is True


def test_pin_resolver_on_the_committed_snapshot_reproduces_the_p7_table() -> None:
    raw = _REAL_SNAPSHOT.read_bytes()

    pins = resolve_pins(
        _REAL_SNAPSHOT, hashlib.sha256(raw).hexdigest(), _p7_boots(), _FakeGit(), _CFG
    )

    assert hashlib.sha256(raw).hexdigest() == _REAL_SNAPSHOT_SHA
    assert [p.commit for p in pins] == _P7_COMMITS
    assert [p.near_boundary for p in pins] == _P7_NEAR
    assert [p.state for p in pins] == ["PINNED", "UNTESTABLE"] + ["PINNED"] * 7


def test_pin_resolver_branch_section_first_head_section_fallback(tmp_path: Path) -> None:
    text = (
        "# source: .git/logs/HEAD\n"
        "2026-10-01T10:00:00+00:00 old=000000000000 new=aaaaaaaaaaaa commit: head only\n"
        "2026-10-02T10:00:00+00:00 old=aaaaaaaaaaaa new=cccccccccccc commit: head differs\n"
        "# source: .git/logs/refs/heads/feat\n"
        "2026-10-02T10:00:00+00:00 old=aaaaaaaaaaaa new=bbbbbbbbbbbb commit: branch\n"
    )
    path = tmp_path / "REFLOG.txt"
    path.write_text(text)
    boots = [_boot(1, "2026-10-01T11:00:00"), _boot(2, "2026-10-02T11:00:00")]

    pins = resolve_pins(path, sha256_text(text), boots, _FakeGit(), _CFG)

    assert [p.commit for p in pins] == ["aaaaaaaaaaaa", "bbbbbbbbbbbb"]  # fallback, then branch


def test_pin_resolver_same_second_rows_and_reset_rows_with_old_equal_new(tmp_path: Path) -> None:
    text = (
        "# source: .git/logs/HEAD\n"
        "2026-10-03T12:00:00+00:00 old=000000000000 new=d00000000001 cherry-pick: a\n"
        "2026-10-03T12:00:00+00:00 old=d00000000001 new=d00000000002 cherry-pick: b\n"
        "2026-10-03T12:00:00+00:00 old=d00000000002 new=d00000000003 cherry-pick: c\n"
        "2026-10-03T12:00:05+00:00 old=d00000000003 new=d00000000003 reset: moving to HEAD\n"
        "2026-10-03T13:00:00+00:00 old=d00000000003 new=d00000000004 commit: e\n"
    )
    path = tmp_path / "REFLOG.txt"
    path.write_text(text)
    boots = [
        _boot(1, "2026-10-03T12:00:00"),  # exactly on the same-second group
        _boot(2, "2026-10-03T12:00:30"),  # after the no-op reset row
        _boot(3, "2026-10-03T13:30:00"),
    ]

    pins = resolve_pins(path, sha256_text(text), boots, _FakeGit(), _CFG)

    assert [p.commit for p in pins] == ["d00000000003", "d00000000003", "d00000000004"]
    assert [p.state for p in pins] == ["PINNED"] * 3


def test_pin_resolver_near_boundary_is_strictly_under_120_seconds(tmp_path: Path) -> None:
    rows = [
        ("2026-10-01T00:00:00", "000000000000", "e00000000001"),
        ("2026-10-01T12:00:00", "e00000000001", "e00000000002"),
    ]
    path = tmp_path / "REFLOG.txt"
    digest = _snapshot(path, rows)
    boots = [_boot(1, "2026-10-01T12:01:59"), _boot(2, "2026-10-01T12:02:01")]

    pins = resolve_pins(path, digest, boots, _FakeGit(), _CFG)

    assert [p.near_boundary for p in pins] == [True, False]  # 119 s and 121 s after the row
    assert [p.commit for p in pins] == ["e00000000002"] * 2


def test_pin_resolver_over_the_production_git_port_and_a_fast_forwarded_old_commit(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    old, new = tmp_git_repo(
        repo,
        ["old-content", "new-content"],
        dates=["2026-10-01T00:00:00+00:00", "2026-10-02T00:00:00+00:00"],
    )
    # new's committer date (10-02) precedes the reflog row that fast-forwarded it (10-04)
    rows = [
        ("2026-10-01T01:00:00", "0" * 12, old[:12]),
        ("2026-10-04T00:00:00", old[:12], new[:12]),
    ]
    snap = tmp_path / "REFLOG.txt"
    digest = _snapshot(snap, rows)
    cfg = PinConfig("manifest.json", "manifest.json", ("manifest.json",))
    o_sha, n_sha = sha256_text("old-content"), sha256_text("new-content")
    boots = [
        _boot(1, "2026-10-03T00:00:00", o_sha, o_sha),  # before the FF row: must NOT pin new
        _boot(2, "2026-10-05T00:00:00", n_sha, n_sha),
        _boot(3, "2026-10-05T01:00:00", o_sha, o_sha),  # logged the stale blob sha
    ]
    real = SubprocessGit(repo)

    pins = resolve_pins(snap, digest, boots, real, cfg)

    assert real.blob_sha256(old, "manifest.json") == o_sha  # at the commit, never HEAD
    assert real.tree_shas(old, ["manifest.json"]) != real.tree_shas(new, ["manifest.json"])
    assert [(p.commit, p.state) for p in pins] == [
        (old[:12], "PINNED"),
        (new[:12], "PINNED"),
        (new[:12], "UNTESTABLE"),
    ]
    assert pins[2].reason == PinReason.CORROBORATION_FAILED


def test_pin_label_uses_the_git_port_stable_for_an_empty_log_inferred_for_a_non_empty_one(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    first, second = tmp_git_repo(repo, ["m1", "m2"])
    (repo / "other.txt").write_text("changed\n")
    git_cmd(repo, "commit", "-q", "-am", "touch other.txt only")
    third = git_cmd(repo, "rev-parse", "HEAD")
    real = SubprocessGit(repo)

    assert real.log_commits(["manifest.json"], third, since=first) == (second,)
    assert pin_label(real, ["manifest.json"], since=first, until=third) == "INFERRED"
    assert pin_label(real, ["manifest.json"], since=second, until=third) == "STABLE"
    assert pin_label(real, ["other.txt"], since=second, until=third) == "INFERRED"
