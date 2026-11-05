# Review: BLOCKERS plan r1 (architect peer)
Verdict: REQUEST_CHANGES (three HIGH findings, B3/B4/B5; all fixable by deleting or narrowing text, nothing needs to be built)

## Per section

**B1: APPROVE with one LOW**
- [LOW] The completion criterion is "this section is committed in plan_r1.md" (plan_r1.md:34). That is circular: the plan becomes its own evidence. The PROGRESS line pointing to it is the real record, so make that line the only criterion.
- The route analysis is sound. T1 is not a send route, T3 is a pin, d2/α is a post-result change, and IOC drops the spread mechanism. Nothing is over-engineered.

**B2: APPROVE**
- The label/`r_lo` distinction is cited to code (maker_stage0_verdict.py:107-116, :173-176, :269-278). I did not re-verify those lines; the python-reviewer owns that check.
- The NOTE plus the PROGRESS:63 text fix is the minimum action. The step that compares CODE_SHA with HEAD with `git show` is proportionate.
- [LOW] PROGRESS.md is currently modified and uncommitted in the shared tree (git status `M`). The row-2 fix must commit only its own hunk, by explicit path, and must not sweep in another agent's work-in-progress.

**B3: REQUEST_CHANGES.** Keeping 300/200 is right. The spec v0.4 edit is not the simplest action.
- [HIGH] Do not edit the spec now; drop v0.4 entirely. Three reasons:
  - The S2 run pins the spec file's sha256 (`scripts/analysis/maker_stage0_pins.py:86,332`; `S2_stage0_replay_plan_r3.md:7` "The run pins the spec sha256"). Block 1 pinned v0.3. A v0.4 committed before the block-2 run on or after 11-04..11-06 means block 2 pins a different spec sha, which is a disclosed cross-block difference in a "same code" second look.
  - The S5 PREREG identity names `spec_sha256 (v0.3)` (`S5_shadow_run_and_gates_plan_r3.md:217`). A v0.4 forces an S5 plan-text change too.
  - The plan's own Risk (2) (plan_r1.md:86) already admits the pin question is unresolved, and the answer is in the repo: it is pinned.
  - **Simpler alternative:** the §9.15 table drift is already superseded by S5 r3 §8 (`:287-296`), which is the operative table. Record one PROGRESS decision line: "S5 300/200 kept; no sequential looks; §9.15 superseded by S5 r3 §8 (c unmeasured, upper bounds); reviewed 2026-10-19". If the spec text still needs fixing, do it in the spec bump S5 makes at freeze anyway, where the sha is re-pinned on purpose.
- [MED] The plan's own numbers drift. It quotes "r 0.10: 413" (plan_r1.md:78) but S5 r3:289 says 412. It also drops the spec's r=0.3 row (SPEC:391) without saying so. The drift-prone figures should be cited, not retyped. This is another reason not to edit.
- [MED] The "≈250 floor" reasoning (plan_r1.md:72) is flagged UNVERIFIED but still listed as a reason. Delete it. The decision stands on the ledger refusing interim looks (`hypothesis_ledger.py:1071-1075`) and on post-result timing alone.
- Open question 3: reject the PMR effective-n rule outright. Parking it as a "named option with a deadline" turns it into a live fork (spec §6.3 sets zero planned revisions, SPEC:258-260).

**B4: REQUEST_CHANGES.** One ruling with both outcomes pre-declared is the right shape, but the question is framed against the wrong text and the YES branch lacks a dated cutoff.
- [HIGH] The scope question rests on a misreading. R4's own text is "a new estimand that clears its power check at intake" (`RULING_RA-13_programme_kill_2026-09-27.md:53`). HUNT-1:38 is a citation there, not a scope limit. The "off-window" wording governs the trigger-4 re-open path in §1 (`RA-13:18`), not the programme backstop. B-5 makes 2027-01-25 a calendar backstop for R2–R4 generally (`RA-13:95`).
  - The ruling should rule on the literal R4 text and note HUNT-1:38 only as provenance. That collapses the Grok/architect/PMR split into a narrow, outcome-free question: is MAKER (spread capture, NO-ladder) a "new estimand"? Open question 2 then needs no S2/S3 clause: S2/S3 continue either way, as evidence (`S5_…_r4_delta.md:58`).
- [HIGH] The R4 event is undefined. E5 is a dry call (`S5_…_r3.md:31`), and S5 takes α "from the WP0 dry call" (`:223`). Nothing in S5 appends to `hypothesis_ledger.jsonl`. Yet "clears its power check at intake" means an AUD-18 registration, and S5 G4 asserts "α matches the ledger record" (`:198`).
  - The ruling must name the event: a REGISTERED record written through the existing `register_and_persist` path (`scripts/analysis/hypothesis_register.py:274-297`), with its ledger sha.
  - Past registrations each added pre-coded constants to `hypothesis_register.py` (`:141-233`), so this is one reviewed code row at freeze. The plan's "no code is built" scope (plan_r1.md:5) must list it as a deferred row, as it does for B6b.
- [HIGH] The YES branch has no cutoff. `S5_…_r4_delta.md:56` says the KILL stands "unless a separate dated R4 ruling lands **before**" 2027-01-25. The S5 freeze is assumed around 2026-11-23 but follows S2 (cap 11-15), S3 REACHABLE, WP0a and S4 entry evidence. Freeze day is not guaranteed before the horizon.
  - Pre-declare: "YES branch is void unless the ledger REGISTERED record and the R4 shell are committed on or before 2027-01-24; otherwise the KILL fires at the horizon."
