# BLOCKERS_2026-10-19 plan r2 (r2.1: verification edits applied 2026-10-19 — architect, PMR, python-reviewer all APPROVE; see `reviews/r2-*.md`)

**Invariants.** Nautilus is immutable. `allow_short` stays False. No safety, settlement, contract or NO-SEND firewall test is weakened or deleted. A guard is only widened by one reviewed row (L-12). Nobody touches live enablement, `BREEZY_ORDERS_ENABLED` or the egress firewall. Nobody assigns an operator-reserved value (max daily budget, max per position). No frozen PREREG is edited and no pre-registered date moves, including 2026-11-04..11-15 and 2027-01-25. No gate changes after a result (`RULING_FQ-v2-NO-TRADE_2026-10-08.md` §Disclosures; L-34). Durable runs use `systemd-run --user` with RuntimeMaxSec. Worktrees use `PYTHONPATH=<wt>/src`. Never run `uv`/`pip` from a worktree. Never `git stash`. Run the full gate after every merge.

**Scope.** The work is decide, pin and record, plus one read-only dry call (B5). No code is built and no spec is edited. The deliverables are exactly three (deliverable 2 includes the one-sentence `deploy/systemd/README.md` note for B6(b)):
1. ONE dated coordinator ruling, `docs/evidence/RULING_BLOCKERS_R4_scope_and_E5_<date>.md`. It carries the B2 unit note, the B3 decision, the B5 pins and dry-call result, and the B4 R4-scope decision.
2. `docs/core/PROGRESS.md` lines for B1 and B6, plus the calendar rows.
3. The row-2 text fix. This is already in the working tree, uncommitted. No further row-2 edit is needed (PROGRESS.md:63 no longer carries "first real rows 10-21"). Commit it by explicit path, only the hunks that belong to it.

The only possible code row is a deferred `hypothesis_register.py` constants row, and only on B4=YES.

## Summary table

| id | blocker | simplest action | owner | effort (h) | needs | pre-declared outcome | done-when |
|---|---|---|---|---|---|---|---|
| B1 | No family has edge; licence closed | One PROGRESS line restating the standing verdict and T1/T2/T3 as written | coordinator | 0.25 | nothing | status line only; "done" may end at B4=NO → K-2 | the PROGRESS line is committed |
| B2 | Label unit; E1/§8 unit | Ruling §B2: mechanism note plus the freeze-day S-1 unit convention | coordinator; PMR, python-reviewer | 0.5 | nothing | no code or plan edit | ruling committed before 2026-11-04 |
| B3 | S5 read target is the pole | Ruling §B3: 300/200 kept; effective-n rule REJECTED; §9.15 superseded by S5 r3 §8 | coordinator; PMR, architect | 0.5 | nothing | NOT negotiable; no spec edit | ruling committed |
| B5 | E5 intake unpinned | Pin inputs, then ONE pure `register_hypothesis` call | Grok (read-only) → python-reviewer | 1.5 | pins committed before the call | **UNDERPOWERED_NOT_REGISTERED** (MDE ≈ 0.118 > 0.08) | call kwargs, record and ledger sha in the ruling |
| B4 | RA-13 KILL vs MAKER (R4) | Ruling §B4 on RA-13:53's literal text; R4 == intake REGISTERED | coordinator; architect, PMR | 1 | B5 result | **NO** → KILL at the first triage ≥ 2027-01-25, then K-2 | ruling committed **before 2026-11-04**; calendar row |
| B6 | Hygiene | (a) LEAVE, conditions recorded; (b) symlink is load-bearing, note only; (c) none | coordinator; security signed (a) | 0.5 | nothing | (a) LEAVE; (b) note; no code row | PROGRESS lines, README sentence, 12-31 calendar row |

Owner order follows `CLAUDE.md`: Grok, then Codex, then Claude. Run `~/.claude/bin/grok-check.sh` before the Grok dispatch. Ruling authoring falls under the Claude-native fallback trigger (plan and spec authoring). Every dispatch is read-only.

## B1. No family has evidence of edge; the licence is closed

**Blocker.** The standing verdict is that no family has edge and no family trades (`PROGRESS.md:28-30`). The re-open routes are T1/T2/T3 (`RULING_FQ-v2-NO-TRADE_2026-10-08.md:45-50`).

