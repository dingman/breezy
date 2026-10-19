# BLOCKERS_2026-10-19 plan r1

**Invariants.** Nautilus is immutable. `allow_short` stays False. No safety, settlement, contract or NO-SEND firewall test is weakened or deleted; a guard is only widened by one reviewed row (L-12). Nobody touches live enablement, `BREEZY_ORDERS_ENABLED` or the egress firewall. Nobody assigns an operator-reserved value (max daily budget, max per position). No frozen PREREG is edited and no pre-registered date moves, including 2026-11-04..11-15 and 2027-01-25. No gate changes after a result (`RULING_FQ-v2-NO-TRADE_2026-10-08.md` §Disclosures; L-34). Durable runs use `systemd-run --user` with RuntimeMaxSec. Worktrees use `PYTHONPATH=<wt>/src`. Never run `uv`/`pip` from a worktree. Never `git stash`. Run the full gate after every merge.

**Scope.** Every action here is decide, pin or record, plus one read-only dry call (B5). No code is built. Two items might later need one reviewed code row (B6b after S2; B6a only if the decision were reversed). Both are deferred on purpose.

## Summary table

| id | blocker | simplest action | owner agent | effort (h) | needs | STOP/decision outcome | done-when |
|---|---|---|---|---|---|---|---|
| B1 | No family has edge; licence closed | Record the standing verdict and what "done" means | coordinator; prediction-market-reviewer | 0.5 | nothing | none; status line only | the B1 section of this plan is committed |
| B2 | S2 label unit unclear | Record the verified code path as a dated note; fix PROGRESS row 2 text | Codex (read-only) → coordinator | 1 | nothing | VERIFIED: the label uses the stricter unit and `r_lo` uses station-day; they do not conflict, so no edit | note committed before 2026-11-06 |
| B3 | S5 read target is the pole | Keep 300/200. Spec v0.4 fixes the §9.15 day counts only | coordinator; prediction-market-reviewer | 1 | nothing | NOT negotiable, recorded | spec v0.4 committed; decision line in PROGRESS |
| B4 | RA-13 KILL 2027-01-25 vs MAKER | One dated ruling: does a MAKER E5 pass count as R4? Both outcomes pre-declared | coordinator; architect + prediction-market-reviewer | 2 | B5 result (input, not a blocker) | YES → R4 shell filed on freeze day; NO → KILL at the horizon, then K-2 | ruling committed; calendar rows added |
| B5 | E5 intake unpinned | Pure dry call of `register_hypothesis`; pin `mde_plausibility_bound` first | Codex (read-only) + prediction-market-reviewer | 2 | the bound pinned outcome-free | REGISTERED, or UNDERPOWERED/refused → routed to B4 | evidence note with the call inputs and the returned record |
| B6 | Hygiene | (a) leave the trading flag as is, documented; (b) keep the symlink, record that it is load-bearing, defer the code row; (c) no action | security-reviewer (a); python-reviewer (b) | 1 | nothing | (a) LEAVE; (b) DEFER until after the S2 evidence commit | decision lines in PROGRESS plus a runbook note |

Owner order follows `CLAUDE.md` (Grok, then Codex, then Claude). Run `~/.claude/bin/grok-check.sh` before any Grok dispatch. Every dispatch here is read-only except the doc commits, which the coordinator makes.

## B1. No family has evidence of edge; the licence is closed

**Blocker.** The standing verdict is that no family has a proven edge and no family trades (`docs/core/PROGRESS.md:29-30`). Live record: 34 fills, 4 wins, net −2.63 (`docs/evidence/TRADE_EFFECTIVENESS_2026-10-11.md:20`). Orders are off through the drop-in `fq-v1-halt-orders-off.conf:7` (gatechain report §1).

