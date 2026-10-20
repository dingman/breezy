# RULING — BLOCKERS R4 scope and E5 intake (2026-10-19)

- **Type:** coordinator ruling.
- **Source plan:** `docs/plans/backlog/BLOCKERS_2026-10-19/plan_r2.md` (r2.1 READY; peer reviews in `docs/plans/backlog/BLOCKERS_2026-10-19/reviews/`).
- **Status:** Commit 2 — content FINAL; peer verdicts on §B4/§B5 Result recorded in the next commit.
- **Arms nothing. Sets no operator control.**

Short names used below: `SPEC` = `docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md`; `S5r3` = `docs/plans/backlog/MAKER_2026-10-12/S5_shadow_run_and_gates_plan_r3.md`; `S2r4d` = `docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r4_delta.md`; `S2r3` = `docs/plans/backlog/MAKER_2026-10-12/S2_second_look_plan_r3.md`; `verdict.py` = `scripts/analysis/maker_stage0_verdict.py`; `ledger.py` = `src/breezy/analysis/hypothesis_ledger.py`; `RA-13` = `docs/evidence/RULING_RA-13_programme_kill_2026-09-27.md`; `HUNT-1` = `docs/evidence/RULING_HUNT-1_all_hours_hunting_2026-09-26.md`; `DocA` = `docs/evidence/RULING_MAKER-S2_second_look_SEARCH_declaration_2026-10-16.md`.

**Invariants, restated.**
- Nautilus Trader is immutable. Nothing in this ruling modifies, patches, forks, bypasses or reimplements it.
- No code, no spec and no plan is edited. No PREREG is edited and no pre-registered date moves (including 2026-11-04..11-15 and 2027-01-25).
- Operator-reserved controls are referred to only as "the per-position cap" and "the daily budget". No value is assigned to either.
- No live enablement change. No ledger edit. Nothing is armed.

---

## §B2 — S2 label unit and the E1/§8 unit convention (DRAFT, peer text fixes applied in 1b)

**Scope.** Mechanism only. This section carries no block-1 or block-2 number as a scenario.

**Label unit (verified).**
- `_stricter` (the lower of the station-day and position units; empty unit on a non-empty denominator is a refusal) is defined at `verdict.py:107-116` and applied to base and stress rates at `verdict.py:215-216`.
- `verdict_label` compares `base` and `stress` with `FILL_FLOOR` (0.10) at `verdict.py:269-278`. `decide` calls it at `verdict.py:319`.
- `r_lo` is the stressed station-day point: `verdict.py:173-176`; `S2r4d:151` (`r_lo` = `r_lo_station_day`, S3 `f_kill`); `S2r4d:152` (stressed point, each unit, min over hypotheses).
- Pre-registered support for the stricter unit: `S2r4d:290` (r3 PMR §5 path 7, "stricter unit"); `SPEC:134-136` ("the gates use the stricter").
- The label and `r_lo` are different quantities by design.

**Byte-identity.** `scripts/analysis/maker_stage0_verdict.py` at `2380042f` is byte-identical to HEAD: `git diff 2380042f HEAD -- scripts/analysis/maker_stage0_verdict.py | wc -l` = 0.

**E1/§8 unit convention (convention ruling; E1 text is frozen and not edited).**
- `S5r3:282`: at MAX_RUNGS = 2, positions/day = 7.28·c·r, so `r` is a per-rung quantity. `S5r3:283`: at MAX_RUNGS = 1, positions/day = station-days/day = 3.64·c·r.
- `S5r3:296`: E1 feasibility reads `r_lo · c` ≳ 0.115 at MAX_RUNGS = 2 and ≳ 0.23 at MAX_RUNGS = 1. Both `r_lo_station_day` and `r_lo_position` exist (`S2r4d:151-152`), so the unit must be fixed.
- Convention, fixed before any block-2 result. The freeze-day S-1 test uses:
  - at MAX_RUNGS = 2: `r = min(r_lo_position, 1 − √(1 − r_lo_station_day))`;
  - at MAX_RUNGS = 1: `r = min(r_lo_position, r_lo_station_day)`;
  - `c` multiplies `r` afterwards (`r · c` against 0.115, `S5r3:296`).
