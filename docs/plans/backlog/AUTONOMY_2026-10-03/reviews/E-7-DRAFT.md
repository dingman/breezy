# Errata E-7 (DRAFT, under peer review): user-unit mount sandboxing is not enforced on this host

## Evidence
2026-10-03, verify-first experiment in the session scratchpad:
- `systemd-run --user -p ReadOnlyPaths=<dir>`: `touch` inside the unit succeeds (rc=0).
- `test -w ~/.local/share/breezy/state` reports WRITABLE, and mountinfo shows no bind.
- `PrivateUsers=yes` does not help, because `kernel.apparmor_restrict_unprivileged_userns=1`.
- `bwrap --ro-bind` IS enforced: touch fails with "Read-only file system". The test gate already runs bwrap inside `systemd-run --user` units.
- Corollary: `ProtectHome=read-only` in the existing `deploy/systemd/*.service` files is probably a no-op as well.

## Rule (binding on every AUT plan; amends ARCH wherever it relies on unit sandbox directives)
1. **Directives are not controls.** No plan may count `ReadOnlyPaths`, `ReadWritePaths`, `ProtectHome`, `ProtectSystem`, `PrivateTmp` or `InaccessiblePaths` as an enforced control. They may stay in unit files as defence-in-depth config only. Tests that only parse them must be named `*_config_*`, not `*_sandbox_*`, and are never cited as enforcement.
2. **Real enforcement for registry-writing units.** The AUT-5 engine, the only holder of registry-write authority, runs its ExecStart under `bwrap`:
   - `--ro-bind / /`, plus `--bind` for exactly its ARCH `ReadWritePaths`;
   - `--dev /dev`, `--proc /proc`, `--die-with-parent`.
   
   At start, a self-probe tries `O_WRONLY|O_CREAT` on a sentinel under `state/`. If that succeeds, the unit refuses with INTEGRITY and a delivered CRITICAL.
   
   Test: `test_engine_bwrap_denies_state_write`. This is a real probe, not a parse.
3. **Code-level read-only for every other autonomy reader.**
   - SQLite opens use `file:…?mode=ro` plus `PRAGMA query_only=ON`. The exec store is the exception and uses the E-8 copy-snapshot.
   - Plain files are opened `O_RDONLY`.
   - An AST test per unit closure fails on any write-mode open, or `SqliteStateStore(` construction, outside that unit's one-writer rows.
4. **One-writer table.** ARCH's one-writer table is enforced by the AST closure test in rule 3, plus the bwrap bind set for the engine. A sandbox directive alone never enforces it.

# Errata E-8 (DRAFT): engine read of the exec store at 16:45Z
- The engine reads the halt mirror and `exec/polymarket_us/intent/current` with the copy-snapshot procedure below. Experiments E1–E3 PASS under `bwrap --ro-bind`:
  1. Open `exec_polymarket_us.sqlite.intent.lock` `O_RDONLY` and take `flock(LOCK_EX|LOCK_NB)`; retry 3× at 5 s intervals.
  2. Fingerprint the db, `-wal` and `-journal` by (inode, size, mtime_ns).
  3. Copy the db, `-wal` and any `-journal` (never `-shm`) into the engine's private cache dir (0700).
  4. Re-fingerprint; any change triggers a retry.
  5. Release the lock.
  6. Open the copy read-write and run `quick_check`.
  7. Read both keys from that one copy, decoding via the shared `SubmitIntent` decode extracted from `probe_open_intent`.
  8. Delete the copy.
- **Blocking states.** `SubmitIntentState` has only OPEN and RETIRED; AMBIGUOUS does not exist. OPEN or `SubmitIntentCorrupt` blocks, matching `probe_open_intent`, and an absent record does not block.
- **Lock file missing.** A missing lock file is a read failure: fail closed. An `O_RDONLY` open cannot create it.
- **Node up.** The node holds the lock for its whole lifetime (`app/trade.py:990`). A held lock after retries is a read failure: no widening write. A persistent failure past H gives HALTED/INTEGRITY per ARCH.
- **Lock hold time.** The engine holds the lock only for the copy, which is ≤3 MB today, and must finish before the 16:47:30 yield. A halt CLI that collides gets `SubmitIntentLockHeld` and retries.
- **Supervisor write without the lock.** `trade_supervisor.py:2418` writes without the lock at 17:05Z, outside the engine window. The re-fingerprint in step 4 is the guard.
- **Supervisor change.** `intent_lock_is_free` switches to an `O_RDONLY` fd. Existing supervisor tests pass unmodified, and a supervisor restart is needed.
- **Supersedes** the AUT-5 r4 `immutable=1` workaround.
- **Tests:**
  - `test_exec_snapshot_recovers_stale_wal_after_sigkill`
  - `test_exec_snapshot_never_copies_shm`
  - `test_exec_snapshot_holds_intent_flock_readonly_fd`
  - `test_exec_snapshot_fingerprint_change_retries_then_read_failure`
  - `test_exec_snapshot_halt_and_intent_from_one_copy`
  - `test_exec_snapshot_missing_lock_file_fails_closed`
  - `test_intent_lock_is_free_readonly_fd`
