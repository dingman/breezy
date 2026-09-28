"""AUD-02 A0: unattended, unauthenticated fee-drift evidence pull.

See ``docs/plans/backlog/AUDIT_2026-09-21/AUD-02-COMPLETION-PLAN-2026-09-25.md``
Section 2 "A0" and the Rev 2.1 addendum (items 2 and 4) for the plan this
implements, and ``docs/evidence/venue/polymarket_us/FEE_DRIFT_EVIDENCE_2026-09-25.md``
for the pre-registered closing rule this script's output feeds.

**Scope, deliberately narrow.** This script performs unauthenticated public
GETs only (``PolymarketUSHttpClient.get_public``, the exact tested dispatch
path :func:`breezy.strategy.current_rung_hold.fee_drift_probe.fetch_wire_fee_coefficient`
already calls). It never signs a request, never touches order submission, and
never imports anything under ``breezy.adapters.polymarket_us.exec`` --
verified by :func:`tests.unit.test_execution_egress_firewall_guard.find_execution_egress_modules`,
which this module's own test asserts stays silent about it.

**Runtime-fix redesign (2026-09-25, first live run TIMED OUT).** The original
design GETed every listed weather slug individually. Measured against the
real, unauthenticated, public gateway the same day: the ``categories=climate``
list carries **4353** markets total since inception (paged to eof at
``limit=500``, 9 pages) but only **58** are ``active=true&closed=false&
archived=false`` (48 of which parse as a weather slug) -- and, decisively,
**every single listed market object already carries its own
``feeCoefficient``** (0 missing across all 4353). A per-slug GET for each was
therefore both unnecessary (the field is already on the list response) and
the actual cause of the timeout: paced at ``QUOTA_KEY_INSTRUMENTS``'s 6/min,
4343 weather slugs would take roughly 12 hours, far past
``TimeoutStartSec=900``. The fixed design (option (a), coordinator's
preference order) reads ``feeCoefficient`` (and the candidate maker field)
directly off each list entry; a per-slug GET (option (b)) is now only a
BOUNDED fallback (:data:`MAX_FALLBACK_PER_SLUG_CALLS`) for the rare listed
market whose entry itself lacks a parseable fee -- never the whole universe.

**Denominator change, documented (coordinator's explicit ask).** "The day's
listed weather slugs" now means the CURRENTLY tradable universe --
``active=true, closed=false, archived=false`` -- not the full historical
archive of every weather market ever listed. This matches
``PolymarketUSMarketDiscoveryConfig``'s own defaults (``config.py:194-196``),
so A0's denominator stays consistent with WP-D1's comparison against the
live node's own discovered-slug snapshot, which uses the same filters. The
95% completeness threshold is unchanged and, against this denominator, is
still meaningful: 48 real weather markets, not thousands of already-settled
historical ones whose fee is a frozen fact, not a daily observation.
:data:`FEE_DRIFT_EVIDENCE_2026-09-25.md` records this change.

**Pacing -- no new transport, no manual sleep.** Every ``get_public`` call
below is budgeted under a ``quota_key`` that ``transport.py`` already enforces
NATIVELY, client-side, via the Nautilus rate limiter
(``nautilus_pyo3.Quota.rate_per_minute``) built into
``build_keyed_quotas``/``build_shared_http_client`` -- the SAME budgets
``PolymarketUSInstrumentProvider._load_slugs``/``_discover_markets`` already
pace their own reads under (``provider.py:639-641,684-687``). This script
reuses those two keys rather than inventing pacing of its own:

* ``MARKET_LIST_QUOTA_KEY = QUOTA_KEY_DISCOVERY`` --
  ``DEFAULT_DISCOVERY_REQUESTS_PER_MINUTE = 6`` requests/minute
  (``transport.py:125``) for each ``GET /v1/markets`` list page.
* ``PER_SLUG_QUOTA_KEY = QUOTA_KEY_INSTRUMENTS`` --
  ``DEFAULT_INSTRUMENT_REQUESTS_PER_MINUTE = 6`` requests/minute
  (``transport.py:126``), now used ONLY for the bounded fallback
  (:data:`MAX_FALLBACK_PER_SLUG_CALLS` calls, worst case).

**Worst-case runtime bound, tested.** :func:`worst_case_runtime_secs` computes
the documented upper bound from :data:`MAX_LIST_PAGES` and
:data:`MAX_FALLBACK_PER_SLUG_CALLS` against a token-bucket quota
(burst == requests/minute, then paced at ``60 / requests_per_minute``
seconds/request -- the exact shape ``build_keyed_quotas`` constructs). At the
current constants this is 580s; ``tests/unit/test_fee_drift_evidence_pull.py``
asserts the shipped unit's ``TimeoutStartSec`` exceeds this bound plus a
margin, so a future constant change that would blow the timeout fails CI
instead of failing in production again.

``scripts/venue/polymarket_us_shape_capture.py`` itself performs no I/O (it is
a pure value-free describe/write module), so there is no pacing constant to
cite FROM it; the pacing this script actually inherits lives one layer below,
in the shared transport every ``get_public`` caller already pays into.

**Maker/taker separation (B-7,** ``POST_FORECAST_PHASE_2026-09-20.md:336-342``
**).** "Record the maker field independently" is unsatisfiable from the
parsed ``Instrument``: ``parsing.py`` writes theta onto *both* flat fields, so
``instrument.maker_fee == instrument.taker_fee`` by construction. This script
never reads a parsed ``Instrument`` at all -- it reads the two fields directly
off the raw wire JSON, under their own wire names, and records ``None`` with
an explicit reason when a name is simply absent from this endpoint's payload.
Nothing here falls back to :data:`breezy.adapters.polymarket_us.fees.MAKER_FEE_COEFFICIENT`
(the DOCUMENTED constant) to fill an observed gap -- an unobserved maker field
is recorded as unobserved, never fabricated.

**Point-in-time guard (AUD-11).** ``breezy.runtime.point_in_time_guard`` polices
records fed into a BACKTEST/REPLAY/STUDY decision stream that could look ahead
of a decision instant. This script computes no decision and replays nothing:
it is a live, wall-clock capture of the venue's CURRENT wire state, written
once per real-time run. There is no ``decision_ts_init_ns`` for a live GET to
look ahead of, so the guard does not apply here -- N/A, not silently skipped.
A future C2 readout that treats this evidence as a backtest INPUT is exactly
the case the guard covers, and must call it there, not here.

**Retention.** ``data/evidence/fee_drift/`` is outside git (``.gitignore``).
Every write under it is followed by a ``manifest.sha256`` covering that day's
raw files, so a later retention pass can prove nothing was silently altered
without needing git history over a directory git never tracked.

**Same-day re-run discipline (code review fix).** A day directory's evidence
artifact set (``slugs.json``/``summary.json``, OR ``incomplete.json``) is
always fully REPLACED by a run, never merged into: every file is written to a
temp path and renamed into place, any of the three names NOT part of this
run's write-set is deleted, and ``manifest.sha256.json`` -- covering exactly
the files left on disk -- is written last, after every data file already has
its final name. This is what keeps the manifest a byte-exact description of
the directory at every point in time, including mid-crash: a reader never
sees a manifest naming a file that is not yet (or no longer) there.

**Downgrade policy: a protected-window run never erases an existing REAL
pull record for the same UTC date.** If ``slugs.json`` and ``summary.json``
already exist for a date (a real attempt, whatever its own ``complete``
value), a run that starts inside the protected window records its own
skipped attempt in a separate sidecar (``skipped_downgrade.json``, never
covered by the manifest, never counted as an evidence artifact) and leaves
the existing three files and the manifest untouched. The reverse direction
(a real pull following an earlier protected-window ``incomplete.json``) is an
upgrade, not a downgrade, and proceeds normally -- ``incomplete.json`` is
removed and replaced by the real record. Rationale: an evidence pack is used
to answer "what did we actually observe", and a scheduler artifact (a
catch-up run landing inside the protected window, e.g. after
``Persistent=true`` fires late) carries strictly less information than an
already-recorded real attempt; silently downgrading the record to
"incomplete" would make the pack LIE about what is actually known for that
date. Recording the later attempt separately, rather than dropping it
silently, keeps the operator able to see that a downgrade was avoided.

**Fail loudly (2026-09-25 production incident, fixed same day).** The first
real 11:10Z run listed ZERO markets and still printed
``complete=False ... reason=None`` and exited **0** -- a silent failure that
never triggered ``OnFailure=``. Root cause, reproduced live (read-only,
unauthenticated, against the real gateway): the list query's own three
filters (:data:`LIST_QUERY_ACTIVE`/:data:`LIST_QUERY_CLOSED`/
:data:`LIST_QUERY_ARCHIVED`) matched zero markets when sent WITHOUT ordering,
even though ``active=true&categories=climate`` alone, queried at the same
moment, returned 100 -- reproducible, not a one-off. ``PolymarketUSMarket
DiscoveryConfig``'s own defaults (``config.py:191-192``) always pair those
same three filters with :data:`LIST_QUERY_ORDER_BY`/
:data:`LIST_QUERY_ORDER_DIRECTION`, and
``PolymarketUSInstrumentProvider._discover_markets`` -- the query shape the
live trading node already discovers and trades markets with -- always sends
them together. This script now does too. Independently of that fix, `main`
never again exits 0 on a silent incomplete day: `run_once` names a
non-``None`` reason on every non-complete outcome (empty listing, or
below-threshold parse rate), and `main` treats every incomplete day as a
failure UNLESS the reason is the one documented, evidence-justified
legitimate case -- the protected window (:data:`_PROTECTED_WINDOW_REASON`).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from datetime import time as dt_time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol

from breezy.adapters.polymarket_us.provider import MARKET_LIST_PATH
from breezy.adapters.polymarket_us.symbology import parse_weather_slug
from breezy.adapters.polymarket_us.transport import (
    DEFAULT_DISCOVERY_REQUESTS_PER_MINUTE,
    DEFAULT_INSTRUMENT_REQUESTS_PER_MINUTE,
    QUOTA_KEY_DISCOVERY,
    QUOTA_KEY_INSTRUMENTS,
)
from breezy.strategy.current_rung_hold.fee_drift_probe import (
    FEE_COEFFICIENT_WIRE_KEY,
    MARKET_BY_SLUG_PATH,
)

logger = logging.getLogger(__name__)

__all__ = [
    "COMPLETE_DAY_THRESHOLD",
    "LIST_QUERY_ACTIVE",
    "LIST_QUERY_ARCHIVED",
    "LIST_QUERY_CLOSED",
    "LIST_QUERY_ORDER_BY",
    "LIST_QUERY_ORDER_DIRECTION",
    "MAKER_FEE_WIRE_KEY",
    "MARKET_LIST_QUOTA_KEY",
    "MAX_FALLBACK_PER_SLUG_CALLS",
    "MAX_LIST_PAGES",
    "PER_SLUG_QUOTA_KEY",
    "PROTECTED_WINDOW_END_UTC",
    "PROTECTED_WINDOW_START_UTC",
    "TAKER_FEE_WIRE_KEY",
    "EvidencePullResult",
    "PublicReadClient",
    "SlugPullResult",
    "build_default_client",
    "is_protected_window",
    "list_weather_markets",
    "main",
    "pull_slug",
    "run_once",
    "worst_case_runtime_secs",
]

#: The venue's own wire field for taker theta -- read verbatim, never renamed
#: (same constant `fee_drift_probe.py` pins at `feeCoefficient`).
TAKER_FEE_WIRE_KEY: str = FEE_COEFFICIENT_WIRE_KEY

#: Candidate wire field for a maker-side coefficient on the SAME market
#: payload, per the shape-capture allowlist
#: (`polymarket_us_shape_capture.py`'s `SHAPE_ALLOWED_KEYS`). Read verbatim;
#: recorded as absent (never fabricated) when this endpoint's payload simply
#: does not carry it -- see the module docstring's B-7 note.
MAKER_FEE_WIRE_KEY: str = "makerCommissionsBasisPoints"

#: Native, client-side rate limiting -- no manual sleep. See module docstring.
PER_SLUG_QUOTA_KEY: str = QUOTA_KEY_INSTRUMENTS
MARKET_LIST_QUOTA_KEY: str = QUOTA_KEY_DISCOVERY

#: Same pagination-termination discipline as `provider.py`'s
#: `MAX_DISCOVERY_PAGES`: a response that never returns a short page is
#: malformed or hostile, and this script refuses to page forever.
MAX_LIST_PAGES: int = 50

#: Page size for the market-list pull. Matches
#: `PolymarketUSMarketDiscoveryConfig.limit`'s own default (`config.py:190`).
DEFAULT_LIST_PAGE_LIMIT: int = 100

#: The venue's own weather/climate category, server-side filter
#: (`PolymarketUSMarketDiscoveryConfig.categories` default, `config.py:193`).
WEATHER_CATEGORY: str = "climate"

#: Server-side filters matching `PolymarketUSMarketDiscoveryConfig`'s own
#: defaults (`config.py:194-196`): only the CURRENTLY tradable universe.
#: Measured 2026-09-25 against the real, unauthenticated gateway: 4353
#: markets total under `categories=climate` since inception vs. 58 with
#: these three filters applied (see module docstring, "Denominator change").
LIST_QUERY_ACTIVE: bool = True
LIST_QUERY_CLOSED: bool = False
LIST_QUERY_ARCHIVED: bool = False

#: **Empty-listing fix (2026-09-25 production incident).** The 11:10Z live
#: run listed ZERO markets with `LIST_QUERY_ACTIVE`/`_CLOSED`/`_ARCHIVED`
#: alone (no ordering). Re-measured live, read-only, unauthenticated,
#: against the real gateway the same day: `active=true&categories=climate`
#: ALONE returned 100 markets at that moment, but adding `closed=false` and
#: `archived=false` with NO `orderBy`/`orderDirection` zeroed the result set
#: -- reproducibly, not a one-off. `PolymarketUSMarketDiscoveryConfig`'s own
#: defaults (`config.py:191-192`) pair those same three filters with
#: `orderBy=("endDate",)`/`orderDirection="asc"`, and
#: `PolymarketUSInstrumentProvider._discover_markets` -- the query shape the
#: live trading node already discovers and trades markets with -- always
#: sends them together. This script must send the SAME proven shape, not a
#: subset of it.
LIST_QUERY_ORDER_BY: tuple[str, ...] = ("endDate",)
LIST_QUERY_ORDER_DIRECTION: str = "asc"

#: Bound on option-(b) fallback per-slug GETs (a listed market whose OWN
#: entry lacks a parseable fee -- never observed as of 2026-09-25, across
#: 4353 markets, but a documented, tested safety net rather than an
#: assumption). Combined with :data:`MAX_LIST_PAGES` this bounds
#: :func:`worst_case_runtime_secs` well under the shipped unit's
#: `TimeoutStartSec` -- see the timeout-bound test.
MAX_FALLBACK_PER_SLUG_CALLS: int = 20

#: [16:35Z, 01:15Z) -- the supervisor's LAUNCH/mid-day-watch/self-check span
#: (`deploy/systemd/breezy-exit-window-study.timer`'s own comment; Rev 2.1
#: item 2). A run started inside this window pulls nothing.
PROTECTED_WINDOW_START_UTC: dt_time = dt_time(16, 35)
PROTECTED_WINDOW_END_UTC: dt_time = dt_time(1, 15)

#: A day counts as COMPLETE only if at least this fraction of that day's
#: venue-listed weather slugs returned a parseable `feeCoefficient`
#: (plan Section 2 "A0", "Complete day").
COMPLETE_DAY_THRESHOLD: Decimal = Decimal("0.95")

_OUTPUT_ROOT_DEFAULT: Path = Path("data/evidence/fee_drift")

_PROTECTED_WINDOW_REASON: str = (
    "protected window [16:35Z, 01:15Z): no pull attempted; day marked INCOMPLETE"
)


class PublicReadClient(Protocol):
    """The one method this script calls -- structurally identical to
    `fee_drift_probe.py`'s own `_PublicReadClient`, restated here because that
    one is module-private and not meant for cross-module import.
    """

    async def get_public(
        self, path: str, *, query: Mapping[str, Any] | None = None, quota_key: str
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class SlugPullResult:
    """One slug's raw-wire pull outcome. `raw` is the untouched wire payload."""

    slug: str
    ok: bool
    taker_fee_coefficient: str | None
    maker_fee_wire: str | None
    reason: str | None
    raw: Mapping[str, Any] | None


