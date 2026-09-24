# Implementation Plan (Rev 2): Stall follow-ups F-1..F-4

Target path (the coordinator saves it): `docs/plans/STALL_FOLLOWUPS_F1_F4_2026-09-24.md`. This is READ-ONLY planning output.
Source: `docs/evidence/STATION_STALL_DIAGNOSIS_2026-09-24.md`. Base: `feat/data-capture-and-risk` @ `ea1873c`.
Rev 2 applies peer reviews D1–D2 (prediction-market-reviewer) and A1–A8 (architect). See the dispositions table at the end.

## Overview

| ID | Verdict | Change | Confidence |
|---|---|---|---|
| F-1a | Defect | A NO-only branch runs when the YES ask is outside the band and the NO leg is inside it. The YES path is untouched. | HIGH |
| F-1b | Defect | A Depth10 book with a bid but no YES ask reaches NO evaluation. | MEDIUM-HIGH (trigger reading, see D1) |
| F-1c | Defect (partial) | A YES instrument-day that is consumed but not filled still evaluates NO. YES IN_FLIGHT and rearm_wait still skip NO, fail-closed. | HIGH |
| F-2 | Gap | Hourly per-process delta rows go to a bounded sidecar. The digest reads them. | MEDIUM-HIGH |
| F-3 | Gap | Cap sized from measurement, a 50% WARN, a streaming digest, and a retention timer. | MEDIUM (measurement pending) |
| F-4 | Intended gate; defect lives elsewhere (L-48) | Observability plus a doc addendum only. | HIGH |

## Invariants (restated in every implementer brief)

- Nautilus Trader is immutable.
- `allow_short=False`.
- `no_side_calibration_gate_cleared` stays default `False`. It is cleared only inside configs that tests construct.
- No operator-cap values.
- Live enablement, the permit, and the NO-SEND firewall are untouched.
- No safety, settlement or contract test is weakened. The only value re-pinned is the provisional F-3 cap.
- PREREG v3 §3/§5/§9 are unchanged.
- Worktrees need `PYTHONPATH`.
- Run `lint-imports` after every slice.

## PREREG findings (L-32 / L-34 check, verified by reading the documents)

- **PREREG v3 §2** (`docs/specs/PREREG_v3_continuous_rung_hold_DRAFT_2026-09-10.md:25`) sets the trigger as "EVERY eligible QuoteTick AND EVERY OrderBookDepth10 ask update".
- **NO amendment** (`docs/evidence/PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md`):
  - §1:13 says side is "determined by market liquidity and the executability gate (§2 depth ladder)".
  - §2:32 defines `NO_ask := 1 − YES_bid`, and §3:48 computes BE on "leg i's own quote".
  - §9:216 lists "Selection population | §2 | Unchanged".
  - §4:114 forbids a NO take only when "a YES **fill** on the sibling YES instrument already exists".
- **Finding for F-1a, CONFIRMS.** L-34's selector test asks which datum becomes the NO trial:
  - Registered rule: the first eligible snapshot where the NO leg's own `1−bid` passes the executable band.
  - Current code: additionally requires the YES ask to be in band (`continuous_strategy.py:1324-1334`), so it selects a later snapshot or none at all.
  - The code is the deviation. F-1a **restores** compliance with the registered NO population. No ruling is needed to merge it or to clear the AUD-01a gate later.
- **Finding for F-1b, CONFIRMS by reading "ask update" per leg.** A bid-only Depth10 update is an update to the NO leg's ask (amendment §2). This leaves one reviewer question:
  - If a reviewer reads §9:216 "Depth10 ask update" as YES-ask-only, that is a CONTRADICTS. F-1b then halts for a ruling (L-32); F-1a and F-1c are unaffected.
  - The prediction-market-reviewer confirms this in the F-1b review.
- **Finding for F-1c, CONFIRMS.** Amendment §4:114 keys the exclusion on a YES *fill*. `refuse_if_sibling_leg_traded` (`trial_day_latch.py:1427-1467`) already implements that through `_FILLED_REASONS`. A consumed YES record that is not a fill does not exclude NO.

