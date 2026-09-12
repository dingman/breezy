"""The ``breezy-alert-test`` console entrypoint (SP-6 A4).

An on-demand, single-shot way to prove the CURRENTLY configured alert sink
actually emits, without waiting for a real condition. Shaped on
``quote_tape_preflight_cli.py``'s ``run(argv, *, env, stdout) -> int``
idiom: never raises, injectable ``env``/``sink``/``stdout`` for tests.

**Exit 0 is NOT delivery proof.** ``emit_alert`` (``runtime/health.py``)
swallows every sink failure by design (it must never unwind into a poll
or boot path) -- exit 0 here means ``emit()`` was attempted and did not
itself raise past ``emit_alert``'s own containment, nothing more. The
captured receipt line (``breezy alert delivered ...``) is the observable
that something happened; for the webhook path, only the destination's own
response (pasted into the acceptance evidence doc, host redacted) settles
whether delivery actually occurred.

Never prints, logs, or echoes the webhook URL -- ``resolve_alert_sink``
already never surfaces it, and this module never reads
``BREEZY_ALERT_WEBHOOK_URL`` directly. Names no venue (C5): this command
is generic across every alert source, not specific to any one.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from typing import TextIO

from breezy.runtime.composition import _close_alert_sink
from breezy.runtime.health import (
    HEALTH_LOGGER_NAME,
    AlertPayload,
    AlertSink,
    LoggingAlertSink,
    emit_alert,
    resolve_alert_sink,
)
from breezy.runtime.logging_bridge import ensure_stderr_visible

__all__ = ["main", "run"]

PROGRAM = "breezy-alert-test"

EXIT_OK = 0
EXIT_NOT_CONFIGURED = 2

TEST_ALERT_EVENT = "ALERT_DELIVERY_TEST"
TEST_ALERT_SITE = "global"
TEST_ALERT_DETAIL = "alert delivery test"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROGRAM)
    parser.add_argument(
        "--require-webhook",
        action="store_true",
        help=(
            "exit 2 instead of 0 when no destination is configured "
            "(the resolved sink is LoggingAlertSink)"
        ),
    )
    return parser


def run(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    sink: AlertSink | None = None,
    stdout: TextIO | None = None,
) -> int:
    """Emit ONE INFO test alert through the resolved sink. Never raises."""
    out = sys.stdout if stdout is None else stdout
    active_env: Mapping[str, str] = env if env is not None else os.environ
    parser = _build_parser()
    try:
        namespace = parser.parse_args(list(argv) if argv is not None else [])
    except SystemExit:
        return EXIT_NOT_CONFIGURED

    # Boot-window visibility (A1's mechanism): this process has no bridge
    # and may have no handler at all otherwise -- without this call the
    # receipt below would be dropped, making the acceptance artefact this
    # command exists to produce unobtainable.
    ensure_stderr_visible(HEALTH_LOGGER_NAME)

    active_sink = sink if sink is not None else resolve_alert_sink(active_env)
    try:
        if namespace.require_webhook and isinstance(active_sink, LoggingAlertSink):
            print(
                f"{PROGRAM}: no webhook destination configured "
                "(BREEZY_ALERT_WEBHOOK_URL unset) and --require-webhook was given",
                file=out,
            )
            return EXIT_NOT_CONFIGURED
        emit_alert(
            active_sink,
            AlertPayload(
                severity="INFO",
                event=TEST_ALERT_EVENT,
                site=TEST_ALERT_SITE,
                detail=TEST_ALERT_DETAIL,
            ),
        )
        print(f"{PROGRAM}: test alert emitted (exit 0 is NOT delivery proof)", file=out)
        return EXIT_OK
    finally:
        _close_alert_sink(active_sink)


def main() -> int:
    """Console-script entrypoint. Returns the process exit code."""
    return run(sys.argv[1:], env=os.environ)


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess in tests
    raise SystemExit(main())
