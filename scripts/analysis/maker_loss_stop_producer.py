"""ARM D1: the harm-stop producer for ``pm_us_no_maker_sharp_v1`` (plan r2 delta D5).

Reads the family's durable fill records and open submit intents from the exec-state SQLite
(READ-ONLY URI), the CLI final from the NWS station catalog (read-only), and the venue's own YES
resolutions from a local file; evaluates the pre-declared D5 harm stop
(``breezy.strategy.no_ladder_maker.harm_stop``); and writes ``derived/maker-loss-stop/latest.json``
in the exact ``loss_stop/v1`` format ``LossStopProbe`` reads. It makes NO network contact and
writes nothing but that artefact.

* PASS / FAIL write the file atomically. FAIL is sticky (a restart needs a new dated ruling), and
  so is a standing file this producer cannot read back.
* HOLD (GET- family fills, an open AMBIGUOUS family intent, an unreadable state DB or any
  undecodable fill record) removes a standing PASS so the probe vetoes at once, and never touches
  a FAIL.
* Zero fills is a PASS. A fill whose settlement is not yet knowable is PENDING until 48 h after the
  end of its local station-day (in no count); after that it is a LOSS.

The artefact lands at ``maker_loss_stop_artefact_path(--catalog-root)``, the path the node's probe
reads (``--catalog-root`` is the node's ``BREEZY_TRADE_CATALOG_ROOT``).

Exit status (so ``OnFailure=`` alerts): 0 PASS, 2 FAIL (a computed FAIL, or a sticky FAIL or
unreadable file standing on disk), 3 HOLD, 1 error.

The venue-settlement input (``--venue-settlements``, default beside the artefact) is a JSON object
``{"schema": "maker_venue_settlement/v1", "yes_resolved": {"<base slug>": true|false}, ...}``
written by ``scripts/venue/maker_settlement_collect.py``; extra keys are ignored. An absent or
unreadable file leaves every fill unresolved (PENDING, then a LOSS past the deadline). The CLI
final alone never resolves a fill (it is the cross-check).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

from breezy.adapters.polymarket_us.exec.client import FILL_KEY_PREFIX, DurableFillRecord
from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from breezy.domain.instrument_leg import (
    base_symbol_of,
    leg_of_symbol,
    symbol_of_instrument_id,
)
from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts
from breezy.persistence.catalog import (
    open_station_catalog,
    read_climate_day_including_corrections,
    station_catalog_path,
)
from breezy.registry.sites import SiteNotFoundError, default_registry
from breezy.runtime.submit_intent import CURRENT_INTENT_KEY, SubmitIntentCorrupt, decode_slot_table
from breezy.strategy.no_ladder_maker.harm_stop import (
    FillOutcome,
    HarmStopResult,
    HarmVerdict,
    SettledFill,
    classify_family_fills,
    d1_fill_cost_conservative,
    evaluate_harm_stop,
    maker_loss_stop_artefact_path,
    settle_fill,
    settlement_deadline,
    station_of_slug,
)
from breezy.strategy.no_ladder_maker.harm_stop_artefact import ACTION_STICKY, Action, publish

VENUE_SCHEMA: Final[str] = "maker_venue_settlement/v1"
VENUE: Final[str] = "polymarket_us"
EXIT_PASS: Final[int] = 0
EXIT_ERROR: Final[int] = 1
EXIT_FAIL: Final[int] = 2
EXIT_HOLD: Final[int] = 3
DEFAULT_DATA_ROOT: Final[Path] = Path.home() / ".local/share/breezy"
#: the collector writes this beside ``latest.json``; the producer reads it
VENUE_SETTLEMENTS_NAME: Final[str] = "venue_settlements.json"
STATE_DB_ENV: Final[str] = "POLYMARKET_US_EXEC_STATE_DB"
#: the node's own variable (``breezy.runtime.settings.TRADE_CATALOG_ROOT_VAR``; not imported: the
#: producer stays free of ``breezy.runtime``)
CATALOG_ROOT_ENV: Final[str] = "BREEZY_TRADE_CATALOG_ROOT"

CliReading = Callable[[WeatherBucketFacts], int | None]
#: station token -> the climate day's fixed standard-time UTC offset in hours (None: unknown)
StdOffset = Callable[[str], float | None]


@dataclass(frozen=True, slots=True)
class Outcome:
    result: HarmStopResult
    action: Action
    path: Path


@dataclass(frozen=True, slots=True)
class _StateRead:
    records: tuple[DurableFillRecord, ...]
    open_slugs: tuple[str, ...]
    blocked: tuple[str, ...]


# -- read-only inputs ----------------------------------------------------------------------------


def _read_state(state_db: Path) -> _StateRead:
    """Fills and open-intent slugs; anything unreadable is a blocking reason (never silent)."""
    if not state_db.is_file():
        return _StateRead((), (), ("state_db_unreadable",))
    try:
        conn = sqlite3.connect(f"{state_db.absolute().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return _StateRead((), (), ("state_db_unreadable",))
    try:
        rows = conn.execute("SELECT key, value FROM state").fetchall()
    except sqlite3.Error:
        return _StateRead((), (), ("state_db_unreadable",))
    finally:
        conn.close()
    blocked: list[str] = []
    records: list[DurableFillRecord] = []
    intent_raw: bytes | None = None
    for key, value in rows:
        if not isinstance(key, str):
            continue
        if key == CURRENT_INTENT_KEY:
            intent_raw = bytes(value)
        elif key.startswith(FILL_KEY_PREFIX):
            try:
                records.append(DurableFillRecord.from_bytes(value))
            except Exception:  # noqa: BLE001 - ANY undecodable record may hide a fill: HOLD
                blocked.append("fill_record_corrupt")
    open_slugs, intent_blocked = _open_slugs(intent_raw)
    return _StateRead(tuple(records), open_slugs, tuple(dict.fromkeys([*blocked, *intent_blocked])))


def _open_slugs(raw: bytes | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    try:
        table = decode_slot_table(raw)
    except SubmitIntentCorrupt:
        return (), ("intent_table_corrupt",)
    blocked: list[str] = []
    slugs: list[str] = []
    for intent in table.open:
        if intent.slug is None:
            blocked.append("open_intent_unattributable")
        else:
            slugs.append(intent.slug)
    if table.unreadable:
        blocked.append("open_intent_unattributable")
    return tuple(slugs), tuple(dict.fromkeys(blocked))


def _read_venue_yes(path: Path | None) -> dict[str, bool]:
    """``{base slug: venue resolved YES}``; absent/unreadable/malformed -> ``{}`` (unresolved)."""
    if path is None:
        return {}
    try:
        body = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(body, dict) or body.get("schema") != VENUE_SCHEMA:
        return {}
    raw = body.get("yes_resolved")
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, bool)}


def registry_std_offset_hours(station: str) -> float | None:
    """The registry's fixed standard-time UTC offset of a station token; ``None`` if unknown."""
    registry = default_registry()
    try:
        city = registry.site_for_venue_city_token(VENUE, station).city
        return registry.climate_day_window(VENUE, city).std_utc_offset_hours
    except SiteNotFoundError:
        return None


