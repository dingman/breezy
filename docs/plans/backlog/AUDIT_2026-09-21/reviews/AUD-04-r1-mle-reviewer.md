# AUD-04 review — round 1 — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-04-portfolio-roi-measurement.md
sha256: a75ce7cf6fee6214140f7439d3057b0e2f8924a3c6bfbb98571cd5eb68320964
Round: 1

## Claims verified
- `PortfolioAnalyzer.calculate_statistics` has its only call site at `backtest/engine.pyx:2211`, none in `live/` — CONFIRMED (grepped installed nautilus_trader tree).
- `Portfolio._handle_position_event` / `record_trade` gated on `updated_position.is_closed_c() and updated_position.realized_pnl is not None` — CONFIRMED (`portfolio.pyx:626,666-670`; plan cites `:665-670`, actual `:666-670` — negligible offset, same code block).
- `fill_time_count.py`'s read-only `mode=ro` URI idiom (`:84-98`) — CONFIRMED, matches file.
- `position_monitor_report_<date>.{md,json}` output shape exists as precedent — CONFIRMED, but its JSON has no `schema_version` field (checked `position_monitor_report_2026-09-20.json`), and no other analysis script in `scripts/analysis/` writes one to a comparable evidence artefact (grep for `schema_version` found only an unrelated backtest record field).

## Defects

**MATERIAL — no versioned output schema for the JSON sibling artefact.**
File: AUD-04-portfolio-roi-measurement.md §7 step 3, §8 AC#3
Issue: The plan requires a JSON sibling "in the shape `position_monitor_report_<date>.{md,json}` already uses," but that precedent has no `schema_version` field (verified on disk), and the plan does not add one. Two other in-repo consumers are named as depending on this report's shape (AC#4's cross-check against the exit-window study, and AUD-06b's AC#8 post-merge reconciliation). Without a versioned schema, a future field rename/addition silently breaks a downstream consumer instead of failing loudly — exactly the "stale/partial number" risk this review was asked to check for, moved from the report's correctness into its consumers' correctness.
Fix: Add an explicit `schema_version` field (integer or semver string) to the JSON output and a RED/GREEN test asserting its presence and value; state the compatibility policy (e.g., additive-only within a major version) in §6.

**MATERIAL — no staleness detector for "inputs stopped growing but the job keeps succeeding."**
File: AUD-04-portfolio-roi-measurement.md §9
Issue: §9 fail-closes on absent/unreadable/empty inputs, which is correct, but has no detector for the input being present and readable yet frozen — e.g., the fill ledger or scored-trial store stops receiving new rows while the daily job continues to exit 0 and emit an (honestly computed, but silently non-updating) report. This is precisely the failure class AUD-07 (§6 finding D, `EXIT_CORPUS_FROZEN`) independently identifies and fixes for the sibling exit-window study in the same backlog batch — AUD-04 does not apply the same defense to itself, and the self-score's §9 discussion names the gap but does not commit to closing it (author scored 12/15 citing this exact weakness as a "named risk," not a required fix).
Fix: Add a `PORTFOLIO_ROI_INPUTS_FROZEN`-shaped WARN (mirroring AUD-07's `EXIT_CORPUS_FROZEN` pattern, delivered through the shipped alert sink) when the newest ledger fill or scored-trial mtime is more than N days older than `--as-of` for ≥3 consecutive runs, so a dead upstream pipeline cannot masquerade indefinitely as a healthy, quiet account.

## Per-criterion points
- Fidelity to gap and completeness: 17/20
- Technical correctness and evidence grounding: 16/20
- Implementation specificity and feasibility: 10/15 (docks the $0.05 tolerance and balance-line parser gaps the author already named, plus the missing schema_version)
- Acceptance criteria and validation quality: 16/20
- Autonomous operation, failure handling, recovery: 10/15 (docked further than the author's 12 for the stale-input detector being a real, not merely cosmetic, gap)
- Portfolio objective alignment, scope, dependencies: 5/10

**Total: 74/100**

## Required changes to reach 100
1. Add `schema_version` to the JSON artefact + test.
2. Add an input-freshness/staleness WARN analogous to AUD-07's `EXIT_CORPUS_FROZEN`.
3. Pin the $0.05 unexplained-flow tolerance to a measured basis (author-named).
4. Specify the balance-line parser's regex/anchor (author-named).

## Blockers
None requiring operator/strategy-lead ruling. The two MATERIAL defects are build-side fixes, not rulings.
