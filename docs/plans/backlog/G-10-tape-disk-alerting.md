# G-10 Tape Disk Alerting

## Problem

The quote-tape recorder writes the only copy of Polymarket.us weather-market
price history Breezy can collect. Missed tape cannot be backfilled, so two
failure modes must be made loud:

- the catalog volume runs out of free space and Nautilus can no longer append;
- the active scheduled-rotation tape file grows unexpectedly within the day.

The backlog claim was re-verified against the installed Nautilus Trader
1.231.0 source before this plan was written. In
`.venv/lib/python3.13/site-packages/nautilus_trader/persistence/writer.py`,
`StreamingFeatherWriter._check_file_rotation` is an `if`/`elif` chain:

- lines 305-306: `NO_ROTATION` returns `False`;
- lines 307-308: only `RotationMode.SIZE` checks
  `self._file_sizes.get(table_name, 0) >= self.max_file_size`;
- lines 309-318: `INTERVAL` and `SCHEDULED_DATES` check only the next scheduled
  rotation time.

Therefore `max_file_size` is not consulted under
`rotation_mode=SCHEDULED_DATES`. The current quote-tape config correctly avoids
claiming a dead size backstop, but one day's file remains unbounded.

## Approach

Implement a runtime-side monitor around the quote-tape process. Do not modify,
fork, patch, bypass, or reimplement Nautilus Trader. Keep
`StreamingConfig`/`StreamingFeatherWriter` as the persistence mechanism.

The monitor will:

- probe `shutil.disk_usage(settings.catalog_root)` so the measured free space is
  for the volume that holds the catalog root;
- scan `settings.catalog_root / "live" / <instance_id>` for `*.feather` files
  and report the largest current stream file as the current day's tape growth
  proxy;
- emit `WARNING` when either warning threshold is crossed;
- emit `ERROR` when either hard-floor threshold is crossed;
- dedupe repeated messages per threshold state, while logging a recovery when a
  condition returns to normal;
- run in a daemon thread while `TradingNode.run()` blocks, and stop/join in the
  same `finally` path that disposes the node.

Settings for this recorder role already use required-no-default for the catalog
root because defaults would let the process start half-configured and record to
an unwatched path. Disk alerting is the same class of operator-owned production
threshold, so its thresholds must also be required with no defaults on the
quote-tape role. The monitor interval may have a conservative default because it
does not encode capacity policy and cannot route tape to an unwatched place.

Planned environment variables:

- `BREEZY_POLYMARKET_US_QUOTE_TAPE_MIN_FREE_BYTES_WARNING`
- `BREEZY_POLYMARKET_US_QUOTE_TAPE_MIN_FREE_BYTES_ERROR`
- `BREEZY_POLYMARKET_US_QUOTE_TAPE_MAX_FILE_BYTES_WARNING`
- `BREEZY_POLYMARKET_US_QUOTE_TAPE_MAX_FILE_BYTES_ERROR`
- `BREEZY_POLYMARKET_US_QUOTE_TAPE_DISK_CHECK_INTERVAL_SECONDS`

Validation:

- thresholds are positive integers;
- error free-space floor is lower than warning free-space floor;
- error file-size ceiling is higher than warning file-size ceiling.

## Halt Decision

Do not halt the recorder at the hard floor. Alert only.

Rationale: the tape is unrecoverable, and a false-positive halt immediately
creates the exact permanent gap this feature is trying to prevent. Continuing
capture while emitting `ERROR` gives the operator a chance to free space, move
the catalog, or intervene before the filesystem rejects writes. If the disk
does fill, Nautilus write failures and monitor `ERROR` records make the state
loud; the process must never silently degrade to recording nothing. This repo has
already seen silent data loss twice, so the monitor's contract is repeated,
escalating log evidence, not a silent stop.

## Files Touched

- `docs/plans/backlog/G-10-tape-disk-alerting.md`
- `src/breezy/runtime/settings.py`
- `src/breezy/runtime/quote_tape_disk_monitor.py`
- `src/breezy/runtime/quote_tape_cli.py`
- `tests/unit/test_quote_tape_disk_monitor.py`
- `tests/unit/test_quote_tape_recorder.py`
- `tests/unit/test_quote_tape_cli.py`

Do not touch `pyproject.toml`, `tests/conftest.py`, or any gap-record loader
code.

## RED Test

Add tests that simulate disk usage without filling a disk by injecting a fake
disk-usage probe:

- normal free space and normal largest tape file emit no warning/error records;
- free space below the warning threshold emits `WARNING`;
- free space below the hard floor emits `ERROR` and does not stop the node;
- largest current `.feather` file above the warning threshold emits `WARNING`;
- largest current `.feather` file above the hard ceiling emits `ERROR`;
- missing required threshold env vars fail quote-tape settings load before node
  construction.

Captured RED criterion: the new tests fail before implementation because the
monitor module/settings fields/CLI integration do not exist.

## GREEN Criterion

- Focused monitor and quote-tape tests pass.
- The monitor starts before the node enters `run()` and is stopped after node
  disposal.
- Low-disk and oversized-file conditions produce log records at the required
  severity without real disk pressure.
- Normal headroom produces no warning/error log records.
- Full gates run and report exit codes: `uv run pytest -q`,
  `uv run ruff check .`, and `uv run mypy`.

## Risks

- The monitor observes files externally, so "current day's tape file" is a proxy
  for Nautilus's active stream files, not writer private state. This is
  intentional: reaching into writer internals would couple Breezy to immutable
  Nautilus implementation details.
- A probe failure must be loud and non-fatal. If `disk_usage` or directory
  scanning raises transiently, the monitor should log `ERROR` and keep trying
  rather than halting capture.
- Log-only alerting depends on production log routing. The quote-tape CLI
  already installs the stdlib-to-Nautilus logging bridge before configuration
  and node startup, so these records should land in the same stream operators
  already watch.
