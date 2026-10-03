**Verdict: APPROVE.** No HIGH or CRITICAL issues remain in r4. I read the artifacts only and ran no probes. No units were started, so there is nothing to confirm cleaned up.

## r3 finding status (checked against the plan body)

| Item | Status | Evidence |
|---|---|---|
| F1 HIGH, symlink-following unsandboxed writer | **RESOLVED** | AC-9.5 uses `mkdirat` (EEXIST tolerated) then `openat(bind_fd, ".bus_snapshot", O_DIRECTORY\|O_NOFOLLOW)`. The `fstat` checks cover directory type, `uid==euid`, `mode&077==0`, same device as the bind, and `(dev,ino)` not in `forbidden_dirs`. Create is `O_EXCL\|O_NOFOLLOW` via `dir_fd`. The sweep uses `scandir(dir_fd)`, a 32-hex regex, `lstat` `S_ISREG`, `unlink(dir_fd=)`, and a non-blocking flock on the validated fd. On any check failure, nothing is written or swept. The unlink-vs-swap race is harmless because `unlink` never follows symlinks. The planted-symlink and sweep tests and the `O_NOFOLLOW` mutation are listed. |
| F2 / C-1, collect-only bypass | **RESOLVED** | Phase 1 loads `-p tests.support.bwrap_host_phase`. The script skips phase 2 only on an exact token and a confirm file reading exactly `collect-only`. Every other state (file missing, empty, `run`, or mktemp failure) falls through to running phase 2. With `--noconftest`, `-p no:…` or `PYTEST_ADDOPTS`, the file is never written, so phase 2 runs. The script's phase-1 bwrap uses `--dev-bind / /` (`run_tests_no_egress.sh:39`), so the file is writable in phase 1. A forged claim (token present, pytest not collect-only) exits rc 2 in `pytest_configure` before any test runs, so a test cannot forge the file. |
| F3, `{instance}` injection | **RESOLVED** | The instance regex starts with `[a-z0-9]`. The substituted token is re-validated. `--` precedes unit tokens. The `breezy-x@-all.service` test exists. |
| F4, writes only after checks | **RESOLVED** | AC-9.2 runs checks 1–5 and `INVOCATION_ID` first, and `execv` is unreachable in this mode. |
| F5 | **RESOLVED** | A `-`-prefixed `touch` pre line replaces the wrapper creating the lock. The wrapper still never creates a bind source. |
| F6 | **RESOLVED** | R15, R21 and E-7e(i) now cover `127.0.0.53:53` and cmdline visibility. |
| F7 / C-2 | **RESOLVED** | `env -u PYTEST_PLUGINS -u PYTEST_ADDOPTS` is the control, and condition 6 is the backstop. |
| F8 | **RESOLVED** | The pid-namespace check is stated as an integrity check, not a boundary (AC-2.8, E-7e(d)). |
| Ruling (d), `--bus-action` | **RESOLVED** | It is removed. The grammar refuses `kill`, `start`, `stop`, `restart` and `systemd-run`. |

## E-7d: ADOPT
- **Skipping phase 2:** the only skip path needs both the exact token and the plugin-written `collect-only` file. In the script, the confirm file is created by `mktemp` and the env var is unset first.
- **Argument smuggling:** `-k --co`, `-m --co`, `--basetemp --co` and similar are argparse usage errors. After `--`, `--co` becomes a path (rc 4, file empty), so phase 2 runs. Abbreviations like `--collect-onl` miss the token and fail safe toward running phase 2.
- **Unregistered or egress-capable module in phase 2:** user arguments are never forwarded. Admission requires the early witness, registry-only positional arguments, no widening option, and neither env variable present. Together with the `meta_path[0]` blocker and the ignore-collect hook, I found no argument or env combination that admits one. The one gap is the `PYTHON*` note under N2 below.

## E-7e: ADOPT-WITH-AMENDMENT (one clause, non-blocking)
Add to (c) after the `credential_env` setenv clause: "`credential_env` keys must additionally not be `PATH`, `HOME`, `TMPDIR`, `XDG_*`, `LD_*`, `PYTHON*` or `BREEZY_AUTONOMY_*`; `validate_table` rejects them." This guards against a future table edit overriding the fixed environment, because `--setenv` runs after the fixed set.

Answers to your specific questions:
- **`credential_env` exposure:** it exposes only a path (`$CREDENTIALS_DIRECTORY/<name>`) in the bwrap argv and cmdline. The secret stays inside the 0400 file in the ro-bound credentials directory, which is bound only for reconcile rows. That directory is already same-uid readable on the host. The wrapper checks the directory, its mode, the exact file set, and the cgroup-leaf match. An inline key alongside the file variable fails closed in the loader. The residual that the sandbox holds a copy of the key on a shared network is stated (R8).
- **State-changing bus calls:** none remain. The verbs are `show`, `list-units` and `list-timers`. The option grammar has no mutating flag, and `-p` takes one `[A-Za-z,]+` token. Unit tokens must start with `breezy-`, so a leading `-` is impossible.
- **`-` prefixed snapshot `ExecStartPre`:** it creates no new trust problem. That code is the same wrapper file that already runs unsandboxed on every start, just before `execv`. It lives in the repo, which is ro-bound in the sandbox, so the sandbox cannot alter it or its `__pycache__`.
  - Its only sandbox-writable surface is the validated directory fd.
  - It parses nothing from the sandbox, and only lists names.
  - A hostile same-uid sandbox can at worst make the snapshot `missing` or `stale` (for example by chmod on the directory, giving 78). That maps to UNKNOWN or a page, which is fail-safe.
  - `INVOCATION_ID` comes from systemd.

## New findings from r4 deltas (all below HIGH)
- **N1, LOW:** the `credential_env` key denylist described under E-7e above (`table.py` `validate_table`).
- **N2, LOW:** `run_phase2` runs `python -m pytest` without `-I`. `PYTHONPATH` can't be scrubbed because worktrees need it, and a `PYTHONPATH` or `sitecustomize` import runs before the blocker. The risk is operator-controlled environment, the same as phase 1. Add a sentence to the E-7d Residual naming `PYTHON*` and `sitecustomize`.
- **N3, INFO:** the `touch` pre line updates the lock's mtime. This is benign. Nothing depends on that mtime in the plan.

No hard invariant is touched. Nautilus is unchanged. `allow_short` is not involved. Conftest N2 is widened by an exact set with an unchanged absent-input path, and N3, N5 and X1 are untouched. No operator control is named. The exec store is never written, because the wrapper never creates bind sources and the `.bus_snapshot` directory is confined to `cache/`.

Files reviewed:
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/ARCH-0-seamB_plan_r4.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-0-seamB-r3-security.md`
- `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh`