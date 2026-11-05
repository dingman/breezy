# F5 pin request r3: the F6 loss-stop floor (A1) and the F7b guard (A2)

<!-- planner, 2026-10-08. r3 of F5-pin-request_r2.md. Applies the "Carried into A1/A2 r3" items of F5-pin-request_r1-review-merge.md ("r2 verification" section): D1–D6, the M8 positive-control escalation, the G3 floor (≥ 2.5 × α_floor), and the four endorsed §10 domain rulings. Only §4, §5, §6 Phase 2/3 and §8–§11 are revised; §0–§3 are replaced by the pointer below and §7 is unchanged. No Monte Carlo was run for this document. Operator-reserved controls are neither named by their environment-variable names nor assigned. No frozen PREREG is edited. No checker or test is weakened. -->

## 0. Pointer (replaces r2 §0–§3)
A0 frozen 43cc3e0f (`F5_prereg_v2_amendment_A0.json:2`, `frozen_sha` 43cc3e0f08bab20eab71792643ed5b40bb60eb7e); see r2 §2–§3 and `scripts/analysis/prereg_amendment_check.py`. The parent `F5_prereg_v2_design.json` stays frozen at 072ab026. The amendment envelope, the additive rule, the sibling checker and `load_verified_amendment` (`prereg_amendment_check.py:358-377`) are exactly as built for A0. r2 §1 (binding lessons and venue facts) still applies. The only lesson re-read for r3 is L-40, with its 2026-09-25 amendment (`docs/core/LESSONS.md:1382-1403`).

**Plain statement carried forward and sharpened.** In the YES-longshot regime the √t floor is at best a gross-loss tripwire. r3 adds two new rows that can only raise c: an exit-cost row (S4) and a correlated-station row (S5). It also adds a hard power floor (G3 ≥ 2.5 × α_floor). The likely gate outcomes are therefore a narrowly passing tripwire at α_floor 0.10, or `unreachable_veto`. Either is acceptable. A dead stop is not.

## 4. A1: the F6 loss-stop floor

### 4.0 Rulings applied
| Source | Ruling | Where |
|---|---|---|
| Q5 | α_floor = 0.10, subject to the M2 gate | §4.6 |
| Q6 | t = settled station-days, standardised bundle increments | §4.1 |
| Q7 | qty ≡ 1 per contract; dollar P&L is diagnostic only | §4.3 (D3 makes it explicit) |
| Q8 / Q9 | Horizon 2027-01-25; fail-closed past it | §4.1 step 9 |
| Q10 / M11 | Anchor = v2 arming; re-arm needs a new ruling and a new epoch | §4.4 |
| §10.1 (endorsed) | Refusal channel = unlink `latest.json` **after** a durable refusal-reason record | §4.4.4 |
| §10.2 (endorsed) | Anchor = (a), the autonomy ledger row; refuse when absent | §4.4.1 |
| §10.3 (endorsed) | If G1 fails at 0.10: the smallest α in {0.20, 0.30} where G1 passes **with margin**, else `unreachable_veto` | §4.6 |
| §10.4 (endorsed) | Tripwire freeze only if G3(−0.16) ≥ 2.5 × α_floor | §4.6 |
| D1–D6 | See the change log (§11) | §4.1–§4.6 |

### 4.1 S_t defined end to end (r2 §4.1 revised; [r3] marks a change)
For each settled station-day d of the FQ v2 family **within the current epoch** (§4.4):

1. **Fills.** Unchanged from r2: the leg comes from the instrument, a NO buy is BUY on the NO-leg instrument at the NO price, and the wire price is never used.

2. **[r3, D1] Same-rung netting is a deterministic, zero-variance mean shift.**
   - For each rung r that has open BUY quantity on both legs, the open lots are `q_y,r` and `q_n,r`. Open means after exits, using `_lot_fraction` (`src/breezy/analysis/labeling/reconcile.py:620-639`), exactly as `_entry_records` pairs them (`reconcile.py:705-714`).
   - The paired rung contributes **one unit** (D3, §4.3):
     `δ_net,r = 1 − BE̅_y,r − BE̅_n,r`
     where BE̅ is the leg's ledger break-even (step 3).
   - It has zero variance, because the pair pays exactly 1 whatever the outcome. The C2 `netting_offset` record pays `paired × 1` with `realised_pnl` 0 (`reconcile.py:717-733`). `δ_net,r` is negative whenever the rung is overround.
   - **It enters x_d** (step 8). It never enters σ_d.
   - **Consistency with the null.** Under the §4.2 categorical joint, a same-rung YES+NO pair's P&L is `1{R=r} − BE_y + 1{R≠r} − BE_n = 1 − BE_y − BE_n`, which is deterministic. D1 therefore records the null's own value of the pair, and the MC carries the same shift (§4.5).
   - **Cross-check (fail closed).** Every paired rung must have a C2 `netting_offset` record. If `CashRecords.unknown_netting_slugs` is non-empty (`reconcile.py:616`, filled at `:719-720`), the producer refuses (§4.4.4).
   - Only the **unpaired remainder** (the side with `q_side − paired > 0`) goes to step 3. This keeps step 4 clear of `_SameRungOppositeSidesRefusal` (`src/breezy/settlement/current_rung_hold_v2.py:235-239`, raised at `:266-271`).

3. **[r3, D3] One leg row per remaining (rung, side), qty ≡ 1.** For each remaining (rung, side), build exactly one `StratumRow` (`current_rung_hold_v2.py:87-130`):
   - `entry_ask = BE̅`, where `BE̅ = Σ(cumulative_cost + cumulative_fee) / Σ cumulative_qty` over that leg's BUY records (the ledger fee, M9);
   - `fee = Decimal(0)`, because the fee is already inside BE̅;
   - `qty = Decimal(1)`;
   - `rung` = the base slug, plus `side` and `held` from step 5.
   - Because there is one row per (rung, side), `_fold_same_rung_rows` never sees same-rung duplicates. Its differing-ask/fee refusals (`:273-284`) therefore cannot fire on multi-fill legs.
   - **Fail closed:** any `fee_reconciled == False` or missing fee refuses (§4.4.4). After a FAIL latch this no longer matters (§4.4.3).

