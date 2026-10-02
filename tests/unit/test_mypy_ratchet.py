"""CF-12 Wave 0: an in-gate mypy ratchet.

``docs/plans/CF-12_MYPY_BURNDOWN_Rev2_2026-09-29.md``, section "Mechanism: a
ratchet test inside the gate (Wave 0)". CI's blocking ``uv run mypy`` step has
been red and ignored for so long that a collection blocker hid the count --
a gate nobody reads is not a gate. This test runs the real, full-config
``mypy`` locally and fails loudly on any regression, so the count is visible
every time the local gate runs.

Pins mypy 2.3.1 (``uv.lock``, measured 2026-09-29). A mypy version bump
re-baselines ``CLEAN``/``CEILINGS`` below in its own commit.

Two layers:

- A pure parser (``parse_mypy_report``) and a pure comparator
  (``assess_ratchet``), unit-tested on fake mypy text -- no subprocess.
- One real test: a module-scoped fixture runs ONE full-config
  ``sys.executable -m mypy --cache-dir <tmp>`` from the repo root (never a
  subset of paths -- following imports changes the counts), then asserts the
  real output against ``CLEAN`` and ``CEILINGS``.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

import pytest

#: Repository root -- the working directory both the real mypy invocation and
#: `pyproject.toml`'s `[tool.mypy]` are relative to.
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

_MYPY_VERSION: Final[str] = "2.3.1"  # uv.lock, measured 2026-09-29 (CF-12 Rev 2)

#: `path:line: error: msg [code]`, optionally `path:line:col: error: ...`.
#: Never matches a `note:` line -- those are dropped.
_ERROR_LINE_RE: Final[re.Pattern[str]] = re.compile(r"^(?P<path>[^:]+):\d+(?::\d+)?: error: .*$")
_SUMMARY_RE: Final[re.Pattern[str]] = re.compile(
    r"^Found (?P<errors>\d+) errors? in (?P<files>\d+) files?\b"
)
_SUCCESS_RE: Final[re.Pattern[str]] = re.compile(r"^Success: no issues found\b")


class MypyReportParseError(RuntimeError):
    """Raised when mypy's output cannot be parsed with confidence.

    Covers both a real crash (no summary line at all) and an internal
    inconsistency (the summary disagrees with the parsed error lines) --
    either one means the count cannot be trusted, so the ratchet must not
    silently pass.
    """


def parse_mypy_report(output: str) -> dict[str, int]:
    """Parse `mypy` output into per-path error counts.

    Drops `note:` lines. Cross-checks the parsed total, and the number of
    distinct files with errors, against the `Found N errors in M files`
    summary line (`Success: no issues found` parses to no errors at all).
    Raises `MypyReportParseError` if no summary line is found (a crashed or
    otherwise unparseable run) or if the summary disagrees with what was
    actually parsed.
    """
    per_file: dict[str, int] = {}
    summary_errors: int | None = None
    summary_files: int | None = None
    for line in output.splitlines():
        error_match = _ERROR_LINE_RE.match(line)
        if error_match is not None:
            path = error_match.group("path")
            per_file[path] = per_file.get(path, 0) + 1
            continue
        if _SUCCESS_RE.match(line):
            summary_errors = 0
            summary_files = 0
            continue
        summary_match = _SUMMARY_RE.match(line)
        if summary_match is not None:
            summary_errors = int(summary_match.group("errors"))
            summary_files = int(summary_match.group("files"))

    if summary_errors is None or summary_files is None:
        raise MypyReportParseError(
            "no `Found N errors in M files` / `Success: no issues found` "
            "summary line in mypy output -- treat this as a crashed or "
            f"otherwise unparseable run:\n{output}"
        )

    total = sum(per_file.values())
    if total != summary_errors:
        raise MypyReportParseError(
            f"parsed {total} error line(s) but the summary reports "
            f"{summary_errors} -- the run is not trustworthy"
        )
    if len(per_file) != summary_files:
        raise MypyReportParseError(
            f"parsed errors in {len(per_file)} file(s) but the summary "
            f"reports {summary_files} -- the run is not trustworthy"
        )
    return per_file


def _matching_entry(path: str, entries: Sequence[str]) -> str | None:
    """The longest entry `path` falls under (exact file, or `entry/` prefix)."""
    hits = [entry for entry in entries if path == entry or path.startswith(entry + "/")]
    if not hits:
        return None
    return max(hits, key=len)


def assess_ratchet(
    per_file: Mapping[str, int],
    *,
    clean: Sequence[str],
    ceilings: Mapping[str, int],
) -> list[str]:
    """Compare parsed per-path error counts against `clean` and `ceilings`.

    Returns a list of human-readable failure messages; empty means the
    ratchet holds. `clean` entries (files or package prefixes) must carry
    zero errors. `ceilings` entries are package-prefix maxima: exceeding one
    is a regression, and falling below one means the ceiling has gone stale
    ("lower the ceiling to N"). Any error under a path that matches neither
    `clean` nor `ceilings` is refused outright -- a new file or package must
    ship clean.
    """
    failures: list[str] = []
    ceiling_actuals: dict[str, int] = dict.fromkeys(ceilings, 0)
    ceiling_keys = list(ceilings)

    for path, count in per_file.items():
        if count <= 0:
            continue
        clean_hit = _matching_entry(path, clean)
        if clean_hit is not None:
            failures.append(
                f"{path}: {count} error(s) under CLEAN entry {clean_hit!r} -- must be 0"
            )
            continue
        ceiling_hit = _matching_entry(path, ceiling_keys)
        if ceiling_hit is not None:
            ceiling_actuals[ceiling_hit] += count
            continue
        failures.append(
            f"{path}: {count} error(s) under no CLEAN or CEILINGS entry -- "
            "new files/packages must ship clean"
        )

    for group, ceiling in ceilings.items():
        actual = ceiling_actuals[group]
        if actual > ceiling:
            failures.append(
                f"{group}: {actual} error(s) exceeds the CEILINGS pin of {ceiling} "
                "-- fix the regression, or raise the ceiling deliberately"
            )
        elif actual < ceiling:
            failures.append(f"{group}: lower the ceiling to {actual}")

    return failures


# ---------------------------------------------------------------------------
# Parser unit tests -- fake mypy text, no subprocess.
# ---------------------------------------------------------------------------


def test_an_error_line_is_counted_against_its_path() -> None:
    output = (
        "src/breezy/runtime/foo.py:12: error: Incompatible types  [assignment]\n"
        "Found 1 error in 1 file (checked 5 source files)\n"
    )

    per_file = parse_mypy_report(output)

    assert per_file == {"src/breezy/runtime/foo.py": 1}


def test_a_note_line_is_never_counted() -> None:
    output = (
        "src/breezy/runtime/foo.py:12: error: Incompatible types  [assignment]\n"
        "src/breezy/runtime/foo.py:12: note: See https://example invalid\n"
        "Found 1 error in 1 file (checked 5 source files)\n"
    )

    per_file = parse_mypy_report(output)

    assert per_file == {"src/breezy/runtime/foo.py": 1}


def test_success_with_no_issues_parses_to_zero_errors() -> None:
    output = "Success: no issues found in 919 source files\n"

    per_file = parse_mypy_report(output)

    assert per_file == {}


def test_a_summary_mismatch_raises_parse_error() -> None:
    # Declares 2 errors but only one error line is present.
    output = (
        "src/breezy/runtime/foo.py:12: error: Incompatible types  [assignment]\n"
        "Found 2 errors in 1 file\n"
    )

    with pytest.raises(MypyReportParseError):
        parse_mypy_report(output)


def test_a_run_with_no_summary_line_raises_parse_error() -> None:
    # A crash: a traceback with no `Found`/`Success` line anywhere.
    output = (
        "Traceback (most recent call last):\n"
        '  File "mypy/main.py", line 1, in <module>\n'
        "AssertionError: internal mypy error\n"
    )

    with pytest.raises(MypyReportParseError):
        parse_mypy_report(output)


# ---------------------------------------------------------------------------
# Ratchet comparator unit tests -- fake parsed counts, no subprocess.
# ---------------------------------------------------------------------------


def test_a_count_rising_above_its_ceiling_fails() -> None:
    per_file = {"scripts/analysis/foo.py": 5}

    failures = assess_ratchet(per_file, clean=(), ceilings={"scripts/analysis": 4})

    assert any("exceeds the CEILINGS pin of 4" in failure for failure in failures)


def test_a_count_falling_below_its_ceiling_fails_with_a_lower_the_ceiling_message() -> None:
    per_file = {"scripts/analysis/foo.py": 2}

    failures = assess_ratchet(per_file, clean=(), ceilings={"scripts/analysis": 4})

    assert "scripts/analysis: lower the ceiling to 2" in failures


def test_any_error_in_a_clean_path_fails() -> None:
    per_file = {"src/breezy/adapters/foo.py": 1}

    failures = assess_ratchet(per_file, clean=("src/breezy/adapters",), ceilings={})

    assert any("must be 0" in failure for failure in failures)


def test_an_error_under_no_ceiling_and_not_clean_fails_because_new_files_must_be_clean() -> None:
    per_file = {"src/breezy/brand_new_package/foo.py": 1}

    failures = assess_ratchet(per_file, clean=(), ceilings={})

    assert any("new files/packages must ship clean" in failure for failure in failures)


def test_a_report_matching_clean_and_ceilings_exactly_has_no_failures() -> None:
    per_file = {
        "src/breezy/adapters/foo.py": 0,
        "scripts/analysis/foo.py": 4,
    }

    failures = assess_ratchet(
        per_file, clean=("src/breezy/adapters",), ceilings={"scripts/analysis": 4}
    )

    assert failures == []


# ---------------------------------------------------------------------------
# The real ratchet: one full-config mypy run, asserted against measured
# constants (HEAD 5166c96, 2026-09-29; see the plan's "Measured baseline").
# ---------------------------------------------------------------------------

#: Packages/files that must carry exactly zero mypy errors. Only ever grows.
CLEAN: Final[tuple[str, ...]] = (
    "src/breezy/adapters",
    # SL-7 (FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md, build-slice
    # row SL-7): a single-module CLEAN override inside the ceilinged
    # `src/breezy/analysis` package -- same pattern as the archive_table.py
    # override below. The package ceiling (13) stays unchanged.
    "src/breezy/analysis/brier_decomposition.py",
    # SL-8 (FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md, build-slice
    # row SL-8): the hierarchical EMOS calibration + S2 gate module -- same
    # single-module override pattern as SL-7's brier_decomposition.py above.
    # The package ceiling (13) stays unchanged.
    "src/breezy/analysis/nbp_calibration.py",
    "src/breezy/domain",
    "src/breezy/ingest",
    "src/breezy/normalize",
    "src/breezy/persistence",
    "src/breezy/registry",
    "src/breezy/runtime",  # CF-12 Wave 1 (c94066e)
    "src/breezy/settlement",
    "src/breezy/strategy",  # CF-12 Wave 1 (c94066e)
    # FROZEN: regeneration tests pin its bytes (5046132). Never edit it to
    # silence a future error here -- a single-module override pinned by a
    # test is the only sanctioned response (plan, "Carve-outs and don'ts").
    "src/breezy/strategy/current_rung_hold/archive_table.py",
    "tests/fixtures",
    "tests/live",
    "tests/replay",
)

#: Per-package error ceilings, measured at HEAD. Falling below one fails with
#: "lower the ceiling to N" so a ceiling can never go stale.
CEILINGS: Final[dict[str, int]] = {
    "src/breezy/analysis": 13,
    "scripts/analysis": 362,
    "scripts/archive": 8,
    "scripts/venue": 23,
    "tests/contract": 11,
    "tests/integration": 1,
    "tests/strategy": 6,
    "tests/support": 2,
    "tests/unit": 1451,
}


@pytest.fixture(scope="module")
def mypy_report(tmp_path_factory: pytest.TempPathFactory) -> dict[str, int]:
    """Run ONE full-config `mypy` pass from the repo root.

    Never a subset of paths -- following imports changes the counts (plan,
    "Mechanism"). `--cache-dir` is per-worktree so parallel worktrees never
    share (or corrupt) each other's mypy cache.
    """
    cache_dir = tmp_path_factory.mktemp("mypy-ratchet-cache")
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--cache-dir", str(cache_dir)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return parse_mypy_report(result.stdout + result.stderr)


def test_mypy_stays_within_the_cf12_clean_set_and_ceilings(
    mypy_report: dict[str, int],
) -> None:
    """CF-12 Wave 0: mypy 2.3.1 must never exceed a measured ceiling, and
    must never regress a CLEAN package/file above zero errors. A ceiling
    that has gone stale (the real count dropped below it) also fails, so
    burn-down work is caught by the gate rather than left to drift."""
    failures = assess_ratchet(mypy_report, clean=CLEAN, ceilings=CEILINGS)

    assert not failures, "\n".join(failures)
