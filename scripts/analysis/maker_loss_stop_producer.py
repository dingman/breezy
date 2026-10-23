"""ARM D1: the harm-stop producer for ``pm_us_no_maker_sharp_v1`` (plan r2 delta D5).

Reads the family's durable fill records and open submit intents from the exec-state SQLite
(READ-ONLY URI), the CLI final from the NWS station catalog (read-only), and the venue's own YES
resolutions from a local file; evaluates the pre-declared D5 harm stop
(``breezy.strategy.no_ladder_maker.harm_stop``); and writes ``derived/maker-loss-stop/latest.json``
in the exact ``loss_stop/v1`` format ``LossStopProbe`` reads. It makes NO network contact and
writes nothing but that artefact.

* PASS / FAIL write the file atomically. FAIL is sticky (a restart needs a new dated ruling), and
  so is a standing file this producer cannot read back.
* HOLD (a ``GET-`` family fill at or after the posting-window floor, an open AMBIGUOUS family
  intent, an unreadable state DB or any undecodable fill record, a missing / incomplete / stale
  venue-settlement file, or a family station with no known UTC offset) removes a standing PASS so
  the probe vetoes at once, and never touches a FAIL.
* Zero fills is a PASS. A fill whose settlement is not yet knowable is PENDING until 48 h after the
  end of its local station-day (in no count); after that it is a LOSS.

The artefact lands at ``maker_loss_stop_artefact_path(--catalog-root)``, the path the node's probe
reads (``--catalog-root`` is the node's ``BREEZY_TRADE_CATALOG_ROOT``).

It runs once a day (``breezy-maker-loss-stop.timer``, 12:50Z), NOT after every settlement batch, so
a loss that settles after 12:50Z is first counted the next day. A resolver-booked ``GET-`` fill
on a family station HOLDs the maker verdict only when its ``ts_event`` is at or after the family's
posting-window open (D-1 16:50Z of manifest ``d0_climate_day``). An earlier FQ resolver fill on a
maker station does not block the maker stop. With no floor (``get_fill_not_before_ns`` unset) the
HOLD stays unbounded, so a missing manifest must not be treated as "no floor".

Exit status (so ``OnFailure=`` alerts): 0 PASS, 2 FAIL (a computed FAIL, or a sticky FAIL or
unreadable file standing on disk), 3 HOLD, 1 error.

The venue-settlement input (``--venue-settlements``, default beside the artefact) is a JSON object
``{"schema": "maker_venue_settlement/v1", "yes_resolved": {"<base slug>": true|false}, ...}``
written by ``scripts/venue/maker_settlement_collect.py``; extra keys are ignored. An absent or
unreadable file leaves every fill unresolved. The CLI final alone never resolves a fill (it is the
cross-check).

The file must be PRESENT, ``complete: true`` and fetched at most
:data:`breezy.strategy.no_ladder_maker.venue_settlement.SETTLEMENT_MAX_AGE` (24 h) before the
producer's ``now``; otherwise the verdict HOLDs (``venue_settlement_missing`` / ``_incomplete`` /
``_stale``) and every fill the file does not resolve stays PENDING instead of turning into a LOSS
(so a partial page cannot latch a sticky FAIL; slugs it DOES resolve are still scored). With a
trusted file, an unresolved fill past its deadline is a LOSS. A family station with no registry
UTC offset likewise HOLDs (``station_offset_unknown``) with its unresolved fills PENDING.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from collections.abc import Sequence
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
from breezy.runtime.submit_intent import CURRENT_INTENT_KEY, SubmitIntentCorrupt, decode_slot_table
from breezy.strategy.no_ladder_maker.cli_final import (
    CliReading,
    StdOffset,
    catalog_cli_reader,
    registry_std_offset_hours,
)
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
from breezy.strategy.no_ladder_maker.rule import window_open_ns
from breezy.strategy.no_ladder_maker.venue_settlement import (
    VENUE_SETTLEMENTS_NAME,
    read_venue_settlement,
    untrusted_reason,
)

EXIT_PASS: Final[int] = 0
EXIT_ERROR: Final[int] = 1
EXIT_FAIL: Final[int] = 2
EXIT_HOLD: Final[int] = 3
DEFAULT_DATA_ROOT: Final[Path] = Path.home() / ".local/share/breezy"
STATE_DB_ENV: Final[str] = "POLYMARKET_US_EXEC_STATE_DB"
#: the node's own variable (``breezy.runtime.settings.TRADE_CATALOG_ROOT_VAR``; not imported: the
#: producer stays free of ``breezy.runtime``)
CATALOG_ROOT_ENV: Final[str] = "BREEZY_TRADE_CATALOG_ROOT"
DEFAULT_FAMILY_MANIFEST: Final[Path] = (
    Path(__file__).resolve().parents[2] / "deploy" / "families" / "pm_us_no_maker_sharp_v1.json"
)


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


# -- one fill -> one settled fill ----------------------------------------------------------------


def _settle_record(
    record: DurableFillRecord,
    venue_yes: dict[str, bool],
    cli_reading: CliReading,
    *,
    now: datetime,
    std_offset_hours: StdOffset,
    settlement_trusted: bool,
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
        pending=not settlement_trusted
        or _before_deadline(station, facts.climate_day, now, std_offset_hours),
    )


def _before_deadline(station: str, climate_day: date, now: datetime, offset: StdOffset) -> bool:
    """Review J2: still inside the settlement window. An unknown station offset leaves the fill
    PENDING (the caller HOLDs ``station_offset_unknown``); it is never turned into a LOSS."""
    hours = offset(station)
    if hours is None:
        return True
    return now < settlement_deadline(climate_day, std_utc_offset_hours=hours)


def _truth_sha(settled: Sequence[tuple[str, SettledFill]]) -> str:
    rows = sorted(
        (slug, f.station_day, f.outcome.value, f.cause, str(f.cost)) for slug, f in settled
    )
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def _get_fill_holds(fills: tuple[DurableFillRecord, ...], not_before_ns: int | None) -> bool:
    """True when a classified ``GET-`` fill should HOLD.

    ``None`` is the unbounded rule (any fill). A bound counts only ``ts_event >= not_before_ns``.
    """
    if not_before_ns is None:
        return bool(fills)
    return any(fill.ts_event >= not_before_ns for fill in fills)


def family_get_fill_floor_ns(manifest: Path) -> int:
    """D-1 16:50Z of ``manifest``'s ``d0_climate_day``, as integer UTC ns.

    ``OSError`` if the file cannot be read. ``ValueError`` if ``d0_climate_day`` is missing or
    not an ISO date. Never invents a floor.
    """
    try:
        text = manifest.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"family manifest {manifest} is not utf-8 text") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"family manifest {manifest} is not JSON") from exc
    raw = payload.get("d0_climate_day") if isinstance(payload, dict) else None
    day_text = raw if isinstance(raw, str) else None
    if day_text is None:
        raise ValueError(f"family manifest {manifest} lacks d0_climate_day")
    try:
        day = date.fromisoformat(day_text)
    except ValueError as exc:
        raise ValueError(
            f"family manifest {manifest} d0_climate_day {day_text!r} is not an ISO date"
        ) from exc
    return window_open_ns(day)


def produce(
    *,
    state_db: Path,
    derived_dir: Path,
    venue_settlements: Path | None,
    family_stations: frozenset[str],
    cli_reading: CliReading,
    now: datetime,
    std_offset_hours: StdOffset = registry_std_offset_hours,
    get_fill_not_before_ns: int | None = None,
) -> Outcome:
    """Evaluate D5 over the stores and publish. Reads only; the one write is ``latest.json``.

    ``get_fill_not_before_ns`` floors the ``GET-`` HOLD at that UTC ns (inclusive). ``None`` keeps
    the unbounded HOLD.
    """
    state = _read_state(state_db)
    # a slug that is not the weather grammar is not a family slug (``station_of_slug`` -> "")
    classification = classify_family_fills(
        state.records, family_stations=family_stations, open_ambiguous_slugs=state.open_slugs
    )
    reasons = list(state.blocked)
    if _get_fill_holds(classification.get_fills, get_fill_not_before_ns):
        reasons.append("get_fill")
    if classification.open_ambiguous_family_intent:
        reasons.append("open_ambiguous_family_intent")
    settlement = read_venue_settlement(venue_settlements)
    distrust = untrusted_reason(settlement, now=now)
    if distrust is not None:
        reasons.append(distrust)
    unknown_offset = {
        station_of_slug(symbol_of_instrument_id(r.instrument_id))
        for r in classification.maker_fills
        if std_offset_hours(station_of_slug(symbol_of_instrument_id(r.instrument_id))) is None
    }
    if unknown_offset:
        reasons.append("station_offset_unknown")
    settled = [
        (
            base_symbol_of(symbol_of_instrument_id(r.instrument_id)),
            _settle_record(
                r,
                settlement.yes_resolved,
                cli_reading,
                now=now,
                std_offset_hours=std_offset_hours,
                settlement_trusted=distrust is None,
            ),
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
    parser.add_argument(
        "--family-manifest",
        type=Path,
        default=None,
        help=(
            "family manifest; d0_climate_day floors GET- fills at D-1 16:50Z "
            f"(default: {DEFAULT_FAMILY_MANIFEST})"
        ),
    )
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
    manifest = args.family_manifest if args.family_manifest is not None else DEFAULT_FAMILY_MANIFEST
    try:
        floor_ns = family_get_fill_floor_ns(manifest)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    outcome = produce(
        state_db=state_db,
        derived_dir=latest.parent,
        venue_settlements=args.venue_settlements or latest.parent / VENUE_SETTLEMENTS_NAME,
        family_stations=frozenset(args.stations),
        cli_reading=catalog_cli_reader(args.catalog_base or args.data_root / "catalog"),
        now=datetime.now(tz=UTC),
        get_fill_not_before_ns=floor_ns,
    )
    print(json.dumps(_summary(outcome), sort_keys=True))
    return exit_code_for(outcome)


if __name__ == "__main__":
    sys.exit(main())
