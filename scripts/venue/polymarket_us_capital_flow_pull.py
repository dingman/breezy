#!/usr/bin/env python3
"""Unattended, read-only capital-flow puller (FU-13b stage 2).

Authority: ``docs/plans/backlog/NIGHT_2026-09-26/FU-13b_plan_r2_2026-09-26.md``
(File-by-File Plan row for this module; AC8/AC9/AC10; round-2 review binding
amendments 1-2).

**What it does, in one sentence.** One signed ``GET /v1/portfolio/
activities`` pull, paginated to ``eof`` (bounded by :data:`MAX_PAGES`),
parsed by :func:`breezy.adapters.polymarket_us.account_activity.
parse_external_flows`, and written as one immutable snapshot via
:func:`breezy.persistence.external_capital_flows.write_snapshot`.

**Read-only by construction.** The only venue call this module can reach is
:meth:`~breezy.adapters.polymarket_us.http.PolymarketUSHttpClient.
get_authenticated`, bound to :data:`~breezy.adapters.polymarket_us.
account_activity.PORTFOLIO_ACTIVITIES_PATH` -- imported, never restated as a
literal (AC8: that literal appears in exactly one module, ``account_
activity.py``). Nothing here imports the venue SDK, ``exec/``, or either
barred permit function (``assert_live_order_submission_permitted``,
``issue_live_trading_permit``).

**No Nautilus logging init.** This process never calls ``init_logging()``, so
the ``Logger`` the shared production client carries emits nothing (round-2
review binding amendment 3: ``Logger`` no-ops without it). Combined with the
wrapper's own filtering (``deploy/systemd/capital-flow-pull-run.sh``), the
only text this process's stdout ever carries is the one summary line below.

**Output.** Exactly ONE stdout line on success::

    CAPITAL_FLOW_PULL status=<OK|INCOMPLETE> pages=<n> records=<n> path=<path>

and on any exception, exactly one line carrying the exception CLASS only
(never its message, which could carry a redacted-but-still-structured venue
detail)::

    CAPITAL_FLOW_PULL status=ERROR error=<ExceptionClassName>

with a non-zero exit. A 5xx (or any other) venue failure raises before
:func:`~breezy.persistence.external_capital_flows.write_snapshot` is ever
called, so a failed run writes nothing (AC9's immutability property extends
trivially: there is no partial file to reason about).

**Output directory.** Resolved by :func:`breezy.persistence.
external_capital_flows.default_capital_flows_dir` -- the SAME env-or-default
rule ``scripts/analysis/portfolio_roi_report.py`` uses for its own output
root, plus ``/capital_flows``, so the puller and the report always agree on
where the evidence lives without a second copy of the rule.

Usage::

    POLYMARKET_US_USER_AGENT='breezy-capital-flow-pull/1.0 (+mailto:ops@example.com)' \\
    /home/jon/breezy/.venv/bin/python scripts/venue/polymarket_us_capital_flow_pull.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:  # pragma: no cover - operator entrypoint
    sys.path.insert(0, str(REPO_ROOT / "src"))

from nautilus_trader.common.component import LiveClock

from breezy.adapters.polymarket_us.account_activity import (
    PORTFOLIO_ACTIVITIES_PATH,
    parse_external_flows,
)
from breezy.adapters.polymarket_us.factories import (
    config_from_env,
    shared_polymarket_us_http_client,
)
from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient
from breezy.adapters.polymarket_us.transport import QUOTA_KEY_PORTFOLIO
from breezy.persistence.external_capital_flows import (
    STATUS_INCOMPLETE,
    STATUS_OK,
    ExternalCapitalFlow,
    default_capital_flows_dir,
    write_snapshot,
)

__all__ = [
    "MAX_PAGES",
    "PAGE_LIMIT",
    "SUMMARY_PREFIX",
    "build_production_client",
    "main",
    "pull_and_write",
]

#: Bounds the pull -- at PAGE_LIMIT=100 this is 2,000 activities/run, and at
#: the shared portfolio quota's <=12 requests/min this completes well inside
#: TimeoutStartSec=300 (plan "Pagination").
MAX_PAGES: Final[int] = 20
PAGE_LIMIT: Final[int] = 100

SUMMARY_PREFIX: Final[str] = "CAPITAL_FLOW_PULL"


async def _pull_pages(
    client: PolymarketUSHttpClient,
    *,
    max_pages: int = MAX_PAGES,
    page_limit: int = PAGE_LIMIT,
) -> tuple[list[ExternalCapitalFlow], int, str]:
    """Page ``GET /v1/portfolio/activities`` to ``eof``, or to ``max_pages``.

    Returns ``(flows, pages_fetched, status)``. ``status`` is
    :data:`~breezy.persistence.external_capital_flows.STATUS_OK` once the
    venue reports ``eof`` (or stops handing back a cursor), or
    :data:`~breezy.persistence.external_capital_flows.STATUS_INCOMPLETE` if
    ``max_pages`` is exhausted first.
    """
    flows: list[ExternalCapitalFlow] = []
    cursor: str | None = None
    pages = 0
    status = STATUS_INCOMPLETE
    for _ in range(max_pages):
        query: dict[str, Any] = {"limit": page_limit}
        if cursor:
            query["cursor"] = cursor
        page = await client.get_authenticated(
            PORTFOLIO_ACTIVITIES_PATH, query=query, quota_key=QUOTA_KEY_PORTFOLIO
        )
        pages += 1
        flows.extend(parse_external_flows(page))
        cursor = page.get("nextCursor") if isinstance(page.get("nextCursor"), str) else None
        if page.get("eof") or not cursor:
            status = STATUS_OK
            break
    return flows, pages, status


def _covered_from_ns(
    flows: list[ExternalCapitalFlow], *, status: str, pulled_at_ns: int
) -> int:
    """How far back this pull's evidence reaches.

    A full pull to ``eof`` (:data:`STATUS_OK`) has walked the account's
    entire activity history, so it covers every window back to account
    inception -- represented as nanosecond-epoch zero, which trivially
    satisfies ``covered_from_ns <= prev_ts`` for any real window.

    A page-capped pull (:data:`STATUS_INCOMPLETE`) has evidence only back to
    the OLDEST ``createTime`` it actually observed (plan "Pagination: Hitting
    the cap gives INCOMPLETE with covered_from = oldest createTime"). If no
    flow carried a usable timestamp at all, the fail-safe choice is
    ``pulled_at_ns`` itself -- i.e. claim ZERO historical coverage rather than
    guess, so no window can be misclassified as covered.
    """
    if status == STATUS_OK:
        return 0
    timestamps = [flow.create_ts_ns for flow in flows if flow.create_ts_ns is not None]
    return min(timestamps) if timestamps else pulled_at_ns


def build_production_client(env: Mapping[str, str] | None = None) -> PolymarketUSHttpClient:
    """The real, credentialed, read-only client -- the SAME production wiring
    the node itself uses (``config_from_env`` + the shared HTTP client
    factory), reused rather than re-implemented (precedent: ``breezy.
    strategy.current_rung_hold.set_family_halt_cli._default_live_positions_
    reader``). Never exercised by a test: every test in the paired suite
    injects its own fake client via :func:`pull_and_write`'s ``client``
    parameter, through the real :class:`PolymarketUSHttpClient` with a fake
    transport -- never through this factory, which would need real
    credentials on disk.
    """
    config = config_from_env(env)
    return shared_polymarket_us_http_client(config, LiveClock())


def pull_and_write(
    client: PolymarketUSHttpClient,
    directory: Path,
    *,
    pulled_at_ns: int | None = None,
) -> tuple[str, int, int, Path]:
    """Pull, parse, and write one snapshot. Returns ``(status, pages,
    records, path)``. Raises whatever :meth:`PolymarketUSHttpClient.
    get_authenticated` raises on a venue failure -- BEFORE writing anything,
    so a failed pull leaves no partial snapshot on disk.
    """
    flows, pages, status = asyncio.run(_pull_pages(client))
    resolved_pulled_at_ns = pulled_at_ns if pulled_at_ns is not None else time.time_ns()
    covered_from_ns = _covered_from_ns(
        flows, status=status, pulled_at_ns=resolved_pulled_at_ns
    )
    path = write_snapshot(
        directory,
        flows=flows,
        pulled_at_ns=resolved_pulled_at_ns,
        covered_from_ns=covered_from_ns,
        status=status,
    )
    return status, pages, len(flows), path


def main(
    *,
    env: Mapping[str, str] | None = None,
    client: PolymarketUSHttpClient | None = None,
    directory: Path | None = None,
) -> int:
    """Entrypoint. ``client``/``directory`` are test seams only -- production
    (``__main__`` below) always passes neither, so it always runs
    :func:`build_production_client` and :func:`~breezy.persistence.
    external_capital_flows.default_capital_flows_dir`.
    """
    try:
        active_client = client if client is not None else build_production_client(env)
        active_directory = (
            directory if directory is not None else default_capital_flows_dir(env)
        )
        status, pages, records, path = pull_and_write(active_client, active_directory)
    except Exception as exc:  # noqa: BLE001 - deliberate: the class name is the whole message
        print(f"{SUMMARY_PREFIX} status=ERROR error={type(exc).__name__}")
        return 1
    print(f"{SUMMARY_PREFIX} status={status} pages={pages} records={records} path={path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