**Simplest action.**
- Record that MAKER (spread capture) is the only hypothesis not yet refuted. It is the T2 candidate (`RULING_FQ-v2-NO-TRADE_2026-10-08.md:45-50`; spec premise `SPEC_pm_us_no_ladder_maker_2026-10-12.md:24-28`).
- T1 (M1-v3) is not a send route. The read is on 2026-12-07, P(WINNER)≈0, and a WINNER "does not arm" (`DECISION_ROI_ROUTE_TO_TRADING_2026-10-09.md:29-30`). Its only sender draft stopped at Stage −1 (`docs/evidence/m1v3/DECISION_READINESS_BUILD_SHELVED_2026-10-09.md`).
- T3 (F13) is not a 2026 route. `source_lags_ns` is null and the freeze is not before 10-21; this is a pin, not a licence (`F13_prereg_blend_v1.json`; DECISION_ROI §T3).
- d2 restricted-mix and per-shape α are not routes. ROI marks them "not pursued". Choosing α=0.10 after D1 FAIL is a post-result change (RULING_FQ-v2-NO-TRADE §Disclosures). M-no G3 is 0.2334 < 0.25 at 12-01 (`docs/evidence/f5/fq_loss_floor_mc_seed20261008.json:1179-1190`).
- Reusing the IOC taker path is not a route. It drops the spread mechanism, and the IOC book is the −2.63 record. The forecast-taker programme is CLOSED (`RULING_forecast_edge_programme_closes_2026-09-20.md` §4).
- "Done" means one thing: an S5 report of PROPOSAL, plus a recorded R4 ruling (B4), plus the manual trio (`BREEZY_SENDING_FAMILY_ID`, supervisor restart, `live_orders_ruling`; `PROGRESS.md:70-71`; `SPEC:380-384`).

**Do NOT build** a new family, a new prereg, an IOC variant of MAKER, or any d2/per-shape α design.

**Completion criterion.** This section is committed in `docs/plans/backlog/BLOCKERS_2026-10-19/plan_r1.md` and one PROGRESS line points to it.

**Risks.** (1) Operator pressure to trade pushes toward route (a)/(b). Mitigation: L-56, L-9, and ROI ranking §2. (2) An unrefuted hypothesis is read as evidence of edge. Mitigation: state that it has no evidence (block-1 position rate 0.0814 < 0.10, `STAGE0_REPLAY_2026-10-16.md:131`).

**Peer reviewers.** prediction-market-reviewer.

## B2. S2 second look: which unit the label uses

**Blocker.** The brief marked as UNVERIFIED which unit the block-2 label uses if V0 does not fire, while `r_lo` = station-day 0.1364 (`S2_stage0_replay_plan_r4_delta.md:151`). **Now VERIFIED from code. There is no ambiguity.**

**Finding, from code and pre-registered text.**
- The label takes the minimum of the two units, for both base and stress. `_stricter` is defined at `scripts/analysis/maker_stage0_verdict.py:107-116` and applied at `:215-216`. `verdict_label` V1/V3 compare against `FILL_FLOOR` 0.10 at `:269-278`. `decide` calls it at `:319`.
- This matches the plan text: "stricter of the two units" (`S2_second_look_plan_r3.md:36,38`) and "the gates use the stricter" (`SPEC:136`).
- `r_lo` is the stressed station-day point (`maker_stage0_verdict.py:173-176`), which is what r4_delta:151 says.
- So the label (stricter unit) and the freeze floor `r_lo` (station-day) are different quantities by design. They do not contradict each other.

**Consequence to record honestly.** If block 2 looks like block 1 (base and stressed stricter rate 0.0814, `STAGE0_REPLAY_2026-10-16.md:131`) and V0 passes, V1 `NO-GO (fill)` fires and the programme ends (`S2_RUN_PROCEDURE_2026-10-14.md:231`).

