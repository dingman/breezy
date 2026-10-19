# Review: BLOCKERS plan r1 — pressure (grok)
Verdict: REQUEST_CHANGES

## Per section (B1..B6)

**B1 — REQUEST_CHANGES.** Record-only is the right action. The "done" sentence is not.
- [HIGH] `plan_r1.md:30` defines done as an S5 PROPOSAL plus the manual trio (`BREEZY_SENDING_FAMILY_ID`, restart, `live_orders_ruling`). That is the send path already stated at `PROGRESS.md:70-71` and `SPEC:380-384`, not the artefact for a closed licence (`PROGRESS.md:28-30`).
- [HIGH] "MAKER is the only hypothesis not yet refuted" and "ROI marks d2 / per-shape α not pursued" (`plan_r1.md:25,28`) overclaim. T2 still names both (`RULING_FQ-v2-NO-TRADE_2026-10-08.md:49`). `DECISION_ROI_ROUTE_TO_TRADING_2026-10-09.md:29-30` is the M1-v3 prior (P(WINNER)≈0, a WINNER does not arm), not a d2 retirement. No "not pursued" in that file.
- [MED] Table done-when is "this section is committed" (`plan_r1.md:11`). Circular. The real artefact is one PROGRESS line.
- [LOW] `0.2334` is `g3["-0.16"]` only (`fq_loss_floor_mc_seed20261008.json:1179-1190`), not the whole G3 object.
- Simpler: one PROGRESS line quoting the standing verdict and T1/T2/T3 as written. No new family ranking.
- Over-engineering: the send-trio "done" definition.

**B2 — REQUEST_CHANGES.** The code finding is right. Two cites and the PROGRESS rewrite are not.
- Verified: `_stricter` is min(station-day, position) (`maker_stage0_verdict.py:107-116`), applied at `:215-216`; `decide` calls `verdict_label` at `:319`; `r_lo` is the stressed station-day point (`:174-176`); `r_lo` = `r_lo_station_day` (`S2_stage0_replay_plan_r4_delta.md:151`). Label and `r_lo` are different quantities. No code edit.
- [HIGH] `S2_second_look_plan_r3.md:36,38` does not say "stricter". That file has zero matches. Those lines are forfeiture / frozen-doc rules. The spec sentence is `SPEC:136` (§6 gates, not the second-look plan).
- [HIGH] Do not replace the S2 status cell. On HEAD the same cell already has both "first real rows 10-21" and "FIRST RUN 10-17 … 8/8 COVERED, n_eff 3.200". Strike the stale six words only. The worktree `PROGRESS.md` already rewrote the cell (uncommitted); a second replace would drop W1 / C7 / Doc A detail.
- [MED] The NOTE must not carry block-1 `0.0814` (`STAGE0_REPLAY_2026-10-16.md:126-131`, descriptive because V0 fired) forward as a block-2 scenario. `S2_RUN_PROCEDURE_2026-10-14.md:231` is "any NO-GO stops the programme", not a V1 forecast.
- [LOW] `S2_second_look_plan_r3.md:416` is stale (Doc A FINAL was 10-16). Leaving that frozen plan unedited is correct. `:417` is a different stale fact (unit enable), same treatment.
- Simpler: a 15-line NOTE plus a six-word strike. No row rewrite.
- Over-engineering: none if the rewrite is dropped. Codex `git show 2380042f:…` stays; that byte match is not done here.

