"""Parallel full gate: the sharder (``scripts/ci/gate_shards.py``) and its driver.

The parallel gate splits the whole collection into weighted shards, runs each
through the UNCHANGED ``run_tests_no_egress.sh``, then runs the unsafe-in-
parallel files serially, and finally PROVES from JUnit output that every
collected test was executed with an expected outcome. The serial gate stays the
reference (``docs/core/PARALLEL_GATE.md``).

These tests pin the pure functions, the real-file affinity facts, the JUnit key
scheme (against pytest's own private functions), the outcome verifier, and the
shell driver (with a fake pytest, as ``test_run_tests_no_egress_phases.py`` does).
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import stat
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Iterator, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SHARDS_PY: Final[Path] = REPO_ROOT / "scripts" / "ci" / "gate_shards.py"
PARALLEL_SH: Final[Path] = REPO_ROOT / "scripts" / "ci" / "run_tests_parallel.sh"
DURATIONS_JSON: Final[Path] = REPO_ROOT / "scripts" / "ci" / "gate_durations.json"
REFERENCE_JSON: Final[Path] = REPO_ROOT / "scripts" / "ci" / "gate_reference.json"

DRIVER: Final[str] = "tests/unit/test_maker_stage0_driver.py"
CENSUS: Final[str] = "tests/unit/test_aud07_m1c_census.py"
ISOLATE: Final[str] = "tests/unit/test_maker_stage0_isolate.py"
FOLLOWUPS: Final[str] = "tests/unit/test_maker_stage0_isolate_followups.py"

#: Independent heavy driver functions that must NOT join the ``e2e`` group.
DRIVER_HEAVY_FUNCTIONS: Final[tuple[str, ...]] = (
    "test_isolated_700s_spike_with_dense_neighbours_no_longer_voids_the_run",
    "test_a_void_run_may_be_rerun_only_with_a_dated_addendum",
    "test_bench_mode_skips_scoring_and_writes_no_episode_or_rate_output",
    "test_tail_only_is_report_only_and_records_code_sha",
    "test_tail_only_needs_a_clean_tree",
    "test_verify_first_runs_only_in_its_mode_and_only_on_2026_06_30",
    "test_driver_scores_only_after_simulation_completes",
    "test_driver_writes_each_episode_to_disk_before_the_next_is_pulled",
    "test_bracketed_unit_runs_both_hypotheses_and_converts_sizes_per_hypothesis",
    "test_a_ladder_listed_after_d_minus_1_noon_is_a_listing_abstention_not_a_bid",
    "test_full_run_is_deterministic",
    "test_bench_weighs_replayed_days_only_and_runs_every_variant",
    "test_the_tail_csv_source_and_episodes_jsonl_are_pinned",
    "test_result_files_are_written_atomically",
    "test_tail_only_csv_is_written_atomically",
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gate_shards", SHARDS_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["gate_shards"] = module
    spec.loader.exec_module(module)
    return module


gs: Any = _load()


def _ids(*pairs: tuple[str, int]) -> list[str]:
    """Node ids ``path::test_0 .. test_{n-1}`` for each ``(path, n)``."""
    return [f"{path}::test_{i}" for path, n in pairs for i in range(n)]


def _unit_args(part: Any) -> list[str]:
    return [arg for shard in part.shards for arg in shard] + list(part.tail)


# ---------------------------------------------------------------------------
# JUnit key scheme
# ---------------------------------------------------------------------------

_KEY_CORPUS: Final[tuple[str, ...]] = (
    "tests/unit/test_a.py::test_plain",
    "tests/unit/test_a.py::test_p[1-2]",
    "tests/unit/test_a.py::Cls::test_m",
    "tests/unit/test_a.py::Outer::Inner::test_m[x]",
    "tests/unit/test_a.py::test_u[café-☃]",
    "tests/unit/test_a.py::test_p[a::b]",
    "tests/unit/test_a.py::test_p[a[b]c]",
    "tests/unit/test_a.py::test_p[ctl\x07\x08]",
    "tests/unit/test_a.py::test_p[del\x7f]",
    "tests/unit/test_a.py::test_p[fffe￾]",
    "tests/unit/test_a.py::test_p[ffff￿]",
    "tests/unit/test_a.py::test_p[astral\U0001f600]",
    "tests/unit/test_a.py::test_p[က0]",
    "tests/unit/test_a.py::test_p[a&b<c>\"d']",
)


def test_nodeid_to_key_matches_pytest_junitxml_functions() -> None:
    from _pytest.junitxml import bin_xml_escape, mangle_test_address

    for nodeid in _KEY_CORPUS:
        names = mangle_test_address(nodeid)
        assert gs.nodeid_to_key(nodeid) == (".".join(names[:-1]), bin_xml_escape(names[-1])), nodeid


def test_nodeid_to_key_round_trips_through_real_xml_attributes() -> None:
    from _pytest.junitxml import bin_xml_escape, mangle_test_address

    for nodeid in _KEY_CORPUS:
        names = mangle_test_address(nodeid)
        element = ET.Element(
            "testcase", classname=".".join(names[:-1]), name=bin_xml_escape(names[-1])
        )
        text = ET.tostring(element, encoding="unicode")
        wrapped = f"<testsuites><testsuite>{text}</testsuite></testsuites>"
        (case,) = gs.parse_junit(wrapped)
        assert (case.classname, case.name) == gs.nodeid_to_key(nodeid), nodeid


def test_nodeid_to_key_does_not_escape_the_classname() -> None:
    assert gs.nodeid_to_key("tests/unit/test_a.py::Cls<>::test_m") == (
        "tests.unit.test_a.Cls<>",
        "test_m",
    )


def test_file_key_matches_a_collect_skip_testcase() -> None:
    assert gs.file_key("tests/unit/test_a.py") == ("", "tests.unit.test_a")


def test_keys_must_be_injective() -> None:
    gs.check_injective(["a/test_x.py::t[1]", "a/test_x.py::t[2]"])
    with pytest.raises(ValueError, match="collide"):
        gs.check_injective(["a/test_x.py::t[1]", "a/test_x.py::t[1]"])
    with pytest.raises(ValueError, match="collide"):
        # Two distinct node ids that mangle to one (classname, name) pair.
        gs.check_injective(["a/b.py::t", "a.b.py::t"])


def test_function_unit_drops_parametrisation_only() -> None:
    assert gs.function_unit("tests/a.py::test_f[x::y]") == "tests/a.py::test_f"
    assert gs.function_unit("tests/a.py::Cls::test_m[1]") == "tests/a.py::Cls::test_m"
    assert gs.function_unit("tests/a.py::test_f") == "tests/a.py::test_f"


# ---------------------------------------------------------------------------
# affinity and fixture drift
# ---------------------------------------------------------------------------

_SYNTH: Final[str] = """
import pytest

@pytest.fixture(scope="module")
def world(): ...

@pytest.fixture(scope="module")
def e2e(world):
    yield 1

@pytest.fixture
def via_e2e(e2e): ...

def test_direct(e2e): ...
def test_indirect(via_e2e): ...
def test_cheap(world): ...
def test_none(): ...

@pytest.mark.parametrize("n", [1, 2])
def test_param(n, e2e): ...

class TestC:
    def test_m(self, e2e): ...
    def test_other(self): ...
