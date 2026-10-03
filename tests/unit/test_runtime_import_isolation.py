"""NOTIFIER-IMPORT-ISOLATION: ``breezy/runtime/__init__.py`` must be import-free.

`docs/plans/backlog/EDGE_2026-09-27/NOTIFIER-IMPORT-ISOLATION_plan_r1_2026-09-27.md`
and its `..._plan_r2_delta_2026-09-27.md` (binding, including the r3
amendments). **The gap this closes.** `breezy-study-failed` -- see
`study_failure_notifier.py`'s own docstring, "a detector without delivery is
not a control" -- is the LAST line of alert delivery for a failed study
unit. Importing it used to run `breezy/runtime/__init__.py`, which eagerly
imported `composition`, and that loaded `nautilus_trader.live.node`. So a
broken Nautilus install -- exactly the kind of fault that can make a study
fail in the first place -- also silently killed the alert that was supposed
to report it. D-1 (r2) picked deletion over a lazy facade: there were zero
callers of the package's re-exported names.

**Stage 0 (D-2 + R3-1), run once, ahead of the fix.** A throwaway `grimp`
script built the Breezy + `scripts/` + `nautilus_trader` import graph, added
synthetic ``module -> ancestor package`` edges (grimp does not model that
importing a submodule runs its ancestors' ``__init__.py`` first -- the false
negative R3-1 exists to fix), and confirmed the positive control:
``breezy.runtime.study_failure_notifier`` reaches ``nautilus_trader.live.node``
at HEAD. It then compared, for every ``[project.scripts]`` entry, every
`deploy/systemd/` ``ExecStart`` module, and every ``scripts/**/*.py`` that
imports `breezy.runtime` (29 entries total), the set of `register_arrow(`
modules reachable (i) on the graph as-is and (ii) with the
``breezy.runtime -> {bootstrap_witness, composition, health, logging_bridge,
node_config, settings}`` edges removed (simulating this import-free
`__init__.py`). Every entry reached the identical set in both graphs -- zero
losses -- corroborated by a fresh-child `sys.modules` snapshot per entry
(a subset of the static result in every case, as expected: grimp counts
function-local imports the snapshot can only see after they execute). This
matches the r3 amendment's own finding that every Breezy `register_arrow`
call sits at module scope in the class's own defining module, so any caller
holding the class has already registered it. **Consequence: no T8-n tests
are needed** -- there is no entry to add an explicit import to.

**Why the assertions below only ever check `sys.modules` in a FRESH
subprocess.** This interpreter's own `sys.modules` already carries whatever
earlier tests in this session imported (including `nautilus_trader` from
unrelated fixtures) -- only a clean child process can prove an import graph
is actually light.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from typing import Final

import pytest

from tests.support.entry_points import (
    REPO_ROOT,
    RUNTIME_INIT_PATH,
    _entry_modules_from_pyproject_scripts,
    _entry_modules_from_scripts_importing,
    _entry_modules_from_systemd,
)

#: The Stage 0 entry set (D-2 + R3-2), reproduced here so T9 is
#: self-documenting: every `[project.scripts]` entry (`pyproject.toml:306-381`,
#: excluding `breezy-clear-family-halt`/`breezy-set-family-halt`, which live in
#: `breezy.strategy` and never import `breezy.runtime` -- `runtime` may not
#: import `strategy`, per the layers contract), every module named in a
#: `deploy/systemd/` `ExecStart` that is a Python module rather than a shell
#: wrapper or `systemctl` call, and every `scripts/**/*.py` that imports
#: `breezy.runtime`.
STAGE0_ENTRY_MODULES: Final[tuple[str, ...]] = (
    "breezy",
    "breezy.runtime.quote_tape_cli",
    "breezy.runtime.quote_tape_preflight_cli",
    "breezy.app.trade",
    "breezy.runtime.quote_tape_ingest_cli",
    "breezy.runtime.clear_submit_intent_cli",
    "breezy.runtime.mark_no_side_position_captured_cli",
    "breezy.runtime.trade_supervisor",
    "breezy.runtime.check_alerts_cli",
    "breezy.runtime.study_failure_notifier",
    "scripts.analysis.discovery_venue_pull",
    "scripts.venue.fee_drift_evidence_pull",
    "scripts.analysis.station_candidate_register",
    "scripts.analysis.cli_basis_offer_gate_scan",
    "scripts.analysis.family_tally_v2",
    "scripts.analysis.score_live_trials",
    "scripts.analysis.hypothesis_triage",
    "scripts.analysis.live_family_tally",
    "scripts.analysis.current_rung_hold_exit_window_study",
    "scripts.analysis.decision_funnel_daily_digest",
    "scripts.analysis.current_rung_hold_paper_replay",
    "scripts.analysis.portfolio_roi_report",
    "scripts.analysis.replay_daily_runner",
    "scripts.archive.iem_mos_freshness_check",
    "scripts.analysis.weather_strategy_backtest_lib",
    "scripts.analysis.asos_cache_freshness_check",
    # `breezy-clear-family-halt` / `breezy-set-family-halt` (`breezy.strategy.
    # current_rung_hold.{clear,set}_family_halt_cli`) are `[project.scripts]`
    # entries too, but Stage 0 confirmed they never import `breezy.runtime`
    # (the layers contract forbids it), so a fresh-process smoke import is
    # still a meaningful T9 case for them even though they cannot touch this
    # package.
    "breezy.strategy.current_rung_hold.clear_family_halt_cli",
    "breezy.strategy.current_rung_hold.set_family_halt_cli",
    # `deploy/systemd/{family-tally-v2,live-tally,score-live-trials}-run.sh`
    # all invoke `"$PY" -m breezy.runtime.exec_state_db_path --check`, and
    # `family-tally-v2-run.sh` additionally invokes `"$PY" -m
    # breezy.runtime.structural_pin_guard`. Both were missing from this list
    # (independent review finding, NOTIFIER-IMPORT-ISOLATION) despite being
    # real `-m` entry points reachable from a deployed wrapper script.
    "breezy.runtime.exec_state_db_path",
    "breezy.runtime.structural_pin_guard",
    # SL-13p A-5 (2026-09-29): the shadow-parity harness and its pure batch
    # sibling both import `breezy.runtime` (the former via
    # `breezy.runtime.backtest_harness`, the latter via
    # `breezy.runtime.trade_supervisor_core.LAUNCH_UTC`), so source (c)
    # picks both up -- tracked here rather than excluded, since neither is
    # known to be unimportable under Stage 0.
    "scripts.analysis.nbp_market_comparison",
    "scripts.analysis.nbp_shadow_parity",
    "scripts.analysis.nbp_shadow_parity_pure",
    # SL-15: the NBP learning nightly imports `breezy.runtime.health` for alert
    # delivery, so it is a covered Stage 0 entry rather than an exclusion.
    "scripts.analysis.nbp_learning_nightly",
    # R1.6: `quote_tape_gaps` moved from `breezy.persistence` to
    # `breezy.runtime`, so `structural_dead_stop` now imports `breezy.runtime`
    # and source (c) picks it up; tracked, not excluded.
    "scripts.analysis.structural_dead_stop",
)

#: Entries that WOULD be required by `test_entry_module_list_covers_every_
#: entry_point`'s derivation below but are deliberately not tracked in
#: `STAGE0_ENTRY_MODULES`. Empty today -- Stage 0 plus this review found no
#: entry that needs the escape hatch -- but the mechanism must exist so a
#: future deliberate exclusion is a one-line, commented, test-asserted
#: decision rather than a silent omission.
STAGE0_EXCLUDED_ENTRY_MODULES: Final[frozenset[str]] = frozenset(
    {
        # Tape seam module. It is not importable standalone as
        # `scripts.analysis.tape_instruments`: it does a bare
        # `from weather_strategy_backtest_lib import ...` that resolves only
        # after a `sys.path.insert(0, <scripts/analysis>)`. Its import isolation
        # is covered through `current_rung_hold_paper_replay` (in the tuple
        # above) and by `test_tape_instruments_import_isolation.py`.
        "scripts.analysis.tape_instruments",
    }
)


# ---------------------------------------------------------------------------
# Meta-test (independent review finding, MEDIUM): STAGE0_ENTRY_MODULES is a
# hard-coded tuple, so a newly added entry point could go untested without
# anyone noticing. This derives the entry set FRESH, at test time, from the
# same three sources Stage 0 used, and pins STAGE0_ENTRY_MODULES against it.
# ---------------------------------------------------------------------------


def test_entry_module_list_covers_every_entry_point() -> None:
    """Never RED at HEAD once green -- this is the drift guard. RED proof
    (both confirmed by hand for this fix): (1) deleting any single entry
    from `STAGE0_ENTRY_MODULES` makes this fail, naming that entry; (2)
    before `breezy.runtime.exec_state_db_path` /
    `breezy.runtime.structural_pin_guard` were added to the tuple, this
    failed naming exactly those two -- they are real `-m` entries in the
    `deploy/systemd/*-run.sh` wrappers (source (b)) that the hard-coded
    tuple had never picked up.
    """
    required = (
        _entry_modules_from_pyproject_scripts()
        | _entry_modules_from_systemd()
        | _entry_modules_from_scripts_importing("breezy.runtime")
    )
    tracked = set(STAGE0_ENTRY_MODULES)

    assert STAGE0_EXCLUDED_ENTRY_MODULES <= required, (
        "STAGE0_EXCLUDED_ENTRY_MODULES contains an entry that no longer "
        "derives from pyproject.toml/deploy/systemd/scripts -- remove it: "
        f"{sorted(STAGE0_EXCLUDED_ENTRY_MODULES - required)}"
    )

    missing = (required - STAGE0_EXCLUDED_ENTRY_MODULES) - tracked
    assert not missing, (
        "entry point(s) not covered by STAGE0_ENTRY_MODULES -- add each to "
        "the tuple, or, if deliberately untested, to "
        f"STAGE0_EXCLUDED_ENTRY_MODULES with a comment explaining why: {sorted(missing)}"
    )

#: Prepended to every T2/T3 child script (D-3). Installs a `find_spec`
#: finder -- `find_module` no longer exists on Python 3.13
#: (`pyproject.toml:9,222`) -- that raises `ImportError` for `nautilus_trader`
#: and every dotted name under it, records each blocked attempt, and then
#: exercises the POSITIVE CONTROL required by D-3 step 3: `import
#: nautilus_trader` must itself raise in this same child, proving the finder
#: is actually installed and actually intercepting, not merely present.
_FINDER_PREAMBLE = """\
import sys
import importlib.abc