- Justification. The k = 2 form inverts the §8 station-day formula (`S5r3:282`: station-days/day = 3.64·c·(1 − (1 − r)²), so `s = 1 − (1 − r)²` gives `r = 1 − √(1 − s)`). Since `1 − √(1 − s) ≤ s` for `s` in [0, 1], and `min` can only lower `r`, the rule can only fire S-1 in a superset of the cases where the station-day unit alone fires it (1−√(1−s) ≤ s on [0,1]; S-1 is a single freeze-day test).
- The k = 2 inversion assumes the two rungs fill independently at equal `r`. The spec says rungs are not independent weather draws (`SPEC:134`), which is why the `min` with `r_lo_position` is taken.

**Citation corrections (verified by opening the lines).**
- `S2r3:36,38` was cited in plan_r1 for the label unit but does not contain it: those lines are census-invocation and registry-narrowing text. They are replaced by `S2r4d:290` and `SPEC:134-136`.
- The stale rows are `S2r3:415-417` (timeline rows for 10-18..10-24, already past). `S2r3` stays unedited because it is frozen input.
- `DocA` pins only its own sha (`DocA:5`), the tail csv (`DocA:73`) and `trade_quantity_unit.json` (`DocA:70`). Code is frozen through `CODE_SHA` (`DocA:64`) from Doc B FINAL.
- The S2 run pins the spec sha256 (`scripts/analysis/maker_stage0_pins.py:86,332`).

**Do not build.** No label change, no station-day-only label, no edit to `verdict.py`, `DocA` or the trigger.

---

## §B3 — S5 read target 300/200 is the pole (DRAFT, peer text fixes applied in 1b)

**Decision.** 300/200 is kept. The effective-n (Kish) rule is REJECTED outright. It is not parked as an option.
- Position target 300: `SPEC:252-253` ("read target of 300 positions (200 × the 1.5 design-effect ceiling) and 200 station-days"); `S5r3:219` ("holdout positions ≥ 300 (200 × deff ceiling 1.5)").
- Effective-n gate 2, 200: `SPEC:262` (§6.4, "Gate 2 uses the realised effective n on the holdout") and `SPEC:310` ("Realised effective n ≥ 200 positions and ≥ 200 station-days"), stated separately.

**Reasons.**
1. An effective-n target cannot be pre-pinned as a number. The realised design effect is known only after the read, so a target expressed in effective n is post-outcome. Gate 2 (`SPEC:262`, `SPEC:310`) already uses realised effective n; if the realised design effect exceeds 1.5, gate 2 fails on a read-once design with no extension. Mechanism note: the ledger refuses any look policy other than a single look (`ledger.py:1071-1075`, `InvalidLookPolicyError`; `SINGLE_LOOK` is the only admitted design).
2. The realised design effect depends on outcomes (clustered fills), so an effective-n target is post-outcome.
3. Choosing n after the block-1 split is visible is the post-result pattern.

**Gate-9 floor.** The floor is 10/mean(p_YES of filled episodes). It is ≤250 iff mean p_YES ≥ 0.04. At 0.03 it is 333, above the 300 target, so gate 9 would then bind rather than the read target. Filled episodes have p_YES ≤ 0.06 (p_NO ≥ P_MIN 0.94), so the mean is bounded above. Source of the floor: `S5r3:174` (pooled m = Σ p_YES,i; m < 10 → UNSCREENED) and `S5r3:44` (S-5b).

**§9.15 is superseded by S5r3 §8.** Values copied verbatim: 412 / 165 / 83 days at MAX_RUNGS = 2, c = 1 (`S5r3:289,291,292`). `c` is unmeasured, so these are upper bounds on speed. The §8 table row at `S5r3:313` maps R6 "r_lo ≳ 0.2" (§9.15) to §8.

