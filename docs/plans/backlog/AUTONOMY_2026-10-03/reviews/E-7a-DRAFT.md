# Errata E-7a (draft, under peer review): bwrap every autonomy unit; the AST test becomes a lint

## Problem
Five consecutive AUT-6 and AUT-5 review rounds have turned up new gaps in the AST closure test. These include unlisted stdlib writers, unresolved receivers, non-call references, lazy imports and vacuous empty closures. A static analyser that is both complete and buildable for Python is not achievable at plan level. Under E-7 rule 3, though, the one-writer property of every autonomy unit that is NOT wrapped rests on that test alone.

## Amendment

### 1. bwrap covers every autonomy-owned unit
Every autonomy-owned systemd unit runs under the E-7 rule-2 bwrap. That covers the AUT-1..AUT-7 producers, the label, refit, tally, reconcile, health, canary, watch, drill and engine units, and their notifiers. Each unit gets:
- `--ro-bind / /`;
- `--bind` for exactly the output directories in its one-writer rows (constant paths);
- the credentials tmpfs;
- `--unshare-pid` where the unit does not need `/proc/locks`, and where it does, the documented exception;
- the self-probe, both negative and positive.

Write-scope is then **OS-enforced for every autonomy unit**. Shared enforcement:
- a single shared wrapper script, `deploy/systemd/breezy-autonomy-bwrap`, with per-unit bind lists declared in one table;
- a test asserting that every `breezy-autonomy-*` unit's `ExecStart` goes through the wrapper.

### 2. The AST closure test becomes a lint
The AST closure test is demoted to **defence-in-depth lint**. It keeps a best-effort denylist plus resolved-name checks. Its completeness is never cited as enforcement and is not a READY criterion. It must still meet three conditions:
- be non-vacuous, asserting a minimum number of judged call sites per entry point;
- carry positive controls;
- be green at build.

### 3. Units outside the scope
Units outside autonomy ownership stay unwrapped, as a stated residual. These are the trading node, the supervisor, the recorder, the ingest, and the operator CLIs.

### 4. E-9 applies
The wrapper is one command per stage, bounded by `timeout -k`.

### 5. Filesystem note
The state and registry live on ext4 (verified). O_TMPFILE works there, so the `O_TMPFILE` fallback paths are removed and `EOPNOTSUPP`/`EINVAL`/`EISDIR` → INTEGRITY.