4. **Bundle.** `combine_station_day` (`current_rung_hold_v2.py:296-343`) runs on the step-3 rows and gives `x_rand = Σ(h_i − BE̅_i)` and the exact L-40 variance (same-side `S(1−S)`; mixed `S − (q_y − q_n)²`, `LESSONS.md:1399`).
   - If it raises `StationDayAdmissionRefusal` for Σq > 1 (`:329-334`), the day is **not dropped**. σ_d comes from the §4.2 shrunk joint through the shared pure function, and x_rand stays realised (unchanged from r2).

5. **Realised outcomes come from the venue** (C2 cash records, `reconcile.py:642-678`). Unchanged.

6. **Exits.** As in r2, `h_eff = (1 − f)·h + f·v`, where v is the per-contract net exit proceeds (`_exit_record`, `reconcile.py:681-694`). The variance stays the unexited Bernoulli value.
   - **[r3, D2]** The realised exit cost is in x_d by construction. The *calibration* allowance for exit cost is the binding MC row S4 (§4.5), which raises c.

7. **Voids.** A voided leg contributes 0 to x_d and 0 to the variance.
   - **[r3, D6]** A void that arrives after a FAIL latch changes nothing (§4.4.3).

8. **[r3] Increment and clock.**
   - `x_d = x_rand + Σ_r δ_net,r + carry`.
   - **A day with σ_d > 0 is a tick:** `Z_d = x_d / σ_d`, then carry := 0.
   - **A day with σ_d = 0** (pairs only, or every leg void or degenerate) is **not a tick**. Its `Σ δ_net` is added to `carry` and enters the next tick's x_d.
   - The artefact's diagnostics report `pending_netting_carry`.
   - Pairs-only days should be rare, because the FQ admission path refuses same-rung opposite sides (`continuous_no_side.py:328-338`, via `refuse_if_sibling_leg_traded`). The producer reports their count.
   - `S_t = Σ_{ticks ≤ t} Z_d`. The null mean is **not** subtracted (unchanged).

9. **Rule.** FAIL iff `S_t < −c·√t` for some t in [t_min, t_at_horizon], where t_at_horizon is the last tick whose climate day is ≤ 2027-01-25.
   - Past the horizon the producer writes no PASS (Q9).
   - Under `floor_mode: unreachable_veto` the producer never writes PASS (§4.6).

10. **[r3, D6] Epoch and latch:** see §4.4.

### 4.2 The H0 bundle joint, including overround (M3)
Unchanged from r2 §4.2: the categorical joint, the YES-first shrink, a refusal when Σ_NO q > 1, and one pure function shared by production and the MC.

**[r3] The conservativeness claim is now tested, not assumed.** r2 argued that because every leg's drift is ≤ 0 under the shrink, the calibrated c is ≥ the c of any feasible zero-drift null. The domain caveat is answered by MC row S6 (§4.5): the **final** c is applied to the feasible zero-drift templates (Σq ≤ 1, exact marginals, no shrink, no netting shift). Their crossing rate must be ≤ α_floor + 3·SE. If S6 fails, the claim is false for this pool: the gate fails, and A1 does not freeze until the peer loop rules.

### 4.3 Quantity handling (D3, consistent with L-40)
- **Meaning of qty ≡ 1.** The floor's unit is one contract per distinct exposure on a station-day. That means each unpaired (rung, side) leg counts as one contract (step 3), and each paired rung counts as one pair (step 2). A leg held at 5 contracts and a leg held at 1 contract contribute the same `h − BE̅` to x_d and the same `q(1−q)` term to σ_d².
  - Because every contract on one leg shares the same outcome h, `h − BE̅` is exactly the leg's **per-contract average P&L**.
  - x_d is therefore the per-contract P&L of a one-contract-per-leg book.
  - σ_d is `combine_station_day`'s variance at qty ≡ 1, which is the scope L-40 validated (`LESSONS.md:1391`).
- **Why qty is not weighted:**
  1. L-40 measured that qty > 1 across sibling rungs de-calibrates a boundary sized at qty = 1 (5.9 % against a ≤ 3.5 % target; `LESSONS.md:1391`).
  2. `StratumRow.qty` is "fixed at `Decimal(1)` by every real caller today" (`current_rung_hold_v2.py:92-97`).
  3. A qty-weighted σ would scale with order size. Order size is bounded by the operator-reserved controls, and the spec forbids deriving the floor from either cap.
- **What this costs.** The floor measures per-contract trading quality, not dollars lost. A loss concentrated on one large position counts once. Dollar P&L (`Σ q·(h − BE̅)`, including the netted dollars) is written to the artefact's diagnostics only. Dollar exposure is bounded by the operator-reserved controls, which this floor neither reads nor replaces.
- **Partial fills and multi-contract orders** are cumulative per venue order (`DurableFillRecord`). Summing them into BE̅ handles re-entries.

### 4.4 Epoch, anchor, FAIL latch and refusal channel (D6, §10.1, §10.2)

#### 4.4.1 Anchor: the autonomy ledger row (ruling §10.2(a))
- **Source.** The autonomy registry `transitions` table, read-only (`SELECT_ROWS`, `src/breezy/persistence/autonomy/registry_schema.py:123`, decoded by `row_from_record` `:145-159` into `TransitionRow`, `src/breezy/persistence/autonomy/schemas.py:353-398`).
- **The arming row.** The latest row (by `venue_seq`) that meets all of these conditions:
  - `family_id` == the FQ v2 family;
  - `to_state` == `CHAMPION`, a sender state (`_SENDER_STATES`, `src/breezy/persistence/autonomy/fold.py:152`);
  - `from_state` is not in the sender states (an entry into sending, not a CHAMPION→CHAMPION row);
  - a non-empty `policy_ruling_id` (`schemas.py:394`; `__post_init__` forces id and sha to be present together, `:408-409`).
- **`armed_at`** = that row's `ts_ns` (`schemas.py:365`).
- **A row with no policy ruling never starts an epoch.** A RESUME without a ruling therefore keeps the old epoch, and with it any latched FAIL (M11).
- **Refusal when absent.** If no row qualifies, the producer refuses (§4.4.4).
  - The same applies if the registry file does not exist, cannot be opened read-only, or fails to decode (`RowDecodeError`).
  - The producer opens the registry read-only and checks it exists first. It never creates the database. This is the same fail-open hazard documented for the state store at `src/breezy/runtime/exit_control_precondition.py:60-73, :80-81`.