**No spec edit.** The S2 run pins the spec sha256 (`scripts/analysis/maker_stage0_pins.py:86,332`). The S5 PREREG names spec v0.3 (`S5r3:217`).

**Do not build.** No S5 redesign, no sequential or LD-OBF looks, no 300/200 change, no station-day-only gate, no effective-n target rule, no live-small holdout variant, no spec edit (v0.4).

---

## §B5 — E5 intake pins (FINAL at Commit 1b; frozen before the call)

**Ledger facts (verified).**
- `register_hypothesis` is `ledger.py:873-899`. It is pure. The status is decided by `recomputed_mde > mde_plausibility_bound` (`ledger.py:1116-1125`). The MDE is `recompute_mde` (`ledger.py:859`). Ask and slippage are recorded only (`ledger.py:1139-1141`).
- Tolerance `MDE_MISMATCH_TOLERANCE` = 1e-4 (`ledger.py:216`), compared at `ledger.py:1119`.
- `ledger.py:177` `PROGRAMME_ALPHA` = 0.05 (older default); `ledger.py:181` `MAX_HYPOTHESES` = 4. The override is checked at `ledger.py:957-964`; the split is `ledger.py:1114-1115`.
- With no strata and no horizon the record is schema v1. The v2 refusal is at `ledger.py:1159-1165`; the v3 refusals are at `ledger.py:1166-1184`, and both `HORIZON_TOLLING_LANDED` (`ledger.py:166`) and `PATH_B_SOURCE_GATE_LANDED` (`ledger.py:174`) are False.
- `read_hypothesis_ledger` is `ledger.py:1369-1394`. `programme_budget_remaining` is `ledger.py:811`. `DuplicateHypothesisIdError` is raised at `ledger.py:943-946`.
- `hypothesis_register.py` (`scripts/analysis/`) is not imported by the call. `freeze_commit` format is not validated there (`scripts/analysis/hypothesis_register.py:235-239`, cited only).

**Pin table (values copied verbatim from `plan_r2.md` §B5). Commit 1b changes the source/citation cells only, plus the `freeze_commit` value description (item 6 of the peer fixes; the concrete sha is still set at the call, so no pinned value changes).**