class _BlockNautilus(importlib.abc.MetaPathFinder):
    blocked = []

    def find_spec(self, fullname, path, target=None):
        if fullname == "nautilus_trader" or fullname.startswith("nautilus_trader."):
            _BlockNautilus.blocked.append(fullname)
            raise ImportError(f"NOTIFIER-IMPORT-ISOLATION test block: {fullname}")
        return None


sys.meta_path.insert(0, _BlockNautilus())

try:
    import nautilus_trader  # noqa: F401
    print("POSITIVE_CONTROL_FAILED: import nautilus_trader did not raise")
except ImportError:
    pass
"""


def _run_child(script: str, *, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    """Run `script` in a fresh interpreter. Inherits the parent's environment
    (including `PYTHONPATH` and, under `run_tests_no_egress.sh`, the no-egress
    namespace attestation) -- mirrors `test_study_failure_alert.py`'s own
    `test_importing_the_notifier_never_pulls_in_the_ingest_cli` convention.
    """
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _assert_positive_control(result: subprocess.CompletedProcess[str]) -> None:
    """Proves the `_BlockNautilus` meta-path finder installed by
    `_FINDER_PREAMBLE` is actually present and actually intercepting in this
    child -- not that the notifier's own import chain would otherwise reach
    Nautilus without it. That absence-vs-presence fact is T1's job
    (`test_notifier_import_never_loads_nautilus`), not this helper's.
    """
    combined = result.stdout + result.stderr
    assert "POSITIVE_CONTROL_FAILED" not in combined, combined
    assert "BLOCKED=" in result.stdout, combined
    blocked_line = next(line for line in result.stdout.splitlines() if line.startswith("BLOCKED="))
    assert "nautilus_trader" in blocked_line, blocked_line


# ---------------------------------------------------------------------------
# T1 / T4: bare imports never load Nautilus (no finder needed -- these prove
# the ABSENCE of the eager chain, not survival of a blocked one).
# ---------------------------------------------------------------------------


def test_notifier_import_never_loads_nautilus() -> None:
    """T1. RED at HEAD because `breezy/runtime/__init__.py` eagerly imports
    `composition`, which imports `nautilus_trader.live.node` -- so importing
    the notifier alone already loads Nautilus.
    """
    script = (
        "import sys\n"
        "import breezy.runtime.study_failure_notifier\n"
        "nautilus_keys = sorted(\n"
        "    m for m in sys.modules\n"
        "    if m == 'nautilus_trader' or m.startswith('nautilus_trader.')\n"
        ")\n"
        "assert not nautilus_keys, nautilus_keys\n"
        "print('OK')\n"
    )
    result = _run_child(script)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_bare_package_import_is_nautilus_free() -> None:
    """T4. RED at HEAD for the same reason as T1: the init is eager."""
    script = (
        "import sys\n"
        "import breezy.runtime\n"
        "nautilus_keys = sorted(\n"
        "    m for m in sys.modules\n"
        "    if m == 'nautilus_trader' or m.startswith('nautilus_trader.')\n"
        ")\n"
        "assert not nautilus_keys, nautilus_keys\n"
        "print('OK')\n"
    )
    result = _run_child(script)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


# ---------------------------------------------------------------------------
# T7: the AST pin. No Read/import needed to check this -- source inspection.
# ---------------------------------------------------------------------------


def test_runtime_init_has_no_import_nodes() -> None:
    """T7. RED at HEAD: the current init has 6 `ImportFrom` nodes (the eager
    re-export block). An AST pin, not a substring grep, so a `# import` in a
    docstring or comment can never trip it and a `__import__(...)` call
    (which this pin does not catch) is a separate concern from the
    `Import`/`ImportFrom` node shape this module must never contain again.
    """
    source = RUNTIME_INIT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(RUNTIME_INIT_PATH))
    import_nodes = [
        node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert import_nodes == [], [ast.dump(node) for node in import_nodes]


# ---------------------------------------------------------------------------
# T2 / T3 (D-3): survive with Nautilus BLOCKED, not merely absent.
# ---------------------------------------------------------------------------


def test_notifier_sends_when_nautilus_import_fails() -> None:
    """T2. RED at HEAD: `import breezy.runtime.study_failure_notifier` raises
    `ImportError` (the blocked package init), so nothing is sent.
    """
    body = """
