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

**Pacing -- no new transport, no manual sleep.** Every ``get_public`` call
below is budgeted under a ``quota_key`` that ``transport.py`` already enforces
NATIVELY, client-side, via the Nautilus rate limiter
(``nautilus_pyo3.Quota.rate_per_minute``) built into
``build_keyed_quotas``/``build_shared_http_client`` -- the SAME budgets
``PolymarketUSInstrumentProvider._load_slugs``/``_discover_markets`` already
pace their own reads under (``provider.py:639-641,684-687``). This script
reuses those two keys rather than inventing pacing of its own:

* ``PER_SLUG_QUOTA_KEY = QUOTA_KEY_INSTRUMENTS`` --
  ``DEFAULT_INSTRUMENT_REQUESTS_PER_MINUTE = 6`` requests/minute
  (``transport.py:126``), i.e. one per-slug ``GET /v1/market/slug/{slug}``
  roughly every 10 seconds.
* ``MARKET_LIST_QUOTA_KEY = QUOTA_KEY_DISCOVERY`` --
  ``DEFAULT_DISCOVERY_REQUESTS_PER_MINUTE = 6`` requests/minute
  (``transport.py:125``) for each ``GET /v1/markets`` list page.

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
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
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
    QUOTA_KEY_DISCOVERY,
    QUOTA_KEY_INSTRUMENTS,
)
from breezy.strategy.current_rung_hold.fee_drift_probe import (
    FEE_COEFFICIENT_WIRE_KEY,
    MARKET_BY_SLUG_PATH,
)

__all__ = [
    "COMPLETE_DAY_THRESHOLD",
    "MAKER_FEE_WIRE_KEY",
    "MARKET_LIST_QUOTA_KEY",
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
    """Page ``MARKET_LIST_PATH`` to eof.

    Returns ``(raw_pages, weather_markets)``: every raw page payload (the
    day's denominator, stored verbatim) and the subset of listed markets that
    parse as a weather slug (client-side confirmation of the server-side
    ``categories=[climate]`` filter, mirroring `provider.py`'s own
    belt-and-braces double-check).
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
                "categories": [WEATHER_CATEGORY],
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


async def pull_slug(client: PublicReadClient, slug: str) -> SlugPullResult:
    """One slug's raw-wire GET. Never raises -- a failure is recorded, not dropped."""
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


def _is_complete(listed_count: int, results: Sequence[SlugPullResult]) -> bool:
    if listed_count == 0:
        return False
    ok = sum(1 for r in results if r.ok)
    return Decimal(ok) / Decimal(listed_count) >= COMPLETE_DAY_THRESHOLD


def _sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: object) -> str:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return _sha256_of(text)


def _write_artifacts(result: EvidencePullResult, day_dir: Path) -> EvidencePullResult:
    day_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, str] = {}

    if not result.complete and result.reason == _PROTECTED_WINDOW_REASON:
        manifest["incomplete.json"] = _write_json(
            day_dir / "incomplete.json",
            {"date": result.date, "reason": result.reason},
        )
        _write_json(day_dir / "manifest.sha256.json", manifest)
        return EvidencePullResult(
            date=result.date,
            complete=False,
            reason=result.reason,
            markets_listed=0,
            slugs=(),
            output_dir=day_dir,
            manifest=manifest,
        )

    manifest["slugs.json"] = _write_json(
        day_dir / "slugs.json",
        [
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
    )
    manifest["summary.json"] = _write_json(
        day_dir / "summary.json",
        {
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
    )
    _write_json(day_dir / "manifest.sha256.json", manifest)
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
    """One day's evidence pull. Never raises on a venue-side failure of an
    individual slug; only a malformed/hostile list response can raise
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
    slugs = [
        m["slug"] for m in weather_markets if isinstance(m.get("slug"), str)
    ]
    results = tuple([await pull_slug(client, slug) for slug in slugs])
    complete = _is_complete(len(slugs), results)
    result = EvidencePullResult(
        date=date,
        complete=complete,
        reason=None,
        markets_listed=len(slugs),
        slugs=results,
    )
    return _write_artifacts(result, day_dir)


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
        signer=None,  # type: ignore[arg-type]  -- see docstring: unreachable for get_public
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
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    client = build_default_client(user_agent=args.user_agent)
    result = asyncio.run(run_once(client=client, output_root=args.output_root))
    print(
        f"fee_drift_evidence_pull: date={result.date} complete={result.complete} "
        f"markets_listed={result.markets_listed} ok={result.ok_count} "
        f"reason={result.reason}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
