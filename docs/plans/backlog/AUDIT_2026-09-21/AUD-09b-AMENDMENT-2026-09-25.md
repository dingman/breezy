# AUD-09b AMENDMENT 2026-09-25 — Rev 2

Target: `docs/plans/backlog/AUDIT_2026-09-21/AUD-09-scheduled-per-station-replay.md`. The coordinator's final status there reads READY, sha `32a2d759…`. Rev 1 was reviewed by three peers: architect REQUEST_CHANGES, trading-bot-architect REQUEST_CHANGES, python-reviewer MEDIUM. This Rev 2 replaces Rev 1 in full. It needs a re-review before any build starts.

## 0. Verdict

- The problem Rev 1 was asked to solve, "relaunch fragments make every day AMBIGUOUS", **is mostly the wrong explanation**. The more likely primary cause is that the census's in-window test checks only the hour, not the date (F3).
  - The 09:00Z daily rotation gives every climate day two instances.
  - For a market listed the day before, the pre-rotation instance holds D-1's afternoon and the post-rotation instance holds D's afternoon.
  - A filter that checks only the hour counts both.
- **Order of work is now staged (YAGNI):**
  - **Stage A:** date scoping, explicit serialisation, cache, a diagnostic dump, and the window-edge fields.
  - **Stage 0:** a measured run.
  - **Stage B:** the overlap rule and FRAGMENT reporting. Built **only if** Stage 0 finds same-date, non-overlapping CLEAN fragments that are each ≥30 min.
- The reviewer's overlap rule is **unsafe without date scoping** (F2). It is kept only as the Stage B design.

## 1. Findings

| # | Finding | Evidence | Conf. |
|---|---|---|---|
| F1 | AMBIGUOUS starts before the relaunch deploy. LAX/SFO from 09-09; MDW/MIA/NYC on 09-05 and from 09-11. The mid-day relaunch deployed 09-15 15:07Z (eed0f4c). | `replay_sufficiency.jsonl` (127 rows, read in full) | High |
| F2 | **Harmful without date scoping (P1).** 69/72 AMBIGUOUS rows have a best span ≥294/300 min, so any second ≥30-min span *on the same date* must overlap it by ≥24 min. Those second spans are therefore either on another date or genuine overlaps. Today's hour-only spans put D-1's and D's afternoons into one "window", and those two never overlap. The overlap rule would then mark such rows SUFFICIENT, and the longest-span winner could be the **D-1** instance. That means replaying a D market on D-1's afternoon: the look-ahead shape in memory `implausible-result-is-a-leak`. Date scoping must land in or before any change to the winner rule. | JSONL; `census.py:212-214,265-271` | High |
| F3 | **The census window checks the hour only.** `_in_decision_window` compares `_local_hour` only. Instruments are date-filtered (`run_weather_strategy_backtests.py:1340`), but their depth rows are not, and the tape spans D-1..D+1. The recorder restarts at 09:00Z daily (`breezy-quote-tape-rotate.service:55`, `try-restart`), and a new `live/<instance_id>/` opens on every start (same file :3-4). So each climate day meets two instances; a day-ahead listing gives the earlier one D-1 afternoon depth for the D market. Whether this explains F1's onset dates depends on when the timer deployed and when listings went day-ahead; **Stage 0 checks this.** | source read | High (mechanism) / Med (onset) |
| F4 | **The census cannot fit the 09b unit.** The real census ran 46 and 52 min at 3.8 and 3.3 GB peak. The 09b unit allows `TimeoutStartSec=1800` under `MemoryHigh=3G/MemoryMax=4G`, and the wrapper runs the census first. A 15:50 start would also run past 16:35Z. The wall time may be inflated by MemoryHigh throttling (L-49); Stage 0 records CPU time to separate the two. | census evidence doc; plan :684-693 | High |
| F5 | AUD-10a already merged the `analysis` layer and both forbidden contracts. 09b must not add them again. | census doc B10 | High |
| F6 | **The a09a branch predates the integration fixes.** It carries `asdict` in `replay_sufficiency.py:274`, plus stale `station_candidates.py` `asdict` uses that integration fixed in a32a7f9 ("credential guard"). | python-reviewer; commit msg | High |
| F7 | **A replayed day can silently change underneath its row.** A LIVE instance that later turns CLEAN, or a rule change, can flip an already-replayed key to AMBIGUOUS or change its winner. The queue key ignores `tape_instance_id`, so the old row would stand unnoticed. | `census.py:362-372`; plan H3 key | High |
| F8 | **Census and KILL clock share only the window.** The KILL clock counts every depth instant across rungs of the merged `data/` catalog, applies no executable-ask filter, and subtracts resolved `QuoteTapeGap`s (`structural_dead_stop.py:163-216`). The census counts per instance, executable asks only (`best_order`), with no gap handling. The census docstring's "cannot disagree about covered" is an overclaim; it will be corrected to "shares the window definition". | source read | High |

