# AUT-7 — Rollback (incl. AUT-7a gate drill, AUT-7b live promotion/rollback drill) — plan r3

## 0. Header

| Field | Value |
|---|---|
| ID | AUT-7 (sub-items AUT-7a gate drill, AUT-7b live drill) |
| Title | Rollback: immutable champion history, automated rollback, fail-closed failure, scheduled drills |
| Round | r3 (2026-10-03). Revises r2 (`AUT-7-rollback_plan_r2.md`, kept unchanged) against `reviews/AUT-7-r2-merged.md` (T1–T8) and the binding `reviews/ROLLBACK-FAILURE-decision.md`. §R3 lists the disposition of each item. |
| ARCH consumed | `AUTONOMY_ARCHITECTURE.md` **Rev 6**, sha256 `81c3c79fab2217af1e17714424c701d424552d9d73089d763c7cd73df67af04e` (byte-identical to `reviews/snapshots/ARCH_rev6.md`, re-hashed 2026-10-03). Code evidence re-checked at `4b8347a6` (codegraph: `exit_gate.py:55-67`, `trade_supervisor.py:402-420`, `fee_drift_probe.py:184,543-584`, `calibration_artefact.py:236-256`). |
| Binding decision consumed | `reviews/ROLLBACK-FAILURE-decision.md` (rollback failure never freezes the venue; `ROLLBACK_FAILED` class; target byte mismatch → target ineligible). It overrides the Rev 6 C5 text "class INTEGRITY on a byte mismatch" for rollback **targets**. |
| Current score | 2 (README: sha-pinned manifests make a rollback a manifest swap; there is no previous-champion pointer, no trigger and no drill) |
| Target | 3 |
| Upstream | ARCH-0 (C5 store, chain, fold, resolver, rollback journal, `pins.py`), AUT-5 (engine modes and `KIND_MASK`, policy ruling and drill clause, watch actor, supervisor boot signals I-5a.1–3), AUT-6 (`deliver_with_proof`, intraday producer, fee/permit/drawdown verdicts, `DRILL_INJECT`/`DRILL_INJECT_HALT` evaluation), AUT-1 (C1 `drill` flag writer), AUT-2 (C2 `excluded_reason=drill`, post-STOP `RECONCILIATION` with open positions by family) |
| Downstream | AUT-5 live proof (AUT-7b is its PROMOTE/DEMOTE/RESUME evidence), AUT-6 (DEMOTE **and HALT** action classes proven live, ARCH P6-4), AUT-4 (live n and the KILL clock exclude drill fills) |

This is a plan only; nothing in it is implemented. All times are UTC.

## 1. Goal state

**README score-3 criterion (verbatim):**
- The registry keeps an immutable champion history.
- An automated rollback to the last good champion fires on the AUT-5 or AUT-6 triggers and takes effect within one supervisor cycle, with no code change.
- A failed rollback fails closed by halting the family.
- Drills run on a schedule in the gate and live.

**Live proof (verbatim):** "tracked as AUT-7b, with its own clock of at least 4 trading days: one live rollback drill through the production path, restoring the prior champion and its byte-identical artefact sha, logged, alerted and reversed, with no human commit (ARCH §5.3). After the 2027-01-25 KILL, the state defined in ARCH §5.3 applies."

**ARCH Rev 6 §10 AUT-7 obligations (verbatim):** "rollback-target selection (most recent `rollback_eligible`, not `terminal_frozen`, bytes re-verified); failed rollback → HALT (P7-3); the advisory 15:30Z intent check (P7-6); the gate drill (AUT-7a); the live drill steps for AUT-7b — with `fq_v1` CHAMPION and not `demoted_for_cause` (W2), mint the byte-identical child `pm_us_crh_fq_v1_r0001` (C3 no-new-lineage), DRILL_ADMIT it, DRILL_PROMOTE at LAUNCH (`fq_v1` superseded and rollback-eligible, W3), write the drill marker so `DRILL_INJECT` demotes it through the live path, remove the marker so the verdict PASSes, RESUME (DRILL class), write the `DRILL_INJECT_HALT` marker so it HALTs, ROLLBACK to `fq_v1` (child DISPLACED; P6-4) — with dates, the drill budget, and the evidence (chain, export, node log, delivery records)."

**How "failed rollback → HALT" is read under the binding decision.**
- A failed rollback writes a C5 `HALT` row with `cause_code=rollback_failed` in the **non-freezing** class `ROLLBACK_FAILED`, on the family that still folds CHAMPION (Rev 6 C5 "Failed rollback"; decision ¶1). It halts that one family only, the engine retries daily, and a CRITICAL goes through `deliver_with_proof`.
- In production the outgoing family F is already HALTED by its own trigger cause, so a failed rollback normally writes **no** new row: F stays HALTED (entries vetoed, exits live). A `rollback_failed` row is written only when a family still folds CHAMPION: the newly effective target after a post-effect failure (R6, R7), or the drill child when its closing ROLLBACK fails while it is CHAMPION (§3.6.6).
- A byte mismatch on a rollback **target** makes that target ineligible (`rollback_eligible=false`, reason `target_integrity`) and sends a CRITICAL. The target was never loaded, so nothing is frozen (decision ¶2).
- A mismatch on the **effective champion's own** artefact at load is a genuine INTEGRITY event and keeps the existing freeze semantics (decision ¶2). AUT-7 does not soften it (§3.5, R7b).
- AUT-7 introduces **no** `cause_code` values. It uses `rollback_failed`, `DRILL_INJECT`, `DRILL_INJECT_HALT` and the trigger's own class (decision ¶3). The plan's r2 codes (`drill_step_failed`, `rollback_post_verify_failed`, `rollback_load_failed`, `rollback_target_corrupt`) and `MAX_ENGINE_HALT_RESUMES_PER_VENUE_7D` are deleted.

ARCH Rev 6 content consumed unchanged:
- C3 no-new-lineage (Y2) and the bootstrap root copy (P7-5): the resolver reads every family's artefact from `derived/artefacts/<model_class>/<sha>/artefact.json`, so a ROLLBACK to `fq_v1` restores the BOOTSTRAP-row sha even if the repo file changes.
- The C5 rows ROLLBACK (pre-launch, with its ACTIVATE in one transaction, P7-4), DRILL_ADMIT, DRILL_PROMOTE, SWAP_CANCEL, SUPERSEDE (W3: only the minted drill child is never made eligible), DISPLACED, RESUME (classes incl. `DRILL`, W2), HALT (incl. failed rollback, P7-3) and RETIRE.
- The root exemption (P7-1): `fq_v1` resolves under its own `_LIVE_ORDERS_ALLOWLIST` triple; the policy-ruling rule binds children only.
- C6 `DRILL_INJECT → DEMOTE` and `DRILL_INJECT_HALT → HALT`, both class `DRILL`, only under the drill clause (P6-4).
- §4.4: daily 15:30 intent check advisory, 16:45 and LAUNCH authoritative (P7-6); §5.2 "daily engine 15:30 (writes pending pairs)".
- §4.5: `MAX_ROLLBACKS_PER_VENUE_30D ≤ 2`, `DRILL_BUDGET_PER_VENUE_30D ≤ 1` drill (one DRILL_PROMOTE, one `DRILL_INJECT` DEMOTE and its DRILL RESUME, one `DRILL_INJECT_HALT`, one DRILL rollback), `RESUME_COOLDOWN_H ≥ 24`, the W1 ATTEST invariant, the Z3 counting rule.
- The node HWM, the W5 auto-clear of `registry_halted`, the C2 W12 invariant (drill fills feed risk) and the §5.3 drill contract.

## 2. L-1 null hypothesis and reuse

| New component | Capability checked first (file:line) | Verdict |
|---|---|---|
| Champion history | Nautilus has no artefact registry or champion state (ARCH §2 L-1). C5 `transitions` (ARCH-0) is append-only, hash-chained and trigger-protected. | **No new store or table.** History is a pure fold over the verified venue chain, never the `families`/`projection` caches (Y4). |
| Target byte verification | `load_family_manifest` hashes raw bytes once (`family_manifest.py:285-296`). `load_live_calibration` re-hashes via `Path(path).read_bytes()` (`calibration_artefact.py:250-256`), which follows symlinks and lives in the strategy layer. The resolver's byte binding (C5 Pickup Y6) reads from the C3 store (P7-5). | **Reuse the resolver's per-row byte binding** (consumed as `verify_family_bytes(row)`; AUT-5 r2 implements it inside `replay_full`), so the engine verifies a target with the exact code the supervisor runs at LAUNCH. No second verifier. |
| Fee-verified state | `FeeDriftProbeActor.is_fee_verified` (`fee_drift_probe.py:543-584`) is in-node memory, staleness `_FEE_VERIFIED_STALENESS_NS` = 4 h (`:184`). | The engine cannot call it. **Reuse AUT-6's fee-and-shape-drift `VERDICT`** (a required C6 class). AUT-7 adds no reader of its own (E6). |
| Open/AMBIGUOUS intent | `probe_open_intent` (`trade_supervisor.py:402-420`) asserts no live node (`:411`) and treats a corrupt singleton as OPEN (`:418-419`). | Reuse: **binding only in the 16:45 pass** (node down). The 15:30 pass uses AUT-5's advisory read through the G6 `mode=ro` URI (ARCH §4.4, P7-6). |
| Position handoff | `_EXIT_RULE_REGISTERED_FAMILIES = {"pm_us_crh_exit_v4"}` (`exit_gate.py:55`); `family_declares_exit_rule` requires both the id literal and a non-None `exit_rule` (`:58-67`), so a child id is never exit-capable. FQ has no exit (G17). | **Reuse `family_declares_exit_rule`** for the ownership predicate (§3.3.3). |
| Rollback write | The C5 ROLLBACK row and its partner through AUT-5's `RegistryStore.append(rows, *, expected_prior_seq, mode)` (AUT-5 r2 §3.2: one `BEGIN IMMEDIATE`, idempotent `transition_id`, per-mode `KIND_MASK`). | Reuse. AUT-7 adds a planner, not a writer. |
| Rollback/readiness journal | ARCH Rev 6 §5.1 puts the **rollback journal in ARCH-0** (Wave 0, with the C5 store). | **Reuse the ARCH-0 module** (`persistence/autonomy/rollback_journal.py`, name per ARCH-0). AUT-7 adds its record kinds and the export-head verification (T7) to that module after ARCH-0 merges; no second journal. |
| "Halt the family" | The exec-store `record_policy_halt` (`trial_day_latch.py:1155-1191`) needs the node flock (G6), blocks exits (G5) and is CLI-cleared. | **Rejected.** Use the registry HALT row (entry-only, exits live). |
| Launch-time pickup | `STOP 16:40`, `LAUNCH 16:50`, window closes 17:00 (`trade_supervisor_core.py:37-59`, G22); the AUT-5a resolver at LAUNCH. | Reuse. A rollback is only registry rows. |
| Post-effect verification | Today's boot line `fq_live_orders … calibration_sha256=<manifest pin>` (`app/trade.py:753-762`), emitted before the artefact load (`:778-797`). | Interim consumed line only; the binding interfaces are AUT-5a's resolved, composed and load-failed lines (I-5a.1, §5). |
| Drill child manifest | `deploy/families/pm_us_crh_fq_v1.json` (805 B; `d0_climate_day "2026-10-02"`; ruling `RULING_operator_fq_live_real_orders_2026-10-01`); artefact sha `9c0b6d6e…923a5e`. Both id regexes accept `<root>_r<NNNN>` (`settings.py:115`; `trial_day_latch.py:301`). | Reuse the root bytes; the child changes exactly 3 keys (§3.6.4). |
| DRILL_INJECT / DRILL_INJECT_HALT | Defined in C6 as two `VERDICT` detector ids over one marker. Nautilus has no fault-injection facility. | New and tiny: one detector class, parameterised by id, with marker binding (§3.6.5). |
| Node pickup of DEMOTE/HALT | `RegistryWatchActor` (AUT-5); W5 auto-clear. | Reuse. AUT-7 adds no node code. |
| Delivery proof | `deliver_with_proof` (AUT-6, §4.6). `emit_alert` swallows failures (G25). | Reuse for every AUT-7 CRITICAL and every drill event the bundle cites. |
| Drill evidence bundle | The AUT-5 daily engine pass at 15:30. | Emitted from that pass on D+4. No new unit. |

**F-1 (closed in ARCH).** The phantom containment base (G34) is fixed by the Rev 6 C5 four-site widening, owned by AUT-5. AUT-7 makes no edit to `family_manifest.py`.

**F-2 (still open in code; gates WP3, T8).** ARCH C5 Pickup says `_compose_family` consumes the resolver's bytes and never re-reads. Today FQ composition passes a **path** (`app/trade.py:788`) and `load_live_calibration` re-reads it (`calibration_artefact.py:250`). Until AUT-5a passes bytes (I-5a.3), the resolve→load TOCTOU window exists. WP3 does not activate before I-5a.1–3 are live (§4, §5).

## 3. Design

### 3.1 Modules

