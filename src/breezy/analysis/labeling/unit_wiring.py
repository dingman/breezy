"""Production wiring of the label run (TE-1 WP-A): the planner, the lag clock and the host seams.

``label_run``'s default mode needs a planner, a settlement source, a delivery binding, a deadline
and a lag clock that only the promoted unit can supply. This module builds them from the pieces
that already exist and adds no attribution rule:

* the planner reuses :func:`attribute_fill` (epoch class, C1, the pre-epoch bridge and the R11
  straddle) and :func:`legacy_join` for the retired CRH families;
* the settlement source is the per-station NWS CLI FINAL (:func:`settlement_source_for`);
* delivery is the AUT-6 ``deliver_with_proof`` binding;
* the lag clock is the plain ``verdicts.lag_start_ns`` raised to the unit's first activation for a
  fill that predates it (R4), so a backlog of pre-activation fills does not read as lag.

``producer_pin_state`` mirrors ``autonomy_health_cli.producer_pin_state``: the default factory
refuses while ``aut2.label`` is not pinned to the closure of ``label_run``.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
from breezy.analysis.labeling.attribution import (
    AttributionEvidence,
    BridgeBasis,
    PreEpochAttribution,
    Unresolved,
    attribute_fill,
    label_family_of,
    latch_key_exists,
    unresolved_row_of,
)
from breezy.analysis.labeling.constants import LABEL_MEMORY_CEILING_GIB
from breezy.analysis.labeling.delivery import Deliver
from breezy.analysis.labeling.delivery import DeliveryProof as LabelDeliveryProof
from breezy.analysis.labeling.fq_scorer import FqFillInput
from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from breezy.analysis.labeling.label_core import FamilyInfo, InputPlan, Planner
from breezy.analysis.labeling.legacy_crh_scorer import LegacyFillInput
from breezy.analysis.labeling.legacy_join import legacy_join
from breezy.analysis.labeling.settlement_source import (
    RefusingSettlementSource,
    SettlementSource,
    settlement_source_for,
)
from breezy.analysis.labeling.verdicts import lag_start_ns as plain_lag_start_ns
from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.persistence.autonomy import pins
from breezy.persistence.autonomy.closure import ClosureUnavailable, closure_sha256
from breezy.persistence.autonomy.label_store import LabelRow, oldest_marker_ns
from breezy.persistence.catalog import station_catalog_path
from breezy.persistence.family_manifest import FamilyManifest
from breezy.registry.health_model import AlertPayload
from breezy.registry.settlement_clock import settlement_deadline_ns
from breezy.registry.sites import default_registry
from breezy.runtime.alert_outbox import AlertOutbox, DeliveryRecordWriter
from breezy.runtime.alert_proof import deliver_with_proof
from breezy.settlement.trial_scorer import ScoredTrial

__all__ = [
    "ENTRY_MODULE",
    "PRODUCER_ID",
    "HostSeamsRefused",
    "LagRule",
    "ProducerUnpinned",
    "StationCatalogSettlements",
    "activation_ns",
    "build_planner",
    "family_infos",
    "fill_deadline_ns",
    "make_deliver",
    "producer_pin_state",
    "row_deadline_ns",
    "unit_memory_max_bytes",
]

PRODUCER_ID: Final = "aut2.label"
ENTRY_MODULE: Final = "breezy.analysis.labeling.label_run"
_UNPINNED_PLACEHOLDER: Final = "0" * 64
_FQ_KIND: Final = "forecast_quantile_ladder"
_NO_BACKFILL: Final = "no_backfill_family"
_DOUBLE_CLAIM: Final = "legacy_trial_double_claim"
_RETIRED: Final = "RETIRED"
_DELIVERY_WRITER: Final = "aut2_label"
_DELIVERY_DETAIL: Final = "label_run"
_GIB: Final = 1024**3


class HostSeamsRefused(Exception):
    """The production host seams (live paths, locks, alerts) are read only inside the label unit."""


class ProducerUnpinned(Exception):
    """``aut2.label`` has no matching ``PRODUCER_SOURCE_SHA256`` pin: the default mode refuses."""


def producer_pin_state() -> tuple[bool, str]:
    """``(pinned, code_sha)``: the closure hash of ``label_run`` and whether the pin names it."""
    try:
        code_sha = closure_sha256(ENTRY_MODULE)
    except ClosureUnavailable:
        return False, _UNPINNED_PLACEHOLDER
    return pins.PRODUCER_SOURCE_SHA256.get(PRODUCER_ID) == code_sha, code_sha


# -- deadlines and the lag clock -----------------------------------------------------------------


def _deadline_ns(venue: str, station: str, climate_day: dt.date) -> int:
    deadline = default_registry().settlement_deadline(venue, station)
    return settlement_deadline_ns(deadline, climate_day)


def fill_deadline_ns(venue: str) -> Callable[[DurableFillRecord], int]:
    """The venue's settlement instant for a fill's climate day (P22)."""

    def deadline(fill: DurableFillRecord) -> int:
        facts = bucket_facts_from_instrument_id(fill.instrument_id)
        if facts is None:
            raise ValueError("a fill's instrument id is not a weather rung")
        return _deadline_ns(venue, facts.settlement_station, facts.climate_day)

    return deadline


def row_deadline_ns(venue: str) -> Callable[[LabelRow], int]:
    """The venue's settlement instant for a label row's climate day."""

    def deadline(row: LabelRow) -> int:
        return _deadline_ns(venue, row.station, dt.date.fromisoformat(row.climate_day))

    return deadline


def activation_ns(data_root: Path, now_ns: int) -> int:
    """The unit's first activation: its oldest run marker under the LIVE root, else this run.

    A ``--measure-peak`` run writes its markers under its own output root, never here, so it can
    neither start nor move this anchor. Once a marker exists the anchor only ever moves BACK (an
    older marker), never forward. Before the first marker every run anchors at its own clock: a run
    that writes no marker leaves the next one its own ``now`` (a later start: lenient toward pass,
    can only hide lag).
    """
    oldest = oldest_marker_ns(data_root)
    return now_ns if oldest is None else oldest


@dataclass(frozen=True)
class LagRule:
    """The R4 label-lag start of a fill.

    The plain rule is ``min(first settlement record, settlement deadline)``. A fill that predates
    ``activation_ns`` could not have been labelled before the unit existed, so its clock starts at
    ``max(plain rule, activation_ns)``; a later fill keeps the plain rule.

    ``first_record_ns`` is ``None`` by design: the unit reads no per-fill settlement-record time, so
    the plain rule is the settlement deadline alone (``min(None, deadline)``): a deadline-only
    start, never earlier than the true first record: lenient toward pass (can only hide lag).
    """

    activation_ns: int
    deadline_of: Callable[[DurableFillRecord], int]
    first_record_ns: Callable[[DurableFillRecord], int | None] = lambda fill: None

    def rule(self, fill: DurableFillRecord) -> int:
        return plain_lag_start_ns(self.first_record_ns(fill), self.deadline_of(fill))

    def is_raised(self, fill: DurableFillRecord) -> bool:
        return fill.ts_event < self.activation_ns and self.rule(fill) < self.activation_ns

    def __call__(self, fill: DurableFillRecord) -> int:
        start = self.rule(fill)
        return max(start, self.activation_ns) if fill.ts_event < self.activation_ns else start


# -- families and the planner --------------------------------------------------------------------


def family_infos(manifests: Sequence[FamilyManifest]) -> tuple[FamilyInfo, ...]:
    """The registered families: the committed bootstrap seed, each with its manifest's kind."""
    by_id = {m.family_id: m for m in manifests}
    infos: list[FamilyInfo] = []
    for family_id, status in pins.BOOTSTRAP_SEED:
        manifest = by_id.get(family_id)
        if manifest is None:
            raise ValueError(f"bootstrap family {family_id} has no manifest")
        infos.append(FamilyInfo(family_id, manifest.composition_kind, retired=status == _RETIRED))
    return tuple(infos)


