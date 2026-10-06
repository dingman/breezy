"""Fill attribution: C1 after the epoch, a storage key before it (AUT-2 r7 WP2, section 3.4).

* **POST_EPOCH** fills are attributed through ``client_order_id -> OrderLink -> DecisionRecord`` and
  nothing else (P2-5, Q2). ``drill`` comes from the C1 record; ``voided_pair`` from the C5 fold
  query. A C5 CHAMPION that differs from the C1 family raises an alert but never re-attributes.
* **PRE_EPOCH** fills get a *storage key* for the label file (:class:`PreEpochAttribution`): never
  an attribution, never admissible, and never read by a statistic. The key comes from rule (b), the
  C5 CHAMPION on the venue at ``ts_event``, and rule (c), the bridge: the base-slug grammar, the
  stored latch key, and exactly one manifest matching kind, venue, station and date window. (b) and
  (c) disagreeing, or neither naming exactly one family, is UNRESOLVED.

No rule here reads a manifest's ``trial_id_prefix``: two families can share one, and the stored
latch key is not derived from it (G35).
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from breezy.adapters.polymarket_us.exec.client import FILL_KEY_PREFIX, DurableFillRecord
from breezy.analysis.labeling.epoch import EpochClass, EpochOutcome, EpochReader, fill_epoch_class
from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from breezy.domain.instrument_leg import base_symbol_of, symbol_of_instrument_id
from breezy.persistence.autonomy.canonical import canonical_json
from breezy.persistence.autonomy.capture_reader import DecisionView, OrderLinkView
from breezy.persistence.autonomy.label_schema import ExcludedReason, PSource
from breezy.persistence.autonomy.single_read import ensure_dir, open_root, write_once
from breezy.persistence.family_manifest import FamilyManifest
from breezy.strategy.current_rung_hold.trial_day_latch import trial_id_for
from breezy.strategy.forecast_quantile_ladder.persistent_latch import (
    FORECAST_QUANTILE_TRIAL_KEY_PREFIX,
)

__all__ = [
    "UNRESOLVED_JOURNAL_DIR",
    "Attribution",
    "BackfillRefused",
    "C1Lookup",
    "PreEpochAttribution",
    "Unresolved",
    "UnresolvedRow",
    "attribute_fill",
    "attribute_post_epoch",
    "backfill_family",
    "fill_key_sha",
    "fq_trial_id",
    "label_family_set",
    "latch_key_exists",
    "unresolved_row_of",
    "write_unresolved_journal",
]

UNRESOLVED_JOURNAL_DIR: Final[tuple[str, ...]] = ("evidence", "aut2", "unresolved")
_JOURNAL_FILE_MODE: Final[int] = 0o600
_FQ_KIND: Final[str] = "forecast_quantile_ladder"
_TAKE: Final[str] = "Take"
_FOLD_DISAGREEMENT: Final[str] = "c1_fold_disagreement"

#: ``(venue, ts_event_ns) -> the CHAMPION family on that venue then, or None``: the C5 fold query.
ChampionAt = Callable[[str, int], str | None]
#: ``(family_id, ts_event_ns) -> True when the family's pair is voided at that instant``.
PairVoided = Callable[[str, int], bool]


class C1Lookup(Protocol):
    def order_links(self, client_order_id: str) -> tuple[OrderLinkView, ...]: ...

    def decision(self, decision_id: str) -> DecisionView | None: ...


class BackfillRefused(Exception):
    """A backfill rule was asked to run on a POST_EPOCH fill: C1 is the only attribution there."""


@dataclass(frozen=True)
class Unresolved:
    """No unique, trustworthy identity: the fill gets no C2 row, a journal row and a CRITICAL."""

    reason: str
    critical: bool = True


@dataclass(frozen=True)
class Attribution:
    """A POST_EPOCH fill's identity, from C1 only."""

    family_id: str
    decision: DecisionView
    link: OrderLinkView
    drill: bool
    voided_pair: bool
    alerts: tuple[str, ...]

    @property
    def excluded_reason(self) -> ExcludedReason | None:
        if self.drill:
            return ExcludedReason.DRILL
        if self.voided_pair:
            return ExcludedReason.VOIDED_PAIR
        return None


