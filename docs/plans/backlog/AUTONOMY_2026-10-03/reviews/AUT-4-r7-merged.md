# AUT-4 r7, merged review (coordinator)

Scores: PM 94, MLE 93. Neither has a CRITICAL or HIGH finding. The final score is 93, so the plan goes to r8.

## MEDIUM

- **AH1 [both]: O-1.**
  - Cite E-7b and mark O-1 closed.
  - Drop the §6.4 row-10 wait for the ruling.
  - Add the E-7b "no HTTP/WS client in the closure" clause to `test_eval_offline_closure_has_no_adapter_exec_module`.
  - WP1 lists the closure measurement. For branch (a) it also lists the symbology shim and the closure test.
- **AH2 [MLE]: error message.** Keep the `n ≤ 0` guard and its exact `ValueError` text in `recompute_mde`, and add a test that pins the message.
- **AH3 [MLE]: private `/tmp`.** Consume E-7c in all three §3.9a rows (`--tmpfs /tmp`, `TMPDIR`). Add `fs_replay` child scratch writes to WP6 verify-first.
- **AH4 [MLE]: quarantine bind.** Resolve the quarantine path now, read-only, from `replay_daily_runner`. If it cannot be resolved, mark the row "not filed until WP6 verify-first", with the wrapper's fail-closed behaviour stated.
- **AH5 [PM]: real import closure.** State the real closure of `sample_size`: `persistence/__init__` pulls in `catalog`, Nautilus and `domain`. Add `lint-imports` ("N kept, 0 broken", run from the tree) as an explicit WP2 gate. Ask ARCH-0 to keep `persistence/__init__` lazy, if needed.

## LOW

- Make the `compute_n_min` vs `n_min_one_sided` equivalence test a grid sweep over σ and X with a ±1-ulp tolerance. A `ceil` boundary flip must be either impossible or handled.
- Add a positive/negative probe test for the fixture row.
