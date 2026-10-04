"""Shared fixtures for the node-log parser tests: REAL retained lines (see each constant) and
small builders. Lines come from ``~/.local/share/breezy/logs/`` unless marked CONSTRUCTED."""

import datetime as dt
from pathlib import Path
from typing import Final

from breezy.analysis import capture_node_log as nl

ANSI_ON: Final[str] = "\x1b[1m"
ANSI_OFF: Final[str] = "\x1b[0m"

# --- REAL lines: breezy-trade-20261002T200526Z.log (ANSI as written by Nautilus) ---------------
REAL_TAKE: Final[str] = (
    f"{ANSI_ON}2026-10-02T20:20:32.924873907Z{ANSI_OFF} [INFO] "
    "BREEZY-L001.FORECAST-QUANTILE-LADDER: SHADOW_DECISION {'now_ns': 1790972432790092624, "
    "'station': 'LAX', 'climate_day': datetime.date(2026, 10, 3), 'rung_id': '93_94', "
    "'side': 'yes', 'instrument_id': 'tc-temp-laxhigh-2026-10-03-gte93lt94f.POLYMARKET_US', "
    "'kind': 'Take', 'qty': 1, 'ev_net': 0.06568776856525851, 'p_hat': 0.2538513678202191, "
    f"'p_lower': 0.2345490185652585, 'p_upper': 0.27614249327505075}}{ANSI_OFF}"
)
REAL_TRY_SUBMIT: Final[str] = (
    f"{ANSI_ON}2026-10-02T20:20:32.924972237Z{ANSI_OFF} [INFO] "
    "BREEZY-L001.FORECAST-QUANTILE-LADDER: SHADOW_DECISION {'now_ns': 1790972432924965987, "
    "'station': 'LAX', 'climate_day': datetime.date(2026, 10, 3), 'rung_id': '93_94', "
    "'side': 'yes', 'instrument_id': 'tc-temp-laxhigh-2026-10-03-gte93lt94f.POLYMARKET_US', "
    f"'kind': 'TrySubmit', 'reason': 'submitted'}}{ANSI_OFF}"
)
REAL_REFUSE: Final[str] = (
    f"{ANSI_ON}2026-10-02T20:05:32.018121135Z{ANSI_OFF} [INFO] "
    "BREEZY-L001.FORECAST-QUANTILE-LADDER: SHADOW_DECISION {'now_ns': 1790971531951257557, "
    "'station': 'MDW', 'climate_day': datetime.date(2026, 10, 3), 'rung_id': 'lt_63', "
    "'side': 'yes', 'instrument_id': 'tc-temp-mdwhigh-2026-10-03-lt64f.POLYMARKET_US', "
    f"'kind': 'Refuse', 'reason': 'forecast_unavailable'}}{ANSI_OFF}"
)
REAL_ORDER_FILLED: Final[str] = (
    f"{ANSI_ON}2026-10-02T20:20:33.123853693Z{ANSI_OFF} [INFO] "
    "BREEZY-L001.FORECAST-QUANTILE-LADDER: <--[EVT] OrderFilled("
    "instrument_id=tc-temp-laxhigh-2026-10-03-gte93lt94f.POLYMARKET_US, "
    "client_order_id=O-20261002-202032-L001-LAX-1, venue_order_id=CVW455HKJYGE, "
    "account_id=POLYMARKET_US-MAIN, trade_id=CVWEANWH8YHR, "
    "position_id=tc-temp-laxhigh-2026-10-03-gte93lt94f.POLYMARKET_US-FORECAST-QUANTILE-LADDER-LAX, "
    "order_side=BUY, order_type=LIMIT, last_qty=1.00, last_px=0.15 USD, commission=0.01 USD, "
    f"liquidity_side=TAKER, ts_event=1790972433034078620){ANSI_OFF}"
)
REAL_INSTANCE_ID: Final[str] = (
    f"{ANSI_ON}2026-10-02T20:05:30.434292449Z{ANSI_OFF} [INFO] "
    f"BREEZY-L001.TradingNode: instance_id: 01cea9fc-cf7d-4efa-b132-cbbaf5d0bde4{ANSI_OFF}"
)
# The ANSI-stripped disposal lines of the same log (lines 70915 and 70928).
REAL_DISPOSED_STRATEGY: Final[str] = (
    "2026-10-02T20:55:21.478676119Z [INFO] BREEZY-L001.FORECAST-QUANTILE-LADDER: DISPOSED"
)
REAL_DISPOSED_NODE: Final[str] = (
    "2026-10-02T20:55:21.494523448Z [INFO] BREEZY-L001.TradingNode: DISPOSED"
)
REAL_PLAIN_LINE: Final[str] = (
    "2026-10-02T20:55:21.494375108Z [INFO] BREEZY-L001.MessageBus: Closed message bus"
)