**Explanations to be tested in Stage 0:**
- **H-A (likely):** the second span is another date's afternoon (F3). Date scoping alone clears the row to SUFFICIENT under the **existing** rule.
- **H-B:** two recorder processes wrote concurrently. The **trade node is refuted** as the second writer: `build_trade_node_config` docstring, `node_config.py:846-848`, *"No streaming. The recorder writes the tape; the trader does not."*
  - A systemd `Restart=always` / `try-restart` cycle is stop-then-start and cannot overlap by itself.
  - Remaining candidates: a legacy `tape_supervisor.sh` / `tape_supervisor_k1.sh` orphan running alongside the unit around the G-14 cutover (`breezy-quote-tape.service:3-6,74-75,95-97`), or an unclean handoff whose boot-snapshot `ts_event` predates the predecessor's last event.
- **H-C:** same-date, non-overlapping restart fragments, each ≥30 min. This is the only case that needs Stage B.

## 2. Stage A + Stage 0 (build these first; everything else waits on the Stage 0 result)

**Precondition P0:**
1. Merge integration (≥ `6398d43`, which contains a32a7f9) into `backlog/aud-09a-replay-sufficiency-census-2026-09-24`.
2. Re-run `lint-imports`, the credential-guard test and the 09a unit tests.
3. Only then apply Stage A. 09a is unmerged, so Stage A lands on that branch before it merges.

**Stage A changes (09a code)**

- **C1 (date-scoped window, pure core):** add `decision_window_ns(*, climate_day: dt.date, std_utc_offset_hours: float) -> tuple[int, int]` to `src/breezy/analysis/replay_sufficiency.py`.
  - It uses integer arithmetic only: `(dt.datetime.combine(d, time(12), tz) - EPOCH) // timedelta(microseconds=1) * 1000`, and the same for 17:00.
  - This avoids `_afternoon_window_ns`'s `timestamp()*1e9` float path (`structural_dead_stop.py:153-154`).
  - The public `ma_prelock_winner_ask_study.in_afternoon_window` (`:201`) is the **test oracle** (test A2). It is not called in the loop, because a datetime conversion per depth row over millions of rows is avoidable cost.
- **C1b (pure extent):** `window_extent(ts_event_ns: Iterable[int], *, start_ns: int, end_ns: int) -> WindowExtent` returns `first_ns`, `last_ns`, `span_ns`.
  - Half-open window. `first`/`last` are `None` when there are no events; `span_ns = 0` when there are fewer than 2.
  - `_discover_clean_spans` calls it with the executable-ask `ts_event`s (`best_order(depth.asks) is not None`, unchanged). The script keeps only I/O (L-24).
  - `_in_decision_window` and `_WINDOW_*_HOUR_LST` are deleted.
- **C2a (row fields):**
  - `InstanceSpan` gains `first_in_window_ns: int | None` and `last_in_window_ns: int | None`. `depth_window_minutes` is derived for reporting only; comparisons use `span_ns`.
  - `ReplaySufficiency` gains `window_start_ns: int`, `window_end_ns: int`, `winner_first_in_window_ns: int | None`, `winner_last_in_window_ns: int | None`, and `window_complete: bool`.
  - `window_complete` is true iff `winner_first − window_start ≤ WINDOW_EDGE_TOLERANCE_NS` **and** `window_end − winner_last ≤ WINDOW_EDGE_TOLERANCE_NS`, with `WINDOW_EDGE_TOLERANCE_NS = 5 min`. A lone 13:00-13:40 winner is therefore `window_complete=False`.
  - **Residual:** gaps inside the window are not detected, because this check looks only at the edges. Gaps are what the `QuoteTapeGap` records cover, and the census does not read them (F8). Stage 0 reports the edge-distance distribution; 5 min is re-reviewed if real complete days miss it.
  - `REPLAY_SUFFICIENCY_SCHEMA_VERSION = 2`, because the meaning of the spans changed. The reader refuses v1.
