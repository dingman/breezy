"""RED-first tests for AUD-12a's measured-slippage script (plan §7 step 1).

Fixtures build real `DurableFillRecord`/`TrialDayRecord` byte payloads and
write them into a throwaway sqlite `state(key, value)` table -- the exact
schema `_open_readonly` and the live exec `SqliteStateStore` share -- so the
read path under test is the real decode path, never a hand-rolled stand-in.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
from breezy.strategy.current_rung_hold.offer_tape import OfferTapeRecord
from breezy.strategy.current_rung_hold.trial_day_latch import TrialDayRecord

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

from measured_slippage_from_fills import (
    DEFAULT_FAMILY_PREFIX,
    MeasuredSlippage,
    SlippageSourceUnreadableError,
    count_refused_priced_offer_tape_records,
    join_fills_to_decision_ask,
    read_fill_records,
    read_taken_trial_records_by_venue_order_id,
    render_evidence_doc,
    summarize_slippage,
)


def _fill(
    *,
    venue_order_id: str,
    instrument_id: str = "tc-temp-laxhigh-2026-09-01-gte78lt80f.POLYMARKET_US",
    px: str,
) -> DurableFillRecord:
    return DurableFillRecord(
        venue_order_id=venue_order_id,
        client_order_id=f"client-{venue_order_id}",
        instrument_id=instrument_id,
        order_side="BUY",
        cumulative_qty=Decimal(1),
        cumulative_cost=Decimal(px),
        cumulative_fee=Decimal("0.01"),
        fee_reconciled=True,
        ts_event=1,
    )


def _trial(*, venue_order_id: str, ask: str, reason: str = "taken") -> TrialDayRecord:
    return TrialDayRecord(
        latched_at_ns=1,
        instrument_id="tc-temp-laxhigh-2026-09-01-gte78lt80f.POLYMARKET_US",
        ask=Decimal(ask),
        reason=reason,
        venue_order_id=venue_order_id,
    )


def _write_state_db(path: Path, rows: dict[str, bytes]) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE state (key TEXT PRIMARY KEY, value BLOB)")
    conn.executemany("INSERT INTO state (key, value) VALUES (?, ?)", rows.items())
    conn.commit()
    conn.close()


class TestJoinFillsToDecisionAsk:
    def test_computes_expected_slippage_for_a_normal_fill(self) -> None:
        fill = _fill(venue_order_id="V1", px="0.45")
        trial = _trial(venue_order_id="V1", ask="0.40")

        measurements, unresolved = join_fills_to_decision_ask([fill], {"V1": trial})

        assert unresolved == ()
        assert len(measurements) == 1
        m = measurements[0]
        assert m.decision_ask == Decimal("0.40")
        assert m.fill_px == Decimal("0.45")
        assert m.slippage == Decimal("0.05")
        assert m.flagged is False

    def test_flags_a_fill_better_than_ask_as_suspect(self) -> None:
        fill = _fill(venue_order_id="V2", px="0.30")
        trial = _trial(venue_order_id="V2", ask="0.40")

        measurements, _ = join_fills_to_decision_ask([fill], {"V2": trial})

        assert len(measurements) == 1
        m = measurements[0]
        assert m.slippage == Decimal("-0.10")
        assert m.flagged is True

    def test_a_fill_with_no_matching_taken_trial_is_reported_unresolved(self) -> None:
        fill = _fill(venue_order_id="V3", px="0.30")

        measurements, unresolved = join_fills_to_decision_ask([fill], {})

        assert measurements == ()
        assert unresolved == ("V3",)


class TestSummarizeSlippage:
    def test_flagged_fill_excluded_from_aggregate_but_still_counted_and_reported(self) -> None:
        normal = MeasuredSlippage(
            venue_order_id="V1", instrument_id="i1",
            decision_ask=Decimal("0.40"), fill_px=Decimal("0.45"),
            slippage=Decimal("0.05"), flagged=False,
        )
        suspect = MeasuredSlippage(
            venue_order_id="V2", instrument_id="i2",
            decision_ask=Decimal("0.40"), fill_px=Decimal("0.30"),
            slippage=Decimal("-0.10"), flagged=True,
        )

        summary = summarize_slippage([normal, suspect], unresolved_venue_order_ids=())

        assert summary.included == (normal,)
        assert summary.flagged == (suspect,)
        assert summary.mean == Decimal("0.05")
        assert summary.median == Decimal("0.05")
        assert summary.minimum == Decimal("0.05")
        assert summary.maximum == Decimal("0.05")

    def test_mean_and_median_over_multiple_included_fills(self) -> None:
        m1 = MeasuredSlippage(
            venue_order_id="V1", instrument_id="i1",
            decision_ask=Decimal("0.40"), fill_px=Decimal("0.40"),
            slippage=Decimal("0.00"), flagged=False,
        )
        m2 = MeasuredSlippage(
            venue_order_id="V2", instrument_id="i2",
            decision_ask=Decimal("0.40"), fill_px=Decimal("0.42"),
            slippage=Decimal("0.02"), flagged=False,
        )

        summary = summarize_slippage([m1, m2])

        assert summary.mean == Decimal("0.01")
        assert summary.median == Decimal("0.01")
        assert summary.minimum == Decimal("0.00")
        assert summary.maximum == Decimal("0.02")

    def test_all_flagged_yields_no_aggregate_but_is_not_silently_dropped(self) -> None:
        suspect = MeasuredSlippage(
            venue_order_id="V1", instrument_id="i1",
            decision_ask=Decimal("0.40"), fill_px=Decimal("0.30"),
            slippage=Decimal("-0.10"), flagged=True,
        )

        summary = summarize_slippage([suspect])

        assert summary.included == ()
        assert summary.flagged == (suspect,)
        assert summary.mean is None
        assert summary.median is None


class TestReadFillRecords:
    def test_reads_only_fill_prefixed_keys_read_only(self, tmp_path: Path) -> None:
        fill = _fill(venue_order_id="V1", px="0.45")
        db_path = tmp_path / "exec.sqlite"
        _write_state_db(
            db_path,
            {
                f"exec/polymarket_us/fill/{fill.venue_order_id}": fill.to_bytes(),
                "exec/polymarket_us/intent/current": b"{}",
            },
        )

        fills = read_fill_records(db_path)

        assert len(fills) == 1
        assert fills[0].venue_order_id == "V1"

    def test_missing_db_raises_unreadable_error(self, tmp_path: Path) -> None:
        with pytest.raises(SlippageSourceUnreadableError):
            read_fill_records(tmp_path / "does-not-exist.sqlite")


class TestReadTakenTrialRecords:
    def test_skips_non_taken_and_missing_venue_order_id(self, tmp_path: Path) -> None:
        taken = _trial(venue_order_id="V1", ask="0.40")
        refused = TrialDayRecord(
            latched_at_ns=1, instrument_id="i2", ask=Decimal("0.10"),
            reason="not_executable",
        )
        no_venue_order_id = TrialDayRecord(
            latched_at_ns=1, instrument_id="i3", ask=Decimal("0.20"), reason="taken",
        )
        db_path = tmp_path / "exec.sqlite"
        _write_state_db(
            db_path,
            {
                f"{DEFAULT_FAMILY_PREFIX}LAX/2026-09-01/i1": taken.to_bytes(),
                f"{DEFAULT_FAMILY_PREFIX}LAX/2026-09-02/i2": refused.to_bytes(),
                f"{DEFAULT_FAMILY_PREFIX}LAX/2026-09-03/i3": no_venue_order_id.to_bytes(),
            },
        )

        by_id = read_taken_trial_records_by_venue_order_id(db_path)

        assert set(by_id) == {"V1"}
        assert by_id["V1"].ask == Decimal("0.40")


class TestCountRefusedPricedOfferTapeRecords:
    def test_counts_only_refuse_with_a_non_null_ask(self, tmp_path: Path) -> None:
        refuse_priced = OfferTapeRecord(
            station="LAX", climate_day="2026-09-01", instrument_id="i1", ask="0.40",
            size=10, reason="not_executable", ts_event=1, hour_lst=10, width_code=1,
            m_code=1, trigger="tick", quote_age_ns=1, minutes_since_window_open=1,
            prior_eligible_snaps=0, illegal_cell=False, source="quote_tick",
            decision="refuse",
        )
        refuse_unpriced = OfferTapeRecord(
            station="LAX", climate_day="2026-09-01", instrument_id="i2", ask=None,
            size=0, reason="observation_unavailable", ts_event=1, hour_lst=10,
            width_code=1, m_code=1, trigger="tick", quote_age_ns=None,
            minutes_since_window_open=1, prior_eligible_snaps=0, illegal_cell=False,
            source="quote_tick", decision="refuse",
        )
        taken = OfferTapeRecord(
            station="LAX", climate_day="2026-09-01", instrument_id="i3", ask="0.30",
            size=1, reason="taken", ts_event=1, hour_lst=10, width_code=1, m_code=1,
            trigger="tick", quote_age_ns=1, minutes_since_window_open=1,
            prior_eligible_snaps=0, illegal_cell=False, source="quote_tick",
            decision="take",
        )
        path = tmp_path / "offer_tape_2026-09-01.jsonl"
        path.write_text(
            "\n".join(
                json.dumps(r.to_dict())
                for r in (refuse_priced, refuse_unpriced, taken)
            )
            + "\n",
            encoding="utf-8",
        )

        counts = count_refused_priced_offer_tape_records([path])

        assert counts == {"offer_tape_2026-09-01.jsonl": 1}

    def test_reads_a_gzipped_tape_transparently(self, tmp_path: Path) -> None:
        """F-3 R5: `measured_slippage_from_fills.py:487`'s reader must handle
        `.jsonl.gz` produced by retention -- same decode path, same counts."""
        import gzip

        refuse_priced = OfferTapeRecord(
            station="LAX", climate_day="2026-09-01", instrument_id="i1", ask="0.40",
            size=10, reason="not_executable", ts_event=1, hour_lst=10, width_code=1,
            m_code=1, trigger="tick", quote_age_ns=1, minutes_since_window_open=1,
            prior_eligible_snaps=0, illegal_cell=False, source="quote_tick",
            decision="refuse",
        )
        path = tmp_path / "offer_tape_2026-09-01.jsonl.gz"
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write(json.dumps(refuse_priced.to_dict()) + "\n")

        counts = count_refused_priced_offer_tape_records([path])

        assert counts == {"offer_tape_2026-09-01.jsonl.gz": 1}


class TestGlobOfferTapePathsDedup:
    def test_dedupes_by_date_preferring_jsonl_over_gz(self, tmp_path: Path) -> None:
        """F-3 R5/AC7: `main`'s glob must cover both `offer_tape_*.jsonl` and
        `offer_tape_*.jsonl.gz`, and when the SAME date has both (the crash
        window between retention's rename and unlink), the plain `.jsonl` is
        the one counted -- never both, never the `.gz`."""
        from measured_slippage_from_fills import glob_offer_tape_paths

        (tmp_path / "offer_tape_2026-09-01.jsonl").write_text("", encoding="utf-8")
        (tmp_path / "offer_tape_2026-09-01.jsonl.gz").write_text("", encoding="utf-8")
        (tmp_path / "offer_tape_2026-09-02.jsonl.gz").write_text("", encoding="utf-8")

        paths = glob_offer_tape_paths(tmp_path)

        assert [p.name for p in paths] == [
            "offer_tape_2026-09-01.jsonl",
            "offer_tape_2026-09-02.jsonl.gz",
        ]


class TestRenderEvidenceDoc:
    def test_includes_the_required_honesty_and_scope_statements(self) -> None:
        m = MeasuredSlippage(
            venue_order_id="V1", instrument_id="i1",
            decision_ask=Decimal("0.40"), fill_px=Decimal("0.40"),
            slippage=Decimal("0.00"), flagged=False,
        )
        summary = summarize_slippage([m], unresolved_venue_order_ids=("V-missing",))

        doc = render_evidence_doc(
            summary,
            offer_tape_counts={"offer_tape_2026-09-24.jsonl": 5},
            family_prefix=DEFAULT_FAMILY_PREFIX,
            run_date="2026-09-24",
        )

        assert "n=1" in doc or "1 included" in doc
        assert "cannot support" in doc
        assert "fills-derived" in doc
        assert "cli_received_ts" in doc
        assert "seven" in doc.lower()
        assert "V-missing" in doc
        assert "5" in doc