@dataclass(frozen=True)
class _Classified:
    """What the planner decided for one fill: a planned input, or why it cannot be planned."""

    kind: str | None = None
    fill_input: FqFillInput | LegacyFillInput | None = None
    reason: str | None = None
    straddle: bool = False


def build_planner(
    *,
    exec_db: Path,
    venue: str,
    manifests: Sequence[FamilyManifest],
    families: Sequence[FamilyInfo],
    evidence: AttributionEvidence,
    scored_trials: Mapping[str, ScoredTrial],
    release_ns: Callable[[DurableFillRecord], int],
    lag_rule: LagRule,
    trial_key_exists: Callable[[str], bool] | None = None,
) -> Planner:
    """The label run's planner over the durable fills.

    ``trial_key_exists`` defaults to the production ``latch_key_exists`` against ``exec_db``.
    Prints ``AUT2 PRE_EPOCH_BRIDGE basis=bridge_post_terminal n=<k>`` and ``AUT2 LAG_BACKLOG
    n=<k>`` once per run.
    """
    exists = trial_key_exists or (lambda key: latch_key_exists(exec_db, key))
    kind_of = {m.family_id: m.composition_kind for m in manifests}
    lag_kinds = frozenset(f.kind for f in families if not f.retired)

    def _classify(fill: DurableFillRecord) -> _Classified:
        outcome = attribute_fill(fill, evidence, manifests, venue=venue, trial_key_exists=exists)
        if isinstance(outcome, Unresolved) and outcome.reason == _NO_BACKFILL:
            joined = legacy_join(
                fill, manifests, exec_db=exec_db, venue=venue, scored_by_trial_id=scored_trials
            )
            if joined is not None:
                return _Classified(kind=joined.kind, fill_input=joined.fill_input)
        if isinstance(outcome, Unresolved):
            return _Classified(reason=outcome.reason)
        if kind_of.get(label_family_of(outcome)) != _FQ_KIND:
            return _Classified(reason="family_kind_not_fq")
        straddle = (
            isinstance(outcome, PreEpochAttribution)
            and outcome.basis is BridgeBasis.BRIDGE_POST_TERMINAL
        )
        fq_input = FqFillInput(
            fill=fill, attribution=outcome, scheduled_release_at_ns=release_ns(fill)
        )
        return _Classified(kind=_FQ_KIND, fill_input=fq_input, straddle=straddle)

    def plan(fills: Sequence[DurableFillRecord]) -> InputPlan:
        inputs: dict[str, list[FqFillInput | LegacyFillInput]] = {}
        fill_kinds: dict[str, str] = {}
        unresolved = []
        unresolved_keys: set[str] = set()
        consumed: set[str] = set()  # legacy trial ids already claimed by a fill of this run
        straddle = 0
        for fill in fills:
            result = _classify(fill)
            planned = result.fill_input
            reason = result.reason
            if isinstance(planned, LegacyFillInput):
                if planned.trial_id in consumed:
                    # one legacy trial is ONE fill's P&L: a second claimant would count twice
                    reason = _DOUBLE_CLAIM
                else:
                    consumed.add(planned.trial_id)
            if reason is not None or planned is None or result.kind is None:
                unresolved.append(unresolved_row_of(fill, None, (reason or _NO_BACKFILL,)))
                unresolved_keys.add(fill.venue_order_id)
                continue
            straddle += result.straddle
            inputs.setdefault(result.kind, []).append(planned)
            fill_kinds[fill.client_order_id] = result.kind
        backlog = sum(
            1
            for f in fills
            if fill_kinds.get(f.client_order_id) in lag_kinds and lag_rule.is_raised(f)
        )
        print(f"AUT2 PRE_EPOCH_BRIDGE basis={BridgeBasis.BRIDGE_POST_TERMINAL.value} n={straddle}")
        print(f"AUT2 LAG_BACKLOG n={backlog}")
        return InputPlan(
            inputs_by_kind={kind: tuple(rows) for kind, rows in inputs.items()},
            fill_kinds=fill_kinds,
            unresolved=tuple(unresolved),
            unresolved_fill_keys=frozenset(unresolved_keys),
        )

    return plan


