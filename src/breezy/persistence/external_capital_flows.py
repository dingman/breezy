"""Immutable per-run snapshots of parsed external capital flows, and the
window-level evidence view the ROI report reads (FU-13b).

Lives in ``persistence/``, not ``adapters/``: the import-linter layer
contract (``pyproject.toml``) places ``adapters`` ABOVE ``persistence``, so
this module -- the lower layer -- may never import
``breezy.adapters.polymarket_us.account_activity``. The dependency runs the
other way: that adapter module imports :class:`ExternalCapitalFlow` from
here. The two ``ACCOUNT_BALANCE_CHANGE_STATUS_*`` literals this module checks
for AC5 counting are therefore its own copy of the same two wire-format
strings the adapter's ``KNOWN_STATUSES`` documents -- a small, deliberate
duplication of protocol vocabulary across a layer boundary that must not be
crossed by import.

No I/O happens except in :func:`write_snapshot` and
:func:`read_latest_snapshot` -- everything else (:func:`flows_between`,
:func:`window_flows`) is pure. Snapshots are immutable and unique-per-run
(the filename embeds ``pulled_at_ns``); a run never overwrites another run's
file, so ``write_snapshot`` uses ``O_EXCL`` rather than a temp-file-plus-
rename dance, and a torn/partial file left by a crashed writer is simply
read back as the newest MALFORMED file on the next run (exercised directly
by ``test_newest_malformed_older_ok_returns_older_and_records_rejected_status``).

Diagnostics (exceptions and log lines) on every malformed/unparseable path
carry field names and positions only -- never amounts, ids, cursors, or raw
file bytes (AC10, AC9).
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, fields
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final

__all__ = [
    "SNAPSHOT_FIELDS",
    "SNAPSHOT_SCHEMA_VERSION",
    "STATUS_INCOMPLETE",
    "STATUS_MALFORMED",
    "STATUS_NOT_CONFIGURED",
    "STATUS_OK",
    "STATUS_UNAVAILABLE",
    "ExternalCapitalFlow",
    "ExternalFlowEvidence",
    "WindowFlows",
    "default_capital_flows_dir",
    "default_output_dir",
    "flows_between",
    "load_evidence",
    "read_latest_snapshot",
    "window_flows",
    "write_snapshot",
]

_logger = logging.getLogger(__name__)

#: Same env var `scripts/analysis/portfolio_roi_report._default_output_dir`
#: reads (FU-13b plan "Same directory rule" / round-2 review binding
#: amendment 2). Duplicated as a STRING, not imported from that script: a
#: `scripts/` module has no importable package identity, and this constant
#: only needs to name the env var, not reach into that module's code.
_LIVE_TALLY_OUTPUT_DIR_ENV_VAR: Final[str] = "BREEZY_LIVE_TALLY_OUTPUT_DIR"

SNAPSHOT_SCHEMA_VERSION: Final[int] = 1

STATUS_OK: Final[str] = "OK"
STATUS_INCOMPLETE: Final[str] = "INCOMPLETE"
STATUS_UNAVAILABLE: Final[str] = "UNAVAILABLE"
STATUS_MALFORMED: Final[str] = "MALFORMED"
STATUS_NOT_CONFIGURED: Final[str] = "NOT_CONFIGURED"

_KNOWN_SNAPSHOT_STATUSES: Final[frozenset[str]] = frozenset({STATUS_OK, STATUS_INCOMPLETE})

# AC5's countable-status set. Duplicated from (never imported from) the
# adapter's ``account_activity.KNOWN_STATUSES`` -- see module docstring.
_COUNTABLE_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "ACCOUNT_BALANCE_CHANGE_STATUS_COMPLETED",
        "ACCOUNT_BALANCE_CHANGE_STATUS_PENDING",
    }
)
_COUNTABLE_CURRENCY: Final[str] = "USD"
_UNRECOGNISED_KIND: Final[str] = "UNRECOGNISED"
_PARSE_STATUS_OK: Final[str] = "OK"

_DIR_MODE: Final[int] = 0o700
_FILE_MODE: Final[int] = 0o600


def default_output_dir(env: Mapping[str, str] | None = None) -> Path:
    """The SAME env-or-default rule ``scripts/analysis/portfolio_roi_report.
    _default_output_dir`` applies, factored out here so the read-only capital-
    flow puller (``scripts/venue/polymarket_us_capital_flow_pull.py``, a
    separate process) and the ROI report resolve the IDENTICAL root without a
    second, potentially-drifting copy of the rule (FU-13b plan "Same
    directory rule" / round-2 review binding amendment 2).

    ``scripts/analysis/portfolio_roi_report.py`` is owned by a parallel build
    stage and is not edited here (this stage may not touch it); that stage is
    expected to replace its own ``_default_output_dir`` body with a
    delegation to this function so the two never diverge. Until then, both
    read the identical env var with the identical fallback, which is what
    :func:`test_puller_dir_matches_report_dir_rule`
    (``tests/unit/test_polymarket_us_capital_flow_pull.py``) verifies against
    the report script's OWN function, not a copy of its logic.
    """
    source = os.environ if env is None else env
    override = source.get(_LIVE_TALLY_OUTPUT_DIR_ENV_VAR, "").strip()
    if override:
        return Path(override)
    return Path.home() / ".local" / "share" / "breezy" / "derived"


def default_capital_flows_dir(env: Mapping[str, str] | None = None) -> Path:
    """``default_output_dir() / "capital_flows"`` -- the puller's own output
    root, and the directory the ROI report must read evidence from."""
    return default_output_dir(env) / "capital_flows"


@dataclass(frozen=True)
class ExternalCapitalFlow:
    """One parsed, evidenced capital-flow record.

    ``kind`` is one of the ``FLOW_TYPES`` kinds
    (``breezy.adapters.polymarket_us.account_activity``), or
    ``"UNRECOGNISED"``. ``signed_amount`` is ``None`` for an unrecognised or
    UNPARSEABLE record. ``transaction_id_sha256`` is the ONLY trace of the
    venue's transaction id ever stored (AC9) -- never a raw id, external id,
    description, or balance.
    """

    kind: str
    signed_amount: Decimal | None
    currency: str | None
    status: str | None
    create_ts_ns: int | None
    update_ts_ns: int | None
    transaction_id_sha256: str | None
    sign_basis: str
    parse_status: str
    failed: bool


#: The closed schema every stored flow dict must match exactly -- an extra
#: or missing key marks the whole snapshot MALFORMED.
SNAPSHOT_FIELDS: Final[tuple[str, ...]] = tuple(f.name for f in fields(ExternalCapitalFlow))


@dataclass(frozen=True)
class ExternalFlowEvidence:
    """The evidence view a report reads: one snapshot's worth of flows plus
    its coverage bounds, or a reason none is usable.

    ``status`` is always one of ``OK``/``INCOMPLETE``/``UNAVAILABLE``/
    ``MALFORMED``/``NOT_CONFIGURED`` (AC2) -- never absent.
    """

    status: str
    flows: tuple[ExternalCapitalFlow, ...]
    pulled_at_ns: int | None
    covered_from_ns: int | None
    newest_rejected_status: str | None


@dataclass(frozen=True)
class WindowFlows:
    """The per-window counting result AC5/AC6/AC7 need.

    ``has_unverifiable`` is set by an UNPARSEABLE record, an unknown status,
    a non-USD currency, or an unrecognised activity type in the window --
    never merely by a failed (excluded) flow, which is well-understood and
    simply subtracted (AC7's "never dropped" applies to the unverifiable
    case, not the failed-and-excluded one).
    """

    covered: bool
    counted_sum: Decimal
    n_counted: int
    n_excluded_failed: int
    has_unverifiable: bool


def _flow_to_dict(flow: ExternalCapitalFlow) -> dict[str, Any]:
    return {
        "kind": flow.kind,
        "signed_amount": None if flow.signed_amount is None else str(flow.signed_amount),
        "currency": flow.currency,
        "status": flow.status,
        "create_ts_ns": flow.create_ts_ns,
        "update_ts_ns": flow.update_ts_ns,
        "transaction_id_sha256": flow.transaction_id_sha256,
        "sign_basis": flow.sign_basis,
        "parse_status": flow.parse_status,
        "failed": flow.failed,
    }


class _SnapshotMalformedError(Exception):
    """Internal only -- carries a payload-free reason, never file bytes."""


def _flow_from_dict(raw: Any) -> ExternalCapitalFlow:
    if not isinstance(raw, dict) or set(raw.keys()) != set(SNAPSHOT_FIELDS):
        raise _SnapshotMalformedError("flow record has an unexpected key set")
    try:
        signed_amount = None if raw["signed_amount"] is None else Decimal(str(raw["signed_amount"]))
    except InvalidOperation as exc:
        raise _SnapshotMalformedError("flow record signed_amount is not decimal") from exc
    if not isinstance(raw["kind"], str) or not isinstance(raw["sign_basis"], str):
        raise _SnapshotMalformedError("flow record kind/sign_basis is not a string")
    if not isinstance(raw["parse_status"], str) or not isinstance(raw["failed"], bool):
        raise _SnapshotMalformedError("flow record parse_status/failed has the wrong type")
    create_ts_ns = raw["create_ts_ns"]
    if create_ts_ns is not None and not isinstance(create_ts_ns, int):
        raise _SnapshotMalformedError("flow record create_ts_ns is not an int")
    is_placeable_ok_flow = (
        raw["kind"] != _UNRECOGNISED_KIND and raw["parse_status"] == _PARSE_STATUS_OK
    )
    if is_placeable_ok_flow and create_ts_ns is None:
        # A window cannot be placed without a timestamp (edge case: FU-13b
        # plan "unparseable createTime means the whole snapshot is
        # MALFORMED").
        raise _SnapshotMalformedError("flow record is missing create_ts_ns")
    update_ts_ns = raw["update_ts_ns"]
    if update_ts_ns is not None and not isinstance(update_ts_ns, int):
        raise _SnapshotMalformedError("flow record update_ts_ns is not an int")
    return ExternalCapitalFlow(
        kind=raw["kind"],
        signed_amount=signed_amount,
        currency=raw["currency"],
        status=raw["status"],
        create_ts_ns=create_ts_ns,
        update_ts_ns=update_ts_ns,
        transaction_id_sha256=raw["transaction_id_sha256"],
        sign_basis=raw["sign_basis"],
        parse_status=raw["parse_status"],
        failed=raw["failed"],
    )


def write_snapshot(
    directory: Path,
    *,
    flows: list[ExternalCapitalFlow],
    pulled_at_ns: int,
    covered_from_ns: int,
    status: str = STATUS_OK,
) -> Path:
    """Write one immutable, closed-schema snapshot.

    ``directory`` is created (0700) if absent. The file is created with
    ``O_EXCL`` at 0600 -- a collision on ``pulled_at_ns`` (two runs at the
    identical nanosecond) raises :class:`FileExistsError` rather than
    silently overwriting evidence.
    """
    if status not in _KNOWN_SNAPSHOT_STATUSES:
        raise ValueError(f"write_snapshot: unknown status {status!r}")
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, _DIR_MODE)
    path = directory / f"{pulled_at_ns:020d}.json"
    payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "pulled_at_ns": pulled_at_ns,
        "covered_from_ns": covered_from_ns,
        "status": status,
        "flows": [_flow_to_dict(flow) for flow in flows],
    }
    data = json.dumps(payload, sort_keys=True).encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _FILE_MODE)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise
    return path


def _load_snapshot_file(path: Path) -> dict[str, Any] | None:
    """Return the validated payload dict, or ``None`` (logging a payload-free
    reason) if ``path`` is not a usable snapshot."""
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        _logger.warning("capital-flow snapshot %s unreadable: %s", path.name, type(exc).__name__)
        return None
    try:
        payload = json.loads(raw_bytes)
    except ValueError:
        _logger.warning(
            "capital-flow snapshot %s is not valid JSON (%d bytes; content withheld)",
            path.name,
            len(raw_bytes),
        )
        return None
    if not isinstance(payload, dict):
        _logger.warning("capital-flow snapshot %s is not a JSON object", path.name)
        return None
    if payload.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        _logger.warning("capital-flow snapshot %s has an unknown schema_version", path.name)
        return None
    status = payload.get("status")
    if status not in _KNOWN_SNAPSHOT_STATUSES:
        _logger.warning("capital-flow snapshot %s has an unknown status", path.name)
        return None
    pulled_at_ns = payload.get("pulled_at_ns")
    covered_from_ns = payload.get("covered_from_ns")
    if not isinstance(pulled_at_ns, int) or not isinstance(covered_from_ns, int):
        _logger.warning("capital-flow snapshot %s has a malformed timestamp field", path.name)
        return None
    raw_flows = payload.get("flows")
    if not isinstance(raw_flows, list):
        _logger.warning("capital-flow snapshot %s has a malformed flows field", path.name)
        return None
    try:
        flows = [_flow_from_dict(raw) for raw in raw_flows]
    except _SnapshotMalformedError as exc:
        _logger.warning("capital-flow snapshot %s: %s", path.name, exc)
        return None
    return {
        "status": status,
        "pulled_at_ns": pulled_at_ns,
        "covered_from_ns": covered_from_ns,
        "flows": flows,
    }


def _unavailable_evidence() -> ExternalFlowEvidence:
    return ExternalFlowEvidence(
        status=STATUS_UNAVAILABLE,
        flows=(),
        pulled_at_ns=None,
        covered_from_ns=None,
        newest_rejected_status=None,
    )


def read_latest_snapshot(directory: Path) -> ExternalFlowEvidence:
    """Walk snapshot filenames newest-first (they are zero-padded on
    ``pulled_at_ns``, so a plain descending sort orders them correctly) and
    return the first valid one. If the newest file is rejected, its rejection
    is recorded in ``newest_rejected_status`` even though an older valid file
    is returned.
    """
    if not directory.is_dir():
        return _unavailable_evidence()
    candidates = sorted(directory.glob("*.json"), reverse=True)
    if not candidates:
        return _unavailable_evidence()
    newest_rejected_status: str | None = None
    for position, path in enumerate(candidates):
        parsed = _load_snapshot_file(path)
        if parsed is None:
            if position == 0:
                newest_rejected_status = STATUS_MALFORMED
            continue
        return ExternalFlowEvidence(
            status=parsed["status"],
            flows=tuple(parsed["flows"]),
            pulled_at_ns=parsed["pulled_at_ns"],
            covered_from_ns=parsed["covered_from_ns"],
            newest_rejected_status=newest_rejected_status,
        )
    return ExternalFlowEvidence(
        status=STATUS_MALFORMED,
        flows=(),
        pulled_at_ns=None,
        covered_from_ns=None,
        newest_rejected_status=newest_rejected_status,
    )


def load_evidence(directory: Path | None) -> ExternalFlowEvidence:
    """``directory is None`` means the puller was never configured (AC2) --
    distinct from a configured directory that is simply missing or empty
    (:data:`STATUS_UNAVAILABLE`)."""
    if directory is None:
        return ExternalFlowEvidence(
            status=STATUS_NOT_CONFIGURED,
            flows=(),
            pulled_at_ns=None,
            covered_from_ns=None,
            newest_rejected_status=None,
        )
    return read_latest_snapshot(directory)


def flows_between(
    flows: tuple[ExternalCapitalFlow, ...], prev_ts_ns: int, this_ts_ns: int
) -> list[ExternalCapitalFlow]:
    """Half-open ``(prev_ts_ns, this_ts_ns]`` selection by ``create_ts_ns``."""
    return [
        flow
        for flow in flows
        if flow.create_ts_ns is not None and prev_ts_ns < flow.create_ts_ns <= this_ts_ns
    ]


def window_flows(evidence: ExternalFlowEvidence, prev_ts_ns: int, this_ts_ns: int) -> WindowFlows:
    """AC5 counting plus AC6/AC7 coverage and unverifiable-flagging for one
    window.

    A window is covered only when the evidence's pull fully spans it:
    ``pulled_at_ns >= this_ts_ns`` and ``covered_from_ns <= prev_ts_ns``.
    """
    not_configured = evidence.status == STATUS_NOT_CONFIGURED
    if not_configured or evidence.pulled_at_ns is None or evidence.covered_from_ns is None:
        return WindowFlows(
            covered=False,
            counted_sum=Decimal(0),
            n_counted=0,
            n_excluded_failed=0,
            has_unverifiable=False,
        )

    covered = evidence.pulled_at_ns >= this_ts_ns and evidence.covered_from_ns <= prev_ts_ns
    window = flows_between(evidence.flows, prev_ts_ns, this_ts_ns)

    counted_sum = Decimal(0)
    n_counted = 0
    n_excluded_failed = 0
    has_unverifiable = False

    for flow in window:
        if (
            flow.parse_status != _PARSE_STATUS_OK
            or flow.kind == _UNRECOGNISED_KIND
            or flow.status not in _COUNTABLE_STATUSES
            or flow.currency != _COUNTABLE_CURRENCY
        ):
            has_unverifiable = True
            continue
        if flow.failed:
            n_excluded_failed += 1
            continue
        if flow.signed_amount is not None:
            counted_sum += flow.signed_amount
            n_counted += 1

    return WindowFlows(
        covered=covered,
        counted_sum=counted_sum,
        n_counted=n_counted,
        n_excluded_failed=n_excluded_failed,
        has_unverifiable=has_unverifiable,
    )