**Simplest action.** Add one PROGRESS line that restates `PROGRESS.md:28-30` and `RULING_FQ-v2-NO-TRADE:45-50` as written. It adds no family ranking and no definition of the send path. It ends with: "done may legitimately end at B4=NO → K-2 (`RULING_RA-13:48,54,65`)".

**Do NOT build** a new family, a new prereg, an IOC variant of MAKER, or any d2/per-shape α design.

**Completion criterion.** The PROGRESS line is committed. That is the only criterion.

**Risk.** Operator pressure to trade. Mitigation: L-56, L-9, and ROI ranking §2.

## B2. S2 label unit, and the E1/§8 unit caveat

**Finding (VERIFIED by python-reviewer and PMR; `2380042f` is byte-identical to HEAD for `maker_stage0_verdict.py`).**
- The label is the stricter of the two units. `_stricter` is defined at `maker_stage0_verdict.py:107-116` and applied at `:215-216`. `verdict_label` compares it to FILL_FLOOR 0.10 at `:269-278`, and `decide` calls it at `:319`.
- `r_lo` is the stressed station-day point (`:173-176`; `S2_stage0_replay_plan_r4_delta.md:151`).
- Pre-registered support: `S2_stage0_replay_plan_r4_delta.md:290` and `SPEC:134-136` ("the gates use the stricter").
- The label and `r_lo` are different quantities by design. The ruling states the mechanism only. It does not carry block 1's 0.0814 forward as a block-2 scenario.

**E1/§8 caveat (PMR HIGH).** S5 r3 §8 takes a per-rung `r` (`S5_…_r3.md:282`: positions/day = 7.28·c·r). E1's "`r_lo · c` ≳ 0.115" (`:296`) is evaluated at `r_lo`, which is a station-day rate. Both units exist in S2 (`r_lo_station_day` and `r_lo_position`, `r4_delta:150-152`).

The ruling fixes a convention now, before any block-2 result. The freeze-day S-1 test uses, at MAX_RUNGS=2, `r = min(r_lo_position, 1 − √(1 − r_lo_station_day))`; at MAX_RUNGS=1, `r = min(r_lo_position, r_lo_station_day)` (§8 `:281-283`); `c` multiplies `r` afterwards (`r·c` vs 0.115, `:296`). The k=2 form inverts §8's own station-day formula and `1−√(1−s) ≤ s`, so the rule can only fire S-1 earlier or at the same time, never later. E1's text is frozen and not edited; this is a convention ruling.

**Citation fixes.**
- `S2_second_look_plan_r3.md:36,38` is replaced by the two citations above.
- The stale rows are `r3:415-417`. The plan doc stays unedited because it is frozen input.
- Doc A pins only its own sha (`:5`), the tail csv (`:73`) and `trade_quantity_unit.json` (`:70`). Code is frozen through CODE_SHA (Doc A `:64`) from Doc B FINAL.

**Do NOT build** a label change, a station-day-only label, or any edit to `maker_stage0_verdict.py`, Doc A or the trigger.

**Completion criterion.** Ruling §B2 is committed before 2026-11-04.

**Risk.** The note is read as a forecast. Mitigation: mechanism only, no numbers carried forward.

## B3. S5 read target is the pole

**Decision.** 300/200 is kept. The effective-n (Kish) rule is REJECTED outright and is not parked as an option.
- The 300-position target is `SPEC:252-253` and `S5_…_r3.md:219`.
- The 200-effective gate 2 is `SPEC:262,310`.
- The decision rests on three points:
  1. The ledger refuses any look policy other than a single look (`hypothesis_ledger.py:1071-1075`).
  2. The realised design effect depends on outcomes (clustered fills).
  3. Choosing n after the block-1 split is visible is the post-result pattern.
- If the gate-9 floor is mentioned, state it as 10/mean(p_YES of filled episodes). It is ≈250 only if mean p_YES ≥ 0.04, and ≈333 at 0.03.

**§9.15.** It is superseded by S5 r3 §8. Copy the values verbatim: 412 / 165 / 83 days at MAX_RUNGS=2, c=1 (`S5_…_r3.md:289,291,292`). c is unmeasured, so these are upper bounds on speed.

**No spec edit.** The S2 run pins the spec sha256 (`maker_stage0_pins.py:86,332`), and the S5 PREREG names spec v0.3 (`S5_…_r3.md:217`).

**Do NOT build** an S5 redesign, sequential or LD-OBF looks, a 300/200 change, a station-day-only gate, an effective-n target rule, a live-small holdout variant, or any spec edit (v0.4).