**Simplest action.**
- Codex, read-only, re-confirms the six cited lines at HEAD and that `CODE_SHA 2380042f`'s copy of `maker_stage0_verdict.py` matches HEAD for those functions (`git show 2380042f:scripts/analysis/maker_stage0_verdict.py`).
- Coordinator writes `docs/evidence/maker/NOTE_S2_label_unit_2026-10-19.md` (dated, about 15 lines) with the citations above and the consequence line.
- If the code had contradicted the plan, this would be a class-C ruling, not an edit. It does not.
- Fix the `PROGRESS.md:63` row-2 contradiction ("first real rows 10-21" vs "FIRST RUN 10-17 … n_eff 3.200"). Replace it with: first check 2026-10-17, `to` 2026-10-15, 8/8 COVERED, n_eff 3.200. Calendar 11-04..11-06 / cap 11-15 unchanged (`S2_second_look_plan_r3.md:80-82`). Text only; no date moves.
- Add one line to the note: `S2_second_look_plan_r3.md:416-417` is stale (it lists Doc A FINAL as 10-18..19). Leave the plan doc unedited, because it is frozen input.

**Do NOT build** a label change, a station-day-only label, or any edit to `maker_stage0_verdict.py`, Doc A or the trigger.

**Completion criterion.** The NOTE file and the PROGRESS fix are committed before the 2026-11-06 10:05Z check.

**Risks.** (1) The NOTE reads as a prediction of the label. Mitigation: state the mechanism only, no forecast. (2) HEAD drifted from CODE_SHA. Mitigation: the `git show` comparison in step 1.

**Peer reviewers.** prediction-market-reviewer (unit semantics); python-reviewer (line citations).

## B3. S5 read target is the pole

**Blocker.** The read target is ≥300 positions and ≥200 station-days (`SPEC:252-253,262,310`; `S5_shadow_run_and_gates_plan_r3.md:219`). At k=2 that is 83 days at r=0.50 and 359 days at r=0.115 (`S5_…_r3.md:287-296`). Every start reads after 2027-01-25 (`S5_…_r4_delta.md:55-58`).

**Decision: not negotiable now.** Reasons:
- Gate 9 needs ≥10 pooled expected losses (`SPEC:296-300`), about 12 at 300 positions, so the floor is about 250. That is architect and PMR arithmetic; UNVERIFIED in the repo.
- The ledger refuses interim looks (`hypothesis_ledger.py:1071-1075`, docstring `:272`).
- Choosing n after the 0.0814 / 0.1364 split is visible is the post-result pattern.
- Judges disagree. PMR proposes a pre-11-08 Kish effective-n rule that saves about 20%. Architect and Grok say no. This plan picks no change: it is simpler, it does not reach 2027-01-25 at any plausible r, and it touches gate 2/9 semantics.

**Simplest action.**
- Spec v0.4, cosmetic and outcome-free. Rewrite §9.15 (`SPEC:388-393`) to match S5 §8 at c=1: k=2 → r 0.10: 413 / r 0.25: 165 / r 0.50: 83 days; k=1 doubles. Remove the "0.25 about 330" line, which equals §8's k=1 row. Add one line saying c is unmeasured, so every value is an upper bound on speed.
- The changelog line reads "v0.4: §9.15 arithmetic aligned to S5 §8; no gate, n, α or date changed."
- Add a PROGRESS decision line: "S5 300/200 kept; no sequential looks; reviewed 2026-10-19."

**Do NOT build** an S5 redesign, sequential or LD-OBF looks, a 300/200 change, a station-day-only gate, an effective-n target rule, or a live-small holdout variant.

**Completion criterion.** The spec v0.4 diff touches only §9.15 and the changelog, is committed, and carries the reviewer verdicts.

**Risks.** (1) The spec edit is read as a licence to edit gates. Mitigation: changelog wording plus a reviewer check that the diff is §9.15-only. (2) S2 Doc A pins a spec sha. Not found by the PMR grep; UNVERIFIED. Mitigation: grep Doc A for the spec sha before committing; if it is pinned, defer v0.4 until after the S2 evidence commit.

**Peer reviewers.** prediction-market-reviewer; architect.

## B4. RA-13 KILL 2027-01-25 vs MAKER (R4 scope)

