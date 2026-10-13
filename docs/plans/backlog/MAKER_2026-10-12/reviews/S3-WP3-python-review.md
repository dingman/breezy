# S3 WP3 python review (a119fd97..8bcc9b31) -- REQUEST_CHANGES (3 MEDIUM, no HIGH/CRITICAL)

Evidence: focused gate EXIT=0 (220 passed incl. import isolation + np_bound); basetemp removed.
mypy on the 6 new scripts: 3 errors (below). Scope stat: 11 files; extra file docs/evidence/maker/S3_WP3_benchmark_2026-10-13.md (benchmark note, acceptable). WP0 pin test untouched.
Runtime check: cell, recheck and horizon dicts all json.dumps(allow_nan=False) cleanly (no numpy leak).

## Scores
1 plan compliance 8 | 2 tests 8 | 3 conventions 8 | 4 security/IO 7 | 5 performance/imports 8 | 6 scope 9

## Findings
[MEDIUM] Input readers raise raw KeyError/TypeError/ValueError, not MakerRefusal
 File: scripts/analysis/fq_loss_floor_mc_maker_inputs.py:224-232 (listing_rate_4stn), :152-155 (realised_bid_iqr), :245-250 (load_s1)
 Issue: S1 rows are not schema-checked: a row lacking reason/station/climate_day/first_seen_ns -> KeyError; a non-object JSONL line -> TypeError; IQR entries non-numeric/bool -> TypeError at `raw_iqr[0] > raw_iqr[1]` or float(). main() catches only MakerRefusal, so these exit with tracebacks, not "REFUSED: ..." exit 2. IQR is also not range-checked to [0,1] / grid span.
 Fix: validate each S1 row (dict, required keys, reason in a known set, first_seen_ns int|None) and each IQR element (non-bool number) and raise MakerRefusal with file+line number. Add a test per malformed shape.

[MEDIUM] "records their sha and lines" only half done
 File: scripts/analysis/fq_loss_floor_mc_maker.py:196-206 (derived/provenance)
 Issue: S2Inputs.lines is computed (inputs.py:157) but never emitted; S1 line count is not recorded; the WP4 artifact "clean-tree line" is absent (only git_head and script blob sha). Also _line() (inputs.py:112-117) returns the first line containing the leaf key, so fill_rate_2x.point and fill_rate_base.point (and lower95) all report the same wrong line.
 Fix: put s2.lines, S1 row count and a `git status --porcelain` clean flag into `provenance`; make _line match the dotted path (or drop lines and record sha only, and say so in the plan).

[MEDIUM] No test drives _binding/_sweep/_write end to end
 File: tests/unit/test_fq_loss_floor_mc_maker_verdict.py (main tests stop at refusals and --inputs-only)
 Issue: the glue that builds kill/low/report cells, calls evaluate_binding, _frozen_horizon, assemble_artifact and writes --out is untested, as are _sweep, benchmark(), and the write-only-to---out guarantee. A wiring regression (e.g. report cells at wrong f/theta, horizon fed the wrong cell) would pass the suite and surface only after a multi-hour WP4 run.
 Fix: monkeypatch maker.run_cell / vmod.recheck_cell / horizon_sensitivity with small fakes and run main(["--binding",...,"--out",tmp]) and main(["--sweep","--out",tmp]); assert artifact keys, report cells carry theta 0.08 at f_pass, nothing is written elsewhere. A benchmark smoke with a stub run_cell.

[LOW] mypy (report only): inputs.py:213 `bids` tuple[float,float,float] reassigned to tuple[float,...]; artifact.py:104 `epoch0` needs annotation (dict[str, Any]); verdict.py:267 returns Any from -> bool (wrap bool()).
[LOW] Weak typing: verdict.py `_context` -> tuple[Any,...] x6 (use a frozen dataclass), `_binding_rates(pooled: Any, config: Any)` (FloorConfig/PreparedDay), maker.py `_frozen_horizon(pin: Any) -> Any` (CapPin | None). Two `# type: ignore[arg-type]` on Literal rungs (inputs.py:213-ish mix_for, templates `_mix`): use typing.cast or validate-then-narrow.
[LOW] Duplicate pin: LISTING (templates.py) and LISTING_PIN (inputs.py), both 0.91; import one. Literals 0.5 (p2) in `_mix`, 66/78/2 in _RUNG_IDS, "2026-10-08..2027-01-25"/"110" hard-coded in artifact.window_label and f_max 0.5/beta 1.0 in sweep_early_stop; derive from DEFAULT_FREEZE/HORIZON/inclusive_days or name them. check_bid_range is public, undocumented, and not in __all__.
[LOW] Private engine imports (_criticals,_partition,_rho,_run,_seed) in verdict.py; np_bound already does this, but a one-line comment or a public alias would stop silent drift.
[LOW] fill_icc silently raised via max(S2 icc, FILL_ICC) (inputs.py:~160): conservative, but record the clamp in provenance.
[LOW] unknown_share denominator is the four-station rows (`len(four)`); delta (g) says "all non-PRE_TRADE rows". Align or note.
[LOW] Report cells and early-stop confirm go through run_cell_final, so a borderline report cell triggers a 50k re-run; plan applies the rule to binding cells. Use final=False for report cells.
[LOW] sweep_early_stop returns None for a freeze_blocked cell without surfacing "builder-defect" to the operator; _sweep should print/flag it. assemble_artifact(early_stop=...) has no production caller (sweep writes its own doc without verdict); drop or wire.
[LOW] Unused-by-design CLI flags (--s2-artifact etc. in --sweep mode) are silently ignored.

## Per-criterion notes
1. Module split justified (CLI 296 <= 300); all pins named constants in templates.py and re-exported via __all__ from the main module; modes/flags match; binding refuses missing s2/s1/s5/out (inputs-only exempts --out). Verdict, frozen-cell, recheck, horizon (re-simulation with len(cuts)>=L_cap guard), borderline, early-stop match r4 (a)-(h). 
2. All planned test names present. Mutation-sensitive: deff (production step_clock, tie-aware), s4 exit floor, bracket/larger-c, freeze_blocked, early stop (both sides), horizon (spy on n_days, rate rises with L_cap), recheck (loose/tight/own c). No ImportError-only tests. Gap: glue (MEDIUM above).
3. Frozen slots dataclasses, no mutable module state (_NO_RECHECK dict is copied before use), early returns, no bare except. Functions all <= ~50 lines.
4. Writes only to --out (atomic tmp+replace); no eval/subprocess shell (git via list args); paths are CLI-supplied. Schema validation incomplete for S1/IQR (MEDIUM).
5. Memory cap applied in sweep/benchmark/binding (after inputs). Sweep cells use outer=0 (matches the ~475 s basis). Recheck cost: per cell 4 binding sims + 3 H1 sims at 10k, x36 cells, groups rebuilt per call: WP4 should budget it from --subset-benchmark (the benchmark does not time recheck). No O(n^2). No maker module imports breezy.runtime; transitively it IS loaded via fq_loss_floor_mc_engine -> breezy.strategy (pre-existing FQ behaviour, verified on the bare engine import); test_runtime_import_isolation passes.
6. Scope clean; gate.py +3 lines (duplicate persist-mode guard, tested) and floor_spec test follow-ups only.
