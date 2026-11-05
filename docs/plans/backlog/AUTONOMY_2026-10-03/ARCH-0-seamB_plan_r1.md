# Build plan: ARCH-0 seam B (sandbox wrapper, WAL snapshot helper, C4.1 holdout ruling)

**Basis.** Frozen ARCH Rev 9.2 (the sha256 of `AUTONOMY_ARCHITECTURE.md` equals `reviews/snapshots/ARCH_rev9_2.md`, `1b288d0e…2f42`, re-hashed in this session), errata E-7, E-7a, E-7b, E-7c, E-8, E-8a and E-13, and HEAD `d231497d` on `feat/data-capture-and-risk`. I wrote no files and ran nothing that changes state. The bwrap facts below are from read-only probes I ran on this host today (labelled **MEASURED**).

**Two new findings the coordinator must rule on. Both are filed as erratum requests in the Risk Register.**
- **ER-B1 (HIGH, MEASURED).** A bwrap namespace cannot be created inside the gate's own bwrap. Running `bwrap --unshare-net --dev-bind / / bwrap --ro-bind / / … true` fails with "No permissions to create a new namespace" (rc=1).
  - Cause: the host apparmor profile `bwrap-userns-restrict` moves bwrap's children into `unpriv_bwrap`.
  - `unshare -r -n` also fails here (`write failed /proc/self/uid_map`).
  - Effect: every "inside the real bwrap namespace" test (E-7c, E-7a rule 3, AUT-5 r7 `tests/integration/test_exec_snapshot.py`, AUT-4's fixture row, AUT-6 verify-first (5)) cannot run inside `scripts/ci/run_tests_no_egress.sh`.
  - Proposed fix: a second gate phase (below).
- **ER-B2 (MEDIUM).** AUT-1 r12, AUT-4 r11, AUT-5 r7 and AUT-6 r15 all name AUT-5 as owner of the wrapper, the table, the self-probe and the snapshot helper (AUT-6 r15 l.241, 1485; AUT-5 r7 l.124, 388). This brief moves them to ARCH-0 seam B.
  - The plan keeps every consumer call shape byte-compatible (`exec_snapshot(cache_dir=…, take_flock=False, lock_path=None)`).
  - AUT-5 keeps the engine adapter, `exec_snapshot.snapshot_exec_store`, which decodes halts and the intent and owns the 16:48:00 deadline. AUT-5 also keeps the E-8 `test_exec_snapshot_*` names.

---

## Acceptance Criteria

**AC-1: shared wrapper (E-7a rule 1, E-7c, E-13 ER-1)**
1. `deploy/systemd/breezy-autonomy-bwrap ROW CMD [ARGS…]` looks up `ROW` in `AUTONOMY_BWRAP_TABLE`.
   - Unknown row → exit 78. There is no default row.
   - It refuses (exit 78) unless the calling systemd unit, taken from `/proc/self/cgroup`, is in the row's `units`.
2. Every bind is validated before exec. It must be:
   - absolute, an existing directory, not a symlink anywhere on its path, and free of `..`;
   - under the data root `~/.local/share/breezy`;
   - not equal to the data root, and not equal to, under, or an ancestor of `state/`;
   - not nested inside another bind of the same row.
   
   Any violation → exit 78.
3. The wrapper builds the argv as a list and calls `os.execv("/usr/bin/bwrap", argv)`. There is no shell and no `shell=True`.
   - The mount order is fixed: `--ro-bind / /`, `--dev /dev`, `--proc /proc`, `--size N --tmpfs /tmp`, `--tmpfs ~/.config`, per-row `--ro-bind` of non-credential config files, per-row `--bind`s, `--unshare-pid` (unless the row is a named exception), `--new-session`, `--die-with-parent`, `--setenv TMPDIR /tmp`, `--setenv BREEZY_AUTONOMY_BWRAP_ROW <row>`, `--`, then the command.
4. `--size` always comes before `--tmpfs /tmp`. The value is the row's `tmpfs_size_bytes`, or `DEFAULT_TMPFS_SIZE_BYTES` (256 MiB) when the row sets none. A malformed value fails closed (exit 78 and a table-validation error).
   - **MEASURED:** `--tmpfs /tmp --size 1048576` (size after) silently gives a 16 GB tmpfs. Size before gives 1024 KiB.
5. Exec failures map to fixed codes:
   - bwrap or the command missing → 127; present but not executable → 126. Both are checked before exec, because a missing child command makes bwrap itself exit 1 (**MEASURED**).
   - Usage error → 64.
   - Rows with `notifier_fallback=True` run a preflight: the same mount argv with `/bin/true`, via a list-argv subprocess. If the preflight fails, they exec the command unwrapped with `BREEZY_AUTONOMY_SANDBOX_DEGRADED=<code>` (the E-7a notifier fallback).
6. The wrapper file and every module it imports sit outside every bind of every row.

**AC-2: self-probe (E-7 rule 2, E-7a rule 1)**
- `require_sandbox(row)` passes only when all of these hold:
  - `BREEZY_AUTONOMY_BWRAP_ROW == row`;
  - `O_WRONLY|O_CREAT|O_EXCL` FAILS (EROFS, EACCES or EPERM) under `state/`, the data root, the repo root, every existing top-level data-root directory not covered by a bind, and every ancestor of a bind;
  - the same open SUCCEEDS in every bind;
  - `stat(~/.config/breezy)` raises ENOENT;
  - `/tmp` is a tmpfs in `/proc/self/mountinfo` and a write there succeeds;
  - if the row unshares pid, `/proc/1/comm == "bwrap"`.
- Anything else raises `SandboxIntegrityError(reason_code)`. The reason code is a label with no absolute path. The caller delivers the CRITICAL and exits INTEGRITY.

**AC-3: WAL snapshot helper (E-8 steps 1–9, E-8a, E-7a rule 3)**
1. The API is `wal_snapshot(db_path, *, cache_dir, take_flock, lock_path, …)`, plus the exec-store form `exec_snapshot(*, cache_dir, take_flock, lock_path=None, …)`.
2. `take_flock=True`:
   - `lock_path` must equal `<db>.intent.lock`;
   - it is opened `O_RDONLY|O_CLOEXEC|O_NOFOLLOW`; a missing file is a read failure;
   - `flock(LOCK_EX|LOCK_NB)` up to 3 times, 5 s apart.
3. `take_flock=False` never opens `lock_path`, and the result is marked `advisory=True`.
4. The copy step:
   - fingerprint db, `-wal` and `-journal` as (inode, size, `mtime_ns`, header digest);
   - copy into a fresh 0700 `snap.*` directory under `cache_dir`, never copying `-shm`;
   - re-fingerprint; any change triggers a retry; still unstable → `FINGERPRINT_UNSTABLE`.
5. The flock is released before the copy is opened. The optional `release_deadline_ns` is enforced; missing it gives `DEADLINE` (failure reason).
6. The copy is opened read-write, `PRAGMA quick_check` must return `ok`, then `PRAGMA journal_mode=DELETE` makes the copy a single file that can be opened with `mode=ro` and no sidecars. The snapshot directory is deleted on exit in every case.
7. The result is `WalSnapshot` or `SnapshotReadFailure(reason)`, never an exception for an expected failure.
8. The cache dir and its parent are checked with `lstat`: a directory, not a symlink, owned by the caller's uid, mode 0700. Otherwise → `CACHE_DIR_MODE`.

**AC-4: lint (E-7a rule 4)**
- `tests/support/autonomy_write_lint.py` builds each entry point's `breezy.*` import closure with grimp and judges every denylisted call site.
- It fails on a site outside the caller's one-writer rows or the shared allowed sites, and when an entry point has fewer judged sites than its minimum.
- Every denylist pattern has a positive-control fixture. It is green at build.

**AC-5: unit-file lint (E-7a rule 1)**
- Every `ExecStart=` and `ExecStopPost=` of every `deploy/systemd/breezy-autonomy-*` unit and drop-in, and every line in any unit that names the wrapper, goes through the wrapper in the order `timeout -k` → (`flock -w`) → wrapper → row → command.
- No `+` or `!` prefix. The row exists and lists the unit.
- Every `OnFailure=` target of a `breezy-autonomy-*` unit is itself wrapped.

**AC-6: C4.1 ruling.** `docs/evidence/RULING_holdout_freeze_and_forward_window_2026-10-03.md` exists. The block between its markers is byte-identical to `ARCH_rev9_2.md` lines 379–392, and a test pins both the snapshot sha and the block sha.

**AC-7: gate.**
- Phase 1 (`run_tests_no_egress.sh`, unchanged) is green.
- Phase 2 (`scripts/ci/run_bwrap_host_tests.sh`) is green, with at least `BWRAP_HOST_MIN_TESTS` tests passing and none skipped.
- `lint-imports` reports "N kept, 0 broken" (console script, run from the tree).

**AC-8: real host.** Steps V0–V13 (Test Strategy) pass on the primary tree after merge and before any consumer row is filed.

## Edge Cases & NFRs

| Case | Handling |
|---|---|
| Node up; it holds the intent flock for its whole life (`app/trade.py:990` per E-8) | `take_flock=True` → `LOCK_HELD` after 3 tries. `take_flock=False` → fingerprint-only, advisory. |
| `-wal` absent (node down, clean close) | Fingerprinted as `present=False`. The db alone is copied and opened. Covered by the phase-2 "sidecars absent" test. |
| SIGKILLed node left a stale `-wal` | WAL recovery runs on the copy when it is opened read-write. `quick_check` then follows. |
| WAL reset inside one coarse mtime tick (frames rewritten, size unchanged) | The header digest (first 32 bytes of `-wal`, salts and checkpoint seq; first 100 bytes of db) is part of the fingerprint. This is **additive** to E-8's triple (see Trade-offs). V13 measures the tick on this host. |
| Writer that ignores the lock (`trade_supervisor.py:2418` at 17:05Z, per E-8) | Re-fingerprint, then retry, then `FINGERPRINT_UNSTABLE`. It never yields a silent torn copy. |
| Helper SIGKILLed while holding the flock | The kernel drops the flock with the fd. The leftover `snap.*` directory is swept by the next run (prefix-matched, no symlink follow). |
| db or a sidecar is a symlink, or the inode changes between fingerprint and open | `O_NOFOLLOW` gives `SOURCE_INVALID`. An `fstat` inode that differs from the fingerprint counts as unstable. |
| Lock file missing, symlinked, or unreadable | `LOCK_FILE_MISSING` or `LOCK_PATH_INVALID` or `LOCK_ERROR`, fail closed. An `O_RDONLY` open never creates it, unlike `submit_intent.py:561-563` (`O_CREAT|O_RDWR`). |
| Cache dir on a read-only path (wrong row) or wrong mode | `CACHE_DIR_MODE` (checked first) or `COPY_ERROR`. |
| Bind source missing at start | The wrapper exits 78 with the row and a reason code (bwrap would exit 1: "Can't find source path", MEASURED). Units create bind sources in a bounded unwrapped `ExecStartPre=install -d -m 0700`. |
| Hand run in a terminal (`.scope` cgroup) | Exit 78. Real-host runs use `systemd-run --user --unit=<row unit>`. |
| Template units (`…@prelaunch.service`, `breezy-autonomy-failed@X.service`) | A `units` entry ending in `@` matches any instance of that template. |
| `ExecStopPost` hook in a non-autonomy unit (AUT-1 `breezy-quote-tape.stop-hook`) | It shares the cgroup `breezy-quote-tape.service`. The row lists that unit. The unit lint scans every unit naming the wrapper. |
| `/proc/locks` consumers (`aut6.health`, AUT-6 evaluate) | The row sets `unshare_pid=False` and names the exception. **MEASURED:** `/proc/locks` shows 156 lines without `--unshare-pid` and 0 with it. `--proc /proc` works in both modes (rc 0). |
| `Type=notify` rows (AUT-3) | Env is passed through unchanged, so `NOTIFY_SOCKET` survives. A unix-socket connect on the ro-bind is verified in V12. |
| Env-borne credentials (AUT-2 reconcile `EnvironmentFile`) | The wrapper does not scrub env (E-7a rule 2 keeps it). File credentials under `~/.config/breezy` are always hidden, and table validation refuses any `config_ro_binds` entry under `breezy/`. |
| bwrap present but userns denied (apparmor change) | Notifier rows degrade to unwrapped with the degraded flag. Every other row fails, so systemd's `OnFailure` fires. |

**NFRs**
- Wrapper overhead p95 ≤ 50 ms (E-7a rule 5), measured in V9. If it is exceeded, switch the shebang to `-IS` with an explicit `/home/jon/breezy/src` path.
- The wrapper package imports stdlib only. `import breezy.runtime` costs 175 µs (MEASURED with `-X importtime`); `import breezy.persistence` costs 392 ms because it loads Nautilus (MEASURED), which is why the code does not live in persistence.
- Snapshot of today's store (db 81,920 B and wal 601,552 B, MEASURED) takes ≤ 1 s. The flock is held only for fingerprint + copy + re-fingerprint.
- No network use, no alert payload content (reason codes only), and no absolute paths in stderr.

## Architecture & Data Flow (API signatures, paths, layer placement)

**Layer.**
- New package `src/breezy/runtime/autonomy_sandbox/`, in the `runtime` layer (`pyproject.toml:74-101`), stdlib only.
- Why runtime:
  - `analysis` (AUT-4, AUT-5 engine, AUT-6) and `runtime` (AUT-1 CLIs, the existing notifier precedent `runtime/study_failure_notifier.py`) can both import it.
  - `breezy/runtime/__init__.py` is import-free by contract (`tests/unit/test_runtime_import_isolation.py:1-30`).
  - It cannot live under `persistence/autonomy/`, because importing `breezy.persistence` pulls in Nautilus through `persistence/__init__.py` → `catalog.py:197-199` (392 ms, against E-7a's 10–50 ms setup budget). This also avoids touching seam A's package.
- It imports no adapter, `sqlite_store` or `submit_intent`, so AUT-5's closure exclusions (r7 l.885) still hold.

**Modules and API**

```python
# table.py (data + validation; the one AUTONOMY_BWRAP_TABLE)
DEFAULT_TMPFS_SIZE_BYTES: Final[int] = 256 * 1024 * 1024
MAX_TMPFS_SIZE_BYTES: Final[int] = 16 * 1024**3
class TableError(ValueError): ...
@dataclass(frozen=True, slots=True)
class SandboxRoots:            # root substitution for tests (AUT-4 LOW-2 request)
    home: Path; data_root: Path; repo_root: Path
    @classmethod
    def production(cls) -> "SandboxRoots"   # pwd.getpwuid(os.getuid()).pw_dir, never $HOME
@dataclass(frozen=True, slots=True)
class BwrapRow:
    name: str                         # "breezy-autonomy-engine@prelaunch", "…-producer-intraday#evaluate"
    owner_plan: str                   # "AUT-5"
    units: frozenset[str]             # exact unit names, or "template@" prefixes
    binds: tuple[str, ...]            # data-root-relative, e.g. "registry", "evidence/alerts"
    entry_modules: tuple[str, ...]    # wrapped Python entry modules (lint input)
    config_ro_binds: tuple[str, ...] = ()   # ~/.config-relative regular files; never under "breezy/"
    unshare_pid: bool = True
    tmpfs_size_bytes: int | None = None
    exceptions: frozenset[str] = frozenset()  # e.g. "E7A_R2_PROC_LOCKS", "E7A_R2_NOTIFY", "E7A_R2_RECONCILE", "E7B_EVAL_OFFLINE"
    notifier_fallback: bool = False
AUTONOMY_BWRAP_TABLE: Final[Mapping[str, BwrapRow]]   # seam B ships ONE row: "breezy-autonomy-selftest"
def validate_table(table=AUTONOMY_BWRAP_TABLE) -> None          # raises TableError; exact-set rules
def resolve_binds(row, roots) -> tuple[Path, ...]               # validated absolute paths
def self_probe_plan(row, roots) -> SelfProbePlan                # negative/positive paths (AUT-6 AUT6_SELF_PROBE_PATHS derives from this)

# bwrap.py (argv builder + wrapper main)
EXIT_USAGE, EXIT_CONFIG, EXIT_NOT_EXECUTABLE, EXIT_NOT_FOUND = 64, 78, 126, 127
BWRAP_PATH: Final[str] = "/usr/bin/bwrap"
def build_bwrap_argv(row: BwrapRow, command: Sequence[str], *, roots: SandboxRoots,
                     extra_namespace_flags: Sequence[str] = ()) -> list[str]
def current_unit_name(cgroup_text: str) -> str | None           # last path component of the "0::" line
def main(argv: Sequence[str], *, roots: SandboxRoots | None = None,
         cgroup_path: Path = Path("/proc/self/cgroup"), bwrap_path: str = BWRAP_PATH) -> int  # execs on success

# self_probe.py
class SandboxIntegrityError(RuntimeError): reason_code: str
@dataclass(frozen=True, slots=True) class SelfProbeResult: ok: bool; degraded: bool; failures: tuple[str, ...]
def run_self_probe(row_name: str, *, roots: SandboxRoots | None = None) -> SelfProbeResult
def require_sandbox(row_name: str, *, roots: SandboxRoots | None = None) -> SelfProbeResult  # raises on not ok

# wal_snapshot.py
EXEC_STORE_FILENAME: Final[str] = "exec_polymarket_us.sqlite"
INTENT_LOCK_SUFFIX: Final[str] = ".intent.lock"     # mirrors submit_intent.py:558
class SnapshotFailureReason(StrEnum): CACHE_DIR_MODE, LOCK_PATH_INVALID, LOCK_FILE_MISSING, LOCK_HELD,
    LOCK_ERROR, SOURCE_INVALID, FINGERPRINT_UNSTABLE, COPY_ERROR, QUICK_CHECK, DEADLINE
@dataclass(frozen=True, slots=True) class FileFingerprint: role: str; present: bool; inode: int|None; size: int|None; mtime_ns: int|None; header_sha256: str|None
@dataclass(frozen=True, slots=True) class WalSnapshot: path: Path; fingerprints: tuple[FileFingerprint, ...]; took_flock: bool; advisory: bool; attempts: int; taken_at_ns: int
@dataclass(frozen=True, slots=True) class SnapshotReadFailure: reason: SnapshotFailureReason; advisory: bool; attempts: int
@contextmanager
def wal_snapshot(db_path: Path, *, cache_dir: Path, take_flock: bool, lock_path: Path | None,
                 release_deadline_ns: int | None = None, flock_attempts: int = 3, flock_retry_s: float = 5.0,
                 copy_attempts: int = 3, clock_ns: Callable[[], int] = time.time_ns,
                 sleep: Callable[[float], None] = time.sleep) -> Iterator[WalSnapshot | SnapshotReadFailure]
def exec_store_paths(data_root: Path | None = None) -> tuple[Path, Path]    # (db, lock); default = production data root
@contextmanager
def exec_snapshot(*, cache_dir: Path, take_flock: bool, lock_path: Path | None = None,
                  data_root: Path | None = None, **kw) -> Iterator[WalSnapshot | SnapshotReadFailure]
def connect_snapshot_readonly(snap: WalSnapshot) -> sqlite3.Connection    # file:<p>?mode=ro, uri=True; PRAGMA query_only=ON

# selftest_cli.py  (python -I -m breezy.runtime.autonomy_sandbox.selftest_cli)
def main(argv: Sequence[str] | None = None) -> int   # require_sandbox("breezy-autonomy-selftest"), /tmp marker, optional --exec-snapshot; prints one JSON line
```

**Data flow (wrapper)**
1. systemd runs `ExecStart=/usr/bin/timeout -k … [flock -w … <lock>] /home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap <row> <cmd…>`.
2. The wrapper script (shebang `/home/jon/breezy/.venv/bin/python3 -I`) calls `bwrap.main`, which does the following in order:
   - `validate_table()`;
   - row lookup;
   - unit match against `/proc/self/cgroup`;
   - bind validation;
   - bwrap and command present and executable;
   - `[notifier preflight]`;
   - `os.execv(bwrap, argv)`.
3. Inside the sandbox, the entry point first calls `require_sandbox(row)`. On failure it delivers the CRITICAL through AUT-6's `deliver_with_proof` and exits INTEGRITY. This seam returns the error only, because it cannot import AUT-6.

**Data flow (snapshot)**
1. Check `cache_dir` and its parent; sweep `snap.*`.
2. If `take_flock`: open the lock `O_RDONLY` and take the flock (3 tries × 5 s, bounded by the deadline).
3. Loop up to `copy_attempts` times:
   - fingerprint;
   - `mkdtemp(prefix="snap.", dir=cache_dir)` (0700);
   - copy db, `-wal` and `-journal` if present, using `O_RDONLY|O_NOFOLLOW` source, `fstat` inode check, and `O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW 0600` destination, in 1 MiB read/write chunks;
   - re-fingerprint; equal → break, else rmtree and retry.
4. Check the deadline, then release the flock.
5. `sqlite3.connect(copy)` (path asserted under `cache_dir`), then `quick_check == [("ok",)]`, then `journal_mode=DELETE` returns `delete`; close; assert no `-wal` or `-shm` remain.
6. Yield `WalSnapshot`.
7. `finally`: release the flock if still held, and `rmtree` the snapshot directory (path asserted under `cache_dir`).

**Phase-2 gate.**
- `scripts/ci/run_bwrap_host_tests.sh` refuses to run inside phase 1 (`BREEZY_TEST_OS_EGRESS_BLOCK` set → exit 3).
- It checks that bwrap can create a namespace, exports `BREEZY_BWRAP_HOST_PHASE=1`, and runs `python -m pytest -m bwrap_host tests/integration/autonomy_sandbox`.
- Every bwrap child that the tests spawn goes through `tests/support/bwrap_harness.py`, which adds `--unshare-net`. So test children have no egress, and the pytest parent keeps conftest's in-process block (`tests/conftest.py:359-380`).

## Consumer Surface (table: consumer plan §, call it makes, delivered here)

| Consumer plan § | Call it makes | Delivered here |
|---|---|---|
| AUT-1 r12 l.662, l.1112 (stop hook) | `ExecStopPost=-/usr/bin/timeout -k 2 10 …/breezy-autonomy-bwrap breezy-quote-tape.stop-hook /home/jon/breezy/.venv/bin/python3 -m breezy.runtime.capture_recorder_hook_cli` | Wrapper; row-name/unit decoupling (row `breezy-quote-tape.stop-hook` lists unit `breezy-quote-tape.service`); the unit lint scans non-autonomy units that name the wrapper. AUT-1 files the row. |
| AUT-1 r12 l.875, 939 | Every AUT-1 unit and `OnFailure=` target is wrapped. Capture-audit reads the exec store with `take_flock=False`. | `exec_snapshot(cache_dir=…, take_flock=False)` (advisory). AC-5 lint. |
| AUT-2 r7 (E-7a consumption: reconcile-poststop, GET egress, `EnvironmentFile`) | Wrapped reconcile units; FQ scorer reads the exec store | Network is never unshared and env passes through, so the Rule-2 exception holds. **Change flagged:** under E-7a rule 3 the wrapped AUT-2 must use `exec_snapshot(take_flock=False)`, not the in-place G6 URI that E-8 allowed for *unwrapped* readers. Label `E7A_R2_RECONCILE` for the lint. |
| AUT-3 r6 (E-7a rule 2) | `Type=notify` refit and `reproduce-pm`, `NotifyAccess=all` | Env is untouched; V12 proves `systemd-notify` through the ro-bind; label `E7A_R2_NOTIFY`, which the unit lint checks against `NotifyAccess=all`. |
| AUT-4 r11 l.27, 862, 874-875, 893, 905-907, 1374 | Three rows with `tmpfs_size_bytes` of 2 GiB, 2 GiB and 128 MiB; `timeout -k 20s 6270s flock -w 900 <studies lock> breezy-autonomy-bwrap breezy-autonomy-eval-offline …`; wrapper merged and deployed **before** any AUT-4 row; deployed-blob sha check; "wrapper harness's root substitution" | `tmpfs_size_bytes`; `DEFAULT_TMPFS_SIZE_BYTES`; malformed fails closed; `test_bwrap_wrapper_provides_private_tmp`; `SandboxRoots` and `tests/support/bwrap_harness.run_in_row`; V11 sha check; `E7B_EVAL_OFFLINE` exception label (AUT-4 owns its closure tests). |
| AUT-4 r11 l.898 (WP0 baseline, WAL inventory) | `take_flock=False` snapshot of the exec store and of any WAL input | `wal_snapshot(db_path, …, take_flock=False, lock_path=None)` (generic) and `exec_snapshot`. |
| AUT-5 r7 l.124, 202, 276-283 | Engine rows per mode (`@daily/@intraday/@prelaunch/@bootstrap` + `derived/artefacts`; stage-S variants + `registry-shadow`); self-probe (state EROFS, own bind writable, `~/.config/breezy` ENOENT); `OnFailure=` | Table rows (AUT-5 files them); `require_sandbox`. **Change flagged:** r7's inline `/usr/bin/bwrap …` ExecStart becomes the wrapper (coordinator: mechanical), and `OnFailure=breezy-study-failed@%n` (r7 l.276) fails AC-5 until it points at AUT-6's wrapped `breezy-autonomy-failed@`. |
| AUT-5 r7 l.388-405 (E-8 at 16:45) | `snapshot_exec_store(...) -> ExecSnapshot \| ReadFailure` with flock, 16:48:00 deadline, cache-dir mode, `quick_check` | `exec_snapshot(cache_dir=…/cache/engine_exec_snapshot, take_flock=True, lock_path=exec_store_paths()[1], release_deadline_ns=<16:48:00>)`; reasons map 1:1 (`cache_dir_mode`, `lock_file_missing`, `lock_held`, `fingerprint_unstable`, `deadline`, `quick_check`). AUT-5 keeps the halt and intent decode and the `test_exec_snapshot_*` names. |
| AUT-6 r15 l.241, 262, 266, 1485 | Seven rows (two with `unshare_pid=False`); `AUT6_SELF_PROBE_PATHS` derived from the table; `exec_snapshot(cache_dir=~/.local/share/breezy/cache/aut6_intraday_exec_snapshot, take_flock=False, lock_path=None)`; AST check on the literal `False` | `self_probe_plan()`; exact kwarg names; `advisory=True`; `E7A_R2_PROC_LOCKS` label with `test_proc_locks_reference_requires_unshare_pid_false_row`; `notifier_fallback` for `breezy-autonomy-failed`. |
| AUT-7 r5 | Inherits the engine row; `registry/drill/` in its bind set | Covered by the engine's `registry` bind; nested binds within a row are refused. |
| AUT-3, AUT-4 (C4.1) | Cite `RULING_holdout_freeze_and_forward_window_2026-10-03` by name | `docs/evidence/` file, filed verbatim (WP-B1) before any AUT-3 fit or AUT-4 screen (ARCH §5.1 l.1044). |

## File-by-File Plan (absolute path | new|modified | exact content | deps)

| Path | N/M | Content | Deps |
|---|---|---|---|
| `/home/jon/breezy/docs/evidence/RULING_holdout_freeze_and_forward_window_2026-10-03.md` | N | See skeleton below | ARCH snapshot |
| `/home/jon/breezy/tests/unit/test_holdout_ruling_filed_verbatim.py` | N | Extracts the `### C4.1 — ` section from `reviews/snapshots/ARCH_rev9_2.md` up to the next `### ` heading, with trailing blank lines stripped. Compares bytes. Pins the snapshot sha and the block sha. Includes a one-byte mutation control. Pattern follows `tests/unit/test_live_orders_ruling_deploy_copy_matches_evidence.py:22-60`. | stdlib |
| `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/__init__.py` | N | Docstring only (import-free, matching the runtime-package contract) | — |
| `…/autonomy_sandbox/table.py` | N | API above. `AUTONOMY_BWRAP_TABLE` = `{"breezy-autonomy-selftest": BwrapRow(owner_plan="ARCH-0", units=frozenset({"breezy-autonomy-selftest.service"}), binds=("cache/autonomy_selftest",), entry_modules=("breezy.runtime.autonomy_sandbox.selftest_cli",))}`. `validate_table` rules are listed below. | stdlib |
| `…/autonomy_sandbox/bwrap.py` | N | `build_bwrap_argv` in the AC-1.3 order. `main` follows the data-flow order. The only spawn is the notifier preflight, `subprocess.run(list, check=False, timeout=10)`. Errors go to stderr as `breezy-autonomy-bwrap: row=<r> reason=<code>`. | `table` |
| `…/autonomy_sandbox/self_probe.py` | N | AC-2 checks. Probe files are named `.autonomy_probe_<sanitised-row>_<pid>_<ns>`, opened `O_EXCL`, and unlinked right after any open that succeeds (on a negative path, a success is first unlinked, then reported). | `table` |
| `…/autonomy_sandbox/wal_snapshot.py` | N | AC-3 algorithm, per the data flow above | stdlib `sqlite3`, `fcntl`, `hashlib` |
| `…/autonomy_sandbox/selftest_cli.py` | N | `require_sandbox`; writes `/tmp/breezy_selftest_<INVOCATION_ID>`; reads the `/tmp` mountinfo `size=`; `--exec-snapshot N` runs N advisory snapshots into `cache/autonomy_selftest`. Prints `{"ok":…, "tmp_marker":…, "tmp_size_kib":…, "snap": {"ok":k, "unstable":u}}`. | all above |
| `/home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap` | N (git mode 0755) | Wrapper script, below | `bwrap.main` |
| `/home/jon/breezy/scripts/ci/run_bwrap_host_tests.sh` | N | Phase-2 script, below | bwrap |
| `/home/jon/breezy/tests/support/bwrap_harness.py` | N | `run_in_row(row: BwrapRow \| str, command, *, roots, timeout_s=30) -> CompletedProcess`. Calls `build_bwrap_argv(..., extra_namespace_flags=("--unshare-net",))`. `make_roots(tmp_path)` builds `home/.config/breezy/`, `data/state/`, `data/cache/` (0700) and `repo/`. | `bwrap` |
| `/home/jon/breezy/tests/support/autonomy_write_lint.py` | N | Shared lint (AC-4), below | grimp 3.15 (installed), ast |
| `/home/jon/breezy/tests/fixtures/autonomy_lint/*.py` | N | One positive-control module per denylist pattern, plus aliased-import and attribute-receiver evasions (as in `test_polymarket_us_exec_refusals.py:574-585`) | — |
| `/home/jon/breezy/tests/integration/autonomy_sandbox/conftest.py` | N | Registers `bwrap_host` via `config.addinivalue_line` (no edit to pyproject `addopts`/`markers`, L-54). Outside phase 2, marked tests are skipped with reason `phase-2 (nested userns denied: bwrap-userns-restrict)`. Inside phase 2, a missing bwrap is `pytest.fail`, never a skip. Session-finish asserts passed ≥ `BWRAP_HOST_MIN_TESTS`. | pytest |
| `/home/jon/breezy/tests/integration/autonomy_sandbox/test_bwrap_wrapper_namespace.py`, `test_wal_snapshot_namespace.py` | N | Phase-2 tests (Test Strategy) | harness |
| `/home/jon/breezy/tests/unit/test_autonomy_sandbox_table.py`, `test_autonomy_bwrap_argv.py`, `test_autonomy_units_wrapped.py`, `test_autonomy_self_probe.py`, `test_wal_snapshot.py`, `test_autonomy_write_lint_controls.py`, `test_run_bwrap_host_tests_script.py` | N | Phase-1 tests (Test Strategy) | — |
| `/home/jon/breezy/deploy/systemd/README.md` | M | New section "Autonomy bwrap wrapper (E-7/E-7a)": nothing is symlinked (units call the repo path); V0–V13 commands; the phase-2 gate; directives are configuration only. | — |

**`validate_table` rules (exact-set; widened only per L-12)**
- The key equals `row.name`, and the name matches `^breezy-[a-z0-9-]+(@[a-z0-9-]*)?([.#][a-z0-9-]+)?$`.
- `units` is non-empty, and each entry matches `^breezy-[a-z0-9@.-]+(\.service|@)$`.
- `binds` is non-empty, relative, contains no `..` or empty segment, and does not start with `state`. Binds within a row are not nested. No bind is `""` or `"."`.
- `config_ro_binds` is relative, does not start with `breezy`, and contains no `..`.
- `tmpfs_size_bytes` is None, or an `int` (not `bool`) with 0 < v ≤ `MAX_TMPFS_SIZE_BYTES`.
- `exceptions` ⊆ `KNOWN_EXCEPTIONS = {"E7A_R2_PROC_LOCKS", "E7A_R2_NOTIFY", "E7A_R2_RECONCILE", "E7B_EVAL_OFFLINE"}`.
- `unshare_pid=False` requires `"E7A_R2_PROC_LOCKS"` in `exceptions`.
- `notifier_fallback=True` requires the row name to start with `breezy-autonomy-failed` or to be listed in `NOTIFIER_ROWS`.

**Wrapper script (exact)**

```python
#!/home/jon/breezy/.venv/bin/python3 -I
"""E-7a rule 1 shared wrapper. Usage: breezy-autonomy-bwrap ROW CMD [ARGS...]. See deploy/systemd/README.md."""
import sys
from breezy.runtime.autonomy_sandbox.bwrap import main
sys.exit(main(sys.argv[1:]))
```

**Phase-2 script (exact core)**

```bash
#!/usr/bin/env bash
# Phase 2 of the gate (ER-B1): tests that must create their own bwrap namespace.
# Nested bwrap inside run_tests_no_egress.sh is denied by apparmor
# (bwrap-userns-restrict -> unpriv_bwrap). Every bwrap child here carries
# --unshare-net (tests/support/bwrap_harness.py); the pytest parent keeps the
# conftest in-process egress block. Run AFTER run_tests_no_egress.sh, both required.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$REPO_ROOT"
PYTHON="${BREEZY_PYTHON:-$REPO_ROOT/.venv/bin/python}"
[[ -x "$PYTHON" ]] || { echo "error: interpreter not found at $PYTHON" >&2; exit 2; }
[[ -z "${BREEZY_TEST_OS_EGRESS_BLOCK:-}" ]] || { echo "error: phase 2 cannot run nested in phase 1" >&2; exit 3; }
bwrap --unshare-net --unshare-pid --ro-bind / / --dev /dev --proc /proc true \
  || { echo "error: bwrap cannot create namespaces on this host" >&2; exit 3; }
export BREEZY_BWRAP_HOST_PHASE=1
exec "$PYTHON" -m pytest -m bwrap_host tests/integration/autonomy_sandbox "$@"
```

**Shared lint (`autonomy_write_lint.py`) contents**
- `DENYLIST`, matched by resolved name with import-alias tracking:
  - `open`/`io.open`/`os.fdopen`/`Path.open` with a non-literal mode or a mode containing `w`, `a`, `x` or `+`;
  - `os.open` whose flags name `O_WRONLY`/`O_RDWR`/`O_CREAT`/`O_TRUNC`/`O_APPEND`, or are not a literal;
  - `Path.{write_text, write_bytes, touch, mkdir, unlink, rename, replace, chmod, rmdir, symlink_to, hardlink_to}`;
  - `os.{replace, rename, link, symlink, unlink, remove, rmdir, mkdir, makedirs, chmod, chown, utime, truncate, ftruncate}`;
  - `shutil.{copy*, move, rmtree}`; `tempfile.{mkstemp, mkdtemp, NamedTemporaryFile, TemporaryDirectory}`;
  - `sqlite3.connect` unless the first argument is a literal or f-string containing `mode=ro` and `uri=True`;
  - `SqliteStateStore(`; `subprocess.*`; `os.system`; `os.exec*`; `os.spawn*`; `os.posix_spawn*`; `ctypes.*`; `importlib.import_module`; `__import__`.
- The literal `/proc/locks` is a tagged reference, not a write.
- `SHARED_ALLOWED_SITES`: the `wal_snapshot` cache-dir writes and the read-write connect on the copy, plus `self_probe`'s probe opens and unlinks. Each site is pinned by (module, function, call).
- `closure(entry_modules) -> frozenset[str]` uses `grimp.build_graph("breezy")` and adds ancestor `__init__` edges (the R3-1 precedent, `test_runtime_import_isolation.py:15-22`).
- `judge(entry_modules, allowed: Mapping[str, frozenset[str]], min_judged_sites: int) -> LintReport`, with `report.offenders` and `report.judged`.
- `assert_lint_clean(...)`: fails on offenders and on `judged < min_judged_sites`.
- `proc_locks_references(entry_modules) -> list[str]`.

**C4.1 ruling file (skeleton; the block is copied by byte-slice, never retyped)**

```markdown
# RULING — holdout freeze and forward window (2026-10-03)

Status: ARCH-owned text (Rev 9.2 §C4.1; P3-1, P4-1), filed verbatim in Wave 0 by ARCH-0 seam B after the
seam-B plan's peer review. Not an operator decision. Source: docs/plans/backlog/AUTONOMY_2026-10-03/reviews/
snapshots/ARCH_rev9_2.md lines 379–392, sha256 1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42.
Changing the text below is an ARCH change, re-reviewed (item 4). AUT-3 and AUT-4 cite this file by name.

<!-- BEGIN VERBATIM ARCH Rev 9.2 §C4.1 -->
<bytes of ARCH_rev9_2.md lines 379–392, unmodified>
<!-- END VERBATIM ARCH Rev 9.2 §C4.1 -->

Filing note (not part of the ruling): at HEAD d231497d, DEFAULT_SPLITS is
src/breezy/analysis/nbp_calibration.py:273-278 (no holdout_end_exclusive yet; AUT-3's L-12 widening adds it);
the single-look marker is HoldoutSingleLookError :334 and open_holdout :353-399 (the frozen text's
":330-345" predates line drift; the text is not edited).
```

## Test Strategy (file | test names | type | failure path)

All phase-1 tests run under `scripts/ci/run_tests_no_egress.sh`. All `bwrap_host` tests run under `scripts/ci/run_bwrap_host_tests.sh`. Fixture WAL stores are written through the real `SqliteStateStore` writer (`sqlite_store.py:117-126`, WAL plus `synchronous=FULL`), per L-42.

| File | Tests | Type | Failure path proven |
|---|---|---|---|
| `tests/unit/test_holdout_ruling_filed_verbatim.py` | `test_c4_1_ruling_file_exists_under_docs_evidence`; `test_frozen_arch_snapshot_sha_is_rev9_2`; `test_c4_1_block_byte_identical_to_frozen_arch_section`; `test_c4_1_block_sha256_pinned`; `test_c4_1_comparator_detects_a_one_byte_variant` | unit | A missing file, a drifted snapshot, a restated variant, and a vacuous comparator all fail |
| `tests/unit/test_autonomy_sandbox_table.py` | `test_table_validates`; `test_unknown_row_has_no_default`; `test_no_row_binds_state_or_its_ancestor`; `test_binds_relative_no_dotdot_not_nested`; `test_config_ro_binds_never_under_breezy`; `test_tmpfs_size_default_applies_to_rows_without_value`; `test_bwrap_table_malformed_tmpfs_size_fails_closed` (bool, 0, −1, str, > max); `test_unshare_pid_false_requires_named_exception`; `test_exceptions_exact_set`; `test_wrapper_and_package_outside_every_bind`; `test_autonomy_sandbox_imports_stdlib_only` (fresh `python -I` child, `sys.modules` has no `nautilus_trader`/`pyarrow`/`breezy.adapters`); `test_autonomy_sandbox_init_is_import_free` | unit | Every validation rule has a failing fixture row |
| `tests/unit/test_autonomy_bwrap_argv.py` | `test_argv_order_ro_root_dev_proc_size_tmpfs_config_binds`; `test_bwrap_wrapper_tmpfs_size_precedes_tmpfs`; `test_credentials_tmpfs_precedes_config_rebinds`; `test_unshare_pid_omitted_only_for_exception_rows`; `test_setenv_tmpdir_and_row`; `test_command_after_double_dash_verbatim`; `test_main_unknown_row_exits_78`; `test_main_unit_mismatch_exits_78`; `test_main_template_unit_matches_at_prefix`; `test_main_missing_bind_source_exits_78`; `test_main_bwrap_missing_127_not_executable_126`; `test_main_command_missing_127`; `test_main_bare_command_resolves_only_in_venv_bin`; `test_notifier_preflight_failure_execs_unwrapped_with_degraded_env` (fake execv); `test_non_notifier_never_falls_back`; `test_main_production_default_reads_real_cgroup_and_refuses` (L-55: no injection; the pytest cgroup is not a row unit → 78); `test_bwrap_module_has_no_shell` (AST: no `shell=True`/`os.system`) | unit | Each exit code; a mutant that swaps `--size` after `--tmpfs` turns `…precedes_tmpfs` red |
| `tests/unit/test_autonomy_units_wrapped.py` | `test_every_autonomy_unit_execs_through_wrapper` (ExecStart and ExecStopPost, drop-ins included); `test_wrapper_lines_order_timeout_flock_wrapper`; `test_wrapper_lines_name_existing_row_listing_the_unit`; `test_wrapped_lines_have_no_plus_or_bang_prefix`; `test_every_autonomy_onfailure_target_is_wrapped`; `test_notify_exception_rows_have_notify_access_all`; `test_execstartpre_only_bounded_install_or_chmod`; `test_unit_lint_positive_controls` (in-test fixture units: unwrapped, wrong order, unknown row, unwrapped `OnFailure`) | unit (config) | Non-vacuous while no `breezy-autonomy-*` unit exists yet, because the positive controls assert detection |
| `tests/unit/test_autonomy_self_probe.py` | `test_self_probe_plan_negatives_include_state_dataroot_repo_bind_ancestors`; `test_self_probe_plan_derived_from_table_not_literal`; `test_self_probe_fails_when_env_row_missing`; `test_self_probe_unwrapped_state_writable_is_integrity` (tmp roots, no bwrap: the negative open succeeds → `state_writable`, probe file removed); `test_reason_codes_carry_no_absolute_paths` | unit | Unwrapped-run detection |
| `tests/unit/test_wal_snapshot.py` | `test_wal_snapshot_take_flock_true_holds_flock_on_readonly_fd` (a second `LOCK_EX\|LOCK_NB` from a child fails while held, and the fd flags are `O_RDONLY`); `test_wal_snapshot_take_flock_false_never_opens_lock_path` (`sys.addaudithook` `open` events, precedent `tests/support/real_tree_write_guard.py`); `test_take_flock_true_requires_lock_path_beside_db`; `test_lock_file_missing_fails_closed_and_is_not_created`; `test_lock_held_after_three_attempts_is_lock_held` (injected sleep, 3 × 5 s); `test_never_copies_shm`; `test_fingerprint_change_retries_then_unstable`; `test_wal_reset_same_size_detected_by_header_digest`; `test_copy_opens_mode_ro_without_sidecars`; `test_quick_check_failure_is_read_failure` (corrupted page in copy); `test_deadline_releases_flock_and_reports_deadline`; `test_flock_released_before_quick_check`; `test_cache_dir_wrong_mode_owner_or_symlink_is_cache_dir_mode`; `test_snapshot_dir_removed_on_every_outcome`; `test_leftover_snap_dirs_swept_never_following_symlinks`; `test_recovers_stale_wal_after_sigkill` (child writer SIGKILLed mid-transaction; committed rows present, uncommitted absent); `test_racing_writer_never_silent_miss` (an unlocked writer loop: every result holds all commits before its first fingerprint, or is a read failure); `test_exec_store_paths_match_node_and_supervisor` (db name = `breezy-score-live-trials.service:69` literal; lock = `trade_supervisor.intent_lock_path`, `trade_supervisor.py:304-307`); `test_exec_store_paths_default_is_pwd_home_data_root` (L-55); `test_exec_snapshot_kwargs_match_consumer_call_shape`; `test_take_flock_true_call_sites_allowlisted` (AST over `src/`: only `breezy.analysis.autonomy_engine.exec_snapshot` may pass `True`; the allowlist starts empty) | unit and integration (fs, no bwrap) | Each `SnapshotFailureReason` value |
| `tests/unit/test_autonomy_write_lint_controls.py` | `test_each_denylist_pattern_flagged` (parametrised over fixtures); `test_aliased_and_attribute_receivers_flagged`; `test_mode_ro_connect_not_flagged`; `test_shared_allowed_sites_pinned`; `test_min_judged_sites_enforced`; `test_selftest_entry_closure_lint_clean`; `test_proc_locks_reference_requires_unshare_pid_false_row` (over every table row's `entry_modules`) | unit | Positive controls (E-7a rule 4) |
| `tests/unit/test_run_bwrap_host_tests_script.py` | `test_phase2_refuses_inside_phase1`; `test_phase2_script_targets_only_bwrap_host_dir` | unit | Exit 3 when `BREEZY_TEST_OS_EGRESS_BLOCK=1` |
| `tests/integration/autonomy_sandbox/test_bwrap_wrapper_namespace.py` (`bwrap_host`) | `test_bwrap_probe_state_write_erofs`; `test_bwrap_own_bind_writable`; `test_bwrap_repo_and_bind_ancestors_erofs`; `test_bwrap_credentials_tmpfs_hides_config_breezy`; `test_bwrap_wrapper_provides_private_tmp` (E-7c: write OK, not visible on host, state still EROFS); `test_bwrap_tmpfs_size_matches_row_and_default` (mountinfo `size=`); `test_bwrap_binds_are_distinct_mounts_exdev_positive_control` (cross-bind rename → EXDEV; same-bind rename OK); `test_bwrap_unshare_pid_hides_proc_locks_exception_row_sees_them`; `test_self_probe_passes_inside_row_and_fails_with_wrong_row`; `test_harness_children_have_no_network` (connect to 198.51.100.7:80 → ENETUNREACH) | integration (real namespace) | Directive-free enforcement (E-7 rule 1) |
| `tests/integration/autonomy_sandbox/test_wal_snapshot_namespace.py` (`bwrap_host`) | `test_wal_snapshot_under_bwrap_sidecars_present`; `test_wal_snapshot_under_bwrap_sidecars_absent`; `test_mode_ro_in_place_fails_under_bwrap_without_sidecars` (control proving rule 3's premise); `test_take_flock_true_under_bwrap_readonly_lock` | integration | E-7a rule 3 |

**Real-host verification.** These run on the **primary tree after merge** (`-I` resolves the editable install, which points at the primary tree: L-51 and the worktree-PYTHONPATH note). Each must pass exactly as stated.
- **V0.** `cd /home/jon/breezy && scripts/ci/run_bwrap_host_tests.sh -q` → exit 0. Also confirm that conftest's `pytest_sessionstart` does not abort an unattested phase-2 session (`tests/conftest.py:359-380`).
- **V1.** `install -d -m 0700 ~/.local/share/breezy/cache ~/.local/share/breezy/cache/autonomy_selftest`
- **V2.** `systemd-run --user --wait --pipe --collect --unit=breezy-autonomy-selftest -p LimitNOFILE=524288 -p TimeoutStartSec=60 /home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap breezy-autonomy-selftest /home/jon/breezy/.venv/bin/python3 -I -m breezy.runtime.autonomy_sandbox.selftest_cli` → exit 0. The JSON shows `"ok": true`, and `tmp_size_kib` = 262144.
- **V3.** After V2: `test ! -e /tmp/breezy_selftest_<INVOCATION_ID from V2 JSON>` (E-7c host invisibility).
- **V4.** Same as V2 with row `breezy-autonomy-nonexistent` → `status=78`.
- **V5.** `systemd-run … --unit=breezy-autonomy-selftest-mismatch … breezy-autonomy-bwrap breezy-autonomy-selftest …` → `status=78`.
- **V6.** `systemd-run --user --wait --pipe --collect --unit=breezy-autonomy-selftest …/breezy-autonomy-bwrap breezy-autonomy-selftest /bin/sh -c 'touch ~/.local/share/breezy/state/.v6; echo rc=$?'` → prints a nonzero rc and "Read-only file system". `ls -a ~/.local/share/breezy/state | grep -c '^\.v6$'` → 0.
- **V7.** As V6 with `touch /home/jon/breezy/.v7` → EROFS (the repo is unwritable).
- **V8.** As V6 with `cat /proc/1/comm` → `bwrap`.
- **V9.** Overhead: 20 × V2 with `/bin/true` against 20 × the same `systemd-run` without the wrapper. Report the p95 delta. It must be ≤ 50 ms, otherwise apply the `-IS` fallback.
- **V10.** Node up: V2 with `--exec-snapshot 20`. Record `ok/unstable` (input to AUT-6 R-34's 0.99 settle rate). The exec store has no new files: `ls ~/.local/share/breezy/state` is unchanged.
- **V11.** `sha256sum /home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap` equals `git -C /home/jon/breezy show <merge_sha>:deploy/systemd/breezy-autonomy-bwrap | sha256sum` (AUT-4 l.875).
- **V12.** `systemd-run --user --wait --collect --unit=breezy-autonomy-selftest -p Type=notify -p NotifyAccess=all …/breezy-autonomy-bwrap breezy-autonomy-selftest /bin/sh -c 'systemd-notify --ready; sleep 1'` → result success (AUT-3 notify row premise).
- **V13.** mtime tick, in the session scratchpad: `python3 -c` writes two appends <1 ms apart to one file and prints both `st_mtime_ns`. Equal values confirm the header-digest guard is needed. Either way the guard stays.

## Work Packages (1–3 commit-sized WPs, order)

**Order:** WP-B1 ‖ WP-B2 → WP-B3. B1 is independent and goes first, so the ruling is filed before any AUT-3 fit or AUT-4 screen. B3 needs B2's harness and table.

| WP | Scope | RED → GREEN | Done when |
|---|---|---|---|
| **WP-B1: C4.1 ruling** (`docs:`) | Ruling file and verbatim test | RED: test fails (file absent). GREEN: file created by byte-slice of snapshot lines 379–392; block sha literal computed and pinned. | Phase 1 green; `test_no_module_under_src_reads_docs_evidence` (`test_probe_containment.py:550-558`) unchanged and green |
| **WP-B2: wrapper, table, self-probe, phase-2 gate** (`feat:`) | `table.py`, `bwrap.py`, `self_probe.py`, `selftest_cli.py`, the wrapper script, `run_bwrap_host_tests.sh`, `bwrap_harness.py`, the integration conftest, the unit-file lint, README | RED first: unit tests and namespace tests. Mutation evidence (L-33): `--size` after `--tmpfs`, dropping `--tmpfs ~/.config`, and dropping the cgroup check each turn a named test red. | Phase 1 + phase 2 green; `lint-imports` "N kept, 0 broken" (`cd` into the tree; worktree `PYTHONPATH` set); V0–V9, V11, V12 pass on the primary tree after merge, before any consumer row |
| **WP-B3: WAL snapshot and shared lint** (`feat:`) | `wal_snapshot.py`, `autonomy_write_lint.py` and fixtures, lint-controls tests, snapshot unit and namespace tests, `selftest_cli --exec-snapshot` | RED first. Mutation evidence: removing the re-fingerprint turns `test_racing_writer_never_silent_miss` red; removing the header digest turns `…header_digest` red; copying `-shm` turns `test_never_copies_shm` red. | Both phases green; lint-imports; V10, V13 recorded in merge evidence |

**Each WP brief carries:**
- exact interpreter `/home/jon/breezy/.venv/bin/python`; never `uv`/`pip`; never `git stash`; `systemd-run -p LimitNOFILE=524288` for unit-launched gates;
- full gate (both phases) after every merge (L-43);
- the binding invariants: Nautilus untouched; `allow_short` stays `False`; no safety, contract or settlement test weakened; no operator-reserved control assigned or named; enablement, permit and NO-SEND untouched.

## Risk Register

| # | Risk | Sev | Mitigation / owner |
|---|---|---|---|
| R1 | **ER-B1:** nested bwrap is impossible inside the gate (MEASURED). Real-namespace tests across AUT-4, AUT-5 and AUT-6 cannot run in phase 1. | HIGH | Phase-2 script (requested as the erratum: "the gate is phase 1 + phase 2"). Tests `pytest.fail`, never skip, in phase 2. Minimum-count assertion. The phase-1 skip reason names phase 2. Coordinator rules ER-B1; default if silent: adopt. |
| R2 | Phase-2 pytest parent runs without the OS egress block | MED | It collects only `tests/integration/autonomy_sandbox`. Every bwrap child carries `--unshare-net` (`test_harness_children_have_no_network`). The conftest in-process block stays active. Phase 2 refuses to run nested in phase 1. Security-reviewer sign-off required. |
| R3 | **ER-B2:** ownership move (AUT-5 → ARCH-0) | MED | Call shapes kept. AUT-5 keeps `snapshot_exec_store`, the E-8 test names and its rows. Errata row filed. |
| R4 | Coarse mtime makes the fingerprint falsely stable | MED | Header digest (additive), `quick_check`, V13 |
| R5 | `--size` order silently ignored (MEASURED) | MED | Builder order, argv test, mountinfo size test |
| R6 | Cgroup unit binding breaks for an unforeseen naming | LOW | Template `@` match; V2/V5; fails closed (a unit failure pages through `OnFailure`) |
| R7 | Notifier unwrapped fallback widens that one notifier's write scope | LOW | Only rows flagged `notifier_fallback`; degraded env flag in the CRITICAL; stated residual (E-7a rule 1) |
| R8 | AUT-2 reconcile loads credentials from a *file* under `~/.config/breezy` | MED | Table refuses that re-bind. AUT-2 verify-first must show its credentials are env-only (`EnvironmentFile`). |
| R9 | E-8 ("unwrapped AUT-2 keeps G6 URI") conflicts with E-7a (everything wrapped; no in-place WAL read under bwrap) | MED | The later erratum (E-7a) governs. `test_mode_ro_in_place_fails_under_bwrap_without_sidecars` proves the premise. Flagged for AUT-2's build item. |
| R10 | AUT-5 r7 `OnFailure=breezy-study-failed@` fails AC-5 | LOW | Consumer table note; switch to AUT-6's wrapped notifier |
| R11 | Wrapper startup exceeds E-9 budgets | LOW | V9; `-IS` fallback |
| R12 | Verification from a worktree checks the primary tree | MED | V-steps run only after merge, on the primary tree |
| R13 | Many plans editing one table literal | LOW | Rows sorted by name, appended by consumer WPs; `validate_table` in phase 1 |
| R14 | apparmor or bwrap upgrade breaks userns | LOW | Self-probe plus wrapper exit codes; AUT-6 health; notifier fallback |

## LESSONS Compliance

LESSONS headers were checked with grep before citing.

| Lesson | How it is met |
|---|---|
| L-1 (null hypothesis) | One row per new component; see the table below. |
| L-12 | `KNOWN_EXCEPTIONS`, row-field rules and the denylist are exact sets, widened with tests. |
| L-14 | Negative probe paths are derived from the table and a live data-root listing, never recalled. |
| L-22 | The flock is acquired inside the helper. A non-advisory snapshot cannot exist without it. The wrapper is the only argv constructor. |
| L-23 | Real probes; directives are configuration only (E-7). |
| L-33 | Mutation evidence is listed per WP. |
| L-42 | Fixtures are written through `SqliteStateStore`. |
| L-43 | Both gate phases after every merge. |
| L-46 | Contract tests were searched before placing the code: `test_runtime_import_isolation.py` (runtime `__init__` import-free; the subpackage `__init__` is docstring-only); `test_probe_containment.py:550-558` (src never reads `docs/evidence`; the ruling ID appears only in test and docs); credential-name scans (the wrapper names no credential env var). |
| L-50 | One cache dir per row, a unique `mkdtemp` per run, and one writer under the unit's own lock. |
| L-51 | Exact interpreter, never `uv`. |
| L-54 | No `pyproject` `addopts`/`markers` edit; the marker is registered in the subdir conftest. |
| L-55 | `test_main_production_default_reads_real_cgroup_and_refuses` and `test_exec_store_paths_default_is_pwd_home_data_root` run the production defaults. |

**L-1 null-hypothesis rows**

| Component | Evidence it is not already provided |
|---|---|
| Wrapper and table | Installed Nautilus has no `bwrap`/`bubblewrap`/`unshare(` (grep of `.venv/.../nautilus_trader`: 0 files). The only Breezy bwrap use is `scripts/ci/run_tests_no_egress.sh:36-43`: `--dev-bind / /` is writable and netns-only, so it gives no write scope. systemd directives are no-ops on this host (E-7). This is reuse of the OS tool bubblewrap 0.11.1 behind a thin wrapper. |
| Self-probe | No Breezy or Nautilus equivalent (E-7 introduces it). |
| Snapshot helper | Nautilus Python has no `sqlite3`, `flock`, `.backup(` or `wal_checkpoint` (grep: 0). Existing Breezy candidates are disqualified: `SqliteStateStore.__init__` (`sqlite_store.py:117-126`) creates dirs, sets WAL and creates a table, so it writes; `probe_open_intent` (`trade_supervisor.py:402-420`) opens through it; `intent_lock_is_free` (`trade_supervisor.py:310-330`) opens `O_RDWR` and returns True when the lock is absent, which is fail-open for E-8; `hold_submit_intent_process_lock` (`submit_intent.py:556-580`) does `O_CREAT\|O_RDWR`; the `mode=ro` idiom (`fill_time_count.py:94`, `trial_day_latch.py:363`) fails under bwrap without sidecars (E-7a rule 3). The stdlib `sqlite3.Connection.backup` would need a connection to the live source, which is the forbidden in-place open, so stdlib reuse is limited to the copy (connect, `quick_check`, `journal_mode=DELETE`). The decode is reused as is: `SubmitIntent.from_bytes` (`submit_intent.py:269-290`, used by AUT-5). |
| Lint harness | grimp 3.15 is installed. Existing scanners are single-purpose: `find_evidence_path_reads` (`test_probe_containment.py:522`) and the asdict scan (`test_polymarket_us_exec_refusals.py:563`). It reuses grimp and ast. |
| Ruling filing | Precedent: `test_live_orders_ruling_deploy_copy_matches_evidence.py:22-60`. No code. |

## Trade-offs

- **Placement in runtime, not persistence/autonomy.** This deviates from the letter of ARCH §3 ("types live in persistence/autonomy"), because this is infrastructure, not a C1–C5 contract type. The cost of the alternative was measured: 392 ms of Nautilus import per wrapper exec, which breaks E-7a's budget. Rejected alternative: a JSON table read by a bash wrapper, which would mean two sources of truth.
- **Header digest added to E-8's fingerprint triple.** It is strictly stronger, deterministic, and costs 132 bytes of extra reads. It is not a change to E-8's semantics, so it is recorded here rather than as an erratum. If reviewers disagree, it can be removed by deleting one field.
- **`journal_mode=DELETE` on the copy.** It lets AUT-6 keep its `mode=ro` reader (`trial_day_latch.py:363`) on the copy. The copy's bytes then differ from the source; no consumer hashes the copy. Rejected alternative: the backup API into a second file (double I/O, no gain).
- **Cgroup binding of the row to the unit.** It turns E-7a's "resolves its row by unit name" from a claim made in argv into a check. The cost is that hand runs must use `systemd-run`.
- **No env scrubbing.** E-7a rule 2 needs `EnvironmentFile` pass-through. File credentials are hidden by the tmpfs; env hygiene stays the job of the unit tests.
- **Phase-2 gate rather than spawning test units through `systemd-run` from inside phase 1.** The rejected option would let gate tests escape the egress sandbox through the user manager.
- **Seam B ships one row (selftest).** Consumers file their own rows (YAGNI), and those rows are checked by the same validation and lint.

## Confidence Self-Assessment

**86/100.**
- High confidence:
  - the API covers every consumer call shape (checked against AUT-1 r12, AUT-4 r11, AUT-5 r7 and AUT-6 r15 line references);
  - bwrap behaviour is MEASURED (size order, proc, `/proc/locks`, config tmpfs, nesting failure, error codes);
  - the code citations were checked through codegraph or reads at HEAD.
- Deductions:
  - −5 because ER-B1 changes the programme's gate definition and needs a coordinator ruling and security sign-off.
  - −4 because these have not yet been run: cgroup naming for templated or slice-nested user units, `NOTIFY_SOCKET` through `--unshare-pid` (V12), and the wrapper overhead (V9).
  - −3 because AUT-2's credential path and its E-8/E-7a reading are unverified.
  - −2 because the header-digest addition and the runtime placement are interpretive and may draw review comments.