---

## F-1a: NO-only branch when the YES ask is outside the band

### Architecture

The YES path at `:1336-1401` is untouched. The `:1328` branch becomes:

```python
if not raw_executable:
    self.diagnostics.record(_DIAG_NOT_EXECUTABLE)          # unchanged
    self._report_alerter(self.diagnostics_alerter, ...)    # unchanged
    if no_leg_executable(snapshot.bid, snapshot.bid_size, self._config):
        self._hunt_no_only(snapshot, facts, station=..., climate_day=..., climate_day_key=...,
                           station_day=..., now_ns=now_ns, hour_lst=hour_lst)
    return
```

`_hunt_no_only` does the following:
1. Quiet `running_max` check: return if the running max is missing. No diagnostic is recorded.
2. Quiet `instrument_rung_is_current` check: return if the rung is not current. No diagnostic. This must stay ahead of NO pricing, because `P_HOLD_*` is keyed on the current rung (`decision.py:364`) and amendment §1:14 allows current-rung NO only.
3. `setup = self._eligible_setup(snapshot.instrument_id, facts, running_max, accumulator, now_ns)`.
4. NO decision:
   - If the snapshot has an ask, take `evaluate_both_sides(...).no`. This single-sources the crossed-book check at `tick_eval.py:276`.
   - Otherwise (F-1b), call `evaluate_eligible_snapshot_no_side(...)`.
5. `_evaluate_no_side_shadow(...)`, which is unchanged.

`_eligible_setup` is a new private helper returning a frozen dataclass `(width_code, m_code, fee_coefficient, staleness_ns)`, built from `width_and_m`, `_guarded_fee_coefficient` and `accumulator.staleness_ns`. It is extracted so the YES path and the NO-only path share it. On the YES path it is a pure extraction: same calls, same order.

New in `decision.py`: public `no_leg_executable(bid, bid_size, config) -> bool` returning `bid is not None and bid_size is not None and _is_executable(_ONE - bid, bid_size, config)`. `_evaluate_no_side:460-469` calls it, so there is one predicate and no behaviour change.

Counter semantics: each tick records exactly the diagnostic it records today. The halt detector's observed-tick gate (`_observe_halt:2450`) therefore sees identical counts.

### Acceptance criteria

1. YES ask outside the band, NO leg executable, running max present, rung current: `_evaluate_no_side_shadow` runs exactly once.
2. On every tick where the YES ask is outside the band, the changes to `diagnostics.counts` are identical to baseline (`in_window_not_executable` +1 only). `refusals.counts`, `takes`, `_eligible_snap_counts` and the YES tape rows do not change.
3. YES and NO both outside the band: byte-identical to today, with no tape row.
4. Gate closed: a NO-only tick appends one NO row with `reason=no_side_calibration_unsafe`. There are zero `submit_order` calls, zero `set_inflight`/`record_attempt` calls on `no_iid`, zero writes of `NO_SIDE_FIRST_LIVE_ORDER_KEY`, and `no_takes == 0` (A4).
5. Gate cleared, test config only: a NO-only tick with edge reaches the arm tail at `:1946-1960`. This proves the code is reachable; it enables nothing.
6. Crossed book on a NO-only tick: NO is refused `not_executable`.
7. A tick with the YES ask in band is byte-identical to baseline: golden rows, counters and order calls.
8. **(D2) Sampling-regime boundary.**
   - The F-1a, F-1b and F-1c merge SHAs are recorded in `docs/core/PROGRESS.md` and cross-referenced from the AUD-01 plan (`docs/plans/backlog/AUDIT_2026-09-21/AUD-01-…md`) as NO-population regime boundaries. This mirrors amendment §1:16's `STUDY_GIT_SHA` precedent.
   - Any NO-calibration study, including the one that would clear the AUD-01a gate, must record those SHAs and must not pool `no_side_shadow` rows across them.
   - The default scope is post-F-1c.
   - The digest artefact carries `no_regime_sha` (the build SHA, read from the deployed tree) so every day's rows are attributable.