- **C3 (LIVE count, B7):**
  - `live_instance_count` counts a LIVE instance for `(s, d)` only if its capture start is before `window_end_ns`. Capture start = min `ts_init` of its `binary_option` registration rows, read through the same identity-only path `_corrupt_instance_station_days` uses, extended to return the minimum.
  - Registration rows span D-1..D+1, so registration alone must not count.
  - Stage 0 checks the count against journal instance start times before R1 relies on it.
- **C4 (explicit serialisation; exact JSON shape, pinned):**
  - `ReplaySufficiency.to_dict() -> dict[str, object]` emits every field by name. Types: `str` / `int` / `bool` / `None`; timestamps are integer ns; `depth_window_minutes` and `quote_window_minutes` are floats. No `asdict`.
  - `ReplaySufficiency.from_dict(payload: Mapping[str, object])` raises `ReplaySufficiencyRecordError` naming the key on any missing key, extra key, or wrong type. It never calls `**payload`.
  - If Stage B adds `excluded_fragments`, the JSON is `list[{"instance_id": str, "first_in_window_ns": int, "last_in_window_ns": int}]`, sorted by `(first_in_window_ns, instance_id)`, and reconstructed as `tuple[FragmentSpan, ...]`, where `FragmentSpan` is `@dataclass(frozen=True, slots=True, kw_only=True)` with exactly those three fields.
- **C6 (on-disk per-instance span cache):**
  - Why on disk and not an in-process memo: the census is a fresh process every night and the cost is paid again on every run. An in-process memo removes nothing.
  - Location: `~/.local/share/breezy/derived/replay/instance_spans.jsonl`, with `INSTANCE_SPANS_SCHEMA_VERSION = 1`. Atomic whole-file rewrite. Refuses an unknown version.
  - Key: `(instance_id, fingerprint, SPAN_ALGO_VERSION)`. `fingerprint` is the sha256 of sorted `(relpath, size, mtime_ns)` over the instance's files. The value is the instance's `(station, climate_day) → InstanceSpan` map.
  - **Only CLEAN instances are cached.** LIVE, EMPTY and CORRUPT are recomputed every run and never written.
  - A fingerprint mismatch recomputes; a `SPAN_ALGO_VERSION` bump invalidates all entries.
  - **Residual (pinned by test A7):** an edit that preserves both size and mtime is not detected.
- **D1 (diagnostic dump; read-only, not a contract):**
  - `--dump-instance-extents PATH` writes one line per `(station, climate_day, instance_id)`: `verdict`, `first/last_in_window_ns` as LST, instance capture start, and pairwise overlap in ns against every other CLEAN instance for the same key.
  - It feeds Stage 0 only. It is not versioned or consumed, and it is deleted with Stage B or after Stage 0.

**Stage 0 (hand run; the cost baseline for F4 and B26)**
1. Run in a quiet window: not 13:30/15:00/15:20/22:30/22:45Z, and not inside [16:35Z, 01:15Z). Command:
   `systemd-run --user --slice=breezy-studies.slice -p MemoryMax=6G --wait --collect /usr/bin/flock -w 600 "$XDG_RUNTIME_DIR/breezy-studies.lock" /usr/bin/time -v .venv/bin/python scripts/analysis/replay_sufficiency_census.py --dump-instance-extents <scratch>/extents.jsonl`
   This is a **cold** cache run. Record wall time, **user+sys CPU**, and max RSS.
2. Run it again the **same UTC day**, so `computed_day` matches, as a **warm** run. `sha256sum` both `replay_sufficiency.jsonl` outputs; they must be byte-identical (B25). Record warm wall, CPU and RSS.
3. For every row that was AMBIGUOUS on 09-25, classify it:
   - H-A: now SUFFICIENT, with the other instance's events on another date.
   - H-B: overlap above 60 s on the same date. Correlate with `journalctl --user -u breezy-quote-tape` start/stop times and any orphan-supervisor evidence.
   - H-C: same date, disjoint, both ≥30 min.
   Also record the rotate timer's deploy date against F1's onset.