- **Consequence (flag to the arming owner):** if FQ v2 is armed without writing this ledger row, the floor vetoes every entry permanently. That is the fail-closed direction, and it is intended.

#### 4.4.2 Epoch id (D6)
- `epoch_id` = the arming row's `transition_id` (64-hex sha256, `schemas.py:361`, checked at `:403`; recomputable through `computed_transition_id`, `:446-458`).
- **It is carried in the artefact in two ways, without changing F6's contract:**
  1. As a field `epoch_id` in `latest.json`. The probe reads only named keys (`src/breezy/strategy/forecast_quantile_ladder/loss_stop_probe.py:344-362`), so an extra key is accepted as is. An F6b test pins this; the probe is not edited.
  2. Bound into the digest through `truth_sha`. `truth_sha` = sha256 of the canonical JSON (r2 §1.3 form) of `{"epoch_id": <id>, "records": <sorted consumed C2 cash-record identities (kind, fill_key, payout as a string, dated_at_ns)>}`. `compute_digest` (`loss_stop_probe.py:108-110`) covers `truth_sha`, so a forged `epoch_id` breaks the digest.
- Every refusal record and latch record (below) also carries `epoch_id`.

#### 4.4.3 Durable FAIL latch (D6)
- **Why it is needed.** The probe latches FAIL **in memory only**:
  - `_state` starts as UNKNOWN on every construction (`loss_stop_probe.py:277`);
  - FAIL is sticky only within the process (`:321-325`, `:373-374`);
  - the family halt is set-only (`:404-415`).

  The producer recomputes S_t statelessly (r2 M11). A late `fee_reconciled` correction (which changes BE̅), a late void (which removes a leg), or a ledger rewrite could therefore bring a recomputed S_t back above the boundary. After a node restart, the probe would then accept PASS.
- **Rule.** On the first run where step 9 yields FAIL for epoch E, the producer writes
  `$DATA/derived/fq-loss-stop/fail_latch/<epoch_id>.json`
  containing {`epoch_id`, `first_fail_tick`, `S_t`, `boundary`, `c`, `t_min`, `truth_sha`, `as_of`}. It is written exclusively (`O_CREAT|O_EXCL`), mode 0600, with the file fsynced and then the directory fsynced. Only after that does it write the FAIL artefact.
- **On every later run** it checks for the latch **before** reading any ledger input. If `fail_latch/<current epoch_id>.json` exists, the producer writes `verdict: FAIL` (fresh `as_of`, so `as_of` stays monotonic, `:360-361`) without recomputing S_t. No input, fee reconcile, void or refusal condition can un-latch it.
- **Latch beats refusal.** A latched epoch writes FAIL even when inputs are unreadable. FAIL is the stronger veto, and it also halts the family.
- **Nothing in code deletes a latch.** Only a new epoch (a new qualifying arming row, §4.4.1) starts a fresh S_t at 0. The old latch stays as evidence.
- **Location.** The latch directory is a sibling of `latest.json` inside the probe-checked directory (`_check_parent_dir`, `loss_stop_probe.py:150-161`). It must not be group/other writable. The probe never reads it.

#### 4.4.4 Refusal channel: unlink after a durable reason record (ruling §10.1)
A refusal happens on any input refusal: a missing anchor, an unreconciled fee, unknown netting, Σ_NO q > 1, a C2 read error, past the horizon, or `unreachable_veto` mode. In that case, and only when no latch exists for the epoch:
1. Write `$DATA/derived/fq-loss-stop/refusals/<as_of>.json` containing {`epoch_id` or null, `reason_code` (closed set), `detail`, the offending record identities, `as_of`}, then fsync the file and the directory.
2. `unlink(latest.json)`, then fsync the directory. Never remove the directory itself: a missing parent also reads as missing (`:154-155`), but the owner/mode checks must keep working.
3. **Effect on the probe:**
   - the missing file → `_ArtefactError("missing")` (`:176-177`);
   - → `_settle(UNKNOWN)` (`:329-332`);
   - → `veto_reason` returns `REASON_UNKNOWN` (`:290-291`);
   - within one probe interval (300 s, `:80`).

   There is no 36 h window under a stale PASS.
4. **If step 1 itself fails** (disk full, permissions), the producer still unlinks and exits non-zero, so the systemd unit fails visibly. A PASS is never kept live to preserve the audit trail.

The order "record, then unlink" holds on every path where the record can be written.

### 4.5 MC specification for c (`scripts/analysis/fq_loss_floor_mc.py`; NOT run)
Unchanged from r2 §4.3:
- the pool and the holdout prohibition;
- the templates;
- the mix scenarios M-pool / M-yes / M-no;
- the production pure functions, imported and replayed verbatim (L-40 amendment (ii), `LESSONS.md:1401`);
- grid step 0.01, ≥ 10,000 replicates, a coordinator-set seed;
- the run hygiene.

**[r3, D5] Take rates, stated:**
- **Calibration of c** uses `rate_cal = max(λ_pool, take_rate_lower)` takes/day, where `take_rate_lower` = 0.25 (`F5_prereg_v2_design.json:14`), with epoch start = the A1 freeze date. More ticks give more crossing chances and therefore a larger c (conservative for Type-I).
- **G1 and G3** use `rate_gate = min(λ_pool, take_rate_lower)`, which gives fewer ticks and is pessimistic for reach and power.
- **Conversion:** takes/day becomes station-day ticks/day through the pool's takes-per-station-day ratio `r_sd`. Per calendar day, a station-day drawn from the pool's empirical per-day distribution is kept with probability `min(1, (rate / r_sd) / λ_sd,pool)`.

**Rows** (L-41: the H0 run is reported on its own and every other row is labelled):

