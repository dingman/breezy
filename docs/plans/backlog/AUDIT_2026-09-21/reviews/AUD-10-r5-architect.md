# AUD-10 — Review record (Round 5, FINAL)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-10-evidence-gated-promotion-proposal.md
- Plan file sha256: dceb37d75d733ed556fd1d8e6bc3e9d332739006235b3e4713228962f9a5cd55 (coordinator recorded dceb37d7…)
- Round: 5 (delta) · Reviewer: architect (code-architect lens)
- Total: 96/100 · Readiness: NOT READY on one §11 correction (no design change required)

## Round-4 dispositions, verified against the plan body AND against source

| R4 defect | Claimed | Verified? |
|---|---|---|
| **10-5 (MATERIAL)** — `C-KILL`'s provenance rule binds the clock to the champion manifest while the deployed counter JSON is v2-scoped ⇒ permanent refusal and a cross-family verdict; the cited "mirror" does not say what was claimed | ACCEPTED IN FULL, option (c) | **FIXED, and option (c) is the right choice.** The new **champion-scope rule is evaluated FIRST**: the file's `manifest_sha256` is compared to the champion manifest's (`family_manifest.py:185`, computed over the file's raw bytes at `:220`; written from `manifest.manifest_sha256` at `structural_dead_stop.py:349` — I re-read `:347-349` and both halves are exact); unequal ⇒ literal `INERT` / `NO_CHAMPION_SCOPED_KILL_CLOCK`, **never `true`, never `false`, never a `structural_dead` read**, and **C14** already bars `PROPOSAL` on any `INERT` — so a missing champion-scoped clock is a standing bar that says why, never permission. The **ordering** is stated and tested (a wrong-family file's age and coverage say nothing about the champion), which is the subtle half I would have flagged had it been left implicit. The rejections are argued, not asserted: (a) would use the wrong-family error *as* permission — the very error §11 exists to control; (b) would stand up a second KILL clock via an unbounded catalog scan inside a 3G/4G cgroup. The **provenance rule is correctly re-framed** as a cheap integrity cross-check that applies only after the sha matches (true: once `manifest_sha256` matches, `fetch_start`/`stations` come from the same manifest at `:347-349`), and the false "mirrors `score-live-trials-run.sh:152-160`" claim is **explicitly withdrawn with the real reading given** — that wrapper compares `fetch_start` to the hard-coded `V1_D0_LITERAL="2026-09-05"` (`:62`, `:157`). I re-verified the underlying facts: `:47` hard-codes `pm_us_crh_v2.json`, passed at `:125`; `pm_us_crh_v2.json:5` is `2026-09-05` vs `pm_us_crh_v4.json:5`'s `2026-09-20`; the wrapper's `:40-46` comment does say the pin "stays v2-scoped only, tracked separately (R-4, SP-1 I5)". **C17 now has seven arms**, (g) generated from the v2 manifest so it is byte-for-byte what deployment writes, and two fixtures are produced by actually invoking `structural_dead_stop.py --family-manifest` — pinning the arms to deployment rather than to hand-built JSON. **C8 is restated** and is now *reachable* on today's tree. **§12's new DEPENDENCY entry** is exact, cites **PROGRESS R-4** (`docs/core/PROGRESS.md:73` — I read it: *"the v3 tally MUST receive a v3-scoped count (own `--family-manifest …`, never v2's JSON); today no unit runs the v3 tally at all"*), cites **AUD-05 by id only** with no assertion about its content or schedule, names the owner, and states that `C-KILL` becomes evaluable **with no change to this plan**. Line ranges corrected (`:115-129`, `:111-132`, `:297-330`). |
| **10-6 (= AUD-09 09-5)** — the emission line contradicts AUD-09's wrapper count | ACCEPTED | **FIXED from both sides.** §6b.4 carries the property over a named script set, §10 restates it, and **C19** tests it from this side (named scripts only, the proposal invocation inside the host-wide `breezy-studies.lock` and after the replay, no JSONL parsing, no `record_blocked`), deliberately duplicating AUD-09's B18 "so neither item can land a wrapper edit that silently breaks the other's criterion". I diffed the normative sentence against AUD-09 §6b.3: **character-identical**. Evidence artefact updated to C1–C19. |
| **c1 (MINOR)** — two line ranges drifted | ACCEPTED | **FIXED** at all three sites, each with the correction called out. |