### Tests

New file `tests/unit/test_continuous_rung_hold_no_only_hunt_2026_09_24.py`, built on the harness from `test_continuous_rung_hold_no_side_shadow_2026_09_14.py`:
- `test_yes_out_of_band_with_executable_no_leg_evaluates_no_side`
- `test_yes_thin_ask_in_band_with_executable_no_leg_evaluates_no_side` (A2). The YES price is in band but `size < minimum_displayed_size`.
- `test_no_only_sweep`: parametrised over asks {0.02, 0.96, 0.99} × bids {0.04, 0.06, 0.50, 0.94, 0.96}. It asserts NO is evaluated exactly when `0.05 < 1−bid < 0.95` and `bid < ask`, and that the diagnostics delta equals baseline.
- `test_both_legs_out_of_band_writes_no_tape_row`
- `test_no_only_gate_closed_never_submits_sets_inflight_or_writes_first_order_key` (sweeps bids 0.06–0.94)
- `test_no_only_gate_cleared_reaches_no_arm_tail`
- `test_no_only_rung_not_current_is_quiet`
- `test_no_only_no_running_max_is_quiet`
- `test_no_only_crossed_book_refuses_not_executable`
- `test_yes_in_band_tick_is_byte_identical`

Additions to `test_current_rung_hold_decision_no_side_2026_09_14.py`:
- `test_no_leg_executable_parity_with_evaluate_no_side` (band edges 0.05/0.95; sizes 0, 0.5, 1)

---

## F-1b: a bid-only Depth10 book reaches NO evaluation (separate commit)

**Mechanism.** `on_order_book_depth:1155-1157` returns when `best_order(depth.asks) is None`, so the cheapest NO (a YES book with only a bid) is never evaluated.

**Change: an optional ask, in the smallest form.**
- `_AskSnapshot.ask: Decimal | None` and `size: int` (0 when there is no ask). Blast radius: it is private to `continuous_strategy.py`, with only the `:268/:290/:1159/:1209/:1322` sites. `_snapshot_from_quote` always sets an ask.
- `on_order_book_depth`: return only when **both** `ask` and `bid` are None. The monitor forwarding at `:1169` is unchanged.
- Dedupe at `:1209`: the key is `(ts_event, ask, size)` when an ask exists, otherwise `(ts_event, None, bid, bid_size)`. YES keys are unchanged.
- In `_hunt_tick:1322`, when `snapshot.ask is None`:
  - Skip the YES diagnostic, because today these frames record nothing. YES counters stay byte-identical, and so does the halt detector's input.
  - If `no_leg_executable(...)`, call `_hunt_no_only`, then return.
  - Everything upstream (halt, budget, consumed, IN_FLIGHT, rearm, intent-open WAIT, window) runs unchanged. It keys on the YES iid of the same book, exactly as for any other frame. One consequence: a bid-only frame that hits the intent-open WAIT now records `open_intent_wait`, where it previously returned at `:1157`. This is accepted and named: it is a real observed tick, and F-2 carries it.
- Guard with `assert ask is not None` on the YES path after the branch, for mypy narrowing.

**Acceptance criteria**
1. A bid-only book with an executable NO leg evaluates NO once.
2. A bid-only book with a NO leg outside the band records nothing and writes no row.
3. A book with neither side still returns early.
4. Gate closed: no order, no inflight, no first-order key.
5. A QuoteTick path is byte-identical.

**Tests** (same new file):
- `test_bid_only_depth_evaluates_no_side`
- `test_bid_only_depth_no_leg_out_of_band_is_silent`
- `test_empty_depth_returns_early`
- `test_bid_only_dedupe_distinguishes_bids_at_same_ts`
- `test_bid_only_gate_closed_never_submits`
- `test_quote_tick_path_unchanged`

---

## F-1c: YES latch states that return before NO (separate commit)

