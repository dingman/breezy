# AUT-1 r8 final review

**Verdict: READY.** Both reviewers scored it 95 (TBA and SFH), with zero CRITICAL and zero HIGH findings.

The items below are binding on the WP1 and WP briefs.

## MEDIUM (both reviewers)

The §3.15 AST closure boundary needs to be pinned down:

- The walk covers only the AUT-1 path globs, i.e. the modules listed in `AUT1_WRITE_AUTHORITY` plus the AUT-1 non-writers. Each other owner's modules are checked under that owner's own table.
- A non-writer may import a cross-unit write module only through named read-only functions.
- A non-literal `open` mode or non-literal `os.open` flags fail closed.
- Reason values must be constants, and the test fails on any non-constant reason.
- State whether a `capture_gap` refusal record cites payloads.

## LOW

- **Heal age-out.** For an unmarked heal older than `today−30`, emit a loud log line and the roll-up field `heal_alert_unabandoned_count`.
- **`on_stop` fact drain.** The drain must be exception-safe and must run before the writer closes. Add a test for this.
- **Stale wording.** Re-grep for "r7" and update the wording. Align `recorder_liveness` with `recorder_stale`.
- **`test_payload_collision_is_critical`.** This test asserts the CRITICAL on the caller side.
- **Watch-actor closure.** The watch-actor closure belongs to AUT-5. `node_observations.py` is AUT-1's node-side non-writer.
- **E-9 (adopted 2026-10-03):** any multi-command oneshot bounds each command and sums the bounds (ARCH-ERRATA E-9). Binding build item.
- **AST allowlist (coordinator ruling, 2026-10-03, from AUT-6 r9 review):** the non-writer closure check is an allowlist of named read-only calls, not a denylist. See reviews/AUT-6-r9-merged.md AC6.
- **E-7a (adopted 2026-10-03):** universal bwrap through the shared wrapper and table; WAL reads via the snapshot helper; AST check is a lint. See ARCH-ERRATA E-7a. Binding build item.
- **E-7c (2026-10-03):** the shared bwrap wrapper provides a private `--tmpfs /tmp` with TMPDIR; see ARCH-ERRATA E-7c. Binding build item.
