# AUD-06b review — round 2 — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-06b-bounded-allocation-sizing.md
sha256: a7c4628ed4b51ed45f021f8e99c0f8202c635349a8f522a26f35b422994d7eca
Round: 2
Reviewer: mle-reviewer (independent, blind)

## Round-1 remedy verification (my own round-1 finding)

My round-1 MATERIAL defect: the AUD-06a envelope re-check ran post-merge (a detector, not a
precondition). §7 step 7a now makes it explicitly a **pre-merge gate**: "Drive the merged sizing
function over the historical ask tape to produce the realised qty distribution; re-run AUD-06a's
sweep (ii) at that distribution... Merge is blocked on this." §7 step 7b additionally adds a bounded
first cohort as defence in depth. This is a genuine structural fix, not a restatement — **but see the
new MATERIAL finding below**, which is a gap in this exact remedy that round 1 did not test for
(round 1 only asked "is it pre- or post-merge", not "what input does the pre-merge sweep actually
run on").

I also re-verified the source claims underpinning this item independently this round (not merely
trusting §13's citations): `config.py:255` — CONFIRMED verbatim
(`"order_quantity must be exactly 1, was {self.order_quantity!r}"`);
`gs_boundary_artefact.py` — CONFIRMED it is exactly the sha-recompute-and-pin idiom the plan claims
(`load_boundary_artefact` recomputes `inputs_sha256` and raises `BoundaryPinMismatch` on drift,
:219-265); `decision.py`'s executable-gate claim — CONFIRMED, `_evaluate_no_side` at :425-446
returns `Refuse("not_executable")` when `inputs.bid`/`inputs.bid_size` is `None`, matching D3's
description exactly; `safety.py:591 _derived_session_order_count` — CONFIRMED to exist, supporting
BLOCKER-C's description of the permit's session order-count ceiling.

## NEW finding this round (whole revised plan, source-checked)

**MATERIAL — the pre-merge realised-qty sweep (§7 step 7a), the round-1 fix that made the envelope
re-check a merge gate, does not say how it obtains a qty distribution without reading the
operator-reserved cap this item is explicitly forbidden from reading.**

File: AUD-06b §5 "Explicitly excluded" (first bullet), §7 step 7a, §12 (the load-bearing assumption
for 7a).

§5's first exclusion is unconditional and item-wide: "**No operator-reserved value is read,
restated, defaulted or assigned**... The cap is consumed only through `DailySpendLedger`'s existing
authorisation seam; the sizing code sees a ledger, never a number it may print. **No value is
assigned to either cap by this item, its first-cohort bound, or its tests.**" D1's own formula is
`qty = min(floor_cent_safe(cap / ask / lot) * lot, executable_size_at_limit, Q_MAX_VALIDATED,
COHORT_QTY_CEILING)` — `cap` is a direct, load-bearing argument to the function under test.

§7 step 7a instructs: "Drive the merged sizing function over the historical ask tape to produce the
realised qty distribution." Read literally, this means invoking `derive_order_quantity(...)` (or
whatever the merged `qty=` formula becomes) over historical asks — which requires a concrete `cap`
value at every simulated station-day, because the function's output is a direct, monotonic function
of `cap`. The plan never states where this pre-merge sweep's `cap` value(s) come from. Two readings,
both leaving a gap:

1. **If the sweep reads the real operator cap** (even only in-memory, never printed) to compute the
   realised distribution, that is reading an operator-reserved value — the plan's own §5 exclusion
   does not carve out an exemption for "read but don't print," and elsewhere in this same plan (D6,
   the "no log line carrying the derived qty" rule) the concern is explicitly that qty *itself*
   reconstructs the cap once combined with a known ask — so a pre-merge artefact that records a
   *realised qty distribution* derived from the real cap is exactly the kind of output D6 warns
   against, now produced as a committed evidence artefact rather than a journal line.
2. **If the sweep is meant to run parametrically** — e.g. over a swept range of dimensionless
   `cap/ask` ratios, the way AUD-06a's own envelope sweep deliberately parameterises over qty *shape*
   rather than reading the cap (AUD-06a §3: "the re-validation must therefore be parameterised over
   the qty distribution, not conditioned on the cap") — the plan does not say so. Nothing in §6 D1,
   §7 step 7a, or §12 states the sweep is cap-agnostic, names the swept range, or explains how a
   cap-agnostic sweep still produces "the realised qty distribution" (singular, definite article) as
   opposed to a family of distributions indexed by an unknown cap.

This is exactly the class of gap this review is asked to catch: a merge-blocking acceptance
criterion (AC #6, "the PRE-MERGE realised-qty sweep reports a crossing rate with Clopper-Pearson
upper bound ≤ 0.025") whose methodology is not specified precisely enough for an implementer to
execute it without either violating the item's own hard exclusion or inventing an unstated
parameterisation scheme. AUD-06a solved exactly this problem for its own sweep and stated the
solution explicitly; AUD-06b inherits the same problem for its pre-merge gate and does not.
Fix: state explicitly, in Amendment-C-adjacent language, whether §7 step 7a's sweep runs (a) over a
swept, dimensionless `cap`-to-typical-ask ratio range (matching AUD-06a's own parameterisation and
resolving the exclusion cleanly), reporting the crossing rate as a function of that ratio rather than
a single number; or (b) some other cap-agnostic construction. If the intended design genuinely
requires the real cap value in-process (never printed) to produce one concrete distribution, say so
and reconcile it explicitly against §5's exclusion rather than leaving the two in unstated tension.

No other new defects found this round. The gate symmetry (G1/G2), the D3 clamp-source correction,
the bounded first cohort, and the BLOCKER-C/D framing all re-verify cleanly against source and
against the round-1 dispositions.

## Round-1 "portfolio objective alignment" (item 9) — assessed fresh

§11 gives a field-level evaluation contract into AUD-04, fixed baselines, an explicit "this item can
REDUCE ROI" row stated as load-bearing (not softened), a cohort-review decision rule (AC #9) that
reverts to qty=1 on a negative cohort rather than explaining it away, and a falsifier. This is a
genuinely more rigorous document than a bare "conditional on an edge" assertion. I find no remaining
defect to name in this section specifically — the low score this criterion earns is a correct
reflection of what the item actually is (the only P3, four-times-gated, money-losing-capable item in
the cluster), not a documentation gap. I do not deduct further here beyond what that honest
structural ceiling already imposes.

## Per-criterion points (cap in parentheses)

- Fidelity to the gap and completeness (20): **16** — re-scopes MP-B correctly and adds the
  edge-gate artefact; `max_equity_fraction` deferral is a recorded decision, not silent. Matches the
  author's assessment; not separately docked further.
- Technical correctness and evidence grounding (20): **15** — every load-bearing citation
  independently re-verified this round and holds exactly (native notional cap, gate-loader idiom,
  executable-gate source, session-order-count derivation). Docked 3 below the author's 18 for the
  pre-merge sweep's unspecified relationship to the operator cap — this is the single artefact this
  item's merge gate is built on, and its methodology is not evidence-grounded as written.
- Implementation specificity and feasibility (15): **10** — docked further than the author's 13:
  the gap above is not merely "specified by intent rather than by harness" (the author's own
  self-criticism of 7a) — it is a gap in what the harness would even compute, since the input
  variable at the center of the sweep is one the item may not read.
- Acceptance criteria and validation quality (20): **15** — AC #6, the pre-merge merge-blocking
  criterion, cannot be objectively verified as specified because its methodology is ambiguous per
  the finding above. Every other AC (byte-identity, property test, gate negative-controls, cohort
  review) is measurable and well-formed.
- Autonomous operation, failure handling, recovery (15): **13** — matches the author's assessment;
  fail-closed gates and clamps, honestly partial rollback with a named compensating control (the
  bounded cohort). No new defect found here.
- Portfolio objective alignment, scope, dependencies (10): **5** — matches the author's revised
  score; assessed fresh above, no further defect found, the low score is structurally correct for
  this item.

**Total: 74/100**

## Required changes to reach 100

1. Specify §7 step 7a's pre-merge sweep methodology precisely with respect to the operator-reserved
   cap — either a dimensionless, swept parameterisation (matching AUD-06a's own approach) or an
   explicit, reconciled statement of why reading the real cap in-process for this one gate does not
   violate §5's exclusion.
2. Once (1) is resolved, restate AC #6 so its Clopper-Pearson bound is over a well-defined,
   reproducible quantity (a swept curve or a named single distribution), not an underspecified
   "realised qty distribution."

## Blockers

Unchanged from round 1, correctly named and not resolvable by this review:
- **BLOCKER-A (build):** AUD-06a must ship first — see the mle-reviewer round-2 record for that
  plan; it is closer to ready but still carries required changes.
- **BLOCKER-B (build):** AUD-02 must publish a family-scoped edge estimate whose CI excludes 0.
- **BLOCKER-C (operator, R-12):** session order-count ceiling vs. the dollar cap.
- **BLOCKER-D (operator):** whether the current per-position cap value is still the intended
  per-order spend once qty is derived from it.
