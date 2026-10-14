# S2 run procedure: MAKER-S2 Stage 0 replay (earliest after S1 Stage B, 2026-10-14)

Status: READY-TO-RUN once S1 Stages A and B have both exited with a readable EXIT line. This procedure was checked against the build merged at 520b233c (HEAD 620b44f9).
Plan: `S2_stage0_replay_plan_r3.md` (§2 E1–E4 / S-1..S-6, WP6 run plan :199-204) + `S2_stage0_replay_plan_r4_delta.md` ((b), (c), (i)3, (i)8–9, (k) steps 1–10, (q), (r)). Licence: `docs/evidence/RULING_MAKER-S1_SEARCH_declaration_amendment_2026-10-13.md` (§1 reads, §3 ledger, §4 RA-13-FW line).
Operator-free. No operator cap is involved. All runs use `systemd-run --user`. Read EXIT lines; never infer an outcome.

## Shell constants (set once per shell)
```
R=/home/jon/breezy; PY=$R/.venv/bin/python; D=$HOME/.local/share/breezy/derived
S1=$D/maker/s1; M0=$D/maker_stage0; LOGD=$D/maker_stage0_logs; IN=$D/maker_stage0_inputs
AMEND=docs/evidence/RULING_MAKER-S1_SEARCH_declaration_amendment_2026-10-13.md
CAT=$HOME/.local/share/breezy/catalog/quote_tape/polymarket_us; NODELOGS=$HOME/.local/share/breezy/logs
mkdir -p $LOGD $IN $M0/{bench,verify_first,tail} $HOME/.cache/breezy/maker_s2
```
- `$M0` is the ledger's `runs_root` (the parent of every verdict `--out-dir`).
- Logs never go inside an `--out-dir`. The driver refuses an existing run dir, and `~` is not expanded inside `bash -c "…"`, so use `$HOME`.
- The ledger `$M0/verdict_ledger.jsonl` is derived by the CLI. It is never a flag.

## Entry criteria (check all of them and quote them in the Step 10 evidence)
- **S1 Stage A** (`$S1/census_run.log`): `EXIT=0` or `EXIT=4`. There must be no `S-1` STOP line and no S-5 `NO-GO pre-screen` line (S1 procedure STOPs). Either line means STOP: S2 does not run.
- **S1 Stage B** (`$S1/tqu_run.log`): `EXIT=0` or `EXIT=4`. In `$S1/trade_quantity_unit.json`, `verdict` must be one of `CONTRACTS`, `USD_NOTIONAL_YES`, `USD_NOTIONAL_TAKER` or `BRACKETED_USD`, and `s2_stop` must not be true. `UNRESOLVED` means S-3 STOP. If S1 Stage C flips `TRADE_QUANTITY_UNIT` (its WP3), that merge must land before Step 3. It is a code change.
- **Host:**
  - `df -B1 --output=avail $HOME` ≥ 10 GiB (E4; re-check before Steps 4, 5, 7 and 8).
  - `free -g` available ≥ 6.
  - `systemctl --user list-units --state=active | grep -E 'study|census|scorer|replay|gate|backfill'` is empty.
  - `flock -n $XDG_RUNTIME_DIR/breezy-studies.lock true` succeeds.
  - `systemctl --user is-active breezy-quote-tape` = active.
- **Tree:** `git -C $R rev-parse --abbrev-ref HEAD` = `feat/data-capture-and-risk`, at or after the S2 merge 520b233c. `git -C $R status --porcelain -- scripts/analysis src tests pyproject.toml uv.lock` is empty.
- **Clock:** no unit may start inside, or run into, 15:10–16:10Z (nightly studies) or 02:05Z. P2 additionally avoids 16:30–17:10Z, because the backfill stops with `paused_launch_window`. Rule: unit start + its `RuntimeMaxSec` must end before the next blocked window.

## Step 1: Read the S1 values (no compute)
- From `census_run.log`, quote verbatim:
  - `N_cov D_cov n_eff_ub C`;
  - the `INFO bidlive:` line;
  - every `STOP` line.
- From `trade_quantity_unit.json`, quote `verdict` and `surviving`.
- If `n_eff_ub` < 30, the run still proceeds. V0 (`UNDERPOWERED-WAIT`) is the expected outcome. Record that expectation now, before any number exists.

