"""K1 on KALSHI -- the large-sample PRIOR for the cheap-ask family.

WHAT THIS IS
------------
`k1_cheap_open_settlement.py` asks one descriptive question of OUR tape: of
the rungs offered cheaply in the D-1 book, what fraction settled YES, and does
that fraction clear the fee-inclusive break-even at the price offered? On
Polymarket.us it has **8** qualifying observations in its largest cell against
the **96** it needs, so it settles nothing yet.

Kalshi has run the identical market -- the same five NWS stations, the same
CLI settlement product, markets opening 14:00Z on D-1 -- since 2021, on a
public unauthenticated API, with an ask-at-open recoverable per market. This
script ports K1's pre-registered methodology to that history so the two are
DIRECTLY COMPARABLE.

WHAT IT IS NOT -- the binding caveat, restated in the artifact it produces
------------------------------------------------------------------------
**This is a prior for the FAMILY, not a measurement of Polymarket.us.** The
settlement leg is identical. The ask leg is a DIFFERENT VENUE with different
participants, liquidity and tick regime. A Kalshi base rate can tell us early
whether the cheap-D-1 family is dead; it cannot estimate Polymarket.us's own
rate, which K1 on our own tape still has to measure. (L-13: a statistic is not
comparable across regimes it was not sampled from.)

Evidence and endpoints: `docs/evidence/kalshi_history_as_k1_prior_2026-09-02.md`.

THE STATISTICS ARE NOT FORKED
------------------------------
Every number that could be compared to K1 is produced by K1's OWN function
objects, imported here: `summarize_stratum`, `wilson_interval`,
`break_even_probability`, `resolution_floor`, `required_n_to_discriminate`,
`min_n_to_refute`, `climate_day_start_ns`, `is_pre_climate_day` and the
`ASK_STRATA` themselves. Exactly ONE input differs: `theta`, which is 0.07 for
the Kalshi taker against 0.06 on Polymarket.us. `tests/unit/
test_k1_kalshi_prior.py` asserts the function IDENTITY, not merely agreement.

THE ONE DIMENSION K1 LACKS: ERA
--------------------------------
Kalshi's own history contains a regime break. 2021-22 markets were
SINGLE-THRESHOLD (1.4-3.5 markets per city-day); 2023 onward they are
EXHAUSTIVE BUCKETS (~6.0 per city-day). Those are different populations: the
cheap-ask fraction of an exhaustive ladder is structurally larger than that of
a lone threshold. Every table here is stratified by era AND by station.
Pooled figures are reported ALONGSIDE, never instead, and are labelled
INDICATIVE ONLY -- a pooled rate across the regime break is the one result the
evidence doc forbids.

ASK AT OPEN -- the definition, and how it differs from K1's
------------------------------------------------------------
K1 on our tape takes the FIRST GENUINE ask by `ts_event` ascending, where
"genuine" means `size > 0 and 0 < price < 1` (an `OrderBookDepth10` pads empty
levels with zeros, and 1.00 is the top of the binary range -- neither is a
liftable offer).

Kalshi exposes no tape, only candlesticks: per period, `yes_ask` OHLC of
top-of-book, WITH NO SIZE. At 60-minute granularity from the market's own
`open_time`, this script takes the FIRST candlestick and reads:

1. `yes_ask.open` if it is genuine -- it is the earliest instant in the
   window, the exact analogue of K1's ordering; otherwise
2. `yes_ask.close` if it is genuine -- the earliest RECOVERABLE genuine ask,
   because a market that opens with no offer reports `yes_ask.open == 1.0000`
   (observed on the majority of markets: the book is empty at the open
   instant) and the hour's `low`/`high` would be the BEST/WORST price over the
   window, which K1 explicitly refuses ("a strategy has to trade what was
   actually offered at the moment it looked"); otherwise
3. nothing -- the market is excluded and counted.

TWO DIVERGENCES FROM K1, both stated in the report:

* **Size is unverifiable.** Candlesticks carry no depth, so K1's `size > 0`
  leg cannot be replicated. Whether a cheap ask was fillable AT SIZE is
  UNVERIFIED here -- consistent with Polymarket.us, where the median
  top-of-book bid is 0.3 contracts, but unverified is not verified.
* **Up to 60 minutes of latency on the fallback branch.** When branch 2
  supplies the price, the ask is the state of the offer at the END of the
  first hour, not at the open instant. The report counts the two branches
  separately so the reader can see the split, and reports the OPEN-only
  sensitivity alongside.

Settlement truth is the venue's own `result` field on the settled market. It
is never re-derived from a strike: the tail markets' strike semantics
("greater than 90" resolving on `floor_strike = 90`) are an off-by-one trap,
and the venue's paid result is the ground truth K1 wants anyway.

CRAWL, CACHE, RESUMABILITY
---------------------------
~29,000 settled markets across five series. Every raw response is cached under
`~/.local/share/breezy/kalshi/` keyed by ticker, append-only, so a re-run is
OFFLINE and FREE and a settled market is never re-fetched. Interrupt it at any
point and re-run: it resumes from the cache. Without `--crawl` the script does
no network I/O at all and analyses whatever is cached, labelling the result
PARTIAL if the cache does not cover every listed market.

The endpoints are UNAUTHENTICATED. This script creates no account, holds no
key, and sends no credential. It imports nothing from any execution path.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.parse
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Literal

# `urlopen`/`Request` are imported by NAME, never reached as
# `urllib.request.urlopen`. Barrier B4/V3
# (`tests/unit/test_polymarket_us_readonly_guard.py`) forbids the attribute
# names `post`/`put`/`patch`/`delete`/`request` anywhere in `src/` or
# `scripts/`, on any receiver, because receiver-type inference is statically
# undecidable. That is the correct rule and this module complies with it
# rather than being excused from it -- which is also why `CandleCache.store`
# is not called `put`. Do not "tidy" either back.
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))

# K1's OWN statistics, imported rather than re-derived. If any of these names
# stops resolving, this script must fail loudly rather than grow a local copy:
# a second Wilson interval or a second break-even formula would destroy the
# only property that makes this measurement worth having -- comparability.
from k1_cheap_open_settlement import (
    ASK_STRATA,
    POWER_P_ALT,
    POWER_P_NULL,
    Stratum,
    _overall_verdict,
    break_even_probability,
    climate_day_start_ns,
    is_pre_climate_day,
    min_n_to_refute,
    required_n_to_discriminate,
    resolution_floor,
    summarize_stratum,
    wilson_interval,
)

from breezy.registry.sites import default_registry

__all__ = [
    "API_BASE",
    "ASK_STRATA",
    "ERA_BOUNDARY",
    "ERA_EXHAUSTIVE_BUCKETS",
    "ERA_SINGLE_THRESHOLD",
    "HISTORICAL_CUTOFF",
    "KALSHI_TAKER_THETA",
    "REASON_MIXED",
    "REASON_STRADDLES",
    "REASON_TOO_FEW",
    "SERIES_TO_CLI_LOCATION",
    "UNAVAILABLE_PAYLOAD",
    "VERDICT_VOCABULARY",
    "AskAtOpen",
    "CandleCache",
    "CrawlSummary",
    "ExclusionLedger",
    "KalshiHttp",
    "Observation",
    "TickerFacts",
    "ask_at_open",
    "break_even_for",
    "break_even_probability",
    "build_observations",
    "climate_day_from_ticker",
    "climate_day_start_ns",
    "distinct_station_days",
    "era_for",
    "fetch_missing_candles",
    "headline_verdict",
    "is_genuine_ask_price",
    "is_pre_climate_day_ts",
    "is_relisted_variant",
    "is_unavailable",
    "main",
    "min_n_to_refute",
    "offset_hours_for_series",
    "overall_verdict",
    "render_report",
    "required_n_to_discriminate",
    "resolution_floor",
    "station_for_series",
    "summarize_stratum",
    "underpowered_reason",
    "wilson_interval",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VENUE: Final[str] = "kalshi"

#: Kalshi's TAKER fee coefficient. The fee has the identical functional form
#: to Polymarket.us' -- `theta * C * p * (1 - p)` -- and exactly this one
#: constant differs (0.06 there). The maker constant 0.0175 is from a
#: secondary source and UNVERIFIED; the taker constant is the one K1's
#: break-even needs, and a long-only taker is the only strategy in scope.
KALSHI_TAKER_THETA: Final[Decimal] = Decimal("0.07")

API_BASE: Final[str] = "https://api.elections.kalshi.com/trade-api/v2"

#: Verified 2026-09-02 against `GET /series/<ticker>`: all five return 200 and
#: SF is `KXHIGHTSFO`, not `KXHIGHSF` (404). Values are the registry's
#: `cli_location` for the SAME station, so the join to Breezy's own settlement
#: identity is by construction rather than by coincidence. Kalshi's Chicago
#: market settles on Midway (`CLIMDW`), never O'Hare.
SERIES_TO_CLI_LOCATION: Final[Mapping[str, str]] = {
    "KXHIGHNY": "NYC",
    "KXHIGHMIA": "MIA",
    "KXHIGHCHI": "MDW",
    "KXHIGHLAX": "LAX",
    "KXHIGHTSFO": "SFO",
}

#: The registry venue whose climate-day windows these stations share. Kalshi
#: is not a registered Breezy venue; the CLIMATE DAY, however, is a property of
#: the STATION (local standard midnight to midnight), not of the venue, so the
#: registered offsets apply unchanged. Reusing them keeps one definition of the
#: climate-day boundary in this repo.
_OFFSET_SOURCE_VENUE: Final[str] = "polymarket_us"

#: THE regime break. 2021-22 markets were single-threshold (1.4 and 3.5 per
#: city-day); 2023 onward exhaustive buckets (6.0 per city-day) -- the coverage
#: table in `docs/evidence/kalshi_history_as_k1_prior_2026-09-02.md`, confirmed
#: in the crawl by the legacy `HIGHNY-` ticker prefix and absent strike
#: metadata before 2023. PINNED, and asserted by test, because moving it
#: silently re-pools across the break.
ERA_BOUNDARY: Final[dt.date] = dt.date(2023, 1, 1)
ERA_SINGLE_THRESHOLD: Final[str] = "2021-22 SINGLE-THRESHOLD"
ERA_EXHAUSTIVE_BUCKETS: Final[str] = "2023+ EXHAUSTIVE-BUCKETS"
ERAS: Final[tuple[str, str]] = (ERA_SINGLE_THRESHOLD, ERA_EXHAUSTIVE_BUCKETS)

#: `GET /historical/cutoff` -> 2026-07-04. Markets whose day precedes it are
#: served by `/historical/...`; the remainder by the live endpoints.
HISTORICAL_CUTOFF: Final[dt.date] = dt.date(2026, 7, 4)

DEFAULT_CACHE_DIR: Final[Path] = Path.home() / ".local/share/breezy/kalshi"

#: Measured 2026-09-02: the public API throttles at roughly 4 requests/second
#: per IP and returns 429 with no `Retry-After`. These bound the crawler's
#: response to that -- short enough to keep the connection at the ceiling,
#: capped so a genuine outage cannot become a hot loop.
THROTTLE_BACKOFF_START_S: Final[float] = 0.25
THROTTLE_BACKOFF_CAP_S: Final[float] = 8.0

#: K1's verdict words, verbatim, so the two reports read side by side.
#: Marker for a market that 404s on BOTH the historical and the live
#: candlestick endpoints. That is DETERMINISTIC -- the data does not exist --
#: so it is cached as a recorded gap rather than retried forever, which would
#: also pin the report at PARTIAL indefinitely. Distinguished in the ledger
#: from "the book carried no genuine offer": "the venue has no data" and
#: "nobody was offering" are different findings.
UNAVAILABLE_KEY: Final[str] = "breezy_unavailable"
UNAVAILABLE_PAYLOAD: Final[Mapping[str, Any]] = {
    "candlesticks": [],
    UNAVAILABLE_KEY: "404 on both the historical and live candlestick endpoints",
}

VERDICT_VOCABULARY: Final[tuple[str, str, str]] = (
    "FAMILY SURVIVES",
    "FAMILY DEAD",
    "UNDERPOWERED -- INCONCLUSIVE",
)

_MONTHS: Final[Mapping[str, int]] = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}

#: The strike admits a LEADING MINUS. Found in the real crawl: 12 settled
#: `HIGHCHI` markets carry a negative strike (`-T-1`, `-B-0.5`) because
#: Chicago genuinely trades sub-zero daily highs in January. A parser
#: requiring `\d+` drops them silently, and drops them NON-RANDOMLY -- from
#: the coldest days of the coldest station -- which is exactly the selective
#: loss that biases a base rate.
_TICKER_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<series>[A-Z]+)-(?P<yy>\d{2})(?P<mon>[A-Z]{3})(?P<dd>\d{2})"
    r"-(?P<kind>[BT])(?P<strike>-?\d+(?:\.\d+)?)$"
)

#: Also found in the real crawl: 11 RE-LISTED duplicates, spelled
#: `HIGHMIA--23MAY11-T89` (double hyphen) and `HIGHCHI-2-24FEB28-B54.5` (a
#: `-2` re-list segment). Each names the SAME bucket as a market already in
#: the sample. Admitting them would double-count an outcome; lumping them
#: into "not a weather ticker" would hide that a real weather market was
#: dropped. They are refused AND counted under their own name.
_RELIST_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Z]+-\d*-\d{2}[A-Z]{3}\d{2}-[BT]-?\d+(?:\.\d+)?$"
)

BucketKind = Literal["BETWEEN", "TAIL"]
AskField = Literal["open", "close"]

overall_verdict = _overall_verdict


def distinct_station_days(observations: Sequence[Observation]) -> int:
    """How many `(station, climate_day)` pairs the sample actually spans.

    `n` alone hides clustering: in the exhaustive-bucket era one station-day
    contributes up to ~6 markets that PARTITION the same outcome.
    """
    return len({(o.station, o.climate_day) for o in observations})


#: The two states K1's single word "UNDERPOWERED" covers. They point the
#: reader in OPPOSITE directions, so the report names which one it is.
REASON_TOO_FEW: Final[str] = (
    "TOO FEW OBSERVATIONS -- the cells have not reached the discrimination "
    "sample; more data is what is missing"
)
REASON_STRADDLES: Final[str] = (
    "INTERVAL STRADDLES BREAK-EVEN AT ADEQUATE n -- the data is in and the "
    "true rate sits genuinely between the two hypotheses; more of the same "
    "data narrows this only slowly, and the clustering caveat below binds "
    "before the raw count does"
)
REASON_MIXED: Final[str] = (
    "MIXED -- some cells have too few observations, others have adequate n "
    "with an interval that still straddles break-even"
)


def underpowered_reason(strata: Sequence[Stratum]) -> str:
    """WHY the strata are underpowered: sample size, or genuine ambiguity?

    Blaming sample size when `n` is already several times
    `required_n_to_discriminate` would send the reader to collect data that
    will not resolve the question.
    """
    required = required_n_to_discriminate()
    undecided = [stratum for stratum in strata if stratum.verdict == "UNDERPOWERED"]
    if not undecided:
        return REASON_TOO_FEW
    thin = any(stratum.n < required for stratum in undecided)
    wide = any(stratum.n >= required for stratum in undecided)
    if thin and wide:
        return REASON_MIXED
    return REASON_STRADDLES if wide else REASON_TOO_FEW


def headline_verdict(strata_by_era: Mapping[str, Sequence[Stratum]]) -> str:
    """The report's headline, as a CONJUNCTION over eras -- never a pooled rate.

    A rate pooled across the 2021-22 / 2023+ regime break is the one result
    the evidence doc forbids as a finding, so the headline cannot be computed
    from it. Each era gets K1's own `_overall_verdict`; the headline then
    combines those verdicts with the same logic one level up:

    * any era SURVIVES -> the family is not refuted;
    * every era WITH DATA is DEAD -> the family is refuted (an era Kalshi
      never ran is absence of data, not evidence, and does not veto);
    * anything else -> UNDERPOWERED.

    A conjunction of separately-computed verdicts is not pooling: no sample
    from one regime ever enters another's interval.
    """
    verdicts = {
        era: overall_verdict(strata)
        for era, strata in strata_by_era.items()
        if any(stratum.n > 0 for stratum in strata)
    }
    if not verdicts:
        return "UNDERPOWERED -- INCONCLUSIVE"
    if any(verdict == "FAMILY SURVIVES" for verdict in verdicts.values()):
        return "FAMILY SURVIVES"
    if all(verdict == "FAMILY DEAD" for verdict in verdicts.values()):
        return "FAMILY DEAD"
    return "UNDERPOWERED -- INCONCLUSIVE"


# ---------------------------------------------------------------------------
# Ticker parsing -- `SERIES-YYMMMDD-Bxx.x` and `-Txx`
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TickerFacts:
    """Everything the ticker itself states. Nothing inferred, nothing guessed."""

    ticker: str
    raw_series: str
    series: str
    climate_day: dt.date
    bucket_kind: BucketKind
    strike: Decimal


def parse_ticker(ticker: str) -> TickerFacts | None:
    """Decode one market ticker, or `None` if it is not a weather-bucket ticker.

    `None` rather than a guess: a mis-decoded climate day silently mis-dates an
    era and mis-joins a station, and both failures are invisible downstream.

    2021-22 markets carry the LEGACY unprefixed series (`HIGHNY-21AUG06-T86`)
    even though `series_ticker=KXHIGHNY` is what returns them, so the raw
    series is folded onto the modern spelling and BOTH are retained.
    """
    match = _TICKER_RE.match(ticker.strip()) if ticker else None
    if match is None:
        return None
    month = _MONTHS.get(match["mon"])
    if month is None:
        return None
    try:
        climate_day = dt.date(2000 + int(match["yy"]), month, int(match["dd"]))
    except ValueError:
        return None
    try:
        strike = Decimal(match["strike"])
    except InvalidOperation:  # pragma: no cover -- the regex already forbids it
        return None
    raw_series = match["series"]
    return TickerFacts(
        ticker=ticker,
        raw_series=raw_series,
        series=raw_series if raw_series.startswith("KX") else f"KX{raw_series}",
        climate_day=climate_day,
        bucket_kind="BETWEEN" if match["kind"] == "B" else "TAIL",
        strike=strike,
    )


def is_unavailable(payload: Mapping[str, Any]) -> bool:
    """Is this cache entry a RECORDED GAP rather than a real response?"""
    return UNAVAILABLE_KEY in payload


def is_relisted_variant(ticker: str) -> bool:
    """Is this a re-listed duplicate of a bucket already in the sample?

    See :data:`_RELIST_RE`. Kept distinct from "unparseable" so the report can
    say WHICH kind of market it dropped -- a venue re-list is a known,
    bounded artifact; an unrecognised shape is a parser gap.
    """
    return bool(_RELIST_RE.match(ticker.strip())) if ticker else False


def climate_day_from_ticker(ticker: str) -> dt.date | None:
    """The climate day the ticker NAMES -- never the venue's open/close clock."""
    facts = parse_ticker(ticker)
    return None if facts is None else facts.climate_day


