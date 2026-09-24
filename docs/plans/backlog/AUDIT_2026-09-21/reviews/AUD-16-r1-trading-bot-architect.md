# AUD-16 review — round 1

Plan: AUD-16-evidence-hygiene-live-counts-family-id-and-funnel-scope.md
sha256: b3ce59867b3db5c8bfb891b1235bbf419be57d704bbf5f4f5bc1feb37f54e40c
Round: 1
Reviewer: trading-bot-architect (execution/portfolio-risk/autonomy lens)

## Claims verified

- (a) Stale live counts — CONFIRMED exactly: `wc -l -c docs/core/PROGRESS.md`
  = 128 lines / 12,055 bytes (plan states the same); `PROGRESS.md:32` and
  `:82` both contain the literal string "3 orders, 2 fills" as cited.
- (b) Family id never logged — CONFIRMED: `grep -c pm_us_crh` on the latest
  node log (`breezy-trade-20260920T165028Z.log`) returns 0, matching the
  plan exactly. `load_family_manifest(_FAMILIES_DIR /
  f"{settings.sending_family_id}.json")` is at `app/trade.py:212` as cited;
  the `settings.sending_family_id is None` branch exists a few lines earlier
  in the same function, consistent with the plan's citation of `:184`.
- The plan's proposed log line placement (immediately after the manifest
  loads, before the permit lines) is consistent with the function's actual
  control flow read via codegraph: the manifest load happens inside the
  `sending_family_id is not None` branch, well before the permit-issuance
  block later in the same module.
- The scope boundary against AUD-14a (different process — node vs.
  supervisor, different field) is real and non-overlapping; no shared file
  is touched by both.

## Analysis

The plan is honest and conservative about what it has NOT verified: it states
plainly that it could not read the sqlite ledger this session ("no sqlite3
binary available") and explicitly forbids copying the audit's agent-reported
"7 orders / 6 fills" into PROGRESS.md, instead requiring the implementing
session to re-derive the count from logs + ledger. This is the correct
discipline for an item whose entire subject is stale/unverified figures —
repeating an unverified number into the file whose staleness is the gap would
reproduce the defect with a newer number, and the plan says so explicitly.

The PROGRESS.md byte-budget constraint (233 bytes headroom against a
12,288-byte hard gate) is real and independently confirmed; the plan
correctly refuses to raise the budget and instead requires a paired
consolidation, with a "re-measure before editing, a sibling session may have
consumed it" caution — appropriate for a shared, size-gated file.

## Defects

No MATERIAL defects found. No additional MINOR defects found beyond the
author's own disclosures (unread ledger; exact rendered log-line format left
to the implementer).

## Per-criterion points

- Fidelity to the audit gap and completeness: 17/20 — (a)-(d) each directly
  addressed with fresh measurements; (e) correctly deferred to G-08 rather
  than absorbed, and stated as such.
- Technical correctness and evidence grounding: 19/20 — every checked claim
  (byte count, log grep, code citation, manifest-load line) reproduces
  exactly at HEAD.
- Implementation specificity and feasibility: 13/15 — insertion point, field
  set, ordering constraint, and the None branch are all concretely named.
- Acceptance criteria and validation quality: 18/20 — falsifiable
  (`grep -c` 0→≥1, byte-unchanged funnel table via `git diff`, size hook must
  not fire); live-proof item lands a day after merge.
- Autonomous operation, failure handling, recovery: 11/15 — correctly bounded
  (cannot halt a boot, cannot become a readiness marker) but genuinely adds
  little autonomy value, honestly scored low by the author rather than
  dressed up.
- Portfolio objective alignment, scope, dependencies: 9/10 — no invented ROI;
  disagreements between logs and ledger correctly routed to AUD-13 rather
  than resolved here.

**Total: 87/100**

## Required changes for full marks

- None material.

## Blockers

None. The plan correctly states no operator/strategy-lead ruling is required;
independent verification confirms no cap, enablement flag, or PREREG
semantic is touched.
