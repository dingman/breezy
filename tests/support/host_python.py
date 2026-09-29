"""Resolve the interpreter/tooling that lives in the SHARED production venv.

WT-VENV. About a dozen tests derive a host entrypoint (``python``,
``lint-imports``, ...) as ``REPO_ROOT / ".venv" / "bin" / <name>``, where
``REPO_ROOT`` is ``Path(__file__).resolve().parents[2]`` -- the test FILE's
own repo root. That is correct in the primary tree (``REPO_ROOT`` IS
``/home/jon/breezy``, which owns the venv), but wrong in a git worktree:
``REPO_ROOT`` there is the worktree's own root, which has no ``.venv`` of its
own (worktrees never carry one -- ``.gitignore`` excludes it, and it is a
large, non-source artefact nobody wants duplicated per worktree). The fix is
never to derive the venv from the tree under test; it is always to resolve
the interpreter that is ACTUALLY running the suite, honouring the
``BREEZY_PYTHON`` override the repo already uses for exactly this purpose
(``tests/unit/test_quote_tape_ingest_definitions_first.py``,
``scripts/ci/run_tests_no_egress.sh``, ``scripts/analysis/
aud07_m1c_sweep.sh``).

Default behaviour in the primary tree is unchanged: ``scripts/ci/
run_tests_no_egress.sh`` already launches pytest via
``${BREEZY_PYTHON:-$REPO_ROOT/.venv/bin/python}``, so ``sys.executable``
inside that process already IS the primary tree's own venv python whenever
``BREEZY_PYTHON`` is unset -- ``resolve_breezy_python()`` returns the exact
same value either way.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

#: The env var the repo already uses to point tests at the shared venv's
#: interpreter when the tree under test (a worktree) has no ``.venv`` of its
#: own. Same name and same fallback (``sys.executable``) as
#: ``tests/unit/test_quote_tape_ingest_definitions_first.py``.
BREEZY_PYTHON_ENV_VAR = "BREEZY_PYTHON"


def resolve_breezy_python() -> str:
    """The interpreter to spawn as a subprocess: ``$BREEZY_PYTHON``, else
    ``sys.executable``.

    Never ``REPO_ROOT / ".venv" / "bin" / "python"`` -- that is exactly the
    path that does not exist under a worktree.
    """
    return os.environ.get(BREEZY_PYTHON_ENV_VAR, sys.executable)


def resolve_sibling_entrypoint(name: str) -> Path:
    """A console-script installed alongside the resolved interpreter (e.g.
    ``lint-imports``, ``mypy``), derived from ITS ``bin/`` directory rather
    than any ``REPO_ROOT``.

    The shared venv installs every console script into the same ``bin/`` as
    ``python`` itself, so the interpreter's own parent directory is the one
    path guaranteed to hold ``name`` regardless of which tree's ``REPO_ROOT``
    happens to be in scope.

    Deliberately ``absolute()``, never ``resolve()``: a venv's ``bin/python``
    is itself a symlink to the interpreter's real install (e.g. a
    ``uv``-managed CPython under ``~/.local/share/uv/``), and THAT directory
    does not hold the venv's console scripts. Resolving the symlink would
    silently point ``lint-imports`` at a directory that never has it.
    """
    return Path(resolve_breezy_python()).absolute().parent / name
