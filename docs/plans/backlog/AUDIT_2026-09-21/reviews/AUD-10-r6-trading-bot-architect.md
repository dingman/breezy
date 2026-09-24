# AUD-10 — Review record (Round 6, delta on the in-place-edited final revision)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-10-evidence-gated-promotion-proposal.md
- Plan file sha256: b4b90dc4c3f5a9e0c14f9b5b59d3ffdb0388c20e14d819f60fea2162424d62c9
- Round: 6 · Reviewer: trading-bot-architect (promotion-gate/risk-architecture lens)
- Total: 99/100 · Readiness: READY (one one-line MINOR outstanding, does not block)

## Round-5 defect verification

My round-5 review scored this plan 100/100 and missed **10-7** (MATERIAL, text-only) and a one-line
MINOR (c1, the same character-identity imprecision as AUD-09's b1). 10-7 is the more serious of the
two: §11 is the section a reader consults for this item's value and retirement rule, and it had not
been updated alongside the round-5 champion-scope `C-KILL` decision, so it (a) omitted `C-KILL` from
the `NO_PROPOSAL` reason list and cited "C1–C16" against an evidence artefact that already said
"C1–C19"; (b) never stated in one place that `PROPOSAL` is unreachable until **both** externally-owned
dependencies land; and (c) carried an abandonment criterion that would have retired a correct gate,
because while `PROPOSAL` is unreachable every human promotion decision is an override by construction.

## 10-7 fix verified against §4, §6b.3, C8, C14, C17(g), §9 and §12

I re-read §11 in full and cross-checked every claim it now makes against the sections it cites:

- **Opening paragraph** now names both `INERT`s with their literal `inert_reason`s
  (`NO_CHALLENGER_REPLAY_PATH`, `NO_CHAMPION_SCOPED_KILL_CLOCK`) and cites C8/C17(g)/§12 — I
  confirmed both literal strings appear identically at C8 (§8), C14 (§8), C17(g) (§8), §9's "No
  champion-scoped KILL clock" case, and both §12 entries (the `--family-manifest` BLOCKER and the
  KILL-verdict DEPENDENCY). No drift between any of these six sites.
- **The compound-limit paragraph** states `PROPOSAL` is unreachable until both dependencies land, and
  names both owners (the live-tally/`score-live-trials` owner for `C-KILL`, citing PROGRESS R-4 —
  confirmed at `docs/core/PROGRESS.md:73`, and AUD-05 by id only; the promotion-loop owner for
  `--family-manifest`, "owner as already named in §12" — confirmed, §12's BLOCKER entry names the
  identical owner). This is new information genuinely absent before, not a restatement.
- **The re-gated abandonment criterion** now counts only decisions "on which EVERY predicate was
  evaluable — no `INERT` anywhere in the run", with the override-by-construction reasoning stated.
  I checked this against C14 ("a run containing an `INERT` predicate can never emit `PROPOSAL`") —
  consistent: since `PROPOSAL` is definitionally unreachable while either predicate is `INERT`, gating
  the abandonment count on "every predicate evaluable" is the only rule that could ever let the
  criterion test what it claims to test.
- **C1–C19** is now used consistently at §11's two live-text sentences and at the evidence-artefact
  line (§8); the only remaining "C1–C16" is inside the round-3 self-score history table, which is
  correctly left verbatim as a historical record (the same convention this plan and its siblings use
  throughout §13) and is not live guidance.

This is a genuine, complete fix — not a rewording that leaves the underlying gap.

## c1 fix verified independently, byte-for-byte (identical method to AUD-09's b1)

I extracted the "every `\"$PY\"` invocation …" bolded property sentence from both this file's §6b.4
and AUD-09's §6b.3, whitespace-normalized both, and hashed the result:

```
normalized sha256: ce5b6d1d05e87b8e481dc204a13ecef253f6bcd1b55a69c78194bfd940a26263
```

Matches the coordinator's cited hash and confirms the property sentences are word-for-word identical.
§6b.4's heading now correctly scopes the claim to the bolded sentence, not the surrounding paragraph.