# ---------------------------------------------------------------------------
# Era -- the one dimension K1 lacks
# ---------------------------------------------------------------------------


def era_for(climate_day: dt.date) -> str:
    """Which market-structure regime `climate_day` belongs to."""
    return ERA_SINGLE_THRESHOLD if climate_day < ERA_BOUNDARY else ERA_EXHAUSTIVE_BUCKETS


# ---------------------------------------------------------------------------
# Station identity and K1's D-1 population rule
# ---------------------------------------------------------------------------


def station_for_series(series: str) -> str:
    """The NWS CLI location this series settles on. Raises for an unknown series.

    Never defaults: silently attributing an unrecognised series to a station
    would pool two cities' outcomes, which G-01 established is invalid.
    """
    return SERIES_TO_CLI_LOCATION[series]


@lru_cache(maxsize=1)
def _offsets_by_station() -> Mapping[str, float]:
    registry = default_registry()
    offsets: dict[str, float] = {}
    for venue, city in registry.pairs():
        if venue != _OFFSET_SOURCE_VENUE:
            continue
        site = registry.settlement_site(venue, city)
        offsets[site.cli_location] = registry.climate_day_window(venue, city).std_utc_offset_hours
    return offsets


def offset_hours_for_series(series: str) -> float:
    """The station's FIXED standard-time UTC offset, from Breezy's registry."""
    return _offsets_by_station()[station_for_series(series)]


