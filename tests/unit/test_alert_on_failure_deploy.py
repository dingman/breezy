"""RED/GREEN coverage for the `breezy-alert@.service` template + the three
parent units it is wired to (SP-6 A9, row 16).

The render helper substitutes systemd's own specifiers `{i, I, n, h, %}`
and FAILS on any other `%X` -- the same escape-sequence trap
`breezy-offer-gate-daily.service:55-65` documents, checked here against
the RENDERED string rather than trusting `systemd-analyze verify`'s own
exit code (measured: it returns 0 even for a directive it could not
parse). Idiom: `tests/unit/test_score_live_trials_deploy.py:24-40`.
Never invokes `curl` or `systemctl` -- text assertions only.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SYSTEMD_DIR = _REPO_ROOT / "deploy" / "systemd"

_TEMPLATE_UNIT = _SYSTEMD_DIR / "breezy-alert@.service"
_WRAPPER = _SYSTEMD_DIR / "alert-webhook-run.sh"
_PARENT_UNITS: dict[str, str] = {
    "breezy-trade-supervisor.service": "breezy-trade-supervisor.service",
    "breezy-quote-tape.service": "breezy-quote-tape.service",
    "breezy-quote-tape-ingest.service": "breezy-quote-tape-ingest.service",
}

_KNOWN_SPECIFIERS: dict[str, str] = {
    "i": "breezy-trade-supervisor.service",
    "I": "breezy/trade/supervisor.service",
    "n": "breezy-trade-supervisor.service",
    "h": "/home/jon",
}


def _render_specifiers(text: str, substitutions: dict[str, str]) -> str:
    """Emulate systemd's specifier expansion. Raises on any `%X` not in
    `substitutions` (and not the literal-percent escape `%%`)."""

    def _replace(match: re.Match[str]) -> str:
        spec = match.group(1)
        if spec == "%":
            return "%"
        if spec in substitutions:
            return substitutions[spec]
        raise ValueError(f"unhandled systemd specifier %{spec!r} in: {text!r}")

    return re.sub(r"%(.)", _replace, text)


def _exec_start_line(unit_text: str) -> str:
    for line in unit_text.splitlines():
        if line.startswith("ExecStart="):
            return line
    raise AssertionError("no ExecStart= line found")


def test_template_unit_contains_no_literal_url() -> None:
    text = _TEMPLATE_UNIT.read_text()
    assert not re.search(r"https?://", text)


def test_template_unit_never_passes_the_url_as_a_bare_argv_token() -> None:
    exec_line = _exec_start_line(_TEMPLATE_UNIT.read_text())
    assert "BREEZY_ALERT_WEBHOOK_URL" not in exec_line
    assert "$" not in exec_line


def test_named_units_declare_onfailure() -> None:
    for filename in _PARENT_UNITS:
        text = (_SYSTEMD_DIR / filename).read_text()
        assert "OnFailure=breezy-alert@%n.service" in text, filename


def test_ingest_unit_gains_no_environment_file() -> None:
    text = (_SYSTEMD_DIR / "breezy-quote-tape-ingest.service").read_text()
    directive_lines = [line for line in text.splitlines() if line.startswith("EnvironmentFile")]
    assert directive_lines == []


def test_execstart_is_a_single_plain_command_with_no_shell() -> None:
    exec_line = _exec_start_line(_TEMPLATE_UNIT.read_text())
    for forbidden in ("bash -c", "sh -c", "$(", "`", ";", "|", "&&"):
        assert forbidden not in exec_line, (forbidden, exec_line)


def test_execstart_survives_rendered_specifier_expansion() -> None:
    exec_line = _exec_start_line(_TEMPLATE_UNIT.read_text())
    _, _, command = exec_line.partition("=")

    rendered = _render_specifiers(command, _KNOWN_SPECIFIERS)  # must not raise

    # AM-6: %i, not %I -- the rendered argument equals the parent unit's
    # OWN filename, never the `/`-unescaped %I form.
    assert rendered.endswith(_KNOWN_SPECIFIERS["i"])
    assert "breezy/trade/supervisor.service" not in rendered


def test_wrapper_script_is_executable_and_referenced_by_path() -> None:
    exec_line = _exec_start_line(_TEMPLATE_UNIT.read_text())
    assert "alert-webhook-run.sh" in exec_line
    assert _WRAPPER.stat().st_mode & 0o111  # some execute bit is set
