"""F13 Phase A veto analysis (F13-R8, R15): how many FQ-style takes would the blend have refused?

DESCRIPTIVE ONLY. It carries no verdict, no p-value and no bound. Plan: docs/plans/backlog/
FQ_LOSS_RESPONSE_2026-10-04/F13-us-source-ingest_plan_r3.md, "Veto analysis".

OPEN-3 (the exact FQ take rule the proxy mirrors) is RESOLVED by citation, not by re-implementation:
the take decision is the shipped ``evaluate`` in
``src/breezy/strategy/forecast_quantile_ladder/decision.py:349-355`` (net EV against fee and
slippage, take iff ``net > forecast_margin(h)``, ``margin.py:30-37``), reached through
``scripts/analysis/fq_mc_livedata.py:370`` ``_call_evaluate`` exactly as the N Monte-Carlo does.
The only substitution is the bounds provider: no out-of-fold bootstrap draws exist, so
``p_lower``/``p_upper`` are ``p_hat -/+ LoopConfig.bound_halfwidth``.

Pre-07-01 proxy: no tape exists before 2026-08-30, so a historical FQ take has no price. The take
set is therefore a MODEL-SIDE proxy: the OUT-OF-FOLD champion's rung probabilities against a
PRE-REGISTERED reference ask (``veto.reference`` in the prereg, pinned by the coordinator). A row
whose champion output is not out of fold is refused; a market-sourced ask on a pre-tape day is
refused; no tape or catalogue reader is imported here. Real FQ takes (>= 2026-08-30) get a forward
shadow count only, never evidence.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, Final

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from breezy.analysis import multisource_blend as msb
from breezy.strategy.forecast_quantile_ladder.decision import SidedAsk, Take
from breezy.strategy.forecast_quantile_ladder.latch import QuantileLadderLatch
from breezy.strategy.ladder_ev.quantile_density import Rung, rung_probabilities
from breezy.strategy.weather_common.costs import venue_fee_prob
from scripts.analysis.fq_mc_livedata import LoopConfig, _call_evaluate
from scripts.analysis.prereg_precommit_check import check_frozen_blob

__all__ = [
    "RULE_CITATION",
    "TAPE_START",
    "ForwardTake",
    "NotOutOfFoldError",
    "PreFreezeDayError",
    "PreTapeMarketPriceError",
    "ReferenceAsk",
    "Refusal",
    "forward_shadow_count",
    "main",
    "proxy_report",
    "rungs_from_edges",
    "would_take",
]

TAPE_START: Final[dt.date] = dt.date(2026, 8, 30)
UNFROZEN: Final[str] = "UNFROZEN"
SOURCE_PREREG_REFERENCE: Final[str] = "prereg_reference"
SOURCE_MARKET: Final[str] = "market"
PROXY_ARM: Final[str] = "M3"
PROXY_HORIZON: Final[str] = "D-1"  # the FQ family trades D+1
RULE_CITATION: Final[Mapping[str, str]] = {
    "evaluate": "src/breezy/strategy/forecast_quantile_ladder/decision.py:349-355",
    "margin": "src/breezy/strategy/forecast_quantile_ladder/margin.py:30-37",
    "fee": "src/breezy/strategy/weather_common/costs.py:155-183",
    "entry": "scripts/analysis/fq_mc_livedata.py:370 (_call_evaluate)",
}
_PROXY_LADDER: Final[tuple[Rung, ...]] = (Rung("proxy", None, None),)


class Refusal(Exception):
    """The analysis is refused."""


class NotOutOfFoldError(Refusal):
    """A champion output that is not out of fold (fitted in sample, or absent)."""


class PreTapeMarketPriceError(Refusal):
    """A market price claimed for a day before the tape starts."""


class PreFreezeDayError(Refusal):
    """A forward-shadow take dated before the first post-freeze day."""


@dataclass(frozen=True, slots=True)
class ReferenceAsk:
    price: float
    source: str


@dataclass(frozen=True, slots=True)
class ForwardTake:
    """A real FQ take read through the live ledger (R12), with the blend's probability."""

    station: str
    climate_day: dt.date
    side: str
    rung_id: str
    blend_p_yes: float
    champion_p_yes: float
    ask: float