def catalog_cli_reader(catalog_base: Path) -> CliReading:
    """The CLI final from the station catalog; ``None`` when no FINAL with a value is stored.

    Never creates a catalog: a station without an existing catalog directory reads ``None``. Each
    station's catalog is opened once (the Nautilus catalog has no close; it holds no handle)."""
    registry = default_registry()
    city_of = {
        registry.settlement_site(venue, city).cli_location: city
        for venue, city in registry.pairs()
        if venue == VENUE
    }
    opened: dict[str, Any] = {}

    def read(facts: WeatherBucketFacts) -> int | None:
        city = city_of.get(facts.settlement_station)
        if city is None or not station_catalog_path(catalog_base, VENUE, city).is_dir():
            return None
        if city not in opened:
            opened[city] = open_station_catalog(catalog_base, VENUE, city)
        record = read_climate_day_including_corrections(
            opened[city], station=facts.settlement_station, climate_day=facts.climate_day
        )
        if record is None or not record.is_final:
            return None
        return record.tmax_f if facts.measure is Measure.HIGH else record.tmin_f

    return read


# -- one fill -> one settled fill ----------------------------------------------------------------


def _settle_record(
    record: DurableFillRecord,
    venue_yes: dict[str, bool],
    cli_reading: CliReading,
    *,
    now: datetime,
    std_offset_hours: StdOffset,
) -> SettledFill:
    symbol = symbol_of_instrument_id(record.instrument_id)
    facts = bucket_facts_from_instrument_id(record.instrument_id)
    station = station_of_slug(symbol)
    # review K3: an unparseable rung is its OWN station-day, never one shared "<station>|unknown"
    day = f"unparseable|{record.venue_order_id}" if facts is None else facts.climate_day.isoformat()
    station_day = f"{station}|{day}"
    cost = d1_fill_cost_conservative(record)
    if facts is None or leg_of_symbol(symbol) != "no":
        cause = "rung_unparseable" if facts is None else "not_a_no_leg"
        return SettledFill(
            station_day=station_day, cost=cost, outcome=FillOutcome.UNRESOLVED, cause=cause
        )
    reading = cli_reading(facts)
    return settle_fill(
        station_day=station_day,
        cost=cost,
        quantity=record.cumulative_qty,
        venue_yes_resolved=venue_yes.get(base_symbol_of(symbol)),
        cli_yes=None if reading is None else facts.contains(reading),
        pending=_before_deadline(station, facts.climate_day, now, std_offset_hours),
    )


def _before_deadline(station: str, climate_day: date, now: datetime, offset: StdOffset) -> bool:
    """Review J2: still inside the settlement window. An unknown station offset is NOT pending."""
    hours = offset(station)
    if hours is None:
        return False
    return now < settlement_deadline(climate_day, std_utc_offset_hours=hours)