**Completion criterion.** Ruling §B3 is committed.

**Risk.** A future spec bump is read as licence to edit gates. Mitigation: any text fix waits for the S5 freeze re-pin.

## B5. E5 intake: one pure dry call (runs FIRST)

**Code facts (VERIFIED).**
- `register_hypothesis` (`hypothesis_ledger.py:873`) is pure.
- Its status depends only on `recompute_mde(...)` > `mde_plausibility_bound` (`:1116-1125`). `mde_reference_ask` and slippage are recorded but do not change the status.
- Under schema v1, REGISTERED is not code-refused. The v3 refusals sit at `:1166-1184`.

**Pins, committed in the ruling draft BEFORE the call (outcome-free; no Stage-0 or block-2 number).**

| kwarg | value | source |
|---|---|---|
| `hypothesis_id` / `hypothesis_class` | exact strings `"H-MAKER-NO-2026-10"` / `"pm_us_no_ladder_maker"` | SPEC §1; not a duplicate of the 4 live ids (python r2) |
| `existing_records` / `disposition` | `read_hypothesis_ledger(<scratchpad copy>)` / default `"NORMAL"` | run step 4 |
| `registered_at` / `freeze_commit` | call date / HEAD 40-hex sha at the call (not format-validated, `scripts/analysis/hypothesis_register.py:235-239` — cite only, never import) | — |
| `k_variants` | 1 | one design; `MAX_RUNGS` is not a variant (precedents `hypothesis_register.py:154,183,214`) |
| `programme_alpha_override` | 0.025, one value | RA-13 binds programme FWER at 0.025 (`RULING_RA-13:5`) and the spec nests α in RA-13. The ledger's `PROGRAMME_ALPHA` 0.05 (`:177`) is the older default. |
| `min_station_days` | 200 | `SPEC:252-253` design value |
| `mde_at_allocated_alpha` | `recompute_mde(per_variant_alpha=0.025/4/1, n_station_days=200)` = the full-precision returned value (0.118063…; python r2 ran it: 0.11806302799), never a rounded literal (tolerance 1e-4, `:1119`, `:216`) | `:859` |
| `mde_reference_ask` | 0.80, the design bid | Break-even is ask-based (`:851-856`); a maker's cost basis is its bid. For every rung with p_NO ≥ P_MIN 0.94, `p_no − E_MIN − fee` ≥ 0.829, so `b_max` = B_CAP 0.80 (`SPEC:72,83`). |
| `mde_slippage_allowance` | 0.01 | The spec names none. Programme convention is the AUD-12a retained placeholder (`RULING_RA-13:13`; precedents `hypothesis_register.py:169,202,229`). |
| `mde_variance_bound` | 0.25 | `VARIANCE_BOUND` (`:196`), Popoviciu; no justification needed |
| `mde_plausibility_bound` | **0.08** (= b 0.80 / w 0.90 cell 0.089 − 0.01 slippage = 0.079, rounded) | cell ENDORSED by architect, PMR and python-reviewer in `reviews/r2-*.md`; any bound in [0.079, 0.118) gives the same status |
| fixed constants | `power_is_primary_only=True`, `mde_fee_theta=0.0695`, `max_single_day_leg_share_cap=0.20`, `station_day_statistic="MEAN_EXCESS_PER_TAKE"`, `order_quantity=1`, `look_policy="SINGLE_LOOK"` | `:196-212,1000-1018` |
| not passed | `re_arm_gating`, `horizon_days`, `variant_stratum_filters` (schema v1) | — |

**Bound unit check (planner-verified at `SPEC:138-147`).**
- The §3 column is "EV per contract" = `w − (b + θ·b·(1−b))`, in dollars per one-unit contract.
- The table's fee implies θ = 0.0111/(0.8·0.2) ≈ 0.0694, which matches `EVIDENCED_FEE_THETA` 0.0695 (`:204`).
- `MEAN_EXCESS_PER_TAKE` is the mean of `W − BE`, with `BE = a + θa(1−a) + slippage` (`:851-856`). At a = b its expectation is the table EV minus slippage.
- So the units are equivalent. The past bounds 0.04 and 0.03 are in the same unit (`hypothesis_register.py:22-34`).

**Correction to the brief's premise.** 0.08 is NOT the table maximum. The maximum is +0.225 (b=0.70, w=0.94). The +0.081 cell is the b=0.85 row, a bid the design never places (B_CAP 0.80).