def would_take(
    *,
    side: str,
    p_yes: float,
    ask: float,
    climate_day: dt.date,
    station: str,
    cfg: LoopConfig | None = None,
) -> bool:
    """ONE call of the shipped FQ take rule (``decision.evaluate``) at ``p_hat = p_yes``."""
    loop = cfg if cfg is not None else LoopConfig()
    decision = _call_evaluate(
        climate_day=climate_day,
        station=station,
        ladder=_PROXY_LADDER,
        rung_id="proxy",
        side=side,  # type: ignore[arg-type]
        ask=SidedAsk(side=side, instrument_id="PROXY", price=ask),  # type: ignore[arg-type]
        p_hat=p_yes,
        cfg=loop,
        h_hours=loop.h_hours,
        latch=QuantileLadderLatch(),
    )
    return isinstance(decision, Take)


def rungs_from_edges(edges: Sequence[int]) -> tuple[Rung, ...]:
    ordered = sorted(edges)
    rungs = [Rung(f"lt{ordered[0]}", None, ordered[0] - 1)]
    rungs += [Rung(f"{lo}-{hi - 1}", lo, hi - 1) for lo, hi in pairwise(ordered)]
    rungs.append(Rung(f"ge{ordered[-1]}", ordered[-1], None))
    return tuple(rungs)


def _contains(rung: Rung, label: int) -> bool:
    return (rung.lo is None or label >= rung.lo) and (rung.hi is None or label <= rung.hi)


def _net_outcome(side: str, rung: Rung, observed_f: float, ask: float, theta: float) -> float:
    inside = _contains(rung, round(observed_f))
    won = inside if side == "yes" else not inside
    return (1.0 if won else 0.0) - ask - venue_fee_prob(executable_price=ask, fee_coefficient=theta)