## Step 2: First print instant (WP0 step 2; amendment §1 item 4, timestamps only)
Write the probe script once:
```
cat > $HOME/.cache/breezy/maker_s2/first_print.py <<'EOF'
import datetime as dt, sys
from pathlib import Path
from scripts.analysis.maker_stage0_probe import first_print_instant
from scripts.analysis.maker_stage0_probe_core import first_replayable_day
days = [dt.date.fromisoformat(s) for s in sys.argv[1].split(",")]
ns = first_print_instant(Path(sys.argv[2]), days, work_root=Path(sys.argv[3]))
print(f"FIRST_PRINT_NS={ns}")
print(f"FIRST_REPLAYABLE_DAY={None if ns is None else first_replayable_day(ns)}")
EOF
```
Set the candidate days (2026-09-18..2026-10-13, minus 2026-10-01) and run:
```
DAYS=$($PY -c 'import datetime as d;a=d.date(2026,9,18);print(",".join(str(a+d.timedelta(i)) for i in range(26) if a+d.timedelta(i)!=d.date(2026,10,1)))')
systemd-run --user --unit=breezy-maker-s2-fp --collect --slice=breezy-studies.slice \\
  -p MemoryMax=4G -p RuntimeMaxSec=3600 -p LimitNOFILE=524288 --working-directory=$R \\
  --setenv=PYTHONPATH=$R/src:$R /bin/bash -c "flock -w 600 \\$XDG_RUNTIME_DIR/breezy-studies.lock \\
  $PY $HOME/.cache/breezy/maker_s2/first_print.py $DAYS $CAT $HOME/.cache/breezy/maker_s2/fp_work \\
  > $LOGD/first_print.log 2>&1; echo EXIT=\\$? >> $LOGD/first_print.log"
```
- Record the wall time as `T_FP` from the unit start/stop journal lines. The verdict run repeats this pass and a heavier probe pass, and Step 7 uses `T_FP`.
- Delete `fp_work` after the run (it is your own scratch).
- **STOP** if `FIRST_PRINT_NS=None`, the EXIT line is not 0, or `FIRST_REPLAYABLE_DAY` ∉ {2026-09-18, 2026-09-19}. The parser accepts only those two days.

## Step 3: Apply the frozen-set rule (r4 (b)), once and mechanically
1. **Pin the truth CSV.** Copy it, make it read-only, and hash it. The live file is rewritten daily by the truth timers, so the run reads the copy.
   ```
   cp $D/fq-truth/truth_cli_finals.csv $IN/truth_cli_finals_2026-10-14.csv; chmod 444 $IN/truth_cli_finals_2026-10-14.csv
   TRUTH=$IN/truth_cli_finals_2026-10-14.csv; TRUTH_SHA=$(sha256sum $TRUTH | cut -d' ' -f1)
   ```
2. **Find the last FINAL day.** This uses the driver's FINAL predicate (`tmax_f` non-empty and `tmax_flag` empty, maker stations only). It reads no tmax value and prints none:
   ```
   $PY -c 'import csv,sys;print(max(r["climate_day"] for r in csv.DictReader(open(sys.argv[1])) if r["station"] in ("LAX","MDW","MIA","SFO") and r["tmax_f"]!="" and r["tmax_flag"]==""))' $TRUTH
   ```
3. **Enumerate the dates:** from `FIRST_REPLAYABLE_DAY` through min(2026-10-13, last_final_day), ascending, without 2026-10-01. NYC is never included. The ceiling is 25 dates.
4. **Fill the block** in `$AMEND`. Use exactly these field names, no indentation, and one date per line after `dates:`:
   ```
   stations: LAX MDW MIA SFO
   first_replayable_day: <Step 2 value>
   truth_csv_path: <$TRUTH, absolute>
   truth_csv_sha256: <$TRUTH_SHA, lowercase>
   last_final_day: <step 2 value, unclamped>
   dates:
   2026-09-18
   …
   ```
