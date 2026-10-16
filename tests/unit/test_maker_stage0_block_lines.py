"""MAKER-S2 second look C5r: block-driven holdout / D5 disclosure lines (plan r3 D7)."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from scripts.analysis import maker_stage0_render as render
from scripts.analysis.maker_stage0_block_lines import block_lines

_S, _E = dt.date(2026, 10, 14), dt.date(2026, 10, 20)
_PINS = {
    "git_commit": "c0",
    "amendment_final_sha256": "a0",
    "truth_csv_sha256_frozen_block": "t0",
    "nbp_consumed": {"sha256": "n0"},
    "installed_package_set_sha256": "p0",
    "ledger_path": "ledger",
    "theta_pin_site": "fees.py",
    "sidecars": {},
}


def _v2() -> SimpleNamespace:
    days = tuple(_S + dt.timedelta(days=i) for i in range((_E - _S).days + 1))
    return SimpleNamespace(block=2, dates=days, trigger_day=_S)


def _now(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(12), tzinfo=dt.UTC)


def test_v1_block_lines_are_the_constants() -> None:
    v1 = SimpleNamespace(block=1, dates=(dt.date(2026, 9, 18),))
    assert block_lines(v1) == (render.HOLDOUT_LINE, render._D5)
    assert block_lines(SimpleNamespace(dates=())) == (render.HOLDOUT_LINE, render._D5)  # no field
    assert block_lines(v1, now=_now(dt.date(2030, 1, 1))) == (render.HOLDOUT_LINE, render._D5)


def test_holdout_line_reflects_the_block() -> None:
    holdout, _ = block_lines(_v2(), now=_now(_E))
    assert holdout != render.HOLDOUT_LINE
    for phrase in (
        "2026-10-14..2026-10-20",
        "forward data",
        "no tail-day read",
        "AUT-4",
        "never calls open_holdout",
        "2026-10-03",
    ):
        assert phrase in holdout
    assert "2026-09-18" not in holdout and "2026-07-01" not in holdout


def test_d5_disclosure_reflects_the_block_and_d14_status() -> None:
    # past D+14 <=> day + 14 < today. now = E: 10-14 + 14 = 10-28 >= 10-20, none past.
    _, early = block_lines(_v2(), now=_now(_E))
    assert "2026-10-14..2026-10-20" in early and "7 of 7 block days" in early
    # now = 10-30: 10-14 (10-28) and 10-15 (10-29) are past D+14 -> 5 not yet past.
    _, mid = block_lines(_v2(), now=_now(dt.date(2026, 10, 30)))
    assert "5 of 7 block days" in mid and "not yet past D+14" in mid
    _, late = block_lines(_v2(), now=_now(dt.date(2027, 1, 1)))
    assert "0 of 7 block days" in late
    assert "2026-09-18" not in early and "bucket_facts_from_instrument_id" in early


def test_render_stop_report_threads_the_supplied_lines() -> None:
    holdout, d5 = block_lines(_v2(), now=_now(_E))
    text = render.render_stop_report(
        _PINS,
        run_id="r",
        reason="why",
        disclosures=render.Disclosures(),
        holdout_line=holdout,
        d5_line=d5,
    )
    assert holdout in text and d5 in text and render.HOLDOUT_LINE not in text
    default = render.render_stop_report(
        _PINS, run_id="r", reason="why", disclosures=render.Disclosures()
    )
    assert render.HOLDOUT_LINE in default and render._D5 in default