# -- seams ---------------------------------------------------------------------------------------


class StationCatalogSettlements:
    """The per-station settlement source of the default wiring.

    ``polymarket_us`` reads the NWS CLI FINAL from the station's catalog; a station whose catalog
    directory does not exist yet has no record (the row stays pending, nothing is created). A venue
    with no reader (Kalshi, unknown) fails closed through :class:`RefusingSettlementSource`.
    """

    def __init__(
        self, catalog_base: Path, venue: str, open_catalog: Callable[[Path, str, str], Any]
    ) -> None:
        self._base = catalog_base
        self._venue = venue
        self._open_catalog = open_catalog
        self._sources: dict[str, SettlementSource] = {}

    def source_for(self, station: str) -> SettlementSource:
        source = self._sources.get(station)
        if source is None:
            catalog = self._open_catalog(self._base, self._venue, station)
            source = self._sources[station] = settlement_source_for(self._venue, catalog)
        return source

    def record(self, station: str, climate_day: dt.date) -> NwsClimateDay | None:
        probe = settlement_source_for(self._venue, None)
        if isinstance(probe, RefusingSettlementSource):
            return probe.record(station, climate_day)  # raises SettlementSourceRefused
        if not station_catalog_path(self._base, self._venue, station).is_dir():
            return None
        return self.source_for(station).record(station, climate_day)


def make_deliver(sink: object, alerts_root: Path) -> Deliver:
    """The label run's delivery seam: AUT-6 ``deliver_with_proof`` (outbox entry first)."""

    def deliver(payload: Mapping[str, Any]) -> LabelDeliveryProof:
        alert = AlertPayload(
            severity=str(payload["severity"]),
            event=str(payload["event"]),
            site=str(payload["subject"]),
            detail=_DELIVERY_DETAIL,
        )
        proof = deliver_with_proof(
            sink,
            alert,
            writer=_DELIVERY_WRITER,
            records=DeliveryRecordWriter(alerts_root),
            attempt_kind="alert",
            outbox=AlertOutbox(alerts_root),
        )
        return LabelDeliveryProof(delivered=proof.delivered, status_class=proof.status_class)

    return deliver


def unit_memory_max_bytes(proc_cgroup_text: str, cgroup_root: Path) -> int:
    """The unit's effective ``MemoryMax``; unlimited, unreadable or absent counts as above the cap.

    ``label_slot_held`` holds every unit above 4 GiB until AUT-6's memory verdict is a PASS, so an
    unbounded unit fails closed.
    """
    unbounded = (LABEL_MEMORY_CEILING_GIB + 1) * _GIB
    path = ""
    for line in proc_cgroup_text.splitlines():
        if line.startswith("0::"):
            path = line[3:].strip()
    if not path:
        return unbounded
    try:
        text = (cgroup_root / path.lstrip("/") / "memory.max").read_text(encoding="utf-8").strip()
    except OSError:
        return unbounded
    return int(text) if text.isascii() and text.isdigit() else unbounded
