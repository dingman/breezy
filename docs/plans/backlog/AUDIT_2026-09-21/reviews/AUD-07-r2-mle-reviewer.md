# AUD-07 review — round 2 — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-07-exit-seam-arming-verification-path.md
sha256: 1feb9c09e1615753cfb083d84ba74f5cd9d43ac12cc85160d6ec57c96090bf24
Round: 2
Reviewer: mle-reviewer (independent, blind)

## Round-1 remedy verification (my own round-1 finding)

My round-1 MINOR defect: the negative `median_minutes_last_executable_to_threatened` was flagged in
§12 as an open question with no assigned closing step. §6 B2 and §7 step 6 now fold it in as a
required sub-step with a concrete per-row `delta_i` classification, a publication gate ("the
reconciled table may not be published while any negative-delta row is unexplained"), two RED tests
covering both orderings through the real writer path, and — beyond what I asked for — an explicit
gate-reading consequence (AFTER-rows do not count toward the R-THREAT qualifying count). CONFIRMED
fixed, and genuinely strengthened past the minimum remedy.

## Re-verification of the plan's central claims against source (independent this round)

I re-read every file:line citation in §3 finding C and §6 C1/C2/C3 directly, not trusting §13's
"CONFIRMED" claims from round 1:

- `_DEFAULT_MONITORED_FAMILY_ID: Final[str] = "pm_us_crh_cont"` — CONFIRMED at
  `scripts/analysis/position_monitor_nightly_report.py:119`, and `--family-manifest` is indeed
  optional (`:864`, `default=None`) with the default literal substituted at `:594` when no manifest
  is supplied.
- `deploy/systemd/position-monitor-report-run.sh`'s `ARGS` block (`:102-106` as cited, verified at
  the corresponding lines in the current file) — CONFIRMED it passes `--summaries-dir`,
  `--scored-trials-dir`, `--out`, `--markdown`, and conditionally `--corpus-summary`, and **never**
  `--family-manifest`. The report is unbound, exactly as C1 claims, not merely mis-bound.
- `MONITOR_ROOT="$(dirname "$CATALOG_ROOT")/monitor"`, `SUMMARIES_DIR="$MONITOR_ROOT/summaries"` —
  CONFIRMED verbatim in the wrapper, and CONFIRMED to match
  `src/breezy/strategy/current_rung_hold/composition.py:563` (`monitor_root = catalog_root.parent /
  _MONITOR_CATALOG_DIRNAME`) and `:663` (`summaries_dir=monitor_root / _MONITOR_SUMMARIES_DIRNAME`)
  by construction — the two paths agree exactly as claimed.
- **C3's on-disk claim, independently re-verified today (read-only):**
  `~/.local/share/breezy/catalog/quote_tape/` contains `decisions/`, `observations/`,
  `polymarket_us/` — **no `monitor/` directory exists.** This is a direct, current confirmation of
  the plan's central diagnostic claim, not a restatement of round 1's finding.
- `exit_gate.py:55 _EXIT_RULE_REGISTERED_FAMILIES = frozenset({"pm_us_crh_exit_v4"})` — CONFIRMED.

All load-bearing technical claims in this plan hold up under independent re-verification this round.

## NEW finding this round (whole revised plan, source-checked)

**MATERIAL — `EXIT_CORPUS_FROZEN` and `EXIT_PNL_RECONCILIATION_MISMATCH` share the same
fire-once-then-permanently-silent latch semantics I found MATERIAL in AUD-04's `PORTFOLIO_ROI_INPUTS_FROZEN`, and this plan explicitly designs it that way "deliberately."**

File: AUD-07 §6 "D — make frozen corpus legible" and "standing P&L reconciliation with AUD-04",
§8 AC #3 and AC #6.

