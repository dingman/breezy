# AUD-05 — Give the live family `pm_us_crh_v4` a tally that runs: fix the two measured tally failures against the registered NO-side formula, instantiate the unit, retire the orphans

## 1. ID and actionable title

**AUD-05** — Diagnose (evidence first) and close the two measured failures of
`breezy-family-tally@pm_us_crh_cont.service`, implementing D-A **against the already-REGISTERED
mixed-side formula** so the registered statistic demonstrably does not change; resolve the
`pm_us_crh_v4` / `pm_us_crh_cont` `trial_id_prefix` collision; instantiate the tally timer for the
family the node actually runs; remove the two orphan `breezy-pm-crh-*-tally` units; and make a
failing tally reach the operator instead of dying into a journal.

## 2. Source finding and class

- **Gap:** G-04 (`docs/evidence/AUTONOMY_ROI_AUDIT_2026-09-21.md:50-54`). Verdict **FALSE**. Timers
  exist only for `pm_us_crh_cont` and `pm_us_crh_v2`; `breezy-family-tally@pm_us_crh_cont.service`
  failed 2026-09-20 17:20:51Z (V) and on both 09-19 runs (A); no unit tallies `pm_us_crh_v4`
  (d0 2026-09-20); orphan `breezy-pm-crh-{cont,v2}-tally` units are `not-found/failed` (V).
- **Registered artefact this item implements against:**
  `docs/evidence/PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md` — **REGISTERED 2026-09-14**, §3 gives
  the exact mixed-side statistic. It is the oracle for D-A, not a background reference.
- **Related ruling — RULED 2026-09-21, peer-ENDORSED:** R-4 (`PROGRESS.md:73`) — v3 §9 is
  "unchanged from v2" with no carve-out, so the tally MUST receive a family-scoped count against
  its own manifest and d0. Ruled in `docs/evidence/RULING_live_family_tally_scope_2026-09-21.md` §4 (review trail
  `docs/evidence/reviews/RULING_tally_scope_review_2026-09-21.md`): the 14:15Z counter is
  **champion-scoped**, never a fixed literal; `SP-1 I5`
  (`docs/plans/LIVE_FILL_SCORING_CHAIN_2026-09-05.md:236,311,313`) stays the **spec of record**
  and **AUD-05 gains a named increment (INC-SP1I5, §6) that IMPLEMENTS it**; AUD-10 only
  consumes the resulting counter. R-4's own literal text names `pm_us_crh_cont.json` as the
  manifest to point at — **superseded**: BLOCKER-2 is ruled and `pm_us_crh_cont` is retired, so
  the counter follows the deployed `sending_family_id` (today `pm_us_crh_v4`), not cont.
- **Sibling ruling that bounds what this item can demonstrate:**
  `docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md` (ENDORSED) rules
  `pm_us_crh_v4` **HALTED — may not SEND orders**, while explicitly ruling that "the node,
  quote-tape capture, shadow valuation, or the KILL clock" keep running (§4). The tally unit is
  therefore still required and still in scope; what changes is that `n` may legitimately stay 0
  while the halt stands (§11).
- **Class:** **autonomous-operation failure** (a scheduled measurement unit has been failing
  unattended for ≥3 days, silently) compounded by an **implementation defect** (two distinct raises)
  and an **integration failure** (no unit instance for the live family).

**Evidence collected for this plan (read-only, 2026-09-21):** both failure modes reproduced from
`~/.local/share/breezy/derived/family_tally_v2.log` and `journalctl --user -u
'breezy-family-tally@pm_us_crh_cont.service'`. Both raise sites and the prefix collision were
independently re-confirmed verbatim by two blind round-1 reviewers. No unit was started, stopped or
modified.

## 3. Current behaviour, required behaviour, concrete gap

**Current — five distinct defects, all measured:**

- **D-A (measured, 2026-09-19 17:20:50Z).**
  `ValueError: build_stratum_v2() is side-blind and refuses any row with side != 'yes' until it is
  made side-aware (fix-first review of 87278dd, item 3)` —
  `src/breezy/settlement/current_rung_hold_v2.py:414-419`, reached via
  `family_tally_v2.py:645 build_stratum_v2("pooled", pooled_rows)`. The NO-side amendment
  (REGISTERED 2026-09-14 under the NO-1 operator ruling) made NO fills a requirement; the v2 stratum
  builder still refuses them. **The tally cannot score a NO fill at all.**
  **Crucial scoping fact, read from the amendment (§3, closing paragraph):** the *statistic* layer
  is ALREADY side-aware — `combine_station_day` at
  `src/breezy/settlement/current_rung_hold_v2.py:298-345` (commit 87278dd; the R2 re-anchor — `:192-227`
  is the `CombinedDraw` docstring that *describes* the formula, not the function) implements the registered
  variance with `signs[i] * signs[j]` in the cross term. The refusal is therefore confined to the
  **stratum builder**, upstream of the statistic. D-A is a narrower fix than "make the statistic
  side-aware", and this bounds its risk: the registered statistic is not being authored here, it is
  being *reached*.
- **D-B (measured, 2026-09-20 17:20:51Z).**
  `ValueError: filled_takes=1 is less than len(rows)=4` — `family_tally_v2.py:666-671`. The guard is
  correct (a fill-time count must be a superset of scored rows); the INPUT is wrong.
  `count_filled_takes` (`scripts/analysis/fill_time_count.py:101-159`) keys counted trials on
  `family_prefix + "<station>/<climate_day>"` and returns `len(counted_trial_keys)` — **one key per
  station-day**. Two candidate causes, not yet discriminated: (i) the MP-A multi-position change
  (R-10 lifted the one-per-station bound) means two rung fills on one station-day collapse to one
  key; (ii) `trial.instrument_id in filled_instrument_ids` fails for the `^no` leg, so the NO fill
  is never counted (L-44 shape). Step 0 discriminates, and §7 step 0(b) now names the exact symbols
  that pre-narrow cause (ii).
- **D-C (measured).** No `breezy-family-tally@pm_us_crh_v4.timer` exists; `systemctl --user
  list-timers` shows instances only for `pm_us_crh_cont` and `pm_us_crh_v2`. The family the node
  runs since `bcb82d6` has never been tallied.
- **D-D (measured, and it blocks D-C).** `deploy/families/pm_us_crh_v4.json:4` declares
  `"trial_id_prefix": "continuous_rung_hold/trial/"` — **byte-identical to
  `deploy/families/pm_us_crh_cont.json:4`**. `filter_rows_to_manifest_prefix`
  (`family_tally_v2.py:531-564`) separates families by prefix ALONE, so simply enabling a v4
  instance would admit every v3 row into v4's `n`. That violates the invariant
  `POST_FORECAST_PHASE_2026-09-20.md` A-9 items 2, 4 and 5 (new prefix, `assert_family_only` refuses
  v3 rows into v4, v4's `n` accrues only from station-days strictly after registration), and L-34.
  `pm_us_crh_cont` carries `"terminal_climate_day": "2026-09-19"` while v4's `d0_climate_day` is
  `2026-09-20`, so the two are *temporally* disjoint but not *identifiably* disjoint. Both manifests
  currently read `"status": "REGISTERED"`.
  **RULED 2026-09-21 (`docs/evidence/RULING_live_family_tally_scope_2026-09-21.md`, BLOCKER-1):
  no re-issue of the registered v4 manifest.** The premise above — that enabling a v4 instance
  "would admit every v3 row into v4's `n`" — is **false at tally time**: `assert_family_only`
  (`src/breezy/settlement/family_barrier.py:52-96`) is called unconditionally by
  `build_family_tally_v2` (`scripts/analysis/family_tally_v2.py:622`) immediately after the
  prefix filter (`:602`), and its `d0_climate_day` lower bound (`family_barrier.py:80-84`) plus
  `terminal_climate_day` inclusive upper bound (`:85-91`) already separate cont (terminal
  2026-09-19) from v4 (d0 2026-09-20), refusing the ENTIRE batch (`:75-96`) rather than dropping
  rows. D-D therefore becomes a **scorer-time** guard (D-G below), not a manifest edit.
- **D-G (NEW, ruled in scope — the admission point that IS unguarded).** The same ruling locates
  the real defect at row-CREATION time: `scripts/analysis/score_live_trials.py` carries only a
  lower temporal bound — `since_climate_day = manifest.d0_climate_day` (`:1789`, inside `main`,
  def `:1748`), whose sole date check is `if climate_day < since_climate_day: continue`
  (`:722`, in `read_filled_trials_state_db`); an exhaustive grep of that file for
  `terminal_climate_day` returns **zero matches** (re-verified 2026-09-21). Meanwhile
  `deploy/systemd/score-live-trials-run.sh` enumerates every REGISTERED `polymarket_us` manifest
  (`:77-94`) and invokes the scorer once per `(city, manifest)` pair into
  `--derived-dir "$STORE_DIR/$FAMILY_ID"` (`:181-187`, the derived-dir at `:187`). Because cont
  and v4 share one `trial_id_prefix`, **one live fill dated on/after 2026-09-20 satisfies BOTH
  manifests' `since_climate_day` and is written into BOTH family stores** — a double-write, and
  a *new* failure mode for cont's own tally (the tally-time barrier then refuses cont's whole
  batch, loudly, which is fail-closed but is not the same as never admitting the row).
- **D-H (NEW, ruled in scope — R-4 / SP-1 I5).** The 14:15Z covered-listed-station-days counter
  is pinned to a literal: `FAMILY_MANIFEST="$REPO/deploy/families/pm_us_crh_v2.json"`
  (`deploy/systemd/score-live-trials-run.sh:47`, with the comment at `:40-46` explicitly
  deferring the fix to "R-4, SP-1 I5"), fed to `structural_dead_stop.py --family-manifest` at
  `:125`. The node's champion has been `pm_us_crh_v4` since `bcb82d6`, so the deployed KILL
  clock counts coverage for a family nobody runs. PREREG v3 §9 binds the structural-dead test to
  *this* family's own D0/coverage window.
- **D-E (measured).** `breezy-pm-crh-cont-tally.timer` and `breezy-pm-crh-v2-tally.timer` still
  appear in `list-timers --all` (last trigger 2026-09-18) with `not-found` units — retired by
  WP-11b but never removed from the user unit directory.

**Required.** The family the node is running has a tally that completes daily, receives a v3/v4-scoped
fill-time count per R-4, scores both legs **exactly as the registered amendment specifies**, cannot
silently inherit another family's rows, and cannot fail three days running without anyone learning.

**Concrete gap.** Four code/config defects (D-A, D-B, D-G, D-H), one systemd-state defect (D-E)
and one missing alert edge (D-F) stand between the live family and any measurement of it. D-D's
manifest-identity question is RULED closed (no re-issue); it is replaced by D-G's scorer guard.

## 4. Priority, rationale, dependencies, execution order

**Priority: P1.** It is a measurement blackout on the live family, and R-4 shows it also renders
SP-1 I5 and SP-5 inert. It is *not* P0 only because there have been no fills since 2026-09-15, so
the blackout is currently over an empty interval — that is a reprieve, not a fix.

**Dependency ordering (STAGE 1, in parallel with AUD-04, sharing no code):**
- **No step of this item is ruling-blocked any more.** BLOCKER-1, BLOCKER-2 and BLOCKER-3 are all
  RULED and peer-ENDORSED in `docs/evidence/RULING_live_family_tally_scope_2026-09-21.md`
  (§12). D-D's manifest edit is ruled OUT; D-G (scorer guard), BLOCKER-2's retirement sequence and
  BLOCKER-3's option (a) implementation are all ruled IN and are executable now.
- **INC-SP1I5 (D-H) is independent of D-A/D-B/D-G** — it touches the counter invocation in
  `score-live-trials-run.sh` and `structural_dead_stop.py`'s inputs, sharing no code with the
  stratum builder, the fill counter or the scorer's date bounds; it may run in parallel.
- **Independent of AUD-04** — deliberately: the portfolio report must not wait on the tally, and the
  tally must not wait on the portfolio report. They measure different estimands (L-2).
- **Unblocks:** SP-1 I5 and SP-5 (per R-4). **Feeds:** AUD-02's family-scoped edge estimate, which is
  in turn AUD-06b's BLOCKER-B — so this item sits upstream of the only money-moving item in the
  backlog, by evidence rather than by code.
- **Interacts with AUD-07** (by id only): AUD-07's family-binding fix must not be made by hard-coding
  a second literal while this prefix collision is open.

**Execution order:** step 0 (evidence, read-only, now including the `pm_us_crh_cont` store
pre-check) → D-A fix (inert half) → D-B fix → alert edge (D-F) → D-G scorer guard + tally-barrier
pin test → BLOCKER-3 ruled implementation (NO rows into the `cell_dead` strata, retiring the
`PENDING_STRATA_RULING` interim) → D-C enable v4 instance → BLOCKER-2 terminal run for
`pm_us_crh_cont` then disable its timer → D-E cleanup. **INC-SP1I5 (D-H) runs in parallel**,
gated only on its own RED tests.

## 5. Scope and explicit exclusions

**In scope:** `settlement/current_rung_hold_v2.py` (side-awareness of the stratum builder ONLY),
`scripts/analysis/fill_time_count.py` (counting unit), `scripts/analysis/family_tally_v2.py`
(stratum call sites, the side-mix carrier, the report renderer), `deploy/systemd/family-tally-v2-run.sh`
(the failure alert edge), one new timer instance, removal of two orphan unit files, and their tests.
**Added by the 2026-09-21 ruling (`docs/evidence/RULING_live_family_tally_scope_2026-09-21.md`):**
`scripts/analysis/score_live_trials.py` (D-G, the scorer-time `terminal_climate_day` bound) and
`deploy/systemd/score-live-trials-run.sh` (D-G's per-(city, manifest) loop and D-H/INC-SP1I5's
champion-manifest resolution at `:47`), plus `scripts/analysis/structural_dead_stop.py`'s inputs
as consumed by that wrapper. The prior §5 exclusion of these two files was this plan's own
scoping choice; the ruling (§6, R-4 ownership) lifts it explicitly.

**Explicitly excluded:**
- **No change to α, `n_max`, `i_max`, `look_step`, `boundary_inputs_sha256`, the LD-OBF boundary, or
  the admissibility predicate.** D-A and D-B are about which rows are SEEN, never about the test.
  The amendment's §7 "UNCHANGED from PREREG v3" list is the binding statement of this, and §8
  criterion 6 proves it by test.
- **No change to `combine_station_day`** (`current_rung_hold_v2.py:298-345`, def at `:298`). It already implements
  the registered mixed-side variance; touching it would be authoring the statistic rather than
  reaching it.
- **No change to the SHAPE of the strata the NO-side amendment's §7 registers as UNCHANGED**
  ("Strata: pooled (sequential monitor), station (cell_dead), ask-band (cell_dead)") — one stratum per
  station and per ask band over that station's/band's rows, regardless of side. Revision 3's proposed
  side-partition is withdrawn (§6). Whether NO rows are admitted into the two `cell_dead`-bearing
  strata at all is **BLOCKER-3** (§12) and is not decided by this plan; until it is ruled, those two
  strata are withheld rather than repartitioned (§6, split item 3).
- **No weakening of the two guards that fired.** `family_tally_v2.py:666-671` and
  `current_rung_hold_v2.py:414-419` are working controls; they are satisfied by fixing their inputs
  and by making the builder genuinely side-aware, never by deleting or relaxing them.
- **No edit to any file under `deploy/families/`.** BLOCKER-1 is RULED: `pm_us_crh_v4.json` is
  NOT re-issued, its `trial_id_prefix` is NOT changed, and `pm_us_crh_cont.json`'s `status` stays
  `"REGISTERED"` (the ruling keeps it as citable history). Any FUTURE re-registration of this
  lineage takes a **new family id, a new `trial_id_prefix`, and `n` reset to 0** per
  `POST_FORECAST_PHASE_2026-09-20.md` §A-9 item 2 — a prospective bar, not work for this item,
  and a precondition governed by `RULING_A1`'s own §7, not by AUD-05.
- **No store row is ever deleted or rewritten.** BLOCKER-2's pre-check is read-only; a
  contaminated `pm_us_crh_cont` store is recorded, never repaired (§6 BLOCKER-2 sequence).
