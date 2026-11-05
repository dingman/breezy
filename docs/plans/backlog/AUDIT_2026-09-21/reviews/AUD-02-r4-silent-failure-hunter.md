# AUD-02 round 4 review — silent-failure-hunter

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-02-edge-discovery-programme-status-and-fold-in.md
sha256: 8790e1921b8c649892fb0e4fc809ed98ecd36c84b9f904f88698c761c90469cd
Round: 4. Reviewer: silent-failure-hunter (independent, blind).

## Claims verified against source (codegraph, this round)
- `FAMILY_HALT_KEY`, `_HALT_CLEARED_MARKER`, `_decode_halt_payload` (never raises), `is_family_halted`
  (fail-closed: any non-cleared value = halted) — CONFIRMED (`trial_day_latch.py:291,301,304-320,1002-1014`).
- `family_halt_submit_veto` consulted synchronously pre-permit-spend in the entry path — CONFIRMED
  (`composition.py:195-228`, wired `app/trade.py:260,316`).
- Exit path (`exit_wiring.submit_exit`) independently re-checks `is_family_halted()` before building
  the closing order — CONFIRMED (`exit_wiring.py:270-275`); no submit-path bypass found for entry or exit.
- `continuous_family_is_halted` mirrors the same fail-closed semantics — CONFIRMED (`trade_supervisor_core.py:345-356`).
- Flock contention → `SubmitIntentLockHeld`/`EXIT_REFUSED`, not swallowed — CONFIRMED (`submit_intent.py:143,534-558`).
- Alert delivery: `emit_alert` catches `BaseException`, logs, never undoes the write — CONFIRMED (`health.py:668-689`).

## MATERIAL defect (new, this round — not caught by any prior round)
`src/breezy/runtime/exec_state_db_path.py` defines `node_store_path_check` / `resolve_store_path`,
an existing value-free pre-flight built specifically to detect a CLI-vs-live-node
`POLYMARKET_US_EXEC_STATE_DB` **store-path mismatch** (MATCH/MISMATCH/NO_NODE/DISCOVERY_FAILED,
pinned by `tests/unit/test_exec_state_db_path.py`). AUD-02b's §6.5/§7 never cites this module and
never invokes it. `breezy-set-family-halt` (mirroring `clear_family_halt_cli.py`) resolves its own
store path independently and writes there; if that path diverges from the live node's env (stale
shell, wrong systemd unit, operator error), the CLI reports `EXIT_OK`/"halted" while the running
node's own store is untouched — the A1 ruling stays silently unenforced with a green CLI exit code.
Step 7-0d's verification ("from the node log... the next decision that would have submitted records
`family_halt`") is the ONLY defense, and it is **vacuous on a day with no decision opportunity** —
exactly the reviewer-brief's named failure shape. No test in the 7-item RED set (§7 step 0a) covers
a store-path mismatch or a positive-control forced-refusal check against the live process.
Required change: (1) step 0c must run `node_store_path_check`/`python -m breezy.runtime.exec_state_db_path --check`
(or equivalent) against the live node before/after the set, asserting MATCH or NO_NODE only; (2) step
0d's verification must include a positive control (a synthetic decision or forced submit attempt) so
"no decision today" cannot pass as "enforced today"; (3) add both as acceptance criteria in §8.

## MINOR
- §6.4's `halt_enforced` digest fallback (A1-open-age line reporting permanent "not open") is stated
  honestly as a known downgrade, not a silent gap — acceptable given it names AUD-02b's own alert/log
  as the independent carrier.

## Per-criterion (cap/points)
fidelity 20: 15 — enforcement mechanism is right in shape but misses the specific failure mode that
  makes "enforced" falsifiable.
technical correctness 20: 16 — every cited file:line/behavior confirmed accurate; the gap is an
  omission (source not read: `exec_state_db_path.py`), not a false claim.
implementation specificity 15: 13 — concrete mirror of an existing CLI; missing the pre-flight step.
acceptance criteria/validation 20: 14 — 7 RED tests are solid but omit store-mismatch and
  positive-control cases; §8(d) verification can pass vacuously.
autonomous operation/failure handling 15: 11 — failure-case catalog (§9) omits the store-mismatch
  failure case entirely.
portfolio alignment/scope 10: 10 — no issue.

**Total: 79/100.**

## Blockers
None operator/strategy-lead-side; this is a buildable fix within AUD-02b's own scope (add the
pre-flight + positive control before/while implementing).