**B3 — REQUEST_CHANGES.** Keeping 300/200 is the simplest decision. Spec v0.4 is not, and its number is wrong.
- [HIGH] `plan_r1.md:78` says align to S5 §8 at r=0.10 → **413**. The table says **412** (`S5_shadow_run_and_gates_plan_r3.md:289`). Shipping 413 creates a new discrepancy. 165 and 83 match `:291-293`.
- [HIGH] `SPEC:262` and `:310` are gate 2: ≥200 **effective** positions and ≥200 station-days. The 300-position read target is `SPEC:252-253` and `S5_…_r3.md:219` only. The plan cites all three as one "300/200" (`plan_r1.md:69`).
- [MED] "Floor about 250" is not in the repo. `SPEC:292` says ~12 expected losses at 300; `:299` says ≥10. Do not use that ratio as a reason. Ledger single-look refusal is real (`hypothesis_ledger.py:1071-1075`; the docstring is `:271-273`, not a general interim-look ban).
- [MED] Doc A does not pin the spec or `maker_stage0_verdict.py` by sha. It cites `SPEC:222-224` and records CODE_SHA at the future run (`RULING_MAKER-S2_second_look_SEARCH_declaration_2026-10-16.md:19,64`). Open question 5 is answered: v0.4 need not wait on a sha. It should still not be done.
- Simpler: one PROGRESS line — "§9.15 day counts are stale; S5 r3 §8 governs (412 / 165 / 83 at k=2, c=1). 300/200 unchanged." Reject the Kish rule outright; do not park it.
- Over-engineering: spec v0.4.

**B4 — REQUEST_CHANGES.** One pre-declared ruling is the right shape. The YES branch is wider than the cite.
- [HIGH] HUNT-1:38 is "a materially different family or estimand **for off-window hours**" that "enters through AUD-18 registration", not "any estimand that clears intake" (`RULING_HUNT-1_all_hours_hunting_2026-09-26.md:38`). RA-13:53 drops the off-window clause and adds "power check at intake". `hypothesis_register.py:1-3` is the AUD-18 wrapper, so the entry path may match; the scope does not. MAKER is daily-high NO (`SPEC:24-28`), not off-window hours. An E5 pass alone must not file the R4 shell (`plan_r1.md:98-103`).
- [MED] `PROGRESS.md:78` already says "2027-01-25 | NO-TRADE ruling review; RA-13 KILL backstop". A second row does not help. `RULING_FQ-v2-NO-TRADE_2026-10-08.md:54` (no review ⇒ ruling stays) is already why that row exists.
- [MED] "about 2027-01-13" (`plan_r1.md:102,182`) is a new date. S5 already says the day-60 check is ~2027-01-22 under a 2026-11-23 start (`S5_…_r3.md:298`). Write freeze+60, not a calendar fact.
- [MED] Summary "needs: B5" (`plan_r1.md:13`) fights "rule before 2026-11-06, outcome-free" (`:180`). The scope question does not need the dry call. An E5 refusal already means no shell (`:105`).
- Simpler: the ruling answers only "does HUNT-1:38 cover MAKER?". YES quotes :38 and states the off-window clause is met. Otherwise the pre-declared branch is NO, and K-2 stays the post-horizon action (`RULING_RA-13:48,54,65`). L-38 counter fields stay mandatory on a real YES (`LESSONS.md` L-38).
- Over-engineering: duplicate 2027-01-25 row; folding the MDE bound into this ruling (`plan_r1.md:130`).