| kwarg | value | source |
|---|---|---|
| `hypothesis_id` / `hypothesis_class` | exact strings `"H-MAKER-NO-2026-10"` / `"pm_us_no_ladder_maker"` | Id RULED KEEP (round-1 text review, all three reviewers). Source: base name `H-MAKER-NO` (`SPEC:24`) plus the ledger's `-YYYY-MM` registration-month suffix convention (`scripts/analysis/hypothesis_register.py:151,180,211`; live ids `H-ARCHIVE-RECAL-2026-09`, `H-NO-SIDE-2026-09`, `H-OFFWINDOW-T4-2026-09`, `H-FORECAST-TAKER-RUNG-SCREEN-2026-09-20`). The id is used only in the exact-match duplicate check (`ledger.py:943`) and cannot change the status (decided only at `:1125`), so this is not a class (C) change. Not a duplicate of the 4 live ids (`reviews/r2-python-reviewer.md:14`). |
| `existing_records` / `disposition` | `read_hypothesis_ledger(<scratchpad copy>)` / default `"NORMAL"` | run step 4 |
| `registered_at` / `freeze_commit` | call date / the Commit 1b sha (must be HEAD or an ancestor of HEAD at the call) (not format-validated, `scripts/analysis/hypothesis_register.py:235-239` — cite only, never import) | §B5 Result must name 1b as the pin commit, earlier than the call. |
| `k_variants` | 1 | one design; `MAX_RUNGS` is not a variant (precedents `hypothesis_register.py:154,183,214`) |
| `programme_alpha_override` | 0.025, one value | RA-13 binds programme FWER at 0.025 (`RULING_RA-13:5`); the spec nests α in RA-13: `SPEC:312` ("α_family (nested in the RA-13 ledger"), `SPEC:334`, `SPEC:260`. `SPEC:298`'s α 0.05 belongs to the §6.9 adverse-selection test outside the efficacy spend (`SPEC:178`). CONFIRMS RA-9 A-3/A-3a override 0.025 (`scripts/analysis/hypothesis_register.py:217-219`). The ledger's `PROGRAMME_ALPHA` 0.05 (`:177`) is the older default. |
| `min_station_days` | 200 | `SPEC:252-253` design value |
| `mde_at_allocated_alpha` | `recompute_mde(per_variant_alpha=0.025/4/1, n_station_days=200)` = the full-precision returned value (0.118063…; python r2 ran it: 0.11806302799), never a rounded literal (tolerance 1e-4, `:1119`, `:216`) | `:859` |
| `mde_reference_ask` | 0.80, the design bid | Break-even is ask-based (`:851-856`); a maker's cost basis is its bid. For every rung with p_NO ≥ P_MIN 0.94, `p_no − E_MIN − fee` ≥ 0.829, so `b_max` = B_CAP 0.80 (`SPEC:72,83`). |
| `mde_slippage_allowance` | 0.01 | The spec names none. Programme convention is the AUD-12a retained placeholder (`RULING_RA-13:13`; precedents `hypothesis_register.py:169,202,229`). |
| `mde_variance_bound` | 0.25 | `VARIANCE_BOUND` (`:196`), Popoviciu; no justification needed |
| `mde_plausibility_bound` | **0.08** (= b 0.80 / w 0.90 cell 0.089 − 0.01 slippage = 0.079, rounded) | cell ENDORSED by architect, PMR and python-reviewer in `reviews/r2-*.md`; any bound in [0.079, 0.118) gives the same status |
| fixed constants | `power_is_primary_only=True`, `mde_fee_theta=0.0695`, `max_single_day_leg_share_cap=0.20`, `station_day_statistic="MEAN_EXCESS_PER_TAKE"`, `order_quantity=1`, `look_policy="SINGLE_LOOK"` | `:196-212,1000-1018` |
| not passed | `re_arm_gating`, `horizon_days`, `variant_stratum_filters` (schema v1) | — |

**Id ruling (Commit 1b): KEEP `"H-MAKER-NO-2026-10"`.** The round-1 text review ruled KEEP on the id (see Peer verdicts). The `-2026-10` suffix follows the ledger's registration-month convention; `SPEC:24` supplies the base name. The string is not a duplicate of a live id.

**Bound unit check (verified).**
- The `SPEC:138-147` column is "EV per contract" = `w − (b + θ·b·(1−b))` (`SPEC:139-140`). The fee column implies θ ≈ 0.0694 (`SPEC:146`), which matches `EVIDENCED_FEE_THETA` 0.0695 (`ledger.py:204`).
- `MEAN_EXCESS_PER_TAKE` is the mean of `W − BE`, with `BE = a + θa(1−a) + slippage` (`ledger.py:851-856`). The units are equivalent.

**Correction to the premise.** 0.08 is NOT the table maximum. The maximum is +0.225 (b = 0.70, w = 0.94; `SPEC:144`, row 0.70). The +0.081 cell is the b = 0.85 row (`SPEC:147`), a bid the design never places (B_CAP 0.80, `SPEC:72`).

**Derivation of the pinned bound.** Design-bid row b = 0.80 at w = 0.90: +0.089 (`SPEC:146`). Net of 0.01 slippage that is 0.079, rounded to 0.08 at the precision of past bounds (`hypothesis_register.py:22-34`).

**Disclosed alternative.** The w = 0.94 cell nets 0.119 (`SPEC:146`, +0.129 less 0.01), which exceeds the MDE 0.1181 by 0.0009 and would REGISTER. It is not the plausibility value. w = 0.94 equals P_MIN (`SPEC:72`), the lowest model p_NO for any bid, so it assumes perfect tail calibration and zero adverse selection. The spec names adverse selection as the falsifier (`SPEC:49-52`), states the hostile priors (`SPEC:41-47`), and reads observed 0.85 as its case (`SPEC:149-154`). The cell choice is made with the MDE known, as in every precedent, and is disclosed here.

