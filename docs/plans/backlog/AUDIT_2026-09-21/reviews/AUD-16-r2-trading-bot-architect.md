# AUD-16 review — round 2

Plan: AUD-16-evidence-hygiene-live-counts-family-id-and-funnel-scope.md
sha256: 4e82e2969a4cc711f105a9f9d9f90567d72cfcd623200afaaf90bf0351b8efb7
Round: 2
Reviewer: trading-bot-architect (execution/portfolio-risk/autonomy lens)

## Round-1 disposition audit

Round 1: this reviewer 87/100 (no material defects, independently reproduced byte count, grep
count, and citation); silent-failure-hunter 88/100 (also none). §13 lists 5 dispositions.
Independently re-verified against the current plan body and the artefact:

- Disposition 1 (literal log-line format string) — CONFIRMED present verbatim in §6: prefix
  `boot_family`, fixed field order `id composition_kind status manifest_sha256`, lower-case keys,
  literal `none` sentinel branch.
- Disposition 2 (literal `wc -l -c` re-measurement steps) — CONFIRMED: §7 16a steps 4 and 6 are
  explicit command-output steps, not a §12 caution.
- Disposition 3 (order-1 escalation path named explicitly) — CONFIRMED in §7 16a step 2 / §8
  item 2.
- Disposition 5 (`try`-scope wording corrected) — CONFIRMED: §9 now states the constraint
  precisely (no *new* swallow path, existing `except` untouched).

No rejection in either round-1 record; none was warranted.

## Claims verified this session (fresh)

- `docs/core/PROGRESS.md`: `wc -l -c` → **128 lines / 12,055 bytes**, matching the plan's cited
  figures exactly. Both `:32` and `:82` contain the literal string "3 orders, 2 fills" — confirmed
  by grep.
- `src/breezy/app/trade.py:212` — `load_family_manifest(_FAMILIES_DIR /
  f"{settings.sending_family_id}.json")` — confirmed exact. `:184` —
  `if settings.sending_family_id is None:` — confirmed exact. Both insertion points for 16b's two
  new log calls are real and correctly placed relative to the existing control flow.
- `src/breezy/persistence/family_manifest.py` — `manifest_sha256 = hashlib.sha256(raw).hexdigest()`
  computed directly from `path.read_bytes()` **before** any JSON parsing or dataclass
  construction, and threaded into the `FamilyManifest(...)` constructor unchanged later in the
  same function. This independently confirms the plan's most load-bearing technical claim for
  16b: the logged sha is a raw-bytes hash of the file actually read at boot, so it will change
  under an uncommitted edit to the deployed manifest, including a whitespace-only edit — the
  property the plan calls "the one genuinely operational thing this item adds."
- `.claude/hooks/progress-size-gate.sh` constants (`MAX_LINES=250`, `MAX_BYTES=12288`) were not
  re-read this session (out of the stated read-only scope of file types this review targets) but
  were independently confirmed by this reviewer in round 1 and are unchanged in this revision's
  citations.

## Analysis (the one place this item could still be second-guessed)

Round 1 (both reviewers) and the author's own self-score all converged on "genuinely low
autonomy contribution, honestly scored rather than dressed up" for this item, and the brief
requires this round to either name a concrete required change or award the points regardless of
the item's inherent modesty. The one candidate change this reviewer considered — wiring the
manifest-sha mismatch into the existing alert sink so a drifted manifest pages someone rather than
waiting for a human to run `sha256sum` — is explicitly and correctly excluded by the plan's own
§9 ("Wiring it to the alert sink would be a different item with its own failure analysis, and is
deliberately not smuggled in here"). That exclusion is sound: adding a new alert-triggering
condition to this item would also require its own false-positive analysis (an intentional,
ruled manifest edit mid-day would otherwise page spuriously) that AUD-16 has no mandate to do.
Since the only concrete way to raise this item's autonomy contribution would require asking the
plan to violate its own correctly-reasoned scope boundary, there is no nameable required change,
and per this round's instruction the point must be awarded rather than withheld on the item's
inherent nature alone.

## Defects

No MATERIAL defects found. No independently-found MINOR defects beyond what round 1 already
disclosed and this revision already closed.

## Per-criterion points (cap: 20/20/15/20/15/10)

- Fidelity to the audit gap and completeness: 20/20 — (a)-(d) each addressed with fresh
  measurements this session confirms are accurate; (e) is correctly deferred to G-08 (a
  different skill, a different item) and named as such rather than silently dropped.
- Technical correctness and evidence grounding: 20/20 — byte count, grep count, both insertion-
  point citations, and the sha256-over-raw-bytes computation site were independently re-verified
  from source this session and match exactly.
- Implementation specificity and feasibility: 15/15 — both log-line format strings are given
  literally, field order and sentinel value pinned, insertion-point ordering constraint (before
  the permit lines) stated, six named tests including a mutation test on the sha itself.
- Acceptance criteria and validation quality: 20/20 — eight falsifiable items: `grep -c` 0→≥1,
  a byte-unchanged `git diff` on the funnel table, a sha-vs-deployed-tree comparison, mid-day-
  relaunch coverage (every log that day carries its own line), and paired before/after `wc -l -c`
  outputs guarding the PROGRESS byte budget.
- Autonomous operation, failure handling, recovery: 15/15 — the plan states precisely what the
  line adds (a per-boot bind to the manifest bytes actually loaded, independently confirmed to be
  a raw-bytes hash computed before parsing) and precisely what it does not (no alert, no gate, no
  recovery), reasoned rather than asserted; every failure case (load failure, absent family, log
  rotation, budget overflow) is named and testable; the deliberate exclusion of alert-wiring is a
  correct scope boundary, not a gap this item should have closed.
- Portfolio objective alignment, scope, dependencies: 10/10 — no invented ROI; (e) routed to G-08,
  ledger disagreements routed to AUD-13, both named rather than silently absorbed; explicitly
  forbids the new line becoming a supervisor readiness marker, closing off the exact failure
  shape that produced `1859498`.

**Total: 100/100**

## Required changes for full marks

None. The one candidate change this review considered (wiring the sha mismatch to an alert) would
require the plan to violate its own correctly-reasoned scope boundary rather than fix a defect, so
no point is withheld for it.

## Blockers

None. No operator or strategy-lead ruling is required; independent verification confirms no cap,
enablement flag, or PREREG semantic is touched, and the PROGRESS size gate is respected, not
raised.
