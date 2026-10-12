"""TE-2 S0-D: rebuild each fill's p-hat from the pinned commit, a derived NBP store and the node
log's cycle visibility (I/O). Plan: TE-2_plan_r3_2.md section 4, S0-D.

The rebuild follows ``decision.evaluate`` (decision.py:221-241): the manifest and artefact are read
from the PINNED commit through the git port, ``load_live_calibration`` verifies the artefact sha, a
fresh ``QuantileLadderLatch`` and the shipped ``LadderEvConfig`` feed ``evaluate`` with the
production ``ArtefactBoundsProvider``. The vector comes from ``ForecastQuantileState.push`` /
``value_at`` (the quantile class, not the TXN one) after the actor's D+1 nearest-window filter.

Pinned semantics: between the pinned boots and HEAD the vector-path files differ only by 4ac87414,
a behaviour-preserving relocation (identical bodies), so the HEAD modules are used
(``SEMANTICS_NOTE``). A rung's probability is a cdf difference, independent of the other rungs, so
a complement ladder around the bought rung gives the same p-hat as the full partition.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Container, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, NamedTuple

from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from breezy.registry.sites import default_registry
from scripts.analysis.fq_loss_taxonomy_classify import (
    S0D_MIN_MATCH,
    S0D_TOLERANCE,
    GateResult,
    S0DMiss,
    classify_s0d_miss,
    reproduction_gate,
)
from scripts.analysis.fq_loss_taxonomy_pins import Boot, BootPin, GitPort
from scripts.analysis.fq_loss_taxonomy_verdict import is_material_k1a

if TYPE_CHECKING:
    # Type-only: the runtime imports of the strategy/persistence stacks (scipy, pandas, nautilus)
    # are deferred into the functions that need them to keep this entry module's import cheap.
    from breezy.persistence.nbp_derived_store import DerivedNbpRow
    from breezy.strategy.forecast_quantile_ladder.artefact_bounds import ArtefactBoundsProvider
    from breezy.strategy.ladder_ev.forecast_state import (
        ForecastQuantileState,
        ForecastQuantileVector,
    )
    from breezy.strategy.ladder_ev.quantile_density import Percentiles, Rung

#: A cycle published this soon AFTER a decision may already have been visible to the live node
#: (the log line follows the bus push), so the cycle in use cannot be decided.
CYCLE_AMBIGUITY_NS: Final = 5 * 10**9
PMF_HALF_WIDTH: Final = 30
VENUE: Final = "polymarket_us"
SEMANTICS_NOTE: Final = (
    "HEAD semantics: 4ac87414 only relocated local_standard_date and NBP_QUANTILE_MODEL "
    "(identical bodies); nbm_quantile_actor.py has no diff between the pinned boots and HEAD"
)
_NS: Final = 10**9
_QUANTILE_KEYS: Final = ("q10", "q25", "q50", "q75", "q90", "mean", "sd")


class S0DStop(Exception):
    """Fewer than 23 of 25 reconstructed p-hat values match the logged value."""


@dataclass(frozen=True)
class FillSpec:
    fill_id: str
    instrument_id: str
    p_hat_logged: float
    decision_now_ns: int
    ask_proxy: float


@dataclass(frozen=True)
class ReconstructedFill:
    fill_id: str
    instrument_id: str
    boot_number: int | None
    commit: str | None
    p_hat_logged: float
    p_hat_reconstructed: float | None
    delta: float | None
    match: bool
    s0d_class: S0DMiss | None
    reason: str | None
    material: bool | None
    cycle_ns: int | None
    raw_sha256: str | None
    cycle_age_s: float | None
    newest_visible: bool | None
    vector: Mapping[str, float] | None
    pmf: Mapping[int, float] | None


@dataclass(frozen=True)
class PinnedModel:
    commit: str
    calibration: Any
    bounds: ArtefactBoundsProvider
    fee_coefficient: float


def load_derived_cycles(
    root: Path, published: Container[int] | None = None
) -> dict[int, tuple[DerivedNbpRow, ...]]:
    """The ``nbp_*.parquet`` rows the ``nbp_backfill.py`` derived store holds, by cycle (read-only).

    With ``published`` only those cycles are kept (the reconstruction never looks at another one),
    so the rest of the store is not held in memory.
    """
    from breezy.persistence.nbp_derived_store import read_partition

    grouped: dict[int, list[DerivedNbpRow]] = {}
    for path in sorted(root.rglob("nbp_*.parquet")):
        for row in read_partition(path):
            if published is None or row.cycle_runtime_ns in published:
                grouped.setdefault(row.cycle_runtime_ns, []).append(row)
    return {cycle: tuple(rows) for cycle, rows in grouped.items()}


def load_pinned_model(git: GitPort, commit: str, manifest_path: str, workdir: Path) -> PinnedModel:
    """Manifest and artefact AT ``commit`` (via ``git show``); the artefact sha is verified."""
    from breezy.strategy.forecast_quantile_ladder.artefact_bounds import ArtefactBoundsProvider
    from breezy.strategy.forecast_quantile_ladder.calibration_artefact import load_live_calibration

    manifest = json.loads(git.show_blob(commit, manifest_path))
    target = workdir / commit / "artefact.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(git.show_blob(commit, manifest["density_artefact_path"]))
    calibration = load_live_calibration(
        str(target), expected_sha256=manifest["density_artefact_sha256"]
    )
    bounds = ArtefactBoundsProvider(cdf_method=calibration.cdf_method)
    return PinnedModel(commit, calibration, bounds, float(manifest["taker_fee_coefficient"]))


def _nearest(rows: Sequence[DerivedNbpRow]) -> list[DerivedNbpRow]:
    """The actor's D+1 filter: the earliest valid window per (station, variable)."""
    nearest: dict[tuple[str, str], DerivedNbpRow] = {}
    for row in rows:
        key = (row.station, row.variable)
        if key not in nearest or row.valid_start_ns < nearest[key].valid_start_ns:
            nearest[key] = row
    return list(nearest.values())


