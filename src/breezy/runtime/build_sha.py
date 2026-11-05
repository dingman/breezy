"""Build-revision resolution, shared by ``trade_supervisor`` (AUD-14a) and
F-2's per-process diagnostics rows (``docs/plans/STALL_FOLLOWUPS_F1_F4_
2026-09-24.md``, Rev 3.1 R8).

``_looks_like_git_sha``, ``_read_ref_sha`` and ``_read_git_head_sha`` were
moved here UNCHANGED from ``breezy.runtime.trade_supervisor`` (no ``git``
subprocess, no GitPython -- only direct ``.git`` file reads, so this stays
reachable from a ``LiveClock``/NO-SEND-guarded process without widening the
execution-egress allowlist). ``trade_supervisor`` re-imports all three under
the same private names, so its own tests (which import ``_read_git_head_sha``
directly from it) stay green and unedited.

``_read_source_tree_head_sha`` deliberately STAYS in ``trade_supervisor`` --
its tests monkeypatch it on that module -- so :func:`resolve_build_revision`
takes an INJECTABLE ``source_tree_head_sha`` callable instead of importing
that function back (which would be circular). Its own default reads
``breezy.__file__`` directly, byte-identical in effect to ``trade_
supervisor``'s copy.
"""

from __future__ import annotations

import importlib.metadata
import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

__all__ = [
    "BUILD_REVISION_ENV_VAR",
    "resolve_build_revision",
]

#: AUD-14a: the sole env var this module reads for build identity. Never an
#: operator-reserved control variable (the two seven-value caps) -- a build
#: revision is a static identifier, not an operator value.
BUILD_REVISION_ENV_VAR: Final = "BREEZY_BUILD_REVISION"

#: A loose sanity check on a value THIS MODULE read out of a `.git` file
#: (HEAD, a loose ref, or a `packed-refs` line) -- never on untrusted input.
_MIN_GIT_SHA_LEN: Final = 12
_HEX_DIGITS: Final = frozenset("0123456789abcdef")


def _looks_like_git_sha(value: str) -> bool:
    return len(value) >= _MIN_GIT_SHA_LEN and all(c in _HEX_DIGITS for c in value)


def _read_ref_sha(common_git_dir: Path, ref_name: str) -> str | None:
    """Resolve ``ref_name`` (e.g. ``"refs/heads/main"``) to a commit sha,
    reading ONLY ``.git`` files under ``common_git_dir`` -- no ``git``
    subprocess, no GitPython. Tries the loose ref file first, then
    ``packed-refs`` (git's own fallback once a branch has been packed and
    no longer has a loose ref file of its own). Returns ``None`` -- never
    raises for an ordinary miss -- so the caller falls through cleanly.
    """
    loose = common_git_dir / ref_name
    if loose.is_file():
        sha = loose.read_text().strip()
        return sha if _looks_like_git_sha(sha) else None

    packed = common_git_dir / "packed-refs"
    if not packed.is_file():
        return None
    for line in packed.read_text().splitlines():
        line = line.strip()
        if not line or line[0] in "#^":
            continue
        parts = line.split(" ", 1)
        if len(parts) != 2 or parts[1] != ref_name:
            continue
        sha = parts[0]
        return sha if _looks_like_git_sha(sha) else None
    return None


def _read_git_head_sha(git_dir: Path) -> str | None:
    """Read the commit sha HEAD points at, directly from ``.git`` files --
    no ``git`` subprocess, no GitPython.

    Handles: an ordinary repo (``git_dir`` is a directory); a linked
    worktree (``git_dir`` is a FILE containing ``gitdir: <path>``, whose
    own directory carries a ``commondir`` file pointing back to the shared
    refs -- exactly the shape a Breezy backlog worktree has); a symbolic
    HEAD (``ref: refs/heads/X``) resolved against a loose ref file or,
    failing that, ``packed-refs``; and a detached HEAD (the file holds the
    raw sha directly).

    Returns ``None`` -- never raises -- for anything it does not
    recognise (missing file, unreadable structure, unresolvable ref), so
    the caller falls through to the next source rather than treating an
    ordinary "this isn't a git checkout" as a crash.
    """
    if git_dir.is_file():
        content = git_dir.read_text().strip()
        prefix = "gitdir:"
        if not content.startswith(prefix):
            return None
        worktree_git_dir = Path(content[len(prefix) :].strip())
        if not worktree_git_dir.is_absolute():
            worktree_git_dir = (git_dir.parent / worktree_git_dir).resolve()
        head_path = worktree_git_dir / "HEAD"
        commondir_file = worktree_git_dir / "commondir"
        if commondir_file.is_file():
            common_raw = Path(commondir_file.read_text().strip())
            common_git_dir = (
                common_raw
                if common_raw.is_absolute()
                else (worktree_git_dir / common_raw).resolve()
            )
        else:
            common_git_dir = worktree_git_dir
    elif git_dir.is_dir():
        head_path = git_dir / "HEAD"
        common_git_dir = git_dir
    else:
        return None

    if not head_path.is_file():
        return None
    head_content = head_path.read_text().strip()

    ref_prefix = "ref:"
    if head_content.startswith(ref_prefix):
        ref_name = head_content[len(ref_prefix) :].strip()
        return _read_ref_sha(common_git_dir, ref_name)

    # Detached HEAD: the file itself holds the raw sha.
    return head_content if _looks_like_git_sha(head_content) else None


def _default_source_tree_head_sha() -> str | None:
    """The git commit of the SOURCE TREE ACTUALLY IMPORTED, located from
    ``breezy.__file__`` -- mirrors ``trade_supervisor._read_source_tree_
    head_sha`` exactly, kept as a separate copy so this module never
    imports ``trade_supervisor`` back (which would be circular: ``trade_
    supervisor`` imports the three helpers above FROM here).
    """
    import breezy

    repo_root = Path(breezy.__file__).resolve().parents[2]
    return _read_git_head_sha(repo_root / ".git")


def resolve_build_revision(
    env: Mapping[str, str],
    *,
    source_tree_head_sha: Callable[[], str | None] = _default_source_tree_head_sha,
) -> str:
    """The running build's static identity (AUD-14a; Rev 3.1 R8).

    Resolution order:
      1. ``BUILD_REVISION_ENV_VAR`` in ``env``, if set and non-blank -- an
         explicit operator/deploy override.
      2. ``source_tree_head_sha()`` (by default, the git commit of the
         imported source tree), truncated to 12 hex characters.
      3. ``importlib.metadata.version("breezy")`` -- a last resort before
         the literal below.
      4. The literal ``"unknown"``.

    The WHOLE resolution is wrapped in a bare ``except Exception``: nothing
    here may crash a caller's startup. Any unexpected failure logs one
    WARNING and returns ``"unknown"`` -- never a raise, never an omitted
    field.

    F-2 (the node's per-process diagnostics rows) calls this directly with
    ``env=os.environ`` and no override, so its ``build_sha`` and ``trade_
    supervisor``'s own ``supervisor_started.revision`` resolve the SAME
    identity for the SAME process tree, keeping D2 attribution joinable.
    """
    try:
        from_env = env.get(BUILD_REVISION_ENV_VAR, "").strip()
        if from_env:
            return from_env
        sha = source_tree_head_sha()
        if sha:
            return sha[:12]
        try:
            return importlib.metadata.version("breezy")
        except importlib.metadata.PackageNotFoundError:
            return "unknown"
    except Exception:
        logger.warning("could not resolve build revision; using 'unknown'", exc_info=True)
        return "unknown"
