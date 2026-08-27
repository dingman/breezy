"""P1 prose lint for programme-wide METAR/CLI conservatism claims."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_GLOBS = (
    "docs/plans/**/*.md",
    "docs/core/**/*.md",
    "docs/evidence/**/*.md",
    "src/**/*.py",
    "scripts/**/*.py",
)

_METAR_RE = re.compile(r"\bMETAR\b", re.IGNORECASE)
_CLI_RE = re.compile(r"\bCLI\b", re.IGNORECASE)
_DIRECTION_RE = re.compile(
    r"\b(?:below|under|conservative|conservatism)\b|lower than|colder than|never exceeds?",
    re.IGNORECASE,
)
_GENERAL_RE = re.compile(
    r"\b(?:always|in general|generally|universally|invariably|every city|all cities|"
    r"programme-wide|program-wide|systematically)\b|as a (?:general )?property",
    re.IGNORECASE,
)
_ASSERTION_RE = re.compile(
    r"\b(?:assert\w*|claim\w*|report\w*|state\w*|treat\w*|rel(?:y|ies)\w*|describ\w*)\b",
    re.IGNORECASE,
)
_NEGATION_RE = re.compile(
    r"\b(?:no|not|never|neither|forbid\w*|prohibit\w*|may not|must not|cannot)\b",
    re.IGNORECASE,
)
_REFUTATION_RE = re.compile(
    r"\b(?:falsif\w*|refut\w*|withdraw\w*|disprov\w*|re-derive\w*|already observed)\b",
    re.IGNORECASE,
)


def _strip_markdown_code(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    return re.sub(r"`[^`]*`", " ", text)


def _sentences(text: str, *, markdown: bool) -> Iterator[str]:
    if markdown:
        text = _strip_markdown_code(text)
    for paragraph in re.split(r"\n\s*\n", text):
        normalized = re.sub(r"(?<!\n)\n(?!\n)", " ", paragraph)
        for fragment in re.split(r"[.;]", normalized):
            sentence = " ".join(fragment.split())
            if sentence:
                yield sentence


def p1_sentence_fires(sentence: str) -> bool:
    if not (
        _METAR_RE.search(sentence)
        and _CLI_RE.search(sentence)
        and _DIRECTION_RE.search(sentence)
        and _GENERAL_RE.search(sentence)
    ):
        return False
    if _REFUTATION_RE.search(sentence):
        return False
    assertion = _ASSERTION_RE.search(sentence)
    if assertion is None:
        return True
    prefix = sentence[max(0, assertion.start() - 90) : assertion.start()]
    return _NEGATION_RE.search(prefix) is None


def iter_p1_scan_paths() -> Iterator[Path]:
    seen: set[Path] = set()
    for pattern in SCAN_GLOBS:
        for path in sorted(REPO_ROOT.glob(pattern)):
            if path.is_file() and path not in seen:
                seen.add(path)
                yield path


def scan_p1() -> list[str]:
    hits: list[str] = []
    for path in iter_p1_scan_paths():
        text = path.read_text(encoding="utf-8")
        for sentence in _sentences(text, markdown=path.suffix == ".md"):
            if p1_sentence_fires(sentence):
                hits.append(f"{path.relative_to(REPO_ROOT).as_posix()}: {sentence}")
    return hits


def test_p1_no_hits_on_the_shipped_tree() -> None:
    hits = scan_p1()
    assert hits == [], "P1 hits:\n" + "\n".join(hits)


def test_p1_scan_covers_plans_core_evidence_src_and_scripts() -> None:
    paths = {path.relative_to(REPO_ROOT).as_posix() for path in iter_p1_scan_paths()}
    assert "docs/plans/SETTLEMENT_REPORTING_PLAN.md" in paths
    assert "docs/core/PROGRESS.md" in paths
    assert "docs/evidence/asymmetric_gate_prereg_2026-08-26.md" in paths
    assert "src/breezy/settlement/coverage.py" in paths
    assert "scripts/analysis/settlement_bucket_guard_band.py" in paths


@pytest.mark.parametrize(
    "sentence",
    [
        "METAR always reads below CLI.",
        "Treat METAR-below-CLI as a general property of the estimator.",
        "METAR always reads below CLI, and this is not in dispute.",
        "The estimator systematically reads METAR below CLI in every city.",
    ],
)
def test_p1_detects_planted_general_claims(sentence: str) -> None:
    assert p1_sentence_fires(sentence) is True


def test_p1_wrap_normalisation_joins_a_hard_wrapped_sentence() -> None:
    text = "METAR always\nreads below\nCLI."
    assert [p1_sentence_fires(sentence) for sentence in _sentences(text, markdown=True)] == [
        True
    ]


def test_p1_code_span_stripping_exempts_a_quoted_fixture() -> None:
    text = "`METAR always reads below CLI.`"
    assert scan_text(text) == []


def scan_text(text: str) -> list[str]:
    return [sentence for sentence in _sentences(text, markdown=True) if p1_sentence_fires(sentence)]


def test_p1_calibration_corpus_does_not_fire() -> None:
    samples = [
        "METAR_BELOW_CLI table label",
        (
            "Any evidence that CLI systematically reads below METAR falsifies "
            "the conservatism claim outright"
        ),
        "No downstream document may assert METAR reads below CLI as a general property",
        "The analysis must re-derive METAR below CLI per city",
        "METAR and CLI measurement rows are reported separately by city",
        "Do not treat METAR below CLI as generally true",
        "The blanket claim that METAR always reads below CLI is refuted",
    ]
    assert [sample for sample in samples if p1_sentence_fires(sample)] == []