@dataclass(frozen=True, slots=True)
class EvidencePullResult:
    """One day's full pull outcome, everything needed to write the artefacts."""

    date: str
    complete: bool
    reason: str | None
    markets_listed: int
    slugs: tuple[SlugPullResult, ...]
    output_dir: Path | None = None
    manifest: Mapping[str, str] = field(default_factory=dict)

    @property
    def ok_count(self) -> int:
        return sum(1 for s in self.slugs if s.ok)

    @property
    def taker_values_observed(self) -> frozenset[str]:
        return frozenset(s.taker_fee_coefficient for s in self.slugs if s.taker_fee_coefficient)

    @property
    def maker_values_observed(self) -> frozenset[str]:
        return frozenset(s.maker_fee_wire for s in self.slugs if s.maker_fee_wire)


def is_protected_window(now: datetime) -> bool:
    """True inside ``[16:35Z, 01:15Z)`` -- wraps midnight."""
    t = now.astimezone(UTC).time()
    return t >= PROTECTED_WINDOW_START_UTC or t < PROTECTED_WINDOW_END_UTC


async def list_weather_markets(
    client: PublicReadClient,
    *,
    limit: int = DEFAULT_LIST_PAGE_LIMIT,
    max_pages: int = MAX_LIST_PAGES,
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """Page ``MARKET_LIST_PATH`` to eof, scoped to the CURRENTLY tradable
    universe (:data:`LIST_QUERY_ACTIVE`/:data:`LIST_QUERY_CLOSED`/
    :data:`LIST_QUERY_ARCHIVED` -- see module docstring "Denominator change").

    Returns ``(raw_pages, weather_markets)``: every raw page payload (the
    day's denominator, stored verbatim) and the subset of listed markets that
    parse as a weather slug (client-side confirmation of the server-side
    ``categories=[climate]`` filter, mirroring `provider.py`'s own
    belt-and-braces double-check). Each returned market dict carries its own
    ``feeCoefficient`` -- the primary source `run_once` reads fees from,
    never a per-slug GET.
    """
    raw_pages: list[Mapping[str, Any]] = []
    weather_markets: list[Mapping[str, Any]] = []
    offset = 0
    for page in range(max_pages + 1):
        if page == max_pages:
            raise RuntimeError(
                f"{MARKET_LIST_PATH} exceeded the {max_pages}-page cap without "
                f"returning a short page (offset {offset}, limit {limit}); "
                "refusing to page forever"
            )
        payload = await client.get_public(
            MARKET_LIST_PATH,
            query={
                "limit": limit,
                "offset": offset,
                "orderBy": LIST_QUERY_ORDER_BY,
                "orderDirection": LIST_QUERY_ORDER_DIRECTION,
                "categories": [WEATHER_CATEGORY],
                "active": LIST_QUERY_ACTIVE,
                "closed": LIST_QUERY_CLOSED,
                "archived": LIST_QUERY_ARCHIVED,
            },
            quota_key=MARKET_LIST_QUOTA_KEY,
        )
        raw_pages.append(payload)
        markets_raw = payload.get("markets")
        page_markets = list(markets_raw) if isinstance(markets_raw, list) else []
        for market in page_markets:
            if not isinstance(market, Mapping):
                continue
            slug = market.get("slug")
            if isinstance(slug, str) and parse_weather_slug(slug) is not None:
                weather_markets.append(market)
        if len(page_markets) < limit:
            break
        offset += limit
    return raw_pages, weather_markets


def _parse_decimal(raw: object) -> str | None:
    try:
        return str(Decimal(str(raw)))
    except (ArithmeticError, InvalidOperation, ValueError, TypeError):
        return None


def _slug_result_from_market(slug: str, market: Mapping[str, Any]) -> SlugPullResult:
    """Build a `SlugPullResult` straight from a market's own wire fields.

    Shared by the PRIMARY path (a listed market's own entry, from
    `list_weather_markets`) and the bounded FALLBACK path (`pull_slug`'s
    decoded per-slug GET) -- one taker/maker extraction rule, never two.
    """
    taker_raw = market.get(TAKER_FEE_WIRE_KEY)
    reason: str | None = None
    taker: str | None = None
    if taker_raw is None:
        reason = f"missing {TAKER_FEE_WIRE_KEY!r}"
    else:
        taker = _parse_decimal(taker_raw)
        if taker is None:
            reason = f"unparseable {TAKER_FEE_WIRE_KEY!r}={taker_raw!r}"

    maker_raw = market.get(MAKER_FEE_WIRE_KEY)
    maker = None if maker_raw is None else (_parse_decimal(maker_raw) or str(maker_raw))

    return SlugPullResult(
        slug=slug,
        ok=reason is None,
        taker_fee_coefficient=taker,
        maker_fee_wire=maker,
        reason=reason,
        raw=market,
    )


async def pull_slug(client: PublicReadClient, slug: str) -> SlugPullResult:
    """FALLBACK per-slug raw-wire GET (option (b)) -- used ONLY for a listed
    market whose own list entry lacked a parseable fee, bounded by
    :data:`MAX_FALLBACK_PER_SLUG_CALLS` in `run_once`. Never raises -- a
    failure is recorded, not dropped.
    """
    try:
        payload = await client.get_public(
            MARKET_BY_SLUG_PATH.format(slug=slug),
            quota_key=PER_SLUG_QUOTA_KEY,
        )
    except Exception as exc:  # noqa: BLE001 - any read failure is a recorded reason, not a crash
        return SlugPullResult(
            slug=slug,
            ok=False,
            taker_fee_coefficient=None,
            maker_fee_wire=None,
            reason=f"{type(exc).__name__}: {exc}",
            raw=None,
        )

    market = payload.get("market") if isinstance(payload.get("market"), Mapping) else payload
    if not isinstance(market, Mapping):
        return SlugPullResult(
            slug=slug,
            ok=False,
            taker_fee_coefficient=None,
            maker_fee_wire=None,
            reason="response carried no market object",
            raw=None,
        )

    return _slug_result_from_market(slug, market)


def _worst_case_paced_seconds(request_count: int, *, requests_per_minute: int) -> float:
    """Upper-bound wall-clock seconds for `request_count` requests under a
    token-bucket quota of `requests_per_minute` with burst ==
    `requests_per_minute` (the exact shape `build_keyed_quotas` constructs):
    the first `requests_per_minute` requests are free (burst), then each
    further request is paced at ``60 / requests_per_minute`` seconds.
    """
    if request_count <= requests_per_minute:
        return 0.0
    return (request_count - requests_per_minute) * (60.0 / requests_per_minute)


def worst_case_runtime_secs(
    *,
    max_list_pages: int = MAX_LIST_PAGES,
    max_fallback_calls: int = MAX_FALLBACK_PER_SLUG_CALLS,
    list_requests_per_minute: int = DEFAULT_DISCOVERY_REQUESTS_PER_MINUTE,
    slug_requests_per_minute: int = DEFAULT_INSTRUMENT_REQUESTS_PER_MINUTE,
) -> float:
    """The documented worst-case wall-clock bound this script's design
    guarantees: the list pagination cap plus the bounded per-slug fallback,
    each paced under its own native quota. A deploy test asserts the shipped
    unit's ``TimeoutStartSec`` exceeds this, plus a margin.
    """
    return _worst_case_paced_seconds(
        max_list_pages, requests_per_minute=list_requests_per_minute
    ) + _worst_case_paced_seconds(
        max_fallback_calls, requests_per_minute=slug_requests_per_minute
    )


def _is_complete(listed_count: int, results: Sequence[SlugPullResult]) -> bool:
    if listed_count == 0:
        return False
    ok = sum(1 for r in results if r.ok)
    return Decimal(ok) / Decimal(listed_count) >= COMPLETE_DAY_THRESHOLD


def _sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


#: The COMPLETE set of names a day directory's evidence record may hold,
#: exclusive of `MANIFEST_FILENAME` itself and the downgrade sidecar. Exactly
#: one of {"slugs.json", "summary.json"} (together) OR {"incomplete.json"} is
#: ever the FULL evidence set for a given day -- `_replace_day_artifacts`
#: enforces that no member outside this run's write-set survives it.
_DAY_ARTIFACT_NAMES: frozenset[str] = frozenset(
    {"slugs.json", "summary.json", "incomplete.json"}
)

MANIFEST_FILENAME: str = "manifest.sha256.json"

#: Records a protected-window run that was REFUSED rather than downgrading an
#: existing real pull record for the same date (see module docstring "Downgrade
#: policy"). Deliberately outside `_DAY_ARTIFACT_NAMES` and never covered by
#: the manifest: it is an audit note about a skipped attempt, not evidence.
_SKIPPED_DOWNGRADE_SIDECAR: str = "skipped_downgrade.json"

_DOWNGRADE_REFUSED_REASON_PREFIX: str = (
    "downgrade refused: a real pull record already exists for "
)


def _atomic_write_json(path: Path, payload: object) -> str:
    """Write ``path`` atomically (temp file, then rename) and return its sha256.

    The temp file lives in the SAME directory as ``path`` so the rename is
    guaranteed to be on one filesystem (an atomic `os.rename`, never a
    cross-filesystem copy). A reader can therefore never observe a partially
    written file at ``path``'s final name.
    """
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)
    return _sha256_of(text)