| Row | What it is | Role |
|---|---|---|
| H0 | §4.2 joint (YES-first shrink); D1 netting shift included as the null's own deterministic value; qty ≡ 1 (§4.3) | **binding** |
| S1 | Independent Bernoulli(BE) per leg, no exclusivity | report |
| S2 | Proportional shrink | report |
| S3 | Share of false-stop mass from single-day crossings, per scenario | report |
| S4 | **[D2] Exit cost.** Each leg is exited with probability `p_exit = max(0.10, pool exit fraction)`, at fraction f ~ U(0,1). The exit adds a deterministic cost `−f·κ_exit`, where `κ_exit` = the pool's median quoted half-spread on the template's leg plus the venue fee at that price under the parent's θ (`F5_prereg_v2_design.json:35`, read, not redefined); the fallback is 0.02 if spreads are unavailable. σ_d stays the unexited Bernoulli value, as in production. | **binding** (exit margin) |
| S5 | **[D4] Correlated same-day stations.** Station-days on the same calendar day draw `U_s = Φ(√ρ·F + √(1−ρ)·ε_s)`, with a common day factor F, and invert the categorical CDF in rung (temperature) order. `ρ_bind = max(0.25, ρ̂_pool)`, where ρ̂_pool is the pool's same-day cross-station correlation of PIT ranks. ρ = 0.5 is also reported. Also reports the share of calendar days with ≥ 2 ticks. | **binding** at ρ_bind |
| S6 | **[domain caveat] Feasible zero-drift verification.** Final c and t_min applied to templates with Σq ≤ 1 only, exact marginals, no shrink, no netting shift. | **acceptance check** on the final c |

**Solving.**
- c = the maximum, over the binding set B = {H0, S4, S5(ρ_bind)} × {M-pool, M-yes, M-no}, of the smallest grid c whose crossing rate is ≤ α_floor.
- Report c per cell, the binding cell, the SE (bootstrap over replicates) and the rate at the final c for every cell.
- **Acceptance:**
  - every binding cell is ≤ α_floor + 3·SE at the final c;
  - S6 is ≤ α_floor + 3·SE.
- **t_min.** Chosen from {1, 2, 3, 5} to maximise G3 at `rate_gate`, subject to the α constraint at `rate_cal`; ties go to the smallest. It is re-chosen for each α on the §4.6 ladder and pinned with the selected α.

**[D4] Why a sensitivity row, not a calendar-day tick:**
1. Q6 fixed the station-day tick. It is also L-40's trial unit.
2. A calendar-day sum would still need σ for that sum. Under H0 the cross-station covariance is unspecified, so the calendar-day tick re-imports the same independence assumption and fixes nothing.
3. Merging days removes looks and coarsens the boundary.

S5 measures the effect directly and enters c, which is the conservative direction. If S5's share of calendar days with ≥ 2 ticks is small (expected at about 0.25 takes/day across 5 PM.us cities), its effect on c is small, and the row shows it.

**Also reported:**
- the share of Σq > 1 templates, the mean κ and the refused templates (as r2);
- the share of templates with a netting pair and the mean δ_net;
- the count of zero-σ days and the mean carry.

**Output:** `docs/evidence/f5/fq_loss_floor_mc_seed<S>.json`, containing every row above, the gate rows of §4.6, the script's git sha, the parent sha and the A0 sha.

### 4.6 The M2 gate (must pass before c freezes; r3 adds D5, margin, the G3 floor and the α ladder)
Every gate row is computed **at the pinned t_min and the final c** for that α, at `rate_gate` (D5). Grid-best values are never used.

- **G1, structural reachability (per mix scenario, median template, per e in {A1 freeze date, 2026-11-01, 2026-11-15, 2026-12-01}).**
  - The all-lose path crosses `−c√t` at some tick `t_cross ∈ [t_min, T_low(e)]`, where `T_low(e)` = the tick count by 2027-01-25 at `rate_gate`.
  - **G1 with margin** means `t_cross ≤ ⌊0.8 · T_low(e)⌋`.
  - Also reported: the minimum fully-lost fraction f\* (unchanged).
- **G2, positive control.** Owned by F6b (§4.10).
- **G3, power.** P(FAIL by 2027-01-25) at δ ∈ {−0.16, −0.08, −0.04}, with the H1 as in r2 (δ_h 0.16, `F5_prereg_v2_design.json:6`).
  - The target is `POWER_TARGET` 0.8 (`scripts/analysis/fq_mc_eprocess.py:35`).
  - **The floor is `G3(−0.16) ≥ 2.5 × α_floor`** (binding).

**α selection (pre-stated; no power shopping):**
1. If G1 passes at α 0.10 for the A1-freeze-date e on every scenario, then **α\* = 0.10**.
2. Otherwise, α\* = the smallest α in {0.20, 0.30} at which **G1 passes with margin** for that e on every scenario (ruling §10.3).
3. Otherwise, `floor_mode: "unreachable_veto"`, `c: null`.
4. **Escalation is driven by G1 (reachability) only.** A G3-floor failure at α\* is never fixed by moving to a larger α.

**Freeze outcomes at α\*:**

| G3(−0.16) at α\* | Action |
|---|---|
| ≥ 0.8 | Freeze `floor_mode: sqrt_boundary`, `power_class: "edge_capable"` |
| in [2.5·α\*, 0.8) | Freeze `floor_mode: sqrt_boundary`, `power_class: "gross_loss_tripwire"` (ruling §10.4). F6b docs state that the floor is not an edge detector; the edge stop is KILL. |
| < 2.5·α\* | Do **not** freeze a √t c. Freeze `floor_mode: "unreachable_veto"`, `c: null`. |
| S6 fails | Do **not** freeze. STOP; the peer loop rules on the shrink claim. |

- **G3 floors in numbers:** 0.25 at α 0.10, 0.50 at α 0.20, 0.75 at α 0.30.
- **Reach cutoff.** `reach_cutoff_epoch_start` = the latest e at which G1 (with margin if α\* > 0.10) and the G3 floor both hold on every scenario. If the eventual arming `ts_ns` is later than that, the producer refuses (§4.4.4; reason `past_reach_cutoff`).
- **`unreachable_veto`.** The producer never writes PASS and always takes the refusal path. FQ v2 entries are vetoed until AUT-6 retires the bridge. This is reported as a goal-state blocker (r2 §4.5).

### 4.7 How the floor looks in the real regime (planning arithmetic, not evidence)
r2 §4.5 estimated c ≈ 2.3–2.5 and power at −0.16 near 0.3 for α 0.10. r3's binding rows S4 and S5 can only raise c, and power falls as c rises.

Against a G3 floor of 0.25, the margin is a few hundredths of power. α escalation raises the floor in proportion (0.50 at 0.20, 0.75 at 0.30), so it rarely rescues G3.

