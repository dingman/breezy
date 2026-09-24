# AUD-02 round 7 review — silent-failure-hunter

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-02-edge-discovery-programme-status-and-fold-in.md
sha256: b9d1106884ccfe88160459cf7e3d4682fdf2e84cba0532ddca67b9a2b66dce4d
Round: 7. Reviewer: silent-failure-hunter (independent, blind).

## Round-6 MATERIAL defect (live GET no eof/pagination gate): FIXED, verified against source
- `_declared_positions` CONFIRMED `@staticmethod` (`client.py:2592-2622`) on `PolymarketUSExecutionClient`
  (class at `:1085`), refusing an absent/non-dict `positions` (`:2595-2605`) and `eof is not True`
  (`:2606-2621`, `ExecutionReportMappingError` extends `VenuePayloadError`, `errors.py:208`) —
  byte-identical to the citations. The plan now applies this SAME parser to the live payload, no
  second parser written — closes the exact truncation class it names (R-4P-1).
- `PERMITTED_METHODS = frozenset({"GET"})` CONFIRMED (`http.py:64`), enforced in `_dispatch` (raises
  `MethodNotPermittedError` otherwise) — the live read structurally cannot become an order.
- Slug-level shape-drift handling (missing/non-`Mapping` entry, absent `netPosition` ⇒ UNKNOWN) is
  correctly modelled on the existing `_write_startup_position_evidence` discipline (`:3071-3079`).
- Previous citation (`auth_smoke.py:1015-1040`, `_probe_authenticated`) is correctly demoted to
  proving only "a positions GET is a permitted read" — it does not parse `positions`/`eof`, and the
  plan no longer claims otherwise. Accurate self-correction.

## Round-6 MINOR (NO-leg netting untested): FIXED, verified
Sign-agnostic `Decimal(net) != 0` rule, applied identically on the live and fallback
(`StartupPositionSnapshot.net_position`, `:876-888`) sources, with RED test (18) asserting a NEGATIVE
`net_position` refuses exactly like a positive one. Correct: refuse-on-any-nonzero requires no sign
interpretation, and the rule is now pinned rather than prose.

## Sweep for remaining fail-open paths: none found
Checked: instance-free static-method call path (no venue connection needed for the read/parse step),
layering (strategy importing `adapters.polymarket_us.exec.client` is an already-established pattern —
`trial_day_latch.py` does the same for `DurableFillRecord`), exception taxonomy (`ExecutionReportMappingError`
stays inside the `VenuePayloadError`/`PolymarketUSError` hierarchy so a catch-all `except PolymarketUSError`
at the CLI boundary would not miss it), and the settle-or-exit WAIT's own failure mode (disclosed, not
silent: printed source/verdict/reason token on every refusal, no latch, re-runs and refuses again on a
new fill). No new MATERIAL defect identified this round.

## MINOR (withheld points, named)
- No RED test pins that the reused `_declared_positions` call is a bare staticmethod invocation with
  NO `PolymarketUSExecutionClient` instantiation (no connection/credentials needed for the read/parse
  step) — an implementer under time pressure could plausibly construct a live client instance instead.
  Required change: one test that fails if the CLI path ever instantiates the exec client class (e.g. a
  monkeypatched `__init__` that raises) to pin "no instance, no connection" as a tested invariant, not
  just prose.
- §8(i) does not require the AUD-02b evidence note to record WHICH failure mode drove a fallback
  (venue auth/timeout/non-2xx vs GET never attempted) — only that a fallback happened. Required change:
  add a criterion that the printed/recorded reason token distinguishes "live GET failed with <class>"
  from "live GET returned but the fallback was chosen for another reason," so a later reader can tell
  connectivity trouble from a design choice.

## Per-criterion (cap/points)
fidelity 20: 20 · technical correctness 20: 20 · implementation specificity 15: 14 (no-instantiation
  invariant untested) · acceptance criteria/validation 20: 19 (fallback-reason granularity not
  required in §8(i)) · autonomous/failure handling 15: 15 · portfolio alignment 10: 10.

**Total: 98/100.**

## Blockers
None. Both named MINOR gaps are buildable within AUD-02b's own scope (add one test, one acceptance
sub-criterion) and do not gate deployment.