def _has_real_pull_record(day_dir: Path) -> bool:
    """True when ``day_dir`` already holds a REAL pull's record (both
    ``slugs.json`` and ``summary.json``), as opposed to only a
    protected-window ``incomplete.json`` or nothing at all.
    """
    return (day_dir / "slugs.json").exists() and (day_dir / "summary.json").exists()


def _replace_day_artifacts(
    day_dir: Path, files: Mapping[str, object]
) -> Mapping[str, str]:
    """Write EXACTLY ``files`` as the day's evidence record, atomically, and
    delete any OTHER member of `_DAY_ARTIFACT_NAMES` left over from a prior
    run for the same day -- a run's write-set fully REPLACES the day
    directory's evidence set, never merges into it. The manifest is written
    LAST, after every data file already has its final on-disk name, so the
    manifest is always an exact description of what is on disk, even if this
    process is killed mid-run (the worst case is a manifest one run behind,
    never a manifest naming a file that does not exist).
    """
    day_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, str] = {}
    for name, payload in files.items():
        manifest[name] = _atomic_write_json(day_dir / name, payload)
    for stale_name in _DAY_ARTIFACT_NAMES - set(files):
        stale_path = day_dir / stale_name
        if stale_path.exists():
            stale_path.unlink()
    _atomic_write_json(day_dir / MANIFEST_FILENAME, manifest)
    return manifest