The latch: "The WARN is emitted **only on the transition `streak == 3` while `last_alerted_streak <
3`**, then `last_alerted_streak` is set and no further alert issues until a reset returns `streak`
to 0. **One alert per frozen streak — never nightly**." This is the identical mechanism, and the
identical gap, I flagged as MATERIAL in the sibling review of AUD-04 (`AUD-04-r2-mle-reviewer.md`,
this round): if the corpus never grows again for the life of the outage — which is the CURRENT,
live, measured state (no fills since 09-15, per §3 finding D and the plan's own baseline in §11) —
this control fires exactly once, on the third consecutive frozen run, and then produces no further
signal for as long as the freeze continues, whether that is another week or another year. The
`EXIT_PNL_RECONCILIATION_MISMATCH` alert (§6, "latched the same way") inherits the identical
semantics for a persistent P&L divergence with AUD-04.

This is not a hypothetical: §11's own stated baseline records "`n_positions_new_since_previous_run`
unreported for 4+ consecutive nights" **today**, meaning this exact control is at or past its
one-shot firing point on the live record right now, under the current, expected-quiet state. The
plan's own §9 "Frozen-corpus alert becomes noise" validation entry addresses over-alerting (the
WP-R1 false-page discipline) but does not address the opposite failure: a genuinely dead
measurement loop (as opposed to a legitimately quiet one) that started identically and gets exactly
one page, then none, indefinitely. Given this item's whole purpose is "a job that cannot progress
says so" (§9, "Autonomous operation"), a control that says so once and then falls silent for the
remaining life of the outage only partially satisfies that purpose.
Fix: either (a) re-emit the WARN on a coarser recurring cadence for as long as the streak stays ≥3
(e.g., once per UTC week while frozen, rather than a single message), or (b) escalate to a second,
higher-severity threshold at a longer streak (e.g., WARN at 3, CRITICAL at 21) so an operator who
missed or dismissed the first message is not permanently unreminded. This should be resolved
identically in AUD-04 and AUD-07 given they are explicitly designed as mirrors of the same control.

No other new defects found. C1/C2/C3's diagnosis, the B2 closing check, the standing reconciliation
design (reading AUD-04 only through its versioned reader), and the registration-package completion
(A) with the empty `exit_gate.py` diff all re-verify cleanly against source.

## Round-1 "portfolio objective alignment" (item 5) — assessed fresh

§11 states the measured structural ceiling (Rev 2 §0's finding that even a perfect-timing oracle
recovers only a fraction of the held loss), a field-level path into AUD-04 with a standing
cross-check, a three-row plausible-vs-demonstrated table whose last row states flatly "this item
changes ROI **not at all** today," a numeric baseline, a falsifier, and — importantly — corrects the
dependency framing so BLOCKER-1 is scoped to corpus growth only, not to this item's own fixes (all
of which are executable today at N=5). This is a substantively different document from a bare
"protective, near-zero" assertion and I find no remaining defect in it. I do not deduct further here.

## Per-criterion points (cap in parentheses)

- Fidelity to the gap and completeness (20): **17** — matches the author's honest self-docking
  (G-12's literal "unarmed" framing is explained rather than advanced toward); every element of the
  round-1 remedy set independently re-confirmed.
- Technical correctness and evidence grounding (20): **18** — every citation re-verified against
  live source and the live filesystem this round, including a fresh on-disk check of the `monitor/`
  directory's absence. Not docked further than the author for the still-open B/C3 causes, since
  those are correctly deferred to step 0/step 6 rather than asserted.
- Implementation specificity and feasibility (15): **13** — matches the author's assessment; the
  branch-on-step-0-finding asymmetry for C2/C3 is real but minor and correctly disclosed.
- Acceptance criteria and validation quality (20): **16** — docked below the author's 18 because AC
  #3 and AC #6, as written, assert the single-shot latch behaviour as correct ("emitted... exactly
  once on the third consecutive zero-new run, re-arming only after a reset") — this criterion locks
  in the MATERIAL gap above as intended rather than flagging it.
- Autonomous operation, failure handling, recovery (15): **10** — docked below the author's 14 for
  the same reason as AUD-04: this item's own headline autonomy fix (a job that cannot progress says
  so) does not actually keep saying so for the duration of an ongoing, indefinite outage, which is
  exactly the state the live record is in today per §11's own baseline.
- Portfolio objective alignment, scope, dependencies (10): **7** — matches the author's score; no
  further defect found on fresh assessment.

**Total: 81/100**

## Required changes to reach 100

1. Fix the fire-once-then-silent latch semantics for `EXIT_CORPUS_FROZEN` (and its mirror
   `EXIT_PNL_RECONCILIATION_MISMATCH`) so an indefinite outage produces more than one signal over its
   lifetime — resolve identically to the same fix required in AUD-04's `PORTFOLIO_ROI_INPUTS_FROZEN`.
2. Rewrite AC #3 and AC #6 to match the corrected re-arm behaviour.

## Blockers

Unchanged from round 1, correctly named and not resolvable by this review:
- **BLOCKER-1 (dependency in fact):** corpus cannot grow until trading resumes — blocks corpus growth
  only, not this item's own measurement fixes.
- **BLOCKER-2 (operator + PREREG):** arming requires PREREG v4 registration and the operator-only
  1-lot positive control.
- **BLOCKER-3 (strategy lead):** v4's boundary package inherits whatever AUD-06a determines about
  boundary validity.