5. **Set FINAL.** Change line 3's `Status: **DRAFT rev 2** …` to `Status: **FINAL** (rev 2; FROZEN_DATE_SET filled 2026-10-14). Immutable once FINAL; …`. No line may still match `^Status: *DRAFT`, and no `<FILL` may remain.
6. **Re-check the first print.** If the block's dates differ from `$DAYS`, re-run Step 2 with `DAYS=<block dates, comma-joined>`. It must return the same `FIRST_REPLAYABLE_DAY`. **STOP** if it does not. The driver repeats this check after the ledger claim, so a mismatch there voids the one verdict run.
7. **Self-check** (`cd $R; PYTHONPATH=$R/src`):
   ```
   $PY -c 'import sys,hashlib;from pathlib import Path;from scripts.analysis.maker_stage0_frozen import load_amendment,rule_dates;p=Path(sys.argv[1]);s=hashlib.sha256(p.read_bytes()).hexdigest();f=load_amendment(p,s);assert f.dates==rule_dates(f.first_replayable_day,f.last_final_day);print("BLOCK_OK",s,len(f.dates))' $AMEND
   ```
8. **Ledger line.** Append the amendment §4 line verbatim, as one line in the file's existing format, to `docs/evidence/RA-13-FW_firewall_audit_2026-09-27.md`.
9. **Commit by explicit paths:**
   ```
   git add -- $AMEND docs/evidence/RA-13-FW_firewall_audit_2026-09-27.md
   git commit -m "docs(maker-s2): S1 SEARCH amendment FINAL, FROZEN_DATE_SET filled (E5)"
   ```
10. **Record the hashes:**
    - `AMEND_SHA=$(sha256sum $AMEND | cut -d' ' -f1)` (= `S2_NBP_LICENCE_SHA256`; it must equal the BLOCK_OK sha);
    - `CODE_SHA=$(git rev-parse HEAD)`.
    - From here to the end of Step 9, nothing merges or commits on this branch. Every `run_manifest.json` `code_sha` must equal `CODE_SHA` (r4 (c)).

## Step 4: P1 disk check, then the P2 NBP backfill (E2)
- **P1:** E4 check (≥ 10 GiB).
- **P2 parameters.** Cycle dates run from 2026-09-30 to `END` = the last block date. Day D needs 13Z D−1, 19Z D−1 and 01Z D.
  - `NDAYS` = (END − 2026-09-30) + 1
  - `BUDGET` = 2×3×NDAYS (`REQUESTS_PER_ITEM_WORST_CASE` 2 × `CYCLES` (13, 19, 1))
- **Dry run first.** It needs no environment and must report `3×NDAYS item(s) planned`:
  ```
  $PY scripts/analysis/nbp_backfill.py --dry-run --start 2026-09-30 --end $END --report-json $LOGD/p2_dry.json 2> $LOGD/p2_dry.log
  ```
- **Apply.** `UA` = the monitored contact string the NBP collector unit already uses (`systemctl --user cat` its service). Never invent one.
  ```
  systemd-run --user --unit=breezy-maker-s2-p2 --collect -p RuntimeMaxSec=3600 --working-directory=$R \\
    --setenv=PYTHONPATH=$R/src --setenv=BREEZY_LIVE=1 --setenv=BREEZY_USER_AGENT="$UA" /bin/bash -c \\
    "$PY scripts/analysis/nbp_backfill.py --apply --start 2026-09-30 --end $END --request-budget $BUDGET \\
     --report-json $LOGD/p2_apply.json > $LOGD/p2.log 2>&1; echo EXIT=\\$? >> $LOGD/p2.log"
  ```
- **Exit codes:**
  - 0 = OK.
  - 1 = failed items or `stop_reason` (`budget_exhausted` / `paused_launch_window`). Read `_failures.json` and re-run only the missing dates with a fresh `2×3×n` budget.
  - 2 = REFUSED (environment or flags).
- **Pin:** `NBP_MANIFEST_SHA=$(sha256sum $D/nbp/_manifest.json | cut -d' ' -f1)`. Re-hash at Step 8 launch. A change is disclosed in Step 10, not a STOP: the driver pins the bytes it read.

## Step 5: Verify-first on 2026-06-30 (S-6; amendment §1 item 3)
```
VF=$M0/verify_first/vf-$(date -u +%Y%m%dT%H%M%SZ)
systemd-run --user --unit=breezy-maker-s2-vf --collect --slice=breezy-studies.slice -p MemoryMax=2G \\
  -p RuntimeMaxSec=1800 -p LimitNOFILE=524288 --working-directory=$R --setenv=PYTHONPATH=$R/src /bin/bash -c \\
  "$PY -m scripts.analysis.maker_stage0_replay --verify-first --out-dir $VF --amendment $AMEND \\
   --amendment-sha $AMEND_SHA > $LOGD/vf.log 2>&1; echo EXIT=\\$? >> $LOGD/vf.log"
```
- Pass requires `EXIT=0`.
- In `$VF/verify_first.json`, every `alignment[].matches_climate_day_for_txn` and every `vintage_age[].within_tolerance` must be true, for all 4 stations.
- Any false, or EXIT 2 (for example no 2026-06-30 rows), is an **S-6 STOP**: return to the spec. A substitute day needs a dated addendum *and* a change to the `VERIFY_FIRST_DAY` constant, which is a new `CODE_SHA`. Both are outside this procedure.