**Sensitivity (L-56).** `recomputed_mde > bound` decides the status (`ledger.py:1125`). Every bound in [0.079, 0.118) is below the recomputed 0.1181 and gives the same status. Only a bound at or above the recomputed value would change it. Concretely:
- The [0.079, 0.118) interval is the sensitivity at the pinned cell only. Any bound ≥ 0.1181 flips the status.
- Rounding 0.079 to 0.08 rounds in the permissive direction (a higher bound makes REGISTERED easier) and is status-neutral.
- Under the spec's own table the w = 0.90 cells at lower bids net more than the MDE and would REGISTER: b = 0.75, 0.137 − 0.01 = 0.127 (`SPEC:145`); b = 0.70, 0.185 − 0.01 = 0.175 (`SPEC:144`).
- The pinned cell (b = 0.80, the B_CAP bid, `SPEC:146`) is the lowest-EV bid at or below B_CAP at w = 0.90, so it is the register-averse choice made with the MDE known.
- The bound is "the plausible effect at the B_CAP bid", not a ceiling on plausible effect.
- L-56: S2 is tape replay; no fills exist or count toward n=200; n stays 200 per SPEC:252-253.

**Pre-declared expected outcome.** `UNDERPOWERED_NOT_REGISTERED`; `is_zero_look=True`; `allocated_alpha=0.0`; `per_variant_alpha=0.0`; `schema_version=1`; programme budget remaining 4.

**Peer endorsements of the cell (quoted; required before the call).**
- Architect, `reviews/r2-architect.md` §2 (line 24): "**Endorsement (required): the w=0.90, b=0.80 cell, giving a bound of 0.08.**"
- PMR, `reviews/r2-prediction-market-reviewer.md` Item 2, "Cell endorsement" (line 19): "I ENDORSE b=0.80, w=0.90, net of 0.01 slippage = 0.079, pinned 0.08."
- Python-reviewer, `reviews/r2-python-reviewer.md` "Cell endorsement (item 2)" (line 24): "I endorse the b=0.80, w=0.90 cell net of 0.01 slippage (0.089 - 0.01 = 0.079 -> 0.08)."

**Procedure pinned (executed in the B5 call, not here).**
1. Run `~/.claude/bin/grok-check.sh` before any dispatch.
2. Grok read-only dispatch, script exactly as in the brief, run as `/home/jon/breezy/.venv/bin/python -I` with `PYTHONPATH=/home/jon/breezy/src`.
3. Ledger source: `~/.local/share/breezy/derived/hypothesis/hypothesis_ledger.jsonl` (hardcoded, never via `default_derived_root()`). Copy it to the executing agent's scratchpad. Record the sha256 of the ORIGINAL ledger before and after, and the copy's sha256.
4. Read the COPY with `read_hypothesis_ledger` (`ledger.py:1369-1394`); record `programme_budget_remaining(records)` first.
5. Exactly ONE call to `register_hypothesis` with the pins above.
6. The script imports only from `breezy.analysis.hypothesis_ledger`. It never imports `hypothesis_register.py` or `write_hypothesis_ledger`.
7. The script catches ANY exception from the call and records its type and message as an outcome. Named outcomes, recorded not bugs: `DuplicateHypothesisIdError` (`ledger.py:943-946`), `MissingRegistrationInputError`, `MdeMismatchError`, `ProgrammeBudgetExhaustedError`, `HorizonTollingNotLandedError`, `PathBSourceGateNotLandedError`. Also recorded, unreachable with these pins but never a crash: `UnknownHypothesisLedgerSchemaError` (`ledger.py:238`), `DuplicateHypothesisLedgerRecordError` (`ledger.py:246`), the `ValueError` from the α guard (`ledger.py:960-964`), `StaleFeeThetaError` (`ledger.py:290`).
8. The α-override block is `ledger.py:948-964`; the status comparison is `ledger.py:1125` with recompute at `ledger.py:1116-1118`; the v2 refusal starts at `ledger.py:1159`.
9. python-reviewer re-derives the arithmetic: z(0.99375) ≈ 2.4977, (2.4977 + 0.8416) · 0.5 / √200 ≈ 0.1181. This agrees with the off-window T4 record, 0.0964 at n=300 with the same α (`scripts/analysis/hypothesis_register.py:223`).

