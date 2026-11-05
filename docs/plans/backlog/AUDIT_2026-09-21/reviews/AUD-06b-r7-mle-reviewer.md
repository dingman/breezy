# AUD-06b review — round 7 (delta, FINAL) — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-06b-bounded-allocation-sizing.md
sha256: 5a75991eec475c719745aebc5fa43a32d3c4b2b62f21fe2b9c940dca425a7ae0
Round: 7 (delta review of the ruling application: RULING 2 + addendum A2 for BLOCKER-C/D; RULING_A1 for BLOCKER-B)

## Ruling application verified faithful and complete

**Citations independently re-verified against source, all exact:** `_derived_session_order_count`
def at `safety.py:591` (`:591-606`); `_session_count` def at `:621` (`:621-625`, body exactly 4
lines); `remaining_order_count=budget_orders` at the fresh-mint site, `:737` (`:735-738`);
`seed_permit_budget_from_prior_spend` def at `:781` (`:781-792`), docstring text "which counts orders
this permit itself authorises, not prior-process spend" at `:788-789` — quoted verbatim in both the
ruling and the plan; `DailySpendLedger.seed_spent` def at `operator_controls.py:306` (`:306-331`);
the lock at `:342` (`:341-345`); `authorize_order_cost` def at `:347` (`:347-426`).

**Faithfulness checklist:**
- Count ceiling **KEPT** as a per-PROCESS bound, with residual R2-a reproduced in §12 — CONFIRMED
  faithful: every substantive clause of addendum A2's R2-a (durable dollar reseed vs. full-reset
  order-count on mint, "per-process not per-day," "ACCEPTED as fail-closed," "not made durable," both
  numbered conditions) is present with identical citations; the wording is a close paraphrase rather
  than a character-for-character quote, but nothing is omitted, softened, or altered in substance.
- Explicit session-count override pinned absent — CONFIRMED, new test
  `test_no_shipped_unit_or_env_template_sets_the_explicit_session_count_override` matches RULING 2
  point 2's requirement exactly (asserts absence of the variable NAME only, reads no operator file).
- **Three new RED tests, matching count and content exactly:**
  `..._named_distinctly_from_a_budget_stop` (RULING 2 §2.3 point 3), `..._valueless_sized_to_cap_event_once`
  (addendum A2's BLOCKER-D condition), `..._session_count_override` (RULING 2 point 2) — plus AC #7e
  (covering the first two) and AC #7f (covering the third), both present.
- BLOCKER-D closure stated as **CONDITIONAL**, not a no-op, on the valueless
  `ORDER_SIZED_TO_POSITION_CAP` event, logged and alert-delivered, deduped to the first cap-sized
  order, carrying no qty/price/cost/fee — matches addendum A2 exactly, including the "detector without
  delivery is not a control" discipline already established elsewhere in this backlog.
- BLOCKER-A unchanged: pure sequencing behind AUD-06a's envelope + staleness predicate.
- BLOCKER-B re-grounded exactly as the coordinator described: `pm_us_crh_v4` may not send orders per
  `RULING_A1...`; the edge estimate is now owned by AUD-18 (cited by id/path only, no outcome
  assumed); execution is blocked until an AUD-18 hypothesis is CONFIRMED **and** a new family is
  registered to carry it — correctly characterized as an evidence precondition, distinct in kind from
  BLOCKER-A's pure sequencing.
- **No cap value stated or implied anywhere:** the previous revision's "~$0.30" per-order estimate
  (old BLOCKER-D text) is removed and not reintroduced; grepped the full diff for dollar figures —
  the only match is the deletion itself. The "10-order cohort at qty ≤ 2" figures are the
  already-established dimensionless build-side constants, not cap-derived.

## Fresh review — no new defect found

I checked whether re-grounding BLOCKER-B on AUD-18 introduces any inconsistency with G2's edge-artefact
interface (unit convention, CI-excludes-zero gate, structural `|edge| <= 1.0` sanity bound): all three
are correctly re-attributed to "the edge-artefact producer's interface — AUD-18" without altering the
gate's mechanics, so the fail-closed sizing gate itself is untouched by the re-grounding — only the
producer's identity changed, which is exactly what RULING_A1 requires and nothing more. I also checked
that the gate-check step (§7 step 0) now additionally asserts the sized family is "registered and
permitted to send orders," correctly excluding `pm_us_crh_v4` — this is a genuine strengthening (a gate
that could previously have been satisfied by re-pointing at the halted family alone) added as a direct,
correct consequence of RULING_A1's "may not send orders" clause, not merely restated prose.

## Per-criterion points (cap in parentheses)

- Fidelity to the gap and completeness (20): **20** — both rulings applied completely, with every
  named consequence (ceiling kept, override absent, R2-a, conditional BLOCKER-D closure, AUD-18
  re-grounding) present in the plan body, not just in §13.
- Technical correctness and evidence grounding (20): **20** — every citation independently re-verified
  exact; no cap value stated or implied.
- Implementation specificity and feasibility (15): **15** — the three new tests and two new ACs are
  concretely specified with clear positive/negative controls.
- Acceptance criteria and validation quality (20): **20** — AC #7e/#7f are objectively testable and
  correctly scoped to the ruling's exact conditions.
- Autonomous operation, failure handling, recovery (15): **15** — unaffected; unchanged from round 6.
- Portfolio objective alignment, scope, dependencies (10): **10** — unaffected; the re-grounded
  BLOCKER-B, if anything, makes the item's honest low-priority framing more accurate, not less.

**Total: 100/100**

## Remaining defects and required changes

None found this round.

## Blockers

- **BLOCKER-A (AUD-06a):** the validated qty envelope and its staleness predicate — unchanged, genuine,
  pure sequencing.
- **BLOCKER-B (evidence precondition):** an AUD-18 CONFIRMED edge hypothesis plus a newly registered
  family to carry it — genuine, cannot be manufactured by any ruling, correctly not resolvable by this
  item.
- BLOCKER-C and BLOCKER-D are CLOSED build-side by `RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md`
  RULING 2 (as amended by addendum A2) — BLOCKER-D's closure is conditional on the
  `ORDER_SIZED_TO_POSITION_CAP` event shipping with this item, not a standing blocker.