**Blocker.** KILL fires at the first triage on or after 2027-01-25 with none of R1–R4 recorded (`RULING_RA-13_programme_kill_2026-09-27.md:45-49`). R1 is inert (B-3, `:89-92`). The backstop is for R2–R4 (B-5, `:95`).
- R4 is "a new estimand that clears its power check at intake" (`:53`). It cites HUNT-1:38, which says "for **off-window hours** … enters through AUD-18 registration" (`RULING_HUNT-1_all_hours_hunting_2026-09-26.md:38`).
- S5 requires a separate dated R4 ruling (`S5_…_r4_delta.md:53-58`).

**Simplest action.** One coordinator ruling, `docs/evidence/RULING_RA-13_R4_scope_MAKER_<date>.md`, peer-reviewed, answering exactly one question: *does a MAKER E5 intake pass (B5) count as RA-13 §3 R4, given HUNT-1:38's off-window wording?*
- Judges disagree. Grok: likely NO on literal scope. Architect: arguably YES, materially different estimand. PMR: not by itself, a ruling is required. The ruling decides; this plan does not.
- **Pre-declared YES.** File `RULING_RA-13_R4_MAKER_<freeze-date>.md` on S5 freeze day. Required fields:
  - E5 record sha (B5 output on the frozen design);
  - S3 REACHABLE artefact path and sha;
  - frozen PREREG sha;
  - its own counter and cap per L-38: `calendar_cap_date` (≤ 2027-11-30), the day-60 outcome-blind check (about 2027-01-13), and the A1 stop, whichever fires first;
  - "S5 report is advisory-only; PROPOSAL arms nothing; activation is the manual trio."
- **Pre-declared NO.** The programme ends at the horizon. K-2 (Kalshi) is the next action (`RULING_RA-13:48,54,65`). MAKER S2/S3 may still run as evidence but cannot defer the KILL.
- Either way, an E5 refusal (B5) means no R4 and the KILL stands.
- Add calendar rows to the `PROGRESS.md` calendar:
  - "≤ S5 freeze day: R4 shell filed, or recorded as N/A";
  - "2027-01-25: FQ-v2-NO-TRADE review record due". Without it the ruling stays in force on its own clause (`RULING_FQ-v2-NO-TRADE_2026-10-08.md:52-54`).

**Do NOT build** an amendment to RA-13's date, a reading of the PREREG freeze as R4, or any R4 shell content before freeze day other than the field list.

**Completion criterion.** The scope ruling is committed with peer verdicts appended, and both calendar rows are present in `PROGRESS.md`.

**Risks.** (1) Answering after seeing the S2 label looks motivated. Mitigation: rule now; the question needs no outcome. (2) YES without a counter is a bare suspension. Mitigation: the L-38 field is mandatory in the shell. (3) The FQ review is forgotten. Mitigation: the calendar row.

**Peer reviewers.** architect; prediction-market-reviewer. No security-reviewer, because this is governance and touches no enablement.

## B5. E5 intake unpinned

**Blocker.** S5 E5 requires `register_hypothesis` to return a registered record "by a pure dry call against the current ledger records" (`S5_…_r3.md:31,89`). Nobody has run it.

**What the code says (VERIFIED).**
- `register_hypothesis` (`src/breezy/analysis/hypothesis_ledger.py:873`) is pure: it returns a `HypothesisRecord` and writes nothing. So the dry path is a direct Python call. `scripts/analysis/hypothesis_register.py` has no dry flag and accepts only pre-coded ids (`:545-557`), so it is not the path.
- MDE is recomputed as `(z(1−α_v)+z(0.80))·√0.25/√n` (`:859-870`), with `allocated_alpha = programme_alpha / MAX_HYPOTHESES` (`:1114-1115`; `PROGRAMME_ALPHA` 0.05 `:177`, `MAX_HYPOTHESES` 4 `:181`).
- **`mde_plausibility_bound` is a caller input, not computed** (`:885,1125`). Past rulings used 0.04 and 0.03 (`hypothesis_register.py:22-34`).
- Pinned inputs: `look_policy` SINGLE_LOOK, `order_quantity` 1, statistic `MEAN_EXCESS_PER_TAKE`, leg-share 0.20, θ 0.0695 (`:1071-1101`; constants `:196-212`).
- Passing `re_arm_gating`/`horizon_days` makes the record schema v3. A REGISTERED v3 is refused while `HORIZON_TOLLING_LANDED` is False (`:166`; docstring `:934-937`).

