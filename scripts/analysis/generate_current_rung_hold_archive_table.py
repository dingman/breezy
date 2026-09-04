#!/usr/bin/env python3
"""Generate the frozen `archive_table.py` for `breezy.strategy.current_rung_hold`.

Spec: `docs/plans/CURRENT_RUNG_HOLD_BLUEPRINT_2026-09-04.md` SS2
(`archive_table.py`). Calls `mb_current_rung_edge_study.build_archive_table`
directly -- Part A only, never `main()`, which also runs Part B's live tape
join -- over the study's own default corpus
(`ARCHIVE_START_DATE..ARCHIVE_END_DATE`, `DEFAULT_ARCHIVE_CACHE_DIR`), and
writes a GENERATED, FROZEN module with a provenance header (this generator's
path and argv, the corpus date range, a sha256 manifest over every ASOS/CLI
cache file the run actually read, the study module's git sha, and a UTC
generation timestamp). Regenerating against an unchanged corpus reproduces
the module byte-for-byte except that timestamp line
(`tests/unit/test_current_rung_hold_archive_table.py`).

No network: every input is a cache-hit read from
`--archive-cache-dir` (default: the study's `DEFAULT_ARCHIVE_CACHE_DIR`); a
cache miss raises `SystemExit` from `load_archive_days_and_finals` itself,
exactly as it does for the study's own CLI.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import subprocess
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Final

_SCRIPTS_ANALYSIS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))

from mb_current_rung_edge_study import (
    ARCHIVE_END_DATE,
    ARCHIVE_HOURS,
    ARCHIVE_START_DATE,
    DEFAULT_ARCHIVE_CACHE_DIR,
    DENSE_STATIONS,
    WIDTH_INTERIOR,
    WIDTH_OPEN_LOWER,
    WIDTH_OPEN_UPPER,
    ArchiveCell,
    ArchiveCellKey,
    build_archive_table,
    load_archive_days_and_finals,
)
from pmr_climatology_study import RunningMaxDay
from settlement_alignment_study import (
    afos_url,
    asos_url,
    cache_path_for_url,
    load_sites,
    year_chunks,
)

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT: Final[Path] = (
    REPO_ROOT / "src" / "breezy" / "strategy" / "current_rung_hold" / "archive_table.py"
)
STUDY_RELATIVE_PATH: Final[str] = "scripts/analysis/mb_current_rung_edge_study.py"

#: `width` string -> the int code stored in the frozen table's key. Fixed
#: forever once a table has been generated with it -- changing these numbers
#: silently reinterprets every published cell.
WIDTH_CODES: Final[dict[str, int]] = {
    WIDTH_INTERIOR: 0,
    WIDTH_OPEN_UPPER: 1,
    WIDTH_OPEN_LOWER: 2,
}


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-cache-dir", default=str(DEFAULT_ARCHIVE_CACHE_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser.parse_args(argv)


def _corpus_files(*, cache_dir: Path, cities: Sequence[str]) -> list[Path]:
    """Every cache file `load_archive_days_and_finals` reads for `cities`.

    One ASOS `.txt` per city plus one AFOS CLI `.zip` per calendar-year chunk
    of `[ARCHIVE_START_DATE, ARCHIVE_END_DATE]` -- exactly the files
    `load_archive_days_and_finals` (ASOS) and `load_cli_records` (CLI, via
    `iter_cached_cli_products`) open, so the sha256 manifest below covers
    precisely the bytes that determine the table, no more and no less.
    """
    specs_by_city = {spec.city: spec for spec in load_sites()}
    files: list[Path] = []
    for city in cities:
        spec = specs_by_city[city]
        files.append(
            cache_path_for_url(
                cache_dir,
                asos_url(spec.iem_asos_id, ARCHIVE_START_DATE, ARCHIVE_END_DATE),
                ".txt",
            )
        )
        for chunk_start, chunk_end in year_chunks(ARCHIVE_START_DATE, ARCHIVE_END_DATE):
            files.append(
                cache_path_for_url(
                    cache_dir,
                    afos_url(spec.site.cli_location, chunk_start, chunk_end, limit=3_000),
                    ".zip",
                )
            )
    return sorted(files, key=lambda path: path.name)


def corpus_sha256(files: Sequence[Path]) -> str:
    """A single sha256 over a sorted `name:sha256(bytes)` manifest of `files`."""
    manifest = hashlib.sha256()
    for path in files:
        if not path.exists():
            raise SystemExit(f"corpus cache file missing: {path}")
        manifest.update(path.name.encode("utf-8"))
        manifest.update(b":")
        manifest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("utf-8"))
        manifest.update(b"\n")
    return manifest.hexdigest()


def study_git_sha(*, repo_root: Path = REPO_ROOT) -> str:
    """The git sha the study module was last committed at, in `repo_root`."""
    result = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", STUDY_RELATIVE_PATH],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    sha = result.stdout.strip()
    if not sha:
        raise SystemExit(f"no git history for {STUDY_RELATIVE_PATH} in {repo_root}")
    return sha


def _quantize(value: float) -> Decimal:
    """String-construct a `Decimal` at the study's own 4-decimal precision."""
    return Decimal(f"{value:.4f}")


