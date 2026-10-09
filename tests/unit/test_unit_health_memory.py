"""AUT-6 WP3 S5: the memory budget ``#31 aut6.memory_budget`` (plan r15 3.10.1; V14, F10, F11).

A synthetic ``deploy/systemd`` and synthetic show blocks make every condition exact; the static
scan and the in-process lock test also read the real tree.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from breezy.persistence.autonomy.detector_catalog import CATALOG
from breezy.runtime import monitor_watch_memory as mem
from breezy.runtime.autonomy_sandbox.table import AUTONOMY_BWRAP_TABLE
from breezy.runtime.monitor_watch import NOT_DEPLOYED_ARTIFACTS, NOT_YET_DEPLOYED
from breezy.runtime.monitor_watch_memory import (
    GIB,
    IN_PROCESS_STUDIES_LOCK_UNITS,
    MEMORY_CRITICAL_FROM,
    addback_kib,
    addback_units,
    evaluate_memory,
    own_lock_units,
    parse_size,
    studies_lock_holders,
)
from breezy.runtime.unit_health_store import MemAvailWindow
from tests.support.monitor_watch_fixtures import (
    GOOD_WINDOW,
    REPO_DEPLOY,
    write_deploy,
)
from tests.support.unit_health_fixtures import NOW_NS, NS, show_block
from tests.unit.test_unit_health import harness

HOLDER = "breezy-study-a.service"
OTHER_HOLDER = "breezy-study-b.service"
OWN_A = "breezy-autonomy-health.service"
OWN_B = "breezy-autonomy-canary.service"
INGEST = "breezy-quote-tape-ingest.service"
TODAY = "2026-10-08"
SRC = Path(mem.__file__).resolve().parents[1]  # src/breezy


def unit_text(*, max_: str = "2G", high: str = "1G", exec_line: str = "/bin/true") -> str:
    return f"[Service]\nExecStart={exec_line}\nMemoryHigh={high}\nMemoryMax={max_}\n"


def timer_text(calendar: str) -> str:
    return f"[Timer]\nOnCalendar={calendar}\n"


LOCKED = "/home/jon/breezy/deploy/systemd/study-run.sh"


@pytest.fixture
def deploy(tmp_path: Path) -> Path:
    return write_deploy(
        tmp_path / "deploy",
        {
            HOLDER: unit_text(exec_line=LOCKED),
            "breezy-study-a.timer": timer_text("*-*-* 12:00:00 UTC"),
            OTHER_HOLDER: unit_text(exec_line="/usr/bin/flock -n %t/breezy-studies.lock /bin/true"),
            "breezy-study-b.timer": timer_text("*-*-* 13:00:00 UTC"),
            "study-run.sh": '#!/bin/bash\nLOCK="$LOCK_DIR/breezy-studies.lock"\nflock -n 9\n',
            OWN_A: unit_text(max_="256M", high="128M"),
            OWN_B: unit_text(max_="128M", high="64M"),
            INGEST: unit_text(max_="2G", high="1G"),
            "breezy-nolock.service": unit_text(
                exec_line="/home/jon/breezy/deploy/systemd/quiet.sh"
            ),
            "quiet.sh": "#!/bin/bash\n# does NOT use breezy-studies.lock\necho hi\n",
        },
    )


def blocks(**per_unit: dict[str, str]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for unit, props in per_unit.items():
        name = unit.replace("_", "-") + ".service"
        text = show_block(name, **props)
        out[name] = dict(line.split("=", 1) for line in text.strip().splitlines())
    return out


def effective(**overrides: dict[str, str]) -> dict[str, dict[str, str]]:
    """Blocks equal to the synthetic files unless overridden (``_`` stands for ``-``)."""
    base = {
        HOLDER: {"MemoryMax": str(2 * GIB), "MemoryHigh": str(GIB)},
        OTHER_HOLDER: {"MemoryMax": str(2 * GIB), "MemoryHigh": str(GIB)},
        OWN_A: {"MemoryMax": str(256 * 2**20), "MemoryHigh": str(128 * 2**20)},
        OWN_B: {"MemoryMax": str(128 * 2**20), "MemoryHigh": str(64 * 2**20)},
        INGEST: {"MemoryMax": str(2 * GIB), "MemoryHigh": str(GIB)},
    }
    for key, props in overrides.items():
        unit = key.replace("_", "-") + ".service"
        base[unit] = {**base.get(unit, {}), **props}
    return {
        unit: dict(line.split("=", 1) for line in show_block(unit, **p).strip().splitlines())
        for unit, p in base.items()
    }


def check(deploy: Path, blocks_: dict[str, dict[str, str]], **kw: Any) -> Any:
    defaults: dict[str, Any] = {
        "window": GOOD_WINDOW,
        "node_rss_kib": 1_000_000,
        "recorder_rss_kib": 500_000,
        "today": TODAY,
    }
    defaults.update(kw)
    return evaluate_memory(deploy_dir=deploy, blocks=blocks_, **defaults)


def violations(result: Any) -> set[str]:
    return set(result.metrics.get("violations", "").split(",")) - {""}


# --------------------------------------------------------------------------- the sum


def test_a_budget_inside_every_condition_passes(deploy: Path) -> None:
    result = check(deploy, effective())
    assert result.outcome == "PASS", result.metrics
    assert result.metrics["memory_sum_kib"]


def test_health_memory_sum_within_memavailable(deploy: Path) -> None:
    """ARCH: max(holder) + sum(own-lock) + ingest + node and recorder RSS against the free side."""
    holder = 2 * GIB // 1024
    own = (256 + 128) * 2**20 // 1024
    ingest = 2 * GIB // 1024
    expected = holder + own + ingest + 1_000_000 + 500_000
    fits = MemAvailWindow(expected, expected, 144, None)
    assert check(deploy, effective(), window=fits).outcome == "PASS"
    tight = MemAvailWindow(expected - 1, expected - 1, 144, None)
    result = check(deploy, effective(), window=tight)
    assert violations(result) == {"memory_sum_over_memavailable"}
    assert result.metrics["memory_sum_kib"] == str(expected)


def test_memory_sum_uses_24h_minimum_memavailable(tmp_path: Path, deploy: Path) -> None:
    """F10: one tight pass in the last 24 h decides, not the instantaneous value."""
    from breezy.runtime.unit_health_store import HealthStore

    store = HealthStore(tmp_path / "uh")
    for i in range(144):
        store.append_memavail(NOW_NS - (i + 1) * 600 * NS, 30_000_000, 30_000_000)
    assert check(deploy, effective(), window=store.memavail_window(NOW_NS)).outcome == "PASS"
    store.append_memavail(NOW_NS - 3 * 3600 * NS, 1_000_000, 1_000_000)  # one tight night pass
    window = store.memavail_window(NOW_NS)
    assert window.minimum_free_kib == 1_000_000
    result = check(deploy, effective(), window=window)
    assert violations(result) == {"memory_sum_over_memavailable"}


def test_memavail_samples_insufficient_is_inconclusive(tmp_path: Path, deploy: Path) -> None:
    from breezy.runtime.unit_health_store import HealthStore

    store = HealthStore(tmp_path / "uh")
    for i in range(71):
        store.append_memavail(NOW_NS - (i + 1) * 600 * NS, 30_000_000, 30_000_000)
    result = check(deploy, effective(), window=store.memavail_window(NOW_NS))
    assert result.outcome == "INCONCLUSIVE"
    assert result.metrics["unknown_reason"] == "memavail_samples_insufficient"
    assert not result.findings and not result.unknown_reasons


def test_insufficient_samples_do_not_hide_a_static_violation(deploy: Path) -> None:
    window = MemAvailWindow(None, None, 3, "memavail_samples_insufficient")
    result = check(deploy, effective(breezy_study_a={"MemoryMax": str(15 * GIB)}), window=window)
    assert result.outcome == "FAIL" and "holder_memory_max_over_14g:" + HOLDER in violations(result)


def test_memory_sum_adds_back_resident_memory_once(deploy: Path) -> None:
    """Section 3.10.1 item 6: ``MemAvailable_free = MemAvailable + sum(MemoryCurrent)`` of every
    counted unit, each unit once even when it is named twice."""
    units = addback_units(deploy)
    assert {HOLDER, OTHER_HOLDER, OWN_A, OWN_B, INGEST} <= units
    assert {mem.NODE_UNIT, mem.RECORDER_UNIT} <= units
    current = {u: {"MemoryCurrent": str(100 * 2**20)} for u in units}
    assert addback_kib(current, units) == len(units) * 100 * 1024
    assert addback_kib(current, [*units, *units]) == len(units) * 100 * 1024
    assert addback_kib({"x": {"MemoryCurrent": str(2**64 - 1)}}, {"x"}) == 0  # unset: skipped


def test_health_pass_appends_the_widened_addback_sample(tmp_path: Path, deploy: Path) -> None:
    from tests.support.monitor_watch_fixtures import snapshot, wiring

    cur = str(100 * 2**20)
    block = show_block(HOLDER, MemoryCurrent=cur) + "\n" + show_block(OWN_A, MemoryCurrent=cur)
    h = harness(
        tmp_path,
        snapshot=lambda: snapshot(blocks=[block]),
        meminfo=lambda: (8_000_000, 16_000_000),
        watch=wiring(tmp_path, deploy, rows=NOT_YET_DEPLOYED, artifacts=NOT_DEPLOYED_ARTIFACTS),
    )
    h.run()
    sample = json.loads(next(h.store.root.glob("memavail_*.jsonl")).read_text().splitlines()[0])
    assert sample["mem_available_free_kib"] == 8_000_000 + 2 * 100 * 1024


def test_unreadable_rss_makes_the_pass_unknown_not_a_pass(deploy: Path) -> None:
    result = check(deploy, effective(), node_rss_kib=None)
    assert result.unknown_reasons == ("memory_rss_unreadable",)
    assert result.outcome != "PASS"


# --------------------------------------------------------------------------- conditions 1 and 2


def test_memory_budget_fails_study_cap_over_14g_without_named_raise(deploy: Path) -> None:
    big = effective(breezy_study_a={"MemoryMax": str(15 * GIB), "MemoryHigh": str(11 * GIB)})
    assert f"holder_memory_max_over_14g:{HOLDER}" in violations(check(deploy, big))
    exactly = effective(breezy_study_a={"MemoryMax": str(14 * GIB), "MemoryHigh": str(12 * GIB)})
    assert not violations(check(deploy, exactly, window=MemAvailWindow(10**9, 10**9, 144, None)))
    high = effective(breezy_study_a={"MemoryMax": str(14 * GIB), "MemoryHigh": str(13 * GIB)})
    assert f"holder_memory_high_over_12g:{HOLDER}" in violations(check(deploy, high))
    named = {HOLDER: 15 * GIB}
    ok = check(deploy, big, raised=named, window=MemAvailWindow(10**9, 10**9, 144, None))
    assert f"holder_memory_max_over_14g:{HOLDER}" not in violations(ok)


def test_memory_budget_named_raise_over_16g_or_in_window_fails(deploy: Path) -> None:
    named = {HOLDER: 15 * GIB}
    window = MemAvailWindow(10**9, 10**9, 144, None)
    over = effective(breezy_study_a={"MemoryMax": str(17 * GIB), "MemoryHigh": str(GIB)})
    assert f"raised_cap_over_16g:{HOLDER}" in violations(
        check(deploy, over, raised=named, window=window)
    )
    # 12:00Z is outside [16:30Z, 01:15Z) and outside [01:00Z, 04:30Z): a clean raised cap
    clean = effective(breezy_study_a={"MemoryMax": str(15 * GIB), "MemoryHigh": str(GIB)})
    assert not violations(check(deploy, clean, raised=named, window=window))
    for calendar, kind in (
        ("*-*-* 17:00:00 UTC", "raised_cap_in_window"),
        ("*-*-* 00:30:00 UTC", "raised_cap_in_window"),
        ("*-*-* 16:30:00 UTC", "raised_cap_in_window"),
    ):
        (deploy / "breezy-study-a.timer").write_text(timer_text(calendar))
        assert f"{kind}:{HOLDER}" in violations(check(deploy, clean, raised=named, window=window))
    (deploy / "breezy-study-a.timer").write_text(timer_text("*-*-* 01:15:00 UTC"))
    assert f"raised_cap_in_window:{HOLDER}" not in violations(
        check(deploy, clean, raised=named, window=window)
    )


def test_a_raised_cap_sharing_a_slot_with_another_heavy_unit_fails(deploy: Path) -> None:
    named = {HOLDER: 15 * GIB}
    both = effective(
        breezy_study_a={"MemoryMax": str(15 * GIB), "MemoryHigh": str(GIB)},
        breezy_study_b={"MemoryMax": str(6 * GIB), "MemoryHigh": str(GIB)},
    )
    (deploy / "breezy-study-b.timer").write_text(timer_text("*-*-* 12:00:00 UTC"))
    result = check(deploy, both, raised=named, window=MemAvailWindow(10**9, 10**9, 144, None))
    assert f"raised_cap_shares_slot:{HOLDER}" in violations(result)


def test_memory_budget_uses_effective_memorymax_including_dropins(deploy: Path) -> None:
    """The file says 2G; the effective value (a drop-in) is 15G: the effective one is judged."""
    with_dropin = effective(
        breezy_study_a={
            "MemoryMax": str(15 * GIB),
            "DropInPaths": "/home/jon/.config/systemd/user/breezy-study-a.service.d/x.conf",
        }
    )
    assert f"holder_memory_max_over_14g:{HOLDER}" in violations(check(deploy, with_dropin))
    # without a block the committed file is the best available limit
    only_files = {k: v for k, v in effective().items() if k != HOLDER}
    assert not any("holder_memory_max" in v for v in violations(check(deploy, only_files)))
    (deploy / HOLDER).write_text(unit_text(max_="15G", high="1G", exec_line=LOCKED))
    assert f"holder_memory_max_over_14g:{HOLDER}" in violations(check(deploy, only_files))


# --------------------------------------------------------------------------- conditions 3-7


def test_memory_budget_fails_study_peak_at_memory_high_by_name(deploy: Path) -> None:
    hit = effective(breezy_study_a={"MemoryHigh": str(GIB), "MemoryPeak": str(GIB)})
    assert f"study_peak_at_memory_high:{HOLDER}" in violations(check(deploy, hit))
    below = effective(breezy_study_a={"MemoryHigh": str(GIB), "MemoryPeak": str(GIB - 1)})
    assert "study_peak_at_memory_high" not in ",".join(violations(check(deploy, below)))
    unset = effective(breezy_study_a={"MemoryHigh": str(GIB), "MemoryPeak": "[not set]"})
    assert "study_peak_at_memory_high" not in ",".join(violations(check(deploy, unset)))


def test_memory_budget_fails_own_lock_sum_over_4g(deploy: Path) -> None:
    over = effective(
        breezy_autonomy_health={"MemoryMax": str(3 * GIB)},
        breezy_autonomy_canary={"MemoryMax": str(GIB + 1)},
    )
    assert "own_lock_sum_over_4g" in violations(check(deploy, over))
    exactly = effective(
        breezy_autonomy_health={"MemoryMax": str(3 * GIB)},
        breezy_autonomy_canary={"MemoryMax": str(GIB)},
    )
    assert "own_lock_sum_over_4g" not in violations(check(deploy, exactly))


def test_memory_budget_names_ingest_while_dropin_stands(deploy: Path) -> None:
    standing = effective(
        breezy_quote_tape_ingest={
            "DropInPaths": "/home/jon/.config/systemd/user/breezy-quote-tape-ingest.service.d/"
            "zz-memory-containment-TEMPORARY.conf"
        }
    )
    assert "ingest_temporary_dropin_stands" in violations(check(deploy, standing))
    assert "ingest_temporary_dropin_stands" not in violations(check(deploy, effective()))


def test_memory_budget_fails_heavy_unit_firing_0100_0430(deploy: Path) -> None:
    heavy = effective(breezy_study_b={"MemoryMax": str(5 * GIB), "MemoryHigh": str(GIB)})
    for calendar, hit in (
        ("*-*-* 01:00:00 UTC", True),
        ("*-*-* 04:29:00 UTC", True),
        ("*-*-* 04:30:00 UTC", False),
        ("*-*-* 00:59:00 UTC", False),
    ):
        (deploy / "breezy-study-b.timer").write_text(timer_text(calendar))
        found = f"heavy_unit_firing_0100_0430:{OTHER_HOLDER}" in violations(check(deploy, heavy))
        assert found is hit, calendar
    (deploy / "breezy-study-b.timer").write_text(timer_text("*-*-* 02:00:00 UTC"))
    four = effective(breezy_study_b={"MemoryMax": str(4 * GIB), "MemoryHigh": str(GIB)})
    assert not any("heavy_unit" in v for v in violations(check(deploy, four)))  # 4G is not > 4G


# --------------------------------------------------------------------------- infinity (F11)


def test_memory_budget_infinity_memorymax_fails(deploy: Path) -> None:
    """An absent limit or ``infinity`` is +inf: it fails conditions 1, 4 and 6, never skipped."""
    window = MemAvailWindow(10**12, 10**12, 144, None)
    holder = check(deploy, effective(breezy_study_a={"MemoryMax": "infinity"}), window=window)
    assert f"holder_memory_max_infinity:{HOLDER}" in violations(holder)
    own = check(deploy, effective(breezy_autonomy_health={"MemoryMax": "infinity"}), window=window)
    assert f"own_lock_memory_max_infinity:{OWN_A}" in violations(own)
    ingest = check(
        deploy, effective(breezy_quote_tape_ingest={"MemoryMax": "infinity"}), window=window
    )
    assert "memory_sum_infinite" in violations(ingest)
    # an absent limit: no block and no directive in the file
    (deploy / OWN_B).write_text("[Service]\nExecStart=/bin/true\n")
    no_block = {k: v for k, v in effective().items() if k != OWN_B}
    assert f"own_lock_memory_max_infinity:{OWN_B}" in violations(
        check(deploy, no_block, window=window)
    )


def test_parse_size_forms() -> None:
    assert parse_size("14G") == 14 * GIB and parse_size("512M") == 512 * 2**20
    assert parse_size("1536M") == 1536 * 2**20 and parse_size("2147483648") == 2 * GIB
    assert parse_size("infinity") == float("inf") and parse_size(str(2**64 - 1)) == float("inf")
    assert parse_size("[not set]") is None and parse_size("") is None


# --------------------------------------------------------------------------- severity


def test_memory_budget_warn_before_2026_10_16_critical_from(deploy: Path) -> None:
    """Row #31: WARNING until 2026-10-16, CRITICAL from it."""
    bad = effective(breezy_study_a={"MemoryMax": str(15 * GIB)})
    assert check(deploy, bad, today="2026-10-15").findings[0].severity == "WARNING"
    assert check(deploy, bad, today="2026-10-16").findings[0].severity == "CRITICAL"
    row = next(r for r in CATALOG if r.id == "aut6.memory_budget")
    assert row.critical_from == MEMORY_CRITICAL_FROM == "2026-10-16"


