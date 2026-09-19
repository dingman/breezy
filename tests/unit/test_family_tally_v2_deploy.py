"""RED-first suite for build-order commit 8 of
`docs/plans/FAMILY_TALLY_V2_BLUEPRINT_2026-09-04.md`: the family-tally-v2
systemd deploy surface. The CLI (`scripts/analysis/family_tally_v2.py`) is
built in a parallel commit and is deliberately NOT invoked here -- the
wrapper's own test stubs `python` so id validation and argv construction are
verified without it.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from breezy.runtime.trade_supervisor_core import LAUNCH_WINDOW_END_UTC

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SYSTEMD_DIR = _REPO_ROOT / "deploy" / "systemd"
_WRAPPER = _SYSTEMD_DIR / "family-tally-v2-run.sh"
_FAMILIES_DIR = _REPO_ROOT / "deploy" / "families"


def _valid_family_ids() -> set[str]:
    """B6: a family manifest is valid only when its own `family_id` field
    equals the file's basename -- excludes `gs_boundary_pm_us_crh_v2.json`
    (a boundary artefact, never a family manifest, carries no `family_id`
    field at all) from ever being mistaken for a family id."""
    ids: set[str] = set()
    for p in _FAMILIES_DIR.glob("*.json"):
        try:
            payload = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("family_id") == p.stem:
            ids.add(p.stem)
    return ids


def _run_wrapper(
    family_arg: list[str],
    tmp_path: Path,
    *,
    stub_python: Path | None = None,
    create_marker: bool = True,
    set_state_db: bool = True,
    write_counter_json: bool = True,
    state_db: Path | None = None,
    families_dir: Path | None = None,
    unset_extra: frozenset[str] = frozenset(),
) -> subprocess.CompletedProcess[str]:
    # I3 (LIVE_FILL_SCORING_CHAIN_2026-09-05.md, BLOCK-2): the wrapper now
    # asserts the 14:15 score-live-trials-run.sh success marker before
    # tallying. Every pre-existing test in this module drives the wrapper
    # PAST that assertion by default (create_marker=True) so it exercises
    # exactly what it did before this increment; the two new marker tests
    # below flip it off.
    out_dir = tmp_path / "derived"
    env = dict(os.environ)
    env["BREEZY_SCORED_TRIALS_DIR"] = str(tmp_path / "scored_trials")
    env["BREEZY_LIVE_TALLY_OUTPUT_DIR"] = str(out_dir)
    # Default to THIS checkout's own deploy/families (never the deployed
    # tree's) so the wrapper enumerates exactly what `_valid_family_ids()`
    # sees -- the wrapper's own default (unset) still resolves to
    # $REPO/deploy/families for the real, deployed systemd unit.
    env["BREEZY_FAMILY_TALLY_V2_FAMILIES_DIR"] = str(
        families_dir if families_dir is not None else _FAMILIES_DIR
    )
    if stub_python is not None:
        env["BREEZY_FAMILY_TALLY_V2_PYTHON"] = str(stub_python)
    if set_state_db:
        env["POLYMARKET_US_EXEC_STATE_DB"] = str(
            state_db
            if state_db is not None
            else tmp_path / "state" / "exec_polymarket_us.sqlite"
        )
    else:
        env.pop("POLYMARKET_US_EXEC_STATE_DB", None)
    # Generic hook (WP-0b/WP-11b's env-var discovery test): remove ANY
    # named var, not just POLYMARKET_US_EXEC_STATE_DB, so a future wrapper
    # requirement is discoverable by the same mechanism without a new
    # dedicated `set_*` parameter per variable.
    for var in unset_extra:
        env.pop(var, None)
    if create_marker:
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d")
        (out_dir / f"score_live_trials_ok_{stamp}").touch()
    if write_counter_json:
        _write_counter_json(tmp_path)
    return subprocess.run(
        ["bash", str(_WRAPPER), *family_arg],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_wrapper_exists_and_is_executable() -> None:
    assert _WRAPPER.exists()
    assert os.access(_WRAPPER, os.X_OK)


def test_wrapper_script_is_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n", str(_WRAPPER)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_at_least_two_real_family_manifests_present() -> None:
    ids = _valid_family_ids()
    assert "pm_us_crh_v2" in ids
    assert "kalshi_crh_v1" in ids


def test_wrapper_rejects_unknown_family_id(tmp_path: Path) -> None:
    result = _run_wrapper(["definitely_not_a_real_family"], tmp_path)
    assert result.returncode == 2
    for valid_id in _valid_family_ids():
        assert valid_id in result.stderr, f"expected {valid_id!r} named in: {result.stderr!r}"
    assert "definitely_not_a_real_family" in result.stderr


def test_wrapper_rejects_missing_family_id(tmp_path: Path) -> None:
    result = _run_wrapper([], tmp_path)
    assert result.returncode == 2
    for valid_id in _valid_family_ids():
        assert valid_id in result.stderr


@pytest.mark.parametrize("family_id", sorted(_valid_family_ids()))
def test_wrapper_passes_family_id_through_unmodified(tmp_path: Path, family_id: str) -> None:
    capture = tmp_path / "argv_capture.txt"
    stub = tmp_path / "stub_python.sh"
    stub.write_text(
        f"""#!/usr/bin/env bash
