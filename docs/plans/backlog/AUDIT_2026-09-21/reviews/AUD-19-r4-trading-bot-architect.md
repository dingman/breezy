# AUD-19 round 4 review — trading-bot-architect

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-19-family-manifest-flag-on-replay-driver.md
sha256: 6e1dfec7b3303156b7636cbc3cfcc096e792336da6a5655f50c306d69e543cf7
Round: 4

## Round-3 reconciliation defects: verified fixed
- **Exit codes (A17/C7):** `EXIT_OK=0`, `EXIT_FAMILY_MANIFEST_REFUSED=2`, `EXIT_FAMILY_MANIFEST_UNUSABLE=3`
  citations confirmed exact — `clear_family_halt_cli.py:46-48` (`EXIT_OK=0`,`EXIT_REFUSED=2`,
  `EXIT_NOTHING_TO_CLEAR=3`), `clear_submit_intent_cli.py:28-30`, `check_alerts_cli.py:51-53`
  (`Final[int]` pattern) all verified against source. No existing path's code changes (still raise-
  and-propagate to CPython's `1`). FIXED.
- **A16 machine-checkable:** `test_the_cited_aud09_anchors_still_exist` now asserts against text/
  symbols rather than relying on a prose note; note retained only as supplementary human record. FIXED.
- **§4 stale wording:** rewritten with per-increment P2 rationale for 19a/19b/19c. FIXED.

## Other reviewer's MATERIAL: verified fixed
E3's blanket "any non-zero driver exit → BLOCKED, day stays queued" is replaced by an exit-code
dispatch table. Confirmed against source: AUD-09 §9 (`:892-896` region) names exactly the three
FAILED-class exceptions cited — verified present in source at `NoDecisionWindowCoverageError`
(`current_rung_hold_paper_replay.py:195`), `EntryAskFromLatchMissingError` (`:180`),
`ImpossibleFillPriceError` (`paper_replay.py:131`) — and the "must never be swallowed" quote matches
verbatim. `:546`/`:703` (`record_blocked`, closed `blocked_reason` set) also confirmed. The old E3
would genuinely have converted an engine crash into a permanently re-queued `BLOCKED` row (the exact
silent-stall class the repo has paid for before); the new table correctly routes exit `1` into AUD-09's
own FAILED classification untouched, dispatches on `returncode` not message text, and D6 honestly
flags that AUD-09 defines no rule for an unclassified exit code rather than inventing one silently. FIXED.

## Sweep
No new defect found. D6 is properly flagged-for-review (not silently decided) and its fallback
direction (unclassified → FAILED-class, day leaves queue) is reasoned from AUD-09's own N3 design
intent rather than asserted.

## Per-criterion points
- Fidelity to audit gap and completeness: 20/20 (unchanged)
- Technical correctness and evidence grounding: 20/20 (every new citation this round verified exact)
- Implementation specificity and feasibility: 15/15 (unchanged)
- Acceptance criteria and validation quality: 20/20 (A16's prior gap closed; A14/A17 close the crash-misclassification and exit-code gaps)
- Autonomous operation, failure handling and recovery: 15/15 (exit-code vocabulary + crash/refusal dispatch closes both remaining gaps from rounds 1-3)
- Portfolio objective alignment, scope and dependencies: 9/10 (unchanged — one point held on inherent three-increment/seven-file scope size, not a textual defect; not further nameable beyond round-3's reconciliation)

**Total: 100/100 (post-reconciliation; see Scoring reconciliation section)**

## Blockers
None.

## Scoring reconciliation (coordinator-requested)
Re-examined the withheld portfolio point for a nameable defect: does bundling 19a with 19b/19c
genuinely harm the item, and is there a concretely better split?

Considered: split 19a into its own freestanding item (e.g. a new AUD-20, or fold into AUD-05, which
already owns the adjacent `live_family_tally.py` collision) so it can merge without waiting on 19c's
review cycles or on AUD-09b's runner existing. **Rejected as a genuine improvement, not merely
asserted:** 19a's `trial_id` collision is not live today — nothing replays a second family
concurrently until 19b's `--family-manifest` flag exists, so 19a carries no standalone urgency separate
from 19b; splitting it out would not let a real, currently-exercised defect land sooner, only
relocate inert code. The ruling itself (Q1 item 7, `:196-199`) frames 19a as the fix that gates the
flag item, and the plan's own coordinator decision ("AUD-19 owns it as AUD-19a, because AUD-19 is the
item the same ruling gates on it") states the rationale rather than asserting it. 19c's separate
gating (blocked on AUD-09b's runner) does not block 19a or 19b's merge — §4 already states "19a and
19b are complete and useful on their own." No alternative split was found that clearly beats the
current 19a→19b→19c sequencing; the "large scope" note from earlier rounds was not backed by a
nameable defect once traced through. **Restored: no defect nameable.**

Portfolio objective alignment, scope and dependencies: **9→10/10**.

**Final total: 100/100.**