**Pre-declared outcome.** UNDERPOWERED_NOT_REGISTERED.

**Do NOT build** a new dry-run tool or CLI flag, a ledger edit, a flip of `HORIZON_TOLLING_LANDED` or `PATH_B_SOURCE_GATE_LANDED`, a live append to `hypothesis_ledger.jsonl`, or a script that imports `hypothesis_register.py`.

**Completion criterion.** Ruling §B5 Result records the pin commit sha (1b, earlier than the call), the kwargs, the returned record or exception, the budget remaining, and the ledger sha before and after.

---

## §B5 — Result

- **Pin commit (1b):** `8f70d1d6c2863eb0cf8637500f260e01c3efaba6` (2026-10-20T00:09:23Z), earlier than the call timestamp 2026-10-20T00:12:04+00:00.
- **Call:** ONE `register_hypothesis` call, run once via Grok read-only (`~/.claude/bin/grok-check.sh` EXIT=0), `/home/jon/breezy/.venv/bin/python -I`, `PYTHONPATH=/home/jon/breezy/src`, exit 0. The script imports only from `breezy.analysis.hypothesis_ledger`.
- **Kwargs:** as pinned, no change (see the §B5 Pin table above). `existing_records` = `read_hypothesis_ledger` of the scratchpad copy; `disposition` default `NORMAL`; `registered_at` = 2026-10-20.
- **Disclosed deviation (not hidden, not re-run):** `freeze_commit` echoed `592cd1c54eb0a3e351a8cd54ae1de51806993b2a` (Commit 1c, a docs-only descendant of 1b: ancestor check exit 0; `git diff 8f70d1d6 592cd1c5 -- src/` empty) rather than the 1b sha the Commit-1b pin row names. The call was launched before the coordinator's correction reached the runner. `freeze_commit` is echo-only: no branch of `register_hypothesis` reads it (signature `ledger.py:873-898`; status decision `:1125`), so the status is unaffected. The one-call rule (plan §B5) forbids a re-run. The original Commit-1 wording "HEAD 40-hex sha at the call" is satisfied exactly. Peers rule on acceptance at the final review.
- **Ledger integrity:** SHA_BEFORE `e335384ef5156c0bb097631278375471b7cb21ae925aa787ee7e744c985d1cd5`; copy `e335384ef5156c0bb097631278375471b7cb21ae925aa787ee7e744c985d1cd5`; SHA_AFTER `e335384ef5156c0bb097631278375471b7cb21ae925aa787ee7e744c985d1cd5` (measured at Commit 2). Live ledger: 4 lines; `grep -c "H-MAKER-NO"` = 0 (no live append).
- **stdout (verbatim, `/tmp/claude-1000/-home-jon-breezy/1676b5d2-4ba0-4fd7-9ec1-56bf76c71ea7/scratchpad/b5/stdout.txt`):**

