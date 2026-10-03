# ARCH r3: merged peer review (coordinator merge), scored sha 66002f49…361af

Scores: architect 81 (3 HIGH), trading-bot-architect 88 (0 HIGH), security-reviewer 88 (0 HIGH). Final = 81.
Duplicates merged; no contradictions. Expected to be mechanical.

## HIGH
- **Z1 [arch N1]**: Verdict acceptance compares against the newest row's artefact sha, but ATTEST, SUPERSEDE, DISPLACED, DEMOTE and RESUME rows do not carry one. After the first ATTEST, every verdict, including a DEMOTE FAIL, becomes ERROR.
  - Change: compare against the family's **bound** artefact sha from its BOOTSTRAP or MINT row. Each family id has one immutable artefact.
  - Add `test_verdict_accepted_after_attest`.
- **Z2 [arch N2, arch N8, trade N3]: the drill path.**
  - Add the row `SHADOW→CHALLENGER | DRILL_ADMIT`. It applies only under the active drill clause when the C3 no-new-lineage equality holds, with no α or `candidates_evaluated` charge, and it counts against the drill budget.
  - `DRILL_INJECT` emits PASS when the marker is absent, and the engine removes the marker.
  - The C1 `drill` flag is the fold from DRILL_PROMOTE through its closing ROLLBACK. Fills after the drill's RESUME are still drill fills. Add a test.
  - Add the step to §10 AUT-7.
- **Z3 [arch N3, trade N4]: the daily cap counts rows.**
  - Count one logical change of sender (the pair plus its ACTIVATE) as 1.
  - Exclude MINT, ATTEST and restrictive rows.
  - Drill rows count only against the drill budget.
  - Charge counters only when a pair takes effect; a lapsed or cancelled pair is not charged.
  - Pin this in `test_damping_ceilings`.

## MEDIUM
- **Z4 [trade N1, sec N2]: bound every validity.**
  - Add a `MAX_VERDICT_VALIDITY_H` ceiling (24 h plus slack), and have the engine reject verdicts above it.
  - The node enforces `attest_valid_until_ns ≤ row.ts_ns + H`.
  - The intraday pass stamps an engine-heartbeat record, and the node vetoes on `registry_engine_heartbeat_stale` at about 1 h. H = 30 h is only the backstop.
- **Z5 [sec N3, arch N4]: the ATTEST verdict set and bootstrap.**
  - The policy block defines the required verdict kinds (for example HEALTH and RECONCILIATION).
  - The `attest_expired` veto is armed only after the first ATTEST row. State this in §5.1, with a test.
- **Z6 [sec N1]**: `entry_veto` starts as `registry_unreadable` until the first verified tick. It also vetoes at call time when `last_verified_tick_age > 3×60 s`. Add a test.
- **Z7 [sec N5, arch N6]: relaunch rule.**
  - The node compares the family id only, and checks that the passed seq is a verified chain prefix.
  - It refuses boot only if the fold at `now` names this family neither CHAMPION nor HALTED.
  - A HALTED family boots with only entries vetoed, so exits stay live.
  - Add a supervisor-provided registry-aware relaunch helper to the §10 AUT-5 obligations; it replaces the hand `systemd-run` runbook.
- **Z8 [arch N7]**: A SWAP_CANCEL in [LAUNCH, 17:00Z) on day D voids the pair that took effect at D's LAUNCH and restores the incumbent. Add `test_post_launch_swap_cancel_restores_incumbent`.
- **Z9 [arch N5]**: Pin sets are append-only, and removal means revocation. Add `test_engine_pin_history_retained`.
- **Z10 [trade N2]**: Infrastructure-class causes do not consume the resume budget that escalates to TERMINAL. Their cap ends in HALTED/INTEGRITY with an alert, never RETIRE.
- **Z11 [sec N4]: demand files.**
  - One file per (venue, family, ts), read under the single-read rule with `O_NOFOLLOW`, a size cap and a strict schema.
  - An unparseable file means a venue-wide `registry_restrictive_pending`.
  - The engine retires a demand once the chain shows the family's state.
- **Z12 [trade N5]**: Watch the leaf verdict directory, or drop the path unit. Stagger the producer and engine timers. Set the SLO to 15 min.
- **Z13 [trade N6]**: Route all CRITICALs through `deliver_with_proof`. Add a NODE_LOCAL veto `alerts_undeliverable` when no 2xx canary has landed in 26 h.
- **Z14 [trade N7]**: Canary fills live in a separate canary store with its own Scorer input. Add a test that reconciliation and `entry_guard` never read it.
- **Z15 [sec N6]**: Add `SELF_HEAL_MAX_RESTARTS_PER_UNIT_PER_DAY`. Restarts use an argv list, never `shell=True`, covered by the AST test.
- **Z16 [sec N7]**: Add the drill marker and the demand files to the single-read list. Run an L-1 check on whether the actor timer runs on the `SqliteStateStore` owning thread (G7). Confirm the mirror ignores `autonomy/` keys.
- **Z17 [trade N8]**: Add an operator-CLI HWM reset for a legitimate restore. It is journaled, alerts, and goes on the chain.
- **Z18 [trade N9]**: State that the budget is venue-scoped (G21) and seeded from durable fills at boot, and that drill fills spend the same budget.
- **Z19 [trade N4]**: AUT-2 measures how often an AMBIGUOUS intent is still open at 16:45Z (promotion-starvation risk).

## LOW
- **Z20 [sec LOW]**: The PROMOTE-side `paired_transition_id` is null. A false-positive DRIFT exhausting the budget is an accepted cost; state it.
