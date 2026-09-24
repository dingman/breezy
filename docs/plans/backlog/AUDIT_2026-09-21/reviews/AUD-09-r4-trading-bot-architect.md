# AUD-09 — Review record (Round 4, FINAL for this cluster)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-09-scheduled-per-station-replay.md
- Plan file sha256: 2812b8b0e02901516d043b198ed308e2a5cf140ab5155a6fa8ceece054d8d3f6
- Round: 4 · Reviewer: trading-bot-architect (scheduling/pipeline/host-resource lens)
- Total: 100/100 · Readiness: READY

## Round-3 defect verification (architect's r3 record read; body checked against source, not §13)

| Defect | Verified fixed, against source I re-read myself? |
|---|---|
| MATERIAL 09-4 — the runner had no named module; H0's Reader and H3's Writer named a shell script as the caller of a Python function; `record_blocked` was an undefined shell helper; B17 parsed the wrapper, which builds no argument vector | YES. §6b.3 now names `scripts/analysis/replay_daily_runner.py` as the module owning: the H0 read (with B14's refusals), target selection under the full key, both subprocess invocations, the `RECOVERED`/`FAILED` crash branch, `record_blocked(reason)` as a function, the row append, and the summary line. `deploy/systemd/replay-daily-run.sh` is restated as owning only `flock`/`say()`/environment resolution and exactly two `"$PY"` invocations. H0's Reader row and H3's Writer row both now name the module. B17 is restated against the module's argument-vector builder (introspected against the driver's own `required=True` parser set) and a new B18 asserts the wrapper contains no JSONL parsing, no `record_blocked`, and exactly two `"$PY"` invocations. |
| MINOR b1 — the producer's output set and its emptiness predicate were two different sets (whole cache vs. windowed rows), with no named boundary helper | YES. §6b.1 states `--out` **is** windowed and names `climate_day_utc_bounds(*, station, climate_day) -> tuple[int, int]`, composed from `default_registry().climate_day_window(...).std_utc_offset_hours` and `breezy.normalize.climate_day.standard_time_zone` — the identical pair `structural_dead_stop._afternoon_window_ns` composes. I re-read `sites.py:135-148` (`ClimateDayWindow`'s docstring: "NEVER DST-aware... local-standard midnight to midnight all year") — matches the plan's quote verbatim, and confirms midnight-to-midnight (not `AFTERNOON_WINDOW_START/END`) is the right bound given `load_replay_observations` consumes the whole replayed day. |
| MINOR b2 — the mypy-entry justification ("would be the only unchecked source package") was false; `src/breezy/app` and `src/breezy/features` are also absent from `[tool.mypy] files` | YES. Re-read `pyproject.toml:159-189` myself: the `files` list is exactly `adapters, normalize, registry, settlement, domain, ingest, persistence, runtime, strategy` plus `scripts/venue`, `scripts/analysis`, `scripts/archive`, `tests` — `src/breezy/app` and `src/breezy/features` are indeed absent and exist on disk. The plan's claim is replaced with the narrower, true reason (H0/H3 contract signatures sit here). |
| MINOR b3 — the producer inherits the hardcoded five-entry `IEM_ASOS_IDS` map, bounding the portability claim | YES. Re-read `settlement_alignment_study.py:65-71` — exactly `KNYC/KSFO/KMIA/KMDW/KLAX`, and the raise at `:647-649` (`RuntimeError(f"no explicit IEM ASOS mapping for {site.icao}")`, confirmed by reading `:640-660`). §12 names the constraint and §6c step 6 states the *second* consequence the plan itself adds beyond the reviewer's finding: the same `load_sites()` also feeds `count_covered_listed_station_days_from_catalog` (`structural_dead_stop.py:237`), so a sixth station would break AUD-08's sufficiency computation and the KILL clock too, not only this producer. |
| TRIVIAL — `load_sites` cited as `:638-659`, actually `:638-658` | YES. Confirmed `def load_sites` at `:638`, `return tuple(sites)` at `:658`. |

No round-3 acceptance is falsely claimed; every disposition matches the body against source.

## Claims verified this round (fresh reads against current source)

| Ref | Claim | Result |
|---|---|---|
| `[tool.mypy] files` list, `src/breezy/app`/`features` absent | CONFIRMED at `pyproject.toml:159-189`. |
| `IEM_ASOS_IDS` five entries, raise site | CONFIRMED at `settlement_alignment_study.py:65-71,647-649`. |
| `ClimateDayWindow` docstring, never-DST-aware | CONFIRMED verbatim at `sites.py:135-148`. |
| `structural_dead_stop.py` imports `MIN_AFTERNOON_STATION_DAYS`, defines the shared constant | CONFIRMED at `:48-61,85`. |
| Runner module and wrapper/module split consistently named across H0, H3, §7 steps, B17/B18 | CONFIRMED by reading the full §6b.3/§6b.4/§7/§8 text — no remaining reference to the wrapper as a Python-function caller. |

## Defects

None found. All four round-3 findings (one MATERIAL, three MINOR, one TRIVIAL) are genuinely
closed. The runner's responsibility table is a real repair, not a rename: every decision the
architect flagged as unreachable from shell (target selection under the full key, the crash branch,
`record_blocked`, the row append) is now named as owned by a Python module with its own RED/GREEN
steps and two acceptance criteria (B17, B18) that test the split from both directions.

## Strengths (credited)

The AUD-09b producer (`asos_cache_csv.py`) closes SP-4's own open blocker rather than carrying it
forward unaddressed, and its "measure before building the timer" discipline (§7 step 3) is the
correct order for a data-availability risk that cannot be resolved by more design work. The
`params_match` divergence recording (B16) and its downstream containment via AUD-10's `C-VALIDITY`
is an honest, mechanically-enforced response to a repeated real failure mode in this repo's history
(memory `bss-headline-is-the-wrong-family`). The b3 fix goes one step further than the finding
required by naming the *second* failure the same root cause produces (the KILL clock), which is
exactly the kind of blast-radius thinking this lens rewards.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | "Scheduled" and "machine-readable" both delivered; SP-4 folded with its blocker discharged by a real producer; the family dimension deferred with a named owner rather than assumed complete. |
| Technical correctness and evidence grounding | 20 | 20 | Every citation I re-opened this round is exact, including the two false/imprecise claims from round 3 (mypy justification, `load_sites` line range) which are now both correct. |
| Implementation specificity and feasibility | 15 | 15 | Runner module named with a full responsibility table; wrapper reduced to flock/env/two invocations; producer's window boundary given a named helper; command block complete and testable. |
| Acceptance criteria and validation quality | 20 | 20 | B1–B18 objective; B17 targets the actual vector-builder; B18 pins the split from both sides; B14 distinguishes an unreadable work list from an empty queue. |
| Autonomous operation, failure handling, recovery | 15 | 15 | `ASOS_CACHE_EMPTY` first-class; crash recovery via the JSONL-row completion marker; duplicate-key hard error; skip-not-kill flock; own-cgroup OOM; timer gated on a non-`BLOCKED` first run. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | Mechanism-vs-edge separation on two independent grounds; deferred driver change named with an owner; PREREG barrier untouched; abandonment criterion with a stated adjustment; IEM-map constraint recorded rather than absorbed. |
| **Total** | **100** | **100** | |

## Required changes to reach 100

None.

## Blockers (recorded, not scored)

- **Evidence/data availability (build):** whether the settlement-alignment cache holds ASOS rows
  for SFO 2026-09-01. Measured at §7 step 3 before the runner is built, with both outcomes
  pre-defined (B9). No plan change can resolve it.
- **Deferred change with a named owner:** a challenger family cannot be replayed until
  `current_rung_hold_paper_replay.py` grows `--family-manifest`. Excluded from scope, mirrored in
  AUD-10 §12.
- **Strategy lead:** R1 `trial_id` provenance, and whether a `MECHANISM_ONLY` replay result may be
  cited in a PREREG v3 §9 context (default: no). Neither is decided in-plan, correctly.