**Plain statement:** the expected outcome is either a narrowly passing tripwire at 0.10 or `unreachable_veto`. The MC decides. Both outcomes are safe. A frozen stop that cannot fire is not an option.

### 4.8 F6b inputs: all pinned or ruled now
| Input | Status |
|---|---|
| Sign, leg source | Pinned in A1 (§4.1 step 1; r2 §1.2) |
| Netting (D1) | Pinned: §4.1 step 2. A zero-variance shift enters x_d; `unknown_netting_slugs` refuses. |
| Qty (D3) | Pinned: §4.3 (one row per (rung, side), qty ≡ 1, BE̅ from the ledger, fee 0) |
| Exits (D2) | Pinned: §4.1 step 6; calibration allowance S4 |
| Voids, overround, zero-σ carry | Pinned: §4.1 steps 4, 7, 8; §4.2 |
| `truth_sha` | Pinned: §4.4.2 (now includes `epoch_id`) |
| Epoch id (D6) | Pinned: §4.4.2 |
| FAIL latch (D6) | Pinned: §4.4.3 |
| Refusal channel | **Ruled (§10.1):** §4.4.4 |
| Anchor source | **Ruled (§10.2):** §4.4.1 |
| Fixed by F6, not re-pinned | `SCHEMA` (`loss_stop_probe.py:63`), the digest (`:108-110`), `MAX_AGE_H`/`STALE_VETO_H` (`:77-78`), the artefact path (`:118-119`), directory and file mode checks |

### 4.9 A1 draft shape (NOT freeze-ready) and its R5
```json
{
  "frozen_sha": "UNFROZEN",
  "amendment_id": "F5_prereg_v2_A1_floor",
  "amends": {"path": "docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F5_prereg_v2_design.json", "frozen_sha": "072ab026cdc790dd6e9a51d62d8164766b85fd82"},
  "loss_stop_floor": {
    "floor_mode": "PENDING_GATE (sqrt_boundary | unreachable_veto)",
    "power_class": "PENDING_GATE (edge_capable | gross_loss_tripwire | none)",
    "alpha_floor": "PENDING_GATE (0.10 | 0.20 | 0.30)",
    "alpha_selection_rule": "§4.6 of F5-pin-request_r3: 0.10 if G1 passes; else smallest of {0.20,0.30} with G1 margin t_cross <= floor(0.8*T_low(e)); else unreachable_veto; never escalate on G3",
    "g3_floor_multiplier": 2.5,
    "gate_rate_rule": "calibration at max(pool, take_rate_lower); G1/G3 at min(pool, take_rate_lower); takes->ticks via pool takes-per-station-day",
    "t_unit": "settled_station_day",
    "pnl_unit": "per_contract_qty1",
    "qty_rule": "one StratumRow per unpaired (rung, side): entry_ask=ledger BE-bar, fee=0, qty=1 (§4.3)",
    "netting_rule": "paired rung = one unit, delta_net = 1 - BEbar_y - BEbar_n, zero variance, enters x_d; zero-sigma days carry to next tick (§4.1 steps 2, 8)",
    "exit_rule": "h_eff=(1-f)h+f*v, variance unexited; calibration margin = binding row S4",
    "increment_rule": "§4.1 steps 1-9 of F5-pin-request_r3",
    "bundle_null_rule": "categorical_yes_first_shrink_v1",
    "boundary_rule": "FAIL iff S_t < -c*sqrt(t) for some t in [t_min, t_at_horizon]",
    "c": "PENDING_MC",
    "c_mc_se": "PENDING_MC",
    "c_binding_cell": "PENDING_MC",
    "t_min": "PENDING_MC",
    "measured_power": {"-0.16": "PENDING_MC", "-0.08": "PENDING_MC", "-0.04": "PENDING_MC"},
    "s6_feasible_rate": "PENDING_MC",
    "t_horizon_climate_day": "2027-01-25",
    "reach_cutoff_epoch_start": "PENDING_MC",
    "past_horizon_rule": "fail_closed_no_pass; recalibration owner coordinator",
    "epoch_anchor_rule": "latest autonomy TransitionRow for the FQ v2 family_id entering CHAMPION from a non-sender state with a non-empty policy_ruling_id; armed_at = ts_ns; refuse if absent",
    "epoch_id_rule": "epoch_id = anchor transition_id; carried in latest.json and in the truth_sha preimage",
    "fail_latch_rule": "fail_latch/<epoch_id>.json written O_EXCL+fsync before the first FAIL; checked before any input; never deleted; latch beats refusal",
    "refusal_rule": "durable refusals/<as_of>.json (fsync file+dir), then unlink latest.json; on record-write failure unlink anyway and exit non-zero",
    "restart_rule": "FAIL terminal within epoch; a new epoch needs a new qualifying arming row; S_t restarts at 0",
    "inputs": {"sign_rule": "...", "fill_rule": "...", "fee_rule": "...", "void_rule": "...", "truth_sha_rule": "..."}
  },
  "provenance": {"mc_module": "scripts/analysis/fq_loss_floor_mc.py", "core_module": "src/breezy/analysis/fq_loss_stop_core.py", "mc_evidence": "PENDING_MC", "mc_seed": "PENDING_COORDINATOR"}
}
```
None of the `loss_stop_floor` child keys collide with the parent's keys or nested keys (`F5_prereg_v2_design.json:1-37`) or with A0's `kill_*` keys. The R3 additive check (`prereg_amendment_check.py:219-241`) enforces this.

**R5 for A1 (new branch in `_check_payload`).** It replaces the placeholder at `prereg_amendment_check.py:315-321` for `F5_prereg_v2_A1_floor` only. A2 keeps the placeholder until Phase 3. The checks:
- exact key set;
- `alpha_floor ∈ ALPHA_FLOOR_GRID`, and `g3_floor_multiplier == G3_FLOOR_MULTIPLIER`, both imported from the core module, never retyped;
- `floor_mode ∈ {sqrt_boundary, unreachable_veto}`;
- if `sqrt_boundary`, then:
  - c is finite and > 0;
  - `t_min` is an int in {1, 2, 3, 5};
  - `measured_power["-0.16"] >= g3_floor_multiplier * alpha_floor`;
  - `power_class ∈ {edge_capable, gross_loss_tripwire}`;
  - `s6_feasible_rate` is a number;
