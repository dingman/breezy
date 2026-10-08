# AUT-6 WP3b: discovery-pull bounded-memory redesign (G12), measurement 2026-10-08

Plan r15 section 3.8.1 and WP3b. Method: fresh child processes, interpreter `/home/jon/breezy/.venv/bin/python`,
`PYTHONPATH=<worktree>/src:<worktree>`, reading the real node logs under `~/.local/share/breezy/logs` read-only.
Only the log-reading and parsing functions ran (`poll_node_logs_once`, `find_initial_trigger`,
`_replay_node_active_slugs`). The full pull was NOT run (it calls the venue) and no unit was started.
RSS is `resource.getrusage(RUSAGE_SELF).ru_maxrss`.

## Verify-first record

| Item | Value |
|---|---|
| 10-02 working set (RSS + swap), plan 3.8.1 step 1 | 4.47 GB (`MemoryPeak` 169.6 MB + `MemorySwapPeak` 4.30 GB, `Result=timeout`, ceilings 128M/256M) |
| Largest node log at measurement | `breezy-trade-20261003T165045Z.log`, 1,426,510,025 bytes (1.43 GB); 10-01 log was 1.16 GB at plan time |
| Verdict | old working set > 1 GB: redesign branch taken (baseline already had the O1 historical-stamp skip and line streaming; what still grew was every kept record, the whole-file replay, and non-atomic writes) |

## After the change (new code)

| Scenario | Delta RSS over post-import baseline |
|---|---|
| Production shape: poll with today's window over the real log dir, then trigger-file replay (today's file 93 MB, 3,555 records kept) | 7,280 KiB (7.1 MiB) |
| Same scenario, OLD code (255,559 records kept; whole-file replay) | 579,676 KiB (566 MiB) |
| Stress: the 1.43 GB log read from byte 0 with no historical skip, 1 MiB chunks, 31,102 records kept | 23,888 KiB (23.3 MiB) |
| Child test `test_poll_reads_in_bounded_chunks_not_whole_file` (64 MiB synthetic log) | < 32 MiB (asserted) |

Acceptance: working set <= 1 GB (target <= 256 MiB) holds: the read adds 7.1 MiB in production shape, 23.3 MiB at worst.

## Absolute process peak (sizes the cgroup)

The cgroup counts the whole process, and the nautilus/breezy imports dominate it. Fresh child that imports everything the
pull imports (`scripts.venue.fee_drift_evidence_pull`, nautilus `LiveClock`/`Logger`, the Polymarket.us provider and
discovery config), then runs the production-shape poll and replay (three runs):

| Run | Interpreter start | Post-import | Peak | Read delta |
|---|---|---|---|---|
| 1 | 14,256 KiB | 307,036 KiB | **314,596 KiB** | 7,560 KiB |
| 2 | 14,232 KiB | 305,168 KiB | 312,864 KiB | 7,696 KiB |
| 3 | 14,192 KiB | 306,408 KiB | 313,948 KiB | 7,540 KiB |

Working set used for sizing: 314,596 KiB = 307.2 MiB. `MemorySwapPeak`: 0 expected.

## Unit values chosen

| Directive | Before | After | Derivation |
|---|---|---|---|
| `MemoryHigh` | 128M | **460M** | floor(1.5 x 307.2 MiB) |
| `MemoryMax` | 256M | **512M** | 2 x 307.2 = 614 MiB exceeds the plan's 512M cap, so the cap binds |
| `TimeoutStartSec` | 1800 | **900** | plan 3.8.1 step 6 |
| `TimeoutStopSec` | unset | **5** | r11 LOW-r11-9 |
| timer `OnCalendar` | 16:52 UTC | **17:12 UTC** | out of `[16:30Z, 17:10Z)`; worst end 17:12 + 60 s + 900 s + 5 s = 17:28:05Z |

Note: the 128M/256M ceilings were below the process's own import baseline (about 299 MiB), which is why the old run was
pushed into swap; the new ceilings sit above the measured peak.

## Owed at activation (coordinator)

- capped-run MemorySwapPeak: owed at activation (coordinator). After `daemon-reload` and the first 17:12Z run, expect
  `Result=success`, `MemorySwapPeak=0`, `MemoryPeak` below 460M, and a printed summary.
- `systemctl --user show breezy-discovery-pull.timer -p TimersCalendar` shows 17:12.
- The script's own deadline is still `RELAUNCH_DEADLINE` 17:12Z, so a 17:12 start succeeds only because the node's
  initial summary has been in its log since the ~16:50Z spawn (the first poll finds it); a node that has not launched by
  17:12 yields the existing exit-0 NO-PULL day.