**Simplest action.**
1. **Pin the bound first, outcome-free.** prediction-market-reviewer proposes `mde_plausibility_bound` for the MAKER estimand from the spec's design effect size (`SPEC` §3 table; break-even w* vs design w). It must not use any Stage-0 rate. The coordinator records it in the B4 scope ruling, or in `docs/evidence/maker/E5_bound_pin_<date>.md`, before 2026-11-06.
2. Codex, read-only, runs a scratchpad script with `PYTHONPATH=/home/jon/breezy/src` and `/home/jon/breezy/.venv/bin/python -I`. It calls `register_hypothesis` with:
   - `existing_records` = the live ledger parsed read-only, path from `ledger_path(default_derived_root())`;
   - `min_station_days` = 200 (`SPEC:252-253`, design value);
   - k = 2 and k = 1;
   - `programme_alpha_override` None and 0.025;
   - the pinned constants above and the step-1 bound.
   No write.
3. Record each returned `status`, `allocated_alpha` (= alpha_family), `per_variant_alpha`, recomputed MDE, and schema version.
   - My arithmetic, UNVERIFIED until the call: MDE ≈ 0.109 (α_v 0.0125), 0.118 (0.00625), 0.126 (0.003125). Any bound below about 0.11 returns UNDERPOWERED_NOT_REGISTERED.
4. Also record: `programme_budget_remaining` on the live ledger (UNVERIFIED today); whether the S5 design needs `re_arm_gating` (if yes, REGISTERED is structurally refused, so route to B4 NO); and whether `MEAN_EXCESS_PER_TAKE` with variance 0.25 fits a maker win-rate gate (if not, say so; do not patch).
5. If any refusal or mismatch appears, it goes to the B4 ruling as input. It is not fixed here.

**Inputs available today.** Every input above, including design n, k, α and pinned constants. **Not used:** any Stage-0 or block-2 outcome (`r_lo`, 0.0814, 0.1364, n_eff).

**Do NOT build** a new dry-run tool or CLI flag, a ledger edit, a flip of `HORIZON_TOLLING_LANDED`, or a live append to `hypothesis_ledger.jsonl`.

**Completion criterion.** `docs/evidence/maker/E5_dry_call_<date>.md` records the bound pin reference, the exact call kwargs, the returned records, and the ledger sha read.

**Risks.** (1) The bound is chosen to pass. Mitigation: pin it before the call from spec numbers only, and have the peer check that order. (2) Reading the real ledger has side effects. Mitigation: open read-only and confirm the file mtime is unchanged.

**Peer reviewers.** prediction-market-reviewer; python-reviewer (the call is pure, no write).

## B6. Hygiene that could bite later

**Blocker.** Three small items: (a) the supervisor unit exports `BREEZY_TRADING_ENABLED=1` while orders are off; (b) the S2 trigger reaches the tape only through a symlink; (c) the S4 order-id charset is still an open residual.

**Simplest action.**
- **(a) LEAVE as-is, documented.**
  - The unit sets `BREEZY_TRADING_ENABLED=1` (`deploy/systemd/breezy-trade-supervisor.service:120`). The drop-in overrides only `BREEZY_ORDERS_ENABLED` (gatechain §1), so a `LiveTradingPermit` probably mints. That is inferred, UNVERIFIED.
  - It cannot send. There is no order permit, so the first refusal is `outside_permit_window`. Behind it come shadow_only, phase0, then halt and loss-stop (gatechain §2).
  - Adding the flag to the drop-in is not a one-liner. The file is sha-allowlisted (`src/breezy/runtime/health_dropins.py:51`). Its directive set is fixed to `Environment=BREEZY_ORDERS_ENABLED=0` (`:57`). Any change pages CRITICAL `allowlist_mismatch` (`:131-135`). The fix would need a code row in a module that must name no other trading gate (`:3-5`).
  - Record the reason in PROGRESS. The security-reviewer signs the LEAVE.