def is_pre_climate_day_ts(open_ts: int, *, climate_day: dt.date, series: str) -> bool:
    """K1's own D-1 rule, applied to a Kalshi market's `open_time`.

    Delegates to `k1_cheap_open_settlement.is_pre_climate_day`: strictly before
    local-STANDARD midnight starting `climate_day`, never DST-aware. Kalshi's
    modern markets open 14:00Z on D-1, which clears the boundary at every one
    of the five stations -- but the rule is applied, not assumed, because the
    2021 markets opened at assorted hours.
    """
    return is_pre_climate_day(
        open_ts * 1_000_000_000,
        climate_day=climate_day,
        std_utc_offset_hours=offset_hours_for_series(series),
    )


# ---------------------------------------------------------------------------
# Ask at open
# ---------------------------------------------------------------------------


def is_genuine_ask_price(price: Decimal) -> bool:
    """Is this an offer a taker could actually have lifted, on PRICE alone?

    The two price legs of `k1_cheap_open_settlement.is_genuine_ask`, verbatim:
    zero is padding / no offer, and 1.00 is the top of the binary range, where
    nothing can be won. K1's THIRD leg (`size > 0`) has no counterpart here --
    candlesticks carry no depth -- and that divergence is reported rather than
    papered over with an assumed size.
    """
    return Decimal(0) < price < Decimal(1)


@dataclass(frozen=True, slots=True)
class AskAtOpen:
    """The ask-at-open recovered from the first D-1 candlestick, and its branch."""

    price: Decimal
    field: AskField
    end_period_ts: int | None


def _candle_decimal(node: Mapping[str, Any], base: str) -> Decimal | None:
    """Read one OHLC field across BOTH response schemas.

    Historical candlesticks name the fields `open`/`close`; the live endpoints
    (post-cutoff) name them `open_dollars`/`close_dollars`. A reader that
    handled only one would silently drop every market on one side of
    2026-07-04 while reporting no error at all.
    """
    for key in (base, f"{base}_dollars"):
        raw = node.get(key)
        if raw is None:
            continue
        try:
            return Decimal(str(raw))
        except InvalidOperation:
            return None
    return None


