"""TE-2 Phase A table rows: per-fill, per-station-day and per-cluster S0-H fields (outcome-blind).

Pure transformation of already-read inputs. No settlement value, win or P&L is ever an input.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any

from breezy.analysis.labeling.fill_source import FillRead
from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from scripts.analysis.fq_loss_taxonomy_core import (
    cluster_probability,
    cluster_station_days,
    loc_pi,
    spread_cluster_null,
    spread_fill,
    station_day_probability,
)
from scripts.analysis.fq_loss_taxonomy_logs import UnparseableInstrumentStop, partition_complete
from scripts.analysis.fq_loss_taxonomy_pins import BootPin
from scripts.analysis.fq_loss_taxonomy_reconstruct import FillSpec, ReconstructedFill


def q_f_of(pmf: Mapping[int, float] | None) -> float | None:
    """The T-SPREAD null tail probability of one fill's pmf (it does not depend on the outcome)."""
    return None if not pmf else spread_fill(pmf, max(pmf, key=pmf.__getitem__)).q_f


def fill_rows(
    fills: FillRead, results: Sequence[ReconstructedFill], specs: Sequence[FillSpec],
    pins: Mapping[int, BootPin], label: str, terminal_climate_day: dt.date,
) -> list[dict[str, Any]]:  # fmt: skip
    rows = []
    for fill, res, spec in zip(fills.fills, results, specs, strict=True):
        facts = bucket_facts_from_instrument_id(fill.instrument_id)
        if facts is None:
            raise UnparseableInstrumentStop(f"unparseable instrument id: {fill.instrument_id}")
        pin = pins.get(res.boot_number) if res.boot_number is not None else None
        rows.append(
            {
                "fill_id": spec.fill_id, "instrument_id": fill.instrument_id,
                "station": facts.settlement_station, "climate_day": facts.climate_day,
                "p_hat": spec.p_hat_logged, "p_hat_reconstructed": res.p_hat_reconstructed,
                "delta": res.delta, "match": res.match, "s0d_class": res.s0d_class,
                "s0d_reason": res.reason, "material_k1a": res.material,
                "ask_proxy": spec.ask_proxy, "decision_now_ns": spec.decision_now_ns,
                "cycle_ns": res.cycle_ns, "raw_sha256": res.raw_sha256,
                "cycle_age_s": res.cycle_age_s, "newest_visible": res.newest_visible,
                "lower_f": facts.lower_f, "upper_f": facts.upper_f,
                "open_ended": facts.lower_f is None or facts.upper_f is None,
                "boot": res.boot_number, "pinned_commit": pin.commit if pin else None,
                "pin_state": pin.state if pin else "UNTESTABLE", "pin_label": label,
                "k1b": facts.climate_day > terminal_climate_day, "q_f": q_f_of(res.pmf),
            }
        )  # fmt: skip
    return rows


def day_and_cluster_rows(
    rows: Sequence[dict[str, Any]],
    results: Sequence[ReconstructedFill],
    union: Mapping[tuple[str, dt.date], frozenset[str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_day: dict[tuple[str, dt.date], list[tuple[dict[str, Any], ReconstructedFill]]] = {}
    for row, res in zip(rows, results, strict=True):
        by_day.setdefault((row["station"], row["climate_day"]), []).append((row, res))
    days: dict[tuple[str, dt.date], dict[str, Any]] = {}
    for key in sorted(by_day):
        pairs = sorted(by_day[key], key=lambda pair: pair[0]["decision_now_ns"])
        q_fs = [row["q_f"] for row, _ in pairs]
        earliest_pmf = pairs[0][1].pmf
        rungs = sorted(union.get(key, frozenset()))
        days[key] = {
            "station": key[0], "climate_day": key[1],
            "P_d": station_day_probability([row["p_hat"] for row, _ in pairs]),
            "pi_d": loc_pi(earliest_pmf) if earliest_pmf else None,
            "q_d": None if None in q_fs else spread_cluster_null(q_fs),
            "partition_rungs": rungs, "partition_complete": partition_complete(rungs),
        }  # fmt: skip
    clusters = []
    for cluster in cluster_station_days(sorted(by_day)):
        keys = [(cluster.station, day) for day in cluster.climate_days]
        pis = [days[k]["pi_d"] for k in keys]
        q_fs = [row["q_f"] for k in keys for row, _ in by_day[k]]
        p_d = [days[k]["P_d"] for k in keys]
        clusters.append(
            {
                "station": cluster.station, "climate_days": list(cluster.climate_days),
                "P_d": p_d, "P_c": cluster_probability(p_d),
                "q_c": None if None in q_fs else spread_cluster_null(q_fs),
                "pi_min": None if None in pis else min(pis),
                "pi_max": None if None in pis else max(pis),
            }
        )  # fmt: skip
    return list(days.values()), clusters


def vector_table(results: Sequence[ReconstructedFill]) -> list[dict[str, Any]]:
    """One row per (cycle, station): the reconstructed vector and its bulletin ``raw_sha256``."""
    table: dict[tuple[int, str], dict[str, Any]] = {}
    for r in results:
        facts = bucket_facts_from_instrument_id(r.instrument_id)
        if r.cycle_ns is None or r.vector is None or facts is None:
            continue
        table[(r.cycle_ns, facts.settlement_station)] = {
            "cycle_ns": r.cycle_ns, "station": facts.settlement_station,
            "raw_sha256": r.raw_sha256, **r.vector,
        }  # fmt: skip
    return [table[key] for key in sorted(table)]
