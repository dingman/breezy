"""Spawn seam: a child launched through the supervisor's ``spawn_node`` with an
operator environment that lacks the monthly cap refuses to mint the order
submission permit, before any dispatch.

The production supervisor is untouched. The child is a stub executable that
runs the REAL ``OrderSubmissionPermit.issue`` and only then writes a
``dispatched`` sentinel. The environment is parsed from a synthetic operator
file built at runtime from the shipped inventory (this module names no control
and assigns no value to one by literal).
"""

from __future__ import annotations

import os
import stat
import sys
import textwrap
import time
from pathlib import Path
from typing import Final

import pytest

from breezy.adapters.polymarket_us.operator_controls import (
    MAX_MONTHLY_BUDGET_USD_ENV_VAR,
    OPERATOR_RESERVED_CONTROL_ENV_VARS,
)
from breezy.runtime.trade_supervisor import spawn_node
from breezy.runtime.trade_supervisor_core import PERMIT_NOT_ISSUED_MARKER

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXIT_REFUSED: Final[int] = 2
WAIT_S: Final[float] = 60.0

_STUB: Final[str] = textwrap.dedent(
    """\
    #!{python}
    import sys, time
    from dataclasses import dataclass
    from pathlib import Path
    from breezy.adapters.polymarket_us.safety import issue_live_trading_permit
    from breezy.runtime.order_enablement import (
        OrderSubmissionRefused,
        OrderSubmissionPermit,
    )

    class Clock:
        def timestamp_ns(self):
            return time.time_ns()

    @dataclass(frozen=True)
    class Settings:
        orders_enabled_requested: bool = True
        sending_family_id: str = "pm_us_crh_v2"
        live_observations: bool = True

    clock = Clock()
    try:
        OrderSubmissionPermit.issue(
            settings=Settings(),
            live_trading_permit=issue_live_trading_permit(clock=clock),
            clock=clock,
        )
    except OrderSubmissionRefused as exc:
        print("{marker}", type(exc).__name__)
        sys.exit({refused})
    Path(sys.argv[0] + ".dispatched").write_text("x")
    """
)


def _operator_file_env_without_the_monthly_cap(path: Path) -> dict[str, str]:
    kept = [n for n in OPERATOR_RESERVED_CONTROL_ENV_VARS if n != MAX_MONTHLY_BUDGET_USD_ENV_VAR]
    lines = [f"{name}=1" for name in kept]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)
    parsed: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        parsed[key] = value
    return parsed


def test_child_without_the_monthly_cap_refuses_before_any_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_polymarket_us_permit_issuance import enable_operator_gate

    enable_operator_gate(monkeypatch)
    gate = {k: v for k, v in os.environ.items() if k not in OPERATOR_RESERVED_CONTROL_ENV_VARS}
    env = {**gate, **_operator_file_env_without_the_monthly_cap(tmp_path / "operator.env")}
    assert MAX_MONTHLY_BUDGET_USD_ENV_VAR not in env

    stub = tmp_path / "node_stub.py"
    stub.write_text(
        _STUB.format(python=sys.executable, marker=PERMIT_NOT_ISSUED_MARKER, refused=EXIT_REFUSED),
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    log_path = tmp_path / "node.log"

    proc = spawn_node(node_bin=stub, repo_root=REPO_ROOT, env=env, log_path=log_path)
    deadline = time.monotonic() + WAIT_S
    while proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert proc.poll() == EXIT_REFUSED, log_path.read_text(encoding="utf-8")
    log_text = log_path.read_text(encoding="utf-8")
    assert PERMIT_NOT_ISSUED_MARKER in log_text
    assert "OperatorCapsNotConfiguredError" in log_text
    assert not Path(str(stub) + ".dispatched").exists()