| YES state (`:1241-1284`) | Evaluate NO? | Rationale (cite) |
|---|---|---|
| `is_consumed(YES iid)`, record reason in `_FILLED_REASONS` | **No.** Skip silently. | Amendment §4:114; `refuse_if_sibling_leg_traded` would refuse on every tick and spam the tape |
| `is_consumed(YES iid)`, record not a fill | **Yes.** Use a NO-only entry. | §4 excludes only on a YES fill; `_FILLED_REASONS` (`trial_day_latch.py:164`) |
| YES IN_FLIGHT, not released | **No.** Fail closed. | The YES fill outcome is unresolved, so §4 exclusion cannot be proven. The account-wide intent is usually OPEN anyway (`:1295`). Rule: the fail-closed reading stands (L-32). |
| YES `rearm_wait` | **No.** Fail closed. | The re-arm gate exists because the prior YES attempt lacks venue evidence of a non-fill (PREREG v3 §5 attempts 2–3). Same §4 reasoning applies. |

**Change.** At `:1241`, when the YES instrument is consumed:
- If `refuse_if_sibling_leg_traded(store, prefix, station, day, no_iid)` is not None, return (unchanged outcome).
- Otherwise run a quiet NO-only entry:
  1. Compute `hour_lst`; return silently if outside the window. No `outside_decision_window` refusal is recorded, keeping counters byte-identical.
  2. Return silently if `is_intent_open()` (the account-wide single in-flight guard; `_evaluate_no_side_shadow` re-checks it).
  3. If `no_leg_executable`, call `_hunt_no_only`.
- `_evaluate_no_side_shadow`'s own `is_consumed(no_iid)`, Σq admission and day-budget gates still apply.
- IN_FLIGHT and rearm_wait keep their returns. Each gets a one-line comment citing this table.

**Acceptance criteria**
1. YES consumed with a filled reason: no NO evaluation and no row.
2. YES consumed with a non-fill reason: NO is evaluated. With the gate closed, the result is `no_side_calibration_unsafe` and no order.
3. YES IN_FLIGHT, and YES rearm_wait: NO is not evaluated.
4. Intent OPEN or outside the window on the consumed path: silent, and counters are byte-identical.

**Tests** (same file):
- `test_yes_consumed_filled_skips_no`
- `test_yes_consumed_unfilled_evaluates_no` (parametrised over every non-fill member of `_REASONS`)
- `test_yes_inflight_skips_no`
- `test_yes_rearm_wait_skips_no`
- `test_consumed_path_intent_open_is_silent`
- `test_consumed_path_outside_window_records_nothing`

**Unknown.** Whether any live path writes a YES record with a non-fill reason; if none does, AC2 is dormant but harmless. The implementer greps `consume(` and `consume_if_absent(` callers and states the answer.

### F-1 risk register

| Risk | Mitigation |
|---|---|
| NO-only path arms YES | It returns before `:1403` and never touches the YES admission, tape or submit block (AC4/AC7) |
| Extra NO rows re-truncate the tape | F-3 merges and deploys first (sequencing) |
| Pooling `no_side_shadow` rows across regimes biases NO calibration | D2 criterion (F-1a AC8) |
| F-1b trigger reading is disputed | Separate commit; halts alone on a CONTRADICTS |
| F-1c evaluates NO next to an unresolved YES order | IN_FLIGHT and rearm_wait stay fail-closed |

**Trade-offs**
- A `no_only` flag threaded through the YES path was dropped (A1): it touched YES lines.
- A NO-only entry that duplicates every pre-gate for F-1b was rejected: it duplicates about 120 lines of latch gates. An optional ask is smaller.

---

## F-2: pre-tape counts visible intraday

### Design