All AUT-7 logic is pure library code in `src/breezy/persistence/autonomy/`, inside the engine's import closure, so `ENGINE_SOURCE_SHA256` is re-pinned in the same commit (§4.3). AUT-5's engine phases (`src/breezy/analysis/autonomy_engine/`, AUT-5 r2 §3.3) call it; AUT-5's `autonomy_engine/drill.py` is the phase adapter and holds no drill logic of its own.

| File | Purpose | Key interfaces |
|---|---|---|
| `rollback.py` | Champion history, trigger, target eligibility, precedence, planner, failure classification, readiness. | `champion_history(chain, now_ns) -> tuple[ChampionEpoch, ...]`; `rollback_trigger(fold, chain, now_ns) -> RollbackTrigger \| None`; `target_eligibility(epoch, f_epoch, chain, evidence, now_ns) -> Eligibility` (E1–E10, each with a reason code); `select_rollback_target(history, chain, evidence, now_ns) -> TargetSelection`; `prelaunch_decision(fold, chain, evidence, now_ns) -> PrelaunchDecision`; `plan_rollback(trigger_or_drill, selection, ports) -> RollbackDecision`; `classify_failure(x) -> RollbackFailure`; `failed_rollback_halt(fold, failure) -> TransitionRow \| None`; `readiness(chain, evidence, ports) -> ReadinessRecord` |
| `drill.py` | AUT-7b sequencer (a state machine derived from the chain, never stored), child composer, allocator, marker writer/remover, episodes, bundle builder. | `drill_state(chain, journal, now_ns) -> DrillState`; `next_drill_child_id(chains, root) -> str`; `compose_drill_child(root_bytes, child_id, policy_ruling_id) -> bytes`; `drill_arm_gate(fold, chain, evidence, now_ns) -> GateResult` (15:30); `drill_start_gate(fold, chain, evidence, now_ns) -> GateResult` (16:45, G-1..G-11); `next_drill_step(state, clause, mode, now_ns, ports) -> DrillStep`; `drill_episodes(chain) -> tuple[DrillEpisode, ...]`; `is_drill_fill(episodes, family_id, ts_ns) -> bool`; `build_drill_bundle(episode, ports) -> DrillBundle` |
| `drill_inject.py` | The C6 `DRILL_INJECT` and `DRILL_INJECT_HALT` `VERDICT` detectors (one class, two ids). | `DrillMarkerDetector(detector_id).evaluate(marker_path, chain_view, clause, now_ns) -> DetectorOutcome` |
| `post_verify.py` | Post-effect verification against AUT-5a's boot lines. | `post_verify(launch_date, chain, boot_lines) -> PostVerifyResult`; `classify_boot_failure(lines) -> BootFailure \| None` |
| ARCH-0 `rollback_journal.py` (extended, not created) | Record kinds `rollback_decision/v1`, `readiness/v1`, `target_status/v1`, `drill_episode/v1`; verification against the newest export (T7). | `append_journal(kind, venue, record) -> JournalHead`; `verify_journal_chain(kind, venue, newest_export) -> JournalHead \| JournalUnverified` |

**Engine wiring.** AUT-5's phases call `rollback.step(mode, …)` and `drill.step(mode, …)`. AUT-7 edits no `app/trade.py`, `settings.py` or `trade_supervisor*.py` (ARCH §5.1). Writes go through `RegistryStore.append(..., mode=…)`. AUT-7 needs these kinds in AUT-5's per-mode `KIND_MASK` (§5):

| Mode | Kinds AUT-7 writes | Other AUT-7 effects |
|---|---|---|
| `daily` 15:30 (node up) | MINT, DRILL_ADMIT, the **pending** DRILL_PROMOTE + SUPERSEDE pair (`effective_launch_date` = today); RETIRE of a closed drill child | advisory intent check (P7-6); readiness; bundle on D+4 |
| `prelaunch` 16:45 (node down) | ACTIVATE or SWAP_CANCEL for a pending drill pair; ROLLBACK + SUPERSEDE/DISPLACED + ACTIVATE in **one** transaction (P7-4); RESUME | binding `probe_open_intent`; G-1..G-11; E1–E10 |
| `intraday` (every 5 min; restrictive-only, W1) | DEMOTE, HALT (incl. `rollback_failed`), SWAP_CANCEL | drill marker write and unlink; `post_verify` |

**Single decision per venue per 16:45 pass.** `prelaunch_decision` returns at most one widening action per venue (drill step, RESUME or ROLLBACK). This is structural damping (§3.3.4).

### 3.2 Immutable champion history (criterion 1)