import breezy.runtime.study_failure_notifier as _mod

_sent = []


class _RecordingSink:
    def emit(self, payload):
        _sent.append(payload)


exit_code = _mod.notify_study_failed(
    ["--unit", "breezy-example-study.service"],
    sink_factory=lambda env: _RecordingSink(),
    cause_reader=lambda unit: "",
)
assert exit_code == 0, exit_code
assert len(_sent) == 1, _sent
assert _sent[0].event == _mod.STUDY_FAILED_ALERT_EVENT, _sent[0].event
assert _sent[0].severity == _mod.STUDY_FAILED_ALERT_SEVERITY, _sent[0].severity
print("BLOCKED=" + repr(sorted(set(_BlockNautilus.blocked))))
print("OK")
"""
    result = _run_child(_FINDER_PREAMBLE + body)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout
    _assert_positive_control(result)


def test_webhook_transport_resolves_without_nautilus() -> None:
    """T3. RED at HEAD: the package import itself fails before
    `resolve_alert_sink` can be reached. r3's T3 detail: set the webhook env
    var to `https://example.invalid/x` and assert `emit` is never called --
    this proves resolution alone never dials out, whether or not Nautilus is
    present.
    """
    body = """
import os

from breezy.runtime.health import (
    ALERT_WEBHOOK_URL_ENV_VAR,
    TeeAlertSink,
    WebhookAlertSink,
    resolve_alert_sink,
)

