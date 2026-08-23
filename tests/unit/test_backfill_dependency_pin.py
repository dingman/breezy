"""Pin the `pyiem` dependency exactly to the version the nws-cli-settlement
skill mandates, and document the current relationship (or lack of one)
between that pin and the `parser_version` provenance field stored on every
`NwsClimateDay`.

Why this test exists: `raw_sha256` on `NwsRawProduct` verifies the raw CLI
product text, never the *parse* of that text. If a future dependency bump
silently changed which Fahrenheit values a parser extracts from identical
raw text, two environments resolving different releases could each treat a
different value as settlement-grade, with nothing in the provenance chain
revealing why. These tests freeze the resolved version so a `uv sync`/lock
resync cannot silently drift it, and pin the current (not yet pyIEM-backed)
architecture so any change to it is deliberate rather than silent.
"""

from __future__ import annotations

import ast
import inspect

import pyiem

from breezy.ingest.nws_actor import PARSER_VERSION

#: Exact version mandated by `.claude/skills/nws-cli-settlement/SKILL.md`
#: ("Pin exact versions in pyproject.toml: pyiem = \"==1.27.0\"") and pinned
#: in `pyproject.toml`'s `backfill` extra. These two literals are hand-kept
#: in lockstep -- there is no single source of truth to derive either from.
MANDATED_PYIEM_VERSION = "1.27.0"


def test_installed_pyiem_matches_the_mandated_pin() -> None:
    """A `uv sync`/`uv lock` that resolves a different pyiem release must
    fail loudly here rather than silently changing what a future
    pyIEM-backed parse would produce.
    """
    assert pyiem.__version__ == MANDATED_PYIEM_VERSION


def test_settlement_parser_version_does_not_yet_encode_pyiem() -> None:
    """Documents current reality, not the skill's target design.

    SKILL.md's "Required Provenance Per Datum" lists `parser_version` as
    "(pyiem version used)", on the premise that pyIEM performs the CLI parse
    (see its "Use pyIEM -- Do NOT Hand-Roll Parsing" section). The live
    settlement path (`breezy.normalize.cli_parse`) is instead a hand-rolled,
    pure-text parser that never imports pyiem (see
    `test_cli_parse_module_does_not_import_pyiem` below), and
    `PARSER_VERSION` in `breezy.ingest.nws_actor` is a hardcoded string
    identifying breezy's own parsing module, not any pyiem release.

    Consequence: pinning `pyiem` exactly (this file's other test) protects a
    *future* pyIEM-backed backfill path, but does NOT currently protect
    live settlement parsing -- that protection comes instead from the
    golden-parse fixtures in `test_normalize_cli_parse.py`, which pin
    `cli_parse.py`'s own behaviour directly.

    If this assertion starts failing because `PARSER_VERSION` now embeds a
    pyiem version, that is a deliberate architecture change, not a
    regression -- update this test (and re-verify the golden-parse
    fixtures still cover whatever pyiem now does) rather than reverting it.
    """
    assert "pyiem" not in PARSER_VERSION.lower()
    assert PARSER_VERSION == "breezy.normalize.cli_parse@0.1.0"


def test_cli_parse_module_does_not_import_pyiem() -> None:
    """Confirms, at the import-graph level, the architectural fact
    `breezy/normalize/cli_parse.py`'s own module docstring already states
    ("PURE module: no I/O ... free of any dependency beyond pure text").

    Walks the module's AST rather than `sys.modules` or `vars()`, so the
    check is unaffected by whether some *other* test session import has
    already pulled `pyiem` in for an unrelated reason.
    """
    import breezy.normalize.cli_parse as cli_parse_module

    source = inspect.getsource(cli_parse_module)
    tree = ast.parse(source)
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    assert "pyiem" not in imported_roots
