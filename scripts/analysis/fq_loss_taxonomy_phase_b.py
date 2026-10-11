"""TE-2 WP1c: the Phase B pipeline (gates, audit reproduction, classification, tests, verdict) and
the post-hoc ``verify`` check. Plan section 4 "Phase B" and section 5 WP3.

Phase B only runs after the freeze. It refuses (nothing is read, nothing is written) unless the
HEAD blobs of every pinned module hold, every ``fq_loss_taxonomy_*.py`` module on disk is pinned,
the predeclaration is committed (an ancestor of HEAD), unmodified since that commit and bound to
the Phase A table passed in. It then reproduces the corrected audit (STOP on a mismatch), joins
truth through the clipping wrapper, and writes ``fq_v1_loss_taxonomy_<date>.json`` and a
generated ``.md``. It never reads a pre-October climate day and builds no second scorer.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, cast

from breezy.analysis.labeling.fill_source import FillRead
from breezy.analysis.labeling.settlement_source import SettlementSource
from scripts.analysis.fq_loss_taxonomy_battery import BatteryResult, run_battery
from scripts.analysis.fq_loss_taxonomy_fills import (
    FillRecord,
    build_fill_records,
    day_records,
    k3_flips,
    k4_mismatches,
    t_edge,
)
from scripts.analysis.fq_loss_taxonomy_pins import (
    GitPort,
    RefusalReason,
    phase_b_refusals,
    post_hoc_violations,
)
from scripts.analysis.fq_loss_taxonomy_predecl import (
    Predeclaration,
    PredeclarationError,
    default_consumer_map,
    load_predeclaration,
    sha256_file,
    unpinned_family_modules,
)
from scripts.analysis.fq_loss_taxonomy_report import (
    class_counts,
    consumers,
    delivery,
    fields_dict,
    fill_json,
    flag_counts,
    forward_route,
    ranked_classes,
    render_markdown,
    te1_block,
    write_json,
)
from scripts.analysis.fq_loss_taxonomy_stats import Status
from scripts.analysis.fq_loss_taxonomy_truth import (
    AuditReproduction,
    alt_truth_summary,
    reproduce_audit,
)
from scripts.analysis.fq_loss_taxonomy_verdict import (
    VerdictInputs,
    apply_downgrade,
    decide_verdict,
    reevaluate_after_ties,
    render_footer,
    report_phrase,
)

EXIT_STOP: Final = 2
RESULT_STEM: Final = "fq_v1_loss_taxonomy"
CLI_PATH: Final = "scripts/analysis/fq_v1_loss_taxonomy.py"
_TESTS: Final = ("T-WIN", "T-LOC", "T-SPREAD", "T-ART")
_CAVEATS: Final = (
    "diagnostic, post-hoc: the audit and triage showed the headline direction before the freeze",
    "ask_proxy is the fill's cumulative cost per unit; the decision-time ask is unauditable",
    "P_d sums p-hat taken at different cycles and assumes marginal calibration",
    "T-LOC is INDICATIVE and conditional on take; it never alone yields MODEL_LIMITATION/FIXABLE",
    (
        "T-SPREAD and T-LOC are conditional on take (adverse selection); spread vs location is "
        "not identified, so a tail rejection is never attributed to spread alone"
    ),
    "PIN=INFERRED: the node imports the working tree at boot; the deployed commit is inferred",
    (
        "H0-K / H1-K use the ask break-even a + theta*a*(1-a) summed per station-day (cap 1), "
        "max over the cluster, same clamp"
    ),
    "K3 uses the METAR/ASOS tmpf max over the local-standard day, rounded; K4 needs a venue file",
    "the raw-median T-LOC companion is not run (no raw pmf is stored); raw error is descriptive",
)


class PhaseBRefused(Exception):
    """Phase B refuses before reading any truth; ``reasons`` is the full list."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


@dataclass(frozen=True)
class PhaseBInputs:
    output_dir: Path
    repo_root: Path
    pins_json: Path
    predeclaration: Path
    phase_a_table: Path
    now_ns: int
    archive_root: Path | None = None
    venue_outcomes: Path | None = None
    te1_ledger: Path | None = None


@dataclass(frozen=True)
class Gates:
    pins: Mapping[str, Any]
    predeclaration: Predeclaration
    table: Mapping[str, Any]