"""


def test_affinity_consumers_include_direct_indirect_param_and_class_methods() -> None:
    got = gs.affinity_consumers(_SYNTH, ["e2e"])
    assert got == {"test_direct", "test_indirect", "test_param", "TestC::test_m"}


def test_affinity_consumers_of_unknown_fixture_is_empty() -> None:
    assert gs.affinity_consumers(_SYNTH, ["nope"]) == set()


def test_real_driver_e2e_consumers_form_one_group_and_exclude_heavy_functions() -> None:
    text = (REPO_ROOT / DRIVER).read_text(encoding="utf-8")
    consumers: set[str] = gs.affinity_consumers(text, ["e2e"])
    assert len(consumers) >= 15
    assert "test_end_to_end_on_the_fixture_produces_a_verdict_and_every_artifact" in consumers
    assert "test_stats_rerun_on_scored_csv_reproduces_tables" in consumers
    for heavy in DRIVER_HEAVY_FUNCTIONS:
        assert heavy not in consumers, heavy


def test_real_driver_partition_gives_one_e2e_group_and_each_heavy_function_its_own_unit() -> None:
    text = (REPO_ROOT / DRIVER).read_text(encoding="utf-8")
    consumers = gs.affinity_consumers(text, ["e2e"])
    functions = re.findall(r"^def (test_\w+)\(", text, flags=re.MULTILINE)
    ids = [f"{DRIVER}::{name}" for name in functions]
    part = gs.partition(ids, 6, None, sources={DRIVER: text})
    args = _unit_args(part)
    group = [a for a in args if a.split("::")[-1] in consumers]
    assert len(group) == len(consumers)
    placed = [i for i, shard in enumerate(part.shards) if any(a in group for a in shard)]
    assert len(placed) == 1
    for heavy in DRIVER_HEAVY_FUNCTIONS:
        assert f"{DRIVER}::{heavy}" in args
        assert f"{DRIVER}::{heavy}" not in group


def test_real_census_canonical_cal_b_dir_consumers_are_grouped() -> None:
    text = (REPO_ROOT / CENSUS).read_text(encoding="utf-8")
    consumers: set[str] = gs.affinity_consumers(text, ["canonical_cal_b_dir"])
    assert {
        "test_derive_pin_refuses_missing_cells",
        "test_derive_pin_refuses_mixed_code_shas",
        "test_derive_pin_refuses_missing_stress_row",
    } <= consumers


def test_every_split_file_exists_and_its_affinity_fixture_is_module_scoped() -> None:
    assert set(gs.SPLIT_FILES) == {DRIVER, CENSUS, ISOLATE, FOLLOWUPS}
    conftests = [
        (REPO_ROOT / name).read_text(encoding="utf-8")
        for name in ("tests/conftest.py", "tests/unit/conftest.py")
    ]
    for path, fixtures in gs.SPLIT_FILES.items():
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
        assert gs.drift_problems(text, fixtures, conftests) == [], path


def test_drift_guard_fails_when_an_affinity_fixture_is_not_module_scoped() -> None:
    text = _SYNTH.replace('@pytest.fixture(scope="module")\ndef e2e', "@pytest.fixture\ndef e2e")
    assert any("e2e" in p for p in gs.drift_problems(text, ["e2e"]))
    assert any("missing" in p for p in gs.drift_problems(_SYNTH, ["absent"]))


def test_drift_guard_fails_on_usefixtures_and_getfixturevalue() -> None:
    uses = "import pytest\n@pytest.mark.usefixtures('x')\ndef test_a(): ...\n"
    gets = "def test_b(request):\n    request.getfixturevalue('x')\n"
    assert any("usefixtures" in p for p in gs.drift_problems(uses, []))
    assert any("getfixturevalue" in p for p in gs.drift_problems(gets, []))


def test_real_driver_calibration_fixture_edited_to_module_scope_is_rejected() -> None:
    text = (REPO_ROOT / DRIVER).read_text(encoding="utf-8")
    edited = text.replace(
        "@pytest.fixture(autouse=True)\ndef _calibration",
        '@pytest.fixture(autouse=True, scope="module")\ndef _calibration',
    )
    assert edited != text
    assert any("_calibration" in p for p in gs.drift_problems(edited, ["e2e"]))


def test_drift_guard_fails_on_a_module_fixture_with_code_after_yield() -> None:
    text = (
        'import pytest\n@pytest.fixture(scope="module")\ndef acc():\n    yield 1\n    cleanup()\n'
    )
    assert any("yield" in p for p in gs.drift_problems(text, []))


def test_drift_guard_allows_a_module_fixture_whose_yield_is_last() -> None:
    text = (
        'import pytest\n@pytest.fixture(scope="module")\n'
        "def e2e():\n    with open('f') as handle:\n        handle.read()\n    yield 1\n"
    )
    assert gs.drift_problems(text, ["e2e"]) == []


def test_drift_guard_fails_on_a_module_level_list_accumulator() -> None:
    text = "SEEN = []\ndef test_a():\n    SEEN.append(1)\n"
    assert any("SEEN" in p for p in gs.drift_problems(text, []))
    const = "NAMES = ['a', 'b']\ndef test_a():\n    assert 'a' in NAMES\n"
    assert gs.drift_problems(const, []) == []


def test_drift_guard_fails_on_conftest_module_fixtures_used_by_split_tests() -> None:
    conftest = 'import pytest\n@pytest.fixture(scope="session")\ndef shared_thing(): ...\n'
    text = "def test_a(shared_thing): ...\n"
    assert any(
        "shared_thing" in p for p in gs.drift_problems(text, [], conftest_sources=[conftest])
    )
    assert gs.drift_problems("def test_a(): ...\n", [], conftest_sources=[conftest]) == []


# ---------------------------------------------------------------------------
# partition
# ---------------------------------------------------------------------------

_PLAIN: Final[list[str]] = _ids(
    ("tests/unit/test_a.py", 5),
    ("tests/unit/test_b.py", 3),
    ("tests/unit/test_c.py", 9),
    ("tests/unit/test_d.py", 1),
    ("tests/unit/test_e.py", 4),
)


def test_partition_is_complete_and_has_no_duplicates() -> None:
    part = gs.partition(_PLAIN, 3, None, tail_files=(), split_files={})
    covered = sorted(_unit_args(part))
    assert covered == sorted({i.split("::")[0] for i in _PLAIN})
    assert len(part.shards) == 3 and part.tail == []


def test_partition_refuses_duplicate_ids_before_splitting(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("split_lanes reached despite duplicate ids")

    monkeypatch.setattr(gs, "_split_lanes", boom)
    with pytest.raises(ValueError, match="duplicate"):
        gs.partition([*_PLAIN, _PLAIN[0]], 3, None, tail_files=(), split_files={})


def test_partition_is_deterministic_and_input_order_independent() -> None:
    first = gs.partition(_PLAIN, 3, None, tail_files=(), split_files={})
    assert first == gs.partition(list(reversed(_PLAIN)), 3, None, tail_files=(), split_files={})


def test_partition_balances_within_the_heaviest_unit() -> None:
    durations = {
        "files": {f"tests/unit/test_{c}.py": ms for c, ms in zip("abcde", (50, 70, 900, 5, 300))}
    }
    part = gs.partition(_PLAIN, 3, durations, tail_files=(), split_files={})
    weight = {p: v for p, v in durations["files"].items()}
    loads = [sum(weight[a] for a in shard) for shard in part.shards]
    assert max(loads) - min(loads) <= max(weight.values())
    assert max(loads) == 900


def test_partition_weights_are_integer_milliseconds() -> None:
    durations = {"files": {"tests/unit/test_a.py": 12.7}}
    part = gs.partition(_PLAIN, 2, durations, tail_files=(), split_files={})
    assert part.weights_ms and all(isinstance(w, int) for w in part.weights_ms.values())


def test_partition_keeps_tail_files_whole_and_out_of_the_shards() -> None:
    part = gs.partition(_PLAIN, 2, None, tail_files=("tests/unit/test_c.py",), split_files={})
    assert part.tail == ["tests/unit/test_c.py"]
    assert "tests/unit/test_c.py" not in [a for s in part.shards for a in s]


def test_partition_with_more_shards_than_units_yields_empty_shards() -> None:
    part = gs.partition(_ids(("tests/unit/test_a.py", 2)), 4, None, tail_files=(), split_files={})
    assert sum(1 for s in part.shards if s) == 1
    assert sum(1 for s in part.shards if not s) == 3


def _split_source() -> str:
    return (
        "import pytest\n"
        '@pytest.fixture(scope="module")\ndef e2e(): yield 1\n'
        "def test_g1(e2e): ...\ndef test_g2(e2e): ...\ndef test_heavy_a(): ...\n"
        "def test_heavy_b(): ...\n"
        "@pytest.mark.parametrize('x', [1, 2, 3])\ndef test_param(x): ...\n"
        "class TestK:\n    def test_m(self): ...\n"
    )


def _split_ids() -> list[str]:
    path = "tests/unit/test_split.py"
    return [
        f"{path}::test_g1",
        f"{path}::test_g2",
        f"{path}::test_heavy_a",
        f"{path}::test_heavy_b",
        f"{path}::test_param[1]",
        f"{path}::test_param[2]",
        f"{path}::test_param[3]",
        f"{path}::TestK::test_m",
    ]


def test_split_file_units_are_functions_with_parametrisations_kept_together() -> None:
    path = "tests/unit/test_split.py"
    part = gs.partition(
        _split_ids(),
        8,
        None,
        sources={path: _split_source()},
        split_files={path: ("e2e",)},
        tail_files=(),
    )
    args = _unit_args(part)
    assert f"{path}::test_param" in args
    assert not any("[" in a for a in args)
    assert f"{path}::TestK::test_m" in args
    group_shards = [s for s in part.shards if f"{path}::test_g1" in s]
    assert len(group_shards) == 1 and f"{path}::test_g2" in group_shards[0]
    assert f"{path}::test_heavy_a" not in group_shards[0]


def test_split_units_spread_across_shards() -> None:
    path = "tests/unit/test_split.py"
    part = gs.partition(
        _split_ids(),
        4,
        None,
        sources={path: _split_source()},
        split_files={path: ("e2e",)},
        tail_files=(),
    )
    assert sum(1 for s in part.shards if s) >= 3


def test_partition_function_weights_come_from_per_function_durations() -> None:
    path = "tests/unit/test_split.py"
    durations = {
        "functions": {
            "tests.unit.test_split::test_heavy_a": 5000,
            "tests.unit.test_split::test_heavy_b": 10,
            "tests.unit.test_split::test_g1": 10,
            "tests.unit.test_split::test_g2": 10,
            "tests.unit.test_split::test_param": 10,
            "tests.unit.test_split.TestK::test_m": 10,
        },
        "files": {path: 5050},
    }
    part = gs.partition(
        _split_ids(),
        2,
        durations,
        sources={path: _split_source()},
        split_files={path: ("e2e",)},
        tail_files=(),
    )
    heavy_shard = next(s for s in part.shards if f"{path}::test_heavy_a" in s)
    assert len(heavy_shard) == 1


def test_missing_duration_fallbacks() -> None:
    ids = _ids(("tests/unit/test_known.py", 2), ("tests/unit/test_unknown.py", 6))
    durations = {"files": {"tests/unit/test_known.py": 200}, "median_test_ms": 100}
    part = gs.partition(ids, 2, durations, tail_files=(), split_files={})
    assert part.weights_ms["tests/unit/test_known.py"] == 200
    assert part.weights_ms["tests/unit/test_unknown.py"] == 600  # median x count
    no_json = gs.partition(ids, 2, None, tail_files=(), split_files={})
    assert (
        no_json.weights_ms["tests/unit/test_unknown.py"]
        == 6 * no_json.weights_ms["tests/unit/test_known.py"] // 2
    )
    assert no_json.warnings and "no durations" in no_json.warnings[0]


def test_unknown_function_in_a_split_file_uses_the_file_median() -> None:
    path = "tests/unit/test_split.py"
    durations = {
        "functions": {
            "tests.unit.test_split::test_heavy_b": 400,
            "tests.unit.test_split::test_g1": 200,
        },
        "files": {path: 600},
        "median_test_ms": 10,
    }
    part = gs.partition(
        _split_ids(),
        4,
        durations,
        sources={path: _split_source()},
        split_files={path: ("e2e",)},
        tail_files=(),
    )
    assert part.weights_ms[f"{path}::test_heavy_a"] == 300  # median of known (200, 400)


# ---------------------------------------------------------------------------
# tail, classification, ENV_SKIPS guards
# ---------------------------------------------------------------------------


def test_tail_is_whole_existing_files_disjoint_from_split_files() -> None:
    tail = gs.tail_files()
    assert tail == sorted(set(tail))
    assert all((REPO_ROOT / f).is_file() for f in tail)
    assert set(tail).isdisjoint(gs.SPLIT_FILES)
    assert "tests/unit/test_persistence_import_free.py" in tail
    assert "tests/unit/test_tier_infra.py" in tail
    assert "tests/unit/test_archive_import_contract.py" in tail
    assert all("::" not in f for f in tail)


def test_serial_tail_includes_the_confirmed_real_clock_budget_files() -> None:
    tail = set(gs.tail_files())
    for name in (
        "autonomy_closure",
        "registry_resolver",
        "registry_replay_parity",
        "nbp_calibration",
        "normalize_cli_parse_fuzz",
        "venue_positions_read",
        "ingest_health_emission_escalation",
        "aut2_delivery",
        "polymarket_us_websocket",
        "polymarket_us_transport",
        "autonomy_bus_handoff",
    ):
        assert f"tests/unit/test_{name}.py" in tail, name
    assert "tests/integration/test_resting_order_lifecycle.py" in tail


def test_every_timing_or_fixed_path_file_is_classified() -> None:
    hits = gs.timing_scan_files(REPO_ROOT) | gs.path_scan_files(REPO_ROOT)
    assert hits, "scan found nothing: the scanner is broken"
    gaps = gs.classification_gaps(hits, gs.tail_files(), gs.REVIEWED_PARALLEL_OK)
    assert gaps == []


def test_reviewed_parallel_ok_has_reasons_and_no_stale_or_tail_entries() -> None:
    tail = set(gs.tail_files())
    for path, reason in gs.REVIEWED_PARALLEL_OK.items():
        assert reason.strip(), path
        assert (REPO_ROOT / path).is_file(), path
        assert path not in tail, path


def test_classification_gaps_names_an_unclassified_file() -> None:
    assert gs.classification_gaps({"tests/unit/test_x.py"}, [], {}) == ["tests/unit/test_x.py"]
    assert gs.classification_gaps({"tests/unit/test_x.py"}, ["tests/unit/test_x.py"], {}) == []
    assert (
        gs.classification_gaps({"tests/unit/test_x.py"}, [], {"tests/unit/test_x.py": "why"}) == []
    )


def test_timing_scan_finds_the_widened_tokens(tmp_path: Path) -> None:
    unit = tmp_path / "tests" / "unit"
    unit.mkdir(parents=True)
    for name, body in {
        "test_pc.py": "import time\nt = time.perf_counter()\n",
        "test_mono.py": "import time\nt = time.monotonic()\n",
        "test_tt.py": "import time\nt = time.time()\n",
        "test_dl.py": "deadline = 1\n",
        "test_wf.py": "await asyncio.wait_for(x, 1)\n",
        "test_ts.py": "f(timeout_s=1)\n",
        "test_none.py": "x = 1\n",
    }.items():
        (unit / name).write_text(body, encoding="utf-8")
    assert gs.timing_scan_files(tmp_path) == {
        f"tests/unit/test_{n}.py" for n in ("pc", "mono", "tt", "dl", "wf", "ts")
    }


def test_path_scan_finds_fixed_paths_home_and_expanduser(tmp_path: Path) -> None:
    unit = tmp_path / "tests" / "unit"
    unit.mkdir(parents=True)
    for name, body in {
        "test_tmp.py": "p = '/tmp/x'\n",
        "test_shm.py": "p = '/dev/shm/x'\n",
        "test_sock.py": "import socket\ns = socket.AF_UNIX\n",
        "test_cache.py": "p = '~/.cache/x'\n",
        "test_home.py": "from pathlib import Path\np = Path.home()\n",
        "test_exp.py": "p = q.expanduser()\n",
        "test_none.py": "x = 1\n",
    }.items():
        (unit / name).write_text(body, encoding="utf-8")
    assert gs.path_scan_files(tmp_path) == {
        f"tests/unit/test_{n}.py" for n in ("tmp", "shm", "sock", "cache", "home", "exp")
    }


def test_env_skips_are_well_formed_justified_and_resource_files_are_in_the_tail() -> None:
    assert gs.ENV_SKIPS, "ENV_SKIPS must be seeded"
    assert gs.env_skip_problems(gs.ENV_SKIPS, gs.tail_files(), REPO_ROOT) == []


def test_env_skip_guard_rejects_malformed_entries() -> None:
    entry = gs.EnvSkip

    def problems(e: Any, tail: Sequence[str] = ()) -> list[str]:
        return list(gs.env_skip_problems([e], tail, REPO_ROOT))

    good = entry(
        "tests.unit.test_unit_health_dropins", "test_x", "^reason$", "static", "host config"
    )
    assert any("function" in p for p in problems(good))  # test_x does not exist there
    ok = entry(
        "tests.unit.test_unit_health_dropins",
        "test_the_live_dropin_matches_the_injected_orders_off_row",
        "^reason$",
        "static",
        "host config",
    )
    assert isinstance(ok, tuple)
    for bad in (
        entry("tests.unit.nonexistent_file", "t", "^r$", "static", "why"),
        entry("tests.unit.test_unit_health_dropins", "t", "^(unclosed$", "static", "why"),
        entry("tests.unit.test_unit_health_dropins", "t", "no anchors", "static", "why"),
        entry("tests.unit.test_unit_health_dropins", "t", "^r$", "weird", "why"),
        entry("tests.unit.test_unit_health_dropins", "t", "^r$", "static", "  "),
    ):
        assert problems(bad), bad
    resource = entry("tests.unit.test_unit_health_dropins", "t", "^r$", "resource", "load")
    assert any("tail" in p for p in problems(resource, tail=()))


# ---------------------------------------------------------------------------
# JUnit parsing and outcome verification
# ---------------------------------------------------------------------------


def _xml(*cases: str) -> str:
    body = "".join(cases)
    return (
        f'<?xml version="1.0"?><testsuites><testsuite name="pytest">{body}</testsuite></testsuites>'
    )


def _case(cls: str, name: str, child: str = "", time: str = "0.5") -> str:
    return f'<testcase classname="{cls}" name="{name}" time="{time}">{child}</testcase>'


SKIP = '<skipped type="pytest.skip" message="{msg}">f.py:1: {msg}</skipped>'
XFAIL = '<skipped type="pytest.xfail" message="{msg}"/>'
FAIL = '<failure message="boom">trace</failure>'
ERROR = '<error message="failed on teardown">trace</error>'
STRICT_XPASS = '<skipped message="xfail-marked test passes unexpectedly">x</skipped>'


def test_parse_junit_classifies_outcomes() -> None:
    cases = gs.parse_junit(
        _xml(
            _case("t.a", "p"),
            _case("t.a", "s", SKIP.format(msg="no store")),
            _case("t.a", "x", XFAIL.format(msg="known")),
            _case("t.a", "f", FAIL),
            _case("t.a", "e", ERROR),
            _case("t.a", "sx", STRICT_XPASS),
        )
    )
    assert [(c.name, c.outcome) for c in cases] == [
        ("p", "pass"),
        ("s", "skip"),
        ("x", "xfail"),
        ("f", "fail"),
        ("e", "fail"),
        ("sx", "fail"),
    ]
    assert cases[1].message == "no store" and cases[2].message == "known"
    assert cases[0].time_s == 0.5


def test_skip_plus_teardown_error_in_one_testcase_is_a_failure() -> None:
    (case,) = gs.parse_junit(_xml(_case("t.a", "s", SKIP.format(msg="m") + ERROR)))
    assert case.outcome == "fail"


_KEYS: Final[set[tuple[str, str]]] = {("t.a", "p"), ("t.a", "s")}


def _reference(*entries: dict[str, str], slow: str = "0") -> dict[str, Any]:
    return {"version": 1, "non_pass": {slow: list(entries)}}


def _np(name: str, outcome: str = "skip", message: str = "no store") -> dict[str, str]:
    return {
        "classname": "t.a",
        "name": name,
        "outcome": outcome,
        "message": message,
        "why": "seed",
    }


def _verify(
    jobs: dict[str, str],
    *,
    keys: set[tuple[str, str]] | None = None,
    reference: dict[str, Any] | None = None,
    primary: bool = True,
    env_skips: Sequence[Any] = (),
    tail_jobs: Sequence[str] = ("tail",),
    run_slow: str = "0",
    collect_xml: str | None = None,
) -> Any:
    return gs.verify(
        expected_keys=_KEYS if keys is None else keys,
        jobs={name: gs.parse_junit(text) for name, text in jobs.items()},
        collect_cases=gs.parse_junit(collect_xml or _xml()),
        reference=reference if reference is not None else _reference(_np("s")),
        env_skips=env_skips,
        tail_jobs=set(tail_jobs),
        run_slow=run_slow,
        primary_tree=primary,
    )


_GOOD = {"s0": _xml(_case("t.a", "p"), _case("t.a", "s", SKIP.format(msg="no store")))}


def test_verify_accepts_matching_keys_and_listed_skip() -> None:
    verdict = _verify(_GOOD)
    assert verdict.rc == 0 and verdict.errors == []


def test_verify_missing_key_is_a_hard_error_everywhere() -> None:
    for primary in (True, False):
        verdict = _verify({"s0": _xml(_case("t.a", "p"))}, primary=primary)
        assert verdict.rc == 4
        assert any("missing" in e and "('t.a', 's')" in e for e in verdict.errors)


def test_verify_extra_key_is_a_hard_error() -> None:
    verdict = _verify({"s0": _GOOD["s0"], "s1": _xml(_case("t.a", "zzz"))})
    assert verdict.rc == 4 and any("extra" in e for e in verdict.errors)


def test_verify_key_run_by_two_jobs_is_a_hard_error() -> None:
    verdict = _verify({"s0": _GOOD["s0"], "s1": _xml(_case("t.a", "p"))})
    assert verdict.rc == 4 and any("twice" in e or "more than one" in e for e in verdict.errors)


@pytest.mark.parametrize("child", [FAIL, ERROR, STRICT_XPASS])
def test_verify_fail_error_and_strict_xpass_are_hard_even_off_the_primary_tree(child: str) -> None:
    jobs = {"s0": _xml(_case("t.a", "p", child), _case("t.a", "s", SKIP.format(msg="no store")))}
    for primary in (True, False):
        assert _verify(jobs, primary=primary).rc == 4


def test_verify_two_elements_under_one_key_is_a_failure() -> None:
    jobs = {
        "s0": _xml(
            _case("t.a", "p"),
            _case("t.a", "p", ERROR),
            _case("t.a", "s", SKIP.format(msg="no store")),
        )
    }
    verdict = _verify(jobs)
    assert verdict.rc == 4 and any("twice" in e or "more than one" in e for e in verdict.errors)


def test_verify_pass_followed_by_teardown_error_in_one_testcase_is_a_failure() -> None:
    jobs = {"s0": _xml(_case("t.a", "p", ERROR), _case("t.a", "s", SKIP.format(msg="no store")))}
    assert _verify(jobs).rc == 4


def test_verify_unlisted_skip_is_hard_on_the_primary_tree_and_advisory_elsewhere() -> None:
    jobs = {
        "s0": _xml(
            _case("t.a", "p", SKIP.format(msg="surprise")),
            _case("t.a", "s", SKIP.format(msg="no store")),
        )
    }
    primary = _verify(jobs, primary=True)
    assert primary.rc == 4 and any("unlisted skip" in e for e in primary.errors)
    other = _verify(jobs, primary=False)
    assert other.rc == 0 and other.advisories
    assert "OUTCOME CHECK ADVISORY" in other.summary


def test_verify_skip_with_a_changed_message_diverges() -> None:
    jobs = {"s0": _xml(_case("t.a", "p"), _case("t.a", "s", SKIP.format(msg="other reason")))}
    assert _verify(jobs, primary=True).rc == 4
    assert _verify(jobs, primary=False).advisories


def test_verify_xfail_must_be_listed() -> None:
    jobs = {
        "s0": _xml(
            _case("t.a", "p", XFAIL.format(msg="known")),
            _case("t.a", "s", SKIP.format(msg="no store")),
        )
    }
    assert _verify(jobs, primary=True).rc == 4
    listed = _reference(_np("s"), _np("p", "xfail", "known"))
    assert _verify(jobs, reference=listed).rc == 0


def test_verify_pass_where_the_reference_lists_xfail_or_skip_is_logged_not_failed() -> None:
    jobs = {"s0": _xml(_case("t.a", "p"), _case("t.a", "s"))}
    verdict = _verify(jobs, reference=_reference(_np("p", "xfail", "known"), _np("s")))
    assert verdict.rc == 0
    assert any("XPASS" in n for n in verdict.notes) and any("STALE" in n for n in verdict.notes)


def test_env_skips_allow_pass_or_skip_but_a_resource_skip_in_a_shard_is_hard() -> None:
    static = gs.EnvSkip("t.a", "s", "^no store$", "static", "needs a store")
    resource = gs.EnvSkip("t.a", "s", "^no store$", "resource", "disk")
    ref = _reference()
    skipped = {"s0": _xml(_case("t.a", "p"), _case("t.a", "s", SKIP.format(msg="no store")))}
    passed = {"s0": _xml(_case("t.a", "p"), _case("t.a", "s"))}
    assert _verify(skipped, reference=ref, env_skips=[static]).rc == 0
    assert _verify(passed, reference=ref, env_skips=[static]).rc == 0
    assert _verify(skipped, reference=ref, env_skips=[resource]).rc == 4
    tail_skip = {"tail": skipped["s0"]}
    assert _verify(tail_skip, reference=ref, env_skips=[resource]).rc == 0


def test_env_skip_matches_exact_name_or_function_prefix_with_anchored_message() -> None:
    entry = gs.EnvSkip("t.a", "test_f", "^needs systemd$", "static", "host")
    assert gs.env_skip_matches([entry], ("t.a", "test_f[1]"), "needs systemd")
    assert gs.env_skip_matches([entry], ("t.a", "test_f"), "needs systemd")
    assert not gs.env_skip_matches([entry], ("t.a", "test_f"), "needs systemd today")
    assert not gs.env_skip_matches([entry], ("t.a", "test_fx"), "needs systemd")
    assert not gs.env_skip_matches([entry], ("t.b", "test_f"), "needs systemd")
    exact = gs.EnvSkip("t.a", "test_f[1]", "^m$", "static", "host")
    assert gs.env_skip_matches([exact], ("t.a", "test_f[1]"), "m")
    assert not gs.env_skip_matches([exact], ("t.a", "test_f[2]"), "m")


def test_verify_requires_a_reference_set_for_the_run_slow_value_on_the_primary_tree() -> None:
    primary = _verify(_GOOD, run_slow="1", primary=True)
    assert primary.rc == 4 and any("run_slow" in e for e in primary.errors)
    other = _verify(_GOOD, run_slow="1", primary=False)
    assert other.rc == 0 and "OUTCOME CHECK ADVISORY" in other.summary


def test_verify_off_the_primary_tree_is_always_marked_advisory_even_when_clean() -> None:
    clean = _verify(_GOOD, primary=False)
    assert clean.rc == 0 and clean.advisories == []
    assert "OUTCOME CHECK ADVISORY" in clean.summary


def test_verify_a_changed_fingerprint_is_never_a_silent_pass() -> None:
    other = _verify(_GOOD, run_slow="1", primary=False)
    assert other.advisories and "run_slow" in " ".join(other.advisories)
    clean = _verify(_GOOD, primary=True)
    assert "ADVISORY" not in clean.summary


def test_verify_collect_skip_is_expected_exactly_when_collect_xml_reports_it() -> None:
    collect = _xml(
        _case("", "tests.unit.test_gone", '<skipped message="collection skipped">x</skipped>')
    )
    ref = _reference(
        _np("s"),
        {
            "classname": "",
            "name": "tests.unit.test_gone",
            "outcome": "skip",
            "message": "collection skipped",
            "why": "seed",
        },
    )
    assert _verify(_GOOD, reference=ref, collect_xml=collect).rc == 0
    # Skips at collection but the reference does not list it: one side only.
    assert _verify(_GOOD, collect_xml=collect, primary=True).rc == 4
    assert _verify(_GOOD, collect_xml=collect, primary=False).advisories
    # Reference lists it, collect.xml no longer skips it: stale, not a failure.
    stale = _verify(_GOOD, reference=ref)
    assert stale.rc == 0 and any("STALE" in n for n in stale.notes)


def test_verify_a_collect_error_is_hard() -> None:
    collect = _xml(_case("", "tests.unit.test_bad", ERROR))
    assert _verify(_GOOD, collect_xml=collect).rc == 4


def test_expected_keys_come_from_ids_and_collect_skips_and_refuse_collisions() -> None:
    keys = gs.expected_keys(["a/test_x.py::t[1]", "a/test_x.py::C::t"], [])
    assert keys == {("a.test_x", "t[1]"), ("a.test_x.C", "t")}
    skipped = gs.expected_keys(["a/test_x.py::t"], [("", "a.test_y")])
    assert ("", "a.test_y") in skipped
    with pytest.raises(ValueError, match="collide"):
        gs.expected_keys(["a/b.py::t", "a.b.py::t"], [])


# ---------------------------------------------------------------------------
# reference recording (serial output only) and durations
# ---------------------------------------------------------------------------


def test_record_reads_only_serial_junit() -> None:
    gs.assert_serial_junit_path(Path("/x/junit/serial.xml"))
    gs.assert_serial_junit_path(Path("/x/junit/serial-2026.xml"))
    for bad in ("s0.xml", "s13.xml", "tail.xml", "collect.xml", "junit.xml"):
        with pytest.raises(ValueError, match="serial"):
            gs.assert_serial_junit_path(Path("/x/junit") / bad)


def test_record_refuses_a_red_serial_run() -> None:
    cases = gs.parse_junit(_xml(_case("t.a", "p", FAIL)))
    with pytest.raises(ValueError, match="not green"):
        gs.record_reference(cases, None, run_slow="0", reason="seed", reasons_for={})


def test_record_accepts_a_serial_rerun_only_for_keys_that_failed_and_now_pass() -> None:
    red = gs.parse_junit(_xml(_case("t.a", "p"), _case("t.a", "flaky", ERROR)))
    green = gs.parse_junit(_xml(_case("t.a", "flaky")))
    still_red = gs.parse_junit(_xml(_case("t.a", "flaky", FAIL)))
    result = gs.record_reference(
        red, None, run_slow="0", reason="seed", reasons_for={}, reruns=green
    )
    assert result.reference["non_pass"]["0"] == []
    assert any("rerun" in line for line in result.diff)
    with pytest.raises(ValueError, match="not green"):
        gs.record_reference(
            red, None, run_slow="0", reason="seed", reasons_for={}, reruns=still_red
        )
    with pytest.raises(ValueError, match="not green"):
        gs.record_reference(red, None, run_slow="0", reason="seed", reasons_for={}, reruns=[])


def test_record_seeds_non_pass_entries_with_the_blanket_reason_and_never_lists_passes() -> None:
    cases = gs.parse_junit(
        _xml(
            _case("t.a", "p"),
            _case("t.a", "s", SKIP.format(msg="no store")),
            _case("t.a", "x", XFAIL.format(msg="known")),
        )
    )
    result = gs.record_reference(cases, None, run_slow="0", reason="seed: serial", reasons_for={})
    entries = result.reference["non_pass"]["0"]
    assert [(e["name"], e["outcome"], e["message"], e["why"]) for e in entries] == [
        ("s", "skip", "no store", "seed: serial"),
        ("x", "xfail", "known", "seed: serial"),
    ]
    assert any("+" in line and "s" in line for line in result.diff)


def test_record_requires_a_per_key_reason_for_a_changed_existing_key() -> None:
    old = _reference(_np("s"))
    cases = gs.parse_junit(_xml(_case("t.a", "s", SKIP.format(msg="different"))))
    with pytest.raises(ValueError, match="reason-for"):
        gs.record_reference(cases, old, run_slow="0", reason="blanket", reasons_for={})
    result = gs.record_reference(
        cases,
        old,
        run_slow="0",
        reason="blanket",
        reasons_for={"t.a::s": "venue changed the message"},
    )
    assert result.reference["non_pass"]["0"][0]["why"] == "venue changed the message"


def test_record_requires_a_reason_and_prunes_stale_entries() -> None:
    old = _reference(_np("gone"))
    cases = gs.parse_junit(_xml(_case("t.a", "gone")))
    with pytest.raises(ValueError, match="reason"):
        gs.record_reference(cases, old, run_slow="0", reason="", reasons_for={})
    result = gs.record_reference(cases, old, run_slow="0", reason="refresh", reasons_for={})
    assert result.reference["non_pass"]["0"] == []
    assert any(line.startswith("-") for line in result.diff)


def test_record_keeps_the_other_run_slow_set() -> None:
    old = _reference(_np("s"), slow="1")
    cases = gs.parse_junit(_xml(_case("t.a", "p")))
    result = gs.record_reference(cases, old, run_slow="0", reason="seed", reasons_for={})
    assert result.reference["non_pass"]["1"] == old["non_pass"]["1"]
    assert result.reference["non_pass"]["0"] == []


def test_durations_sum_per_file_and_per_function_for_split_files_only() -> None:
    cases = gs.parse_junit(
        _xml(
            _case("tests.unit.test_a", "t1", time="1.0"),
            _case("tests.unit.test_a", "t2", time="0.25"),
            _case("tests.unit.test_s", "f[1]", time="2.0"),
            _case("tests.unit.test_s", "f[2]", time="3.0"),
            _case("tests.unit.test_s.TestC", "g", time="1.5"),
        )
    )
    out = gs.build_durations(
        cases,
        ["tests/unit/test_a.py", "tests/unit/test_s.py"],
        split_files=["tests/unit/test_s.py"],
    )
    assert out["files"] == {"tests/unit/test_a.py": 1250, "tests/unit/test_s.py": 6500}
    assert out["functions"] == {
        "tests.unit.test_s::f": 5000,
        "tests.unit.test_s.TestC::g": 1500,
    }
    assert out["median_test_ms"] > 0
    assert list(out["files"]) == sorted(out["files"])


# ---------------------------------------------------------------------------
# shard count, aggregation, run dir
# ---------------------------------------------------------------------------


def _meminfo(avail_gb: float) -> str:
    return f"MemTotal:       32000000 kB\nMemAvailable:   {int(avail_gb * 1048576)} kB\n"


def test_choose_n_low_memory_normal_and_override() -> None:
    low, low_reason = gs.choose_n(_meminfo(9), None, 2.0)
    assert low == 2 and "memory" in low_reason
    normal, _ = gs.choose_n(_meminfo(40), None, 2.0)
    assert normal == 10
    override, reason = gs.choose_n(_meminfo(40), 4, 2.0)
    assert override == 4 and "requested" in reason
    capped, _ = gs.choose_n(_meminfo(40), 99, 2.0)
    assert capped == 10
    floor, _ = gs.choose_n(_meminfo(1), None, 2.0)
    assert floor == 1
    assert gs.choose_n(_meminfo(9), 8, 2.0)[0] == 2


def test_choose_n_refuses_unreadable_meminfo() -> None:
    with pytest.raises(ValueError, match="MemAvailable"):
        gs.choose_n("MemTotal: 1 kB\n", None, 2.0)


@pytest.mark.parametrize(
    ("rcs", "expected"),
    [([0, 0, 0], 0), ([0, 5, 0], 5), ([1, 0, 2], 1), ([0, 0, 3], 3), ([5], 5)],
)
def test_aggregate_returns_the_first_nonzero(rcs: list[int], expected: int) -> None:
    assert gs.aggregate(rcs) == expected


def test_aggregate_refuses_an_empty_list() -> None:
    with pytest.raises(ValueError, match="empty"):
        gs.aggregate([])


def test_validate_run_dir_accepts_only_short_names_under_pytest_tmp() -> None:
    root = Path("/r/repo")
    ok = gs.validate_run_dir(root, root / ".pytest-tmp" / "run1")
    assert ok == root / ".pytest-tmp" / "run1"
    for bad in (
        root / "elsewhere" / "run1",
        root / ".pytest-tmp",
        root / ".pytest-tmp" / "a" / "b",
        root / ".pytest-tmp" / ("x" * 17),
        root / ".pytest-tmp" / "bad name",
        Path("/tmp/run1"),
        Path.home() / ".cache" / "breezy-gate",
        root / ".pytest-tmp" / ".." / "run1",
    ):
        with pytest.raises(ValueError):
            gs.validate_run_dir(root, bad)


def test_validate_run_dir_refuses_paths_too_long_for_unix_sockets() -> None:
    root = Path("/") / ("d" * 60) / ("e" * 20) / "repo"
    with pytest.raises(ValueError, match="socket|AF_UNIX|long"):
        gs.validate_run_dir(root, root / ".pytest-tmp" / "run1")


# ---------------------------------------------------------------------------
# module shape: stdlib only, no environment writes, no asdict, scripts untouched
# ---------------------------------------------------------------------------


def test_gate_shards_is_stdlib_only_and_writes_no_environment() -> None:
    import ast

    text = SHARDS_PY.read_text(encoding="utf-8")
    tree = ast.parse(text)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            imported.add(node.module.split(".")[0])
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {
        n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
    }
    assert not names & {"environ", "environb", "putenv", "unsetenv", "asdict"}


def test_the_existing_gate_scripts_are_untouched() -> None:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--quiet",
            "HEAD",
            "--",
            "scripts/ci/run_tests_no_egress.sh",
            "scripts/ci/run_tier.sh",
            "scripts/ci/run_t1_lanes.sh",
            "scripts/ci/tier_lanes.py",
        ],
        cwd=REPO_ROOT,
        check=False,
    )
    if result.returncode == 128:
        pytest.skip("not a git work tree")
    assert result.returncode == 0


def test_committed_json_files_are_well_formed() -> None:
    durations = json.loads(DURATIONS_JSON.read_text(encoding="utf-8"))
    assert set(durations) >= {"files", "functions", "median_test_ms"}
    assert list(durations["files"]) == sorted(durations["files"])
    assert all(isinstance(v, int) for v in durations["files"].values())
    reference = json.loads(REFERENCE_JSON.read_text(encoding="utf-8"))
    assert reference["version"] == 1 and "0" in reference["non_pass"]
    for entries in reference["non_pass"].values():
        for entry in entries:
            assert entry["outcome"] in {"skip", "xfail"}
            assert entry["why"].strip()


# ---------------------------------------------------------------------------
# shell driver, with a fake pytest
# ---------------------------------------------------------------------------

_FAKE_PYTEST: Final[str] = r"""
import json, os, sys
from pathlib import Path
sys.path.insert(0, os.environ["FAKE_SCRIPTS_DIR"])
import gate_shards as gs

