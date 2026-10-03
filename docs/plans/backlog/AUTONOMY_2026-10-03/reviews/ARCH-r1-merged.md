# ARCH r1: merged peer review (coordinator merge)

Reviewers ran blind. Scores: architect 69, trading-bot-architect 68, security-reviewer 71. Verdict
from all three: SOUND-WITH-CHANGES. Final = the lowest = 68. Duplicates are merged; where one
defect has two sources, the tag shows both. No reviewer contradicted another. Architect D8
(Nautilus REDUCING) is a proposal and needs an L-1 proof.

## CRITICAL
- **X1 [arch D1]**: The CRH composition kinds send on a permit and never call `live_orders_authorized`
  (`app/trade.py:740,795`; `composition.py:257-291`). A registry CHAMPION row of a CRH kind would therefore send.
  - Required: the resolver refuses any CHAMPION whose kind is not routed through the gate, or the gate is wired into every kind.
  - Add `test_registry_champion_requires_live_orders_gate_for_every_kind`.
- **X2 [sec 1]**:
  - Add an AST test that the policy allowlist is a literal-only tuple.
  - The node verifies at LAUNCH that the sha of the deploy-copy ruling equals the allowlisted sha.
  - `engine_code_sha` becomes an allowlisted, committed pin that the node checks.
- **X3 [sec 2, 8]**: The registry is a mutable SQLite file that a same-user writer can rewrite consistently. Required:
  - a hash chain over transitions (`prev_transition_hash`), verified end to end at LAUNCH
  - SQLite triggers that refuse UPDATE and DELETE
  - a daily export outside the DB, with `decided_by` and the unit invocation id
  - `operator_cli` writes on the same chain
  - the node checks the child's `live_orders_ruling` and the root allowlist and never trusts the row
  - file modes 0600 and 0700; the engine in its own systemd unit with `ReadWritePaths`; the node read-only

## HIGH
- **X4 [trade 1]**: Promotion must not rest on external-weather skill alone (the 09-20 ruling closed the forecast edge). The pre-registered predicate requires:
  - (a) a market-implied baseline on the traded rung
  - (b) EV net of fees and observed slippage
  - (c) the traded-rung calibration leg passing

  An offline-only PASS is never enough for CHALLENGER→CHAMPION.
- **X5 [trade 2]**: Every candidate is scored against a sealed holdout, which leaks it through adaptive selection.
  - Pre-register a cumulative multiple-testing α spend, or use a rolling forward holdout of post-training days.
  - Count `holdout_touched` across candidates.
- **X6 [trade 3]**: PROMOTE, RESUME, ROLLBACK and SUPERSEDE require no OPEN or AMBIGUOUS intent, clean reconciliation, and no unreconciled leg-signed position.
  - A demoted FQ family holds to settlement.
  - Address exit capability: only `pm_us_crh_exit_v4` has it, under the G17 exit allowlist.
- **X7 [trade 4, arch 10, arch 3]**: Activation and pickup.
  - PROMOTE, SUPERSEDE and ROLLBACK write `pending_activation`; the old champion keeps running until the next LAUNCH, so there is no dead zone.
  - The supervisor polls the projection and relaunches inside a declared safe window.
  - The supervisor resolves once and passes `(family_id, registry_seq)` to the node through the environment. The node re-reads and refuses boot on a mismatch.
  - Add a test that a swap cannot exceed the single-day budget across latch and budget namespaces.
- **X8 [arch 2]**: Enforce at most one live family per venue. Specifically:
  - add HALTED→CHALLENGER (DISPLACED), atomic with another family's →CHAMPION
  - allow RESUME only when `projection.champion_family_id` equals that family
  - seed `pm_us_crh_v4` as RETIRED or SHADOW, not HALTED
  - add the invariant to the CAS test
- **X9 [arch 4]**: Write a table mapping every `record_policy_halt` reason (fee drift, A1, legacy) to a cause class. Either move the fee probe to an entry-only registry DEMOTE or declare fee drift TERMINAL. Make AUT-6 self-heal and AUT-5 RESUME reachable.
- **X10 [sec 3]**: Path widening.
  - Keep `resolve()` and the `..` and absolute refusals.
  - Add a symlink RED test.
  - Registry artefacts are mode 0444 and never symlinks.
  - Verify and load share one file descriptor: read once, hash, parse the same bytes. Today both `load_family_manifest` and the artefact loader re-read.
  - Add `settings.py:183` `_FAMILIES_DIR` and `_validate_sending_family_manifest` (`:366-388`) to the widening list.