@dataclass(frozen=True)
class PreEpochAttribution:
    """A PRE_EPOCH fill: ``storage_key`` names the label file only. It is never an attribution."""

    storage_key: str
    decision_id: None = None
    admissible: bool = False
    excluded_reason: ExcludedReason = ExcludedReason.UNATTRIBUTED
    allowed_p_sources: tuple[PSource, ...] = (PSource.ARTEFACT_RECOMPUTE, PSource.NONE)


def attribute_post_epoch(
    fill: DurableFillRecord,
    c1: C1Lookup,
    *,
    venue: str,
    champion_at: ChampionAt | None = None,
    pair_voided: PairVoided | None = None,
) -> Attribution | Unresolved:
    """Attribute one POST_EPOCH fill through C1, or say why it cannot be."""
    links = c1.order_links(fill.client_order_id)
    if not links:
        return Unresolved("no_order_link")
    if len({link.decision_id for link in links}) > 1:
        return Unresolved("link_conflict")
    link = links[0]
    decision = c1.decision(link.decision_id)
    if decision is None:
        return Unresolved("no_decision")
    if decision.kind == _TAKE and not decision.p_hat:
        return Unresolved("take_without_p_hat")
    alerts: tuple[str, ...] = ()
    if champion_at is not None:
        champion = champion_at(venue, fill.ts_event)
        if champion is not None and champion != decision.family_id:
            alerts = (_FOLD_DISAGREEMENT,)
    voided = pair_voided is not None and pair_voided(decision.family_id, fill.ts_event)
    return Attribution(
        family_id=decision.family_id,
        decision=decision,
        link=link,
        drill=decision.drill,
        voided_pair=voided,
        alerts=alerts,
    )


def fq_trial_id(station: str, climate_day: str, rung_id: str, side: str) -> str:
    """The stored latch key of an FQ trial: ``<prefix><STATION>/<day>/<rung_id>:<side>.<VENUE>``.

    Built by the latch's own public key builder, with the same composite instrument segment the
    persistent FQ latch writes, so it is the key the live store holds (G28, G35).
    """
    for label, value in (("rung_id", rung_id), ("side", side)):
        if ":" in value or "/" in value:
            raise ValueError(f"{label} must not contain a ':' or '/' separator: {value!r}")
    return trial_id_for(
        FORECAST_QUANTILE_TRIAL_KEY_PREFIX, station, climate_day, f"{rung_id}:{side}"
    )


def latch_key_exists(db_path: Path, trial_id: str) -> bool:
    """Whether the exec store holds the latch key, read through a ``mode=ro`` URI."""
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        return conn.execute("SELECT 1 FROM state WHERE key = ?", (trial_id,)).fetchone() is not None
    finally:
        conn.close()


def _fq_rung_id(lower: int | None, upper: int | None) -> str | None:
    if lower is not None and upper is not None:
        return f"{lower}_{upper}"
    if lower is None and upper is not None:
        return f"lt_{upper}"
    return None  # an open upper rung has no observed key shape: not bridgeable


def _bridge_family(
    fill: DurableFillRecord,
    manifests: Sequence[FamilyManifest],
    trial_key_exists: Callable[[str], bool],
    venue: str,
) -> str | None:
    """Rule (c): grammar -> stored latch key -> exactly one manifest, else ``None``."""
    facts = bucket_facts_from_instrument_id(fill.instrument_id)
    if facts is None:
        return None
    rung_id = _fq_rung_id(facts.lower_f, facts.upper_f)
    if rung_id is None:
        return None
    leg = "no" if symbol_of_instrument_id(fill.instrument_id).endswith("^no") else "yes"
    climate_day = facts.climate_day.isoformat()
    key = fq_trial_id(facts.settlement_station, climate_day, rung_id, leg)
    if not trial_key_exists(key):
        return None
    matching = {
        m.family_id
        for m in manifests
        if m.composition_kind == _FQ_KIND
        and m.venue == venue
        and facts.settlement_station in m.stations
        and m.d0_climate_day <= climate_day
        and (m.terminal_climate_day is None or climate_day <= m.terminal_climate_day)
    }
    return next(iter(matching)) if len(matching) == 1 else None


