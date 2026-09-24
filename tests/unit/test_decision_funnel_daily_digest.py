"""AUD-03: daily decision-funnel digest over the offer-tape JSONL sidecar.

Pure aggregation tests pin the live stage rule and the closed ``source``
allow-list. Nothing here opens a socket, reads the live tape, or touches
the node.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

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