`ChampionEpoch` is a frozen dataclass with explicit serialisation. Fields:
- `venue`, `family_id`, `lineage_root_family_id`, `manifest_sha256`, `artefact_sha256` (from the family's BOOTSTRAP/MINT row, Z1);
- `entered_venue_seq`, `entered_kind` (`BOOTSTRAP`\|`PROMOTE`\|`DRILL_PROMOTE`\|`ROLLBACK`\|`RESUME`), `effective_from_ns`;
- `left_venue_seq | None`, `left_kind` (`SUPERSEDE`\|`DEMOTE`\|`HALT`\|`DISPLACED`\|`RETIRE`\|None), `left_cause_class`, `left_cause_code`, `left_effective_ns | None`;
- `rollback_eligible`, `demoted_for_cause`, `drill_child` (the subject of a DRILL_ADMIT row, W3);
- `last_attest_ns | None` (the newest ATTEST row for this family while CHAMPION).

How the history is built and protected:
- **Derivation.** A pure fold over `transitions` from genesis, checked by the AUT-5 verifier (hash links and the newest-export prefix), using the `resolve_champion` fold rule (Y8): pending, lapsed and voided pairs create no epoch (Z3).
- **Derived flags, never cached.** SUPERSEDE sets `rollback_eligible` unless the subject is a drill child (W3); DEMOTE and HALT (any class, incl. `DRILL` and `ROLLBACK_FAILED`) clear it and set `demoted_for_cause`; DISPLACED never sets it; a SWAP_CANCEL carrying a cause on the incoming family sets `demoted_for_cause` (Y8).
- **Target-integrity status is not a chain flag.** The decision's `rollback_eligible=false, cause=target_integrity` has no C5 row kind (a SWAP_CANCEL cause would set the stronger `demoted_for_cause`, which the decision does not ask for). AUT-7 therefore holds it as a journal-derived input to `target_eligibility` (E10, §3.5), which every consumer (planner, readiness, drill) calls. Raised as N-4 (§11).
- **Immutability.** No new mutable state. History inherits the `BEFORE UPDATE/DELETE → RAISE(ABORT)` triggers, the per-venue chain, the 0444 export and the node HWM. The daily pass renders `evidence/registry/champion_history_<venue>_<ts_ns>.json` (0444, write-once) for humans only; a test pins it equal to the fold.

### 3.3 Automated rollback (criterion 2)

#### 3.3.1 Trigger (code-fixed literal; no new policy key)

`rollback_trigger` fires when all of these hold on the fold at `now`:
1. The venue's {CHAMPION, HALTED} slot holds family F in **HALTED**.
2. F's halting row is a DEMOTE or HALT whose cause class is `RECOVERABLE_MODEL` (policy `detector → class` map: live sequential, drawdown, forecast and calibration drift, fill rate, slippage).
3. No pending pair exists on the venue (Y8).

| Cause class on F | Why it never triggers a rollback |
|---|---|
| `RECOVERABLE_INFRA` | A feed, permit or unit fault hits every family alike. RESUME is the cure. |
| `DRILL` | The drill sequencer owns the RESUME and the closing ROLLBACK (§3.6). |
| `TERMINAL` | The lineage is `terminal_frozen`; the store refuses the ROLLBACK and the champion RETIREs (ARCH §5.3). |
| `INTEGRITY` | The venue is frozen for ROLLBACK by C5 (W15). A rollback never **creates** this freeze; it only respects one created by an exec-store cause or by a champion's own load mismatch (decision ¶2). |
| `ROLLBACK_FAILED` | F is a target that failed after effect. Its exit is the daily-retried rollback (§3.5.2); it never re-triggers itself. |

A genuine (non-`DRILL_INJECT*`) `RECOVERABLE_MODEL` fault on a drill child does fire the trigger; E9 then decides (§3.6.6).

#### 3.3.2 Target eligibility

`target_eligibility` walks `champion_history` backwards from F's epoch. The target is the **first** epoch whose family G passes every predicate. Each predicate has a reason code and its own RED test; `readiness()` calls the same function.

| # | Predicate | Source |
|---|---|---|
| E1 | G folds CHALLENGER, `rollback_eligible`, not `demoted_for_cause`, not a drill child | chain fold |
| E2 | G's lineage is not `terminal_frozen` | chain fold |
| E3 | `composition_kind` ∈ `LIVE_GATE_ROUTED_KINDS`; G is a root under `_LIVE_ORDERS_ALLOWLIST` (P7-1) or a child whose root is in `_LINEAGE_POLICY_ALLOWLIST` (`live_orders_gate.py:76-84`) | committed code |
| E4 | **Fresh ATTEST up to departure (W1-defined).** `last_attest_ns` is not None and `left_effective_ns − last_attest_ns ≤ ATTEST_PERIOD_H + L_max + ATTEST_MARGIN_H`, where `L_max` = `INTRADAY_ATTEST_VERDICT_PERIOD_MIN` + the 150 s engine offset, and all three terms are read from the same pinned ceilings and policy values the §4.5 W1 invariant uses. At the ceilings this is 6 + 1.04 + 0.5 = 7.54 h ≤ `ATTEST_VERDICT_VALIDITY_H`. **No literal 1.04 in code**; a test pins the bound to the W1 left-hand side. | chain; `pins.py`; policy block |
| E5 | **Age cap:** `now − left_effective_ns ≤ ROLLBACK_TARGET_MAX_AGE_D` (proposed ceiling ≤ 30 d, policy 30; still an ARCH ask, C-7) | chain |
| E6 | **Fee verified:** an accepted AUT-6 fee-drift `VERDICT` PASS produced after today's STOP, citing a node-log `outcome=AGREE` line within `_FEE_VERIFIED_STALENESS_NS` (4 h) of 16:40, that verified a `taker_fee_coefficient` equal to G's manifest value | C4 |
| E7 | **Current `live_orders_ruling`:** a root through its committed allowlist triple with the deploy copy's sha re-verified (`live_orders_gate.py:130-190`); a child names the current policy ruling. One function shared with the resolver. | committed code, ruling file |
| E8 | **No pending cause on G:** no accepted FAIL mapped to DEMOTE/HALT naming G after `left_effective_ns` that a later PASS has not superseded; no demand file naming G; no exec-store halt for G (engine mirror) | C4, demand dir, mirror |
| E9 | **No byte-identical remedy (T5).** If F's standing halting cause is any class other than `DRILL` (i.e. not `DRILL_INJECT`/`DRILL_INJECT_HALT`), G's `artefact_sha256` ≠ F's. Restoring the same model is no remedy for a genuine fault. | chain |
| E10 | **Bytes:** no open `target_status=target_integrity` record for G's `artefact_sha256`, and the resolver's per-row byte binding on G's BOOTSTRAP/MINT row passes now (single-read manifest and C3-store artefact, sha equality, child-id regex and root, §4.2 equality against the committed root, `O_NOFOLLOW`) | resolver; journal |

Rules applied to the result:
- **No fallback past an integrity failure.** If the first candidate fails E10, there is no rollback that pass (R2). Corrupt bytes may signal tampering, so the planner never walks on to older bytes.
- **Policy failures skip.** A candidate failing E1–E9 is skipped as ineligible.
- **Budget.** `MAX_ROLLBACKS_PER_VENUE_30D` (≤ 2), counted at effect, with pending pairs as reservations (Z3). Drill ROLLBACKs count only against the drill budget (Z3).
- **Journal verified.** No ROLLBACK is planned unless both journals verify against the newest export (§3.5.3, T7).

#### 3.3.3 Position handoff invariant

**Every open position held under the outgoing family id has an owner after the swap.** `position_handoff_ok(outgoing, incoming, recon)` holds iff either:
- (a) `recon.open_positions_by_family[outgoing] == ∅`, from the post-STOP `RECONCILIATION` verdict (16:41, ARCH §4.4); or
- (b) the incoming family owns them: `family_declares_exit_rule(incoming) == family_declares_exit_rule(outgoing)` (`exit_gate.py:58`), with the same `composition_kind` and `lineage_root_family_id`, so §4.2 makes `exit_rule` and `no_leg_exit` equal.

For FQ both sides are exit-incapable (G17): positions are held to settlement and reconciled venue-net per slug, so (b) holds, consistent with ARCH §4.4. An exit-capable outgoing family (only `pm_us_crh_exit_v4`) never hands off to a child, so the swap is refused while it holds positions. The check binds at 16:45 for every sender change (ROLLBACK, the drill pair's ACTIVATE, the closing drill ROLLBACK). A missing `open_positions_by_family` metric gives `INCONCLUSIVE`, and nothing is written. Successor re-entry stays blocked by `rung_net_position_held` (C5 Y16) and the kind-scoped latch (G28).

#### 3.3.4 Pre-launch decision, precedence and damping

`prelaunch_decision` runs once per venue in the 16:45 pass, after the post-STOP reconciliation, and returns **one** action:
1. **Drill step** due today (§3.6.5). The sequencer owns the slot; steps 2–3 are skipped. A genuine fault during an episode is handled in §3.6.6.
2. **RESUME of F** if F's cause class is admissible (`RECOVERABLE_MODEL`, `RECOVERABLE_INFRA`, or `DRILL` with `cause_code=DRILL_INJECT`), its cause verdict now PASSes, `RESUME_COOLDOWN_H` is met, the class budget is available, there is no pending pair and §4.4 passes. RESUME wins over ROLLBACK: it restores the same verified sender. RESUME of F stays available after any failed rollback.
3. **ROLLBACK** if `rollback_trigger` stands, a target passes §3.3.2, the budget is available, the journals verify and `position_handoff_ok` holds.
4. **Nothing.** The engine journals a reason code and sends a CRITICAL once per day per code (R1, R4).

**Damping (T6: `ROLLBACK_MIN_DWELL_H` deleted).** AUT-7 adds no dwell constant. Oscillation is bounded by ARCH's own ceilings and by structure:
- one widening decision per venue per 16:45 pass, so at most one sender change or RESUME per venue per day from AUT-7, under `MAX_SENDER_CHANGES_PER_VENUE_PER_DAY ≤ 2` (Z3);
- `MAX_ROLLBACKS_PER_VENUE_30D ≤ 2`, `RESUME_COOLDOWN_H ≥ 24`, `MAX_RECOVERABLE_RESUMES_PER_LINEAGE_14D ≤ 2`;
- DISPLACED never sets `rollback_eligible`, so two families cannot ping-pong by ROLLBACK;
- a ROLLBACK requires F HALTED by a new accepted cause, and a HALT never charges the rollback budget.
- **Drill closing and abort ROLLBACKs** are subject to no dwell. They count only against the drill budget (Z3), not against `MAX_SENDER_CHANGES_PER_VENUE_PER_DAY` or the production rollback budget, and they are still one decision per venue per 16:45 pass.

**Write.** When step 3 is chosen, one `RegistryStore.append(..., mode=PRELAUNCH)` transaction writes:
- the ROLLBACK row (G: CHALLENGER→CHAMPION, with `artefact_sha256`, `manifest_sha256`, `lineage_root_family_id`; Y6);
- its partner DISPLACED row (F: HALTED→CHALLENGER);
- the `ACTIVATE` row citing the pair.

All carry `effective_launch_date` = today and `cause_verdict_ids` = F's halting causes. §4.4 runs **before** the write, so a failing check writes nothing (R4). `transition_id`s are deterministic (Y9), so a crash-retry is a no-op.

**Effect within one supervisor cycle.** A qualifying DEMOTE committed before 16:45 on day D takes effect at D's 16:50 LAUNCH; one committed at or after 16:45 takes effect at D+1's LAUNCH. The worst case is ≤ 24 h 05 min (no dwell is added). Entries are already vetoed ≤ 15 min after the cause (C5 SLO), so the wait costs availability, never safety. **No code change:** the supervisor resolves the fold at LAUNCH (G2), and the rollback writes only under `~/.local/share/breezy/{registry,evidence}`.

**Gate-proven versus live-proven (stated plainly).** While `promote_enabled=false` (expected, ARCH §4.2 Y12), the only SUPERSEDE that ever makes a family `rollback_eligible` is a DRILL_PROMOTE. Outside a drill episode there is no eligible target, so the trigger→ROLLBACK chain **cannot fire live**; readiness reports `NO_TARGET` as INFO. The trigger leg is gate-proven (AUT-7a). AUT-7b proves live the same `plan_rollback` → write+ACTIVATE → resolver → node path, invoked by the sequencer.

### 3.4 Preconditions per mode

| Check | Daily 15:30 (node up) | Pre-launch 16:45 (node down) | Supervisor LAUNCH 16:50 |
|---|---|---|---|
| Rows AUT-7 writes | MINT, DRILL_ADMIT, pending drill pair; RETIRE | ACTIVATE/SWAP_CANCEL for the drill pair; ROLLBACK + partner + ACTIVATE; RESUME | — |
| Open/AMBIGUOUS intent | **advisory** read via the G6 `mode=ro` URI (corrupt = OPEN); OPEN → no drill pair written that day (P7-6) | **binding** `probe_open_intent` | binding re-check (§4.4) |
| `RECONCILIATION` PASS produced after today's STOP (W8), incl. `open_positions_by_family` | — | required | — |
| Position handoff (§3.3.3) | — | required for every sender change | — |
| Target eligibility E1–E10 | readiness only | required | resolver re-runs byte binding (Y6) |
| Drill gates | `drill_arm_gate` (G-1..G-4, G-9, G-11 advisory) | `drill_start_gate` G-1..G-11, binding | — |
| Budgets, lineage freeze, INTEGRITY freeze, journal verification | readiness reports them | required | resolver refusals |
| RESUME (incl. drill RESUME) | — | **only here** | — |

A pending drill pair is inert: it takes effect only with an ACTIVATE written at 16:45 after G-1..G-11 pass (C5 fold); otherwise it is SWAP_CANCELled or lapses, uncharged (Z3).

### 3.5 Failed rollback fails closed (criterion 3)

No rollback failure freezes the venue (decision ¶1–¶2). Reason codes below (`no_target`, `target_integrity`, …) are **journal and alert reason codes**, not C5 `cause_code` values; the only `cause_code` AUT-7 writes on a failure is `rollback_failed`.

| # | Failure | Detected by | Effect |
|---|---|---|---|
| R1 | No eligible target; rollback budget exhausted; journal unverified (§3.5.3); venue already INTEGRITY-frozen by another cause | `prelaunch_decision` | F already HALTED: **no row**, F stays HALTED (entries vetoed, exits live). If a family still folds CHAMPION (drill abort, §3.6.6): HALT it, `cause_code=rollback_failed`, class `ROLLBACK_FAILED` (Rev 6 P7-3). Journal `{trigger, decision, reason_code, attempt_n}`; CRITICAL `ROLLBACK_UNAVAILABLE` via `deliver_with_proof` once per day per reason. Retried at every 16:45 pass. No budget charged. |
| R2 | Target bytes fail E10 (sha, symlink, missing, strict-load, §4.2 inequality) | resolver byte binding | **Target ineligible** (decision ¶2): journal `target_status/v1 {artefact_sha256, status: target_integrity}`; CRITICAL `ROLLBACK_TARGET_INTEGRITY`. No pair, no older-candidate fallback that pass, F stays HALTED. **Nothing is frozen**; the target was never loaded. Clears automatically (L-48) after two consecutive daily readiness re-verifications ≥ 24 h apart pass on the same bytes (journal `status: cleared`). |
| R3 | CAS failure on the write | store | Non-restrictive: re-read, re-evaluate, retry once, then CRITICAL; retried next pass. A restrictive `rollback_failed` HALT retries until committed, with a demand file (Y19, Z11). |
| R4 | §4.4 fails at 16:45 (intent OPEN/AMBIGUOUS, reconciliation missing/INCONCLUSIVE/FAIL, handoff not owned) | `prelaunch_decision` | **Nothing written**: the checks precede the write. F stays HALTED and boots entries-vetoed (Z7). CRITICAL `ROLLBACK_DEFERRED`. Retried daily. `consecutive_deferred` is journaled and never escalates. In the drill-abort case where the child folds CHAMPION, R1's HALT rule applies. |
| R5 | Resolver refuses at LAUNCH after ACTIVATE (byte drift 16:45→16:50, chain or HWM fault) | supervisor resolver | C5 path: `REGISTRY_UNAVAILABLE`; the intraday pass writes `SWAP_CANCEL` in [16:50, 17:00) (Z8) as an engine-detected inconsistency, with **no** `cause_verdict_ids` on G, so G does not get `demoted_for_cause`. The fold restores F (HALTED) and the supervisor relaunches it entries-vetoed. Byte drift additionally opens `target_integrity` on G (R2 semantics). A chain or HWM fault is AUT-5's venue-wide path. |
| R6 | Post-effect mismatch: the boot line for the effective LAUNCH names a different `family_id`, `registry_seq`, `manifest_sha256` or `artefact_sha256` than the authorising row; or no composed line by 17:30 | `post_verify` in the intraday passes from 17:05 | After 17:00 an effective pair is never voided (Z8). Mismatch: HALT G at once, `cause_code=rollback_failed`, class `ROLLBACK_FAILED`. Missing line: re-checked each intraday pass, HALT at the first pass ≥ 17:30 if still absent. CRITICAL `ROLLBACK_FAILED`. No venue freeze. |
| R7a | **Load failure on verified bytes** after the resolver passed (strict-load, plug-in refusal), signalled by I-5a.1 `registry_boot_load_failed … reason≠sha_mismatch` | `classify_boot_failure` | The supervisor does not relaunch that resolved family before the next LAUNCH and triggers the intraday pass (I-5a.2). In [16:50, 17:00): `SWAP_CANCEL` (no cause on G) restores F, HALTED. From 17:00: HALT G, `rollback_failed`, `ROLLBACK_FAILED`. Journal `target_status {status: target_load_failed, engine_code_sha}`: G is ineligible until the engine pin rotates (the reviewed build-side fix path). CRITICAL `ROLLBACK_FAILED`. No crash loop. |
| R7b | **Champion's own artefact mismatch at load** (`registry_boot_load_failed … reason=sha_mismatch`) | `classify_boot_failure` | Decision ¶2: a genuine INTEGRITY event with the existing freeze semantics. The engine writes HALT on the effective champion with `cause_code=rollback_failed`, class `INTEGRITY` (the Rev 6 C5 byte-mismatch text, retained by the decision for the champion's own bytes). With I-5a.3 live (bytes passed to composition) this needs tampering after the resolver read; it is gate-proven only. |

**Every failure ends with no family sending new entries on an unverified path.** Nothing falls back to an older or unverified family, and only R7b (the champion's own bytes) freezes. The journal records `{trigger, target, decision, reason_code, attempt_n, chain_head, prev_sha256}`.

#### 3.5.1 Engine HALT rows written by AUT-7

One shape only: `kind=HALT`, CHAMPION→HALTED, `decided_by=engine`, `cause_verdict_ids=[]`, `cause_code=rollback_failed`, class `ROLLBACK_FAILED` (R1-drill, R6, R7a) or `INTEGRITY` (R7b only). Restrictive, always permitted, never counted. The intraday mode writes it (W1). AUT-7 writes no other engine `cause_code`. DRILL-class DEMOTE/HALT rows come from the C6 detectors through the normal verdict path, not from AUT-7 directly.

#### 3.5.2 Exit path for a `ROLLBACK_FAILED` family

`ROLLBACK_FAILED` is outside the C5 RESUME set {RECOVERABLE_MODEL, RECOVERABLE_INFRA, DRILL}, so the family **never RESUMEs**. Its exit is the daily-retried rollback: each 16:45 pass runs `select_rollback_target` with that family as F. In production the previous champion was DISPLACED (never eligible), so normally no target exists and the family **stays HALTED** with a daily CRITICAL until an eligible champion exists (a new reviewed root, or a future eligible target). That is fail-safe: entries stopped, exits live, no freeze, no RETIRE, no `terminal_frozen`. The drill child's exit is its closing ROLLBACK with a DISPLACED partner (§3.6.6). Raised for Rev 7 as N-1 (§11).

#### 3.5.3 Journal verification against the newest export (T7)

`verify_journal_chain(kind, venue, newest_export)` runs for both kinds (`rollback_decision`, `readiness`) at the start of every 16:45 pass and every daily readiness run:
1. Select the newest export: highest `export_seq` for the venue (an HWM_RESET export supersedes, W4); single-read, `O_NOFOLLOW`.
2. Read `evidence_journal_heads.{rollback,readiness}` from it (AUT-5 export widening, §5).
3. Walk the journal from genesis by `prev_sha256`; every link must hold.
4. The export's head must be a record on that chain (**mismatch** otherwise), and the journal must extend at or beyond it, with every record after it linking (**missing tail** otherwise: records at or after the exported head were removed).

On any failure (`link_broken`, `export_head_absent`, `tail_missing`, `export_unreadable`): every ROLLBACK (production and drill) is refused as R1 with reason `journal_unverified`, the drill start gate fails G-11, and CRITICAL `ROLLBACK_JOURNAL_UNVERIFIED` is sent once per day. Restrictive writes and RESUME are never blocked, so the block cannot deadlock its own recovery (L-48). It clears automatically when verification passes again (journal files restored); otherwise build-side incident handling. Records written after the newest export (≤ 24 h) can only be checked for linkage. That is the stated residual.

### 3.6 Drills (criterion 4)

#### 3.6.1 AUT-7a — gate drill

`tests/integration/autonomy/test_rollback_drill_gate.py` runs the whole §3.6.5 sequence (incl. HALT), the R1–R7 matrix, the position-across-swap cases, the retry, the budget-strand case and the genuine-fault path in-process, in **every** gate run (`scripts/ci/run_tests_no_egress.sh`; L-43). It uses:
- a fake clock and a tmp `HOME` registry;
- a tmp exec store written through the real writer path (L-42);
- the real AUT-5 store, resolver, fold and engine modes;
- the real `DrillMarkerDetector` (both ids), intraday producer and `RegistryWatchActor.tick_once`.

Supervisor LAUNCH is a port that calls the real resolver; the test also runs the production default port once (L-55).

#### 3.6.2 Production readiness

Every daily pass, `rollback.readiness()` runs `target_eligibility` (E1–E10) for the current champion's would-be target, without writing a row, and appends a `readiness/v1` record to the ARCH-0 journal (write-once, `os.link` from a `mkstemp` file, failing if the name exists; L-50). It reports the per-predicate reason codes, open `target_status` records, the budgets and the journal-verification result. A present target failing E10 sends CRITICAL `ROLLBACK_TARGET_INTEGRITY`. `NO_TARGET` is INFO while `promote_enabled=false` outside a drill.

#### 3.6.3 AUT-7b schedule and gates

**Drill clause values** (AUT-5 owns the block; proposed within ceilings):
- `drill_cadence_days: 60`, measured from the last COMPLETED episode's closing ROLLBACK.
- `drill_first_eligible_date` (≥ AUT-5b activation + 3 sessions of soak, §6).
- `drill_inject_utc: "15:00"` (D+1), `drill_demote_slo_min: 15`; `drill_halt_utc: "15:00"` (D+3), `drill_halt_slo_min: 15`.
- `drill_max_episode_days: 6`; `drill_min_drawdown_headroom_frac: 0.5`; RETIRE reason `drill_episode_closed`.

**Arm gate (`drill_arm_gate`, D 15:30, advisory).** G-1..G-4, G-9 and G-11 as below, plus the advisory intent read. Pass → write the pending rows (§3.6.5). Fail → write nothing that day; journal the reason.

**Start gate (`drill_start_gate`, D 16:45, binding).** Pass → ACTIVATE; fail → SWAP_CANCEL. Each item has its own RED test.

| # | Condition | Source |
|---|---|---|
| G-1 | The incumbent folds CHAMPION, not `demoted_for_cause` (W2), and is **not a drill child**; no pending pair other than the drill pair; lineage not `terminal_frozen`; no INTEGRITY freeze | chain |
| G-2 | **Budget without stranding (T4):** drill budget unspent in the trailing 30 d, cadence met, **and** the D 15:30 arm instant ≥ `ts_ns` of the newest charged drill row + 27 d. The newest charged row of a closed episode is its closing ROLLBACK (16:50), so D ≥ that date + 28, and every row of the new episode (latest: its ROLLBACK at D+3 16:50) falls ≥ 30 d after the same-kind row before it. | chain |
| G-3 | ≥ 1 ATTEST for the incumbent within `ATTEST_VERDICT_VALIDITY_H` (Z5) | chain |
| G-4 | AUT-6 canary `delivered=true` within `ALERT_CANARY_MAX_AGE_H` | delivery records |
| G-5 | `RECONCILIATION` PASS produced after today's STOP | C4 |
| G-6 | Fee verified (E6 on the incumbent) | C4 |
| G-7 | **Permit unexpired:** an AUT-6 permit-liveness `HEALTH` PASS from the last intraday producer run before STOP, and no `permit_lapsed` C1 `EntryVeto` after it. Read-only. | C4, C1 |
| G-8 | No OPEN or AMBIGUOUS intent: `probe_open_intent`, binding, node down | exec store |
| G-9 | Drawdown headroom: newest accepted drawdown verdict's `metrics.drawdown_used_frac ≤ 1 − drill_min_drawdown_headroom_frac`, drill fills included | C4 (AUT-5 r2 `live.drawdown`) |
| G-10 | `position_handoff_ok(incumbent, child)` | C4 (AUT-2) |
| G-11 | Both journals verify against the newest export (§3.5.3) | journal, export |

**Why option (b) of T4 and not a budget-exempt ROLLBACK.** Exempting the closing ROLLBACK from the budget would change the §4.5 contract (a ROLLBACK row requires its budget). G-2 keeps the contract and makes stranding impossible by construction: an episode starts only when every one of its rows already fits the window.

#### 3.6.4 Child manifest and allocator

`compose_drill_child` emits the root's exact JSON with **only three keys** changed: `family_id = <root>_r<NNNN>`; `trial_id_prefix = forecast_quantile_ladder/trial/<root>_r<NNNN>/`; `live_orders_ruling` = the policy ruling id. `d0_climate_day`, `density_artefact_path`, `density_artefact_sha256` and every size, price, station, θ and exit key stay byte-equal (§4.2). The MINT row cites the existing C3 directory for sha `9c0b6d6e…` (Y2, P7-5); the resolver reads the artefact from the C3 store by sha, so the path key is informational. The child is written 0444 to `registry/families/<child>.json` through AUT-5's child-write API.

**Allocator (`next_drill_child_id`).** `NNNN = 1 + max` over every BOOTSTRAP/MINT `family_id` matching `^<root>_r(\d{4})$` in **all** venue chains (lineage counters are venue-independent), starting at 1. A number is never reused (RETIRED, lapsed or voided). `NNNN > 9999` refuses with a CRITICAL. The id must match both regexes. The function is chain-pure, so a crash-retry yields the same id and MINT `transition_id`. If AUT-5's store exposes a shared `<root>_r<NNNN>` allocator, AUT-7 calls it instead.

#### 3.6.5 Drill sequence for D = the first eligible day

Every row is engine-written (`decided_by=engine`) and charged only to the drill budget at effect (Z3). DEMOTE and HALT rows are restrictive and never refused; their drill-budget items are enforced where the injection starts, at the **marker writer** (N-2, §11).

| When | Mode | Row(s) / action | Proof artefact |
|---|---|---|---|
| D 15:30 | daily | advisory intent read; `drill_arm_gate`; then **one transaction**: `MINT` r0001 ∅→SHADOW (no C3 record, no counter; Y2); `DRILL_ADMIT` →CHALLENGER; `DRILL_PROMOTE` r0001→CHAMPION + `SUPERSEDE` fq_v1→CHALLENGER (`rollback_eligible=true`, W3), both `effective_launch_date=D` (pending) | chain; journal; `DRILL_ARMED` delivered |
| D 16:41 | post-STOP producer (AUT-2) | `RECONCILIATION` incl. `open_positions_by_family` | verdict |
| D 16:45 | prelaunch | `drill_start_gate` G-1..G-11 → `ACTIVATE` (pass) or `SWAP_CANCEL` (fail, no cause on r0001) | chain; `DRILL_STARTED` delivered |
| D 16:50 | supervisor | resolves r0001; node boots it; **episode opens** (C1 `drill=true`) | I-5a.1 resolved and composed lines, `family_id=pm_us_crh_fq_v1_r0001 … artefact_sha256=9c0b6d6e…` |
| D 17:05 | intraday | `post_verify` (R6/R7) | journal `POST_VERIFY_OK`; delivered |
| D+1 15:00 | intraday | marker `detector=DRILL_INJECT`, `step=demote` (schema below); drill-DEMOTE budget checked here | marker sha in journal |
| ≤ D+1 15:05 | producer (AUT-6) | `DRILL_INJECT` FAIL only if the marker binds → C4 `HEALTH` FAIL, action DEMOTE, class `DRILL` | verdict |
| ≤ D+1 15:08 | intraday | `DEMOTE` r0001 CHAMPION→HALTED, `cause_code=DRILL_INJECT`; unlink the marker | chain; `DRILL_DEMOTED` delivered |
| ≤ D+1 15:09 | watch actor | `entry_veto=registry_halted`; exits live | C1 `EntryVeto`; node log |
| D+1 15:10 | producer | marker absent → `DRILL_INJECT` PASS (Z2) | verdict |
| D+1 16:50 | supervisor | HALTED r0001 boots entries-vetoed (Z7) | node log |
| D+2 16:45 | prelaunch | `RESUME` HALTED→CHAMPION, class `DRILL`, `cause_code=DRILL_INJECT` (cooldown ≥ 24 h since ≈ D+1 15:08; binding probe; §4.4) | chain; `DRILL_RESUMED` delivered |
| D+2 16:50 / 17:05 | supervisor / intraday | r0001 boots unvetoed (W5 clear on first tick); `post_verify` | node log; journal |
| D+3 15:00 | intraday | marker `detector=DRILL_INJECT_HALT`, `step=halt`; drill-HALT budget checked here | marker sha in journal |
| ≤ D+3 15:05 | producer (AUT-6) | `DRILL_INJECT_HALT` FAIL only if the marker binds → action HALT, class `DRILL` | verdict |
| ≤ D+3 15:08 | intraday | `HALT` r0001 CHAMPION→HALTED, `cause_code=DRILL_INJECT_HALT`; never writes the exec store, never `terminal_frozen`, never an INTEGRITY freeze (C6 P6-4); unlink the marker | chain; `DRILL_HALTED` delivered |
| ≤ D+3 15:09 / 15:10 | watch actor / producer | `registry_halted` veto; `DRILL_INJECT_HALT` PASS | C1 `EntryVeto`; verdict |
| D+3 16:45 | prelaunch | `plan_rollback` (drill-invoked): E1–E10 on fq_v1 (E9 passes: r0001's standing cause is class `DRILL`), handoff, journals, then **one transaction** `ROLLBACK` fq_v1 CHALLENGER→CHAMPION (sha `9c0b6d6e…` re-verified from the C3 store) + `DISPLACED` r0001 HALTED→CHALLENGER (never eligible) + `ACTIVATE`, `effective_launch_date=D+3` (P7-4) | chain; `DRILL_ROLLBACK` delivered |
| D+3 16:50 / 17:05 | supervisor / intraday | node boots fq_v1; **episode closes**; `post_verify` (R6) | resolved line `family_id=pm_us_crh_fq_v1 artefact_sha256=9c0b6d6e…`; `POST_VERIFY_OK` delivered |
| D+4 15:30 | daily | `RETIRE` r0001 CHALLENGER→RETIRED (`drill_episode_closed`); then the evidence bundle (§6) | chain; export `registry_polymarket_us_<D+4>.jsonl`; `evidence/drills/drill_polymarket_us_<episode_id>.json`; `DRILL_CLOSED` delivered |

**Marker schema `drill_marker/v1` (exact-set; T1).** `{schema, registry_root, venue, episode_id, child_id, detector, step, window_start_ns, window_end_ns, abort_record_sha256, drill_clause_sha256, ts_ns}`.
- `detector` ∈ {`DRILL_INJECT`, `DRILL_INJECT_HALT`}; `step` ∈ {`demote`, `halt`, `abort_halt`}. `demote` pairs only with `DRILL_INJECT`; `halt` and `abort_halt` only with `DRILL_INJECT_HALT`.
- Windows per step: `demote` = [D+1 `drill_inject_utc`, + `drill_demote_slo_min`]; `halt` = [D+3 `drill_halt_utc`, + `drill_halt_slo_min`]; `abort_halt` = [abort decision `ts_ns`, + `drill_halt_slo_min`], with `abort_record_sha256` naming the journaled abort decision (null otherwise).
- `registry_root` keeps AUT-5's M20 root-keying (a shadow detector never trips on the production marker).

**Marker binding.** `DrillMarkerDetector(id)` single-reads the marker (`O_NOFOLLOW`, ≤ 4096 B, exact-set) and returns:
- **PASS** when the marker is absent, or present with `detector` ≠ its own id (the other detector's marker);
- **FAIL** only when `detector` = its id and all of these hold: `episode_id` equals the chain-derived open episode; `child_id` equals the fold's CHAMPION and that family is the episode's drill child; `drill_clause_sha256` equals the active block's; `step` matches the sequencer's due step (or a journaled abort); `ts_ns` and the evaluation `now_ns` both lie in [`window_start_ns`, `window_end_ns`]; `registry_root` equals its own root;
- **ERROR** (never FAIL, never PASS) and a CRITICAL on any other case: a binding mismatch, a window passed with the marker still present, a symlink, oversize, or a parse failure. Outside the drill clause the engine treats either verdict as ERROR (C6).

**Retry restated on the 15:30/16:45 split (K5 → T2).**
- **Pre-arm failure** (15:30 gate fails or the engine is down): nothing written; retried at the next day's 15:30.
- **16:45 failure** (any G-check, or a crash before ACTIVATE): `SWAP_CANCEL` with no cause, or the pair lapses at LAUNCH. Neither is charged (Z3). r0001 stays CHALLENGER (MINT and DRILL_ADMIT stand, ADMIT already charged). The next eligible **15:30** pass reuses r0001 and writes only a new `DRILL_PROMOTE` + `SUPERSEDE` pair (new `family_prior_seq`, so a new `transition_id`); the next 16:45 pass ACTIVATEs or cancels it. No second MINT, no second DRILL_ADMIT.
- **Post-launch SWAP_CANCEL** in [16:50, 17:00) (R5/R7a on r0001): same as a 16:45 failure.
- If r0001 carries `demoted_for_cause` (a cause on the incoming family, Y8), it is RETIREd (policy) at the next daily pass and the next eligible arm allocates r0002.

#### 3.6.6 Abort and genuine-fault paths

**Abort (a drill step fails; no genuine cause on the child).** Triggers: no DEMOTE or HALT within its marker window; RESUME refused at D+2; a `post_verify` mismatch after the DRILL_PROMOTE or RESUME effect; or the episode passing `drill_max_episode_days`. The sequencer journals an abort decision, sends CRITICAL `DRILL_ABORTED`, stops further injections and closes:
1. If r0001 folds CHAMPION and the episode's drill-HALT is unspent, the intraday pass writes an `abort_halt` marker (`DRILL_INJECT_HALT`), so r0001 is HALTED through the live path within `drill_halt_slo_min`. A post-verify mismatch always takes this step first.
2. At the next 16:45 pass whose preconditions hold, the **closing ROLLBACK** to fq_v1: partner `DISPLACED` if r0001 is HALTED, `SUPERSEDE` if it is still CHAMPION (never eligible, W3). E9 passes: r0001 carries no standing cause other than class `DRILL`. Then RETIRE r0001 at the next daily pass.
3. If that ROLLBACK fails (R1–R5) while r0001 folds CHAMPION, the Rev 6 P7-3 rule applies: HALT r0001, `rollback_failed`, `ROLLBACK_FAILED` (§3.5.1). The venue then has no new-entry sender; the closing ROLLBACK retries daily with a DISPLACED partner. No INTEGRITY freeze.

Because G-2 admitted the episode only when every row fits the 30-day window, the closing ROLLBACK is never refused by the drill budget. An aborted episode is a failed episode: its closing ROLLBACK is the newest charged row for the next G-2.

**Genuine fault on r0001 (T5).** Any accepted DEMOTE or HALT on r0001 whose cause is **not** `DRILL_INJECT`/`DRILL_INJECT_HALT`, including a SWAP_CANCEL + HALT on the outgoing side (Y8), or an exec-store mirror:
1. **The episode is abandoned.** The sequencer writes no further drill step and appends `drill_episode/v1 {episode_id, status: abandoned, cause_transition_id}` to the journal. CRITICAL `DRILL_ABANDONED`.
2. **Never ROLLBACK to a target with the same `artefact_sha256` while that cause stands** (E9). fq_v1 is byte-identical, so it is excluded: no drill closing ROLLBACK and no production ROLLBACK to it.
3. **r0001 stays HALTED under production rules.** It may RESUME only under its own cause class, charging that class's **production** budget (`MAX_RECOVERABLE_RESUMES_PER_LINEAGE_14D` or `MAX_INFRA_RESUMES_PER_VENUE_7D`), never the drill budget. A `RECOVERABLE_MODEL` trigger may roll back only to a non-identical eligible target, charged to the production rollback budget. A TERMINAL cause, or an exhausted model budget, RETIREs r0001 and sets `terminal_frozen` on the fq_v1 lineage (ARCH Y10); only a reviewed new root recovers.
4. **What sends next.** In order: (a) r0001, after a production RESUME of its own cause; (b) a non-identical eligible target, through a production ROLLBACK (none exists today while `promote_enabled=false`); (c) otherwise **no sender on the venue** until an eligible champion exists. That is fail-safe (entries stopped, exits live, no freeze), and CRITICAL `DRILL_ABANDONED_NO_SENDER` is sent daily through `deliver_with_proof`.
5. **Abandoned-episode close.** RETIRE is not open to a HALTED family with a recoverable cause (C5: HALTED→RETIRED only on TERMINAL or an exhausted model budget), so the close is the journal record in step 1 plus, if r0001 later RESUMEs and folds CHAMPION with **no standing cause**, a **deferred restorative close**: at a later 16:45 pass (≥ 1 LAUNCH after that RESUME), the closing ROLLBACK to fq_v1 with a `SUPERSEDE` partner, charged to the episode's drill rollback, then RETIRE r0001. This restores the root identity and unblocks future drills (G-1 excludes a drill-child incumbent). It runs only if fq_v1 still passes E1–E10 (E5 age cap included); otherwise r0001 remains the champion and drills stay blocked (risk K-15).

Drill fills follow ARCH §5.3 unchanged: `drill=true` from DRILL_PROMOTE through the closing ROLLBACK, including an abandoned episode's production period. That is conservative: it only removes fills from n and the KILL clock, never from risk.

#### 3.6.7 Drill fills, budget and costs

`drill_episodes()` returns `[DRILL_PROMOTE effective_ns, closing ROLLBACK effective_ns)` per child (open-ended while unclosed). `is_drill_fill` is true for any fill inside an interval, or of a drill-child family id. Consumers: AUT-1 stamps C1 `drill=true`; AUT-2 re-derives `excluded_reason=drill`, `admissible=false`; AUT-4's live sequential and the KILL clock exclude them.

**Drill fills stay in risk (W12).** They are real money: they count in every DRIFT/HEALTH detector, the drawdown limit (AUT-5 r2 `live.drawdown` includes `excluded_reason=drill`), venue-net reconciliation, realised P&L, portfolio ROI and the venue daily budget (Z18, G21). Only n and the KILL clock exclude them. Tests: ARCH-named `test_detectors_and_drawdown_include_drill_fills`, `test_drill_fills_spend_venue_budget`; AUT-7's `test_gate_drill_fills_feed_risk_reconciliation_and_pnl`.

**Drill budget per 30 d per venue (§4.5, T1).**

| Item | Row | Charged | Enforced at |
|---|---|---|---|
| 1 DRILL_ADMIT | `DRILL_ADMIT` (D 15:30) | at effect (now) | store (`drill_admits`) |
| 1 DRILL_PROMOTE | `DRILL_PROMOTE` pair (D 16:50) | at effect (LAUNCH) | store (`drill_promotes`) |
| 1 `DRILL_INJECT` DEMOTE | `DEMOTE` (≈ D+1 15:08) | at marker write | marker writer (restrictive rows are never capped) |
| 1 DRILL RESUME | `RESUME` (D+2 16:45) | at effect | store (`drill_resumes`) |
| 1 `DRILL_INJECT_HALT` | `HALT` (≈ D+3 15:08) | at marker write (incl. `abort_halt`) | marker writer |
| 1 DRILL rollback | `ROLLBACK` pair (D+3 16:50) | at effect | store (`drill_rollbacks`), never refused by construction (G-2) |

A lapsed or cancelled pair is never charged. A rollback during an abandoned episode to a non-identical target is charged to the **production** budget.

**Statistical cost.**
- Drill fills: session D (D 16:50 → D+1 15:08) and session D+2 (D+2 16:50 → D+3 15:08), about **2 sessions ≈ 10 fills** at about 5 fills a day.
- Vetoed: D+1 15:08 → D+2 16:50 (≈ 1 session) plus D+3 15:08 → 16:40, about **1.1 sessions ≈ 5–6 fills of opportunity**.
- No extra money at risk: the byte-identical child trades inside the same caps.

### 3.7 Units

No new unit. Everything runs inside AUT-5's `breezy-autonomy-engine@{daily,intraday,prelaunch}` under `registry/engine.lock` and within the engine's memory cap (own-lock autonomy units ≤ 4G in total, §5.2). The bundle is emitted by the D+4 daily pass.

## 4. Work packages

Gate commands for every WP:
- `scripts/ci/run_tests_no_egress.sh <focused paths>`, then the full `scripts/ci/run_tests_no_egress.sh`, reading EXIT before any push;
- `cd <tree root> && lint-imports`, which must print "N kept, 0 broken" (the console script, never `python -m importlinter`);
- the mypy ratchet `tests/unit/test_mypy_ratchet.py`.

Worktrees export `PYTHONPATH=<worktree>/src` and use the exact interpreter. Never `uv`, `pip` or `git stash`. Each WP is RED-first, and its commit message carries the RED and GREEN output. Every WP that touches the engine closure re-pins `ENGINE_SOURCE_SHA256` in the same commit (`test_code_identity_pins_cover_import_closure`).

### AUT-7.WP1 — champion history (Wave 1, against ARCH-0 stubs)
- **Files:** `src/breezy/persistence/autonomy/rollback.py`; `tests/unit/autonomy/test_rollback_champion_history.py`.
- **RED first:**
  - `::test_history_is_a_pure_fold_of_the_verified_chain`
  - `::test_history_never_reads_projection_or_families_cache`
  - `::test_history_refuses_unverified_or_export_divergent_chain`
  - `::test_pending_lapsed_and_voided_pairs_create_no_epoch`
  - `::test_drill_promote_supersede_makes_incumbent_rollback_eligible` (W3)
  - `::test_drill_child_is_never_rollback_eligible`
  - `::test_demote_halt_any_class_clears_and_displaced_never_sets_rollback_eligible` (incl. `DRILL` and `ROLLBACK_FAILED`)
  - `::test_swap_cancel_with_incoming_cause_sets_demoted_for_cause`
  - `::test_last_attest_left_effective_and_left_cause_derived`
  - `::test_every_champion_epoch_appears_in_history` (parametrized over `_COMPOSITION_KINDS`)
  - `::test_history_render_equals_fold_and_is_write_once`
- **GREEN:** all pass, plus `test_rollback_module_has_no_family_literals` (AST).
- **Activation:** a pure library, live when the engine imports it (WP3).

### AUT-7.WP2 — trigger, eligibility, precedence, journal verification (Wave 1; journal part after ARCH-0 merges)
- **Files:** `rollback.py`; the ARCH-0 `rollback_journal.py` (record kinds and `verify_journal_chain` only); `tests/unit/autonomy/test_rollback_planner.py`, `test_rollback_eligibility.py`, `test_rollback_journal.py`.
- **RED first, trigger and precedence:**
  - `::test_trigger_fires_on_recoverable_model_demote_of_champion`
  - `::test_trigger_silent_for_infra_drill_terminal_integrity_and_rollback_failed`
  - `::test_trigger_fires_for_genuine_model_fault_on_drill_child`
  - `::test_trigger_refused_while_pair_pending`
  - `::test_resume_preferred_over_rollback_when_admissible`
  - `::test_resume_of_halted_f_stays_available_after_failed_rollback`
  - `::test_at_most_one_widening_decision_per_venue_per_prelaunch_pass` (T6)
  - `::test_rollback_resume_ping_pong_damped_by_z3_ceilings` (alternating FAIL/PASS on F and G over 30 d, no dwell constant: ≤ 1 widening per pass, ≤ 2 rollbacks, then F HALTED)
  - `::test_no_dwell_constant_in_rollback_module` (AST: no `ROLLBACK_MIN_DWELL_H`; T6)
  - `::test_drill_rollbacks_count_only_against_drill_budget` (Z3)
  - `::test_budget_exhausted_halt_charges_no_rollback_budget`
- **RED first, eligibility** (`test_rollback_eligibility.py`, one per predicate):
  - `::test_target_requires_fresh_attest`
  - `::test_e4_bound_equals_w1_invariant_terms` (T6: the bound is `ATTEST_PERIOD_H + L_max + ATTEST_MARGIN_H` read from `pins.py`/policy; no literal 1.04)
  - `::test_target_refused_past_age_cap`
  - `::test_target_requires_fee_verified_verdict_matching_theta`
  - `::test_target_requires_current_live_orders_ruling` (root via allowlist triple, P7-1; child via policy ruling)
  - `::test_target_refused_with_pending_cause_or_demand_or_exec_halt`
  - `::test_target_refused_byte_identical_for_any_non_drill_cause` (T5: model, infra, mirror causes)
  - `::test_target_excludes_demoted_terminal_and_unrouted`
  - `::test_target_is_most_recent_eligible`
  - `::test_no_fallback_to_older_target_on_byte_failure`
  - `::test_open_target_integrity_record_makes_target_ineligible` (decision ¶2)
  - `::test_readiness_reports_every_predicate_reason`
- **RED first, budget, bytes and handoff:**
  - `::test_rollback_budget_counted_at_effect_with_reservations`
  - `::test_target_symlink_or_missing_or_sha_mismatch_is_target_integrity`
  - `::test_position_handoff_owned_or_flat_else_refused` (FQ→FQ child owned; exit-capable outgoing with open positions refused; missing metric INCONCLUSIVE)
  - `::test_autonomy_rollback_introduces_no_cause_code` (AST: AUT-7 modules reference only the ARCH enum members `rollback_failed`, `DRILL_INJECT`, `DRILL_INJECT_HALT`; decision ¶3)
- **RED first, journal** (`test_rollback_journal.py`, T7):
  - `::test_journal_exact_set_write_once_0444_no_paths`
  - `::test_journal_prev_sha256_links_and_chain_head`
  - `::test_journal_verified_against_newest_export_heads`
  - `::test_journal_uses_highest_export_seq_incl_hwm_reset_export`
  - `::test_journal_head_mismatch_blocks_rollback_and_alerts`
  - `::test_journal_missing_tail_blocks_rollback_and_alerts`
  - `::test_journal_block_never_blocks_resume_or_restrictive_writes` (L-48)
  - `::test_readiness_filenames_unique_never_overwritten`
- **GREEN:** all pass. The byte binding is imported from the resolver (`test_rollback_uses_resolver_byte_binding`, AST).
- **Activation:** with WP3.

### AUT-7.WP3 — engine integration, fail-closed matrix, post-verify, readiness (Wave 1 code against the AUT-5a stub)
- **Files:** `rollback.py` step hooks, `post_verify.py`; `tests/integration/autonomy/test_rollback_engine.py`, `tests/unit/autonomy/test_post_verify.py`.
- **RED first:**
  - `::test_demote_before_1645_rolls_back_at_same_day_launch`
  - `::test_demote_after_1645_rolls_back_at_next_launch`
  - ARCH-named `::test_prelaunch_writes_rollback_and_activate_atomically` (P7-4)
  - `::test_prelaunch_checks_precede_write_so_failure_writes_nothing`
  - `::test_rollback_requires_no_code_change` (repo mounted read-only)
  - ARCH-named `tests/unit/autonomy/test_rollback_restores_byte_identical_artefact.py::test_rollback_restores_byte_identical_artefact`
  - ARCH-named `::test_rollback_to_root_reads_content_addressed_copy` (P7-5, through the real resolver: the repo artefact file is altered, the restored sha is the BOOTSTRAP row's)
  - ARCH-named `::test_failed_rollback_halts_champion` (P7-3 under the decision: HALT `rollback_failed`, class `ROLLBACK_FAILED`, only on a family that folds CHAMPION; no INTEGRITY row, no freeze)
  - `::test_failed_rollback_leaves_halted_f_without_new_row_and_retries_daily` (R1–R4; journaled counter; delivered CRITICAL)
  - `::test_no_rollback_failure_ever_freezes_the_venue` (parametrized R1–R7a; decision ¶1)
  - `::test_target_byte_mismatch_marks_target_ineligible_without_freeze` (R2/R5; decision ¶2)
  - `::test_target_integrity_clears_after_two_clean_readiness_passes` (L-48)
  - `::test_champion_own_artefact_mismatch_at_load_is_integrity` (R7b; decision ¶2)
  - `::test_rollback_failed_class_is_never_resumed_and_exits_by_retried_rollback` (§3.5.2)
  - `::test_post_launch_resolver_refusal_cancels_without_cause_on_target` (R5)
  - `::test_daily_pass_writes_only_drill_mint_admit_and_pending_pair` (T2)
  - `::test_resume_written_only_in_prelaunch_with_binding_probe`
  - `::test_rollback_alerts_journal_delivery` (non-2xx → `delivered=false`, retried; G25)
  - `::test_wp3_consumes_aut5a_boot_signals` (T8: contract test that I-5a.1's event names, I-5a.2's non-relaunch hook and I-5a.3's bytes-only composition signature exist and are imported from AUT-5a, not re-declared)
- **RED first, post-verify** (`test_post_verify.py`):
  - `::test_post_verify_runs_from_1705_against_boot_resolved_sha`
  - `::test_post_verify_mismatch_halts_target_rollback_failed` (R6)
  - `::test_post_verify_missing_composed_line_halts_at_1730`
  - `::test_post_verify_interim_parses_fq_live_orders_line` (`app/trade.py:753-762` format; interim only)
  - `::test_load_failure_after_resolve_cancels_or_halts_not_crash_loop` (R7a: before 17:00 SWAP_CANCEL, after 17:00 HALT; no second relaunch of the same resolved family; `target_load_failed` until the engine pin rotates)
- **GREEN:** all pass. The §4.7 envelope tests stay unweakened and `test_damping_ceilings` stays green.
- **Activation (T8, stated technical reason).** Merged and activated only after AUT-5a's I-5a.1 (`registry_boot_load_failed`), I-5a.2 (supervisor non-relaunch plus intraday trigger) and I-5a.3 (bytes passed to composition, ARCH `test_verify_and_load_share_bytes` green) are merged **and live**. Reason: without them R7 cannot be detected, and the resolve→load re-read (F-2) could load unverified bytes after a rollback. Then engine restart in 01:00–16:40, never touching the node.

### AUT-7.WP4 — drill library and marker detectors (Wave 1)
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
  - `::test_drill_halt_never_freezes_or_writes_exec_store` (P6-4, T1)
- **RED first, then:**
  - `::test_drill_child_equals_root_modulo_three_keys`
  - `::test_drill_child_writes_no_c3_lineage_and_no_counter`
  - `::test_next_drill_child_id_monotone_never_reused_across_venues`
  - `::test_daily_arm_writes_mint_admit_and_pending_pair_after_advisory_intent_check` (T2; OPEN or corrupt intent → nothing written)
  - `::test_prelaunch_activates_or_cancels_drill_pair_after_g1_to_g11` (T2)
  - `::test_drill_start_gate_each_condition` (parametrized G-1..G-11)
  - `::test_drill_start_gate_requires_27d_after_newest_charged_drill_row` (T4)
  - `::test_drill_cadence_from_last_completed_episode`
  - `::test_drill_retry_after_cancel_writes_new_pair_at_next_daily_reusing_r0001` (T2 restatement of K5: no second MINT or ADMIT)
  - `::test_drill_demote_and_halt_budget_enforced_at_marker_writer` (N-2)
  - `test_drill_inject.py::test_marker_detector_field_selects_detector` (T1: the other id's marker → PASS)
  - `::test_marker_window_per_step_demote_halt_abort` (T1)
  - `::test_marker_must_bind_episode_child_clause_step_and_root` (each field mismatched → ERROR)
  - `::test_marker_symlink_oversize_unparseable_or_expired_is_error_not_pass`
  - `::test_drill_child_resumes_only_on_drill_inject_cause`
  - `::test_genuine_fault_on_drill_child_abandons_episode_no_auto_resume` (T5)
  - `::test_is_drill_fill_by_interval_or_family_id`
  - `::test_drill_state_is_derived_from_chain_after_restart`
- **GREEN:** all pass, and the producer pin covers `drill_inject.py` (`test_code_identity_pins_cover_import_closure`).
- **Activation:** with WP6.

### AUT-7.WP5 — AUT-7a gate drill (Wave 1; completes after the AUT-5a/AUT-6 interfaces land)
- **Files:** `tests/integration/autonomy/test_rollback_drill_gate.py`.
- **RED first:**
  - `::test_gate_drill_full_episode` (T1): the exact §3.6.5 rows and modes for DEMOTE → RESUME → HALT → ROLLBACK; pending pair at 15:30, ACTIVATE at 16:45; RESUME and the closing ROLLBACK only in prelaunch; the child DISPLACED HALTED→CHALLENGER; byte identity of the restored sha; `drill=true` from D 16:50 to D+3 16:50; each marker → veto ≤ 15 min; post-verify OK ×3; delivered events `DRILL_ARMED`, `DRILL_STARTED`, `DRILL_DEMOTED`, `DRILL_RESUMED`, `DRILL_HALTED`, `DRILL_ROLLBACK`, `DRILL_CLOSED`.
  - `::test_gate_drill_position_open_across_each_swap` (a position opened under fq_v1 before DRILL_PROMOTE, under r0001 before the closing ROLLBACK, and in a production ROLLBACK; reconciliation stays PASS; `rung_net_position_held` blocks re-entry; an exit-capable outgoing refuses).
  - `::test_gate_drill_failure_matrix` (R1–R7 at each step; abort path with `abort_halt`; no freeze except R7b; alerts journaled).
  - `::test_gate_drill_retry_after_swap_cancel` (T2).
  - `::test_failed_episode_retry_never_strands_closing_rollback` (T4: an aborted episode closing at D+6, a retry admitted at the G-2 bound, every retry row within budget, closing ROLLBACK admitted).
  - `::test_genuine_fault_on_drill_child_never_restores_identical_artefact` (T5: while the non-DRILL cause stands, no ROLLBACK to sha `9c0b6d6e…`, r0001 stays HALTED, production budget charged on its RESUME).
  - `::test_genuine_fault_with_no_eligible_target_leaves_venue_without_sender_and_alerts` (T5).
  - `::test_abandoned_episode_restores_root_only_after_clean_production_resume` (T5 deferred close).
  - `::test_gate_drill_fills_feed_risk_reconciliation_and_pnl`.
  - ARCH-named `::test_drill_fills_excluded_from_n_and_kill_clock`.
  - `::test_gate_drill_runs_production_default_port_once` (L-55).
- **GREEN:** passes in the full gate and is listed in the T1 lane (`scripts/ci/tier_lanes.py`).
- **Activation:** the gate is the schedule, so it is live on merge.

### AUT-7.WP6 — live drill wiring and evidence bundle (Wave 3, after the AUT-5b ruling and allowlist widening)
- **Scope:** `drill.step(mode)` in the daily, prelaunch and intraday modes; `build_drill_bundle` from the D+4 daily pass; the rollback and drill section of `deploy/systemd/README.md`; the drill-clause values (§3.6.3) handed to AUT-5's ruling.
- **RED first:**
  - `tests/unit/autonomy/test_drill_bundle.py::test_bundle_requires_chain_export_nodelog_delivery_items` (incl. the HALT row, its marker and `DRILL_HALTED`)
  - `::test_bundle_refuses_on_missing_or_mismatched_node_log_line`
  - `::test_bundle_lists_window_commits_against_allowed_set`
  - `::test_bundle_emitted_only_from_d4_daily_pass_no_unit`
  - `::test_bundle_write_once_0444`
  - `::test_abandoned_or_aborted_episode_bundle_is_marked_not_proof`
- **GREEN:** all pass, plus a gate-drill rerun.
- **Activation:** on merge with the engine restart. The drill starts on its own at `drill_first_eligible_date`; no timer to install.

### AUT-7.WP7 — AUT-7b execution (live, no code)
- The engine runs §3.6 unattended. The coordinator only observes, with a Monitor on the chain export and the bundle path (memory note `every-background-job-needs-a-watch`).
- **GREEN:** an independent scorer signs off the §6 bundle as complete.

## 5. Association

Interfaces consumed. Each is a blind assumption; if one is absent, AUT-7 raises it in that area's review and never forks it.

| Contract | From | Interface AUT-7 needs |
|---|---|---|
| C5 store | ARCH-0/AUT-5 | `VerifiedVenueChain`; `resolve_champion`; `RegistryStore.append(rows, *, expected_prior_seq, mode)` (atomic multi-row, so MINT + ADMIT + pending pair, and ROLLBACK + partner + ACTIVATE, each fit one transaction); per-mode `KIND_MASK` admitting §3.1's kinds (daily: MINT, DRILL_ADMIT, DRILL_PROMOTE, SUPERSEDE, RETIRE; prelaunch: ACTIVATE, SWAP_CANCEL, ROLLBACK, SUPERSEDE, DISPLACED, RESUME; intraday: DEMOTE, HALT, SWAP_CANCEL); the resolver's per-row byte binding exposed as `verify_family_bytes(row)`; the child-write API; lineage and drill counters; the shared allocator if any |
| C5 cause enum | ARCH Rev 7 / AUT-5 | `CauseClass` gains `ROLLBACK_FAILED` (non-freezing, outside the RESUME set) per the decision; `cause_code` `rollback_failed` (N-1) |
| C5 journal + export | ARCH-0/AUT-5 | the ARCH-0 rollback journal module; the daily export carries `evidence_journal_heads: {rollback, readiness}` (T7) |
| C5 engine | AUT-5 | phase hooks `rollback.step`/`drill.step` (AUT-5 r2 `engine.rollback.propose`); the advisory 15:30 intent read through the G6 `mode=ro` URI (corrupt = OPEN, P7-6); `probe_open_intent` at 16:45 |
| **I-5a.1** | AUT-5a | node log lines `registry_resolved venue=<v> family_id=<id> registry_seq=<n> chain_head=<h> manifest_sha256=<m> artefact_sha256=<a>`, `registry_composed family_id=<id> artefact_sha256=<a>`, and **`registry_boot_load_failed family_id=<id> stage=manifest\|artefact\|compose reason=<code>`** (with `reason=sha_mismatch` distinguishable); node log FILE paths (memory note `trade-node-dies-with-the-session`) |
| **I-5a.2** | AUT-5a | **supervisor non-relaunch:** after I-5a.1 load-failed, the supervisor never relaunches that resolved family before the next LAUNCH, and it triggers the intraday engine pass |
| **I-5a.3** | AUT-5a | **bytes passed to composition:** `_compose_family` consumes `ResolvedFamily` bytes and never re-reads a path (closes F-2; ARCH `test_verify_and_load_share_bytes`) |
| C5 policy | AUT-5 ruling | the drill clause (§3.6.3) and `drill_clause_sha256`; RETIRE reason; `DRILL_INJECT → DEMOTE` and `DRILL_INJECT_HALT → HALT`, class `DRILL`; the `RECOVERABLE_MODEL` map; `ROLLBACK_TARGET_MAX_AGE_D`, `drill_min_drawdown_headroom_frac`, `INTRADAY_ATTEST_VERDICT_PERIOD_MIN`, `ATTEST_PERIOD_H`, `ATTEST_MARGIN_H` |
| C4 | AUT-6 | the intraday producer evaluates `DrillMarkerDetector` for both ids; a fee-drift `VERDICT` citing the AGREE line and the verified θ (E6/G-6); a permit-liveness `HEALTH` verdict (G-7) |
| C4 | AUT-5 | the `live.drawdown` verdict with `metrics.drawdown_used_frac`, drill fills included (G-9) |
| C4 | AUT-2 | post-STOP `RECONCILIATION` with `metrics.open_positions_by_family`, plus intraday RECONCILIATION |
| C1 | AUT-1 | `drill` flag from `is_drill_fill`; `EntryVeto` records (`registry_halted`, `permit_lapsed`) |
| C2 | AUT-2 | `excluded_reason=drill`; drill rows keep `realized_pnl` and feed P&L/ROI |
| C4 live / KILL | AUT-4 | admissible-only n; the KILL clock keyed on `lineage_root_family_id` |
| §4.6 | AUT-6 | `deliver_with_proof` and the per-attempt delivery records |

**Cross-plan alignment (for AUT-5 r3).** AUT-5 r2 §3.10 has the older drill timeline: RESUME at the 15:30 daily pass, the ROLLBACK proposed pending from the daily pass, no HALT step, 6 days. Rev 6 §4.4 (16:45 authoritative intent; ROLLBACK with ACTIVATE at pre-launch, P7-4) and §10 (HALT step) make the §3.6.5 timeline above the binding one; ARCH assigns the drill steps to AUT-7. AUT-5 r3 should cite §3.6.5 and keep only the mechanics.

**Provided:**
- `champion_history`, `target_eligibility` and `readiness` → AUT-5 and AUT-6;
- `position_handoff_ok` → AUT-5, offered for PROMOTE as well (C-11);
- `drill_episodes` and `is_drill_fill` → AUT-1, AUT-2, AUT-4;
- `DrillMarkerDetector` (`DRILL_INJECT`, `DRILL_INJECT_HALT`) → AUT-6;
- the executed AUT-7b → the AUT-5 (PROMOTE/DEMOTE/RESUME) and AUT-6 (DEMOTE and HALT class) live proofs.

**Order:**
- WP1, WP2 (minus the journal part) and WP4 run in parallel in Wave 1; WP2's journal part follows ARCH-0's journal module.
- WP3 completes after AUT-5a (engine modes, resolver, **I-5a.1–3**) and AUT-6 (`deliver_with_proof`, producer, fee/permit verdicts); WP5 completes with them.
- WP6 follows AUT-5b, AUT-1 (drill flag) and AUT-2b (drill exclusion and `open_positions_by_family`).
- WP7 follows the §6 soak.

## 6. Live-proof protocol

**Preconditions (all observed, none hand-made):**
- the AUT-5a watch actor live ≥ 3 sessions with no `registry_unreadable`; I-5a.1–3 live (WP3 activation);
- ≥ 1 ATTEST for fq_v1;
- an AUT-6 canary `delivered=true` record (`alerts_undeliverable` armed);
- the post-STOP RECONCILIATION producer emitting `open_positions_by_family`;
- the fee, permit and drawdown verdicts flowing; AUT-6 evaluating both marker detectors;
- the readiness journal running daily and verifying against the newest export (§3.5.3).

**Bundle** `~/.local/share/breezy/evidence/drills/drill_polymarket_us_<episode_id>.json` (0444, write-once, emitted by the D+4 15:30 daily pass). It cross-references:
1. **Chain export rows** `registry_polymarket_us_<D..D+4>.jsonl`: MINT, DRILL_ADMIT, DRILL_PROMOTE+SUPERSEDE (D 15:30, pending), ACTIVATE (D 16:45), DEMOTE `DRILL_INJECT` (D+1), RESUME (D+2 16:45), HALT `DRILL_INJECT_HALT` (D+3), ROLLBACK+DISPLACED+ACTIVATE (D+3 16:45), RETIRE (D+4). All `decided_by=engine` with one pinned `engine_code_sha`, contiguous `venue_seq` and a verified chain head; the export's `evidence_journal_heads` match the journals.
2. **Node log files:** resolved and composed lines for r0001 at D, the HALTED boot at D+1, r0001 at D+2 and fq_v1 at D+3, each `artefact_sha256=9c0b6d6e66a587c1b4e14e5f95ff5cedb3c7195f62f8ad4238191fdd75923a5e`; both `registry_halted` set lines (D+1 DEMOTE, D+3 HALT) and the D+2 clear line.
3. **Verdict files:** `DRILL_INJECT` FAIL (bound marker) then PASS; `DRILL_INJECT_HALT` FAIL then PASS; both marker shas from the journal.
4. **Delivery records:** `delivered=true` for `DRILL_ARMED`, `DRILL_STARTED`, `DRILL_DEMOTED`, `DRILL_RESUMED`, `DRILL_HALTED`, `DRILL_ROLLBACK`, the three `POST_VERIFY_OK` and `DRILL_CLOSED`.
5. **No commit in the loop:** `git log --since=<D 15:30> --until=<D+4 15:30> --format='%H %s' -- deploy src` is empty, **or** every listed commit appears by sha in `allowed_commits` with its touched paths, and none touches `deploy/families/**`, `deploy/systemd/**`, `src/breezy/persistence/autonomy/**`, `src/breezy/persistence/live_orders_gate.py`, `src/breezy/app/trade.py` or `src/breezy/runtime/trade_supervisor*.py`. Every drill row's `engine_code_sha` is identical.
6. **Drill fills:** C1 `drill=true` and C2 `excluded_reason=drill`; live n and the KILL-clock counter unchanged; the same fills present in the drawdown, reconciliation and P&L inputs.

An aborted or abandoned episode emits a bundle marked `status: failed|abandoned`, which is never live proof. The coordinator copies a summary to `docs/evidence/AUT-7b_drill_<D>.md` after the fact; that step is outside the loop.

**Clock and ETA** (honest; build pace is not guaranteed):

| Milestone | Earliest | P50 | P90 |
|---|---|---|---|
| ARCH-0 merged | 2026-10-09 | 10-12 | 10-17 |
| WP1/2/4 merged; WP3/5 after AUT-5a (incl. I-5a.1–3) and AUT-6 | 10-16 | 10-21 | 10-28 |
| AUT-5b ruling + allowlist; AUT-2b; WP6 | 10-27 | 11-04 | 11-14 |
| Soak met → D | 11-02 | 11-09 | 11-19 |
| AUT-7b closes (D+4 bundle) = **live proof**, first episode | **2026-11-06** | **2026-11-13** | **2026-11-23** |
| One failed episode, retry under G-2 | — | — | **2026-12-24** (nominal) / **12-27** (abort at D+6) |

**P90 recomputed (T4).** First D = 11-19, nominal closing ROLLBACK E = 11-22 16:50. If that episode fails after charges:
- nominal failure (closes at D+3): the retry arm needs D′ 15:30 ≥ E + 27 d = 12-19 16:50, so D′ = 12-20; it closes 12-23, bundle **12-24**, margin to the 2027-01-25 KILL **32 days**;
- worst abort (closes at D + `drill_max_episode_days` = 11-25): D′ = 12-23, bundle **12-27**, margin **29 days**;
- a second consecutive failure: E′ = 12-23..12-26 → D″ = 01-20..01-23 → bundle 01-24..01-27, i.e. a 1-day margin at best and a miss at worst. **A second retry cannot be relied on before the KILL.**

A pre-effect lapse or SWAP_CANCEL is not charged and slips one day. If the KILL fires TERMINAL first, DRILL_PROMOTE is refused (ARCH §5.3). The drill needs no natural fill, so the ~5 fills/day rate does not gate it.

**Evidence class:** "machinery proven, edge unproven". While `promote_enabled=false` the trigger→ROLLBACK chain is **gate-proven**, and the live drill proves the shared `plan_rollback`→LAUNCH path (§3.3.4). The exec-store HALT writers and the TERMINAL/INTEGRITY paths (incl. R7b) stay gate-proven (C6 P6-4).

## 7. Score-3 verification checklist (independent scorer)

| Criterion | Check |
|---|---|
| History immutable | `sqlite3 'file:…/registry.sqlite?mode=ro' ".backup <scratch>/reg_copy.sqlite"`, then `sqlite3 <scratch>/reg_copy.sqlite "UPDATE transitions SET kind=kind WHERE seq=1"` must fail with the trigger's ABORT, and the same for `DELETE`; production is never written. Plus `test_history_never_reads_projection_or_families_cache`, `test_history_render_equals_fold_and_is_write_once`. |
| (a) unattended | bundle item 1 (`decided_by=engine`, one `engine_code_sha`); item 5 |
| (b) family-agnostic | `test_every_champion_epoch_appears_in_history`, `test_rollback_module_has_no_family_literals` |
| Trigger within one cycle, no code change | `test_demote_before_1645_rolls_back_at_same_day_launch`, `test_demote_after_1645_rolls_back_at_next_launch`, `test_prelaunch_writes_rollback_and_activate_atomically`, `test_rollback_requires_no_code_change`; live: D+3 16:45 ROLLBACK+DISPLACED+ACTIVATE → D+3 16:50 boot line. Trigger leg gate-proven while `promote_enabled=false`. |
| Target eligibility | `test_rollback_eligibility.py` (one test per E-predicate, incl. `test_e4_bound_equals_w1_invariant_terms`, `test_target_refused_byte_identical_for_any_non_drill_cause`) |
| Position handoff | `test_position_handoff_owned_or_flat_else_refused`, `test_gate_drill_position_open_across_each_swap` |
| (c) fails closed, no venue freeze | `test_failed_rollback_halts_champion`, `test_no_rollback_failure_ever_freezes_the_venue[R1..R7a]`, `test_target_byte_mismatch_marks_target_ineligible_without_freeze`, `test_champion_own_artefact_mismatch_at_load_is_integrity`, `test_rollback_failed_class_is_never_resumed_and_exits_by_retried_rollback`, `test_gate_drill_failure_matrix`; `test_autonomy_rollback_introduces_no_cause_code` |
| (d) detected + delivered | `test_rollback_alerts_journal_delivery`; bundle item 4; `test_journal_verified_against_newest_export_heads`, `test_journal_head_mismatch_blocks_rollback_and_alerts`, `test_journal_missing_tail_blocks_rollback_and_alerts` |
| Damping | `test_at_most_one_widening_decision_per_venue_per_prelaunch_pass`, `test_rollback_resume_ping_pong_damped_by_z3_ceilings`, `test_no_dwell_constant_in_rollback_module`, `test_budget_exhausted_halt_charges_no_rollback_budget` |
| (e) RED→GREEN | WP commit messages; full-gate EXIT=0 per merge |
| Drills scheduled | gate: `test_rollback_drill_gate.py` in the T1 lane (`scripts/ci/tier_lanes.py`); live: `drill_cadence_days` and `drill_first_eligible_date` in the sha-pinned policy block, plus the journal of daily `drill_arm_gate`/`drill_start_gate` decisions |
| Drill HALT step (P6-4) | `test_gate_drill_full_episode`, `test_drill_halt_never_freezes_or_writes_exec_store`; bundle items 1–4 (HALT row, marker, verdicts, `DRILL_HALTED`) |
| Budget never strands | `test_drill_start_gate_requires_27d_after_newest_charged_drill_row`, `test_failed_episode_retry_never_strands_closing_rollback` |
| Genuine fault on child | `test_genuine_fault_on_drill_child_never_restores_identical_artefact`, `test_genuine_fault_with_no_eligible_target_leaves_venue_without_sender_and_alerts` |
| (f) live proof | the bundle is complete; restored sha = `9c0b6d6e…923a5e`; ≥ 4 trading days D…D+3 |
| Drill exclusion, risk inclusion | `test_drill_fills_excluded_from_n_and_kill_clock`, `test_gate_drill_fills_feed_risk_reconciliation_and_pnl`, `test_detectors_and_drawdown_include_drill_fills` |

## 8. Risks and failure modes

| ID | Risk | Mitigation |
|---|---|---|
| K-1 | Fee drift during the drill: the exec-store `policy_halt` on r0001 is TERMINAL and freezes the fq_v1 lineage | Accepted fail-closed cost (Z20 analogue). G-6 requires a fee-verified verdict at D 16:45. Recovery is a reviewed new root. |
| K-2 | Each drill costs ≈ 10 drill fills plus ≈ 1.1 vetoed sessions | Cadence 60 d from completion; at most 2 completed drills before the KILL. |
| K-3 | The champion-scoped KILL clock (`promotion_criteria.py:135`) would follow r0001 | AUT-2/AUT-4 key it on `lineage_root_family_id` and exclude drill intervals. |
| K-4 | An AMBIGUOUS intent open at 16:45 defers the drill or a rollback (Z19) | R4 writes nothing and retries daily. In a drill abort with r0001 CHAMPION, P7-3 HALTs r0001 (fail-closed). AUT-2 measures the rate. |
| K-5 | Byte drift of a committed root | The resolver reads the C3 copy (P7-5), so repo drift no longer poisons the target; drift of the C3 copy opens `target_integrity`, clearing after two clean readiness passes. |
| K-6 | F-2 resolve→load re-read | WP3 does not activate until I-5a.3 is live; R7a/R7b are the backstops. |
| K-7 | Memory on the 31 GB host | Runs inside the engine's ≤ 4G own-lock budget; no new unit; the bundle builder streams the export and reads only the node-log lines it needs. |
| K-8 | Shared venv, concurrent agents | Exact interpreter; no `uv`/`pip`/`git stash`; per-agent scratchpads; `PYTHONPATH`; disjoint files; full gate after every merge; the ARCH-0 journal module is touched only after ARCH-0 merges. |
| K-9 | Engine crash mid-drill | State re-derived from the chain and journal; idempotent ids; chain-pure allocator; a crash between 15:30 and 16:45 lets the pending pair lapse uncharged; the heartbeat veto bounds exposure. |
| K-10 | Statistical capacity | No edge claim. |
| K-11 | KILL 2027-01-25 | P90 first episode 11-23; one failed episode retried under G-2 closes by 12-24 to 12-27 (29–32 d margin); a second retry cannot be relied on. |
| K-12 | No eligible target live while `promote_enabled=false` | Stated in §3.3.4 and §6; trigger path gate-proven; readiness reports `NO_TARGET` as INFO. |
| K-13 | The interim post-verify line logs the manifest pin before the load | Interim only, and WP3 activation waits for I-5a.1's resolved/composed lines. |
| K-14 | A journal mismatch or missing tail blocks all rollbacks | Fail-closed by design (T7); RESUME and restrictive writes stay open (L-48); clears when verification passes again. |
| K-15 | A genuine fault on r0001 that never clears, or fq_v1 ageing past E5 before the deferred close | r0001 stays HALTED or remains champion; drills stay blocked by G-1; the venue may have no sender (fail-safe, daily CRITICAL). Probability is bounded by the ~4-day episode; a reviewed new root is the recovery. |
| K-16 | A post-verify false positive (missing line) HALTs a healthy target with `ROLLBACK_FAILED` | Grace to 17:30 for a missing line; a mismatch HALTs at once. Accepted fail-closed cost: the class never freezes the venue. |

## 9. Binding-constraint compliance

- **Nautilus:** untouched. Only the existing native `Actor` pattern is consumed (AUT-5).
- **Caps:** never read, assigned or derived. The drawdown headroom (G-9) is a policy-ruling value, not an operator cap. `test_autonomy_never_reads_or_writes_operator_controls` covers every AUT-7 module.
- **allow_short:** stays `False`. The child equals the root on every size and side key.
- **NO-SEND:** unchanged. The gate drill runs under `run_tests_no_egress.sh`. The only egress is `deliver_with_proof` on the existing `alerts.env` key (`test_autonomy_alert_egress_not_widened`).
- **Master enablement and permit:** untouched. G-7 only reads a permit-liveness verdict. Rollback and drill change only which allowlisted family the resolver names.
- **PREREG via ruling:** the drill clause, cadence, windows, age cap and headroom live only in the AUT-5 sha-pinned policy block under code ceilings; AUT-7 adds no constant of its own (dwell and the engine-HALT counter withdrawn).
- **Safety tests:** none weakened. The §4.7 list stays green; new tests only add pins. r2's planned `test_rollback_min_dwell_refuses_within_24h_of_last_change` and `test_engine_halt_resume_rule_and_counter_never_integrity` were never written, so dropping them weakens nothing.

## 10. Self-score

| Axis | Score | Note |
|---|---|---|
| Fidelity | 18/20 | Rev 6 §10 obligations met item by item, including the HALT step, P7-3/P7-4/P7-5/P7-6 and the binding decision. It depends on Rev 7 adding `ROLLBACK_FAILED` and the drill-HALT counter (N-1, N-2). |
| Correctness | 17/20 | Code evidence re-checked at `4b8347a6`. The G-2 bound is derived per row kind. I-5a.1–3 and the export journal heads are unconfirmed asks. |
| Specificity | 14/15 | Exact modules, rows, times, marker schema, predicates and tests. |
| Acceptance | 18/20 | Scorer-runnable checks for every criterion, plus HALT, strand and genuine-fault rows. The trigger leg stays gate-proven while `promote_enabled=false`. |
| Autonomy-safety | 14/15 | No venue freeze from rollback; fail-safe no-sender states alert daily; journal anchored to the export. K-15 is a stated residual. |
| Reuse | 9/10 | ARCH-0 journal reused rather than recreated; resolver binding, exit gate, probe and fee verdict reused; no new unit. |
| **Total** | **90/100** | r2 self-scored 89 and reviewers gave 77, almost all from the Rev 5 base. r3 is rebased on Rev 6, but N-1/N-2 still need ARCH, so the score is raised by only one point. |

## 11. ARCH assumptions and contradictions (against Rev 6)

**Resolved by Rev 6 or the decision:**
- **C-1** root exemption: Rev 6 C5 P7-1 (`test_root_resolves_under_live_orders_allowlist`). E3/E7 consume it.
- **C-3** engine HALT row: Rev 6 C5 P7-3 plus the binding decision. AUT-7 writes only `rollback_failed` (`ROLLBACK_FAILED`, or `INTEGRITY` for R7b). The r2 cause codes and their resume counter are deleted.
- **C-4** pre-launch writes: Rev 6 §4.4 P7-4 (ROLLBACK + ACTIVATE at 16:45) and §5.2 (daily writes pending pairs). §3.6.5 follows the split.
- **C-5** child artefact path: Rev 6 C3 P7-5 (C3 store read by sha).
- **C-6** advisory 15:30 intent: Rev 6 §4.4 P7-6.
- **C-8** INFRA exhaustion → INTEGRITY: moot for AUT-7, since rollback failures use `ROLLBACK_FAILED`, never `RECOVERABLE_INFRA`. ARCH's INFRA rule is consumed unchanged.
- **C-10** "never re-reads": now ARCH text; the code gap is gated by I-5a.3 (T8).

**Still open:**
- **C-7 (constants).** Needed: `ROLLBACK_TARGET_MAX_AGE_D ≤ 30` as a `pins.py` ceiling; drill-clause keys `drill_min_drawdown_headroom_frac`, `drill_halt_utc`, `drill_halt_slo_min`. **Withdrawn:** `ROLLBACK_MIN_DWELL_H`, `MAX_ENGINE_HALT_RESUMES_PER_VENUE_7D`.
- **C-9 (contradiction, unchanged in Rev 6).** §4.4 still defines a horizon "for an intraday RESUME", but the intraday engine is restrictive-only (W1). AUT-7 writes every RESUME at 16:45. Rev 7 should delete the clause.
- **C-11.** §4.4 has no position-ownership precondition. AUT-7 applies `position_handoff_ok` to its own swaps; ARCH should state it for PROMOTE too.

**New (raised by r3):**
- **N-1.** The Rev 6 C5 HALT row says "class INTEGRITY on a byte mismatch", and `CauseClass` (C5; AUT-5 r2 `schemas.py`) has no `ROLLBACK_FAILED`. The decision supersedes this. Rev 7 must add `ROLLBACK_FAILED` (non-freezing, outside the RESUME set, exit by the retried rollback), narrow INTEGRITY to the champion's own bytes at load, and state the exit path (§3.5.2).
- **N-2 (new contradiction).** §4.5 budgets one `DRILL_INJECT` DEMOTE and one `DRILL_INJECT_HALT` per drill, but C5 `lineage_counters` has no `drill_demotes`/`drill_halts`, and DEMOTE/HALT rows are "always permitted, never capped". Those two budget items can only bind at the marker writer (§3.6.7). Rev 7 should add the counters and name that locus.
- **N-3.** Decision ¶1 "halts only the family that failed to activate" versus C5 "HALT … on the current champion if it still folds CHAMPION". They coincide in R6/R7 (the target is the champion that failed to activate) and in the drill abort (the child is the champion). §1 records this reading; Rev 7 should use one wording.
- **N-4.** The decision's `rollback_eligible=false, cause=target_integrity` has no C5 row kind; a SWAP_CANCEL cause would set the stronger `demoted_for_cause`. AUT-7 keeps it as a journal-derived eligibility input (§3.2). If ARCH wants it on chain, Rev 7 must name a row.
- **N-5 (cross-plan, not ARCH).** AUT-5 r2 §3.10 drill timeline contradicts Rev 6 §4.4/§10 (§5 alignment note).

## §R3 Disposition (review `reviews/AUT-7-r2-merged.md`; decision `reviews/ROLLBACK-FAILURE-decision.md`)

**8 FIXED, 0 REJECTED.** Rebased on ARCH Rev 6 (sha `81c3c79f…`) and the binding ROLLBACK-FAILURE decision.

| T | Disposition | Evidence (where) |
|---|---|---|
| T1 drill includes HALT | FIXED | §3.6.5 sequence DEMOTE → RESUME → HALT (`DRILL_INJECT_HALT`) → ROLLBACK with the child DISPLACED HALTED→CHALLENGER; marker schema with `detector` and `step` plus a window per step (`demote`, `halt`, `abort_halt`); HALT in the drill budget table (§3.6.7), the §6 bundle items 1–4, delivery event `DRILL_HALTED`; `test_gate_drill_full_episode` updated; ARCH-named `test_drill_halt_never_freezes_or_writes_exec_store` (WP4); `test_marker_detector_field_selects_detector`, `test_marker_window_per_step_demote_halt_abort` |
| T2 pre-launch write split | FIXED | §3.1 mode table, §3.4, §3.6.5: D 15:30 advisory intent read, then MINT + DRILL_ADMIT + pending DRILL_PROMOTE pair; D 16:45 G-1..G-11, then ACTIVATE or SWAP_CANCEL; the 16:45 pass writes ROLLBACK + partner + ACTIVATE together (P7-4). K5 retry restated on the split (§3.6.5 "Retry"); `test_daily_arm_writes_mint_admit_and_pending_pair_after_advisory_intent_check`, `test_prelaunch_activates_or_cancels_drill_pair_after_g1_to_g11`, `test_drill_retry_after_cancel_writes_new_pair_at_next_daily_reusing_r0001` |
| T3 ROLLBACK-FAILURE decision | FIXED | §1 reading; §3.5 R1–R7b (`rollback_failed`, class `ROLLBACK_FAILED`; target byte mismatch → `target_integrity` ineligibility, no freeze; R7b champion's own bytes keep INTEGRITY); §3.5.1 one HALT shape; r2 cause codes and `MAX_ENGINE_HALT_RESUMES_PER_VENUE_7D` deleted; `test_autonomy_rollback_introduces_no_cause_code`, `test_failed_rollback_halts_champion`, `test_target_byte_mismatch_marks_target_ineligible_without_freeze`; C-3, C-8, C-9 updated in §11 |
| T4 budget never strands a retry | FIXED | Option (b): G-2 requires the arm instant ≥ newest charged drill row + 27 d (§3.6.3, with the per-kind derivation and the reason for not exempting the ROLLBACK); §6 P90 recomputed: first 11-23, one retry 12-24 (32 d margin) to 12-27 (29 d); a second retry cannot be relied on; `test_drill_start_gate_requires_27d_after_newest_charged_drill_row`, `test_failed_episode_retry_never_strands_closing_rollback` |
| T5 genuine fault on the drill child | FIXED | §3.6.6: episode abandoned; E9 widened to any non-`DRILL` cause, so no ROLLBACK to the same `artefact_sha256` while it stands; r0001 stays HALTED under production rules and the production budget; abandoned-episode journal close plus a deferred restorative close only after a clean production RESUME; "what sends next" stated, with the no-sender fail-safe and a daily CRITICAL; `test_genuine_fault_on_drill_child_never_restores_identical_artefact`, `test_genuine_fault_with_no_eligible_target_leaves_venue_without_sender_and_alerts`, `test_abandoned_episode_restores_root_only_after_clean_production_resume` |
| T6 dwell | FIXED | `ROLLBACK_MIN_DWELL_H` deleted; damping is the Z3 ceilings plus one widening decision per venue per 16:45 pass (§3.3.4); drill closing and abort ROLLBACKs take no dwell and count only against the drill budget; E4 is defined by the W1 terms (`ATTEST_PERIOD_H + L_max + ATTEST_MARGIN_H`, no literal 1.04); `test_no_dwell_constant_in_rollback_module`, `test_at_most_one_widening_decision_per_venue_per_prelaunch_pass`, `test_e4_bound_equals_w1_invariant_terms` |
| T7 journal against the newest export | FIXED | §3.5.3 `verify_journal_chain` against the highest-`export_seq` export's `evidence_journal_heads`; a mismatch or missing tail blocks every rollback (R1 `journal_unverified`) and the drill (G-11) with CRITICAL `ROLLBACK_JOURNAL_UNVERIFIED`; never blocks RESUME or restrictive writes; WP2 journal tests; the journal module is ARCH-0's (reused, not recreated) |
| T8 WP3 gated on AUT-5a | FIXED | §5 named consumed interfaces I-5a.1 (`registry_boot_load_failed`), I-5a.2 (supervisor non-relaunch), I-5a.3 (bytes passed to composition); WP3 activation waits for all three to be live, with the stated technical reason; `test_wp3_consumes_aut5a_boot_signals` |

**r2 K-ids:** K1–K18 keep their r2 dispositions (`AUT-7-rollback_plan_r2.md` §R2); where r3 changes a mechanism (K5 → T2, K7 → T1/T5, K8 → T6, K9 → T3, K11 → T7), the T-row above governs.