## Step 6: WP0 direction check + SFO positive control (no separate unit)
- The CLI has no probe-only mode. WP0 runs **inside the verdict invocation** (`maker_stage0_driver._wp0`), after the ledger claim and before any episode exists.
- Order inside the run:
  1. first print;
  2. `probe` writes `wp0_agreement.json`;
  3. S-2 is enforced;
  4. the first-replayable-day check against the block;
  5. the S-7 Δ pre-pass.
- Any failure there **voids** the run (exit 3). Step 3 item 6 is therefore the only guard against a voided run caused by a first-day mismatch.

## Step 7: Bench at 4, then 8 (r4 (i)8–9; heaviest by catalog bytes, chosen by the code)
- Never pass `--stations` or `--days`. The code picks the heaviest station-days in the frozen set, which keeps the choice outcome-blind.
- Bench 4:
  ```
  B4=$M0/bench/bench4-$(date -u +%Y%m%dT%H%M%SZ)
  systemd-run --user --unit=breezy-maker-s2-bench4 --collect --slice=breezy-studies.slice -p MemoryMax=4G \\
    -p RuntimeMaxSec=1800 -p LimitNOFILE=524288 --working-directory=$R --setenv=PYTHONPATH=$R/src /bin/bash -c \\
    "flock -w 600 \\$XDG_RUNTIME_DIR/breezy-studies.lock $PY -m scripts.analysis.maker_stage0_replay --bench 4 \\
     --census-days $S1/censused_days.jsonl --trade-unit $S1/trade_quantity_unit.json --truth $TRUTH \\
     --node-log-dir $NODELOGS --out-dir $B4 --amendment $AMEND --amendment-sha $AMEND_SHA \\
     > $LOGD/bench4.log 2>&1; echo EXIT=\\$? >> $LOGD/bench4.log"
  ```
- Then run the same unit as `--bench 8`: unit `breezy-maker-s2-bench8`, `B8=$M0/bench/bench8-…`, `RuntimeMaxSec` = max(1800, 6 × bench-4 wall time).
- Bench exit codes: 0 = done; 2 = refused (the preflight also dry-checks census completeness, the truth sha and θ). STOP and fix the input if it refuses.
- Read `bench.json` from B8. `run_manifest.json` carries `code_sha` (must equal `CODE_SHA`) and `peak_rss_bytes`. cgroup `MemoryPeak` is not reported on this host.
  - `projected_total_s`, `projected_peak_rss_bytes`, `s5_exceeded`
  - per row: `elapsed_s`, `peak_rss_bytes`
- **Projection:** `PROJ` = `projected_total_s` + 2×`T_FP`. The WP0 first-print and probe passes are outside the bench; counting each at `T_FP` is a stated screen, not a proof.
- **S-5 STOP** (fix the reader first; no verdict run) if any of these holds:
  - `s5_exceeded` is true;
  - `PROJ` > 21600 s;
  - `projected_peak_rss_bytes` > 4 GiB;
  - either bench aborted on `MemoryAbort`.
- **Caps for the verdict run:**
  - `RTMAX` = min(21600, max(1800, 3×`PROJ`)).
  - `MEMMAX` = min(2 × max over rows of `peak_rss_bytes`, 4G), in bytes. This is containment; the in-code RSS abort is at 4 GiB.
  - `T_STALL` = max(600, 3 × max over rows of `elapsed_s`).

## Step 8: The verdict run (one ledger entry; r4 (c))
**Pre-launch checks:**
- Clean tree; `git rev-parse HEAD` = `CODE_SHA`.
- E4 check.
- `$M0/verdict_ledger.jsonl` is absent or holds no `verdict_run_start` with `"amendment_sha": "$AMEND_SHA"`.
- The window rule holds for `RTMAX`.

