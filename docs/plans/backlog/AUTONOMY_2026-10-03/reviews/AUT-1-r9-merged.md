# AUT-1 r9: merged blind review (2026-10-03)

| Reviewer | Score | Verdict |
|---|---|---|
| trading-bot-architect | 80 | NOT READY (3 HIGH) |
| silent-failure-hunter | 80 | NOT READY (2 HIGH) |

## Verified by both reviewers against the Nautilus source

- The config-dump crash: `kernel.py:606-611`, `config.py:176`.
- The silent drop of a record with an `instrument_id` field: `writer.py:210-239`.
- No try/except around bus handlers: `component.pyx:2832-2834`.
- `serialize_batch` sits outside the writer's try block: `writer.py:259`.
- The 60 s heartbeat flush bound: `writer.py:278`.
- The quote is cached before it is published: `engine.pyx:2716` comes before `:2728`.

No hard-invariant violation was found.

## Coordinator rulings

- **R-A (option B is primary).** Both reviewers agree.
  - Ship **option B**: an actor-owned native `StreamingFeatherWriter` behind a catch-all wrapper.
  - `CapturePublisher` calls the wrapper directly for the custom records.
  - Option A is dropped, and with it V-2, V-4 and the global `register_config_encoding`.
  - L-1 still holds because the writer is native.
- **R-B (forecast references are native).** Stream `ForecastPoint` natively. It is already `register_arrow`ed at `domain/forecast_point.py:675` and has no `instrument_id` field. Add it to `CAPTURE_INCLUDE_TYPES`, and add `forecast_available_at_ns` to `DecisionRecord`.
  - References resolve inside the stream, keyed `(station, cycle_ns, available_at_ns)`.
  - The `derived/nbp` store premise (V-12) and the `FrameCopy.forecast_body` fallback are removed.
  - `NbmQuantileActor._publish` persists nothing, and `nbp_backfill` dedupes differently.
- **R-C (Take-path frame copy).** Adopted as flagged in r9; this ruling is unchanged.
- **Cross-plan X-1..X-7** bind this plan. They are defined in `reviews/AUT-6-r14-merged.md` and summarised here; AUT-6 r15 is being revised under the same rulings.
  - **X-1:** `NotifyAccess=all`.
  - **X-2:** `Type=notify`.
  - **X-3:** the launch-window deferral lives in `classify_recorder_sample`, and is journaled once per stall.
  - **X-4:** per-kill paging is AUT-6's native `OnFailure=` notifier. AUT-1's `ExecStopPost=` hook loses its paging duty. Either delete the hook, or keep it as evidence only, writing the stall record. r10 decides which and justifies the choice.
  - **X-5:** `READY=1` is sent once the feed is connected and subscribed. Only `WATCHDOG=1` is gated on advancing counters. Add a test that a quiet-feed start does not time out.
  - **X-6:** storm escalation is owned by AUT-6.
  - **X-7:** the deferral WARN is delivered by AUT-6.
- **Errata dedupe.** AUT-6's E-11 is the single vehicle for the ARCH §4.5/§4.6 SELF_HEAL wording.
  - ER-8 is reduced to AUT-1-only recorder-unit text.
  - That text includes: "the ping source runs from process start, through discovery".

## Owed in r10

### EH1 [HIGH, architect]: the ping site does not run during discovery

**Problem:**
- `_watch_feed` is created at the end of `_connect` (`data.py:1117-1121`), after `initialize()`, which can retry for 3600 s (`node_config.py:349`).
- With `WatchdogSec=600`, the 09:00Z listing hole would therefore kill a healthy recorder.
- `test_recorder_unit_watchdog_config_exact` contradicts step 1's "unit edit later". The unit is symlinked into the repo.

**Fix:**
- Start the ping task at the top of `_connect`, or on a node timer.
- Treat DISCOVERING as OK until `empty_discovery_retry_secs + 300`.
- Land the unit edit and its test only in step 2.

### EH2 [HIGH, architect]: the forecast-reference premise is false

Apply R-B.

### EH3 [HIGH, both]: native-event serialisation can unwind into execution

Apply R-A.

### EH4 [HIGH, silent-failure-hunter]: the bytes-flat check is blind to per-type loss

**Problem:**
- The heartbeat write keeps the byte total growing.
- `writer.py:284-288`, `:261` and `:251` drop records silently.

**Fix:**
- Track a per-type published count against per-type file growth (`lstat` each type's file, over a 180 s window).
- Any type whose count rose while its file stayed flat sets `health.ok=False`, which raises `capture_gap`.
- Amend ER-7 to read "per-type stream bytes".

### EM1: stop-hook failure paths

The audit requires that every journal `UNIT_RESULT=watchdog` entry has a stall record and a `delivered=true` proof. Otherwise the audit FAILs and re-sends. Reconcile this with X-4.

### EM2: sampling exceptions

The new `lstat`/classify code goes inside a try/except. On an exception it emits ERROR `RECORDER_SAMPLE_FAILED`, increments a counter, and records non-OK `sample_error`. A dead `_watch_feed` must never stop pings silently.

### EM3: R5 counts native events

The actor counts `OrderInitialized` and `OrderFilled`, and `CaptureHeartbeat` carries those counts.

### EM4: Take-path flush

Under option B, call `writer.flush()` synchronously after the Take-path publishes and before `super().submit_order`. Measure it against `CAPTURE_PATH_P99_BUDGET_MS`.

### EM5: `node_boot_id` equals the kernel `instance_id`

Set the trade-node `instance_id` explicitly, as the recorder does (`node_config.py:536-544`).

### EM6: missing `RecorderSample` fields

`phase`, `discovered_slugs` and `depths_published` do not exist in `data.py`. Add accessors to WP3's file list.

### EM7: the per-instrument `md_feed_freshness` veto is vacuous on frame paths

Keep it as an observation only.

### EL1

- `lost_in_flush_window` requires the missing records to be at most 61 s older than the boot's last log line.
- The risk row at about line 1169 cites the existing `salvage_truncated_instance`.

### EL2

- Name a retention owner for `derived/capture_stream`, or state "none required (~2 MB/day)" in ER-2.
- Pin file paths in the "unedited tests" list.

### Errata verdicts to apply

| Erratum | Verdict |
|---|---|
| ER-1 | AMEND: option B named; ~1 s flush; per-type check. Fix the `<capture_root>` naming. |
| ER-2 | AMEND: retention. |
| ER-3 | AMEND: `ForecastPoint` stream. |
| ER-4 | AMEND: add `forecast_available_at_ns`. |
| ER-5 | ADOPT. |
| ER-6 | AMEND: the config.json clause is dropped under B. |
| ER-7 | AMEND: per-type. |
| ER-8 | REDUCE: recorder-unit-only text, plus the ping from process start and the journal cross-check. |
| ER-9 | ADOPT. |
| ER-10 | ADOPT: add the `ForecastPoint` stream. |

## Approval bar

Both reviewers ≥95 and zero CRIT/HIGH.
