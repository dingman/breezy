"""ARM D1 S-COL: the read-only settlement collector for the maker harm stop.

One signed ``GET /v1/portfolio/activities`` traversal (the SAME client and endpoint constant as
``polymarket_us_capital_flow_pull.py``), paginated to ``eof`` (bounded by :data:`MAX_PAGES`). The
``ACTIVITY_TYPE_POSITION_RESOLUTION`` rows are read by
:func:`breezy.adapters.polymarket_us.account_activity.parse_position_resolutions`, kept for the
family's stations only, cross-checked against the CLI final by the existing
``reconcile_settlement`` (:mod:`breezy.analysis.labeling.maker_settlement_crosscheck`), merged
with the previous file, and written as ``maker_venue_settlement/v1`` (atomic, 0600) beside the
harm-stop artefact. The producer (``maker_loss_stop_producer.py``, no network) reads that file.

* A resolution whose outcome cannot be read with certainty, one that disagrees with the CLI final,
  and a slug the file already holds with the OPPOSITE outcome are all OMITTED (never guessed): an
  omitted slug is unresolved, which the harm stop counts as PENDING and, past the deadline, a LOSS.
* Read-only by construction: the only venue call reachable is ``get_authenticated``. No SDK, no
  ``exec/``, no permit. No Nautilus logging is initialised, and stdout carries ONE summary line of
  counts and a path -- never a header, a credential, a body, an id or an amount.
* A venue failure raises before anything is written (a failed run leaves the old file).

Exit status: 0 complete (``eof`` reached; some rows may still be omitted: see the summary counts),
1 error, 4 INCOMPLETE (``MAX_PAGES`` hit or no cursor before ``eof``; the file is still written
with ``complete: false`` and the producer then HOLDs). Non-zero fires ``OnFailure=``.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:  # pragma: no cover - operator entrypoint
    sys.path.insert(0, str(REPO_ROOT / "src"))

from nautilus_trader.common.component import LiveClock

from breezy.adapters.polymarket_us.account_activity import (
    PORTFOLIO_ACTIVITIES_PATH,
    parse_position_resolutions,
)
from breezy.adapters.polymarket_us.factories import (
    config_from_env,
    shared_polymarket_us_http_client,
)
from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient
from breezy.adapters.polymarket_us.transport import QUOTA_KEY_PORTFOLIO
from breezy.analysis.labeling.maker_settlement_crosscheck import crosscheck_with_cli
from breezy.strategy.no_ladder_maker.cli_final import CliReading, catalog_cli_reader
from breezy.strategy.no_ladder_maker.harm_stop import (
    maker_loss_stop_artefact_path,
    station_of_slug,
)
from breezy.strategy.no_ladder_maker.venue_settlement import (
    VENUE_SETTLEMENTS_NAME,
    read_venue_yes,
    write_venue_settlement,
)

__all__ = ["EXIT_INCOMPLETE", "MAX_PAGES", "PAGE_LIMIT", "SUMMARY_PREFIX", "collect", "main"]

#: 2,000 activities per run at the shared portfolio quota; past it the run is INCOMPLETE
MAX_PAGES: Final[int] = 20
PAGE_LIMIT: Final[int] = 100
SUMMARY_PREFIX: Final[str] = "MAKER_SETTLEMENT"
EXIT_INCOMPLETE: Final[int] = 4
CATALOG_ROOT_ENV: Final[str] = "BREEZY_TRADE_CATALOG_ROOT"
DEFAULT_DATA_ROOT: Final[Path] = Path.home() / ".local/share/breezy"


@dataclass(frozen=True, slots=True)
class CollectResult:
    complete: bool
    pages: int
    resolutions: int
    unreadable: int
    conflicts: int
    written: int
    unchecked: int
    mismatched: int


async def _pull_resolutions(
    client: PolymarketUSHttpClient, *, max_pages: int = MAX_PAGES
) -> tuple[dict[str, bool], set[str], int, int, bool]:
    """``(yes by slug, conflicting slugs, unreadable rows, pages, reached eof)``."""
    yes: dict[str, bool] = {}
    conflicts: set[str] = set()
    unreadable = pages = 0
    cursor: str | None = None
    complete = False
    for _ in range(max_pages):
        query: dict[str, Any] = {"limit": PAGE_LIMIT}
        if cursor:
            query["cursor"] = cursor
        page = await client.get_authenticated(
            PORTFOLIO_ACTIVITIES_PATH, query=query, quota_key=QUOTA_KEY_PORTFOLIO
        )
        pages += 1
        scan = parse_position_resolutions(page)
        unreadable += scan.unreadable
        for resolution in scan.resolutions:
            if yes.setdefault(resolution.slug, resolution.yes_resolved) != resolution.yes_resolved:
                conflicts.add(resolution.slug)
        raw_cursor = page.get("nextCursor")
        cursor = raw_cursor if isinstance(raw_cursor, str) and raw_cursor else None
        if page.get("eof") is True:
            complete = True
            break
        if not cursor:
            break  # not at eof and nowhere to go: the traversal is incomplete, never "done"
    return yes, conflicts, unreadable, pages, complete


def collect(
    client: PolymarketUSHttpClient,
    *,
    path: Path,
    stations: frozenset[str],
    cli_reading: CliReading,
    now: datetime,
) -> CollectResult:
    """Pull, scope, cross-check, merge, write. Raises on a venue failure BEFORE writing."""
    yes, conflicts, unreadable, pages, complete = asyncio.run(_pull_resolutions(client))
    in_scope = {s: v for s, v in yes.items() if station_of_slug(s) in stations}
    previous = {s: v for s, v in read_venue_yes(path).items() if station_of_slug(s) in stations}
    for slug, value in previous.items():
        if in_scope.setdefault(slug, value) != value:
            conflicts.add(slug)
    candidates = {s: v for s, v in in_scope.items() if s not in conflicts}
    checked = crosscheck_with_cli(candidates, cli_reading)
    keep = {s: candidates[s] for s in (*checked.agreed, *checked.unchecked)}
    write_venue_settlement(path, keep, fetched_at=now, complete=complete)
    return CollectResult(
        complete=complete,
        pages=pages,
        resolutions=len(in_scope),
        unreadable=unreadable,
        conflicts=len(conflicts),
        written=len(keep),
        unchecked=len(checked.unchecked),
        mismatched=len(checked.mismatched),
    )


def build_production_client(env: Mapping[str, str] | None = None) -> PolymarketUSHttpClient:
    """The real, credentialed, read-only client (never exercised by a test)."""
    return shared_polymarket_us_http_client(config_from_env(env), LiveClock())


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect the venue's YES resolutions (read-only).")
    parser.add_argument(
        "--station", action="append", required=True, dest="stations", help="family station token"
    )
    parser.add_argument("--catalog-root", type=Path, default=None)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--catalog-base", type=Path, default=None)
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    client: PolymarketUSHttpClient | None = None,
    cli_reading: CliReading | None = None,
    now: datetime | None = None,
) -> int:
    """Entrypoint. ``client`` / ``cli_reading`` / ``now`` are test seams; production passes none."""
    try:
        args = _parse(argv)
        environ = os.environ if env is None else env
        root_text = str(args.catalog_root) if args.catalog_root else environ.get(CATALOG_ROOT_ENV)
        if not root_text:
            print(f"{SUMMARY_PREFIX} status=ERROR error=MissingCatalogRoot")
            return 1
        path = maker_loss_stop_artefact_path(Path(root_text)).parent / VENUE_SETTLEMENTS_NAME
        active_client = client if client is not None else build_production_client(env)
        reader = cli_reading or catalog_cli_reader(args.catalog_base or args.data_root / "catalog")
        result = collect(
            active_client,
            path=path,
            stations=frozenset(args.stations),
            cli_reading=reader,
            now=now or datetime.now(tz=UTC),
        )
    except Exception as exc:  # noqa: BLE001 - deliberate: the class name is the whole message
        print(f"{SUMMARY_PREFIX} status=ERROR error={type(exc).__name__}")
        return 1
    status = "OK" if result.complete else "INCOMPLETE"
    print(
        f"{SUMMARY_PREFIX} status={status} pages={result.pages} resolutions={result.resolutions} "
        f"written={result.written} unchecked={result.unchecked} mismatched={result.mismatched} "
        f"unreadable={result.unreadable} conflicts={result.conflicts} path={path}"
    )
    return 0 if result.complete else EXIT_INCOMPLETE


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