os.environ[ALERT_WEBHOOK_URL_ENV_VAR] = "https://example.invalid/x"

_emit_calls = []
_orig_emit = WebhookAlertSink.emit


def _spy_emit(self, payload):
    _emit_calls.append(payload)
    return _orig_emit(self, payload)


WebhookAlertSink.emit = _spy_emit

sink = resolve_alert_sink()
assert isinstance(sink, TeeAlertSink), type(sink)
assert any(isinstance(branch, WebhookAlertSink) for branch in sink.sinks), sink.sinks
assert _emit_calls == [], _emit_calls
print("BLOCKED=" + repr(sorted(set(_BlockNautilus.blocked))))
print("OK")
"""
    result = _run_child(_FINDER_PREAMBLE + body)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout
    _assert_positive_control(result)


# ---------------------------------------------------------------------------
# T9 (R3-2): fresh-process import smoke, one per Stage 0 entry. Never RED at
# HEAD (nothing is broken yet) -- this is the regression guard for any future
# entry that comes to depend on the eager chain. Mutant M-e (a module-scope
# `breezy.runtime.health` import added to `nws_actor`) is structurally inert
# once D-1 is applied (there is no eager chain left for it to depend on); T7
# (`test_runtime_init_has_no_import_nodes`, the AST pin on `__init__.py`) is
# the operative guard against it, not this test.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entry_module", STAGE0_ENTRY_MODULES)
def test_entry_module_imports_cleanly(entry_module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {entry_module}"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
