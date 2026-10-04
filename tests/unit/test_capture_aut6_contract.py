"""AUT-1 WP5 stage 3, S2: the AUT-6 key shapes AUT-1 reads (design r3 D11; S3-R9, S3-R30, S3-R44).

``capture_aut6_contract`` owns the name shapes of the delivery evidence AUT-6 writes: the notifier
marker, the NBP missed-cycle marker and the per-attempt delivery record. Files are real, under
``tmp_path``, in the layout AUT-6 r15 section 3.6.2 gives
(``evidence/alerts/<date>/<ts_ns>_<writer>_d.json`` and
``evidence/alerts/notify/<date>/<name>.delivered.json``).
"""

import ast
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

import pytest

from breezy.analysis import capture_audit_inputs as inputs
from breezy.analysis import capture_aut6_contract as contract
from breezy.analysis.capture_audit_input_types import LogMarkers, NotifierProof
from breezy.analysis.capture_audit_model import LegOutcome
from breezy.analysis.capture_audit_stream_legs import (
    NBP_MISSED_PROOF_UNIT,
    RECORDER_UNIT,
    leg_n,
)
from breezy.analysis.capture_node_log_markers import NbpCycleMissedLine
from tests.support.capture_audit_fixtures import DAY, make_boot, make_inputs

NS: Final = 1_000_000_000
UNIT: Final = "breezy-quote-tape.service"
INVOCATION: Final = "0123456789abcdef0123456789abcdef"
CYCLE: Final = 1_791_032_400 * NS
SRC: Final = Path(contract.__file__)


def _put(root: Path, rel: tuple[str, ...], name: str, body: Any) -> Path:
    directory = root.joinpath(*rel)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    path.write_bytes(raw)
    path.chmod(0o600)
    return path


def _record(
    root: Path,
    day: dt.date,
    event: str,
    *,
    delivered: Any = True,
    ts: int = 1,
    suffix: str | None = None,
    **over: Any,
) -> Path:
    body: dict[str, Any] = {
        "schema": contract.DELIVERY_SCHEMA,
        "event": event,
        "delivered": delivered,
        "ts_ns": ts,
    }
    body.update(over)
    tag = suffix or ("d" if delivered else "f")
    return _put(root, ("evidence", "alerts", day.isoformat()), f"{ts}_daily_{tag}.json", body)


def _marker(root: Path, day: dt.date, name: str, *, delivered: bool = True) -> Path:
    body = {"delivered": delivered}
    return _put(root, ("evidence", "alerts", "notify", day.isoformat()), name, body)


# -- the name shapes ---------------------------------------------------------------------------


def test_marker_shapes_single_source() -> None:
    """The patterns live in this module only: the inputs gatherer holds no copy of its own."""
    assert contract.NOTIFIER_MARKER_RE.pattern == contract.NOTIFIER_MARKER_PATTERN
    assert contract.NBP_MISSED_MARKER_RE.pattern == contract.NBP_MISSED_MARKER_PATTERN
    assert contract.DELIVERY_RECORD_NAME_RE.pattern == contract.DELIVERY_RECORD_NAME_PATTERN
    assert not hasattr(inputs, "_NOTIFY_NAME_RE")
    assert vars(inputs)["read_notifier_proofs"] is contract.read_notifier_proofs
    assert contract.NBP_MISSED_PROOF_UNIT == NBP_MISSED_PROOF_UNIT == "NBP_CYCLE_MISSED"


@pytest.mark.parametrize(
    ("name", "ok"),
    [
        (f"{UNIT}__{INVOCATION}.delivered.json", True),
        (f"a__b__{INVOCATION}.delivered.json", True),
        (f"{UNIT}__{INVOCATION[:-1]}.delivered.json", False),
        (f"{UNIT}__{INVOCATION.upper()}.delivered.json", False),
        (f"{UNIT}__{INVOCATION}.json", False),
        (f"NBP_CYCLE_MISSED__{CYCLE}.delivered.json", False),
    ],
)
def test_notifier_marker_shape(name: str, ok: bool) -> None:
    assert (contract.NOTIFIER_MARKER_RE.fullmatch(name) is not None) is ok


