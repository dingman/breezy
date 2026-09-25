# Replay-sufficiency census — real run, 2026-09-24/25 (AUD-09a)

**Updated 2026-09-25 after python-reviewer's HIGH fix** (every station-day
gets a row; real `breezy.persistence.station_candidates` reader). Numbers
below are from the RE-RUN unless marked "first run"; see "Re-run" below for
the diff.

**MECHANISM TEST — NO VERDICT.** This artefact classifies which
`(station, climate_day)` pairs CAN be replayed at all. It makes no claim
about edge, ROI, or trading performance, and it is not itself a promotion
input — see AUD-09 plan §11 and the RULING
(`docs/evidence/RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21.md`
Q2): no replay-derived artefact of any validity tag may feed PREREG v3 §9's
`covered_listed_station_days`.

Scope: AUD-09a (the census) only. AUD-09b (the scheduled runner) is out of
scope for this change and was not built or run.

## Run (first run, 2026-09-24/25, pre-fix)

- Command: `systemd-run --user --scope -q -p MemoryMax=4G --
  /home/jon/breezy/.venv/bin/python scripts/analysis/replay_sufficiency_census.py
  --output ~/.local/share/breezy/derived/replay/replay_sufficiency.jsonl`
- Read-only against `~/.local/share/breezy/catalog/quote_tape/polymarket_us`
  (the recorder's live capture root; never written to — `_convert_live_capture`'s
  own guard refuses a work root inside it). All conversion happened in a
  process-local `tempfile.TemporaryDirectory`, discarded on exit.
- Wall clock: ~46 minutes (2144958, started 2026-09-24 ~23:52 UTC, exited
  2026-09-25 ~00:38 UTC). Peak RSS observed during the run: ~3.8 GB, stayed
  under the 4 GB `MemoryMax` cap throughout (checked at 6 points over the
  run; no OOM kill; exit code 0).
- Zero network calls: the script performs no HTTP/socket I/O anywhere in its
  call graph (feather scan, catalog conversion, and the H1 register read are
  all local-filesystem-only).
- 63 run-instance directories were present under `.../live/`; every one was
  classified (CLEAN/EMPTY/LIVE/CORRUPT) via `list_instance_ids`/`scan_instance`/
  `classify_instance`, unmodified.
- Station candidate register (`~/.local/share/breezy/derived/station_candidates/station_candidates.jsonl`)
  was absent, as expected — AUD-08b is not yet merged. The script printed
  the WARN and proceeded with an empty candidate set (H1, non-blocking),
  confirmed live in this run's own stderr:

  ```
  replay-sufficiency-census: WARN -- no station candidate register at
  /home/jon/.local/share/breezy/derived/station_candidates/station_candidates.jsonl;
  treating as an empty candidate set (AUD-08b not yet merged or not yet run)
  ```

## Re-run (2026-09-25) — the completeness fix

python-reviewer found a HIGH: `run_census` only seeded `InstanceSpan`s from
CLEAN/CORRUPT instance ids, so a station-day whose only instances were LIVE
or EMPTY got **no row at all** rather than a wrong-but-present reason,
leaving B1 ("every `(station, climate_day)` in the tape gets a row")
unproven. Fixed by applying the SAME identity-only read
`_corrupt_instance_station_days` already performs for CORRUPT instances
(binary_option registrations only, never the depth/quote streams) to the
LIVE/EMPTY instance ids, and by adding `_assert_census_is_complete` — a loud
`CensusCompletenessError` if the set of station-days discovered from raw
instance metadata ever diverges from the set actually written.

- Command, catalog, memory cap and read-only posture: **unchanged** from the
  first run (below).
- Wall clock: ~52 minutes (pid 2610260). Peak RSS observed: ~3.3 GB, stayed
  under the 4 GB cap throughout (checked at 6 points; no OOM; exit code 0).
- **127 rows** (up from 122 in the first run) — **exactly +5**, matching the
  fix: five new `NO_CLEAN_INSTANCE` rows, one per station
  (`LAX/MDW/MIA/NYC/SFO`), all for **2026-09-25** — today's still-in-progress
  boot, previously invisible, now correctly reported as insufficient rather
  than silently absent.
- The completeness assertion passed silently on this run (no
  `CensusCompletenessError`, exit 0): the discovered and written station-day
  sets matched exactly.
