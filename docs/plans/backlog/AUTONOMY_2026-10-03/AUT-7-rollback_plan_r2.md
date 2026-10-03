# AUT-7 — Rollback (incl. AUT-7a gate drill, AUT-7b live promotion/rollback drill) — plan r2

## 0. Header

| Field | Value |
|---|---|
| ID | AUT-7 (sub-items AUT-7a gate drill, AUT-7b live drill) |
| Title | Rollback: immutable champion history, automated rollback, fail-closed failure, scheduled drills |
| Round | r2 (2026-10-03). Revises r1 (`AUT-7-rollback_plan_r1.md`, kept unchanged) against `reviews/AUT-7-r1-merged.md` (K1–K18, the coordinator's INTEGRITY ruling, ARCH deltas). §R2 lists the disposition of each item. |
| ARCH consumed | `AUTONOMY_ARCHITECTURE.md` **Rev 5**, sha256 `5d2b75fa77e2c0abaaa478bd38d32e7e06ac98c8057ce50a5045f0dd0eff8403` (byte-identical to `reviews/snapshots/ARCH_rev5.md`). Code evidence checked at `4b8347a6`. Rev 6 is in progress; the assumptions for C-1, C-3, C-4, C-5 and C-6 are stated in §11. |
| Current score | 2 (README: sha-pinned manifests make a rollback a manifest swap; there is no previous-champion pointer, no trigger and no drill) |
| Target | 3 |
| Upstream | ARCH-0 (C5 store, chain, fold, resolver, `pins.py`), AUT-5 (engine modes, policy ruling and drill clause, watch actor, lineage allowlist, supervisor boot lines), AUT-6 (`deliver_with_proof`, intraday producer, fee/permit/drawdown verdicts), AUT-1 (C1 `drill` flag writer), AUT-2 (C2 `excluded_reason=drill`, post-STOP `RECONCILIATION` with open positions by family) |
| Downstream | AUT-5 live proof (AUT-7b is its PROMOTE/DEMOTE/RESUME evidence, README AUT-5), AUT-6 (the DEMOTE action class proven through the live path), AUT-4 (live n and the KILL clock exclude drill fills) |

This is a plan only; nothing in it is implemented. All times are UTC.

## 1. Goal state

**README score-3 criterion (verbatim):**
- The registry keeps an immutable champion history.
- An automated rollback to the last good champion fires on the AUT-5 or AUT-6 triggers and takes effect within one supervisor cycle, with no code change.
- A failed rollback fails closed by halting the family.
- Drills run on a schedule in the gate and live.

**Live proof (verbatim):** "tracked as AUT-7b, with its own clock of at least 4 trading days: one live rollback drill through the production path, restoring the prior champion and its byte-identical artefact sha, logged, alerted and reversed, with no human commit (ARCH §5.3). After the 2027-01-25 KILL, the state defined in ARCH §5.3 applies."

**ARCH Rev 5 §10 AUT-7 obligations (verbatim):** "rollback-target selection (most recent `rollback_eligible`, not `terminal_frozen`, bytes re-verified); failed rollback → HALT; the gate drill (AUT-7a); the live drill steps for AUT-7b — with `fq_v1` CHAMPION and not `demoted_for_cause` (W2), mint the byte-identical child `pm_us_crh_fq_v1_r0001` (C3 no-new-lineage), DRILL_ADMIT it, DRILL_PROMOTE at LAUNCH (`fq_v1` superseded and rollback-eligible, W3), write the drill marker so `DRILL_INJECT` demotes it through the live path, remove the marker so the verdict PASSes, RESUME (DRILL class), ROLLBACK to `fq_v1` — with dates, the drill budget, and the evidence (chain, export, node log, delivery journal)."

**How "failed rollback → HALT" is read under the coordinator ruling (K9).** In production the outgoing family F is already HALTED by its own cause when the trigger fires. A failed or cancelled rollback therefore **leaves F HALTED**: entries stay vetoed and exits stay live. The engine retries every day, sends a CRITICAL through `deliver_with_proof` and journals a counter. A rollback failure **never** causes a venue INTEGRITY freeze. A corrupt target (R2) blocks only rollback into that target's lineage. A new engine HALT row is written only when the outgoing or newly effective family is CHAMPION, which happens in the drill and in the post-effect failures R6 and R7 (§3.5).

ARCH Rev 5 content consumed unchanged:
- C3 no-new-lineage (Y2).
- The C5 rows ROLLBACK, DRILL_ADMIT, DRILL_PROMOTE, SWAP_CANCEL, SUPERSEDE (W3: the drill-episode family is only the minted child), DISPLACED, RESUME (cause classes incl. `DRILL`, W2) and RETIRE.
- The node HWM and the W5 auto-clear of `registry_halted`.
- §4.5 `MAX_ROLLBACKS_PER_VENUE_30D ≤ 2`, `DRILL_BUDGET_PER_VENUE_30D ≤ 1`, `RESUME_COOLDOWN_H ≥ 24`.
- C6 `DRILL_INJECT → DEMOTE`, class `DRILL`.
- The C2 W12 invariant (drill fills feed risk).
- The §5.3 drill contract.

## 2. L-1 null hypothesis and reuse

| New component | Capability checked first (file:line) | Verdict |
|---|---|---|
| Champion history | Nautilus has no artefact registry or champion state (ARCH §2 L-1). C5 `transitions` (ARCH-0) is already append-only, hash-chained and trigger-protected. | **No new store or table.** History is a pure fold over the verified venue chain, never the `families`/`projection` caches (Y4). |
| Target byte verification | `load_family_manifest` hashes raw bytes once (`family_manifest.py:285-296`). `load_live_calibration` re-hashes the artefact (`calibration_artefact.py:250-256`), but through `Path(path).read_bytes()`, which follows symlinks, and it lives in the strategy layer. The resolver's byte binding (C5 Pickup Y6) is the LAUNCH verifier. | **Reuse `resolver.verify_family_bytes`**, so the engine verifies a target with the exact code the supervisor runs at LAUNCH. No second verifier. |
| Fee-verified state | `FeeDriftProbeActor.is_fee_verified` (`fee_drift_probe.py:543-578`) is **in-node memory**: `_last_agree_at_ns` is "Not a store key" (`:292-299`), with staleness `_FEE_VERIFIED_STALENESS_NS` = 4 h (`:184`). The probe logs `event=fee_drift_probe outcome=AGREE` at INFO (`:436-441`). | The engine cannot call it. **Reuse AUT-6's fee-and-shape-drift `VERDICT`** (a required C6 detector class), whose input is the newest node-log AGREE line. AUT-7 adds no reader of its own (§3.3.2). |
| Open/AMBIGUOUS intent | `probe_open_intent` (`trade_supervisor.py:402-420`) treats a corrupt singleton as OPEN and refuses while a node PID is live (`trade_supervisor_core.py:554-560`). `SubmitIntentState` is `{OPEN, RETIRED}` (`submit_intent.py:68-70`), so an AMBIGUOUS intent is an unretired OPEN one. | Reuse, **binding only in the 16:45 pre-launch pass**. Every sender change and every RESUME is written there (K6, K10, K14). |
| Position handoff | The exit capability is the family-id literal `_EXIT_RULE_REGISTERED_FAMILIES = {"pm_us_crh_exit_v4"}` (`exit_gate.py:55`), so a child id is never exit-capable. FQ has no exit (G17). Reconciliation is venue-net per base slug, family-agnostic (C2). | **Reuse `family_declares_exit_rule`** (`exit_gate.py:58`) for the ownership predicate (§3.3.3). No new store. |
| Rollback write | The C5 ROLLBACK row and its SUPERSEDE/DISPLACED partner, written through the AUT-5 store API (CAS, idempotent `transition_id`, Y9). | Reuse. AUT-7 adds a planner, not a writer. |
| "Halt the family" | The exec-store `record_policy_halt` (`trial_day_latch.py:1155-1191`) needs the node flock (G6), blocks exits (G5) and is cleared only by the CLI. | **Rejected.** Use the registry HALT row, which is entry-only and leaves exits live. |
| Launch-time pickup | `STOP_PRIOR_UTC 16:40`, `LAUNCH_UTC 16:50`, `RELAUNCH_CUTOFF_UTC 17:00` (`trade_supervisor_core.py:37-40`); the AUT-5a resolver at LAUNCH. | Reuse. A rollback is only registry rows. |
| Post-effect verification | Today's boot line is `fq_live_orders enabled=… family_id=… ruling=… reason=… ruling_sha256=… calibration_sha256=<manifest.density_artefact_sha256>` (`app/trade.py:753-762`). It is emitted after `live_orders_authorized` and before the artefact load (`:778-797`). | Reuse as the **interim** consumed line. The binding interface is the AUT-5a resolved-family boot line plus a composed line (§3.5, K4). |
| Drill child manifest | `deploy/families/pm_us_crh_fq_v1.json` (805 B; `d0_climate_day "2026-10-02"`, `live_orders_ruling "RULING_operator_fq_live_real_orders_2026-10-01"`); artefact sha `9c0b6d6e…923a5e` (re-hashed 2026-10-03). Both id regexes accept `pm_us_crh_fq_v1_r0001` (C5 Pickup 3). | Reuse the committed root bytes. The child changes exactly 3 keys (K5). |
| DRILL_INJECT detector | Defined in C6 as a dedicated `VERDICT` detector. Nautilus has no fault-injection facility. | New and tiny. Marker binding added (K7). |
| Node pickup of DEMOTE | `RegistryWatchActor` (AUT-5; the `fee_drift_probe.py:358-375` bridge); W5 auto-clear. | Reuse. AUT-7 adds no node code. |
| Delivery proof | `deliver_with_proof` (AUT-6, §4.6). `emit_alert` swallows failures (G25). | Reuse for every AUT-7 CRITICAL and drill event. |
| Drill evidence bundle | The AUT-5 daily engine pass already runs at 15:30. | **Emitted from that pass on D+4** (K18). No new unit. |

**Finding F-1 (kept from r1, still open).** `_assert_artefact_path_contained` uses `allowed_root = manifest_dir / "deploy/families"` (`family_manifest.py:169,276-279`). That is a phantom directory for a manifest already under `deploy/families/`, while the real read is CWD-relative (`app/trade.py:788`). This is handed to AUT-5's four-site containment widening (C5 Pickup 3). AUT-7 makes no edit to `family_manifest.py`.

**Finding F-2 (new, feeds R7).** C5 Pickup says `_compose_family` consumes the resolver's bytes and "never re-reads". Today the FQ composition passes a **path** (`app/trade.py:788`), and `load_live_calibration` re-reads it with `Path.read_bytes` (`calibration_artefact.py:250`), which follows symlinks. That leaves a TOCTOU window between the supervisor's resolve and the node's load. AUT-5a must close it by passing the bytes. Until it does, R7 (§3.5) is the fail-closed backstop.

## 3. Design

### 3.1 Modules

All modules are new, in `src/breezy/persistence/autonomy/`, inside the engine's import closure. `ENGINE_SOURCE_SHA256` is re-pinned in the same commit (§4.3).

| File | Purpose | Key interfaces |
|---|---|---|
| `rollback.py` | Champion history, trigger, target eligibility, precedence, planner, failure classification, readiness. Pure functions over the verified chain plus injected ports. | `champion_history(chain, now_ns) -> tuple[ChampionEpoch, ...]`; `rollback_trigger(fold, chain, now_ns) -> RollbackTrigger \| None`; `target_eligibility(epoch, chain, evidence, now_ns) -> Eligibility` (all §3.3.2 predicates, each with a reason code); `select_rollback_target(history, chain, evidence, now_ns) -> TargetSelection`; `prelaunch_decision(fold, chain, evidence, now_ns) -> PrelaunchDecision` (the K8 precedence); `plan_rollback(trigger, selection, ports) -> RollbackDecision`; `classify_failure(x) -> RollbackFailure`; `readiness(chain, evidence, ports) -> ReadinessRecord` |
| `drill.py` | The AUT-7b sequencer (a state machine derived from the chain, never stored), child composer, child-id allocator, marker writer/remover, episodes, bundle builder. | `drill_state(chain, now_ns) -> DrillState`; `next_drill_child_id(chains, root) -> str`; `compose_drill_child(root_bytes, child_id, policy_ruling_id) -> bytes`; `drill_start_gate(fold, chain, evidence, now_ns) -> GateResult`; `next_drill_step(state, clause, now_ns, ports) -> DrillStep`; `drill_episodes(chain) -> tuple[DrillEpisode, ...]`; `is_drill_fill(episodes, family_id, ts_ns) -> bool`; `build_drill_bundle(episode, ports) -> DrillBundle` |
| `drill_inject.py` | The `DRILL_INJECT` C6 `VERDICT` detector, with marker binding (K7). | `DrillInjectDetector.evaluate(marker_path, chain_view, clause_sha256, now_ns) -> DetectorOutcome` |
| `rollback_journal.py` | Hash-linked, write-once evidence journals for rollback decisions and readiness (K11). | `append_journal(kind, venue, record) -> JournalHead`; `verify_journal_chain(kind, venue) -> JournalHead`; `journal_head(kind, venue) -> str` |
| `post_verify.py` | Post-effect verification against the node boot lines (K4). | `post_verify(launch_date, chain, boot_lines) -> PostVerifyResult`; `classify_boot_failure(lines) -> BootFailure \| None` |

**Engine wiring.** AUT-5's engine binary calls `rollback.step(mode, …)` and `drill.step(mode, …)` in its `daily`, `intraday` and `prelaunch` modes. AUT-7 edits no `app/trade.py`, `settings.py` or `trade_supervisor*.py` (ARCH §5.1).

**Mode responsibilities after r2.**
- `prelaunch` (16:45, node down) is the **only** mode that widens. It writes every sender change and every RESUME: ROLLBACK, DRILL_PROMOTE and their partners, together with ACTIVATE (K6, K10, K14).
- `daily` (15:30) is read-only for widening rows. It runs readiness, the RETIRE of a closed drill child and the bundle.
- `intraday` stays restrictive-only. It writes the drill marker, DEMOTE, HALT, SWAP_CANCEL and post-verify HALTs.

### 3.2 Immutable champion history (criterion 1)

`ChampionEpoch` is a frozen dataclass with explicit serialisation. Fields:
- `venue`, `family_id`, `lineage_root_family_id`, `manifest_sha256`, `artefact_sha256` (from the family's BOOTSTRAP/MINT row, Z1);
- `entered_venue_seq`, `entered_kind` (`BOOTSTRAP`\|`PROMOTE`\|`DRILL_PROMOTE`\|`ROLLBACK`\|`RESUME`), `effective_from_ns`;
- `left_venue_seq | None`, `left_kind` (`SUPERSEDE`\|`DEMOTE`\|`HALT`\|`DISPLACED`\|`RETIRE`\|None), `left_effective_ns | None`;
- `rollback_eligible`, `demoted_for_cause`, `drill_child` (the subject of a DRILL_ADMIT row, W3);
- `last_attest_ns | None` (the newest ATTEST row for this family while it was CHAMPION).

How the history is built and protected:
- **Derivation.** A pure fold over `transitions` from genesis, checked by the AUT-5 verifier (hash links and the newest-export prefix). It uses the `resolve_champion` fold rule (Y8): pending, lapsed and voided pairs create no epoch (Z3).
- **Derived flags, never cached.**
  - SUPERSEDE sets `rollback_eligible` unless the subject is a drill child (W3); DEMOTE and HALT clear it; DISPLACED never sets it.
  - DEMOTE/HALT sets `demoted_for_cause`, and so does a SWAP_CANCEL that carries a cause on the incoming family (Y8).
- **Immutability.** No new mutable state. History inherits the `BEFORE UPDATE/DELETE → RAISE(ABORT)` triggers, the per-venue chain, the 0444 export and the node HWM. The daily pass renders `evidence/registry/champion_history_<venue>_<ts_ns>.json` (0444, write-once, the K11 naming) for humans only. A test pins it equal to the fold.

### 3.3 Automated rollback (criterion 2)

#### 3.3.1 Trigger (a code-fixed literal; no new policy key)

`rollback_trigger` fires when all of these hold on the fold at `now`:
1. The venue's {CHAMPION, HALTED} slot holds family F in **HALTED**.
2. F's halting row is a DEMOTE or HALT with cause class `RECOVERABLE_MODEL` (the policy's `detector → class` map: live sequential, drawdown, forecast and calibration drift, fill rate, slippage).
3. No pending pair exists on the venue (Y8).

The r1 drill-family exemption (rule 3) is **removed** (K7). A genuine non-`DRILL_INJECT` DEMOTE of a drill child takes the real-fault path in §3.6.6.

| Cause class | Why it never triggers a rollback |
|---|---|
| `RECOVERABLE_INFRA` | A feed, permit or unit fault hits every family alike. RESUME is the cure. |
| `DRILL` | The drill sequencer owns the RESUME and ROLLBACK (§3.6). |
| `TERMINAL` | The lineage is `terminal_frozen`, so the store refuses the ROLLBACK and the champion RETIREs (ARCH §5.3). |
| `INTEGRITY` (exec-store mirror) | The venue is frozen for ROLLBACK by C5 (W15). A rollback never **creates** this freeze (coordinator ruling); it only respects one created by `duplicate_fill`, `ambiguous_exit` or `halts_all`. |
| engine `cause_code` HALTs (§3.5) | Not a model fault. The resume rule in §3.5.2 applies. |

#### 3.3.2 Target eligibility (K2)

`target_eligibility` walks `champion_history` backwards from F's epoch. The target is the **first** epoch whose family G passes every predicate below. Each predicate has a reason code and its own RED test. `readiness()` calls the same function.

| # | Predicate | Source |
|---|---|---|
| E1 | G folds CHALLENGER, `rollback_eligible`, not `demoted_for_cause`, not a drill child | chain fold |
| E2 | G's lineage is not `terminal_frozen` and not rollback-blocked (§3.5, R2/R7 lineage block) | chain fold; rollback journal |
| E3 | `composition_kind` ∈ `LIVE_GATE_ROUTED_KINDS`; root in `_LINEAGE_POLICY_ALLOWLIST` or `_LIVE_ORDERS_ALLOWLIST` (`live_orders_gate.py:76`) | committed code |
| E4 | **Fresh ATTEST:** `last_attest_ns` is not None, and `left_effective_ns − last_attest_ns ≤ ATTEST_PERIOD_H + 1.04 h + ATTEST_MARGIN_H`, so G was attested up to its departure under the W1 cadence invariant | chain |
| E5 | **Age cap:** `now − left_effective_ns ≤ ROLLBACK_TARGET_MAX_AGE_D`. Proposed code ceiling ≤ 30 d; the policy value is 30 (C-7). | chain |
| E6 | **Fee verified:** an accepted AUT-6 fee-drift `VERDICT` PASS that (a) was produced after today's STOP, (b) cites a node-log `outcome=AGREE` line within `_FEE_VERIFIED_STALENESS_NS` (4 h, `fee_drift_probe.py:184`) of 16:40, and (c) verified a `taker_fee_coefficient` equal to G's manifest value. For a same-lineage G, §4.2 guarantees (c); for any other G it is checked. | C4 |
| E7 | **Current `live_orders_ruling`:** a child names the current policy ruling (§4.2); a root resolves through its committed `_LIVE_ORDERS_ALLOWLIST` triple with the deploy copy's sha re-verified (`live_orders_gate.py:130-190`). This is one function shared with the resolver (assumption C-1, §11). | committed code, ruling file |
| E8 | **No pending cause on G:** no accepted FAIL mapped to DEMOTE/HALT naming G after `left_effective_ns` that a later PASS has not superseded; no demand file naming G; no exec-store halt for G (the engine mirror) | C4, demand dir, mirror |
| E9 | **No byte-identical remedy:** G's `artefact_sha256` ≠ F's when F's cause is `RECOVERABLE_MODEL`. Rolling back to the same model is no remedy. | chain |
| E10 | `resolver.verify_family_bytes(G's BOOTSTRAP/MINT row)`: single-read manifest and artefact, sha equality, child-id regex and root, §4.2 equality against the committed root, `O_NOFOLLOW` | resolver |

Rules applied to the result:
- **No fallback.** If the first candidate fails E10, there is no rollback (R2).
- **Earlier failures skip.** A candidate that fails E1–E9 is skipped as ineligible: these are policy facts, not corruption.
- **Budget.** `MAX_ROLLBACKS_PER_VENUE_30D` (≤ 2) is counted at effect, with pending pairs as reservations (Z3).

#### 3.3.3 Position handoff invariant (K1)

The invariant: **every open position held under the outgoing family id has an owner after the swap.** `position_handoff_ok(outgoing, incoming, recon)` holds iff either:
- (a) `recon.open_positions_by_family[outgoing] == ∅`, from the post-STOP `RECONCILIATION` verdict (16:41, §4.4); or
- (b) the incoming family **owns** them: `family_declares_exit_rule(incoming) == family_declares_exit_rule(outgoing)` (`exit_gate.py:58`), with the same `composition_kind` and the same `lineage_root_family_id`, so §4.2 makes `exit_rule` and `no_leg_exit` equal.

For FQ, both sides are exit-incapable (G17). Positions are held to settlement and reconciled venue-net per slug, so (b) holds and no flatness is needed, consistent with ARCH §4.4. For an exit-capable outgoing family (today only `pm_us_crh_exit_v4`, a family-id literal), a child is never exit-capable. The swap is therefore refused while it holds positions, and nothing is stranded.

Where the check runs:
- It is binding in the 16:45 pass for ROLLBACK, DRILL_PROMOTE and the drill's closing ROLLBACK.
- A missing `open_positions_by_family` metric makes the verdict `INCONCLUSIVE`, and the swap is not written.
- Successor re-entry is still blocked by `rung_net_position_held` (C5 Y16) and the kind-scoped latch (G28).

The metric is an interface ask to AUT-2 (§5).

#### 3.3.4 Pre-launch decision and precedence (K6, K8, K14)

`prelaunch_decision` runs once per venue in the 16:45 pass, after the post-STOP reconciliation. It evaluates in this order:
1. **Drill step** due today (§3.6). The drill sequencer owns the slot and the steps below are skipped. A real-fault trigger during an episode is handled under §3.6.6.
2. **RESUME of F** if every RESUME precondition holds: F's own cause class is admissible (`RECOVERABLE_MODEL`/`RECOVERABLE_INFRA`, or `DRILL` with `cause_code=DRILL_INJECT`), its cause verdict now PASSes, `RESUME_COOLDOWN_H` is met, the class budget is available, there is no pending pair and §4.4 passes. RESUME wins over ROLLBACK because it restores the same verified sender with no sender change. **RESUME of F always stays available** (K9).
3. **ROLLBACK** if `rollback_trigger` stands, a target passes §3.3.2, the budget is available, `ROLLBACK_MIN_DWELL_H` is met and `position_handoff_ok` holds.
4. **Nothing.** The engine journals a reason code (R1 or R4) and sends a CRITICAL once per day per code.

**Damping.**
- `ROLLBACK_MIN_DWELL_H` is a proposed code ceiling ≥ 24, policy value 24 (C-7). No ROLLBACK may take effect less than 24 h after the previous sender change or RESUME on the venue took effect, measured effective instant to effective instant (a ROLLBACK's is its LAUNCH).
- DISPLACED never sets `rollback_eligible`, so two families cannot ping-pong by ROLLBACK.
- RESUME ping-pong is bounded by `MAX_RECOVERABLE_RESUMES_PER_LINEAGE_14D`.
- A HALT is restrictive and **never** charges the rollback budget, including the HALT that follows an exhausted budget (§4.5 "then a rollback trigger HALTs": F is already HALTED, so no row is written).

**Write (K14).** When step 3 is chosen, one `BEGIN IMMEDIATE` transaction through the AUT-5 API writes:
- the ROLLBACK row (G: CHALLENGER→CHAMPION, with `artefact_sha256`, `manifest_sha256` and `lineage_root_family_id`, Y6);
- its partner DISPLACED row (F: HALTED→CHALLENGER);
- the `ACTIVATE` row citing the pair.

All three carry `effective_launch_date` = today and `cause_verdict_ids` = F's halting causes. The §4.4 checks run **before** the write, so a failing check writes nothing (R4). The `transition_id`s are deterministic (Y9), so a crash-retry is a no-op.

**Effect within one supervisor cycle.** A qualifying DEMOTE committed before 16:45 on day D takes effect at D's 16:50 LAUNCH. One committed at or after 16:45 takes effect at D+1's LAUNCH. The worst case is ≤ 24 h 05 min, plus `ROLLBACK_MIN_DWELL_H` when a change took effect in the previous 24 h. Entries are already vetoed ≤ 15 min after the cause (the C5 SLO), so the dwell costs availability, never safety. **No code change:** the supervisor resolves the fold at LAUNCH (G2), and the rollback writes only under `~/.local/share/breezy/{registry,evidence}`.

**Gate-proven versus live-proven (K14, stated plainly).** While the policy has `promote_enabled=false` (the expected state, ARCH §4.2 Y12), the only SUPERSEDE that ever makes a family `rollback_eligible` is a DRILL_PROMOTE. Outside a drill episode there is therefore no eligible target, and the trigger→ROLLBACK chain **cannot fire live**: readiness reports `NO_TARGET` as INFO. The trigger path (`rollback_trigger` → `select_rollback_target` → `plan_rollback`) is **gate-proven only** (AUT-7a) while `promote_enabled=false`. AUT-7b proves live the same `plan_rollback` → write+ACTIVATE → resolver → node path that a triggered rollback uses, invoked by the drill sequencer instead of the trigger.

### 3.4 Preconditions per mode

| Check | Daily 15:30 | Pre-launch 16:45 | Supervisor LAUNCH 16:50 |
|---|---|---|---|
| Writes widening rows | **never** | ROLLBACK/DRILL_PROMOTE + partner + ACTIVATE; MINT/DRILL_ADMIT; RESUME | — |
| Open/AMBIGUOUS intent | not checked (no widening row) | **binding** `probe_open_intent` (node down; corrupt = OPEN) | binding re-check (§4.4) |
| `RECONCILIATION` PASS, produced after today's STOP (W8) | — | required, incl. `open_positions_by_family` | — |
| Position handoff (§3.3.3) | — | required for every sender change | — |
| Target eligibility E1–E10 | readiness only (no write) | required | resolver re-runs byte binding (Y6) |
| Fee verified (E6), permit (drill gate) | readiness reports them | required | — |
| Budgets, dwell, lineage freeze/block, INTEGRITY freeze | readiness reports them | required | resolver refusals |
| RESUME (incl. drill RESUME) | — | **only here** (K6) | — |

### 3.5 Failed rollback fails closed (criterion 3)

Rollback failures never cause a venue INTEGRITY freeze (coordinator ruling).

| # | Failure | Detected by | Effect |
|---|---|---|---|
| R1 | No eligible target; budget exhausted; dwell not met; venue already INTEGRITY-frozen by an exec-store cause | `prelaunch_decision` | **F stays HALTED** (entries vetoed, exits live). Journal `{trigger, decision, reason_code, attempt_n}`; CRITICAL `ROLLBACK_UNAVAILABLE` via `deliver_with_proof` once per day per reason. Retried at every 16:45 pass while the trigger stands. No row is written and no budget is charged. |
| R2 | Target bytes fail E10 (sha, symlink, missing, strict-load, §4.2 inequality) | `verify_family_bytes` | No pair. F stays HALTED. CRITICAL `ROLLBACK_TARGET_CORRUPT`. **Lineage rollback block**: rollback into G's lineage is refused (E2) from that journal record until two consecutive daily readiness records ≥ 24 h apart re-verify the lineage's candidate clean. That clears automatically once the bytes are repaired, with no operator step (L-48). Nothing else is frozen. |
| R3 | CAS failure on the write | store | Non-restrictive: re-read, re-evaluate, retry once, then CRITICAL. F stays HALTED and is retried next pass. A drill-abort HALT is restrictive and is retried until committed, with a demand file (Y19, Z11). |
| R4 | §4.4 fails at 16:45 (intent OPEN/AMBIGUOUS, reconciliation missing/INCONCLUSIVE/FAIL, handoff not owned) | `prelaunch_decision` | **Nothing written**, because the checks precede the write. F stays HALTED and boots entries-vetoed (Z7). CRITICAL `ROLLBACK_DEFERRED` with the reason. Retried daily. The journal counter `consecutive_deferred` grows; it does **not** escalate (the r1 "3 × → INTEGRITY" rule is deleted). |
| R5 | Resolver refuses at LAUNCH after ACTIVATE (byte drift 16:45→16:50, chain or HWM fault) | supervisor resolver | The C5 path: `REGISTRY_UNAVAILABLE`, and the supervisor triggers the intraday pass, which writes `SWAP_CANCEL` in [16:50, 17:00) (Z8). The fold restores F (HALTED) and the supervisor relaunches it entries-vetoed. For byte drift, the SWAP_CANCEL carries cause `rollback_target_corrupt` on G (→ `demoted_for_cause`, Y8) and the R2 lineage block. A chain or HWM fault carries no cause on G. |
| R6 | Post-effect mismatch: the boot line for the effective LAUNCH names a different family, `registry_seq`, `manifest_sha256` or `artefact_sha256` than the authorising row, or no composed line exists by 17:05 | `post_verify` in the first intraday pass ≥ 17:05 | After 17:00 a pair is never voided (Z8), so a HALT row on G is written (`cause_code=rollback_post_verify_failed`, restrictive). CRITICAL `ROLLBACK_POST_VERIFY_FAILED`. |
| R7 | **Load-time crash after the resolver passed** (K4: TOCTOU, F-2; `Path.read_bytes` follows symlinks). The node exits during composition with a manifest or artefact load error. | `classify_boot_failure` over the node log, triggered by AUT-5a's supervisor `registry_boot_load_failed` signal | The supervisor **stops relaunching** that resolved family (AUT-5a interface, §5) and triggers the intraday pass. In [16:50, 17:00): `SWAP_CANCEL` with cause `rollback_load_failed` on G (restores F, HALTED, entries-vetoed). From 17:00: a HALT row on G (`cause_code=rollback_load_failed`). The R2 lineage block applies in both cases. CRITICAL `ROLLBACK_LOAD_FAILED`. There is no crash loop: the next relaunch, if any, boots a HALTED family that is either F or blocked G. |

**Every failure ends with no family sending new entries on an unverified path.** Nothing falls back to an older or unverified family, and nothing freezes the venue. The journal records `{trigger, target, decision, failure_code, attempt_n, chain_head, prev_sha256}`.

#### 3.5.1 Engine `cause_code` HALT rows (assumption on Rev 6 C-3, §11)

These rows carry `decided_by=engine`, `cause_verdict_ids=[]` and `cause_code ∈ {drill_step_failed, rollback_post_verify_failed, rollback_load_failed}`. `rollback_target_corrupt` is used only as a SWAP_CANCEL cause. They are written only on a CHAMPION: the drill child (§3.6.5) or a newly effective G (R6, R7). They are restrictive, always permitted and never counted.

#### 3.5.2 Resume rule for engine `cause_code` HALTs (K9)

| cause_code | RESUME | Exit path |
|---|---|---|
| `drill_step_failed` (drill child) | **Never** (K7: a drill child resumes only on `DRILL_INJECT`) | The drill's closing ROLLBACK (DISPLACED), then RETIRE |
| `rollback_post_verify_failed`, `rollback_load_failed` (G) | In the 16:45 pass, only if all hold: (a) the cause clears, i.e. G's next HALTED boot passes `post_verify` (family, seq, shas) and E10 passes; (b) `RESUME_COOLDOWN_H`; (c) a dedicated venue counter `engine_halt_resumes` (≤ 3 per 7 d, proposed C-7); (d) §4.4 | If the counter is exhausted, G **stays HALTED** with a daily CRITICAL. It never goes to INTEGRITY, never RETIREs and never becomes `terminal_frozen`. A load failure clears only after the on-disk bytes are repaired through a reviewed build-side commit (the same path as K-5), with no operator decision. |

### 3.6 Drills (criterion 4)

#### 3.6.1 AUT-7a — gate drill

`tests/integration/autonomy/test_rollback_drill_gate.py` runs the whole AUT-7b sequence, the R1–R7 matrix, the position-across-swap cases (K1), the retry (K5) and the real-fault path (K7) in-process, in **every** gate run (`scripts/ci/run_tests_no_egress.sh`; L-43). It uses:
- a fake clock and a tmp `HOME` registry;
- a tmp exec store written through the real writer path (L-42);
- the real AUT-5 store, resolver, fold and engine modes;
- the real `DrillInjectDetector`, intraday producer and `RegistryWatchActor.tick_once`.

Supervisor LAUNCH is a port that calls the real resolver. The test also runs the production default port once (L-55).

#### 3.6.2 Production readiness

Every daily pass, `rollback.readiness()` runs `target_eligibility` (E1–E10) for the current champion's would-be target, without writing a row. It appends a readiness record (K11) to `evidence/rollback/readiness_<venue>_<ts_ns>_<invocation_id>.json`, which is write-once (`os.link` from a `mkstemp` file, failing if the name exists; never `os.replace` over an existing name; L-50). It reports:
- the per-predicate reason codes;
- the R2 lineage-block state;
- the budget, the dwell and `engine_halt_resumes`.

A present-but-corrupt target sends CRITICAL `ROLLBACK_TARGET_CORRUPT`. `NO_TARGET` is INFO, and stays so while `promote_enabled=false` outside a drill (§3.3.4).

#### 3.6.3 AUT-7b schedule and start gate

**Schedule.** The policy drill clause (AUT-5 owns the block; these values are proposed within the ceilings):
- `drill_cadence_days: 60`, measured **from the last COMPLETED episode** (its `RETIRE … drill_episode_closed` row) (K12). A failed or aborted episode is limited only by `DRILL_BUDGET_PER_VENUE_30D`, i.e. 30 days from its charged DRILL_PROMOTE.
- `drill_first_eligible_date` (≥ AUT-5b activation + 3 sessions of soak, §6).
- `drill_start_pass: "prelaunch"`, `drill_inject_utc: "15:00"` on D+1, `drill_demote_slo_min: 15`, `drill_max_episode_days: 6`.
- `drill_min_drawdown_headroom_frac: 0.5`.
- RETIRE reason `drill_episode_closed`.

**Start gate (`drill_start_gate`, 16:45 pass, all required).** Each item has its own RED test.

| # | Condition | Source |
|---|---|---|
| G-1 | The fold names the lineage root CHAMPION, not HALTED, not `demoted_for_cause` (W2); no pending pair; not `terminal_frozen`; no INTEGRITY freeze | chain |
| G-2 | Drill budget unspent in the trailing 30 d; cadence (K12) met | chain |
| G-3 | ≥ 1 ATTEST for the champion within `ATTEST_VERDICT_VALIDITY_H` (Z5) | chain |
| G-4 | AUT-6 canary `delivered=true` within `ALERT_CANARY_MAX_AGE_H` | delivery journal |
| G-5 | `RECONCILIATION` PASS produced after today's STOP | C4 |
| G-6 | **Fee verified** (E6 predicate on the champion) (K10) | C4 |
| G-7 | **Permit unexpired:** an AUT-6 permit-liveness `HEALTH` PASS from the last intraday producer run before STOP, and no `permit_lapsed` C1 `EntryVeto` record in the session after that run (K10). Read-only, so the permit authority is untouched. | C4, C1 |
| G-8 | **No OPEN or AMBIGUOUS intent:** `probe_open_intent` binding, node down (K10) | exec store |
| G-9 | **Drawdown headroom:** the newest accepted drawdown verdict's `metrics.drawdown_used_frac ≤ 1 − drill_min_drawdown_headroom_frac`, with drill fills included (K3) | C4 (AUT-6) |
| G-10 | `position_handoff_ok(fq_v1, child)` (§3.3.3) | C4 (AUT-2) |

#### 3.6.4 Child manifest and allocator (K5, K15)

`compose_drill_child` emits the root's exact JSON with **only three keys** changed:
- `family_id = <root>_r<NNNN>`;
- `trial_id_prefix = forecast_quantile_ladder/trial/<root>_r<NNNN>/`;
- `live_orders_ruling` = the policy ruling id.

`d0_climate_day` (`"2026-10-02"`), `density_artefact_path`, `density_artefact_sha256` and every size, price, station, θ and exit key stay byte-equal (§4.2). The child is written 0444 to `registry/families/<child>.json` via the AUT-5 child-write API.

**Allocator (`next_drill_child_id`).** `NNNN = 1 + max` over every BOOTSTRAP/MINT `family_id` matching `^<root>_r(\d{4})$` in **all** venue chains (lineage counters are venue-independent), starting at 1.
- A number is never reused, even when its family is RETIRED, lapsed or voided.
- `NNNN > 9999` refuses with a CRITICAL.
- The result must match both id regexes.
- It is a pure function of the chain, so a crash-retry yields the same id and the same MINT `transition_id`.
- If AUT-5's store exposes one shared `<root>_r<NNNN>` allocator for AUT-3 children, AUT-7 calls that instead and does not fork it (§5).

#### 3.6.5 Drill sequence for D = the first eligible day

Every row is engine-written, `decided_by=engine`, and charged only to the drill budget at effect (Z3).

| When | Mode | Row(s) / action | Proof artefact |
|---|---|---|---|
| D 16:41 | post-STOP producer (AUT-2) | `RECONCILIATION` incl. `open_positions_by_family` | verdict |
| D 16:45 | pre-launch | start gate G-1..G-10, then in one transaction: `MINT` r0001 ∅→SHADOW (no C3 record, no counter, Y2); `DRILL_ADMIT` →CHALLENGER; `DRILL_PROMOTE` r0001→CHAMPION + `SUPERSEDE` fq_v1→CHALLENGER (`rollback_eligible=true`, W3); `ACTIVATE`; all `effective_launch_date=D` (K10, K14; assumption C-4) | chain; journal; `DRILL_STARTED` via `deliver_with_proof` |
| D 16:50 | supervisor | resolves r0001; node boots it; **episode opens** (C1 `drill=true`) | AUT-5a resolved-family line `family_id=pm_us_crh_fq_v1_r0001 … artefact_sha256=9c0b6d6e…` |
| D 17:05 | intraday | `post_verify` (R6/R7) for D's LAUNCH | journal `POST_VERIFY_OK`; delivered |
| D+1 15:00 | intraday | writes `registry/drill/marker.json` (0444, `drill-marker/v1`: `episode_id` = the effective DRILL_PROMOTE `transition_id`, `child_id`, `ts_ns`, `clause_sha256`) | marker sha in journal |
| ≤ D+1 15:05 | intraday producer (AUT-6) | `DRILL_INJECT` FAIL **only if the marker binds** (K7, below) → C4 `HEALTH` FAIL, `declared_action_class=DEMOTE`, class `DRILL` | verdict |
| ≤ D+1 15:08 | intraday engine | `DEMOTE` r0001 CHAMPION→HALTED, `cause_code=DRILL_INJECT`; unlink the marker | chain; `DRILL_DEMOTED` |
| ≤ D+1 15:09 | watch actor | `entry_veto=registry_halted` on the next tick; exits live | C1 `EntryVeto`; node log |
| D+1 15:10 | producer | marker absent → `DRILL_INJECT` PASS (Z2) | verdict |
| D+1 16:50 | supervisor | HALTED r0001 boots entries-vetoed (Z7) | node log |
| D+2 16:45 | pre-launch | `RESUME` HALTED→CHAMPION, class `DRILL`, `cause_code=DRILL_INJECT` (cooldown ≥ 24 h since ≈ D+1 15:08; probe binding; §4.4) (K6) | chain; `DRILL_RESUMED` |
| D+2 16:50 / 17:05 | supervisor / intraday | r0001 boots unvetoed; `post_verify` | node log; journal |
| D+3 16:45 | pre-launch | `plan_rollback` (drill-invoked): E1–E10 on fq_v1, handoff, dwell (D+3 16:50 − D+2 16:45 = 24 h 05 m ≥ 24 h), then **in one transaction** `ROLLBACK` fq_v1 CHALLENGER→CHAMPION (re-verified sha `9c0b6d6e…`) + `SUPERSEDE` r0001→CHALLENGER (never eligible, W3) + `ACTIVATE`, `effective_launch_date=D+3` (K14) | chain; `DRILL_ROLLBACK` |
| D+3 16:50 / 17:05 | supervisor / intraday | node boots fq_v1; **episode closes**; `post_verify` (R6) | resolved-family line `family_id=pm_us_crh_fq_v1 artefact_sha256=9c0b6d6e…`; `POST_VERIFY_OK` delivered |
| D+4 15:30 | daily | `RETIRE` r0001 (`drill_episode_closed`); then the **evidence bundle** (§6) built in the same pass (K18) | chain; export `registry_polymarket_us_<D+4>.jsonl`; `evidence/drills/drill_polymarket_us_<episode_id>.json` |

**Marker binding (K7).** `DrillInjectDetector` returns FAIL only when the single-read marker (`O_NOFOLLOW`, ≤ 4096 B, exact-set schema) satisfies all of:
- `episode_id` equals the chain-derived open episode;
- `child_id` equals the fold's current CHAMPION and that family is a drill child;
- `clause_sha256` equals the active policy block's `drill_clause_sha256`;
- `ts_ns` ∈ [D+1 `drill_inject_utc`, + `drill_demote_slo_min`].

Any mismatch, symlink, oversize or parse failure gives **ERROR** (never FAIL, never PASS) and a CRITICAL. An absent marker gives PASS.

**Retry (K5).** If D's 16:45 start gate fails **after** MINT and DRILL_ADMIT already committed (a crash between transactions, or a later G-check), or a later `SWAP_CANCEL` without a cause on r0001 voids the pair:
- the next eligible pre-launch pass **reuses CHALLENGER r0001**;
- it writes only a new `DRILL_PROMOTE` + `SUPERSEDE` (+ `ACTIVATE`); the new `family_prior_seq` gives a new `transition_id`;
- there is no second MINT and no second DRILL_ADMIT charge; the voided pair was never charged (Z3).

If r0001 carries `demoted_for_cause`, the episode is abandoned and the next cadence allocates r0002.

#### 3.6.6 Abort and real-fault paths

- **SLO failure** (no DEMOTE within `drill_demote_slo_min` of the marker, RESUME refused, post-verify mismatch, episode past `drill_max_episode_days`):
  - the intraday pass HALTs r0001 (`cause_code=drill_step_failed`, never resumed);
  - the closing ROLLBACK runs at the next 16:45 pass with partner `DISPLACED` r0001 HALTED→CHALLENGER, then RETIRE;
  - if that ROLLBACK fails, R1–R7 apply: r0001 stays HALTED, the venue has no new-entry sender, retries run daily, and there is no INTEGRITY freeze.
- **Genuine fault on r0001 (K7).** A DEMOTE from a non-`DRILL_INJECT` detector:
  - follows the real-fault path: its own cause class, **no** drill auto-RESUME, and `rollback_trigger` fires (rule 3 removed);
  - E9 excludes fq_v1, whose bytes are identical, as a model remedy, so the trigger gives R1, r0001 stays HALTED and a CRITICAL is sent;
  - r0001 may later RESUME only under its own class rules (e.g. `RECOVERABLE_MODEL`, charging the lineage budget);
  - the drill sequencer then writes the closing drill ROLLBACK to fq_v1 at the next 16:45 pass, which is an identity restore with no model change, so the episode closes;
  - a TERMINAL cause freezes the lineage, and only a reviewed new root recovers (ARCH §5.3).

#### 3.6.7 Drill fills and costs

`drill_episodes()` returns `[DRILL_PROMOTE effective_ns, closing ROLLBACK effective_ns)` per child. `is_drill_fill` is true for any fill of a drill-child family id **or** any fill inside an interval. Consumers:
- AUT-1 stamps C1 `drill=true`;
- AUT-2 re-derives `excluded_reason=drill`, `admissible=false`;
- AUT-4's live sequential and the KILL clock exclude them.

**Drill fills stay in risk (K3, W12).** They are real money:
- they count in every DRIFT/HEALTH detector, the drawdown limit, venue-net reconciliation, realised P&L and portfolio ROI, and the venue daily budget (Z18, G21);
- only n and the KILL clock exclude them.

Tests: the ARCH-named `test_detectors_and_drawdown_include_drill_fills` and `test_drill_fills_spend_venue_budget`, and AUT-7's `test_gate_drill_fills_feed_risk_reconciliation_and_pnl`.

**Drill budget per 30 d per venue.** 1 DRILL_PROMOTE, 1 RESUME of class `DRILL`, 1 drill ROLLBACK (§4.5), plus the `drill_admits` counter. All are charged at effect; a lapsed or cancelled pair is not charged. A real-fault rollback during an episode is charged to the **production** rollback budget.

**Statistical cost (K13).**
- Session D (D 16:50 → D+1 15:08 veto) and session D+2 (D+2 16:50 → D+3 16:40) carry drill fills: about **2 sessions ≈ 10 fills** at about 5 fills per day.
- Session D+1 is vetoed: about **1 session ≈ 5 fills of opportunity**.
- There is no extra money at risk: the byte-identical child trades inside the same caps.

### 3.7 Units

No new unit (K18). Everything runs inside `breezy-autonomy-engine*` (AUT-5) under `engine.lock` and within the engine's memory cap (own-lock units ≤ 4G in total, §5.2). The r1 `breezy-autonomy-drill-report.service/.timer` is **deleted**.

## 4. Work packages

Gate commands for every WP:
- `scripts/ci/run_tests_no_egress.sh <focused paths>`, then the full `scripts/ci/run_tests_no_egress.sh`, reading EXIT before any push;
- `cd <tree root> && lint-imports`, which must print "N kept, 0 broken" (the console script, never `python -m importlinter`);
- the mypy ratchet `tests/unit/test_mypy_ratchet.py`.

Worktrees export `PYTHONPATH=<worktree>/src` and use the exact interpreter. Never `uv`, `pip` or `git stash`. Each WP is RED-first, and its commit message carries the RED and GREEN output.

### AUT-7.WP1 — champion history (Wave 1, against ARCH-0 stubs)
- **Files:** `src/breezy/persistence/autonomy/rollback.py`; `tests/unit/autonomy/test_rollback_champion_history.py`.
- **RED first:**
  - `::test_history_is_a_pure_fold_of_the_verified_chain`
  - `::test_history_never_reads_projection_or_families_cache`
  - `::test_history_refuses_unverified_or_export_divergent_chain`
  - `::test_pending_lapsed_and_voided_pairs_create_no_epoch`
  - `::test_drill_promote_supersede_makes_incumbent_rollback_eligible` (W3)
  - `::test_drill_child_is_never_rollback_eligible`
  - `::test_demote_clears_and_displaced_never_sets_rollback_eligible`
  - `::test_swap_cancel_with_incoming_cause_sets_demoted_for_cause`
  - `::test_last_attest_and_left_effective_ns_derived`
  - `::test_every_champion_epoch_appears_in_history` (parametrized over `_COMPOSITION_KINDS`)
  - `::test_history_render_equals_fold_and_is_write_once`
- **GREEN:** all pass, plus `test_rollback_module_has_no_family_literals` (AST).
- **Activation:** a pure library, live when the engine imports it (WP3). Engine pin updated in the same commit.

### AUT-7.WP2 — trigger, eligibility, precedence, journal (Wave 1)
- **Files:** `rollback.py`, `rollback_journal.py`; `tests/unit/autonomy/test_rollback_planner.py`, `test_rollback_eligibility.py`, `test_rollback_journal.py`.
- **RED first, trigger and precedence:**
  - `::test_trigger_fires_on_recoverable_model_demote_of_champion`
  - `::test_trigger_silent_for_infra_drill_terminal_integrity_and_engine_cause`
  - `::test_trigger_fires_for_genuine_fault_on_drill_child` (K7)
  - `::test_trigger_refused_while_pair_pending`
  - `::test_resume_preferred_over_rollback_when_admissible`
  - `::test_resume_of_halted_f_stays_available_after_failed_rollback` (K9)
  - `::test_rollback_min_dwell_refuses_within_24h_of_last_change`
  - `::test_rollback_resume_ping_pong_damped` (alternating FAIL/PASS on F and G over 30 d: ≤ 1 change per dwell, ≤ 2 rollbacks, then F HALTED)
  - `::test_budget_exhausted_halt_charges_no_rollback_budget` (K8)
- **RED first, eligibility** (`test_rollback_eligibility.py`, one per predicate, K2):
  - `::test_target_requires_fresh_attest`
  - `::test_target_refused_past_age_cap`
  - `::test_target_requires_fee_verified_verdict_matching_theta`
  - `::test_target_requires_current_live_orders_ruling`
  - `::test_target_refused_with_pending_cause_or_demand_or_exec_halt`
  - `::test_target_refused_byte_identical_for_model_cause`
  - `::test_target_excludes_demoted_terminal_unrouted_and_blocked_lineage`
  - `::test_target_is_most_recent_eligible`
  - `::test_no_fallback_to_older_target_on_verify_failure`
  - `::test_readiness_reports_every_predicate_reason`
- **RED first, budget, bytes and handoff:**
  - `::test_rollback_budget_counted_at_effect_with_reservations`
  - ARCH-named `tests/unit/autonomy/test_rollback_restores_byte_identical_artefact.py::test_rollback_restores_byte_identical_artefact`
  - `::test_target_symlink_or_missing_or_sha_mismatch_is_corrupt`
  - `::test_position_handoff_owned_or_flat_else_refused` (K1: FQ→FQ child owned; exit-capable outgoing with open positions refused; missing metric INCONCLUSIVE)
- **RED first, journal** (K11):
  - `test_rollback_journal.py::test_journal_exact_set_write_once_0444_no_paths`
  - `::test_journal_prev_sha256_links_and_chain_head`
  - `::test_journal_broken_link_blocks_all_rollbacks_and_alerts`
  - `::test_readiness_filenames_unique_never_overwritten`
- **GREEN:** all pass. `verify_family_bytes` is imported from the resolver (`test_rollback_uses_resolver_byte_binding`, AST).
- **Activation:** with WP3.

### AUT-7.WP3 — engine integration, fail-closed matrix, post-verify, readiness (Wave 1 code against the AUT-5a stub; live after AUT-5a)
- **Files:** `rollback.py` step hooks, `post_verify.py`; `tests/integration/autonomy/test_rollback_engine.py`, `tests/unit/autonomy/test_post_verify.py`.
- **RED first:**
  - `::test_demote_before_1645_rolls_back_at_same_day_launch`
  - `::test_demote_after_1645_rolls_back_at_next_launch`
  - `::test_prelaunch_writes_pair_and_activate_in_one_transaction` (K14)
  - `::test_prelaunch_checks_precede_write_so_failure_writes_nothing`
  - `::test_rollback_requires_no_code_change` (repo mounted read-only)
  - `::test_failed_rollback_leaves_f_halted_and_retries_daily` (parametrized R1–R4; asserts no INTEGRITY row or freeze, a journaled counter and a delivered CRITICAL)
  - `::test_no_rollback_failure_ever_freezes_the_venue` (coordinator ruling; parametrized R1–R7)
  - `::test_corrupt_target_blocks_only_its_lineage_and_clears_after_two_clean_readiness`
  - `::test_post_launch_resolver_refusal_cancels_with_cause_on_target` (R5)
  - `::test_daily_pass_writes_no_widening_row`
  - `::test_resume_written_only_in_prelaunch_with_binding_probe` (K6)
  - `::test_rollback_alerts_journal_delivery` (non-2xx → `delivered=false`, retried; G25)
- **RED first, post-verify** (`test_post_verify.py`, K4):
  - `::test_post_verify_runs_at_1705_against_boot_resolved_sha`
  - `::test_post_verify_mismatch_halts_target` (R6)
  - `::test_post_verify_missing_composed_line_by_1705_halts`
  - `::test_post_verify_interim_parses_fq_live_orders_line` (`app/trade.py:753-762` format)
  - `::test_load_crash_after_resolve_halts_and_alerts_not_crash_loop` (R7: symlink swap between resolve and load; before 17:00 → SWAP_CANCEL with cause; after → HALT; no second relaunch of the same resolved family)
  - `::test_engine_halt_resume_rule_and_counter_never_integrity` (§3.5.2)
- **GREEN:** all pass. The §4.7 envelope tests stay unweakened and `test_damping_ceilings` stays green.
- **Activation:** on merge, after AUT-5a's engine units are live. Engine restart in 01:00–16:40 (memory note `activate-code-immediately`), never touching the node.

### AUT-7.WP4 — drill library and DRILL_INJECT (Wave 1)
- **Files:** `drill.py`, `drill_inject.py`; `tests/unit/autonomy/test_drill.py`, `test_drill_inject.py`.
- **RED first, ARCH-named:**
  - `::test_drill_promote_refuses_non_champion_sha`
  - `::test_drill_inject_mapped_only_in_clause`
  - `::test_drill_budget_separate`
  - `::test_drill_flag_spans_promote_to_rollback`
  - `::test_drill_admit_charges_only_drill_budget`
  - `::test_drill_inject_passes_when_marker_absent`
  - `::test_drill_resume_never_charges_model_budget`
  - `::test_drill_refused_over_halted_incumbent`
  - `::test_drill_rollback_to_superseded_incumbent_admitted`
- **RED first, then:**
  - `::test_drill_child_equals_root_modulo_three_keys` (K5: `d0_climate_day` byte-equal)
  - `::test_drill_child_writes_no_c3_lineage_and_no_counter`
  - `::test_next_drill_child_id_monotone_never_reused_across_venues` (K15: RETIRED/voided numbers skipped; > 9999 refuses; crash-retry idempotent)
  - `::test_drill_start_gate_each_condition` (parametrized G-1..G-10: fee verified, permit, intent, drawdown headroom, handoff; K3, K10)
  - `::test_drill_cadence_from_last_completed_episode` (K12)
  - `::test_failed_episode_limited_only_by_30d_budget` (K12)
  - `::test_drill_retry_reuses_admitted_child_and_charges_no_second_admit` (K5)
  - `test_drill_inject.py::test_marker_must_bind_episode_child_clause_and_window` (K7: each field mismatched → ERROR)
  - `::test_marker_symlink_oversize_unparseable_is_error_not_pass`
  - `::test_drill_child_resumes_only_on_drill_inject_cause` (K7)
  - `::test_genuine_fault_on_drill_child_takes_real_path_no_auto_resume` (K7)
  - `::test_is_drill_fill_by_family_id_or_interval`
  - `::test_drill_state_is_derived_from_chain_after_restart`
- **GREEN:** all pass, and the producer pin covers `drill_inject.py` (`test_code_identity_pins_cover_import_closure`).
- **Activation:** with WP6.

### AUT-7.WP5 — AUT-7a gate drill (Wave 1; completes after the AUT-5a/AUT-6 interfaces land)
- **Files:** `tests/integration/autonomy/test_rollback_drill_gate.py`.
- **RED first:**
  - `::test_gate_drill_full_episode`: the exact §3.6.5 rows and modes; RESUME and the closing ROLLBACK only in prelaunch; byte identity of the restored sha; `drill=true` from D 16:50 to D+3 16:50; marker→veto ≤ 15 min; post-verify OK ×3.
  - `::test_gate_drill_position_open_across_each_swap` (K1: a position opened under fq_v1 before DRILL_PROMOTE, under r0001 before the closing ROLLBACK, and in a production ROLLBACK case; asserts reconciliation stays PASS, `rung_net_position_held` blocks re-entry and nothing is stranded; an exit-capable outgoing refuses).
  - `::test_gate_drill_failure_matrix` (R1–R7 at each step; no INTEGRITY freeze; child HALTED; alert journaled).
  - `::test_gate_drill_retry_after_swap_cancel` (K5).
  - `::test_gate_drill_genuine_fault_path` (K7).
  - `::test_gate_drill_fills_feed_risk_reconciliation_and_pnl` (K3).
  - `::test_drill_fills_excluded_from_n_and_kill_clock` (ARCH-named).
  - `::test_gate_drill_runs_production_default_port_once` (L-55).
- **GREEN:** passes in the full gate and is listed in the T1 lane (`scripts/ci/tier_lanes.py`).
- **Activation:** the gate is the schedule, so it is live on merge.

### AUT-7.WP6 — live drill wiring and evidence bundle (Wave 3, after the AUT-5b ruling and allowlist widening)
- **Scope:** `drill.step(mode)` in the prelaunch, intraday and daily modes; `build_drill_bundle` called from the D+4 daily pass (K18); the rollback and drill section of `deploy/systemd/README.md`; the drill-clause values handed to AUT-5's ruling.
- **RED first:**
  - `tests/unit/autonomy/test_drill_bundle.py::test_bundle_requires_chain_export_nodelog_journal_items`
  - `::test_bundle_refuses_on_missing_or_mismatched_node_log_line`
  - `::test_bundle_lists_window_commits_against_allowed_set` (K17)
  - `::test_bundle_emitted_only_from_d4_daily_pass_no_unit` (K18)
  - `::test_bundle_write_once_0444`
- **GREEN:** all pass, plus a gate-drill rerun.
- **Activation:** on merge with the engine restart. The drill then starts on its own at `drill_first_eligible_date`; no timer to install.

### AUT-7.WP7 — AUT-7b execution (live, no code)
- The engine runs §3.6 unattended. The coordinator only observes, with a Monitor on the chain export and the bundle path (memory note `every-background-job-needs-a-watch`).
- **GREEN:** an independent scorer signs off the §6 bundle as complete.

## 5. Association

Interfaces consumed. Each is a blind assumption; if one is absent, AUT-7 raises it in the AUT-5/AUT-6/AUT-2 review and never forks it.

| Contract | From | Interface AUT-7 needs |
|---|---|---|
| C5 store | ARCH-0/AUT-5 | `VerifiedVenueChain`; `resolve_champion`; `write_transitions(rows, expected_prior_seq)` (atomic multi-row, so pair + ACTIVATE fit one transaction); `write_child_manifest`; `resolver.verify_family_bytes(row)`; lineage and drill counters; the shared `<root>_r<NNNN>` allocator if AUT-5 owns one (K15); engine `cause_code` HALT rows (C-3) |
| C5 export | AUT-5 | the daily export carries `evidence_journal_heads: {rollback, readiness}` (sha of the newest journal file per venue), so the journals are anchored outside the engine (K11) |
| C5 engine | AUT-5 | mode hooks; prelaunch may write MINT, DRILL_ADMIT, pair + ACTIVATE and RESUME (C-4); intraday writes the marker under the active clause |
| Supervisor / node (AUT-5a) | AUT-5 | (1) the **resolved-family boot line** `registry_resolved venue=<v> family_id=<id> registry_seq=<n> chain_head=<h> manifest_sha256=<m> artefact_sha256=<a>`, emitted by the node after resolve; (2) a **composed line** `registry_composed family_id=<id> artefact_sha256=<a>` after the artefact load succeeds; (3) `registry_boot_load_failed family_id=<id> stage=manifest\|artefact`, and the supervisor neither relaunches that resolved family again before the next LAUNCH nor fails to trigger the intraday pass (R7); (4) node log file paths (memory note `trade-node-dies-with-the-session`: log FILES, not journald); (5) bytes passed to composition, closing F-2. Interim: the `fq_live_orders … calibration_sha256=` line (`app/trade.py:753-762`) plus successful strategy construction. |
| C5 policy | AUT-5 ruling | the drill clause (§3.6.3), `drill_clause_sha256`, RETIRE reason, `DRILL_INJECT → DEMOTE` class `DRILL`, the `RECOVERABLE_MODEL` map, the policy values `ROLLBACK_MIN_DWELL_H`, `ROLLBACK_TARGET_MAX_AGE_D`, `drill_min_drawdown_headroom_frac` |
| C4 | AUT-6 | the intraday producer evaluates `DrillInjectDetector`; a fee-drift `VERDICT` citing the AGREE log line and the verified θ (E6/G-6); a permit-liveness `HEALTH` verdict (G-7); a drawdown verdict with `metrics.drawdown_used_frac` that includes drill fills (G-9, K3) |
| C4 | AUT-2 | post-STOP `RECONCILIATION` with `metrics.open_positions_by_family` (K1), plus intraday RECONCILIATION |
| C1 | AUT-1 | `drill` flag from `is_drill_fill`; `EntryVeto` records (`registry_halted`, `permit_lapsed`) |
| C2 | AUT-2 | `excluded_reason=drill`; drill rows keep `realized_pnl` and feed P&L/ROI aggregates (K3) |
| C4 live / KILL | AUT-4 | admissible-only n; the KILL clock keyed on `lineage_root_family_id` (K-3) |
| §4.6 | AUT-6 | `deliver_with_proof` and the delivery journal |

**Provided:**
- `champion_history`, `target_eligibility` and `readiness` → AUT-5 and AUT-6;
- `position_handoff_ok` → AUT-5, offered for PROMOTE as well (cross-area note: PROMOTE has the same stranding risk);
- `drill_episodes` and `is_drill_fill` → AUT-1, AUT-2, AUT-4;
- `DrillInjectDetector` → AUT-6;
- the executed AUT-7b → the AUT-5 and AUT-6 live proofs.

**Order:**
- WP1, WP2 and WP4 run in parallel in Wave 1.
- WP3 and WP5 complete when AUT-5a (engine modes, resolver, boot lines) and AUT-6 (`deliver_with_proof`, producer, fee/permit/drawdown verdicts) land.
- WP6 follows AUT-5b, AUT-1 (drill flag) and AUT-2b (drill exclusion and `open_positions_by_family`).
- WP7 follows the §6 soak.

## 6. Live-proof protocol

**Preconditions (all observed, none hand-made):**
- the AUT-5a watch actor live ≥ 3 sessions with no `registry_unreadable`;
- ≥ 1 ATTEST for fq_v1;
- an AUT-6 canary `delivered=true` row (`alerts_undeliverable` armed);
- the post-STOP RECONCILIATION producer emitting `open_positions_by_family`;
- the fee, permit and drawdown verdicts flowing;
- the WP3 readiness journal running daily with an intact `prev_sha256` chain.

**Bundle** `~/.local/share/breezy/evidence/drills/drill_polymarket_us_<episode_id>.json` (0444, write-once, emitted by the D+4 15:30 daily pass). It cross-references:
1. The chain export rows `registry_polymarket_us_<D..D+4>.jsonl`: MINT, DRILL_ADMIT, DRILL_PROMOTE+SUPERSEDE+ACTIVATE (D 16:45), DEMOTE (D+1), RESUME (D+2 16:45), ROLLBACK+SUPERSEDE+ACTIVATE (D+3 16:45), RETIRE (D+4). All are `decided_by=engine` with one pinned `engine_code_sha`, contiguous `venue_seq` and a verified chain head; the export's `evidence_journal_heads` match the journal files.
2. The node log files: resolved-family and composed lines for r0001 at D, the HALTED boot at D+1, r0001 at D+2 and fq_v1 at D+3, each with `artefact_sha256=9c0b6d6e66a587c1b4e14e5f95ff5cedb3c7195f62f8ad4238191fdd75923a5e`; the `registry_halted` set and clear lines.
3. Verdict files: DRILL_INJECT FAIL (bound marker) then PASS.
4. The delivery journal: `delivered=true` for DRILL_STARTED, DRILL_DEMOTED, DRILL_RESUMED, DRILL_ROLLBACK and the three POST_VERIFY_OK events.
5. **No commit in the loop (K17):** `git log --since=<D 16:45> --until=<D+4 15:30> --format='%H %s' -- deploy src` is empty, **or** every listed commit appears by sha in the bundle's `allowed_commits` with its touched paths, and none touches `deploy/families/**`, `deploy/systemd/**`, `deploy/families/rulings/**`, `src/breezy/persistence/autonomy/**`, `src/breezy/persistence/live_orders_gate.py`, `src/breezy/app/trade.py` or `src/breezy/runtime/trade_supervisor*.py`. Every drill row's `engine_code_sha` is identical.
6. Drill fills: C1 `drill=true` and C2 `excluded_reason=drill`; live n and the KILL-clock counter unchanged; the same fills present in the drawdown, reconciliation and P&L inputs (K3).

The coordinator copies a summary to `docs/evidence/AUT-7b_drill_<D>.md` after the fact; that step is outside the loop.

**Clock and ETA** (honest; build pace is not guaranteed):

| Milestone | Earliest | P50 | P90 |
|---|---|---|---|
| ARCH-0 merged | 2026-10-09 | 10-12 | 10-17 |
| WP1/2/4 merged; WP3/5 after AUT-5a/AUT-6 | 10-16 | 10-21 | 10-28 |
| AUT-5b ruling + allowlist; AUT-2b; WP6 | 10-27 | 11-04 | 11-14 |
| Soak met → D | 11-02 | 11-09 | 11-19 |
| AUT-7b closes (D+4 bundle) = **live proof** | **2026-11-06** | **2026-11-13** | **2026-12-23** |

**P90 recomputed (K12).** First D = 11-19. That episode takes effect, then fails, and is charged. A failed episode is limited only by the 30-day budget, not by the 60-day cadence, so the retry D′ = 11-19 + 30 d = 12-19 and it closes at D′+4 = **12-23**. The margin to the 2027-01-25 KILL is **33 days**. A second consecutive post-effect failure gives D″ = 2027-01-18, closing 01-22, with a 3-day margin; a third cannot complete before the KILL. A pre-effect lapse or SWAP_CANCEL is not charged and slips one day. If the KILL fires TERMINAL first, DRILL_PROMOTE is refused (ARCH §5.3). The drill needs no natural fill, so the ~5 fills/day rate does not gate it.

**Evidence class:** "machinery proven, edge unproven". In addition, while `promote_enabled=false` the trigger→ROLLBACK chain is **gate-proven**, and the live drill proves the shared `plan_rollback`→LAUNCH path (§3.3.4).

## 7. Score-3 verification checklist (independent scorer)

| Criterion | Check |
|---|---|
| History immutable | Immutability probe (K16): `sqlite3 'file:…/registry.sqlite?mode=ro' ".backup <scratch>/reg_copy.sqlite"`, then `sqlite3 <scratch>/reg_copy.sqlite "UPDATE transitions SET kind=kind WHERE seq=1"` must fail with the trigger's ABORT, and the same for `DELETE`. Production is never written. Also `test_history_never_reads_projection_or_families_cache` and `test_history_render_equals_fold_and_is_write_once`. |
| (a) unattended | bundle item 1 (`decided_by=engine`, one `engine_code_sha`); item 5 (K17) |
| (b) family-agnostic | `test_every_champion_epoch_appears_in_history`, `test_rollback_module_has_no_family_literals` |
| Trigger within one cycle, no code change | `test_demote_before_1645_rolls_back_at_same_day_launch`, `test_demote_after_1645_rolls_back_at_next_launch`, `test_prelaunch_writes_pair_and_activate_in_one_transaction`, `test_rollback_requires_no_code_change`; live: the D+3 16:45 ROLLBACK+ACTIVATE → D+3 16:50 boot line. The trigger leg is **gate-proven** while `promote_enabled=false`, as stated. |
| Target eligibility | `test_rollback_eligibility.py` (one test per E-predicate) |
| Position handoff | `test_position_handoff_owned_or_flat_else_refused`, `test_gate_drill_position_open_across_each_swap` |
| (c) fails closed | `test_failed_rollback_leaves_f_halted_and_retries_daily[R1..R4]`, `test_no_rollback_failure_ever_freezes_the_venue[R1..R7]`, `test_post_verify_mismatch_halts_target`, `test_load_crash_after_resolve_halts_and_alerts_not_crash_loop`, `test_gate_drill_failure_matrix` |
| (d) detected + delivered | `test_rollback_alerts_journal_delivery`; bundle item 4; readiness journal chain verified (`verify_journal_chain`) and head equal to the export's `evidence_journal_heads` |
| Damping | `test_rollback_resume_ping_pong_damped`, `test_rollback_min_dwell_refuses_within_24h_of_last_change`, `test_budget_exhausted_halt_charges_no_rollback_budget` |
| (e) RED→GREEN | WP commit messages; full-gate EXIT=0 per merge |
| Drills scheduled | gate: `test_rollback_drill_gate.py` in the T1 lane (`scripts/ci/tier_lanes.py`); live: `drill_cadence_days` and `drill_first_eligible_date` in the sha-pinned policy block, plus the engine journal of daily `drill_start_gate` decisions (no timer exists to list, K18) |
| (f) live proof | the bundle is complete; restored sha = `9c0b6d6e…923a5e`; ≥ 4 trading days D…D+3 |
| Drill exclusion, risk inclusion | `test_drill_fills_excluded_from_n_and_kill_clock`, `test_gate_drill_fills_feed_risk_reconciliation_and_pnl`, `test_detectors_and_drawdown_include_drill_fills` |

## 8. Risks and failure modes

| ID | Risk | Mitigation |
|---|---|---|
| K-1 | Fee drift during the drill: the exec-store `policy_halt` on r0001 is TERMINAL and freezes the whole fq_v1 lineage | Accepted fail-closed cost (Z20 analogue). G-6 requires a fee-verified verdict at D 16:45. Recovery is a reviewed new root. |
| K-2 | Each drill costs ≈ 10 drill fills plus ≈ 1 vetoed session (K13) | Cadence 60 d from completion; at most 2 completed drills before the KILL. |
| K-3 | The champion-scoped KILL clock (`promotion_criteria.py:135`) would follow r0001 | AUT-2/AUT-4 key it on `lineage_root_family_id` and exclude drill intervals (test pinned). |
| K-4 | An AMBIGUOUS intent open at 16:45 defers the drill or a rollback (Z19) | R4 writes nothing and retries daily with no escalation. AUT-2 measures the rate. |
| K-5 | Byte drift of a committed root poisons the target | Readiness alerts the same day. R2 blocks only that lineage and clears after repair plus two clean readiness passes. |
| K-6 | F-1 phantom containment base; F-2 TOCTOU re-read | AUT-5 fixes both (§5). R5/R7 are the backstops. |
| K-7 | Memory on the 31 GB host | Runs inside the engine's ≤ 4G own-lock budget; the unit was removed (K18); the bundle builder streams the export and reads only the node log lines it needs. |
| K-8 | Shared venv, concurrent agents | Exact interpreter; no `uv`/`pip`/`git stash`; per-agent scratchpads; `PYTHONPATH`; disjoint files; full gate after every merge. K17 lists concurrent commits rather than requiring an empty window. |
| K-9 | Engine crash mid-drill | State re-derived from the chain; idempotent ids; the allocator is chain-pure; the heartbeat veto bounds exposure. |
| K-10 | Statistical capacity | No edge claim. |
| K-11 | KILL 2027-01-25 | P90 margin 33 d; two consecutive post-effect failures leave 3 d. |
| K-12 | No eligible target exists live while `promote_enabled=false` | Stated in §3.3.4 and §6. The trigger path is gate-proven; readiness reports `NO_TARGET` as INFO rather than a defect. |
| K-13 | The interim post-verify line (`app/trade.py:753-762`) logs the manifest-pinned sha before the load | Interim only. A mismatch at load raises (`calibration_artefact.py:252-256`), so the interim check requires the composed outcome too, and the AUT-5a composed line replaces it. |
| K-14 | A broken rollback/readiness journal link | Fail-closed: all rollbacks blocked (R1) plus a CRITICAL; repair is build-side. |

## 9. Binding-constraint compliance

- **Nautilus:** untouched. Only the existing native `Actor` pattern is consumed (AUT-5).
- **Caps:** never read, assigned or derived. The drawdown headroom (G-9) is a policy-ruling risk value, not an operator cap. `test_autonomy_never_reads_or_writes_operator_controls` covers all five new modules.
- **allow_short:** stays `False`. The child equals the root on every size and side key.
- **NO-SEND:** unchanged. The gate drill runs under `run_tests_no_egress.sh`. The only egress is `deliver_with_proof` on the existing `alerts.env` key (`test_autonomy_alert_egress_not_widened`).
- **Master enablement and permit:** untouched. G-7 only **reads** a permit-liveness verdict. Rollback and drill change only which allowlisted family the resolver names.
- **PREREG via ruling:** the drill clause, cadence, dwell, age cap and headroom live only in the AUT-5 sha-pinned policy block, under proposed code ceilings (C-7).
- **Safety tests:** none weakened. The §4.7 list stays green, and new tests only add pins.

## 10. Self-score

| Axis | Score | Note |
|---|---|---|
| Fidelity | 18/20 | Every README and §10 item is covered and K1–K18 are dispositioned. Rests on 5 Rev 6 assumptions plus C-7. |
| Correctness | 17/20 | Code evidence re-checked at `4b8347a6`, including the in-node `is_fee_verified` (fee E6 is therefore verdict-based). New interface asks to AUT-2/AUT-5/AUT-6 are unconfirmed. |
| Specificity | 14/15 | Exact modules, rows, times, predicates, allocator and tests. |
| Acceptance | 17/20 | Scorer-runnable checks. The trigger leg is gate-proven only while `promote_enabled=false`, which is honest but weaker. |
| Autonomy-safety | 14/15 | No operator dependency; no venue freeze from rollback; position handoff; marker binding. K-1 stays an accepted cost. |
| Reuse | 9/10 | No new store or unit; resolver binding, exit gate, probe and fee verdict reused. |
| **Total** | **89/100** | r1 self-scored 90 and reviewers gave 81. r2 closes all 18 items, but adds cross-area interface dependencies, so the score is not raised. |

## 11. ARCH assumptions and contradictions (against Rev 5; Rev 6 pending)

Assumptions for the Rev 6 items (planner feedback P7-*):
- **C-1 (P7-1).** Assumed: Rev 6 exempts committed **roots** from "`live_orders_ruling` must be the policy ruling". A root resolves through its `_LIVE_ORDERS_ALLOWLIST` triple (G4), and the rule binds children only. E7 is one shared function, so if Rev 6 rules otherwise, only that function and fq_v1's committed bytes change (a reviewed commit), and E10 re-verifies the new bytes.
- **C-3 (P7-3).** Assumed: Rev 6 admits a CHAMPION→HALTED `HALT` with `decided_by=engine`, `cause_verdict_ids=[]` and the closed `cause_code` enum of §3.5.1. Its resume semantics are §3.5.2: a dedicated counter, and on exhaustion it **stays HALTED**, never INTEGRITY or RETIRE.
- **C-4 (P7-4).** Assumed: Rev 6 lets the pre-launch pass write MINT, DRILL_ADMIT, a →CHAMPION pair together with its ACTIVATE, and RESUME. It also lets the intraday mode write the drill marker under the active clause.
- **C-5 (P7-5).** Assumed: Rev 6 accepts that the drill child cites the committed artefact path byte-equal, or ARCH-0 materialises `derived/artefacts/<class>/9c0b6d6e…/artefact.json` at BOOTSTRAP. `density_artefact_path` is in the §4.2 allowlist, so either form is equal modulo the allowlist, and `compose_drill_child` takes the path from the store.
- **C-6 (P7-6).** Moot under r2: every widening row and every RESUME is written at 16:45 with the binding probe, and the 15:30 pass widens nothing.

New items raised by r2:
- **C-7 (new constants).** §4.5 needs `ROLLBACK_MIN_DWELL_H ≥ 24`, `ROLLBACK_TARGET_MAX_AGE_D ≤ 30` and `MAX_ENGINE_HALT_RESUMES_PER_VENUE_7D ≤ 3` as `pins.py` ceilings, plus `drill_min_drawdown_headroom_frac` in the drill clause.
- **C-8 (contradiction).** Rev 5 says an exhausted `RECOVERABLE_INFRA` budget ends in an INTEGRITY freeze (C5 cause classes). If Rev 6 classes engine rollback HALTs as INFRA, that contradicts the coordinator ruling that rollback failures never freeze the venue. Hence the dedicated semantics in C-3.
- **C-9 (contradiction).** Rev 5 §4.4 defines a horizon "for an intraday RESUME", but the intraday engine is restrictive-only (C5 latency, W1), so no intraday RESUME can exist. r2 writes every RESUME at 16:45 under the post-STOP horizon.
- **C-10.** C5 Pickup says composition "never re-reads", but `app/trade.py:788` → `calibration_artefact.py:250` re-reads by path (F-2).
- **C-11.** §4.4 has no position-ownership precondition. r2 adds the stricter AUT-7-local `position_handoff_ok` for ROLLBACK and DRILL_PROMOTE; ARCH should state it for PROMOTE as well.

## §R2 Disposition (review `reviews/AUT-7-r1-merged.md`)

**18 FIXED, 0 REJECTED.** The coordinator's INTEGRITY-deletion ruling is applied in §1, §3.5 and §3.5.2. The ARCH Rev 5 deltas are consumed: W2 (`DRILL` class: §3.3.1, §3.6.5, WP4), W3 (drill child only: §3.2, §3.6.5) and W5 (auto-clear: §3.6.5 D+2). Rev 6 assumptions are in §11.

| K | Disposition | Where |
|---|---|---|
| K1 position handoff | FIXED | §3.3.3 `position_handoff_ok` (flat, or same exit capability/kind/root via `exit_gate.py:55-58`), binding at 16:45 for ROLLBACK, DRILL_PROMOTE and the closing ROLLBACK; G-10; `test_position_handoff_owned_or_flat_else_refused`, `test_gate_drill_position_open_across_each_swap`; AUT-2 metric ask (§5) |
| K2 target eligibility | FIXED | §3.3.2 E4 fresh ATTEST, E5 age cap, E6 fee verified (via verdict, since `is_fee_verified` is in-node, `fee_drift_probe.py:292-299`), E7 current ruling, E8 no pending cause; the same function feeds `readiness()`; one RED test each (WP2) |
| K3 drill fills in risk | FIXED | §3.6.7; G-9 drawdown headroom; `test_gate_drill_fills_feed_risk_reconciliation_and_pnl`, ARCH W12 tests; bundle item 6 |
| K4 post-verify, load crash | FIXED | §3.5 R6 at 17:05 keyed to the boot-resolved sha; consumed AUT-5a boot-line format (§5) with the interim `app/trade.py:753-762` line; R7 plus F-2; `test_load_crash_after_resolve_halts_and_alerts_not_crash_loop` |
| K5 drill retry | FIXED | §3.6.5 Retry; 3-key child (`d0_climate_day` byte-equal, §3.6.4); `test_drill_retry_reuses_admitted_child_and_charges_no_second_admit` |
| K6 RESUME binding intent | FIXED | §3.1 mode table, §3.4 RESUME row, §3.6.5 D+2 16:45; `test_resume_written_only_in_prelaunch_with_binding_probe` |
| K7 marker and cause | FIXED | §3.6.5 marker binding (ERROR otherwise); DEMOTE carries `cause_code`; RESUME only on `DRILL_INJECT` (§3.5.2); trigger rule 3 removed (§3.3.1); real-fault path §3.6.6; tests in WP4 |
| K8 damping | FIXED | §3.3.4 `ROLLBACK_MIN_DWELL_H`, RESUME-over-ROLLBACK precedence, an exhausted-budget HALT never charged; `test_rollback_resume_ping_pong_damped`; C-7 |
| K9 deletion ruling | FIXED | §1, §3.5 (R2 lineage block, R4 no escalation), §3.5.2 resume rule; RESUME of F stays available (§3.3.4 step 2); `test_no_rollback_failure_ever_freezes_the_venue` |
| K10 drill start gate | FIXED | §3.6.3 G-6 fee verified, G-7 permit unexpired (read-only), G-8 binding intent probe at 16:45 |
| K11 journals | FIXED | §3.1 `rollback_journal.py`: `prev_sha256` + `chain_head`; journal heads in the export (§5); unique write-once readiness names (§3.6.2); WP2 tests; K-14 |
| K12 cadence | FIXED | §3.6.3 cadence from the last COMPLETED episode; failed episode limited only by the 30 d budget; §6 P90 recomputed: 12-23, 33 d margin |
| K13 statistical cost | FIXED | §3.6.7: ≈ 2 sessions ≈ 10 drill fills plus ≈ 1 vetoed session |
| K14 drill ROLLBACK via plan_rollback | FIXED | §3.3.4 Write (pair + ACTIVATE in one 16:45 transaction), §3.6.5 D+3; gate-proven-only statement (§3.3.4, §6, K-12) |
| K15 allocator | FIXED | §3.6.4 `next_drill_child_id`; `test_next_drill_child_id_monotone_never_reused_across_venues` |
| K16 immutability check | FIXED | §7 row 1: `.backup` to a scratch copy, UPDATE/DELETE on the copy, assert ABORT |
| K17 commits | FIXED | §6 item 5: empty, or allowed commits listed by sha with forbidden paths; `test_bundle_lists_window_commits_against_allowed_set` |
| K18 no new unit | FIXED | §3.7 unit deleted; bundle from the D+4 daily pass (§3.6.5, WP6); r1's nonexistent `tests/unit/test_systemd_units.py` reference dropped |
