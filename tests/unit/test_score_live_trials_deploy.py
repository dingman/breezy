"""RED-first suite for I3-deploy of
`docs/plans/LIVE_FILL_SCORING_CHAIN_2026-09-05.md` -- the new 14:15 UTC
`breezy-score-live-trials` unit pair + `deploy/systemd/
score-live-trials-run.sh`. The counter (`structural_dead_stop.py`), the
scorer (`score_live_trials.py`) and the node-env pre-flight leaf
(`breezy.runtime.exec_state_db_path`) are built in parallel commits and are
deliberately NOT invoked here -- the wrapper's own `$PY` is stubbed with a
shell script that dispatches on the invocation shape, so argv, the marker
and failure propagation are pinned against a stub, never a real scorer
(plan section 3.0, `test_family_tally_v2_deploy.py:40-47,95-99,127-133`
idiom).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SYSTEMD_DIR = _REPO_ROOT / "deploy" / "systemd"
_FAMILIES_DIR = _REPO_ROOT / "deploy" / "families"
_WRAPPER = _SYSTEMD_DIR / "score-live-trials-run.sh"
_V1_WRAPPER = _SYSTEMD_DIR / "live-tally-run.sh"
_FAMILY_MANIFEST_LITERAL = str(_REPO_ROOT / "deploy" / "families" / "pm_us_crh_v2.json")


def _registered_polymarket_us_family_ids() -> list[str]:
    """L-38: every REGISTERED, venue=polymarket_us family manifest under
    THIS checkout's own `deploy/families` -- mirrors the wrapper's own
    enumeration (`manifest_field`), read directly here (never shelling out
    to the wrapper) so the expected set is independent of the fix under
    test."""
    ids: list[str] = []
    for path in sorted(_FAMILIES_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("venue") == "polymarket_us" and payload.get("status") == "REGISTERED":
            family_id = payload.get("family_id")
            if isinstance(family_id, str):
                ids.append(family_id)
    return ids

_PINNED_STATE_DB_LITERAL = (
    "Environment=POLYMARKET_US_EXEC_STATE_DB="
    "/home/jon/.local/share/breezy/state/exec_polymarket_us.sqlite"
)

_MARKER_WRITE_PATTERN = re.compile(
    r'^\s*:\s*>\s*"\$OUT/score_live_trials_ok_\$STAMP"\s*$', re.MULTILINE
)


def _default_counter_json(*, count: int = 20, fetch_start: str = "2026-09-05") -> str:
    payload = {
        "count": count,
        "depth_root_present": True,
        "fetch_end": "2026-09-05",
        "fetch_start": fetch_start,
        "manifest_sha256": "a" * 64,
        "stations": ["LAX", "MDW", "MIA", "SFO"],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _make_stub(
    tmp_path: Path,
    *,
    check_exit: int = 0,
    check_token: str = "MATCH",
    counter_exit: int = 0,
    counter_json: str | None = None,
    scorer_fail_city: str = "",
    scorer_exit: int = 0,
) -> tuple[Path, Path]:
    """A dispatching stub `$PY`: recognises the three invocation shapes the
    wrapper makes (the `--check` module call, the counter, one scorer call
    per city), logs each to `argv_log` tagged by shape, and behaves per the
    keyword arguments. Returns (stub_path, argv_log_path)."""
    argv_log = tmp_path / "argv_log.txt"
    json_text = counter_json if counter_json is not None else _default_counter_json()
    script = f"""#!/usr/bin/env bash
ARGV_LOG={shlex.quote(str(argv_log))}
case "$*" in
  *"-m breezy.runtime.exec_state_db_path --check"*)
    echo "CHECK $*" >> "$ARGV_LOG"
    echo "{check_token}"
    exit {check_exit}
    ;;
  *"structural_dead_stop.py"*)
    echo "COUNTER $*" >> "$ARGV_LOG"
    if [ {counter_exit} -eq 0 ]; then
      prev=""
      for arg in "$@"; do
        if [ "$prev" = "--output" ]; then
          cat > "$arg" <<'BREEZY_STUB_JSON'
{json_text}
BREEZY_STUB_JSON
        fi
        prev="$arg"
      done
    fi
    exit {counter_exit}
    ;;
  *"score_live_trials.py"*)
    echo "SCORER $*" >> "$ARGV_LOG"
    city=""
    prev=""
    for arg in "$@"; do
      if [ "$prev" = "--city" ]; then
        city="$arg"
      fi
      prev="$arg"
    done
    if [ -n "{scorer_fail_city}" ] && [ "$city" = "{scorer_fail_city}" ]; then
      exit 1
    fi
    exit {scorer_exit}
    ;;
  *)
    echo "UNKNOWN $*" >> "$ARGV_LOG"
    exit 0
    ;;