def test_the_finding_key_changes_with_the_violation_set(deploy: Path) -> None:
    one = check(deploy, effective(breezy_study_a={"MemoryMax": str(15 * GIB)}))
    two = check(
        deploy,
        effective(
            breezy_study_a={"MemoryMax": str(15 * GIB)}, breezy_study_b={"MemoryMax": str(15 * GIB)}
        ),
    )
    assert one.findings[0].key != two.findings[0].key
    again = check(deploy, effective(breezy_study_a={"MemoryMax": str(15 * GIB)}))
    assert one.findings[0].key == again.findings[0].key


def test_an_unsupported_calendar_is_unknown_not_a_crash(deploy: Path) -> None:
    (deploy / "breezy-study-a.timer").write_text("[Timer]\nOnCalendar=weekly\n")
    result = check(deploy, effective())
    assert result.unknown_reasons == ("calendar_unsupported:breezy-study-a.timer",)


# --------------------------------------------------------------------------- the static scan (F11)


def test_studies_holders_identified_by_static_execstart_scan_ignoring_comments(
    deploy: Path,
) -> None:
    holders = studies_lock_holders(deploy)
    assert {HOLDER, OTHER_HOLDER} <= holders  # via the script, and via a direct flock
    assert "breezy-nolock.service" not in holders  # the lock is named only in a comment
    commented = (
        "[Service]\n# ExecStart=/usr/bin/flock %t/breezy-studies.lock /bin/true\n"
        "ExecStart=/bin/true\n"
    )
    (deploy / "breezy-commented.service").write_text(commented)
    assert "breezy-commented.service" not in studies_lock_holders(deploy)
    continued = "[Service]\nExecStart=/usr/bin/flock -n \\\n  %t/breezy-studies.lock /bin/true\n"
    (deploy / "breezy-continued.service").write_text(continued)
    assert "breezy-continued.service" in studies_lock_holders(deploy)


