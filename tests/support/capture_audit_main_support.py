"""Helpers for the audit ``_main`` tests (S3-R55: moved out of ``test_capture_audit.py``)."""

import os

import pytest

from breezy.analysis import capture_audit_cli as cli


@pytest.fixture(autouse=True)
def no_real_heal(monkeypatch: pytest.MonkeyPatch) -> None:
    """S3-R18: ``_main`` runs the heal duty, which reads the real recorder journal; here it is a
    no-op (the heal wiring is tested in ``test_capture_audit_cli.py``)."""
    monkeypatch.setattr(cli, "run_heal_duty", lambda *a, **k: 0)


def no_lock() -> int:
    """S3-R13: _main takes the studies lock by injection; a unit test never takes the real one."""
    return os.open(os.devnull, os.O_RDONLY | os.O_CLOEXEC)
