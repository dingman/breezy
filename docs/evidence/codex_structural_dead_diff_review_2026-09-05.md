# Codex independent review — structural-dead diff (uncommitted, 7 files)

Task: task-mtoip1nh-rtv3rf (read-only). Grok review of the same diff failed on 402 balance exhaustion.

REJECT

1. [HIGH] [scripts/analysis/structural_dead_stop.py](/home/jon/breezy/scripts/analysis/structural_dead_stop.py:260) is fail-open on unreadable gap data. `_resolved_gaps_from_catalog()` catches `Exception`, logs, returns `()`, and [covered_listed_station_days](/home/jon/breezy/scripts/analysis/structural_dead_stop.py:246) then counts captured days as if no outage rows exist. If the missing gap partition contains an afternoon outage and the captured span still exceeds 30 minutes, the denominator is inflated toward an early structural **KILL**. Exact fix: make unreadable gap data a counter refusal: raise/return unavailable, have `main()` exit nonzero and write no JSON, so the 15:30 wrapper’s missing-counter path halts.

2. [HIGH] [deploy/systemd/family-tally-v2-run.sh](/home/jon/breezy/deploy/systemd/family-tally-v2-run.sh:122) still allows a non-authoritative fill source when no live node is found. `exec_state_db_path --check` exits 0 for `NO_NODE` by contract, and this wrapper only warns at [line 126](/home/jon/breezy/deploy/systemd/family-tally-v2-run.sh:126), then passes `$POLYMARKET_US_EXEC_STATE_DB` as `--fill-source`. A readable stale/non-live sqlite with zero matching fills yields `filled_takes=0` via [family_tally_v2.py](/home/jon/breezy/scripts/analysis/family_tally_v2.py:1006), so covered>=15 can false-KILL. Exact fix: for `pm_us_crh_v2`, require `CHECK_TOKEN=MATCH`; treat `NO_NODE` as exit 1 or skip structural evaluation.

3. [MED] [scripts/analysis/structural_dead_stop.py](/home/jon/breezy/scripts/analysis/structural_dead_stop.py:153) has an edge-overlap bug. `_gap_overlaps_afternoon()` calls inclusive `gap.covers(start_ns)` at [line 155](/home/jon/breezy/scripts/analysis/structural_dead_stop.py:155), and `QuoteTapeGap.covers()` is inclusive at both ends ([tape_records.py](/home/jon/breezy/src/breezy/adapters/polymarket_us/tape_records.py:158)). A gap ending exactly at `[12:00,17:00)` start is treated as overlapping and can wrongly exclude a day. Exact fix: use explicit half-open overlap: `gap.started_ns < end_ns and (not gap.resolved or gap.ended_ns > start_ns)`, with boundary tests.

| Plan-review finding | Status | Evidence |
|---|---|---|
| 1 | SATISFIED | Render keeps SHADOW first and uses `tally.verdict` at empty looks: [family_tally_v2.py](/home/jon/breezy/scripts/analysis/family_tally_v2.py:879). |
| 2 | SATISFIED | Structural KILL skips loop; terminal path receives `structural_fired`: [family_tally_v2.py](/home/jon/breezy/scripts/analysis/family_tally_v2.py:528), [current_rung_hold_v2.py](/home/jon/breezy/src/breezy/settlement/current_rung_hold_v2.py:221). |
| 3 | SATISFIED | Six-key JSON preserved: [structural_dead_stop.py](/home/jon/breezy/scripts/analysis/structural_dead_stop.py:315), [test_structural_dead_stop_cli.py](/home/jon/breezy/tests/unit/test_structural_dead_stop_cli.py:182). |
| 4 | SATISFIED | PM-only wrapper gate; Kalshi gets no structural args: [family-tally-v2-run.sh](/home/jon/breezy/deploy/systemd/family-tally-v2-run.sh:84), [test_family_tally_v2_deploy.py](/home/jon/breezy/tests/unit/test_family_tally_v2_deploy.py:280). |
| 5 | PARTIAL | Uses `resolved_gaps_by_seq`, but unreadable gaps fail open and gap-only listed days are not unioned: [structural_dead_stop.py](/home/jon/breezy/scripts/analysis/structural_dead_stop.py:192), [line 260](/home/jon/breezy/scripts/analysis/structural_dead_stop.py:260). |
| 6 | MISSED | Plan still states 9.5h, not amended to ~12h: [STRUCTURAL_DEAD_RULE_2026-09-05.md](/home/jon/breezy/docs/plans/STRUCTURAL_DEAD_RULE_2026-09-05.md:50). |
| 7 | SATISFIED | Paper sidecar refused; empty unmarked store remains R2; live prefix used: [family_tally_v2.py](/home/jon/breezy/scripts/analysis/family_tally_v2.py:473), [line 1010](/home/jon/breezy/scripts/analysis/family_tally_v2.py:1010). |

Codex session ID: 01a0721c-dbd3-7441-9951-a3b8480e5641
Resume in Codex: codex resume 01a0721c-dbd3-7441-9951-a3b8480e5641

## Fix pass

F1 RED tests: `test_unreadable_gap_partition_refuses_and_writes_no_output`;
`test_absent_gap_partition_with_no_gap_rows_is_honestly_empty`. Failure line:
not produced because both `scripts/ci/run_tests_no_egress.sh ...` and the
`tests/conftest.py` fallback `unshare -r -n env BREEZY_TEST_OS_EGRESS_BLOCK=1
.venv/bin/python -m pytest ...` failed before collection (`exit 3` launcher;
`unshare: unshare failed: Operation not permitted`). GREEN line: direct probe
printed `manual structural probes passed` and `manual absent-gap probe passed`;
unreadable gaps now raise `QuoteTapeGapDataUnavailable`, `main()` returns 1,
and no counter JSON is written.

F2 RED test:
`test_pm_wrapper_skips_structural_eval_when_node_check_returns_no_node`.
Failure line: not produced for the same namespace block. GREEN line: direct
wrapper probe printed `FAMILY TALLY V2 (pm_us_crh_v2) SKIPPED -- node-env
pre-flight token NO_NODE (required MATCH); structural evaluation unavailable`
and `manual wrapper rc=1`; no downstream argv capture was created.

F3 RED tests: `test_gap_ending_exactly_at_afternoon_start_is_covered`,
`test_gap_starting_exactly_at_afternoon_end_is_covered`,
`test_gap_overlapping_afternoon_by_one_ns_is_not_covered`. Failure line: not
produced for the same namespace block. GREEN line: direct structural probe
printed `manual structural probes passed`; overlap is now half-open:
`gap.started_ns < end_ns and (not gap.resolved or gap.ended_ns > start_ns)`.

Full gate command: `scripts/ci/run_tests_no_egress.sh -q -p no:cacheprovider
tests/unit`; exit code `3`; progress line: none, pytest did not start. Ruff:
Python files command printed `All checks passed!`; the literal six-path command
including `deploy/systemd/family-tally-v2-run.sh` cannot pass because ruff
parses the shell script as Python (`invalid-syntax`). Wrapper syntax:
`bash -n deploy/systemd/family-tally-v2-run.sh` exit `0`. Mypy:
`Success: no issues found in 3 source files`. `git status --porcelain`: the
expected touched files remain modified plus the pre-existing unrelated dirty
whole-tape/current-rung/derived/doc files. Left undone: pytest RED/GREEN and the
full unit gate are blocked by missing OS network namespace support on this host.
