# ARCH r2: merged peer review (coordinator merge), scored sha 8a9c89b7…7b37a

Scores: architect 78 (the architect could not hash the file, but scored the on-disk file, which is the
hashed revision), trading-bot-architect 76, security-reviewer 88. All three: SOUND-WITH-CHANGES.
Final = the lowest = 76. Duplicates are merged. No contradictions.

Layering guidance for the reviser: ARCH defines **contracts and invariants**. Area-specific procedure
(drill steps, slot table rows, detector catalogues) may move to an "Area plan obligations" list per
AUT-n, where the area plan must specify it. That keeps ARCH under about 900 lines.

## HIGH
- **Y1 [trade N4, arch N9, sec N6]: demotion latency.**
  - Transient conditions (feed or recorder stall, permit lapse, capture gap) become **node-local, auto-clearing watch-actor entry vetoes**, with no HALTED transition and no damping charge.
  - DEMOTE is reserved for verdict-driven causes, and an **intraday demote-only engine pass** handles it, every 5 min or by a path unit over `verdicts/`.
  - An intraday producer turns `DetectorEvent` records into C4 verdicts.
  - Add a latency SLO test.
- **Y2 [arch N2, trade N5, sec N7]: the drill.**
  - Add an explicit C5 row, `CHALLENGER→CHAMPION | DRILL_PROMOTE`. It is allowed only when the artefact and manifest equal the champion's, under a pinned drill-clause sha.
  - Add a dedicated `DRILL_INJECT` detector id, read by a pinned detector from a drill marker. The policy maps it only while the drill clause is active.
  - The drill has its own damping budget, separate from production.
  - Drill fills are tagged and excluded from the lineage's live-sequential n and from the KILL clock.
  - Define how MINT and C3 treat a child with no new lineage.
  - Add a test refusing `DRILL_PROMOTE` for any sha other than the champion's.
- **Y3 [sec N2, trade N4]: a dead engine must not let a stale champion trade.** `RegistryWatchActor` vetoes entries when either:
  - the champion's newest accepted verdict is past `valid_until_ns`, or
  - the chain-head age is past the horizon.

  This check is node-side and independent of the engine. Define the dead-man horizon as at least one engine period plus slack.
- **Y4 [sec N4, arch N6]: never trust `projection`.**
  - The actor re-folds the chain, or checks the chain head against the transitions tail.
  - The node keeps a monotonic `registry_seq` and `chain_head` high-water mark in node-local durable state, and refuses a lower value (DB revert).
  - `registry_unreadable` clears only after a verified read.
  - Verdict and export reads use `O_NOFOLLOW` and a single read.
- **Y5 [arch N5]: SQLite and WAL.** A read-only node cannot recreate `-wal` and `-shm` after the oneshot engine exits. Use a rollback journal or persistent WAL. Add a RED test that opens read-only on a read-only directory with the engine stopped.
- **Y6 [sec N1]: the chain must bind bytes.**
  - The hashed transition row carries `manifest_sha256`, `artefact_sha256` and `lineage_root_family_id` for MINT, PROMOTE and ROLLBACK.
  - The resolver compares the single-read bytes against them.
  - The cited verdicts' `subject_artefact_sha256` must equal the artefact sha.
  - The root comes from the child-id regex.
  - Manifest equality is checked against the committed `deploy/families/<root>.json`, never a registry copy.
- **Y7 [sec N3]: hand-relaunch bypass.** Once the registry has any transition, the node refuses boot to a sending family unless `BREEZY_FAMILY_SOURCE=registry` and the resolved id equals `BREEZY_SENDING_FAMILY_ID`. Add a test.
- **Y8 [arch N1]: pending-swap semantics.**
  - State and the X8 invariant come only from the effective-time fold `resolve_champion(venue, now)`.
  - A DEMOTE on either family while a swap is pending cancels the swap. The outgoing family goes HALTED and is never superseded.
  - RESUME is refused while `next_*` is set.
  - Add `test_demote_during_pending_swap_{incoming,outgoing}`.
- **Y9 [arch N3]: `transition_id` collisions.** Include `family_prior_seq` and the paired transition id. Add `test_repeat_supersede_same_family_is_not_replay`.
- **Y10 [arch N8]: a TERMINAL policy halt (A1, fee drift) freezes the whole lineage** for PROMOTE and ROLLBACK. Add `test_terminal_halt_freezes_lineage`.
- **Y11 [trade N8]: alert delivery proof.** `emit_alert` returns None and swallows errors (`health.py:479`).
  - Define a delivery-proof API: an HTTP 2xx, journaled.
  - Add a sink-side or external heartbeat, so a missing canary pages someone off-host.
  - Name which area builds it (AUT-6).
- **Y12 [trade N1]: forward-shadow reachability.**
  - The policy ruling must carry a feasibility calculation (n_min, takes per day, ETA before 2027-01-25) as a precondition to enabling PROMOTE.
  - If the ETA is later than the KILL date, §7 states that PROMOTE is machinery-proven by the drill only.
  - Forward-shadow inputs come only from tape days that pass replay-sufficiency.
  - Champion slippage must not stand in for a different policy without that being stated.
- **Y13 [trade N2]: multiple testing under daily refit.** Pre-register a cap on candidates per lineage per forward window and a mint-rate limit. State the MDE at α_K.

## MEDIUM
- **Y14 [trade N3]**: Forward-shadow n is counted in independent station-days, not takes.
- **Y15 [trade N6, arch N7]**: "Reconciled" means venue net equals the ledger, not flat.
  - Rename the test `test_promotion_requires_reconciled_state`.
  - The supervisor re-runs the §4.4 preconditions at LAUNCH.
  - Define how this works with the existing AMBIGUOUS boot refusal without causing a launch deadlock.
- **Y16 [trade N7]**: Name where the per-rung double-take predicate (over exec-store fills) lives, and put it in the `entry_veto` contract.
- **Y17 [arch N4]**: Each pin is the sha over the transitive `breezy.*` import closure, computed by the gate test from the import graph.
- **Y18 [arch X12 caveat]**: M (the promotion rate limit) gets a code ceiling in `pins.py`.
- **Y19 [arch N10]**: DEMOTE and HALT retry until committed. If they still fail, they set the in-node veto.
- **Y20 [arch N11]**: State whether there is one chain per venue (a per-venue prev link) or a single global chain.
- **Y21 [sec N5]**: Self-heal restarts use a literal allowlist of restartable unit names in `pins.py`. The list excludes the supervisor and trade units and any unit-file or env edits. Add a test.
- **Y22 [sec N8]**: The policy ruling has a literal machine-readable block, hashed with the file. A test rejects any value looser than the code ceilings.
- **Y23 [trade N4b]**: The engine and the dead-man use their own lock, not the studies flock. Every study has a `RuntimeMaxSec` ending before 16:30Z. Respect the 31 GB host.
