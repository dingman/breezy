from __future__ import annotations

import os
import sys

import pytest

from tests.support.bwrap_harness import run_raw_true

pytestmark = pytest.mark.bwrap_host


def test_phase2_witness_sees_phase_env_only() -> None:
    assert os.environ["BREEZY_BWRAP_HOST_PHASE"] == "1"
    assert "BREEZY_TEST_OS_EGRESS_BLOCK" not in os.environ


def test_phase2_witness_parent_has_not_loaded_refused_modules() -> None:
    loaded = [
        name
        for name in sys.modules
        if name in {"nautilus_trader", "breezy.adapters"}
        or name.startswith(("nautilus_trader.", "breezy.adapters."))
    ]
    assert loaded == []


def test_phase2_witness_children_use_bwrap_unshare_net() -> None:
    result = run_raw_true()
    assert result.returncode == 0, result.stderr