**B5 — REQUEST_CHANGES.** A pure `register_hypothesis` call is the simplest E5 check (`S5_…_r3.md:31,89`). The call as written will not return a record, and the bound source is the wrong unit.
- [HIGH] NORMAL registration raises `MissingRegistrationInputError` unless every required kwarg is set (`hypothesis_ledger.py:1000-1018`) and `MdeMismatchError` unless `mde_at_allocated_alpha` matches `recompute_mde` within 1e-4 (`:1114-1123`, formula `:859-870`). The plan's kwargs omit the caller-stated MDE, `mde_reference_ask`, slippage, variance, and `power_is_primary_only=True`. An exception is not `UNDERPOWERED_NOT_REGISTERED`.
- [HIGH] `k = 2 and k = 1` plus `programme_alpha_override` None and 0.025 (`plan_r1.md:134-135`) is a menu. `k_variants` splits alpha (`:1114-1115`); it is not MAX_RUNGS. Spec and S5 r3 do not pin `k_variants`. MAX_RUNGS never enters `recompute_mde`. "Any bound below ~0.11" is only the α_v=0.0125 cell (k_variants=1, programme α=0.05). k_variants=2 is ~0.118. A grid can manufacture UNDERPOWERED and feed it to B4.
- [HIGH] Step 1 derives `mde_plausibility_bound` from §3 w* vs design w (`plan_r1.md:130`, table `SPEC:138-147`, win-rate units). The ledger statistic is pinned to `MEAN_EXCESS_PER_TAKE` with variance 0.25 (`hypothesis_ledger.py:196-199,1081-1085`). Past bounds 0.04 and 0.03 are on that excess statistic (`hypothesis_register.py:22-34`). A win-rate gap is not that bound. Open question 1 is the blocker; step 1 answers it the wrong way. Step 4 ("if it does not fit, say so; do not patch") is the right action and contradicts step 1.
- CLI path claim is right: no dry flag; only pre-coded ids (`hypothesis_register.py:545-557`). v3 REGISTERED is refused while `HORIZON_TOLLING_LANDED` is False (`:166`, `:934-937`). S5 does not pass `re_arm_gating`, so the design call stays schema v1.
- Simpler: one call. `k_variants=1`, `programme_alpha_override=None`, `min_station_days=200`, no horizon, no re-arm. Bound, if any, is an excess number pinned from a pre-registered excess source. If none exists, the note says the win-rate gate has no ledger bound, and nothing is registered.
- Over-engineering: the 4-cell grid. Do not add a CLI flag (the plan already forbids that).

**B6 — REQUEST_CHANGES.** LEAVE / DEFER / no-action is the right split. The reason for (a) is wrong.
- [HIGH] With orders off, `OrderSubmissionPermit` is not minted (`trade.py:1366-1368`). The FQ strategy returns `phase0_permit_absent` and does not call `submit_order` (`strategy.py:629-637,646-649`). `outside_permit_window` is an FQ decision reason (`decision.py:134`), not that barrier. `backtest_order_guard.py:317-318` returns without refusing when the order permit is None, so the kernel is not the backstop. LEAVE still stands: do not touch the drop-in or `health_dropins.py`.
- Verified: unit sets `BREEZY_TRADING_ENABLED=1` and `BREEZY_ORDERS_ENABLED=1` (`breezy-trade-supervisor.service:120-121`). Drop-in line 7 is `Environment=BREEZY_ORDERS_ENABLED=0` and says remove only with the v2 resume. Mint keys on `BREEZY_TRADING_ENABLED=="1"` plus caps and operator id (`safety.py:710-719`); the boot call is unconditional (`trade.py:1321-1325`). Allowlist directive set is `[Service]` plus that one Environment line (`health_dropins.py:57`); a byte change is CRITICAL (`:131-135`).
- [MED] The allowlist row expires **2026-12-31** (`health_dropins.py:47-54`). On that day `_allowlist_match` fails (`:94`) and the same bytes page CRITICAL. Orders stay off. Record it so nobody "fixes" the page by editing the drop-in.
- (b) Verified: census default is `~/.local/share/breezy/catalog/quote_tape/polymarket_us` (`maker_tape_census.py:61-63`); `--catalog-root` is the only root flag (`:515`); `census_argv` omits it (`maker_stage0_trigger_io.py:134-140`). That path is a symlink to `/mnt/storage/breezy/catalog/quote_tape/polymarket_us` (06:38 today). `polymarket_us.old-20261019` is absent. Deferring the code row until after the S2 evidence commit is the simplest safe action. Doc A does not sha-pin the trigger today (`:64` is a future CODE_SHA).
- (c) No action is correct. Charset stays fail-closed and S4 WP1+ is gated on S2/S3 (`S4_…_r4_delta.md:41,129`; `PROGRESS.md:65`).
- Simpler: three PROGRESS lines and one README sentence. No code.
- Over-engineering: none, once the refusal sentence is corrected.

