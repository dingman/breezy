# AUT-6 r11, merged review (coordinator)

Scores: SFH 95 (READY); TBA 91 with 1 HIGH. Final score 91, so the plan goes to r12.

## HIGH
**AF1 [TBA H1]: halt-decode import closure.** Coordinator ruling: option (a).
- **The move:** move the pure halt-mirror decode out of `strategy/current_rung_hold/trial_day_latch.py` into an adapter-free domain module, with delegating shims. This follows the `instrument_leg.py` and `leg_prices` precedent.
  - Functions: `read_family_halt_rows_readonly`, `decode_family_halt_state`.
  - Constants: `FILL_KEY_PREFIX`, `REFUSAL_REASONS`, and any others they need.
  - Name the module and every symbol.
- **Closure check at plan time:** compute the import closure of the evaluate and daily entry points now (grimp or equivalent, run against the current tree, read-only). Record the result in §0, and show that no `breezy.adapters.*` or `breezy.strategy.current_rung_hold` package `__init__` remains in the closure.
- **Not accepted:** do not narrow the E-7 closure rule. That was option (b), and it is rejected.

## MEDIUM
- **AF2 [TBA M1, L2]:** consume errata **E-8a**. Pass `take_flock=False` with an AUT-6 `cache_dir`. The result is advisory. Cite E-8a, and drop the O-6(ii) deviation framing.
- **AF3 [both, TBA M2 + SFH M2]: snapshot settle rate.**
  - WP verify-first measures the snapshot settle rate with the node up, against a named floor.
  - An UNKNOWN streak escalates through #25 to a CRITICAL after N passes. State N.
- **AF4 [SFH M1]: notifier markers.** The wrapped notifier writes an `attempted` marker before delivery and a `delivered` marker after. The fallback raises `wrapper_failed` only when `attempted` is absent, and it never re-delivers when `delivered` is present.

## LOW
- **AF5 [TBA L1]: `leg_prices` gate.** The NO-side tests run before merge: `test_leg_prices_2026_09_14`, `test_fq_no_leg_reconciliation_parity` and `test_polymarket_us_exec_reports`. Add a one-line heads-up in the WP brief. The same gate applies to the AF1 move.
- **SFH lows:**
  - Only invocations judged and ended can end an episode.
  - The stage records its own delivery in the episode file.
  - Prune the `notify/` markers along with `stage_status/`.
  - Add a config test that no unit file carries `Environment=` secrets.