def ask_at_open(payload: Mapping[str, Any]) -> AskAtOpen | None:
    """The ask at the D-1 open, from the FIRST candlestick of the response.

    `open` first, `close` as the fallback -- see this module's docstring for
    the full definition and its two divergences from K1. Returns `None` when
    no genuine offer is recoverable, which is an EXCLUSION, never a zero.
    """
    candles = payload.get("candlesticks")
    if not isinstance(candles, Sequence) or not candles:
        return None
    first = candles[0]
    if not isinstance(first, Mapping):
        return None
    yes_ask = first.get("yes_ask")
    if not isinstance(yes_ask, Mapping):
        return None
    end_ts = first.get("end_period_ts")
    end_period_ts = int(end_ts) if isinstance(end_ts, (int, float)) else None
    for branch in ("open", "close"):
        price = _candle_decimal(yes_ask, branch)
        if price is not None and is_genuine_ask_price(price):
            return AskAtOpen(
                price=price,
                field="open" if branch == "open" else "close",
                end_period_ts=end_period_ts,
            )
    return None


# ---------------------------------------------------------------------------
# Break-even at the Kalshi taker fee
# ---------------------------------------------------------------------------


def break_even_for(threshold: Decimal) -> Decimal:
    """K1's break-even formula at Kalshi's taker `theta`. One constant differs."""
    return break_even_probability(ask=threshold, theta=KALSHI_TAKER_THETA)


# ---------------------------------------------------------------------------
# Population assembly
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Observation:
    """One settled market with a D-1 ask-at-open and the venue's paid result."""

    ticker: str
    series: str
    station: str
    climate_day: dt.date
    era: str
    bucket_kind: BucketKind
    strike: Decimal
    ask: Decimal
    ask_field: AskField
    settled_yes: bool


@dataclass(frozen=True, slots=True)
class ExclusionLedger:
    """Why listed markets did not reach the measured population.

    Every exclusion is COUNTED. A silently dropped market is indistinguishable
    from a market that never existed, and the difference is the whole finding.
    """

    unparseable_ticker: int = 0
    relisted_variant: int = 0
    unknown_series: int = 0
    missing_open_time: int = 0
    not_pre_climate_day: int = 0
    observation_not_pre_climate_day: int = 0
    unsettled: int = 0
    voided: int = 0
    no_candlestick: int = 0
    candlesticks_unavailable: int = 0
    no_genuine_ask: int = 0


def _parse_open_ts(raw: object) -> int | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # A naive stamp is unanchored: reading it as UTC would silently shift
        # the D-1 boundary by up to 8 hours at LAX/SFO. Refuse instead.
        return None
    return int(parsed.timestamp())


def build_observations(
    *,
    markets: Iterable[Mapping[str, Any]],
    candles: Mapping[str, Mapping[str, Any]],
) -> tuple[list[Observation], ExclusionLedger]:
    """Join settled markets to their D-1 ask-at-open, counting every exclusion."""
    counts: dict[str, int] = defaultdict(int)
    observations: list[Observation] = []

    for market in markets:
        ticker = str(market.get("ticker") or "")
        facts = parse_ticker(ticker)
        if facts is None:
            counts["relisted_variant" if is_relisted_variant(ticker) else "unparseable_ticker"] += 1
            continue
        if facts.series not in SERIES_TO_CLI_LOCATION:
            counts["unknown_series"] += 1
            continue
        open_ts = _parse_open_ts(market.get("open_time"))
        if open_ts is None:
            counts["missing_open_time"] += 1
            continue
        if not is_pre_climate_day_ts(open_ts, climate_day=facts.climate_day, series=facts.series):
            counts["not_pre_climate_day"] += 1
            continue
        raw_result = market.get("result")
        result = str(raw_result).strip().lower() if raw_result is not None else ""
        if result == "":
            counts["unsettled"] += 1
            continue
        if result not in ("yes", "no"):
            counts["voided"] += 1
            continue
        payload = candles.get(ticker)
        if payload is None:
            counts["no_candlestick"] += 1
            continue
        if is_unavailable(payload):
            counts["candlesticks_unavailable"] += 1
            continue
        entry = ask_at_open(payload)
        if entry is None:
            counts["no_genuine_ask"] += 1
            continue
        # K1's D-1 rule binds on the instant the price was OBSERVED, not on
        # the market's open. The `close` branch observes at the END of the
        # first hour, so a market opening shortly before local-standard
        # midnight can pass the `open_time` test while its close-of-hour ask
        # was standing INSIDE the climate day -- an intraday quote, which is
        # exactly the population K1 excludes.
        observed_ts = open_ts if entry.field == "open" else entry.end_period_ts
        if observed_ts is not None and not is_pre_climate_day_ts(
            observed_ts, climate_day=facts.climate_day, series=facts.series
        ):
            counts["observation_not_pre_climate_day"] += 1
            continue
        observations.append(
            Observation(
                ticker=ticker,
                series=facts.series,
                station=station_for_series(facts.series),
                climate_day=facts.climate_day,
                era=era_for(facts.climate_day),
                bucket_kind=facts.bucket_kind,
                strike=facts.strike,
                ask=entry.price,
                ask_field=entry.field,
                settled_yes=result == "yes",
            )
        )

    return observations, ExclusionLedger(**counts)


# ---------------------------------------------------------------------------
# Cache -- append-only, keyed by ticker, so a re-run is offline and free
# ---------------------------------------------------------------------------


class CandleCache:
    """Append-only JSONL cache of raw candlestick responses, keyed by ticker.

    A settled market's candlesticks are IMMUTABLE, so a cache hit is never
    stale and is never re-fetched. Append-only because the crawl is long and
    interruptible: an interrupted run loses at most the line it was writing,
    and a partial trailing line is skipped on load rather than made fatal.
    """

    FILENAME: Final[str] = "candles.jsonl"

    def __init__(self, directory: Path) -> None:
        self._directory = Path(directory)
        self._directory.mkdir(parents=True, exist_ok=True)
        self._path = self._directory / self.FILENAME
        self._entries: dict[str, Mapping[str, Any]] = {}
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    # A truncated trailing line from an interrupted append.
                    # Losing one cached market is recoverable; refusing to
                    # start is not.
                    continue
                ticker = record.get("ticker")
                if isinstance(ticker, str):
                    self._entries[ticker] = record.get("response")

    def get(self, ticker: str) -> Mapping[str, Any] | None:
        return self._entries.get(ticker)

    def store(self, ticker: str, response: Mapping[str, Any]) -> None:
        self._entries[ticker] = response
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"ticker": ticker, "response": response}) + "\n")
            handle.flush()

    def tickers(self) -> set[str]:
        return set(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


def _market_list_path(directory: Path, series: str) -> Path:
    return Path(directory) / f"markets_{series}.json"


def load_cached_markets(directory: Path, series: str) -> list[Mapping[str, Any]]:
    path = _market_list_path(directory, series)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    markets = data.get("markets") if isinstance(data, Mapping) else None
    return list(markets) if isinstance(markets, list) else []


def store_markets(directory: Path, series: str, markets: Sequence[Mapping[str, Any]]) -> None:
    path = _market_list_path(directory, series)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "series": series,
                "fetched_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                "markets": list(markets),
            }
        ),
        encoding="utf-8",
    )


def fetch_missing_candles(
    *,
    tickers: Iterable[str],
    cache: CandleCache,
    fetch: Callable[[str], Mapping[str, Any] | None],
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Mapping[str, Any]]:
    """Return candlesticks for `tickers`, fetching ONLY what is not cached.

    The resumability guarantee: a cached ticker never reaches `fetch`. A fetch
    that returns `None` (a hard failure) is NOT cached, so the next run retries
    it; an empty-but-successful response IS cached, so a market that genuinely
    has no first-hour candlestick is never re-fetched.
    """
    unique = list(dict.fromkeys(tickers))
    total = len(unique)
    resolved: dict[str, Mapping[str, Any]] = {}
    for index, ticker in enumerate(unique, start=1):
        payload = cache.get(ticker)
        if payload is None:
            payload = fetch(ticker)
            if payload is not None:
                cache.store(ticker, payload)
        if payload is not None:
            resolved[ticker] = payload
        if progress is not None:
            progress(index, total)
    return resolved