def check_gates(inp: PhaseBInputs, git: GitPort) -> Gates:
    """Every refusal reason at once (all checks run); raises ``PhaseBRefused`` when any fails."""
    reasons: list[str] = []
    pins: Mapping[str, Any] = {}
    try:
        pins = json.loads(inp.pins_json.read_text())
        blobs = pins["head_blob_sha256"]
        pre_commit = pins["predeclaration_commit"]
        reasons += [r.value for r in phase_b_refusals(blobs, pre_commit, git)]
        missing = unpinned_family_modules(inp.repo_root, blobs)
        if missing:
            reasons.append(f"{RefusalReason.UNPINNED_FAMILY_MODULE.value}: {list(missing)}")
        reasons += _predeclaration_modified(inp, pre_commit, git)
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        reasons.append(f"pins unusable: {type(exc).__name__}: {exc}")
    predeclaration = None
    try:
        predeclaration = load_predeclaration(inp.predeclaration, inp.phase_a_table)
        absent = [k for k in default_consumer_map() if k not in predeclaration.consumer_map]
        if absent:
            reasons.append(f"consumer_map missing findings: {absent}")
    except PredeclarationError as exc:
        reasons.append(str(exc))
    table: Mapping[str, Any] = {}
    try:
        table = json.loads(inp.phase_a_table.read_text())
        if table.get("phase") != "A" or table.get("outcome_blind") is not True:
            reasons.append("the Phase A table is not an outcome-blind Phase A table")
    except (OSError, ValueError) as exc:
        reasons.append(f"Phase A table unreadable: {exc}")
    if reasons or predeclaration is None:
        raise PhaseBRefused(reasons)
    return Gates(pins, predeclaration, table)


def _predeclaration_modified(inp: PhaseBInputs, commit: str, git: GitPort) -> list[str]:
    try:
        rel = inp.predeclaration.resolve().relative_to(inp.repo_root.resolve()).as_posix()
    except ValueError:
        return ["predeclaration_outside_repo"]
    committed = git.blob_sha256(commit, rel)
    if committed is None or committed != sha256_file(inp.predeclaration):
        return [RefusalReason.PREDECLARATION_MODIFIED.value]
    return []


def _audit_ok(audit: AuditReproduction, expected: Mapping[str, Any]) -> bool:
    return (
        audit.n_fills == int(expected["n_fills"])
        and audit.n_wins == int(expected["n_wins"])
        and abs(audit.net_pnl - Decimal(str(expected["net_pnl"])))
        <= Decimal(str(expected["tolerance"]))
    )


def _decisions(result: BatteryResult) -> dict[str, bool]:
    return {name: result.outcomes[name].rejects for name in _TESTS}


def _verdict_inputs(result: BatteryResult, records: list[FillRecord]) -> VerdictInputs:
    flags = {f for r in records for f in r.flags}
    material = any(
        r.row.get("s0d_class") == "K1a" and r.row.get("material_k1a") is True for r in records
    )
    return VerdictInputs(
        t_win=result.outcomes["T-WIN"], loo_rejects=result.loo_rejects,
        t_loc=result.outcomes["T-LOC"], t_spread=result.outcomes["T-SPREAD"],
        t_art=result.outcomes["T-ART"], has_k4="K4" in flags, material_k1a=material,
        k3_present="K3" in flags, k1b_present="K1b" in flags,
    )  # fmt: skip