@pytest.mark.parametrize(
    ("name", "ok"),
    [
        (f"NBP_CYCLE_MISSED__{CYCLE}.delivered.json", True),
        ("NBP_CYCLE_MISSED__1.delivered.json", True),
        ("NBP_CYCLE_MISSED__" + "9" * 21 + ".delivered.json", False),
        ("NBP_CYCLE_MISSED__abc.delivered.json", False),
        ("NBP_CYCLE_MISSED__.delivered.json", False),
        (f"NBP_CYCLE_MISSED__{CYCLE}.json", False),
        (f"x_NBP_CYCLE_MISSED__{CYCLE}.delivered.json", False),
    ],
)
def test_nbp_missed_marker_shape(name: str, ok: bool) -> None:
    assert (contract.NBP_MISSED_MARKER_RE.fullmatch(name) is not None) is ok


@pytest.mark.parametrize(
    ("name", "ok"),
    [
        ("1791032400000000000_daily_d.json", True),
        ("1_node_d.json", True),
        ("1_node_f.json", False),
        ("1_legacy_component_d.json", True),
        ("1_daily_x.json", False),
        ("daily_d.json", False),
        ("1_Daily_d.json", False),
        ("1_daily_d.json.tmp", False),
    ],
)
def test_delivery_record_name_shape(name: str, ok: bool) -> None:
    assert (contract.DELIVERY_RECORD_NAME_RE.fullmatch(name) is not None) is ok


# -- the notifier proofs (extracted from the inputs module) ---------------------------------------


def test_read_notifier_proofs_reads_both_marker_shapes(tmp_path: Path) -> None:
    _marker(tmp_path, DAY, f"{UNIT}__{INVOCATION}.delivered.json")
    _marker(tmp_path, DAY, f"NBP_CYCLE_MISSED__{CYCLE}.delivered.json")
    proofs = contract.read_notifier_proofs(tmp_path, DAY)
    assert set(proofs) == {
        NotifierProof(UNIT, INVOCATION, True, DAY.isoformat()),
        NotifierProof(NBP_MISSED_PROOF_UNIT, str(CYCLE), True, DAY.isoformat()),
    }


def test_read_notifier_proofs_covers_the_day_and_the_next_and_sorts(tmp_path: Path) -> None:
    nxt = DAY + dt.timedelta(days=1)
    _marker(tmp_path, nxt, f"{UNIT}__{INVOCATION}.delivered.json")
    _marker(tmp_path, DAY, f"NBP_CYCLE_MISSED__{CYCLE}.delivered.json")
    _marker(tmp_path, DAY + dt.timedelta(days=2), f"{UNIT}__{'b' * 32}.delivered.json")
    proofs = contract.read_notifier_proofs(tmp_path, DAY)
    assert [p.date for p in proofs] == [DAY.isoformat(), nxt.isoformat()]


def test_an_unreadable_or_false_marker_proves_no_delivery(tmp_path: Path) -> None:
    _marker(tmp_path, DAY, f"{UNIT}__{INVOCATION}.delivered.json", delivered=False)
    _put(tmp_path, ("evidence", "alerts", "notify", DAY.isoformat()),
         f"NBP_CYCLE_MISSED__{CYCLE}.delivered.json", b"{not json")  # fmt: skip
    proofs = contract.read_notifier_proofs(tmp_path, DAY)
    assert {p.delivered for p in proofs} == {False}
    assert len(proofs) == 2


def test_no_notify_directory_is_no_proofs(tmp_path: Path) -> None:
    assert contract.read_notifier_proofs(tmp_path, DAY) == ()


def test_leg_n_reads_nbp_cycle_missed_decimal_marker(tmp_path: Path) -> None:
    """F10: a delivered ``NBP_CYCLE_MISSED__<cycle_ns>`` marker was never seen (the 32-hex shape
    cannot match a decimal), so leg N failed closed. Read through the contract, it is seen."""
    line = NbpCycleMissedLine(3, CYCLE, CYCLE, CYCLE, "NBM_NBP", True)
    boot = make_boot(markers=LogMarkers(nbp_cycle_missed=(line,)))
    undelivered = leg_n(make_inputs(boots=(boot,), nbp_cycles_ns=(), notifier_proofs=()))
    assert [f.cause for f in undelivered.findings] == ["nbp_missed_alert_undelivered"]
    _marker(tmp_path, DAY, f"NBP_CYCLE_MISSED__{CYCLE}.delivered.json")
    proofs = contract.read_notifier_proofs(tmp_path, DAY)
    seen = leg_n(make_inputs(boots=(boot,), nbp_cycles_ns=(), notifier_proofs=proofs))
    assert seen.outcome == LegOutcome.PASS
    assert seen.findings == ()