4. Report the distribution of `window_complete`, and verify `live_instance_count` against journal start times.
5. **Decide:**
   - **Zero H-C rows:** Stage B is **not built**. B27 reduces to `window_complete`.
   - **Any H-C rows:** build Stage B.
   - **H-B rows:** they stay AMBIGUOUS. Open a capture item for the concurrent writer, owned by the recorder owner. Never relax the rule to pick between overlapping writers.

## 3. Stage B (conditional on H-C): the overlap winner rule

- **Eligible:** CLEAN with `span_ns ≥ MIN_DEPTH_WINDOW_NS` (30 min), using C1's date-scoped extents only.
- **Overlap(i, j):** `min(last_i, last_j) − max(first_i, first_j)`. The pair overlaps iff this exceeds `OVERLAP_TOLERANCE_NS = 60 s`.
  - Touching or separated intervals are disjoint. The check is pairwise.
  - 60 s is far below 30 min, so a real duplicate can hide at most 60 s. It is above zero to absorb a boot-snapshot `ts_event` at handoff.
  - Stage 0's overlap list justifies the value; any change goes through review.
- **Classification:**
  1. No CLEAN instance: unchanged.
  2. Any eligible pair overlaps: `AMBIGUOUS_WINNER_OVERLAPPING_CLEAN_GE_30MIN`, replacing the old token, which becomes false text under this rule.
  3. Otherwise, if at least one instance is eligible: SUFFICIENT. The winner is the first instance after sorting by `(−span_ns, first_ns, instance_id)`.
  4. Else: `DEPTH_WINDOW_UNDER_30MIN` / `NO_IN_WINDOW_DEPTH`.
- **Invariant:** the result is identical for every permutation of the input.
- **Hours from non-winning fragments are never replayed.** There is no stitch or union: the driver takes one `--tape-instance-id`, per the base plan and the Nautilus null hypothesis. The loss is recorded:
  - `coverage_kind ∈ {"WHOLE", "FRAGMENT"}`. FRAGMENT iff any other CLEAN instance, of any span, has a date-scoped event outside `[winner_first, winner_last]`.
  - `excluded_fragments` in C4's pinned shape.
  - Schema moves to v3.
- **Runner additions:**
  - **R2:** the result row gains `sufficiency_coverage_kind` and `excluded_fragment_count`.
  - **R3:** the summary line prints `coverage_kind`.

## 4. 09b runner changes (always; independent of Stage B)

- **R1 selection:**
  - Build `dict[(station, climate_day)] → row` from `read_replay_sufficiency`.
  - Eligible: SUFFICIENT, `live_instance_count == 0`, `station in SUPPORTED_STATIONS` (drift: the census emits NYC rows; base §5 excludes them from the queue), and no result row under the full key.
  - Order by an explicit sort on `(climate_day, SUPPORTED_STATIONS.index(station))`, never file order.
- **R2 row fields:** add `window_complete`, `replayed_first_ns`, `replayed_last_ns`, `census_schema_version`. `REPLAY_RESULTS_SCHEMA_VERSION` stays 1 because nothing has shipped.
- **R3 summary line:** "replayed [hh:mm, hh:mm] LST of [12:00, 17:00); window_complete=…". A replay is never described as full-day unless `window_complete` is true.
- **R4 provenance-drift check (resolves F7):**
  - Every run, before selection, compare every existing `replay_results` key with the current census row for `(station, climate_day)`. A key is **drifted** iff that row is no longer SUFFICIENT or its `winner_instance_id ≠ tape_instance_id`.
  - Write the drifted set to `~/.local/share/breezy/derived/replay/replay_drift.jsonl` (versioned, atomic whole-file rewrite, sorted).
  - For each key **new** to the set compared with the previous file, emit one `BREEZY_REPLAY_PROVENANCE_DRIFT` alert through `resolve_alert_sink` / `emit_alert`: severity warning, detail = key + old/new verdict and winner, no path. The durable dedupe is the previous file, so each drifted key alerts once.
  - Drifted keys are not re-replayed (the key is unchanged; B11 holds).
  - AUD-10 must refuse drifted keys (B27).
  - A raising sink never changes the exit code.