args = sys.argv[1:]
log = Path(os.environ["BREEZY_FAKE_LOG"])
universe = json.loads(Path(os.environ["BREEZY_FAKE_UNIVERSE"]).read_text())
opts = {"-p", "--basetemp", "--junitxml", "-m"}
positional, xml, basetemp, collect = [], None, None, False
i = 0
while i < len(args):
    a = args[i]
    if a.startswith("--basetemp="):
        basetemp = a.split("=", 1)[1]
    elif a == "--basetemp":
        basetemp = args[i + 1]; i += 1
    elif a == "--junitxml":
        xml = args[i + 1]; i += 1
    elif a in opts:
        i += 1
    elif a in ("--collect-only", "--co", "--collectonly"):
        collect = True
    elif not a.startswith("-"):
        positional.append(a)
    i += 1
with log.open("a") as handle:
    handle.write(json.dumps({
        "gate_dir": os.environ.get("BREEZY_GATE_DIR"), "tmpdir": os.environ.get("TMPDIR"),
        "basetemp": basetemp, "collect": collect, "args": positional,
        "phase2": os.environ.get("BREEZY_BWRAP_HOST_PHASE"),
    }) + "\n")
if os.environ.get("BREEZY_BWRAP_HOST_PHASE") == "1":
    sys.exit(int(os.environ.get("BREEZY_FAKE_PHASE2_RC", "0")))