# --- REAL marker lines (AUT-1 WP5 stage 2a, S2-R2): breezy-trade-20261003T165045Z.log ------------
# WARN and ERROR lines carry an ANSI colour code BEFORE the level, which the grammar must accept.
ANSI_WARN: Final[str] = "\x1b[1;33m"
ANSI_ERROR: Final[str] = "\x1b[1;31m"
REAL_ORDER_SUBMITTED: Final[str] = (
    f"{ANSI_ON}2026-10-03T16:50:52.484350257Z{ANSI_OFF} [INFO] "
    "BREEZY-L001.FORECAST-QUANTILE-LADDER: <--[EVT] OrderSubmitted("
    "instrument_id=tc-temp-laxhigh-2026-10-04-gte93lt94f.POLYMARKET_US, "
    "client_order_id=O-20261003-165052-L001-LAX-1, account_id=POLYMARKET_US-MAIN, "
    f"ts_event=1791046252271779297){ANSI_OFF}"
)
REAL_ORDER_DENIED: Final[str] = (
    f"{ANSI_ON}2026-10-03T16:50:52.284134547Z{ANSI_OFF} {ANSI_WARN}[WARN] "
    "BREEZY-L001.FORECAST-QUANTILE-LADDER: <--[EVT] OrderDenied("
    "instrument_id=tc-temp-laxhigh-2026-10-04-gte91lt92f.POLYMARKET_US, "
    "client_order_id=O-20261003-165052-L001-LAX-2, "
    f"reason='submit intent is already OPEN for this account; wait for it to resolve'){ANSI_OFF}"
)
REAL_NBP_PUBLISHED: Final[str] = (
    f"{ANSI_ON}2026-10-03T16:50:52.234701405Z{ANSI_OFF} [INFO] "
    "BREEZY-L001.breezy: NBM_NBP_PUBLISHED cycle_ns=1791032400000000000 stations=4 points=28 "
    f"model_version=5.0{ANSI_OFF}"
)
REAL_FQ_VECTOR_COMPLETE: Final[str] = (
    f"{ANSI_ON}2026-10-03T16:50:52.234526902Z{ANSI_OFF} [INFO] "
    "BREEZY-L001.ForecastQuantileStateActor: FQ_VECTOR_COMPLETE station=KLAX "
    f"cycle_ns=1791032400000000000 climate_day=2026-10-04 era=v5.0{ANSI_OFF}"
)
# CONSTRUCTED from the source literals (no retained log line exists yet): the message text is the
# f-string in ``guarded_strategy._refuse_one`` (``self.log.error``: ERROR level, ANSI before level).
CONSTRUCTED_CAPTURE_REFUSED: Final[str] = (
    f"{ANSI_ON}2026-10-03T16:51:02.100000000Z{ANSI_OFF} {ANSI_ERROR}[ERROR] "
    "BREEZY-L001.FORECAST-QUANTILE-LADDER: CAPTURE_REFUSED reason=capture_gap "
    f"order_ref=O-20261003-165102-L001-LAX-3{ANSI_OFF}"
)
CONSTRUCTED_CAPTURE_REFUSED_ALERT_UNDELIVERED: Final[str] = (
    f"{ANSI_ON}2026-10-03T16:51:02.100000001Z{ANSI_OFF} {ANSI_ERROR}[ERROR] "
    "BREEZY-L001.FORECAST-QUANTILE-LADDER: CAPTURE_REFUSED_ALERT_UNDELIVERED "
    f"cause=no_outbox{ANSI_OFF}"
)
# PINNED from WP4 ``2608599c:src/breezy/ingest/nbm_quantile_actor.py``
# (``_offer_missed_cycle_alerts``):
# ``logger.critical("%s %s (no alert_offer wired)", "NBP_CYCLE_MISSED",
# "cycle_ns={cycle_ns} now_ns={now_ns} model=NBM_NBP")``. The message text is pinned; the level
# wrapper is the stdlib-logger shape of ``NBM_NBP_PUBLISHED`` (component ``BREEZY-L001.breezy``).
PINNED_NBP_CYCLE_MISSED_MESSAGE: Final[str] = (
    "NBP_CYCLE_MISSED cycle_ns=1791032400000000000 now_ns=1791054000000000000 "
    "model=NBM_NBP (no alert_offer wired)"
)
PINNED_NBP_CYCLE_MISSED: Final[str] = (
    f"{ANSI_ON}2026-10-03T20:20:51.000000000Z{ANSI_OFF} {ANSI_ERROR}[CRITICAL] "
    f"BREEZY-L001.breezy: {PINNED_NBP_CYCLE_MISSED_MESSAGE}{ANSI_OFF}"
)
# CONSTRUCTED from plan r8 section 3.3.5 (``CAPTURE_EPOCH_START family=<id> epoch_ns=<n>``).
CONSTRUCTED_EPOCH_START: Final[str] = (
    f"{ANSI_ON}2026-10-03T16:50:48.000000000Z{ANSI_OFF} [INFO] "
    "BREEZY-L001.CaptureActor: CAPTURE_EPOCH_START family=pm_us_crh_fq_v1 "
    f"epoch_ns=1791046248000000000{ANSI_OFF}"
)

# --- REAL supervisor lines (breezy-trade-supervisor.log) ----------------------------------------
REAL_SUP_LAUNCHED: Final[str] = (
    "2026-10-03T16:50:45Z INFO breezy.runtime.trade_supervisor launched pid=529436"
)
REAL_SUP_RELAUNCHING: Final[str] = (
    "2026-09-18T16:51:20Z INFO breezy.runtime.trade_supervisor relaunching attempt=1"
)

NS: Final[int] = 1_000_000_000


def write_log(path: Path, *lines: str, tail: str = "\n") -> Path:
    path.write_bytes(("\n".join(lines) + tail).encode("utf-8"))
    return path


def events_of(path: Path) -> list[object]:
    return list(nl.iter_node_log(path))


def spawn_event(ts: str, event: str, **kw: int) -> nl.SpawnEvent:
    when = dt.datetime.fromisoformat(ts).replace(tzinfo=dt.UTC)
    return nl.SpawnEvent(
        line_no=1, ts=when, event=event, pid=kw.get("pid"), attempt=kw.get("attempt")
    )


def node_log_path(name: str) -> Path:
    return Path("/logs") / f"breezy-trade-{name}.log"
