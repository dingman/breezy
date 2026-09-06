# Strategy-lead ruling: `observation_ambiguous` must not consume the station-day (GL-3)

**Ruled by:** Codex (strategy lead for `pm_us_crh_v2`), 2026-09-06 ~19:55Z,
session `01a0784d-cf71-7fe0-8ddf-64455e6be44b`. Brief:
`docs/prompts/codex_gl3_ambiguous_consume_ruling_2026-09-06.md`. Requested by
the coordinator after the operator delegated the determination to the build
side (see `GO_LIVE_BLOCKERS_2026-09-06.md`, operator answers).

## Ruling

1. **Registered text covers it, by incorporation.** Registered v2 §2 freezes
   the take rule and v2 §8 ties the unit of observation to v1 §2:41-44, which
   says: "A failed taken test consumes the station-day; an ambiguous or
   non-executable snapshot does not." v2 §13 binds `pm_us_crh_v2`,
   D0 = 2026-09-05.
2. **Conformance fix, not an amendment.** Changing live `observation_ambiguous`
   from consume to skip restores the frozen admission rule; it is not a §12
   screen and does not create a new family.
3. **No contamination, no restart.** n = 0 stays n = 0; ambiguous latch rows
   are not filled Takes; the §9 covered-listed denominator is recorder/listed
   based, not latch based; structural-dead accounting and D0 are unchanged.
4. **Must NOT consume:** `observation_ambiguous` (v1 §2:41-44, §3:54);
   non-executable snapshots / `not_executable` (v1 §2:41-44);
   `in_window_no_running_max_yet` (pre-candidate, no latch).
   **Not covered by this ruling:** stale `observation_unavailable` — tests pin
   it as latched; do not broaden without a separate ruling.
   **Do consume:** the first unambiguous executable candidate that fails the
   taken/admission filters (`fee_schedule_mismatch`, `illegal_cell`,
   `p_hold_undefined`, `edge_below_break_even`); `taken` consumes before submit.
5. **Tests pinned wrong** (correcting them is not weakening a contract):
   `tests/unit/test_current_rung_hold_strategy.py::TestObservationRefusals::test_an_ambiguous_observation_refuses_observation_ambiguous`
   and `::TestSpanningIntervalRouting::test_an_interval_only_touching_this_instruments_upper_bound_is_counted_ambiguous`
   assert a latch record with reason `observation_ambiguous`. The pure
   decision test returning `Refuse("observation_ambiguous")` stays.
6. **`n_ambiguous_skip`** (rev2:121) is not registered; an operational counter
   may be added if non-gating and excluded from n, S, I, the §9 denominator
   and verdict logic.

## Binding statement (ruling of record)

For `pm_us_crh_v2`, `observation_ambiguous` is a skip-without-consume
condition. Registered v2 freezes and inherits v1's take/admission rule, under
which only the first unambiguous executable candidate that fails the
taken/admission filters consumes the station-day; ambiguous and non-executable
snapshots do not. Changing live strategy behaviour so `observation_ambiguous`
records visibility but leaves the trial-day latch open is a conformance fix,
not an amendment or new family. Existing n = 0, D0 = 2026-09-05, the §9
recorder/listed coverage denominator, and structural-dead zero-fill accounting
are unchanged.

**Not verified by the ruler:** the live sqlite/node-log events for MIA/MDW on
09-05/09-06 (those were verified by the coordinator in
`GO_LIVE_BLOCKERS_2026-09-06.md`).