def selected(nodeid):
    if not positional:
        return True
    for a in positional:
        if nodeid == a or nodeid.startswith(a + "::") or nodeid.startswith(a + "["):
            return True
    return False

chosen = [n for n in universe["ids"] if selected(n)]
drop = universe.get("drop_from_run", [])
fail = universe.get("fail", [])
skip = universe.get("skip", {})
if collect:
    for n in chosen:
        print(n)
    print(f"{len(chosen)} tests collected")
    if os.environ.get("BREEZY_GATE_COLLECT_ONLY_CONFIRM_FILE"):
        Path(os.environ["BREEZY_GATE_COLLECT_ONLY_CONFIRM_FILE"]).write_text("collect-only")
    cases = []
    for path in universe.get("collect_skip_files", []):
        cls, name = gs.file_key(path)
        skipped = '<skipped message="collection skipped">x</skipped>'
        cases.append(f'<testcase classname="{cls}" name="{name}">{skipped}</testcase>')
    if xml:
        Path(xml).parent.mkdir(parents=True, exist_ok=True)
        body = "".join(cases)
        Path(xml).write_text(f"<testsuites><testsuite>{body}</testsuite></testsuites>")
    sys.exit(0)

rc = 0
cases = []
for n in chosen:
    if n in drop:
        continue
    cls, name = gs.nodeid_to_key(n)
    child = ""
    if n in fail:
        child = '<failure message="boom">x</failure>'; rc = 1
    elif n in skip:
        child = f'<skipped type="pytest.skip" message="{skip[n]}">f:1: {skip[n]}</skipped>'
    cases.append(f'<testcase classname="{cls}" name="{name}" time="0.01">{child}</testcase>')
