# AUD-10 — Review record (Round 7, delta on the in-place-edited final revision)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-10-evidence-gated-promotion-proposal.md
- Plan file sha256: 7bfea8e92b7a6e822b200122c8706cbcbd81571ac0f021329eb1ec3398ee4f2f
- Round: 7 · Reviewer: trading-bot-architect (promotion-gate/risk-architecture lens)
- Total: 100/100 · Readiness: READY

## Round-6 finding verification

My round-6 review scored this plan 99/100 for one self-found MINOR: §11's compound-limit paragraph
claimed both `INERT` dependencies were "out of this item's scope (§5)", but §5's exclusion list only
had a bullet for `C-PAIRED`'s dependency (`--family-manifest`), not for `C-KILL`'s (the live-tally
wrapper's champion-scoping). Required change was to add a mirroring §5 bullet, or narrow the
citation.

## Edit 1 verified — new §5 bullet

Confirmed present, placed directly after the `--family-manifest` bullet:

> **Standing up a champion-scoped KILL clock.** No change to `deploy/systemd/score-live-trials-run.sh`
> or its hard-coded `FAMILY_MANIFEST` (`:47`), and no second counter invocation — the dependency
> `C-KILL` would need. Named as a dependency (§6b.3, §11, §12; owner PROGRESS R-4 / AUD-05), not
> taken here.

I re-read `deploy/systemd/score-live-trials-run.sh:40-47` myself: `FAMILY_MANIFEST="$REPO/deploy/
families/pm_us_crh_v2.json"` is exactly at line 47, confirming the citation. The bullet's "no second
counter invocation" clause is consistent with §6b.3's *Whose KILL clock is it?* text, which rejects
exactly that option ("computing a champion-scoped counter inside AUD-09b's wrapper... stands up a
second KILL clock the round-3 binding expressly refused") — the two passages do not contradict each
other, they state the same rejected alternative from two places for two different reasons (§6b.3:
memory-envelope/second-clock; §5: this is out of scope regardless).

## Edit 2 verified — §11 sentence

Now reads: *"Both `INERT`s are the expected steady state recorded in **C8**, tested by **C14**
(`C-PAIRED`) and **C17(g)** (`C-KILL`), excluded from this item's scope by the two §5 dependency
bullets, and named with owners in §12; neither is ever `true`, ever `false`, or ever read as
permission."* I checked each clause against its target:

- **C8** — confirmed it records both `C-PAIRED` (`NO_CHALLENGER_REPLAY_PATH`) and `C-KILL`
  (`NO_CHAMPION_SCOPED_KILL_CLOCK`) as the reachable steady state.
- **C14 tests `C-PAIRED`** — confirmed: C14's text is specifically "`C-PAIRED` is emitted as `INERT`
  with `inert_reason="NO_CHALLENGER_REPLAY_PATH"`... and a run containing an `INERT` predicate can
  never emit `PROPOSAL`" — the predicate-specific assertion is about `C-PAIRED`, matching the
  parenthetical.
- **C17(g) tests `C-KILL`** — confirmed: arm (g) is exactly the manifest-identity check that yields
  `C-KILL = INERT` / `NO_CHAMPION_SCOPED_KILL_CLOCK`.
- **"excluded... by the two §5 dependency bullets"** — now literally true: §5 has exactly two
  dependency bullets (`--family-manifest` for `C-PAIRED`, the new bullet for `C-KILL`), verified by
  direct count.
- **"named with owners in §12"** — confirmed both entries present: the `C-PAIRED` BLOCKER ("owner:
  whoever takes the promotion loop past its first proposal") and the `C-KILL` DEPENDENCY ("owner:
  whoever owns the live-tally unit"), both re-read this round and unchanged from round 6.

This closes the round-6 finding completely, not by rewording but by making the citation true.

## Check nothing regressed

Re-read §6b.3's full `C-KILL` binding table (champion-scope rule, the seven-key artefact binding,
the max-age rule), C8, C14, C17 in full, and both §12 dependency entries. All byte-identical to what
I verified in round 6 except for the two named edits. The evidence-artefact line still reads
"C1–C19"; the abandonment criterion's re-gating (round-5 10-7) is untouched; 10a's six-site
disposition table, C15's seven-refusal-shape fix, C18's boot-log pin, and C10==B10 are all unchanged.

I also checked for a new instance of the same class of defect: does any other self-referential
citation in the file now claim something not literally true? Scanned every "(§5)", "(§12)", "(§4)"
parenthetical citation touching `C-PAIRED`/`C-KILL` in §4, §6b.3, §9, §11 and §12 — all consistent
with each other and with source. Found none.

## Defects

None found in this revision.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | Unchanged; the item's reachable steady state and retirement rule are both correctly and now fully self-consistently described. |
| Technical correctness and evidence grounding | 20 | 20 | The round-6 imprecise citation is now literally accurate; every clause of the revised §11 sentence checked against its cited target and found exact. |
| Implementation specificity and feasibility | 15 | 15 | Unchanged; the `C-KILL` binding remains decided to the line. |
| Acceptance criteria and validation quality | 20 | 20 | Unchanged; C1–C19 objective and consistently cited. |
| Autonomous operation, failure handling, recovery | 15 | 15 | Unchanged; `INERT` remains non-permissive by construction on both predicates. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | The new §5 bullet makes the scope exclusion complete and symmetric with the existing `C-PAIRED` bullet; no defect found here. |
| **Total** | **100** | **100** | |

## Required changes to reach 100

None.

## Blockers (recorded, not scored)

- **Strategy lead — 10b cannot be judged *correct* without a ruling:** R5-7/R5-8 were written for a
  family under a programme ruled terminally CLOSED.
- **Strategy lead:** whether a `MECHANISM_ONLY` result may feed any criterion (default: no).
- **Externally-owned dependency:** a deployed wrapper that counts the armed family — PROGRESS R-4,
  owner = the live-tally/`score-live-trials` owner. Until then `C-KILL` is `INERT`.
- **Deferred change with a named owner:** `--family-manifest` on the replay driver; until then
  `C-PAIRED` is `INERT`.
- **Operator:** arming, live enablement, the two reserved caps — named, untouched.