def backfill_family(
    fill: DurableFillRecord,
    manifests: Sequence[FamilyManifest],
    *,
    epoch_class: EpochClass,
    champion_at: ChampionAt | None,
    trial_key_exists: Callable[[str], bool],
    venue: str,
) -> PreEpochAttribution | Unresolved:
    """The storage key for a PRE_EPOCH fill. Raises ``BackfillRefused`` for a POST_EPOCH one."""
    if epoch_class is not EpochClass.PRE_EPOCH:
        raise BackfillRefused("backfill rules never run on a post-epoch fill")
    by_fold = champion_at(venue, fill.ts_event) if champion_at is not None else None
    by_bridge = _bridge_family(fill, manifests, trial_key_exists, venue)
    if by_fold is not None and by_bridge is not None and by_fold != by_bridge:
        return Unresolved("backfill_disagreement")
    chosen = by_fold if by_fold is not None else by_bridge
    if chosen is None:
        return Unresolved("no_backfill_family")
    return PreEpochAttribution(storage_key=chosen)


class _Evidence(EpochReader, C1Lookup, Protocol):
    """Epoch reader and C1 lookup in one object (the production ``C1Epoch``)."""


def attribute_fill(
    fill: DurableFillRecord,
    evidence: _Evidence,
    manifests: Sequence[FamilyManifest],
    *,
    venue: str,
    trial_key_exists: Callable[[str], bool],
    champion_at: ChampionAt | None = None,
    pair_voided: PairVoided | None = None,
) -> Attribution | PreEpochAttribution | Unresolved:
    """Classify the fill's epoch, then attribute (C1) or backfill (storage key) accordingly."""
    outcome: EpochOutcome = fill_epoch_class(fill, evidence)
    if outcome.epoch_class is None:
        cause = outcome.unresolved_cause
        return Unresolved(cause.value if cause is not None else "epoch_unresolved")
    if outcome.epoch_class is EpochClass.POST_EPOCH:
        return attribute_post_epoch(
            fill, evidence, venue=venue, champion_at=champion_at, pair_voided=pair_voided
        )
    return backfill_family(
        fill,
        manifests,
        epoch_class=EpochClass.PRE_EPOCH,
        champion_at=champion_at,
        trial_key_exists=trial_key_exists,
        venue=venue,
    )


def label_family_set(
    *, non_retired: Iterable[str], unlabelled_attributed: Mapping[str, int]
) -> frozenset[str]:
    """Every non-RETIRED family, plus every family still holding an attributed fill without a final
    label: a retired family keeps its real scorer until its last fill is labelled (P2-6)."""
    return frozenset(non_retired) | frozenset(
        family for family, count in unlabelled_attributed.items() if count > 0
    )


def fill_key_sha(fill: DurableFillRecord) -> str:
    """The journal's stable handle for a fill: sha256 of its durable store key, never an amount."""
    return hashlib.sha256(f"{FILL_KEY_PREFIX}{fill.venue_order_id}".encode()).hexdigest()


@dataclass(frozen=True)
class UnresolvedRow:
    """One unresolved fill as journalled: identity and rule outcomes only, no amounts."""

    fill_key_sha: str
    base_slug: str
    ts_event: int
    epoch_class: str | None
    rule_outcomes: tuple[str, ...]


def unresolved_row_of(
    fill: DurableFillRecord, epoch_class: EpochClass | None, outcomes: Iterable[str]
) -> UnresolvedRow:
    return UnresolvedRow(
        fill_key_sha=fill_key_sha(fill),
        base_slug=base_symbol_of(symbol_of_instrument_id(fill.instrument_id)),
        ts_event=fill.ts_event,
        epoch_class=None if epoch_class is None else epoch_class.value,
        rule_outcomes=tuple(outcomes),
    )


def write_unresolved_journal(
    data_root: Path, rows: Sequence[UnresolvedRow], *, now_ns: int, day: str
) -> Path:
    """Write ``evidence/aut2/unresolved/<day>/<now_ns>_label_run.json`` once (mode 0600)."""
    parts = (*UNRESOLVED_JOURNAL_DIR, day, f"{now_ns}_label_run.json")
    body = {
        "schema": "aut2_unresolved/v1",
        "rows": [
            {
                "fill_key_sha": row.fill_key_sha,
                "base_slug": row.base_slug,
                "ts_event": row.ts_event,
                "epoch_class": row.epoch_class,
                "rule_outcomes": list(row.rule_outcomes),
            }
            for row in rows
        ],
    }
    rootfd = open_root(data_root)
    try:
        os.close(ensure_dir(rootfd, parts[:-1]))
    finally:
        os.close(rootfd)
    path = data_root.joinpath(*parts)
    write_once(path, canonical_json(body), root=data_root, mode=_JOURNAL_FILE_MODE)
    return path