if xml:
    Path(xml).parent.mkdir(parents=True, exist_ok=True)
    Path(xml).write_text('<testsuites><testsuite>' + "".join(cases) + '</testsuite></testsuites>')
sys.exit(rc)
"""


def _exe(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class _Fake:
    """A throwaway toolchain: fake python/bwrap/unshare plus a universe of ids."""

    def __init__(self, root: Path, universe: dict[str, Any]) -> None:
        self.root = root
        root.mkdir(parents=True)
        self.bin = root / "bin"
        self.bin.mkdir()
        (root / "fake_pytest.py").write_text(_FAKE_PYTEST, encoding="utf-8")
        real = sys.executable
        _exe(
            self.bin / "python",
            "#!/usr/bin/env bash\nset -euo pipefail\n"
            "if [[ ${1:-} == '-I' ]]; then\n"
            "  printf '%s\\n' tests/integration/test_bwrap_host_phase_witness.py; exit 0\nfi\n"
            f'exec "{real}" "{root}/fake_pytest.py" "${{@:3}}"\n',
        )
        _exe(
            self.bin / "bwrap",
            "#!/usr/bin/env bash\nset -euo pipefail\n"
            "while [[ $# -gt 0 ]]; do\n  case $1 in\n"
            '    --setenv) export "$2=$3"; shift 3;;\n'
            "    --dev-bind|--ro-bind) shift 3;;\n    --chdir|--dev|--proc) shift 2;;\n"
            "    --unshare-*|--disable-userns) shift;;\n    *) break;;\n  esac\ndone\n"
            'exec "$@"\n',
        )
        self.universe_path = root / "universe.json"
        self.universe_path.write_text(json.dumps(universe), encoding="utf-8")
        self.log = root / "calls.jsonl"
        self.reference = root / "reference.json"
        self.reference.write_text(
            json.dumps({"version": 1, "non_pass": {"0": [], "1": []}}), encoding="utf-8"
        )

    def env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        env = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "HOME": str(self.root / "home"),
            "BREEZY_PYTHON": str(self.bin / "python"),
            "BREEZY_GATE_TOOL_PYTHON": sys.executable,
            "BREEZY_FAKE_LOG": str(self.log),
            "BREEZY_FAKE_UNIVERSE": str(self.universe_path),
            "FAKE_SCRIPTS_DIR": str(REPO_ROOT / "scripts" / "ci"),
            "BREEZY_GATE_REFERENCE": str(self.reference),
            "BREEZY_GATE_TAIL_MAX_WAIT_S": "0",
            "PYTHONPATH": str(REPO_ROOT / "src"),
        }
        if extra:
            env.update(extra)
        return env

    def calls(self) -> list[dict[str, Any]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines() if line]


_SHELL_IDS: Final[list[str]] = [
    "tests/unit/test_one.py::test_a",
    "tests/unit/test_one.py::test_b[1]",
    "tests/unit/test_one.py::test_b[2]",
    "tests/unit/test_two.py::test_c",
    "tests/unit/test_three.py::test_d",
    "tests/unit/test_tier_infra.py::test_tail_member",
]


@pytest.fixture
def run_dir() -> Iterator[Path]:
    path = REPO_ROOT / ".pytest-tmp" / f"gs-{uuid.uuid4().hex[:8]}"
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _run_parallel(
    fake: _Fake, run_dir: Path, *args: str, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PARALLEL_SH), "--run-dir", str(run_dir), *args],
        cwd=REPO_ROOT,
        env=fake.env(extra_env),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _fake(tmp_path: Path, **universe: Any) -> _Fake:
    return _Fake(tmp_path / "fake", {"ids": _SHELL_IDS, **universe})


def test_shell_green_run_executes_every_unit_with_per_job_isolation(
    tmp_path: Path, run_dir: Path
) -> None:
    fake = _fake(tmp_path)
    result = _run_parallel(fake, run_dir, "--shards", "2")
    assert result.returncode == 0, result.stderr + result.stdout
    runs = [c for c in fake.calls() if not c["collect"] and c["phase2"] != "1"]
    assert len(runs) == 3  # two shards plus the tail
    assert len({c["gate_dir"] for c in runs}) == 3
    assert len({c["tmpdir"] for c in runs}) == 3
    assert len({c["basetemp"] for c in runs}) == 3
    for call in runs:
        for key in ("gate_dir", "tmpdir", "basetemp"):
            assert str(call[key]).startswith(str(run_dir)), call
    assert all(not a.startswith("@") for c in runs for a in c["args"])
    shard_args = sorted(a for c in runs[:2] for a in c["args"])
    assert "tests/unit/test_tier_infra.py" not in shard_args
    assert any(c["args"] == ["tests/unit/test_tier_infra.py"] for c in runs)
    assert "execution proof" in result.stdout.lower()


def test_shell_tail_starts_only_after_every_shard_has_exited(tmp_path: Path, run_dir: Path) -> None:
    fake = _fake(tmp_path)
    assert _run_parallel(fake, run_dir, "--shards", "2").returncode == 0
    runs = [c for c in fake.calls() if not c["collect"] and c["phase2"] != "1"]
    assert runs[-1]["args"] == ["tests/unit/test_tier_infra.py"]


def test_shell_refuses_a_run_dir_outside_pytest_tmp(tmp_path: Path) -> None:
    fake = _fake(tmp_path)
    result = _run_parallel(fake, tmp_path / "elsewhere")
    assert result.returncode == 2
    assert fake.calls() == []


def test_shell_refuses_unknown_arguments(tmp_path: Path, run_dir: Path) -> None:
    fake = _fake(tmp_path)
    result = _run_parallel(fake, run_dir, "--record-reference")
    assert result.returncode == 2 and fake.calls() == []


def test_shell_empty_collection_exits_2_before_any_shard_starts(
    tmp_path: Path, run_dir: Path
) -> None:
    fake = _fake(tmp_path, ids=[])
    result = _run_parallel(fake, run_dir)
    assert result.returncode == 2
    assert [c for c in fake.calls() if not c["collect"]] == []


def test_shell_nonzero_shard_rc_is_the_gate_rc_and_the_tail_still_runs(
    tmp_path: Path, run_dir: Path
) -> None:
    fake = _fake(tmp_path, fail=["tests/unit/test_two.py::test_c"])
    result = _run_parallel(fake, run_dir, "--shards", "2")
    assert result.returncode == 1
    assert any(c["args"] == ["tests/unit/test_tier_infra.py"] for c in fake.calls())


def test_shell_phase2_rc_propagates_through_a_shard(tmp_path: Path, run_dir: Path) -> None:
    fake = _fake(tmp_path)
    result = _run_parallel(fake, run_dir, "--shards", "1", extra_env={"BREEZY_FAKE_PHASE2_RC": "7"})
    assert result.returncode == 7


def test_shell_execution_proof_fails_when_a_test_does_not_run(
    tmp_path: Path, run_dir: Path
) -> None:
    fake = _fake(tmp_path, drop_from_run=["tests/unit/test_three.py::test_d"])
    result = _run_parallel(fake, run_dir, "--shards", "2")
    assert result.returncode == 4
    assert "missing" in (result.stdout + result.stderr)


def test_shell_skips_empty_shards_explicitly(tmp_path: Path, run_dir: Path) -> None:
    fake = _fake(tmp_path, ids=["tests/unit/test_one.py::test_a"])
    result = _run_parallel(fake, run_dir, "--shards", "3")
    assert result.returncode == 0, result.stderr + result.stdout
    assert "empty" in result.stdout.lower()
    runs = [c for c in fake.calls() if not c["collect"] and c["phase2"] != "1"]
    assert len(runs) == 1


def test_shell_collect_skipped_module_is_not_assigned_and_is_checked(
    tmp_path: Path, run_dir: Path
) -> None:
    fake = _fake(tmp_path, collect_skip_files=["tests/unit/test_gone.py"])
    result = _run_parallel(fake, run_dir, "--shards", "2")
    # Skips at collection but the (empty) reference does not list it.
    assert result.returncode in (0, 4)
    runs = [c for c in fake.calls() if not c["collect"] and c["phase2"] != "1"]
    assert all("tests/unit/test_gone.py" not in c["args"] for c in runs)
    assert "OUTCOME CHECK ADVISORY" in result.stdout or result.returncode == 4


def test_shell_green_run_removes_scratch_and_failed_run_keeps_logs(
    tmp_path: Path, run_dir: Path
) -> None:
    fake = _fake(tmp_path)
    assert _run_parallel(fake, run_dir, "--shards", "2").returncode == 0
    assert not (run_dir / "bt").exists() and not (run_dir / "tmp").exists()
    assert (run_dir / "logs").is_dir()


def test_shell_script_never_writes_the_environment_and_leaves_the_default_gate_dir() -> None:
    text = PARALLEL_SH.read_text(encoding="utf-8")
    assert "os.environ" not in text
    assert ".cache/breezy-gate" not in text
    assert "setsid" in text and "mapfile -t" in text
    assert not re.search(r"(?<![\"$\[])@\S+\.(args|txt)", text)  # no pytest @file argv