- **(b) DEFER the code row; keep the symlink.**
  - The census honours no env var. It reads only `--catalog-root` (`scripts/analysis/maker_tape_census.py:515`), defaulting to `~/.local/share/breezy/catalog/quote_tape/polymarket_us` (`:61-63`). `census_argv` omits that flag, and its flags are pinned by a test (`scripts/analysis/maker_stage0_trigger_io.py:134-140`). So a drop-in like `catalog-on-storage.conf` cannot help.
  - Record in PROGRESS and in `deploy/systemd/README.md` that the symlink is load-bearing for `breezy-maker-s2-trigger.service` until S2 closes. Also record that the drop-in's rollback path `…/polymarket_us.old-20261019` does not exist (gatechain §4).
  - After the S2 evidence commit, the minimal reviewed change is: `census_argv` passes `--catalog-root` from `BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG` when set, with one test row, then the full gate. Changing the trigger mid-block risks the S2 code pin; whether trigger code is sha-pinned by Doc A is UNVERIFIED.
- **(c) No action.** The S4 order-id charset residual stays fail-closed (`^[A-Za-z0-9_-]{1,64}$`, `S4_…_r4_delta.md:41,129`).

**Do NOT build** a drop-in change, a new drop-in, an allowlist row, a `health_dropins.py` edit, a census or trigger edit during block 2, symlink removal, or an S4 charset change.

**Completion criterion.** Three decision lines in `PROGRESS.md`; a README note for (b); the security-reviewer verdict on (a) appended to this plan's review file.

**Risks.** (1) Someone "cleans up" the symlink before S2 closes and the 10:05Z check reads an empty tape. Mitigation: the README note, plus the trigger's COVERED counts showing a drop. (2) A future enablement change forgets the latent live permit. Mitigation: the (a) line names it for the v2 resume or F9.

**Peer reviewers.** security-reviewer (a); python-reviewer (b).

## Sequencing

- **Now, in parallel, all read-only or docs:** B1 record; B2 NOTE and PROGRESS fix; B3 spec v0.4; B5 step 1 bound pin, then steps 2–4 dry call; B6 decision lines. Owners are independent and each brief is self-contained.
- **B4 scope ruling:** drafted now. It takes the B5 output as input when available. It must be committed **before 2026-11-06**, the first possible T=34 cross observation (`S2_second_look_plan_r3.md:82`), so that it is outcome-free with respect to the S2 label.
- **Waits on S2/S3:** the R4 shell is filed only on S5 freeze day (YES branch). The B6b code row lands only after the S2 evidence commit. The S5 E5 re-run on the frozen design is the S5 WP0 note (`S5_…_r3.md:89`).
- **Calendar:** 2027-01-13 day-60 check (if a shadow exists); 2027-01-25 RA-13 triage and FQ-v2 review record.

## Open questions for the review round

1. B5: what outcome-free source sets `mde_plausibility_bound` for a maker win-rate estimand, given the ledger statistic is pinned to `MEAN_EXCESS_PER_TAKE` with variance 0.25? Is that statistic even admissible for MAKER?
2. B4: is MAKER "materially different … for off-window hours" (HUNT-1:38)? If the answer is NO, should the ruling also say whether S2/S3 still run as evidence?
3. B3: reject PMR's pre-11-08 effective-n rule outright, or park it as a named option with its deadline stated?
4. B6a: does the security-reviewer accept LEAVE, given the live permit mints in shadow? Or does it want the allowlist row now despite the code and test cost?
5. B2: does Doc A pin `maker_stage0_verdict.py` or the spec by sha? This decides whether B3 v0.4 and B6b must wait for the S2 evidence commit.