```text
N_RECORDS 4
IDS ['H-ARCHIVE-RECAL-2026-09', 'H-FORECAST-TAKER-RUNG-SCREEN-2026-09-20', 'H-NO-SIDE-2026-09', 'H-OFFWINDOW-T4-2026-09']
BUDGET_REMAINING 4
MDE 0.11806302799068735
FREEZE_COMMIT 592cd1c54eb0a3e351a8cd54ae1de51806993b2a REGISTERED_AT 2026-10-20
RESULT {"allocated_alpha": 0.0, "freeze_commit": "592cd1c54eb0a3e351a8cd54ae1de51806993b2a", "hypothesis_class": "pm_us_no_ladder_maker", "hypothesis_id": "H-MAKER-NO-2026-10", "is_zero_look": true, "k_variants": 1, "look_policy": "SINGLE_LOOK", "max_single_day_leg_share_cap": 0.2, "mde_at_allocated_alpha": 0.11806302799068735, "mde_fee_theta": 0.0695, "mde_plausibility_bound": 0.08, "mde_reference_ask": 0.8, "mde_slippage_allowance": 0.01, "mde_variance_bound": 0.25, "mde_variance_bound_justification": null, "min_station_days": 200, "order_quantity": 1, "per_variant_alpha": 0.0, "power_is_primary_only": true, "registered_at": "2026-10-20", "schema_version": 1, "station_day_statistic": "MEAN_EXCESS_PER_TAKE", "status": "UNDERPOWERED_NOT_REGISTERED"}
```

- **Outcome:** status `UNDERPOWERED_NOT_REGISTERED`; `is_zero_look` true; `allocated_alpha` 0.0; `per_variant_alpha` 0.0; `schema_version` 1; programme budget remaining 4. This matches the pre-declared outcome (§B5 "Pre-declared expected outcome").
- **Re-derivation:** python-reviewer verdict: `recompute_mde` = 0.11806302799068735, identical to the call's value; z(0.99375) = 2.4977054744; z(0.8) = 0.8416212336. T4 cross-check 0.0964 at n=300 (`scripts/analysis/hypothesis_register.py:223`).

---

## §B4 — RA-13 KILL vs MAKER (R4 scope)

**FINAL (Commit 2) — peer verdicts pending.**

**Scope.** Decides whether the RA-13 programme KILL (2027-01-25) is pre-empted by an R4 event. Branches are pre-committed here, before the §B5 result exists. Nothing in this section reads a §B5 outcome.

**RA-13's literal R4 text.** `RULING_RA-13_programme_kill_2026-09-27.md:53`: "R4: a new estimand that clears its power check at intake" (cited there as `[VERIFIED RULING_HUNT-1:38]`). Verified by opening the line.

**HUNT-1:38, quoted in full (byte-exact; `RULING_HUNT-1_all_hours_hunting_2026-09-26.md:38`, trigger 4):**
> A materially different family or estimand is proposed for off-window hours. That proposal enters through AUD-18 registration, never by widening the window.

