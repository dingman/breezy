# S1 run procedure — census + crosscheck (earliest 2026-10-14 10:00Z)

Status: READY-TO-RUN once the final S1 merge gate is green and pushed.
Plan: `S1_preconditions_plan_r3.md` WP1/WP2 run stages, §6, §8. Build evidence:
WP0 6068a00e, WP2 dfb2d223 (+ d0cfd259 fixes), WP1 9604ea4a (+ `--prints-out`).

## Entry criteria (all must hold, checked by the launcher, quoted in WP4)
- Clock ≥ 2026-10-14 10:00Z and < 15:00Z (clear of the 15:20Z/15:50Z studies).
- `df --output=avail -BG /home` ≥ 10G; `free -g` available ≥ 6G; no unit matching
  `study|census|scorer|replay|gate` running; `breezy-studies.lock` free.
- `sha256sum docs/evidence/RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md`
  == `38663caad38e455ab1512ca91a049f97d31c2dcfb1477c42db02ceca407abbc6`.
- Recorder active (`systemctl --user is-active breezy-quote-tape`); the live
  instance is counted, never read (the script enforces it).

## Stage A — census (WP1 run)
```
OUT=~/.local/share/breezy/derived/maker/s1; mkdir -p $OUT
systemd-run --user --unit=breezy-maker-s1-census --collect --slice=breezy-studies.slice \
  -p MemoryHigh=3G -p MemoryMax=4G -p RuntimeMaxSec=3600 -p LimitNOFILE=524288 \
  --working-directory=/home/jon/breezy --setenv=PYTHONPATH=/home/jon/breezy/src \
  /bin/bash -c "flock -w 600 \$XDG_RUNTIME_DIR/breezy-studies.lock \
    /home/jon/breezy/.venv/bin/python scripts/analysis/maker_tape_census.py \
    --from 2026-08-30 --to 2026-10-13 --stations LAX,MDW,MIA,SFO \
    --search-declaration docs/evidence/RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md \
    --output $OUT/censused_days.jsonl --prints-out $OUT/prints.jsonl \
    > $OUT/census_run.log 2>&1; echo EXIT=\$? >> $OUT/census_run.log"
```
RuntimeMaxSec: benchmark 16.7 s / 459 MB on a 3 GB instance × 81 instances →
15–25 min projected; 3600 s = ≥ 2.4× projection (plan: 3× benchmark, min 1800).
Stall watch: log mtime unchanged 15 min while active → report STALL, let
RuntimeMaxSec end it, never kill the node.

Exit codes (WP1): 0 OK · 2 REFUSED (firewall/scope/parse) · 3 IO_FAILED ·
4 UNSCREENED (< 10 covered station-days; output IS written; a valid result).
Read from the log: `N_cov D_cov n_eff_ub C` on the plan window, the
`INFO bidlive:` line (`N_cov_bidlive D_cov_bidlive C_bidlive n_eff_ub_bidlive`),
the reason histogram, `rows_discarded_out_of_scope`, `prints_written`,
`prints_skipped_no_aggressor`, and every `STOP` line verbatim.

STOPs (plan window, pre-registered): S-1 `n_eff_ub < 30` → UNDERPOWERED → Q1;
S-5 `C < 0.05` → NO-GO pre-screen (family stays v0.3, no S2 build);
`0.05 ≤ C < 0.10` → KILL-LIKELY, S2 proceeds; S-5 UNSCREENED below 10 covered
days. The bid-live figures are REPORT-ONLY in S1 and are handed to S2.

## Stage B — crosscheck (WP2 run), only after Stage A exit ∈ {0, 4}
```
systemd-run --user --unit=breezy-maker-s1-tqu --collect --slice=breezy-studies.slice \
  -p MemoryMax=2G -p RuntimeMaxSec=900 --working-directory=/home/jon/breezy \
  --setenv=PYTHONPATH=/home/jon/breezy/src \
  /bin/bash -c "/home/jon/breezy/.venv/bin/python scripts/analysis/trade_quantity_unit_crosscheck.py \
    --prints $OUT/prints.jsonl \
    > $OUT/trade_quantity_unit.json 2> $OUT/tqu_run.log; echo EXIT=\$? >> $OUT/tqu_run.log"
```
(The result JSON goes to stdout; there is no output flag. Flags verified on the
merged tree: `--db` defaults to the live exec store, opened `mode=ro`;
`--declaration` defaults to the WP0 path; `--prints` is the WP1 file.) Exit codes (WP2, DIFFERENT meanings from WP1):
0 OK · 2 BAD_INPUT · 3 PIN_MISMATCH (kept set ≠ the 28 pinned) · 4 STOP
(S-2 UNRESOLVED or S-3 CONTRADICTED; result written) · 5 NO_FIREWALL.
Expected: BRACKETED_USD is the likely verdict (only 2 of 28 kept fills are NO
legs); `match_basis` is `unique_candidate_in_window` for every counted match.

## Stage C — disposition
- Verdict single-hypothesis → WP3 (RED test → flip `TRADE_QUANTITY_UNIT` →
  remove the UNRESOLVED pin → full gate → merge; effective at the 09:00Z
  rotation). BRACKETED_USD → WP3 skipped; S2 runs under both, conservative governs.
- WP4: `docs/evidence/MAKER-S1_preconditions_2026-10-14.md` quoting every value
  above with provenance (unit names, log paths, EXIT lines, sha256), the
  bid-live vs plan-window comparison, the reason histogram, the NO_AGGRESSOR
  skip count, the `instances_corrupt_unread` lower-bound caveat, and the
  unique-candidate limitation. Words GO / NOT-KILLED never appear.
- PROGRESS row: S1 → outcome (UNDERPOWERED / NO-GO pre-screen / proceed to S2
  with KILL-LIKELY flag if any). Push only after a green gate with EXIT read.
