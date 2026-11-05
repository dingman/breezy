# OPS-4 S3c — Round 1 review merge (python-reviewer HIGH 8/9/8/8/9/8; architect REQUEST_CHANGES; security APPROVE w/ 3 conditions)

## Blocking (all text-level; no redesign)
1. STALE PIN PREMISE. Plan says `e2d4412f → new`. Live pin is `c2c84ab6…9f69` (pins.py L47; MONTH-cap commit 11ff973d re-pinned after S3b). Fix text; require the "was" value read from disk at commit time; add `# re-pin: OPS-4 S3c (...); was c2c84ab6...9f69` comment matching pins.py L25-46 convention. Pin commit (pins.py + BWRAP_HOST_EXPECTED_TESTS 41→42) is a security-reviewer item citing a dated ruling (L-12).
2. MERGE ATOMICITY [HIGH]. Code commit alone is deliberately red (pin mismatch, host count 42≠41) and the integration tree is the live tree. A timer fire (05:00Z / 14:15Z) between code merge and pin merge → unit exits 2 `producer_unpinned`, OnFailure fires. Require: code+pin merged as one pair; merge outside ±20 min of each timer slot; neither pushed/merged alone; gate run on the merged head (per-commit gates red on pin test in between).
3. BEHAVIOUR CHANGE OUTSIDE SANDBOX [MED]. Plan says "outside sandbox unaffected" — false for a missing lock: old code created it (`label_run.py:496`), new code raises `Missing`. Enumerate every `StudiesFlock(` construction/caller and test using a real StudiesFlock on a nonexistent path; state the change in the docstring. `ExecStartPre=-touch` ignores failure so a failed touch now surfaces as loud REFUSED (acceptable).
4. SHARED CLOSURE [MED]. `label_run` now imports `studies_lock.py`, joining the `aut2.label` closure; future edits to it (shared with `capture_audit_cli`) unpin the label unit. State in pins.py comment. Confirm `aut6.health` stays pinned (`test_code_identity_pins_cover_import_closure` green with only aut2.label changed).

## Missing tests (add)
- `main()`-level test: StudiesLockRefused → exit 1, one pathless line, no traceback through the real entrypoint (AC4 promises "never a traceback"; run_unit alone doesn't prove it).
- `release()` after refused `acquire` is a no-op (`_fd` stays None); no fd leak on refusal path.
- `chmod 0o400` EACCES stand-in: add `skipif(os.geteuid()==0)`; the `os.open` flag-spy test is the primary RED; bwrap EROFS test is the binding RED.
- AC3 at `run_unit` level: real helper + outside holder + `wait_s=0` → False → skip journal.
- Run `test_aut2_units_no_expected_failure.py` (caller of run_unit).

## Non-blocking
- Remove unused `fcntl` import (ruff F401); add `from breezy.runtime.autonomy_sandbox.studies_lock import StudiesLockError, StudiesLockTimeout, acquire_studies_lock`.
- Name the barrier-derivation expected-red set explicitly: `test_te1_label_wiring.py`, `test_aut2_label_run.py`.
- AC8(c): compare `written_at_ns` against the merge commit epoch, not wall-clock text.
- Mention wrapper exit-78 as the expected signature if the lock is absent on a normal start.
- Cosmetic line cites: bwrap.py rebind loop + `--remount-ro /run` ≈ L249-252, `--tmpfs /run` L225; capture_audit_cli use is L119.
- Refusal handler wraps the call at `label_run.py:569`, before the try/finally (nothing held on refusal).

## Verified claims
`acquire_studies_lock(path, *, wait_s, poll_s, monotonic, sleep) -> int`; Missing/Refused/Timeout subclass StudiesLockError with pathless `.code`; tries once at wait_s=0; no fd outlives failure. `_RC_FAILED = 1` at L132. Tripwire at test_te1_label_wiring.py L750-753 survives (signature unchanged). No other pin depends on aut2.label. No import-layer problem. Guard loosening: none. Read-only fd + flock LOCK_EX sound (fstat on opened fd is race-free). Prohibited-command scan: clean.
