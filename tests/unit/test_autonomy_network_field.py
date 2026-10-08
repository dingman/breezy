"""AUT-1 WP5 stage 3 (E-15, S3-R10..R12, S3-R38): the ``BwrapRow.network`` field.

Emission fails closed: ``--unshare-net`` is added unless the value is exactly ``"egress"``.
``validate_table`` refuses a non-``str`` value, an unknown value, ``none`` with ``resolves_dns``
and ``none`` on a fallback row. The three seam B selftest rows stay ``egress`` (S3-R11).
"""

from __future__ import annotations

import dataclasses
import inspect
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from breezy.runtime.autonomy_sandbox.binds import OpenedBind, OpenedBinds
from breezy.runtime.autonomy_sandbox.bwrap import build_bwrap_argv
from breezy.runtime.autonomy_sandbox.table import (
    AUTONOMY_BWRAP_TABLE,
    BwrapRow,
    SandboxRoots,
    TableError,
    validate_table,
)

SELFTEST = AUTONOMY_BWRAP_TABLE["breezy-autonomy-selftest"]
NOTIFY = AUTONOMY_BWRAP_TABLE["breezy-autonomy-selftest-notify"]
PROC = AUTONOMY_BWRAP_TABLE["breezy-autonomy-selftest-proc"]
STOP_HOOK = AUTONOMY_BWRAP_TABLE["breezy-quote-tape.stop-hook"]
CAPTURE_ROWS = (
    "breezy-capture-settlement",
    "breezy-capture-audit",
    "breezy-capture-live-proof",
)
ROOTS = SandboxRoots(
    home=Path("/home/u"),
    data_root=Path("/home/u/.local/share/breezy"),
    repo_root=Path("/home/u/repo"),
    python_prefix=Path("/home/u/py"),
    uid=1000,
    run_user=Path("/run/user/1000"),
)
UNSHARE_NET = "--unshare-net"


def _argv(row: BwrapRow) -> list[str]:
    binds = tuple(
        OpenedBind(rel, f"/home/u/.local/share/breezy/{rel}", 100 + i, 1, 100 + i)
        for i, rel in enumerate(row.binds)
    )
    return build_bwrap_argv(
        row,
        ("/usr/bin/true",),
        roots=ROOTS,
        opened=OpenedBinds(binds=binds, config_files=(), config_dirs=()),
        rebinds=(),
        environ={},
        cwd="/",
    )


def _table(row: BwrapRow) -> Mapping[str, BwrapRow]:
    return MappingProxyType({row.name: row})


def _refused(row: BwrapRow, match: str, **kwargs: Any) -> None:
    with pytest.raises(TableError, match=match):
        validate_table(_table(row), wrapper_line_only_units={}, **kwargs)


def _none_row(**changes: Any) -> BwrapRow:
    return dataclasses.replace(STOP_HOOK, **changes)


@pytest.mark.parametrize(
    ("value", "emitted"),
    [
        ("none", True),
        ("egress", False),
        ("None", True),
        ("EGRESS", True),
        ("", True),
        (" egress", True),
        ("egress ", True),
        (None, True),
        (0, True),
        (("egress",), True),
    ],
)
def test_unshare_net_unless_exactly_egress(value: Any, emitted: bool) -> None:
    """MUTATION M-EQNONE: emit iff ``== "none"`` leaves ``"None"`` and ``None`` with a network."""
    row = dataclasses.replace(SELFTEST, network=value)
    assert (UNSHARE_NET in _argv(row)) is emitted


def test_unshare_net_is_one_flag_not_a_prefix_of_the_command() -> None:
    argv = _argv(STOP_HOOK)
    assert argv.count(UNSHARE_NET) == 1
    assert argv.index(UNSHARE_NET) < argv.index("--")


@pytest.mark.parametrize("value", ["None", "NONE", "Egress", "", "host", "all", "none "])
def test_unknown_network_value_refused(value: str) -> None:
    """MUTATION M-CASE: accepting ``"None"`` (case-folded) is the only way this passes."""
    _refused(_none_row(network=value), "network")