- **R5 unit:** 15:50, 3G/4G, 1800 s, as specified. The timer is enabled only after (a) a real non-BLOCKED row **and** (b) B26: the Stage 0 warm census plus one replay fits the unit (wall < 900 s, peak < 3 GB).

## 5. Citability under the ruling

- **Every 09b row is `MECHANISM_ONLY`.** It is written only from `REPLAY_VALIDITY` (B7). The ruling text:
  - **Q2 item 1:** *"a `MECHANISM_ONLY` replay result may never feed any promotion criterion requiring an edge statistic."*
  - **Q2 item 2:** *"no replay-derived artefact — of any validity tag … — may ever be read by, substituted into, or used to corroborate PREREG v3 §9's structural-dead test."*
  - So a partial or fragment replay is citable only as mechanism evidence (take-rate, fill vs book, refusal histogram), only for the interval it replayed, never as edge, and never for §9.
- **Gap in the ruling:** Q2 item 3 admits `params_match == true` rows to `C-ESTIMATOR/C-N/C-PAIRED` once `validity` flips. It is silent on coverage.
- **Decision (fail-closed; stricter than the ruling, so no new ruling is needed):** an edge criterion additionally requires:
  - `window_complete == true`;
  - `coverage_kind == "WHOLE"` when that field exists (Stage B);
  - the key not being in the drift set.
- **Why:** a partial window is selection bias. `trial_day_consumed` allows one trial per station-day, so a replay starting late can take where the full day would have consumed or refused earlier.
- **Owner:** AUD-10 (`C-VALIDITY`), by id (B27). The Q1 item 8 caveat still ships unchanged.

## 6. Tests to write first (RED list)

**Stage A** (`tests/unit/test_replay_sufficiency.py`, `tests/unit/test_replay_sufficiency_census.py`)
- A1: `window_extent` excludes a D-market event at 14:00 LST on **D-1**, includes 14:00 on D, and returns `None` with no events.
- A2: for all 5 stations, `decision_window_ns` bounds agree with the `in_afternoon_window` oracle at start−1 ns, start, end−1 ns and end (half-open, integer).
- A3 **(ARCH B2):** a D-market instance with depth only on D-1's afternoon plus one on D's afternoon gives SUFFICIENT with the **D** instance as winner under the existing rule; the D-1 instance contributes no in-window events.
- A4: a lone 13:00-13:40 winner gives `window_complete=False`; a 12:02-16:58 winner gives True; each edge tested exactly at the 5-min boundary.
- A5: C4 round-trip is lossless. `from_dict` raises on a missing key, an extra key and a wrong type. The reader refuses v1.
- A6: cache hit reuses spans; a fingerprint mismatch recomputes; a `SPAN_ALGO_VERSION` bump invalidates; LIVE/CORRUPT/EMPTY are never written; cold and warm runs over a fixture with the same `computed_day` are byte-identical.
- A7 **(residual pin):** an edit that keeps size and restores mtime (`os.utime`) is **reused**. The test is named to document the known gap.
- A8: a LIVE instance counts toward `live_instance_count` only if its capture start is before `window_end_ns`; a LIVE instance whose registration covers D+1 but which started after W does not count.
- A9: per-module pin that `replay_sufficiency.py` does not use `dataclasses.asdict`.
- A10: `_discover_clean_spans` calls `window_extent`, checked through a stub-injected seam rather than by re-implementing it.

**Runner** (`tests/unit/test_replay_daily_runner.py`; every fixture written through the real v2 `write_replay_sufficiency`, per L-42)
- R-a: a shuffled census file gives the same target.
- R-b: `live_instance_count > 0` is never selected.
- R-c: NYC SUFFICIENT is never selected.
- R-d: the row carries the R2 fields, and the summary contains the replayed LST interval and `window_complete`.
- R-e **(DOMAIN 2):** a replayed key whose census row flips SUFFICIENT→AMBIGUOUS, or changes winner, is written to `replay_drift.jsonl` and emits exactly one `BREEZY_REPLAY_PROVENANCE_DRIFT`. The next run with the same drift emits none. A raising sink leaves exit 0. The key is not re-replayed.
- Existing B11-B20 tests are unchanged.

