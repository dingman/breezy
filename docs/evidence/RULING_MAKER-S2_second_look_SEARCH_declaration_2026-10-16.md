# RULING_MAKER-S2_second_look_SEARCH_declaration_2026-10-16

Status: **FINAL** (2026-10-16; every precondition in §0 holds and is quoted there; immutable from this commit; any later change is a new dated ruling or a §3-style addendum). Decision owner per Pre-Auth; no operator cap involved.
Type: dated SEARCH declaration for the MAKER-S2 **second look** under `RULING_MAKER-S1_SEARCH_declaration_amendment_2026-10-13.md` §3 ("More days (S3 r3 :149 second look) need a new dated declaration with its own frozen set") and RA-13 B-3. Plan: `docs/plans/backlog/MAKER_2026-10-12/S2_second_look_plan_r3.md` + `S2_second_look_plan_r3_delta_coordinator.md` (READY 2026-10-16; 9 blind reviews) and this document's own blind review (prediction-market-reviewer + architect, 2026-10-16; both sets of edits applied).
Hash: `S2_SECOND_LOOK_DECLARATION_SHA256` = sha256 of this file's FINAL committed bytes, pinned in code by unit C1 (`src/breezy/analysis/maker_search_declarations.py`, registry row 1). The 10-12 declaration, the 10-13 amendment and both 10-15 addenda are not edited.
Sequencing (binding): Doc A FINAL → C1 pins its sha → **no census invocation under this sha (including the first `check`) runs until C1, C1b and C4 are all merged with the full gate EXIT=0 and `lint-imports` "N kept, 0 broken"**; C1 and C1b merge as one unit, or C1's row 1 refuses until the C1b guard is present; the first invocation is a C4 `check`; the commit shas are quoted on the first ledger line.