**Corrected derivation of 0.08.** Take the design-bid row (b = 0.80) at w = 0.90: +0.089 (`SPEC:146`). Net of the 0.01 slippage that is 0.079, rounded to 0.08 at the precision of past bounds.

**Disclosed alternative.** The w = 0.94 cell nets 0.119, which exceeds the MDE 0.1181 by 0.0009 and would REGISTER. It is not the plausibility value. w = 0.94 equals P_MIN, the lowest model p_NO for any bid, so it assumes perfect tail calibration and zero adverse selection. The spec names adverse selection as the falsifier (`SPEC:49-52`), states the hostile priors (`:41-47`), and reads observed 0.85 as its case (`:149-154`).

This choice is made with the MDE known, as in every precedent. The peers must endorse the cell explicitly before the call.

**Run.**
1. Run the gate: `~/.claude/bin/grok-check.sh`.
2. Grok runs read-only. The exact script is in the brief, run as `/home/jon/breezy/.venv/bin/python -I` with `PYTHONPATH=/home/jon/breezy/src`.
3. Copy `~/.local/share/breezy/derived/hypothesis/hypothesis_ledger.jsonl` by its hardcoded path to the agent's scratchpad. Record the sha256 of the original before and after.
4. Read the COPY with `read_hypothesis_ledger` (`:1369-1392`). Do not import `hypothesis_register.py` or `write_hypothesis_ledger`.
5. Record `programme_budget_remaining(records)` first.
6. Make ONE call.
7. These exceptions are recorded outcomes, not bugs: `DuplicateHypothesisIdError` (`:943-946`), `MissingRegistrationInputError`, `MdeMismatchError`, `ProgrammeBudgetExhaustedError`, `HorizonTollingNotLandedError`, `PathBSourceGateNotLandedError`.
8. python-reviewer re-derives the arithmetic: z(0.99375) ≈ 2.4977, (2.4977 + 0.8416)·0.5/√200 ≈ 0.1181. This agrees with the off-window T4 record, 0.0964 at n=300 with the same α (`hypothesis_register.py:223`).

**Pre-declared outcome.** UNDERPOWERED_NOT_REGISTERED.

**Do NOT build** a new dry-run tool or CLI flag, a ledger edit, a flip of `HORIZON_TOLLING_LANDED` or `PATH_B_SOURCE_GATE_LANDED`, a live append to `hypothesis_ledger.jsonl`, or a script that imports `hypothesis_register.py`.

**Completion criterion.** Ruling §B5 records the pin commit sha (earlier than the call), the kwargs, the returned record or exception, the budget remaining, and the ledger sha before and after.

**Risks.**
1. The bound is chosen to pass. Mitigation: the pins are committed first, and the 0.119 alternative is disclosed.
2. A side effect on the ledger. Mitigation: read a copy, with sha equality as evidence.

## B4. RA-13 KILL vs MAKER: R4 scope