**Stage B only:**
- B-a: overlap >60 s gives AMBIGUOUS; exactly 60 s and touching intervals are disjoint.
- B-b: disjoint 12:00-14:00 and 14:05-17:00 give SUFFICIENT, the longer wins, FRAGMENT, and `excluded_fragments` has C4's shape.
- B-c: a single instance plus a disjoint 10-min fragment gives FRAGMENT.
- B-d: the tie-break order.
- B-e: every permutation of 4 spans gives an identical row.
- B-f: the old token is absent.

## 7. Acceptance criteria (added to B1-B20)

| # | Criterion | Evidence |
|---|---|---|
| B21 | Census and KILL clock share the **window definition only** (A2). The remaining differences (per-instance vs merged catalog; executable-ask filter; no gap subtraction) are named in the census docstring, and the "cannot disagree" claim is removed. | A2 + docstring diff |
| B22 | Winner choice and runner selection do not depend on input order | R-a (+B-e) |
| B23 | Every SUFFICIENT row carries `window_complete` and the winner interval; every replay summary states the replayed LST interval (+`coverage_kind` if Stage B) | A4, R-d, step-13 row |
| B24 | Stage 0 report: every previously-AMBIGUOUS row classified H-A/H-B/H-C with extents, the journal correlation, the rotate-timer date, and the build/skip decision for Stage B | new evidence doc |
| B25 | Cold and warm census runs, **same `computed_day`**, byte-identical | two `sha256sum`s |
| B26 | Warm census plus one replay fits the unit (<900 s wall, <3 GB peak); the cold 6G run is the recorded cost baseline, **with CPU time** | `time -v` + journal |
| B27 | AUD-10 `C-VALIDITY` amended: refuse `window_complete=false`, `coverage_kind≠WHOLE` (if present), and drifted keys | AUD-10 plan diff |
| B28 | A drifted provenance alerts exactly once per key and never re-replays | R-e |

B2 is re-baselined: the SUFFICIENT set **will** change, and the difference is recorded, not absorbed.

## 8. Must the census be re-run? Yes

- Schema v2 and date scoping change the spans and the verdicts; the 09-24/25 artefact is superseded, and the runner refuses v1 by design.
- The Stage 0 cold and warm runs are the re-run.
- Evidence doc: `docs/evidence/replay_sufficiency_census_<date>_v2.md` with the B1 histogram, the B2 diff against 09-25, B24, B25 and the B26 baseline. It should also show SFO 09-01's winner, with the reason if it is no longer `5a111bca…`, plus both caveats (MECHANISM TEST — NO VERDICT; the Q2 §9 bar).

## 9. Risks

- **H-B is dominant:** the queue stays small and the problem becomes a capture item. Stage 0 detects this on day one, and base §11 applies immediately.
- **The 5-min edge tolerance and 60-s overlap tolerance may be mis-set:** both are measured in Stage 0 and changed only through review. Gaps inside the window remain undetected (§2 C2a residual).
- **Cache staleness:** covered by the fingerprint and algo version. The size-and-mtime-preserving edit is an accepted residual, pinned by A7.
- **Driver date scoping:** `assert_decision_window_has_coverage` (`current_rung_hold_paper_replay.py:299-302`) also checks only the hour, and the driver is excluded here (§5). If the strategy acts on a D market during D-1's afternoon, that is look-ahead and belongs to AUD-11 (by id). R2's `replayed_first/last_ns` make it visible.
- **Cold census cost:** 3.8 GB against a 4G cap. Cold runs happen only by hand at 6G; the nightly unit only ever runs warm (B26 gate).
- **The drift alert is noisy after a planned rule change:** a Stage B build or a `SPAN_ALGO_VERSION` bump can drift many keys at once. Each key alerts once, which is accepted as visibility. The evidence doc must list the expected drift before deploy.

## 10. 09b remaining scope (base plan, restated with drift)

1. **P0:** merge integration into the 09a branch (F6), then Stage A (C1-C4, C6, D1) with its tests, then Stage 0, then merge 09a.
2. **Stage B:** only if Stage 0 finds H-C.
3. **ASOS producer** `asos_cache_csv.py`: unchanged (§6b.1). Step 3 re-measures SFO 09-01 with the real producer (the 09-21 grep found 313 rows).
4. **`replay_results.py`:** H3 plus the R2 fields; `REPLAY_VALIDITY` unchanged.
5. **`replay_daily_runner.py`:** the base responsibility table (H0 read, B17 vectors, RECOVERED/FAILED, `record_blocked`, B19 stall alert, B20 `family_id` + `manifest_sha256`), plus R1, R3 and R4.
   - Re-verify B16's expected `params_match=False` (driver 0.06 vs manifest 0.0695) at build, since AUD-12b and the fee-theta work have landed.
