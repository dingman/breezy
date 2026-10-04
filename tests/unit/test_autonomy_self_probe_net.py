"""AUT-1 WP5 stage 3 (E-15, S3-R10, S3-R34): the self-probe's network check on ``none`` rows.

Phase 1 cannot nest bubblewrap, so every case injects the connect result and the interface list
(``ProbeFs.connect_errno``, a scratch ``/proc/net/dev``). The real isolation is proven by the
phase-1 argv test (``test_autonomy_network_field``) and host V3 through the real wrapper.
"""

from __future__ import annotations

import dataclasses
import errno
import socket
from pathlib import Path
from typing import Any

import pytest

from breezy.runtime.autonomy_sandbox import self_probe
from breezy.runtime.autonomy_sandbox.bwrap import ROW_VAR
from breezy.runtime.autonomy_sandbox.self_probe import (
    FIXED_REASON_CODES,
    PROBE_CONNECT_HOST,
    PROBE_CONNECT_PORT,
    ProbeFs,
    SelfProbeResult,
    run_self_probe,
)
from breezy.runtime.autonomy_sandbox.table import AUTONOMY_BWRAP_TABLE
from tests.support.bwrap_harness import make_roots

pytestmark = pytest.mark.allow_socket

NONE_ROW = "breezy-quote-tape.stop-hook"
EGRESS_ROW = "breezy-autonomy-selftest"
NET_CODES = {"net_reachable", "net_iface_visible"}
DEV_HEADER = (
    "Inter-|   Receive                                                |  Transmit\n"
    " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs\n"
)


def _dev_line(name: str) -> str:
    return f"{name:>6}: 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n"


def _dev(*names: str) -> str:
    return DEV_HEADER + "".join(_dev_line(name) for name in names)


def _probe(
    tmp_path: Path,
    row: str = NONE_ROW,
    *,
    errno_value: int = errno.ENETUNREACH,
    dev: str | None = None,
    calls: list[tuple[str, int]] | None = None,
) -> SelfProbeResult:
    roots = make_roots(tmp_path)
    fsroot = tmp_path / "fsroot"
    (fsroot / "proc" / "net").mkdir(parents=True)
    if dev is not None:
        (fsroot / "proc" / "net" / "dev").write_text(dev)

    def connect(host: str, port: int) -> int:
        if calls is not None:
            calls.append((host, port))
        return errno_value

    fs = ProbeFs(host_root=fsroot, run=fsroot / "run", tmp=fsroot / "tmp", proc=fsroot / "proc")
    return run_self_probe(
        row,
        roots=roots,
        environ={ROW_VAR: row},
        fs=dataclasses.replace(fs, connect_errno=connect),
    )


def test_probe_none_row_reachable_fails_net_reachable(tmp_path: Path) -> None:
    """MUTATION M-SKIPNET: dropping the check on ``none`` rows leaves a reachable network green."""
    for value in (0, errno.ECONNREFUSED, errno.ETIMEDOUT, errno.EPERM, errno.EHOSTUNREACH):
        result = _probe(tmp_path / str(value), errno_value=value, dev=_dev("lo"))
        assert "net_reachable" in result.failures, value
        assert "net_iface_visible" not in result.failures


def test_probe_none_row_isolated_has_no_net_failure(tmp_path: Path) -> None:
    result = _probe(tmp_path, dev=_dev("lo"))
    assert not NET_CODES & set(result.failures)
    assert result.facts["net_ifaces"] == ["lo"]


def test_probe_connects_to_the_documentation_address_over_udp(tmp_path: Path) -> None:
    """S3-R34: TEST-NET-2 ``198.51.100.7:80``; UDP sends no packet even if isolation is broken."""
    calls: list[tuple[str, int]] = []
    _probe(tmp_path, dev=_dev("lo"), calls=calls)
    assert calls == [("198.51.100.7", 80)]
    assert (PROBE_CONNECT_HOST, PROBE_CONNECT_PORT) == ("198.51.100.7", 80)


def test_default_connect_is_a_sock_dgram_connect_that_reports_the_errno(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    class FakeSocket:
        def __init__(self, family: int, kind: int, *rest: Any) -> None:
            seen["family"], seen["kind"] = family, kind

        def settimeout(self, value: float | None) -> None:
            seen["timeout"] = value

        def connect(self, address: tuple[str, int]) -> None:
            seen["address"] = address
            raise OSError(errno.ENETUNREACH, "unreachable")

        def close(self) -> None:
            seen["closed"] = True

    monkeypatch.setattr("breezy.runtime.autonomy_sandbox.self_probe.socket.socket", FakeSocket)
    assert self_probe.udp_connect_errno("198.51.100.7", 80) == errno.ENETUNREACH
    assert seen["family"] == socket.AF_INET and seen["kind"] == socket.SOCK_DGRAM
    assert seen["address"] == ("198.51.100.7", 80)
    assert seen["timeout"] is not None and 0 < seen["timeout"] <= 5
    assert seen["closed"] is True


def test_default_connect_reports_zero_when_the_connect_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Connected:
        def __init__(self, *args: Any) -> None: ...

        def settimeout(self, value: float | None) -> None: ...

        def connect(self, address: tuple[str, int]) -> None: ...

        def close(self) -> None: ...

    monkeypatch.setattr("breezy.runtime.autonomy_sandbox.self_probe.socket.socket", Connected)
    assert self_probe.udp_connect_errno("198.51.100.7", 80) == 0


@pytest.mark.parametrize(
    "dev",
    [_dev("lo", "eth0"), _dev("eth0"), _dev("lo", "docker0", "veth1"), _dev(), "", "garbage\n"],
)
def test_probe_none_row_extra_iface_fails(tmp_path: Path, dev: str) -> None:
    """MUTATION M-ANYIFACE: accepting any interface list. ``lo`` alone is the only pass."""
    result = _probe(tmp_path, dev=dev)
    assert "net_iface_visible" in result.failures
    assert "net_reachable" not in result.failures


def test_probe_none_row_unreadable_interface_list_fails_closed(tmp_path: Path) -> None:
    result = _probe(tmp_path, dev=None)
    assert "net_iface_visible" in result.failures
    assert result.facts["net_ifaces"] == []


def test_probe_none_row_reports_both_codes_without_a_path(tmp_path: Path) -> None:
    result = _probe(tmp_path, errno_value=0, dev=_dev("lo", "eth0"))
    assert NET_CODES <= set(result.failures)
    assert all("/" not in code for code in result.failures)


def test_probe_egress_row_skips_net_check_records_fact(tmp_path: Path) -> None:
    """The seam B rows keep their network (S3-R11): reachable and ``eth0`` are not failures."""
    calls: list[tuple[str, int]] = []
    result = _probe(tmp_path, EGRESS_ROW, errno_value=0, dev=_dev("lo", "eth0"), calls=calls)
    assert not NET_CODES & set(result.failures)
    assert result.facts["net_ifaces"] == ["eth0", "lo"]
    assert calls == []


def test_net_ifaces_fact_is_recorded_on_every_row(tmp_path: Path) -> None:
    for name in AUTONOMY_BWRAP_TABLE:
        result = _probe(tmp_path / name.replace("/", "_"), name, dev=_dev("lo"))
        assert result.facts["net_ifaces"] == ["lo"], name


def test_the_two_reason_codes_are_in_the_fixed_vocabulary() -> None:
    assert NET_CODES <= FIXED_REASON_CODES
    assert all("/" not in code and code == code.lower() for code in NET_CODES)
