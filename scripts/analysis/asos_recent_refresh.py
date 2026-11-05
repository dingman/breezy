"""Refresh recent ASOS observations, ahead of the offer-gate scan (Item 4).

WHY THIS EXISTS, AND WHY IT IS A SEPARATE STEP
--------------------------------------------------
`cli_basis_offer_gate_scan.py` is CACHE-ONLY and ZERO-NETWORK BY
CONSTRUCTION (its own module docstring): it reads whatever `.txt` files an
EARLIER, incidental fetch happened to leave in the settlement-alignment
cache, and BL-24 records that nothing in Breezy otherwise fetches today's or
yesterday's ASOS. Left alone, the cache's most recent observation stops
advancing and every subsequent nightly scan reports
`NO_OBSERVATION_DATA` for the days that matter -- the scan starves.

This module is deliberately NOT folded into the scan itself: the scan's
zero-network guarantee is load-bearing (it is what lets it run inside the
no-egress test sandbox), so the fetch lives in its own script, run as an
earlier, independent step from the systemd timer -- where network IS
available -- and writes into the SAME cache directory
(`load_recent_asos_rows` scans it unconditionally, so a freshly-written file
here is picked up by the very next scan run with no further wiring).

NULL HYPOTHESIS, checked before this module was written (L-1, L-11)
---------------------------------------------------------------------
* The fetch mechanism itself -- `asos_url` (the IEM 5-minute ASOS endpoint,
  correctly padded), `fetch_text_cached` (URL-keyed on-disk caching, the
  SAME cache-file convention `load_recent_asos_rows` already scans), and
  `HistoricalDataClient` (the narrow `httpx.Client` `Protocol` this module's
  OWN tests inject a fake against) -- already exists in
  `settlement_alignment_study.py`, reused verbatim via import. NATIVE-
  EXISTS-AND-REUSED. (An earlier relay of this brief pointed at
  `settlement_alignment_cache.py`; that module holds only the cache
  DIRECTORY resolver, not a fetch function -- corrected here to the actual
  location, per L-11.)
* `parse_asos_rows` -- used to verify a fetch actually returned parseable
  rows (L-8: a 0-row read is not a quiet market until verified) rather than
  trusting a 200 status code alone. Reused verbatim via import.
* `load_sites` -- the registry site list this refresh iterates. Reused
  verbatim via import.
* A per-site, per-run "fetch recent ASOS and report the shortfall instead of
  raising" orchestration does NOT exist upstream. GENUINE GAP, built
  entirely from the pieces above.

FAIL-SOFT, EXPLICITLY
----------------------
Every site is fetched independently; one site's network failure, timeout, or
empty response is recorded as its own outcome and never aborts the run for
the remaining sites, and `main()` always exits 0 -- a fetch shortfall is
diagnostic information for the scan that runs next, never a reason to fail
the systemd unit. `EMPTY_RESPONSE` is distinguished from `FETCH_FAILED`: a
response that arrived but parsed to zero rows is reported as its own named
state (matching LESSONS L-8's discipline for the quote tape, applied here to
a fetch instead of a read), never silently folded into a quiet "success".
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx
from settlement_alignment_cache import DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR
from settlement_alignment_study import (
    USER_AGENT,
    HistoricalDataClient,
    SiteSpec,
    asos_url,
    cache_path_for_url,
    fetch_text_cached,
    load_sites,
    parse_asos_rows,
)

__all__ = [
    "DEFAULT_LOOKBACK_DAYS",
    "RefreshOutcome",
    "RefreshReport",
    "SiteRefreshResult",
    "lookback_days_since",
    "main",
    "refresh_recent_asos",
    "refresh_window",
]

#: A small pad past `asos_url`'s own +/-1/+2 day padding, so a run that slips
#: past midnight (or a timer misfire) still recovers the target days.
DEFAULT_LOOKBACK_DAYS: Final[int] = 3

RefreshOutcome = Literal["FETCHED", "EMPTY_RESPONSE", "FETCH_FAILED"]

# ---------------------------------------------------------------------------
# 429/5xx pacing and bounded retry (production evidence 2026-09-22..09-24:
# NYC fetched, then SFO/MIA/MDW/LAX each got HTTPStatusError 429 back-to-back
# with ZERO spacing -- `fetch_text_cached`'s own `time.sleep(delay_s)` runs
# only AFTER a successful `response.raise_for_status()`, so a 429 skips it
# entirely and the very next station's request fires immediately).
#
# Mirrors two already-reviewed patterns rather than inventing a third:
# `current_rung_hold_exit_window_study.py`'s `_RetryWaitBudget` (a run-wide
# ceiling on the SUM of every retry wait, never per-station alone) and
# `iem_mos_backfill.py`'s `_make_fetch`/`_retry_wait` (Retry-After honoured
# in its integer-seconds form, capped, else exponential backoff, 429/5xx
# only). `fetch_text_cached` itself is NEVER modified here -- every other
# caller (`settlement_alignment_study.main`, `current_rung_hold_resting_bid_
# study.py`, the exit-window study's own wrapper) keeps its existing,
# single-attempt behaviour.
# ---------------------------------------------------------------------------

#: IEM's expected minimum spacing between requests -- the same 1 s floor
#: `iem_mos_probe_transport.IemPacer`/`IEM_MIN_INTERVAL_NS` charge for the
#: MOS/1-minute-ASOS transports. `--delay-seconds` (default below) drives
#: this pacer's `min_interval_s` directly, so the CLI default keeps the
#: existing 1.0 s politeness floor.
_DEFAULT_MIN_INTERVAL_S: Final[float] = 1.0
_RETRY_BACKOFFS_S: Final[tuple[float, ...]] = (5.0, 15.0, 45.0)
_MAX_RETRY_WAIT_S: Final[float] = 60.0
_MAX_FETCH_RETRIES: Final[int] = 3
#: A run-wide ceiling on the SUM of every retry wait across every site in
#: one run -- matches `iem_mos_backfill._MAX_RETRY_WALL_S` exactly, and sits
#: well under `_ASOS_ASSUMED_BUDGET_S` (600 s, `test_asos_refresh_alert_env
#: .py`) with headroom left for the GET calls and pacing themselves.
_TOTAL_RETRY_WAIT_BUDGET_S: Final[float] = 300.0


@dataclass(slots=True)
class _RetryWaitBudget:
    """A per-RUN ceiling on the TOTAL retry wait summed across every site --
    one shared instance for the whole `refresh_recent_asos` loop. Once
    exhausted, retrying stops immediately for every remaining site too."""

    remaining_s: float

    def consume(self, seconds: float) -> bool:
        """`True` (and decrements `remaining_s`) iff the FULL `seconds` fits
        in what remains; `False` (unchanged) otherwise."""
        if seconds > self.remaining_s:
            return False
        self.remaining_s -= seconds
        return True


@dataclass(slots=True)
class _InterRequestPacer:
    """>= `min_interval_s` between actual network ATTEMPTS, charged BEFORE
    every attempt -- success or failure alike. Unlike `fetch_text_cached`'s
    own post-SUCCESS-only `time.sleep`, this pacer cannot be skipped by a
    429: it is what closes the production gap above."""

    min_interval_s: float
    monotonic: Callable[[], float]
    sleep: Callable[[float], None]
    _last_attempt: float | None = field(default=None, init=False)

    def wait(self) -> None:
        now = self.monotonic()
        if self._last_attempt is not None:
            residual = self.min_interval_s - (now - self._last_attempt)
            if residual > 0:
                self.sleep(residual)
        self._last_attempt = self.monotonic()


def _retry_wait_seconds(exc: httpx.HTTPStatusError, attempt: int) -> float:
    """Seconds to wait before retrying `exc`'s station (`attempt` is
    0-indexed: 0 is the wait before the FIRST retry). Honours `Retry-After`
    in its seconds form only -- an HTTP-date `Retry-After`, or one that
    fails to parse as a float, falls back to `_RETRY_BACKOFFS_S`. Always
    capped at `_MAX_RETRY_WAIT_S`.
    """
    seconds = _RETRY_BACKOFFS_S[attempt]
    retry_after = exc.response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            parsed = float(retry_after)
        except ValueError:
            pass
        else:
            if parsed >= 0:
                seconds = parsed
    return min(seconds, _MAX_RETRY_WAIT_S)


def _fetch_text_paced_with_retry(
    client: HistoricalDataClient,
    cache_dir: Path,
    url: str,
    *,
    pacer: _InterRequestPacer,
    sleep: Callable[[float], None],
    budget: _RetryWaitBudget,
) -> str:
    """Bounded retry (429/5xx only) around `fetch_text_cached`, paced at
    least `pacer.min_interval_s` apart before every attempt. A cache hit
    never touches the network, so it is never paced or retried. Any other
    `httpx.HTTPStatusError` (e.g. 404) or a connection-level error is raised
    on the very first attempt, exactly like the pre-retry behaviour.
    """
    path = cache_path_for_url(cache_dir, url)
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    for attempt in range(_MAX_FETCH_RETRIES + 1):
        pacer.wait()
        try:
            return fetch_text_cached(client, cache_dir, url, 0.0)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            retryable = status == 429 or 500 <= status < 600
            if not retryable or attempt == _MAX_FETCH_RETRIES:
                raise
            wait_s = _retry_wait_seconds(exc, attempt)
            if not budget.consume(wait_s):
                raise
            sleep(wait_s)
    raise AssertionError("unreachable: the loop above always returns or raises")


@dataclass(frozen=True, slots=True)
class SiteRefreshResult:
    city: str
    iem_asos_id: str
    outcome: RefreshOutcome
    rows_found: int
    detail: str | None


@dataclass(frozen=True, slots=True)
class RefreshReport:
    generated_at: dt.datetime
    results: tuple[SiteRefreshResult, ...]

    @property
    def any_shortfall(self) -> bool:
        return any(result.outcome != "FETCHED" for result in self.results)


def refresh_window(*, today: dt.date, lookback_days: int) -> tuple[dt.date, dt.date]:
    """`[today - lookback_days, today]` -- the window handed to `asos_url`.

    `asos_url` pads this further on both sides (`- 1 day` / `+ 2 days`), so
    this window only needs to cover the days the scan actually evaluates,
    not their own margin.
    """
    if lookback_days < 0:
        raise ValueError(f"lookback_days must be >= 0, was {lookback_days}")
    return today - dt.timedelta(days=lookback_days), today


def lookback_days_since(*, today: dt.date, since: dt.date) -> int:
    """`lookback_days` that pins `refresh_window`'s start to an absolute
    `since`, instead of one that drifts a day further from a fixed anchor
    (e.g. `ma_prelock_winner_ask_study.ASOS_FETCH_START`) every day a fixed
    `--lookback-days` runs. Backs `--since` below.
    """
    if since > today:
        raise ValueError(f"since ({since}) must not be after today ({today})")
    return (today - since).days


def refresh_recent_asos(
    *,
    client: HistoricalDataClient,
    cache_dir: Path,
    sites: Sequence[SiteSpec],
    today: dt.date,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    delay_s: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    retry_wait_budget_s: float = _TOTAL_RETRY_WAIT_BUDGET_S,
) -> RefreshReport:
    """Fetch each site's recent ASOS window into `cache_dir`, failing SOFT.

    One `SiteRefreshResult` per site, always -- a network error or an empty
    response for one station is recorded and the loop continues; nothing
    here ever raises past this function. `delay_s` sets the pacer's minimum
    interval between network attempts (charged before every attempt, not
    just after a success -- see the pacing/retry block above); `sleep` and
    `monotonic` are test seams so a test never really sleeps;
    `retry_wait_budget_s` is a run-wide ceiling on the SUM of every retry
    wait across every site (production default `_TOTAL_RETRY_WAIT_BUDGET_S`,
    injectable small for a test).
    """
    start, end = refresh_window(today=today, lookback_days=lookback_days)
    pacer = _InterRequestPacer(min_interval_s=delay_s, monotonic=monotonic, sleep=sleep)
    budget = _RetryWaitBudget(remaining_s=retry_wait_budget_s)
    results: list[SiteRefreshResult] = []
    for spec in sites:
        url = asos_url(spec.iem_asos_id, start, end)
        try:
            text = _fetch_text_paced_with_retry(
                client, cache_dir, url, pacer=pacer, sleep=sleep, budget=budget
            )
        except Exception as exc:  # noqa: BLE001 -- fail soft; every exception is reportable
            results.append(
                SiteRefreshResult(
                    city=spec.city,
                    iem_asos_id=spec.iem_asos_id,
                    outcome="FETCH_FAILED",
                    rows_found=0,
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        rows = len(parse_asos_rows(text))
        if rows == 0:
            results.append(
                SiteRefreshResult(
                    city=spec.city,
                    iem_asos_id=spec.iem_asos_id,
                    outcome="EMPTY_RESPONSE",
                    rows_found=0,
                    detail=(
                        "fetch succeeded but returned zero parseable ASOS rows -- "
                        "L-8: not treated as a quiet market until verified"
                    ),
                )
            )
        else:
            results.append(
                SiteRefreshResult(
                    city=spec.city,
                    iem_asos_id=spec.iem_asos_id,
                    outcome="FETCHED",
                    rows_found=rows,
                    detail=None,
                )
            )
    return RefreshReport(generated_at=dt.datetime.now(dt.UTC), results=tuple(results))


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-dir", default=DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR.as_posix()
    )
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument(
        "--since",
        type=dt.date.fromisoformat,
        default=None,
        help="Absolute start date (YYYY-MM-DD), overriding --lookback-days with a "
        "window that does not drift a day further from this anchor every run.",
    )
    parser.add_argument("--delay-seconds", type=float, default=_DEFAULT_MIN_INTERVAL_S)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    cache_dir = Path(args.cache_dir)
    sites = load_sites()
    today = dt.datetime.now(dt.UTC).date()
    lookback_days = (
        lookback_days_since(today=today, since=args.since)
        if args.since is not None
        else args.lookback_days
    )

    with httpx.Client(headers={"User-Agent": USER_AGENT}) as client:
        report = refresh_recent_asos(
            client=client,
            cache_dir=cache_dir,
            sites=sites,
            today=today,
            lookback_days=lookback_days,
            delay_s=args.delay_seconds,
        )

    for result in report.results:
        line = f"[asos-refresh] {result.city} outcome={result.outcome} rows={result.rows_found}"
        if result.detail is not None:
            line += f" detail={result.detail!r}"
        print(line)
    if report.any_shortfall:
        print(
            "[asos-refresh] one or more sites had a shortfall this run -- the "
            "offer-gate scan still runs on whatever is cached; see per-site lines above"
        )
    # Always 0: a fetch shortfall is diagnostic for the scan that runs next,
    # never a reason to fail this systemd unit (Item 4: fail soft).
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