def build_frozen_table(
    *, archive_cache_dir: Path
) -> dict[tuple[str, str, int, int, int], Decimal | None]:
    """Run Part A only and re-key each cell to the frozen table's int-only key."""
    specs_by_city = {spec.city: spec for spec in load_sites() if spec.city in DENSE_STATIONS}
    days_by_city: dict[str, tuple[RunningMaxDay, ...]] = {}
    finals_by_city: dict[str, dict[dt.date, int]] = {}
    for city in DENSE_STATIONS:
        spec = specs_by_city[city]
        days, finals = load_archive_days_and_finals(cache_dir=archive_cache_dir, spec=spec)
        days_by_city[city] = days
        finals_by_city[city] = finals
    archive: dict[ArchiveCellKey, ArchiveCell] = build_archive_table(
        days_by_city, finals_by_city, hours=ARCHIVE_HOURS
    )
    table: dict[tuple[str, str, int, int, int], Decimal | None] = {}
    for (city, season, hour, width, m), cell in archive.items():
        width_code = WIDTH_CODES[width]
        m_code = 0 if m is None else m
        p_hold_lower = cell.p_hold_lower
        table[(city, season, hour, width_code, m_code)] = (
            None if p_hold_lower is None else _quantize(p_hold_lower)
        )
    return table


def render_module(
    *,
    table: dict[tuple[str, str, int, int, int], Decimal | None],
    corpus_sha256_hex: str,
    study_sha: str,
    argv: Sequence[str],
    generated_at: dt.datetime,
) -> str:
    """Render the frozen module's exact source text.

    Deterministic given `table`/`corpus_sha256_hex`/`study_sha`/`argv`: the
    dict is emitted in sorted-key order and the only line that varies between
    two runs against an unchanged corpus is the `Generated at (UTC):` line.
    """
    argv_repr = " ".join(argv) if argv else "(no arguments)"
    header = f'''"""FROZEN Part A archive p_hold table for `current_rung_hold`.

GENERATED -- do not hand-edit. Regenerate via:
    python scripts/analysis/generate_current_rung_hold_archive_table.py {argv_repr}

Corpus: {ARCHIVE_START_DATE.isoformat()}..{ARCHIVE_END_DATE.isoformat()}
(`mb_current_rung_edge_study.ARCHIVE_START_DATE` / `.ARCHIVE_END_DATE`),
complete 24h days only, dense stations only (NYC excluded, L-13).
Corpus sha256 (manifest over every ASOS/CLI cache file this run read):
    {corpus_sha256_hex}
Study git sha ({STUDY_RELATIVE_PATH}):
    {study_sha}
Generated at (UTC): {generated_at.isoformat()}

Key: `(station, season, hour_lst, width_code, m_code)`.
`width_code`: 0 = interior_2F, 1 = open_upper, 2 = open_lower.
`m_code`: interior margin (0 or 1, per the memo's geometry correction); fixed
at 0 on the two open tails, which have no margin axis.
Value: the Wilson 95%-lower bound on `p_hold`, or `None` below `N_MIN`
(never `0.0` -- an under-powered cell is undefined, not the worst cell).
"""'''
    lines = [
        header,
        "",
        "from __future__ import annotations",
        "",
        "from collections.abc import Mapping",
        "from decimal import Decimal",
        "from types import MappingProxyType",
        "from typing import Final",
        "",
        '__all__ = ["CORPUS_SHA256", "P_HOLD_LOWER", "STUDY_GIT_SHA"]',
        "",
        f'CORPUS_SHA256: Final[str] = "{corpus_sha256_hex}"',
        f'STUDY_GIT_SHA: Final[str] = "{study_sha}"',
        "",
        "P_HOLD_LOWER: Final[Mapping[tuple[str, str, int, int, int], Decimal | None]] = (",
        "    MappingProxyType(",
        "        {",
    ]
    for key in sorted(table.keys()):
        value = table[key]
        value_repr = "None" if value is None else f'Decimal("{value}")'
        city, season, hour, width_code, m_code = key
        lines.append(
            f'            ("{city}", "{season}", {hour}, {width_code}, {m_code}): '
            f"{value_repr},"
        )
    lines.extend(["        },", "    )", ")", ""])
    return "\n".join(lines)


def generate(
    *,
    argv: Sequence[str] | None = None,
    now: dt.datetime | None = None,
) -> tuple[str, dict[tuple[str, str, int, int, int], Decimal | None], str]:
    """Build the frozen module source. Returns `(source, table, corpus_sha)`."""
    parsed_argv = list(argv) if argv is not None else list(sys.argv[1:])
    args = _parse_args(parsed_argv)
    archive_cache_dir = Path(args.archive_cache_dir).expanduser()
    table = build_frozen_table(archive_cache_dir=archive_cache_dir)
    files = _corpus_files(cache_dir=archive_cache_dir, cities=DENSE_STATIONS)
    sha = corpus_sha256(files)
    sha_study = study_git_sha()
    generated_at = now if now is not None else dt.datetime.now(dt.UTC).replace(microsecond=0)
    source = render_module(
        table=table,
        corpus_sha256_hex=sha,
        study_sha=sha_study,
        argv=parsed_argv,
        generated_at=generated_at,
    )
    return source, table, sha


def main(argv: Sequence[str] | None = None) -> int:
    parsed_argv = list(argv) if argv is not None else list(sys.argv[1:])
    args = _parse_args(parsed_argv)
    source, table, sha = generate(argv=parsed_argv)
    output_path = Path(args.output).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(source, encoding="utf-8")
    n_cells = len(table)
    n_defined = sum(1 for value in table.values() if value is not None)
    print(
        f"[generate-current-rung-hold-archive-table] wrote {output_path} "
        f"({n_cells} cells, {n_defined} defined, corpus sha256={sha})",
        file=sys.stderr,
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
