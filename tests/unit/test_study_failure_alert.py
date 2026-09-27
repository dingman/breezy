"""AUD-15a -- ``OnFailure=`` alert path for every study unit.

`docs/plans/backlog/AUDIT_2026-09-21/AUD-15-failing-study-units-fix-or-retire-and-alert.md`
§7 15a steps 2-4. No unit in `deploy/systemd/` declared `OnFailure=`, so a
study that timed out, was OOM-killed, or exited non-zero landed in `failed`
and alerted nobody. This module pins:

1. every `.service` file with a sibling `.timer` declares
   `OnFailure=breezy-study-failed@%n.service` (except the notifier's own
   template unit -- an alert-loop guard);
2. the notifier template unit itself declares no `OnFailure=`, no
   `Restart=`, and no `EnvironmentFile=`;
3. the notifier's alert payload is a fixed-shape WARN with a closed-enum
   `detail` that never carries the failing unit's name (that travels on the
   plain log line instead).
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

from breezy.runtime.health import (
    AlertPayload,
    LoggingAlertSink,
    TeeAlertSink,
    WebhookAlertSink,
    resolve_alert_sink,
)
from breezy.runtime.quote_tape_exit_codes import EXIT_DEFERRAL_STALLED, PROGRAM
from breezy.runtime.study_failure_notifier import (
    STUDY_FAILED_ALERT_EVENT,
    STUDY_FAILED_ALERT_SEVERITY,
    STUDY_FAILED_ALERT_SITE,
    StudyFailedDetail,
    notify_study_failed,
)

_QUOTE_TAPE_INGEST_UNIT: Final[str] = f"{PROGRAM}.service"

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_DEPLOY_DIR: Final[Path] = _REPO_ROOT / "deploy" / "systemd"

_NOTIFIER_TEMPLATE_UNIT: Final[str] = "breezy-study-failed@.service"
_ONFAILURE_LINE: Final[str] = "OnFailure=breezy-study-failed@%n.service"

#: AUD-15 amendment (2026-09-22): the ONE alert env file a study-adjacent
#: unit may declare -- never `breezy-trade.env`/`polymarket.env`/
#: `operator.env`, which carry a venue credential or an operator-reserved
#: value this unit must never hold.
_PERMITTED_ENV_FILES: Final[frozenset[str]] = frozenset({"%h/.config/breezy/alerts.env"})
_FORBIDDEN_ENV_SUBSTRINGS: Final[tuple[str, ...]] = (
    "breezy-trade.env",
    "polymarket.env",
    "operator.env",
)


def _service_files_with_a_sibling_timer() -> tuple[Path, ...]:
    """Every `.service` file in `deploy/systemd/` that has a same-stem
    `.timer` sibling -- scanning the TREE, not a frozen list, so a future
    study unit added (or a retired one removed) without updating this test
    stays correctly covered either way (AUD-15 §9's own residual note)."""
    services = []
    for path in sorted(_DEPLOY_DIR.glob("*.service")):
        timer_path = _DEPLOY_DIR / f"{path.stem}.timer"
        if timer_path.is_file():
            services.append(path)
    return tuple(services)


def test_every_study_unit_declares_an_onfailure_handler() -> None:
    services = _service_files_with_a_sibling_timer()
    assert services, "expected at least one study unit with a sibling timer"
    missing = [
        path.name
        for path in services
        if path.name != _NOTIFIER_TEMPLATE_UNIT
        and _ONFAILURE_LINE not in path.read_text().splitlines()
    ]
    assert missing == [], f"units missing {_ONFAILURE_LINE!r}: {missing}"


def _directive_lines(text: str) -> list[str]:
    """Actual `Directive=value` lines only -- never a comment that merely
    mentions the directive name in prose (mirrors
    `test_analysis_units_memory_capped.py::_directive_value`'s own
    comment-skipping convention)."""
    return [line.strip() for line in text.splitlines() if not line.strip().startswith("#")]


def test_the_notifier_declares_no_onfailure_and_no_restart() -> None:
    path = _DEPLOY_DIR / _NOTIFIER_TEMPLATE_UNIT
    assert path.is_file(), f"{_NOTIFIER_TEMPLATE_UNIT} does not exist"
    lines = _directive_lines(path.read_text())
    assert not any(line.startswith("OnFailure=") for line in lines), (
        "the notifier must not chain into itself (alert loop)"
    )
    assert not any(line.startswith("Restart=") for line in lines)


def test_the_study_failure_notifier_declares_only_the_allowlisted_alert_env_file() -> None:
    """AUD-15 amendment (2026-09-22): REPLACES
    `test_the_study_failure_notifier_carries_no_environmentfile_and_no_credential`.

    This is a RE-SCOPE, not a weakening: the protected property was never
    literally "no EnvironmentFile=" -- it is "no VENUE credential, no
    operator-reserved value, no node/exec env on a study unit". The plan's
    original text ("No EnvironmentFile=, no credential") conflated the
    mechanism with the property because, at the time it was written, no
    non-venue shared env file existed to load instead. It does now
    (`~/.config/breezy/alerts.env`, a single key, `BREEZY_ALERT_WEBHOOK_URL`,
    never a credential) -- so the test is re-aimed at the actual invariant:
    exactly one `EnvironmentFile=` line, and it is the allowlisted one; the
    three forbidden substrings (venue/operator files) still assert absent,
    which is the property this test always existed to protect.
    """
    lines = _directive_lines((_DEPLOY_DIR / _NOTIFIER_TEMPLATE_UNIT).read_text())
    env_files = [
        line.removeprefix("EnvironmentFile=").lstrip("-")
        for line in lines
        if line.startswith("EnvironmentFile=")
    ]
    assert set(env_files) == _PERMITTED_ENV_FILES
    assert not any(
        forbidden in env_file for env_file in env_files for forbidden in _FORBIDDEN_ENV_SUBSTRINGS
    )


def test_the_supervisor_unit_also_loads_the_shared_alert_env_file() -> None:
    """Single source of truth (AMENDMENT.md option B): the supervisor reads
    the SAME `alerts.env` the notifier and refresh units read, rather than
    keeping its own copy of the webhook URL in `breezy-trade.env`."""
    text = (_DEPLOY_DIR / "breezy-trade-supervisor.service").read_text()
    lines = _directive_lines(text)
    env_files = [
        line.removeprefix("EnvironmentFile=").lstrip("-")
        for line in lines
        if line.startswith("EnvironmentFile=")
    ]
    assert "%h/.config/breezy/alerts.env" in env_files


def test_the_alert_path_never_resolves_a_log_only_sink_under_the_units_declared_environment() -> (
    None
):
    """A unit test of `resolve_alert_sink` under the declared key name --
    it does NOT close the runtime gap (a study process could still run with
    no `alerts.env` on disk and silently downgrade); that is closed by
    `log_alert_egress_status` being called every run
    (`test_notify_study_failed_logs_alert_egress_status_before_resolving_the_sink`
    below) plus the deploy-time delivery check (README, §4d). This test only
    proves: IF the declared `EnvironmentFile=` key
    (`BREEZY_ALERT_WEBHOOK_URL`) is present in the process environment, THEN
    `resolve_alert_sink` returns a real `WebhookAlertSink`, never
    `LoggingAlertSink` -- i.e. the env-var NAME the unit declares is the one
    `resolve_alert_sink` actually reads."""
    env = {"BREEZY_ALERT_WEBHOOK_URL": "https://ntfy.sh/fake-topic-token"}

    sink = resolve_alert_sink(env)

    # `resolve_alert_sink` fans a configured webhook out to BOTH the local
    # log (the authoritative forensic record, WP-B0a) AND the webhook --
    # never EITHER/OR -- so the real assertion is that a WebhookAlertSink
    # branch is present, never that the sink IS bare LoggingAlertSink.
    assert not isinstance(sink, LoggingAlertSink)
    assert isinstance(sink, TeeAlertSink)
    assert any(isinstance(branch, WebhookAlertSink) for branch in sink.sinks)


def test_notify_study_failed_logs_alert_egress_status_before_resolving_the_sink(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AUD-15 amendment A-2: this is the runtime visibility leg -- a
    missing/empty `alerts.env` must leave a distinct journal line on every
    invocation of the notifier, not merely a silently-downgraded sink."""
    with caplog.at_level(logging.WARNING, logger="breezy.runtime.health"):
        exit_code = notify_study_failed(["--unit", "breezy-k1-daily.service"], env={})

    assert exit_code == 0
    assert any(
        "NO alert egress is configured" in record.getMessage() for record in caplog.records
    )


def test_the_notifier_alert_detail_is_a_fixed_enum_and_carries_no_unit_text() -> None:
    payloads: list[AlertPayload] = []

    class _RecordingSink:
        def emit(self, payload: AlertPayload) -> None:
            payloads.append(payload)

    def _sink_factory(_env: object) -> _RecordingSink:
        return _RecordingSink()

    exit_code = notify_study_failed(
        ["--unit", "breezy-k1-daily.service"],
        sink_factory=_sink_factory,
    )

    assert exit_code == 0
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload.severity == STUDY_FAILED_ALERT_SEVERITY == "WARN"
    assert payload.event == STUDY_FAILED_ALERT_EVENT
    assert payload.site == STUDY_FAILED_ALERT_SITE
    assert payload.detail == StudyFailedDetail.STUDY_UNIT_REACHED_FAILED_STATE.value
    assert "breezy-k1-daily" not in payload.detail
    assert ".service" not in payload.detail


def test_the_notifier_never_raises_on_a_missing_unit_argument() -> None:
    exit_code = notify_study_failed([], sink_factory=lambda _env: _RaisingSink())
    assert exit_code == 0


class _RaisingSink:
    def emit(self, payload: AlertPayload) -> None:  # pragma: no cover - defensive
        raise AssertionError("must not be called with no --unit")


def test_the_notifier_contains_a_sink_failure_and_still_exits_0() -> None:
    class _ExplodingSink:
        def emit(self, payload: AlertPayload) -> None:
            raise RuntimeError("sink is down")

    exit_code = notify_study_failed(
        ["--unit", "breezy-k1-daily.service"],
        sink_factory=lambda _env: _ExplodingSink(),
    )
    assert exit_code == 0


def test_importing_the_notifier_never_pulls_in_the_ingest_cli() -> None:
    """The notifier is the LAST line of alert delivery (module docstring's
    "Never a heavy import" note). A missing `pyarrow` wheel or a syntax
    error anywhere in `quote_tape_ingest_cli`'s own import chain --
    exactly the kind of fault that can make a study unit fail in the first
    place -- must never crash the notifier before it can send its alert
    (L-52). Run in a FRESH subprocess: `sys.modules` in-process already
    carries whatever earlier tests in this session imported, so only a
    clean interpreter proves the notifier's own import graph is light.

    NOT asserted here: that `nautilus_trader` itself is absent. That is
    `test_runtime_import_isolation.py::test_notifier_import_never_loads_nautilus`
    (T1)'s job -- it is the test that proves importing this notifier, package
    and all, leaves `sys.modules` free of `nautilus_trader*`
    (NOTIFIER-IMPORT-ISOLATION). `breezy/runtime/__init__.py` used to import
    `breezy.runtime.composition` eagerly, which pulled in
    `nautilus_trader.live.node` on ANY `breezy.runtime.*` import including
    this one; that package `__init__` is now import-free, so this test's own
    narrower assertion (the ingest CLI's absence) and T1's broader one (all of
    Nautilus) are both satisfied by the same fix.
    """
    script = (
        "import sys\n"
        "import breezy.runtime.study_failure_notifier\n"
        "assert 'breezy.runtime.quote_tape_ingest_cli' not in sys.modules, sorted(sys.modules)\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


# ---------------------------------------------------------------------------
# Cause-of-failure lookup (alertcause 2026-09-27): the notifier reads
# ExecMainStatus/Result via an injectable seam -- these tests never touch
# systemd, only fake the seam.
# ---------------------------------------------------------------------------


def _recording_sink_factory() -> tuple[list[AlertPayload], object]:
    payloads: list[AlertPayload] = []

    class _RecordingSink:
        def emit(self, payload: AlertPayload) -> None:
            payloads.append(payload)

    return payloads, (lambda _env: _RecordingSink())


def test_cause_lookup_names_the_exit_code_for_the_quote_tape_ingest_unit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    payloads, sink_factory = _recording_sink_factory()

    def _fake_cause_reader(unit: str) -> str:
        assert unit == _QUOTE_TAPE_INGEST_UNIT
        return f"ExecMainStatus={EXIT_DEFERRAL_STALLED}\nResult=exit-code\n"

    with caplog.at_level(logging.WARNING, logger="breezy.runtime.study_failure_notifier"):
        exit_code = notify_study_failed(
            ["--unit", _QUOTE_TAPE_INGEST_UNIT],
            sink_factory=sink_factory,
            cause_reader=_fake_cause_reader,
        )

    assert exit_code == 0
    assert len(payloads) == 1
    assert any(
        f"cause=exit-code exit={EXIT_DEFERRAL_STALLED} (DEFERRAL_STALLED)" in record.getMessage()
        for record in caplog.records
    )


def test_cause_lookup_has_no_named_mapping_for_a_non_ingest_unit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    payloads, sink_factory = _recording_sink_factory()

    def _fake_cause_reader(unit: str) -> str:
        return "ExecMainStatus=1\nResult=exit-code\n"

    with caplog.at_level(logging.WARNING, logger="breezy.runtime.study_failure_notifier"):
        exit_code = notify_study_failed(
            ["--unit", "breezy-mb-daily.service"],
            sink_factory=sink_factory,
            cause_reader=_fake_cause_reader,
        )

    assert exit_code == 0
    assert len(payloads) == 1
    messages = [record.getMessage() for record in caplog.records]
    assert any("cause=exit-code exit=1" in message for message in messages)
    assert not any("(" in message for message in messages if "cause=" in message)


def test_a_raising_cause_reader_still_sends_the_alert(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """L-52: a detector without delivery is not a control -- a broken cause
    probe must never suppress or delay the alert itself."""
    payloads, sink_factory = _recording_sink_factory()

    def _raising_cause_reader(unit: str) -> str:
        raise RuntimeError("no systemd user session")

    with caplog.at_level(logging.WARNING, logger="breezy.runtime.study_failure_notifier"):
        exit_code = notify_study_failed(
            ["--unit", _QUOTE_TAPE_INGEST_UNIT],
            sink_factory=sink_factory,
            cause_reader=_raising_cause_reader,
        )

    assert exit_code == 0
    assert len(payloads) == 1
    assert any("cause=unknown" in record.getMessage() for record in caplog.records)


def test_a_garbage_cause_reader_output_still_sends_the_alert(
    caplog: pytest.LogCaptureFixture,
) -> None:
    payloads, sink_factory = _recording_sink_factory()

    def _garbage_cause_reader(unit: str) -> str:
        return "not systemctl show output at all\nneither is this"

    with caplog.at_level(logging.WARNING, logger="breezy.runtime.study_failure_notifier"):
        exit_code = notify_study_failed(
            ["--unit", _QUOTE_TAPE_INGEST_UNIT],
            sink_factory=sink_factory,
            cause_reader=_garbage_cause_reader,
        )

    assert exit_code == 0
    assert len(payloads) == 1
    assert any("cause=unknown" in record.getMessage() for record in caplog.records)


def test_the_alert_payload_still_carries_no_unit_text_when_cause_is_present() -> None:
    """The cause text lands on the log line only -- `AlertPayload.detail`
    stays the fixed enum, matching
    `test_the_notifier_alert_detail_is_a_fixed_enum_and_carries_no_unit_text`
    above."""
    payloads, sink_factory = _recording_sink_factory()

    exit_code = notify_study_failed(
        ["--unit", _QUOTE_TAPE_INGEST_UNIT],
        sink_factory=sink_factory,
        cause_reader=lambda _unit: f"ExecMainStatus={EXIT_DEFERRAL_STALLED}\nResult=exit-code\n",
    )

    assert exit_code == 0
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload.detail == StudyFailedDetail.STUDY_UNIT_REACHED_FAILED_STATE.value
    assert "quote-tape" not in payload.detail
    assert "exit" not in payload.detail