- [MED] The "rule before 2026-11-06" date is correct but understated. The S2 first possible cross is around 11-04 (`S2_second_look_plan_r3.md:82`, "about 11-04 … to 11-06"). Use **before 2026-11-04**, the earliest expected E, so the ruling cannot follow any block-2 read. The cost is zero, since the ruling needs no outcome.
- [MED] The second calendar row duplicates an existing one: `PROGRESS.md:78` already reads "2027-01-25 | NO-TRADE ruling review; RA-13 KILL backstop". Add only the "≤ S5 freeze / ≤ 2027-01-24: R4 record or N/A" row.
- [MED] The day-60 date conflicts. The plan says about 2027-01-13 (plan_r1.md:102,182), but `S5_…_r3.md:298` says about 2027-01-22. Cite the S5 formula and don't restate a date.
- Over-engineering: none. The field list for the shell is appropriate (L-38 counter and cap).

**B5: REQUEST_CHANGES.** The dry call is the right minimal tool and the reuse of existing code is correct. The call grid creates a forking path.
- [HIGH] Running `programme_alpha_override` as both None and 0.025, and k as both 2 and 1 (plan_r1.md:134-135), lets a passing configuration be picked after the fact. That is the post-result pattern the invariants forbid (L-34).
  - α: RA-13 binds programme FWER at α=0.025 (`RA-13:5`), and the spec nests α in RA-13 (SPEC:334 v0.2 row). Pin the override at 0.025, one value.
  - k: `k_variants` counts design variants, not `MAX_RUNGS`. MAKER is one design (compare the k_variants=1 precedents, `hypothesis_register.py:154,183,214`). The plan's MDE triple (0.109/0.118/0.126) shows it set k_variants=2, which conflates rungs with variants.
  - **Simpler:** make exactly one call with k_variants=1, override 0.025 and min_station_days=200. Expected MDE is about 0.118 (UNVERIFIED until run).
- [MED] Run B5 first and gate B4 on it. With variance 0.25 on `MEAN_EXCESS_PER_TAKE`, an outcome-free bound below about 0.118 returns UNDERPOWERED (plan_r1.md:139). The spec's E_MIN of 0.10 (SPEC:333) suggests that is the likely outcome. If so, R4 is unreachable by B5's own rule (plan_r1.md:105), and B4 shrinks to a one-line "NO by E5 refusal" record.
- [LOW] Checking that the ledger mtime is unchanged is adequate, since `register_hypothesis` is pure (`hypothesis_ledger.py:873`). Opening the file read-only adds nothing.

**B6: APPROVE**
- (a) LEAVE is sound: it is fail-closed behind the permit window, and an allowlist row costs a reviewed code change. The flag is confirmed at `breezy-trade-supervisor.service:120`.
- (b) The DEFER is right: the census reads only `--catalog-root` (`maker_tape_census.py:515`), and the census argv flags are pinned by a test. A README note plus a PROGRESS line is the minimum.
- (c) No action is correct.
- No over-engineering.

## Cross-cutting
- **Invariant breaches:** none direct. The B5 α/k grid is a latent post-result breach (fix 7). The B3 spec edit risks an S2 pin change mid-block (fix 1).
- **Sequencing (corrected):**
  1. Now: B1, B2, the B3 decision line (no spec edit), and B6.
  2. B5: bound pin committed first, then one dry call.
  3. B4 ruling committed before 2026-11-04, taking B5 as input, and reduced to a one-line NO if E5 refuses.
  4. On S5 freeze: one reviewed `hypothesis_register.py` constants row, then a REGISTERED ledger append, then the R4 shell, all on or before 2027-01-24.
  5. After the S2 evidence commit: B6b.
- **Missing blocker:** the ledger-append code row behind any YES on R4 (see B4).

## Required edits
1. B3: delete spec v0.4; replace it with one PROGRESS decision line stating that §9.15 is superseded by S5 r3 §8 (`:287-296`).
2. B3: delete the UNVERIFIED "floor ≈250" reason and answer open question 3 with "reject outright".
3. B4: frame the question on R4's literal text (`RA-13:53`, "new estimand … power check at intake"), with HUNT-1:38 as provenance only.
4. B4: define the R4 event as a REGISTERED record appended through `register_and_persist`, which needs one reviewed constants row; list it in Scope as deferred.
5. B4: add "YES void unless the ledger record and R4 shell are committed on or before 2027-01-24".
6. B4: change the deadline to before 2026-11-04, drop the duplicate 2027-01-25 calendar row (PROGRESS:78 exists), and cite the S5 day-60 formula instead of 2027-01-13.
7. B5: make one call with `k_variants=1` and `programme_alpha_override=0.025`; delete the grid.
8. Sequencing: B5 before B4; B4 reduces to a one-line NO record on E5 refusal.
9. B1: the completion criterion is the PROGRESS line only.

## UNVERIFIED
- maker_stage0_verdict.py line citations (B2); `health_dropins.py:51,57,131-135` (B6a); the census-argv pin test lines (`maker_stage0_trigger_io.py:134-140`).
- Whether the block-2 pin step actively refuses a spec sha that differs from block 1, or only records it. Either way the sha changes across blocks.
- The live ledger's `programme_budget_remaining`, and the expected MDE of about 0.118 (k_variants=1, α_v 0.00625, n=200), which is my arithmetic.
- Who owns the uncommitted change to `docs/core/PROGRESS.md`.
