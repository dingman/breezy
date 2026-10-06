"""AUT-2 r7 WP3 / section 3.4.4: the backfill-only decision bridge over the node's log FILES.

The bridge keys on ``client_order_id`` inside bounded windows and never on line adjacency. It runs
only for PRE_EPOCH fills; a POST_EPOCH fill is attributed through C1 and nothing else (Q2).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.analysis.labeling.attribution import BackfillRefused
from breezy.analysis.labeling.decision_link import (
    BridgeEvent,
    BridgeMatch,
    BridgeUnmatched,
    bridge_decision,
    bridge_report,
    parse_log_line,
    read_log_events,
)
from breezy.analysis.labeling.epoch import EpochClass
from tests.support.aut2_fixtures import DurableFillRecord, durable_fill

SLUG = "tc-temp-laxhigh-2026-10-02-gte89lt90f"
YES = f"{SLUG}.POLYMARKET_US"
NO = f"{SLUG}^no.POLYMARKET_US"
_BASE = dt.datetime(2026, 10, 1, 16, 2, 5, tzinfo=dt.UTC)
_ESC = "\x1b[1m"
_END = "\x1b[0m"


def _ts(offset_s: float) -> str:
    moment = _BASE + dt.timedelta(seconds=offset_s)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond:06d}000Z"


def _ns(offset_s: float) -> int:
    moment = _BASE + dt.timedelta(seconds=offset_s)
    epoch = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)
    delta = moment - epoch
    return (delta.days * 86400 + delta.seconds) * 10**9 + delta.microseconds * 1000


def _take(offset_s: float, *, instrument: str = YES, side: str = "yes", p_hat: str = "0.38") -> str:
    return (
        f"{_ESC}{_ts(offset_s)}{_END} [INFO] BREEZY-L001.FORECAST-QUANTILE-LADDER: "
        f"SHADOW_DECISION {{'now_ns': {_ns(offset_s)}, 'station': 'LAX', "
        f"'climate_day': datetime.date(2026, 10, 2), 'rung_id': '89_90', 'side': '{side}', "
        f"'instrument_id': '{instrument}', 'kind': 'Take', 'qty': 1, 'ev_net': 0.09, "
        f"'p_hat': {p_hat}, 'p_lower': 0.34, 'p_upper': 0.42}}{_END}"
    )


def _init(offset_s: float, coid: str = "O-1", instrument: str = YES) -> str:
    return (
        f"{_ESC}{_ts(offset_s)}{_END} [INFO] BREEZY-L001.FORECAST-QUANTILE-LADDER: <--[EVT] "
        f"OrderInitialized(instrument_id={instrument}, client_order_id={coid}, side=BUY, "
        f"type=LIMIT, quantity=1.00, time_in_force=IOC)"
    )


def _filled(offset_s: float, coid: str = "O-1", trade: str = "T-1", instrument: str = YES) -> str:
    return (
        f"{_ESC}{_ts(offset_s)}{_END} [INFO] BREEZY-L001.FORECAST-QUANTILE-LADDER: <--[EVT] "
        f"OrderFilled(instrument_id={instrument}, client_order_id={coid}, venue_order_id=V1, "
        f"account_id=A, trade_id={trade}, order_side=BUY, last_qty=1.00, last_px=0.40 USD)"
    )


def _events(*lines: str) -> tuple[BridgeEvent, ...]:
    parsed = [parse_log_line(line) for line in lines]
    return tuple(event for event in parsed if event is not None)


def _fill(coid: str = "O-1", trade: str | None = "T-1", instrument: str = YES) -> DurableFillRecord:
    return durable_fill(client_order_id=coid, trade_id=trade, instrument_id=instrument)


def _bridge(
    events: Sequence[BridgeEvent],
    fill: DurableFillRecord | None = None,
    recalibration: str = "none",
) -> BridgeMatch | BridgeUnmatched:
    return bridge_decision(
        fill or _fill(), events, epoch_class=EpochClass.PRE_EPOCH, recalibration=recalibration
    )


def test_bridge_joins_on_client_order_id_not_adjacency() -> None:
    noise = _init(100.5, coid="O-other")
    events = _events(_take(10), noise, _init(11), _take(50, p_hat="0.99"), _filled(12))

    result = _bridge(events)

    assert isinstance(result, BridgeMatch)
    assert result.p_at_decision == pytest.approx(0.38)


def test_bridge_window_bounds_enforced() -> None:
    inside = _events(_take(8.0), _init(10.0), _filled(309.9))
    too_old_init = _events(_take(8.0), _init(10.0), _filled(310.5))
    take_too_early = _events(_take(7.9), _init(10.0), _filled(12))

    assert isinstance(_bridge(inside), BridgeMatch)
    assert isinstance(_bridge(too_old_init), BridgeUnmatched)
    assert isinstance(_bridge(take_too_early), BridgeUnmatched)


def test_two_takes_in_window_unmatched() -> None:
    result = _bridge(_events(_take(9.0), _take(9.5, p_hat="0.31"), _init(10), _filled(11)))

    assert isinstance(result, BridgeUnmatched)
    assert result.reason == "ambiguous_takes"


def test_take_after_init_is_not_linked() -> None:
    result = _bridge(_events(_init(10), _take(10.5), _filled(11)))

    assert isinstance(result, BridgeUnmatched)
    assert result.reason == "no_take_in_window"


def test_unmatched_fill_p_source_none() -> None:
    result = _bridge(_events(_init(10), _filled(11)))

    assert isinstance(result, BridgeUnmatched)
    assert result.p_source == "none"
    matched = _bridge(_events(_take(9), _init(10), _filled(11)))
    assert isinstance(matched, BridgeMatch) and matched.p_source == "artefact_recompute"


def test_unmatched_fill_increments_p_null_count() -> None:
    matched = _bridge(_events(_take(9), _init(10), _filled(11)))
    unmatched = _bridge(_events(_init(10), _filled(11)))
    report = bridge_report([matched, unmatched, unmatched])

    assert (report.n, report.matched, report.p_null_count) == (3, 1, 2)


def test_bridge_match_rate_reported_for_backfill() -> None:
    matched = _bridge(_events(_take(9), _init(10), _filled(11)))
    unmatched = _bridge(_events(_init(10), _filled(11)))

    assert bridge_report([matched, unmatched, matched, matched]).match_rate == Decimal("0.75")
    assert bridge_report([]).match_rate is None


def test_bridge_never_runs_on_post_epoch_fills() -> None:
    events = _events(_take(9), _init(10), _filled(11))

    with pytest.raises(BackfillRefused):
        bridge_decision(_fill(), events, epoch_class=EpochClass.POST_EPOCH, recalibration="none")


def test_a_take_whose_side_disagrees_with_the_fill_leg_is_unmatched() -> None:
    events = _events(_take(9, side="no"), _init(10, instrument=NO), _filled(11, instrument=NO))
    # a NO-side take against a YES fill
    wrong = _bridge(_events(_take(9, side="no"), _init(10), _filled(11)))

    assert isinstance(wrong, BridgeUnmatched) and wrong.reason == "side_leg_mismatch"
    right = _bridge(events, fill=_fill(instrument=NO))
    assert isinstance(right, BridgeMatch) and right.p_at_decision == pytest.approx(0.62)


def test_p_raw_is_known_only_when_the_artefact_recalibration_is_none() -> None:
    events = _events(_take(9), _init(10), _filled(11))
    plain = _bridge(events, recalibration="none")
    recal = _bridge(events, recalibration="isotonic")

    assert isinstance(plain, BridgeMatch) and plain.p_raw_at_decision == pytest.approx(0.38)
    assert isinstance(recal, BridgeMatch) and recal.p_raw_at_decision is None


def test_a_fill_without_a_trade_id_is_unmatched() -> None:
    result = _bridge(_events(_take(9), _init(10), _filled(11)), fill=_fill(trade=None))

    assert isinstance(result, BridgeUnmatched) and result.reason == "no_trade_id"


def test_real_default_log_reader_on_tmp_file(tmp_path: Path) -> None:
    log = tmp_path / "breezy-trade-20261001T160158Z.log"
    log.write_text(
        "\n".join(
            [
                "unrelated line",
                _take(9),
                _init(10),
                _filled(11),
                "BREEZY-NWS subscribe error (cosmetic)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    events = read_log_events([log])

    assert [event.kind for event in events] == ["take", "init", "filled"]
    assert events[1].ts_ns == _ns(10) and events[1].client_order_id == "O-1"
    assert isinstance(_bridge(events), BridgeMatch)


def test_parse_log_line_ignores_non_decision_shadow_lines() -> None:
    refuse = _take(9).replace("'kind': 'Take'", "'kind': 'Refuse'")

    assert parse_log_line(refuse) is None
    assert parse_log_line("") is None