- **X11 [sec 4]**: The child manifest equals the root on every key except an explicit allowlist (artefact sha, `trial_id_prefix`, `d0_climate_day`). That covers every size and price knob, `exit_rule`, `no_leg_exit` and the recalibration and correction forms. `exit_gate.py` (G17) stays code-only, with a test.
- **X12 [sec 5]**: Damping.
  - A RESUME cooldown.
  - At most N RECOVERABLE resumes per lineage per window, after which the cause becomes TERMINAL.
  - A global ROLLBACK budget, after which the family goes to HALT.
  - Never roll back to a family demoted for cause; clear `rollback_eligible` on DEMOTE or HALT.
  - A daily transition cap that the engine cannot change.
- **X13 [sec 6, arch 12/trade 12]**: Any registry failure means an entry veto and no permit-bearing composition. There is no fallback to the lineage root.
  - Test that the fallback path mints no permit.
  - `BREEZY_FAMILY_SOURCE` is fixed in the committed unit, and a scan shows engine code cannot set it.
  - The `registry_unreadable` veto clears on the next good read, with a test.
- **X14 [trade 6]**: Add an external dead-man check: a timer independent of the engine reads the engine heartbeat. Add a daily delivery-proof canary alert.
- **X15 [trade 11, arch 6]**: Live proof must exercise PROMOTE, RESUME and ROLLBACK through the production path, for example a byte-identical child of `fq_v1` promoted and then rolled back under the policy ruling (permit withheld or live). Track this as AUT-7b with its own clock. Define the state after the KILL on 2027-01-25.

## MEDIUM
- **X16 [trade 7]**: Reconcile at net position per instrument; the venue nets NO as short YES. Add a RED test where a NO fill offsets a YES holding. Root-cause the FQ −0.37 / +0.37 conflict as a first step. Score only `window_complete` rows.
- **X17 [trade 8]**: Write a slot table with a serialised flock queue, a `MemoryMax` per job, and the reproducibility rerun on a sampled subset only. Resolve the clash between the 01:00–04:30Z blackout and the 02:05Z nightly.
- **X18 [trade 9, arch 11]**: `decision_id` must be recomputable. Either derive it from event-time keys, or capture `eval_ns` and make the recorded value authoritative.
- **X19 [trade 10]**: The live-proof windows need at least N real fills, or clearly tagged synthetic canary fills. Zero-fill days do not count. State the evidence class honestly: "machinery proven, edge unproven".
- **X20 [arch 7]**: The policy ruling maps `detector id → action_class`. The engine refuses any verdict whose declared class differs from that map.
- **X21 [arch 8]**: Run an L-1 proof of the native Nautilus `TradingState.REDUCING` (already reached via `account_presence_halt.py:171`) against the NO-leg SELL/BUY_SHORT representation, before building a custom entry veto.
- **X22 [arch 9]**: To prove own-outcome use, refitting with the label set left out must change the artefact sha. Name the model class that consumes C2.
- **X23 [arch 5]**: Remove `expected_prior_seq` from `transition_id`. Replaying a pair that is already applied is a logged no-op. Drop the "CAS conflict → node boots shadow" row.
- **X24 [sec 7]**: The engine accepts a verdict only when all of the following hold:
  - its `producer_code_sha` is in a committed set
  - its input shas resolve under the expected roots
  - its `prereg_ruling_sha256` equals the policy ruling's

  Verdict directories are mode 0700, and producers run as a separate service.
- **X25 [sec 9]**: Alerts and C1 records carry no paths, env values, venue ids or credentials. Reuse the `health_model.py` alert-payload rule and add a scan test.
- **X26 [sec 10]**: When the engine mirrors exec-store halts and its read fails, treat that as an INTEGRITY halt.

## LOW
- **X27 [sec 11]**: Add a test that autonomy code never imports the order-submission path or the exec client. Allowlist the new alert egress in the firewall test without widening it.
- **X28 [arch 11]**: YAGNI: kinds with no non-RETIRED family may use a `RefusingPlugin` instead of the full C6 plug-ins.
- **X29**: The architecture runs past its line cap (643 lines). Keep it under about 750 after the revision.
