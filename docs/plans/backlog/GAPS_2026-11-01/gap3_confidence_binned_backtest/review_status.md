# GAP-3 review status (2026-11-01)
- plan_r1.md — architect: APPROVE (3 LOW); python-reviewer: APPROVE (3 LOW). Peer review CLOSED at r1.
- LOW notes accepted as binding build notes (no re-review needed):
  1. §4.3(i) clean-tree check: refuse when `git status --porcelain -- scripts/analysis src/breezy` is non-empty, not only when the script differs from HEAD.
  2. §3 `_day_matrices` return annotation widens to `list[CellKey | ForecastCellKey]` (`:545`) so mypy stays green.
  3. §4.3(i) exit-4 handling of `_refuse_live_root` applies only under the flag; the default path keeps raising `ValueError` (`test_out_dir_refuses_live_data_root :327` and the byte pin unchanged).
  4. §4.3(iv)/(v): `Observation` (`:176-185`) gains no field; `key_fn` is a closure over a `(rung, window) → p` map; default `key_fn` untouched.
  5. §6: the whole `test_market_calibration_scan_forecast_p.py` module patches the git helper through one shared fixture; the helper uses `subprocess` with a list argv and adds no module matching the `:259` guard words.
  6. §4.3(vii): `write_outputs(exclusive=True)` leaves the default call byte-identical (`exist_ok=True`, mode `"w"` default, covered by the pin).
- 2026-11-01 later: STRATEGY-SEARCH r3 delta supersedes GAP-3 r1's run-file location: flagged runs write to r1 D4 `~/.local/share/breezy/derived/strategy_iteration/<run_id>/` (create-exclusive), never into `docs/evidence/`; evidence is committed only by coordinator action. GAP-3 A-1(a)–(c) otherwise unchanged.