- Event-time rollover at the top of `_hunt_tick`: `bucket = ts_event // 3.6e12`, rolling only forwards.
- On rollover, emit the deltas since the last emission for `diagnostics`, `refusals`, `takes` (YES), `no_takes` (A4, NO) and `offer_tape.sidecar_capped`.
- Emit a `final` row in `on_stop`, before `:1050`.
- Memory: the last-emitted copies are bounded by the counters' key sets.
- `station = ",".join(self._config.stations)` (A5). No assertion.
- Output 1, an INFO log line: `diagnostics_hourly: station=… hour_utc=… diag={…} refusals={…} takes=+n no_takes=+n tape_capped=+n`.
- Output 2, a JSONL row with schema `crh_diag_hourly_v1`: `station, pid, boot_ns, hour_utc_start_ns, emitted_at_ns, diagnostics, refusals, takes, no_takes, offer_tape_capped, final`.
- Sidecar path: `_decisions_dir(catalog_root) / f"diagnostics_summary_{day}.jsonl"`, with `day` taken from the same boot-day `min(today_by_station.values())` as the offer tape (A5).
- `no_takes` (A4) is a new int on the strategy, incremented where NO sets IN_FLIGHT (`:1951`). This mirrors YES `takes` at `:1619`. `HaltDetector.observe(takes=self.takes)` is **unchanged**: no cited rule makes the halt detector NO-aware.

### Acceptance criteria

1. At most one row per strategy per UTC hour that saw a tick, plus one `final` row.
2. For each process that reached `on_stop`, its rows' deltas (grouped by `pid, boot_ns, station`) sum to its `diagnostics snapshot` line (A5).
3. An emission never raises into `_hunt_tick`: it runs under `_run_observability`, and a sidecar `OSError` only increments an error count.
4. No new keys in `diagnostics` or `refusals`, so there are no new alerter conditions.
5. An older `on_data` `ts_event` never rolls a bucket back.
6. Digest: stalled stations get `pre_tape_by_station` in the artefact, plus a `stall=MDW(not_executable:826)` token that is dropped first when the text exceeds `MAX_ALERT_DETAIL_CHARS`. A missing summary file leaves output byte-identical.

### File-by-file

- New `src/breezy/strategy/current_rung_hold/diagnostics_summary.py` (stdlib only):
  - `DiagnosticsSummarySink(path | None, max_bytes=4 MiB)`, with the same best-effort, byte-capped, resume-from-stat semantics as `OfferTape.append:395-430`.
  - Pure `delta(prev, cur)`.
- `composition.py`:
  - Add `_decisions_dir(catalog_root)`. `_default_offer_tape_path` and the new `_default_diagnostics_summary_path` both use it.
  - Build one shared sink beside `tape` (`:559`) and pass it to each strategy.
- `continuous_strategy.py`:
  - `__init__`: kwarg `diagnostics_summary=None`; `no_takes`; bucket state.
  - New `_maybe_roll_diagnostics`.
  - `on_stop` flush.
- `continuous_backtest_only.py`: forward the kwarg if it forwards kwargs explicitly (verify).
- Digest: `_read_summary` (streaming), `--summary`, `FunnelReport.pre_tape_by_station`.

### Tests

- `tests/unit/test_continuous_rung_hold_diagnostics_hourly.py`:
  - `test_rollover_one_row_per_hour`
  - `test_per_process_deltas_sum_to_on_stop_snapshot`
  - `test_older_on_data_ts_never_rolls_back`
  - `test_sidecar_oserror_never_raises`
  - `test_no_new_counter_keys`
  - `test_memory_bounded_by_key_set` (10^5 ticks)
  - `test_no_takes_counted_at_no_inflight_and_halt_detector_takes_unchanged`
  - `test_station_field_is_joined_config_stations`
- `tests/unit/test_diagnostics_summary_sink.py`:
  - `test_two_sink_instances_one_file_rows_intact_and_attributable` (A5: pid/boot_ns)
  - `test_cap_and_resume`
  - `test_unwritable_dir_in_memory_only`
- Digest tests:
  - `test_stalled_station_annotated_from_summary`
  - `test_missing_summary_byte_identical`
  - `test_pre_token_dropped_first`
- Composition test: `test_diagnostics_summary_path_uses_decisions_dir_boot_day`.

**Tripwire.** `test_execution_egress_firewall_guard.py` scans the new module. It uses no egress names; if a scanned-file set is enumerated (near `:1601`), add the file there and weaken nothing.