def _percentiles(vector: ForecastQuantileVector) -> Percentiles:
    from breezy.strategy.ladder_ev.quantile_density import Percentiles

    return Percentiles(
        q10=vector.q10, q25=vector.q25, q50=vector.q50, q75=vector.q75, q90=vector.q90,
        mean=vector.mean, sd=vector.sd,
    )  # fmt: skip


def _complement_ladder(lower: int | None, upper: int | None) -> list[Rung]:
    from breezy.strategy.ladder_ev.quantile_density import Rung

    ladder = [Rung("target", lower, upper)]
    if lower is not None:
        ladder.append(Rung("below", None, lower - 1))
    if upper is not None:
        ladder.append(Rung("above", upper + 1, None))
    return ladder


class _CycleFacts(NamedTuple):
    selected: ForecastQuantileVector | None
    newest_cycle: int | None
    available: bool
    reissued: bool
    unambiguous: bool


class Reconstructor:
    """Rebuilds p-hat per fill. ``cycles`` is the derived store, ``published`` the node log's
    ``cycle_ns -> visible_ns`` (a cycle absent from the log was never visible to the node)."""

    def __init__(
        self,
        git: GitPort,
        *,
        manifest_path: str,
        workdir: Path,
        cycles: Mapping[int, Sequence[DerivedNbpRow]],
        published: Mapping[int, int],
    ) -> None:
        self._git, self._manifest_path, self._workdir = git, manifest_path, workdir
        self._cycles, self._published = cycles, published
        self._models: dict[str, PinnedModel] = {}
        self._states: dict[str, ForecastQuantileState] = {}

    def _model(self, commit: str) -> PinnedModel:
        if commit not in self._models:
            self._models[commit] = load_pinned_model(
                self._git, commit, self._manifest_path, self._workdir
            )
        return self._models[commit]

    def _icao_rows(self, icao: str, cycle_ns: int) -> list[DerivedNbpRow]:
        return [r for r in self._cycles.get(cycle_ns, ()) if r.station == icao]

    def _state(self, icao: str, offset: float) -> ForecastQuantileState:
        if icao not in self._states:
            from breezy.normalize.climate_day import local_standard_date
            from breezy.strategy.ladder_ev.forecast_state import (
                NBP_QUANTILE_VARIABLES,
                ForecastQuantileState,
            )

            state = ForecastQuantileState()
            for cycle_ns, visible_ns in sorted(self._published.items()):
                for row in _nearest(self._icao_rows(icao, cycle_ns)):
                    if row.variable not in NBP_QUANTILE_VARIABLES:
                        continue
                    state.push(
                        variable=row.variable,
                        value_f=row.value_f,
                        available_at_ns=visible_ns,
                        cycle_runtime_ns=cycle_ns,
                        climate_day=local_standard_date(row.valid_end_ns, offset),
                        model_version=row.nbm_version_era,
                    )
            self._states[icao] = state
        return self._states[icao]

    def _cycle_facts(self, icao: str, offset: float, now_ns: int) -> _CycleFacts:
        """The cycle in use at ``now_ns`` and whether it can be trusted."""
        visible = {c: v for c, v in self._published.items() if v <= now_ns}
        newest = max(visible, key=lambda c: (visible[c], c), default=None)
        selected = self._state(icao, offset).value_at(now_ns)
        available = selected is not None and selected.cycle_runtime_ns == newest
        reissued = False
        if available and selected is not None:
            rows = self._icao_rows(icao, selected.cycle_runtime_ns)
            reissued = (
                max(r.available_at_ns for r in rows) > self._published[selected.cycle_runtime_ns]
            )
        unambiguous = not any(
            now_ns < v <= now_ns + CYCLE_AMBIGUITY_NS and self._icao_rows(icao, c)
            for c, v in self._published.items()
        )
        return _CycleFacts(selected, newest, available, reissued, unambiguous)

    def _p_hat(
        self,
        model: PinnedModel,
        spec: FillSpec,
        vector: ForecastQuantileVector,
        site: tuple[float, float],
    ) -> tuple[float | None, str | None, bool]:
        """``(p_hat, refusal_reason, take_reproduced)`` through the production ``evaluate``."""
        from breezy.strategy.forecast_quantile_ladder.decision import (
            Refuse,
            SidedAsk,
            Take,
            evaluate,
        )
        from breezy.strategy.forecast_quantile_ladder.latch import QuantileLadderLatch
        from breezy.strategy.forecast_quantile_ladder.margin import hours_to_settlement
        from breezy.strategy.ladder_ev.config import LadderEvConfig

        facts = bucket_facts_from_instrument_id(spec.instrument_id)
        assert facts is not None
        offset, latitude = site
        cfg = LadderEvConfig()
        decision = evaluate(
            now_ns=spec.decision_now_ns, std_utc_offset_hours=offset, permit_covers=True,
            vector=vector, station=facts.settlement_station, climate_day=facts.climate_day,
            ladder=_complement_ladder(facts.lower_f, facts.upper_f), rung_id="target", side="yes",
            ask=SidedAsk(side="yes", instrument_id=spec.instrument_id, price=spec.ask_proxy),
            fee_coefficient=model.fee_coefficient, slippage_floor_prob=cfg.slippage_floor_prob,
            h_hours=hours_to_settlement(
                now_ns=spec.decision_now_ns, climate_day=facts.climate_day,
                std_utc_offset_hours=offset,
            ),
            cfg=cfg, calibration=model.calibration, latitude_deg=latitude,
            bounds_provider=model.bounds, latch=QuantileLadderLatch(),
        )  # fmt: skip
        if isinstance(decision, Take):
            return decision.p_hat, None, True
        reason = getattr(decision, "reason", type(decision).__name__)
        if not isinstance(decision, Refuse) or reason not in ("below_margin", "not_executable"):
            return None, reason, False
        # The ask proxy priced the rung out of a Take; p-hat itself is ask-independent.
        resolved = model.calibration.resolve(
            vector.model_version, latitude_deg=latitude, climate_day=facts.climate_day
        )
        bounds = model.bounds(
            percentiles=_percentiles(vector), draws=resolved.draws,
            ladder=_complement_ladder(facts.lower_f, facts.upper_f), rung_id="target",
        )  # fmt: skip
        return bounds.p_hat, None, False

    def _pmf(
        self, model: PinnedModel, vector: ForecastQuantileVector, latitude: float
    ) -> dict[int, float] | None:
        """The model's own integer-degF pmf for this vector (same draws, mean over draws)."""
        from breezy.strategy.ladder_ev.quantile_density import Rung, rung_probability_interval

        try:
            resolved = model.calibration.resolve(
                vector.model_version, latitude_deg=latitude, climate_day=vector.climate_day
            )
        except Exception:  # noqa: BLE001 - an unknown era is a recorded gap, not a crash
            return None
        centre = round(vector.q50)
        degrees = list(range(centre - PMF_HALF_WIDTH, centre + PMF_HALF_WIDTH + 1))
        ladder = [
            Rung("lt", None, degrees[0] - 1),
            *[Rung(str(t), t, t) for t in degrees],
            Rung("gte", degrees[-1] + 1, None),
        ]
        interval = rung_probability_interval(
            _percentiles(vector), model.calibration.cdf_method, resolved.draws, ladder
        )
        return {t: interval[str(t)][0] for t in degrees}

    def reconstruct(self, spec: FillSpec, commit: str) -> ReconstructedFill:
        facts = bucket_facts_from_instrument_id(spec.instrument_id)
        if facts is None:
            raise ValueError(f"unparseable instrument id: {spec.instrument_id}")
        registry, city = default_registry(), facts.settlement_station
        offset = registry.climate_day_window(VENUE, city).std_utc_offset_hours
        latitude = registry.enrichment_coordinates(VENUE, city).lat
        icao = registry.settlement_site(VENUE, city).icao
        facts_at = self._cycle_facts(icao, offset, spec.decision_now_ns)
        selected, available = facts_at.selected, facts_at.available
        reissued, unambiguous = facts_at.reissued, facts_at.unambiguous
        base = ReconstructedFill(
            spec.fill_id, spec.instrument_id, None, commit, spec.p_hat_logged, None, None, False,
            None, None, None, None, None, None, None, None, None,
        )  # fmt: skip
        p_hat: float | None = None
        reason: str | None = "bulletin_unavailable"
        reproduced = False
        if available and selected is not None:
            p_hat, reason, reproduced = self._p_hat(
                self._model(commit), spec, selected, (offset, latitude)
            )
        delta = None if p_hat is None else p_hat - spec.p_hat_logged
        match = delta is not None and abs(delta) <= S0D_TOLERANCE
        miss = None
        material = None
        if not match:
            miss = classify_s0d_miss(
                bulletin_available=available, bulletin_reissued=reissued,
                cycle_selection_matches=unambiguous, delta_survives_root_cause=True,
            )  # fmt: skip
            reason = "bulletin_reissued" if reissued else reason
            if miss == S0DMiss.K1A:
                material = True if delta is None else is_material_k1a(delta, not reproduced)
        if selected is None or not available:
            return dataclasses.replace(
                base, p_hat_reconstructed=None, s0d_class=miss, reason=reason
            )
        vector = {key: getattr(selected, key) for key in _QUANTILE_KEYS}
        rows = self._icao_rows(icao, selected.cycle_runtime_ns)
        return dataclasses.replace(
            base, p_hat_reconstructed=p_hat, delta=delta, match=match, s0d_class=miss,
            reason=None if match else reason, material=material, cycle_ns=selected.cycle_runtime_ns,
            raw_sha256=rows[0].raw_sha256 if rows else None,
            cycle_age_s=(spec.decision_now_ns - selected.cycle_runtime_ns) / _NS,
            newest_visible=selected.cycle_runtime_ns == facts_at.newest_cycle,
            vector=vector, pmf=self._pmf(self._model(commit), selected, latitude),
        )  # fmt: skip

    def reproduces_under(
        self, specs_by_boot: Mapping[int, Sequence[FillSpec]]
    ) -> Callable[[int, str], bool]:
        """The near-boundary callback: every fill of the boot reproduces under ``commit``."""

        def check(boot_number: int, commit: str) -> bool:
            return all(
                self.reconstruct(s, commit).match for s in specs_by_boot.get(boot_number, ())
            )

        return check