def _refuse_downgrade(result: EvidencePullResult, day_dir: Path) -> EvidencePullResult:
    """Record a refused protected-window downgrade attempt and return the
    EXISTING on-disk record's own facts -- never this run's protected-window
    facts, and never touching `slugs.json`/`summary.json`/the manifest.
    """
    day_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(
        day_dir / _SKIPPED_DOWNGRADE_SIDECAR,
        {"date": result.date, "attempted_reason": result.reason},
    )
    logger.warning(
        "fee_drift_evidence_pull: refusing to downgrade date=%s -- a real pull "
        "record already exists; recorded the skipped attempt in %s",
        result.date,
        _SKIPPED_DOWNGRADE_SIDECAR,
    )
    existing_summary = json.loads((day_dir / "summary.json").read_text(encoding="utf-8"))
    existing_manifest = json.loads((day_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    return EvidencePullResult(
        date=result.date,
        complete=bool(existing_summary["complete"]),
        reason=f"{_DOWNGRADE_REFUSED_REASON_PREFIX}{result.date}",
        markets_listed=int(existing_summary["markets_listed"]),
        slugs=(),
        output_dir=day_dir,
        manifest=existing_manifest,
    )


def _write_artifacts(result: EvidencePullResult, day_dir: Path) -> EvidencePullResult:
    is_protected_skip = not result.complete and result.reason == _PROTECTED_WINDOW_REASON

    if is_protected_skip and _has_real_pull_record(day_dir):
        return _refuse_downgrade(result, day_dir)

    if is_protected_skip:
        manifest = _replace_day_artifacts(
            day_dir,
            {"incomplete.json": {"date": result.date, "reason": result.reason}},
        )
        return EvidencePullResult(
            date=result.date,
            complete=False,
            reason=result.reason,
            markets_listed=0,
            slugs=(),
            output_dir=day_dir,
            manifest=manifest,
        )

    manifest = _replace_day_artifacts(
        day_dir,
        {
            "slugs.json": [
                {
                    "slug": s.slug,
                    "ok": s.ok,
                    "taker_fee_coefficient": s.taker_fee_coefficient,
                    "maker_fee_wire": s.maker_fee_wire,
                    "reason": s.reason,
                    "raw": s.raw,
                }
                for s in result.slugs
            ],
            "summary.json": {
                "date": result.date,
                "complete": result.complete,
                "markets_listed": result.markets_listed,
                "ok_count": result.ok_count,
                "failed_count": len(result.slugs) - result.ok_count,
                "taker_values_observed": sorted(result.taker_values_observed),
                "maker_values_observed": sorted(result.maker_values_observed),
                "failed_slugs": [
                    {"slug": s.slug, "reason": s.reason} for s in result.slugs if not s.ok
                ],
            },
        },
    )
    return EvidencePullResult(
        date=result.date,
        complete=result.complete,
        reason=result.reason,
        markets_listed=result.markets_listed,
        slugs=result.slugs,
        output_dir=day_dir,
        manifest=manifest,
    )


async def run_once(
    *,
    client: PublicReadClient,
    output_root: Path = _OUTPUT_ROOT_DEFAULT,
    now: datetime | None = None,
    list_limit: int = DEFAULT_LIST_PAGE_LIMIT,
) -> EvidencePullResult:
    """One day's evidence pull.

    PRIMARY path: fee fields come straight off each listed market's own list
    entry (no per-slug GET). FALLBACK path: any listed market whose entry
    lacked a parseable fee gets a per-slug GET, bounded by
    :data:`MAX_FALLBACK_PER_SLUG_CALLS` -- an overflow beyond that cap is
    recorded with a reason, never attempted, so the worst case stays bounded
    (:func:`worst_case_runtime_secs`). Never raises on a venue-side failure of
    an individual slug; only a malformed/hostile list response can raise
    (`list_weather_markets`'s page cap).
    """
    moment = now if now is not None else datetime.now(tz=UTC)
    date = moment.astimezone(UTC).date().isoformat()
    day_dir = output_root / date

    if is_protected_window(moment):
        result = EvidencePullResult(
            date=date,
            complete=False,
            reason=_PROTECTED_WINDOW_REASON,
            markets_listed=0,
            slugs=(),
        )
        return _write_artifacts(result, day_dir)

    _raw_pages, weather_markets = await list_weather_markets(client, limit=list_limit)

    primary_results: list[SlugPullResult] = []
    fallback_slugs: list[str] = []
    for market in weather_markets:
        slug = market.get("slug")
        if not isinstance(slug, str):
            continue
        result = _slug_result_from_market(slug, market)
        if result.ok:
            primary_results.append(result)
        else:
            fallback_slugs.append(slug)

    fallback_slugs.sort()  # deterministic which slugs get the bounded fallback
    attempted = fallback_slugs[:MAX_FALLBACK_PER_SLUG_CALLS]
    overflow = fallback_slugs[MAX_FALLBACK_PER_SLUG_CALLS:]
    fallback_results = [await pull_slug(client, slug) for slug in attempted]
    fallback_results.extend(
        SlugPullResult(
            slug=slug,
            ok=False,
            taker_fee_coefficient=None,
            maker_fee_wire=None,
            reason=(
                f"fallback per-slug GET cap ({MAX_FALLBACK_PER_SLUG_CALLS}) "
                "exceeded; not attempted"
            ),
            raw=None,
        )
        for slug in overflow
    )

    results = tuple(primary_results + fallback_results)
    listed_count = len(primary_results) + len(fallback_slugs)
    complete = _is_complete(listed_count, results)
    reason = None if complete else _incomplete_reason(listed_count=listed_count, results=results)
    result = EvidencePullResult(
        date=date,
        complete=complete,
        reason=reason,
        markets_listed=listed_count,
        slugs=results,
    )
    return _write_artifacts(result, day_dir)


def _incomplete_reason(*, listed_count: int, results: Sequence[SlugPullResult]) -> str:
    """Name WHY a day is incomplete -- never leave ``reason=None`` on a real
    (non-protected-window) run. A silent ``complete=False, reason=None`` is
    exactly the 2026-09-25 production incident this function closes: a run
    that lists zero markets exits looking indistinguishable from success.
    """
    if listed_count == 0:
        return (
            "empty listing: the "
            f"{MARKET_LIST_PATH} query (categories={[WEATHER_CATEGORY]!r}, "
            f"active={LIST_QUERY_ACTIVE}, closed={LIST_QUERY_CLOSED}, "
            f"archived={LIST_QUERY_ARCHIVED}) matched zero weather markets"
        )
    ok = sum(1 for r in results if r.ok)
    return (
        f"only {ok}/{listed_count} listed slugs returned a parseable "
        f"{TAKER_FEE_WIRE_KEY!r} (< {COMPLETE_DAY_THRESHOLD:.0%} threshold)"
    )


def build_default_client(*, user_agent: str) -> PublicReadClient:
    """The production client: the shipped, natively-rate-limited,
    unauthenticated transport. Never imported at module load, so importing
    this module (as the test suite does) touches no network machinery.

    ``signer=None``: ``PolymarketUSHttpClient.get_public`` dispatches with
    ``authenticated=False`` unconditionally (``http.py:137-152``), and
    ``_dispatch``'s ``if authenticated:`` guard (``http.py:200-202``) is the
    ONLY place ``self._signer`` is read -- so it is provably unreachable here,
    not merely unused. This script holds no credential of any kind.
    """
    from nautilus_trader.common.component import Logger

    from breezy.adapters.polymarket_us.config import (
        POLYMARKET_US_API_BASE_URL,
        POLYMARKET_US_GATEWAY_BASE_URL,
    )
    from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient
    from breezy.adapters.polymarket_us.transport import (
        NautilusHttpTransport,
        build_default_quota,
        build_keyed_quotas,
        build_shared_http_client,
    )

    native_client = build_shared_http_client(
        timeout_secs=10,
        default_quota=build_default_quota(),
        keyed_quotas=build_keyed_quotas(),
        default_headers={"User-Agent": user_agent},
    )
    transport = NautilusHttpTransport(client=native_client)
    return PolymarketUSHttpClient(
        transport=transport,
        signer=None,  # type: ignore[arg-type]  # see docstring: unreachable for get_public
        api_base_url=POLYMARKET_US_API_BASE_URL,
        gateway_base_url=POLYMARKET_US_GATEWAY_BASE_URL,
        logger=Logger("fee-drift-evidence-pull"),
    )


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=_OUTPUT_ROOT_DEFAULT,
        help="Directory evidence days are written under (default: %(default)s)",
    )
    parser.add_argument(
        "--user-agent",
        required=True,
        help="A specific, contactable User-Agent -- never a generic placeholder",
    )
    args = parser.parse_args(argv)
    # The systemd unit substitutes this value from ${BREEZY_USER_AGENT} via
    # EnvironmentFile= (deploy/systemd/breezy-fee-evidence-pull.service): an
    # unset variable reaches argparse as an EMPTY string, not a missing
    # argument, so `required=True` alone never catches it. Refuse loudly
    # rather than sending the venue a blank or whitespace-only contact
    # header.
    if not args.user_agent.strip():
        parser.error("--user-agent must be a specific, contactable value -- never empty/blank")
    return args


#: The ONLY reasons under which an incomplete/empty day is a legitimate,
#: evidence-justified outcome rather than a failure -- see module docstring
#: "Fail loudly" and the 2026-09-25 production incident this closes. Every
#: other incomplete day (empty listing, below-threshold parse rate, a
#: refused same-day downgrade over a still-incomplete existing record) must
#: make `main` exit non-zero so `OnFailure=` actually fires.
_LOUD_FAILURE_EXEMPT_REASONS: frozenset[str] = frozenset({_PROTECTED_WINDOW_REASON})


def main(argv: Sequence[str] | None = None, *, now: datetime | None = None) -> int:
    args = _parse_args(argv)
    client = build_default_client(user_agent=args.user_agent)
    result = asyncio.run(run_once(client=client, output_root=args.output_root, now=now))
    print(
        f"fee_drift_evidence_pull: date={result.date} complete={result.complete} "
        f"markets_listed={result.markets_listed} ok={result.ok_count} "
        f"reason={result.reason}"
    )
    if not result.complete and result.reason not in _LOUD_FAILURE_EXEMPT_REASONS:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
