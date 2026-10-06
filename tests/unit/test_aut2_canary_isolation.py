"""AUT-2 r7 WP8 / section 3.8 (Z14): a canary is isolated from every real input and output.

The canary path writes only ``derived/canary/`` and ``derived/labels_canary/``, on a UTC day with
zero real fills. Reconciliation, the entry guard and portfolio-roi never read it; its rows are never
admissible and never enter ``labels/``, the verdict ``n`` or the completeness counts.
"""

from __future__ import annotations

import ast
import builtins
import contextlib
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis.labeling.completeness import coverage_partition
from breezy.analysis.labeling.fill_source import read_durable_fills
from breezy.analysis.labeling.label_run import (
    CanaryRefused,
    UnitContext,
    main,
    run_canary,
    synthesize_canary_fills,
)
from breezy.persistence.autonomy.canary_store import (
    CANARY_DIR,
    LABELS_CANARY_DIR,
    read_canary_fills,
)
from breezy.persistence.autonomy.label_schema import ExcludedReason
from breezy.persistence.autonomy.label_store import admissible_rows, read_labels
from tests.support.aut2_fixtures import durable_fill, seed_fills

_VENUE = "polymarket_us"
_FAMILY = "pm_us_crh_fq_v1"
_DAY = "2026-10-02"
_NOW = 1_790_000_000_000_000_000
_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src" / "breezy"
#: Every identifier that reaches the canary store. Only the canary path may use any of them.
_NEEDLES = (
    "canary_store",
    "read_canary_fills",
    "write_canary_fills",
    "CANARY_DIR",
    "labels_canary",
)
_ALLOWED_READERS = frozenset(
    {
        _SRC / "persistence" / "autonomy" / "canary_store.py",
        _SRC / "analysis" / "labeling" / "label_run.py",
        _SRC / "analysis" / "labeling" / "proof_window.py",
        _SRC / "analysis" / "labeling" / "proof_source.py",
        # declares the canary writer's own binds; it opens nothing
        _SRC / "runtime" / "autonomy_sandbox" / "table.py",
    }
)