case "$*" in
  *"-m breezy.runtime.exec_state_db_path --check"*)
    echo "MATCH"
    exit 0
    ;;
  *"-m breezy.runtime.structural_pin_guard"*)
    exit 0
    ;;
  *)
    printf "%s\\n" "$@" > "{capture}"
    exit 0
    ;;
esac
"""
    )
    stub.chmod(0o755)

    result = _run_wrapper([family_id], tmp_path, stub_python=stub)

    assert result.returncode == 0, result.stderr
    argv_lines = capture.read_text().splitlines()
    assert "--family" in argv_lines
    assert argv_lines[argv_lines.index("--family") + 1] == family_id
    assert "--store-dir" in argv_lines
    # L-38: this family's own scored-trial subdirectory
    # ($BREEZY_SCORED_TRIALS_DIR/<family_id>), never the shared top-level
    # directory -- family_tally_v2.py's filter_rows_to_manifest_prefix
    # refuses a store contaminated by another family's rows
    # (FamilyStoreContaminationError), so score-live-trials-run.sh writes
    # each REGISTERED family's rows to its own subdirectory and this
    # wrapper must read exactly that one back.
    store_dir_arg = argv_lines[argv_lines.index("--store-dir") + 1]
    assert store_dir_arg.endswith(f"/{family_id}"), (
        f"--store-dir {store_dir_arg!r} does not end with this family's own "
        f"subdirectory /{family_id}"
    )
    assert "--output" in argv_lines
    output_arg = argv_lines[argv_lines.index("--output") + 1]
    assert family_id in output_arg
    # B6: --as-of is passed a UTC date stamp (YYYY-MM-DD).
    assert "--as-of" in argv_lines
    as_of_arg = argv_lines[argv_lines.index("--as-of") + 1]
    assert len(as_of_arg) == len("2026-09-04")
    assert as_of_arg.count("-") == 2


def test_wrapper_never_lists_a_boundary_artefact_json_as_a_valid_family_id(
    tmp_path: Path,
) -> None:
    """B6: `gs_boundary_pm_us_crh_v2.json` sits in the same directory as the
    family manifests but is never itself a family manifest (no `family_id`
    field) -- the wrapper must never accept it as a `--family` value."""
    result = _run_wrapper(["gs_boundary_pm_us_crh_v2"], tmp_path)
    assert result.returncode == 2
    assert "gs_boundary_pm_us_crh_v2" not in _valid_family_ids()


def test_wrapper_families_dir_override_replaces_the_enumerated_manifest_set(
    tmp_path: Path,
) -> None:
    """`BREEZY_FAMILY_TALLY_V2_FAMILIES_DIR` swaps which directory the
    wrapper enumerates for `--family` validation -- it is what lets this
    module's own tests validate against THIS checkout's `deploy/families`
    (which may hold manifests, such as a DRAFT_NOT_REGISTERED one, not yet
    present on the deployed tree the wrapper defaults to) instead of
    silently reading the deployed tree's set. An id that is valid only in
    the override directory is accepted; the deployed-default set's ids are
    no longer recognised once the override is in effect."""
    only_family_dir = tmp_path / "only_family"
    only_family_dir.mkdir()
    (only_family_dir / "solo_family.json").write_text(
        json.dumps({"family_id": "solo_family"})
    )

    stub = tmp_path / "stub_python.sh"
    stub.write_text("#!/usr/bin/env bash\nexit 0\n")
    stub.chmod(0o755)
    accepted = _run_wrapper(
        ["solo_family"], tmp_path, stub_python=stub, families_dir=only_family_dir
    )
    assert accepted.returncode == 0, accepted.stderr

    rejected = _run_wrapper(
        ["pm_us_crh_v2"], tmp_path, stub_python=stub, families_dir=only_family_dir
    )
    assert rejected.returncode == 2
    valid_ids_named = rejected.stderr.split("valid ids:", 1)[1]
    assert "pm_us_crh_v2" not in valid_ids_named
    assert "solo_family" in valid_ids_named


def test_wrapper_exits_nonzero_and_never_invokes_the_tally_when_marker_absent(
    tmp_path: Path,
) -> None:
    stub = tmp_path / "stub_python.sh"
    capture = tmp_path / "argv_capture.txt"
    stub.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" >> "{capture}"\nexit 0\n')
    stub.chmod(0o755)

    family_id = min(_valid_family_ids())
    result = _run_wrapper([family_id], tmp_path, stub_python=stub, create_marker=False)

    assert result.returncode != 0
    assert not capture.exists()


def test_wrapper_invokes_the_tally_when_marker_present(tmp_path: Path) -> None:
    stub = tmp_path / "stub_python.sh"
    capture = tmp_path / "argv_capture.txt"
    stub.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "{capture}"\nexit 0\n')
    stub.chmod(0o755)

    family_id = min(_valid_family_ids())
    result = _run_wrapper([family_id], tmp_path, stub_python=stub, create_marker=True)

    assert result.returncode == 0, result.stderr
    assert capture.exists()


def test_wrapper_reports_failure_from_the_stub_analysis_script(tmp_path: Path) -> None:
    stub = tmp_path / "stub_python.sh"
    stub.write_text("#!/usr/bin/env bash\nexit 1\n")
    stub.chmod(0o755)

    family_id = min(_valid_family_ids())
    result = _run_wrapper([family_id], tmp_path, stub_python=stub)

    assert result.returncode == 1


#: WP-11b (active-family registry, cardinality-1): the former per-family
#: unit COPIES (breezy-pm-crh-v2-tally.{service,timer},
#: breezy-pm-crh-cont-tally.{service,timer}) are retired in favour of ONE
#: instantiated systemd template. `%i` (the systemd instance name) IS the
#: family id -- test_family_tally_template_passes_family_id_as_percent_i is
#: the WP-11b RED test naming this requirement directly.
_TEMPLATE_SERVICE = "breezy-family-tally@.service"
_TEMPLATE_TIMER = "breezy-family-tally@.timer"


def test_template_unit_pair_exists_and_wires_to_wrapper_via_percent_i() -> None:
    service_path = _SYSTEMD_DIR / _TEMPLATE_SERVICE
    timer_path = _SYSTEMD_DIR / _TEMPLATE_TIMER
    assert service_path.exists()
    assert timer_path.exists()

    service_text = service_path.read_text()
    exec_start_lines = [line for line in service_text.splitlines() if line.startswith("ExecStart=")]
    assert len(exec_start_lines) == 1
    assert "family-tally-v2-run.sh" in exec_start_lines[0]
    assert exec_start_lines[0].strip().endswith("%i")

    timer_text = timer_path.read_text()
    assert "Unit=breezy-family-tally@%i.service" in timer_text


def test_family_tally_template_passes_family_id_as_percent_i() -> None:
    """WP-11b RED test (9): no per-family ``ExecStart=`` literal survives --
    the template's ONLY argument to the wrapper is the systemd specifier
    ``%i``, so promoting a new family (e.g. a future ``fc_v1``/``fc_v2``
    forecast revision) is ``systemctl --user enable --now
    breezy-family-tally@<family_id>.timer``, never a new unit file."""
    service_text = (_SYSTEMD_DIR / _TEMPLATE_SERVICE).read_text()
    exec_start_lines = [
        line for line in service_text.splitlines() if line.startswith("ExecStart=")
    ]
    assert len(exec_start_lines) == 1
    exec_start = exec_start_lines[0]
    assert exec_start.strip().endswith("family-tally-v2-run.sh %i")
    # No literal family id anywhere on the ExecStart= line -- %i is the ONLY
    # argument token after the wrapper path.
    for literal_family_id in _valid_family_ids():
        assert literal_family_id not in exec_start

    # Neither retired per-family unit file exists any more -- the template
    # is the only unit driving this wrapper.
    assert not (_SYSTEMD_DIR / "breezy-pm-crh-v2-tally.service").exists()
    assert not (_SYSTEMD_DIR / "breezy-pm-crh-cont-tally.service").exists()


def test_template_timer_fires_at_1720_utc() -> None:
    timer_text = (_SYSTEMD_DIR / _TEMPLATE_TIMER).read_text()
    assert "OnCalendar=*-*-* 17:20:00 UTC" in timer_text


def test_template_tally_tick_is_after_node_launch() -> None:
    """A1: parse OnCalendar= and require the tick at/after launch-window end.

    Compares the parsed ``dt.time`` to ``LAUNCH_WINDOW_END_UTC`` (not a
    restated 16:50 literal).
    """
    timer_text = (_SYSTEMD_DIR / _TEMPLATE_TIMER).read_text()
    match = re.search(
        r"^OnCalendar=\S+\s+(\d{2}):(\d{2}):(\d{2})\s+UTC\s*$",
        timer_text,
        re.MULTILINE,
    )
    assert match is not None, f"{_TEMPLATE_TIMER} has no parseable OnCalendar="
    tick = _dt.time(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    assert tick >= LAUNCH_WINDOW_END_UTC


# --- WP-0b regression, folded together with WP-11b's template collapse ---
#
# WP-0b (commit 49e095c) built a discovery-based regression test,
# `test_every_tally_unit_carries_every_env_var_its_family_requires`, that
# derives BOTH sides from the real artefacts instead of hardcoding them:
#
#   * the REQUIRED variable set comes from parsing the wrapper's own
#     `${VAR:?message}` syntax -- never a Python-side restatement of which
#     variables it needs, which could drift the moment the wrapper's own
#     requirements change;
#   * WHICH families actually trigger that requirement is determined by
#     actually RUNNING the wrapper against each family's REAL manifest with
#     the variable unset and checking for the wrapper's own message --
#     never a Python mirror of the wrapper's
#     `status == REGISTERED and venue == polymarket_us` bash conditional;
#   * the units under test are DISCOVERED by scanning every
#     deploy/systemd/*.service file's ExecStart= for an invocation of
#     family-tally-v2-run.sh, never named one at a time.
#
# WP-0b's original `_discover_tally_units()` skipped any unit file that
# names no CONCRETE family -- an uninstantiated `@.service` template has no
# `@<instance>` suffix, so it named none. WP-11b's whole tally surface IS
# such a template (`breezy-family-tally@.service` replaces the per-family
# unit files WP-0b's discovery used to iterate), so that skip would leave
# POLYMARKET_US_EXEC_STATE_DB unguarded on the one unit that matters -- the
# exact env line WP-0b exists to keep from being missed.
#
# Fixed here by making the bare template a FIRST-CLASS discovery result
# rather than a skipped one: `_discover_tally_units()` now pairs a bare
# template with the set of every REGISTERED family in `deploy/families/`
# the wrapper could require a variable for (a template is instantiable with
# ANY of them), and the assertion loop below checks the template declares
# every variable required by ANY of those families. A concrete
# `@<instance>` unit, should one reappear, is still resolved to its own one
# family and checked individually.
#
# WP-11b's separate `test_bare_template_declares_every_env_var_...` test
# (added directly against the template, without going through
# `_discover_tally_units()`) is now REDUNDANT with this strengthened
# discovery test -- both derive the same required-var set from the
# wrapper's `${VAR:?...}` syntax and the same triggering-family set by
# running the real wrapper, and both assert the template declares the
# union. Folded into this one test rather than kept side by side.


def _required_env_var_messages() -> dict[str, str]:
    """Every strictly-required ``${VAR:?message}`` parameter expansion in
    the wrapper's own source, keyed by variable name. This is the wrapper's
    OWN definition of "required" -- never a hardcoded name list that could
    drift out of sync with it."""
    text = _WRAPPER.read_text()
    return dict(re.findall(r"\$\{([A-Z_][A-Z0-9_]*):\?([^}]*)\}", text))


def _discover_tally_units() -> list[tuple[Path, list[str]]]:
    """Every ``deploy/systemd/*.service`` unit whose ``ExecStart=`` invokes
    ``family-tally-v2-run.sh``, paired with the family id(s) it must
    satisfy the wrapper's env-var contract for. Units are found by
    scanning ExecStart=, never a hardcoded unit-name list:

    * a CONCRETE unit -- ``ExecStart=...wrapper %i`` on an
      ``@<instance>`` filename, or a literal family-id argument -- is
      paired with that ONE family id, resolved from the unit's own
      filename/argument;
    * a BARE, uninstantiated template (``ExecStart=...wrapper %i``, no
      ``@<instance>`` suffix -- WP-11b's ``breezy-family-tally@.service``)
      is instantiable with ANY REGISTERED family, so it is paired with
      EVERY valid family id and must satisfy the union of what any of them
      could require. It is a first-class discovery result, never skipped:
      skipping it would leave the one unit that matters unguarded.
    """
    pairs: list[tuple[Path, list[str]]] = []
    for unit in sorted(_SYSTEMD_DIR.glob("*.service")):
        text = unit.read_text()
        exec_start_lines = [
            line for line in text.splitlines() if line.startswith("ExecStart=")
        ]
        if not exec_start_lines:
            continue
        exec_start = exec_start_lines[0]
        if "family-tally-v2-run.sh" not in exec_start:
            continue
        trailing = exec_start.strip().split()[-1]
        if trailing == "%i":
            # unit.stem for "breezy-family-tally@pm_us_crh_v2.service" is
            # "breezy-family-tally@pm_us_crh_v2" (family after the "@");
            # for the BARE template "breezy-family-tally@.service" it is
            # "breezy-family-tally@" -- "@" present, but nothing after it.
            family_id = unit.stem.split("@", 1)[1] if "@" in unit.stem else ""
            if family_id:
                pairs.append((unit, [family_id]))
                continue
            # Bare template: instantiable with any REGISTERED family --
            # check it against the union of them, never skip it.
            family_ids = sorted(_valid_family_ids())
            assert family_ids, (
                f"{unit.name} is a bare template with no ExecStart= "
                "instance suffix, but no valid family manifest exists to "
                "check its env contract against"
            )
            pairs.append((unit, family_ids))
        else:
            pairs.append((unit, [trailing]))
    return pairs


def _family_requires_env_var(
    family_id: str, var_name: str, message: str, tmp_path: Path
) -> bool:
    """Run the REAL wrapper against family_id's REAL manifest with
    var_name unset, and report whether the wrapper's own bash parameter
    expansion fails with its own message -- the wrapper's runtime
    behaviour is the source of truth for "required", never a Python
    restatement of its internal branching."""
    probe_dir = tmp_path / f"probe_{family_id}_{var_name}"
    out_dir = probe_dir / "derived"
    out_dir.mkdir(parents=True)
    stamp = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d")
    (out_dir / f"score_live_trials_ok_{stamp}").touch()
    _write_counter_json(probe_dir)

    stub = probe_dir / "stub_python.sh"
    stub.write_text(
        """#!/usr/bin/env bash
case "$*" in
  *"-m breezy.runtime.exec_state_db_path --check"*)
    echo "MATCH"
    exit 0
    ;;
  *"-m breezy.runtime.structural_pin_guard"*)
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
"""
    )
    stub.chmod(0o755)

    env = dict(os.environ)
    env["BREEZY_SCORED_TRIALS_DIR"] = str(probe_dir / "scored_trials")
    env["BREEZY_LIVE_TALLY_OUTPUT_DIR"] = str(out_dir)
    env["BREEZY_FAMILY_TALLY_V2_FAMILIES_DIR"] = str(_FAMILIES_DIR)
    env["BREEZY_FAMILY_TALLY_V2_PYTHON"] = str(stub)
    env.pop(var_name, None)

    result = subprocess.run(
        ["bash", str(_WRAPPER), family_id],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    log_path = out_dir / "family_tally_v2.log"
    blob = f"{result.stdout}{result.stderr}"
    blob += log_path.read_text() if log_path.exists() else ""
    return result.returncode != 0 and message in blob


def test_every_tally_unit_carries_every_env_var_its_family_requires(
    tmp_path: Path,
) -> None:
    """WP-0b regression, strengthened for WP-11b's template collapse:
    catches a tally unit -- concrete OR the bare, instantiable-with-any-
    family template -- that invokes the wrapper for a family the wrapper
    requires a variable for, without declaring it. Discovery never skips
    the bare template; it is checked against the union of every family it
    could be instantiated with."""
    required_messages = _required_env_var_messages()
    assert required_messages, (
        "expected at least one ${VAR:?message} required parameter in "
        f"{_WRAPPER} -- wrapper syntax changed, this test's derivation is stale"
    )
    assert "POLYMARKET_US_EXEC_STATE_DB" in required_messages, (
        "the wrapper's own ${VAR:?...} syntax no longer names "
        "POLYMARKET_US_EXEC_STATE_DB -- update this test's expectation, "
        "do not just widen the template"
    )

    units = _discover_tally_units()
    assert units, "expected at least one systemd unit invoking family-tally-v2-run.sh"

    requires_cache: dict[tuple[str, str], bool] = {}

    def _requires(family_id: str, var_name: str, message: str) -> bool:
        key = (family_id, var_name)
        if key not in requires_cache:
            requires_cache[key] = _family_requires_env_var(
                family_id, var_name, message, tmp_path
            )
        return requires_cache[key]

    checked_a_required_case = False
    for unit_path, family_ids in units:
        unit_text = unit_path.read_text()
        for family_id in family_ids:
            manifest_path = _FAMILIES_DIR / f"{family_id}.json"
            assert manifest_path.exists(), (
                f"{unit_path.name} invokes the wrapper for unknown family {family_id!r}"
            )

            for var_name, message in required_messages.items():
                if not _requires(family_id, var_name, message):
                    continue
                checked_a_required_case = True
                has_line = re.search(
                    rf"^Environment={re.escape(var_name)}=", unit_text, re.MULTILINE
                )
                assert has_line, (
                    f"{unit_path.name} invokes family-tally-v2-run.sh for family "
                    f"{family_id!r}, which the wrapper's own logic requires "
                    f"{var_name} for, but the unit declares no "
                    f"Environment={var_name}= line"
                )

    assert checked_a_required_case, (
        "no discovered unit's family actually required any of the wrapper's "
        "required variables -- this test would pass vacuously; the "
        "fixture/manifest set changed under it"
    )


def _write_counter_json(
    tmp_path: Path, *, fetch_start: str = "2026-09-05", count: int = 20
) -> Path:
    out = tmp_path / "derived"
    out.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d")
    payload = {
        "count": count,
        "depth_root_present": True,
        "fetch_end": fetch_start,
        "fetch_start": fetch_start,
        "manifest_sha256": "b" * 64,
        "stations": ["LAX", "MDW", "MIA", "SFO"],
    }
    path = out / f"covered_listed_station_days_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return path


def test_wrapper_passes_covered_listed_and_fill_source(tmp_path: Path) -> None:
    """pm_us_crh_v2 only: same-day JSON + POLYMARKET_US_EXEC_STATE_DB + d0."""
    capture = tmp_path / "argv_capture.txt"
    stub = tmp_path / "stub_python.sh"
    stub.write_text(
        f"""#!/usr/bin/env bash
case "$*" in
  *"-m breezy.runtime.exec_state_db_path --check"*)
    echo "MATCH"
    exit 0
    ;;
  *"-m breezy.runtime.structural_pin_guard"*)
    exit 0
    ;;
  *)
    printf "%s\\n" "$@" > "{capture}"
    exit 0
    ;;
esac
"""
    )
    stub.chmod(0o755)
    _write_counter_json(tmp_path, count=42, fetch_start="2026-09-05")
    result = _run_wrapper(
        ["pm_us_crh_v2"],
        tmp_path,
        stub_python=stub,
        set_state_db=True,
        write_counter_json=False,
    )
    assert result.returncode == 0, result.stderr
    argv_lines = capture.read_text().splitlines()
    assert "--covered-listed-station-days" in argv_lines
    assert argv_lines[argv_lines.index("--covered-listed-station-days") + 1] == "42"
    assert "--fill-source" in argv_lines
    assert argv_lines[argv_lines.index("--fill-source") + 1] == str(
        tmp_path / "state" / "exec_polymarket_us.sqlite"
    )
    assert "--fill-since-climate-day" in argv_lines
    assert argv_lines[argv_lines.index("--fill-since-climate-day") + 1] == "2026-09-05"

    kalshi_capture = tmp_path / "kalshi_argv.txt"
    kalshi_stub = tmp_path / "kalshi_stub.sh"
    kalshi_stub.write_text(
        f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "{kalshi_capture}"\nexit 0\n'
    )
    kalshi_stub.chmod(0o755)
    kalshi = _run_wrapper(["kalshi_crh_v1"], tmp_path, stub_python=kalshi_stub)
    assert kalshi.returncode == 0, kalshi.stderr
    kalshi_argv = kalshi_capture.read_text().splitlines()
    assert "--covered-listed-station-days" not in kalshi_argv
    assert "--fill-source" not in kalshi_argv
    assert "--fill-since-climate-day" not in kalshi_argv


def test_wrapper_skips_when_counter_json_absent(tmp_path: Path) -> None:
    capture = tmp_path / "argv_capture.txt"
    stub = tmp_path / "stub_python.sh"
    stub.write_text(
        f"""#!/usr/bin/env bash
case "$*" in
  *"-m breezy.runtime.exec_state_db_path --check"*)
    echo "MATCH"
    exit 0
    ;;
  *"-m breezy.runtime.structural_pin_guard"*)
    exit 0
    ;;
  *)
    printf "%s\\n" "$@" > "{capture}"
    exit 0
    ;;
esac
"""
    )
    stub.chmod(0o755)
    result = _run_wrapper(
        ["pm_us_crh_v2"],
        tmp_path,
        stub_python=stub,
        set_state_db=True,
        write_counter_json=False,
    )
    assert result.returncode != 0
    assert not capture.exists()


def _wrapper_output_blob(result: subprocess.CompletedProcess[str], tmp_path: Path) -> str:
    log_path = tmp_path / "derived" / "family_tally_v2.log"
    log_text = log_path.read_text() if log_path.exists() else ""
    return f"{result.stdout}{result.stderr}{log_text}"


def test_pm_wrapper_exits_nonzero_and_does_not_invoke_tally_when_check_returns_no_node(
    tmp_path: Path,
) -> None:
    capture = tmp_path / "argv_capture.txt"
    stub = tmp_path / "stub_python.sh"
    stub.write_text(
        f"""#!/usr/bin/env bash
case "$*" in
  *"-m breezy.runtime.exec_state_db_path --check"*)
    echo "NO_NODE"
    exit 0
    ;;
  *"-m breezy.runtime.structural_pin_guard"*)
    echo "UNAVAILABLE token='NO_NODE'" >&2
    exit 1
    ;;
  *)
    printf "%s\\n" "$@" > "{capture}"
    exit 0
    ;;
esac
"""
    )
    stub.chmod(0o755)
    result = _run_wrapper(
        ["pm_us_crh_v2"],
        tmp_path,
        stub_python=stub,
        set_state_db=True,
    )
    blob = _wrapper_output_blob(result, tmp_path)
    assert result.returncode != 0
    assert "UNAVAILABLE" in blob or "PRE_LAUNCH" in blob
    assert "NO_NODE" in blob
    assert not capture.exists()


def test_pm_wrapper_exits_nonzero_and_does_not_invoke_tally_when_check_refuses(
    tmp_path: Path,
) -> None:
    """Non-zero --check (token 'refused') must fail-loud: no sequential tally."""
    capture = tmp_path / "argv_capture.txt"
    stub = tmp_path / "stub_python.sh"
    stub.write_text(
        f"""#!/usr/bin/env bash
case "$*" in
  *"-m breezy.runtime.exec_state_db_path --check"*)
    exit 1
    ;;
  *"-m breezy.runtime.structural_pin_guard"*)
    echo "UNAVAILABLE token='refused'" >&2
    exit 1
    ;;
  *)
    printf "%s\\n" "$@" > "{capture}"
    exit 0
    ;;
esac
"""
    )
    stub.chmod(0o755)
    result = _run_wrapper(
        ["pm_us_crh_v2"],
        tmp_path,
        stub_python=stub,
        set_state_db=True,
    )
    blob = _wrapper_output_blob(result, tmp_path)
    assert result.returncode != 0
    assert "UNAVAILABLE" in blob or "PRE_LAUNCH" in blob
    assert "refused" in blob
    assert not capture.exists()


def test_pm_wrapper_mismatch_exits_1_and_does_not_pass_fill_source(
    tmp_path: Path,
) -> None:
    """A7/A12: --check exit 3 (MISMATCH) → wrapper exit 1, no --fill-source."""
    capture = tmp_path / "argv_capture.txt"
    guard_capture = tmp_path / "guard_argv.txt"
    stub = tmp_path / "stub_python.sh"
    stub.write_text(
        f"""#!/usr/bin/env bash
case "$*" in
  *"-m breezy.runtime.exec_state_db_path --check"*)
    echo "MISMATCH"
    exit 3
    ;;
  *"-m breezy.runtime.structural_pin_guard"*)
    printf "%s\\n" "$@" > "{guard_capture}"
    exit 1
    ;;
  *)
    printf "%s\\n" "$@" > "{capture}"
    exit 0
    ;;
esac
"""
    )
    stub.chmod(0o755)
    other_db = tmp_path / "other" / "exec_polymarket_us.sqlite"
    result = _run_wrapper(
        ["pm_us_crh_v2"],
        tmp_path,
        stub_python=stub,
        set_state_db=True,
        state_db=other_db,
    )
    assert result.returncode == 1
    assert not capture.exists()
    assert guard_capture.exists()
    guard_argv = guard_capture.read_text().splitlines()
    assert "--token" in guard_argv
    assert guard_argv[guard_argv.index("--token") + 1] == "MISMATCH"


def test_pm_wrapper_invokes_structural_pin_guard_then_tally_on_match(
    tmp_path: Path,
) -> None:
    tally_capture = tmp_path / "tally_argv.txt"
    guard_capture = tmp_path / "guard_argv.txt"
    stub = tmp_path / "stub_python.sh"
    stub.write_text(
        f"""#!/usr/bin/env bash
case "$*" in
  *"-m breezy.runtime.exec_state_db_path --check"*)
    echo "MATCH"
    exit 0
    ;;
  *"-m breezy.runtime.structural_pin_guard"*)
    printf "%s\\n" "$@" > "{guard_capture}"
    exit 0
    ;;
  *)
    printf "%s\\n" "$@" > "{tally_capture}"
    exit 0
    ;;
esac
"""
    )
    stub.chmod(0o755)
    result = _run_wrapper(
        ["pm_us_crh_v2"],
        tmp_path,
        stub_python=stub,
        set_state_db=True,
    )
    assert result.returncode == 0, result.stderr
    assert guard_capture.exists()
    guard_argv = guard_capture.read_text().splitlines()
    assert "--family" in guard_argv
    assert guard_argv[guard_argv.index("--family") + 1] == "pm_us_crh_v2"
    assert "--token" in guard_argv
    assert guard_argv[guard_argv.index("--token") + 1] == "MATCH"
    assert "--now" not in guard_argv
    tally_argv = tally_capture.read_text().splitlines()
    assert "--covered-listed-station-days" in tally_argv
    assert "--fill-source" in tally_argv
    assert "--fill-since-climate-day" in tally_argv
    assert tally_argv[tally_argv.index("--fill-since-climate-day") + 1] == "2026-09-05"


def test_wrapper_passes_covered_listed_and_fill_source_for_cont_family_with_its_own_d0(
    tmp_path: Path,
) -> None:
    """SD-1/L-38: pm_us_crh_cont is REGISTERED + venue=polymarket_us but is
    NOT the literal pm_us_crh_v2 -- before the fix it got neither input and
    tallied with filled_takes=None forever (its structural-dead stop never
    evaluable). It must now get all three flags too, WITHOUT going through
    the v2-only structural-pin-guard/CHECK_TOKEN path (no case for
    `exec_state_db_path`/`structural_pin_guard` in this stub -- if the
    wrapper called either for a non-pm_us_crh_v2 family this test's stub
    would fall through to the default capture branch and corrupt the
    tally's own argv capture). `--fill-since-climate-day` must be the
    family's OWN `d0_climate_day` (2026-09-12), never the v2 literal
    (2026-09-05) baked into the shared counter JSON's `fetch_start`.
    """
    capture = tmp_path / "argv_capture.txt"
    stub = tmp_path / "stub_python.sh"
    stub.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "{capture}"\nexit 0\n')
    stub.chmod(0o755)
    _write_counter_json(tmp_path, count=17, fetch_start="2026-09-05")
    result = _run_wrapper(
        ["pm_us_crh_cont"],
        tmp_path,
        stub_python=stub,
        set_state_db=True,
        write_counter_json=False,
    )
    assert result.returncode == 0, result.stderr
    argv_lines = capture.read_text().splitlines()
    assert "--covered-listed-station-days" in argv_lines
    assert argv_lines[argv_lines.index("--covered-listed-station-days") + 1] == "17"
    assert "--fill-source" in argv_lines
    assert argv_lines[argv_lines.index("--fill-source") + 1] == str(
        tmp_path / "state" / "exec_polymarket_us.sqlite"
    )
    assert "--fill-since-climate-day" in argv_lines
    assert argv_lines[argv_lines.index("--fill-since-climate-day") + 1] == "2026-09-12"


def test_wrapper_never_supplies_structural_dead_stop_inputs_for_a_draft_family(
    tmp_path: Path,
) -> None:
    """A DRAFT_NOT_REGISTERED manifest (pm_us_crh_exit_v4) is a valid
    `--family` id (B6: its own `family_id` matches the filename) but must
    never receive the structural-dead-stop inputs -- generalising to
    "REGISTERED, venue=polymarket_us" must not silently widen to every
    manifest on disk."""
    capture = tmp_path / "argv_capture.txt"
    stub = tmp_path / "stub_python.sh"
    stub.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "{capture}"\nexit 0\n')
    stub.chmod(0o755)
    result = _run_wrapper(
        ["pm_us_crh_exit_v4"],
        tmp_path,
        stub_python=stub,
        set_state_db=True,
    )
    assert result.returncode == 0, result.stderr
    argv_lines = capture.read_text().splitlines()
    assert "--covered-listed-station-days" not in argv_lines
    assert "--fill-source" not in argv_lines
    assert "--fill-since-climate-day" not in argv_lines


def test_wrapper_never_supplies_structural_dead_stop_inputs_for_a_non_polymarket_us_family(
    tmp_path: Path,
) -> None:
    """kalshi_crh_v1 is currently DRAFT_NOT_REGISTERED (parked, see
    test_kalshi_crh_unit_pair_is_parked_off_main) but even a hypothetically
    REGISTERED non-polymarket_us manifest must never get these inputs --
    the venue check is a second, independent gate, not a byproduct of the
    status check alone."""
    capture = tmp_path / "argv_capture.txt"
    stub = tmp_path / "stub_python.sh"
    stub.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "{capture}"\nexit 0\n')
    stub.chmod(0o755)
    result = _run_wrapper(
        ["kalshi_crh_v1"],
        tmp_path,
        stub_python=stub,
        set_state_db=True,
    )
    assert result.returncode == 0, result.stderr
    argv_lines = capture.read_text().splitlines()
    assert "--covered-listed-station-days" not in argv_lines
    assert "--fill-source" not in argv_lines
    assert "--fill-since-climate-day" not in argv_lines


def test_wrapper_logs_which_structural_dead_stop_inputs_were_supplied_per_family(
    tmp_path: Path,
) -> None:
    """SD-1/L-38: the wrapper must log, per family, which structural-dead
    stop inputs it supplied (or that it skipped them and why) -- so a
    `journalctl`/`family_tally_v2.log` read tells a reader which families
    are actually evaluable without re-deriving it from the argv."""
    stub = tmp_path / "stub_python.sh"
    stub.write_text('#!/usr/bin/env bash\nexit 0\n')
    stub.chmod(0o755)
    out_dir = tmp_path / "derived"
    _write_counter_json(tmp_path, count=17, fetch_start="2026-09-05")

    cont_result = _run_wrapper(
        ["pm_us_crh_cont"], tmp_path, stub_python=stub, write_counter_json=False
    )
    assert cont_result.returncode == 0, cont_result.stderr
    cont_log = (out_dir / "family_tally_v2.log").read_text()
    assert "pm_us_crh_cont" in cont_log
    assert "covered-listed-station-days=17" in cont_log
    assert "fill-since-climate-day=2026-09-12" in cont_log

    draft_result = _run_wrapper(["pm_us_crh_exit_v4"], tmp_path, stub_python=stub)
    assert draft_result.returncode == 0, draft_result.stderr
    draft_log = (out_dir / "family_tally_v2.log").read_text()
    assert "pm_us_crh_exit_v4" in draft_log
    assert "SKIPPED" in draft_log
    assert "DRAFT_NOT_REGISTERED" in draft_log


def test_kalshi_crh_unit_pair_is_parked_off_main(tmp_path: Path) -> None:
    # breezy-kalshi-crh-tally.{service,timer} moved to wip/kalshi-s4-registry
    # per the 2026-09-04 operator priority (PM-only until PM is working).
    # The manifest itself still exists on disk, so the wrapper must keep
    # listing kalshi_crh_v1 as a valid family id even with no unit for it.
    assert not (_SYSTEMD_DIR / "breezy-kalshi-crh-tally.service").exists()
    assert not (_SYSTEMD_DIR / "breezy-kalshi-crh-tally.timer").exists()
    assert "kalshi_crh_v1" in _valid_family_ids()