def _bucket(values: Sequence[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "mean_net_per_contract": (sum(values) / len(values)) if values else None,
    }


def proxy_report(
    rows: Sequence[msb.ScoredRow],
    *,
    rungs: Sequence[Rung],
    reference_ask: Callable[[msb.ScoredRow, Rung, str], ReferenceAsk | None],
    cfg: LoopConfig | None = None,
) -> dict[str, Any]:
    """Refusal rate and CLI outcomes of refused versus kept proxy takes, by station."""
    loop = cfg if cfg is not None else LoopConfig()
    tallies: dict[str, dict[str, list[float]]] = {}
    skipped = 0
    for row in rows:
        if row.climate_day >= msb.HOLDOUT_START:
            raise msb.HoldoutLeakError(f"{row.climate_day} is on or after {msb.HOLDOUT_START}")
        if row.fold_id is None or row.champion is None:
            raise NotOutOfFoldError(
                f"{row.station} {row.climate_day}: the champion output is not out of fold; a "
                "fitted-in-sample champion is never used"
            )
        if row.horizon != PROXY_HORIZON:
            skipped += 1
            continue
        blend = row.arm_predictions.get(PROXY_ARM)
        if blend is None:
            raise Refusal(f"{row.station} {row.climate_day}: no {PROXY_ARM} prediction on the row")
        champion_p = rung_probabilities(msb.champion_cdf(row.champion), rungs)
        blend_p = rung_probabilities(msb.blend_cdf(blend), rungs)
        bucket = tallies.setdefault(row.station, {"refused": [], "kept": []})
        for rung in rungs:
            for side in ("yes", "no"):
                ask = reference_ask(row, rung, side)
                if ask is None:
                    continue
                if ask.source == SOURCE_MARKET and row.climate_day < TAPE_START:
                    raise PreTapeMarketPriceError(
                        f"a market price was supplied for {row.climate_day}, before the tape "
                        f"starts on {TAPE_START}"
                    )
                p_c = champion_p[rung.rung_id]
                kwargs: dict[str, Any] = {
                    "side": side,
                    "ask": ask.price,
                    "climate_day": row.climate_day,
                    "station": row.station,
                    "cfg": loop,
                }
                if not would_take(p_yes=p_c, **kwargs):
                    continue
                kept = would_take(p_yes=blend_p[rung.rung_id], **kwargs)
                outcome = _net_outcome(side, rung, row.observed_f, ask.price, loop.theta)
                bucket["kept" if kept else "refused"].append(outcome)
    refused = [v for b in tallies.values() for v in b["refused"]]
    kept_all = [v for b in tallies.values() for v in b["kept"]]
    takes = len(refused) + len(kept_all)
    return {
        "label": "descriptive_only_no_verdict",
        "rule_citation": dict(RULE_CITATION),
        "n_rows": len(rows),
        "n_rows_skipped_other_horizon": skipped,
        "fitted_in_sample_champion_used": False,
        "takes": takes,
        "refused": len(refused),
        "kept": len(kept_all),
        "refusal_rate": (len(refused) / takes) if takes else 0.0,
        "outcome_refused": _bucket(refused),
        "outcome_kept": _bucket(kept_all),
        "by_station": {
            station: {
                "takes": len(b["refused"]) + len(b["kept"]),
                "refused": len(b["refused"]),
                "kept": len(b["kept"]),
                "outcome_refused": _bucket(b["refused"]),
                "outcome_kept": _bucket(b["kept"]),
            }
            for station, b in sorted(tallies.items())
        },
    }


def forward_shadow_count(
    takes: Sequence[ForwardTake], *, first_forward_day: dt.date, cfg: LoopConfig | None = None
) -> dict[str, Any]:
    """Shadow count for real FQ takes on post-freeze days: scan days, never evidence (R12)."""
    loop = cfg if cfg is not None else LoopConfig()
    by_station: dict[str, int] = {}
    refused = 0
    for take in takes:
        if take.climate_day < first_forward_day:
            raise PreFreezeDayError(
                f"{take.climate_day} is before the first post-freeze day {first_forward_day}"
            )
        kept = would_take(
            side=take.side,
            p_yes=take.blend_p_yes,
            ask=take.ask,
            climate_day=take.climate_day,
            station=take.station,
            cfg=loop,
        )
        if not kept:
            refused += 1
            by_station[take.station] = by_station.get(take.station, 0) + 1
    return {
        "label": "scan_day_shadow_count_never_evidence",
        "feeds_verdict": False,
        "n_takes": len(takes),
        "n_blend_would_refuse": refused,
        "by_station_would_refuse": dict(sorted(by_station.items())),
    }


# ------------------------------------------------------------------ CLI


def _reference_from_prereg(
    design: Mapping[str, Any],
) -> Callable[[msb.ScoredRow, Rung, str], ReferenceAsk | None]:
    spec = design.get("veto", {}).get("reference")
    if not isinstance(spec, Mapping):
        raise Refusal(
            "veto.reference is not pinned in the prereg: the coordinator pins the reference ask"
        )
    if spec.get("kind") != "const":
        raise Refusal(
            f"unsupported veto reference kind {spec.get('kind')!r}: only 'const' is implemented"
        )
    price = float(spec["price"])
    return lambda _row, _rung, _side: ReferenceAsk(price=price, source=SOURCE_PREREG_REFERENCE)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="F13 Phase A descriptive veto proxy")
    parser.add_argument("--prereg", type=Path, required=True)
    parser.add_argument("--oof-rows", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    design = json.loads(args.prereg.read_text(encoding="utf-8"))
    if design.get("frozen_sha") == UNFROZEN:
        raise Refusal("frozen_sha is UNFROZEN: the draft prereg has not been frozen")
    defects = check_frozen_blob(args.prereg, design)
    if defects:
        raise Refusal("; ".join(f"[{d.code}] {d.message}" for d in defects))
    reference = _reference_from_prereg(design)
    edges = design.get("pins", {}).get("rung_edges_f")
    if not edges:
        raise Refusal("pins.rung_edges_f is not pinned in the prereg")
    lines = [ln for ln in args.oof_rows.read_text(encoding="utf-8").splitlines() if ln.strip()]
    rows = [msb.scored_row_from_json(json.loads(ln)) for ln in lines]
    report = proxy_report(
        rows, rungs=rungs_from_edges([int(e) for e in edges]), reference_ask=reference
    )
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
