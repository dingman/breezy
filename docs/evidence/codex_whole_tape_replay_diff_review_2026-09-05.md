# Codex independent review — whole-tape paper replay diff

Task: task-mtojk7wd-yg19h0 (read-only).

**Verdict: REJECT**

1. [HIGH] Paper output is not contained. `--output-root` is arbitrary, and rows/reports write under it without a guard: `scripts/analysis/whole_tape_paper_replay.py:237`, `:322`, `:347`, `:446`, `:586`. Exact fix: resolve `output_root` before any write and refuse unless it is under `derived/paper_replay/`.

2. [HIGH] Replay idempotence sentinel is wrong. Skip checks only `scored_trials_*.parquet` (`:265-266`), but this wrapper writes `mechanism_trials.csv/parquet` (`:338-347`), so reruns overwrite instead of skipping. Exact fix: make the produced artifact and skip sentinel match, with an atomic complete marker.

3. [MED] CORRUPT-only station-days are never populated in `run()`: `corrupt_station_days` is always empty (`:534-538`). Exact fix: derive station-days from CORRUPT instances or fail/report them as unknown, and test through `run()`, not only the helper.

4. [MED] Real-catalog zero replayables could be a silent metadata drop: `_load_clean_instance` swallows missing/non-mapping `instrument.info["climate_date"]` via `continue` (`:485-490`) before the fail-closed `read_weather_bucket_facts` path. Exact fix: parse facts with `read_weather_bucket_facts()` and report/refuse malformed instruments explicitly. The LST conversion itself looks aligned: wrapper imports `_local_hour` (`:42`, `:146`), whose source uses fixed standard offset (`src/breezy/strategy/current_rung_hold/strategy.py:185-191`).

5. [LOW] “Every artifact” caveat is partial: parquet metadata and trial CSV rows carry it (`:316`, `:324`, `:345-347`), but `station_day_counts.csv` does not (`:451-454`). Exact fix: add a `lookahead_caveat` column or a separate caveated counts artifact.

**Plan-Review 1-7**

| Finding | Status | Evidence |
|---|---|---|
| earliest-first-instant winner | SATISFIED | `whole_tape_paper_replay.py:195-233` |
| dual-cover refuse only identical first instant | SATISFIED | `:225-231` |
| single precision arm / no pooled arms | SATISFIED | `:51`, `:376-383` |
| unique work catalog per attempt | SATISFIED | `:247-262`, `:363` |
| caveat on parquet/sidecar; fill-vs-ask surface | PARTIAL | `:316-347`, counts gap `:451-454` |
| per-station QuoteTick coverage filter | SATISFIED | `:128-147`, `:150-174` |
| BLOCKED not no-take denominator | PARTIAL | denominator `:571-578`, corrupt-only gap `:534-538` |

**Test Evidence**

```text
scripts/ci/run_tests_no_egress.sh ... 
exit code 3
error: no usable unprivileged network-namespace mechanism on this host.

TMPDIR=/dev/shm .venv/bin/python -m pytest -q -p no:cacheprovider ...
exit code 2
progress line: none emitted
failure: [breezy] N2 execution-egress firewall barrier: execution-egress module(s) exist but the OS egress firewall is not attested (BREEZY_TEST_OS_EGRESS_BLOCK=1).
```

I did not set `BREEZY_TEST_OS_EGRESS_BLOCK=1` manually because `tests/conftest.py:86-98` documents it as an OS-firewall attestation, not a bypass.


Codex session ID: 01a07233-0aa2-7fb1-bd5a-cbcc238652a1
Resume in Codex: codex resume 01a07233-0aa2-7fb1-bd5a-cbcc238652a1
