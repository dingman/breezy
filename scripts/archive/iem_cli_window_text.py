"""``window-text``: cache one validated ``fmt=text`` AFOS CLI window per maker station.

MAKER-S2 second look, unit C6b (``S2_second_look_plan_r3_delta_coordinator.md`` section 1).
Logic for the ``iem_cli_fetch.py window-text`` subcommand, which stays the single writer
(this module is only ever called from it, with its paced transport injected as
``fetch_text``; it never opens a socket). The settlement cross-check for the block-2
replay reads the result through ``settlement_truth_dataset.read_window_issuances``.

CONTRACT
--------
* Maker stations only (``MAKER_S2B_CITIES``); anything else is refused before any lock,
  fetch or write.
* One exclusive cache lock (the revision store's) is held across the whole pass.
* Validate BEFORE committing: every city's body must parse to FINAL products whose latest
  climate day is >= ``--min-final-day``. If ANY city fails, NOTHING is written (no ``.txt``
  and no sidecar line), so the same URL can be retried later.
* A ``.txt`` is written atomically to ``cache_path_for_url(cache_dir, url, ".txt")`` and
  is NEVER overwritten; the sha256 sidecar line is appended in the same format the zip
  path uses (``<digest>  <name>``), temp + rename, under the same lock.

EXIT CODES
----------
0 ok / 1 transport, HTTP, lock or I/O failure / 2 refused (bad city, bad argument, would
overwrite, missing cache dir) / 3 short window (max FINAL day below ``--min-final-day``).
The 16:30-17:10 UTC launch window is refused by ``iem_cli_fetch.main`` (exit 6).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
for _sibling in ("analysis", "archive"):  # pragma: no cover - bootstrap
    _sibling_path = str(_SCRIPTS_ROOT / _sibling)
    if _sibling_path not in sys.path:
        sys.path.insert(0, _sibling_path)

from iem_cli_revisions import (  # type: ignore[import-not-found]
    CacheLockedError,
    RevisionStore,
    atomic_write,
    sha256_hex,
)
from settlement_alignment_cache import (  # type: ignore[import-not-found]
    DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR,
    SettlementAlignmentCacheError,
    require_settlement_alignment_cache_dir,
)
from settlement_alignment_study import (  # type: ignore[import-not-found]
    SiteSpec,
    cache_path_for_url,
    load_sites,
    parse_cli_labels,
)
from settlement_text_window import (  # type: ignore[import-not-found]
    MAKER_S2B_CITIES,
    MAKER_S2B_LIMIT,
    MAKER_S2B_WINDOW_END,
    MAKER_S2B_WINDOW_START,
    text_window_url,
)

EXIT_OK: Final[int] = 0
EXIT_FAILED: Final[int] = 1
EXIT_REFUSED: Final[int] = 2
EXIT_SHORT: Final[int] = 3

#: ``(url, station) -> (body_text, error)``; exactly one of the two is non-empty.
FetchText = Callable[[str, str], Awaitable[tuple[str | None, str]]]


@dataclass(frozen=True, slots=True)
class _Item:
    spec: SiteSpec
    url: str
    path: Path


def add_window_text_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--city", action="append", default=None, help="maker station; repeatable")
    command.add_argument("--start", default=MAKER_S2B_WINDOW_START.isoformat())
    command.add_argument("--end", default=MAKER_S2B_WINDOW_END.isoformat())
    command.add_argument("--min-final-day", required=True, help="latest FINAL day required")
    command.add_argument("--cache-dir", default=str(DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR))
    command.add_argument("--limit", type=int, default=MAKER_S2B_LIMIT)


def _say(message: str) -> None:
    print(message, file=sys.stderr)


def _target_path(cache_dir: Path, url: str) -> Path:
    path: Path = cache_path_for_url(cache_dir, url, ".txt")
    return path


def _plan(args: argparse.Namespace, cache_dir: Path) -> tuple[_Item, ...]:
    """Validated items, or ``ValueError`` naming the first refusal. Touches nothing."""
    cities = tuple(dict.fromkeys(args.city or ()))
    if not cities:
        raise ValueError("no --city given; name one or more of " + " ".join(MAKER_S2B_CITIES))
    bad = [city for city in cities if city not in MAKER_S2B_CITIES]
    if bad:
        raise ValueError(
            f"not a maker station: {' '.join(bad)} (allowed: {' '.join(MAKER_S2B_CITIES)})"
        )
    start, end = dt.date.fromisoformat(args.start), dt.date.fromisoformat(args.end)
    dt.date.fromisoformat(args.min_final_day)
    if start > end:
        raise ValueError(f"--start {start} is after --end {end}")
    by_city = {spec.city: spec for spec in load_sites()}
    items = []
    for city in cities:
        url = text_window_url(by_city[city].site.cli_location, start, end, args.limit)
        items.append(_Item(by_city[city], url, _target_path(cache_dir, url)))
    return tuple(items)


def _short_reason(item: _Item, text: str, args: argparse.Namespace) -> str | None:
    """A one-line reason when the body does not reach ``--min-final-day``, else ``None``."""
    labels, _drops, _errors = parse_cli_labels(
        city=item.spec.city,
        site=item.spec.site,
        raw_text=text,
        source_url=item.url,
        start=dt.date.fromisoformat(args.start),
        end=dt.date.fromisoformat(args.end),
    )
    required = dt.date.fromisoformat(args.min_final_day)
    latest = max(labels) if labels else None
    if latest is not None and latest >= required:
        return None
    return f"short window: {item.spec.city} max FINAL climate day {latest} < required {required}"


def _append_sidecar(cache_dir: Path, name: str, digest: str) -> None:
    sidecar = cache_dir.with_suffix(".sha256")
    existing = sidecar.read_bytes() if sidecar.is_file() else b""
    if existing and not existing.endswith(b"\n"):
        existing += b"\n"
    atomic_write(sidecar, existing + f"{digest}  {name}\n".encode())


def _commit(cache_dir: Path, path: Path, text: str) -> None:
    body = text.encode("utf-8")
    atomic_write(path, body)
    try:
        _append_sidecar(cache_dir, path.name, sha256_hex(body))
    except OSError:
        path.unlink(missing_ok=True)  # created by this pass under the lock; leave no orphan
        raise


async def _pass(
    items: Sequence[_Item], args: argparse.Namespace, cache_dir: Path, fetch_text: FetchText
) -> int:
    existing = [item.path.name for item in items if item.path.exists()]
    if existing:
        _say(f"refused: would overwrite existing cache file(s): {' '.join(existing)}")
        return EXIT_REFUSED
    fetched: list[tuple[_Item, str]] = []
    for item in items:
        text, error = await fetch_text(item.url, item.spec.city)
        if text is None:
            _say(f"failed: {item.spec.city}: {error}")
            return EXIT_FAILED
        reason = _short_reason(item, text, args)
        if reason is not None:
            _say(reason)
            return EXIT_SHORT
        fetched.append((item, text))
    for item, text in fetched:
        _commit(cache_dir, item.path, text)
        print(f"{item.spec.city} committed {item.path.name}")
    return EXIT_OK


def run_window_text(args: argparse.Namespace, *, fetch_text: FetchText) -> int:
    try:
        cache_dir = require_settlement_alignment_cache_dir(args.cache_dir)
        items = _plan(args, cache_dir)
    except (ValueError, SettlementAlignmentCacheError) as exc:
        _say(f"refused: {exc}")
        return EXIT_REFUSED
    try:
        with RevisionStore(cache_dir).locked():
            return asyncio.run(_pass(items, args, cache_dir, fetch_text))
    except CacheLockedError as exc:
        _say(f"aborted: {exc}")
    except OSError as exc:
        _say(f"failed: {exc}")
    return EXIT_FAILED