**Disposal chain (CONFIRMS RA-13 and HUNT-1, L-32: the prior rulings were read, not inferred from the backlog row).**
1. HUNT-1 trigger 4 is the off-window clause. It is scoped to the hour-window hunt.
2. RA-13 re-opens the trigger-4 path at `RULING_RA-13:18` ("a materially different estimand entering through AUD-18").
3. RA-13 restates the test as intake at `:53` and cites HUNT-1:38 as provenance only.
4. MAKER rests bids; it is not an hour-window hunt.
5. Therefore R4 == ledger intake returns REGISTERED. HUNT-1:38 is not a second test.
6. Both readings give NO under UNDERPOWERED. The literal reading (Grok's) and this reading agree.
7. An E5 pass alone never files the shell; only the ruling does.

**DECISION BRANCH — NO (pre-declared expected; mechanically the result of §B5 = UNDERPOWERED_NOT_REGISTERED).**
- KILL fires at the first triage on or after 2027-01-25 (`RULING_RA-13:48`). The next action is K-2 (`RULING_RA-13:54,65`).
- S2/S3 still run as evidence. They cannot defer the KILL and cannot be cited as R4 (`docs/plans/backlog/MAKER_2026-10-12/S5_shadow_run_and_gates_plan_r4_delta.md:56-58`: "S2/S3 artifacts are inputs to R4, never a substitute for it").
- Calendar: `docs/core/PROGRESS.md:91` already carries the row `≤ 2027-01-24 | RA-13 R4 record (ledger REGISTERED + shell) or N/A (BLOCKERS B4)`. At Commit 2, on NO, annotate that row "(N/A per this ruling)". Do not add a second 2027-01-25 row. No date moves.

**DECISION BRANCH — YES (conditional; applies only if §B5 returns REGISTERED).**
- The R4 event is a REGISTERED record written through `register_and_persist` (`scripts/analysis/hypothesis_register.py:274-297`, verified: it reads the ledger, calls `register_hypothesis`, then rewrites the file with the record appended). That needs one reviewed constants row at freeze (deferred code row).
- UNVERIFIED: whether RA-9 A-3 requires a schema v3 record for any REGISTERED look-taking record. The v2 refusal is at `src/breezy/analysis/hypothesis_ledger.py:1159-1165` (verified); v3 is refused while `HORIZON_TOLLING_LANDED` (`:166`) and `PATH_B_SOURCE_GATE_LANDED` (`:174`) are False (verified). The constants row must settle this.
- YES is VOID unless the ledger record and the R4 shell are both committed on or before 2027-01-24.
- The R4 shell holds only the L-38 counter and cap, plus the line "S5 report is advisory-only; PROPOSAL arms nothing; activation is the manual trio." No other content before freeze day.

**Do NOT (binding).**
- No amendment to RA-13's date (2027-01-25 stands).
- No reading of the PREREG freeze as an R4 event.
- No R4 shell content before freeze day other than the field list.

**Risk table.**

| Risk | Control |
|---|---|
| Motivated reading after block 2 (a REGISTERED-looking outcome reinterpreted as R4) | Branches frozen here, before §B5 result; deadline before 2026-11-04; B5 purity (L-34: the trigger is pinned; no re-look). |
| YES without a counter | L-38 fields mandatory in the R4 shell (counter and cap). A stop rule whose counter cannot increment is a missing stop. |
| Misreading a prior ruling | CONFIRMS cites above (L-32): RA-13:18, :48, :53, :54, :65 and HUNT-1:38 were opened and quoted, not paraphrased from the backlog row. |

**DECISION: NO. §B5 returned UNDERPOWERED_NOT_REGISTERED (Commit 2); R4 is unmet. The NO branch applies: KILL fires at the first triage on or after 2027-01-25 (RULING_RA-13:48); next action K-2 (:54,65). S2/S3 still run as evidence and cannot defer the KILL or be cited as R4.** Mechanical rule (unchanged): status UNDERPOWERED_NOT_REGISTERED or any exception → NO; REGISTERED → YES.

---

## Peer verdicts

**Round-1 text review (input to Commit 1b; no pin value changed).**
- prediction-market-reviewer: REQUEST_CHANGES (warning; text only). Id KEEP. MDE 0.11806302799 and 412 / 165 / 83 re-derived.
- python-reviewer: APPROVE. Id KEEP. All 12 NORMAL-path inputs supplied; `recompute_mde` = 0.11806302799068735.
- architect: REQUEST_CHANGES (text only). Id KEEP.
- All three ruled KEEP on every §B5 value. All requested text fixes are applied in Commit 1b. Final verdicts on §B4 are pending Commit 2.

---

## What this ruling does NOT decide

- No PREREG, pre-registered date, spec, code, live-enablement or budget/position-cap change. No ledger edit.
- `allow_short` stays False. No safety, settlement, contract or NO-SEND test is weakened. Guards are widened only by one reviewed row (L-12). The egress firewall is untouched. No gate changes after a result (L-34).
- B4 pre-commitments, frozen now: an E5 pass alone never files the shell; no RA-13 date amendment; S2/S3 cannot defer the KILL or count as R4.
- The drop-in `fq-v1-halt-orders-off.conf` (`5f2981e5:docs/core/PROGRESS.md:29`) is untouched.
- Activation remains the manual trio (`5f2981e5:docs/core/PROGRESS.md:82-83`). No auto-arm path is created.