def test_the_real_tree_holders_follow_the_executable_lines() -> None:
    holders = studies_lock_holders(REPO_DEPLOY)
    # score-live-trials names the lock only in a comment ("NOT a member of breezy-studies.lock")
    assert "breezy-score-live-trials.service" not in holders
    assert "breezy-portfolio-roi.service" in holders
    assert holders >= IN_PROCESS_STUDIES_LOCK_UNITS & {
        p.name for p in REPO_DEPLOY.glob("*.service")
    }


def test_own_lock_units_are_the_autonomy_units_without_the_studies_lock() -> None:
    own = own_lock_units(REPO_DEPLOY, studies_lock_holders(REPO_DEPLOY))
    assert {
        "breezy-autonomy-health.service",
        "breezy-autonomy-canary.service",
        "breezy-autonomy-alert-redeliver.service",
    } <= own
    assert "breezy-quote-tape.service" not in own  # the recorder's stop-hook sub-row owns no lock
    assert not own & studies_lock_holders(REPO_DEPLOY)


def test_in_process_studies_lock_units_are_derived_from_the_table_rows() -> None:
    expected = {
        unit
        for row in AUTONOMY_BWRAP_TABLE.values()
        if row.studies_lock and not row.name.startswith("breezy-autonomy-selftest")
        for unit in row.units
    }
    assert IN_PROCESS_STUDIES_LOCK_UNITS == expected and expected


