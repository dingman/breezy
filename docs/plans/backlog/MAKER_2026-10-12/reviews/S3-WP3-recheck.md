# S3 WP3 recheck of 34b58508 (vs 8bcc9b31) -- APPROVE (0 HIGH/MEDIUM; 3 LOW notes)

mypy on scripts/analysis/fq_loss_floor_mc_maker*.py: "Success: no issues found in 7 source files" (run by reviewer). No tests run.

## Resolution table
PMR M1 CLI orchestration untested: RESOLVED. stages.py + test_..._stages.py drive main() with stubbed run_cell/recheck/horizon/cap.
PMR M2 early-stop artifact: RESOLVED. stages.py run_sweep -> assemble_artifact(early_stop_evaluation(...)); test asserts verdict UNREACHABLE,
   early_stop, basis, 30 sweep + 6 confirm cells, provenance (git_head, script sha, tree_clean), freeze_blocked_cells. BUILDER-DEFECT printed (tested).
PMR M3 deff unit: RESOLVED. templates.py FILL_ICC (rung-trial) + FILL_ICC_SD = 0.5/3; Beta draw uses station_day_icc(); realised deff tested by MC at ICC 0.5/7 (=1.5, 3 SE; 1.214 excluded at 6 SE) and at 0.2 (=2.4).
PMR M4 benchmark note: RESOLVED. Itemised stages, units (sweep 4 h / binding 8 h), recheck 84 sims, confirm, horizon, re-runs, watch, mandatory 1000-rep calibration. Totals re-add (1.19 / 3.24 / 4.4 h).
PMR L1/PY S1-S2 validation + f_pass<=f_kill: RESOLVED (both rung classes; per-line S1 schema with file:line; IQR numeric/[0,1]/contains median; tests present).
PMR L2/PY unknown_share basis: RESOLVED (kept four-station; all-rows figure + UNKNOWN_SHARE_BASIS recorded in provenance; documented deviation from r4 (g)).
PY M2 provenance: RESOLVED. s2_lines, s1_rows, git_tree_clean, raw ICC clamp recorded; _line now walks the dotted path; test asserts distinct lines for fill_rate_2x.point vs fill_rate_base.point.
PY M3 glue untested: RESOLVED (see (b)).
PY borderline re-run: RESOLVED. Report cells use runners.plain; test shows 12 re-runs, all theta 0.0695 seed 20261013, none on report cells.
PY duplicate pin: RESOLVED (LISTING_PIN removed; inputs imports LISTING; no remaining reference).
PY mypy: RESOLVED (tuple[float,...] annotation, epoch0 dict[str, Any], bool()).

## Judgements
(a) ICC mapping CORRECT. Equal-deff under an exchangeable-within-date model: 1+7*rho_rt = 1+3*rho_sd => rho_sd = rho_rt*7/3; 0.5/7 -> 0.5/3.
   Beta(f, rho) gives Var(p)=rho f(1-f), so a count of 4 station-day trials has deff 1+3*rho_sd exactly (the MC test confirms). Refusing rung-trial ICC >= 3/7
   is right: it maps to rho_sd >= 1 (degenerate Beta, a+b<=0), and 4 trials cap deff at 4 = 1+7*3/7. Floor stays on the rung-trial value (tested).
   Caveat (LOW): S2's rung-trial ICC mixes within-station-day (k=2 rung pairs) and across-station correlation; collapsing to one trial per station-day is an
   approximation that matches the spec's own deff definition, not a derivation. The provenance records both units, so it is auditable.
(b) Stage tests pin the wiring. Sweep: 30 cells at 2000 reps, outer (0,0); confirm: 6 cells f=0.5, 10k, outer (20,2000); binding: 12 pinned cells (k,f) set exact,
   all 10k + outer 20x2000 + SEED; report: 6 cells theta 0.08 at f_pass only (set {(2,.22),(1,.14)}), plain runner; 12 rechecks all at the frozen c, none for report;
   horizon fed the frozen cell (k2,b.75,f_kill .30) with L_cap 220 and the S5 dates; --out is the only file written; report cells do not move the verdict.
   Gap (LOW, test only): no test with a VETOING report cell proving REACHABLE is unchanged; the freeze_blocked test covers only the blocked case.
(c) Memory extrapolation holds. Three consistent points (100/200: 396/407; 1000: 498; 4000: 829 MiB) -> 0.11 MiB/rep, intercept ~388; 50k -> ~5.9 GB (5.77 GiB by
   my arithmetic, note rounds up; fine). The 5G unit cap would be breached, so 9G/12 GiB is right. LOW: --max-memory-gib 12 is address space, and VmPeak was never
   measured (RSS only); the 50k point is a 12.5x extrapolation. Add one 20k-50k replicate point (RSS + VmPeak) to WP4 step 0, or keep 12 as provisional (note says so).
   Sweep unit worst case (4.1 h) exceeds its 4 h RuntimeMaxSec; central 1.2 h, note says recalibrate -- acceptable.
(d) IQR fixture change does not weaken the test. binding_cells reads only s2.bid_iqr (not the median); the median is clamped into the IQR only to satisfy the new
   contains-median refusal, so all four IQR assertions (outward rounding both sides, point IQR with admitted_k, None) and the per-class f_kill/f_pass check are unchanged.

## Remaining LOW (optional, none block)
- inputs.py _line: "verdict"/"n0" (top-level) resolve to the first match at any depth; fine for current S2 shape.
- verdict-test gap above; `# type: ignore[arg-type]` on Literal rungs and `pin: Any` remain (out of coordinator scope).
