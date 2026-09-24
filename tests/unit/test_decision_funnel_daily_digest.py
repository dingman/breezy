"""AUD-03: daily decision-funnel digest over the offer-tape JSONL sidecar.

Pure aggregation tests pin the live stage rule and the closed ``source``
allow-list. Nothing here opens a socket, reads the live tape, or touches
the node.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import hold_submit_intent_process_lock
from breezy.strategy.current_rung_hold.trial_day_latch import FAMILY_HALT_KEY

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "analysis"
    / "decision_funnel_daily_digest.py"
)
_SPEC = importlib.util.spec_from_file_location("decision_funnel_daily_digest", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_DIGEST = importlib.util.module_from_spec(_SPEC)
# Register before exec so a slots=True dataclass can see its module dict.
sys.modules[_SPEC.name] = _DIGEST
_SPEC.loader.exec_module(_DIGEST)


def _row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "station": "MIA",
        "climate_day": "2026-09-20",
        "source": "quote",
        "reason": "observation_ambiguous",
        "illegal_cell": False,
        "ask": None,
        "break_even": None,
        "p_bound": None,
        "decision": "refuse",
        "observed_at_ns": 1,
        "exit_rule": None,
        "exit_decision": None,
    }
    base.update(overrides)
    return base


def _september_20_rows() -> list[dict[str, object]]:
    """Count-equivalent of DECISION_FUNNEL_2026-09-20.md's six-stage table.

    35,980 ``observation_ambiguous`` + 4,816 ``illegal_cell`` = 40,796
    emitted, 4,816 rung-resolved, and zero past the cell gate. Built from
    the real schema fields and the real ``source`` literals (``quote`` /
    ``depth``), not from the 40,796 raw tape lines.
    """
    ambiguous = [
        _row(
            station="MIA" if index % 2 == 0 else "LAX",
            source="quote" if index % 5 else "depth",
            observed_at_ns=1_000 + index,
        )
        for index in range(35_980)
    ]
    illegal = [
        _row(
            station="SFO",
            source="depth" if index % 4 == 0 else "quote",
            reason="illegal_cell",
            illegal_cell=True,
            observed_at_ns=2_000_000 + index,
        )
        for index in range(4_816)
    ]
    return ambiguous + illegal


def test_funnel_for_day_reproduces_the_2026_09_20_stage_counts() -> None:
    report = _DIGEST.funnel_for_day(_september_20_rows())
    assert report.totals.decisions_emitted == 40_796
    assert report.totals.rung_resolved == 4_816
    assert report.totals.cell_legal == 0
    assert report.totals.reached_price == 0
    assert report.totals.margin_positive == 0
    assert report.totals.orders == 0


def test_position_monitor_row_is_excluded_from_every_entry_stage() -> None:
    rows = [
        _row(source="quote"),
        _row(
            station="SFO",
            source="position_monitor",
            decision="exit_fired",
            exit_rule=None,
            exit_decision="fired",
            reason="fired",
        ),
    ]
    report = _DIGEST.funnel_for_day(rows)
    assert report.totals.decisions_emitted == 1
    assert report.totals.rung_resolved == 0
    assert report.exit_fired == 1
    assert report.exit_refused == 0


def test_quote_and_depth_sources_both_count_as_decisions_emitted() -> None:
    report = _DIGEST.funnel_for_day(
        [_row(source="quote"), _row(station="LAX", source="depth")]
    )
    assert report.totals.decisions_emitted == 2


@pytest.mark.parametrize("source", ["bogus", "quote_tick"])
def test_unrecognised_source_raises(source: str) -> None:
    with pytest.raises(_DIGEST.UnknownOfferTapeSourceError):
        _DIGEST.funnel_for_day([_row(source=source)])


def test_shadow_row_is_excluded_from_the_entry_funnel_and_counted_apart() -> None:
    report = _DIGEST.funnel_for_day(
        [
            _row(source="quote", reason="observation_ambiguous"),
            _row(station="LAX", source="no_side_shadow", reason="rest", decision="refuse"),
        ]
    )
    assert report.totals.decisions_emitted == 1
    assert report.totals.rung_resolved == 0
    assert report.totals.cell_legal == 0
    assert report.totals.reached_price == 0
    assert report.totals.margin_positive == 0
    assert report.totals.orders == 0
    assert report.shadow_count == 1
    assert dict(report.shadow_by_reason) == {"rest": 1}


def test_margin_stage_uses_p_bound_against_break_even_not_ask() -> None:
    """``ask < break_even`` is true on both rows (fee is positive). Only the
    row with ``p_bound > break_even`` is margin > 0 — the live rule at
    ``decision.py`` ``_finalize_take``.
    """
    below = _row(
        reason="edge_below_break_even",
        illegal_cell=False,
        ask="0.40",
        break_even="0.42",
        p_bound="0.41",
        decision="refuse",
    )
    above = _row(
        station="SFO",
        source="depth",
        reason="edge_below_break_even",
        illegal_cell=False,
        ask="0.40",
        break_even="0.42",
        p_bound="0.50",
        decision="take",
    )
    assert Decimal(str(below["ask"])) < Decimal(str(below["break_even"]))
    assert Decimal(str(above["ask"])) < Decimal(str(above["break_even"]))
    report = _DIGEST.funnel_for_day([below, above])
    assert report.totals.reached_price == 2
    assert report.totals.margin_positive == 1
    assert report.totals.orders == 1


def test_station_with_zero_entry_rows_inside_an_open_window_is_stalled() -> None:
    report = _DIGEST.funnel_for_day(
        [_row(station="LAX", source="quote")],
        window_open_stations=("LAX", "MDW"),
    )
    assert report.stalled_stations == ("MDW",)


def test_no_side_calibration_unsafe_is_reported_verbatim_past_the_cell_gate() -> None:
    """AUD-01a refusal. The digest has no fault/wait taxonomy: the reason is
    counted verbatim, and the existing stage predicates place it (rung
    resolved, cell legal, not priced — the gate returns before break-even).
    """
    report = _DIGEST.funnel_for_day(
        [
            _row(
                station="LAX",
                source="depth",
                reason="no_side_calibration_unsafe",
                illegal_cell=False,
                ask=None,
                break_even=None,
                p_bound=None,
                decision="refuse",
            )
        ]
    )
    assert report.totals.decisions_emitted == 1
    assert report.totals.rung_resolved == 1
    assert report.totals.cell_legal == 1
    assert report.totals.reached_price == 0
    assert report.totals.margin_positive == 0
    assert report.totals.orders == 0
    assert dict(report.entry_reasons) == {"no_side_calibration_unsafe": 1}


def test_coverage_window_is_the_observed_at_ns_span_actually_read() -> None:
    report = _DIGEST.funnel_for_day(
        [
            _row(observed_at_ns=10),
            _row(station="LAX", observed_at_ns=50),
            _row(station="SFO", observed_at_ns=None),
        ]
    )
    assert report.coverage_min_observed_at_ns == 10
    assert report.coverage_max_observed_at_ns == 50


def test_default_climate_day_is_the_previous_utc_date() -> None:
    now = dt.datetime(2026, 9, 21, 9, 20, tzinfo=dt.UTC)
    assert _DIGEST.default_climate_day(now) == dt.date(2026, 9, 20)


def test_digest_detail_names_shadow_rows_as_outside_the_orders_funnel() -> None:
    report = _DIGEST.funnel_for_day(
        [_row(source="no_side_shadow", reason="rest")],
        window_open_stations=("MDW",),
    )
    detail = _DIGEST.format_digest_detail(report, climate_day="2026-09-20")
    assert "shadow=" in detail
    assert "not-orders" in detail
    assert len(detail) <= 200
    assert "stall=MDW" in detail


class _Sink:
    def __init__(self) -> None:
        self.payloads: list[object] = []

    def emit(self, payload: object) -> None:
        self.payloads.append(payload)


def test_main_emits_one_info_payload_for_a_real_shaped_jsonl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tape = tmp_path / "offer_tape_2026-09-20.jsonl"
    tape.write_text(json.dumps(_row(source="quote", observed_at_ns=7)) + "\n", encoding="utf-8")
    sink = _Sink()
    monkeypatch.setattr(_DIGEST, "resolve_alert_sink", lambda env=None: sink)
    out = tmp_path / "out"
    code = _DIGEST.main(
        [
            "--tape",
            str(tape),
            "--climate-day",
            "2026-09-20",
            "--stations",
            "MIA",
            "--output-dir",
            str(out),
        ]
    )
    assert code == 0
    assert len(sink.payloads) == 1
    payload = sink.payloads[0]
    assert payload.severity == "INFO"
    assert payload.event == "decision_funnel_daily"
    assert "e=1" in payload.detail
    assert "r=0" in payload.detail
    artefact = json.loads((out / "decision_funnel_2026-09-20.json").read_text(encoding="utf-8"))
    assert artefact["totals"]["decisions_emitted"] == 1
    assert artefact["coverage_min_observed_at_ns"] == 7
    assert artefact["coverage_max_observed_at_ns"] == 7


def test_missing_tape_is_a_named_info_diagnostic_not_a_zero_funnel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = _Sink()
    monkeypatch.setattr(_DIGEST, "resolve_alert_sink", lambda env=None: sink)
    missing = tmp_path / "offer_tape_2026-09-20.jsonl"
    code = _DIGEST.main(
        [
            "--tape",
            str(missing),
            "--climate-day",
            "2026-09-20",
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    assert code == 0
    assert len(sink.payloads) == 1
    payload = sink.payloads[0]
    assert payload.severity == "INFO"
    assert payload.detail == "no decision tape found for 2026-09-20"
    assert "e=" not in payload.detail
    assert not (tmp_path / "out" / "decision_funnel_2026-09-20.json").exists()


def test_empty_tape_is_a_real_zero_funnel_distinct_from_a_missing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tape = tmp_path / "offer_tape_2026-09-20.jsonl"
    tape.write_text("", encoding="utf-8")
    sink = _Sink()
    monkeypatch.setattr(_DIGEST, "resolve_alert_sink", lambda env=None: sink)
    code = _DIGEST.main(
        [
            "--tape",
            str(tape),
            "--climate-day",
            "2026-09-20",
            "--stations",
            "MDW",
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    assert code == 0
    assert len(sink.payloads) == 1
    assert "e=0" in sink.payloads[0].detail
    assert "no decision tape found" not in sink.payloads[0].detail
    assert "stall=MDW" in sink.payloads[0].detail


# ---------------------------------------------------------------------------
# AUD-03 follow-up: `halt_enforced` (yes/no/unknown), read via the digest's
# OWN read-only sqlite connection -- never the node's exclusive submit-intent
# flock (docs/plans/backlog/AUDIT_2026-09-21/AUD-03-FOLLOWUP-a1-digest-line.md,
# coordinator build decision 2026-09-24).
# ---------------------------------------------------------------------------


def _store_with_halt_value(tmp_path: Path, raw: bytes | None) -> Path:
    store_path = tmp_path / "exec-state.db"
    store = SqliteStateStore(store_path)
    try:
        if raw is not None:
            store.set(FAMILY_HALT_KEY, raw)
    finally:
        store.close()
    return store_path


def test_read_family_halt_status_is_no_when_the_key_is_absent(tmp_path: Path) -> None:
    store_path = _store_with_halt_value(tmp_path, None)

    status = _DIGEST.read_family_halt_status(store_path)

    assert status.value == "no"
    assert status.reason is None


def test_read_family_halt_status_is_yes_when_a_halt_is_recorded(tmp_path: Path) -> None:
    store_path = _store_with_halt_value(
        tmp_path, b'{"v":1,"reason":"policy_halt","tsNs":1,"detail":"x","evidenceSha256":"a"}'
    )

    status = _DIGEST.read_family_halt_status(store_path)

    assert status.value == "yes"
    assert status.reason is None


def test_read_family_halt_status_is_no_when_the_halt_was_cleared(tmp_path: Path) -> None:
    store_path = _store_with_halt_value(tmp_path, b'{"v":1,"state":"cleared"}')

    status = _DIGEST.read_family_halt_status(store_path)

    assert status.value == "no"
    assert status.reason is None


def test_read_family_halt_status_is_unknown_when_the_store_file_is_missing(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.db"

    status = _DIGEST.read_family_halt_status(missing)

    assert status.value == "unknown"
    assert status.reason
    assert "OperationalError" in status.reason


def test_read_family_halt_status_is_unknown_when_the_stored_value_is_malformed(
    tmp_path: Path,
) -> None:
    """A real corruption/schema-drift shape: the `state` table's `value`
    column is declared BLOB, but SQLite's dynamic typing lets a raw writer
    insert TEXT -- `sqlite3` then returns a `str`, not `bytes`, and
    `decode_family_halt` must never be handed that silently."""
    store_path = tmp_path / "exec-state.db"
    conn = sqlite3.connect(store_path)
    conn.execute("CREATE TABLE state (key TEXT PRIMARY KEY, value BLOB NOT NULL)")
    conn.execute("INSERT INTO state (key, value) VALUES (?, ?)", (FAMILY_HALT_KEY, "not-bytes"))
    conn.commit()
    conn.close()

    status = _DIGEST.read_family_halt_status(store_path)

    assert status.value == "unknown"
    assert status.reason
    assert "malformed" in status.reason.lower()


def test_read_family_halt_status_is_unknown_when_locked_beyond_the_busy_timeout(
    tmp_path: Path,
) -> None:
    store_path = _store_with_halt_value(tmp_path, None)

    def _always_locked(*args: object, **kwargs: object) -> sqlite3.Connection:
        raise sqlite3.OperationalError("database is locked")

    status = _DIGEST.read_family_halt_status(store_path, connect=_always_locked)

    assert status.value == "unknown"
    assert status.reason
    assert "locked" in status.reason.lower()


def test_read_family_halt_status_never_fails_open_to_no_or_closed_to_yes_on_error(
    tmp_path: Path,
) -> None:
    """Never guess a direction on failure -- every error path lands on
    `unknown`, distinct from both `yes` and `no`."""
    missing = tmp_path / "does-not-exist.db"

    status = _DIGEST.read_family_halt_status(missing)

    assert status.value not in ("yes", "no")


def test_read_family_halt_status_succeeds_while_the_node_holds_the_submit_intent_flock(
    tmp_path: Path,
) -> None:
    """The digest's own read-only sqlite connection must never contend with
    `breezy.runtime.submit_intent`'s exclusive, node-lifetime-held flock --
    that flock lives beside the store (`<store>.intent.lock`), a different
    file from the sqlite store itself."""
    store_path = _store_with_halt_value(
        tmp_path, b'{"v":1,"reason":"policy_halt","tsNs":1,"detail":"x","evidenceSha256":"a"}'
    )

    with hold_submit_intent_process_lock(store_path):
        status = _DIGEST.read_family_halt_status(store_path)

    assert status.value == "yes"
    assert status.reason is None


# ---------------------------------------------------------------------------
# `halt_enforced` threaded into the digest's alert detail and artefact.
# ---------------------------------------------------------------------------


def test_digest_detail_reports_halt_enforced_yes() -> None:
    report = _DIGEST.funnel_for_day([_row(source="quote")])
    halt = _DIGEST.FamilyHaltStatus(value="yes", reason=None)

    detail = _DIGEST.format_digest_detail(report, climate_day="2026-09-20", halt=halt)

    assert "halt=yes" in detail
    assert len(detail) <= 200


def test_digest_detail_reports_halt_enforced_unknown_with_reason(tmp_path: Path) -> None:
    report = _DIGEST.funnel_for_day([_row(source="quote")])
    halt = _DIGEST.FamilyHaltStatus(value="unknown", reason="OperationalError: unable to open")

    detail = _DIGEST.format_digest_detail(report, climate_day="2026-09-20", halt=halt)

    assert "halt=unknown" in detail
    assert "unable to open" in detail
    assert len(detail) <= 200


def test_digest_detail_drops_the_halt_reason_before_anything_else_when_over_budget() -> None:
    """The halt reason is free text and the LOWEST-priority field: it is
    dropped first, ahead of even the existing `why=` reason tally, once the
    line would exceed MAX_ALERT_DETAIL_CHARS. `halt=<value>` itself is never
    dropped."""
    many_reasons = [
        _row(source="quote", reason=f"reason_number_{i}", illegal_cell=True) for i in range(30)
    ]
    report = _DIGEST.funnel_for_day(many_reasons)
    long_reason = "OperationalError: " + ("x" * 300)
    halt = _DIGEST.FamilyHaltStatus(value="unknown", reason=long_reason)

    detail = _DIGEST.format_digest_detail(report, climate_day="2026-09-20", halt=halt)

    assert len(detail) <= 200
    assert "halt=unknown" in detail
    assert long_reason not in detail


def test_digest_detail_omits_halt_entirely_when_none_is_passed() -> None:
    """Back-compat: existing callers that never pass `halt` see no field."""
    report = _DIGEST.funnel_for_day([_row(source="quote")])

    detail = _DIGEST.format_digest_detail(report, climate_day="2026-09-20")

    assert "halt=" not in detail


def test_main_reports_halt_enforced_unknown_when_the_store_path_does_not_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tape = tmp_path / "offer_tape_2026-09-20.jsonl"
    tape.write_text(json.dumps(_row(source="quote", observed_at_ns=7)) + "\n", encoding="utf-8")
    sink = _Sink()
    monkeypatch.setattr(_DIGEST, "resolve_alert_sink", lambda env=None: sink)
    out = tmp_path / "out"
    missing_store = tmp_path / "does-not-exist.db"

    code = _DIGEST.main(
        [
            "--tape", str(tape),
            "--climate-day", "2026-09-20",
            "--stations", "MIA",
            "--output-dir", str(out),
            "--store-path", str(missing_store),
        ]
    )

    assert code == 0
    payload = sink.payloads[0]
    assert "halt=unknown" in payload.detail
    artefact = json.loads((out / "decision_funnel_2026-09-20.json").read_text(encoding="utf-8"))
    assert artefact["halt_enforced"] == "unknown"
    assert artefact["halt_reason"]


def test_main_reports_halt_enforced_yes_from_a_real_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tape = tmp_path / "offer_tape_2026-09-20.jsonl"
    tape.write_text(json.dumps(_row(source="quote", observed_at_ns=7)) + "\n", encoding="utf-8")
    sink = _Sink()
    monkeypatch.setattr(_DIGEST, "resolve_alert_sink", lambda env=None: sink)
    out = tmp_path / "out"
    store_path = _store_with_halt_value(
        tmp_path, b'{"v":1,"reason":"policy_halt","tsNs":1,"detail":"x","evidenceSha256":"a"}'
    )

    code = _DIGEST.main(
        [
            "--tape", str(tape),
            "--climate-day", "2026-09-20",
            "--stations", "MIA",
            "--output-dir", str(out),
            "--store-path", str(store_path),
        ]
    )

    assert code == 0
    payload = sink.payloads[0]
    assert "halt=yes" in payload.detail
    artefact = json.loads((out / "decision_funnel_2026-09-20.json").read_text(encoding="utf-8"))
    assert artefact["halt_enforced"] == "yes"
    assert artefact["halt_reason"] is None
