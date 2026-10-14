# S2 WP6 PMR RE-CHECK of fix 83f47531 (on 2bbcdc1f)

Worktree `.claude/worktrees/maker-s2-wp6`; paths under `scripts/analysis/` unless noted. Blind. Code read plus AST read of the closure test; tests not run.

**VERDICT: APPROVE** (no HIGH; 1 MEDIUM residual, 3 LOW). H1-H3 resolved; M1 and M5 partly, rest resolved.

## Disposition
| id | state | evidence |
|---|---|---|
| H1 listing abstention | RESOLVED | driver `_listing_abstains`/`_wp0` (probe flag OR `rule.listed_in_time`) -> `Wp0.abstained` -> `modes.build_context(abstained=)` -> `station_loop._prepare` (no store, `_no_selector`); counted in `out.listing_abstained` only for replayed days; RED tests driver test :819/:836 |
| H2 ledger/repo-root | RESOLVED | replay.py `ledger=DEFAULT_LEDGER`, `--ledger`/`--repo-root` removed; `package_repo_root()` = git toplevel of `drv.__file__` |
| H3 tail-only licence | RESOLVED (licence) | preflight `mode_of`: parity stations must be in `MAKER_STATIONS` (NYC refused), range fixed. Residual L3 |
| M1 closure root | PARTLY | roots now `station_loop, runio, events_build, adapter, modes, catalog_read`, banned `report/driver/render/preflight/finish/pins`; but `load_truth` still lives in `inputs`, which IS in the closure (`station_loop` imports `UnitHypothesis`). See N1 |
| M2 avoidable voids | RESOLVED | preflight `require_inputs` (cross-check parquet, NBP manifest, spec, uv.lock, node-log dir is_dir), `requested` census completeness, theta, disk, truth sha, all before `claim_verdict_run` |
| M3 census completeness | RESOLVED | preflight `requested`: duplicate key and absent key each raise `FrozenSetRefused` pre-claim |
| M4 bench | RESOLVED | `BENCH_COUNTS=(4,8)` in `mode_of`/`run_bench`; weights restricted to `replays()` keys; all `VARIANTS` run |
| M5 D3 hand-over | PARTLY | `_first_ts` now min over frames, prints, gaps, truncations; still first in-window event, not ledger start; docs aligned and D3 disclosed. Acceptable: slices are window-clipped, so pre-window start is unobservable there |
| M6 no-book / K1 | RESOLVED | adapter `_priced`: `bookable` maps no-book rungs to `None`; `select_rungs` treats None as ineligible; hindsight `wanted_without_book` computed on unrestricted bids, write-only |
| M7 provenance | RESOLVED | finish `_extra_pins`: `episodes_jsonl`, `tail_csv_source` (+ sibling `run_manifest.json`) pinned and rendered in `_pins_block` |
| D1-D8 | ALL PRESENT | render `disclosures_block`: D1, D2 (three abstain reasons separately), D3, D4 (prints floored to 0 and ceil-raised levels per hypothesis), D5 (CLI FINAL proxy, no VOID/UNRESOLVED, inclusive edges, no-FINAL count at any age), D6, D8, listing_abstained, unknown-delta. D7 is in `render_stop_report` (ledger consumed, no label, n_sd=0, rest null, re-run needs new declaration). Disclosures are also in the S-4 stop report |

## Rulings
- **(a) No `station_days.csv` listing column: ACCEPT.** The r4 delta column list (:178-179) has none; S3 consumes `bid_bearing_share_of_covered_listed` = n_sd / covered, where a listing-abstained day is covered and not bid-bearing, which is the correct live behaviour. Cost: the count is not recomputable from the three CSVs, and the row looks like "covered, no eligible rung". LOW: add a `listing_abstain` bool to the row when next the CSV schema is touched.
- **(b) Post-simulation `verify_set_matches_rule`, mismatch = void: ACCEPT.** A mismatch is a defective declaration (two sha-pinned inputs disagree), not a strategy result, so a void (exit 3, no label) is right and a reported STOP would wrongly read as evidence. It is not a forking path: the outcome depends only on the max FINAL date and fixed bytes, never on tmax values or fills. It does burn the one-shot for an error knowable earlier. LOW fix: a dates-only (no tmax) check pre-claim.
- **(c) NEVER_LISTED fixture rows: ACCEPT.** `NEVER_LISTED` is in the S1 `REASONS`; fixture rows carry `covered_bidlive=False`, so they take the `_unreplayed` path, and `requested` needs a row per frozen station x date. Consistent with S1 vocabulary.
- **(d) Empty node-log directory: ACCEPT per delta (d) :115** (no covering file -> `node_log_absent`, kept on PRIMARY, counted, per-row column). The pin lists zero logs, so it is visible. A nonexistent directory is refused pre-claim.
- **(e) No-book rung rule: no K1 interaction left.** A no-book rung is neither priced, ranked, `k1_rung`, nor able to displace a bookable rung; the count feeds only the (r)1 denominator. A rung whose book appears later can become K1 only once it exists, which matches "first-ranked at the first attempt".
- **(f) Restructure leaks/forks: none found.** Truth is parsed only in `report.score` (called by `finish` after `_simulate_all`; `load_tail_truth` only in `run_tail`, which simulates nothing). preflight only hashes the truth. `TYPE_CHECKING` skip in `runio._walk_runtime` is correct (those bodies never run). `RunVoided` is caught before the generic `REFUSALS` in `main`, so exit 3 is preserved. Disclosure counts are loop-collected, not truth-derived. The ledger is no longer caller-choosable. Closure guarantee is weaker than claimed: N1.

## Findings
**N1 [MEDIUM] Name-based closure test does not stop module-attribute access to the truth loader.** `tests/unit/test_maker_stage0_driver.py:672-690` checks only `from X import load_truth|TruthTable|load_tail_truth`. `inputs` is in the loop closure and defines `load_truth` (inputs:323); a loop module doing `from scripts.analysis import maker_stage0_inputs as i; i.load_truth(...)` passes. Today `load_truth` needs the truth path, cross-check and `keys`, which the loop does not hold, and call order is separately tested (:586-600). Fix (cheap): extend the AST scan to flag any `Attribute(attr in TRUTH_NAMES)` and any `Import`/`ImportFrom` of `inputs` as a whole in loop modules; durable fix is moving `load_truth`/`TruthTable` to a truth-only module and banning it from the closure (M1's original fix). Not blocking.

**N2 [LOW] H3 residual.** `--parity` is flag-supplied, not derived from the ladder, and need not equal `fs.stations`; a wrong parity yields wrong bands in a report-only table that a verdict run can embed via `--tail-csv`. Validate parity against the catalog ladder (or pin the parity flag in the tail run manifest).

**N3 [LOW] `tail_reliability.csv` is a derived file not in `CANONICAL_SIDECARS`;** its source is now pinned, so provenance is sufficient. Note only.