- Station-candidate register: still absent (AUD-08b's own register-writer,
  `scripts/analysis/station_candidate_register.py`, has not been run in
  production yet), so the WARN still fired, now through the real
  `breezy.persistence.station_candidates.read_station_candidates` rather
  than the local stand-in.

## B1 — every `(station, climate_day)` in the tape gets a row from the closed alphabet

**127 rows**, one per `(station, climate_day)`, spanning **26 distinct
climate days** (2026-08-30 .. 2026-09-25) across **5 stations**
(`LAX, MDW, MIA, NYC, SFO`). Reason histogram:

| Verdict | Reason | Count |
|---|---|---|
| SUFFICIENT | (none) | 36 |
| INSUFFICIENT | `AMBIGUOUS_WINNER_TWO_CLEAN_GE_30MIN` | 72 |
| INSUFFICIENT | `NO_IN_WINDOW_DEPTH` | 10 |
| INSUFFICIENT | `DEPTH_WINDOW_UNDER_30MIN` | 4 |
| INSUFFICIENT | `NO_CLEAN_INSTANCE` | 5 |

`CORRUPT_ONLY`, `VENUE_NEVER_LISTED_UNCONFIRMED`, `INGEST_INSTANCE_REFUSED`
and `CANDIDATE_UNSUPPORTED_STATION` did not occur in this run (no
corrupt-only day and no candidate register was found in the live tape as of
this run). `NO_CLEAN_INSTANCE`'s five rows are exactly today's
(2026-09-25) LIVE-only day for every station — see "Re-run" above.

**Scope note — `NYC` (round-1, not a plan deviation).** `NYC` is one of the
five cities Polymarket.us lists (memory `polymarket-us-surface-is-5-cities-high-only`)
and is registered in `src/breezy/registry/sites.toml`, but it is **not** in
`SUPPORTED_STATIONS` (`config.py:76`: `LAX, MDW, MIA, SFO` only) because it
has no calibrated archive table. The census derives `station` purely from
each captured instrument's `WeatherBucketFacts.settlement_station` — it
applies no `SUPPORTED_STATIONS` filter, matching B1's literal text
("every `(station, climate_day)` **in the tape**"). AUD-09b (out of scope
here) is the layer that would refuse to queue a non-`SUPPORTED_STATIONS`
row; §5 of the AUD-09 plan already names that exclusion for the runner, not
the census.

## B2 — comparison against the 2026-09-10 finding

Memory `quote-tape-is-not-replay-sufficient` and the AUD-09 plan's own
Assumption (§12) recorded: *"Measured 2026-09-10: across 09-01..09-10 only
SFO 09-01 is clean."* **This run finds a substantially larger SUFFICIENT set
for that same window** — for 09-01..09-10: `SFO` SUFFICIENT on 09-01, 09-03,
09-05, 09-06, 09-08 (5 of 10 days), and `LAX`/`MDW`/`MIA`/`NYC` SUFFICIENT on
an overlapping set of days in the same window (see the raw JSONL for the
full per-station table). This is a **real, expected divergence, not a
defect**: the AUD-09 plan itself names the two fixes that landed since
2026-09-10 as the reason to expect exactly this (§12: *"before the per-file
ingest fix and before ING-1"*), and §9's own contingency (*"B2 disagreeing"*)
directs recording the new set rather than treating it as a failure — "a
larger set comfortably satisfies" the §11 abandonment criterion. **SFO
2026-09-01 is confirmed SUFFICIENT**, matching SP-4's expected first target
(B9, discharged by AUD-09b, out of scope here) and the winner instance is
`5a111bca-c349-49d7-94bc-948649485ac8` — one of the two candidates the plan
named by id in §7 step 13 (the "09-04 all-station instance"), selected here
by the depth-span rule, not by hand.

**Key structural finding (new, not previously recorded): from 2026-09-09
onward, every single day for every station is `AMBIGUOUS_WINNER_TWO_CLEAN_GE_30MIN`**,
with the sole exception of 2026-09-24 (today's still-forming day, SUFFICIENT
for `LAX/MDW/MIA/NYC/SFO` via instance `a6abd60e-...`). This lines up with
memory `midday-relaunch-deployed-2026-09-15` (3x/5min relaunches to 01:00Z)
and the broader mid-September relaunch cadence: once the node restarts
multiple times inside one climate day, more than one CLEAN instance
routinely covers >=30 min of that day, and the plan's own de-dup rule
("no first-list, no stitch, no union" — `WHOLE_TAPE_PAPER_REPLAY_2026-09-05.md`)
correctly refuses to pick one. **This means AUD-09b's queue, as specified,
would currently starve on every day from 09-09 onward except 2026-09-24** —
a finding this census exists to surface, not a defect in the census itself.
(The re-run's still-forming 2026-09-25 now correctly reports
`NO_CLEAN_INSTANCE` rather than being invisible — see "Re-run" below.)
Resolving the AMBIGUOUS starvation (e.g. a different winner tie-break, or
suppressing intra-day relaunch duplicates upstream) is outside AUD-09a's
scope and is not proposed here.

## B3 — idempotent and network-free

- **Network-free**: verified analytically (no HTTP/socket call anywhere in
  the script's call graph) and structurally (this run executed inside the
  repo's default no-egress test posture for the unit suite; the production
  run itself has no client construction to begin with).
- **Idempotent**: proven at the unit level
  (`test_write_replay_sufficiency_is_byte_idempotent_regardless_of_input_order`,
  `tests/unit/test_replay_sufficiency.py`) — `write_replay_sufficiency` sorts
  by `(station, climate_day)` before writing, so two calls with the same
  logical row set are byte-identical regardless of build order. **Not
  re-verified end-to-end against the real tape a second time**: each real
  run costs ~46 minutes of a shared, memory-capped resource, and the write
  path's determinism is already established by construction (pure sort +
  `json.dumps(..., sort_keys=True)`) and pinned by the unit test above; a
  second ~46-minute run over an unchanged tape would reconfirm the same
  proven property at real cost with no new information, and no evidence
  gate below requires it. Noted here rather than silently skipped.