esac
"""
    stub = tmp_path / "stub_python.sh"
    stub.write_text(script)
    stub.chmod(0o755)
    return stub, argv_log


def _run_wrapper(
    tmp_path: Path,
    *,
    stub_python: Path | None,
    set_state_db: bool = True,
    families_dir: Path | None = None,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home)
    env["BREEZY_SCORED_TRIALS_DIR"] = str(tmp_path / "scored_trials")
    env["BREEZY_LIVE_TALLY_OUTPUT_DIR"] = str(tmp_path / "derived")
    # L-38: default to THIS checkout's own deploy/families (never the
    # deployed tree's, which the wrapper's hardcoded REPO=/home/jon/breezy
    # still points --fill-source-independent bits like the counter's
    # FAMILY_MANIFEST at) -- mirrors test_family_tally_v2_deploy.py's own
    # BREEZY_FAMILY_TALLY_V2_FAMILIES_DIR default override.
    env["BREEZY_SCORE_LIVE_TRIALS_FAMILIES_DIR"] = str(
        families_dir if families_dir is not None else _FAMILIES_DIR
    )
    if set_state_db:
        env["POLYMARKET_US_EXEC_STATE_DB"] = str(tmp_path / "state" / "exec_polymarket_us.sqlite")
    else:
        env.pop("POLYMARKET_US_EXEC_STATE_DB", None)
    if stub_python is not None:
        env["BREEZY_SCORE_LIVE_TRIALS_PYTHON"] = str(stub_python)
    return subprocess.run(
        ["bash", str(_WRAPPER)],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _marker_path(tmp_path: Path) -> Path:
    stamp = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d")
    return tmp_path / "derived" / f"score_live_trials_ok_{stamp}"


def _cjson_path(tmp_path: Path) -> Path:
    stamp = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d")
    return tmp_path / "derived" / f"covered_listed_station_days_{stamp}.json"


def _seed_stale_cjson(tmp_path: Path) -> Path:
    """A well-shaped but STALE/foreign counter JSON -- wrong station list,
    so a test can prove it either survived (bug) or was removed (fix)."""
    cjson = _cjson_path(tmp_path)
    cjson.parent.mkdir(parents=True, exist_ok=True)
    stale = json.loads(_default_counter_json())
    stale["stations"] = ["ZZZ"]
    cjson.write_text(json.dumps(stale, indent=2, sort_keys=True))
    return cjson


def _scorer_calls(argv_log: Path) -> list[str]:
    if not argv_log.exists():
        return []
    return [line for line in argv_log.read_text().splitlines() if line.startswith("SCORER")]


def _cities_of(calls: list[str]) -> set[str]:
    cities: set[str] = set()
    for call in calls:
        parts = call.split()
        cities.add(parts[parts.index("--city") + 1])
    return cities


def test_wrapper_exists_and_is_executable() -> None:
    assert _WRAPPER.exists()
    assert os.access(_WRAPPER, os.X_OK)


def test_wrapper_script_is_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n", str(_WRAPPER)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_marker_written_only_when_counter_and_all_cities_succeed(tmp_path: Path) -> None:
    # L-38: one scorer invocation per (city, REGISTERED family manifest)
    # pair -- 4 cities x every REGISTERED polymarket_us family (pm_us_crh_v2
    # AND pm_us_crh_cont today; kalshi_crh_v1/pm_us_crh_exit_v4 are
    # DRAFT_NOT_REGISTERED and never invoked), never 4 flat.
    stub, argv_log = _make_stub(tmp_path)
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode == 0, result.stderr
    assert _marker_path(tmp_path).exists()
    family_ids = _registered_polymarket_us_family_ids()
    assert len(family_ids) >= 2, "expected at least pm_us_crh_v2 and pm_us_crh_cont REGISTERED"
    assert len(_scorer_calls(argv_log)) == 4 * len(family_ids)


def test_one_city_failure_leaves_all_cities_attempted_no_marker_nonzero(
    tmp_path: Path,
) -> None:
    stub, argv_log = _make_stub(tmp_path, scorer_fail_city="MDW")
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode != 0
    assert not _marker_path(tmp_path).exists()
    calls = _scorer_calls(argv_log)
    family_ids = _registered_polymarket_us_family_ids()
    assert len(calls) == 4 * len(family_ids)
    assert _cities_of(calls) == {"LAX", "MDW", "MIA", "SFO"}


def test_counter_failure_leaves_no_marker_and_never_invokes_a_scorer(
    tmp_path: Path,
) -> None:
    stub, argv_log = _make_stub(tmp_path, counter_exit=1)
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode != 0
    assert not _marker_path(tmp_path).exists()
    assert not _scorer_calls(argv_log)


def test_check_exit_3_leaves_no_marker_and_never_runs_the_counter(tmp_path: Path) -> None:
    stub, argv_log = _make_stub(tmp_path, check_exit=3, check_token="MISMATCH")
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode != 0
    assert not _marker_path(tmp_path).exists()
    calls = argv_log.read_text().splitlines() if argv_log.exists() else []
    assert not any(line.startswith("COUNTER") for line in calls)


def test_no_node_token_warns_but_marker_still_written(tmp_path: Path) -> None:
    stub, _ = _make_stub(tmp_path, check_token="NO_NODE", check_exit=0)
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode == 0, result.stderr
    assert _marker_path(tmp_path).exists()
    log_text = (tmp_path / "derived" / "score_live_trials.log").read_text()
    assert "NO_NODE" in log_text or "WARN" in log_text


def test_fetch_start_mismatch_leaves_no_marker(tmp_path: Path) -> None:
    bad_json = _default_counter_json(fetch_start="2026-09-06")
    stub, argv_log = _make_stub(tmp_path, counter_json=bad_json)
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode != 0
    assert not _marker_path(tmp_path).exists()
    assert not _scorer_calls(argv_log)


def test_stations_parsed_from_seeded_counter_json_exact_layout(tmp_path: Path) -> None:
    stub, argv_log = _make_stub(tmp_path)
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode == 0, result.stderr
    assert _cities_of(_scorer_calls(argv_log)) == {"LAX", "MDW", "MIA", "SFO"}


def test_scorer_argv_pinned_no_fill_source_family_manifest_present_one_city(
    tmp_path: Path,
) -> None:
    # NOTE: this test's ORIGINAL (pre-L-38) shape asserted the hardcoded
    # /home/jon/breezy `_FAMILY_MANIFEST_LITERAL` against every call; that
    # assertion is worktree-fragile (the wrapper's REPO= is hardcoded to
    # the deployed tree, never the checkout under test) and was already a
    # known worktree-only failure before this change. L-38 additionally
    # makes the single-manifest premise false (every call now carries
    # exactly ONE of >= 2 REGISTERED manifests, never always v2's), so this
    # test is widened to check shape generically instead of the one
    # hardcoded literal -- see test_scorer_argv_pinned_per_family below for
    # the real per-family pin.
    stub, argv_log = _make_stub(tmp_path)
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode == 0, result.stderr
    calls = _scorer_calls(argv_log)
    family_ids = _registered_polymarket_us_family_ids()
    assert len(calls) == 4 * len(family_ids)
    for call in calls:
        assert "--fill-source" not in call
        assert "--family-manifest" in call
        assert call.count("--city") == 1


def test_scorer_argv_pinned_per_family(tmp_path: Path) -> None:
    """L-38: every (city, family) pair gets its OWN scorer invocation --
    each call carries exactly one manifest (named by family_id, never a
    hardcoded literal path so this test is worktree-portable) and a
    --derived-dir ending in that same family_id's own subdirectory (never a
    shared top-level directory -- family_tally_v2.py's
    filter_rows_to_manifest_prefix refuses a store mixing two families'
    rows, FamilyStoreContaminationError)."""
    stub, argv_log = _make_stub(tmp_path)
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode == 0, result.stderr
    calls = _scorer_calls(argv_log)
    family_ids = _registered_polymarket_us_family_ids()
    assert len(calls) == 4 * len(family_ids)

    seen_pairs: set[tuple[str, str]] = set()
    for call in calls:
        parts = call.split()
        city = parts[parts.index("--city") + 1]
        manifest_arg = parts[parts.index("--family-manifest") + 1]
        derived_dir_arg = parts[parts.index("--derived-dir") + 1]
        matching = [fid for fid in family_ids if manifest_arg.endswith(f"/{fid}.json")]
        assert len(matching) == 1, f"call {call!r} manifest did not match exactly one family id"
        family_id = matching[0]
        assert derived_dir_arg.endswith(f"/{family_id}"), (
            f"--derived-dir {derived_dir_arg!r} does not end with the family's own "
            f"subdirectory /{family_id}"
        )
        seen_pairs.add((city, family_id))

    expected_pairs = {
        (city, family_id)
        for city in ("LAX", "MDW", "MIA", "SFO")
        for family_id in family_ids
    }
    assert seen_pairs == expected_pairs


def test_draft_family_manifests_are_skipped_with_a_logged_reason(tmp_path: Path) -> None:
    """kalshi_crh_v1 (DRAFT_NOT_REGISTERED, and non-polymarket_us venue) and
    pm_us_crh_exit_v4 (DRAFT_NOT_REGISTERED) must never be invoked, and the
    skip must be visible in the log -- never a silent drop."""
    stub, argv_log = _make_stub(tmp_path)
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode == 0, result.stderr
    calls = _scorer_calls(argv_log)
    assert not any("kalshi_crh_v1" in call for call in calls)
    assert not any("pm_us_crh_exit_v4" in call for call in calls)
    log_text = (tmp_path / "derived" / "score_live_trials.log").read_text()
    assert "kalshi_crh_v1.json" in log_text and "SKIP" in log_text
    assert "pm_us_crh_exit_v4.json" in log_text and "SKIP" in log_text


def test_no_registered_family_manifests_skips_with_no_marker(tmp_path: Path) -> None:
    """An empty/all-draft FAMILIES_DIR override must refuse loudly (exit
    nonzero, no marker, no scorer invocation) rather than silently writing
    a success marker over zero scored families."""
    empty_dir = tmp_path / "empty_families"
    empty_dir.mkdir()
    stub, argv_log = _make_stub(tmp_path)
    result = _run_wrapper(tmp_path, stub_python=stub, families_dir=empty_dir)
    assert result.returncode != 0
    assert not _marker_path(tmp_path).exists()
    assert not _scorer_calls(argv_log)


def test_unset_state_db_env_var_is_nonzero_and_never_invokes_python(tmp_path: Path) -> None:
    stub, argv_log = _make_stub(tmp_path)
    result = _run_wrapper(tmp_path, stub_python=stub, set_state_db=False)
    assert result.returncode != 0
    assert not argv_log.exists()


def test_stale_marker_removed_when_a_later_run_fails(tmp_path: Path) -> None:
    # F2: a prior successful run's marker must not survive a later same-day
    # failed run -- both tally wrappers accept the marker by existence alone.
    stub, _argv_log = _make_stub(tmp_path, scorer_fail_city="MDW")
    marker = _marker_path(tmp_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()
    assert marker.exists()

    result = _run_wrapper(tmp_path, stub_python=stub)

    assert result.returncode != 0
    assert not marker.exists()


def test_stale_marker_removed_then_rewritten_on_a_later_successful_run(
    tmp_path: Path,
) -> None:
    stub, _argv_log = _make_stub(tmp_path)
    marker = _marker_path(tmp_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("stale-run-marker-content")

    result = _run_wrapper(tmp_path, stub_python=stub)

    assert result.returncode == 0, result.stderr
    assert marker.exists()
    assert marker.read_text() == ""


def test_truncated_counter_json_missing_closing_brace_leaves_no_marker(
    tmp_path: Path,
) -> None:
    lines = _default_counter_json().splitlines()
    truncated = "\n".join(lines[:-1])  # drop the closing "}"
    stub, argv_log = _make_stub(tmp_path, counter_json=truncated)

    result = _run_wrapper(tmp_path, stub_python=stub)

    assert result.returncode != 0
    assert not _marker_path(tmp_path).exists()
    assert not _scorer_calls(argv_log)


def test_counter_json_with_duplicate_count_line_leaves_no_marker(tmp_path: Path) -> None:
    lines = _default_counter_json().splitlines()
    count_idx = next(i for i, line in enumerate(lines) if line.strip().startswith('"count"'))
    duplicated = lines[: count_idx + 1] + [lines[count_idx]] + lines[count_idx + 1 :]
    bad_json = "\n".join(duplicated)
    stub, argv_log = _make_stub(tmp_path, counter_json=bad_json)

    result = _run_wrapper(tmp_path, stub_python=stub)

    assert result.returncode != 0
    assert not _marker_path(tmp_path).exists()
    assert not _scorer_calls(argv_log)


def test_stale_counter_json_removed_when_counter_fails(tmp_path: Path) -> None:
    # Trust-boundary residual (Codex re-check, MEDIUM): a stale or foreign
    # well-shaped counter JSON must never survive to be read by a station
    # loop or the v1 tally wrapper -- it must be gone the instant this run's
    # own counter did not (re)write it.
    stub, argv_log = _make_stub(tmp_path, counter_exit=1)
    cjson = _seed_stale_cjson(tmp_path)
    assert cjson.exists()

    result = _run_wrapper(tmp_path, stub_python=stub)

    assert result.returncode != 0
    assert not cjson.exists()
    assert not _marker_path(tmp_path).exists()
    assert not _scorer_calls(argv_log)


def test_stale_counter_json_replaced_by_this_runs_fresh_output_on_success(
    tmp_path: Path,
) -> None:
    stub, argv_log = _make_stub(tmp_path)
    cjson = _seed_stale_cjson(tmp_path)

    result = _run_wrapper(tmp_path, stub_python=stub)

    assert result.returncode == 0, result.stderr
    assert cjson.exists()
    fresh = json.loads(cjson.read_text())
    assert fresh["stations"] == ["LAX", "MDW", "MIA", "SFO"]
    assert _marker_path(tmp_path).exists()
    assert len(_scorer_calls(argv_log)) == 4 * len(_registered_polymarket_us_family_ids())


def test_environment_lines_byte_identical_and_equal_pinned_literal() -> None:
    names = (
        "breezy-score-live-trials.service",
        "breezy-live-tally.service",
        "breezy-pm-crh-v2-tally.service",
    )
    env_lines: list[str] = []
    for name in names:
        text = (_SYSTEMD_DIR / name).read_text()
        matching = [
            line
            for line in text.splitlines()
            if line.startswith("Environment=POLYMARKET_US_EXEC_STATE_DB=")
        ]
        assert len(matching) == 1, name
        env_lines.append(matching[0])
    assert env_lines[0] == env_lines[1] == env_lines[2] == _PINNED_STATE_DB_LITERAL


def test_neither_i3_unit_carries_an_environment_file_directive() -> None:
    # Repo-wide: breezy-quote-tape.service legitimately carries an
    # EnvironmentFile= for venue credentials -- out of scope here. This
    # increment's invariant is narrower: neither of the units that carry
    # the pinned sqlite Environment= line may carry an EnvironmentFile=.
    for name in (
        "breezy-score-live-trials.service",
        "breezy-live-tally.service",
        "breezy-pm-crh-v2-tally.service",
    ):
        assert "EnvironmentFile=" not in (_SYSTEMD_DIR / name).read_text(), name


def test_family_manifest_assignment_byte_identical_across_wrappers() -> None:
    scorer_lines = [
        line for line in _WRAPPER.read_text().splitlines() if line.startswith("FAMILY_MANIFEST=")
    ]
    v1_lines = [
        line for line in _V1_WRAPPER.read_text().splitlines() if line.startswith("FAMILY_MANIFEST=")
    ]
    assert len(scorer_lines) == 1
    assert len(v1_lines) == 1
    assert scorer_lines[0] == v1_lines[0]


def test_v1_d0_literal_assignment_byte_identical_across_wrappers() -> None:
    scorer_lines = [
        line for line in _WRAPPER.read_text().splitlines() if line.startswith("V1_D0_LITERAL=")
    ]
    v1_lines = [
        line for line in _V1_WRAPPER.read_text().splitlines() if line.startswith("V1_D0_LITERAL=")
    ]
    assert len(scorer_lines) == 1
    assert len(v1_lines) == 1
    assert scorer_lines[0] == v1_lines[0]


def test_only_the_scorer_wrapper_writes_the_success_marker() -> None:
    writers = [
        sh.name
        for sh in sorted(_SYSTEMD_DIR.glob("*.sh"))
        if _MARKER_WRITE_PATTERN.search(sh.read_text())
    ]
    assert writers == ["score-live-trials-run.sh"]


def test_score_live_trials_unit_pair_exists_and_wires_to_wrapper() -> None:
    service_path = _SYSTEMD_DIR / "breezy-score-live-trials.service"
    timer_path = _SYSTEMD_DIR / "breezy-score-live-trials.timer"
    assert service_path.exists()
    assert timer_path.exists()

    service_text = service_path.read_text()
    exec_lines = [line for line in service_text.splitlines() if line.startswith("ExecStart=")]
    assert len(exec_lines) == 1
    assert exec_lines[0].strip().endswith("score-live-trials-run.sh")
    assert "TimeoutStartSec=" in service_text
    assert "EnvironmentFile=" not in service_text

    timer_text = timer_path.read_text()
    assert "Unit=breezy-score-live-trials.service" in timer_text
    assert "OnCalendar=*-*-* 14:15:00 UTC" in timer_text
    assert "Persistent=true" in timer_text