## New finding this round (MINOR) — §11's "(§5)" citation over-states what §5 contains

§11's compound-limit paragraph reads: *"Both are out of this item's scope (§5) and both become
evaluable with no change to this plan (§6b.3, §12)."* I read §5 in full: its "Explicitly excluded"
list has a bullet for `C-PAIRED`'s dependency — *"Any change to `current_rung_hold_paper_replay.py`,
including the `--family-manifest` flag `C-PAIRED` would need. Named as a dependency (§4, §6b.3, §12),
not taken here"* — but **no corresponding bullet for `C-KILL`'s dependency** (modifying
`deploy/systemd/score-live-trials-run.sh` / the live-tally wrapper to count the champion family). So
"(§5)" is accurate for `C-PAIRED` and not literally supported for `C-KILL`: a reader who follows the
citation to verify it finds one of the two exclusions, not both. This is the same class of finding as
c1 — a self-referential citation that does not fully hold on inspection — and, like c1, it costs
nothing in test coverage or design correctness: §12's DEPENDENCY entry and §6b.3's binding table both
state the owner and mechanism correctly and completely; only the §11→§5 pointer is imprecise.
REQUIRED: add one bullet to §5 naming the live-tally/`score-live-trials-run.sh` champion-scoping
change as excluded (dependency named in §11/§12) — mirroring the existing `C-PAIRED` bullet — or
narrow §11's citation to point only at §12, where the dependency is actually enumerated.

## Full re-scan for anything else of the kind

Re-read §4, §6b.3's full `C-KILL` binding table (including the champion-scope rule and *Whose KILL
clock is it?*), §9's KILL-clock failure cases, C8, C14, C17 and both §12 entries once more end to end
specifically hunting for other over-stated or under-stated cross-references. Found none beyond the
one above. 10a, C15's seven-refusal-shape fix, C18's boot-log pin, and C10==B10 remain unchanged and
correct.

## Defects

**MINOR (new)** — §11's "(§5)" citation for the `C-KILL` dependency's scope-exclusion is not fully
supported by §5's text (see above). Required change stated above; one line, author-resolvable,
touches no test or design decision.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | §11 now states the compound limit and both `INERT` reasons honestly; the item's reachable steady state and retirement rule are both correctly described. |
| Technical correctness and evidence grounding | 20 | 19 | Every citation I independently re-derived this round in §11 is exact against C8/C14/C17(g)/§9/§12/PROGRESS R-4. −1 for the imprecise "(§5)" citation (new finding, above). |
| Implementation specificity and feasibility | 15 | 15 | Unchanged; the `C-KILL` binding remains decided to the line, including the champion-scope test and its evaluation order. |
| Acceptance criteria and validation quality | 20 | 20 | C1–C19 objective and consistently cited in live text; C17's seven arms, C14's bar, C8's two-way reachable steady state all unchanged and sound. |
| Autonomous operation, failure handling, recovery | 15 | 15 | Unchanged; `INERT` remains non-permissive by construction on both predicates, with a stated evaluation order. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | The abandonment criterion no longer retires a correct gate for an upstream cause — the round-5 deduction is fully discharged. |
| **Total** | **100** | **99** | |

## Required changes to reach 100

1. Add a §5 bullet naming the live-tally wrapper's champion-scoping change as excluded (or narrow
   §11's citation to §12 only) — new MINOR finding, above.

## Blockers (recorded, not scored)

- **Strategy lead — 10b cannot be judged *correct* without a ruling:** R5-7/R5-8 were written for a
  family under a programme ruled terminally CLOSED.
- **Strategy lead:** whether a `MECHANISM_ONLY` result may feed any criterion (default: no).
- **Externally-owned dependency:** a deployed wrapper that counts the armed family — PROGRESS R-4,
  owner = the live-tally/`score-live-trials` owner. Until then `C-KILL` is `INERT`.
- **Deferred change with a named owner:** `--family-manifest` on the replay driver; until then
  `C-PAIRED` is `INERT`.
- **Operator:** arming, live enablement, the two reserved caps — named, untouched.
