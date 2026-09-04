"""PREREG v1 non-modification pin (ruling (3)).

`docs/plans/FAMILY_TALLY_V2_BLUEPRINT_2026-09-04.md` build order commit 3 and
Sec "Tests": v1's registered statistic must never be touched by the v2
build. This module AST-extracts the verbatim source text of v1's four
registered symbols in `scripts/analysis/mb_current_rung_edge_study.py`
(`FEE_THETA`, `break_even`, `RealizedStratum`, `build_realized_stratum`) plus
the three `build_realized_stratum` call sites in
`scripts/analysis/live_family_tally.py` (line-anchored after b08166c's
structural-dead-stop shift: `:193` station, `:206` ask-band, `:290` pooled),
sha256-pins each to its CURRENT text, and proves each pin can fail in BOTH
directions with a widened and a narrowed neighbour mutant -- the same
equality-pin discipline as `test_cage_rule_constants_are_pinned.py`.

No import of either module (source-text extraction only): a drift in the
STATISTIC is what this guards, not merely importability.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MB_STUDY_PATH = REPO_ROOT / "scripts/analysis/mb_current_rung_edge_study.py"
LIVE_TALLY_PATH = REPO_ROOT / "scripts/analysis/live_family_tally.py"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_module_level_symbol_source(source: str, name: str) -> str:
    """Verbatim source text of one module-level `AnnAssign`/`Assign`/
    `FunctionDef`/`ClassDef` named `name`, via `ast.get_source_segment` --
    never a regex or a naive line-range guess."""
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == name:
                segment = ast.get_source_segment(source, node)
                if segment is not None:
                    return segment
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    segment = ast.get_source_segment(source, node)
                    if segment is not None:
                        return segment
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name:
            segment = ast.get_source_segment(source, node)
            if segment is not None:
                return segment
    raise LookupError(f"{name!r} not found at module level of the given source")


def extract_line(source: str, lineno: int) -> str:
    """The exact text of one 1-indexed source line, no trailing newline."""
    return source.splitlines()[lineno - 1]


def _mutate_widened(text: str) -> str:
    """A neighbour that ADDS to the text -- loosening/widening proof."""
    return text + "  # widened-neighbour-mutant"


def _mutate_narrowed(text: str) -> str:
    """A neighbour that REMOVES from the text -- narrowing proof (the
    dangerous direction: `test_cage_rule_constants_are_pinned.py`'s
    module docstring measured this going undetected by a subset check)."""
    lines = text.splitlines()
    if len(lines) > 1:
        return "\n".join(lines[:-1])
    return text[:-1] if text else text


#: Sha256 of the CURRENT (as of this commit) verbatim source text of each
#: v1 symbol this spec freezes (`docs/plans/FAMILY_TALLY_V2_BLUEPRINT_2026-09-04.md`
#: "Files to modify" table: NOT modified). Computed once by running the
#: extraction and pinning the printed value -- never hand-typed.
PINNED_SYMBOL_HASHES: dict[str, str] = {
    "FEE_THETA": "79b1f4f8b7767b66dc3a38f382a18c335f2225af369ba2cb500c65594320e3fb",
    "break_even": "e4cd6007b98f7c074b524614e310237af8c3a797bfc92fb3d10eee2ca1291fc4",
    "RealizedStratum": "ec6376eeefd4245b10c66ef93b27c95c0c8ae470d6f78041bde78d5df0f6a706",
    "build_realized_stratum": "8929066a9335fced693c6c8b22e84ff6611f3f603100f781c1d220f163b19a8c",
}

#: Sha256 of the CURRENT text of each `build_realized_stratum` call site in
#: `live_family_tally.py`, line-anchored after b08166c's shift (blueprint
#: Sec "Tests"): `:193` station stratum, `:206` ask-band stratum, `:290`
#: pooled stratum.
PINNED_CALL_SITE_HASHES: dict[int, str] = {
    193: "10afd2cb4abcefd10527b55dc4dd5c20c90c5af381256812608b347a7d69e517",
    206: "5d75c71e94c8de385603ec2b9bac36c89734e666696600bf039aa70ddf1003fd",
    290: "9e7cb7e9fb91daab14aab35e09887a16d95a8378b6dbef44fb765af04a72c9fa",
}


@pytest.fixture(scope="module")
def mb_source() -> str:
    return MB_STUDY_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def live_tally_source() -> str:
    return LIVE_TALLY_PATH.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", sorted(PINNED_SYMBOL_HASHES))
def test_v1_symbol_source_matches_its_sha256_pin(name: str, mb_source: str) -> None:
    segment = extract_module_level_symbol_source(mb_source, name)
    actual = _sha256(segment)
    assert actual == PINNED_SYMBOL_HASHES[name], (
        f"scripts/analysis/mb_current_rung_edge_study.py's {name!r} drifted "
        f"from its byte pin -- v1 must stay byte-unmodified.\n"
        f"expected sha256: {PINNED_SYMBOL_HASHES[name]}\nactual sha256:   {actual}\n"
        f"current text:\n{segment}"
    )


@pytest.mark.parametrize("lineno", sorted(PINNED_CALL_SITE_HASHES))
def test_v1_call_site_line_matches_its_sha256_pin(lineno: int, live_tally_source: str) -> None:
    line = extract_line(live_tally_source, lineno)
    actual = _sha256(line)
    assert actual == PINNED_CALL_SITE_HASHES[lineno], (
        f"scripts/analysis/live_family_tally.py:{lineno} drifted from its "
        f"byte pin -- v1's call sites into build_realized_stratum must stay "
        f"unmodified.\nexpected sha256: {PINNED_CALL_SITE_HASHES[lineno]}\n"
        f"actual sha256:   {actual}\ncurrent text: {line!r}"
    )


@pytest.mark.parametrize("name", sorted(PINNED_SYMBOL_HASHES))
def test_v1_symbol_pin_refuses_a_widened_neighbour(name: str, mb_source: str) -> None:
    segment = extract_module_level_symbol_source(mb_source, name)
    mutant = _mutate_widened(segment)
    assert mutant != segment
    assert _sha256(mutant) != PINNED_SYMBOL_HASHES[name]


@pytest.mark.parametrize("name", sorted(PINNED_SYMBOL_HASHES))
def test_v1_symbol_pin_refuses_a_narrowed_neighbour(name: str, mb_source: str) -> None:
    segment = extract_module_level_symbol_source(mb_source, name)
    mutant = _mutate_narrowed(segment)
    assert mutant != segment
    assert _sha256(mutant) != PINNED_SYMBOL_HASHES[name]


@pytest.mark.parametrize("lineno", sorted(PINNED_CALL_SITE_HASHES))
def test_v1_call_site_pin_refuses_a_widened_neighbour(lineno: int, live_tally_source: str) -> None:
    line = extract_line(live_tally_source, lineno)
    mutant = _mutate_widened(line)
    assert mutant != line
    assert _sha256(mutant) != PINNED_CALL_SITE_HASHES[lineno]


@pytest.mark.parametrize("lineno", sorted(PINNED_CALL_SITE_HASHES))
def test_v1_call_site_pin_refuses_a_narrowed_neighbour(lineno: int, live_tally_source: str) -> None:
    line = extract_line(live_tally_source, lineno)
    mutant = _mutate_narrowed(line)
    assert mutant != line
    assert _sha256(mutant) != PINNED_CALL_SITE_HASHES[lineno]


def test_the_pin_predicate_accepts_the_pinned_value_itself(mb_source: str) -> None:
    """Control: a comparison that refused everything would pass both
    non-vacuity proofs above vacuously."""
    for name, expected_hash in PINNED_SYMBOL_HASHES.items():
        segment = extract_module_level_symbol_source(mb_source, name)
        assert _sha256(segment) == expected_hash


def test_symbol_pin_table_covers_exactly_the_four_ruling_3_symbols() -> None:
    assert set(PINNED_SYMBOL_HASHES) == {
        "FEE_THETA",
        "break_even",
        "RealizedStratum",
        "build_realized_stratum",
    }


def test_call_site_pin_table_covers_exactly_the_three_ruling_3_line_numbers() -> None:
    assert set(PINNED_CALL_SITE_HASHES) == {193, 206, 290}
