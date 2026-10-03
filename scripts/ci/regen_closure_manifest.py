"""Regenerate ``closure_manifest.py`` from the import graph (grimp), gate-side only.

Output is a deterministic ``ruff format``-stable literal: sorted keys, sorted module tuples.
``--check`` exits 1 when the target differs from the regenerated text instead of rewriting it.
Entries default to the components already in the manifest; name modules to add new ones.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from breezy.persistence.autonomy import closure_manifest
from breezy.persistence.autonomy.closure import closure_from_grimp

DEFAULT_TARGET: Final[Path] = Path(closure_manifest.__file__)
_HEADER: Final[
    str
] = '''"""Import-closure manifest for the code-identity pins (ARCH 4.3). Generated; do not edit.

Regenerate with ``scripts/ci/regen_closure_manifest.py``. Empty at ARCH-0.
"""

from types import MappingProxyType
from typing import Final

'''
_DECL: Final[str] = (
    "CLOSURE_MODULES: Final[MappingProxyType[str, tuple[str, ...]]] = MappingProxyType("
)


def render_manifest(closures: Mapping[str, Sequence[str]]) -> str:
    """The module source for ``closures``; every tuple sorted, every key sorted."""
    if not closures:
        return f"{_HEADER}{_DECL}{{}})\n"
    lines = [f"{_DECL}", "    {"]
    for entry in sorted(closures):
        members = sorted(closures[entry])
        if not members:
            lines.append(f'        "{entry}": (),')
            continue
        lines.append(f'        "{entry}": (')
        lines.extend(f'            "{m}",' for m in members)
        lines.append("        ),")
    lines.extend(["    }", ")"])
    return _HEADER + "\n".join(lines) + "\n"


def regenerate(entries: Sequence[str]) -> str:
    return render_manifest({entry: closure_from_grimp(entry) for entry in sorted(set(entries))})


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("entries", nargs="*", help="entry modules (default: the current manifest)")
    parser.add_argument("--check", action="store_true", help="fail on drift instead of rewriting")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args(argv)
    entries = args.entries or list(closure_manifest.CLOSURE_MODULES)
    text = regenerate(entries)
    if args.check:
        return 0 if args.target.read_text(encoding="utf-8") == text else 1
    args.target.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