@pytest.mark.parametrize("value", [None, 0, 1, True, b"none", ("none",), ["egress"], object()])
def test_non_str_network_value_refused(value: Any) -> None:
    """MUTATION (S3-R38): accept a non-``str`` network value."""
    _refused(_none_row(network=value), "network must be a str")


def test_network_none_with_resolves_dns_refused() -> None:
    """MUTATION M-DNS: drop the ``none`` + ``resolves_dns`` rule."""
    _refused(_none_row(resolves_dns=True), "resolves_dns")
    validate_table(
        _table(_none_row(resolves_dns=True, network="egress")), wrapper_line_only_units={}
    )


def test_network_none_fallback_row_refused() -> None:
    """MUTATION M-FALLBACK: a notifier-fallback row must keep its network (S3-R12)."""
    _refused(_none_row(notifier_fallback=True), "fallback")
    _refused(_none_row(), "fallback", fallback_rows=frozenset({STOP_HOOK.name}))
    validate_table(
        _table(_none_row(notifier_fallback=True, network="egress")), wrapper_line_only_units={}
    )
    validate_table(
        _table(_none_row(network="egress")),
        wrapper_line_only_units={},
        fallback_rows=frozenset({STOP_HOOK.name}),
    )


def test_fallback_rows_default_is_the_shipped_set() -> None:
    from breezy.runtime.autonomy_sandbox import table as table_module

    default = inspect.signature(validate_table).parameters["fallback_rows"].default
    assert default is table_module.NOTIFIER_FALLBACK_ROWS


def test_network_field_is_required_with_no_default() -> None:
    fields = {f.name: f for f in dataclasses.fields(BwrapRow)}
    assert fields["network"].default is dataclasses.MISSING
    assert fields["network"].default_factory is dataclasses.MISSING
    with pytest.raises(TypeError, match="network"):
        BwrapRow(  # type: ignore[call-arg]
            name="breezy-t",
            owner_plan="T",
            units=frozenset({"breezy-t.service"}),
            binds=("cache/t",),
            entry_modules=("x",),
            resolves_dns=False,
        )


def test_every_row_declares_network() -> None:
    expected: Sequence[tuple[BwrapRow, str]] = (
        (SELFTEST, "egress"),
        (NOTIFY, "egress"),
        (PROC, "egress"),
        (STOP_HOOK, "none"),
        *((AUTONOMY_BWRAP_TABLE[name], "none") for name in CAPTURE_ROWS),
        # AUT-2 WP6 (E-15): the label run declares egress (DNS) for its injected delivery seam
        (AUTONOMY_BWRAP_TABLE["breezy-label-outcomes"], "egress"),
        # AUT-6 WP1 (E-15): the redeliver row declares egress for delivery
        (AUTONOMY_BWRAP_TABLE["breezy-autonomy-alert-redeliver"], "egress"),
        # AUT-6 WP2 (A9): the canary row declares egress for its delivery POST
        (AUTONOMY_BWRAP_TABLE["breezy-autonomy-canary"], "egress"),
    )
    assert {row.name for row, _ in expected} == set(AUTONOMY_BWRAP_TABLE)
    for row, value in expected:
        assert type(row.network) is str
        assert row.network == value, row.name
    validate_table()


def test_seam_b_selftest_rows_stay_egress_and_emit_no_unshare_net() -> None:
    """S3-R11: their true behaviour is not tightened."""
    for row in (SELFTEST, NOTIFY, PROC):
        assert row.network == "egress"
        assert UNSHARE_NET not in _argv(row)


def test_none_rows_unshare_net_in_the_real_argv() -> None:
    for name in ("breezy-quote-tape.stop-hook", *CAPTURE_ROWS):
        assert UNSHARE_NET in _argv(AUTONOMY_BWRAP_TABLE[name])
