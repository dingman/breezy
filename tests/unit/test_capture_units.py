"""AUT-1 WP3 step 1 (r11, GH1): the bound constants have ONE source.

Step 2 adds the unit-file cases; no unit file is edited or read here.
"""

from __future__ import annotations

import ast
import math
from pathlib import Path

from breezy.adapters.polymarket_us import recorder_watchdog as rw
from breezy.runtime import node_config

BANNED_LITERALS = {4200, 4362, 4500, 4662, 4680}


def test_bound_constants_single_source() -> None:
    base = rw.UNIT_TIMEOUT_START_SEC
    expected_start = (
        base
        + node_config.QUOTE_TAPE_EMPTY_DISCOVERY_RETRY_SECS
        + rw.DISCOVERING_GRACE_S
        + rw.CONNECT_BUDGET_S
        + rw.START_EXTEND_S
    )
    assert node_config.QUOTE_TAPE_MAX_START_SECS == expected_start == 4500
    assert node_config.QUOTE_TAPE_MAX_START_SECS == node_config.recorder_max_start_s(base)
    total = rw.UNIT_TIMEOUT_STOP_SEC + rw.STOP_HOOK_BOUND_S + expected_start + rw.ROTATE_MARGIN_S
    assert total == 4662
    assert node_config.QUOTE_TAPE_ROTATE_TIMEOUT_START_SECS == math.ceil(total / 60) * 60 == 4680
    assert node_config.QUOTE_TAPE_ROTATE_TIMEOUT_START_SECS == node_config.rotate_timeout_start_s(
        node_config.QUOTE_TAPE_MAX_START_SECS
    )
    # The pinger's own extension window is the same parts: it can never grant past the budget.
    assert (
        rw.UNIT_TIMEOUT_START_SEC + rw.extension_window_s() + rw.START_EXTEND_S
        == node_config.QUOTE_TAPE_MAX_START_SECS
    )


def test_a_raised_base_moves_both_constants_together() -> None:
    assert node_config.recorder_max_start_s(240) == 4560
    assert node_config.rotate_timeout_start_s(4560) == 4740


def test_no_module_carries_a_bound_literal() -> None:
    """The derived numbers appear nowhere as literals: they are computed, in one place each."""
    for module in (node_config, rw):
        tree = ast.parse(Path(str(module.__file__)).read_text())
        literals = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, int)
        }
        assert not literals & BANNED_LITERALS, module.__name__