## 0. Preconditions for FINAL (all must hold; each is quoted here when met)
- [x] C6b (text-window cross-check producer, delta §1) merged on `feat/data-capture-and-risk` as commit `71ae58f1` with the full gate EXIT=0 and `lint-imports` "13 kept, 0 broken" — gate line: `[breezy] gate: phase1 rc=0 phase2 rc=0` / `EXIT=0` (unit `breezy-feat-full-gate`, 2026-10-16 12:08:22–13:36Z on HEAD `05e1434a`, which contains 71ae58f1; `27241 passed, 73 skipped, 5 deselected, 158 xfailed, 3 xpassed`; `Contracts: 13 kept, 0 broken.` at 10:07Z on the same tree). Pushed to origin as 59aa57a4..05e1434a.
- [x] Live positive-control fetch (2026-10-16 08:16Z, transient unit `breezy-s2b-positive-control`, EXIT=0): `window-text --city LAX --start 2026-10-01 --end 2026-10-03 --min-final-day 2026-10-03` into a scratch cache under `~/.cache`; stdout sealed 0400; the reader (`read_window_issuances` on the same URL-hashed path) returned 12 issuances, 0 refusals, climate days 09-30..10-03, 8 FINAL rows, max FINAL day 2026-10-03 (counts only were read; the window includes 10-01, a day sealed for forecast reads, read here only as CLI truth counts, outside any MAKER-S2 licence). U-3 is closed **for format and transport**; the 09-29..11-15 / limit 3000 request remains covered by R9 (retry; 3-day failure → peer ruling).
- [x] B6 RA-13-FW pre-check CLEAN on 2026-10-16 ≈08:10Z (Explore, read-only): no consumer has read quote-tape for climate days ≥ 2026-10-14 at LAX/MDW/MIA/SFO as a statistic (exit-window study max day 10-06; replay-daily skipped since 10-11, max 10-01; position monitor frozen pre-10-14; S1 census max 10-13). The decision-funnel digest on 10-14 holds refusal-reason counts (`NotDPlus1`, `outside_permit_window` — calendar/permit gates independent of quote values) read from the decision-log JSONL, not the catalog (`RA-13-FW_firewall_audit_2026-09-27.md:16`); RA-13 B-3 binds the quote-tape corpus (`RULING_RA-13…:90`) → CLEAN. **Repeated within 24 h before the FINAL commit and again at `close`; the FINAL-time result is quoted here:** 2026-10-16 10:08Z (Explore, read-only) **CLEAN** — exit-window study rows max 09-22 / missing_inputs max 10-06 (10-10..10-15 files identical, md5 834c9aab…); replay-daily max 09-30/10-01, SKIPPED 10-14 and 10-15 (no replay_daily_runner); position monitor v4 frozen at 1 position / 2565 frames / 555 mark-missing on 10-14 and 10-15, other families 0/0/0; decision funnel 10-15 (written 10-16 09:20Z) holds decision counts only, tallies from the node's own offer tape (`decision_funnel_daily_digest.py:84`), not Depth10 → CLEAN under `RA-13-FW_firewall_audit_2026-09-27.md:16`; older studies ≤ 09-30; S1 census max 10-13 (provenance [08-30, 10-13], EXIT=0); files new since 08:00Z are host-health verdicts, phl/nyc listing sightings and housekeeping; score-live-trials 10-14/10-15 `.skipped` (no scorer); aud07 drain exited 1 on lock wait; hypothesis-triage log empty; nbp-learning-nightly reads no tape.
- [x] U-8 timing: wall time of one single-day census, from a licensed re-read of 2026-10-12 under the 10-12 declaration sha as a transient unit (stdout sealed 0400, never read; wall time taken from the unit's `ExecMainStartTimestamp`/`ExecMainExitTimestamp`): `1566 s` (unit `breezy-u8-census-timing`, 2026-10-16 13:37:12Z start, `--from 2026-10-12 --to 2026-10-12 --search-declaration RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md`, output under `~/.cache/breezy-u8-census-timing/20261016T133712Z`, stdout sealed 0400 and never read). Fraction of c−2 days whose holding instance was not yet rotated at 10:05Z, measured **stat-only** (instance directory mtimes and the rotation journal; no feather byte read) over climate days ≤ 2026-10-13: **0 of 104 station-days (0 %)** (26 days × 4 stations, 2026-09-18..10-13; rotate timer 09:00Z daily, an instance started on day S holds {S, S+1}; journal Stopped times used, mtimes give the same 0 %; measured 2026-10-16 ≈09:46Z). No census, catalog or tape read of any day ≥ 2026-10-14 occurs before FINAL.
- [x] Doc B DRAFT (exactly the §12 template) committed in the same commit as Doc A FINAL.
- [x] Peer review of this document converged (prediction-market-reviewer + architect, blind), including acceptance of the §5 narrowing.

## 1. Basis
- Amendment :71 "A second verdict scoring pass on this set is forbidden"; :76 "A result-driven re-run is forbidden"; :77 "More days … need a new dated declaration with its own frozen set".
- `S3_loss_floor_reachability_plan_r3.md:149` (second look once the census adds ≥ n0 more climate dates; n0 = 12).
- Spec `docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md:222-224` (effective n ≥ 30, else UNDERPOWERED-WAIT).
- RA-13 B-3 (`RULING_RA-13_programme_kill_2026-09-27.md:90`): any post-freeze count, outcome-blind or not, spends the days; the firewall binds the quote-tape corpus.
- The first look: `docs/evidence/maker/STAGE0_REPLAY_2026-10-16.md` — run `s2v-20261016T020707Z`, label UNDERPOWERED-WAIT, n_sd 44 bid-bearing station-days on 12 dates, `n_eff_gov` 18.73 < 30.
- **Orphan day.** 2026-10-13 was declared under SEARCH 1 (10-12 :28), lacked FINAL at run 1 and was "never added" (amendment :20); it belongs to neither block and is never recovered. S = 2026-10-14 is the conservative reading of the amendment ceiling (:21).
- **Cross-check independence verdict: parsing-only.** The pinned truth CSV (`scripts/archive/iem_cli_fetch.py fetch` → `dataset`, `breezy-truth-fetch.service`, `breezy-truth-dataset.service`) and the block-2 cross-check (IEM AFOS CLI text windows fetched by `iem_cli_fetch.py window-text` and parsed by `settlement_truth_dataset.py --include-maker-s2b-window`) are both IEM AFOS CLI products. The agreement check verifies parsing, not the source; a shared upstream revision error is invisible to it. The cross-check never validates truth. Corroboration (disclosed, never an exit failure): fq-truth revision markers record a catalog cross-check (`deploy/systemd/README.md:1971-1973`).

## 2. Declaration
- Stations: LAX, MDW, MIA, SFO. Never NYC.
- Days: 2026-10-14 .. 2026-11-15 (ceiling). The realised range is [S, E] (§4) and registry row 1 is narrowed to it after the evidence commit (§5).
- Covers: the counts-only trigger census invocations (§4), the single full Stage A over [S, E], and the MAKER-S2 reads licensed by Doc B (`RULING_MAKER-S2_second_look_licence_2026-10-16.md`). Never S5.
- Reads under this declaration carry the sha of this file; the census firewall (`require_firewall_clearance`) clears a block-2 day only against registry row 1.

## 3. Pooling ruling
Block 2 is disjoint from block 1 and receives its own standalone V0 (`n_sd`, `n0`, `n_eff_gov` on block-2 rows only). The union would re-score block 1 (:71); a pooled statistic would count seen outcomes toward n (L-56). Block-1 numbers may be cited descriptively; they never enter any n, rate or confidence interval. No pooled table is produced, even report-only.

## 4. Trigger rule (outcome-blind; fixed here before any read)
- **Counted station-day:** census `reason == "COVERED"` **and** `maker_stage0_rule.listed_in_time(first_seen_ns, day)` (listed by D-1 12:00Z inclusive; `None` → not listed). COVERED (`src/breezy/analysis/maker_tape_census.py:590 classify`) depends on capture spans, coverage and print-parse success (TRADE_PARSE_FAILURE); never on any print count, price, size, fill or outcome value. Counts-only mode still parses in-scope prints, so every invoked station-day is a read for §5.
- **Proxy:** `n_eff_proxy([S, d]) = Σ_date m_date / (1 + (m_date − 1) · RHO_ASSUMED)`, `RHO_ASSUMED` = 0.5 imported from `breezy.analysis.maker_tape_census`, computed by `n_eff_gov` (`maker_stage0_inputs.py`) over counted rows; the rule lives in the pure module `scripts/analysis/maker_stage0_trigger_rule.py` (`first_crossing`, `TRIGGER_THRESHOLD`), imported by both the trigger tool and the C2 pre-claim check.
- **Threshold T = 34** (n_eff units). Derivation from block 1 (posting facts only, no fill): 88 COVERED rows; `listing_abstain` true on 44 (40 COVERED + 4 LOW_COVERAGE); COVERED ∧ listed-in-time = 48 = 12 dates × 4 → proxy 19.20; realised `n_eff_gov` 18.73 (four posted-but-not-bid-bearing station-days: LAX 10-03, SFO 10-03, SFO 10-04, LAX 10-08) → shrink 0.976 → bare requirement 30.7. T = 34 adds a deliberate margin (≈ 2 dates) pinned here. **Unmodelled risk:** listing before D-1 12:00Z began only on 2026-09-30 in block 1 and may not persist (R1).
- **E** = the first day d ≥ S at which `n_eff_proxy([S, d]) ≥ 34`, evaluated over the pinned trigger rows in date order. **Cap:** if no crossing occurs through 2026-11-15, the last `check` covers 11-15 (run on 11-17), `close` writes E = 2026-11-15 with `crossed: false`, `first_crossing` returns the cap and C2 recomputes it identically (`test_close_at_cap_without_crossing`); the full Stage A and the verdict then proceed over [S, 11-15] and V0 decides the label.
- **Mechanics (unit C4, `scripts/analysis/maker_stage0_trigger.py`):** `check` runs daily at 10:05Z (after the 09:00Z rotation; ingest-frequent overlap accepted: ingest is idempotent per file, LIVE instances are read as `live_unread`, days ≤ c−2 are rotated) under the studies lock, in **counts-only** census mode (`--counts-only`: writes only `station, climate_day, reason, first_seen_ns` to a file sealed 0400 and read only by the trigger tool up to E; no summary, no prints file, exit 0 regardless of S-5), batching all not-yet-checked days ≤ c−2 in one invocation; appends rows in date order; at the first crossing writes a terminal `CROSSED` row, discards later rows unread, and refuses every later `check`. `close` hashes only rows ≤ E, writes `trigger_close.json` (E, rows sha, chain hash, `crossed`), re-verifies the forfeiture line against the read-ledger, repeats the B6 pre-check, and copies the rows into the repo (`trigger_rows_path` in Doc B).
- **Pre-claim verification (unit C2):** before the ledger claim the driver hashes the trigger rows, the census-days file and the cross-check against the Doc B fence, recomputes E from the pinned rows with `first_crossing` and refuses on any mismatch; `last_final_day ≥ E` is a hard STOP for Doc B FINAL.
- **Single look.** S-1 and S-5 bind **only** on the single full Stage A over [S, E], which the census refuses until `close` has written E and refuses a second time without a dated addendum. Every other census output is counts-only; any other stdout is sealed (0400) and never read.
- **Fail-closed direction.** A station-day ≤ E that the trigger rows **count** (COVERED ∧ listed-in-time) but the final Stage A does not class COVERED refuses Doc B FINAL. The reverse direction (not counted at check time, e.g. `live_unread`/AMBIGUOUS_NO_CLEAN_INSTANCE, but COVERED in the final Stage A) is disclosed and never moves E (deliberately narrower than delta 2.15, which was symmetric: E cannot move in the reverse direction and n can only grow). A counted day whose `first_seen_ns` fails `listed_in_time` in the final run is disclosed. Enforced pre-claim by C2 (`test_v2_counted_day_not_covered_in_final_census_refused_before_claim`) and by the §6 step-5 self-check.
- **Ends of the block (named next actions; L-3).** On the final Stage A, the S-1 STOP (`n_eff_ub < 30`), any S-5 pre-screen STOP, and a counted-but-not-COVERED disagreement each end the block: no Doc B FINAL, no verdict claim, next action = dated peer ruling. E and S are never recomputed, extended or re-triggered under this declaration; more days need a new dated declaration (amendment :77).

## 5. SEARCH cost (RA-13 B-3)
- Every census invocation under this sha is ledgered **before** any tape is touched (`~/.local/share/breezy/derived/maker_stage0/search_read_ledger.jsonl`: `sha, mode, from, to, rows_chain_sha256` (chain over previously committed rows), `ts`; a post-read line commits the current rows). C1b's default `read_ledger` path equals this path (pinned by test). Refused when `to > today − 2` or when no read-ledger is supplied. An invocation that fails or is killed after its pre-read line counts over its full [from, to] and is disclosed; a firewall-refused invocation never counts.
- **Realised forfeiture** = 4 × (max day in any invocation under this sha − S + 1). Unlike 10-12 §2 (whole scope forfeited at the first run), forfeiture here accrues by read; days in (max-invoked, 11-15] are not forfeited and not licensed after the narrowing. Ceiling = 4 × 33 = 132 station-days.
- **Overshoot.** Reads in (E, max-invoked] occur only inside the crossing invocation (a catch-up batch after missed checks) and are bounded by that invocation's `to` (≤ today − 2); a normal daily batch ends at E with zero overshoot. They are counted in the realised forfeiture and disclosed. **A violation** is (a) any read of a day > E by an invocation other than the crossing invocation, or (b) any invocation under this sha that §4/§5 do not permit (a counts-only invocation outside a C4 `check`, a full Stage A other than the single one over [S, E], or a second full Stage A without a dated addendum). Violations are reported on the closing ledger line.
- **Code refusals.** C1b refuses any invocation under this sha whose `to` > E once `trigger_close` exists, in every mode (`test_census_refuses_any_mode_past_close_e`); before `close`, counts-only invocations are permitted only through the C4 `check` (trigger lock held) and any other invocation is refused (`test_counts_only_outside_trigger_check_refused`); the crosscheck library path refuses registry rows ≥ 1 (D4). Exposure window from `close` to the narrowing commit: only ad-hoc Python remains.
- EDGE-4 date effect (10-12 :61-64 arithmetic) is reported at the ceiling (upper bound) and at the realised figure.
- After the evidence commit, registry row 1 is narrowed to [S, E] (tightening; edits the two ceiling tests in the same commit). The narrowing is accepted as part of the §0 peer check.
- RA-13 backstop 2027-01-25 is firm (`RULING_RA-13…:97`). The closing ledger line embeds the read-ledger sha256, `trigger_close.json` sha256, the B6 re-check result, the realised range, and (if used) the bench exception's pre/post `CODE_SHA` and bench numbers; it is the authoritative `CODE_SHA` record.

## 6. NBP holdout and AUT-4
Block days are forward data (holdout ruling 2026-10-03 :9-11). MAKER-S2 NBP-vs-outcome statistics on [S, E] are disclosed contamination for AUT-4 forward windows, extending amendment :66 to the new range. The pre-block tail table (07-01..09-17, §10) is already disclosed under clause 3. Nothing calls `open_holdout`; no α is spent; no refit.

## 7. S5 consequence
Block-2 days are Stage 0 dev days (seen). S5 `holdout_start_date` ≥ (max census-invoked day under this sha) + 2, tied to the read-ledger by a test (tightens `S5_shadow_run_and_gates_plan_r3.md:218`).

## 8. Outcome statement, disposition and hard constraints
- Exploratory; GO is never an outcome (spec :224). Block-2 labels map to the S2 run procedure Step 8 dispositions. A second UNDERPOWERED-WAIT goes to a dated peer ruling; there is no automatic third block.
- Passing V0 does not secure §6.9 power (`MIN_EXPECTED_LOSSES` 10; run 1 needed 469 pooled fills); NOT-KILLED-UNSCREENED is admissible (S3 allowlist; S5 G9 re-screens).
- **Pre-registered expectation:** the pre-block tail table (07-01..09-17) showed a 2.5× YES excess (137 observed vs 54.4 expected at p_yes < 0.06) against the frozen Test A margin 1.5 (`maker_stage0_stats.py AS_MARGIN`); a Test A FAIL → `NO-GO (adverse selection)` is therefore the likely block-2 outcome. That path stands; the margin is not changed.
- **CODE_SHA freeze:** verify-first, the benches and the verdict run execute at one recorded `CODE_SHA`; between Doc B FINAL and the evidence commit no freeze-scope module changes except the single pre-declared exception below. `CODE_SHA` is recorded in the run manifest and the closing ledger line, never in Doc B.
- **Pre-declared bench exception:** if a block-2 bench projects PROJ > 21,600 s, exactly one C7 merge (instance pre-filter; touches only `probe.py` and its split module, asserted by test) is permitted before the claim, followed by the full gate and a re-bench; `CODE_SHA` is re-recorded on the ledger line with pre/post shas and bench numbers. If the re-bench still exceeds 21,600 s: STOP → dated peer ruling.
- Truth timer stuck ≥ 3 days with no advance of `last_final_day`, or the cross-check fetch failing for 3 days: STOP → dated peer ruling.
- **Hard constraints:** nothing under this declaration enables, arms or changes live trading, the A1 halt, the permit, the NO-SEND firewall or either operator cap; `allow_short` stays False; Nautilus is untouched; no outcome under it is a live-enablement input.

## 9. Trade unit reused
`trade_quantity_unit.json` sha `6459e9f6384af85af69efca1f70f7a8e8155e343fc18551d85c94d1d9afd4835`, verdict CONTRACTS, is reused as is. Stage B and WP3 are not re-run (their licensed fills are the 28 pinned rows ≤ 2026-10-06, 10-12 §6). Any own fill on a block-2 day would be unlicensed: reported, never read.

## 10. Tail disclosure
The pre-block tail table (`tail_reliability.csv`, 07-01..09-17, sha `6749a92133e54a89bd3c21c1ffb079ea335704eb9ccbba30978d5bd16f2be35d`; first-look evidence §5a) is passed to the block-2 verdict run via `--tail-csv`, so the `TAIL-MISCALIBRATED` annotation (label-neutral by test) is emitted and pinned. Routed as disclosure only: this document, S5 PREREG `holdout_freeze_disclosure` (model-risk note), AUT-4 contamination note. Never to FQ-v2 triggers, NBP fits or any margin.

## 11. Ledger lines
One line in `docs/evidence/RA-13-FW_firewall_audit_2026-09-27.md` (an evidence ledger) at FINAL and one at `close`; a **new dated section appended** to `docs/evidence/RULING_H-ARCHIVE-RECAL-2026-09_horizon_2026-09-25.md` at FINAL (pattern 10-12 :130-134; existing sections are never edited) and a second dated section at `close`.

## 12. Doc B template (verbatim; Doc B may differ only in the filled fields and the Status line; C2's v2 field set equals exactly the 13 keys of this fence — `test_v2_field_set_equals_doc_a_template`)

````
# RULING_MAKER-S2_second_look_licence_<date>
Status: DRAFT | FINAL. Licence under RULING_MAKER-S2_second_look_SEARCH_declaration_<date> (sha <FILL Doc A sha256>).
## 1. Licensed reads (exhaustive)
1. One verdict scoring pass over block days: NBP 13Z/19Z D−1 and 01Z D; tape incl. Depth10 and DepthTruncation; the pinned truth CSV and the pinned cross-check.
2. --bench 4 and 8 on block days.
3. Verify-first on 2026-06-30 at CODE_SHA.
4. WP0 direction check and SFO positive control on block days.
5. --tail-csv ~/.local/share/breezy/derived/maker_stage0/tail/tail-20261016T062622Z/tail_reliability.csv (sha 6749a92133e54a89bd3c21c1ffb079ea335704eb9ccbba30978d5bd16f2be35d; fallback: the committed sidecar copy, same sha) — annotation only; no new NBP read.
--tail-only is not licensed (refused for a v2 block).
## 2. Frozen set
```FROZEN_DATE_SET_V2
stations: LAX MDW MIA SFO
block_first_day: 2026-10-14
trigger_day: <FILL>
trigger_rows_path: <FILL repo-relative>
trigger_rows_sha256: <FILL>
census_days_path: <FILL>
census_days_sha256: <FILL>
truth_csv_path: <FILL>
truth_csv_sha256: <FILL>
cross_check_path: <FILL>
cross_check_sha256: <FILL>
last_final_day: <FILL ≥ trigger_day>
dates:
<FILL: block_first_day .. min(trigger_day, last_final_day, 2026-11-15)>
```
## 3. Re-run rule
The text of amendment §3 (:71-77) is copied here verbatim; the addendum name is RULING_MAKER-S2_second_look_addendum_<date>.md. Residual post-claim voids (all non-result): S-2 direction, S-7 Δ bound, S-5 RSS abort, RTMAX/OOM/host kill, unexpected exceptions.
## 4. Provenance
The §0 precondition quotes of Doc A, the read-ledger sha256, trigger_close.json sha256, the sealed-stdout paths. CODE_SHA is recorded in the run manifest and the closing ledger line, not here.
````