## Cross-cutting
- No invariant breach in the "do not build" lists: no Nautilus edit, no `allow_short`, no test weakening, no `BREEZY_ORDERS_ENABLED` edit, no frozen-PREREG edit, no move of 2026-11-04..11-15 or 2027-01-25. The hazards are prose: B1's send-shaped "done", B4's YES shell, B5's alpha/k grid (a menu, not yet a write).
- Sequencing: B4 must not wait on B5. Bound pin stays out of the scope ruling. B3's spec bump is not on the critical path.
- Missing calendar fact, not a new workstream: drop-in allowlist expiry 2026-12-31, before the 2027-01-25 review. Not a second orders switch.
- Missing as a decided blocker: E5's statistic is excess, not maker win rate. That is B5's open question 1 and should be closed in r2, not explored.
- Open Q3 is already decided (no Kish rule). Open Q5 is answered above (Doc A pins neither sha).

## Required edits
1. B1: one PROGRESS line restating `PROGRESS.md:28-30` and `RULING_FQ-v2-NO-TRADE:48-50` as written, and delete the "only unrefuted" ranking and the send-trio definition of done.
2. B2: drop the `S2_second_look_plan_r3.md:36,38` cite; the stricter rule is `maker_stage0_verdict.py:107-116,215-216` and `SPEC:136`.
3. B2: strike only HEAD's "first real rows 10-21"; do not replace the status cell and do not re-edit the uncommitted PROGRESS rewrite.
4. B2: the NOTE states the mechanism only and does not carry block-1's 0.0814 forward.
5. B3: do not publish spec v0.4; one PROGRESS line that S5 r3 §8 governs, copying 412 not 413 (`S5_…_r3.md:289`), with 300/200 unchanged.
6. B3: cite `SPEC:252-253` and `S5_…_r3.md:219` for the 300-position target, and `SPEC:262,310` only as the 200-effective gate.
7. B4: YES is available only if the ruling quotes `RULING_HUNT-1:38` and states MAKER is an off-window-hours estimand; an E5 pass alone does not file the shell.
8. B4: do not add a second 2027-01-25 row (`PROGRESS.md:78` has it) and do not write 2027-01-13; day-60 is freeze+60.
9. B4 does not wait on B5; pin any MDE bound in its own note, not in the scope ruling, and commit the scope ruling before 2026-11-06.
10. B5: one call only (`k_variants=1`, `programme_alpha_override=None`, `min_station_days=200`, no re-arm), with every NORMAL-required kwarg and `mde_at_allocated_alpha` equal to `recompute_mde` (`hypothesis_ledger.py:1000-1018,1114-1123`).
11. B5: the bound, if pinned, is in `MEAN_EXCESS_PER_TAKE` units; do not derive it from `SPEC:138-147`; if no excess source exists, record the mismatch and do not register.
12. B6a: replace the `outside_permit_window` sentence with the `trade.py:1367-1368` / `strategy.py:636-637` / `backtest_order_guard.py:317-318` facts, and note the allowlist expires 2026-12-31 (`health_dropins.py:47-54`).

## UNVERIFIED
- Byte identity of `maker_stage0_verdict.py` at `2380042f` versus HEAD (line cites above are HEAD).
- Whether the running node currently holds a `LiveTradingPermit` (mint needs the reserved caps and operator id, `safety.py:716-719`; values not read).
- `programme_budget_remaining` on the live ledger.
- `F13` `source_lags_ns` null (file not opened).
- `mde_one_sided` numeric output (formula not executed). The plan's 0.109 / 0.118 / 0.126 sketch matches the usual normal formula at n=200; still unexecuted.
- No "gatechain report" file in the repo. §1 and the symlink were checked on the live drop-in and the catalog path instead.