**Trade-offs (options rejected)**
- A Nautilus `clock.set_timer` was rejected. L-16: a raise inside a `LiveClock` timer callback is silently discarded. Timers also run on wall-clock time while tape and replay run on event time. Counts change only on ticks, so a timer gains nothing.
- `HaltDetector._tally` as the source was rejected (A5):
  - It is an alerting component with its own window semantics.
  - `_observe_halt` runs only after the budget, consumed, inflight, rearm and intent gates. `open_intent_wait` and the other pre-gate counts would be invisible or double-sourced.
  - Coupling a sidecar into it widens its responsibility.
- Tape rows for pre-gate refusals were rejected: roughly 5k rows per station-day, and they break the digest's closed `source` set and `OfferTapeRecord`'s legacy keys.
- Log-only was rejected: the digest cannot parse boot-named ANSI logs reliably.

---

## F-3: tape cap, streaming digest, retention

### Measurement first (the implementer runs these read-only and puts the output in the PR)

1. `df -h ~/.local/share/breezy`
2. `du -sh ~/.local/share/breezy/catalog/quote_tape/decisions` and a per-file listing
3. F-1 row growth on 09-20: count the ticks F-1a would newly evaluate (`nogap.py` method, scratchpad, `systemd-run --user --scope -p MemoryMax=4G`). Multiply by the mean NO row size (about 1 KB). Add the untruncated peak day (projected from 09-22's 64 MiB at 20:37Z plus its rate through 01:00Z).
4. Cap = at most 2× the projected peak day including F-1 growth. The Rev 1 figure of 512 MiB is the ceiling unless the measurement justifies more.

### Acceptance criteria

1. `DEFAULT_OFFER_TAPE_SIDECAR_MAX_BYTES` is set to the measured value. Its comment cites the measurement.
2. One WARN when a file crosses 50% of its cap.
3. `sidecar_capped` appears in F-2 rows. The digest prints `truncated=1` when that count is above 0.
4. The digest streams line by line. Peak `tracemalloc` on a 10^5-row tape stays under 50 MB.
5. A truncated or malformed last line makes the digest exit 1 with `decision tape unreadable` (A6).
6. Retention:
   - A new `scripts/ops/decisions_retention.py` gzips `offer_tape_*.jsonl` and `diagnostics_summary_*.jsonl` older than N days and deletes `.jsonl.gz` files older than M days. N and M come from the measured disk figures; the default proposal is N=7, M=90.
   - It runs from `deploy/systemd/breezy-decisions-retention.{service,timer}` and takes the studies flock, like `decision-funnel-digest-run.sh:37-40`.
   - It never touches `observations/` (`observation_composition.py:52`) or today's file.
   - It is dry-run by default in tests.
   - The AUD-03 digest stays read-only, so retention does not go into the digest unit.
7. Readers stay working:
   - The digest reads `.jsonl` or `.jsonl.gz`.
   - `scripts/analysis/band_decider_stage0b_screen.py:37` pins `offer_tape_2026-09-16.jsonl`. It gets a `.gz` fallback, or that file sits on an explicit keep-list.
   - The implementer re-greps `scripts/` and `src/` for `decisions`, `offer_tape_` and `diagnostics_summary_` and lists every reader, confirming none reads files older than M days.

### File-by-file

- `offer_tape.py`: the constant and the half-cap WARN.
- Digest: generator `_iter_jsonl`, with `.gz` support through `gzip.open`.
- New retention script, unit and timer.
- `band_decider_stage0b_screen.py`: `.gz` fallback.

### Tests

- `test_current_rung_hold_offer_tape.py`: re-pin `test_default_sidecar_max_bytes_is_pinned_at_64_mib` under a new name with the measured value. It is a provisional value pin, not a safety test; the commit says so. Add `test_half_cap_warn_once`.
- Digest tests:
  - `test_digest_streams_bounded_memory`
  - `test_truncated_last_line_exits_1_unreadable`
  - `test_reads_gz_tape`
  - `test_truncated_flag_from_summary`
- `tests/unit/test_decisions_retention.py`:
  - `test_gzips_older_than_n`
  - `test_prunes_older_than_m`
  - `test_never_touches_today_or_observations`
  - `test_keep_list_respected`
  - `test_skips_on_lock_contention`

### Risks

| Risk | Mitigation |
|---|---|
| Disk runs out | The measurement gates the cap; retention bounds the total |
| Pruning deletes something a study needs | Reader grep plus the keep-list |
| Gzip breaks a reader | `.gz` fallback in both readers |

Rejected: rotating part-files (breaks the one-file-per-day readers), sampling or dedupe (corrupts funnel counts), compacting the schema (breaks `from_dict`).

---

## F-4: one station's open intent makes every other station wait

### Disposition: the gate is intended

- `is_intent_open` (`trial_day_latch.py:626-645`) is the account-wide R-7 singleton.
- `MULTI_POSITION_PER_STATION_2026-09-14.md:100` keeps it as runaway guard (1), "one order in flight at a time across the whole account", and `:113` freezes it.
- The 09-14 ruling lifted only one-position-per-station.
- The 09-23 waits (27,611–115,468 ticks) are the L-48 shape: an AMBIGUOUS IOC (CP05MNWMAWP6) held the intent OPEN, and the latch's clearing path was blocked. That is where the defect is.
- The coordinator names two resolver fixes merged 2026-09-24 as owners of AMBIGUOUS retirement speed: terminal-leaves `df66327` and the past-day instrument loader `c3398bb`. The implementer verifies both with `git show --stat` before citing them; they were not found in `docs/`.

### Observability change (in `continuous_strategy.py`)

- At `:1295`, read `current_open_submit_intent()` only when this station's event-time **minute** bucket changes (`snapshot.ts_event // 60e9`) (A7).
- Dedupe on `intent_id`: log `open_intent_wait: station=… intent_id=… age_s=…`, where `age_s = (snapshot.ts_event − created_ns)/1e9`.
  - Log it once per new `intent_id` per station.
  - Log it again at most hourly while the same id persists.
- Never log `fingerprint` (it is `repr=False`).
- The read runs under `_run_observability`.
- State is two scalars per strategy (last minute bucket, last intent id and when it was logged), so memory is bounded.

### Doc addendum

Add "F-4 disposition" to the evidence doc. It cites the plan lines above, R-7/GL-1, and L-48. Its measurement acceptance criterion (A7):
- Measure 09-23's intent open→retired interval from the node logs and the `SubmitIntent` `created_ns`/`retired_ns` (read-only).
- State the retirement reason.
- State whether `df66327` (state-aware terminal leaves) and `c3398bb` (past-day instrument loader) would have shortened the interval, with the mechanism, per the counterfactual lesson.
- Include L-48's "clearing path" row for the intent latch.

### Acceptance criteria

1. At most one store read per station per event-minute.
2. One line per `(station, intent_id)` plus at most one per hour after that, with no fingerprint.
3. The gate outcome is byte-identical (WAIT, same diagnostic).
4. A raise during the read is contained.
5. The addendum's measurement is present.

### Tests

In `test_continuous_rung_hold_strategy.py`:
- `test_open_intent_read_once_per_event_minute`
- `test_open_intent_logged_once_per_intent_id_then_hourly`
- `test_open_intent_log_omits_fingerprint`
- `test_open_intent_age_from_ts_event`
- `test_intent_read_failure_contained`

---

## Sequencing (A8, L-43)

1. **F-3**: merge, then run the full `scripts/ci/run_tests_no_egress.sh` gate. Deploy it first so the cap is live before extra NO rows appear.
2. **F-1a**: merge, full gate.
3. **F-1b**: merge, full gate. It halts alone if D1's trigger reading is contested.
4. **F-1c**: merge, full gate.
5. **F-2 + F-4**: one slice, because both touch `_hunt_tick`'s head, `on_stop`, `__init__`, `composition.py` and the digest. Merge, full gate.

Rules for every merge:
- Run the full no-egress gate after every merge, before starting the next one (L-43).
- Nothing runs in parallel on the integration branch. Review can overlap with the next slice's implementation in a separate worktree, rebased after the gate.
- Deploy through `breezy-trade-supervisor`'s daily boot only; no mid-day hand relaunch.
- Record the D2 regime SHAs at each F-1 merge.

**Must stay green, unedited:**
- `test_continuous_rung_hold_strategy.py`
- `test_continuous_rung_hold_no_side_shadow_2026_09_14.py`
- `test_no_side_first_order_pending_2026_09_14.py`
- `test_no_side_calibration_gate_manifest.py`
- `test_current_rung_hold_tick_eval_no_side_2026_09_14.py`
- `test_halt_detector.py`
- `test_submit_intent_latch.py`
- `test_current_rung_hold_paper_replay.py`
- `test_execution_egress_firewall_guard.py`
- `test_test_safety_tooling_config.py` (the `ignore_imports` set is unchanged; the new modules import only stdlib or intra-package code)

## Success criteria

- [ ] F-1a/b/c ACs green; gate-closed tests prove no NO order is possible
- [ ] YES golden byte-identity holds
- [ ] D2 SHAs recorded
- [ ] F-2 per-process sums match `on_stop`; the digest annotates the MDW 09-20-shaped stall
- [ ] F-3 cap measured, retention live, streaming digest in place, truncated-line exit 1
- [ ] F-4 lines bounded; addendum measures the 09-23 interval against `df66327`/`c3398bb`
- [ ] Full no-egress gate plus `lint-imports` green after every merge

## Unknowns

- F-1b trigger reading (reviewer confirms).
- Whether any live path writes a non-fill YES `TrialDayRecord` (F-1c AC2 may be dormant).
- Whether `continuous_backtest_only` forwards kwargs.
- Disk headroom and N/M values (measured in F-3).
- That the `df66327`/`c3398bb` SHAs exist (verify before citing).

## Rev 2 dispositions

| Item | Landed |
|---|---|
| D1: F-1 restores the registered NO population; CONFIRMS | "PREREG findings"; F-1 risk row rewritten; citations verified (v3 §2:25; amendment §1:13, §2:32, §3:48, §4:114, §9:216) |
| D2: two sampling regimes, `STUDY_GIT_SHA` precedent | F-1a AC8 (PROGRESS plus AUD-01 cross-reference, digest `no_regime_sha`); F-1 risk register; sequencing |
| A1: drop the `no_only` flag; `_hunt_no_only`; shared setup helper | F-1a Architecture (`:1328` branch, `_hunt_no_only`, `_eligible_setup`; YES `:1336-1401` untouched) |
| A2: thin-ask test and the 3×5 sweep | F-1a Tests |
| A3: F-1b bid-only Depth10; F-1c YES latch states | F-1b and F-1c sections, each a separate commit with its own ACs and tests |
| A4: `no_takes` counter; halt detector unchanged | F-2 Design, AC and test; F-1a AC4 |
| A5: station join, per-process AC2, pid/boot_ns, two-sink test, reject `_tally`, L-16, `_decisions_dir` | F-2 Design, AC2, Tests, Trade-offs |
| A6: measure first, cap ≤2× peak, retention, reader grep, truncated-line test | F-3 Measurement, AC1–AC7, retention script and timer, tests |
| A7: minute-bucket read, `intent_id` dedupe, `ts_event` age, L-48, `df66327`/`c3398bb`, measurement AC | F-4 Disposition, Observability change, Doc addendum |
| A8: F-3 → F-1a → b → c → F-2+F-4, gate after every merge, paper_replay must stay green, supervisor boot | Sequencing; must-stay-green list |

Lesson numbers cited (headers checked in `docs/core/LESSONS.md`): L-16 (:772), L-32 (:1268), L-34 (:1296), L-43 (:1424), L-48 (:1515).

Status: Rev 2 — pending delta peer review.
