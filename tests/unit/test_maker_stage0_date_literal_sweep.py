"""MAKER-S2 second look C5r D8: every 2026 date literal in the Stage 0 modules is intended."""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_MODULES = sorted((_ROOT / "scripts" / "analysis").glob("maker_stage0_*.py"))
_DATE = re.compile(r"\bdate\(\s*2026\b|\b2026-\d\d-\d\d\b")
# doc paths (contain "/" or end in ".md") are exempt: stripped before matching
_DOC_PATH = re.compile(r"[\w.\-]*(?:/[\w.\-]*)+|[\w.\-]+\.md\b")

#: the exact set of (file, line-substring) pairs for the intended literals
ALLOWLIST: frozenset[tuple[str, str]] = frozenset(
    {
        ("maker_stage0_frozen.py", "outside the rule, 2026-10-01 (sealed holdout day)"),
        ("maker_stage0_frozen.py", "``min(2026-10-13, last FINAL day"),
        ("maker_stage0_frozen.py", "SEALED_DAY: Final[dt.date] = dt.date(2026, 10, 1)"),
        ("maker_stage0_frozen.py", "LAST_ALLOWED_DAY: Final[dt.date] = dt.date(2026, 10, 13)"),
        ("maker_stage0_frozen.py", "FIRST_REPLAYABLE_CHOICES"),
        ("maker_stage0_frozen.py", "minus 2026-10-01."),
        ("maker_stage0_frozen.py", "SECOND_LOOK_FIRST_DAY: Final[dt.date] = dt.date(2026, 10, 14)"),
        ("maker_stage0_frozen.py", "SECOND_LOOK_MAX_DAY: Final[dt.date] = dt.date(2026, 11, 15)"),
        ("maker_stage0_frozen.py", "min(trigger_day, last_final_day, 2026-11-15)"),
        ("maker_stage0_driver.py", "TAIL_RANGE: tuple[dt.date, dt.date] = (dt.date(2026, 7, 1)"),
        ("maker_stage0_render.py", "Holdout touch: replay days 2026-09-18..2026-09-30"),
        ("maker_stage0_render.py", "inside the frozen NBP holdout [2026-07-01, 2026-10-02)"),
        ("maker_stage0_render.py", "2026-10-01 is sealed and never read"),
        ("maker_stage0_render.py", "2026-10-02..2026-10-13 statistics are disclosed"),
        ("maker_stage0_render.py", "days 2026-09-18..2026-09-30 are already past D+14"),
        ("maker_stage0_block_lines.py", "holdout ruling 2026-10-03"),
        ("maker_stage0_runio.py", "(2026-09-17 00:00Z..17:00Z)"),
        ("maker_stage0_inputs.py", "sealed 2026-10-01, days after 2026-10-13"),
        ("maker_stage0_model.py", "(2026-06-30), and"),
        ("maker_stage0_model.py", "FIT_WINDOW_END: Final[dt.date] = dt.date(2026, 6, 30)"),
        ("maker_stage0_verify_first.py", "2026-06-30 (amendment"),
        ("maker_stage0_verify_first.py", "VERIFY_FIRST_DAY: Final = dt.date(2026, 6, 30)"),
    }
)


def _strip(line: str) -> str:
    return _DOC_PATH.sub("", line)


def _hits() -> list[tuple[str, int, str]]:
    found = []
    for path in _MODULES:
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _DATE.search(_strip(line)):
                found.append((path.name, no, line))
    return found


def test_no_unlisted_block_date_literals_in_maker_stage0_modules() -> None:
    bad = [
        f"{name}:{no}: {line.strip()}"
        for name, no, line in _hits()
        if not any(f == name and pat in line for f, pat in ALLOWLIST)
    ]
    assert not bad, "unlisted date literals:\n" + "\n".join(bad)


def test_sweep_allowlist_has_no_stale_entries() -> None:
    hits = _hits()
    stale = [
        (f, p) for f, p in sorted(ALLOWLIST) if not any(f == n and p in line for n, _, line in hits)
    ]
    assert not stale, f"allowlist entries matching no hit: {stale}"


def test_sweep_flags_an_injected_literal_and_exempts_doc_paths() -> None:
    assert _DATE.search(_strip("x = dt.date(2026, 11, 2)"))
    assert _DATE.search(_strip('"window 2026-11-02..2026-11-09"'))
    assert not _DATE.search(_strip("see docs/evidence/RULING_2026-10-13.md here"))
    assert not _DATE.search(_strip("SPEC_pm_us_no_ladder_maker_2026-10-12.md"))
