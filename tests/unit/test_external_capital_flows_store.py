"""RED-first unit tests for ``breezy.persistence.external_capital_flows``
(FU-13b stage 1)."""

from __future__ import annotations

import json
import stat
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.persistence import external_capital_flows as ecf
from breezy.persistence.external_capital_flows import ExternalCapitalFlow


def _flow(
    *,
    kind: str = "ACCOUNT_DEPOSIT",
    signed_amount: Decimal | None = Decimal(10),
    currency: str | None = "USD",
    status: str | None = "ACCOUNT_BALANCE_CHANGE_STATUS_COMPLETED",
    create_ts_ns: int | None = 1_000,
    update_ts_ns: int | None = 1_000,
    transaction_id_sha256: str | None = "a" * 64,
    sign_basis: str = "type_table",
    parse_status: str = "OK",
    failed: bool = False,
) -> ExternalCapitalFlow:
    return ExternalCapitalFlow(
        kind=kind,
        signed_amount=signed_amount,
        currency=currency,
        status=status,
        create_ts_ns=create_ts_ns,
        update_ts_ns=update_ts_ns,
        transaction_id_sha256=transaction_id_sha256,
        sign_basis=sign_basis,
        parse_status=parse_status,
        failed=failed,
    )


def test_snapshot_roundtrip_closed_schema(tmp_path: Path) -> None:
    flows = [_flow(), _flow(kind="TRANSFER", signed_amount=Decimal(-5), sign_basis="literal")]
    path = ecf.write_snapshot(tmp_path, flows=flows, pulled_at_ns=5_000, covered_from_ns=0)
    evidence = ecf.read_latest_snapshot(tmp_path)
    assert evidence.status == ecf.STATUS_OK
    assert evidence.pulled_at_ns == 5_000
    assert evidence.covered_from_ns == 0
    assert evidence.flows == tuple(flows)
    assert path.exists()

    raw = json.loads(path.read_bytes())
    for flow_dict in raw["flows"]:
        assert set(flow_dict.keys()) == set(ecf.SNAPSHOT_FIELDS)


def test_write_is_0600_o_excl(tmp_path: Path) -> None:
    path = ecf.write_snapshot(tmp_path, flows=[_flow()], pulled_at_ns=1, covered_from_ns=0)
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600
    dir_mode = stat.S_IMODE(tmp_path.stat().st_mode)
    assert dir_mode == 0o700
    with pytest.raises(FileExistsError):
        ecf.write_snapshot(tmp_path, flows=[_flow()], pulled_at_ns=1, covered_from_ns=0)


def test_read_latest_picks_newest_valid(tmp_path: Path) -> None:
    ecf.write_snapshot(
        tmp_path, flows=[_flow(create_ts_ns=100)], pulled_at_ns=100, covered_from_ns=0
    )
    ecf.write_snapshot(
        tmp_path, flows=[_flow(create_ts_ns=200)], pulled_at_ns=200, covered_from_ns=0
    )
    evidence = ecf.read_latest_snapshot(tmp_path)
    assert evidence.pulled_at_ns == 200
    assert evidence.newest_rejected_status is None


def test_newest_malformed_older_ok_returns_older_and_records_rejected_status(
    tmp_path: Path,
) -> None:
    ecf.write_snapshot(
        tmp_path, flows=[_flow(create_ts_ns=100)], pulled_at_ns=100, covered_from_ns=0
    )
    newest_path = tmp_path / f"{200:020d}.json"
    newest_path.write_bytes(b"{not json")
    import os as _os

    _os.chmod(newest_path, 0o600)

    evidence = ecf.read_latest_snapshot(tmp_path)
    assert evidence.status == ecf.STATUS_OK
    assert evidence.pulled_at_ns == 100
    assert evidence.newest_rejected_status == ecf.STATUS_MALFORMED


def test_no_dir_is_not_configured() -> None:
    evidence = ecf.load_evidence(None)
    assert evidence.status == ecf.STATUS_NOT_CONFIGURED
    assert evidence.flows == ()


def test_missing_dir_unavailable(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    evidence = ecf.load_evidence(missing)
    assert evidence.status == ecf.STATUS_UNAVAILABLE


def test_bad_json_malformed(tmp_path: Path) -> None:
    bad = tmp_path / f"{1:020d}.json"
    bad.write_bytes(b"not json at all")
    evidence = ecf.read_latest_snapshot(tmp_path)
    assert evidence.status == ecf.STATUS_MALFORMED
    assert evidence.flows == ()


def test_malformed_diagnostic_has_no_file_bytes(tmp_path: Path, caplog) -> None:
    sentinel = b"SENTINEL-RAW-BYTES-999"
    bad = tmp_path / f"{1:020d}.json"
    bad.write_bytes(sentinel)
    import logging

    with caplog.at_level(logging.WARNING):
        ecf.read_latest_snapshot(tmp_path)
    assert sentinel.decode("ascii") not in caplog.text


def test_incomplete_sets_covered_from(tmp_path: Path) -> None:
    ecf.write_snapshot(
        tmp_path,
        flows=[_flow(create_ts_ns=500)],
        pulled_at_ns=1_000,
        covered_from_ns=250,
        status=ecf.STATUS_INCOMPLETE,
    )
    evidence = ecf.read_latest_snapshot(tmp_path)
    assert evidence.status == ecf.STATUS_INCOMPLETE
    assert evidence.covered_from_ns == 250


def test_flows_between_half_open_interval() -> None:
    flows = (
        _flow(create_ts_ns=100),
        _flow(create_ts_ns=200),
        _flow(create_ts_ns=300),
    )
    selected = ecf.flows_between(flows, 100, 200)
    assert [f.create_ts_ns for f in selected] == [200]


def test_window_flows_excludes_failed_and_flags_unverifiable() -> None:
    ok_flow = _flow(create_ts_ns=150, signed_amount=Decimal(10))
    failed_flow = _flow(create_ts_ns=160, signed_amount=Decimal(40), failed=True)
    unrecognised_flow = _flow(
        kind="UNRECOGNISED",
        signed_amount=None,
        status=None,
        currency=None,
        create_ts_ns=170,
    )
    unknown_status_flow = _flow(create_ts_ns=180, status="ACCOUNT_BALANCE_CHANGE_STATUS_FAILED")
    non_usd_flow = _flow(create_ts_ns=190, currency="EUR")
    unparseable_flow = _flow(create_ts_ns=195, parse_status="UNPARSEABLE", signed_amount=None)
    evidence = ecf.ExternalFlowEvidence(
        status=ecf.STATUS_OK,
        flows=(
            ok_flow,
            failed_flow,
            unrecognised_flow,
            unknown_status_flow,
            non_usd_flow,
            unparseable_flow,
        ),
        pulled_at_ns=1_000,
        covered_from_ns=0,
        newest_rejected_status=None,
    )
    result = ecf.window_flows(evidence, 100, 200)
    assert result.covered is True
    assert result.counted_sum == Decimal(10)
    assert result.n_counted == 1
    assert result.n_excluded_failed == 1
    assert result.has_unverifiable is True