def _truth_sha(settled: Sequence[tuple[str, SettledFill]]) -> str:
    rows = sorted(
        (slug, f.station_day, f.outcome.value, f.cause, str(f.cost)) for slug, f in settled
    )
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def produce(
    *,
    state_db: Path,
    derived_dir: Path,
    venue_settlements: Path | None,
    family_stations: frozenset[str],
    cli_reading: CliReading,
    now: datetime,
    std_offset_hours: StdOffset = registry_std_offset_hours,
) -> Outcome:
    """Evaluate D5 over the stores and publish. Reads only; the one write is ``latest.json``."""
    state = _read_state(state_db)
    # a slug that is not the weather grammar is not a family slug (``station_of_slug`` -> "")
    classification = classify_family_fills(
        state.records, family_stations=family_stations, open_ambiguous_slugs=state.open_slugs
    )
    reasons = list(state.blocked)
    if classification.get_fills:
        reasons.append("get_fill")
    if classification.open_ambiguous_family_intent:
        reasons.append("open_ambiguous_family_intent")
    venue_yes = _read_venue_yes(venue_settlements)
    settled = [
        (
            base_symbol_of(symbol_of_instrument_id(r.instrument_id)),
            _settle_record(r, venue_yes, cli_reading, now=now, std_offset_hours=std_offset_hours),
        )
        for r in classification.maker_fills
    ]
    result = evaluate_harm_stop(
        [f for _, f in settled], blocked_reasons=tuple(dict.fromkeys(reasons))
    )
    ts_max = max((r.ts_event for r in classification.maker_fills), default=0)
    published = publish(
        derived_dir / "latest.json",
        result,
        as_of=now,
        c2_hwm=f"maker_fills={len(classification.maker_fills)};ts_event_max={ts_max}",
        truth_sha=_truth_sha(settled),
    )
    return Outcome(result=result, action=published.action, path=derived_dir / "latest.json")


def artefact_path(catalog_root: Path) -> Path:
    """Where the node's probe reads this family's verdict (J6: one function, shared with the probe's
    own path rule in ``harm_stop``)."""
    return maker_loss_stop_artefact_path(catalog_root)


# -- CLI -----------------------------------------------------------------------------------------


def exit_code_for(outcome: Outcome) -> int:
    """The verdict's code; a sticky FAIL (or unreadable file) standing on disk is always FAIL."""
    if outcome.action == ACTION_STICKY:
        return EXIT_FAIL
    return {
        HarmVerdict.PASS: EXIT_PASS,
        HarmVerdict.FAIL: EXIT_FAIL,
        HarmVerdict.HOLD: EXIT_HOLD,
    }[outcome.result.verdict]


def _summary(outcome: Outcome) -> dict[str, Any]:
    r = outcome.result
    return {
        "verdict": r.verdict.value,
        "action": outcome.action,
        "triggers": list(r.triggers),
        "hold_reasons": list(r.hold_reasons),
        "fills": r.fills,
        "wins": r.wins,
        "losses": r.losses,
        "n": r.n,
        "unresolved": r.unresolved,
        "pending": r.pending,
        "w_star": None if r.w_star is None else str(r.w_star),
        "cum_pnl": str(r.cum_pnl),
        "cp_upper": r.cp_upper,
        "path": str(outcome.path),
    }


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument(
        "--station",
        action="append",
        required=True,
        dest="stations",
        help="family station token (repeatable), e.g. nyc; no default",
    )
    parser.add_argument(
        "--state-db", type=Path, default=None, help=f"exec-state sqlite; default ${STATE_DB_ENV}"
    )
    parser.add_argument(
        "--catalog-root",
        type=Path,
        default=None,
        help=f"the node's quote-tape catalog root; default ${CATALOG_ROOT_ENV}",
    )
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--catalog-base", type=Path, default=None)
    parser.add_argument("--venue-settlements", type=Path, default=None)
    return parser.parse_args(argv)


def _required_path(flag: Path | None, env_name: str) -> Path | None:
    if flag is not None:
        return flag
    return Path(os.environ[env_name]) if os.environ.get(env_name) else None


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse(argv)
    state_db = _required_path(args.state_db, STATE_DB_ENV)
    if state_db is None:
        print(f"error: --state-db or ${STATE_DB_ENV} is required", file=sys.stderr)
        return EXIT_ERROR
    catalog_root = _required_path(args.catalog_root, CATALOG_ROOT_ENV)
    if catalog_root is None:
        print(f"error: --catalog-root or ${CATALOG_ROOT_ENV} is required", file=sys.stderr)
        return EXIT_ERROR
    latest = artefact_path(catalog_root)
    outcome = produce(
        state_db=state_db,
        derived_dir=latest.parent,
        venue_settlements=args.venue_settlements or latest.parent / VENUE_SETTLEMENTS_NAME,
        family_stations=frozenset(args.stations),
        cli_reading=catalog_cli_reader(args.catalog_base or args.data_root / "catalog"),
        now=datetime.now(tz=UTC),
    )
    print(json.dumps(_summary(outcome), sort_keys=True))
    return exit_code_for(outcome)


if __name__ == "__main__":
    sys.exit(main())
