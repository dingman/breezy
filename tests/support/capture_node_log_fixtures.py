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