**What the ruling decides.**
- It rules on RA-13's literal R4 text, "a new estimand that clears its power check at intake" (`RULING_RA-13:53`).
- It must quote `RULING_HUNT-1:38` in full: "A materially different family or estimand is proposed for off-window hours. That proposal enters through AUD-18 registration, never by widening the window."
- It disposes of the off-window clause as follows:
  - That clause is HUNT-1's own re-open trigger 4, scoped to the hour-window hunt. RA-13 uses it to re-open the trigger-4 path at `:18`.
  - At `:53` RA-13 cites it as provenance and restates the test as intake.
  - MAKER rests bids; it is not an hour-window hunt.
  - So R4 == ledger intake returns REGISTERED. HUNT-1:38 is not a second test.
  - Under the expected UNDERPOWERED outcome, the literal reading (Grok's) and this reading agree on NO.
- An E5 pass alone never files the shell; only the ruling does.

**Pre-declared NO (expected; mechanically the result of B5 = UNDERPOWERED).**
- KILL fires at the first triage on or after 2027-01-25 (`RULING_RA-13:48`), and the next action is K-2 (`:54,65`).
- S2/S3 still run as evidence. They cannot defer the KILL and cannot be cited as R4 (`S5_…_r4_delta.md:56-58`).

**YES (only if E5 returns REGISTERED).**
- The R4 event is a REGISTERED record appended through `register_and_persist` (`hypothesis_register.py:274-297`). That needs one reviewed constants row at freeze (deferred code row).
- UNVERIFIED: RA-9 A-3 may require a v3 record for any REGISTERED look-taking record (`hypothesis_ledger.py:1160-1165` text). v3 is refused while `:166`/`:174` are False, and the constants row must settle this.
- YES is VOID unless the ledger record and the R4 shell are both committed on or before 2027-01-24.
- The shell carries only the L-38 counter and cap (day-60 check per the formula at `S5_…_r3.md:298`, with no restated date; `calendar_cap_date` ≤ 2027-11-30), plus this line: "S5 report is advisory-only; PROPOSAL arms nothing; activation is the manual trio."

**Calendar.**
- ADD the row "≤ 2027-01-24 | RA-13 R4 record (ledger REGISTERED + shell) or N/A".
- Do NOT add a second 2027-01-25 row (`PROGRESS.md:78` already has one).

**Do NOT build** an amendment to RA-13's date, a reading of the PREREG freeze as R4, or any R4 shell content before freeze day other than the field list.

**Completion criterion.** The ruling is committed with peer verdicts **before 2026-11-04**, the earliest possible E, and the calendar row is present.

**Risks.**
1. A motivated reading after block 2. Mitigation: the deadline, plus B5's purity.
2. A YES without a counter becomes a bare suspension. Mitigation: the L-38 fields are mandatory.

## B6. Hygiene

**(a) LEAVE (security-reviewer SIGNED).**
- The unit sets `BREEZY_TRADING_ENABLED=1` (`breezy-trade-supervisor.service:120`). The drop-in sets only `BREEZY_ORDERS_ENABLED=0`.
- The live permit mints on the code path (`safety.py:710-720`, `app/trade.py:1323`) if the unit carries the caps and operator id. That condition is UNVERIFIED.
- The only send barrier is orders=0 plus the strategy gate `phase0_permit_absent` (`strategy.py:636`). The kernel guard allows a None permit (`backtest_order_guard.py:315-317`).
- Changing the drop-in costs a sha row plus a directive-set code change in `health_dropins.py` (`:51,57,131-135`).
- The PROGRESS line must say: **any new strategy, exit-seam arming, F9 or v2 resume must treat the live permit as already minted; do not rely on `backtest_order_guard` for a None permit.**
- **Calendar row:** 2026-12-31, drop-in allowlist row expiry (`health_dropins.py:55`). After that date the unchanged drop-in pages CRITICAL `allowlist_mismatch` unless a reviewed row renews it. Decide the renewal in December, not now. Never "fix" the page by editing the drop-in.

**(b) Note only.**
- `~/.local/share/breezy/catalog/quote_tape/polymarket_us` is a symlink to `/mnt/storage/…` and is load-bearing for `breezy-maker-s2-trigger.service`.
- The census reads only `--catalog-root` (`maker_tape_census.py:515,61-63`), and `census_argv` omits it (`maker_stage0_trigger_io.py:125-140`).
- The rollback path `polymarket_us.old-20261019` is absent.
- Record this in PROGRESS and in one `deploy/systemd/README.md` sentence (paths only). No code row (YAGNI).

**(c) No action.** The S4 order-id charset stays fail-closed (`S4_…_r4_delta.md:41,129`).

**Do NOT build** a drop-in change, a new drop-in, an allowlist row, a `health_dropins.py` edit, a census or trigger edit during block 2, symlink removal, a catalog-root env-var code row, or an S4 charset change.

**Completion criterion.** The PROGRESS lines for (a) and (b), the README sentence, and the 12-31 calendar row are committed.

**Risks.**
1. The symlink is "cleaned up" mid-S2. Mitigation: the README note, plus the COVERED counts.
2. The latent permit is forgotten. Mitigation: the (a) line.

## Sequencing

1. **Now, in parallel:**
   - B1 and B6 PROGRESS lines and calendar rows. Commit `PROGRESS.md` by explicit path, own hunks only, because the tree carries uncommitted coordinator work.
   - Ruling draft §B2/§B3.
   - §B5 pin table.
   - Peers: PMR and architect endorse the pins, including the bound cell.
2. **Commit 1:** the ruling draft with the B5 pins, which gives the pin-before-call git evidence.
3. **B5 call:** Grok runs it read-only; python-reviewer checks it.
4. **Commit 2:** the ruling FINAL (B5 result + B4 decision + peer verdicts) **before 2026-11-04**.
5. **Waits:**
   - On YES only: the constants row, the REGISTERED append and the shell, all ≤ 2027-01-24.
   - S5's E5 re-run on the frozen design stays the S5 WP0 note (`S5_…_r3.md:89`).

## Review disposition

| reviewer | finding | applied / rejected, and why |
|---|---|---|
| architect, PMR | Collapse the paperwork to one ruling | APPLIED: three deliverables |
| architect | B1 completion criterion is circular | APPLIED: the PROGRESS line is the only criterion |
| Grok | B1 overclaims "only unrefuted"; send-trio "done" | APPLIED: restate as written; ranking and trio dropped |
| PMR | "done" may end at B4=NO → K-2 | APPLIED |
| python, Grok | `S2_second_look_plan_r3.md:36,38` miscited | APPLIED: `r4_delta:290` + `SPEC:134-136` |
| python | stale rows are r3:415-417 | APPLIED |
| python | Doc A pins only its own sha, the csv and the json; CODE_SHA freeze `:64` | APPLIED |
| PMR | E1/§8 uses a station-day `r_lo` as per-rung `r` | APPLIED: convention ruled before block 2 |
| Grok | Do not carry 0.0814 forward | APPLIED |
| Grok | Strike only six words in row 2 | SUPERSEDED: row already consolidated in the tree; no further edit |
| PMR, python, architect | Codex re-confirmation is redundant | APPLIED: dropped (verdict script byte-identical) |
| architect | Drop spec v0.4 (S2 pins the spec sha, `maker_stage0_pins.py:86,332`) | APPLIED |
| Grok, architect | 412 not 413; cite §8, don't retype | APPLIED: copied verbatim |
| Grok | Cite 300 and 200 separately | APPLIED |
| architect, Grok | Delete the "≈250 floor" reason | APPLIED: restated as 10/mean(p_YES) per PMR |
| PMR, architect, Grok | Reject effective-n outright | APPLIED |
| architect, PMR | R4 on RA-13:53's literal text; HUNT-1:38 provenance only | APPLIED |
| Grok | YES only if MAKER is an off-window estimand | REJECTED: HUNT-1:38 is quoted and disposed of; both readings give NO under UNDERPOWERED |
| architect | R4 event = REGISTERED via `register_and_persist`; deferred row; void after 2027-01-24 | APPLIED |
| architect | Deadline before 2026-11-04; no duplicate 01-25 row; day-60 by formula | APPLIED |
| Grok | B4 must not wait on B5 | REJECTED: B5 uses no outcome; one ruling is simpler |
| PMR | Trim the YES field list | APPLIED: L-38 counter, cap and advisory line only |
| architect, Grok | One call, no grid; `k_variants=1` | APPLIED |
| Grok | `programme_alpha_override=None` | REJECTED: RA-13:5 binds 0.025 |
| python, Grok | Every required kwarg; `mde_at_allocated_alpha` via `recompute_mde` | APPLIED: pin table |
| python | Exceptions are outcomes; both v3 flags (`:166,:174`) | APPLIED |
| PMR, python | `mde_reference_ask` = design bid; budget checked first; pin ask and slippage | APPLIED: 0.80; 0.01 (spec names none) |
| Grok | Bound is in excess units, not the w*-gap | APPLIED: unit equivalence verified at `SPEC:138-147` and `:851-856` |
| PMR, coordinator | "0.08 = table maximum" | CORRECTED: the max is 0.225; 0.08 re-derived from b=0.80, w=0.90, net of slippage; 0.119 alternative disclosed |
| PMR | Variance 0.25 is valid but loose | APPLIED: recorded, no patch |
| security | Read a scratchpad copy, hardcoded path, sha before and after; no `hypothesis_register` import | APPLIED |
| security, Grok | B6a barrier wording; three latent-permit conditions | APPLIED |
| security, Grok | 2026-12-31 allowlist-expiry calendar row | APPLIED: renewal decided in December |
| python | B6b invents an env name; delete the code row | APPLIED: note only |
| Grok | No "gatechain report" in the repo | APPLIED: direct file citations only |

## UNVERIFIED
- Whether the unit env carries the caps and operator id, so whether the live permit mints today.
- `programme_budget_remaining` on the live ledger. The call records it.
- Whether RA-9 A-3 forces schema v3 for a MAKER REGISTERED record. Matters only on YES.
- Whether `maker_stage0_trigger_io.py` is in the CODE_SHA freeze scope. It does not matter, since no code row is planned.
