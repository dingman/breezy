# RULING_MAKER-S1_SEARCH_declaration_amendment_2026-10-13

Status: **DRAFT rev 2** (coordinator ruling). It becomes FINAL only on the commit that fills the `FROZEN_DATE_SET` block. Immutable once FINAL; any change is a new dated ruling or a §3 addendum.
Date: 2026-10-13. Type: dated amendment to `docs/evidence/RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md` (6068a00e), under RA-13 B-3. Decision owner per Pre-Auth; no operator cap involved.
Naming: "MAKER-S2" = the maker Stage 0 replay (`docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r3.md` + r4 delta). "NBP S2" = the calibration study named in holdout clause 3. They are different studies.
Hash: `S2_NBP_LICENCE_SHA256` = sha256 of this file's **FINAL** committed bytes, never the DRAFT. MAKER-S2 pins it in `pins.json` (r4 delta (b), E5). The 10-12 file is not edited, and S1's `SEARCH_DECLARATION_SHA256` (`src/breezy/analysis/maker_tape_census.py:76-78`) is unaffected.

## 1. Amendment: licensed reads (exhaustive; any read not listed is unlicensed)
The 10-12 declaration's "Not licensed: … any forecast-store read" (:32) and "permits no forecast-store read" (:40) are amended for MAKER-S2 only. Stations are LAX, MDW, MIA and SFO; never NYC.
1. **Verdict scoring pass (exactly one).** Reads the NBP derived store `~/.local/share/breezy/derived/nbp/` (+ `_manifest.json`), cycles 13Z D−1, 19Z D−1 and 01Z D. It also reads the tape, including Depth10 (`order_book_depths`) and `DepthTruncation`, the pinned truth CSV and its cross-check parquet (same days). Frozen set only.
2. **Bench (`--bench`).** Reads 1 on 4, then 8, frozen-set station-days chosen as the heaviest by catalog bytes. Timing and RSS only.
3. **WP2 verify-first (S-6).** One 01Z/13Z/19Z cycle per station for climate day **2026-06-30** (fit slice, outside the holdout) and that day's CLI FINAL. Alignment and vintage-age lines only.
4. **WP0 direction check and SFO positive control.** Tape prints and Depth10 on frozen-set days; agreement statistics only. WP0 step 2 (global first print instant) reads print timestamps only and is already licensed at :31.
5. **`--tail-only` tail-reliability table (report-only, diagnostic).** NBP and CLI truth for 2026-07-01..2026-09-17, licensed by name as descriptive under holdout clause 3. It may set only the `TAIL-MISCALIBRATED` annotation, never the label.

There is one scoring pass. The report-only overlay and the +60 min and poll-lag stress variants are computed inside that same verdict invocation (one ledger entry), read the same data as item 1, write only their named sidecars, and set no label. Bench, verify-first, the WP0 control and tail-only read without producing fill-rate, episode or label output; tail-only produces only its reliability table.

**Frozen replay date set (mechanical rule, applied once after the S1 run and before P2).**
- The range is the first replayable day (MAKER-S2 WP0 step 2: 2026-09-18, or 09-19 if the first print is after 09-17 16:50Z) .. min(2026-10-13, last day with a FINAL row in the truth CSV pinned below). 2026-10-01 and NYC are excluded.
- A day lacking FINAL at run time is excluded from §6.9 and counted, never added.
- The driver fails closed on: an unfilled placeholder; a date outside the rule; 2026-10-01; a date > 2026-10-13; an NYC row.

```FROZEN_DATE_SET
stations: LAX MDW MIA SFO
first_replayable_day: <FILL>
truth_csv_path: <FILL>
truth_csv_sha256: <FILL>
last_final_day: <FILL>
dates: <FILL: ISO dates, ascending, one per line; 2026-10-01 absent>
```

## 2. Why this complies with RA-13 B-3 (`RULING_RA-13_programme_kill_2026-09-27.md:89-92`)
- **No new forfeiture.** B-3 binds the corpus. Every set day is PRE_FREEZE (≤ 09-25) or SEARCH_DECLARED (09-26..10-13, forfeited at 6068a00e, cost 72). Excluding 10-01 removes a read, not a forfeiture, so the cost stays 72. The ceiling is 25 dates / 100 station-days.
- **Exploratory only** (spec v0.3 §6.0 :211, :225; declaration §5).
  - No MAKER-S2 number or label drives an NBP fit, recalibration or promotion decision.
  - None feeds a CONFIRM leg, a GO, or an FQ-v2 NO-TRADE re-open trigger.
