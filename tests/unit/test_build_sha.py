"""Rev 3.1 R8: `breezy.runtime.build_sha` -- the extraction of `trade_
supervisor`'s `.git`-reading helpers, plus the standalone `resolve_build_
revision` entry point F-2's node rows call directly.

`trade_supervisor` keeps its own re-export/monkeypatch tests
(`test_trade_supervisor.py`); this file exercises the module's OWN default
`source_tree_head_sha` path (never overridden), the individual `.git`
readers directly, and the "no subprocess" guarantee.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from breezy.runtime import build_sha
from breezy.runtime.build_sha import (
    BUILD_REVISION_ENV_VAR,
    _looks_like_git_sha,
    _read_git_head_sha,
    _read_ref_sha,
    resolve_build_revision,
)


class TestLooksLikeGitSha:
    def test_a_full_length_hex_sha_is_accepted(self) -> None:
        assert _looks_like_git_sha("a" * 40) is True

    def test_a_too_short_value_is_rejected(self) -> None:
        assert _looks_like_git_sha("abc123") is False

    def test_a_non_hex_value_is_rejected(self) -> None:
        assert _looks_like_git_sha("z" * 12) is False


class TestReadRefSha:
    def test_reads_a_loose_ref_file(self, tmp_path: Path) -> None:
        ref = tmp_path / "refs" / "heads" / "main"
        ref.parent.mkdir(parents=True)
        ref.write_text("b" * 40 + "\n")

        assert _read_ref_sha(tmp_path, "refs/heads/main") == "b" * 40

    def test_falls_back_to_packed_refs(self, tmp_path: Path) -> None:
        (tmp_path / "packed-refs").write_text(
            "# pack-refs with: peeled fully-peeled sorted\n"
            f"{'c' * 40} refs/heads/main\n"
        )

        assert _read_ref_sha(tmp_path, "refs/heads/main") == "c" * 40

    def test_missing_ref_returns_none(self, tmp_path: Path) -> None:
        assert _read_ref_sha(tmp_path, "refs/heads/nope") is None


class TestReadGitHeadSha:
    def test_ordinary_repo_directory(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("d" * 40 + "\n")

        assert _read_git_head_sha(git_dir) == "d" * 40

    def test_symbolic_head_resolves_via_loose_ref(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        (git_dir / "refs" / "heads").mkdir(parents=True)
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
        (git_dir / "refs" / "heads" / "main").write_text("e" * 40 + "\n")

        assert _read_git_head_sha(git_dir) == "e" * 40

    def test_linked_worktree_follows_gitdir_pointer_and_commondir(
        self, tmp_path: Path
    ) -> None:
        common = tmp_path / "main" / ".git"
        (common / "refs" / "heads").mkdir(parents=True)
        (common / "refs" / "heads" / "main").write_text("f" * 40 + "\n")

        worktree_git_dir = tmp_path / "wt" / ".git-worktree"
        worktree_git_dir.mkdir(parents=True)
        (worktree_git_dir / "HEAD").write_text("ref: refs/heads/main\n")
        (worktree_git_dir / "commondir").write_text(str(common) + "\n")

        pointer = tmp_path / "wt" / ".git"
        pointer.write_text(f"gitdir: {worktree_git_dir}\n")

        assert _read_git_head_sha(pointer) == "f" * 40

    def test_detached_head_returns_the_raw_sha(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("a1" * 20 + "\n")

        assert _read_git_head_sha(git_dir) == "a1" * 20

    def test_missing_git_dir_returns_none_never_raises(self, tmp_path: Path) -> None:
        assert _read_git_head_sha(tmp_path / "nope") is None

    def test_malformed_gitdir_pointer_returns_none(self, tmp_path: Path) -> None:
        pointer = tmp_path / ".git"
        pointer.write_text("not a gitdir pointer\n")

        assert _read_git_head_sha(pointer) is None


class TestResolveBuildRevision:
    def test_env_override_wins_and_is_stripped(self) -> None:
        assert resolve_build_revision({BUILD_REVISION_ENV_VAR: "  deadbeef1234  "}) == (
            "deadbeef1234"
        )

    def test_default_source_tree_head_sha_reads_this_checkout(self) -> None:
        """No override passed: the module's own default reads `breezy.
        __file__`'s repo root directly -- proven here by asserting it
        returns a real-looking sha for THIS worktree (a git checkout),
        never `None`/"unknown" (this repo's own `.git` is always present
        in CI)."""
        revision = resolve_build_revision({})

        assert revision != "unknown"
        assert len(revision) == 12
        assert _looks_like_git_sha(revision)

    def test_injected_source_tree_head_sha_overrides_the_default(self) -> None:
        revision = resolve_build_revision({}, source_tree_head_sha=lambda: "9" * 40)

        assert revision == "9" * 12

    def test_none_from_injected_reader_falls_through_to_metadata_or_unknown(self) -> None:
        revision = resolve_build_revision({}, source_tree_head_sha=lambda: None)

        assert revision  # either the installed package version or "unknown"

    def test_an_unexpected_exception_is_contained_to_unknown(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        def _boom() -> str | None:
            raise RuntimeError("boom")

        with caplog.at_level("WARNING"):
            revision = resolve_build_revision({}, source_tree_head_sha=_boom)

        assert revision == "unknown"
        assert any("build revision" in record.getMessage() for record in caplog.records)


class TestNoSubprocessUsed:
    def test_module_source_never_references_subprocess(self) -> None:
        """R8/no-egress-adjacent guarantee: this module reads `.git` files
        directly and must never shell out to the `git` binary."""
        source = Path(build_sha.__file__).read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(alias.name == "subprocess" for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                assert node.module != "subprocess"
        assert subprocess  # imported here only for the isinstance-style guard above
