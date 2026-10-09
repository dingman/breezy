"""X-13 (binding activation ruling): the drop-in allowlist row (WP3 S6)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Final

import pytest

from breezy.runtime.health_dropins import (
    DROPIN_ALLOWLIST,
    DropinAllow,
    classify_dropins,
    read_dropin_file,
)

UNIT: Final = "breezy-trade-supervisor.service"
NAME: Final = "fq-v1-halt-orders-off.conf"
SAFE: Final = b"# orders off by ruling\n[Service]\nEnvironment=BREEZY_ORDERS_ENABLED=0\n"
RULING: Final = "RULING_FQ-v2-NO-TRADE_2026-10-08"
TODAY: Final = "2026-10-09"


def _row(content: bytes = SAFE, expires: str = "2026-12-31") -> DropinAllow:
    return DropinAllow(UNIT, NAME, hashlib.sha256(content).hexdigest(), RULING, expires)


def _blocks(path: Path) -> dict[str, dict[str, str]]:
    return {UNIT: {"DropInPaths": str(path)}}


def _file(tmp_path: Path, content: bytes = SAFE) -> Path:
    path = tmp_path / NAME
    path.write_bytes(content)
    return path


def _classify(path: Path, content: bytes = SAFE, **kw: object) -> tuple[list[str], tuple[str, ...]]:
    allow = kw.pop("rows", (_row(content),))
    verdict = classify_dropins(
        _blocks(path),
        {},
        today=kw.pop("today", TODAY),  # type: ignore[arg-type]
        read_dropin=read_dropin_file,
        allowlist=allow,  # type: ignore[arg-type]
    )
    return [f"{f.severity}:{f.dropin}" for f in verdict.findings], verdict.allowlisted


def test_a_matching_regular_file_is_allowlisted_and_listed(tmp_path: Path) -> None:
    findings, allowlisted = _classify(_file(tmp_path))
    assert findings == [] and allowlisted == (f"{UNIT}:{NAME}",)


def test_edited_content_is_critical(tmp_path: Path) -> None:
    path = _file(tmp_path, SAFE + b"# edited\n")
    findings, allowlisted = _classify(path, rows=(_row(),))
    assert findings == [f"CRITICAL:{NAME}"] and allowlisted == ()


def test_a_symlink_is_critical_even_with_the_right_content(tmp_path: Path) -> None:
    real = tmp_path / "real.conf"
    real.write_bytes(SAFE)
    link = tmp_path / NAME
    os.symlink(real, link)
    findings, allowlisted = _classify(link)
    assert findings == [f"CRITICAL:{NAME}"] and allowlisted == ()


def test_an_unreadable_or_missing_file_is_critical(tmp_path: Path) -> None:
    findings, allowlisted = _classify(tmp_path / NAME)
    assert findings == [f"CRITICAL:{NAME}"] and allowlisted == ()


def test_an_expired_row_is_critical(tmp_path: Path) -> None:
    path = _file(tmp_path)
    assert _classify(path, today="2026-12-30")[1] != ()
    findings, allowlisted = _classify(path, today="2026-12-31")
    assert findings == [f"CRITICAL:{NAME}"] and allowlisted == ()


def test_an_unlisted_dropin_keeps_the_ordinary_drift_severity(tmp_path: Path) -> None:
    path = tmp_path / "other.conf"
    path.write_bytes(SAFE)
    findings, allowlisted = _classify(path, rows=())
    assert findings == ["WARNING:other.conf"] and allowlisted == ()


def test_the_same_content_under_another_unit_or_name_is_not_allowlisted(tmp_path: Path) -> None:
    path = tmp_path / "renamed.conf"
    path.write_bytes(SAFE)
    findings, allowlisted = _classify(path)
    assert findings == ["WARNING:renamed.conf"] and allowlisted == ()


@pytest.mark.parametrize(
    "extra",
    [
        b"Environment=BREEZY_ORDERS_ENABLED=1\n",
        b"Environment=BREEZY_MAX_DAILY_USD=5\n",
        b"EnvironmentFile=/home/jon/.config/breezy/operator.env\n",
        b"ExecStartPre=/bin/true\n",
    ],
)
def test_a_dropin_that_sets_caps_or_the_permit_is_never_allowlisted(
    tmp_path: Path, extra: bytes
) -> None:
    """Even if a row's hash named such a file, the content guard refuses to match it."""
    content = SAFE + extra
    findings, allowlisted = _classify(_file(tmp_path, content), content)
    assert findings == [f"CRITICAL:{NAME}"] and allowlisted == ()


def test_the_shipped_row_is_pinned_to_the_ruling_and_its_expiry() -> None:
    (row,) = DROPIN_ALLOWLIST
    assert (row.unit, row.dropin, row.ruling, row.expires) == (UNIT, NAME, RULING, "2026-12-31")
    assert len(row.sha256) == 64


def test_the_live_dropin_matches_the_row_and_sets_only_the_orders_off_directive() -> None:
    live = Path.home() / ".config/systemd/user" / f"{UNIT}.d" / NAME
    if not live.is_file():
        pytest.skip("the orders-off drop-in is not installed on this host")
    data = read_dropin_file(str(live))
    assert data is not None
    directives = [
        line.strip()
        for line in data.decode().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert directives == ["[Service]", "Environment=BREEZY_ORDERS_ENABLED=0"]
    assert hashlib.sha256(data).hexdigest() == DROPIN_ALLOWLIST[0].sha256


def test_the_reader_refuses_a_directory_and_an_oversize_file(tmp_path: Path) -> None:
    assert read_dropin_file(str(tmp_path)) is None
    big = tmp_path / "big.conf"
    big.write_bytes(b"x" * 70_000)
    assert read_dropin_file(str(big)) is None