def _canary_references(source: str) -> list[str]:
    """Every name, attribute, import or string literal in ``source`` that names the canary store."""
    hits: list[str] = []
    for node in ast.walk(ast.parse(source)):
        values: list[str] = []
        if isinstance(node, ast.Name):
            values.append(node.id)
        elif isinstance(node, ast.Attribute):
            values.append(node.attr)
        elif isinstance(node, ast.ImportFrom):
            values.extend([node.module or "", *(a.name for a in node.names)])
        elif isinstance(node, ast.Import):
            values.extend(a.name for a in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            values.append(node.value)
        hits.extend(v for v in values if any(n in v for n in _NEEDLES) or "/canary" in v)
    return hits


def _non_canary_sources() -> list[Path]:
    judged = [*_SRC.rglob("*.py"), _REPO / "scripts" / "analysis" / "portfolio_roi_report.py"]
    return [p for p in judged if p not in _ALLOWED_READERS and p.exists()]


@contextlib.contextmanager
def canary_open_guard() -> Iterator[list[str]]:
    """Trip on any open of a canary path, by full path or by directory-fd component name."""
    tripped: list[str] = []
    real_os_open = os.open
    real_open = builtins.open

    def _check(path: object) -> None:
        text = os.fspath(path) if isinstance(path, (str, bytes, os.PathLike)) else ""
        text = text.decode() if isinstance(text, bytes) else text
        if text == "canary" or "/derived/canary" in text or "canary_fills_" in text:
            tripped.append(text)
            raise AssertionError(f"a canary path was opened: {text}")

    def _os_open(path: Any, *args: Any, **kwargs: Any) -> int:
        _check(path)
        return real_os_open(path, *args, **kwargs)

    def _open(file: Any, *args: Any, **kwargs: Any) -> Any:
        _check(file)
        return real_open(file, *args, **kwargs)

    os.open = _os_open
    builtins.open = _open
    try:
        yield tripped
    finally:
        os.open = real_os_open
        builtins.open = real_open


def _run(tmp_path: Path, **over: Any) -> Any:
    args: dict[str, Any] = {
        "data_root": tmp_path,
        "venue": _VENUE,
        "family_id": _FAMILY,
        "day": _DAY,
        "now_ns": _NOW,
        "real_fill_count": 0,
    }
    args.update(over)
    return run_canary(**args)


# -- the ARCH section 4.7 name ----------------------------------------------------------------


def test_reconciliation_and_entry_guard_never_read_canary_store(tmp_path: Path) -> None:
    offenders = {
        str(p.relative_to(_REPO)): refs
        for p in _non_canary_sources()
        if (refs := _canary_references(p.read_text(encoding="utf-8")))
    }
    assert offenders == {}
    scanned = {p.name for p in _non_canary_sources()}
    assert {
        "reconcile.py",
        "fill_source.py",
        "entry_guard.py",
        "portfolio_roi_report.py",
    } <= scanned

    # the runtime half: the read-only reconciliation inputs run with a canary file planted
    _run(tmp_path)
    db = tmp_path / "exec.sqlite"
    seed_fills(db, [durable_fill()])
    with canary_open_guard() as tripped:
        read = read_durable_fills(db)
    assert read.n_keys == 1 and tripped == []


def test_canary_ast_scanner_flags_planted_reader() -> None:
    planted = "from breezy.persistence.autonomy.canary_store import read_canary_fills\n"

    assert _canary_references(planted)
    assert _canary_references("p = '/home/x/derived/canary/polymarket_us'")
    assert _canary_references("import os\n") == []


def test_runtime_canary_guard_trips_on_planted_open(tmp_path: Path) -> None:
    _run(tmp_path)
    planted = tmp_path.joinpath(*CANARY_DIR)

    with canary_open_guard() as tripped, pytest.raises(AssertionError):
        os.open(planted / _VENUE / f"canary_fills_{_DAY}.jsonl", os.O_RDONLY)

    assert tripped


# -- the canary path --------------------------------------------------------------------------


def test_canary_written_only_on_zero_real_fill_day(tmp_path: Path) -> None:
    with pytest.raises(CanaryRefused):
        _run(tmp_path, real_fill_count=1)
    assert not (tmp_path / "derived").exists()

    result = _run(tmp_path)

    assert result.canary_fills == len(read_canary_fills(tmp_path, _VENUE, _DAY)) > 0
    assert (result.real_fills, result.live_fill_check) == (0, "vacuous")


def test_canary_run_is_idempotent_for_the_same_day(tmp_path: Path) -> None:
    first = _run(tmp_path)
    again = _run(tmp_path)

    assert again.canary_fills == first.canary_fills
    assert synthesize_canary_fills(venue=_VENUE, family_id=_FAMILY, day=_DAY) == (
        read_canary_fills(tmp_path, _VENUE, _DAY)
    )


def test_canary_labels_are_never_admissible(tmp_path: Path) -> None:
    result = _run(tmp_path)

    assert result.rows
    assert all(r.excluded_reason is ExcludedReason.CANARY for r in result.rows)
    assert all(r.admissible is False for r in result.rows)
    assert admissible_rows(result.rows) == ()
    assert all(r.p_at_decision is not None for r in result.rows)
    assert result.labelled_with_p and result.reconciliation_passes


def test_canary_rows_excluded_from_verdict_n_and_completeness(tmp_path: Path) -> None:
    before = coverage_partition([], [], now_ns=_NOW, deadline_ns=lambda _r: _NOW)

    result = _run(tmp_path)

    assert read_labels(tmp_path, _FAMILY) == ()
    assert not (tmp_path / "derived" / "labels").exists()
    assert len(read_labels(tmp_path, _FAMILY, labels_dir=LABELS_CANARY_DIR)) == len(result.rows)
    after = coverage_partition([], [], now_ns=_NOW, deadline_ns=lambda _r: _NOW)
    assert after == before and after.durable_fill_count == 0


def test_canary_never_touches_the_exec_store_or_other_stores(tmp_path: Path) -> None:
    _run(tmp_path)

    written = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file())

    assert all(w.startswith(("derived/canary/", "derived/labels_canary/")) for w in written)