def test_leg_w_still_reads_the_recorder_marker_through_the_contract(tmp_path: Path) -> None:
    _marker(tmp_path, DAY, f"{RECORDER_UNIT}__{INVOCATION}.delivered.json")
    (proof,) = contract.read_notifier_proofs(tmp_path, DAY)
    assert (proof.unit, proof.invocation_id, proof.delivered) == (RECORDER_UNIT, INVOCATION, True)


# -- the delivery records -------------------------------------------------------------------------


def test_delivery_record_reader_fixture(tmp_path: Path) -> None:
    _record(tmp_path, DAY, "CAPTURE_HEALED_aa", ts=1)
    _record(tmp_path, DAY, "CAPTURE_JOIN_GAP", ts=2)
    got = contract.delivered_events(tmp_path, DAY, DAY)
    assert got == frozenset({"CAPTURE_HEALED_aa", "CAPTURE_JOIN_GAP"})


def test_only_delivered_true_records_count(tmp_path: Path) -> None:
    _record(tmp_path, DAY, "E_FAILED", delivered=False, ts=1, suffix="d")
    _record(tmp_path, DAY, "E_STRING_TRUE", ts=2, delivered="true")
    _record(tmp_path, DAY, "E_FAILED_NAME", delivered=False, ts=5)
    _record(tmp_path, DAY, "E_ONE", ts=3, delivered=1)
    _record(tmp_path, DAY, "E_OK", ts=4)
    assert contract.delivered_events(tmp_path, DAY, DAY) == frozenset({"E_OK"})


def test_a_wrong_or_missing_schema_is_not_a_delivery(tmp_path: Path) -> None:
    _record(tmp_path, DAY, "E_OLD", ts=1, schema="alert_delivery/v0")
    _put(tmp_path, ("evidence", "alerts", DAY.isoformat()), "2_daily_d.json",
         {"event": "E_NO_SCHEMA", "delivered": True})  # fmt: skip
    _record(tmp_path, DAY, "E_OK", ts=3)
    assert contract.delivered_events(tmp_path, DAY, DAY) == frozenset({"E_OK"})


def test_a_record_without_a_string_event_is_ignored(tmp_path: Path) -> None:
    _record(tmp_path, DAY, "", ts=1)
    body = {"schema": contract.DELIVERY_SCHEMA, "event": 7, "delivered": True}
    _put(tmp_path, ("evidence", "alerts", DAY.isoformat()), "2_daily_d.json", body)
    _record(tmp_path, DAY, "E_OK", ts=3)
    assert contract.delivered_events(tmp_path, DAY, DAY) == frozenset({"E_OK"})


def test_ledger_missing_or_unreadable_is_not_delivered(tmp_path: Path) -> None:
    """A missing directory, garbage bytes, a JSON list and a symlinked record all read as not
    delivered: the caller then re-sends (fail closed)."""
    assert contract.delivered_events(tmp_path, DAY, DAY) == frozenset()
    rel = ("evidence", "alerts", DAY.isoformat())
    _put(tmp_path, rel, "1_daily_d.json", b"\x00\xff garbage")
    _put(tmp_path, rel, "2_daily_d.json", [1, 2, 3])
    outside = tmp_path / "outside.json"
    outside.write_text(
        json.dumps({"schema": contract.DELIVERY_SCHEMA, "event": "E", "delivered": True})
    )
    os.symlink(outside, tmp_path.joinpath(*rel) / "3_daily_d.json")
    assert contract.delivered_events(tmp_path, DAY, DAY) == frozenset()


def test_a_symlinked_date_directory_is_not_delivered(tmp_path: Path) -> None:
    real = tmp_path / "elsewhere"
    _record(real, DAY, "E_OK")  # builds real/evidence/alerts/<day>
    alerts = tmp_path / "evidence" / "alerts"
    alerts.mkdir(parents=True)
    os.symlink(real / "evidence" / "alerts" / DAY.isoformat(), alerts / DAY.isoformat())
    assert contract.delivered_events(tmp_path, DAY, DAY) == frozenset()