def boot_for(boots: Sequence[Boot], now_ns: int) -> int | None:
    """The boot in force at ``now_ns``: the last one whose boot time is at or before it."""
    eligible = [b for b in boots if int(b.boot_time.timestamp()) * _NS <= now_ns]
    return max(eligible, key=lambda b: b.boot_time).number if eligible else None


def _untestable(
    spec: FillSpec, boot: int | None, pin: BootPin | None, reason: str
) -> ReconstructedFill:
    return ReconstructedFill(
        spec.fill_id, spec.instrument_id, boot, pin.commit if pin else None, spec.p_hat_logged,
        None, None, False, S0DMiss.UNTESTABLE, reason, None, None, None, None, None, None, None,
    )  # fmt: skip


def reconstruct_all(
    reconstructor: Reconstructor,
    specs: Sequence[FillSpec],
    boots: Sequence[Boot],
    pins: Sequence[BootPin],
) -> tuple[ReconstructedFill, ...]:
    """One result per spec, at its boot's pinned commit; an unpinned boot is UNTESTABLE."""
    pin_by_boot = {p.boot_number: p for p in pins}
    results = []
    for spec in specs:
        number = boot_for(boots, spec.decision_now_ns)
        pin = pin_by_boot.get(number) if number is not None else None
        if pin is None or pin.state != "PINNED" or pin.commit is None:
            why = "no_boot" if pin is None else (pin.reason.value if pin.reason else "unpinned")
            results.append(_untestable(spec, number, pin, why))
            continue
        results.append(
            dataclasses.replace(reconstructor.reconstruct(spec, pin.commit), boot_number=number)
        )
    return tuple(results)


def s0d_gate(results: Sequence[ReconstructedFill]) -> GateResult:
    """STOP (``S0DStop``) below 23 matches; UNTESTABLE counts as a non-match."""
    gate = reproduction_gate([r.match for r in results], minimum=S0D_MIN_MATCH)
    if not gate.passed:
        misses = [r.fill_id for r in results if not r.match]
        raise S0DStop(
            f"S0-D: {gate.n_match}/{gate.n_total} p-hat match (< {S0D_MIN_MATCH}): {misses}"
        )
    return gate