# ---------------------------------------------------------------------------
# HTTP -- unauthenticated, paced, backing off on 429
# ---------------------------------------------------------------------------


class KalshiHttp:
    """A paced, unauthenticated reader for Kalshi's public API.

    No credential is ever sent: these endpoints are documented with an empty
    security array and were verified unauthenticated on 2026-09-02. If one
    ever answers 401/403, that is a finding to report, not a prompt to create
    an account -- so the client raises rather than retrying with auth.

    Rate limit measured on 2026-09-02: ~10 requests/second before a 429, so
    the default pace is deliberately below it and a 429 is backed off
    exponentially rather than hammered.
    """

    def __init__(
        self,
        *,
        base_url: str = API_BASE,
        min_interval_s: float = 0.12,
        max_retries: int = 10,
        user_agent: str = "breezy-research/1.0 (K1 Kalshi prior; contact: repo owner)",
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._min_interval_s = min_interval_s
        self._max_retries = max_retries
        self._user_agent = user_agent
        self._sleep = sleep
        self._last_call = 0.0

    def get_json(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        url = f"{self._base_url}/{path.lstrip('/')}{query}"
        # A 429 here is CONGESTION, not an error: the limit is per-IP and
        # ~4 requests/second (measured 2026-09-02, no `Retry-After` header),
        # so a crawl at the ceiling meets them constantly. Backing off a full
        # second per 429 would idle the connection far below the limit it is
        # respecting, so throttle backoff starts SHORT and grows; transport
        # failures, which are genuine errors, still start at a full second.
        throttle_delay = THROTTLE_BACKOFF_START_S
        transport_delay = 1.0
        for attempt in range(self._max_retries):
            elapsed = time.monotonic() - self._last_call
            if elapsed < self._min_interval_s:
                self._sleep(self._min_interval_s - elapsed)
            probe = Request(url, headers={"User-Agent": self._user_agent})
            self._last_call = time.monotonic()
            try:
                with urlopen(probe, timeout=30) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    raise RuntimeError(
                        f"Kalshi returned {exc.code} for {url}. These endpoints are "
                        "supposed to be UNAUTHENTICATED; stop and report this rather "
                        "than creating an account or a key."
                    ) from exc
                if exc.code == 404:
                    raise
                if exc.code == 429 or 500 <= exc.code < 600:
                    if attempt == self._max_retries - 1:
                        raise
                    self._sleep(throttle_delay)
                    throttle_delay = min(throttle_delay * 2, THROTTLE_BACKOFF_CAP_S)
                    continue
                raise
            except (urllib.error.URLError, TimeoutError):
                if attempt == self._max_retries - 1:
                    raise
                self._sleep(transport_delay)
                transport_delay *= 2
        raise RuntimeError(f"exhausted retries for {url}")  # pragma: no cover

    def list_series_markets(self, series: str) -> list[Mapping[str, Any]]:
        """Every settled market for one series, historical AND live, deduped."""
        collected: dict[str, Mapping[str, Any]] = {}
        for path, params in (
            ("historical/markets", {"series_ticker": series, "limit": 1000}),
            ("markets", {"series_ticker": series, "status": "settled", "limit": 1000}),
        ):
            cursor: str | None = None
            while True:
                page_params = dict(params)
                if cursor:
                    page_params["cursor"] = cursor
                page = self.get_json(path, page_params)
                markets = page.get("markets") or []
                for market in markets:
                    ticker = market.get("ticker")
                    if isinstance(ticker, str):
                        collected.setdefault(ticker, market)
                cursor = page.get("cursor")
                if not cursor or not markets:
                    break
        return list(collected.values())

    def first_hour_candlesticks(
        self, *, ticker: str, series: str, open_ts: int, climate_day: dt.date
    ) -> Mapping[str, Any] | None:
        """The single 60-minute candlestick starting at the market's own open.

        The endpoint family is chosen by the climate day against the published
        historical cutoff, with the other family tried on a 404 -- the cutoff
        is a date, and a market straddling it must not be silently dropped.
        """
        window = {"start_ts": open_ts, "end_ts": open_ts + 3600, "period_interval": 60}
        historical_first = climate_day < HISTORICAL_CUTOFF
        paths = (
            f"historical/markets/{ticker}/candlesticks",
            f"series/{series}/markets/{ticker}/candlesticks",
        )
        ordered = paths if historical_first else tuple(reversed(paths))
        for path in ordered:
            try:
                payload = self.get_json(path, window)
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise
                continue
            if isinstance(payload, Mapping):
                return payload
        return UNAVAILABLE_PAYLOAD


@dataclass(frozen=True, slots=True)
class CrawlSummary:
    """What the crawl actually did -- reported as data, never assumed."""

    series_seen: tuple[str, ...]
    markets_listed: int
    candles_cached: int
    candles_fetched: int
    fetch_failures: tuple[tuple[str, str], ...] = ()
    complete: bool = True
    elapsed_s: float = 0.0


# ---------------------------------------------------------------------------
# Reporting -- K1's shape, K1's vocabulary, plus the mandatory prior caveat
# ---------------------------------------------------------------------------

_PRIOR_DISCLAIMER: Final[str] = (
    "**THIS IS A PRIOR FOR THE FAMILY, MEASURED ON KALSHI HISTORY. It cannot "
    "estimate Polymarket.us's own settle rate.** The settlement leg is "
    "identical -- the same five NWS CLI stations, the same product. The ASK "
    "leg is a different venue with different participants, liquidity and tick "
    "regime. This measurement can tell us early whether the cheap-D-1 family "
    "is dead everywhere; it cannot tell us what Polymarket.us pays, which K1 "
    "on our own tape still has to measure (L-13: a statistic is not comparable "
    "across regimes it was not sampled from)."
)

_TABLE_HEADER: Final[str] = (
    "| Scope | Ask <= | n | k | pi | Wilson 95% low | Wilson 95% high | "
    "Break-even | Clears? | Resolution floor | Verdict |"
)
_TABLE_DIVIDER: Final[str] = "|---|---:|---:|---:|---:|---:|---:|---:|:--:|---:|---|"


def _rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def _stratum_row(scope: str, threshold: Decimal, stratum: Stratum) -> str:
    clears = "-" if stratum.clears is None else ("YES" if stratum.clears else "no")
    return (
        f"| {scope} | {threshold} | {stratum.n} | {stratum.k} | "
        f"{_rate(stratum.pi)} | {_rate(stratum.wilson_lower)} | "
        f"{_rate(stratum.wilson_upper)} | {stratum.break_even} | {clears} | "
        f"{_rate(stratum.resolution_floor)} | {stratum.verdict} |"
    )


def _strata_for(observations: Sequence[Observation]) -> list[Stratum]:
    return [
        summarize_stratum(
            threshold=threshold,
            outcomes=[o.settled_yes for o in observations if o.ask <= threshold],
            theta=KALSHI_TAKER_THETA,
        )
        for threshold in ASK_STRATA
    ]


def render_report(
    *,
    observations: Sequence[Observation],
    ledger: ExclusionLedger,
    crawl: CrawlSummary,
    generated_at: dt.datetime,
) -> str:
    lines: list[str] = []
    add = lines.append
    stamp = generated_at.strftime("%Y-%m-%dT%H:%M:%SZ")

    add("# K1 on KALSHI -- a large-sample PRIOR for the cheap-D-1 family")
    add("")
    add(f"Generated {stamp}")
    add("")
    add(_PRIOR_DISCLAIMER)
    add("")
    add(
        "Regenerate: `python scripts/analysis/k1_kalshi_prior.py` (offline, from "
        "cache) or `--crawl` (network). Companion measurement on our own tape: "
        "`scripts/analysis/k1_cheap_open_settlement.py`. Evidence: "
        "`docs/evidence/kalshi_history_as_k1_prior_2026-09-02.md`."
    )
    add("")
    add(
        "Every statistic below is produced by K1's OWN function objects -- "
        "`summarize_stratum`, `wilson_interval`, `break_even_probability`, "
        "`resolution_floor`, `required_n_to_discriminate`, `min_n_to_refute` -- "
        "imported, not re-derived. Exactly ONE input differs: `theta = "
        f"{KALSHI_TAKER_THETA}` (Kalshi taker) against 0.06 on Polymarket.us. "
        "This is a DESCRIPTIVE settlement-frequency measurement plus a "
        "closed-form break-even comparison. No order, fill, position or P&L is "
        "simulated: Nautilus Trader is the exclusive owner of backtesting."
    )
    add("")

    # -- 1. crawl -----------------------------------------------------------
    add("## 1. Crawl preflight")
    add("")
    if not crawl.complete:
        add(
            "**PARTIAL CRAWL.** The candlestick cache does not cover every listed "
            "settled market, so every figure below is computed on a SUBSET. Re-run "
            "with `--crawl` to resume: the cache is append-only and keyed by "
            "ticker, so nothing already fetched is fetched again."
        )
        add("")
    add("| Quantity | Count |")
    add("|---|---:|")
    add(f"| Series crawled | {len(crawl.series_seen)} |")
    add(f"| Settled markets listed | {crawl.markets_listed} |")
    add(f"| Candlestick responses in cache | {crawl.candles_cached} |")
    add(f"| Candlestick responses fetched this run | {crawl.candles_fetched} |")
    add(f"| Fetch failures | {len(crawl.fetch_failures)} |")
    add(f"| Crawl complete | {'YES' if crawl.complete else 'NO -- PARTIAL'} |")
    add("")
    add(f"Series: {', '.join(crawl.series_seen) if crawl.series_seen else 'none'}.")
    add("")
    if crawl.fetch_failures:
        add("### Fetch failures")
        add("")
        for ticker, reason in crawl.fetch_failures[:50]:
            add(f"- `{ticker}` -- {reason}")
        if len(crawl.fetch_failures) > 50:
            add(f"- ... and {len(crawl.fetch_failures) - 50} more")
        add("")

    # -- 2. population ------------------------------------------------------
    add("## 2. Population as implemented")
    add("")
    add(
        "One member per settled market whose `open_time` fell STRICTLY before "
        "its climate day began in local STANDARD time -- K1's own "
        "`is_pre_climate_day`, against the registry's fixed "
        "`std_utc_offset_hours`, never DST-aware. Kalshi's modern markets open "
        "14:00Z on D-1, which clears that boundary at all five stations; the "
        "rule is nevertheless APPLIED rather than assumed, because 2021 markets "
        "opened at assorted hours."
    )
    add("")
    add(
        "**Ask at open** is taken from the FIRST 60-minute candlestick starting "
        "at the market's own `open_time`: `yes_ask.open` when it is a genuine "
        "offer (`0 < p < 1`), else `yes_ask.close`. A market that opens with an "
        "empty book reports `yes_ask.open = 1.0000`, which is *nobody is "
        "offering*, not a 100c offer -- K1's `is_genuine_ask` rejects `p >= 1` "
        "for exactly that reason. The hour's `low`/`high` are never used: they "
        "are the best/worst price over the window, and K1 refuses to trade a "
        "price that was not on the screen at the moment it looked."
    )
    add("")
    add(
        "K1's D-1 rule binds on the instant the price was OBSERVED, not on the "
        "market's open: on the `close` branch that instant is the END of the "
        "first hour, so a market opening shortly before local-standard midnight "
        "is excluded even though its `open_time` cleared the boundary. An "
        "intraday quote is the population K1 exists to exclude."
    )
    add("")
    add(
        "**Two divergences from K1, stated rather than hidden.** (1) Kalshi "
        "candlesticks carry NO size, so K1's `size > 0` leg cannot be "
        "replicated: whether a cheap ask was fillable AT SIZE is UNVERIFIED "
        "here. (2) On the `close` branch the price is the state of the offer at "
        "the END of the first hour, up to 60 minutes after K1's instant. The "
        "branch split is reported below, and the `open`-only sensitivity is "
        "reported alongside every headline figure."
    )
    add("")
    add(
        "**Settlement truth is the venue's own `result` field** on the settled "
        "market -- never re-derived from a strike. The tail markets' semantics "
        '("greater than 90" resolving on `floor_strike = 90`) are an '
        "off-by-one trap, and the venue's paid result is the ground truth K1 "
        "wants anyway. Kalshi's settlement source is the SAME NWS CLI product "
        "as Breezy's (`CLINYC`, `CLIMIA`, `CLIMDW`, `CLILAX`, `CLISFO`), read "
        "via The Weather Company -- one hop more than Breezy's direct NWS path, "
        "same underlying."
    )
    add("")
    add("| Stage | Count |")
    add("|---|---:|")
    add(f"| Settled markets listed | {crawl.markets_listed} |")
    add(f"| Dropped: ticker not a weather bucket | {ledger.unparseable_ticker} |")
    add(f"| Dropped: re-listed duplicate of an existing bucket | {ledger.relisted_variant} |")
    add(f"| Dropped: series not one of the five | {ledger.unknown_series} |")
    add(f"| Dropped: no usable `open_time` | {ledger.missing_open_time} |")
    add(f"| Dropped: opened after the climate day began | {ledger.not_pre_climate_day} |")
    add(
        "| Dropped: ask-at-open OBSERVED after the climate day began | "
        f"{ledger.observation_not_pre_climate_day} |"
    )
    add(f"| Dropped: no settled `result` | {ledger.unsettled} |")
    add(f"| Dropped: non-binary result (void) | {ledger.voided} |")
    add(f"| Dropped: no candlestick in cache | {ledger.no_candlestick} |")
    add(
        "| Dropped: venue has no candlestick for this market (404 on both "
        f"endpoints) | {ledger.candlesticks_unavailable} |"
    )
    add(f"| Dropped: no genuine ask in the first hour | {ledger.no_genuine_ask} |")
    add(f"| **MEASURED POPULATION** | **{len(observations)}** |")
    add("")

    open_branch = sum(1 for o in observations if o.ask_field == "open")
    close_branch = len(observations) - open_branch
    add(
        f"Ask-at-open branch split: `yes_ask.open` supplied {open_branch}, "
        f"`yes_ask.close` supplied {close_branch}."
    )
    add("")

    add("### Coverage by era and station")
    add("")
    add("| Era | Station | n | First climate day | Last climate day |")
    add("|---|---|---:|---|---|")
    for era in ERAS:
        for station in sorted(set(SERIES_TO_CLI_LOCATION.values())):
            cell = [o for o in observations if o.era == era and o.station == station]
            days = sorted(o.climate_day for o in cell)
            add(
                f"| {era} | {station} | {len(cell)} | "
                f"{days[0].isoformat() if days else 'n/a'} | "
                f"{days[-1].isoformat() if days else 'n/a'} |"
            )
    add("")

    # -- 3. ask distribution ------------------------------------------------
    add("## 3. Ask-at-open distribution (all measured members, all outcomes)")
    add("")
    if not observations:
        add("No measured member has an ask-at-open.")
        add("")
    else:
        for era in ERAS:
            prices = sorted(o.ask for o in observations if o.era == era)
            add(f"### {era}")
            add("")
            if not prices:
                add("No observation in this era.")
                add("")
                continue
            histogram: dict[Decimal, int] = defaultdict(int)
            for price in prices:
                histogram[price] += 1
            add("| Ask at open | Count |")
            add("|---:|---:|")
            for price in sorted(histogram):
                if price <= Decimal("0.10"):
                    add(f"| {price} | {histogram[price]} |")
            cheap = sum(count for price, count in histogram.items() if price <= Decimal("0.10"))
            add(f"| _> 0.10 (not shown individually)_ | {len(prices) - cheap} |")
            add("")
            add(
                f"Min {prices[0]}, median {prices[len(prices) // 2]}, "
                f"max {prices[-1]}, n={len(prices)}."
            )
            add("")

    # -- 4. the measurement -------------------------------------------------
    add("## 4. Settlement frequency by era, station and cheap-ask stratum")
    add("")
    add(
        "Break-even is `ask + theta * ask * (1 - ask)` evaluated at the stratum "
        f"THRESHOLD (the most expensive ask admitted), with `theta = "
        f"{KALSHI_TAKER_THETA}` -- Kalshi's TAKER coefficient. `clears?` asks "
        "whether the Wilson 95% UPPER bound exceeds break-even."
    )
    add("")
    add(
        "**Era x station is the PRIMARY table.** 2021-22 markets were "
        "single-threshold, 2023+ exhaustive buckets: the cheap-ask fraction of "
        "an exhaustive ladder is structurally larger than that of a lone "
        "threshold, so the two eras are different populations. G-01 separately "
        "established that WFOs are not exchangeable, so stations are not pooled "
        "either. Everything pooled below is INDICATIVE ONLY."
    )
    add("")

    add("### Era x station (PRIMARY)")
    add("")
    add(_TABLE_HEADER)
    add(_TABLE_DIVIDER)
    for era in ERAS:
        for station in sorted(set(SERIES_TO_CLI_LOCATION.values())):
            cell = [o for o in observations if o.era == era and o.station == station]
            for threshold, stratum in zip(ASK_STRATA, _strata_for(cell), strict=True):
                add(_stratum_row(f"{era} / {station}", threshold, stratum))
    add("")

    add("### Pooled across stations, WITHIN era (INDICATIVE ONLY)")
    add("")
    add("Pools cities but never eras. Reported for scale; G-01 says it is not the finding.")
    add("")
    add(_TABLE_HEADER)
    add(_TABLE_DIVIDER)
    era_strata: dict[str, list[Stratum]] = {}
    for era in ERAS:
        cell = [o for o in observations if o.era == era]
        strata = _strata_for(cell)
        era_strata[era] = strata
        for threshold, stratum in zip(ASK_STRATA, strata, strict=True):
            add(_stratum_row(f"POOLED / {era}", threshold, stratum))
    add("")

    add("### Pooled across BOTH eras (INDICATIVE ONLY -- crosses the regime break)")
    add("")
    add(
        "A pooled rate across the regime break is the one result the evidence "
        "doc forbids as a finding. It appears here ONLY alongside the "
        "stratified tables above, for scale, and must never be quoted alone."
    )
    add("")
    add(_TABLE_HEADER)
    add(_TABLE_DIVIDER)
    pooled_strata = _strata_for(observations)
    for threshold, stratum in zip(ASK_STRATA, pooled_strata, strict=True):
        add(_stratum_row("POOLED / ALL ERAS", threshold, stratum))
    add("")

    add("### Sensitivity: `yes_ask.open` branch only (no close-of-hour fallback)")
    add("")
    add(
        "The subset whose ask-at-open came from the first candlestick's `open` "
        "-- i.e. an offer standing at the open INSTANT, with no up-to-60-minute "
        "latency. Smaller and therefore weaker, but free of divergence (2)."
    )
    add("")
    add(_TABLE_HEADER)
    add(_TABLE_DIVIDER)
    for era in ERAS:
        cell = [o for o in observations if o.era == era and o.ask_field == "open"]
        for threshold, stratum in zip(ASK_STRATA, _strata_for(cell), strict=True):
            add(_stratum_row(f"OPEN-ONLY / {era}", threshold, stratum))
    add("")

    # -- 5. power -----------------------------------------------------------
    required = required_n_to_discriminate()
    add("## 5. Power")
    add("")
    add(
        f"To distinguish a true settle rate of {POWER_P_ALT:.0%} (a real edge at "
        f"a 1c ask) from {POWER_P_NULL:.0%} (no edge) at 95% confidence requires "
        f"**n = {required}** qualifying observations per cell -- K1's own "
        "`required_n_to_discriminate`, unchanged."
    )
    add("")
    add(
        "That is only the DISCRIMINATION sample. The binding constraint on a "
        "FAMILY DEAD verdict is stricter: the Wilson 95% UPPER bound must fall "
        "to break-even even when NOTHING settles YES, and at zero events that "
        "bound is `z^2 / (n + z^2)`."
    )
    add("")
    add(
        "| Stratum (ask <=) | Break-even (theta=0.07) | n to discriminate 3% from 1% "
        "| n to REFUTE at zero YES |"
    )
    add("|---:|---:|---:|---:|")
    for threshold in ASK_STRATA:
        add(
            f"| {threshold} | {break_even_for(threshold)} | {required} | "
            f"{min_n_to_refute(threshold=threshold, theta=KALSHI_TAKER_THETA)} |"
        )
    add("")
    add("| Cell | Largest n reached |")
    add("|---|---:|")
    for era in ERAS:
        add(f"| POOLED / {era} | {max((s.n for s in era_strata[era]), default=0)} |")
    largest = max((s.n for s in pooled_strata), default=0)
    add(f"| POOLED / ALL ERAS | {largest} |")
    add("")
    floor = resolution_floor(largest)
    if floor is not None:
        add(
            f"At n = {largest} the smallest Wilson 95% upper bound obtainable -- at "
            f"ZERO observed YES settlements -- is {floor:.6f}. Any break-even below "
            f"that figure is UNREACHABLE with the corpus on hand."
        )
        add("")

    add("### Effective sample: the markets are clustered, and NOT independent")
    add("")
    add("| Era | Measured markets | Distinct station-days | Markets per station-day |")
    add("|---|---:|---:|---:|")
    for era in ERAS:
        era_rows = [o for o in observations if o.era == era]
        day_count = distinct_station_days(era_rows)
        add(
            f"| {era} | {len(era_rows)} | {day_count} | {(len(era_rows) / day_count):.2f} |"
            if day_count
            else f"| {era} | {len(era_rows)} | 0 | n/a |"
        )
    all_days = distinct_station_days(observations)
    add(
        f"| ALL | {len(observations)} | {all_days} | "
        + (f"{(len(observations) / all_days):.2f} |" if all_days else "n/a |")
    )
    add("")
    add(
        "**Buckets within one station-day are NOT independent.** In the "
        "exhaustive-bucket era the ~6 markets of a station-day PARTITION the "
        "same outcome: exactly one settles YES, so the rest are forced to NO. "
        "Observations inside a day are therefore negatively correlated, the "
        "Wilson intervals above are narrower than the true uncertainty, and the "
        "EFFECTIVE sample is closer to the station-day count than to n. K1 "
        "carries this caveat on its own tape; it binds at least as hard here, "
        "where the ladder is exhaustive. Treat every n above as an upper bound "
        "on information, not a count of independent trials."
    )
    add("")

    # -- 6. verdict ---------------------------------------------------------
    verdict = headline_verdict(era_strata)
    add("## 6. VERDICT")
    add("")
    add(f"**{verdict}**")
    add("")
    add(
        "Computed as a CONJUNCTION over eras -- each era's verdict from K1's own "
        "`_overall_verdict`, then combined -- never from the pooled-across-eras "
        "table, which the evidence doc forbids as a finding. Per era: "
        + "; ".join(f"{era} = {overall_verdict(era_strata[era])}" for era in ERAS)
        + "."
    )
    add("")
    if not crawl.complete:
        add(
            "**Read this as PARTIAL.** The crawl did not cover every listed "
            "market; the verdict is the one supported by the subset cached so "
            "far and can move as the crawl completes."
        )
        add("")
    if verdict.startswith("UNDERPOWERED"):
        undecided = [
            stratum
            for era in ERAS
            for stratum in era_strata[era]
            if stratum.verdict == "UNDERPOWERED" and stratum.n > 0
        ]
        add(f"Reason: **{underpowered_reason(undecided)}**.")
        add("")
        add(
            f"No era's strata jointly clear the {POWER_P_ALT:.0%}-versus-"
            f"{POWER_P_NULL:.0%} discrimination at 95% confidence. The "
            f"discrimination sample is n = {required} per cell; the undecided "
            "cells and their reached n are:"
        )
        add("")
        add("| Era | Ask <= | n | Wilson 95% | Break-even |")
        add("|---|---:|---:|---|---:|")
        for era in ERAS:
            for threshold, stratum in zip(ASK_STRATA, era_strata[era], strict=True):
                if stratum.verdict != "UNDERPOWERED" or stratum.n == 0:
                    continue
                add(
                    f"| {era} | {threshold} | {stratum.n} | "
                    f"[{_rate(stratum.wilson_lower)}, {_rate(stratum.wilson_upper)}] | "
                    f"{stratum.break_even} |"
                )
    elif verdict == "FAMILY DEAD":
        add(
            "Every populated stratum's Wilson 95% UPPER bound sits at or below "
            "its fee-inclusive break-even at adequate n. On KALSHI, cheap D-1 "
            "rungs do not settle YES often enough to pay for themselves."
        )
    else:
        add(
            "At least one stratum's Wilson 95% LOWER bound exceeds its "
            "fee-inclusive break-even at adequate n. On KALSHI the family is not "
            "refuted and warrants the next step."
        )
    add("")
    add("### What this verdict does and does not license")
    add("")
    add(_PRIOR_DISCLAIMER)
    add("")
    add(
        "A FAMILY DEAD reading here is strong evidence about the FAMILY, because "
        "the settlement leg is identical and the sample is three orders of "
        "magnitude larger than ours. A FAMILY SURVIVES reading here licenses "
        "nothing on Polymarket.us on its own: the edge would still have to "
        "exist in OUR book, at OUR asks, against OUR fee -- which only K1 on our "
        "own tape can measure. Neither reading moves the mechanical go-live "
        "date, which is gated on the execution spine, not on data."
    )
    add("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Crawl driver and entry point
# ---------------------------------------------------------------------------


def _progress(index: int, total: int) -> None:
    if index == total or index % 250 == 0:
        pct = 100.0 * index / total if total else 100.0
        print(f"  candlesticks {index}/{total} ({pct:.1f}%)", file=sys.stderr, flush=True)


def gather(
    *,
    cache_dir: Path,
    crawl_network: bool,
    series_tickers: Sequence[str],
    max_markets: int | None = None,
    client: KalshiHttp | None = None,
) -> tuple[list[Mapping[str, Any]], dict[str, Mapping[str, Any]], CrawlSummary]:
    """List markets and resolve their first-hour candlesticks, cache-first."""
    started = time.monotonic()
    cache = CandleCache(cache_dir)
    cached_before = len(cache)
    http = client
    if crawl_network and http is None:
        http = KalshiHttp()

    markets: list[Mapping[str, Any]] = []
    for series in series_tickers:
        listed = load_cached_markets(cache_dir, series)
        if crawl_network and http is not None:
            print(f"listing {series} ...", file=sys.stderr, flush=True)
            listed = list(http.list_series_markets(series))
            store_markets(cache_dir, series, listed)
        print(f"{series}: {len(listed)} settled markets", file=sys.stderr, flush=True)
        markets.extend(listed)

    if max_markets is not None:
        markets = markets[:max_markets]

    wanted: list[str] = []
    open_by_ticker: dict[str, tuple[str, int, dt.date]] = {}
    for market in markets:
        ticker = str(market.get("ticker") or "")
        facts = parse_ticker(ticker)
        open_ts = _parse_open_ts(market.get("open_time"))
        if facts is None or open_ts is None or facts.series not in SERIES_TO_CLI_LOCATION:
            continue
        wanted.append(ticker)
        open_by_ticker[ticker] = (facts.series, open_ts, facts.climate_day)

    failures: list[tuple[str, str]] = []

    def fetch(ticker: str) -> Mapping[str, Any] | None:
        if http is None:
            return None
        series, open_ts, climate_day = open_by_ticker[ticker]
        try:
            return http.first_hour_candlesticks(
                ticker=ticker, series=series, open_ts=open_ts, climate_day=climate_day
            )
        except Exception as exc:  # noqa: BLE001 -- the count IS the finding
            failures.append((ticker, f"{type(exc).__name__}: {exc}"))
            return None

    candles = fetch_missing_candles(tickers=wanted, cache=cache, fetch=fetch, progress=_progress)
    missing = [ticker for ticker in wanted if ticker not in candles]
    summary = CrawlSummary(
        series_seen=tuple(series_tickers),
        markets_listed=len(markets),
        candles_cached=len(cache),
        candles_fetched=len(cache) - cached_before,
        fetch_failures=tuple(failures[:200]),
        complete=not missing,
        elapsed_s=time.monotonic() - started,
    )
    if missing:
        print(
            f"PARTIAL: {len(missing)} of {len(wanted)} markets have no cached candlestick",
            file=sys.stderr,
            flush=True,
        )
    return markets, dict(candles), summary


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="K1 on Kalshi -- family prior.")
    parser.add_argument(
        "--crawl",
        action="store_true",
        help="Permit network I/O. Without it the script is fully offline and "
        "analyses only what is already cached.",
    )
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR.as_posix())
    parser.add_argument(
        "--series",
        nargs="*",
        default=list(SERIES_TO_CLI_LOCATION),
        help="Series tickers to crawl (default: all five).",
    )
    parser.add_argument("--max-markets", type=int, default=None)
    parser.add_argument(
        "--output",
        default=None,
        help="Markdown snapshot path (default: <cache-dir>/k1_kalshi_<date>.md).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    cache_dir = Path(args.cache_dir)
    generated_at = dt.datetime.now(dt.UTC)
    output = (
        Path(args.output)
        if args.output
        else cache_dir / f"k1_kalshi_{generated_at.date().isoformat()}.md"
    )

    markets, candles, summary = gather(
        cache_dir=cache_dir,
        crawl_network=bool(args.crawl),
        series_tickers=list(args.series),
        max_markets=args.max_markets,
    )
    observations, ledger = build_observations(markets=markets, candles=candles)
    report = render_report(
        observations=observations,
        ledger=ledger,
        crawl=summary,
        generated_at=generated_at,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")

    pooled = _strata_for(observations)
    print(f"wrote {output}")
    print(f"MEASURED POPULATION: {len(observations)} (crawl complete: {summary.complete})")
    for threshold, stratum in zip(ASK_STRATA, pooled, strict=True):
        print(
            f"  ask<={threshold}: n={stratum.n} k={stratum.k} "
            f"pi={_rate(stratum.pi)} wilson=[{_rate(stratum.wilson_lower)}, "
            f"{_rate(stratum.wilson_upper)}] break_even={stratum.break_even} "
            f"{stratum.verdict}"
        )
    print(f"VERDICT (pooled, indicative): {overall_verdict(pooled)}")
    print("This is a KALSHI prior for the family; it cannot estimate Polymarket.us.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