- if `unreachable_veto`, then c is null and `power_class == "none"`;
- every `PENDING_*` string is refused;
- `t_horizon_climate_day` is an ISO date.

**Existing test.** `tests/unit/test_prereg_amendment_check.py:280-292` asserts `PAYLOAD_NOT_YET_DEFINED` for an A1 draft. Its payload (`{"kill_grid_points": ...}`) still fails under the new rule. The assertion is rewritten to the new A1 defect code (`BAD_FLOOR_KEYS`). This replaces a placeholder refusal with a real one and is no weaker. The `KEY_OVERLAP` assertion on `:291` stays byte-unchanged.

### 4.10 A1 and F6b tests (ADD)
**Pure core (`fq_loss_stop_core.py`):**
- `test_paired_rung_enters_x_as_zero_variance_shift` (D1)
- `test_pairs_only_day_is_not_a_tick_and_carries`
- `test_unknown_netting_slug_refuses`
- `test_one_row_per_rung_side_qty1_ledger_be` (D3): a 5-contract and a 1-contract leg give identical x and σ
- `test_multi_fill_leg_never_hits_fold_refusal`
- the r2 rows (the L-40 formulas, the shrink and its refusal, the NO price from the instrument, `fee_reconciled=False` refuses, exits and voids)

**Checker:**
- A1 R5 planted defects, one each:
  - G3 below the floor;
  - α off the grid;
  - multiplier ≠ 2.5;
  - `unreachable_veto` with a non-null c;
  - `PENDING_*`.
- The rewritten `:292` assertion.

**MC acceptance:**
- every binding cell, and S6, ≤ α_floor + 3·SE;
- mutation tests: a dollar-scaled P&L, a cap-derived c, a dropped overround day, a dropped netting shift, or S4/S5 excluded from c must each fail.

**F6b (owned by F6b):**
- `test_anchor_from_ledger_row_refuses_when_absent`
- `test_registry_opened_read_only_never_created`
- `test_epoch_id_in_artefact_and_truth_sha` (a forged `epoch_id` fails the digest)
- `test_probe_accepts_extra_epoch_id_key` (pins `loss_stop_probe.py:344-362` behaviour; the probe is not edited)
- `test_fail_latch_survives_late_fee_reconcile`
- `test_fail_latch_survives_late_void`
- `test_fail_latch_survives_producer_and_node_restart`
- `test_latch_beats_refusal`
- `test_refusal_writes_reason_then_unlinks` (with a crash injected between the two steps)
- `test_refusal_record_failure_still_unlinks_and_exits_nonzero`
- `test_new_ruling_row_starts_new_epoch_at_zero`
- `test_resume_without_ruling_keeps_epoch`
- the **L-38 positive control** (G2): a synthetic post-epoch all-lose stream yields FAIL through the real writer and the real probe, then a restart still reads FAIL
- `test_floor_read_from_prereg_never_from_operator_controls`

## 5. A2: the calibration guard

### 5.1 Rulings applied
Unchanged from r2 §5.1:
- α_guard 0.10, calibrated to the ever-blocked rate;
- point-in-band (`_group_status`, `src/breezy/analysis/autonomy/evaluators/forecast_quantile_ladder.py:166-180`);
- `per_side` (`_guard` `:183-194`; `_POOLINGS` `src/breezy/analysis/autonomy/eprocess.py:71`);
- a present side below `n_guard_min` blocks PASS;
- the guard only removes PASS days (`pass_hit`, `forecast_quantile_ladder.py:295`), is evaluated every settled day (`:292`), and leaves KILL untouched (`:296-298`).

### 5.2 Guard MC (`scripts/analysis/fq_guard_mc.py`; NOT run)
Unchanged from r2 §5.2: the pool and holdout, the calibrated categorical null, the verbatim `_guard` replay, the ever-FAIL metric, the one-parameter threshold family, the `n_guard_min` grid with occupancy (≥ 3 bins × ≥ 5 takes on ≥ 95 % of windows), `_DEFAULT_BIN_EDGES` (`:84`) with a quintile fallback, and the power alternatives.

**[r3, D5] Rate.** The daily evaluation runs at `rate_gate` (§4.5). The occupancy condition is checked at `rate_gate` too: fewer takes per window is the pessimistic case for occupancy.

### 5.3 Positive control and the permanent PASS veto (M8, escalated)
- **Measurement.** On the pool's real out-of-fold windows, `real_pool_ok_rate` = P(the guard status is `OK` on the window's last settled day, on both sides present), at the frozen thresholds. Report the point estimate, the Wilson 95 % interval, and the per-side and per-failure-reason breakdown (`FAIL(spiegelhalter_z)` vs `FAIL(reliability_slope)`).
- **Pre-stated rule.** If the Wilson upper bound of `real_pool_ok_rate` is < 0.05, A2 freezes with `guard_basis.pass_reachability: "permanent_pass_veto"`. Otherwise it freezes with `"reachable"`.
- **Plain statement:**

  > **If `real_pool_ok_rate` ≈ 0, A2 is a PERMANENT PASS VETO for FQ v2.** The guard thresholds are calibrated on the null and are never tuned to real windows. The rung density is known to be under-confident, so on real data the guard returns FAIL and `pass_hit` (`forecast_quantile_ladder.py:295`) is never true. **No amount of forward evidence can produce a PASS.** KILL stays fully live, because the guard never touches it (`:296-298`). Lifting the veto requires a recalibrated density. That is a new model and a new design, never an edit or re-freeze of A2 (L-12, L-34).

- **Goal-state consequence.** Under `permanent_pass_veto`, the FQ v2 promotion path through the e-process is closed. This is reported as a blocker to the goal state, alongside any A1 `unreachable_veto`.

### 5.4 Timing and 6b registration (Q12, M8)
- A2 freezes before the first forward-shadow source is registered. `REGISTERED_FORWARD_SHADOW_SOURCES` is empty today (`forecast_quantile_ladder.py:87-89`; enforced by `check_forward_shadow_inputs` `:110-115`).
- **The 6b registration change (owned by 6b) must:**
  1. load A2 through `load_verified_amendment(path, "F5_prereg_v2_A2_guard")`, and refuse registration if A2 is missing or UNFROZEN (Q12);
  2. **surface `pass_reachability`:**
     - if it is `permanent_pass_veto`, registration still proceeds, because shadow evidence still feeds KILL and diagnostics;
     - but the registration emits a CRITICAL alert through the existing alert sink, with the fixed text constant `FQ_V2_PASS_UNREACHABLE_UNDER_A2: the calibration guard vetoes every PASS; KILL remains live`;
     - the same line goes into the registration commit body and the registration record;
     - a 6b test asserts the alert is emitted and that registration under `reachable` emits nothing.
