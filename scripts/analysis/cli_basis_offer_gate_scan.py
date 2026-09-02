"""CLI-basis candidate #2 -- does the venue actually OFFER the upper tail?

WHY THIS EXISTS, AND WHAT IT ADDS TO THE ARCHIVE GATE
-------------------------------------------------------
`cli_basis_boundary_study.py` gated candidate #2 against 2021-2025 archive and
PASSED: the CLI final print lands at or above `running_f + 1` often enough
(13-56% by station/hour) to make a cheap `>= X` tail +EV against a 6.285%
break-even. But that is a SETTLEMENT-FREQUENCY measurement over history, and
L-9 already refuted THREE strategy families on a completely different axis:
the venue's ladder stays liquid, but the rung that would actually win is
NEVER OFFERED (total addressable notional at the winning rung measured at
$0.574 -- negative after fees, below `min_liquidity_contracts=25`). This scan
is the missing test: on the ACTUAL captured order book, does a live ASK at or
below 0.05, in size >= the shared liquidity floor, exist at the moment the
ASOS running maximum sits 1 or 2 degrees below an open upper-tail strike?

If yes: candidate #2 clears the mechanism that killed the other three, and is
worth building execution logic for. If no: it dies the same way, for $0
instead of with capital -- and that is reported plainly, not softened.

CORRECTIONS APPLIED MID-BUILD (coordinator relay, 2026-09-02)
---------------------------------------------------------------
1. **No hour restriction.** An earlier draft of this programme considered
   restricting to local-standard hours 17-23 (the diurnal-peak-converged
   window). That framing is WRONG: `P(R_17 == R_23)` measures 99.40% at LAX
   and 95.49% at NYC, i.e. the running max has already converged by 17:00
   and an hour filter adds no discrimination. The event condition below is
   evaluated at WHATEVER time of day the headroom condition and a qualifying
   ask coincide. Local-standard hour is still recorded, per instant, as a
   DIAGNOSTIC breakdown in the report -- never as a gate.
2. **NYC is measurement-contaminated, not measurement-supporting.** KNYC
   (Central Park) reports hourly (~24 obs/day) against ~321/day at the other
   four stations. Downsampling the dense stations to NYC's cadence moves
   their measured boundary-hit rate from 15-25% to 54-65% -- landing on
   NYC's own 56-60% -- which is the signature of a sparse series
   understating the running max and mechanically inflating the boundary
   statistic. NYC is still SCANNED and its numbers are still reported, always
   labelled CONTAMINATED, but it is EXCLUDED from the `n`/`k` that feed the
   pre-registered kill rule below.

NULL HYPOTHESIS, checked before this module was written (L-1, L-11)
---------------------------------------------------------------------
* Running-max fold: `pmr_climatology_study.build_running_max_days` and
  `local_standard_hour` -- reused verbatim via import. NATIVE-EXISTS-AND-
  REUSED.
* Per-hour ASOS true-coverage (as opposed to the carried-forward running
  value): `cli_basis_boundary_study.hour_coverage` -- reused verbatim via
  import; it already has no dependency on that module's `STUDY_HOURS`
  constant, so reusing it does not smuggle the hour restriction back in.
  NATIVE-EXISTS-AND-REUSED.
* ASOS archive parsing (`parse_asos_rows`, `metar_temperatures`), site
  registry resolution (`load_sites`, `SiteSpec`, `IEM_ASOS_IDS` via
  `asos_url`'s station mapping) and the settlement-alignment cache path
  resolver -- all reused verbatim via import from `settlement_alignment_study`
  / `settlement_alignment_cache`. NATIVE-EXISTS-AND-REUSED.
* Wilson score interval, both bounds: `k1_cheap_open_settlement.wilson_interval`
  (itself built on `settlement_alignment_study.wilson_lower_bound`) -- reused
  verbatim via import, so this program cannot end up with a third disagreeing
  Wilson formula in the same repo. NATIVE-EXISTS-AND-REUSED.
* Tape-instance truncation preflight: `breezy.persistence.feather_preflight`
  (`list_instance_ids`, `scan_instance`, `PreflightReport`) is the SAME
  library the `breezy-quote-tape-preflight` console script wraps -- reused
  verbatim via import rather than re-opening feather files by hand.
  NATIVE-EXISTS-AND-REUSED.
* Weather-slug grammar: `breezy.adapters.polymarket_us.symbology.parse_weather_slug`
  -- reused verbatim via import. NATIVE-EXISTS-AND-REUSED.
* `min_liquidity_contracts`: lives in ONE place,
  `breezy.strategy.weather_common.risk.RiskLimits.min_liquidity_contracts`
  (`src/breezy/strategy/weather_common/risk.py:104`), and every shipped
  strategy config defaults to it (`=25.0`). Read here via `RiskLimits()`, not
  re-hardcoded. NATIVE-EXISTS-AND-REUSED.
* A cache-wide "scan every file for rows matching this station" ASOS loader
  (`load_recent_asos_rows` below) does NOT exist upstream: every existing
  fetch helper (`fetch_text_cached`, `read_cached`) is keyed to ONE exact URL,
  and this scan cannot know in advance what date range an incidental fetch
  used. GENUINE GAP -- see `load_recent_asos_rows` docstring for the
  hard-dependency this exists to work around (BL-24: no live intraday
  ingest).
* An instance-scoped Arrow-stream loader restricted to CLEAN instances only
  (as opposed to `k1_cheap_open_settlement`'s catalog-wide glob across every
  instance) does NOT exist upstream. GENUINE GAP, but a narrow variation on
  K1's own already-reused pattern, not a re-derivation of it.

THE HARD DEPENDENCY: NO LIVE INTRADAY ASOS INGEST (BL-24)
-------------------------------------------------------------
Breezy has ~5 years of archived 5-minute ASOS on disk, but nothing in the bot
fetches TODAY's or YESTERDAY's ASOS as capture accumulates. This scan is
therefore CACHE-ONLY and ZERO-NETWORK by construction (`load_recent_asos_rows`
never calls `httpx`; it only reads `.txt` files already sitting under the
settlement-alignment cache directory, from whatever incidental fetch put them
there). A station-day whose tape shows an open-tail market but whose ASOS
cache has no covering rows is reported as `BLOCKED: no observation data`,
never fabricated from the running value carried forward past the last real
observation, and never silently treated as a zero.

THIS IS A DAILY ACCUMULATOR, NOT A ONE-SHOT VERDICT
--------------------------------------------------------
Re-runnable by design, same as K1: run it again as capture (and, separately,
whatever incidentally refreshes the ASOS cache) accumulates. The
pre-registered kill/GO rule below is stated ONCE, in code, before any output
was read.

PRE-REGISTERED KILL / GO RULE (fixed before running; do not move after
looking at a result)
------------------------------------------------------------------------
`n` = admissible DENSE (non-NYC) station-days: station-days on which at least
one instant had BOTH a clean (non-corrupt, non-live) tape AND ASOS coverage
reaching an hour where headroom (`strike_f - running_f`) was 1 or 2 -- i.e. a
station-day where the scan COULD have observed a qualifying offer, whether or
not it did. `k` = of those, the count with >= 1 qualifying ask (price <= 0.05,
size >= `min_liquidity_contracts`) at a qualifying instant.

* **FAMILY_DEAD**: `n >= 50` and `k == 0` and the Wilson 95% UPPER bound on
  `k/n` is below 10%. (At `k=0, n=50` the Wilson upper bound is `z^2/(n+z^2)`
  = 7.1%, comfortably under 10%; the bar is stated as 10% so a stray single
  event at small `n` cannot flip the verdict by rounding.)
* **GO**: `n >= 50` AND the Wilson 95% LOWER bound on `k/n` exceeds 10%
  (mirrors the DEAD bound: confidently more than 1-in-10 dense station-days
  show a qualifying offer, which is enough addressable liquidity to be worth
  building execution logic for). `n` gates GO exactly as it gates DEAD -- a
  single lucky event at `n=1` must never read as GO, the same small-sample
  mistake `k1_cheap_open_settlement.summarize_stratum` was written to refuse.
* **UNDERPOWERED**: everything else, including every station-day short of
  `n >= 50` -- most runs, for a long time, will land here. That is expected
  and is not itself a finding.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Literal

import pyarrow as pa
from nautilus_trader.model.data import OrderBookDepth10, QuoteTick
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli_basis_boundary_study import hour_coverage
from k1_cheap_open_settlement import wilson_interval
from pmr_climatology_study import (
    RunningMaxDay,
    build_running_max_days,
    local_standard_hour,
)
from settlement_alignment_cache import (
    DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR,
)
from settlement_alignment_study import (
    SiteSpec,
    load_sites,
    metar_temperatures,
    parse_asos_rows,
)

from breezy.adapters.polymarket_us.parsing import FEE_COEFFICIENT_KEY
from breezy.adapters.polymarket_us.symbology import parse_weather_slug
from breezy.adapters.polymarket_us.tape_records import DepthTruncation
from breezy.domain.weather_bucket_facts import (
    CLIMATE_DAY_KEY,
    SETTLEMENT_STATION_KEY,
    STRIKE_LOWER_F_KEY,
    STRIKE_UPPER_F_KEY,
)
from breezy.persistence.feather_preflight import (
    PreflightError,
    PreflightReport,
    list_instance_ids,
    scan_instance,
)
from breezy.runtime.quote_tape_preflight_cli import WRITER_ACTIVITY_GRACE_NS
from breezy.strategy.weather_common.risk import RiskLimits

__all__ = [
    "BLOCKED_NO_OBSERVATION_DATA",
    "BLOCKED_NO_QUALIFYING_SETUP",
    "BLOCKED_TAPE_PREFLIGHT_FAILED",
    "CHEAP_ASK_CEILING",
    "CONTAMINATED_STATIONS",
    "DEAD_UPPER_BOUND",
    "GO_LOWER_BOUND",
    "MIN_ADMISSIBLE_N",
    "MIN_LIQUIDITY_CONTRACTS",
    "QUALIFYING_HEADROOM",
    "AskLevel",
    "InstrumentFacts",
    "StationDayResult",
    "classify_blocked_reason",
    "classify_instance",
    "fee_coefficient_from_instrument",
    "genuine_ask_levels",
    "headroom_f",
    "is_open_upper_tail_facts",
    "is_open_upper_tail_slug",
    "is_qualifying_headroom",
    "kill_rule_verdict",
    "load_recent_asos_rows",
    "main",
    "notional_at_qualifying_levels",
    "qualifying_ask_levels",
    "station_days_only_on_corrupt_tape",
]

VENUE: Final[str] = "polymarket_us"

DEFAULT_QUOTE_TAPE_PATH: Final[Path] = (
    Path.home() / ".local/share/breezy/catalog/quote_tape/polymarket_us"
)
DEFAULT_ASOS_CACHE_DIR: Final[Path] = DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR
DEFAULT_OUTPUT_PATH: Final[Path] = Path("docs/evidence/cli_basis_offer_gate_placeholder.md")

#: The single shared floor every strategy's `RiskLimits` defaults to
#: (`src/breezy/strategy/weather_common/risk.py:104`). Read, never re-typed.
MIN_LIQUIDITY_CONTRACTS: Final[Decimal] = Decimal(str(RiskLimits().min_liquidity_contracts))

#: The cheap-offer ceiling this candidate trades at, per the brief.
CHEAP_ASK_CEILING: Final[Decimal] = Decimal("0.05")

#: The boundary this thesis is about: the ASOS running max sits 1 or 2 whole
#: degrees below the strike -- "just missed", the exact belief a seller
#: anchored to ASOS would price the tail as dead on.
QUALIFYING_HEADROOM: Final[frozenset[int]] = frozenset({1, 2})

#: KNYC reports hourly; the other four stations report at ~5-minute cadence.
#: See the module docstring's "CORRECTIONS APPLIED" section for the measured
#: contamination. Still scanned, never in the kill-rule aggregate.
CONTAMINATED_STATIONS: Final[frozenset[str]] = frozenset({"NYC"})

#: Pre-registered kill/GO thresholds. See the module docstring.
MIN_ADMISSIBLE_N: Final[int] = 50
DEAD_UPPER_BOUND: Final[float] = 0.10
GO_LOWER_BOUND: Final[float] = 0.10

InstanceVerdict = Literal["CLEAN", "EMPTY", "LIVE", "CORRUPT"]

#: The three DISTINCT reasons a station-day can be inadmissible (Item 2: the
#: prior single conflated reason -- "ASOS coverage never reached a
#: headroom-1-or-2 instant" -- silently merged "we hold no ASOS for this
#: station-day, so we cannot know" with "we hold the ASOS and the headroom
#: genuinely never reached 1-2", which are different facts feeding different
#: conclusions. Only `BLOCKED_NO_QUALIFYING_SETUP` is a genuine base-rate
#: observation; the other two mean the day teaches us nothing either way.
BLOCKED_NO_OBSERVATION_DATA: Final[str] = "NO_OBSERVATION_DATA"
BLOCKED_NO_QUALIFYING_SETUP: Final[str] = "NO_QUALIFYING_SETUP"
BLOCKED_TAPE_PREFLIGHT_FAILED: Final[str] = "TAPE_PREFLIGHT_FAILED"

BLOCKED_REASON_DESCRIPTIONS: Final[Mapping[str, str]] = {
    BLOCKED_NO_OBSERVATION_DATA: (
        "no cached ASOS observation for this station -- fixable by fetching, "
        "not evidence about the setup's base rate"
    ),
    BLOCKED_NO_QUALIFYING_SETUP: (
        "ASOS coverage exists but headroom never reached 1-or-2 this "
        "station-day -- a genuine no-setup day"
    ),
    BLOCKED_TAPE_PREFLIGHT_FAILED: (
        "this station-day's open-tail instrument exists ONLY on a CORRUPT "
        "quote-tape instance -- its quotes cannot be trusted, independent of "
        "ASOS coverage"
    ),
}


# ---------------------------------------------------------------------------
# Open-tail vs interior classification
# ---------------------------------------------------------------------------


def is_open_upper_tail_facts(*, lower_f: int | None, upper_f: int | None) -> bool:
    """Is this an open `>= X` upper tail, per the instrument's OWN strike facts?

    Authoritative: `strike_lower_f` / `strike_upper_f` are populated by the
    ingestion pipeline from the venue's own description/title, CROSS-CHECKED
    against the slug (`symbology.py` module docstring -- "THE SLUG IS NOT THE
    SOURCE OF TRUTH FOR THE COMPARATOR"). An open upper tail has a lower bound
    and NO upper bound; an interior bucket has both; an open LOWER tail (the
    bottom rung, e.g. `lt76f`) has an upper bound and no lower bound and is
    explicitly NOT this shape.
    """
    return lower_f is not None and upper_f is None


def is_open_upper_tail_slug(slug: str) -> bool | None:
    """Cross-check classification straight from the slug grammar.

    Returns `None` when the slug does not parse at all (an honest "cannot
    tell", never a guess). A single `gte<N>f` token is the open upper tail;
    `gte<A>lt<B>f` is interior; a single `lt<N>f` token is the open LOWER
    tail (the wrong side). Confirmed against real tape slugs, not assumed:
    `tc-temp-sfohigh-2026-09-01-gte72f` (open tail), `tc-temp-nychigh-
    2026-09-01-gte82lt83f` (interior), `tc-temp-laxhigh-2026-09-01-lt76f`
    (open lower tail).
    """
    parsed = parse_weather_slug(slug)
    if parsed is None:
        return None
    if parsed.measure != "high":
        return False
    return len(parsed.bounds) == 1 and parsed.bounds[0][0] == "gte"


# ---------------------------------------------------------------------------
# Headroom boundary: X - R(t) in {1, 2}
# ---------------------------------------------------------------------------


def headroom_f(*, strike_f: int, running_f: int) -> int:
    """How far the ASOS running maximum sits BELOW the open tail's strike."""
    return strike_f - running_f


def is_qualifying_headroom(headroom: int) -> bool:
    return headroom in QUALIFYING_HEADROOM


# ---------------------------------------------------------------------------
# Ask levels: genuine, then qualifying (price <= 0.05 AND size >= floor)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AskLevel:
    """One priced, sized ask level -- from a depth snapshot or a quote top."""

    price: Decimal
    size: Decimal


def genuine_ask_levels(levels: Iterable[AskLevel]) -> tuple[AskLevel, ...]:
    """Levels a taker could actually lift.

    `OrderBookDepth10` pads unfilled levels with price/size 0.00, and a price
    of 1.00 is the top of the binary range (nothing above it can be won, so
    it is not a tradeable cheap-tail offer either). Same predicate as
    `k1_cheap_open_settlement.is_genuine_ask`, applied per-level instead of
    per-observation because this scan needs every qualifying level, not just
    the best one, to compute addressable notional.
    """
    return tuple(level for level in levels if level.size > 0 and 0 < level.price < 1)


def qualifying_ask_levels(
    levels: Iterable[AskLevel],
    *,
    ceiling: Decimal = CHEAP_ASK_CEILING,
    min_size: Decimal = MIN_LIQUIDITY_CONTRACTS,
) -> tuple[AskLevel, ...]:
    """Genuine levels that ALSO clear both bars this candidate trades at.

    Both bars are inclusive at their edge (`<=` / `>=`): a size or price
    landing exactly on the floor/ceiling is tradeable, not excluded.
    """
    genuine = genuine_ask_levels(levels)
    return tuple(level for level in genuine if level.price <= ceiling and level.size >= min_size)


def notional_at_qualifying_levels(levels: Iterable[AskLevel]) -> Decimal:
    """Dollar cost to buy every qualifying level at ONE snapshot instant.

    The direct comparator to the $0.574 figure that killed the prior three
    families (L-9). Deliberately NOT summed across time: the same resting
    order sampled on repeated polls is one unit of liquidity, not one per
    poll, so the per-station-day report takes the MAXIMUM single-instant
    total observed that day (see `_aggregate_station_day`), never a running
    sum across observations.
    """
    total = Decimal(0)
    for level in levels:
        total += level.price * level.size
    return total


# ---------------------------------------------------------------------------
# Tape-instance preflight classification (L-8)
# ---------------------------------------------------------------------------


def classify_instance(
    report: PreflightReport, *, now_ns: int, grace_ns: int = WRITER_ACTIVITY_GRACE_NS
) -> InstanceVerdict:
    """CLEAN / EMPTY / LIVE / CORRUPT, from the shared preflight primitives.

    `LIVE` (not `CORRUPT`) only when EVERY truncated/unreadable file was
    written within `grace_ns` of `now_ns` -- a live writer's tail is
    byte-identical to a cut one (`quote_tape_preflight_cli.py` module
    docstring), so recency is the only honest discriminator. A single stale
    truncation among several fresh ones still means CORRUPT: a real loss
    must never be laundered by pooling it with an unrelated live instance.
    """
    if report.captured_nothing:
        return "EMPTY"
    if report.has_truncation:
        bad_files = report.truncated + report.unreadable
        if all(now_ns - f.mtime_ns < grace_ns for f in bad_files):
            return "LIVE"
        return "CORRUPT"
    return "CLEAN"


# ---------------------------------------------------------------------------
# Blocked-reason classification (Item 2: split the conflated reason)
# ---------------------------------------------------------------------------


def classify_blocked_reason(*, boundary_hits: int, asos_row_count: int) -> str | None:
    """Which of the three BLOCKED states applies, or `None` if admissible.

    `boundary_hits > 0` means the scan COULD have observed a qualifying
    offer this station-day (ASOS coverage reached a headroom-1-or-2 instant
    on a CLEAN tape), regardless of whether one was actually found -- that
    is admissibility, unchanged from before this split. Below that, the
    reason is exactly one of two DIFFERENT facts, previously conflated into
    one sentence: zero cached ASOS rows for the station means "we cannot
    know" (`BLOCKED_NO_OBSERVATION_DATA`); ASOS rows present but the
    boundary never held means "we know, and it didn't happen"
    (`BLOCKED_NO_QUALIFYING_SETUP`) -- a genuine, countable base-rate fact.
    Only the second may ever be read as evidence about how often the setup
    occurs; the first is fixable by fetching, and must never be silently
    folded into the same denominator.
    """
    if boundary_hits > 0:
        return None
    if asos_row_count == 0:
        return BLOCKED_NO_OBSERVATION_DATA
    return BLOCKED_NO_QUALIFYING_SETUP


def station_days_only_on_corrupt_tape(
    *,
    corrupt_station_days: Iterable[tuple[str, dt.date]],
    clean_station_days: Iterable[tuple[str, dt.date]],
) -> frozenset[tuple[str, dt.date]]:
    """Station-days whose open-tail instrument exists ONLY on CORRUPT tape.

    A station-day whose only sighting is inside a CORRUPT-classified
    instance never reaches the clean-instance pipeline at all today, so it
    is invisible to the report -- not even a row -- and a missing row reads,
    incorrectly, as "this station-day never had an open-tail market". This
    is the THIRD blocked state (Item 2): a real data-loss incident (L-8),
    orthogonal to ASOS coverage, and it must be surfaced as its own row
    rather than silently absorbed into either ASOS-based reason.
    """
    return frozenset(corrupt_station_days) - frozenset(clean_station_days)


# ---------------------------------------------------------------------------
# Fee-coefficient extraction -- best-effort, diagnostic only (never charges)
# ---------------------------------------------------------------------------


def fee_coefficient_from_instrument(instrument: BinaryOption) -> Decimal | None:
    """This market's `theta`, read from `instrument.info`, or `None`.

    Mirrors `PolymarketUSFeeModel`'s own read of
    `instrument.info[FEE_COEFFICIENT_KEY]`
    (`breezy.adapters.polymarket_us.fees._fee_coefficient`) -- NEVER a second,
    hardcoded value -- but is deliberately non-raising: this scan reports
    theta as a diagnostic fact about a qualifying event, not as a live fee
    charge, so a market whose coefficient is absent or unparseable is
    reported as `None` ("fee unknown") rather than aborting the whole scan.
    """
    info = instrument.info
    if not isinstance(info, Mapping):
        return None
    raw = info.get(FEE_COEFFICIENT_KEY)
    if raw is None or isinstance(raw, bool):
        return None
    try:
        theta = Decimal(str(raw))
    except Exception:  # noqa: BLE001 -- any malformed value is just "unknown"
        return None
    if not theta.is_finite() or theta < 0 or theta > 1:
        return None
    return theta


# ---------------------------------------------------------------------------
# Recent ASOS cache loader -- cache-only, zero network (BL-24 workaround)
# ---------------------------------------------------------------------------


def load_recent_asos_rows(cache_dir: Path, iem_asos_id: str) -> tuple[Mapping[str, str], ...]:
    """Every cached ASOS row for `iem_asos_id`, from WHATEVER is on disk.

    THE HARD DEPENDENCY (BL-24): there is no live intraday ASOS ingest in
    Breezy, so nothing guarantees the settlement-alignment cache holds
    anything for a tape-era date. What sometimes DOES exist is an incidental
    fetch some other analysis made with its own arbitrary date range (this
    repo's `fetch_text_cached` keys its cache file on the exact request URL,
    hashed -- `settlement_bucket_gate.cache_path_for_url` -- so this scan
    cannot know in advance what URL, and therefore what cache filename, an
    earlier fetch used). Reconstructing "the" URL for a target date and
    hoping it collides with a differently-parameterised earlier fetch would
    silently under-read a cache that actually has the answer.

    So instead of one exact-URL lookup, this reads and parses EVERY `.txt`
    file already in `cache_dir` with the existing, reused
    `settlement_alignment_study.parse_asos_rows`, and keeps only rows whose
    `station` column matches `iem_asos_id`, de-duplicated on
    `(station, valid)` (two overlapping incidental fetches cover the same
    instant). ZERO NETWORK: a missing or nonexistent cache directory, or a
    station never incidentally fetched, returns `()` -- never fabricated,
    never fetched, matching `settlement_bucket_gate.read_cached`'s refusal
    philosophy but generalised across whatever cache entries exist.
    """
    if not cache_dir.is_dir():
        return ()
    seen: set[tuple[str, str]] = set()
    rows: list[Mapping[str, str]] = []
    for path in sorted(cache_dir.glob("*.txt")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for row in parse_asos_rows(text):
            if row.get("station") != iem_asos_id:
                continue
            key = (row.get("station", ""), row.get("valid", ""))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return tuple(sorted(rows, key=lambda r: r.get("valid", "")))


# ---------------------------------------------------------------------------
# Instrument facts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InstrumentFacts:
    """The open-upper-tail rung identity this scan joins tape observations on."""

    instrument_id: str
    station: str
    climate_day: dt.date
    strike_f: int


def _instrument_facts(instrument: BinaryOption) -> InstrumentFacts | None:
    """Open-upper-tail facts for one instrument, or `None` if it is not one.

    Cross-checks the authoritative strike facts against the slug grammar and
    SKIPS (does not raise) on disagreement -- a single mis-classified rung
    must not crash a nightly job, but silently trusting either source alone
    would repeat exactly the mistake `symbology.py` was written to prevent.
    Disagreements are counted by the caller as an exclusion reason.
    """
    info = instrument.info
    try:
        station = str(info[SETTLEMENT_STATION_KEY])
        climate_day = dt.date.fromisoformat(str(info[CLIMATE_DAY_KEY]))
        raw_lower = info[STRIKE_LOWER_F_KEY]
        raw_upper = info[STRIKE_UPPER_F_KEY]
    except (KeyError, ValueError):
        return None
    lower_f = None if raw_lower is None else int(raw_lower)
    upper_f = None if raw_upper is None else int(raw_upper)
    if not is_open_upper_tail_facts(lower_f=lower_f, upper_f=upper_f):
        return None
    assert lower_f is not None  # narrowed by is_open_upper_tail_facts
    slug_verdict = is_open_upper_tail_slug(str(instrument.id).split(".", 1)[0])
    if slug_verdict is False:
        return None  # facts/slug disagree; refuse rather than guess
    return InstrumentFacts(
        instrument_id=str(instrument.id),
        station=station,
        climate_day=climate_day,
        strike_f=lower_f,
    )


# ---------------------------------------------------------------------------
# Tape reading, scoped to CLEAN instances only
# ---------------------------------------------------------------------------


def _read_arrow_table(path: Path) -> pa.Table:
    if path.suffix == ".parquet":
        import pyarrow.parquet as pq

        return pq.read_table(path)
    with pa.ipc.open_stream(pa.memory_map(str(path))) as reader:
        return reader.read_all()


def _instance_files(instance_dir: Path, folder: str) -> list[Path]:
    """Every feather file for one data class, in EITHER tape layout.

    `binary_option` / `instrument_close` / `instrument_status` /
    `custom_venue_clock_offset` are written as flat, prefixed files directly
    under the instance root (e.g. `binary_option_<ts>.feather`) -- there is
    no `binary_option/` subdirectory. `order_book_depths`, `quote_tick`,
    `custom_depth_truncation` and the other per-market streams DO nest one
    subdirectory per instrument. Both layouts are globbed for unconditionally
    so a caller never has to know which one a given `folder` uses; only one
    pattern will ever match for a given `folder`.
    """
    return (
        sorted(instance_dir.glob(f"{folder}_*.feather"))
        + sorted(instance_dir.glob(f"{folder}/*.feather"))
        + sorted(instance_dir.glob(f"{folder}/*/*.feather"))
    )


def _load_stream(instance_dirs: Sequence[Path], folder: str, data_cls: type) -> list[Any]:
    seen: set[tuple[str, int, int]] = set()
    objects: list[Any] = []
    for instance_dir in instance_dirs:
        for path in _instance_files(instance_dir, folder):
            try:
                table = _read_arrow_table(path)
                parsed = ArrowSerializer.deserialize(data_cls, table)
            except Exception as exc:  # noqa: BLE001 -- a CLEAN instance should never fail here
                # Loud, not silent: a CLEAN-classified instance failing to
                # parse would mean the preflight and the reader disagree,
                # which is itself a finding worth seeing on stderr.
                print(f"[offer-gate] unexpected parse failure on {path}: {exc}", file=sys.stderr)
                continue
            for obj in parsed:
                identifier = getattr(obj, "instrument_id", None)
                instrument_id = str(obj.id if identifier is None else identifier)
                key = (instrument_id, int(obj.ts_event), int(obj.ts_init))
                if key in seen:
                    continue
                seen.add(key)
                objects.append(obj)
    return objects


# ---------------------------------------------------------------------------
# Boundary + ask join
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QualifyingInstant:
    station: str
    climate_day: dt.date
    hour: int
    strike_f: int
    running_f: int
    best_ask: Decimal
    best_ask_size: Decimal
    notional: Decimal
    #: The instrument identity and the FULL qualifying ask-level breakdown at
    #: this instant -- needed downstream (Item 1's settlement join) to price
    #: realized fees exactly, level by level, rather than approximating from
    #: the aggregate notional alone.
    instrument_id: str = ""
    levels: tuple[AskLevel, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class StationDayResult:
    """One `(station, climate_day)`'s offer-gate outcome."""

    station: str
    climate_day: dt.date
    dense: bool
    admissible: bool
    event: bool
    n_qualifying_instants: int
    best_ask: Decimal | None
    best_ask_size: Decimal | None
    max_notional: Decimal
    blocked_reason: str | None
    hour_histogram: Mapping[int, int] = field(default_factory=dict)
    #: The open-tail rung's own strike, and the peak-notional instant's full
    #: identity/level breakdown/fee facts -- populated only when `event` is
    #: True, and consumed by the settlement-join module (Item 1) rather than
    #: recomputed there. `None`/`()` for every non-event row.
    strike_f: int | None = None
    peak_instrument_id: str | None = None
    peak_levels: tuple[AskLevel, ...] = field(default_factory=tuple)
    fee_coefficient: Decimal | None = None
    quote_currency_precision: int | None = None


def _ns_to_utc(ts_ns: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(ts_ns / 1_000_000_000, dt.UTC)


def _asos_rows_by_climate_day(
    *, spec: SiteSpec, cache_dir: Path
) -> tuple[dict[dt.date, RunningMaxDay], dict[dt.date, frozenset[int]], int]:
    raw_rows = load_recent_asos_rows(cache_dir, spec.iem_asos_id)
    if not raw_rows:
        return {}, {}, 0
    temperatures, _drops = metar_temperatures(
        city=spec.city, rows=raw_rows, std_utc_offset_hours=spec.std_utc_offset_hours
    )
    running_days = build_running_max_days(
        city=spec.city, temperatures=temperatures, std_utc_offset_hours=spec.std_utc_offset_hours
    )
    coverage = hour_coverage(temperatures, std_utc_offset_hours=spec.std_utc_offset_hours)
    by_day = {day.climate_day: day for day in running_days}
    return by_day, coverage, len(raw_rows)


def _depth_ask_levels(depth: OrderBookDepth10) -> tuple[AskLevel, ...]:
    return tuple(
        AskLevel(price=Decimal(str(level.price)), size=Decimal(str(level.size)))
        for level in depth.asks
    )


def _evaluate_instrument(
    *,
    facts: InstrumentFacts,
    depth_by_instrument: Mapping[str, list[OrderBookDepth10]],
    quote_by_instrument: Mapping[str, list[QuoteTick]],
    running_days: Mapping[dt.date, RunningMaxDay],
    covered_hours: Mapping[dt.date, frozenset[int]],
    offset_hours: float,
) -> tuple[list[QualifyingInstant], int]:
    """Every qualifying instant for one open-tail instrument, plus a count of
    instants where the boundary held (admissible) whether or not it qualified.
    """
    running_day = running_days.get(facts.climate_day)
    covered = covered_hours.get(facts.climate_day, frozenset())
    qualifying: list[QualifyingInstant] = []
    boundary_hits = 0

    observations: list[tuple[int, tuple[AskLevel, ...]]] = []
    for depth in depth_by_instrument.get(facts.instrument_id, ()):
        observations.append((int(depth.ts_event), _depth_ask_levels(depth)))
    for quote in quote_by_instrument.get(facts.instrument_id, ()):
        observations.append(
            (
                int(quote.ts_event),
                (
                    AskLevel(
                        price=Decimal(str(quote.ask_price)), size=Decimal(str(quote.ask_size))
                    ),
                ),
            )
        )

    if running_day is None:
        return qualifying, boundary_hits

    for ts_event_ns, levels in observations:
        hour = local_standard_hour(_ns_to_utc(ts_event_ns), offset_hours)
        if hour not in covered:
            continue  # ASOS coverage does not reach this instant -- BLOCKED, not a zero
        running_f = running_day.running_max_f[hour]
        if running_f is None:
            continue
        if not is_qualifying_headroom(headroom_f(strike_f=facts.strike_f, running_f=running_f)):
            continue
        boundary_hits += 1
        qualifiers = qualifying_ask_levels(levels)
        if not qualifiers:
            continue
        best = min(qualifiers, key=lambda level: level.price)
        qualifying.append(
            QualifyingInstant(
                station=facts.station,
                climate_day=facts.climate_day,
                hour=hour,
                strike_f=facts.strike_f,
                running_f=running_f,
                best_ask=best.price,
                best_ask_size=best.size,
                notional=notional_at_qualifying_levels(qualifiers),
                instrument_id=facts.instrument_id,
                levels=qualifiers,
            )
        )
    return qualifying, boundary_hits


def _aggregate_station_day(
    *,
    station: str,
    climate_day: dt.date,
    instants: Sequence[QualifyingInstant],
    admissible: bool,
    blocked_reason: str | None,
) -> StationDayResult:
    histogram: Counter[int] = Counter(instant.hour for instant in instants)
    if not instants:
        return StationDayResult(
            station=station,
            climate_day=climate_day,
            dense=station not in CONTAMINATED_STATIONS,
            admissible=admissible,
            event=False,
            n_qualifying_instants=0,
            best_ask=None,
            best_ask_size=None,
            max_notional=Decimal(0),
            blocked_reason=blocked_reason,
            hour_histogram=dict(histogram),
        )
    best_instant = min(instants, key=lambda i: i.best_ask)
    peak_notional_instant = max(instants, key=lambda i: i.notional)
    return StationDayResult(
        station=station,
        climate_day=climate_day,
        dense=station not in CONTAMINATED_STATIONS,
        admissible=True,
        event=True,
        n_qualifying_instants=len(instants),
        best_ask=best_instant.best_ask,
        best_ask_size=best_instant.best_ask_size,
        max_notional=peak_notional_instant.notional,
        blocked_reason=None,
        hour_histogram=dict(histogram),
        strike_f=peak_notional_instant.strike_f,
        peak_instrument_id=peak_notional_instant.instrument_id,
        peak_levels=peak_notional_instant.levels,
    )


# ---------------------------------------------------------------------------
# Kill / GO rule
# ---------------------------------------------------------------------------


def kill_rule_verdict(*, n: int, k: int) -> tuple[str, float, float]:
    """`(verdict, wilson_lower, wilson_upper)` under the pre-registered rule."""
    if n <= 0:
        return "UNDERPOWERED", 0.0, 1.0
    interval = wilson_interval(k, n)
    assert interval is not None  # n > 0 guarantees a defined interval
    lower, upper = interval
    if n < MIN_ADMISSIBLE_N:
        # n gates BOTH directional verdicts, not just the negative one -- a
        # single lucky event at small n must never read as GO, the same
        # small-sample mistake `k1_cheap_open_settlement.summarize_stratum`
        # was written to refuse.
        return "UNDERPOWERED", lower, upper
    if k == 0 and upper < DEAD_UPPER_BOUND:
        return "FAMILY_DEAD", lower, upper
    if lower > GO_LOWER_BOUND:
        return "GO", lower, upper
    return "UNDERPOWERED", lower, upper


# ---------------------------------------------------------------------------
# Instance discovery + orchestration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InstanceClassification:
    instance_id: str
    verdict: InstanceVerdict
    total_rows: int


def _classify_all_instances(tape_root: Path, *, now_ns: int) -> list[InstanceClassification]:
    try:
        instance_ids = list_instance_ids(tape_root, "live")
    except PreflightError:
        return []
    results: list[InstanceClassification] = []
    for instance_id in instance_ids:
        try:
            report = scan_instance(tape_root, instance_id, "live")
        except PreflightError:
            continue
        results.append(
            InstanceClassification(
                instance_id=instance_id,
                verdict=classify_instance(report, now_ns=now_ns),
                total_rows=report.total_rows,
            )
        )
    return results


def build_scan(
    *, tape_root: Path, asos_cache_dir: Path, now_ns: int | None = None
) -> dict[str, Any]:
    """Run the full offer-gate scan. Returns the raw ingredients for the report."""
    now = int(dt.datetime.now(dt.UTC).timestamp() * 1_000_000_000) if now_ns is None else now_ns
    classifications = _classify_all_instances(tape_root, now_ns=now)
    clean_dirs = [
        tape_root / "live" / c.instance_id for c in classifications if c.verdict == "CLEAN"
    ]
    corrupt_dirs = [
        tape_root / "live" / c.instance_id for c in classifications if c.verdict == "CORRUPT"
    ]

    binary_options = _load_stream(clean_dirs, "binary_option", BinaryOption)
    # Identity-only read of CORRUPT instances' instrument registrations, so a
    # station-day that exists ONLY on a corrupt tape (Item 2's third blocked
    # state) is detected at all -- never used for quotes/depths/fees, which
    # stay CLEAN-only throughout.
    corrupt_binary_options = _load_stream(corrupt_dirs, "binary_option", BinaryOption)
    corrupt_station_days = {
        (facts.station, facts.climate_day)
        for facts in (_instrument_facts(instrument) for instrument in corrupt_binary_options)
        if facts is not None
    }
    depths = _load_stream(clean_dirs, "order_book_depths", OrderBookDepth10)
    quotes = _load_stream(clean_dirs, "quote_tick", QuoteTick)
    truncations = _load_stream(clean_dirs, "custom_depth_truncation", DepthTruncation)

    facts_by_id: dict[str, InstrumentFacts] = {}
    excluded_not_open_tail = 0
    for instrument in binary_options:
        facts = _instrument_facts(instrument)
        if facts is None:
            excluded_not_open_tail += 1
            continue
        facts_by_id[facts.instrument_id] = facts

    depth_by_instrument: dict[str, list[OrderBookDepth10]] = defaultdict(list)
    for depth in depths:
        depth_by_instrument[str(depth.instrument_id)].append(depth)
    quote_by_instrument: dict[str, list[QuoteTick]] = defaultdict(list)
    for quote in quotes:
        quote_by_instrument[str(quote.instrument_id)].append(quote)
    truncated_ask_snapshots = sum(
        1 for t in truncations if t.ask_levels_seen and t.levels_dropped > 0
    )

    sites_by_cli_location = {spec.site.cli_location: spec for spec in load_sites()}
    stations_needed = {facts.station for facts in facts_by_id.values()}
    running_by_station: dict[str, dict[dt.date, RunningMaxDay]] = {}
    coverage_by_station: dict[str, dict[dt.date, frozenset[int]]] = {}
    asos_row_counts: dict[str, int] = {}
    for station in stations_needed:
        spec = sites_by_cli_location.get(station)
        if spec is None:
            continue
        running_by_station[station], coverage_by_station[station], asos_row_counts[station] = (
            _asos_rows_by_climate_day(spec=spec, cache_dir=asos_cache_dir)
        )

    by_station_day: dict[tuple[str, dt.date], list[QualifyingInstant]] = defaultdict(list)
    boundary_hits_by_day: dict[tuple[str, dt.date], int] = defaultdict(int)
    station_days_seen: set[tuple[str, dt.date]] = set()
    for facts in facts_by_id.values():
        station_days_seen.add((facts.station, facts.climate_day))
        spec = sites_by_cli_location.get(facts.station)
        if spec is None:
            continue
        qualifying, boundary_hits = _evaluate_instrument(
            facts=facts,
            depth_by_instrument=depth_by_instrument,
            quote_by_instrument=quote_by_instrument,
            running_days=running_by_station.get(facts.station, {}),
            covered_hours=coverage_by_station.get(facts.station, {}),
            offset_hours=spec.std_utc_offset_hours,
        )
        by_station_day[(facts.station, facts.climate_day)].extend(qualifying)
        boundary_hits_by_day[(facts.station, facts.climate_day)] += boundary_hits

    binary_option_by_id = {str(instrument.id): instrument for instrument in binary_options}

    results: list[StationDayResult] = []
    for station, climate_day in sorted(station_days_seen):
        instants = by_station_day.get((station, climate_day), [])
        hits = boundary_hits_by_day.get((station, climate_day), 0)
        blocked_reason = classify_blocked_reason(
            boundary_hits=hits, asos_row_count=asos_row_counts.get(station, 0)
        )
        result = _aggregate_station_day(
            station=station,
            climate_day=climate_day,
            instants=instants,
            admissible=blocked_reason is None,
            blocked_reason=blocked_reason,
        )
        if result.event and result.peak_instrument_id is not None:
            instrument = binary_option_by_id.get(result.peak_instrument_id)
            if instrument is not None:
                result = replace(
                    result,
                    fee_coefficient=fee_coefficient_from_instrument(instrument),
                    quote_currency_precision=instrument.quote_currency.precision,
                )
        results.append(result)

    # Item 2's third blocked state: a station-day whose open-tail instrument
    # exists ONLY on a CORRUPT tape instance never reaches `station_days_seen`
    # (which is derived from CLEAN instances only) and would otherwise be
    # invisible -- not even a row -- rather than reported as a real, named
    # data-loss incident.
    tape_failed_station_days = station_days_only_on_corrupt_tape(
        corrupt_station_days=corrupt_station_days, clean_station_days=station_days_seen
    )
    for station, climate_day in sorted(tape_failed_station_days):
        results.append(
            _aggregate_station_day(
                station=station,
                climate_day=climate_day,
                instants=(),
                admissible=False,
                blocked_reason=BLOCKED_TAPE_PREFLIGHT_FAILED,
            )
        )
    results.sort(key=lambda r: (r.station, r.climate_day))

    dense_admissible = [r for r in results if r.dense and r.admissible]
    n = len(dense_admissible)
    k = sum(1 for r in dense_admissible if r.event)
    verdict, wilson_lower, wilson_upper = kill_rule_verdict(n=n, k=k)

    return {
        "generated_at": dt.datetime.now(dt.UTC),
        "tape_root": tape_root,
        "asos_cache_dir": asos_cache_dir,
        "instance_classifications": classifications,
        "excluded_not_open_tail": excluded_not_open_tail,
        "truncated_ask_snapshots": truncated_ask_snapshots,
        "asos_row_counts": asos_row_counts,
        "station_day_results": results,
        "n": n,
        "k": k,
        "verdict": verdict,
        "wilson_lower": wilson_lower,
        "wilson_upper": wilson_upper,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render_report(scan: Mapping[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    add("# CLI-basis candidate #2 -- offer-gate scan (daily)")
    add("")
    generated_at: dt.datetime = scan["generated_at"]
    add(f"Generated {generated_at.isoformat(timespec='seconds').replace('+00:00', 'Z')}")
    add(f"- Quote tape: `{scan['tape_root']}`")
    add(f"- ASOS cache (cache-only, zero network): `{scan['asos_cache_dir']}`")
    add(
        "- Regenerate: "
        "`.venv/bin/python scripts/analysis/cli_basis_offer_gate_scan.py`"
    )
    add("")

    add("## 1. Tape-instance preflight")
    add("")
    add("| Instance | Verdict | Rows |")
    add("|---|---|---:|")
    for c in scan["instance_classifications"]:
        add(f"| `{c.instance_id}` | {c.verdict} | {c.total_rows} |")
    add("")
    add(
        f"Excluded (not an open upper-tail rung, or facts/slug disagreed): "
        f"{scan['excluded_not_open_tail']}"
    )
    add(
        f"Ask-side depth-truncated snapshots observed: "
        f"{scan['truncated_ask_snapshots']} (truncation drops only DEEPER, "
        "more expensive levels -- see module docstring; a cheap qualifying "
        "ask is never hidden by it, but total notional under truncation is a "
        "lower bound)."
    )
    add("")

    add("## 2. ASOS cache coverage found (BL-24: no live intraday ingest)")
    add("")
    add("| Station | Cached rows found |")
    add("|---|---:|")
    for station, count in sorted(scan["asos_row_counts"].items()):
        add(f"| {station} | {count} |")
    add("")

    add("## 3. Per station-day results")
    add("")
    add(
        "| Station | Climate day | Dense? | Admissible | Event | Qualifying "
        "instants | Strike | Best ask | Size | Max notional | Blocked reason |"
    )
    add("|---|---|:--:|:--:|:--:|---:|---:|---:|---:|---:|---|")
    for r in scan["station_day_results"]:
        label = "CONTAMINATED" if not r.dense else "dense"
        reason_text = "-"
        if r.blocked_reason is not None:
            reason_text = (
                f"{r.blocked_reason} ({BLOCKED_REASON_DESCRIPTIONS.get(r.blocked_reason, '')})"
            )
        add(
            f"| {r.station} | {r.climate_day.isoformat()} | {label} | "
            f"{'yes' if r.admissible else 'no'} | {'YES' if r.event else 'no'} | "
            f"{r.n_qualifying_instants} | "
            f"{'gte' + str(r.strike_f) + 'f' if r.strike_f is not None else '-'} | "
            f"{r.best_ask if r.best_ask is not None else '-'} | "
            f"{r.best_ask_size if r.best_ask_size is not None else '-'} | "
            f"{r.max_notional} | {reason_text} |"
        )
    add("")
    add("### Hour-of-day breakdown (diagnostic only -- NOT a gate; see docstring)")
    add("")
    for r in scan["station_day_results"]:
        if r.hour_histogram:
            hours = ", ".join(f"{h:02d}:00={n}" for h, n in sorted(r.hour_histogram.items()))
            add(f"- {r.station} {r.climate_day.isoformat()}: {hours}")
    add("")

    add("## 4. Pre-registered kill / GO rule")
    add("")
    add(
        "`n` counts admissible DENSE (non-NYC) station-days only; `k` counts "
        "those with >= 1 qualifying event."
    )
    add(
        f"n = {scan['n']}, k = {scan['k']}, Wilson 95% lower = "
        f"{scan['wilson_lower']:.4f}, upper = {scan['wilson_upper']:.4f}"
    )
    add("")
    add(f"**{scan['verdict']}**")
    add("")
    if scan["verdict"] == "UNDERPOWERED":
        add(
            f"Needs n >= {MIN_ADMISSIBLE_N} admissible dense station-days to reach "
            "a decisive verdict either way. Re-run as capture and the ASOS cache "
            "accumulate."
        )
    elif scan["verdict"] == "FAMILY_DEAD":
        add(
            "Zero qualifying offers across an adequate dense-station sample: the "
            "same mechanism that killed the prior three families (L-9) kills this "
            "one too."
        )
    else:
        add(
            "The Wilson 95% lower bound on the qualifying-offer rate clears 10%: "
            "candidate #2 is not refuted by the offer-gate mechanism and warrants "
            "building execution logic."
        )
    add("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quote-tape", default=DEFAULT_QUOTE_TAPE_PATH.as_posix())
    parser.add_argument("--asos-cache", default=DEFAULT_ASOS_CACHE_DIR.as_posix())
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH.as_posix())
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    tape_root = Path(args.quote_tape)
    asos_cache_dir = Path(args.asos_cache)
    output_path = Path(args.output)

    if not tape_root.exists():
        raise FileNotFoundError(f"quote tape not found: {tape_root}")

    scan = build_scan(tape_root=tape_root, asos_cache_dir=asos_cache_dir)
    report = render_report(scan)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"wrote {output_path}")
    # One summary line for `journalctl -u breezy-offer-gate-daily.service`,
    # so the daily verdict is visible without opening the snapshot -- the
    # same operational role K1's driver-script log line plays, without
    # requiring a second file.
    print(
        f"[offer-gate] n={scan['n']} k={scan['k']} verdict={scan['verdict']} "
        f"wilson_lower={scan['wilson_lower']:.4f} wilson_upper={scan['wilson_upper']:.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