6. **Wrapper and unit:** as specified, plus the B18 property. **Drift:** the census step is viable only with a warm cache (B26).
7. **Drop:** the pyproject layers/contracts and the mypy entry (F5; confirm with `lint-imports`).
8. **Step 13 real run:** in a quiet window, on the census's own pick. Evidence doc with both caveats plus the interval sentence.
9. **Timer:** enabled only after a non-BLOCKED row **and** B26. Then ratchet B5 at 2×.
10. **Owned elsewhere, by id:** AUD-19a/b, AUD-11/12, AUD-10 (H3 and B27), AUD-08b (H1). **Conditional:** a capture item if Stage 0 finds H-B.

## 11. Rev 2 dispositions

| Review item | Disposition | Where |
|---|---|---|
| ARCH B1 `window_complete` | Accepted. New field; AUD-10 requires `window_complete` AND WHOLE | §2 C2a, §5, B23/B27, A4, R-d |
| ARCH B2 F2 direction; C1 first; D-1/D test | Accepted. F2 restated as "harmful without P1"; C1 lands in Stage A before any rule change; test added | §1 F2, §2 C1, A3 |
| ARCH B3 staged build; cache justified; never cache LIVE/CORRUPT; B25 same `computed_day` | Accepted. Stages A → 0 → B; on-disk cache justified (fresh process per night); CLEAN-only; same-day cold and warm runs | §0, §2, §3, A6, B25 |
| ARCH B4 lock, slice, CPU time, cost baseline | Accepted | §2 Stage 0 step 1, B26 |
| ARCH B5 window-only claim; public oracle; integer bounds | Accepted. Integer `decision_window_ns`; `in_afternoon_window` is the test oracle, not called per row (per-row cost); differences named | §1 F8, §2 C1, A2, B21 |
| ARCH B6 pure function; real writer; per-module pin | Accepted | §2 C1b, A1, A9, A10, §6 runner note |
| ARCH B7 LIVE count meets W | Accepted. Counted by capture start before `window_end`; verified in Stage 0 | §2 C3, Stage 0 step 4, A8 |
| DOMAIN 1 H-B refuted for the trade node | Accepted, verified at `node_config.py:846-848`. H-B rewritten; journal correlation added. The recorder's systemd restart is stop-then-start and cannot overlap by itself | §1 hypotheses, Stage 0 step 3 |
| DOMAIN 2 F7 drift alert | Accepted. R4 drift set plus one alert per key | §4 R4, R-e, B28, B27 |
| DOMAIN 3 pin cache residual | Accepted | §2 C6, A7, §9 |
| PY 1 merge integration first | Accepted as precondition P0; F6 raised to High | §1 F6, §2 P0, §10 item 1 |
| PY 2 pin nested JSON shape | Accepted | §2 C4 |
| New since Rev 1 | The daily rotation (`breezy-quote-tape-rotate.service:55`) is the concrete mechanism for H-A. Two-instance restarts are sequential under systemd, which lowers the prior on H-B | §1 F3 |

## 12. Confidence (updated)

| Claim | Conf. | Basis |
|---|---|---|
| F1, F4, F5 | High | read from artefacts and the plan |
| F2 (hour-only spans make the overlap rule pick the wrong day) | High | arithmetic on the JSONL plus the source of the window filter |
| F3 mechanism (hour-only filter plus daily rotation gives two instances per day) | High | source read (census, rotate unit) |
| H-A is the dominant cause | Medium | fits rotation plus day-ahead listing; not measured; Stage 0 decides |
| Stage B will be needed | Low-medium | mid-window restarts exist (09-09 incident), but ≥30-min fragments on both sides are unmeasured |
| Tolerances (5 min edge, 60 s overlap) | Medium | reasoned bounds; measured in Stage 0 |
| C6 cache design | Medium-high | CLEAN instances are closed; on-disk storage is needed across processes |
| Citability answer (always MECHANISM_ONLY; never §9; edge only if window complete, WHOLE and not drifted, after the flip) | High | Q2 items 1-3 quoted; the added bar is stricter, so no new ruling is needed |
| Queue unstarves after Stage A | Medium | depends on H-A dominating |

