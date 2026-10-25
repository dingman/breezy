"""MAKER_POST appends the posted rung's p_NO, ceiling, edge slack and forecast cycle."""

from __future__ import annotations

from breezy.strategy.ladder_ev.forecast_state import ForecastQuantileVector
from breezy.strategy.no_ladder_maker import rule
from breezy.strategy.no_ladder_maker.pno import PNoAtInstant
from breezy.strategy.no_ladder_maker.pno_store import PNoStore
from breezy.strategy.no_ladder_maker.records import Decision, DecisionContext, DepthFrame
from breezy.strategy.no_ladder_maker.selector import (
    RungPricer,
    SelectorConfig,
    _Memo,
    _priced,
    _quote,
)
from tests.strategy.no_ladder_maker.maker_strategy_support import (
    NOW_NS,
    Harness,
    cents_of,
    identity_calibration,
    want,
)
from tests.support.nautilus_log_capture import capture_nautilus_logs, wait_for_logged

_EXISTING_KEYS = ("station", "day", "rung", "bid_cents", "expire_ns", "client_order_id")
_EVIDENCE_KEYS = ("p_no", "b_max", "edge_slack", "cycle_ns")
_CYCLE_NS = 1_759_000_000_000_000_000
_TARGET_P_YES = 0.02


def _maker_post(err: str) -> dict[str, str]:
    """The one ``MAKER_POST`` payload. Nautilus writes it to stderr, prefix and all."""
    posts = [line for line in err.splitlines() if "MAKER_POST " in line]
    assert len(posts) == 1, posts or err
    payload = posts[0].split("MAKER_POST ", 1)[1]
    fields: dict[str, str] = {}
    for part in payload.split():
        key, value = part.split("=", 1)
        fields[key] = value
    return fields


def _decision_for(h: Harness, target: str) -> Decision:
    """One real ``_priced`` decision: only ``target`` is booked, so it is the only post."""
    edges = {rung.rung_id: rung.lower_edge_f for rung in h.ladder.rungs.values()}
    modal = h.rung("gte70lt71f")
    p_yes = {rung_id: 0.5 if rung_id == modal else 0.05 for rung_id in edges}
    p_yes[target] = _TARGET_P_YES
    theta = h.strategy._theta
    params = h.strategy._params
    frame = DepthFrame(rung_id=target, ts_ns=NOW_NS, yes_bids=((5, 10),), yes_asks=((12, 10),))
    served = PNoAtInstant(
        p_yes_point_live=p_yes,
        bounds={},
        cycle=_CYCLE_NS,
        available_at_ns=NOW_NS - 1,
        vintage_age_s=1.0,
        vector=ForecastQuantileVector(
            q10=70.0,
            q25=71.0,
            q50=72.0,
            q75=73.0,
            q90=74.0,
            mean=72.0,
            sd=1.0,
            available_at_ns=NOW_NS - 1,
            cycle_runtime_ns=_CYCLE_NS,
            climate_day=h.day,
        ),
    )
    cfg = SelectorConfig(
        store=PNoStore({}, frozenset(), identity_calibration(), {}),
        station="SFO",
        day=h.day,
        stress="none",
        delta_ns=0,
        theta=theta,
        lower_edges_f=edges,
        params=params,
    )
    ctx = DecisionContext(
        now_ns=NOW_NS,
        books={target: frame},
        live_bids={},
        held=frozenset(),
    )
    return _priced(cfg, None, _Memo(RungPricer(theta, _quote, params)), ctx, served)


def test_maker_post_logs_p_no_b_max_slack_and_cycle_with_bid_cents_unchanged() -> None:
    h = Harness()
    target = h.rung("lt66f")
    decision = _decision_for(h, target)
    (desired,) = decision.desired
    h.install(lambda _ctx: decision)
    read_logs = capture_nautilus_logs()
    h.book("lt66f", bids=(("0.05", 10),), asks=(("0.12", 10),))
    (submit,) = h.submits(h.drain())

    fields = _maker_post(wait_for_logged(read_logs, "MAKER_POST "))
    assert tuple(fields) == (*_EXISTING_KEYS, *_EVIDENCE_KEYS)
    assert fields["bid_cents"] == str(cents_of(submit)) == str(desired.bid_cents)
    assert fields["rung"] == target
    p_no = 1.0 - _TARGET_P_YES
    cap = rule.b_max(p_no, h.strategy._theta, h.strategy._params)
    assert cap is not None
    bid = desired.bid_cents / 100
    slack = p_no - bid - h.strategy._theta * bid * (1.0 - bid)
    assert fields["p_no"] == f"{p_no:.4f}"
    assert fields["b_max"] == f"{cap:.2f}"
    assert fields["edge_slack"] == f"{slack:.4f}"
    assert fields["cycle_ns"] == str(_CYCLE_NS)


def test_maker_post_logs_na_when_evidence_is_missing() -> None:
    h = Harness()
    rung = h.rung("gte72lt73f")
    h.install(lambda _ctx: want((rung, 89)))
    read_logs = capture_nautilus_logs()
    h.book("gte72lt73f")
    (submit,) = h.submits(h.drain())

    fields = _maker_post(wait_for_logged(read_logs, "MAKER_POST "))
    assert tuple(fields) == (*_EXISTING_KEYS, *_EVIDENCE_KEYS)
    assert fields["bid_cents"] == "89" == str(cents_of(submit))
    assert [fields[key] for key in _EVIDENCE_KEYS] == ["na", "na", "na", "na"]