def lock_openers(source: str) -> bool:
    """True when the module takes the studies lock: it calls ``acquire_studies_lock`` or holds the
    lock's file name as a string constant (comments and docstrings are not code)."""
    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.FunctionDef | ast.ClassDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name == "acquire_studies_lock":
                return True
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
            and "breezy-studies.lock" in node.value
        ):
            return True
    return False


def test_lock_opener_detection_positive_controls() -> None:
    assert lock_openers("acquire_studies_lock(path)")
    assert lock_openers("x.acquire_studies_lock(path)")
    assert lock_openers("NAME = 'breezy-studies.lock'")
    assert not lock_openers('"""mentions breezy-studies.lock"""\nx = 1')
    assert not lock_openers("# breezy-studies.lock\nx = 1")


def test_in_process_studies_lock_openers_are_listed() -> None:
    """F11 (AST): every ``src/`` module that opens ``breezy-studies.lock`` is the entry module of a
    table row with ``studies_lock=True``, whose units are in ``IN_PROCESS_STUDIES_LOCK_UNITS``."""
    entry_to_units: dict[str, set[str]] = {}
    for row in AUTONOMY_BWRAP_TABLE.values():
        if row.studies_lock and not row.name.startswith("breezy-autonomy-selftest"):
            for module in row.entry_modules:
                entry_to_units.setdefault(module, set()).update(row.units)
    sandbox = SRC / "runtime" / "autonomy_sandbox"
    unmapped: list[str] = []
    seen = 0
    for path in sorted(SRC.rglob("*.py")):
        if sandbox in path.parents or path.name.startswith("monitor_watch"):
            continue  # the helper, the wrapper's mount code and this check only name the lock
        if not lock_openers(path.read_text(encoding="utf-8")):
            continue
        seen += 1
        module = ".".join(("breezy", *path.relative_to(SRC).with_suffix("").parts))
        units = entry_to_units.get(module)
        if not units or not units <= IN_PROCESS_STUDIES_LOCK_UNITS:
            unmapped.append(module)
    assert seen >= 2, "the scan found no lock opener at all: it is blind"
    assert unmapped == [], f"unlisted in-process studies-lock openers: {unmapped}"
