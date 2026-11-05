"""TE-2 WP1c: Phase B report pieces: ranked classes, consumers, routes, JSON and Markdown (pure
except ``write_json``). Plan sections 3, 7 and 10."""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from scripts.analysis.fq_loss_taxonomy_classify import FillClass
from scripts.analysis.fq_loss_taxonomy_fills import FillRecord
from scripts.analysis.fq_loss_taxonomy_predecl import PredeclarationError

#: finding keys for the NOT-TESTABLE / CONDITIONAL / UNTESTABLE consumer row.
UNTESTABLE_KEY: Final = "NOT_TESTABLE_OR_CONDITIONAL"
_CLASS_FINDINGS: Final = frozenset(
    {"SIBLING_WON", "BOUNDARY", "TAIL", "BAND_SELECTION", "BODY_MISS"}
)
_FLAG_FINDINGS: Final = ("K1a", "K1b", "K2", "K3", "K4")
SLIP_TEXT: Final = (
    "the result artefact is later than the soft delivery target; cite TE-2 as 'pending' in "
    "dependent reports (plan section 7)"
)


def fields_dict(obj: Any) -> Any:
    """Explicit field-by-field JSON mapping (recursive); replaces ``dataclasses.asdict``."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: fields_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, (list, tuple)):
        return [fields_dict(v) for v in obj]
    if isinstance(obj, dict):
        return {k: fields_dict(v) for k, v in obj.items()}
    return obj


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def fill_json(rec: FillRecord) -> dict[str, Any]:
    row = rec.row
    return {
        "fill_id": rec.fill_id, "instrument_id": rec.instrument_id, "station": rec.station,
        "climate_day": rec.climate_day, "tmax_f": rec.tmax_f, "won": rec.won,
        "pnl": str(rec.pnl), "class": str(rec.cls), "flags": list(rec.flags),
        "p_hat": rec.p_hat, "ask_proxy": rec.ask_proxy, "edge_dist_f": rec.edge_dist,
        "pit": rec.pit, "z": rec.z, "corrected_median_f": rec.corr_median,
        "raw_q50": rec.raw_q50, "corrected_error_f": rec.corr_err, "raw_error_f": rec.raw_err,
        "correction_f": None if rec.corr_median is None or rec.raw_q50 is None
        else rec.corr_median - rec.raw_q50,
        "cycle_age_s": row.get("cycle_age_s"), "newest_visible": row.get("newest_visible"),
        "boot": row.get("boot"), "pinned_commit": row.get("pinned_commit"),
        "pin_state": row.get("pin_state"), "pin_label": row.get("pin_label"),
        "rungs_same_day": rec.rungs_same_day, "partition_incomplete": not rec.partition_complete,
        "station_day_has_win": rec.day_has_win,
    }  # fmt: skip


def class_counts(records: Sequence[FillRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for rec in records:
        counts[str(rec.cls)] = counts.get(str(rec.cls), 0) + 1
    return counts


def flag_counts(records: Sequence[FillRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for rec in records:
        for flag in rec.flags:
            counts[flag] = counts.get(flag, 0) + 1
    return counts


def ranked_classes(records: Sequence[FillRecord]) -> list[dict[str, Any]]:
    """Loss classes ranked by their share of the dollar loss (a mixed result is a ranked list)."""
    losers = [r for r in records if not r.won]
    total = sum((-r.pnl for r in losers), Decimal(0))
    ranked: dict[str, tuple[int, Decimal]] = {}
    for rec in losers:
        count, loss = ranked.get(str(rec.cls), (0, Decimal(0)))
        ranked[str(rec.cls)] = (count + 1, loss - rec.pnl)
    rows = [
        {
            "class": name, "count": count, "loss": str(loss),
            "share_of_loss": float(loss / total) if total else 0.0,
        }
        for name, (count, loss) in ranked.items()
    ]  # fmt: skip
    return sorted(rows, key=lambda r: (-r["share_of_loss"], r["class"]))


def consumers(
    label: str,
    records: Sequence[FillRecord],
    statuses: Iterable[str],
    consumer_map: Mapping[str, str],
) -> list[dict[str, str]]:
    """Each finding present in this run, mapped to exactly one predeclared consumer."""
    present = [label]
    present += sorted(c for c in {str(r.cls) for r in records} if c in _CLASS_FINDINGS)
    present += [f for f in _FLAG_FINDINGS if any(f in r.flags for r in records)]
    weak = any(s != "TESTABLE" for s in statuses)
    if weak or any(r.cls is FillClass.UNTESTABLE for r in records):
        present.append(UNTESTABLE_KEY)
    unmapped = [f for f in present if f not in consumer_map]
    if unmapped:
        raise PredeclarationError(f"consumer_map missing findings: {unmapped}")
    return [{"finding": f, "consumer": consumer_map[f]} for f in dict.fromkeys(present)]


def forward_route(p_cs: Sequence[float], thresholds: Mapping[str, Any]) -> dict[str, Any]:
    """INCONCLUSIVE routes: size a forward-only plan by the clusters P(W = 0) <= alpha needs."""
    mean_p = math.fsum(p_cs) / len(p_cs) if p_cs else 0.0
    alpha = float(thresholds["alpha_primary"])
    needed = None if not 0.0 < mean_p < 1.0 else math.ceil(math.log(alpha) / math.log(1.0 - mean_p))
    feasible = needed is not None and needed <= int(thresholds["forward_clusters_feasible"])
    return {
        "clusters_needed": needed,
        "feasible_bound": thresholds["forward_clusters_feasible"],
        "route": "forward_evidence_plan_to_T2" if feasible else "closed_no_action_until_T1_12_07",
        "basis": "clusters n with (1 - mean P_c)^n <= alpha_primary",
    }


def delivery(thresholds: Mapping[str, Any], run_date: dt.date) -> dict[str, Any]:
    target = str(thresholds["delivery_soft_target"])
    late = run_date > dt.date.fromisoformat(target)
    return {"soft_target": target, "slip": SLIP_TEXT if late else None}


def te1_block(ledger: Path | None, sha256: str | None) -> dict[str, Any]:
    if ledger is None:
        return {"status": "TE-1 cross-check pending"}
    return {
        "status": "TE-1 ledger supplied, not re-scored here (no second scorer)",
        "path": str(ledger), "sha256": sha256,
    }  # fmt: skip


def render_markdown(payload: Mapping[str, Any]) -> str:
    """The generated report: provenance, verdict, tests, classes, consumers, footer."""
    prov, pre, verdict = payload["provenance"], payload["predeclaration"], payload["verdict"]
    lines = [
        "# TE-2 FQ v1 loss taxonomy (generated, post-hoc diagnostic)", "",
        (
            f"Verdict: **{verdict['label']}** sublabel={verdict['sublabel']} "
            f"qualifiers={verdict['qualifiers']} reason={verdict['reason']}"
        ),
        "",
        "## Provenance", "",
        f"- script sha256 (HEAD blob): `{prov['script_sha256']}`",
        f"- pins.json sha256: `{prov['pins_json_sha256']}`",
        f"- reflog snapshot sha256: `{prov['reflog_snapshot_sha256']}`",
        f"- predeclaration commit: `{pre['commit']}` (file sha256 `{pre['sha256']}`)",
        f"- Phase A table sha256: `{prov['phase_a_table_sha256']}`", "",
        "## Tests (cluster level)", "",
    ]  # fmt: skip
    lines += [f"- {phrase}" for phrase in payload["report_phrases"]]
    lines += ["", "## Classes (ranked by share of loss)", ""]
    lines += [
        f"- {r['class']}: {r['count']} fills, share of loss {r['share_of_loss']:.3f}"
        for r in payload["ranked_classes"]
    ]
    lines += ["", f"Flags: {payload['flag_counts']}", "", "## Consumers", ""]
    lines += [f"- {c['finding']}: {c['consumer']}" for c in payload["consumers"]]
    lines += ["", f"Delivery: {payload['delivery']}", f"{payload['te1_cross_check']['status']}", ""]
    lines += ["## Caveats", ""] + [f"- {c}" for c in payload["caveats"]]
    lines += ["", "## Footer", "", payload["footer"], ""]
    return "\n".join(lines)