def _analyse(inp: PhaseBInputs, gates: Gates, audit: AuditReproduction) -> dict[str, Any]:
    pre, table = gates.predeclaration, gates.table
    th = pre.thresholds
    terminal = dt.date.fromisoformat(pre.terminal_climate_day)
    days = {
        (d["station"], dt.date.fromisoformat(str(d["climate_day"]))): d
        for d in table["station_days"]
    }
    present = bool(table["s0g"]["k3_status"] == "SOURCE_PRESENT")
    scored = {s.fill_id: s for s in audit.per_fill}
    bare = build_fill_records(
        table["per_fill"], days, scored, thresholds=th, terminal_climate_day=terminal,
        k3=None, k4=None,
    )  # fmt: skip
    k3, k4 = (
        k3_flips(bare, inp.archive_root, present=present),
        k4_mismatches(bare, inp.venue_outcomes),
    )
    records = build_fill_records(
        table["per_fill"], days, scored, thresholds=th, terminal_climate_day=terminal, k3=k3, k4=k4
    )
    alpha, alpha_art = float(th["alpha_primary"]), float(th["alpha_art"])
    all_days = day_records(records, days, float(th["fee_theta"]))
    in_scope = [d for d in all_days if d.climate_day <= terminal]
    cluster = run_battery(all_days, level="cluster", alpha_primary=alpha, alpha_art=alpha_art)
    by_day = run_battery(all_days, level="day", alpha_primary=alpha, alpha_art=alpha_art)
    six = run_battery(in_scope, level="cluster", alpha_primary=alpha, alpha_art=alpha_art)
    downgrade = apply_downgrade(_decisions(cluster), _decisions(by_day), _decisions(six))
    verdict = decide_verdict(_verdict_inputs(cluster, records))
    declared = cast("dict[str, Status]", dict(pre.s0i_statuses))
    ties = reevaluate_after_ties(declared, cluster.after_ties)
    n_clusters = cluster.report["n_units"]
    footer = render_footer(len(all_days), n_clusters)
    label = str(verdict.label)
    run_date = dt.datetime.fromtimestamp(inp.now_ns / 1e9, tz=dt.UTC).date()
    pins = gates.pins
    return {
        "phase": "B",
        "provenance": {
            "script_sha256": pins["head_blob_sha256"].get(CLI_PATH),
            "head_blob_sha256": pins["head_blob_sha256"],
            "pins_json_sha256": sha256_file(inp.pins_json),
            "reflog_snapshot_sha256": pins.get("reflog_snapshot_sha256"),
            "phase_a_table_sha256": pre.phase_a_table_sha256,
        },
        "predeclaration": {
            "commit": pins["predeclaration_commit"], "sha256": pre.raw_sha256,
            "thresholds": dict(th), "terminal_climate_day": pre.terminal_climate_day,
        },
        "audit": {
            "n_fills": audit.n_fills, "n_wins": audit.n_wins, "net_pnl": str(audit.net_pnl),
            "wins": [list(w) for w in audit.wins], "n_refused": audit.n_refused,
            "expected": dict(th["audit"]),
        },
        "fills": [fill_json(r) for r in records],
        "class_counts": class_counts(records),
        "ranked_classes": ranked_classes(records),
        "flag_counts": flag_counts(records),
        "tests": cluster.report,
        "sensitivity": {"station_day": by_day.report, "six_cluster": six.report},
        "downgrade": fields_dict(downgrade),
        "testability": {
            "predeclared": dict(pre.s0i_statuses), "after_ties": dict(cluster.after_ties),
            "recomputed_pre_ties": cluster.report["testability"]["pre_ties"],
            "predeclared_matches_recomputed": dict(pre.s0i_statuses)
            == cluster.report["testability"]["pre_ties"],
        },
        "tie_reevaluation": fields_dict(ties),
        "verdict": {
            "label": label, "sublabel": verdict.sublabel and str(verdict.sublabel),
            "qualifiers": [str(q) for q in verdict.qualifiers], "reason": verdict.reason,
            "notes": list(verdict.notes),
        },
        "report_phrases": [report_phrase(cluster.outcomes[n]) for n in _TESTS],
        "footer": footer,
        "consumers": consumers(label, records, cluster.after_ties.values(), pre.consumer_map),
        "inconclusive_route": forward_route(
            [u["P_c"] for u in table["clusters"]], th
        ) if label == "INCONCLUSIVE" else None,
        "delivery": delivery(th, run_date),
        "te1_cross_check": te1_block(
            inp.te1_ledger, sha256_file(inp.te1_ledger) if inp.te1_ledger else None
        ),
        "alt_truth": fields_dict(alt_truth_summary(k3, k4)),
        "t_edge": t_edge(records),
        "h0k": cluster.report["T-WIN"]["h0k"],
        "caveats": list(_CAVEATS),
    }  # fmt: skip


def execute(inp: PhaseBInputs, gates: Gates, fills: FillRead, source: SettlementSource) -> int:
    """Audit (STOP on mismatch), analyse, write the JSON and Markdown. Returns the exit code."""
    table_ids = {r["fill_id"] for r in gates.table["per_fill"]}
    if table_ids != {f.venue_order_id for f in fills.fills}:
        sys.stderr.write("STOP: the fill store and the Phase A table hold different fills\n")
        return EXIT_STOP
    audit = reproduce_audit(fills, source, now_ns=inp.now_ns)
    write_json(
        inp.output_dir / "phase_b_audit.json", {"phase": "B", "audit_fq": fields_dict(audit)}
    )
    if not _audit_ok(audit, gates.predeclaration.thresholds["audit"]):
        sys.stderr.write("STOP: the corrected audit (25 fills, 2 wins, -2.17) did not reproduce\n")
        return EXIT_STOP
    payload = _analyse(inp, gates, audit)
    run_date = dt.datetime.fromtimestamp(inp.now_ns / 1e9, tz=dt.UTC).date().isoformat()
    stem = inp.output_dir / f"{RESULT_STEM}_{run_date}"
    write_json(stem.with_suffix(".json"), payload)
    stem.with_suffix(".md").write_text(render_markdown(payload))
    sys.stdout.write(
        f"phase B result written to {stem}.json and .md ({payload['verdict']['label']})\n"
    )
    return 0


def verify_artefact(
    repo_root: Path, pins_json: Path, artefact: Path, git: GitPort
) -> tuple[str, ...]:
    """Post-hoc check: the result artefact is committed, clean, and in a STRICT descendant of the
    predeclaration commit. Returns the violation reasons (empty = OK)."""
    pre_commit = json.loads(pins_json.read_text())["predeclaration_commit"]
    try:
        rel = artefact.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return ("artefact_outside_repo",)
    commits = git.log_commits([rel], "HEAD")
    if not commits or not git.porcelain_clean([rel]):
        return (RefusalReason.ARTEFACT_UNCOMMITTED.value,)
    return tuple(r.value for r in post_hoc_violations(pre_commit, commits[-1], git))