- The evaluator already reports a guard-blocked crossing as `window_end_guard_blocked` (`:338`) or through `_guard_reason` (`:197`). The registration alert is the up-front signal; these are the per-window ones.

### 5.5 A2 payload (draft) and R5
- `guard`: exactly the five `GuardThresholds` fields (`eprocess.py:88-116`). All are `PENDING_MC` except `pooling: "per_side"`.
- `guard_basis` = {`alpha_guard`: 0.10, `ci_rule`: "point", `absent_side_rule`: "skip", `present_side_below_min_rule`: "blocks_pass", `real_pool_ok_rate`: PENDING_MC, `real_pool_ok_wilson_upper`: PENDING_MC, `pass_reachability`: PENDING_MC, `gate_rate_rule`: "min(pool, take_rate_lower)"}.
- **R5 for A2** replaces the `:315-321` placeholder for `F5_prereg_v2_A2_guard`:
  - `GuardThresholds(**guard)` constructs;
  - `pooling == "per_side"`;
  - `bin_edges` equals the imported deciles or the quintile fallback;
  - `pass_reachability ∈ {reachable, permanent_pass_veto}`, and it is consistent with `real_pool_ok_wilson_upper` against the 0.05 rule;
  - `PENDING_*` is refused.
- **Tests (ADD):**
  - `test_guard_from_amendment_constructs_guard_thresholds`
  - `test_guard_only_removes_pass_days` (property test)
  - `test_pass_reachability_matches_wilson_rule`
  - the occupancy, ever-FAIL and power acceptance rows
  - the 6b-owned `test_registration_alerts_on_permanent_pass_veto` and `test_registration_refuses_unfrozen_a2`

## 6. Implementation order (each phase merges on its own)

**Phase 0–1 (A0): done, except one item.** A0 is frozen at 43cc3e0f and the sibling checker is merged. **Still open:** r2 Phase 1 step 6, the M10 KILL power report. Neither `scripts/analysis/fq_kill_power_report.py` nor `docs/evidence/f5/fq_kill_power_negative_edge_seed20261008.json` exists yet. It runs after the freeze with the seed confirmed in the merge, is reporting only, and blocks nothing below.

**Phase 2. A1.**
1. **Rulings are in.** The refusal channel (§4.4.4) and the anchor (§4.4.1) are ruled. Record that the arming procedure must write the §4.4.1 ledger row, and hand that note to the arming owner.
2. **Pure core** `src/breezy/analysis/fq_loss_stop_core.py`, TDD first (tdd-guide, RED → GREEN). It has no I/O and no c. It holds:
   - leg normalisation (§4.3);
   - the netting split and shift, with the zero-σ carry (D1);
   - `combine_station_day` reuse;
   - the shrunk-null variance;
   - the crossing function;
   - `ALPHA_FLOOR_GRID` and `G3_FLOOR_MULTIPLIER`.

   Run `lint-imports` from the tree root and read the "N kept, 0 broken" line.
3. **Checker R5 for A1** (§4.9): TDD, plus the `:292` assertion rewrite. `prereg_precommit_check.py` and its test stay byte-unchanged.
4. **Floor MC** with rows H0, S1–S6 and the copula (§4.5). TDD it on tiny seeds that import the core.
5. **Run.** The coordinator sets the seed. Run it capped (address-space cap), watched (stall watch plus a Monitor armed in the launch turn), one heavy job at a time, with a subset benchmark first.
6. **Gate** per §4.6, applying the α ladder mechanically. S6 must pass.
7. **Peer review** of the evidence: architect + prediction-market-reviewer + python-reviewer.
8. **Freeze A1** (freeze commit, then stamp commit, then the digest test) **before any v2 arming row exists**. Full gate `scripts/ci/run_tests_no_egress.sh`; read EXIT, and only then push.
9. **F6b** (a separate plan) builds the producer against the frozen A1: the anchor reader, epoch id, latch, refusal channel and the G2 positive control (§4.10).

**Phase 3. A2.**
1. Checker R5 for A2 (§5.5), TDD.
2. Guard MC with the `rate_gate` occupancy and the Wilson positive control (§5.2–§5.3), TDD.
3. The coordinator sets the seed; run capped and watched.
4. Peer review. If `permanent_pass_veto`, the review states the goal-state blocker explicitly.
5. Freeze A2 before the first 6b registration.
6. Hand the §5.4 registration obligations (load, refuse, CRITICAL alert, test) to the 6b owner as binding inputs.

## 7. Testing strategy
Unchanged from r2 §7. The new rows are listed in §4.10 and §5.5.

## 8. Risks and mitigations
- **The G3 floor fails at α\*, so A1 is `unreachable_veto`.** The FQ v2 entry path is then always vetoed until AUT-6.
  - Mitigation: none is needed for safety; this is the intended fail-closed outcome. Report it as a goal-state blocker so the trading path is planned through AUT-6.
- **A2 is `permanent_pass_veto`.**
  - Mitigation: KILL stays live; the 6b alert makes the veto visible at registration (§5.4); any lift is a new design, not an A2 edit.
- **No ledger row is written at arming, so the veto is permanent** (§4.4.1).
  - Mitigation: flagged to the arming owner in Phase 2 step 1; F6b test `test_anchor_from_ledger_row_refuses_when_absent`.
- **A late fee reconcile or void un-latches a FAIL.**
  - Mitigation: the durable epoch latch is checked before any input (§4.4.3), plus three F6b tests.
- **A crash between the refusal record and the unlink.**
  - Mitigation: the record is idempotent and the next run repeats both steps. A record-write failure still unlinks (§4.4.4).
- **The shrink-conservativeness claim is false for this pool.**
  - Mitigation: S6 is an acceptance check; a failure STOPs the freeze.
- **Correlated stations under-stated by ρ_bind.**
  - Mitigation: ρ_bind = max(0.25, ρ̂_pool); ρ = 0.5 is reported; the peer review sees the share of days with ≥ 2 ticks.