10a is untouched and still exact (six `SUPPORTED_STATIONS` sites with dispositions, the `:319` guard-domain
narrowing, the non-`app` caller enumeration, C4's attainable grep). C15's seven refusal shapes with the
base-class catch and the `__bases__` pin, C18's boot-log pin, and C10 == B10 are unchanged.

## The coordinator's question, judged: is the INERT steady state stated honestly?

**Yes in the binding sections, no in §11 — and §11 is where a reader looks for the item's value and
its retirement rule.** Honest and complete: §4 (`C-PAIRED`'s dependency "is not scheduled"), §6b.3's
*Whose KILL clock is it?* (both `INERT`s, both `inert_reason`s, the owner, PROGRESS R-4, AUD-05 by id
only, "becomes evaluable with no change to this plan"), **C8** (the expected steady state now records
**both** `C-PAIRED` and `C-KILL` `INERT`), **C14** (any `INERT` bars `PROPOSAL`), **C17(g)**, §9 and
two §12 entries with owners. Nothing anywhere claims a working promotion path in those sections.
§11, however, was not revised with them — see 10-7.

## Defects found in revision 5

**10-7 (MATERIAL, NEW) — §11 was not updated alongside the INERT decision, so the one section that
states this item's value and its retirement rule now misdescribes its reachable outcomes, and its
abandonment criterion would fire for an upstream cause.** Three concrete problems:
1. **Stale enumeration.** §11 lists the reasons the output will be `NO_PROPOSAL` as *"no proven edge,
   admissible n = 0, forecast programme closed, and (round 3) `C-PAIRED` inert"* — **`C-KILL` INERT is
   absent**, although it is now the second standing bar and is recorded in C8 and §12. "How it will be
   evaluated: **by C1–C16**" is also stale (C17–C19 exist, and the evidence artefact line two sections
   later correctly says C1–C19).
2. **The compound limit is never stated in one place.** With both predicates `INERT`, `PROPOSAL` is
   **unreachable until two independent, externally-owned changes land** (a champion-scoped KILL clock
   from the live-tally owner; `--family-manifest` on the replay driver). Each dependency is stated
   separately and well; their *conjunction* — "until then this is a refusal engine, not a promotion
   path" — is never said, and §11 is where it belongs.
3. **The abandonment criterion is now wrong.** *"If after two real promotion decisions the proposal is
   ignored or overridden both times … retire it."* While `PROPOSAL` is unreachable the generator can
   only ever say "do not promote", so any human promotion is an override **by construction**. The rule
   would mechanically retire the gate after two decisions for a reason that has nothing to do with the
   criteria's quality — it would retire a correct gate for a missing upstream unit.
REQUIRED: in §11, (a) add `C-KILL` to the inert list and correct "C1–C16" to "C1–C19"; (b) state the
compound limit explicitly with its two owners — that no run can emit `PROPOSAL` until both land, and
that the item's deliverable until then is a **machine-checked refusal with reasons**; (c) gate the
abandonment criterion on the condition that actually tests the criteria — e.g. it starts counting only
once both `INERT`s clear, or it is restated as "ignored/overridden on a decision where every predicate
was evaluable". No design change is required; this is the plan's own §11 catching up with §6b.3/C8/§12.

**c1 (MINOR, NEW) — the "character-identical in AUD-09 §6b.3" claim does not hold.** The two §6b.4 /
§6b.3 paragraphs differ in lead-in and closing (this one adds *"an unnamed fourth still fails. This
item carries C19…"*); only the **bolded property sentence** is identical — which I verified word for
word, so no contract drifts. But these self-identity claims are the plans' own drift-detection
mechanism (`C10 == B10`, the §6c tables, H1/H3), and one that fails a literal diff devalues it.
REQUIRED: scope the claim to the property sentence, or make the paragraphs identical — mirrored in
AUD-09.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | 10a closes REG-1 across all six sites and closes the zero-strategy boot path; 10b binds every predicate to a real artefact, and the steady state is now **reachable** rather than a permanent refusal. −1: §11 still frames the item as a promotion path and omits the compound limit (10-7). |
| Technical correctness and evidence grounding | 20 | 18 | The champion-scope rule, the `manifest_sha256` provenance chain, the re-framed integrity check, the withdrawn mirror claim, PROGRESS R-4's wording, the v2/v4 d0 values and all three corrected line ranges verified exact at source. −1 for §11's stale enumeration (10-7), −1 for the false character-identity claim (c1). |
| Implementation specificity and feasibility | 15 | 15 | The `C-KILL` binding is decided to the line — artefact, keys, reader, max-age, champion-scope test, evaluation **order**, and the `evaluable`-before-`structural_dead` rule — and two C17 fixtures are generated by invoking the shipped script, so nothing is left for the implementer to infer. |
| Acceptance criteria and validation quality | 20 | 20 | C1–C19 objective. C17's seven arms are the right seven and none is permissive; (g) pins identity *and* ordering; C8 is two-way and now satisfiable; C14/C15/C16/C18/C19 unchanged and sound. |
| Autonomous operation, failure handling, recovery | 15 | 15 | `INERT` is non-permissive by construction and cannot be reached as a verdict; stale, absent, not-evaluable and wrong-family are four distinct, named, non-permissive outcomes with a stated precedence; content-hash idempotency; read-only posture; generator failure still surfaces through the host unit, whose stall mode AUD-09's B19 now covers. |
| Portfolio objective alignment, scope and dependencies | 10 | 9 | Zero-ROI honesty, the correctness benefit named as correctness, both strategy-lead blockers kept verbatim, the new dependency named with an owner and cited to PROGRESS R-4 + AUD-05 by id only, arming/caps/NO-SEND untouched. −1: the abandonment criterion would retire a correct gate for an upstream cause (10-7 item 3). |
| **Total** | **100** | **96** | |

## Required changes to reach 100
1. Update §11: add `C-KILL` to the inert list, correct "C1–C16" → "C1–C19", state the compound
   "no `PROPOSAL` until both externally-owned dependencies land" limit with its owners, and re-gate
   the abandonment criterion on decisions where every predicate was evaluable (10-7).
2. Scope the "character-identical" claim to the property sentence (c1), mirrored in AUD-09.

## Blockers (recorded separately; not scored)
- **Strategy lead — 10b cannot be judged *correct* without a ruling:** R5-7/R5-8 were written for a
  family under a programme ruled terminally CLOSED; whether they transfer, and what
  champion/challenger means at admissible n = 0, is a ruling. Correctly transcribed, not adapted, and
  tagged `SOURCE=FORECAST_FAMILY_R5`.
- **Strategy lead:** whether a `MECHANISM_ONLY` result may feed any criterion (default: no).
- **Externally-owned dependency (no plan change resolves it):** a deployed wrapper that counts the
  armed family — PROGRESS R-4, owner = the live-tally / score-live-trials owner. Until then `C-KILL`
  is `INERT`; the plan needs no edit when it lands.
- **Deferred change with a named owner:** `--family-manifest` on the replay driver; until then
  `C-PAIRED` is `INERT`.
- **Operator:** arming, live enablement, the two reserved caps — named, untouched, no value proposed.

_Saved verbatim by the coordinator: the `architect` reviewer has no file-write tool._