**Launch:**
```
RUN_ID=s2v-$(date -u +%Y%m%dT%H%M%SZ); OUT=$M0/$RUN_ID
systemd-run --user --unit=breezy-maker-s2-verdict --collect --slice=breezy-studies.slice \\
  -p MemoryMax=$MEMMAX -p RuntimeMaxSec=$RTMAX -p LimitNOFILE=524288 --working-directory=$R \\
  --setenv=PYTHONPATH=$R/src /bin/bash -c "flock -w 600 \\$XDG_RUNTIME_DIR/breezy-studies.lock \\
  $PY -m scripts.analysis.maker_stage0_replay --census-days $S1/censused_days.jsonl \\
  --trade-unit $S1/trade_quantity_unit.json --truth $TRUTH --node-log-dir $NODELOGS \\
  --catalog-root $CAT --nbp-root $D/nbp --truth-cross-check $D/settlement-truth/settlement_truth.parquet \\
  --out-dir $OUT --amendment $AMEND --amendment-sha $AMEND_SHA \\
  > $LOGD/$RUN_ID.log 2>&1; echo EXIT=\\$? >> $LOGD/$RUN_ID.log"
```
- Scratch defaults to `~/.cache/breezy/maker_stage0_work/$RUN_ID`. The spec defaults to the repo spec.

**Stall watch (arm it in the launch turn; re-arm on expiry):**
- Before `$OUT/progress.jsonl` exists (the WP0 phase): alert if the unit has been active longer than 6×`T_FP` + 600 s.
- After it exists: alert if its mtime is older than `T_STALL` while the unit is active.
- Done = `ActiveState` ∉ {active, activating}.
- On a stall, report STALL and let `RuntimeMaxSec` end the unit. Never kill the node.

**Exit codes** (the last `EXIT=` line in `$LOGD/$RUN_ID.log`, plus the stderr line):

| EXIT | Meaning | Action |
|---|---|---|
| 0 | `verdict run done label=<L>`, including `STOP-S4-NO-BID-BEARING-DAYS` (reported stop; ledger entry kept) | read the outputs below |
| 2 | `REFUSED: …` before the claim (also `LedgerRefused`: an entry already exists, so STOP) | fix the input; relaunch with a new `RUN_ID`; ledger untouched |
| 3 | `VOID: …`; `$OUT` was renamed `.void` and a ledger void entry was written | classify the cause (below); never open `episodes.jsonl` |
| none | `RuntimeMaxSec`, OOM or host kill; `$OUT` is not renamed | void by hand (below); treat as host kill or S-5 |

Voiding by hand:
```
$PY -c 'import datetime as d,sys;from pathlib import Path;from scripts.analysis.maker_stage0_ledger import void_run_dir;print(void_run_dir(Path(sys.argv[1]),ledger=Path(sys.argv[2]),now=d.datetime.now(d.UTC)))' $OUT $M0/verdict_ledger.jsonl
```

**Void causes:**
- S-5 (`MemoryAbort`), S-7 (Δ > 10 min), E4, OOM, crash or host kill are non-result voids. A re-run is allowed only via `RULING_MAKER-S1_SEARCH_amendment_addendum_<date>.md`. The addendum names the run_id, the cause, and the old and new `code_sha`, and attests that no fill, rate or label output was read. Then relaunch with `--addendum PATH --addendum-sha SHA`.
- S-2 (direction inverted or inconclusive) is a return to the spec, not an addendum re-run. Amendment §3 does not list S-2.

**What to read on EXIT 0:**
- `report.md`: the verdict line, V0 block, fitted-ICC block and any `FITTED-ICC DISAGREES ON THE FLOOR` banner.
- `s3_inputs.json`:
  - `verdict`, `r_lo`, `r_lo_lcb_cluster_boot`, `r_lo_k1`;
  - `b`, `fill_icc_rung_trial` (null if undefined), `n_eff_gov`, `n0_climate_dates`, `unit_hypothesis`, `code_sha`.
- `wp0_agreement.json`: `direction`, `positive_control`, `first_replayable_day`.
- `run_manifest.json`: `ladder_lower_parity`.

**Disposition:**
- `NO-GO (…)`: S-1 programme STOP. Nothing is built; S4/S5 are not started; the maker programme ends.
- `UNDERPOWERED-WAIT`: no build. S3's binding run refuses it.
- `NOT-KILLED-UNSCREENED` / `NOT-KILLED`: licenses S4/S5 shadow work only, under the holdout gate. S3 consumes `s3_inputs.json` once its allowlist test is merged. This is not evidence of edge.
- `STOP-S4`: report and stop.

