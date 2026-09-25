"""F-3: `measured_slippage_from_fills.py`'s reader must count identically
before and after `decisions_retention.py` gzips a day's tape (R5)."""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts" / "analysis").as_posix())
sys.path.insert(0, (REPO_ROOT / "scripts" / "ops").as_posix())

from decisions_retention import gzip_eligible_files
from measured_slippage_from_fills import (
    count_refused_priced_offer_tape_records,
    glob_offer_tape_paths,
)

from breezy.strategy.current_rung_hold.offer_tape import OfferTapeRecord

_NOW = dt.datetime(2026, 9, 25, 12, 0, 0, tzinfo=dt.UTC)


def _record(*, instrument_id: str, ask: str | None, decision: str) -> OfferTapeRecord:
    return OfferTapeRecord(
        station="LAX", climate_day="2026-09-01", instrument_id=instrument_id, ask=ask,
        size=1, reason="not_executable", ts_event=1, hour_lst=10, width_code=1,
        m_code=1, trigger="tick", quote_age_ns=1, minutes_since_window_open=1,
        prior_eligible_snaps=0, illegal_cell=False, source="quote_tick",
        decision=decision,
    )


def test_offer_tape_counts_equal_before_and_after_retention(tmp_path: Path) -> None:
    records = [
        _record(instrument_id="i1", ask="0.40", decision="refuse"),
        _record(instrument_id="i2", ask=None, decision="refuse"),
        _record(instrument_id="i3", ask="0.30", decision="take"),
        _record(instrument_id="i4", ask="0.55", decision="refuse"),
    ]
    path = tmp_path / "offer_tape_2026-09-01.jsonl"
    path.write_text(
        "\n".join(json.dumps(r.to_dict()) for r in records) + "\n", encoding="utf-8"
    )
    old_mtime = (_NOW - dt.timedelta(days=10)).timestamp()
    os.utime(path, (old_mtime, old_mtime))

    before_paths = glob_offer_tape_paths(tmp_path)
    before_counts = count_refused_priced_offer_tape_records(before_paths)
    assert before_counts == {"offer_tape_2026-09-01.jsonl": 2}

    outcome = gzip_eligible_files(tmp_path, older_than_days=7, now=_NOW)
    assert outcome.gzipped == ("offer_tape_2026-09-01.jsonl",)
    assert not path.exists()

    after_paths = glob_offer_tape_paths(tmp_path)
    after_counts = count_refused_priced_offer_tape_records(after_paths)

    assert [p.name for p in after_paths] == ["offer_tape_2026-09-01.jsonl.gz"]
    assert sum(after_counts.values()) == sum(before_counts.values())
    assert after_counts == {"offer_tape_2026-09-01.jsonl.gz": 2}