- **The exit-cost model is crude** (σ unexited, deterministic cost).
  - Mitigation: σ is overstated, which is conservative for Type-I. The cost is binding in c. The exit seam is unarmed today, so the realised exit cost is 0 until it is armed.
- **qty ≡ 1 under-weights large losing positions** (§4.3).
  - Mitigation: stated plainly. Dollar exposure is bounded elsewhere by the operator-reserved controls. Dollar P&L is in the diagnostics.
- **Pairs-only days defer their loss to the next tick.**
  - Mitigation: they are expected to be rare (admission refuses same-rung opposite sides); the carry and count are reported; past the horizon nothing passes.
- **Unchanged from r2:** the parent re-freeze STOP, the shallow clone, the heavy NO tails (S3), the pool mix (max over scenarios), the F13 import coupling, and the shared-tree hazards (a scratchpad per agent, `ruff format` only on touched files, never stash, never `uv sync`).

## 9. Success criteria
- [ ] The M10 KILL power report exists (δ clamped at 0, no constant changed).
- [ ] The core module is merged TDD-first with the D1/D3 tests, and `lint-imports` shows "N kept, 0 broken".
- [ ] Checker R5 for A1 and A2 is merged. The `:292` assertion is rewritten to a real defect code, and the parent checker and its test are byte-unchanged.
- [ ] The floor MC evidence holds:
  - c per binding cell (H0/S4/S5 × three mixes), the binding cell, SE, t_min;
  - S1–S3 and S5 at ρ = 0.5;
  - S6 ≤ α_floor + 3·SE;
  - G1 (with margin where required), f\* and G3 at the pinned t_min and `rate_gate`;
  - the netting, zero-σ and Σq > 1 shares.
- [ ] A1 is frozen as `sqrt_boundary` (with G3(−0.16) ≥ 2.5·α_floor, which the checker enforces) or as `unreachable_veto`, before any v2 arming row exists.
- [ ] The guard MC evidence holds the ever-FAIL calibration, occupancy at `rate_gate`, power, `real_pool_ok_rate` with its Wilson bound, and `pass_reachability`. A2 is frozen before any 6b registration, and the 6b owner has the §5.4 obligations.
- [ ] Any `unreachable_veto` or `permanent_pass_veto` is reported as a goal-state blocker.
- [ ] The census grep returns 0 for operator-control names on this doc and on A1/A2. No operator-reserved control is named or assigned.

## 10. Residual questions for the peer loop
1. **The S4 and S5 floors** (`p_exit ≥ 0.10`, `κ_exit` fallback 0.02, `ρ_bind ≥ 0.25`): are these pre-stated floors acceptable, or should they be higher?
2. **The G1 margin** `t_cross ≤ ⌊0.8·T_low(e)⌋`: is 20 % slack the right reading of "with margin" in ruling §10.3?
3. **The "≈ 0" rule for M8** (Wilson upper bound < 0.05): acceptable?
4. **Zero-σ carry** (§4.1 step 8): accept it, or standardise a pairs-only day by a pinned reference σ instead?

## 11. r2 → r3 change log
| Item | Change | Where |
|---|---|---|
| §0–§3 | Replaced by a pointer: A0 frozen 43cc3e0f; see r2 §2–§3 and `prereg_amendment_check.py` | §0 |
| D1 | Same-rung netting loss `1 − BE̅_y − BE̅_n` per paired rung enters x_d as a deterministic zero-variance shift (r2 had excluded it to diagnostics); `unknown_netting_slugs` refuses; zero-σ days carry | §4.1 steps 2, 8; §4.2; §4.10 |
| D2 | Exit-cost row S4, binding in c (an exit margin) | §4.1 step 6; §4.5 |
| D3 | qty ≡ 1 made explicit: one `StratumRow` per unpaired (rung, side), BE̅ from the ledger, fee 0; x_d = per-contract P&L, σ_d at the L-40 qty ≡ 1 scope; why qty is not weighted | §4.1 step 3; §4.3 |
| D4 | Kept the station-day tick (Q6); added the correlated same-day copula row S5, binding at ρ_bind; justified rejecting the calendar-day tick | §4.5 |
| D5 | Calibration at `max(pool, 0.25)`, G1/G3 at `min(pool, 0.25)`; every gate row at the pinned t_min and final c; t_min re-chosen per α | §4.5; §4.6; §5.2 |
| D6 | `epoch_id` = anchor `transition_id`, carried in the artefact and bound into `truth_sha`; a durable epoch FAIL latch checked before any input, so a late fee reconcile or void cannot un-latch it; latch beats refusal | §4.4.2–§4.4.3; §4.10 |
| §10.1 | Refusal = durable reason record, then unlink; a record failure still unlinks and exits non-zero | §4.4.4 |
| §10.2 | Anchor = (a): the autonomy `TransitionRow` entering CHAMPION with a policy ruling; refused when absent; registry opened read-only | §4.4.1 |
| §10.3 | α ladder: 0.10, else the smallest of {0.20, 0.30} with G1 margin, else `unreachable_veto`; no escalation on G3 | §4.6 |
| §10.4 / G3 floor | Tripwire freezes only if G3(−0.16) ≥ 2.5·α_floor; the checker enforces it in R5 | §4.6; §4.9 |
| M8 | `real_pool_ok_rate` Wilson upper bound < 0.05 → `permanent_pass_veto`, stated loudly; 6b registration emits a CRITICAL alert and records it | §5.3; §5.4; §5.5 |
| Domain caveat | S6: the final c applied to feasible zero-drift templates is an acceptance check on the shrink-conservativeness claim | §4.2; §4.5; §4.6 |
| Checker | A1/A2 R5 replace the `PAYLOAD_NOT_YET_DEFINED` placeholder (`prereg_amendment_check.py:315-321`); the `test_prereg_amendment_check.py:292` assertion is rewritten to a real defect code, never weakened | §4.9; §5.5 |
| Phase 2/3 | Rulings recorded; core → checker → MC → run → gate → review → freeze; F6b and 6b obligations handed over; M10 report flagged as still open | §6 |
| §8–§10 | Risks updated for the veto outcomes, the latch, the refusal crash window, S4–S6, qty and carry; success criteria updated; residual questions reduced to four parameter checks | §8–§10 |