- **Pre-declared and outcome-blind.** The set is fixed by the §1 rule before any fill number exists.
- **One scoring pass on a committed sha, enforced by the §3 ledger.**
- **NBP holdout** (`RULING_holdout_freeze_and_forward_window_2026-10-03.md`; frozen [2026-07-01, 2026-10-02), clause 1):
  - Days in [07-01, 10-01) (the tail table 07-01..09-17 and set days 09-18..09-30) are read under clause 3's contamination disclosure as descriptive evidence only.
  - **2026-10-01** is inside the frozen holdout and outside clause 3's disclosed window. It is sealed: excluded from every read here.
  - Disclosure (clause 2; `docs/plans/backlog/AUTONOMY_2026-10-03/AUT-4-evaluation_plan_r10.md:574`): "MAKER-S2 NBP-vs-outcome statistics on 2026-10-02..10-13 are disclosed contamination for AUT-4 forward windows anchored (proposed) at 2026-10-02 by AUT-4 r10 :574; clause 2 makes days on or after 2026-10-02 forward data; AUT-4 treats them as descriptive, never confirmation."
  - MAKER-S2 fits nothing and never calls `open_holdout` (`nbp_calibration.py:353`). No α is spent.

## 3. Still forbidden; re-run rule
- **Forbidden:** any refit or recalibration on these rows; any day > 2026-10-13; 2026-10-01; any other station; any other consumer, including S5 (which needs its own declaration).
- **A second verdict scoring pass on this set is forbidden.**
  - Mechanism: `~/.local/share/breezy/derived/maker_stage0/verdict_ledger.jsonl` (path in `pins.json`), keyed by this file's sha. An entry is appended at verdict-run start, before any scoring. The driver refuses when an entry exists.
- **Exception: a run void for a non-result reason** (S-5, S-6, S-7, E4 disk, OOM, crash, host kill).
  - Such a run may be re-run only via a dated addendum `RULING_MAKER-S1_SEARCH_amendment_addendum_<date>.md`.
  - The addendum names the voided `run_id`, the cause, and the old and new `code_sha`, and attests that no fill, rate or label output of the void run was read. The driver accepts its sha only if the named `run_id` directory is `.void`-renamed and contains none of `scored_episodes.csv`, `s3_inputs.json`, `verdict.*`. The same addendum form may name a substitute verify-first day (on or before 2026-06-30, by date, before run-time step 5).
  - A result-driven re-run is forbidden.
- **More days** (S3 r3 :149 second look) need a new dated declaration with its own frozen set.
- **MAKER-S2 numbers gate nothing** except S3's `s3_inputs.json` inputs and the MAKER-S2 label.

## 4. Provenance
- Plan: `S2_stage0_replay_plan_r3.md` + `S2_stage0_replay_plan_r4_delta.md` rev 2 (b), (c).
- Reviews: `reviews/S2-r3-pmr-verification.md` F-4/E-2; `reviews/S2-r4-pmr-verification.md` H-2, H-3, M-4, M-6; `reviews/S2-r4-mle-verification.md` M3, M5.
- Spec v0.3 §6.0 :196-230; declaration 2026-10-12 §2–§5; RA-13 B-3; holdout ruling clauses 1–3; AUT-4 r10 :574.
- Ledger: the FINAL commit adds one line to `docs/evidence/RA-13-FW_firewall_audit_2026-09-27.md`: "MAKER-S1 amendment 2026-10-13: MAKER-S2 NBP read licensed (five named reads); 2026-10-01 excluded; forfeiture unchanged at 72; AUT-4 forward windows: 2026-10-02..10-13 MAKER-S2 NBP-vs-outcome statistics disclosed as descriptive contamination".
- Final-round verification: `reviews/S2-r4-pmr-final.md` (compliant with RA-13 B-3 once E-A/E-D/E-E/E-F land; applied here, DRAFT rev 2 + final edits).