- **No trading-enablement change.** `RULING_A1` halts `pm_us_crh_v4` from SENDING; nothing in
  this item sets, clears or tests that halt (the set-halt CLI is AUD-02b's, by id only), and
  nothing here may be read as satisfying any part of RULING_A1 §7's re-arm bar.
- No change to `pm_us_crh_v2`'s tally, to `live_family_tally.py`, to the structural-pin guard
  (pm_us_crh_v2-only by design), or to `kalshi_crh_v1`.
- No node change; no trading-behaviour change.

## 6. Proposed changes grounded in inspected code

**Native-mechanism note (L-1).** This item touches no Nautilus surface: the tally is a Breezy
offline analysis script over a Breezy parquet store and a Breezy SQLite state store, and systemd is
the scheduler. The null hypothesis is satisfied trivially — nothing new is built, three existing
functions are corrected and one alert edge is added on an existing sink.

### D-A → make `build_stratum_v2` side-aware, against the registered oracle

The refusal at `current_rung_hold_v2.py:418-423` (inside `build_stratum_v2`, def at `:405`) is a
deliberate fail-closed placeholder from the fix-first review of `87278dd`. **It is the FIRST raise
site this tally reaches**, established by execution order in `family_tally_v2.py`: `pooled =
build_stratum_v2("pooled", pooled_rows)` at `:645` runs before `combined_draws =
_combined_draws_for_looks(ordered)` (which calls `combine_station_day` at `:485`). The module's other
side-blind refusal, `score()` at `:164-169`, is never reached by this tally at all — `family_tally_v2.py`
imports and calls only `score_combined` (`:700`, `:782`). D-A's target is therefore `build_stratum_v2`
and nothing else.

**R2 correction — which function computes what.** Round 2 established that the amendment §3 `Var_H0`
cross-term formula is computed by `combine_station_day` (def `:298`; the cross term verbatim at
`:344`, `variance -= 2.0 * qtys[i] * qtys[j] * signs[i] * signs[j] * qs[i] * qs[j]`, with `signs` built
at `:329` and `qs` at `:330`) — **not** by `build_stratum_v2`. `build_stratum_v2` (`:405-437`) computes
exactly `n = len(rows)` (`:424`), `k = sum(1 for row in rows if row.held)` (`:425`),
`mean_ask = mean(entry_ask)` (`:426`), `pi = mean(break_even_row(entry_ask, fee))` (`:427`) and a Wilson
interval (`:428`); `StratumV2`'s field list (`:391-397`) is `label, n, k, mean_ask, pi, wilson_lower,
wilson_upper` — **there is no variance field and no cross term anywhere on this path.** The two paths are
structurally separate: `combine_station_day` feeds the sequential pooled monitor through `score_combined`;
`build_stratum_v2` feeds the fixed-rule `cell_dead` diagnostic (`:400-402`, `n >= 60 and wilson_upper <
float(pi)`), documented at `:387-389` as "no sequential monitoring here". Revision 2 quoted the right
formula against the wrong function; this revision separates them and re-points the test that proves it.

**The statistic a side-aware `build_stratum_v2` computes — RECOMMENDED here for the half that needs a
ruling, DECIDED here only for the half that is provably inert (R3 restructure).** The amendment
registers no stratum-level statistic (its §3 closed form is written for the sequential pooled draw),
so the oracle is derived from what the fields already mean, read from source:

- `StratumRow`'s docstring (`:99-105`) states `entry_ask`/`fee` are **always the leg's own**
  (`BE_i = ask_i + fee_i` "prices whichever side was actually bought"), and `held` is **always the
  caller-supplied per-side truth** (`1{HIGH ∈ r_i}` for YES, `1{HIGH ∉ r_i}` for NO) — "this module
  performs no further inversion of its own".
- Therefore `k/n` is already the **leg** win rate and `pi = mean(BE_i)` is already the **leg's own**
  hurdle, for a NO row exactly as for a YES row. Under H0 a NO leg wins with probability
  `1 − q_i = BE_i` (`_cell_probability`, `:225-227`: `q_i = 1 − BE_i` for NO), so
  `pi = mean(BE_i) = mean(E[held_i])` — precisely the null that `k/n` must be compared against.
- **Recommended disposition (the statistic): `pi` stays `mean(BE_i)`; `k`, `mean_ask`, the Wilson call
  and `cell_dead` keep their current arithmetic byte-unchanged; `StratumV2` gains no field; and the
  rows are **NOT partitioned by side**.** The algebra, re-derived from source this revision and stated
  in full so the ruling authority can check it rather than take it: `held` is the leg's own truth
  (`StratumRow` docstring `:103-105`) and `q_i = P(HIGH ∈ r_i)` (`_cell_probability`, `:225-227`), so
  under H0 `E[held_i] = q_i = BE_i` for a YES leg and `E[held_i] = 1 − q_i = 1 − (1 − BE_i) = BE_i` for
  a NO leg. **`E[held_i] = BE_i` on BOTH sides.** Therefore `k = Σ held_i` compared against
  `pi = mean(BE_i)` (`:425`, `:427`) is already the correct null for a MIXED stratum, with no
  partition, no new field and no new formula — the arithmetic at `:424-428` needs no change at all, and
  the ONLY code change D-A requires in `current_rung_hold_v2.py` is the removal of the blanket refusal
  at `:418-423`.
- **The alternative considered and REJECTED (unchanged from revision 3):** `pi := mean(q_i)` (the
  reflected probability) is inverted for NO rows — `q_i = P(HIGH ∈ r_i)` (`:226`) while `k` counts the
  leg's own win, so on a NO-only stratum it compares the NO-leg win rate against the YES-leg win
  probability and flips `cell_dead`'s verdict.
- **A SECOND alternative, newly REJECTED this revision: side-PARTITIONING the strata** (revision 3's own
  recommendation — `"pooled|no"`, `"station:KSFO|no"`, `"ask:(0.2,0.3]|no"` built at
  `family_tally_v2.py:498`, `:511`, `:645`). Both round-3 reviewers independently found that this
  invents stratum ENTITIES that exist in neither PREREG v3 nor the NO-side amendment, whose §7
  "UNCHANGED from PREREG v3" list reads verbatim **"Strata: pooled (sequential monitor), station
  (cell_dead), ask-band (cell_dead)"**. Since the unpartitioned form is provably correct under H0 (the
  bullet above), partitioning buys nothing statistically and costs a departure from the registered
  shape: it multiplies the number of cells that can independently fire `cell_dead`, which changes the
  KILL rate's operating characteristics. **Revision 4 withdraws it.** The two homogeneity worries that
  motivated it are answered from source rather than by partitioning: (i) `mean_ask` (`:426`) is **not
  read by `cell_dead`** (`:400-402` reads only `n`, `wilson_upper`, `pi`) — it is printed by
  `_fmt_stratum_row` (`family_tally_v2.py:830-835`) and nowhere else, so a mixed `mean_ask` is a
  REPORTING artefact and is handled by labelling the rendered column (**specified concretely below —
  R4 mle defect 1: this sentence was the justification for withdrawing the partition and previously
  had no step, AC or test behind it**), not by repartitioning a registered stratum; (ii) `classify_ask_band(float(row.entry_ask))` (`family_tally_v2.py:507`) bands
  on the **leg's own** entry ask, and since `E[held_i] = BE_i ≈ ask_i + fee_i` on both sides, a NO leg
  bought at 0.30 and a YES leg bought at 0.30 share the same null — the band is homogeneous in exactly
  the quantity `cell_dead` tests.

**D-A(ii) — the `mean_ask` side-mix label, specified rather than promised (R5, mle defect 1).** The
withdrawal of the partition above is only safe if a mixed-side `mean_ask` is *visibly* mixed to the
human and the downstream reader who consume the rendered table. Read from source before specifying:
`STRATUM_TABLE_HEADER` is the fixed string
`"| stratum | n | k | mean ask | mean BE (pi) | Wilson-lower | Wilson-upper | |"`
(`family_tally_v2.py:182-184`), rendered once at `:1072` with `STRATUM_TABLE_DIVIDER` (`:185`);
`_fmt_stratum_row` (`:830-835`) formats one row and already uses the trailing empty column for the
`"CELL-DEAD"` marker; the rows are rendered at `:1075` (`tally.pooled`) and `:1077` (the two frozen
strata). `StratumV2` (`current_rung_hold_v2.py:386-402`) carries no side field, and **this plan does
not add one** — that dataclass is the registered statistic's own shape.

The concrete change is confined to the report renderer **plus one carrier field**, because the
renderer cannot reach the rows (R6, mle defect 1). Verified in source this revision:
`render_markdown_v2` is defined at `family_tally_v2.py:1025` with the signature
`(tally: FamilyTallyV2, *, source_paths, as_of)` and contains BOTH cited call sites (`:1075`,
`:1077`); its only datum is the already-built `FamilyTallyV2`, whose field list (`:262-294`) carries
`pooled`/`station_strata`/`ask_band_strata`/`looks`/`verdict` and **no rows and no side counts**. The
row sequences are locals of a DIFFERENT function, `build_family_tally_v2` (`:567`): `pooled_rows` at
`:644` and the `non_excluded` groups consumed by `_station_strata`/`_ask_band_strata` at `:653`/`:654`
— all out of scope by the time `main()` calls the renderer (`:1312-1325`). So "computed at the call
site from the row sequence" (revision 5's wording) is **not implementable and is withdrawn**; the
data-flow is named explicitly instead:

- **`FamilyTallyV2` gains one defaulted carrier field, `pooled_side_mix: str = ""`** (`:262-294`,
  the frozen/slots/kw_only dataclass — appended alongside the existing defaulted fields
  `store_empty_no_sidecar`/`n_residual_excluded`/`residual_scored_contradictions` at `:286-294`, so
  every existing constructor keyword stays untouched). It is computed ONCE inside
  `build_family_tally_v2` from `pooled_rows` (`:644`, whose `StratumRow.side` field is the per-leg
  truth documented at `current_rung_hold_v2.py:99-110`) immediately before the `FamilyTallyV2(...)`
  return at `:809-827`, i.e. while the rows are still in scope. Once BLOCKER-3 admits NO rows to the
  `cell_dead`-bearing strata, the same mechanism extends additively with
  `strata_side_mix: tuple[str, ...] = ()` — one entry per element of the rendered
  `(*station_strata, *ask_band_strata)` sequence (`:1076`), an empty tuple meaning "no annotation",
  which is exactly today's behaviour.
- This is the **smallest correct extension**: a label string, not a statistic. `StratumV2`
  (`current_rung_hold_v2.py:386-402`) still gains no field; `build_stratum_v2` is unchanged; the new
  field is never read by `cell_dead` (`family_tally_v2.py:655`), never enters `look_verdict`/
  `terminal_look` (`:728`/`:753`/`:792`), and never reaches the score.
- **Effect on the byte-identity guarantee (AC #5) — none, and this is checkable rather than
  asserted.** `FamilyTallyV2` is never serialised: its only consumer is `render_markdown_v2`, reached
  from `main()` at `:1312-1325`, so the guarantee AC #5 makes lives on the *rendered report text*, not
  on the dataclass shape. The defaults (`""` / `()`) make an all-YES corpus emit no annotation and no
  footnote, so the rendered bytes are unchanged; adding a defaulted kw-only field also leaves every
  existing `FamilyTallyV2(...)` construction and every pinned fixture valid unchanged.
- `_fmt_stratum_row` takes one new keyword-only argument, `side_mix: str` (`:830-835`), supplied by
  the renderer from `tally.pooled_side_mix` at `:1075` and from `strata_side_mix` at `:1077` (falling
  back to `""` while that tuple is empty) — never re-derived inside the formatter, never persisted,
  never read by `cell_dead`.
- `side_mix` takes exactly three values and renders exactly this text, appended **inside the
  `mean ask` cell**, immediately after the existing `f"{stratum.mean_ask:.4f}"`:
  - all rows `side == "yes"` → **the empty string** (the cell is byte-identical to today's);
  - all rows `side == "no"` → `" (NO-only)"`;
  - both sides present → `" (mixed-side: Y<n_yes>/N<n_no>)"` with the two integer counts, e.g.
    `| pooled | 12 | 7 | 0.3125 (mixed-side: Y9/N3) | 0.3400 | … |`.
- When at least one rendered row carries a non-empty annotation, exactly one footnote line is added
  immediately after the table (the blank line at `:1078`):
  `"mean ask is a per-leg average in each leg's OWN price domain; a NO leg's ask is not comparable "`
  `"with a YES leg's. Annotated cells mix domains and must not be read as one price. pi = mean(BE_i) "`
  `"is unaffected: E[held_i] = BE_i on both sides (see the family manifest and PREREG v3 amendment "`
  `"NO_SIDE 2026-09-14 §3)."`
  On an all-YES corpus no annotation is produced and **the footnote is not emitted**.
- `STRATUM_TABLE_HEADER` and `STRATUM_TABLE_DIVIDER` are **NOT changed.** This is deliberate and is
  what keeps AC #5's end-to-end byte-identity floor intact: on an all-YES corpus every cell, the
  header and the footnote region are byte-for-byte what they are today.

This makes the §6 justification a checked artefact: the partition is withdrawn *and* the disclosure
that makes withdrawing it safe is built and tested, rather than asserted in prose.

**The fact that decides what may ship without a ruling — `cell_dead` IS gating, and the two round-3
reviewers disagreed about it.** Settled here from source, with line refs, because the whole
restructure turns on it:

- `any_cell_dead = any(s.cell_dead for s in (*station_strata, *ask_band_strata))` —
  `family_tally_v2.py:655`.
- It is passed as `cell_dead=any_cell_dead` into `terminal_look(...)` at `:728` and `:792`, and into
  `look_verdict(...)` at `:753`.
- `look_verdict`'s docstring (`current_rung_hold_v2.py:449-453`) and its body (`:461-465`) implement
  `SURVIVE <=> S >= b_eff AND total_pnl > 0 AND not cell_dead AND not structural_fired` and
  `KILL <=> S <= b_fut OR cell_dead OR structural_fired`. The result is assigned to `verdict` (`:748`,
  `:722`, `:786`) and returned as `FamilyTallyV2.verdict` (`:822`).
- **Therefore `station_strata`/`ask_band_strata` `cell_dead` is a LIVE KILL TRIGGER on the registered
  sequential test, not a report label.** The round-3 mle record's claim that `any_cell_dead` is "a
  REPORT-LEVEL flag, never fed into any admission gate" is REJECTED with evidence: of the five sites it
  cites, only `:655` computes it and only `:831` is report text; `:728`, `:753` and `:792` are the
  three verdict calls above. The round-3 pm record is correct on this point.
- **`pooled` is the opposite, and this is what may ship without a ruling.** `pooled =
  build_stratum_v2("pooled", pooled_rows)` (`:645`) is NOT a member of `any_cell_dead`'s tuple
  (`:655`); it flows only to `FamilyTallyV2.pooled` (`:818`) and is rendered by `_fmt_stratum_row`
  (`:830-835`). The sequential pooled monitor is a different object entirely (`combined_draws` →
  `score_combined`, `:652`, `:700`, `:782`). So the `pooled` StratumV2's `cell_dead` is provably inert
  to every registered element, and admitting NO rows into it decides nothing.
- **Correction to a claim in the round-3 pm record:** it states a `pooled`-only fix "already clears the
  measured D-A failure" because `:645` raises first. It does not. `_station_strata` (`:653`, calling
  `build_stratum_v2` at `:498`) and `_ask_band_strata` (`:654`, calling it at `:511`) run over the same
  `non_excluded` rows immediately after, so a `pooled`-only fix moves the `ValueError` from `:645` to
  `:653`. The tally still does not run. That is why the meantime behaviour below is needed and is not
  optional.

**The three-way split this revision makes (per the round-3 finding that a §7-frozen element must not
be decided in-plan):**

1. **Ships without a ruling — provably inert.** Remove the blanket refusal at `:418-423` so
   `build_stratum_v2` accepts a NO row, and admit NO rows into the **`pooled`** stratum (`:645`) only.
   Justified entirely by the two facts above: `pooled` is not in `any_cell_dead`, and the existing
   arithmetic is the correct null on both sides. `StratumV2` gains no field; `:424-428` is unchanged.
2. **RULED 2026-09-21 — BLOCKER-3 is answered, option (a) (`docs/evidence/RULING_live_family_tally_scope_2026-09-21.md`, §4).** NO-side rows
   are **admitted into `station_strata`/`ask_band_strata` UNPARTITIONED, with
   `pi = mean(BE_i)`** — exactly the disposition this plan recommended, now confirmed against the
   registered text rather than merely derived: PREREG v3 §10 registers the `cell_dead` strata as
   `n≥60` vs `mean(BE_i)` with no side field
   (`docs/specs/PREREG_v3_continuous_rung_hold_DRAFT_2026-09-10.md:210`), independently
   corroborated by `docs/evidence/PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md:186`, which restates
   "Strata: pooled (sequential monitor), station (cell_dead), ask-band (cell_dead)" in the very
   amendment that made NO rows admissible. Option (c) (side-partitioning) is affirmatively
   REJECTED by the ruling and option (b) (YES-only strata) is rejected as the *more permissive*
   choice. **What changes in this plan, concretely:** `_station_strata` (`:653`, builder call at
   `:498`) and `_ask_band_strata` (`:654`, `:511`) run over the same `non_excluded` rows
   regardless of side, with no label suffix and no new field; `StratumV2` still gains nothing;
   `:424-428` is still byte-unchanged; and the `strata_side_mix: tuple[str, ...] = ()` carrier
   this plan already reserved in D-A(ii) is now **exercised**, one entry per element of the
   rendered `(*station_strata, *ask_band_strata)` sequence (`:1076-1077`). The strict `xfail` on
   `test_a_mixed_station_stratum_renders_the_side_mix_label` (§7 step 1) **converts to a plain
   passing test** in the same change, which is precisely what that marker was placed to force.
3. **Interim behaviour — now time-boxed by the ruling, not by the ruling's absence.** The ruling
   (§4, "Interim state before this ruling is implemented") **retains this behaviour as the
   deployed behaviour until item 2's code lands and passes its own RED→GREEN tests**, and not one
   run longer: once BLOCKER-3's option (a) is implemented, the `PENDING_STRATA_RULING` branch and
   its sentinel verdict are **removed in the same change** (the sentinel was widened into the
   verdict union only to defer an unruled decision; a ruled decision retires it). Until then, in
   `build_family_tally_v2`, compute `no_side_rows` from `non_excluded` (the same
   `_stratum_row(t).side` the builder reads). Then:
   - `no_side_rows` empty → **every line of behaviour is byte-identical to today**, which is what the
     all-YES invariance floor in §7 step 1 proves.
   - `no_side_rows` non-empty → `station_strata = ()` and `ask_band_strata = ()` are **not computed**,
     `any_cell_dead` is **not fabricated as `False`** (a silent false-negative on a KILL trigger is the
     exact failure this refuses to commit), the look loop is skipped by the same mechanism the
     structural-dead branch already uses (`scheduled_ns = range(0)`, `:694-696`), and the tally
     publishes `verdict = "PENDING_STRATA_RULING"` with the named reason
     `NO_SIDE_STRATA_UNRULED (BLOCKER-3)` rendered in the report. **It still emits `n_scored`,
     `n_excluded`, the residual/contradiction counts and the `pooled` statistic** (`:809-827`), so `n`
     is visible to AUD-02 and the §11 chain is not blocked by the ruling. `bca_line` stays `None`
     (it is only assigned inside the look loop, `:744`/`:769`/`:807`) and the report says so.
   - **No look is lost by withholding.** `build_family_tally_v2` rebuilds `looks` from scratch on every
     invocation (`looks: list[LookRecord] = []` at `:686`, populated from `combined_draws` at
     `:699-807`); nothing is persisted or spent. Re-running after the ruling reproduces the full look
     trail from the same store, so declining to evaluate costs nothing and asserts nothing.
   - The unit **exits 0** — this is a deliberate withholding, not a failure — and emits one WARN
     `FAMILY_TALLY_STRATA_RULING_PENDING` per `(family_id, UTC day)` through D-F's sink and latch, so
     the withheld verdict is visible rather than silent.
   - The verdict literal gains this one new sentinel value; the three registered outcomes
     (`SURVIVE`/`KILL`/`CONTINUE`) keep their exact meanings and arithmetic. Widening the union is a
     new value, never a redefinition.

This keeps D-A a refusal-removal plus a call-site-level guard that invents no statistic, leaves the
registered sequential statistic (`combine_station_day` → `score_combined`) byte-untouched, and — now
that BLOCKER-3 is RULED — reaches the §7-frozen strata shape only in the one way the authority that
owns it has ruled: unpartitioned admission at `pi = mean(BE_i)`, shape unchanged.

**The registered formula, quoted for the invariance test — asserted in §7 step 1b against
`combine_station_day`, the function that actually computes it.** From
`PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md` §3:

- Sign: `s_i = +1` for YES legs, `s_i = −1` for NO legs (amendment §3 "Notation").
- Break-even on each leg's OWN quote:
  `BE_i = ask_YES_i + fee(ask_YES_i)` for YES;
  `BE_i = (1 − bid_YES_i) + fee(1 − bid_YES_i)` for NO.
- Outcome: `held_i = 1{HIGH ∈ r_i}` for YES; `held_i = 1{HIGH ∉ r_i}` for NO.
- Cell probability, side-independent by construction: `q_i = BE_i` for YES; `q_i = 1 − BE_i` for NO,
  with the registered semantics `q_i = P(HIGH ∈ r_i)` under H0.
- Draw and variance (amendment §3, "Station-day draw variance (exact formula)"):
  `x_sd = Σ_i qty_i (held_i − BE_i)`
  `Var_H0(x_sd) = Σ_i qty_i² q_i (1 − q_i) − 2 Σ_{i<j} qty_i qty_j s_i s_j q_i q_j`
- Pair-sign breakdown (amendment §3, "Three pair cases"): YES/YES → `−2 q_i q_j`;
  **YES/NO → `+2 q_i q_j` (positive)**; NO/NO → `−2 q_i q_j`.
- Admission gate (amendment §3 closing line and §4): `Σ_YES BE_i + Σ_NO (1 − BE_j) ≤ 1`.
- Substitution check (amendment §3): all-YES reduces byte-identically to PREREG v3.

The fee model is symmetric under `p → 1 − p` (amendment §2), and the amendment instructs reuse of
`decision._fee:253-260` **verbatim, no new code path** — so D-A introduces no second fee function.

The refusal is **replaced by handling, not removed**: a row with a side outside `{yes, no}` still
raises at `StratumRow.__post_init__` (`:132-138`), and a mixed-side row set still raises inside
`build_stratum_v2` per the ruling above. The implementer's field-level work is confined to
`build_stratum_v2` (`current_rung_hold_v2.py:405-437`, R2 re-anchor from the stale `:380-430` estimate)
and the three call sites that build its `label`; step 0(f) prints `StratumRow`'s and `StratumV2`'s actual
field lists into the evidence doc so the change is sized from evidence rather than from reading the plan.

### D-B → fix the counting unit, not the guard

`count_filled_takes` (`fill_time_count.py:139-159`) must count what `len(rows)` counts. Under MP-A
the scored-row unit is one row per FILL while `counted_trial_keys` is one key per STATION-DAY — a
category error that makes the guard fire on correct data. The fix follows **whichever single cause
step 0 establishes** (if both are operative, each gets its own RED test and its own commit):
count fills (not station-day keys) under the family prefix, and match the `^no` instrument id on
the same leg basis the ledger writes it. `family_tally_v2.py:666-671` stays byte-unchanged.

**Pre-narrowing for cause (ii), from inspected source.** NO-leg fills live on a *composite*
instrument id `"<slug>^no"` minted by `symbology.no_leg_instrument_id` (`:277`), classified by
`symbology.leg_of` (`:289`, delegating to `domain.instrument_leg.leg_of_symbol`), with
`sibling_instrument_id` (`:318`) as the YES↔NO involution and `LEG_NO`
(`adapters/polymarket_us/parsing.py:1471`) as the parse-side token. A NO buy is never a SELL of YES
(`submit_chain.py unmappable_order_reason`: "only a BUY is mappable (a SELL is a naked short);
refusing"). So the FIRST check in step 0(b) is simply: **do the ledger's `filled_instrument_ids`
contain composite `^no` ids, and does the scored row's `trial.instrument_id` carry the same
composite form?** If the two forms differ (one base, one composite), cause (ii) is established
without further work.

### D-D → RULED CLOSED: v4 keeps its identity; the guard moves to the scorer

**Superseded by `docs/evidence/RULING_live_family_tally_scope_2026-09-21.md` (BLOCKER-1).**
No new `trial_id_prefix`, no manifest edit, no `n` reset. The tally-time barrier already separates
the pair (`family_barrier.py:52-96` at `family_tally_v2.py:622`, after the prefix filter at `:602`),
and re-issuing a REGISTERED manifest while `RULING_A1` is adjudicating that family's trading
disposition would itself be a class-C act taken outside that ruling's process. The work D-D carried
is replaced, one-for-one, by **D-G**.

### D-G → the scorer refuses a fill past a family's terminal day (the ruled BLOCKER-1 remedy)

`score_live_trials.py` must not admit a row whose `climate_day` follows the manifest's
`terminal_climate_day`, mirroring at CREATION time the bound `assert_family_only` enforces at tally
time (`family_barrier.py:85-91`, inclusive upper bound). The seam is the one place the lower bound
is already resolved: `main()` reads `since_climate_day = manifest.d0_climate_day` (`:1789`) and
passes it into `score_live_trials` → `read_filled_trials_state_db`, whose only date check is
`climate_day < since_climate_day` (`:722`). The smallest correct extension is the symmetric
companion — resolve `until_climate_day = manifest.terminal_climate_day` (`None` = still open,
exactly the manifest's own semantics, `family_barrier.py:41-45`) at the same site and skip any row
with `climate_day > until_climate_day` on the same pass. **Excluded, deliberately:** no new
CLI flag whose default could silently reopen the gap, no change to the wrapper's enumeration, and
no exception class — an out-of-bounds row is *not scored for that family*, which is the behaviour
the manifest already declares; the loud refusal stays where it already is, at tally time.

**Pin test on the tally-time barrier (required by the same ruling).** The barrier is the reason
BLOCKER-1 does not require a manifest re-issue, so its behaviour on THIS pair becomes a pinned
contract rather than an incidental property: assert that a `pm_us_crh_cont`-dated row is refused
from a `pm_us_crh_v4` tally and a v4-dated row from a cont tally, both raising
`FamilyBarrierRefusal` (`family_barrier.py:48-49`), under the **shared** `trial_id_prefix` the two
manifests actually declare — so a future prefix or bound edit cannot quietly remove the protection
this ruling relies on.

### D-H / INC-SP1I5 → the 14:15Z KILL-clock counter follows the deployed champion (R-4, SP-1 I5)

**Named increment, per the R-4 ownership ruling: `SP-1 I5`
(`docs/plans/LIVE_FILL_SCORING_CHAIN_2026-09-05.md:236,311,313`) remains the spec of record;
INC-SP1I5 is the AUD-05 increment that IMPLEMENTS it.** AUD-10's `C-KILL` (cited by ID only)
CONSUMES the resulting counter and never builds it.

**Current:** `score-live-trials-run.sh:47` hard-codes
`FAMILY_MANIFEST="$REPO/deploy/families/pm_us_crh_v2.json"` and feeds it to
`structural_dead_stop.py --family-manifest` at `:125`; the comment at `:40-46` records the pin as
deferred to "R-4, SP-1 I5". **Required:** the counter counts for whichever family the node is
actually deployed to send from.

**Champion resolution — single source of truth, no second literal.** The deployed family is named
in exactly one place: `deploy/systemd/breezy-trade-supervisor.service:115`,
`Environment=BREEZY_SENDING_FAMILY_ID=pm_us_crh_v4`, which is the variable
`SENDING_FAMILY_ID_VAR` (`src/breezy/runtime/settings.py:112`) that the node itself loads and
fail-closed validates into `deploy/families/<id>.json` (`_validate_sending_family_manifest`,
`:373-393`). The wrapper therefore resolves the manifest by READING that unit's environment
(`systemctl --user show breezy-trade-supervisor.service --property=Environment`, parsed for
`BREEZY_SENDING_FAMILY_ID`) and mapping the id through the same `$FAMILIES_DIR/<id>.json` rule the
settings loader uses — never by a second hard-coded family literal, and never by "whichever
manifest looks newest". **Fail closed:** if the variable is absent, empty, resolves to no manifest
file, or resolves to a manifest whose `status` is not `REGISTERED`, the wrapper `say`s the reason
and exits 1 **before** removing `$CJSON` — the same posture the counter already takes when
`structural_dead_stop.py` fails (`score-live-trials-run.sh:118-128`), so a stale counter is never consumed and yesterday's
counts are never silently re-read.

**Scope verification for the consumer.** `structural_dead_stop.py` already records
`manifest_sha256` from the loaded manifest (`:349`, emitted into the counter JSON at `:304`,
`:318`, `:391`), so the counter JSON **already carries** the field a consumer needs; INC-SP1I5's
obligation is to prove it carries the CHAMPION's sha — asserted by test, not by inspection — so
AUD-10's `C-KILL` can verify scope by comparing it against the currently-armed family's own
manifest. No new field is invented.

**Behaviour while `pm_us_crh_v4` is HALTED (`RULING_A1`).** The clock keeps counting: RULING_A1 §4
rules explicitly that the halt stops SENDING only and that "the node, quote-tape capture, shadow
valuation, or the KILL clock" continue. For a family that cannot send, "KILL" keeps its registered
meaning — the structural-dead test asks whether this family's own D0/coverage window has closed
without the evidence it needed, and a halted family accrues covered station-days but no fills, so
the clock runs toward structural death rather than away from it. That is the correct and intended
reading: it is the mechanism by which an indefinitely halted family stops being an open question
instead of ageing silently. INC-SP1I5 therefore neither pauses nor special-cases the counter on the
halt, and the counter is **never** a re-arm signal (RULING_A1 §7 owns that bar).

### D-C → enable the instance

`systemctl --user enable --now breezy-family-tally@pm_us_crh_v4.timer`. The template
(`deploy/systemd/breezy-family-tally@.service`) is explicitly designed for this and does not change.
The wrapper already supplies `--covered-listed-station-days`, `--fill-source` and
`--fill-since-climate-day` for any REGISTERED polymarket_us family (`family-tally-v2-run.sh`,
SD-1/L-38 generalisation), reading v4's own `d0_climate_day`.

### D-E → delete the two orphan unit files

From the user unit directory, then `daemon-reload`. Nothing references them; WP-11b already replaced
them.

### D-F (NEW, R1) → a failing tally must reach a human

Round 1 correctly refused to accept "pick one of two options". **The choice is made here:** the
wrapper's failure branch emits through the same sink the rest of the repo uses —
`emit_alert(resolve_alert_sink(), AlertPayload(severity="CRITICAL", event="FAMILY_TALLY_FAILED",
site="breezy-family-tally@<family_id>", detail="<exception class + the raising file:line, no
currency figure>"))` — delivering since `f97c26f`. **Latched:** one alert per `(family_id, UTC day)`,
via a latch file under `derived/family_tally/.alert_latch.json`, so a repeating daily failure pages
once a day, not once per retry (the false-page discipline WP-R1 was opened for). A systemd `failed`
unit state remains the secondary signal, never the only one — "a detector without delivery is not a
control" (readiness audit 2026-09-12).

## 7. Ordered implementation / verification steps (RED first)

0. **EVIDENCE PACK (read-only; no unit started, no code changed).**
   `docs/evidence/FAMILY_TALLY_FAILURE_2026-09-__.md` recording:
   (a) both tracebacks verbatim from `family_tally_v2.log` with their timestamps and the journal
   lines that bracket them;
   (b) the exec-state ledger's `TrialDayRecord` keys under `continuous_rung_hold/trial/` since
   2026-09-12 and the `DurableFillRecord` instrument ids **printed in full so the composite `^no`
   form is visible**, side by side with each scored row's `trial.instrument_id` — **this is the
   measurement that discriminates D-B cause (i) from (ii)**, and it decides the fix. Check the
   `leg_of`/`^no` form FIRST (see §6);
   (c) the enabled/failed/orphan unit inventory;
   (d) the `trial_id_prefix` collision, shown from both manifests;
   (e) whether any NO-leg fill exists in the record at all today (this bounds what AC #4's live half
   can mean);
   (f) the verbatim field lists of `StratumRow` (`current_rung_hold_v2.py:124-130`) and `StratumV2`
   (`:391-397`), plus `build_stratum_v2`'s body (`:405-437`), so D-A's field-level change is sized from
   evidence (R2 re-anchor: the round-2 `:380-430` estimate was stale);
   (g) the installed `breezy-family-tally@*` unit inventory joined against every manifest's `status` in
   `deploy/families/`, so D-E's orphan guard has a baseline;
   (h) **(ruled, required before BLOCKER-2's terminal run) the `pm_us_crh_cont` store pre-check**
   — load `$STORE_DIR/pm_us_crh_cont`'s rows with `read_scored_trials`
   (`src/breezy/persistence/scored_trial_store.py:118-134`, the same function
   `family_tally_v2.py:1288` already uses — no new I/O path, no new store surface) and record, in
   memory only, every row whose `climate_day` falls outside `pm_us_crh_cont.json`'s own
   `d0_climate_day`/`terminal_climate_day` bounds (i.e. `climate_day >= pm_us_crh_v4.json`'s
   `d0_climate_day`), by `trial_id` and `climate_day`. **This step writes nothing and repairs
   nothing**; it exists to predict whether the terminal run can produce a report or will raise
   `FamilyBarrierRefusal` (`assert_family_only` refuses the WHOLE batch on the first offending
   row, `family_barrier.py:75-96`), and both outcomes are already ruled (§6, BLOCKER-2
   sequence);
   (i) the deployed champion as read from `breezy-trade-supervisor.service:115`
   (`BREEZY_SENDING_FAMILY_ID`) beside `score-live-trials-run.sh:47`'s literal, so INC-SP1I5's
   before/after is evidenced rather than assumed.
   Read-only SQLite access only (the `mode=ro` URI idiom at `fill_time_count.py:84-98`).
1. **RED for D-A, against the function D-A actually changes (R2 fix — round 2 established that the
   round-1 oracle belonged to `combine_station_day`, which this item does not change):**
   - `test_a_no_leg_row_is_scored_not_refused` — a single-sided NO stratum through `build_stratum_v2`.
     RED today (`:418-423` raises `ValueError`); GREEN after, returning a `StratumV2` whose `k` is the
     NO legs' own wins and whose `pi` is `mean(BE_i)` over those legs' own `entry_ask + fee`.
   - `test_a_no_only_stratum_uses_the_legs_own_break_even_not_its_reflection` — on a NO-only fixture
     with every `BE_i = 0.40`, assert `pi == Decimal("0.40")` and **not** `0.60`, and that `cell_dead`
     is evaluated against that `pi`. This is the test that discriminates the ruled statistic from the
     REJECTED `mean(q_i)` alternative: it is RED today (the call raises) and would still fail against a
     `mean(q_i)` implementation after the fix.
   - `test_a_mixed_side_pooled_stratum_scores_each_leg_against_its_own_break_even` (R4, replaces
     revision 3's `test_a_mixed_side_row_set_still_raises`) — one YES row at `BE = 0.30` and one NO row
     at `BE = 0.70`; assert `n == 2`, `k` counts each leg's own `held`, and `pi == Decimal("0.50")`,
     i.e. the unpartitioned mixed stratum is scored against `mean(BE_i)` exactly as the §6 derivation
     `E[held_i] = BE_i` requires. RED today (`:418-423` raises).
   - `test_a_row_with_an_unknown_side_still_raises` — `StratumRow.__post_init__` (`:132-138`) stays live;
     proves the side validation was not weakened along with the refusal.
   - `test_a_no_bearing_corpus_withholds_the_cell_dead_strata_and_the_verdict` (R4) — drive
     `build_family_tally_v2` over a corpus containing one NO row; assert `station_strata == ()`,
     `ask_band_strata == ()`, `verdict == "PENDING_STRATA_RULING"` with reason
     `NO_SIDE_STRATA_UNRULED`, `looks == ()`, and that `n_scored`/`n_excluded`/`pooled` are still
     populated. This is the test that proves the ruling is deferred rather than silently taken.
   - `test_a_no_bearing_corpus_never_reports_cell_dead_false` (R4) — the negative control on the
     false-negative direction: assert no code path passes a fabricated `cell_dead=False` into
     `look_verdict`/`terminal_look` when the `cell_dead` strata were withheld.
   - `test_no_stratum_label_carries_a_side_suffix` (R4) — the regression floor on the withdrawn
     partition: over the call sites `family_tally_v2.py:498`, `:511`, `:645`, assert no built label
     contains `"|no"` or `"|yes"`, so a later implementer cannot reintroduce the unregistered
     partition without a RED test.
   - **NEW (R5)** `test_a_mixed_side_pooled_row_renders_the_side_mix_label_on_mean_ask` — the test
     that makes §6 D-A(ii)'s labelling commitment checkable, and it is exercisable **in this item**
     (not only post-BLOCKER-3) because `pooled` is exactly where this plan admits NO rows: **an
     isolated formatter test** — call `_fmt_stratum_row(stratum, side_mix="…")` directly over a
     stratum built from 9 YES and 3 NO rows and assert the `mean ask` cell is
     `f"{mean_ask:.4f} (mixed-side: Y9/N3)"` verbatim, and that
     `STRATUM_TABLE_HEADER`/`STRATUM_TABLE_DIVIDER` are unchanged strings. RED today
     (`_fmt_stratum_row` has no `side_mix` argument, `family_tally_v2.py:830-835`).
   - **NEW (R5)** `test_a_no_only_stratum_renders_the_no_only_label_on_mean_ask` — the single-sided
     NO case, isolated the same way: the cell carries `" (NO-only)"`. RED today.
   - **NEW (R6, the plumbing proof — mle defect 1)**
     `test_the_side_mix_label_reaches_the_rendered_report_end_to_end` — the isolated tests above prove
     the formatter *formats*, not that the renderer can ever *produce* the argument, which is exactly
     the gap §6 D-A(ii) now closes with `FamilyTallyV2.pooled_side_mix`. This test drives the whole
     path: build a `ScoredTrial` corpus of 9 YES and 3 NO rows → `build_family_tally_v2(rows, …)`
     (`family_tally_v2.py:567`) → `render_markdown_v2(tally, source_paths=…, as_of=…)` (`:1025`), and
     asserts on the RETURNED REPORT TEXT that the pooled row's `mean ask` cell carries
     `" (mixed-side: Y9/N3)"` and that the price-domain footnote appears exactly once. It additionally
     asserts `tally.pooled_side_mix == "(mixed-side: Y9/N3)"`'s rendered literal is not fabricated by
     the renderer — i.e. the field, not the call site, is the source of the label. **RED today on the
     carrier, not only on the formatter:** `FamilyTallyV2` (`:262-294`) has no `pooled_side_mix`
     field, so the test fails at construction/attribute access before it ever reaches
     `_fmt_stratum_row`. This is the test whose absence let revision 5 specify an unimplementable
     mechanism.
   - **NEW (R5)** `test_an_all_yes_corpus_renders_no_side_mix_label_and_no_footnote` — the
     byte-identity guard on the label itself: over the all-YES fixture, assert **no** annotation text
     and **no** footnote line appear anywhere in the rendered report, so the disclosure cannot drift
     into the registered path. This test is the companion of, and must not be confused with, the
     end-to-end floor `test_an_all_yes_corpus_renders_a_byte_identical_report`.
   - **NEW (R5, deferred exercise — BLOCKER-3)** `test_a_mixed_station_stratum_renders_the_side_mix_label`
     — the same assertion on a `station_strata`/`ask_band_strata` row. It is written now and marked
     with a **strict** `xfail` naming BLOCKER-3, because those strata are withheld until the ruling;
     it converts to a plain passing test the moment NO rows are admitted there. The strict marker is
     the mechanism that stops the ruling landing without the label following it.
   **End-to-end invariance floor (must be GREEN before AND after — this is the proof that the
   REGISTERED statistic is unchanged, run over the whole pipeline rather than one function):**
   - `test_an_all_yes_corpus_renders_a_byte_identical_report` — drive `build_family_tally_v2` over an
     all-YES fixture and assert the **rendered report text** is byte-identical pre- and post-fix.
     Amendment §3's substitution check and §10 criterion 2, applied end to end.
   **1b. Invariance characterisation of the registered variance — explicitly NOT a RED test for D-A**
   (`combine_station_day` does not change; it is already side-aware and is an §5 exclusion). Labelled as
   such in the test module docstring so no later reader mistakes it for proof of D-A:
   - `test_combine_station_day_matches_the_registered_variance_formula_at_unequal_qty` — a YES/NO pair
     with `qty_i ≠ qty_j` (e.g. `qty_i = 1`, `qty_j = 3`), asserting the **diagonal terms**
     (`Σ qty_i² q_i(1−q_i)`, `:341`) and the **cross term** (`:344`) **independently** against
     hand-computed values, not merely the aggregate `Var_H0`, and asserting the cross term is POSITIVE
     for the YES/NO pair. Unequal `qty` is what separates "sign carried on the pair product `s_i s_j`"
     (amendment §3, `signs` at `:329`) from "sign folded into `q_i`": the two agree at `qty_i = qty_j`
     and diverge on the diagonal otherwise — the "plausible but wrong" class the amendment's own history
     note warns about.
   - `test_a_station_day_breaching_the_sum_q_gate_is_refused` — amendment §4's gate, live at `:331-336`.
2. **GREEN D-A** in `settlement/current_rung_hold_v2.py`, **stratum builder only**;
   `combine_station_day` diff must be empty (asserted at merge).
3. **RED for D-B:** a fixture built through the real writer path (L-42) with two rung fills on one
   station-day and one `^no` fill; assert `count_filled_takes` ≥ the scored-row count, and assert
   `build_family_tally_v2` no longer raises. Plus `test_a_settled_only_count_still_raises` — the
   guard must stay live. Plus `test_a_no_leg_fill_is_counted_under_its_composite_instrument_id`
   (cause (ii)) and/or `test_two_rung_fills_on_one_station_day_count_as_two`
   (cause (i)) — **only the test(s) for the cause step 0 established.**
4. **GREEN D-B** in `fill_time_count.py`. Re-run the contract test that already covers it
   (`tests/contract/test_live_fill_scoring_chain_contract.py`) and
   `tests/unit/test_fill_time_count.py`.
5. **RED/GREEN D-F:** `test_a_failing_tally_emits_a_critical_alert_through_the_sink`;
   `test_the_failure_alert_fires_once_per_family_per_day`;
   `test_the_failure_alert_carries_no_currency_denominated_field`.
6. **D-G (replaces D-D; BLOCKER-1 is already RULED — no artefact to author, cite
   `docs/evidence/RULING_live_family_tally_scope_2026-09-21.md`).**
   **RED first:** `test_a_fill_after_a_familys_terminal_day_is_refused_for_that_family` — a
   fixture fill dated 2026-09-21 scored under `pm_us_crh_cont.json` (terminal 2026-09-19) is
   admitted today and must be excluded after the fix;
   `test_a_fill_inside_a_familys_bounds_is_still_scored` — the non-regression control, a fill on
   2026-09-15 under cont and a fill on 2026-09-21 under v4 both still score;
   `test_the_terminal_day_bound_is_inclusive_on_both_edges` — boundary days: a row exactly on
   `terminal_climate_day` (2026-09-19) is KEPT and a row exactly on `d0_climate_day` is KEPT,
   mirroring `family_barrier.py:80-91`'s inclusive bounds in both directions;
   `test_an_open_family_with_no_terminal_day_is_unbounded_above` — `terminal_climate_day: None`
   keeps today's behaviour exactly. **GREEN** in `score_live_trials.py` at the `:1789`/`:722`
   seam. **Plus the ruled pin test on the tally-time barrier:**
   `test_the_barrier_separates_cont_from_v4_under_their_shared_prefix` — both directions, both
   raising `FamilyBarrierRefusal`, against the two manifests' real declared values, so the
   protection BLOCKER-1 relies on cannot be removed silently.
7. **D-C** enable the v4 timer instance; **D-E** remove the orphans; `daemon-reload`. **Plus the
   re-accumulation guard (R2):** `test_no_installed_family_tally_timer_targets_an_unregistered_family` —
   enumerate the installed `breezy-family-tally@*` units and fail if any instance's family is not
   `status: REGISTERED` in `deploy/families/`. RED against the two orphans from step 0(g) before D-E,
   GREEN after; it then stands as the standing guard against the WP-11b failure mode that created them.
8. `scripts/ci/run_tests_no_egress.sh` + `lint-imports`. Observe three consecutive 17:20Z runs.
9. **BLOCKER-3's ruled implementation (option (a)), after D-C is running.** RED first:
   `test_a_mixed_station_stratum_scores_no_rows_unpartitioned_against_mean_be` and
   `test_a_no_bearing_corpus_produces_a_registered_verdict_not_the_pending_sentinel` (the direct
   inverse of step 1's withholding test, which is REPLACED by it — the withholding test is
   retired in the same commit that retires the branch it pins, never left asserting behaviour the
   ruling removed). Convert `test_a_mixed_station_stratum_renders_the_side_mix_label` from a
   strict `xfail` to a plain passing test by wiring `strata_side_mix` through `render_markdown_v2`
   at `:1076-1077`. Keep `test_no_stratum_label_carries_a_side_suffix` GREEN — the ruling rejects
   partitioning, so that regression floor stands unchanged. GREEN: `_station_strata` (`:653`) and
   `_ask_band_strata` (`:654`) over all `non_excluded` rows; delete the `PENDING_STRATA_RULING`
   branch and its sentinel value.
10. **BLOCKER-2's ruled retirement sequence for `pm_us_crh_cont`, in this order, after steps 2/4
   land** (D-A and D-B are family-agnostic — they fix `build_stratum_v2` and `count_filled_takes`):
   (a) read step 0(h)'s pre-check findings; (b) attempt the terminal tally run **once**, whatever
   the pre-check said — a clean store yields a terminal report; a contaminated store yields the
   expected `FamilyBarrierRefusal`, and **that refusal, together with the pre-check's named
   out-of-bounds `trial_id`/`climate_day` values, IS the terminal evidentiary state** (never a
   fabricated verdict, never a filtered re-read: `family_tally_v2.py`'s `main()` has no in-bounds
   filtering path and none is added); (c) record both in the evidentiary note that closes the
   family's record; (d) disable the timer — **unconditionally, in either branch** (§10).
11. **INC-SP1I5 (D-H), in parallel.** RED first:
   `test_the_counter_resolves_the_manifest_from_the_deployed_sending_family_id` (champion
   `pm_us_crh_v4` resolved from `BREEZY_SENDING_FAMILY_ID`, not from the `:47` literal);
   `test_the_counter_json_carries_the_champion_manifest_sha256` (asserting the emitted
   `manifest_sha256`, `structural_dead_stop.py:304`/`:318`/`:349`/`:391`, equals the champion
   manifest's own — the field AUD-10's `C-KILL` verifies scope with);
   `test_the_counter_refuses_when_the_sending_family_id_is_absent_or_unregistered` (fail-closed:
   non-zero exit, `$CJSON` left absent, no stale file consumable);
   `test_the_counter_still_runs_for_a_halted_family` (the halt stops SENDING only — the clock
   keeps counting coverage). GREEN in `score-live-trials-run.sh` at `:40-47`/`:118-128`. **No
   second family literal is introduced anywhere** — assert that too, by grepping the wrapper for
   `deploy/families/` literals in the test.

## 8. Measurable acceptance criteria and required evidence

1. `breezy-family-tally@pm_us_crh_v4.service` completes **exit 0 on three consecutive days**, with
   `family_tally_v2_pm_us_crh_v4_<date>.md` written each day. Evidence: `systemctl --user status`,
   three artefacts, the wrapper log lines.
2. **(RULED)** `pm_us_crh_cont` is retired: its timer is **disabled either way**, and the
   evidentiary note that closes its record carries BOTH (a) step 0(h)'s read-only pre-check
   findings (the specific out-of-bounds `trial_id`/`climate_day` values, or "none found") and
   (b) the terminal run's outcome — `SURVIVE`/`KILL`/`CONTINUE` **or** `REFUSED-BY-BARRIER` with
   the raising row. It is never left enabled-and-failing, and disablement is never made contingent
   on a clean run. Evidence: the note, the pre-check output, `systemctl --user is-enabled` after.
3. The v4 report's `n` counts **zero** rows whose `climate_day < 2026-09-20`, proved by a test, not
   by inspection (A-9 item 5).
4. A NO-leg fill is **scored** (not refused) by the stratum builder, proven by the step-1 fixture.
   The live half ("and again when a real NO fill occurs") is recorded as an OPEN observation, not a
   merge gate — there have been no fills since 09-15 and step 0(e) states whether any NO-leg fill
   exists at all. Making an unschedulable event a gate would block the fix behind the blackout it is
   meant to end.
5. **The registered statistic is unchanged**, proven three independent ways (R2: each now asserted
   against the code path it actually describes): (a) `test_an_all_yes_corpus_renders_a_byte_identical_report`
   is GREEN before and after, over the **rendered end-to-end report**, not one function's return value;
   (b) the step-1b characterisation test matches amendment §3 at **unequal `qty_i ≠ qty_j`**, with the
   diagonal and cross terms asserted separately, against `combine_station_day` — the function that
   computes that formula; (c) `combine_station_day`'s diff is empty, asserted at merge. Evidence: the
   diff plus RED→GREEN output for step 1 and the before/after GREEN pair for (a).
6. `systemctl --user list-timers --all | grep breezy-pm-crh` returns nothing.
7. A simulated tally failure produces exactly one CRITICAL alert for that family that UTC day,
   delivered out-of-process, carrying no currency figure.
8. RED→GREEN output for every test in §7, plus the unchanged-guard tests
   (`test_a_settled_only_count_still_raises`, `test_a_row_with_an_unknown_side_still_raises`) green.
9. The step-0 evidence doc exists and names which D-B cause was established (and says so explicitly
   if both were).
10. `test_no_installed_family_tally_timer_targets_an_unregistered_family` is RED against the step-0(g)
   orphan inventory and GREEN after D-E, and stays in the suite as the standing re-accumulation guard.
11. **The inert half is implemented and the frozen half is withheld (R4 restructure).** `pi` is
   `mean(BE_i)` on both sides and no stratum label carries a side suffix, proven by
   `test_a_no_only_stratum_uses_the_legs_own_break_even_not_its_reflection`,
   `test_a_mixed_side_pooled_stratum_scores_each_leg_against_its_own_break_even` and
   `test_no_stratum_label_carries_a_side_suffix`; `StratumV2`'s field list and the body at `:424-428`
   are unchanged, asserted by diff. AC #11 **does not** assert that the side-aware `cell_dead` question
   is settled — it is BLOCKER-3 and is explicitly not a merge gate.
12. **(SUPERSEDED IN PART — this is now the INTERIM criterion, binding only until step 9 lands.)**
   BLOCKER-3 is RULED (option (a)); per the ruling the withholding behaviour stays deployed until
   the ruled code passes its own RED→GREEN, and AC #16 is what replaces this criterion at that
   point. Until then, and as the merge gate for steps 1–8: on a NO-bearing corpus the unit exits 0,
   writes its dated report, publishes `n` and the `pooled` statistic, publishes
   `verdict = "PENDING_STRATA_RULING"` with reason `NO_SIDE_STRATA_UNRULED`, computes no
   `station_strata`/`ask_band_strata` and passes no fabricated `cell_dead` anywhere — proven by
   `test_a_no_bearing_corpus_withholds_the_cell_dead_strata_and_the_verdict` and
   `test_a_no_bearing_corpus_never_reports_cell_dead_false`, plus exactly one WARN
   `FAMILY_TALLY_STRATA_RULING_PENDING` per family per UTC day. **This criterion replaces, and must not
   be read as weakening, any expectation that a NO fill produces a verdict before the ruling: it
   requires the strictly stronger behaviour of refusing to publish one.** Retiring this criterion
   is permitted **only** by AC #16 being GREEN, never by deleting the branch on its own.
13. **(R5) The mixed-side `mean_ask` disclosure that justified withdrawing the partition is built,
   rendered and tested — not merely asserted (R4 mle defect 1).** On a mixed-side corpus the pooled
   row's `mean ask` cell renders `f"{mean_ask:.4f} (mixed-side: Y<n_yes>/N<n_no>)"` and on a NO-only
   stratum `" (NO-only)"`, with the price-domain footnote emitted exactly once; on an all-YES corpus
   neither the annotation nor the footnote appears and `STRATUM_TABLE_HEADER`/
   `STRATUM_TABLE_DIVIDER` are unchanged strings. Proven by
   `test_a_mixed_side_pooled_row_renders_the_side_mix_label_on_mean_ask`,
   `test_a_no_only_stratum_renders_the_no_only_label_on_mean_ask` and
   `test_an_all_yes_corpus_renders_no_side_mix_label_and_no_footnote`, with
   `test_a_mixed_station_stratum_renders_the_side_mix_label` carried as a **strict** `xfail` naming
   BLOCKER-3 so the ruling cannot land without the label following it. **(R6) The label must be
   proven to REACH the report, not merely to format:** the three tests above exercise
   `_fmt_stratum_row` in isolation with `side_mix` pre-supplied, so this criterion additionally
   requires `test_the_side_mix_label_reaches_the_rendered_report_end_to_end` — rows →
   `build_family_tally_v2` (`family_tally_v2.py:567`) → `render_markdown_v2` (`:1025`) → asserted
   report text — to be GREEN, which is the only evidence that the `FamilyTallyV2.pooled_side_mix`
   carrier specified in §6 D-A(ii) is actually wired. **This criterion adds a disclosure and removes
   nothing:** `StratumV2` gains no field, `cell_dead` reads nothing new, the one new `FamilyTallyV2`
   field is a defaulted label string that no statistic reads, and AC #5's byte-identity floor is
   unaffected by construction.
14. **(RULED, D-G) The scorer cannot create a row outside a family's declared bounds.** A fill
   dated after a family's `terminal_climate_day` is not scored into that family's store; a fill
   inside the bounds still scores; both boundary days behave inclusively; an open family
   (`terminal_climate_day: None`) is unchanged. Evidence: RED→GREEN for the four §7 step-6 tests,
   plus `test_the_barrier_separates_cont_from_v4_under_their_shared_prefix` GREEN as the standing
   pin on the tally-time protection BLOCKER-1's disposition depends on. **No file under
   `deploy/families/` appears in the diff** — asserted at merge, since a manifest edit is exactly
   what the ruling forbids.
15. **(RULED, INC-SP1I5) The 14:15Z counter is champion-scoped and provably so.** The counter runs
   against the manifest named by `BREEZY_SENDING_FAMILY_ID`
   (`deploy/systemd/breezy-trade-supervisor.service:115`), its JSON's `manifest_sha256` equals
   that manifest's own, the wrapper exits non-zero with `$CJSON` absent when the id is missing or
   not REGISTERED, and it still counts while the family is halted from sending. Evidence: RED→GREEN
   for the four §7 step-11 tests plus a grep-assertion that `score-live-trials-run.sh` contains no
   second `deploy/families/<family>.json` literal. AUD-10's `C-KILL` is the consumer and is cited
   by id only; this item does not verify AUD-10's side.
16. **(RULED, BLOCKER-3 option (a)) NO rows reach the `cell_dead` strata unpartitioned.**
   `station_strata`/`ask_band_strata` are computed over all `non_excluded` rows regardless of
   side, at `pi = mean(BE_i)`, with no label suffix, no new `StratumV2` field and `:424-428`
   byte-unchanged; `strata_side_mix` annotates the rendered rows; the `PENDING_STRATA_RULING`
   branch and sentinel are GONE; `test_a_mixed_station_stratum_renders_the_side_mix_label` passes
   as a plain test and `test_no_stratum_label_carries_a_side_suffix` is still GREEN. AC #5's
   all-YES byte-identity floor is GREEN before and after — the all-YES path is untouched by this
   criterion.
17. **Every ruled disposition is cited, never re-decided.** The plan text, the commit messages and
   the evidence doc name `docs/evidence/RULING_live_family_tally_scope_2026-09-21.md` (and
   `docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md` for the halt) as the authority
   for D-D's closure, D-G, BLOCKER-2's sequence, BLOCKER-3's option (a) and INC-SP1I5. No
   implementer re-opens a ruled question inside this item.

## 9. Validation: failure cases, integration, autonomous operation

- **The guards must still fire.** Both fixes are input fixes; §8 criterion 8 is the proof that
  neither guard was disguised. This is the L-46 failure class (disguising the offender is deleting
  the guard) and the explicit prohibition in §5.
- **The registered statistic drifts under the D-A fix.** The single highest-risk outcome of this
  item. Guarded three ways, each pointed at the path it actually covers (R2): the end-to-end all-YES
  byte-identity floor on the rendered report (amendment §10 criterion 2), the unequal-`qty`
  characterisation of amendment §3 against `combine_station_day` (the function that computes it), and
  an empty diff on `combine_station_day` plus an unchanged `StratumV2` field list.
- **The `cell_dead` KILL trigger changes basis without a ruling.** The highest-consequence failure this
  revision closes: `any_cell_dead` (`family_tally_v2.py:655`) is a KILL disjunct in `look_verdict`
  (`current_rung_hold_v2.py:461-465`), so admitting NO rows into `station_strata`/`ask_band_strata`
  under an unregistered convention would silently change when the live family's evidence collection
  stops — in either direction (a false KILL ends the tally this item exists to restore; a false
  negative lets a genuinely dead cell keep contributing looks). Closed by withholding both strata and
  the verdict until BLOCKER-3 rules, and by `test_a_no_bearing_corpus_never_reports_cell_dead_false`.
- **The withheld verdict becomes a permanent silent hold.** A ruling that never arrives would leave the
  live family reporting `PENDING_STRATA_RULING` indefinitely. Bounded by the WARN
  `FAMILY_TALLY_STRATA_RULING_PENDING` on D-F's latch (once per family per UTC day), so the hold is a
  standing, delivered signal rather than a quiet artefact nobody reads.
- **A future implementer reintroduces the withdrawn side-partition.** Closed by
  `test_no_stratum_label_carries_a_side_suffix` as a standing regression floor, not by prose.
- **A future retire leaves a third orphan timer.** The WP-11b failure mode that produced D-E's two
  orphans is closed by the standing guard in §7 step 7 / AC #10, not only by deleting today's two.
- **Store contamination.** With v4 on its own prefix, a v3 row reaching the v4 store raises
  `FamilyStoreContaminationError` rather than being dropped — verify the store-declared-single-family
  path still refuses.
- **Residual/scored contradiction.** The 09-20 log shows one such contradiction already being
  excluded fail-closed (ruling R1/R4). The fixes must not change that count; assert it.
- **Two families tallying the same store.** While `pm_us_crh_cont` remains REGISTERED, the scorer
  writes both families. Assert each family reads only its own `--derived-dir`.
- **Alert becomes noise.** D-F's latch fires once per family per UTC day; a chronically failing unit
  pages daily, not per-run.
- **(D-G) The scorer guard silently drops rows that should have scored.** The failure direction
  that matters: an over-broad upper bound would hide real fills from a live family's `n`. Closed by
  `test_a_fill_inside_a_familys_bounds_is_still_scored` and the inclusive-boundary test, and by the
  guard reading the manifest's own declared value rather than any literal date.
- **(D-G) The protection BLOCKER-1 relies on is removed later.** The ruling's "no manifest re-issue"
  disposition is only safe while `assert_family_only`'s bounds hold for this pair; a future prefix
  or bound edit could void it invisibly. Closed by the standing pin test, not by prose.
- **(INC-SP1I5) Champion resolution drifts or fails open.** If `BREEZY_SENDING_FAMILY_ID` is
  renamed, unset, or points at an unregistered manifest, a counter that fell back to a default
  would resume counting the wrong family's coverage — the exact defect D-H exists to end. Closed
  fail-closed: exit 1 with `$CJSON` absent, so the downstream consumer refuses rather than reads a
  stale file (`score-live-trials-run.sh:118-128`).
- **(INC-SP1I5) A halted family's clock is mistaken for a re-arm signal.** The counter keeps
  running under `RULING_A1`'s halt by design; nothing in this item may be read as clearing that
  halt, and `C-KILL`'s consumption (AUD-10, by id) is scope verification, never enablement.
- **(BLOCKER-3) The interim sentinel outlives its ruling.** `PENDING_STRATA_RULING` is a deferral
  device for an unruled question that is now ruled; leaving it deployed after step 9 would publish
  a withheld verdict on a settled basis. Closed by AC #16 requiring the branch and the sentinel to
  be gone, and by the strict `xfail` converting in the same change.
- **(BLOCKER-2) A contaminated store is "repaired".** The strongest temptation in step 10. Refused
  structurally: the pre-check is read-only, no filtered-read path exists or is added, and the
  refusal itself is the recorded evidence (L-46 shape — disguising the offender is deleting the
  guard).
- **Autonomous operation:** the template already has `Persistent=true`, no `Restart=`, and a memory
  ceiling. The residual autonomy defect — **three days of failure produced no alert** — is closed by
  D-F, not deferred to a choice.

## 10. Deployment, observability, rollback

- **Deploy:** merge the code fix; commit the wrapper and unit changes (**no manifest change** —
  BLOCKER-1 is RULED); `daemon-reload`; enable the v4 timer instance; remove the orphan timers. No
  node restart and **no change to trading behaviour** — the tally is a read-only observer, and
  `RULING_A1`'s halt is untouched.
- **Disabling `breezy-family-tally@pm_us_crh_cont.timer` is an implementation-time DEPLOYMENT act,
  not a planning act — it is specified here and performed by the implementer, never by this plan.**
  Step: after step 10(b)'s single terminal run and 10(c)'s note,
  `systemctl --user disable --now breezy-family-tally@pm_us_crh_cont.timer`, then
  `systemctl --user daemon-reload`. **Verification:** `systemctl --user is-enabled` reports
  `disabled`, `list-timers --all` no longer lists the instance, and the evidentiary note records
  the disable timestamp beside the terminal outcome. **Rollback:**
  `systemctl --user enable --now breezy-family-tally@pm_us_crh_cont.timer` restores it exactly —
  the template is untouched and no state is destroyed, so this step is fully reversible. The
  manifest's `status` stays `"REGISTERED"`; a reader must not infer un-registration from a disabled
  timer, which is why the reason is recorded in the note and in the unit-inventory evidence.
- **INC-SP1I5 deploy:** commit the wrapper change; the next 14:15Z run resolves the champion from
  `BREEZY_SENDING_FAMILY_ID` and writes `$CJSON` with the champion's `manifest_sha256`.
  **Verification:** the wrapper's `say` line names the resolved family and manifest path, and
  `$CJSON`'s `manifest_sha256` matches `deploy/families/pm_us_crh_v4.json`'s own. **Rollback:**
  revert the single wrapper commit — `:47`'s literal returns and the counter reverts to v2 scope
  (a known-wrong but previously-deployed state), with no persistent artefact to unwind beyond the
  one day's `$CJSON`.
- **Observability:** the wrapper's `say` lines in `family_tally_v2.log`, the dated report artefacts,
  unit state, and (new) a delivered CRITICAL on failure.
- **Rollback:** `systemctl --user disable --now breezy-family-tally@pm_us_crh_v4.timer` and revert
  the commit. The manifest prefix change is the only irreversible-ish element: once v4 rows are
  written under the new prefix, reverting strands them. Mitigation: the prefix change lands with
  the ruling, before any new fill, and the old prefix's rows are untouched.

## 11. Relationship to portfolio-level ROI and how it is evaluated

**Channel: epistemic, and it is the gating channel for the only money-moving item in this backlog.**
The tally measures a *family's registered sequential statistic*, not portfolio ROI — different
estimands (L-2), and this plan lets neither stand in for the other. But the dependency is concrete
and directional, not rhetorical:

`AUD-05 (a tally that runs) → n can grow → AUD-02 can publish a family-scoped edge estimate → that
artefact is AUD-06b's BLOCKER-B → sizing may be built → AUD-04 measures whether it paid.`

**Baseline.** The explicit baseline is today's state, stated as a number: the live family's tally
has produced **zero** reports, `n` is **0**, and the unit has failed on **≥3** consecutive scheduled
runs. Post-change the baseline comparison is: reports produced on 3/3 days, `n` accruing from
v4-scoped rows only, failures delivered rather than silent.

**Plausible vs demonstrated.** This item demonstrates **no ROI whatsoever** and must never be
presented as doing so. What it demonstrates is *admissibility*: that a fill can reach a registered
statistic at all. Without it, "increasing ROI" has no admissible evidence path for the live family —
which is a claim about the evidence pipeline, not about returns.

**How it is evaluated.** Binary and structural: does a live fill reach a v4-scoped report within one
day of settlement, and does a failing tally reach a human within one day. Both are observable from
the artefacts in §8 without running anything.

**Falsifier.** If the v4 report's `n` ever counts a row from the v3 prefix, or if the all-YES
byte-identity floor breaks, the item has failed even though the unit exits 0 — a tally that runs on
the wrong rows is worse than one that fails loudly.

**What `RULING_A1`'s halt changes here — stated plainly, because it bounds the whole §11 chain.**
`pm_us_crh_v4` may not SEND orders (`docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`
§4), so while the halt stands the live family produces no NEW fills and `n` may legitimately remain
0 no matter how well this item works. That does **not** make the item optional or premature: the
ruling keeps the node, capture, tally and KILL clock running precisely so the measurement spine is
ready and observable, and a blackout discovered later — after a re-arm, with fills on the floor —
costs strictly more than one fixed now. It does mean the chain above is **deferred, not
demonstrated**: this item's honest claim is that the pipeline is admissible and observable, never
that `n` will grow on any schedule. The falsifier below is unaffected — it tests correctness of the
rows that DO arrive, including the six historical fills, not their arrival rate.

**Dependency ordering.** Stage 1 (with AUD-04, independent of it). **No longer ruling-blocked:**
BLOCKER-1/2/3 are RULED (§12), so D-A, D-B, D-F, D-G, the BLOCKER-2 sequence, BLOCKER-3's
implementation and INC-SP1I5 are all executable now; INC-SP1I5 runs in parallel, sharing no code.

## 12. Assumptions, unresolved questions, blockers

- **BLOCKER-1 — RULED 2026-09-21, peer-ENDORSED. NOT a blocker any more.** Artefact:
  `docs/evidence/RULING_live_family_tally_scope_2026-09-21.md` §4 (review trail
  `docs/evidence/reviews/RULING_tally_scope_review_2026-09-21.md`). **Ruled: neither (a) nor (b) as
  posed** — no re-issue and no edit of the registered `pm_us_crh_v4` manifest, and no date bound
  added to `filter_rows_to_manifest_prefix`, because the tally-time barrier already discriminates
  the pair (`family_barrier.py:52-96` at `family_tally_v2.py:622`). The ruled remedy is D-G's
  scorer-time `terminal_climate_day` guard plus the barrier pin test (§6, §7 step 6, AC #14). Any
  FUTURE re-registration of this lineage takes a new family id, a new `trial_id_prefix` and `n`
  reset to 0 (`POST_FORECAST_PHASE_2026-09-20.md` §A-9 item 2) — prospective, and a precondition
  `RULING_A1` §7 owns, not this item. The question as originally posed is recorded below for the
  record only:
- **[HISTORICAL — the question BLOCKER-1 asked, now answered above.]** `pm_us_crh_v4` is
  REGISTERED with a `trial_id_prefix` identical to `pm_us_crh_cont`'s. Changing a REGISTERED
  family's manifest identity is the class-C question L-34 governs. The ruling must state: (a) is v4
  re-issued with a new prefix (and if so, is `n` reset — A-9 says yes, and `n` is currently 0 so the
  cost is nil), or (b) is prefix-plus-`d0`/`terminal_climate_day` accepted as sufficient separation
  (which requires `filter_rows_to_manifest_prefix` to gain a date bound — a change to the tally's
  admission logic, i.e. a larger and riskier change)? **Recommendation: (a)** — it is the smaller
  change, `n` is 0, and it satisfies A-9 without touching admission logic.
- **BLOCKER-3 — RULED 2026-09-21, peer-ENDORSED. NOT a blocker any more.** Artefact:
  `docs/evidence/RULING_live_family_tally_scope_2026-09-21.md` §4. **Ruled: option (a)** — NO
  rows are admitted to `station_strata`/`ask_band_strata` **unpartitioned, at `pi = mean(BE_i)`**,
  confirmed against the registered text (`docs/specs/PREREG_v3_continuous_rung_hold_DRAFT_2026-09-10.md:210`)
  and corroborated by `docs/evidence/PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md:186`; option (c)
  affirmatively rejected, option (b) rejected as more permissive, not more conservative. The
  `PENDING_STRATA_RULING` interim is retained ONLY until §7 step 9 lands (§6 split item 3), then
  removed. Implemented by §7 step 9; verified by AC #16. The question as originally posed:
- **[HISTORICAL — the question BLOCKER-3 asked, now answered above.]** Does admitting NO-side rows into `station_strata`/`ask_band_strata` require a
  PREREG ruling before it lands? `PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md` §7 "UNCHANGED from PREREG
  v3" lists verbatim **"Strata: pooled (sequential monitor), station (cell_dead), ask-band
  (cell_dead)"** — at the same level of authority as α, the look schedule and the boundary hash — and
  neither PREREG v3 nor the amendment says how a NO-side row enters those two strata. They are not
  diagnostics: `any_cell_dead` (`family_tally_v2.py:655`) is a KILL disjunct of `look_verdict`
  (`current_rung_hold_v2.py:449-453`, `:461-465`) via `:728`/`:753`/`:792`. The ruling must state
  whether (a) NO rows are admitted unpartitioned with `pi = mean(BE_i)`, (b) the strata stay YES-only
  and NO rows are excluded from `cell_dead` entirely, or (c) some other disposition.
  **Recommendation: (a)** — §6 derives `E[held_i] = BE_i` on both sides from `StratumRow`'s own field
  semantics (`:103-105`) and `_cell_probability` (`:225-227`), so (a) requires no new statistic, no new
  field and no new stratum entity, and it preserves the §7 shape (one stratum per station/band over
  that station's/band's rows) exactly. Two alternatives are recorded as REJECTED with evidence in §6:
  `pi := mean(q_i)` (inverted for NO rows) and side-partitioning the strata (invents cells the
  registration never described). **This plan does not decide it.** Until it is ruled, §6's split item 3
  applies and the tally withholds those two strata and its verdict — the ruling is the only thing
  gated, never the tally's ability to run, publish `n`, or alert.
- **BLOCKER-2 — RULED 2026-09-21, peer-ENDORSED. NOT a blocker any more.** Artefact:
  `docs/evidence/RULING_live_family_tally_scope_2026-09-21.md` §4. **Ruled: YES, retired**
  as of 2026-09-20 (`bcb82d6`); `terminal_climate_day: 2026-09-19` structurally forecloses any new
  row, and the champion moved to v4. Sequence: read-only store pre-check (§7 step 0(h)) → ONE
  attempted terminal run → record the outcome (report, or the expected `FamilyBarrierRefusal` plus
  the pre-check findings) → **disable the timer either way** (§7 step 10, §10, AC #2). Store rows
  are never deleted or rewritten; the manifest `status` stays `"REGISTERED"` so AUD-02 can still
  cite the family's terminal record.
- **R-4 — RULED 2026-09-21, peer-ENDORSED.** Same artefact, §4: the 14:15Z counter is
  champion-scoped; `SP-1 I5` stays the spec of record and **INC-SP1I5 (§6, §7 step 11, AC #15) is
  the AUD-05 increment that implements it**; AUD-10's `C-KILL` consumes it (by id only). R-4's own
  literal text pointing the counter at `pm_us_crh_cont.json` is **superseded** — cont is retired.
**What genuinely remains open (no ruling pending on any of it):**

- **Unresolved until step 0:** which of the two D-B causes is operative (possibly both). The fix is
  scoped to the established cause(s) only — §7 step 3. This is a measurement, not a ruling.
- **Unresolved until step 0(h):** whether `$STORE_DIR/pm_us_crh_cont` is already contaminated by
  the D-G gap. Both branches are ruled (§7 step 10), so this determines which evidentiary outcome
  is recorded, never whether the item can proceed.
- **External, not owned here:** `RULING_A1`'s halt is **UNENFORCED** until AUD-02b's
  `breezy-set-family-halt` CLI lands and is run (cited by id; not this item's work). While it is
  unenforced, nothing in this item makes the family more or less able to send — the tally is a
  read-only observer — but the §11 chain stays deferred either way.
- **Not a blocker, an acknowledged limitation:** AC #1's three-consecutive-day clock and AC #4's
  live half (no NO-leg fill exists yet, step 0(e)) remain observations rather than merge gates.
- **Settled by round 1, no longer open:** whether fixing D-A risks changing the registered statistic.
  It does not: the amendment is REGISTERED (2026-09-14), §3 gives the exact formula, and
  `combine_station_day` already implements it. D-A closes the gap between a registered statistic and
  a placeholder refusal that predates its registration. §8 criterion 5 proves this rather than
  asserting it.
- **Assumption:** `pm_us_crh_v4.json`'s `taker_fee_coefficient: "0.0695"` is intended and is the
  A1(iii) re-registration. Not re-litigated here; noted because a tally over a family halted by
  `FEE_SCHEDULE_MISMATCH_REFUSALS` will legitimately report `n=0` for reasons AUD-05 cannot fix.
  Note the amendment's §7 pins `θ = 0.06` for `pm_us_crh_cont`; v4's different coefficient is part of
  why v4 is a distinct family and reinforces BLOCKER-1's option (a).
- **Assumption:** no live fill occurs before the fix lands. If one does, it lands under the old
  prefix and BLOCKER-1's option (a) must state its disposition.

## 13. Review history

**Baseline self-score (2026-09-21, author), 79/100** — carried-forward weaknesses are folded into
the Revision 2 table below.

### Round 1 (2026-09-21) — independent blind peer review

| Reviewer | Total |
|---|---|
| mle-reviewer (statistical validation / measurement engineering) | 78/100 |
| prediction-market-reviewer (portfolio accounting / risk) | 80/100 |

**Dispositions:**

| # | Reviewer | Defect | Disposition |
|---|---|---|---|
| 1 | mle | MINOR — D-A's fix under-cites the registered formula it must implement | **ACCEPTED, and treated as the item's central fix.** §6 D-A now quotes the amendment's §3 notation, `BE_i` per leg, `q_i`, `held_i`, the exact `Var_H0` formula, the three pair-sign cases and §4's admission gate, and instructs verbatim reuse of `decision._fee:253-260`. §7 step 1 adds `test_a_mixed_side_station_day_matches_the_registered_variance_formula` (asserting the POSITIVE YES/NO cross term) and `test_a_station_day_breaching_the_sum_q_gate_is_refused`. §8 criterion 5 makes "the registered statistic is unchanged" an acceptance criterion with three independent proofs. **Additional finding from verifying the amendment:** its §3 closing paragraph records that `combine_station_day` (`current_rung_hold_v2.py:192-227`, 87278dd) ALREADY implements the registered variance with `signs[i]*signs[j]` — so D-A is confined to the stratum builder and `combine_station_day` is now an explicit §5 exclusion with an empty-diff merge assertion. The amendment has no worked numeric example, so the test asserts the closed form directly rather than a quoted number. |
| 2 | pm | MINOR — D-B's two causes are not pre-ranked | **ACCEPTED.** §6 D-B and §7 step 0(b) now name `symbology.no_leg_instrument_id:277`, `leg_of:289`, `sibling_instrument_id:318` and `parsing.LEG_NO:1471`, and make "compare the composite `^no` form in the ledger against the scored row's `trial.instrument_id`" the FIRST check — which establishes cause (ii) without further work if the forms differ. §7 step 3 scopes the fix and its tests to the established cause(s) only. |
| 3 | both | Alert wiring left as a choice between two options | **ACCEPTED, choice made.** New §6 D-F: the wrapper's failure branch emits a CRITICAL `FAMILY_TALLY_FAILED` through `resolve_alert_sink`/`emit_alert`, latched once per `(family_id, UTC day)`; systemd `failed` remains secondary. Three tests in §7 step 5; AC #7. |
| 4 | both | D-A's field-level fix location unpinned | **ACCEPTED.** §6 D-A names the stratum builder's `side`/`BE`/`held` carriers around `current_rung_hold_v2.py:380-430`, and §7 step 0(f) requires the dataclass's verbatim field list in the evidence pack so the change is sized from evidence, not from prose. |
| 5 | mle | Establish the single D-B root cause before coding | **ACCEPTED.** §7 step 3 makes the test set conditional on step 0's finding; §8 criterion 9 requires the evidence doc to name it (and to say so explicitly if both are operative). |
| 6 | both | AC #4's live half is unschedulable | **ACCEPTED (own carried weakness, now closed).** AC #4 is split: the fixture half is the merge gate; the live half is an OPEN observation, with step 0(e) recording whether any NO-leg fill exists at all. Gating the fix on an unschedulable event would block the fix behind the blackout it exists to end. |
| 7 | both | "Portfolio objective alignment" 5/10 — contribution is indirect | **ACCEPTED in cause, REJECTED as a reason to inflate the claim.** The cause was that §11 asserted indirectness without showing the path. §11 now states the explicit chain (AUD-05 → n grows → AUD-02 edge artefact → AUD-06b BLOCKER-B → AUD-04 measures it), a numeric baseline (0 reports, n=0, ≥3 consecutive failures), a plausible-vs-demonstrated separation that concedes **zero** ROI contribution, an evaluation rule, a falsifier, and the dependency stage. The indirectness itself is real and is NOT dressed up. |

**Rejections:** none outright. Two remedies re-scoped (#6 split rather than dropped; #7 path made explicit without inflating the ROI claim). Both BLOCKERs stay blockers — neither reviewer disputed them, and this revision does not resolve either.

**Revision 2 self-score (2026-09-21, author), 88/100:**

| Criterion | Max | Score | Named remaining weakness |
|---|---|---|---|
| Fidelity to the gap and completeness | 20 | 18 | Covers every element of G-04 and surfaces D-D and D-F, which G-04 did not name. Loses points for not resolving R-4 itself — deferred to BLOCKER-2, which is the correct authority but leaves the item partially gated. |
| Technical correctness and evidence grounding | 20 | 19 | Both failures reproduced from the live journal with file:line, the prefix collision read byte-for-byte from both manifests (independently re-confirmed twice), and D-A is now anchored to a REGISTERED artefact's exact formula rather than a narrative reference. Loses a point because the D-B root cause is still two hypotheses pending step 0. |
| Implementation specificity and feasibility | 15 | 13 | Seams, call sites, the registered formula, the leg-form pre-narrowing, the alert latch and the field-list evidence step are all named. Loses points because the exact stratum-row field names are produced by step 0 rather than stated here — deliberate (they are read from source, not asserted), but it still leaves a discovery step inside the plan. |
| Acceptance criteria and validation quality | 20 | 18 | Criteria measurable; guard-preservation and statistic-invariance are each proven by test; AC #4 no longer depends on an unschedulable event. Loses points because AC #1's three-consecutive-day clock makes acceptance a three-day window. |
| Autonomous operation, failure handling, recovery | 15 | 14 | The real autonomy defect (three days of silent failure) is now closed by a specified, latched, delivering alert rather than a choice. Loses a point because a `not-found` orphan unit class is cleaned up but nothing prevents a future orphan from re-accumulating. |
| Portfolio objective alignment, scope, dependencies | 10 | 6 | §11 now states the explicit evidence chain to the only money-moving item, a numeric baseline, a falsifier and the dependency stage. Still scores mid-range because the contribution is genuinely epistemic — this item cannot move ROI, only make a family's statistic reachable — and D-D remains gated on a ruling this plan does not own. |

### Round 2 (2026-09-21) — independent blind peer review

| Reviewer | Total |
|---|---|
| prediction-market-reviewer (portfolio accounting / risk) | 92/100 |
| mle-reviewer (statistical validation / measurement engineering) | 73/100 |

**Round-2 readiness is the LOWER of the two: 73/100.**

**Dispositions (every defect, both reviewers):**

| # | Reviewer | Severity | Defect | Disposition |
|---|---|---|---|---|
| 1 | mle | MATERIAL | D-A's RED-test oracle (the amendment §3 `Var_H0` cross term) is not a statistic `build_stratum_v2` computes; the test is either never-RED (if it calls the unchanged `combine_station_day`) or implies inventing an unregistered variance field; and the amendment gives no oracle for a side-aware `pi`/`cell_dead` | **ACCEPTED in full — the central fix of this revision, and verified against source before writing.** Facts established by reading `src/breezy/settlement/current_rung_hold_v2.py` directly: `build_stratum_v2` def at `:405`, body `:405-437`, computing only `n` (`:424`), `k = sum(1 for row in rows if row.held)` (`:425`), `mean_ask` (`:426`), `pi = mean(break_even_row(entry_ask, fee))` (`:427`), Wilson (`:428`); `StratumV2` fields `:391-397` are `label, n, k, mean_ask, pi, wilson_lower, wilson_upper` — **no variance field**; `cell_dead` at `:400-402`. `combine_station_day` def at `:298`, `signs` at `:329`, `qs` at `:330`, diagonal at `:341`, cross term verbatim at `:344`. The reviewer is right on every point. Three changes: **(a)** §6 D-A now separates the two paths explicitly and states that the amendment's §3 formula is computed by `combine_station_day`, not by the changed function. **(b)** §6 D-A **rules** what side-aware means, deriving it from source rather than leaving it to the implementer: `pi` stays `mean(BE_i)` — because `StratumRow`'s docstring (`:99-105`) makes `entry_ask`/`fee` the leg's own and `held` the per-side truth, so under H0 a NO leg wins with probability `1 − q_i = BE_i` (`_cell_probability`, `:225-227`) and `pi = mean(BE_i) = mean(E[held_i])` is exactly the null `k/n` is compared against. The reviewer's own suggested `pi := mean(q_i)` is **REJECTED with evidence**: `q_i = P(HIGH ∈ r_i)` (`:204`, `:226`) while `k` counts the leg's win, so on a NO-only stratum it compares the NO-leg win rate against the YES-leg win probability and inverts `cell_dead`. What is genuinely side-unsafe is POOLING (`mean_ask` at `:426` across mixed sides; `classify_ask_band` at `family_tally_v2.py:507`), so the change is to partition strata by side at `family_tally_v2.py:498`, `:511`, `:645`, with a mixed-side row set still raising. No new statistic, no new field. **(c)** §7 step 1 is re-pointed so every RED test exercises `build_stratum_v2`, the invariance proof is the **end-to-end byte-identical rendered report** on an all-YES corpus, and the amendment §3 assertion moves to step 1b labelled explicitly as a characterisation of `combine_station_day`, NOT a RED test for D-A. AC #5 and §9 restated to match; AC #11 added. |
| 2 | mle | MINOR | Both central line citations stale (`combine_station_day` cited `:192-227`, actually `:298`; `build_stratum_v2` cited `:380-430`, actually `:405`) | **ACCEPTED, verified, corrected.** Re-anchored in §3 (`:298-345`, noting `:192-227` is the `CombinedDraw` docstring that *describes* the formula), §5 (`:298-345`), §6 D-A (`:405-437`, raise site `:418-423`) and §7 step 0(f) (`StratumRow` `:124-130`, `StratumV2` `:391-397`, body `:405-437`). |
| 3 | mle | (implied) | Which raise site D-A actually faces is not established | **ACCEPTED and answered from source.** §6 D-A now records the execution order in `family_tally_v2.py`: `build_stratum_v2("pooled", pooled_rows)` at `:645` runs before `_combined_draws_for_looks` (`combine_station_day` at `:485`), and `score()`'s own side-blind refusal (`:164-169`) is never reached — the tally calls only `score_combined` (`:700`, `:782`). `build_stratum_v2` is the first and only raise site for this item. |
| 4 | pm | MINOR | The positive-cross-term assertion cannot distinguish "sign on the pair product `s_i s_j`" from "sign folded into `q_i`"; they diverge only at `qty_i ≠ qty_j` on the diagonal | **ACCEPTED.** §7 step 1b's `test_combine_station_day_matches_the_registered_variance_formula_at_unequal_qty` uses `qty_i = 1`, `qty_j = 3` and asserts the diagonal (`:341`) and cross (`:344`) terms **independently** against hand-computed values, not the aggregate. AC #5(b) requires it. |
| 5 | pm | MINOR | D-E's orphan cleanup has no regression guard against re-accumulation (self-conceded, still open) | **ACCEPTED.** §7 step 0(g) adds the unit-vs-manifest inventory baseline; §7 step 7 adds `test_no_installed_family_tally_timer_targets_an_unregistered_family`, RED against the two orphans and GREEN after D-E; AC #10 and a new §9 failure case carry it. |
| 6 | mle | scoring note | Portfolio alignment 7/10 attributed to a "structural ceiling for enabling-only work", with **no named defect** | **RECORDED, no change made — and round 3 must justify or award.** The prediction-market reviewer scored this same §11, unchanged, at **10/10**, stating the indirect contribution "is a fact about this item's charter, not a plan defect". The mle record likewise states "I find no remaining defect in this section on its own terms". A criterion deduction with no named defect and no requested change is not actionable: there is nothing to fix. If round 3 deducts here it must name the concrete gap; otherwise the points should be awarded. |

**Rejections:** one, with evidence — the mle reviewer's proposed remedy `pi := mean(q_i)` (its "required change 1", option one) is rejected as inverted for NO rows per the source reading in disposition #1; the underlying defect it was proposed to fix is accepted in full and remedied by the stated ruling instead. Both BLOCKERs stay blockers; neither reviewer disputed them and this revision resolves neither. No scope was removed and no acceptance criterion softened — AC #5 was strengthened from one function's return value to an end-to-end rendered-report identity.

**Revision 3 self-score (2026-09-21, author) — deliberately conservative, scored against the lower round-2 total:**

| Criterion | Max | Score | Named remaining weakness |
|---|---|---|---|
| Fidelity to the gap and completeness | 20 | 17 | G-04 fully covered plus D-D/D-F/D-E; the D-A semantic gap the mle reviewer opened is now closed by a stated, source-derived ruling rather than left to the implementer. Still loses points: R-4 is deferred to BLOCKER-2, and the side-partitioning ruling changes the stratum **labels** a downstream reader sees, which no consumer has been surveyed for. |
| Technical correctness and evidence grounding | 20 | 16 | Every citation re-anchored against the current file and quoted with its line (`:298`, `:329`, `:341`, `:344`, `:405-437`, `:391-397`, `:418-423`, `:225-227`, `:99-105`); the raise-site ordering established by execution order. Does not claim full marks: the `pi = mean(BE_i)` ruling is a *derivation* from field semantics, not a registered formula, and it is this revision's single largest new claim. |
| Implementation specificity and feasibility | 15 | 11 | The statistic is now defined, the three call sites named, the rejected alternative recorded. Loses points because the label-suffix convention (`\|no`) is authored here rather than inherited from an existing convention, and D-B's root cause is still two hypotheses pending step 0. |
| Acceptance criteria and validation quality | 20 | 16 | AC #5 is now achievable for the function actually changed, and stronger (end-to-end rendered-report identity); AC #10/#11 added; unequal-`qty` coverage closes the pm reviewer's correctness gap. Loses points for AC #1's three-consecutive-day clock and AC #4's live half remaining an OPEN observation. |
| Autonomous operation, failure handling, recovery | 15 | 13 | D-F's latched delivering alert closes the three-day silent-failure defect; the orphan re-accumulation guard closes the last self-conceded gap. Loses points because both signals still depend on the timer firing at all — a stopped timer is caught only by systemd state. |
| Portfolio objective alignment, scope, dependencies | 10 | 7 | §11's chain, numeric baseline and falsifier are concrete and concede zero direct ROI. Held at the lower reviewer's mark rather than the higher, pending round 3 naming a defect or awarding the points (disposition #6). |

### Round 3 (2026-09-21) — independent blind peer review

| Reviewer | Total |
|---|---|
| prediction-market-reviewer (portfolio accounting / risk) | 77/100 |
| mle-reviewer (statistical validation / measurement engineering) | 80/100 |

**Round-3 readiness is the LOWER of the two: 77/100.**

**Dispositions (every defect, both reviewers):**

| # | Reviewer | Severity | Defect | Disposition |
|---|---|---|---|---|
| 1 | pm + mle (independently, same finding) | MATERIAL | Side-partitioning `station_strata`/`ask_band_strata` changes a component the NO-side amendment §7 lists as UNCHANGED ("Strata: pooled (sequential monitor), station (cell_dead), ask-band (cell_dead)"); the plan decided it in-plan under a "Ruling:" heading while filing two lower-stakes identity questions as blockers | **ACCEPTED in full; the central restructure of this revision.** The reviewers **disagreed on the load-bearing fact** (mle: `cell_dead` is "a REPORT-LEVEL flag, never fed into any admission gate", citing `family_tally_v2.py:655,728,753,792,831`; pm: it feeds `look_verdict`'s KILL decision). **Settled from source, and the pm reviewer is correct:** `any_cell_dead` is computed at `:655` over `(*station_strata, *ask_band_strata)` and passed as `cell_dead=` into `terminal_look` at `:728` and `:792` and `look_verdict` at `:753`; `look_verdict` (`current_rung_hold_v2.py:440-465`) documents and implements `KILL <=> S <= b_fut OR cell_dead OR structural_fired` (`:452`, `:463`) and its result becomes `FamilyTallyV2.verdict` (`:822`). Of the mle record's five cited lines only `:831` (`_fmt_stratum_row`) is report text — **that part of the mle finding is REJECTED with evidence**, while its conclusion (a ruling is required) is accepted. Conversely `pooled` (`:645`) is NOT in `any_cell_dead`'s tuple and reaches only `FamilyTallyV2.pooled` (`:818`) and `_fmt_stratum_row` — **the pm record's parenthetical that `pooled` is reporting-only is CONFIRMED.** Changes made: (a) §6 is restructured into three parts — the provably inert part (drop the `:418-423` refusal; admit NO rows to `pooled` only) ships without a ruling; the `cell_dead`-bearing strata become **BLOCKER-3**; and a meantime behaviour keeps the unit running. (b) The recommended disposition is **strengthened and simplified**: re-deriving from source, `E[held_i] = q_i = BE_i` for YES and `E[held_i] = 1 − q_i = BE_i` for NO, so `k` vs `pi = mean(BE_i)` is already correct for a MIXED stratum — **side-partitioning is unnecessary as well as unregistered, and revision 3's own partition proposal is WITHDRAWN**, replaced by "admit unpartitioned" as the recommendation carried into BLOCKER-3. (c) §5 gains an exclusion on the §7 strata shape; §7 step 1 replaces the partition tests with mixed-stratum, withholding and anti-partition regression tests; AC #11 is rewritten to stop presupposing a ruling and AC #12 added; §9 gains three failure cases; §12 gains BLOCKER-3. |
| 2 | pm | MATERIAL (same finding, remedy option (b)) | Restrict D-A to the `pooled` stratum only, which "already clears the measured D-A failure" since the fatal `ValueError` is reached via `build_stratum_v2("pooled", ...)` first | **ACCEPTED as scoping, REJECTED on the factual premise, with evidence.** A `pooled`-only fix does NOT clear the failure: `_station_strata` (`family_tally_v2.py:653`, calling `build_stratum_v2` at `:498`) and `_ask_band_strata` (`:654`, calling it at `:511`) run over the same `non_excluded` rows immediately after `:645`, so the `ValueError` simply moves from `:645` to `:653` and the tally still cannot run. This is why §6's split item 3 (withhold the two `cell_dead` strata and the verdict, keep `n`, `pooled` and the report) is required and is not optional — it is the only disposition that both defers the ruling and lets the unit run unattended. Recorded in §6 as an explicit correction. |
| 3 | pm | MINOR | No AC asserts that the `cell_dead`-eligible strata's KILL-triggering behaviour is unchanged; the all-YES byte-identity floor never exercises it | **ACCEPTED.** AC #12 requires, on a NO-bearing corpus, that `station_strata == ()`, `ask_band_strata == ()`, no fabricated `cell_dead=False` reaches `look_verdict`/`terminal_look`, and the verdict is withheld — asserted by `test_a_no_bearing_corpus_withholds_the_cell_dead_strata_and_the_verdict` and `test_a_no_bearing_corpus_never_reports_cell_dead_false`. On an all-YES corpus the withholding branch never triggers, so the existing byte-identity floor still proves the registered path unchanged. |
| 4 | mle | (required change 2, carried) | Pin the exact D-B root cause via step 0 before writing its fix | **ALREADY SATISFIED, no change.** §7 step 3 is already conditional on step 0's finding and §8 AC #9 requires the evidence doc to name the established cause; the reviewer states "no change needed beyond what's there". |
| 5 | mle | verification note | RED-test oracle, all-YES byte-identity floor, `pi := mean(q_i)` rejection, D-B pre-narrowing, D-F alert wiring and the orphan guard all independently re-verified and hold | **NOTED, no change.** Carried unchanged into revision 4 except where the restructure above re-points a test. |
| 6 | both | scoring note | §11 (portfolio alignment) awarded 10/10 by both reviewers with no named defect, resolving the round-2 disposition #6 | **RESOLVED and awarded.** Round 2's open question is closed by both round-3 records explicitly; the revision-4 self-score raises this criterion to 10/10 rather than continuing to hold it at the lower mark. |

**Rejections:** two, both partial and both evidenced — the mle record's factual claim that `cell_dead` is non-gating (refuted at `:728`/`:753`/`:792` and `current_rung_hold_v2.py:461-465`), and the pm record's claim that a `pooled`-only fix clears D-A (refuted at `:653`/`:654`). Both reviewers' *conclusions* are accepted in full. **No scope was removed and no criterion softened:** AC #11 was narrowed only to stop asserting a ruling this plan may not make, and AC #12 imposes the strictly stronger requirement that a verdict be REFUSED rather than published on an unruled basis. BLOCKER-1, BLOCKER-2 and the new BLOCKER-3 are all left as blockers.

**Points withheld in round 3 without a named defect or requested change — round 4 must justify or award:**

- **mle, "Implementation specificity and feasibility" 11/15.** The record cites only "matches round 2" plus D-B's two hypotheses pending step 0 — which the same record elsewhere calls "acceptable given step 0 discriminates before code is written", i.e. not a defect. No other gap is named and no change is requested.
- **mle, "Acceptance criteria and validation quality" 14/20.** The record's own text is self-contradictory here ("docked 2 below round 2's 14→ wait, aligned to the new finding rather than round 2's unrelated defect, resulting in 14"). The only substantive reason given is AC #11 presupposing a ruling, which is now fixed; the record itself estimates ~16 "on the strength of the now-correct test oracle". Round 4 must either name a remaining AC gap or award to that level.
- **mle, "Autonomous operation" 13/15** and **pm, same 13/15.** Both cite only the shared dependency on the timer firing at all — a stated, honest limitation of any scheduled unit, named in §9 and §13 across three rounds, with no fixable gap identified and no change requested.
- **pm, "Fidelity" 16/20, "Technical correctness" 13/20, "Implementation specificity" 10/15, "Acceptance criteria" 15/20.** Every one of these deductions is attributed to the single MATERIAL finding, which is now remedied in full (dispositions #1–#3). Round 4 must re-score these against the revised text rather than carry the deduction.

**Revision 4 self-score (2026-09-21, author) — deliberately conservative, scored against the lower round-3 total (77):**

| Criterion | Max | Score | Named remaining weakness |
|---|---|---|---|
| Fidelity to the gap and completeness | 20 | 17 | G-04 fully covered plus D-D/D-E/D-F; the §7-frozen element is now surfaced as BLOCKER-3 with a recommended disposition rather than decided in-plan, and the tally still runs unattended while the ruling is open. Loses points because R-4 stays deferred to BLOCKER-2 and because the live family now has THREE open rulings gating parts of its measurement. |
| Technical correctness and evidence grounding | 20 | 17 | The load-bearing fact the two reviewers disputed is settled from source with line refs in both directions (`:655`/`:728`/`:753`/`:792`/`:822` vs `:645`/`:818`/`:830-835`), and the `E[held_i] = BE_i` identity is derived on both sides rather than asserted. Does not claim full marks: that identity is still a derivation from field semantics, not a registered formula, and it is the premise BLOCKER-3's recommendation rests on. |
| Implementation specificity and feasibility | 15 | 12 | The code change is now minimal and exactly located (remove `:418-423`; guard the two call sites; reuse the `:694-696` skip mechanism), and the withdrawn partition removes the invented `\|no` label convention that cost a point in revision 3. Loses points because the withholding branch requires widening the verdict literal and the renderer, which is new surface, and because D-B's root cause is still two hypotheses pending step 0. |
| Acceptance criteria and validation quality | 20 | 16 | AC #12 adds a negative control on the false-negative KILL direction and AC #11 no longer presupposes a ruling; the all-YES byte-identity floor is untouched. Loses points for AC #1's three-consecutive-day clock, AC #4's live half remaining an OPEN observation, and because no AC can exercise the post-ruling `cell_dead` behaviour until BLOCKER-3 is answered. |
| Autonomous operation, failure handling, recovery | 15 | 13 | The unit runs, exits 0, publishes `n` and alerts on both the failure edge (D-F) and the withheld verdict, so neither a crash nor a deferral is silent. Loses points because every signal still depends on the timer firing at all. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | §11's chain, numeric baseline and falsifier are concrete and concede zero direct ROI; both round-3 reviewers awarded 10/10 with no named defect, resolving the round-2 question. |

**Latest score:** 85/100 (Revision 4 self-score); round-3 peer readiness 77/100.
**Readiness: NOT READY — round 4 peer review pending. BLOCKER-1, BLOCKER-2 and BLOCKER-3 remain open and are not resolvable by any reviewer.**

### Round 4 (reconciled) (2026-09-21) — independent blind peer review, with scoring reconciliation

| Reviewer | Total |
|---|---|
| prediction-market-reviewer (portfolio accounting / risk) | 100/100 |
| mle-reviewer (statistical validation / measurement engineering) | 94/100 |

**Round-4 readiness is the LOWER of the two: 94/100.** Both records ran a reconciliation pass over
round 3's unnamed deductions: every withheld point was either tied to a named, text-fixable defect or
awarded back with its external cause recorded as a blocker.

**Dispositions (every defect and every note, both reviewers):**

| # | Reviewer | Severity | Defect | Disposition |
|---|---|---|---|---|
| 1 | mle | MINOR (−1 Technical correctness, −1 Implementation specificity, −1 Acceptance criteria) | §6's rejection of side-partitioning rests on the claim that a mixed-side `mean_ask` is "handled by labelling the rendered column" — but no AC, no §7 step and no named test specifies **what the label is, where it appears, or how it is verified**. A load-bearing justification with nothing behind it: an implementer could withdraw the partition correctly and never build the disclosure that made withdrawing it safe | **ACCEPTED in full; the only change of this revision.** Source read before specifying: `STRATUM_TABLE_HEADER` is the fixed string at `family_tally_v2.py:182-184`, `STRATUM_TABLE_DIVIDER` at `:185`, both rendered at `:1072-1073`; `_fmt_stratum_row` (`:830-835`) formats one row and already uses the trailing column for `"CELL-DEAD"`; rows render at `:1075` (`pooled`) and `:1077` (the two frozen strata); `StratumV2` (`current_rung_hold_v2.py:386-402`) carries no side field. Changes made: (a) §6 gains **D-A(ii)**, specifying the rendering concretely — a keyword-only `side_mix` argument to `_fmt_stratum_row` computed at the call site from the same row sequence the stratum was built from, three exact literals (`""` for all-YES, `" (NO-only)"`, `" (mixed-side: Y<n>/N<n>)"`) appended inside the `mean ask` cell, plus one price-domain footnote emitted exactly once whenever any annotation is present; `STRATUM_TABLE_HEADER`/`STRATUM_TABLE_DIVIDER` and `StratumV2` are deliberately **unchanged**, which is what keeps AC #5's byte-identity floor intact. (b) §7 step 1 gains four tests, three of which are exercisable **in this item** because `pooled` is exactly where this plan admits NO rows — the reviewer's suggested post-BLOCKER-3 exercise is therefore delivered *earlier* than requested, not deferred: `test_a_mixed_side_pooled_row_renders_the_side_mix_label_on_mean_ask`, `test_a_no_only_stratum_renders_the_no_only_label_on_mean_ask`, `test_an_all_yes_corpus_renders_no_side_mix_label_and_no_footnote`, plus `test_a_mixed_station_stratum_renders_the_side_mix_label` carried as a **strict** `xfail` naming BLOCKER-3 so the ruling cannot land without the label following it. (c) §8 gains **AC #13**. **No scope removed, no criterion softened:** this adds a disclosure only — no registered field, no `cell_dead` input, no change to `pi = mean(BE_i)`. |
| 2 | mle | BLOCKER-external, awarded | Fidelity (−3) and part of Technical correctness (−3) were withheld for BLOCKER-2/BLOCKER-3 being open and for `E[held_i] = BE_i` being "a derivation from field semantics, not a registered formula" | **NOTED, no change; correctly recorded as blockers rather than deductions.** The reviewer awarded both in full on re-examination: a ruling this plan may not make unilaterally is a BLOCKER, and no plan text can make a derivation "registered". BLOCKER-1, BLOCKER-2 and BLOCKER-3 stay open and stay blockers; the recommended BLOCKER-3 disposition (`pi = mean(BE_i)`, unpartitioned) remains **recommended, not adopted**. |
| 3 | mle | awarded on re-reading | Autonomous operation was held at 13/15 in round 3 with no defect actually named — the record's own text described what works rather than a gap | **NOTED, no change.** Awarded in full (15/15). The withheld-verdict WARN, the D-F failure alert and the orphan re-accumulation guard were each independently re-verified. |
| 4 | pm | none | No MATERIAL and no new defect. All three settled claims independently re-verified verbatim from source (`any_cell_dead` gating at `family_tally_v2.py:655`/`:728`/`:753`/`:792`; `pooled` inert at `:645`; a pooled-only fix does **not** clear D-A because `:653`/`:654` run `build_stratum_v2` over the same `non_excluded` rows), and `E[held_i] = BE_i` re-derived independently on both sides | **NOTED, no change.** The record additionally performed an unrequested check for downstream readers pattern-matching a closed three-value verdict union and found none outside `family_tally_v2.py`/`current_rung_hold_v2.py`/tests — recorded here as a positive verification that the `PENDING_STRATA_RULING` widening is safe, not as a licence to stop checking it at implementation time. |

**Rejections:** none this round. The single fixable defect is closed in the plan body (§6 D-A(ii), §7 step 1, AC #13), not in this table.

**Revision 5 self-score (2026-09-21, author) — deliberately conservative, scored against the lower round-4 total (94):**

| Criterion | Max | Score | Named remaining weakness |
|---|---|---|---|
| Fidelity to the gap and completeness | 20 | 18 | G-04 is covered end to end (D-A/A(ii)/B/C/D/E/F), the §7-frozen element is surfaced as BLOCKER-3 with a source-derived recommendation rather than decided in-plan, and the unit keeps running unattended while the ruling is open. Holds points back because the live family now carries THREE open rulings gating parts of its own measurement, and R-4 stays deferred to BLOCKER-2 — real incompleteness, even though no plan text can close it. |
| Technical correctness and evidence grounding | 20 | 18 | The disputed load-bearing fact is settled from source in both directions, `E[held_i] = BE_i` is derived rather than asserted, and the labelling claim is now grounded in the actual renderer (`:182-185`, `:830-835`, `:1072-1077`) read before specifying. Holds points back because that identity is still a derivation from field semantics rather than a registered formula, and it is the premise BLOCKER-3's recommendation rests on. |
| Implementation specificity and feasibility | 15 | 13 | The code change is minimal and exactly located (drop the `:418-423` refusal; admit NO rows to `pooled` only; reuse the `:694-696` `range(0)` skip; add a call-site-computed `side_mix` to the report renderer only). Holds points back because the withholding branch widens the verdict literal and the renderer gains new surface, and D-B's root cause is still two hypotheses pending step 0. |
| Acceptance criteria and validation quality | 20 | 18 | AC #13 plus three immediately-exercisable tests and one strict `xfail` make the labelling commitment a checked artefact; AC #12's false-negative negative control and AC #5's byte-identity floor are untouched. Holds points back because AC #1 needs three consecutive days of live running and AC #4's live half remains an OPEN observation on a corpus with no NO-leg fill yet. |
| Autonomous operation, failure handling, recovery | 15 | 14 | The unit exits 0, publishes `n` and `pooled`, refuses to publish a verdict on an unruled basis, and alerts on both the failure edge (D-F, CRITICAL) and the deferral (WARN); the orphan guard is standing. Holds a point back because every signal still depends on the timer firing at all. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | §11's chain, numeric baseline and falsifier are concrete and concede zero direct ROI; awarded 10/10 with no named defect by both reviewers in rounds 3 and 4. |

**Latest score:** 91/100 (Revision 5 self-score); round-4 peer readiness 94/100.
**Readiness: NOT READY — round 5 delta review pending. BLOCKER-1, BLOCKER-2 and BLOCKER-3 remain OPEN, are strategy-lead/PREREG rulings, and are not resolvable by any reviewer or by this plan.**

### Round 5 (delta) — `reviews/AUD-05-r5-mle-reviewer.md`, 98/100

| # | Reviewer | Severity | Defect | Disposition |
|---|---|---|---|---|
| 1 | mle | MINOR (−1 Implementation specificity, −1 Acceptance criteria) | D-A(ii)'s stated mechanism — `side_mix` "computed at the call site from the row sequence the stratum was built from" — is not implementable at the cited call sites `family_tally_v2.py:1075`/`:1077`, which sit inside `render_markdown_v2` and receive only the built `FamilyTallyV2`; the raw rows are locals of `build_family_tally_v2`. No alternative data-flow was named, and none of the four new tests drives `render_markdown_v2` end to end, so the plumbing gap was unspecified AND untested | **ACCEPTED in full; the only change of revision 6, and re-verified against source before writing.** Confirmed exactly as reported: `render_markdown_v2` def at `:1025` with signature `(tally: FamilyTallyV2, *, source_paths, as_of)`, containing both call sites (`:1075`, `:1077`); `FamilyTallyV2` field list at `:262-294` carries no rows and no side counts; `pooled_rows` is a local of `build_family_tally_v2` at `:644` (def `:567`), consumed into the `FamilyTallyV2(...)` return at `:809-827`; `StratumRow.side` documented at `current_rung_hold_v2.py:99-110`. Changes made: **(a)** §6 D-A(ii) withdraws the "computed at the call site" wording and names the real data-flow — `FamilyTallyV2` gains ONE defaulted carrier field `pooled_side_mix: str = ""`, computed inside `build_family_tally_v2` from `pooled_rows` while they are still in scope, with `strata_side_mix: tuple[str, ...] = ()` as the additive post-BLOCKER-3 extension; `_fmt_stratum_row` reads it via the renderer at `:1075`/`:1077`. **(b)** §6 states the effect on AC #5 explicitly: `FamilyTallyV2` is never serialised (its only consumer is `render_markdown_v2` via `main()` at `:1312-1325`), the guarantee is on rendered text, and the `""`/`()` defaults keep an all-YES corpus byte-identical while leaving every existing constructor and fixture valid. **(c)** §7 step 1 labels the three existing tests as isolated formatter tests and adds `test_the_side_mix_label_reaches_the_rendered_report_end_to_end` (rows → `build_family_tally_v2` → `render_markdown_v2` → asserted report text), RED today on the missing carrier field rather than only on the formatter argument. **(d)** AC #13 requires that end-to-end test GREEN. **No scope removed, no criterion softened, no statistic touched:** the added field is a label string read by nothing but the renderer. |
| 2 | mle | verification note | The three-literal rendering rule, the footnote text, the `xfail` carrying BLOCKER-3, and D-A(ii)'s labelling semantics were all independently re-checked and found sound and correctly scoped; the citations `:182-185`, `:830-835`, `:1075`, `:1077` and `current_rung_hold_v2.py:386-402` re-verified exact | **NOTED, no change.** Carried unchanged into revision 6. |
| 3 | mle | blockers | BLOCKER-1 (`trial_id_prefix` collision), BLOCKER-2 (`pm_us_crh_cont` retirement) and BLOCKER-3 (NO rows into the `cell_dead`-bearing strata) each re-affirmed as genuine and unchanged | **NOTED, no change.** All three stay OPEN as recorded in §12; revision 6 resolves none of them and alters none of their wording. The reviewer's note that BLOCKER-3's `xfail` "would also need the plumbing fix once exercised" is satisfied by the additive `strata_side_mix` extension named in §6 D-A(ii). |

**Rejections:** none this round. The single fixable defect is closed in the plan body (§6 D-A(ii), §7 step 1, AC #13), not in this table.

**Revision 6 self-score (2026-09-21, author) — scored against the round-5 peer total (98):**

| Criterion | Max | Score | Named remaining weakness |
|---|---|---|---|
| Fidelity to the gap and completeness | 20 | 20 | Unchanged by this revision; awarded 20/20 by the round-5 record with no named defect. |
| Technical correctness and evidence grounding | 20 | 20 | Unchanged; the round-5 record awarded full marks and this revision only adds source-verified plumbing (`:262-294`, `:567`, `:644`, `:809-827`, `:1025`, `:1075`, `:1077`, `:1312-1325`). |
| Implementation specificity and feasibility | 15 | 14 | The withheld point is now addressed: the data-flow is named, the carrier field located in the dataclass, and the post-BLOCKER-3 extension made additive. Holds a point back because the renderer still gains new surface and D-B's root cause is two hypotheses pending step 0 — unchanged causes, not the closed defect. |
| Acceptance criteria and validation quality | 20 | 19 | The withheld point is addressed by the end-to-end test now required by AC #13. Holds a point back because AC #1 still needs three consecutive days of live running and AC #4's live half remains an OPEN observation on a corpus with no NO-leg fill yet. |
| Autonomous operation, failure handling, recovery | 15 | 15 | Unchanged; awarded in full in rounds 4 and 5. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Unchanged; awarded 10/10 in rounds 3, 4 and 5 with no named defect. |

**Latest score:** 98/100 (Revision 6 self-score); round-5 peer readiness 98/100.
**Readiness: NOT READY — round 6 delta review pending. BLOCKER-1, BLOCKER-2 and BLOCKER-3 remain OPEN, are strategy-lead/PREREG rulings, and are not resolvable by any reviewer or by this plan.**

### Round 7 (2026-09-21) — ruling hand-down applied (no peer review this round)

Not a review round. `BLOCKER-1`, `BLOCKER-2`, `BLOCKER-3` and `PROGRESS` R-4 were ruled and
independently peer-ENDORSED outside this plan; this revision applies their **Consequences** to the
plan text surgically. No scope was removed, no criterion softened, no section renumbered.

| # | Source | Change applied |
|---|---|---|
| 1 | Tally-scope ruling §4, BLOCKER-1 | D-D's manifest re-issue is **ruled out** (§3, §5, §6): the tally-time barrier (`family_barrier.py:52-96` at `family_tally_v2.py:622`, after `:602`) already separates cont (terminal 2026-09-19) from v4 (d0 2026-09-20). Replaced one-for-one by **D-G**, a scorer-time `terminal_climate_day` bound at `score_live_trials.py:1789`/`:722` (zero `terminal_climate_day` matches in that file today) — the gap `score-live-trials-run.sh:77-94,181-187` turns into a double-write into `$STORE_DIR/$FAMILY_ID` for both families. RED tests + a standing barrier pin test (§7 step 6); AC #14. FUTURE re-registration: new family id, new prefix, n=0. |
| 2 | Tally-scope ruling §4, BLOCKER-2 | `pm_us_crh_cont` is **retired**. Added the read-only store pre-check reusing `read_scored_trials` (`scored_trial_store.py:118-134`, as used at `family_tally_v2.py:1288`) as §7 step 0(h); ruled both branches in §7 step 10 (clean → terminal run; contaminated → the expected `FamilyBarrierRefusal` plus the pre-check findings ARE the terminal evidentiary state, rows never deleted or rewritten); **timer disabled either way**, specified in §10 as a deployment step with verification and rollback and NOT performed here. AC #2 rewritten. |
| 3 | Tally-scope ruling §4, BLOCKER-3 | Option **(a)** — NO rows admitted to `station_strata`/`ask_band_strata` **unpartitioned at `pi = mean(BE_i)`**. §6 split item 2 rewritten from "blocked" to "ruled"; §6 split item 3's interim `PENDING_STRATA_RULING` is now time-boxed and retired by §7 step 9, which also converts the strict `xfail` on `test_a_mixed_station_stratum_renders_the_side_mix_label` to a plain test and exercises the reserved `strata_side_mix` carrier at `family_tally_v2.py:1076-1077`. AC #12 becomes the INTERIM criterion; new **AC #16** replaces it on landing. `test_no_stratum_label_carries_a_side_suffix` stands (partitioning is rejected by the ruling too). |
| 4 | Tally-scope ruling §4, R-4 | New named increment **INC-SP1I5** (§6 D-H, §7 step 11, AC #15) implementing `SP-1 I5` (`LIVE_FILL_SCORING_CHAIN_2026-09-05.md:236,311,313` stays the spec of record). The counter resolves the champion from the single source of truth — `BREEZY_SENDING_FAMILY_ID` at `breezy-trade-supervisor.service:115`, the `SENDING_FAMILY_ID_VAR` of `settings.py:112` mapped through `_validate_sending_family_manifest` (`:373-393`) — never a second literal, replacing `score-live-trials-run.sh:47`'s `pm_us_crh_v2.json`; fail-closed on absent/unregistered id (`:118-128`). The counter JSON already carries `manifest_sha256` (`structural_dead_stop.py:304,318,349,391`) for AUD-10's `C-KILL` (by id only) to verify scope. R-4's literal naming of `pm_us_crh_cont.json` is **superseded** — cont is retired. |
| 5 | `RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md` §4 | v4 may not SEND; node, capture, tally and KILL clock keep running. Recorded in §2, §5 (exclusion: no enablement/halt work here — AUD-02b owns the set-halt CLI, by id), §6 D-H (what "KILL" means for a family that cannot send: the clock still counts coverage and runs toward structural death, which is the intended reading, and is never a re-arm signal) and §11 (the ROI chain is **deferred, not demonstrated**; `n` may legitimately stay 0). |
| 6 | Both rulings | §4 and §12 updated: nothing in this item is ruling-blocked. §12 now lists only what genuinely remains — D-B's cause pending step 0, the store's contamination state pending step 0(h), AUD-02b's external unenforced-halt dependency, and the two acknowledged AC limitations. |

**Latest score:** unchanged from Revision 6 (98/100 self, 98/100 round-5 peer; round-6 peer records
scored the pre-ruling text). This revision adds ruled scope (D-G, D-H/INC-SP1I5, BLOCKER-3's
implementation, BLOCKER-2's sequence) that no reviewer has yet seen, so the prior totals do not
carry over to it.

**Readiness: NOT READY — the round-7 ruled scope is unreviewed. BLOCKER-1, BLOCKER-2, BLOCKER-3 and
R-4 are RULED and peer-ENDORSED (`docs/evidence/RULING_live_family_tally_scope_2026-09-21.md`) and
are no longer blockers; what remains is an unreviewed revision, an external dependency on AUD-02b's
enforcement of `RULING_A1`'s halt, and two measurements (step 0 / step 0(h)) that the plan itself
schedules.**

<!-- COORDINATOR FINAL STATUS — appended after review; everything above this line is the reviewed revision -->

## Coordinator final status (2026-09-22) — authoritative

This block supersedes any score or readiness wording in §13 above, which plan revisers wrote
before review closed.

- **Reviewed revision sha256** (file content above the marker line): `49695d5a1ce437165815070aa9a159baecb7c6a72fa9012f1e27fac9311b9d28`
- **Baseline self-score:** 79/100
- **Final score (lowest reviewer, never averaged):** 100/100
  - `mle-reviewer` round 8: 100/100 — `reviews/AUD-05-r8-mle-reviewer.md`
  - `prediction-market-reviewer` round 8: 100/100 — `reviews/AUD-05-r8-prediction-market-reviewer.md`
- **Readiness:** **READY**
- **Unresolved blockers / notes:**
  - None. BLOCKER-1/2/3 and R-4 are RULED and peer-ENDORSED (`docs/evidence/RULING_live_family_tally_scope_2026-09-21.md`). Disabling the retired family's timer is an implementation-time deployment step.
- **Full review history:** 16 records, `reviews/AUD-05-r*-*.md`
- Planning only. Nothing in this plan has been implemented.
