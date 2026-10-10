"""EXEC-PAR WP5b: value-free digest telemetry for the parallel-intent path.

Pure bookkeeping, no I/O and no operator control. The exec-watcher actors
(:mod:`breezy.runtime.breaker_watcher`) feed it from native order events and
from the ledger's own counter, then log one ``event=exec_par_digest`` line.

What it reports (r5 section 5 WP5b):

* ``cross_day_settles_total``: settles that took the prior-day / uncharged path;
* heartbeat-stale denials: entries denied while the watcher heartbeat was
  older than its bound (counted from the watcher's own tick gap, because the
  exec client reports every latch denial under one wait reason);
* the dropped-candidate share by denial reason: ``denials(reason) /
  (denials + submitted)``, as a four-decimal string;
* per-station-day submitted notional (the exposure the node itself created);
* orders and notional per fixed 5 s window (the current and the peak).

Nothing here is a cap, a budget or a permit value. Station keys come from an
injected mapper so this module knows no slug grammar.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final

WINDOW_NS: Final[int] = 5 * 1_000_000_000
_NS_PER_DAY: Final[int] = 86_400 * 1_000_000_000
_SHARE_QUANT: Final[Decimal] = Decimal("0.0001")

#: Bounds so a hostile or buggy reason string cannot grow the digest.
MAX_REASONS: Final[int] = 32
MAX_STATION_DAYS: Final[int] = 512
_OVERFLOW_KEY: Final[str] = "<other>"


@dataclass(frozen=True, slots=True)
class DigestSnapshot:
    """One immutable reading of the digest."""

    cross_day_settles_total: int
    heartbeat_stale_denials: int
    submitted_total: int
    denied_total: int
    dropped_share_by_reason: tuple[tuple[str, str], ...]
    exposure_by_station_day: tuple[tuple[str, str], ...]
    window_orders: int
    window_notional: str
    peak_window_orders: int
    peak_window_notional: str

    def render(self) -> str:
        """One log line of ``key=value`` pairs; ASCII, no free text."""
        shares = ",".join(f"{reason}:{share}" for reason, share in self.dropped_share_by_reason)
        exposure = ",".join(f"{key}:{value}" for key, value in self.exposure_by_station_day)
        return (
            "event=exec_par_digest "
            f"cross_day_settles_total={self.cross_day_settles_total} "
            f"heartbeat_stale_denials={self.heartbeat_stale_denials} "
            f"submitted_total={self.submitted_total} denied_total={self.denied_total} "
            f"dropped_share={shares or '-'} station_day_exposure={exposure or '-'} "
            f"window_orders={self.window_orders} window_notional={self.window_notional} "
            f"peak_window_orders={self.peak_window_orders} "
            f"peak_window_notional={self.peak_window_notional}"
        )


@dataclass
class ExecParDigest:
    """Mutable collector; every method is safe from any thread."""

    station_of: Callable[[str], str] = lambda slug: slug
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _denials: dict[str, int] = field(default_factory=dict)
    _submitted: int = 0
    _heartbeat_stale: int = 0
    _cross_day: int = 0
    _exposure: dict[str, Decimal] = field(default_factory=dict)
    _window_start: int = -1
    _window_orders: int = 0
    _window_notional: Decimal = Decimal(0)
    _last_window_orders: int = 0
    _last_window_notional: Decimal = Decimal(0)
    _peak_orders: int = 0
    _peak_notional: Decimal = Decimal(0)

    def record_denial(self, reason: str) -> None:
        with self._lock:
            known = reason in self._denials or len(self._denials) < MAX_REASONS
            key = reason if known else _OVERFLOW_KEY
            self._denials[key] = self._denials.get(key, 0) + 1

    def denied_total(self) -> int:
        with self._lock:
            return sum(self._denials.values())

    def record_heartbeat_stale_denials(self, count: int) -> None:
        """Entries denied during a heartbeat gap the watcher itself observed."""
        if count > 0:
            with self._lock:
                self._heartbeat_stale += count

    def record_submitted(self, slug: str, notional: Decimal, ts_ns: int) -> None:
        with self._lock:
            self._submitted += 1
            self._roll_window(ts_ns)
            self._window_orders += 1
            self._window_notional += notional
            key = f"{self.station_of(slug)}@{ts_ns // _NS_PER_DAY}"
            if key not in self._exposure and len(self._exposure) >= MAX_STATION_DAYS:
                key = _OVERFLOW_KEY
            self._exposure[key] = self._exposure.get(key, Decimal(0)) + notional

    def set_cross_day_settles_total(self, value: int) -> None:
        with self._lock:
            self._cross_day = max(self._cross_day, value)

    def snapshot(self, now_ns: int) -> DigestSnapshot:
        with self._lock:
            self._roll_window(now_ns)
            denied = sum(self._denials.values())
            total = denied + self._submitted
            shares = tuple(
                (reason, str((Decimal(count) / Decimal(total)).quantize(_SHARE_QUANT)))
                for reason, count in sorted(self._denials.items())
            )
            exposure = tuple((k, str(v)) for k, v in sorted(self._exposure.items()))
            return DigestSnapshot(
                cross_day_settles_total=self._cross_day,
                heartbeat_stale_denials=self._heartbeat_stale,
                submitted_total=self._submitted,
                denied_total=denied,
                dropped_share_by_reason=shares,
                exposure_by_station_day=exposure,
                window_orders=self._last_window_orders,
                window_notional=str(self._last_window_notional),
                peak_window_orders=self._peak_orders,
                peak_window_notional=str(self._peak_notional),
            )

    def _roll_window(self, ts_ns: int) -> None:
        start = ts_ns - ts_ns % WINDOW_NS
        if self._window_start < 0:
            self._window_start = start
            return
        if start <= self._window_start:
            return
        self._last_window_orders = self._window_orders
        self._last_window_notional = self._window_notional
        self._peak_orders = max(self._peak_orders, self._window_orders)
        self._peak_notional = max(self._peak_notional, self._window_notional)
        if start - self._window_start > WINDOW_NS:
            self._last_window_orders = 0
            self._last_window_notional = Decimal(0)
        self._window_start = start
        self._window_orders = 0
        self._window_notional = Decimal(0)