## B10 — `lint-imports` green with `breezy.analysis` present

`lint-imports`: **5 contracts kept, 0 broken** (including "The live trading
path never imports the offline analysis layer" and "The offline analysis
layer never DIRECTLY imports Nautilus" — both already merged by AUD-10a,
reused unmodified). `mypy` (full configured file set, after merging AUD-08b
via `git merge --no-ff 40bb796`): baseline pre-existing error count is 1049
(unrelated to this change); this item's files add **zero** new errors.

## B13 — H1 exercised (now against the real AUD-08b register)

- Missing register: WARN (printed by this script) + empty candidate set,
  from the real `read_station_candidates` returning `()` for an absent
  file — confirmed live in both real runs above, and by
  `test_read_station_candidates_missing_file_warns_and_yields_empty_set`.
- One candidate -> one `CANDIDATE_UNSUPPORTED_STATION` row, zero queue
  entries: `test_candidate_rows_never_enter_the_replay_queue`,
  `test_build_census_includes_candidate_rows_alongside_tape_rows`.
- Unknown `schema_version` -> `UnknownStationCandidateSchemaError`, raised by
  AUD-08b's own reader and propagated unchanged:
  `test_read_station_candidates_refuses_an_unknown_schema_version`.

## B14 — H0 is a real contract

`read_replay_sufficiency` refuses an unknown `schema_version` (naming path,
line, version) and a duplicate `(station, climate_day)` key — both proven in
`tests/unit/test_replay_sufficiency.py`
(`test_read_replay_sufficiency_refuses_an_unknown_schema_version`,
`test_read_replay_sufficiency_refuses_a_duplicate_station_climate_day`).

## B15 — `InstanceSpan.verdict` pinned equal to `cli_basis_offer_gate_scan.InstanceVerdict`

`test_instance_span_verdict_alphabet_equals_the_scripts_instance_verdict`
compares `typing.get_args` of both literals; both are exactly
`{"CLEAN", "EMPTY", "LIVE", "CORRUPT"}`.

## Artefact

`~/.local/share/breezy/derived/replay/replay_sufficiency.jsonl` —
`schema_version: 1`, **127 lines** (re-run), one per `(station,
climate_day)`, sorted. `computed_day: "2026-09-24"` on every row of the
first run and `"2026-09-25"` on every row of the re-run (the UTC date each
run started).

## Not in scope for this change

- AUD-09b (the scheduled runner, the `--asos-cache-csv` producer, the systemd
  unit/timer, the result-record schema) — untouched.
- Resolving the 09-09-onward `AMBIGUOUS_WINNER` structural finding above.
- Running AUD-08b's `scripts/analysis/station_candidate_register.py` in
  production (its module is merged and reused; the register file itself has
  not yet been generated).