## Step 9: `--tail-only` (report-only; same `CODE_SHA`; amendment §1 item 5)
- `PAR` = `ladder_lower_parity` from `$OUT/run_manifest.json`, written as `LAX:p,MDW:p,MIA:p,SFO:p`. If any station is missing, skip this step and record why.
- Run a unit `breezy-maker-s2-tail` with Step 7's `MEMMAX` and `RuntimeMaxSec=3600`, and the same flags as the bench, except: `--tail-only --parity $PAR --out-dir $M0/tail/tail-<stamp>`.
- The run writes only `tail_reliability.csv`. It may annotate `TAIL-MISCALIBRATED`, never set the label.

## Step 10: Evidence, PROGRESS, gate, push
- **Evidence doc:** `docs/evidence/maker/STAGE0_REPLAY_2026-10-14.md`. It holds `report.md` verbatim plus a provenance header:
  - unit names, every EXIT line, `RUN_ID`, `CODE_SHA`, `AMEND_SHA`, `TRUTH_SHA`;
  - `NBP_MANIFEST_SHA` at Steps 4 and 8;
  - `T_FP`, the bench numbers, `RTMAX`/`MEMMAX`/`T_STALL`;
  - the Step 1 S1 values;
  - the tail result.
- **Sidecars:** `docs/evidence/maker/stage0_2026-10-14/` gets:
  - `s3_inputs.json`, `pins.json`, `run_manifest.json`, `wp0_agreement.json`;
  - `station_days.csv`, `scored_episodes.csv`, the `*_station_days.csv` files, `process_schedule*.json`, `catalog_slice_manifest.json`;
  - the two `bench.json` files, `verify_first.json` and the tail CSV.
  - Files ≥ 5 MB are gzipped and their sha256 listed. The run's truth copy is not committed (it holds sealed rows); only its sha is.
- **PROGRESS:** add a `docs/core/PROGRESS.md` row: S2 → label, run_id, next action per the Step 8 disposition.
- **Commit:** `git add --` each path explicitly, then `git commit -m "docs(maker-s2): Stage 0 replay <label> (run <RUN_ID>)"`.
- **Gate:** run `scripts/ci/run_tests_no_egress.sh` with basetemp under `~/.cache` (one heavy job, so not while anything else runs). Read EXIT, then delete the basetemp. Push both commits only on `EXIT=0`.

## Never
- Never run a second verdict pass on this amendment sha, except by addendum after a non-result void.
- Never re-run for a result-driven reason.
- Never pass `--stations`, `--days`, `--bench` or `--tail-only` to the verdict run.
- Never edit the amendment, block, truth copy or code from the Step 3 commit through Step 9. No edits after the run either: corrections are a new dated ruling.
- Never re-choose the frozen set, and never read 2026-10-01, any day after 2026-10-13, or NYC.
- Never open a `.void` run's `episodes.jsonl`.
- Never run `uv`, `pip`, `git stash` or `git add -A`.
- Never run two heavy units at once, and never start inside the blocked windows.
- Never kill the node or the recorder.
- Never record an S-2 inversion as a rule flip.

## Open notes (planner 2026-10-14; coordinator dispositions)
1. Step 2 is a coordinator script (the CLI has no first-print mode); `T_FP` and its use in `PROJ` are a stated screen. Accepted.
2. The verdict report's tail table is empty by construction (parity is known only after the verdict run); the Step 9 `--tail-only` CSV is the tail evidence. Accepted; disclose in Step 10.
3. `nbp_backfill --dry-run` may not distinguish present from missing items; a pre-2026-09-30 gap surfaces only as `NO_VECTOR` abstentions in `report.md`. Accepted; quote the abstention counts in Step 10.
4. `~/.local/share/breezy/logs` holds 73 `breezy-trade-<stamp>.log` plus a few unstamped files (`breezy-trade-supervisor*.log`, `quote_tape_*.log`); WP1's scanner rejects unstamped names as unverifiable (`node_log_absent` path, never OUTAGE), so they cannot count as covering files. Accepted.
5. `BREEZY_USER_AGENT` is taken from the existing NBP collector unit (`systemctl --user cat`), never invented. Accepted.