def test_portfolio_roi_never_reads_canary() -> None:
    text = (_REPO / "scripts" / "analysis" / "portfolio_roi_report.py").read_text(encoding="utf-8")

    assert _canary_references(text) == []
    assert "/".join(CANARY_DIR) not in text and "labels_canary" not in text


# -- the CLI ----------------------------------------------------------------------------------

_IN_UNIT = UnitContext(
    invocation_id="inv-1", cgroup_path="/user.slice/breezy-label-outcomes.service"
)


def _main(argv: list[str]) -> int:
    return main(argv, unit_context=_IN_UNIT)


_DAY_START_NS = 1_790_899_200_000_000_000  # 2026-10-02T00:00:00Z
_CLI_NOW = _DAY_START_NS + 36 * 3_600_000_000_000  # 2026-10-03T12:00Z: the day is closed


def _argv(root: Path, db: Path, *extra: str) -> list[str]:
    return [
        "--canary",
        "--data-root",
        str(root),
        "--exec-db",
        str(db),
        "--venue",
        _VENUE,
        "--family",
        _FAMILY,
        "--day",
        _DAY,
        "--now-ns",
        str(_CLI_NOW),
        *extra,
    ]


def test_cli_canary_refuses_when_a_real_fill_exists_that_day(tmp_path: Path) -> None:
    db = tmp_path / "exec.sqlite"
    seed_fills(db, [durable_fill(ts_event=_DAY_START_NS + 3_600_000_000_000)])

    rc = _main(_argv(tmp_path / "data", db))

    assert rc != 0 and not (tmp_path / "data" / "derived").exists()


def test_cli_canary_runs_on_a_zero_fill_day_and_ignores_other_days_fills(tmp_path: Path) -> None:
    db = tmp_path / "exec.sqlite"
    seed_fills(db, [durable_fill(ts_event=_DAY_START_NS - 3_600_000_000_000)])
    root = tmp_path / "data"
    root.mkdir(mode=0o700)

    rc = _main(_argv(root, db))

    assert rc == 0 and read_canary_fills(root, _VENUE, _DAY)


def test_cli_canary_with_an_unreadable_exec_store_exits_nonzero(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir(mode=0o700)

    rc = _main(_argv(root, tmp_path / "missing.sqlite"))

    assert rc != 0 and not (root / "derived").exists()


def test_cli_proof_window_has_no_store_source_yet_and_fails_closed(tmp_path: Path) -> None:
    rc = _main(["--proof-window", "--data-root", str(tmp_path), "--start-day", _DAY])

    assert rc == 2 and not (tmp_path / "evidence").exists()


def test_cli_requires_exactly_one_mode(tmp_path: Path) -> None:
    assert _main([]) == 2
    assert _main(["--canary", "--proof-window"]) == 2


def test_cli_canary_refuses_an_open_or_future_day(tmp_path: Path) -> None:
    db = tmp_path / "exec.sqlite"
    seed_fills(db, [durable_fill(ts_event=_DAY_START_NS - 3_600_000_000_000)])
    root = tmp_path / "data"
    root.mkdir(mode=0o700)
    same_day = _argv(root, db)
    same_day[same_day.index("--now-ns") + 1] = str(_DAY_START_NS + 3_600_000_000_000)
    earlier = _argv(root, db)
    earlier[earlier.index("--now-ns") + 1] = str(_DAY_START_NS - 1)

    assert _main(same_day) != 0 and _main(earlier) != 0
    assert not (root / "derived").exists()


def test_a_drill_fill_counts_as_a_real_fill_when_refusing_a_canary(tmp_path: Path) -> None:
    """Deliberately conservative: the day's fill count is every durable fill, drill included."""
    db = tmp_path / "exec.sqlite"
    seed_fills(db, [durable_fill(venue_order_id="drill-1", ts_event=_DAY_START_NS + 1)])

    assert _main(_argv(tmp_path / "data", db)) != 0