Overall: **high** on the findings and the staging; **medium** on the outcome until Stage 0 runs.

Files cited:
- `/home/jon/breezy/docs/plans/backlog/AUDIT_2026-09-21/AUD-09-scheduled-per-station-replay.md`
- `/home/jon/breezy/docs/evidence/RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21.md`
- `/home/jon/breezy-a09a/src/breezy/analysis/replay_sufficiency.py`
- `/home/jon/breezy-a09a/scripts/analysis/replay_sufficiency_census.py`
- `/home/jon/breezy-a09a/docs/evidence/replay_sufficiency_census_2026-09-24.md`
- `/home/jon/.local/share/breezy/derived/replay/replay_sufficiency.jsonl`
- `/home/jon/breezy/src/breezy/runtime/node_config.py`
- `/home/jon/breezy/deploy/systemd/breezy-quote-tape.service`
- `/home/jon/breezy/deploy/systemd/breezy-quote-tape-rotate.service`
- `/home/jon/breezy/scripts/analysis/structural_dead_stop.py`
- `/home/jon/breezy/scripts/analysis/ma_prelock_winner_ask_study.py`
- `/home/jon/breezy/scripts/analysis/current_rung_hold_paper_replay.py`

## Rev 2.1 (coordinator, 2026-09-25) — binding corrections from the round-2 review

Round 2: architect REQUEST_CHANGES (minor; B1–B7 confirmed resolved), trading-bot-architect APPROVE (8.5/10; F3 rotation mechanism independently verified). These corrections supersede the text above where they conflict; with them the amendment is APPROVED.

1. **Stage 0 command (§2 step 1).** Run from the AUD-09a worktree with its code, never the primary tree's, and never overwrite the v1 baseline:
   - First `cp ~/.local/share/breezy/derived/replay/replay_sufficiency.jsonl <scratch>/replay_sufficiency_v1_2026-09-25.jsonl` (the B2 diff baseline).
   - `systemd-run --user --slice=breezy-studies.slice -p MemoryMax=6G -p WorkingDirectory=/home/jon/breezy-a09a -E PYTHONPATH=/home/jon/breezy-a09a/src --wait --collect /usr/bin/flock -w 600 "$XDG_RUNTIME_DIR/breezy-studies.lock" /usr/bin/time -v /home/jon/breezy/.venv/bin/python scripts/analysis/replay_sufficiency_census.py --output <scratch>/replay_sufficiency_v2_cold.jsonl --dump-instance-extents <scratch>/extents.jsonl`
   - Precede it with a one-line import check printing `breezy.analysis.replay_sufficiency.__file__` (must be under /home/jon/breezy-a09a). If `--output` does not exist, Stage A adds it.
2. **C3 LIVE capture start.** Do NOT extend the shared `_corrupt_instance_station_days` (it merges all instances into one set and is shared with the whole-tape driver and the CORRUPT path; unchanged per base plan). Add a census-local helper that calls `_load_stream([one_instance_dir], "binary_option", BinaryOption)` per LIVE instance and returns `(station_days, min_ts_init)`. Registration `ts_init` may be listing time rather than capture time; that errs toward over-counting (fail-closed), and Stage 0 step 4's journal check is the guard.
3. **A2 oracle precision.** `in_afternoon_window` takes a `datetime` (µs resolution): test the oracle agreement at ±1 µs around both bounds. The ns-level half-open behaviour (start−1, start, end−1, end) is pinned in A1 directly on `window_extent`/`decision_window_ns`.
4. **R4 missing key.** A replayed key whose census row is ABSENT is drifted too (verdict `MISSING`); add that case to R-e.
5. **C6 cache key.** Fold `std_utc_offset_hours` for the instance's stations into the fingerprint (or equivalently the registry's offset table hash), so a registry offset change invalidates the cached spans.
6. **B27 note.** AUD-10's `C-VALIDITY` must read `replay_drift.jsonl` as well as `replay_results.jsonl`.