def test_the_date_range_is_inclusive_and_bounded(tmp_path: Path) -> None:
    for offset in (-1, 0, 1, 2, 3):
        _record(tmp_path, DAY + dt.timedelta(days=offset), f"E{offset}")
    got = contract.delivered_events(tmp_path, DAY, DAY + dt.timedelta(days=2))
    assert got == frozenset({"E0", "E1", "E2"})
    assert contract.delivered_events(tmp_path, DAY + dt.timedelta(days=2), DAY) == frozenset()


def test_names_that_are_not_delivery_records_are_ignored(tmp_path: Path) -> None:
    rel = ("evidence", "alerts", DAY.isoformat())
    body = {"schema": contract.DELIVERY_SCHEMA, "event": "E_BAD", "delivered": True}
    _put(tmp_path, rel, "1_daily_x.json", body)
    _put(tmp_path, rel, "notes.json", body)
    _put(tmp_path, rel, "1_daily_d.json.tmp", body)
    assert contract.delivered_events(tmp_path, DAY, DAY) == frozenset()


# -- isolation ------------------------------------------------------------------------------------


def test_contract_module_never_imports_inputs() -> None:
    """S3-R30: no import cycle with the inputs gatherer; only the I/O helper and single_read. The
    ``NotifierProof`` type lives here (the input types re-export it), so the closure stays free of
    the input types' Nautilus import."""
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    imported = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 0
    }
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any(m.endswith("capture_audit_inputs") for m in imported)
    breezy = {m for m in imported if m.startswith("breezy.")}
    assert breezy <= {
        "breezy.analysis.capture_audit_io",
        "breezy.persistence.autonomy.single_read",
    }
    assert "breezy.analysis.capture_audit_io" in breezy


REPO_ROOT: Final = Path(__file__).resolve().parents[2]
_ENV: Final = {"PYTHONPATH": str(REPO_ROOT / "src"), "PATH": "/usr/bin:/bin"}
_BAD: Final = (
    "bad = sorted(m for m in sys.modules if m.split('.')[0] in\n"
    "    {'httpx', 'requests', 'aiohttp', 'urllib3', 'nautilus_trader'}\n"
    "    or m.startswith('breezy.adapters'))\n"
    "print(bad)\n"
)


def _probe(code: str) -> str:
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, env=_ENV
    )
    return done.stdout.strip()


def test_importing_the_contract_alone_does_not_load_the_inputs_module() -> None:
    code = (
        "import sys\n"
        "import breezy.analysis.capture_aut6_contract\n"
        "print('breezy.analysis.capture_audit_inputs' in sys.modules)\n"
    )
    assert _probe(code) == "False"


def test_the_notifier_proof_type_is_one_class_re_exported_by_the_input_types() -> None:
    from breezy.analysis.capture_audit_input_types import NotifierProof as from_types

    assert from_types is contract.NotifierProof


def test_capture_aut6_contract_sys_modules_closure() -> None:
    """S3-R37: reading a record never loads an adapter, an HTTP client or Nautilus."""
    code = (
        "import sys, tempfile, pathlib, datetime as dt\n"
        "from breezy.analysis import capture_aut6_contract as c\n"
        "with tempfile.TemporaryDirectory() as d:\n"
        "    root = pathlib.Path(d); root.chmod(0o700)\n"
        "    c.delivered_events(root, dt.date(2026, 10, 1), dt.date(2026, 10, 2))\n"
        "    c.read_notifier_proofs(root, dt.date(2026, 10, 1))\n"
    ) + _BAD
    assert _probe(code) == "[]"


def test_the_closure_probe_is_not_vacuous() -> None:
    """Positive control: the same probe flags a program that does load an adapter."""
    code = "import sys, breezy.adapters.polymarket_us.recorder_watchdog\n" + _BAD
    assert _probe(code) != "[]"


def test_read_notifier_proofs_survives_an_unreadable_notify_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3-R57: the listing goes through the guarded ``_names`` helper, as the docstring says."""

    def refusing(*_a: Any) -> list[str]:
        raise OSError("notify directory unreadable")

    monkeypatch.setattr(contract, "list_names", refusing)

    assert contract.read_notifier_proofs(tmp_path, DAY) == ()
