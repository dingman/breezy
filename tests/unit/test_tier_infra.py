"""Tier runner, heavy-mark allowlist, and the collect-only partition check.

T1 owns this module. ``heavy`` must not appear here: the partition check and
the allowlist are the things that keep a later edit from shrinking coverage.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TIER_SCRIPT = _REPO_ROOT / "scripts" / "ci" / "run_tier.sh"
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_EXCL = "not live and not venue_live and not real_money"
_NODEID = re.compile(r"^tests/.+\.py::")

#: Empty until a later step marks real heavy tests. A file not listed here
#: must not carry ``pytest.mark.heavy``.
HEAVY_ALLOWLIST: tuple[str, ...] = ()

#: Guard and safety scans that stay in the fast tier forever. Names are the
#: repo-relative paths of those modules; none of them may join the allowlist.
HEAVY_DENYLIST: frozenset[str] = frozenset(
    {
        "tests/unit/test_polymarket_us_readonly_guard.py",
        "tests/unit/test_execution_egress_firewall_guard.py",
        "tests/unit/test_polymarket_us_credential_gate.py",
        "tests/unit/test_cage_rule_constants_are_pinned.py",
        "tests/unit/test_polymarket_us_permit_issuance.py",
        "tests/unit/test_order_submission_permit_issuance.py",
        "tests/unit/test_operator_control_assignment_scan.py",
        "tests/unit/test_polymarket_us_fee_guard.py",
        "tests/unit/test_probe_containment.py",
        "tests/unit/test_no_native_read_spies.py",
        "tests/unit/test_strategy_module_gate.py",
        "tests/unit/test_mypy_ratchet.py",
    }
)


def _arm(text: str, tier: str) -> str:
    return text.split(f"{tier})", 1)[1].split(";;", 1)[0]


def test_run_tier_holds_the_three_exclusions_in_one_constant() -> None:
    text = _TIER_SCRIPT.read_text(encoding="utf-8")
    assert text.count(_EXCL) == 1
    assert f"EXCL='{_EXCL}'" in text
    pyproject = _PYPROJECT.read_text(encoding="utf-8")
    assert f"-m '{_EXCL}'" in pyproject


def test_every_tier_uses_the_exclusion_constant() -> None:
    """T1–T3 expand ``$EXCL``. T4 passes no ``-m``, so addopts keeps the same exclusion."""
    text = _TIER_SCRIPT.read_text(encoding="utf-8")
    overrides = re.findall(r'-m\s+"([^"]*)"', text)
    assert len(overrides) == 3
    assert all("$EXCL" in expr for expr in overrides)
    for tier in ("T1", "T2", "T3"):
        assert "$EXCL" in _arm(text, tier)
    t4 = _arm(text, "T4")
    assert "-m" not in t4
    assert '"$@"' in t4
    assert "run_tests_no_egress.sh" in text
    assert "-q" not in text


def _uses_pytest_mark_heavy(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr != "heavy":
            continue
        mark = node.value
        if not isinstance(mark, ast.Attribute) or mark.attr != "mark":
            continue
        base = mark.value
        if isinstance(base, ast.Name) and base.id == "pytest":
            return True
    return False


def files_marked_heavy(tests_root: Path) -> set[str]:
    marked: set[str] = set()
    for path in sorted(tests_root.rglob("*.py")):
        if ".venv" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if _uses_pytest_mark_heavy(tree):
            marked.add(path.relative_to(tests_root.parent).as_posix())
    return marked


def test_heavy_denylist_names_files_that_exist() -> None:
    missing = sorted(path for path in HEAVY_DENYLIST if not (_REPO_ROOT / path).is_file())
    assert missing == []


def test_heavy_allowlist_is_disjoint_from_the_denylist() -> None:
    assert set(HEAVY_ALLOWLIST).isdisjoint(HEAVY_DENYLIST)


def test_heavy_mark_appears_only_on_the_allowlist() -> None:
    marked = files_marked_heavy(_REPO_ROOT / "tests")
    offenders = sorted(marked - set(HEAVY_ALLOWLIST))
    assert offenders == []


def test_heavy_detector_flags_a_mark_and_ignores_prose() -> None:
    marked = ast.parse("import pytest\npytestmark = pytest.mark.heavy\n")
    prose = ast.parse('"""pytest.mark.heavy stays off this module."""\nX = 1\n')
    assert _uses_pytest_mark_heavy(marked)
    assert not _uses_pytest_mark_heavy(prose)


def partition_report(parts: dict[str, set[str]], total: set[str]) -> str | None:
    """Empty when ``parts`` is a set partition of ``total``; otherwise a short report."""
    seen: dict[str, str] = {}
    overlaps: list[str] = []
    for name, node_ids in parts.items():
        for node_id in node_ids:
            prior = seen.get(node_id)
            if prior is not None:
                overlaps.append(f"{node_id} in {prior} and {name}")
            else:
                seen[node_id] = name
    union = set(seen)
    missing = sorted(total - union)
    extra = sorted(union - total)
    if not overlaps and not missing and not extra:
        return None
    lines: list[str] = []
    if overlaps:
        lines.append(f"overlaps ({len(overlaps)}):")
        lines.extend(overlaps[:20])
    if missing:
        lines.append(f"missing from every bucket ({len(missing)}):")
        lines.extend(missing[:20])
    if extra:
        lines.append(f"outside the collected total ({len(extra)}):")
        lines.extend(extra[:20])
    return "\n".join(lines)


def test_partition_checker_rejects_a_gap_and_an_overlap() -> None:
    total = {"a", "b", "c"}
    gap = partition_report({"t1": {"a"}, "rest": {"b"}}, total)
    assert gap is not None and "c" in gap
    overlap = partition_report({"t1": {"a", "b"}, "rest": {"b", "c"}}, total)
    assert overlap is not None and "b" in overlap
    assert partition_report({"t1": {"a"}, "rest": {"b", "c"}}, total) is None


def _node_ids(stdout: str) -> set[str]:
    return {line.strip() for line in stdout.splitlines() if _NODEID.match(line.strip())}


def _collect(args: list[str], basetemp: Path) -> set[str]:
    """``--collect-only`` inside the already-sandboxed interpreter. No extra ``-q``."""
    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-p",
            "no:randomly",
            "-p",
            "no:cacheprovider",
            *args,
            "--basetemp",
            str(basetemp),
        ],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    node_ids = _node_ids(proc.stdout)
    if proc.returncode not in (0, 5) or (proc.returncode == 5 and node_ids):
        tail = (proc.stdout + proc.stderr)[-2000:]
        raise AssertionError(f"collect-only {args} exited {proc.returncode}\n{tail}")
    return node_ids


def test_tier_buckets_partition_the_collected_suite() -> None:
    """The five buckets are a set partition of every collected node id."""
    base = Path.home() / ".cache" / "breezy-gate" / "r0a-partition-bt"
    base.mkdir(parents=True, exist_ok=True)
    tautology = "live or venue_live or real_money or not (live or venue_live or real_money)"
    specs: dict[str, list[str]] = {
        "total": ["-m", tautology],
        "T1": [
            "-m",
            f"{_EXCL} and not contract and not heavy",
            "tests/unit",
            "tests/strategy",
        ],
        "contract": ["-m", f"contract and {_EXCL}"],
        "heavy": ["-m", f"heavy and not contract and {_EXCL}"],
        "integration": ["-m", f"{_EXCL} and not contract", "tests/integration"],
        "live_class": ["-m", "live or venue_live or real_money"],
    }

    def _one(item: tuple[str, list[str]]) -> tuple[str, set[str]]:
        name, args = item
        return name, _collect(args, base / name)

    with ThreadPoolExecutor(max_workers=len(specs)) as pool:
        collected = dict(pool.map(_one, specs.items()))
    heavy_outside = {
        node_id for node_id in collected["heavy"] if not node_id.startswith("tests/integration/")
    }
    report = partition_report(
        {
            "T1": collected["T1"],
            "contract": collected["contract"],
            "heavy_outside_contract_and_integration": heavy_outside,
            "integration_outside_contract": collected["integration"],
            "live_class": collected["live_class"],
        },
        collected["total"],
    )
    assert report is None, report
