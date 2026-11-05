# AUT-7 — Rollback (incl. AUT-7a gate drill, AUT-7b live promotion/rollback drill) — plan r5

## 0. Header

| Field | Value |
|---|---|
| ID | AUT-7 (sub-items AUT-7a gate drill, AUT-7b live drill) |
| Title | Rollback: immutable champion history, automated rollback, fail-closed failure, scheduled drills |
| Round | r5 (2026-10-03), the **final polish**. Revises r4 (`docs/plans/backlog/AUTONOMY_2026-10-03/AUT-7-rollback_plan_r4.md`, kept unchanged) per `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/AUT-7-r4-merged.md` (G1–G8) and errata E-5. §R5 lists every change; §R4 (the rebase onto Rev 9.2) is kept below as history. |
| ARCH consumed | **FROZEN Rev 9.2**, `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/snapshots/ARCH_rev9_2.md`, sha256 `1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42` (re-hashed 2026-10-03), plus `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-ERRATA-rev9_2.md` (E-1..E-5; E-3 read: Rev 9.2 tags are cited as `R9.2-Z1…Z9`; E-2 read: the 16:45 pass mirrors the exec store itself before any check that reads the mirror, §3.4; E-5 adopted as the restorative RESUME after a failed drill close, §3.6.6 step 4). No older snapshot is cited as a basis. Code evidence re-checked at `4b8347a6` through codegraph (`exit_gate.py:55-67`, `trade_supervisor.py:402-420`, `fee_drift_probe.py:184,543-584`, `calibration_artefact.py:236-256`, `family_manifest.py:13-48`, `deploy/families/pm_us_crh_fq_v1.json:4-10`). |
| Binding decisions consumed | `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ROLLBACK-FAILURE-decision.md` (now carried by ARCH C5 "Failed rollback", P7-3/P7-8); `ALPHA-decision.md` and `HOLDOUT-decision.md` (no AUT-7 surface: drill rows are never nominations, C4). |
| Current score | 2 (README: sha-pinned manifests make a rollback a manifest swap; there is no previous-champion pointer, no trigger and no drill) |
| Target | 3 |
| Upstream | ARCH-0 (C5 store, chain, fold, resolver, rollback journal, `pins.py` ceilings), AUT-5 (engine modes and per-mode `KIND_MASK`, policy ruling and drill clause, watch actor, supervisor signals I-5a.1–3, ROOT_ADMIT), AUT-6 (`deliver_with_proof`, intraday producer, `fee_schedule` DRIFT verdict, permit and drawdown verdicts, evaluation of `DRILL_INJECT`/`DRILL_INJECT_HALT`), AUT-1 (C1 `drill` flag writer), AUT-2 (C2 `excluded_reason=drill`, post-STOP and intraday `RECONCILIATION` with open positions by family) |
| Downstream | AUT-5 live proof (AUT-7b is its PROMOTE/DEMOTE/RESUME evidence), AUT-6 (DEMOTE **and HALT** action classes proven live, ARCH P6-4), AUT-4 (live n and the KILL clock exclude drill fills) |

This is a plan only; nothing in it is implemented. All times are UTC. Runtime paths are absolute under the state root `/home/jon/.local/share/breezy/` (ARCH `~/.local/share/breezy/`); repo paths are repo-root-relative.

## 1. Goal state

**README score-3 criterion (verbatim):**
- The registry keeps an immutable champion history.
- An automated rollback to the last good champion fires on the AUT-5 or AUT-6 triggers and takes effect within one supervisor cycle, with no code change.
- A failed rollback fails closed by halting the family.
- Drills run on a schedule in the gate and live.

**Live proof (verbatim):** "tracked as AUT-7b, with its own clock of at least 4 trading days: one live rollback drill through the production path, restoring the prior champion and its byte-identical artefact sha, logged, alerted and reversed, with no human commit (ARCH §5.3). After the 2027-01-25 KILL, the state defined in ARCH §5.3 applies."

**ARCH Rev 9.2 §10 AUT-7 obligations (verbatim):** "rollback-target selection (most recent `rollback_eligible`, not `terminal_frozen`, bytes re-verified); the C5 failed-rollback rules (`ROLLBACK_FAILED`, `target_integrity`), no new `cause_code` (ROLLBACK-FAILURE); the three P7-7 values; fee via the AUT-6 verdict (P7-11); the advisory 15:30Z intent check (P7-6); the gate drill (AUT-7a); the live drill steps for AUT-7b — with `fq_v1` CHAMPION and not `demoted_for_cause` (W2), mint the byte-identical child `pm_us_crh_fq_v1_r0001` (C3 no-new-lineage), DRILL_ADMIT it, DRILL_PROMOTE at LAUNCH (`fq_v1` superseded and rollback-eligible, W3), write the drill marker so `DRILL_INJECT` demotes it through the live path, remove the marker so the verdict PASSes, RESUME (DRILL class), write the `DRILL_INJECT_HALT` marker so it HALTs, ROLLBACK to `fq_v1` (child DISPLACED; P6-4) — with dates, the drill budget, and the evidence (chain, export, node log, delivery records); the §5.3 timeline and 27-day start rule (P7-14); `TARGET_INELIGIBLE` rows and first-LAUNCH target integrity (V11); the marker `ERROR` rule, its directory-descriptor read (U7) and first cause wins (V12); `drill_demotes`, `drill_halts` (V15)."

Where each obligation lands: selection §3.3.2; failed-rollback rules §3.5; P7-7 §3.3.4 and §3.6.3; P7-11 E6/G-6; P7-6 §3.4; AUT-7a §3.6.1; AUT-7b §3.6.5; timeline and start rule §3.6.3 G-2; V11 §3.5 R2/R5; U7/V12 §3.6.5 marker; V15 §3.6.7. Errata E-5 (restorative RESUME) lands in §3.5.2 step 0 and §3.6.6 step 4; errata E-2 (stale halt mirror) in §3.4 and G-1/E8.

**How "failed rollback → HALT" is read (ARCH C5 "Failed rollback", binding; no reading of our own).**
- A failure (no eligible target, rollback budget exhausted, pair lapsed or SWAP_CANCELled) writes HALT `cause_code=rollback_failed`, class `ROLLBACK_FAILED`, `trigger_cause_class` = the trigger's class, **on the champion if it still folds CHAMPION**. It halts only that family: no venue freeze, no `terminal_frozen`, no RETIRE, no budget charge, never `RECOVERABLE_INFRA` (P7-8). The daily or pre-launch pass retries daily; a success displaces it. A CRITICAL goes through `deliver_with_proof`.
- In production the outgoing family F is already HALTED by its own trigger, so a failed rollback normally writes **no** new row: F stays HALTED (entries vetoed, exits live). A `rollback_failed` row exists only when a family still folds CHAMPION: a ROLLBACK target that took effect and then failed after 17:00Z (R6, R7a), the drill child when its closing ROLLBACK fails while it is CHAMPION (§3.6.6 step 3), or the root `fq_v1` when the drill's closing ROLLBACK took effect and then failed after 17:00 (R5/R6/R7a on the closing pair; `trigger_cause_class=DRILL`). That last case exits by the errata E-5 restorative RESUME (§3.6.6 step 4). This matches ARCH §4.5 "`MAX_ROLLBACKS_PER_VENUE_30D` ≤ 2, then a rollback trigger HALTs as `ROLLBACK_FAILED`" because a HALT applies only to a CHAMPION.
- **Target integrity.** A manifest or artefact sha mismatch at selection, at ACTIVATE or at the target's first LAUNCH makes the target ineligible by a `TARGET_INELIGIBLE` row (`cause_code=target_integrity`), with a CRITICAL. Selection moves on to the next candidate. The target was never loaded, so nothing freezes.
- **Champion's own bytes past its first LAUNCH** are a genuine INTEGRITY event with the existing freeze. That HALT is written by the AUT-5 engine from the P7-10 load signal, not by AUT-7 (§3.5 R7b).
- AUT-7 introduces **no** `cause_code`. It writes only the ARCH enum members `rollback_failed` (HALT) and `target_integrity` (TARGET_INELIGIBLE, SWAP_CANCEL), plus the RESUME cause `drill_close_restore` that errata E-5 defines (binding on every area plan, not an AUT-7 invention). It relies on `DRILL_INJECT`/`DRILL_INJECT_HALT`, which come through the C6 verdict path.

ARCH Rev 9.2 content consumed unchanged:
- C3 no-new-lineage (Y2) and the bootstrap root copy (P7-5): the resolver reads every family's artefact from `/home/jon/.local/share/breezy/derived/artefacts/<model_class>/<sha>/artefact.json`, so a ROLLBACK to `fq_v1` restores the BOOTSTRAP-row sha even if the repo file changes.
- The C5 rows ROLLBACK (with its ACTIVATE in one 16:45 transaction, P7-4; dwell, age, fee, sha re-verification, V11), DRILL_ADMIT, DRILL_PROMOTE, ACTIVATE (re-verifies the incoming shas, V11), SWAP_CANCEL, TARGET_INELIGIBLE (V11, P7-13), SUPERSEDE (W3: only the minted drill child is never made eligible), DISPLACED, DEMOTE/HALT (first cause wins, V12; failed rollback, P7-3), RESUME (incl. `ROLLBACK_FAILED` under its `trigger_cause_class`; every cause cleared, V12; 16:45Z only, P7-9), RETIRE and ROOT_ADMIT (V6, AUT-5's).
- The root exemption (P7-1): `fq_v1` resolves under its own `_LIVE_ORDERS_ALLOWLIST` triple; the policy-ruling rule binds children only.
- §4.2 child identity (V10, U1, R9.2-Z1): `d0_climate_day` ≥ the `effective_launch_date` of the child's first →CHAMPION row that took effect in the fold, and > every earlier d0 in the lineage; ROLLBACK and RESUME exempt.
- C6 `DRILL_INJECT → DEMOTE` and `DRILL_INJECT_HALT → HALT`, both class `DRILL`, only under the drill clause, read through a verified directory descriptor (U7).
- §4.4: no intraday RESUME horizon; RESUME only at 16:45Z; the 15:30Z pending write uses the intraday RECONCILIATION (W8); 15:30Z intent check advisory, 16:45Z and LAUNCH authoritative (P7-6); 16:52:30 is the guaranteed post-launch SWAP_CANCEL slot, 16:57:30 best-effort (V7).
- §4.5: `ROLLBACK_MIN_DWELL_H` ≥ 24, `ROLLBACK_TARGET_MAX_AGE_D` ≤ 30, `DRILL_MIN_DRAWDOWN_HEADROOM_FRAC` ≥ 0.5 (P7-7); `MAX_ROLLBACKS_PER_VENUE_30D` ≤ 2; `DRILL_BUDGET_PER_VENUE_30D` ≤ 1 with each drill counter (incl. `drill_demotes`, `drill_halts`) ≤ 1 and refused above (V15); `RESUME_COOLDOWN_H` ≥ 24; the W1 ATTEST invariant; the Z3 counting rule.
- C5 entry veto: `registry_attest_expired` armed only by an ATTEST dated after the family's latest →CHAMPION or RESUME row (V5); until then `registry_chain_stale` bounds it.
- §5.2 launch-window table, §5.3 drill contract and timeline (P7-14), the node HWM, the W5 auto-clear of `registry_halted`, and the C2 W12 invariant (drill fills feed risk).

## 2. L-1 null hypothesis and reuse

| New component | Capability checked first (file:line) | Verdict |
|---|---|---|
| Champion history | Nautilus has no artefact registry or champion state (ARCH §2 L-1). C5 `transitions` (ARCH-0) is append-only, hash-chained and trigger-protected. | **No new store or table.** History is a pure fold over the verified venue chain, never the `families`/`projection` caches (Y4). |
| Target byte verification | `load_family_manifest` hashes raw bytes once (`family_manifest.py:285-296`). `load_live_calibration` reads once and hashes that buffer (`calibration_artefact.py:250-256`) but follows symlinks (G38). The resolver's byte binding (C5 Pickup Y6) reads from the C3 store (P7-5). | **Reuse the resolver's per-row byte binding** (consumed as `verify_family_bytes(row)`), so selection, ACTIVATE and LAUNCH verify with one implementation. No second verifier. |
| Fee-verified state | `FeeDriftProbeActor.is_fee_verified` (`fee_drift_probe.py:543-584`) is node memory, staleness `_FEE_VERIFIED_STALENESS_NS` = 4 h (`:184`), unset at boot (G39). | The engine cannot call it. **Reuse AUT-6's `fee_schedule` DRIFT verdict** (P7-11). AUT-7 adds no reader of its own. |
| Open/AMBIGUOUS intent | `probe_open_intent` (`trade_supervisor.py:402-420`) asserts no live node (`:411`) and treats a corrupt singleton as OPEN (`:418-419`). | Reuse: **binding only in the 16:45 pass** (node down). The 15:30 pass uses AUT-5's advisory read through the G6 `mode=ro` URI (P7-6). |
| Position handoff | `_EXIT_RULE_REGISTERED_FAMILIES = {"pm_us_crh_exit_v4"}` (`exit_gate.py:55`); `family_declares_exit_rule` requires the id literal and a non-None `exit_rule` (`:58-67`), so a child id is never exit-capable. FQ has no exit (G17). | **Reuse `family_declares_exit_rule`** for the ownership predicate (§3.3.3). |
| Rollback write | C5 ROLLBACK row and partner through AUT-5's `RegistryStore.append(rows, *, expected_prior_seq, mode)` (one `BEGIN IMMEDIATE`, idempotent `transition_id`, per-mode `KIND_MASK`). | Reuse. AUT-7 adds a planner, not a writer. |
| Rollback/readiness journal | ARCH §5.1 puts the rollback journal in ARCH-0 (Wave 0). | **Reuse the ARCH-0 module** (`src/breezy/persistence/autonomy/rollback_journal.py`, name per ARCH-0). AUT-7 adds record kinds and export-head verification after ARCH-0 merges. |
| Target ineligibility | ARCH Rev 9.2 C5 `TARGET_INELIGIBLE` row (`cause_code=target_integrity`). | **Reuse the row.** r3's journal-only status is withdrawn; the journal keeps a mirror record and the clearing evidence (§3.5 R2). |
| "Halt the family" | Exec-store `record_policy_halt` (`trial_day_latch.py:1155-1191`) needs the node flock (G6), blocks exits (G5) and is CLI-cleared. | **Rejected.** Use the registry HALT row (entry-only, exits live). |
| Launch-time pickup | STOP 16:40, LAUNCH 16:50, window closes 17:00 (`trade_supervisor_core.py:37-59`, G22); the AUT-5a resolver at LAUNCH. | Reuse. A rollback is only registry rows. |
| Post-effect verification | AUT-5a's journaled supervisor signals (`launch_target_integrity`, `launch_precheck_failed`) and node lines (`registry_resolved`, `registry_composed`, `registry_boot_load_failed`), I-5a.1. Today's boot line `fq_live_orders … calibration_sha256=<manifest pin>` (`app/trade.py:753-762`) is interim only. | Reuse; no new log line. |
| Drill child manifest | `deploy/families/pm_us_crh_fq_v1.json` (`trial_id_prefix` `forecast_quantile_ladder/trial/pm_us_crh_fq_v1/`, `d0_climate_day "2026-10-02"`, `density_artefact_sha256 9c0b6d6e…923a5e`, lines 4-10). d0 is a settlement/tally admission lower bound (`family_manifest.py:13-48`, `settlement/family_barrier.py:80`), not a trading gate. Child ids `<root>_r<NNNN>` match both regexes (`settings.py:115`; `trial_day_latch.py:301`). | Reuse the root bytes; the child changes exactly **4** keys (§3.6.4). |
| DRILL_INJECT / DRILL_INJECT_HALT | C6: two `VERDICT` ids over one marker `registry/drill/marker.json`, read through a verified directory descriptor (U7). Nautilus has no fault-injection facility. | New and tiny: one detector class parameterised by id (§3.6.5). |
| Node pickup of DEMOTE/HALT | `RegistryWatchActor` (AUT-5); W5 auto-clear. | Reuse. AUT-7 adds no node code. |
| Delivery proof | `deliver_with_proof` (AUT-6, §4.6). `emit_alert` swallows failures (G25). | Reuse for every AUT-7 CRITICAL and every drill event the bundle cites. |
| Recovery with no sender | ROOT_ADMIT (C5 V6, AUT-5). | Consumed, never written by AUT-7. |
| Restoring the root after a failed drill close | C5 RESUME row (16:45 only, P7-9) as amended by errata E-5: `cause=drill_close_restore`, store counter `drill_close_restores` (≤ 1 per venue per day), charged to no drill counter and no production resume budget. | **Reuse the RESUME row** with the E-5 cause. AUT-7 adds a planner predicate only (§3.6.6 step 4). |
| Exec-store halt state at 16:45 | The engine's read-only exec-store halt mirror (ARCH C5 "Exec-store halt mirror"; `HALT_MIRROR_MAX_AGE_S` ≤ 180). | **Reuse.** The 16:45 pass writes its own mirror first; G-1, E8, E9 and the E-5 predicate read only that fresh mirror (errata E-2). |
| Drill evidence bundle | The AUT-5 daily engine pass at 15:30. | Emitted from that pass on D+4. No new unit. |

**F-1 (closed in ARCH).** The phantom containment base (G34) is fixed by the C5 four-site widening, owned by AUT-5. AUT-7 makes no edit to `src/breezy/persistence/family_manifest.py`.

**F-2 (still open in code; gates WP3).** Today FQ composition passes a manifest **path** (`app/trade.py:788-789`) and `load_live_calibration` re-reads it (`calibration_artefact.py:250`), following symlinks (G38). ARCH P7-10 closes this: the node passes the resolver's content-addressed store path and the authorising row's `artefact_sha256`, and the loader's one-buffer read-hash-parse (widened to `O_NOFOLLOW`) re-verifies by sha at load (`test_node_loads_artefact_from_store_by_row_sha`). Until that handoff (I-5a.3) is live, WP3 does not activate (§4).

## 3. Design

### 3.1 Modules

All AUT-7 logic is pure library code in `src/breezy/persistence/autonomy/`, inside the engine's import closure, so `ENGINE_SOURCE_SHA256` is re-pinned in the same commit (§4.3, append-only, Z9). AUT-5's engine phases (`src/breezy/analysis/autonomy_engine/`) call it; AUT-5's `src/breezy/analysis/autonomy_engine/drill.py` is the phase adapter and holds no drill logic.

| File | Purpose | Key interfaces |
|---|---|---|
| `src/breezy/persistence/autonomy/rollback.py` | Champion history, trigger, target eligibility, precedence, dwell timing, planner, failure classification, readiness. | `champion_history(chain, journal, now_ns) -> tuple[ChampionEpoch, ...]`; `rollback_trigger(fold, chain, now_ns) -> RollbackTrigger \| None`; `target_eligibility(epoch, f_epoch, chain, evidence, now_ns) -> Eligibility` (E1–E11, each with a reason code); `select_rollback_target(history, chain, evidence, now_ns) -> TargetSelection` (returns the chosen target plus any `TARGET_INELIGIBLE` rows to write first); `dwell_ok(chain, launch_ns) -> bool`; `prelaunch_decision(fold, chain, evidence, now_ns) -> PrelaunchDecision`; `plan_rollback(trigger_or_drill, selection, ports) -> RollbackDecision`; `classify_failure(x) -> RollbackFailure`; `failed_rollback_halt(fold, failure, trigger_cause_class) -> TransitionRow \| None`; `target_ineligible_row(epoch, reason) -> TransitionRow`; `readiness(chain, evidence, ports) -> ReadinessRecord` |
| `src/breezy/persistence/autonomy/drill.py` | AUT-7b sequencer (a state machine derived from the chain, never stored), child composer, allocator, marker writer/remover, episodes, bundle builder. | `drill_state(chain, journal, now_ns) -> DrillState`; `next_drill_child_id(chains, root) -> str`; `compose_drill_child(root_bytes, child_id, policy_ruling_id, d0_climate_day) -> bytes`; `drill_arm_gate(fold, chain, evidence, now_ns) -> GateResult` (15:30); `drill_start_gate(fold, chain, evidence, now_ns) -> GateResult` (16:45, G-1..G-13); `genuine_cause_since_drill_promote(family_id, chain, fresh_mirror, promote_seq) -> bool` (shared by E9, the marker pre-check and E-5); `restorative_resume_decision(fold, chain, evidence, fresh_mirror, now_ns) -> TransitionRow \| None` (E-5); `sweep_stale_marker(drill_dir, chain, journal, now_ns) -> SweepResult` (G4); `next_drill_step(state, clause, mode, now_ns, ports) -> DrillStep`; `drill_episodes(chain) -> tuple[DrillEpisode, ...]`; `is_drill_fill(episodes, family_id, ts_ns) -> bool`; `build_drill_bundle(episode, ports) -> DrillBundle` |
| `src/breezy/persistence/autonomy/drill_inject.py` | The C6 `DRILL_INJECT` and `DRILL_INJECT_HALT` `VERDICT` detectors (one class, two ids). | `DrillMarkerDetector(detector_id).evaluate(drill_dir_path, chain_view, clause, now_ns) -> DetectorOutcome` |
| `src/breezy/persistence/autonomy/post_verify.py` | Post-effect verification against AUT-5a's supervisor signals and node lines. | `post_verify(launch_date, chain, signals, boot_lines, now_ns) -> PostVerifyResult`; `classify_boot_failure(signals, lines, first_launch: bool) -> BootFailure \| None` |
| ARCH-0 `src/breezy/persistence/autonomy/rollback_journal.py` (extended, not created) | Record kinds `rollback_decision/v1`, `readiness/v1`, `target_status/v1`, `drill_episode/v1`; verification against the newest export (T7). | `append_journal(kind, venue, record) -> JournalHead`; `verify_journal_chain(kind, venue, newest_export) -> JournalHead \| JournalUnverified` |

**Engine wiring.** AUT-5's phases call `rollback.step(mode, …)` and `drill.step(mode, …)`. AUT-7 edits no `src/breezy/app/trade.py`, `src/breezy/runtime/settings.py` or `src/breezy/runtime/trade_supervisor*.py` (ARCH §5.1). Writes go through `RegistryStore.append(..., mode=…)`. AUT-7 needs these kinds in AUT-5's per-mode `KIND_MASK` (§5; A-1):

| Mode (engine slot, §5.2) | Kinds AUT-7 writes | Other AUT-7 effects |
|---|---|---|
| `daily` 15:30 (node up; `-w` ≤ 120 s, ends ≤ 15:47) | MINT, DRILL_ADMIT, the **pending** DRILL_PROMOTE + SUPERSEDE pair (`effective_launch_date` = today), all in one transaction; RETIRE of a closed or failed drill child | advisory intent check (P7-6); intraday RECONCILIATION check (W8); readiness; bundle on D+4 |
| `prelaunch` 16:45 (node down; `-w` ≤ 60 s, `TimeoutStartSec` ≤ 180 s, ends ≤ 16:49) | ACTIVATE or SWAP_CANCEL (+ TARGET_INELIGIBLE on a sha failure) for a pending drill pair; TARGET_INELIGIBLE for a failing candidate, then ROLLBACK + SUPERSEDE/DISPLACED + ACTIVATE in **one** transaction (P7-4); RESUME, incl. the E-5 restorative RESUME (`cause=drill_close_restore`); HALT `rollback_failed` on a drill child that folds CHAMPION with no rollback possible | **first** the pass's own exec-store halt mirror (errata E-2); then binding `probe_open_intent`; post-STOP RECONCILIATION; G-1..G-13; E1–E11 |
| `intraday` (every 5 min, 150 s after the producer; restrictive-only, W1) | DEMOTE, HALT (incl. `rollback_failed`), SWAP_CANCEL, TARGET_INELIGIBLE (first-LAUNCH target integrity, V11) | **first** the stale-marker sweep (§3.6.5, G4), then drill marker write and unlink; `post_verify` |

**Single decision per venue per 16:45 pass.** `prelaunch_decision` returns at most one widening action per venue (drill step, RESUME or ROLLBACK). Restrictive rows (TARGET_INELIGIBLE, SWAP_CANCEL, HALT) are not limited.

### 3.2 Immutable champion history (criterion 1)

`ChampionEpoch` is a frozen dataclass with explicit serialisation. Fields:
- `venue`, `family_id`, `lineage_root_family_id`, `manifest_sha256`, `artefact_sha256` (from the family's BOOTSTRAP/MINT row, Z1);
- `entered_venue_seq`, `entered_kind` (`BOOTSTRAP`\|`PROMOTE`\|`DRILL_PROMOTE`\|`ROLLBACK`\|`RESUME`\|`ROOT_ADMIT`), `effective_from_ns`;
- `left_venue_seq | None`, `left_kind` (`SUPERSEDE`\|`DEMOTE`\|`HALT`\|`DISPLACED`\|`RETIRE`\|None), `left_cause_class`, `left_trigger_cause_class` (on a `rollback_failed` HALT only), `left_cause_code`, `left_effective_ns | None`;
- `rollback_eligible`, `demoted_for_cause`, `target_integrity_ineligible`, `drill_child` (the subject of a DRILL_ADMIT row, W3);
- `last_attest_ns | None`: the newest ATTEST for this family dated **after its latest →CHAMPION or RESUME row** (V5 arming rule), while CHAMPION.

How the history is built and protected:
- **Derivation.** A pure fold over `transitions` from genesis, checked by the AUT-5 verifier (hash links and the newest-export prefix), using the `resolve_champion` fold rule (Y8): pending, lapsed and voided pairs create no epoch (Z3).
- **Derived flags, never cached.** SUPERSEDE sets `rollback_eligible` unless the subject is a drill child (W3). DEMOTE and HALT (any class, incl. `DRILL` and `ROLLBACK_FAILED`) clear it and set `demoted_for_cause`. DISPLACED never sets it. A SWAP_CANCEL carrying a cause on the incoming family sets `demoted_for_cause` (Y8).
- **Target integrity is on the chain.** A `TARGET_INELIGIBLE` row sets `target_integrity_ineligible` for that family. It clears only by AUT-7's re-verification rule (§3.5 R2), never by an operator. Because ARCH names no clearing row, the clear is read from the verified rollback journal (A-2). If the journal is unverified the flag stays set (fail-closed).
- **Immutability.** No new mutable state. History inherits the `BEFORE UPDATE/DELETE → RAISE(ABORT)` triggers, the per-venue chain, the 0444 export and the node HWM. The daily pass renders `/home/jon/.local/share/breezy/evidence/registry/champion_history_<venue>_<ts_ns>.json` (0444, write-once) for humans only; a test pins it equal to the fold.

### 3.3 Automated rollback (criterion 2)

#### 3.3.1 Trigger (code-fixed literal; no new policy key)

`rollback_trigger` fires when all of these hold on the fold at `now`:
1. The venue's {CHAMPION, HALTED} slot holds family F in **HALTED**.
2. F's halting row is a DEMOTE or HALT whose cause class is `RECOVERABLE_MODEL` (policy `detector → class` map: live sequential, drawdown, forecast and calibration drift, fill rate, slippage), **or** a `rollback_failed` HALT whose `trigger_cause_class` is `RECOVERABLE_MODEL` (the daily retry, §3.5.2).
3. No pending pair exists on the venue (Y8).

| Cause class on F | Why it never triggers a rollback |
|---|---|
| `RECOVERABLE_INFRA` | A feed, permit or unit fault hits every family alike. RESUME is the cure. |
| `DRILL` | The drill sequencer owns the RESUME and the closing ROLLBACK (§3.6). |
| `TERMINAL` | The lineage is `terminal_frozen`; the store refuses the ROLLBACK and the champion RETIREs. Recovery is AUT-5's ROOT_ADMIT of a reviewed root (C5 V6). |
| `INTEGRITY` | The venue is frozen for ROLLBACK by C5 (Z7, W15). A rollback never **creates** this freeze; it respects one created by an exec-store cause or by the champion's own bytes past first LAUNCH. |
| `ROLLBACK_FAILED` with a non-model `trigger_cause_class` | Its exit is RESUME under that class or a drill closing ROLLBACK (§3.5.2). |

A genuine (non-`DRILL_INJECT*`) `RECOVERABLE_MODEL` fault on a drill child does fire the trigger; E9 then decides (§3.6.6).

#### 3.3.2 Target eligibility

`target_eligibility` walks `champion_history` backwards from F's epoch. The target is the **first** epoch whose family G passes every predicate. Each predicate has a reason code and its own RED test; `readiness()` calls the same function.

| # | Predicate | Source |
|---|---|---|
| E1 | G folds CHALLENGER, `rollback_eligible`, not `demoted_for_cause`, not a drill child | chain fold |
| E2 | G's lineage is not `terminal_frozen` | chain fold |
| E3 | `composition_kind` ∈ `LIVE_GATE_ROUTED_KINDS`; G is a root under `_LIVE_ORDERS_ALLOWLIST` (P7-1) or a child whose root is in `_LINEAGE_POLICY_ALLOWLIST` (`live_orders_gate.py:76-84`) | committed code |
| E4 | **Fresh ATTEST up to departure (AUT-7 selection rule, stricter than the store).** `last_attest_ns` (V5: an ATTEST after G's latest →CHAMPION or RESUME row) is not None and `left_effective_ns − last_attest_ns ≤ ATTEST_PERIOD_H + L_max + ATTEST_MARGIN_H`, where `L_max` = `INTRADAY_ATTEST_VERDICT_PERIOD_MIN` + the 150 s engine offset, all read from the pinned ceilings and policy values the §4.5 W1 invariant uses. At the ceilings 6 + 1.04 + 0.5 = 7.54 h ≤ `ATTEST_VERDICT_VALIDITY_H`. No literal 1.04 in code. | chain; `pins.py`; policy block |
| E5 | **Age cap (P7-7):** `now − left_effective_ns ≤ ROLLBACK_TARGET_MAX_AGE_D` (`pins.py` ceiling ≤ 30; policy value 30) | chain; `pins.py` |
| E6 | **Fee verified (P7-11):** the newest accepted AUT-6 `DRIFT` verdict for `fee_schedule` (from the probe's `DetectorEvent`s) is a PASS within `ATTEST_VERDICT_VALIDITY_H` of `now`; none means unverified. θ equality needs no extra check: §4.2 makes every child's `taker_fee_coefficient` equal its root's. | C4 |
| E7 | **Current `live_orders_ruling`:** a root through its committed allowlist triple with the deploy copy's sha re-verified (`live_orders_gate.py:130-190`); a child names the current policy ruling. One function shared with the resolver. | committed code, ruling file |
| E8 | **No pending cause on G:** no accepted FAIL mapped to DEMOTE/HALT naming G after `left_effective_ns` that a later PASS has not superseded; no demand file naming G; no exec-store halt for G in the **fresh** mirror that this 16:45 pass wrote first (a mirror written before the pass started, e.g. by the 16:41 reconcile, is stale by construction and is never read; errata E-2, `HALT_MIRROR_MAX_AGE_S`) | C4, demand dir, fresh mirror |
| E9 | **No byte-identical remedy (T5).** E9 passes iff **either** G's `artefact_sha256` ≠ F's, **or** both: (i) F's standing state is drill-only, meaning its halting class is `DRILL`, or `ROLLBACK_FAILED` with `trigger_cause_class=DRILL`, or (abort close only) F is the episode's drill child still folding CHAMPION with no halting row; and (ii) `genuine_cause_since_drill_promote(F)` is false: no accepted non-DRILL FAIL mapped to DEMOTE/HALT names F, and no exec-store halt for F stands in the fresh mirror, at any point since the episode's DRILL_PROMOTE row. Clause (ii) matters because first cause wins (V12): a genuine FAIL that arrives after the DRILL HALT writes no row, so F's halting class still reads `DRILL`. Otherwise G's sha must differ from F's. | chain, C4, fresh mirror |
| E10 | **Bytes (V11):** G is not `target_integrity_ineligible`; there is no open `target_status=target_load_failed` journal record for G under the current engine pin (R7a); and the resolver's per-row byte binding on G's BOOTSTRAP/MINT row passes now (single-read manifest and C3-store artefact under `O_NOFOLLOW`, sha equality for **both** manifest and artefact, child-id regex and root, §4.2 equality against the committed root) | resolver; chain |
| E11 | **Child identity (V10/U1):** none needed for a ROLLBACK. The d0 rule binds only a child's first →CHAMPION row, so ROLLBACK to an earlier child is exempt (`test_rollback_to_earlier_child_passes_d0_rule`). Listed so that no implementer adds a d0 check here. | ARCH §4.2 |

Rules applied to the result:
- **A byte failure is skipped, and selection moves on (ARCH C5).** A candidate failing E10's live re-verification gets a `TARGET_INELIGIBLE` row (`cause_code=target_integrity`), a `target_status/v1` journal mirror and a CRITICAL `ROLLBACK_TARGET_INTEGRITY`. Selection then continues to the next older epoch. The corrupt bytes are never loaded, and every older candidate is verified independently. r3's "no fallback past an integrity failure" rule is withdrawn because it contradicts ARCH.
- **Policy failures skip.** A candidate failing E1–E9 is skipped as ineligible, and no row is written.
- **Budget.** `MAX_ROLLBACKS_PER_VENUE_30D` (≤ 2), counted at effect, with pending pairs as reservations (Z3). Drill ROLLBACKs count only against the drill budget.
- **Journal verified.** No ROLLBACK is planned unless both journals verify against the newest export (§3.5.3, T7).
- **Engine input journal.** A pass that cannot write its `engine_input/v1` journal writes no ROLLBACK (C5 P4-9).

#### 3.3.3 Position handoff invariant

**Every open position held under the outgoing family id has an owner after the swap.** `position_handoff_ok(outgoing, incoming, recon)` holds iff either:
- (a) `recon.open_positions_by_family[outgoing] == ∅`, from the post-STOP `RECONCILIATION` verdict (16:41, ARCH §4.4); or
- (b) the incoming family owns them: `family_declares_exit_rule(incoming) == family_declares_exit_rule(outgoing)` (`exit_gate.py:58`), with the same `composition_kind` and `lineage_root_family_id`, so §4.2 makes `exit_rule` and `no_leg_exit` equal.

For FQ both sides are exit-incapable (G17): positions are held to settlement and reconciled venue-net per slug, so (b) holds. This is consistent with ARCH §4.4 ("flatness is **not** required"). An exit-capable outgoing family (only `pm_us_crh_exit_v4`, seeded RETIRED) never hands off to a child. The check binds at 16:45 for every sender change. **The `INCONCLUSIVE` case applies only to branch (a):** a missing `open_positions_by_family` metric makes (a) undecidable, so the result is `INCONCLUSIVE` and nothing is written, **unless** branch (b) holds. Branch (b) is decided from the two manifests alone and needs no metric, so an owned handoff passes even when the metric is missing (the post-STOP RECONCILIATION PASS is still separately required by §4.4, R4). Successor re-entry stays blocked by `rung_net_position_held` (C5 Y16) and the kind-scoped latch (G28). This is an AUT-7-internal check that is stricter than ARCH; see C-11.

#### 3.3.4 Pre-launch decision, precedence, dwell and damping

`prelaunch_decision` runs once per venue in the 16:45 pass, after the post-STOP reconciliation, and returns **one** widening action:
1. **Drill step** due today (§3.6.5), including the E-5 restorative RESUME of the root after a failed drill close (§3.6.6 step 4). The sequencer owns the slot, and steps 2–3 are skipped. A genuine fault during an episode is handled in §3.6.6.
2. **RESUME of F** if F's `halt_cause_class` is admissible (`RECOVERABLE_MODEL`, `RECOVERABLE_INFRA`, or `DRILL` with `cause_code=DRILL_INJECT`), **or** F is `ROLLBACK_FAILED` with such a `trigger_cause_class` (charged to it). Further conditions: the cause verdict and every DEMOTE/HALT-mapped FAIL accepted since the halt row now PASS; no exec-store halt stands (V12); `RESUME_COOLDOWN_H` is met; that class's budget is available; there is no pending pair; and §4.4 passes. RESUME wins over ROLLBACK because it restores the same verified sender.
3. **ROLLBACK** if `rollback_trigger` stands, a target passes §3.3.2, `dwell_ok` holds, the budget is available, the journals verify and `position_handoff_ok` holds.
4. **Nothing.** The engine journals a reason code and sends a CRITICAL once per day per code (R1, R4).

**Dwell (P7-7, consumed; reverses r3's T6 deletion).** `dwell_ok(chain, launch_ns)` holds iff today's LAUNCH instant is ≥ `ROLLBACK_MIN_DWELL_H` (≥ 24 h) after the effective instant of the venue's previous sender change or RESUME. It **delays, never refuses**: a ROLLBACK that fails dwell is re-planned at the next 16:45 pass and is charged nothing. Drill ROLLBACKs are included. **The dwell never pushes a rollback past the next LAUNCH.** Every sender change takes effect at a LAUNCH (16:50) and a RESUME at a 16:45 pass, and the one-widening-per-pass rule allows at most one of them per day. So the previous effective instant is ≤ the previous day's 16:50, and today's 16:50 LAUNCH is ≥ 24 h after it. A test enumerates every predecessor kind and slot (`test_rollback_dwell_never_delays_past_next_launch`).

**Damping.** AUT-7 adds no constant of its own. Oscillation is bounded by ARCH ceilings and by structure:
- one widening decision per venue per 16:45 pass, under `MAX_SENDER_CHANGES_PER_VENUE_PER_DAY` ≤ 2 (Z3);
- `ROLLBACK_MIN_DWELL_H` ≥ 24, `MAX_ROLLBACKS_PER_VENUE_30D` ≤ 2, `RESUME_COOLDOWN_H` ≥ 24, `MAX_RECOVERABLE_RESUMES_PER_LINEAGE_14D` ≤ 2;
- DISPLACED never sets `rollback_eligible`, so two families cannot ping-pong by ROLLBACK;
- a ROLLBACK requires F HALTED by an accepted cause, and a HALT never charges the rollback budget;
- drill closing and abort ROLLBACKs count only against the drill budget (Z3), but they are subject to the dwell.

**Write.** When step 3 is chosen, any `TARGET_INELIGIBLE` rows from selection are committed first (restrictive, retry-until-commit). Then one `RegistryStore.append(..., mode=PRELAUNCH)` transaction writes:
- the ROLLBACK row (G: CHALLENGER→CHAMPION, with `artefact_sha256`, `manifest_sha256`, `lineage_root_family_id`; Y6);
- its partner DISPLACED row (F: HALTED→CHALLENGER), citing the ROLLBACK's `transition_id` as `paired_transition_id`;
- the `ACTIVATE` row citing the pair, written only after G's manifest and artefact shas are re-verified against its authorising row in the same pass (V11).

All carry `effective_launch_date` = today and `cause_verdict_ids` = F's halting causes. §4.4 runs **before** the write, so a failing check writes nothing (R4). `transition_id`s are deterministic (Y9), so a crash-retry is a no-op.

**Effect within one supervisor cycle.** A qualifying DEMOTE committed before 16:45 on day D takes effect at D's 16:50 LAUNCH. One committed at or after 16:45 takes effect at D+1's LAUNCH. The worst case is ≤ 24 h 05 min, and the dwell adds nothing (above). Entries are already vetoed ≤ 15 min after the cause (C5 SLO), so the wait costs availability, never safety. **No code change:** the supervisor resolves the fold at LAUNCH (G2), and the rollback writes only under `/home/jon/.local/share/breezy/{registry,evidence}`.

**Gate-proven versus live-proven.** While `promote_enabled=false` (expected, ARCH §4.2 Y12), the only SUPERSEDE that makes a family `rollback_eligible` is a DRILL_PROMOTE. Outside a drill episode there is no eligible target, so the trigger→ROLLBACK chain **cannot fire live**; readiness reports `NO_TARGET` as INFO. The trigger leg is gate-proven (AUT-7a). AUT-7b proves live the same `plan_rollback` → write+ACTIVATE → resolver → node path, invoked by the sequencer.

### 3.4 Preconditions per mode

| Check | Daily 15:30 (node up) | Pre-launch 16:45 (node down) | Supervisor LAUNCH 16:50 |
|---|---|---|---|
| Rows AUT-7 writes | MINT, DRILL_ADMIT, pending drill pair; RETIRE | ACTIVATE/SWAP_CANCEL for the drill pair; TARGET_INELIGIBLE; ROLLBACK + partner + ACTIVATE; RESUME; drill-child `rollback_failed` HALT | — |
| Open/AMBIGUOUS intent | **advisory** read via the G6 `mode=ro` URI (corrupt = OPEN); OPEN → no drill pair written that day (P7-6) | **binding** `probe_open_intent` | binding re-check; failure → `launch_precheck_failed`, nothing launched (§4.4) |
| `RECONCILIATION` | newest accepted **intraday** PASS within `ATTEST_VERDICT_VALIDITY_H` (W8; `test_pending_write_uses_intraday_reconciliation`) | PASS produced after today's STOP (16:41 unit), incl. `open_positions_by_family` | reuses the 16:45 verdict |
| Position handoff (§3.3.3) | — | required for every sender change | — |
| Target eligibility E1–E11 | readiness only (journal + CRITICAL; no row) | required; E10 failure → TARGET_INELIGIBLE | resolver re-runs byte binding (Y6); failure → `launch_target_integrity` |
| Sha re-verification of the incoming family | — | at ACTIVATE (V11) | at load, by row sha (P7-10) |
| Exec-store halt mirror (errata E-2) | the daily pass's own mirror read (advisory) | written **first** in the pass; G-1, E8, E9 and E-5 read only this fresh mirror; a mirror older than the pass start (e.g. from the 16:41 reconcile) is never read (`HALT_MIRROR_MAX_AGE_S`) | — |
| Drill gates | `drill_arm_gate` (G-1..G-7, G-9, G-11, G-12, G-13; G-5 in its intraday form; advisory intent instead of G-8) | `drill_start_gate` G-1..G-13, binding | — |
| Budgets, dwell, lineage freeze, INTEGRITY freeze, journal verification | readiness reports them | required | resolver refusals |
| RESUME (incl. drill RESUME and the E-5 restorative RESUME) | — | **only here** (P7-9; `test_resume_written_only_at_prelaunch`) | — |

A pending drill pair is inert. It takes effect only with an ACTIVATE written at 16:45 after G-1..G-13 pass (C5 fold); otherwise it is SWAP_CANCELled or lapses, uncharged (Z3).

### 3.5 Failed rollback fails closed (criterion 3)

No rollback failure freezes the venue (ARCH C5 "Failed rollback"; P7-8). Reason codes below (`no_target`, `journal_unverified`, `target_load_failed`, …) are **journal and alert reason codes**, not C5 `cause_code` values.

| # | Failure | Detected by | Effect |
|---|---|---|---|
| R1 | No eligible target; rollback budget exhausted; journal unverified (§3.5.3); venue INTEGRITY-frozen by another cause | `prelaunch_decision` | F already HALTED: **no row**, F stays HALTED (entries vetoed, exits live). If a family still folds CHAMPION (drill child, §3.6.6): HALT it, `cause_code=rollback_failed`, class `ROLLBACK_FAILED`, `trigger_cause_class=DRILL`. Journal `{trigger, decision, reason_code, attempt_n}`; CRITICAL `ROLLBACK_UNAVAILABLE` via `deliver_with_proof` once per day per reason. Retried at every 16:45 pass. No budget charged. **Dwell not yet met is not a failure:** it is journaled `dwell_wait` (INFO) and re-planned next pass (§3.3.4). |
| R2 | A candidate's bytes fail live re-verification at selection (manifest or artefact sha, symlink, missing, §4.2 inequality) | resolver byte binding, called by `select_rollback_target` | `TARGET_INELIGIBLE` row on G (CHALLENGER→CHALLENGER, `cause_code=target_integrity`; restrictive, never capped or counted), journal mirror `target_status/v1 {artefact_sha256, manifest_sha256, status: target_integrity}`, CRITICAL `ROLLBACK_TARGET_INTEGRITY`. **Selection moves on** to the next older candidate in the same pass. Nothing is frozen and the bytes are never loaded. **Clearing rule (AUT-7's, as ARCH requires; never an operator):** two consecutive daily readiness re-verifications ≥ 24 h apart pass on the same bytes, each journaled, and then `target_status {status: cleared}` is appended. The flag clears in the fold only while the journal verifies against the newest export (A-2). |
| R3 | CAS failure on the write | store | Non-restrictive: re-read, re-evaluate, retry once, then CRITICAL; retried next pass. A restrictive row (`rollback_failed` HALT, TARGET_INELIGIBLE, SWAP_CANCEL) retries until committed and writes a demand file if the first attempt fails (Y19, Z11). |
| R4 | §4.4 fails at 16:45 (intent OPEN/AMBIGUOUS, post-STOP reconciliation missing/INCONCLUSIVE/FAIL, handoff not owned) | `prelaunch_decision` | **Nothing written**, because the checks precede the write. F stays HALTED and boots entries-vetoed (Z7). CRITICAL `ROLLBACK_DEFERRED`. Retried daily. `consecutive_deferred` is journaled and never escalates. In the drill case where the child folds CHAMPION, R1's HALT rule applies. |
| R5 | **First LAUNCH of the pair fails** (V11): the resolver's byte binding or the load refuses the incoming family (byte drift 16:45→16:50), signalled by AUT-5a's journaled `launch_target_integrity`; or the supervisor's LAUNCH re-check fails while ACTIVATE stands (`launch_precheck_failed`) | `post_verify` reading AUT-5a signals (I-5a.1) | The supervisor launches nothing. **16:52:30 intraday pass (guaranteed slot, V7):** for `launch_target_integrity`, SWAP_CANCEL (`cause_code=target_integrity`, Z8) + TARGET_INELIGIBLE on G in one transaction; for `launch_precheck_failed`, SWAP_CANCEL with no cause (§4.4 failed). The fold restores the incumbent (F HALTED, relaunched entries-vetoed; or `fq_v1` CHAMPION for a drill pair). 16:57:30 is best-effort. **If neither commits by 17:00,** the pair stays effective (never voided after 17:00) and G folds CHAMPION without having loaded. For a ROLLBACK pair: HALT G `rollback_failed`, `ROLLBACK_FAILED`, `trigger_cause_class` = F's trigger class, plus journal `target_status {status: target_integrity}`. A TARGET_INELIGIBLE row cannot be written on a non-CHALLENGER family, and the HALT's `demoted_for_cause` already excludes G as a target (A-3). For the **opening** drill pair (DRILL_PROMOTE): the abort path (§3.6.6). For the drill's **closing** ROLLBACK pair, G is the root `fq_v1` and F's trigger class is `DRILL`, so the HALT carries `trigger_cause_class=DRILL` and the exit is the E-5 restorative RESUME (§3.6.6 step 4). A chain or HWM fault is AUT-5's venue-wide `REGISTRY_UNAVAILABLE` path. |
| R6 | Post-effect mismatch: the boot lines for the effective LAUNCH name a different `family_id`, `registry_seq`, `manifest_sha256` or `artefact_sha256` than the authorising row; or no composed line by 17:30 | `post_verify` at 16:52:30, 16:57:30, then every intraday pass from 17:02:30 | Before 17:00: as R5 (sha mismatch → target integrity; otherwise SWAP_CANCEL with no cause). From 17:00 a mismatch HALTs G at once: `rollback_failed`, `ROLLBACK_FAILED`. A missing line is re-checked each pass and HALTs at the first pass ≥ 17:30 (17:32:30) if still absent. CRITICAL `ROLLBACK_FAILED`. No venue freeze. |
| R7a | **Load failure on verified bytes** at the first LAUNCH (strict-load or plug-in refusal), signalled by I-5a.1 `registry_boot_load_failed … reason≠sha_mismatch` | `classify_boot_failure(first_launch=True)` | The supervisor does not relaunch that resolved family before the next LAUNCH and triggers the intraday pass (I-5a.2). In [16:50, 17:00): SWAP_CANCEL with no cause on G (an engine-detected inconsistency) restores the incumbent. From 17:00: HALT G, `rollback_failed`, `ROLLBACK_FAILED`. Journal `target_status {status: target_load_failed, engine_code_sha}`: G is ineligible (E10) until the engine pin rotates through the reviewed build-side fix. CRITICAL `ROLLBACK_FAILED`. No crash loop. |
| R7b | **Champion's own artefact mismatch at load past its first LAUNCH** (`registry_boot_load_failed … reason=sha_mismatch`, P7-10) | AUT-5 engine; AUT-7 `classify_boot_failure(first_launch=False)` only classifies | A genuine INTEGRITY event with the existing freeze (ARCH C5). **The HALT is written by the AUT-5 engine**, not by AUT-7, and AUT-7 writes no row for it. AUT-7 then sees an INTEGRITY freeze and plans no ROLLBACK (R1). This covers the drill child's boot after its RESUME at D+2. It is gate-proven only. |

**Every failure ends with no family sending new entries on an unverified path.** Nothing loads unverified bytes, and only R7b (the champion's own bytes past first LAUNCH) freezes. The journal records `{trigger, target, decision, reason_code, attempt_n, chain_head, prev_sha256}`.

#### 3.5.1 Rows written by AUT-7 on failure

- **HALT, one shape only:** `kind=HALT`, CHAMPION→HALTED, `decided_by=engine`, `cause_verdict_ids=[]`, `cause_code=rollback_failed`, `halt_cause_class=ROLLBACK_FAILED`, `trigger_cause_class` ∈ {`RECOVERABLE_MODEL` (production trigger), `DRILL` (drill close: on the child in §3.6.6 step 3, or on the root when the closing pair fails after 17:00, §3.6.6 step 4)}. Restrictive, always permitted, never counted. The pre-launch pass writes it in the drill-child R1 case; the intraday pass writes it for R5/R6/R7a after 17:00 (W1). A pending pair naming the family is voided in the same transaction (C5 DEMOTE/HALT row).
- **TARGET_INELIGIBLE:** CHALLENGER→CHALLENGER, `cause_code=target_integrity`, written at selection (16:45), at ACTIVATE (16:45) or for a first-LAUNCH failure (16:52:30 with its SWAP_CANCEL). Restrictive, never capped, never counted.
- **SWAP_CANCEL:** `cause_code=target_integrity` with a TARGET_INELIGIBLE (R5, ACTIVATE re-verification), or no cause for a §4.4 or load failure (R5, R7a).
- AUT-7 writes no INTEGRITY-class row, and no `cause_code` outside {`rollback_failed`, `target_integrity`}. DRILL-class DEMOTE/HALT rows come from the C6 detectors through the normal verdict path.

#### 3.5.2 Exit path for a `ROLLBACK_FAILED` family (ARCH C5 RESUME row)

A `ROLLBACK_FAILED` family resumes only under its `trigger_cause_class`, charged to that class, with one errata exception (step 0). In order:
0. **Restorative RESUME (errata E-5), root only.** When the family is the incumbent root halted because the drill's closing ROLLBACK to it failed after 17:00 (`trigger_cause_class=DRILL`), the 16:45 pass writes RESUME `cause=drill_close_restore` under the §3.6.6 step 4 conditions, charged to no drill counter and no production resume budget. It never applies to the drill child or after a genuine fault.
1. **RESUME** at a 16:45 pass, when the trigger class is RESUME-admissible, every DEMOTE/HALT-mapped FAIL accepted since the halt row now PASSes, no exec-store halt stands, `RESUME_COOLDOWN_H` is met and that class's budget is available (V12, Z10). For `trigger_cause_class=DRILL` this charges `drill_resumes`, which is normally already spent in the episode, so it is refused and the exit is step 2.
2. **The daily-retried rollback.** The production trigger (§3.3.1 item 2) re-runs selection with this family as F. For a drill child, the closing ROLLBACK is retried with a DISPLACED partner.
3. **RETIRE and ROOT_ADMIT.** A TERMINAL cause, or an exhausted `MAX_RECOVERABLE_RESUMES_PER_LINEAGE_14D`, RETIREs the family. If the venue then has no CHAMPION or HALTED family, AUT-5's ROOT_ADMIT can seat a reviewed root (C5 V6; `root_admit_enabled` under `ROOT_ADMIT_ENABLED_CEILING`, committed `false`; `ROOT_ADMIT_COOLDOWN_H`).

While none of these applies, the family **stays HALTED** with a daily CRITICAL: entries stopped, exits live, no freeze, no `terminal_frozen`. A HALTED `ROLLBACK_FAILED` family occupies the {CHAMPION, HALTED} slot, so ROOT_ADMIT is not available until it RETIREs (K-18).

#### 3.5.3 Journal verification against the newest export (T7)

`verify_journal_chain(kind, venue, newest_export)` runs for both kinds (`rollback_decision`, `readiness`) at the start of every 16:45 pass and every daily readiness run:
1. Select the newest export: the highest `export_seq` for the venue (an HWM_RESET export supersedes, W4), read once under `O_NOFOLLOW`.
2. Read `evidence_journal_heads.{rollback,readiness}` from it (AUT-5 export widening, §5).
3. Walk the journal from genesis by `prev_sha256`; every link must hold.
4. The export's head must be a record on that chain (**mismatch** otherwise), and the journal must extend at or beyond it, with every record after it linking (**missing tail** otherwise).

On any failure (`link_broken`, `export_head_absent`, `tail_missing`, `export_unreadable`): every ROLLBACK (production and drill) is refused as R1 with reason `journal_unverified`; the drill start gate fails G-11; every `target_integrity_ineligible` flag stays set; and CRITICAL `ROLLBACK_JOURNAL_UNVERIFIED` is sent once per day. Restrictive writes and RESUME are never blocked, so the block cannot deadlock its own recovery (L-48). It clears automatically when verification passes again; otherwise it goes to build-side incident handling. Records written after the newest export (≤ 24 h) can only be checked for linkage. That is the stated residual.

### 3.6 Drills (criterion 4)

#### 3.6.1 AUT-7a — gate drill

`tests/integration/autonomy/test_rollback_drill_gate.py` runs in-process, in **every** gate run (`scripts/ci/run_tests_no_egress.sh`; L-43):
- the whole §3.6.5 sequence (incl. HALT);
- the R1–R7b matrix;
- the position-across-swap cases;
- the pre-effect retry with a new child;
- the budget-strand case;
- the dwell enumeration;
- the genuine-fault path.

It uses:
- a fake clock and a tmp `HOME` registry;
- a tmp exec store written through the real writer path (L-42);
- the real AUT-5 store, resolver, fold and engine modes;
- the real `DrillMarkerDetector` (both ids, real directory-descriptor read), the intraday producer and `RegistryWatchActor.tick_once`.

Supervisor LAUNCH is a port that calls the real resolver. The test also runs the production default port once (L-55).

#### 3.6.2 Production readiness

Every daily pass, `rollback.readiness()` runs `target_eligibility` (E1–E11) for the current champion's would-be target, without writing a row. It appends a `readiness/v1` record to the ARCH-0 journal (write-once, `os.link` from a `mkstemp` file, failing if the name exists; L-50). The record reports the per-predicate reason codes, open `target_status` records, the clearing-rule progress, the budgets, the dwell clock and the journal-verification result. A present target failing E10 sends CRITICAL `ROLLBACK_TARGET_INTEGRITY` (the row itself is written at the next 16:45 selection). `NO_TARGET` is INFO while `promote_enabled=false` outside a drill.

#### 3.6.3 AUT-7b schedule and gates

**Drill clause values** (AUT-5 owns the block; proposed within ceilings):
- `drill_cadence_days: 60`, measured from the last COMPLETED episode's closing ROLLBACK.
- `drill_first_eligible_date`: ≥ AUT-5b activation + 3 sessions of soak (§6).
- `drill_inject_utc: "15:00"` (D+1) and `drill_halt_utc: "15:00"` (D+3). The marker is written by the first intraday engine pass at or after that time (15:02:30). `drill_demote_slo_min: 15`, `drill_halt_slo_min: 15`.
- `drill_max_episode_days: 6`.
- The drawdown headroom is the policy value of `DRILL_MIN_DRAWDOWN_HEADROOM_FRAC` (`pins.py` floor ≥ 0.5; proposed 0.5; the policy may only raise it).
- RETIRE reasons: `drill_episode_closed` (completed or aborted episode) and `drill_gate_failed` (single-use child after a pre-effect failure). Both are policy RETIRE reasons, not cause codes.

**Arm gate (`drill_arm_gate`, D 15:30, advisory).** G-1..G-7, G-9, G-11, G-12 and G-13, with G-5 in its intraday form, plus the advisory intent read in place of G-8. Pass → write the pending rows (§3.6.5). Fail → write nothing that day, journal the reason, and retry the next day uncharged.

**Start gate (`drill_start_gate`, D 16:45, binding).** Pass → ACTIVATE. Fail → SWAP_CANCEL (with TARGET_INELIGIBLE on a G-12 sha failure). Each item has its own RED test.

| # | Condition | Source |
|---|---|---|
| G-1 | The incumbent folds CHAMPION, is not `demoted_for_cause` (W2) and is **not a drill child**; no pending pair other than the drill pair; lineage not `terminal_frozen`; no INTEGRITY freeze; no exec-store halt for the incumbent in the pass's own **fresh** mirror (at 16:45 the mirror is written first in the pass, never taken from the 16:41 reconcile; errata E-2) | chain, fresh mirror |
| G-2 | **Start rule without stranding (P7-14, plus per-counter windows):** drill budget unspent in the trailing 30 d, cadence met, **and** the arm instant, taken as the `ts_ns` of the arm transaction **at write time** (never the 15:30 timer nominal), is **strictly >** max(newest charged drill row `ts_ns` + 27 d, previous charged `DRILL_ADMIT` `ts_ns` + 30 d). Strict `>` is stricter than ARCH's `≥` and removes the equality edge of the 30 d trailing window; the boundary is pinned by `test_drill_start_gate_window_boundary_is_strict_at_write_time` (exactly at the bound refused, 1 ns past admitted). The 27 d term is ARCH's rule (`test_drill_timeline_matches_aut7_sequence`). The `DRILL_ADMIT` term covers episodes whose newest charged row is early: a pre-effect failure (ADMIT only) or an abort before D+3. In both cases every row kind of the new episode then falls > 30 d after the same-kind row before it, so no counter refuses mid-episode. | chain |
| G-3 | ≥ 1 ATTEST for the incumbent dated after its latest →CHAMPION or RESUME row and within `ATTEST_VERDICT_VALIDITY_H` (V5, Z5) | chain |
| G-4 | AUT-6 canary `delivered=true` within `ALERT_CANARY_MAX_AGE_H` | delivery records |
| G-5 | `RECONCILIATION` PASS: at 15:30 the newest accepted intraday PASS within `ATTEST_VERDICT_VALIDITY_H` (W8); at 16:45 the post-STOP PASS produced after today's STOP | C4 |
| G-6 | Fee verified (E6, P7-11) | C4 |
| G-7 | **Permit unexpired:** an AUT-6 permit-liveness `HEALTH` PASS from the last intraday producer run before STOP (16:40, G22), and no `permit_lapsed` C1 `EntryVeto` after it. Read-only. | C4, C1 |
| G-8 | No OPEN or AMBIGUOUS intent: `probe_open_intent`, binding, node down | exec store |
| G-9 | Drawdown headroom (P7-7): the newest accepted drawdown verdict's `metrics.drawdown_used_frac` ≤ 1 − `DRILL_MIN_DRAWDOWN_HEADROOM_FRAC`, drill fills included | C4 (AUT-5 `live.drawdown`) |
| G-10 | `position_handoff_ok(incumbent, child)` | C4 (AUT-2) |
| G-11 | Both journals verify against the newest export (§3.5.3) | journal, export |
| G-12 | **Child identity and bytes:** the child's `d0_climate_day` equals the pair's `effective_launch_date` D and is > every earlier d0 in the lineage (V10, R9.2-Z1); `trial_id_prefix` = `forecast_quantile_ladder/trial/<child_id>/`; at 15:30 the MINT is admissible under `MAX_MINTS_PER_LINEAGE_PER_DAY` (A-4); at 16:45 the child's manifest and artefact shas re-verify against its MINT row (V11); **and the child passes the live-orders ruling check** of E3 (routed `composition_kind`, root in `_LINEAGE_POLICY_ALLOWLIST`) and E7 (names the current policy ruling), through the one function shared with the resolver | chain, registry child file, C3 store, committed code, ruling file |
| G-13 | **Incumbent actually booted verified bytes:** the newest I-5a.1 `registry_composed` line for the incumbent at its last LAUNCH carries the authorising row's `artefact_sha256` (read from the node log FILE, never journald). Absent, unreadable or mismatched → fail. Needs WP3 live (§4 WP6) | node log, chain |

**Why the start rule and not a budget-exempt ROLLBACK.** Exempting the closing ROLLBACK from the budget would change the §4.5 contract. G-2 keeps the contract and makes stranding impossible by construction: an episode starts only when every one of its rows already fits the window.

#### 3.6.4 Child manifest and allocator

`compose_drill_child` emits the root's exact JSON with **exactly four keys** changed (all inside the §4.2 allowlist):
- `family_id = <root>_r<NNNN>`;
- `trial_id_prefix = forecast_quantile_ladder/trial/<root>_r<NNNN>/` (V10 shape);
- `live_orders_ruling` = the policy ruling id;
- `d0_climate_day` = D, the pending pair's `effective_launch_date`. This makes d0 equal to the first →CHAMPION row's effective date and greater than the root's `2026-10-02` and every earlier child's d0 (V10, U1, R9.2-Z1). d0 is a settlement and tally lower bound (`family_manifest.py:13-48`, `settlement/family_barrier.py:80`), so drill fills on climate days ≥ D still label and feed risk.

`density_artefact_path`, `density_artefact_sha256` and every size, price, station, θ and exit key stay byte-equal. The C3 no-new-lineage equality (artefact sha, and manifest modulo §4.2) holds. The MINT row cites the existing C3 directory for sha `9c0b6d6e…` (Y2, P7-5), with no C3 record and no lineage counter. The child is written 0444 to `/home/jon/.local/share/breezy/registry/families/<child>.json` through AUT-5's child-write API.

**A child is single-use.** Because d0 is fixed to D in the MINT-bound bytes, a child whose pair did not take effect on D can never satisfy the d0 rule on a later day. A retry therefore always mints a new child (§3.6.5 Retry).

**Allocator (`next_drill_child_id`).** `NNNN = 1 + max` over every BOOTSTRAP/MINT `family_id` matching `^<root>_r(\d{4})$` in **all** venue chains (lineage counters are venue-independent), starting at 1. A number is never reused (RETIRED, lapsed or voided). `NNNN > 9999` refuses with a CRITICAL. The id must match both regexes. The function is chain-pure, so a crash-retry yields the same id and MINT `transition_id`. If AUT-5's store exposes a shared `<root>_r<NNNN>` allocator, AUT-7 calls it instead.

#### 3.6.5 Drill sequence for D = the first eligible day

Every row is engine-written (`decided_by=engine`, `drill=true`, `drill_clause_sha256` set) and charged only to the drill budget at effect (Z3). The DRILL-class DEMOTE and HALT are capped by the store counters `drill_demotes` and `drill_halts` (≤ 1, refused above; V15). The marker writer pre-checks both, so a refusal means a defect, which aborts the episode.

| When | Mode | Row(s) / action | Proof artefact |
|---|---|---|---|
| D 15:30 | daily | advisory intent read; `drill_arm_gate`; then **one transaction**: `MINT` r0001 ∅→SHADOW (d0 = D; no C3 record, no counter; Y2); `DRILL_ADMIT` →CHALLENGER (`drill_admits`); `DRILL_PROMOTE` r0001→CHAMPION + `SUPERSEDE` fq_v1→CHALLENGER (`rollback_eligible=true`, W3), both `effective_launch_date=D` (pending) | chain; journal; `DRILL_ARMED` delivered |
| D 16:41 | post-STOP reconcile (AUT-2) | `RECONCILIATION` incl. `open_positions_by_family` | verdict |
| D 16:45 | prelaunch | fresh exec-store mirror first (E-2); `drill_start_gate` G-1..G-13 (incl. V11 re-verification of r0001) → `ACTIVATE` (pass), or `SWAP_CANCEL` (fail; no cause on r0001, except `target_integrity` + `TARGET_INELIGIBLE` on a sha failure) | chain; `DRILL_STARTED` delivered |
| D 16:50 | supervisor | resolves r0001; node boots it; **episode opens** (C1 `drill=true`; `drill_promotes` charged) | I-5a.1 `registry_resolved`/`registry_composed`, `family_id=pm_us_crh_fq_v1_r0001 … artefact_sha256=9c0b6d6e…` |
| D 16:52:30 / 17:02:30 | intraday | `post_verify` (R5/R6/R7a); the 16:52:30 slot is the guaranteed slot for a first-LAUNCH SWAP_CANCEL; the first post-swap ATTEST for r0001 arms `registry_attest_expired` (V5) | journal `POST_VERIFY_OK`; delivered; ATTEST row |
| D+1 15:02:30 | intraday | pre-checks: no exec-store halt and no accepted non-DRILL DEMOTE/HALT FAIL for r0001 (V12; otherwise §3.6.6 genuine-fault path); `drill_demotes` unspent. Then write the marker `detector=DRILL_INJECT`, `step=demote` | marker sha in journal |
| D+1 15:05 | producer (AUT-6) | `DRILL_INJECT` FAIL (bound) → C4 `HEALTH` FAIL, action DEMOTE, class `DRILL`; `DRILL_INJECT_HALT` → `ERROR(marker_other_detector)` | verdicts |
| D+1 15:07:30 | intraday | `DEMOTE` r0001 CHAMPION→HALTED, `cause_code=DRILL_INJECT` (`drill_demotes` charged); unlink the marker after commit | chain; `DRILL_DEMOTED` delivered |
| ≤ D+1 15:08:30 | watch actor | `entry_veto=registry_halted`; exits live | C1 `EntryVeto`; node log |
| D+1 15:10 | producer | marker absent → both detectors PASS (Z2) | verdicts |
| D+1 16:50 | supervisor | HALTED r0001 boots entries-vetoed (Z7) | node log |
| D+2 16:45 | prelaunch | `RESUME` HALTED→CHAMPION, class `DRILL`, `cause_code=DRILL_INJECT` (cooldown ≥ 24 h: ≈ 25 h 37 min since 15:07:30; every cause cleared, V12; binding probe; §4.4; `drill_resumes`) | chain; `DRILL_RESUMED` delivered |
| D+2 16:50 / 16:52:30 | supervisor / intraday | r0001 boots unvetoed (W5 clear on first tick); `post_verify`; the first post-RESUME ATTEST re-arms the veto (V5) | node log; journal; ATTEST row |
| D+3 15:02:30 | intraday | the same pre-checks with `drill_halts` unspent; write the marker `detector=DRILL_INJECT_HALT`, `step=halt` | marker sha in journal |
| D+3 15:05 | producer (AUT-6) | `DRILL_INJECT_HALT` FAIL (bound) → action HALT, class `DRILL`; `DRILL_INJECT` → `ERROR(marker_other_detector)` | verdicts |
| D+3 15:07:30 | intraday | `HALT` r0001 CHAMPION→HALTED, `cause_code=DRILL_INJECT_HALT` (`drill_halts` charged). It never writes the exec store, never sets `terminal_frozen` and never freezes the venue (C6 P6-4). Unlink the marker after commit. | chain; `DRILL_HALTED` delivered |
| ≤ D+3 15:08:30 / 15:10 | watch actor / producer | `registry_halted` veto; both detectors PASS | C1 `EntryVeto`; verdicts |
| D+3 16:45 | prelaunch | `plan_rollback` (drill-invoked): E1–E11 on fq_v1 (E9 passes because r0001's standing cause is class `DRILL` **and** no genuine cause names r0001 since its DRILL_PROMOTE; d0 exempt); dwell RESUME D+2 16:45 → LAUNCH D+3 16:50 = 24 h 05 min ≥ `ROLLBACK_MIN_DWELL_H`; handoff; journals. Then **one transaction**: `ROLLBACK` fq_v1 CHALLENGER→CHAMPION (manifest and artefact sha `9c0b6d6e…` re-verified from the C3 store, V11) + `DISPLACED` r0001 HALTED→CHALLENGER (never eligible) + `ACTIVATE`, `effective_launch_date=D+3` (P7-4) | chain; `DRILL_ROLLBACK` delivered |
| D+3 16:50 / 16:52:30 | supervisor / intraday | node boots fq_v1; **episode closes** (`drill_rollbacks` charged); `post_verify` (R5/R6); the first post-ROLLBACK ATTEST for fq_v1 re-arms the veto | resolved line `family_id=pm_us_crh_fq_v1 artefact_sha256=9c0b6d6e…`; `POST_VERIFY_OK` delivered |
| D+4 15:30 | daily | `RETIRE` r0001 CHALLENGER→RETIRED (`drill_episode_closed`); then the evidence bundle (§6) | chain; export `registry_polymarket_us_<D+4>.jsonl`; `/home/jon/.local/share/breezy/evidence/drills/drill_polymarket_us_<episode_id>.json`; `DRILL_CLOSED` delivered |

**Marker file and read (C6, U7).**
- **Path.** One fixed file, `/home/jon/.local/share/breezy/registry/drill/marker.json`. The directory `registry/drill/` (0700) is created idempotently by the engine on every pass, checked with `lstat`, never through a symlink.
- **Writes.** Written only by the engine's intraday mode under `registry/engine.lock` (the one-writer rule) and only under the active drill clause. Each write is a `mkstemp` in that directory plus `os.replace`, then fsync of the file and the directory. The engine unlinks the file once the DEMOTE or HALT row commits.
- **Stale-marker sweep (G4).** Every intraday engine pass, before it evaluates anything else, unlinks `marker.json` if the step row it names is already committed (a crash between commit and unlink) or its `window_end_ns` has passed, appends a `drill_episode/v1 {event: marker_swept, reason: step_committed|window_expired, marker_sha256}` journal record, and only then evaluates the drill step. An expired window with no committed row is then an abort trigger (§3.6.6). The sweep runs under `registry/engine.lock` and goes through the same verified directory descriptor as the read.
- **Reads.** `DrillMarkerDetector(id)` opens `registry/drill/` with `O_DIRECTORY|O_NOFOLLOW` and `fstat`-checks it (a directory, owner uid, mode 0700). It then `openat`s `marker.json` with `O_NOFOLLOW` and reads ≤ 4096 B once, hashing and parsing those bytes.

**Marker schema `drill_marker/v1` (exact-set).** `{schema, registry_root, venue, episode_id, child_id, detector, step, window_start_ns, window_end_ns, abort_record_sha256, drill_clause_sha256, ts_ns}`.
- `detector` ∈ {`DRILL_INJECT`, `DRILL_INJECT_HALT`}; `step` ∈ {`demote`, `halt`, `abort_halt`}. `demote` pairs only with `DRILL_INJECT`; `halt` and `abort_halt` only with `DRILL_INJECT_HALT`.
- Windows per step: `demote` = [write instant, + `drill_demote_slo_min`]; `halt` = [write instant, + `drill_halt_slo_min`]; `abort_halt` = [abort decision `ts_ns`, + `drill_halt_slo_min`]. `abort_record_sha256` names the journaled abort decision (null otherwise).
- `registry_root` keeps AUT-5's root-keying, so a shadow-root detector never trips on the production marker.

**Detector outcomes (ARCH C6: FAIL while its marker exists, PASS only on `ENOENT` of the marker, ERROR otherwise).**
- **PASS** only when `openat` returns `ENOENT` for `marker.json`.
- **FAIL** only when `detector` = its own id and every binding holds:
  - `episode_id` equals the chain-derived open episode;
  - `child_id` equals the fold's CHAMPION, and that family is the episode's drill child;
  - `drill_clause_sha256` equals the active block's;
  - `step` matches the sequencer's due step (or a journaled abort);
  - `ts_ns` and the evaluation `now_ns` both lie in [`window_start_ns`, `window_end_ns`];
  - `registry_root` equals its own root.
- **ERROR**, never PASS:
  - `ENOENT` on the directory itself;
  - a marker naming the other detector (`marker_other_detector`, A-6). It is never a cause, and no RESUME needs it, because both drill RESUMEs happen with no marker present;
  - any binding mismatch, a window passed with the marker still present, a symlink, a permission error, oversize or a parse failure. Each of these sends a CRITICAL through `deliver_with_proof`.
- ERROR never satisfies a RESUME (`test_drill_marker_read_error_never_resumes`). Outside the drill clause the engine treats any outcome as ERROR (C6).

**First cause wins (V12).** The marker writer refuses (writes no marker, and the episode goes to §3.6.6) while `genuine_cause_since_drill_promote(child)` is true. The store independently refuses a DRILL-class row in that state.

**Retry (rewritten for the V10 d0 rule).**
- **Pre-arm failure** (15:30 gate fails, MINT ceiling refuses, or the engine is down): nothing is written, so nothing is charged; retry at the next day's 15:30.
- **Pre-effect failure after arming** (16:45 SWAP_CANCEL, lapse at LAUNCH, or a 16:52:30 SWAP_CANCEL after `launch_precheck_failed`/`launch_target_integrity`): the pair is voided and never charged (Z3), but the `DRILL_ADMIT` charged at D 15:30 stands. r0001 cannot be reused, because its d0 = D is earlier than any later effective date (V10). It is RETIREd at the next daily pass (`drill_gate_failed`), the episode is journaled `failed_pre_effect`, and the retry mints r0002 (d0 = D′) once G-2 admits: D′ 15:30 ≥ the r0001 `DRILL_ADMIT` `ts_ns` + 30 d.
- **Post-effect failure:** the abort path (§3.6.6), then G-2.
- A child carrying `demoted_for_cause` (a cause on the incoming family, Y8) is RETIREd at the next daily pass.

#### 3.6.6 Abort and genuine-fault paths

**Abort (a drill step fails, with no genuine cause on the child).** Triggers:
- no DEMOTE or HALT within its marker window;
- RESUME refused at D+2;
- a `post_verify` mismatch or first-LAUNCH failure that was not SWAP_CANCELled by 17:00 (the child folds CHAMPION without a verified load);
- the episode passing `drill_max_episode_days`;
- a drill counter refusal.

The sequencer journals an abort decision, sends CRITICAL `DRILL_ABORTED`, stops further injections and closes the episode:
1. If r0001 folds CHAMPION and `drill_halts` is unspent, the intraday pass writes an `abort_halt` marker (`DRILL_INJECT_HALT`), so r0001 is HALTED through the live path within `drill_halt_slo_min`. A post-verify mismatch always takes this step first.
2. At the next 16:45 pass whose preconditions and dwell hold, the **closing ROLLBACK** to fq_v1 runs. Its partner is `DISPLACED` if r0001 is HALTED, or `SUPERSEDE` if r0001 is still CHAMPION (never eligible, W3). E9 passes only if r0001's standing state is drill-only **and** no genuine cause names it since DRILL_PROMOTE (E9 clause ii); otherwise the episode is abandoned instead (below). The earliest abort close is DRILL_PROMOTE D 16:50 → D+1 16:50 = 24 h, which meets the dwell. Then RETIRE r0001 at the next daily pass.
3. If that ROLLBACK fails (R1, R4, R5) while r0001 folds CHAMPION, HALT r0001: `rollback_failed`, `ROLLBACK_FAILED`, `trigger_cause_class=DRILL` (§3.5.1). The venue then has no new-entry sender, and the closing ROLLBACK retries daily with a DISPLACED partner. No INTEGRITY freeze.
4. **Closing ROLLBACK took effect, then failed (errata E-5).** If the closing pair (nominal D+3 or abort close) takes effect and then fails after 17:00 (R5 not cancelled by 17:00, R6 mismatch, or R7a), the intraday pass HALTs the **root** `fq_v1`: `rollback_failed`, `ROLLBACK_FAILED`, `trigger_cause_class=DRILL` (§3.5.1). Its RESUME would charge `drill_resumes`, already spent at D+2, and no rollback target exists (r0001 is DISPLACED and never eligible), so without E-5 the venue would have no sender for about 28 days (until the D+2 `drill_resumes` charge leaves the 30 d window). The next 16:45 pass therefore writes a **restorative RESUME** of `fq_v1`, `cause=drill_close_restore`, when **all** hold:
   - `fq_v1`'s manifest and artefact shas re-verify byte-identical against its BOOTSTRAP row from the C3 store (resolver byte binding, V11);
   - `genuine_cause_since_drill_promote(fq_v1)` is false: no accepted non-DRILL cause and no exec-store halt (fresh mirror, E-2) names it since the episode's DRILL_PROMOTE;
   - the §4.4 preconditions hold (binding intent probe, post-STOP RECONCILIATION, no INTEGRITY freeze);
   - the store admits it under `drill_close_restores` (≤ 1 per venue per day);
   - `RESUME_COOLDOWN_H` is met (AUT-7 applies the cooldown conservatively, since E-5 does not exempt it; A-7);
   - **AUT-7-stricter:** no open `target_status=target_load_failed` record for `fq_v1` under the current engine pin (R7a would only fail again on the same bytes and code), and no earlier restorative RESUME in this episode (one per episode, so a recurring post-17:00 failure cannot loop daily).
   It charges no drill counter and no production resume budget. It **never** applies to the drill child, and never after a genuine fault: in those cases the root stays HALTED under §3.5.2 steps 1–3 with a daily CRITICAL (K-20). **Outage bound:** the HALT commits between 17:02:30 and 17:32:30 on the close day C, so `RESUME_COOLDOWN_H` (24) is met before the C+2 16:45 pass, never the C+1 pass; the RESUME takes effect at the C+2 16:50 LAUNCH. The venue has no sender for at most C 17:00 → C+2 16:50 (≤ 47 h 50 min, 2 sessions). The episode is closed as `failed` (its bundle is never proof), r0001 is RETIREd at the next daily pass, and the retry follows G-2, whose newest charged row is the closing ROLLBACK. **ETA effect:** the ≤ 2 lost live days are reported to AUT-4's `eta_date` (§3.6.7), and the retry date is unchanged: G-2 keys on the closing ROLLBACK's charged `ts_ns`, so the retry equals the nominal post-effect failure row of §6 (P90 bundle 12-24).

Because G-2 admitted the episode only when every row fits the 30-day window, the closing ROLLBACK is never refused by the drill budget. An aborted episode is a failed episode: its closing ROLLBACK is the newest charged row for the next G-2.

**Genuine fault on r0001 (T5).** This is any accepted DEMOTE or HALT on r0001 whose cause is **not** `DRILL_INJECT`/`DRILL_INJECT_HALT`. It includes a SWAP_CANCEL + HALT on the outgoing side (Y8), an exec-store mirror, and the R7b INTEGRITY HALT.
The genuine-fault test is `genuine_cause_since_drill_promote(r0001)` over the chain, the C4 verdicts and the fresh mirror, so a genuine FAIL that arrives after a DRILL HALT (and therefore writes no row, V12) still abandons the episode.
1. **The episode is abandoned.** The sequencer writes no further drill step and appends `drill_episode/v1 {episode_id, status: abandoned, cause_transition_id}`. CRITICAL `DRILL_ABANDONED`.
2. **Never ROLLBACK to a target with the same `artefact_sha256` while that cause stands** (E9). fq_v1 is byte-identical, so it is excluded.
3. **r0001 stays HALTED under production rules.** It may RESUME only under its own cause class, charging that class's production budget, never the drill budget. A `RECOVERABLE_MODEL` trigger may roll back only to a non-identical eligible target, charged to the production rollback budget. A TERMINAL cause, or an exhausted model budget, RETIREs r0001 and sets `terminal_frozen` on the fq_v1 lineage (Y10). Recovery is then AUT-5's ROOT_ADMIT of a reviewed new root (C5 V6).
4. **What sends next**, in order:
   - (a) r0001, after a production RESUME of its own cause;
   - (b) a non-identical eligible target, through a production ROLLBACK (none exists while `promote_enabled=false`);
   - (c) a ROOT_ADMITted root, once the venue fold names no CHAMPION or HALTED family;
   - (d) otherwise **no sender on the venue**. That is fail-safe (entries stopped, exits live, no freeze, unless R7b), and CRITICAL `DRILL_ABANDONED_NO_SENDER` is sent daily through `deliver_with_proof`.
5. **Abandoned-episode close.** RETIRE is not open to a HALTED family with a recoverable cause (C5). The close is therefore the journal record in step 1. If r0001 later RESUMEs and folds CHAMPION with **no standing cause**, a **deferred restorative close** follows at a later 16:45 pass (dwell ≥ 24 h after that RESUME): the closing ROLLBACK to fq_v1 with a `SUPERSEDE` partner, charged to the episode's reserved drill rollback (d0 exempt), then RETIRE r0001. It runs only if fq_v1 still passes E1–E11 (the E5 age cap included). Otherwise r0001 remains the champion and drills stay blocked by G-1 (K-15).

Drill fills follow ARCH §5.3 unchanged: `drill=true` from DRILL_PROMOTE through the closing ROLLBACK, including an abandoned episode's production period. That is conservative: it removes fills from n and the KILL clock, never from risk. **Effect of an abandoned episode on n and the KILL clock** (stated in §3.6.7 and K-15): the drill interval is open-ended until the deferred restorative close, r0001's RETIRE, or a production ROLLBACK away from r0001; every fill in it is excluded from n and the KILL-clock counter. The 2027-01-25 KILL date itself never moves.

#### 3.6.7 Drill fills, budget and costs

`drill_episodes()` returns `[DRILL_PROMOTE effective_ns, closing ROLLBACK effective_ns)` per child (open-ended while unclosed; an abandoned episode's interval ends at the deferred restorative close, r0001's RETIRE, or a production ROLLBACK away from r0001). `is_drill_fill` is true for any fill inside an interval, or of a drill-child family id. Consumers: AUT-1 stamps C1 `drill=true`; AUT-2 re-derives `excluded_reason=drill`, `admissible=false`; AUT-4's live sequential and the KILL clock exclude them.

**Drill fills stay in risk (W12).** They are real money. They count in every DRIFT/HEALTH detector, the drawdown limit (AUT-5 `live.drawdown` includes `excluded_reason=drill`), venue-net reconciliation, realised P&L, portfolio ROI and the venue daily budget (Z18, G21). Only n and the KILL clock exclude them. Tests: ARCH-named `test_detectors_and_drawdown_include_drill_fills` and `test_drill_fills_spend_venue_budget`; AUT-7's `test_gate_drill_fills_feed_risk_reconciliation_and_pnl`.

**Drill budget per 30 d per venue (§4.5, V15).**

| Item | Row | Charged | Enforced at |
|---|---|---|---|
| 1 DRILL_ADMIT | `DRILL_ADMIT` (D 15:30) | at effect (now) | store (`drill_admits`) |
| 1 DRILL_PROMOTE | `DRILL_PROMOTE` pair (D 16:50) | at effect (LAUNCH) | store (`drill_promotes`) |
| 1 `DRILL_INJECT` DEMOTE | `DEMOTE` (D+1 15:07:30) | at effect | store (`drill_demotes`, ≤ 1, refused above; V15), with a marker-writer pre-check |
| 1 DRILL RESUME | `RESUME` (D+2 16:45) | at effect | store (`drill_resumes`) |
| 1 `DRILL_INJECT_HALT` | `HALT` (D+3 15:07:30, or `abort_halt`) | at effect | store (`drill_halts`, ≤ 1, refused above; V15), with a marker-writer pre-check |
| 1 DRILL rollback | `ROLLBACK` pair (D+3 16:50) | at effect | store (`drill_rollbacks`); never refused, by construction (G-2) |
| (0 or 1) restorative RESUME (E-5) | `RESUME` `cause=drill_close_restore` of the root after a failed close (§3.6.6 step 4) | **not charged** to any drill counter or production resume budget | store (`drill_close_restores`, ≤ 1 per venue per day); AUT-7 planner: ≤ 1 per episode |

A lapsed or cancelled pair is never charged. A rollback during an abandoned episode to a non-identical target is charged to the **production** budget.

**Statistical cost (ARCH V19).**
- `drill=true` from D 16:50 to D+3 16:50: 3 live days of n and KILL-clock evidence lost per episode (6 with one post-effect retry). AUT-5 adds this to `eta_date`.
- Drill fills: session D (D 16:50 → D+1 15:07:30) and session D+2 (D+2 16:50 → D+3 15:07:30), about **2 sessions ≈ 10 fills** at about 5 fills a day.
- Vetoed: D+1 15:07:30 → D+2 16:50, plus D+3 15:07:30 → 16:40, about **1.1 sessions ≈ 5–6 fills of opportunity**.
- A pre-effect failure loses no live days. It costs the 30 d wait for the next `DRILL_ADMIT` (§6 ETA).
- **Abandoned episode (G7).** n and the KILL-clock counter receive nothing from r0001 for as long as the abandoned interval stays open, so each such day is a lost live day; with no sender (§3.6.6 step 4d) nothing is lost beyond the absent fills. The engine journals the open-interval day count daily and hands it to **AUT-4's `eta_date`** (the feasibility record AUT-5's ruling consumes, ARCH §5.3/§10), recomputed each day while the interval is open. While open, `eta_date` therefore grows by one day per day, which keeps `promote_enabled` false (§4.2 Y12) rather than letting the KILL clock run on unadmissible evidence.
- **Failed drill close restored by E-5:** ≤ 2 lost live days (no sender), reported to AUT-4's `eta_date` the same way.
- No extra money at risk: the byte-identical child trades inside the same caps.

### 3.7 Units and the launch window

**No new unit.** Everything runs inside AUT-5's `breezy-autonomy-engine@{daily,intraday,prelaunch}` under `registry/engine.lock`, within the engine's memory cap (own-lock autonomy units ≤ 4G in total, §5.2 V14). The programme systemd rule (`TimeoutStartSec`, never `RuntimeMaxSec`, on oneshots; no overlap of [16:30Z, 17:10Z) outside the table) is met by AUT-5's units. AUT-7 adds no unit file, so it consumes `test_oneshot_units_use_timeout_start_sec_not_runtime_max_sec` and `test_no_unit_overlaps_launch_window` unchanged.

AUT-7 actions map onto the ARCH §5.2 launch-window table:

| ARCH §5.2 firing | AUT-7 action | Bound |
|---|---|---|
| Daily engine 15:30 (outside the window) | arm gate, MINT/ADMIT/pending pair, RETIRE, readiness, bundle | `-w` ≤ 120 s, ≤ 900 s; ends ≤ 15:47 |
| Intraday engine 15:02:30, 15:07:30 (outside the window) | stale-marker sweep first (every pass); marker write; DEMOTE/HALT commit via the producer verdict; marker unlink | ≤ 140 s each |
| Intraday engine 16:32:30, 16:37:30 | `post_verify` of a prior day's missing line only; no drill step | ends ≤ 16:39:50 |
| Intraday engine 16:42:30 | nothing new (ends 16:44:50, before pre-launch) | — |
| Pre-launch 16:45 | fresh exec-store mirror first (E-2); every widening write incl. the E-5 restorative RESUME, TARGET_INELIGIBLE, drill-child `rollback_failed` HALT | `-w` ≤ 60 s, ≤ 180 s; ends ≤ 16:49 |
| Intraday 16:47:30 | yields to the pre-launch lock (`test_intraday_pass_yields_to_prelaunch_lock`); no AUT-7 action | times out by 16:47:50 |
| Intraday 16:52:30 (guaranteed) / 16:57:30 (best-effort) | R5/R6/R7a SWAP_CANCEL + TARGET_INELIGIBLE inside [LAUNCH, 17:00) | ends ≤ 16:54:50 / 16:59:50 |
| Intraday 17:02:30, 17:07:30 and later | post-17:00 `post_verify`; `rollback_failed` HALT; missing-line HALT at 17:32:30 | ≤ 140 s each |

A test pins that every AUT-7 write kind occurs only in its listed mode and slot (`test_aut7_actions_only_in_listed_engine_slots`).

## 4. Work packages

Gate commands for every WP:
- `scripts/ci/run_tests_no_egress.sh <focused paths>`, then the full `scripts/ci/run_tests_no_egress.sh`, reading EXIT before any push;
- `cd <tree root> && lint-imports`, which must print "N kept, 0 broken" (the console script, never `python -m importlinter`);
- the mypy ratchet `tests/unit/test_mypy_ratchet.py`.

Worktrees export `PYTHONPATH=<worktree>/src` and use the exact interpreter. Never `uv`, `pip` or `git stash`. Each WP is RED-first, and its commit message carries the RED and GREEN output. Every WP that touches the engine closure re-pins `ENGINE_SOURCE_SHA256` (append-only, Z9) in the same commit (`test_code_identity_pins_cover_import_closure`). Tests named in ARCH §4.7 keep their ARCH names exactly. No existing test is weakened.

### AUT-7.WP1 — champion history (Wave 1, against ARCH-0 stubs)
- **Files:** `src/breezy/persistence/autonomy/rollback.py`; `tests/unit/autonomy/test_rollback_champion_history.py`.
- **RED first:**
  - `tests/unit/autonomy/test_rollback_champion_history.py::test_history_is_a_pure_fold_of_the_verified_chain`
  - `tests/unit/autonomy/test_rollback_champion_history.py::test_history_never_reads_projection_or_families_cache`
  - `tests/unit/autonomy/test_rollback_champion_history.py::test_history_refuses_unverified_or_export_divergent_chain`
  - `tests/unit/autonomy/test_rollback_champion_history.py::test_pending_lapsed_and_voided_pairs_create_no_epoch`
  - `tests/unit/autonomy/test_rollback_champion_history.py::test_drill_promote_supersede_makes_incumbent_rollback_eligible`
  - `tests/unit/autonomy/test_rollback_champion_history.py::test_drill_child_is_never_rollback_eligible`
  - `tests/unit/autonomy/test_rollback_champion_history.py::test_demote_halt_any_class_clears_and_displaced_never_sets_rollback_eligible`
  - `tests/unit/autonomy/test_rollback_champion_history.py::test_swap_cancel_with_incoming_cause_sets_demoted_for_cause`
  - `tests/unit/autonomy/test_rollback_champion_history.py::test_target_ineligible_row_sets_target_integrity_flag`
  - `tests/unit/autonomy/test_rollback_champion_history.py::test_rollback_failed_halt_records_trigger_cause_class`
  - `tests/unit/autonomy/test_rollback_champion_history.py::test_last_attest_counts_only_attests_after_latest_champion_or_resume_row`
  - `tests/unit/autonomy/test_rollback_champion_history.py::test_every_champion_epoch_appears_in_history`
  - `tests/unit/autonomy/test_rollback_champion_history.py::test_history_render_equals_fold_and_is_write_once`
- **GREEN:** all pass, plus `tests/unit/autonomy/test_rollback_champion_history.py::test_rollback_module_has_no_family_literals` (AST).
- **Activation:** a pure library, live when the engine imports it (WP3).

### AUT-7.WP2 — trigger, eligibility, dwell, precedence, journal verification (Wave 1; journal part after ARCH-0 merges)
- **Files:** `src/breezy/persistence/autonomy/rollback.py`; the ARCH-0 `src/breezy/persistence/autonomy/rollback_journal.py` (record kinds and `verify_journal_chain` only); `tests/unit/autonomy/test_rollback_planner.py`, `tests/unit/autonomy/test_rollback_eligibility.py`, `tests/unit/autonomy/test_rollback_journal.py`.
- **RED first, trigger, precedence and dwell:**
  - `tests/unit/autonomy/test_rollback_planner.py::test_trigger_fires_on_recoverable_model_demote_of_champion`
  - `tests/unit/autonomy/test_rollback_planner.py::test_trigger_fires_on_rollback_failed_with_model_trigger_class`
  - `tests/unit/autonomy/test_rollback_planner.py::test_trigger_silent_for_infra_drill_terminal_integrity`
  - `tests/unit/autonomy/test_rollback_planner.py::test_trigger_fires_for_genuine_model_fault_on_drill_child`
  - `tests/unit/autonomy/test_rollback_planner.py::test_trigger_refused_while_pair_pending`
  - `tests/unit/autonomy/test_rollback_planner.py::test_resume_preferred_over_rollback_when_admissible`
  - `tests/unit/autonomy/test_rollback_planner.py::test_rollback_failed_family_resumes_only_under_trigger_cause_class`
  - `tests/unit/autonomy/test_rollback_planner.py::test_at_most_one_widening_decision_per_venue_per_prelaunch_pass`
  - `tests/unit/autonomy/test_rollback_planner.py::test_rollback_resume_ping_pong_damped_by_ceilings`
  - `tests/unit/autonomy/test_rollback_planner.py::test_rollback_dwell_delays_never_refuses`
  - `tests/unit/autonomy/test_rollback_planner.py::test_rollback_dwell_never_delays_past_next_launch`
  - `tests/unit/autonomy/test_rollback_planner.py::test_drill_rollbacks_count_only_against_drill_budget`
  - `tests/unit/autonomy/test_rollback_planner.py::test_budget_exhausted_halt_charges_no_rollback_budget`
- **RED first, eligibility (one per predicate):**
  - `tests/unit/autonomy/test_rollback_eligibility.py::test_target_requires_fresh_post_champion_attest`
  - `tests/unit/autonomy/test_rollback_eligibility.py::test_e4_bound_equals_w1_invariant_terms`
  - `tests/unit/autonomy/test_rollback_eligibility.py::test_target_refused_past_age_cap`
  - `tests/unit/autonomy/test_rollback_eligibility.py::test_rollback_fee_check_uses_verdict_not_node_memory`
  - `tests/unit/autonomy/test_rollback_eligibility.py::test_target_requires_current_live_orders_ruling`
  - `tests/unit/autonomy/test_rollback_eligibility.py::test_target_refused_with_pending_cause_or_demand_or_exec_halt`
  - `tests/unit/autonomy/test_rollback_eligibility.py::test_target_refused_byte_identical_for_any_non_drill_cause`
  - `tests/unit/autonomy/test_rollback_eligibility.py::test_e9_passes_only_for_drill_or_drill_triggered_rollback_failed_else_sha_must_differ` (G3)
  - `tests/unit/autonomy/test_rollback_eligibility.py::test_drill_close_refused_when_genuine_fail_follows_drill_halt` (G2)
  - `tests/unit/autonomy/test_rollback_eligibility.py::test_drill_close_refused_when_exec_store_halt_follows_drill_promote` (G2)
  - `tests/unit/autonomy/test_rollback_eligibility.py::test_e8_reads_only_fresh_prelaunch_mirror_never_1641_mirror` (G6, E-2)
  - `tests/unit/autonomy/test_rollback_eligibility.py::test_target_excludes_demoted_terminal_and_unrouted`
  - `tests/unit/autonomy/test_rollback_eligibility.py::test_target_is_most_recent_eligible`
  - `tests/unit/autonomy/test_rollback_eligibility.py::test_selection_skips_target_integrity_candidate_and_moves_on`
  - `tests/unit/autonomy/test_rollback_eligibility.py::test_target_ineligible_flag_excludes_target_until_cleared`
  - `tests/unit/autonomy/test_rollback_eligibility.py::test_target_integrity_clears_only_by_two_clean_readiness_passes`
  - `tests/unit/autonomy/test_rollback_eligibility.py::test_target_load_failed_ineligible_until_engine_pin_rotates`
  - `tests/unit/autonomy/test_rollback_eligibility.py::test_rollback_selection_never_applies_d0_rule`
  - `tests/unit/autonomy/test_rollback_eligibility.py::test_readiness_reports_every_predicate_reason`
- **RED first, budget, bytes and handoff:**
  - `tests/unit/autonomy/test_rollback_eligibility.py::test_rollback_budget_counted_at_effect_with_reservations`
  - `tests/unit/autonomy/test_rollback_eligibility.py::test_target_symlink_missing_or_manifest_or_artefact_sha_mismatch_writes_target_ineligible`
  - `tests/unit/autonomy/test_rollback_eligibility.py::test_position_handoff_owned_or_flat_else_refused`
  - `tests/unit/autonomy/test_rollback_eligibility.py::test_handoff_inconclusive_only_when_branch_b_fails` (G8)
  - `tests/unit/autonomy/test_rollback_eligibility.py::test_autonomy_rollback_introduces_no_cause_code`
- **RED first, journal (T7):**
  - `tests/unit/autonomy/test_rollback_journal.py::test_journal_exact_set_write_once_0444_no_paths`
  - `tests/unit/autonomy/test_rollback_journal.py::test_journal_prev_sha256_links_and_chain_head`
  - `tests/unit/autonomy/test_rollback_journal.py::test_journal_verified_against_newest_export_heads`
  - `tests/unit/autonomy/test_rollback_journal.py::test_journal_uses_highest_export_seq_incl_hwm_reset_export`
  - `tests/unit/autonomy/test_rollback_journal.py::test_journal_head_mismatch_blocks_rollback_and_alerts`
  - `tests/unit/autonomy/test_rollback_journal.py::test_journal_missing_tail_blocks_rollback_and_alerts`
  - `tests/unit/autonomy/test_rollback_journal.py::test_journal_unverified_keeps_target_integrity_flags_set`
  - `tests/unit/autonomy/test_rollback_journal.py::test_journal_block_never_blocks_resume_or_restrictive_writes`
  - `tests/unit/autonomy/test_rollback_journal.py::test_readiness_filenames_unique_never_overwritten`
- **GREEN:** all pass. The byte binding is imported from the resolver (`tests/unit/autonomy/test_rollback_eligibility.py::test_rollback_uses_resolver_byte_binding`, AST). The P7-7 ceilings are read from `pins.py` and the policy block, never from literals (consumes ARCH `test_rollback_dwell_age_and_drill_headroom_ceilings`).
- **Activation:** with WP3.

### AUT-7.WP3 — engine integration, fail-closed matrix, post-verify, readiness (Wave 1 code against the AUT-5a stub)
- **Files:** `src/breezy/persistence/autonomy/rollback.py` step hooks, `src/breezy/persistence/autonomy/post_verify.py`; `tests/integration/autonomy/test_rollback_engine.py`, `tests/unit/autonomy/test_post_verify.py`; ARCH-named `tests/unit/autonomy/test_rollback_restores_byte_identical_artefact.py::test_rollback_restores_byte_identical_artefact`.
- **RED first, engine:**
  - `tests/integration/autonomy/test_rollback_engine.py::test_demote_before_1645_rolls_back_at_same_day_launch`
  - `tests/integration/autonomy/test_rollback_engine.py::test_demote_after_1645_rolls_back_at_next_launch`
  - `tests/integration/autonomy/test_rollback_engine.py::test_prelaunch_writes_rollback_and_activate_atomically`
  - `tests/integration/autonomy/test_rollback_engine.py::test_activate_reverifies_incoming_manifest_and_artefact_shas`
  - `tests/integration/autonomy/test_rollback_engine.py::test_prelaunch_checks_precede_write_so_failure_writes_nothing`
  - `tests/integration/autonomy/test_rollback_engine.py::test_rollback_requires_no_code_change`
  - `tests/integration/autonomy/test_rollback_engine.py::test_rollback_to_root_reads_content_addressed_copy`
  - `tests/integration/autonomy/test_rollback_engine.py::test_failed_rollback_halts_champion`
  - `tests/integration/autonomy/test_rollback_engine.py::test_failed_rollback_leaves_halted_f_without_new_row_and_retries_daily`
  - `tests/integration/autonomy/test_rollback_engine.py::test_rollback_failed_never_freezes_venue`
  - `tests/integration/autonomy/test_rollback_engine.py::test_target_byte_mismatch_ineligible_without_freeze`
  - `tests/integration/autonomy/test_rollback_engine.py::test_target_manifest_mismatch_marks_ineligible`
  - `tests/integration/autonomy/test_rollback_engine.py::test_first_launch_target_integrity_cancels_at_165230_and_restores_incumbent`
  - `tests/integration/autonomy/test_rollback_engine.py::test_first_launch_failure_after_1700_halts_rollback_failed`
  - `tests/integration/autonomy/test_rollback_engine.py::test_launch_precheck_failed_cancels_without_cause`
  - `tests/integration/autonomy/test_rollback_engine.py::test_champion_own_artefact_mismatch_past_first_launch_is_aut5_integrity_halt`
  - `tests/integration/autonomy/test_rollback_engine.py::test_rollback_failed_exits_by_resume_retry_or_retire_then_root_admit`
  - `tests/integration/autonomy/test_rollback_engine.py::test_daily_pass_writes_only_drill_mint_admit_pending_pair_and_retire`
  - `tests/integration/autonomy/test_rollback_engine.py::test_resume_written_only_at_prelaunch`
  - `tests/integration/autonomy/test_rollback_engine.py::test_rollback_alerts_journal_delivery`
  - `tests/integration/autonomy/test_rollback_engine.py::test_wp3_consumes_aut5a_boot_signals`
  - `tests/integration/autonomy/test_rollback_engine.py::test_aut7_actions_only_in_listed_engine_slots`
  - `tests/integration/autonomy/test_rollback_engine.py::test_prelaunch_pass_mirrors_exec_store_before_g1_e8_e9` (G6, E-2)
- **RED first, post-verify:**
  - `tests/unit/autonomy/test_post_verify.py::test_post_verify_runs_at_165230_165730_and_from_170230`
  - `tests/unit/autonomy/test_post_verify.py::test_post_verify_mismatch_halts_target_rollback_failed_after_1700`
  - `tests/unit/autonomy/test_post_verify.py::test_post_verify_missing_composed_line_halts_at_173230`
  - `tests/unit/autonomy/test_post_verify.py::test_post_verify_interim_parses_fq_live_orders_line`
  - `tests/unit/autonomy/test_post_verify.py::test_load_failure_after_resolve_cancels_or_halts_not_crash_loop`
  - `tests/unit/autonomy/test_post_verify.py::test_classify_boot_failure_splits_first_launch_from_champion_own_bytes`
- **GREEN:** all pass. The §4.7 envelope tests stay unweakened, and `test_damping_ceilings` stays green.
- **Activation (stated technical reason).** Merged and activated only after AUT-5a's I-5a.1 (journaled `launch_target_integrity`, `launch_precheck_failed`, and node lines incl. `registry_boot_load_failed`), I-5a.2 (supervisor non-relaunch plus intraday trigger) and I-5a.3 (the P7-10 artefact handoff: store path plus row sha, re-verified at load; ARCH `test_node_loads_artefact_from_store_by_row_sha` green) are merged **and live**. Reason: without them R5–R7b cannot be detected or classified, and the path re-read (F-2) could load unverified bytes after a rollback. Then restart the engine in 01:00–16:40, never touching the node.

### AUT-7.WP4 — drill library and marker detectors (Wave 1)
- **Files:** `src/breezy/persistence/autonomy/drill.py`, `src/breezy/persistence/autonomy/drill_inject.py`; `tests/unit/autonomy/test_drill.py`, `tests/unit/autonomy/test_drill_inject.py`.
- **RED first, ARCH-named:**
  - `tests/unit/autonomy/test_drill.py::test_drill_promote_refuses_non_champion_sha`
  - `tests/unit/autonomy/test_drill.py::test_drill_inject_mapped_only_in_clause`
  - `tests/unit/autonomy/test_drill.py::test_drill_budget_separate`
  - `tests/unit/autonomy/test_drill.py::test_drill_flag_spans_promote_to_rollback`
  - `tests/unit/autonomy/test_drill.py::test_drill_admit_charges_only_drill_budget`
  - `tests/unit/autonomy/test_drill.py::test_drill_resume_never_charges_model_budget`
  - `tests/unit/autonomy/test_drill.py::test_drill_refused_over_halted_incumbent`
  - `tests/unit/autonomy/test_drill.py::test_drill_rollback_to_superseded_incumbent_admitted`
  - `tests/unit/autonomy/test_drill.py::test_drill_halt_never_freezes_or_writes_exec_store`
  - `tests/unit/autonomy/test_drill.py::test_drill_demote_and_halt_counters_capped`
  - `tests/unit/autonomy/test_drill.py::test_drill_timeline_matches_aut7_sequence`
- **RED first, drill library:**
  - `tests/unit/autonomy/test_drill.py::test_drill_child_equals_root_modulo_four_allowlisted_keys`
  - `tests/unit/autonomy/test_drill.py::test_drill_child_d0_equals_pair_effective_date_and_exceeds_lineage_d0`
  - `tests/unit/autonomy/test_drill.py::test_drill_child_writes_no_c3_lineage_and_no_counter`
  - `tests/unit/autonomy/test_drill.py::test_next_drill_child_id_monotone_never_reused_across_venues`
  - `tests/unit/autonomy/test_drill.py::test_daily_arm_writes_mint_admit_and_pending_pair_after_advisory_intent_and_intraday_reconciliation`
  - `tests/unit/autonomy/test_drill.py::test_daily_arm_writes_nothing_when_mint_ceiling_refuses`
  - `tests/unit/autonomy/test_drill.py::test_prelaunch_activates_or_cancels_drill_pair_after_g1_to_g12`
  - `tests/unit/autonomy/test_drill.py::test_drill_start_gate_each_condition`
  - `tests/unit/autonomy/test_drill.py::test_drill_start_gate_requires_27d_after_newest_charged_row_and_30d_after_admit`
  - `tests/unit/autonomy/test_drill.py::test_drill_start_gate_window_boundary_is_strict_at_write_time` (G8)
  - `tests/unit/autonomy/test_drill.py::test_drill_gates_require_incumbent_composed_line_with_row_sha` (G-13, G5)
  - `tests/unit/autonomy/test_drill.py::test_drill_start_gate_g12_checks_child_live_orders_ruling` (G6)
  - `tests/unit/autonomy/test_drill.py::test_g7_permit_pass_taken_before_1640_stop` (G8)
  - `tests/unit/autonomy/test_drill.py::test_intraday_pass_sweeps_committed_or_expired_marker_before_evaluating` (G4)
  - `tests/unit/autonomy/test_drill.py::test_restorative_resume_never_for_child_or_after_genuine_fault` (G1, E-5)
  - `tests/unit/autonomy/test_drill.py::test_restorative_resume_charges_no_drill_or_production_budget_and_is_capped_per_day_and_episode` (E-5)
  - `tests/unit/autonomy/test_drill.py::test_restorative_resume_refused_on_byte_mismatch_open_load_failure_or_cooldown` (E-5)
  - `tests/unit/autonomy/test_drill.py::test_drill_cadence_from_last_completed_episode`
  - `tests/unit/autonomy/test_drill.py::test_pre_effect_failure_retires_child_and_retry_mints_new_child_after_30d`
  - `tests/unit/autonomy/test_drill.py::test_drill_counter_precheck_at_marker_writer`
  - `tests/unit/autonomy/test_drill.py::test_marker_writer_refuses_while_non_drill_cause_stands`
  - `tests/unit/autonomy/test_drill.py::test_drill_child_resumes_only_on_drill_inject_cause`
  - `tests/unit/autonomy/test_drill.py::test_genuine_fault_on_drill_child_abandons_episode_no_auto_resume`
  - `tests/unit/autonomy/test_drill.py::test_is_drill_fill_by_interval_or_family_id`
  - `tests/unit/autonomy/test_drill.py::test_drill_state_is_derived_from_chain_after_restart`
- **RED first, marker detector (C6, U7, V12):**
  - `tests/unit/autonomy/test_drill_inject.py::test_drill_inject_passes_when_marker_absent`
  - `tests/unit/autonomy/test_drill_inject.py::test_drill_marker_read_error_never_resumes`
  - `tests/unit/autonomy/test_drill_inject.py::test_marker_read_via_verified_directory_descriptor`
  - `tests/unit/autonomy/test_drill_inject.py::test_missing_drill_directory_is_error_not_pass`
  - `tests/unit/autonomy/test_drill_inject.py::test_other_detector_marker_is_error_not_pass_or_fail`
  - `tests/unit/autonomy/test_drill_inject.py::test_marker_window_per_step_demote_halt_abort`
  - `tests/unit/autonomy/test_drill_inject.py::test_marker_must_bind_episode_child_clause_step_and_root`
  - `tests/unit/autonomy/test_drill_inject.py::test_marker_symlink_oversize_unparseable_or_expired_is_error`
  - `tests/unit/autonomy/test_drill_inject.py::test_marker_written_only_under_engine_lock_and_clause`
- **GREEN:** all pass, and the producer pin covers `drill_inject.py` (`test_code_identity_pins_cover_import_closure`).
- **Activation:** with WP6.

### AUT-7.WP5 — AUT-7a gate drill (Wave 1; completes after the AUT-5a/AUT-6 interfaces land)
- **Files:** `tests/integration/autonomy/test_rollback_drill_gate.py`.
- **RED first:**
  - `tests/integration/autonomy/test_rollback_drill_gate.py::test_gate_drill_full_episode`
  - `tests/integration/autonomy/test_rollback_drill_gate.py::test_gate_drill_position_open_across_each_swap`
  - `tests/integration/autonomy/test_rollback_drill_gate.py::test_gate_drill_failure_matrix`
  - `tests/integration/autonomy/test_rollback_drill_gate.py::test_gate_drill_pre_effect_retry_with_new_child`
  - `tests/integration/autonomy/test_rollback_drill_gate.py::test_failed_episode_retry_never_strands_closing_rollback`
  - `tests/integration/autonomy/test_rollback_drill_gate.py::test_gate_drill_dwell_enumeration`
  - `tests/integration/autonomy/test_rollback_drill_gate.py::test_genuine_fault_on_drill_child_never_restores_identical_artefact`
  - `tests/integration/autonomy/test_rollback_drill_gate.py::test_genuine_fault_with_no_eligible_target_leaves_venue_without_sender_and_alerts`
  - `tests/integration/autonomy/test_rollback_drill_gate.py::test_abandoned_episode_restores_root_only_after_clean_production_resume`
  - `tests/integration/autonomy/test_rollback_drill_gate.py::test_gate_drill_fills_feed_risk_reconciliation_and_pnl`
  - `tests/integration/autonomy/test_rollback_drill_gate.py::test_drill_fills_excluded_from_n_and_kill_clock`
  - `tests/integration/autonomy/test_rollback_drill_gate.py::test_gate_drill_runs_production_default_port_once`
  - `tests/integration/autonomy/test_rollback_drill_gate.py::test_drill_close_target_failure_after_1700_exit_path` (G1, E-5: closing pair fails after 17:00 → root HALT `trigger_cause_class=DRILL` → restorative RESUME at C+2 16:45 → root sends at C+2 16:50; outage ≤ 47 h 50 min)
  - `tests/integration/autonomy/test_rollback_drill_gate.py::test_abandoned_episode_interval_open_ended_and_reported_to_eta` (G7)
- `test_gate_drill_full_episode` asserts:
  - the exact §3.6.5 rows, modes and slots: pending pair at 15:30, ACTIVATE at 16:45, marker at 15:02:30, DEMOTE/HALT at 15:07:30, RESUME and the closing ROLLBACK only in prelaunch;
  - the child's d0 = D;
  - the child DISPLACED HALTED→CHALLENGER;
  - byte identity of the restored sha;
  - `drill=true` from D 16:50 to D+3 16:50;
  - each marker → veto ≤ 15 min;
  - `post_verify` OK ×3;
  - the first post-swap ATTEST rows;
  - delivered events `DRILL_ARMED`, `DRILL_STARTED`, `DRILL_DEMOTED`, `DRILL_RESUMED`, `DRILL_HALTED`, `DRILL_ROLLBACK`, `DRILL_CLOSED`.
- `test_gate_drill_failure_matrix` covers R1–R7b at each step, including the abort path with `abort_halt`. It asserts no freeze except R7b (written by the AUT-5 engine) and that alerts are journaled.
- **GREEN:** passes in the full gate and is listed in the T1 lane (`scripts/ci/tier_lanes.py`).
- **Activation:** the gate is the schedule, so it is live on merge.

### AUT-7.WP6 — live drill wiring and evidence bundle (Wave 3, after the AUT-5b ruling and allowlist widening)
- **Scope:** `drill.step(mode)` in the daily, prelaunch and intraday modes; `build_drill_bundle` from the D+4 daily pass; the rollback and drill section of `deploy/systemd/README.md`; the drill-clause values (§3.6.3) handed to AUT-5's ruling.
- **RED first:**
  - `tests/unit/autonomy/test_drill_bundle.py::test_bundle_requires_chain_export_nodelog_delivery_items`
  - `tests/unit/autonomy/test_drill_bundle.py::test_bundle_cites_first_post_swap_attest_rows`
  - `tests/unit/autonomy/test_drill_bundle.py::test_bundle_refuses_on_missing_or_mismatched_node_log_line`
  - `tests/unit/autonomy/test_drill_bundle.py::test_bundle_lists_window_commits_against_allowed_set`
  - `tests/unit/autonomy/test_drill_bundle.py::test_bundle_emitted_only_from_d4_daily_pass_no_unit`
  - `tests/unit/autonomy/test_drill_bundle.py::test_bundle_write_once_0444`
  - `tests/unit/autonomy/test_drill_bundle.py::test_abandoned_aborted_or_pre_effect_failed_episode_bundle_is_marked_not_proof`
- **GREEN:** all pass, plus a gate-drill rerun.
- **Activation:** on merge, with the engine restart, **and only once WP3 is live** (G-13 reads the I-5a.1 `registry_composed` line, which exists only after WP3's activation gate). The drill starts on its own at `drill_first_eligible_date`; there is no timer to install.

### AUT-7.WP7 — AUT-7b execution (live, no code)
- The engine runs §3.6 unattended. The coordinator only observes, with a Monitor on the chain export and the bundle path (memory note `every-background-job-needs-a-watch`).
- **GREEN:** an independent scorer signs off the §6 bundle as complete.

## 5. Association

Interfaces consumed. Each is a blind assumption; if one is absent, AUT-7 raises it in that area's review and never forks it.

| Contract | From | Interface AUT-7 needs |
|---|---|---|
| C5 store | ARCH-0/AUT-5 | `VerifiedVenueChain`; `resolve_champion`; `RegistryStore.append(rows, *, expected_prior_seq, mode)` (atomic multi-row: MINT + ADMIT + pending pair; ROLLBACK + partner + ACTIVATE; SWAP_CANCEL + TARGET_INELIGIBLE); per-mode `KIND_MASK` admitting §3.1's kinds (daily: MINT, DRILL_ADMIT, DRILL_PROMOTE, SUPERSEDE, RETIRE; prelaunch: ACTIVATE, SWAP_CANCEL, TARGET_INELIGIBLE, ROLLBACK, SUPERSEDE, DISPLACED, RESUME, HALT; intraday: DEMOTE, HALT, SWAP_CANCEL, TARGET_INELIGIBLE; A-1); the resolver's per-row byte binding exposed as `verify_family_bytes(row)`; the child-write API; the drill counters incl. `drill_demotes`/`drill_halts` (V15); the errata E-5 counter `drill_close_restores` (≤ 1 per venue per day) and RESUME `cause=drill_close_restore` admitted in the prelaunch mask; the shared allocator if any |
| C5 columns and enums | ARCH-0/AUT-5 | `cause_code` ∈ {`rollback_failed`, `target_integrity`, …}; `halt_cause_class` incl. `ROLLBACK_FAILED`; `trigger_cause_class` on a `rollback_failed` HALT; `drill`, `drill_clause_sha256`, `paired_transition_id` (closed enums in `pins.py`) |
| C5 journal + export | ARCH-0/AUT-5 | the ARCH-0 rollback journal module; the daily export carries `evidence_journal_heads: {rollback, readiness}` (T7) |
| C5 engine | AUT-5 | phase hooks `rollback.step`/`drill.step`; the advisory 15:30 intent read through the G6 `mode=ro` URI (corrupt = OPEN, P7-6); `probe_open_intent` at 16:45; the `engine_input/v1` journal (P4-9); the `registry/drill/` directory under the engine's `ReadWritePaths=`; the exec-store halt mirror written **first** in the 16:45 pass and exposed to phase hooks as that pass's fresh mirror (errata E-2) |
| **I-5a.1** | AUT-5a | journaled supervisor signals `launch_target_integrity` and `launch_precheck_failed` (names per AUT-5a); node log lines `registry_resolved venue=<v> family_id=<id> registry_seq=<n> chain_head=<h> manifest_sha256=<m> artefact_sha256=<a>`, `registry_composed family_id=<id> artefact_sha256=<a>`, and `registry_boot_load_failed family_id=<id> stage=manifest\|artefact\|compose reason=<code>` (with `reason=sha_mismatch` distinguishable); node log FILE paths (memory note `trade-node-dies-with-the-session`) |
| **I-5a.2** | AUT-5a | **supervisor non-relaunch:** after a load failure, the supervisor never relaunches that resolved family before the next LAUNCH, and it triggers the intraday engine pass |
| **I-5a.3** | AUT-5a | **artefact handoff (P7-10):** the node passes the resolver's content-addressed store path and the row's `artefact_sha256`; the loader re-verifies by sha in one `O_NOFOLLOW` read (`test_node_loads_artefact_from_store_by_row_sha`); the manifest is consumed from the resolver and never re-read |
| C5 policy | AUT-5 ruling | the drill clause (§3.6.3) and `drill_clause_sha256`; RETIRE reasons; `DRILL_INJECT → DEMOTE` and `DRILL_INJECT_HALT → HALT`, class `DRILL`; the `RECOVERABLE_MODEL` map; policy values for `ROLLBACK_MIN_DWELL_H`, `ROLLBACK_TARGET_MAX_AGE_D`, `DRILL_MIN_DRAWDOWN_HEADROOM_FRAC` (P7-7), `INTRADAY_ATTEST_VERDICT_PERIOD_MIN`, `ATTEST_PERIOD_H`, `ATTEST_MARGIN_H`, each within its `pins.py` ceiling |
| C5 ROOT_ADMIT | AUT-5 | recovery after the KILL or a TERMINAL event (V6); AUT-7 never writes it, and reads it only as an `entered_kind` in the history |
| C4 | AUT-6 | the intraday producer evaluates `DrillMarkerDetector` for both ids; the `fee_schedule` DRIFT verdict (P7-11; E6/G-6); a permit-liveness `HEALTH` verdict (G-7) |
| C4 | AUT-5 | the `live.drawdown` verdict with `metrics.drawdown_used_frac`, drill fills included (G-9) |
| C4 | AUT-2 | post-STOP `RECONCILIATION` with `metrics.open_positions_by_family`, plus the intraday RECONCILIATION (W8) |
| C1 | AUT-1 | `drill` flag from `is_drill_fill`; `EntryVeto` records (`registry_halted`, `permit_lapsed`) |
| C2 | AUT-2 | `excluded_reason=drill`; drill rows keep `realized_pnl` and feed P&L/ROI |
| C4 live / KILL | AUT-4 | admissible-only n; the KILL clock keyed on `lineage_root_family_id`; `eta_date` accepts AUT-7's journaled lost-live-day counts (abandoned-episode open interval; E-5 outage) |
| §4.6 | AUT-6 | `deliver_with_proof` and the per-attempt delivery records |

**Cross-plan alignment (N-5).** ARCH Rev 9.2 §5.3 now carries the AUT-7 timeline (P7-14), and §10 tells AUT-5 to consume it unchanged. AUT-5's plan should cite §5.3 and this §3.6.5 and keep only the mechanics: KIND_MASK, the counters and the engine slots.

**Provided:**
- `champion_history`, `target_eligibility` and `readiness` → AUT-5 and AUT-6;
- `position_handoff_ok` → AUT-5, offered for PROMOTE as well (C-11);
- `drill_episodes` and `is_drill_fill` → AUT-1, AUT-2, AUT-4;
- `DrillMarkerDetector` (`DRILL_INJECT`, `DRILL_INJECT_HALT`) → AUT-6;
- the executed AUT-7b → the AUT-5 (PROMOTE/DEMOTE/RESUME) and AUT-6 (DEMOTE and HALT class) live proofs.

**Order:**
- WP1, WP2 (minus the journal part) and WP4 run in parallel in Wave 1. WP2's journal part follows ARCH-0's journal module.
- WP3 completes after AUT-5a (engine modes, resolver, **I-5a.1–3**) and AUT-6 (`deliver_with_proof`, producer, fee/permit verdicts). WP5 completes with them.
- WP6 follows AUT-5b, AUT-1 (drill flag), AUT-2b (drill exclusion and `open_positions_by_family`) and **WP3 live** (G-13).
- WP7 follows the §6 soak.

## 6. Live-proof protocol

**Preconditions (all observed, none hand-made):**
- the AUT-5a watch actor live ≥ 3 sessions with no `registry_unreadable`; I-5a.1–3 live (WP3 activation);
- ≥ 1 post-→CHAMPION ATTEST for fq_v1 (V5);
- an AUT-6 canary `delivered=true` record (`alerts_undeliverable` armed);
- the post-STOP and intraday RECONCILIATION producers emitting `open_positions_by_family`;
- the `fee_schedule`, permit and drawdown verdicts flowing; AUT-6 evaluating both marker detectors;
- the readiness journal running daily and verifying against the newest export (§3.5.3);
- a `registry_composed` line for fq_v1 at its last LAUNCH carrying the BOOTSTRAP row's `artefact_sha256` (G-13).

**Bundle** `/home/jon/.local/share/breezy/evidence/drills/drill_polymarket_us_<episode_id>.json` (0444, write-once, emitted by the D+4 15:30 daily pass). It cross-references:
1. **Chain export rows** `registry_polymarket_us_<D..D+4>.jsonl`:
   - MINT r0001 with d0 = D, DRILL_ADMIT, DRILL_PROMOTE+SUPERSEDE (D 15:30, pending), ACTIVATE (D 16:45);
   - the first post-swap ATTEST for r0001 (D), DEMOTE `DRILL_INJECT` (D+1), RESUME (D+2 16:45) and the first post-RESUME ATTEST;
   - HALT `DRILL_INJECT_HALT` (D+3), ROLLBACK+DISPLACED+ACTIVATE (D+3 16:45), the first post-ROLLBACK ATTEST for fq_v1, RETIRE (D+4).
   All are `decided_by=engine` with one pinned `engine_code_sha`, `drill=true` on episode rows, contiguous `venue_seq` and a verified chain head. The export's `evidence_journal_heads` match the journals.
2. **Node log files:** resolved and composed lines for r0001 at D, the HALTED boot at D+1, r0001 at D+2 and fq_v1 at D+3, each `artefact_sha256=9c0b6d6e66a587c1b4e14e5f95ff5cedb3c7195f62f8ad4238191fdd75923a5e`; both `registry_halted` set lines (D+1 DEMOTE, D+3 HALT) and the D+2 clear line.
3. **Verdict files:** `DRILL_INJECT` FAIL (bound marker) then PASS; `DRILL_INJECT_HALT` FAIL then PASS; both marker shas from the journal.
4. **Delivery records:** `delivered=true` for `DRILL_ARMED`, `DRILL_STARTED`, `DRILL_DEMOTED`, `DRILL_RESUMED`, `DRILL_HALTED`, `DRILL_ROLLBACK`, the three `POST_VERIFY_OK` and `DRILL_CLOSED`.
5. **No commit in the loop:** `git log --since=<D 15:30> --until=<D+4 15:30> --format='%H %s' -- deploy src` is empty, **or** every listed commit appears by sha in `allowed_commits` with its touched paths. None may touch `deploy/families/**`, `deploy/systemd/**`, `src/breezy/persistence/autonomy/**`, `src/breezy/persistence/live_orders_gate.py`, `src/breezy/app/trade.py` or `src/breezy/runtime/trade_supervisor*.py`. Every drill row's `engine_code_sha` is identical.
6. **Drill fills:** C1 `drill=true` and C2 `excluded_reason=drill`; live n and the KILL-clock counter unchanged; the same fills present in the drawdown, reconciliation and P&L inputs.

An aborted, abandoned or pre-effect-failed episode emits a bundle marked `status: failed|abandoned|failed_pre_effect`, which is never live proof. The coordinator copies a summary to `docs/evidence/AUT-7b_drill_<D>.md` after the fact; that step is outside the loop.

**Clock and ETA** (honest; build pace is not guaranteed):

| Milestone | Earliest | P50 | P90 |
|---|---|---|---|
| ARCH-0 merged | 2026-10-09 | 10-12 | 10-17 |
| WP1/2/4 merged; WP3/5 after AUT-5a (incl. I-5a.1–3) and AUT-6 | 10-16 | 10-21 | 10-28 |
| AUT-5b ruling + allowlist; AUT-2b; WP6 | 10-27 | 11-04 | 11-14 |
| Soak met → D | 11-02 | 11-09 | 11-19 |
| AUT-7b closes (D+4 bundle) = **live proof**, first episode | **2026-11-06** | **2026-11-13** | **2026-11-23** |
| One failed episode, retry under G-2 | — | — | **2026-12-23** (pre-effect) / **12-24** (nominal post-effect) / **12-27** (abort at D+6) |

**P90 recomputed for the r4 retry rule.** First D = 11-19; the nominal closing ROLLBACK E = 11-22 16:50; DRILL_ADMIT at 11-19 15:30.
- **Pre-effect failure at D** (16:45 cancel, lapse or 16:52:30 cancel): only the ADMIT is charged. D′ 15:30 ≥ 11-19 15:30 + 30 d = 12-19, so D′ = 12-19 with r0002. It closes 12-22, bundle **12-23**, margin to the 2027-01-25 KILL **33 days**. (r3's "slips one day" no longer holds: under V10 the child is single-use.)
- **Nominal post-effect failure** (closes at D+3): D′ 15:30 ≥ max(E + 27 d = 12-19 16:50, ADMIT + 30 d = 12-19 15:30), so D′ = 12-20. It closes 12-23, bundle **12-24**, margin **32 days**.
- **Worst abort** (closes at D + `drill_max_episode_days` = 11-25): D′ = 12-23, bundle **12-27**, margin **29 days**.
- **A second consecutive failure** pushes the bundle to 01-22..01-27: a 3-day margin at best and a miss at worst. **A second retry cannot be relied on before the KILL.**

A pre-arm failure is not charged and slips one day. A closing ROLLBACK that takes effect and fails after 17:00 is restored by E-5 at C+2 16:50 (≤ 2 sessions without a sender) and then follows the post-effect retry row. An abandoned episode adds its open-interval days to `eta_date` (§3.6.7). If the KILL fires TERMINAL first, DRILL_PROMOTE is refused (ARCH §5.3), and recovery is ROOT_ADMIT. The drill needs no natural fill, so the ~5 fills/day rate does not gate it.

**Evidence class:** "machinery proven, edge unproven". While `promote_enabled=false` the trigger→ROLLBACK chain is **gate-proven**, and the live drill proves the shared `plan_rollback`→LAUNCH path (§3.3.4). The exec-store HALT writers, the TERMINAL/INTEGRITY paths (incl. R7b), TARGET_INELIGIBLE and the post-17:00 `rollback_failed` HALT stay gate-proven (C6 P6-4).

## 7. Score-3 verification checklist (independent scorer)

| Criterion | Check |
|---|---|
| History immutable | `sqlite3 'file:/home/jon/.local/share/breezy/registry/registry.sqlite?mode=ro' ".backup <scratch>/reg_copy.sqlite"`, then `sqlite3 <scratch>/reg_copy.sqlite "UPDATE transitions SET kind=kind WHERE seq=1"` must fail with the trigger's ABORT, and the same for `DELETE`; production is never written. Plus `tests/unit/autonomy/test_rollback_champion_history.py::test_history_never_reads_projection_or_families_cache` and `::test_history_render_equals_fold_and_is_write_once`. |
| (a) unattended | bundle item 1 (`decided_by=engine`, one `engine_code_sha`); item 5 |
| (b) family-agnostic | `tests/unit/autonomy/test_rollback_champion_history.py::test_every_champion_epoch_appears_in_history`, `::test_rollback_module_has_no_family_literals` |
| Trigger within one cycle, no code change | `tests/integration/autonomy/test_rollback_engine.py::test_demote_before_1645_rolls_back_at_same_day_launch`, `::test_demote_after_1645_rolls_back_at_next_launch`, `::test_prelaunch_writes_rollback_and_activate_atomically`, `::test_rollback_requires_no_code_change`; `tests/unit/autonomy/test_rollback_planner.py::test_rollback_dwell_never_delays_past_next_launch`; live: D+3 16:45 ROLLBACK+DISPLACED+ACTIVATE → D+3 16:50 boot line. The trigger leg is gate-proven while `promote_enabled=false`. |
| Target eligibility and integrity | `tests/unit/autonomy/test_rollback_eligibility.py` (one test per predicate, incl. `::test_e4_bound_equals_w1_invariant_terms`, `::test_rollback_fee_check_uses_verdict_not_node_memory`, `::test_selection_skips_target_integrity_candidate_and_moves_on`, `::test_target_integrity_clears_only_by_two_clean_readiness_passes`); `tests/integration/autonomy/test_rollback_engine.py::test_target_manifest_mismatch_marks_ineligible`, `::test_activate_reverifies_incoming_manifest_and_artefact_shas` |
| P7-7 values | ARCH `test_rollback_dwell_age_and_drill_headroom_ceilings`; `tests/unit/autonomy/test_rollback_planner.py::test_rollback_dwell_delays_never_refuses`; `tests/unit/autonomy/test_rollback_eligibility.py::test_target_refused_past_age_cap`; `tests/unit/autonomy/test_drill.py::test_drill_start_gate_each_condition[G-9]` |
| Position handoff | `tests/unit/autonomy/test_rollback_eligibility.py::test_position_handoff_owned_or_flat_else_refused`, `tests/integration/autonomy/test_rollback_drill_gate.py::test_gate_drill_position_open_across_each_swap` |
| (c) fails closed, no venue freeze | `tests/integration/autonomy/test_rollback_engine.py::test_failed_rollback_halts_champion`, `::test_rollback_failed_never_freezes_venue`, `::test_target_byte_mismatch_ineligible_without_freeze`, `::test_first_launch_target_integrity_cancels_at_165230_and_restores_incumbent`, `::test_first_launch_failure_after_1700_halts_rollback_failed`, `::test_champion_own_artefact_mismatch_past_first_launch_is_aut5_integrity_halt`, `::test_rollback_failed_exits_by_resume_retry_or_retire_then_root_admit`; `tests/integration/autonomy/test_rollback_drill_gate.py::test_gate_drill_failure_matrix`; `tests/unit/autonomy/test_rollback_eligibility.py::test_autonomy_rollback_introduces_no_cause_code` |
| (d) detected + delivered | `tests/integration/autonomy/test_rollback_engine.py::test_rollback_alerts_journal_delivery`; bundle item 4; `tests/unit/autonomy/test_rollback_journal.py::test_journal_verified_against_newest_export_heads`, `::test_journal_head_mismatch_blocks_rollback_and_alerts`, `::test_journal_missing_tail_blocks_rollback_and_alerts` |
| Damping | `tests/unit/autonomy/test_rollback_planner.py::test_at_most_one_widening_decision_per_venue_per_prelaunch_pass`, `::test_rollback_resume_ping_pong_damped_by_ceilings`, `::test_budget_exhausted_halt_charges_no_rollback_budget`; ARCH `test_damping_ceilings` |
| (e) RED→GREEN | WP commit messages; full-gate EXIT=0 per merge |
| Drills scheduled | gate: `tests/integration/autonomy/test_rollback_drill_gate.py` in the T1 lane (`scripts/ci/tier_lanes.py`); live: `drill_cadence_days` and `drill_first_eligible_date` in the sha-pinned policy block, plus the journal of daily `drill_arm_gate`/`drill_start_gate` decisions |
| Drill HALT step and counters (P6-4, V15) | `tests/integration/autonomy/test_rollback_drill_gate.py::test_gate_drill_full_episode`; `tests/unit/autonomy/test_drill.py::test_drill_halt_never_freezes_or_writes_exec_store`, `::test_drill_demote_and_halt_counters_capped`; bundle items 1–4 |
| Marker (U7, V12) | `tests/unit/autonomy/test_drill_inject.py::test_marker_read_via_verified_directory_descriptor`, `::test_drill_marker_read_error_never_resumes`, `::test_other_detector_marker_is_error_not_pass_or_fail`; `tests/unit/autonomy/test_drill.py::test_marker_writer_refuses_while_non_drill_cause_stands` |
| Child identity (V10) | `tests/unit/autonomy/test_drill.py::test_drill_child_d0_equals_pair_effective_date_and_exceeds_lineage_d0`, `::test_pre_effect_failure_retires_child_and_retry_mints_new_child_after_30d`; ARCH `test_child_d0_and_trial_prefix_pinned`, `test_rollback_to_earlier_child_passes_d0_rule`, `test_resume_not_subject_to_d0_rule` (AUT-5) |
| Timeline and budget never strands (P7-14) | `tests/unit/autonomy/test_drill.py::test_drill_timeline_matches_aut7_sequence`, `::test_drill_start_gate_requires_27d_after_newest_charged_row_and_30d_after_admit`; `tests/integration/autonomy/test_rollback_drill_gate.py::test_failed_episode_retry_never_strands_closing_rollback` |
| Genuine fault on child | `tests/integration/autonomy/test_rollback_drill_gate.py::test_genuine_fault_on_drill_child_never_restores_identical_artefact`, `::test_genuine_fault_with_no_eligible_target_leaves_venue_without_sender_and_alerts`; `tests/unit/autonomy/test_rollback_eligibility.py::test_drill_close_refused_when_genuine_fail_follows_drill_halt`, `::test_e9_passes_only_for_drill_or_drill_triggered_rollback_failed_else_sha_must_differ` |
| Failed drill close (E-5) | `tests/integration/autonomy/test_rollback_drill_gate.py::test_drill_close_target_failure_after_1700_exit_path`; `tests/unit/autonomy/test_drill.py::test_restorative_resume_never_for_child_or_after_genuine_fault`, `::test_restorative_resume_charges_no_drill_or_production_budget_and_is_capped_per_day_and_episode` |
| Fresh mirror, stale marker, G-13 | `tests/integration/autonomy/test_rollback_engine.py::test_prelaunch_pass_mirrors_exec_store_before_g1_e8_e9`; `tests/unit/autonomy/test_drill.py::test_intraday_pass_sweeps_committed_or_expired_marker_before_evaluating`, `::test_drill_gates_require_incumbent_composed_line_with_row_sha`, `::test_drill_start_gate_window_boundary_is_strict_at_write_time` |
| (f) live proof | the bundle is complete; restored sha = `9c0b6d6e…923a5e`; ≥ 4 trading days D…D+3 |
| Drill exclusion, risk inclusion | `tests/integration/autonomy/test_rollback_drill_gate.py::test_drill_fills_excluded_from_n_and_kill_clock`, `::test_gate_drill_fills_feed_risk_reconciliation_and_pnl`; ARCH `test_detectors_and_drawdown_include_drill_fills` |

## 8. Risks and failure modes

| ID | Risk | Mitigation |
|---|---|---|
| K-1 | Fee drift during the drill: the exec-store `policy_halt` on r0001 is TERMINAL and freezes the fq_v1 lineage | Accepted fail-closed cost (Z20 analogue). G-6 requires a `fee_schedule` PASS at D 16:45. Recovery is ROOT_ADMIT of a reviewed root. |
| K-2 | Each drill costs ≈ 10 drill fills, ≈ 1.1 vetoed sessions and 3 live days of n (V19) | Cadence 60 d from completion; at most 2 completed drills before the KILL; AUT-5 adds the days to `eta_date`. |
| K-3 | The champion-scoped KILL clock (`promotion_criteria.py:135`) would follow r0001 | AUT-2/AUT-4 key it on `lineage_root_family_id` and exclude drill intervals. |
| K-4 | An AMBIGUOUS intent open at 16:45 defers the drill or a rollback (Z19) | R4 writes nothing and retries daily. In a drill abort with r0001 CHAMPION, P7-3 HALTs r0001 (fail-closed). AUT-2 measures the rate. |
| K-5 | Byte drift of a committed root or of the C3 copy | The resolver reads the C3 copy (P7-5), so repo drift does not poison the target. C3 drift writes TARGET_INELIGIBLE, selection moves on, and the flag clears after two clean readiness passes. |
| K-6 | F-2 path re-read | WP3 does not activate until I-5a.3 (P7-10 handoff) is live; R5–R7b are the backstops. |
| K-7 | Memory on the 30 GiB (31 GB) host | Runs inside the engine's ≤ 4G own-lock budget (V14); no new unit; the bundle builder streams the export and reads only the node-log lines it needs. |
| K-8 | Shared venv, concurrent agents | Exact interpreter; no `uv`/`pip`/`git stash`; per-agent scratchpads; `PYTHONPATH`; disjoint files; full gate after every merge; the ARCH-0 journal module is touched only after ARCH-0 merges. |
| K-9 | Engine crash mid-drill | State re-derived from the chain and journal; idempotent ids; a chain-pure allocator; a crash between 15:30 and 16:45 lets the pending pair lapse (pair uncharged; the child is single-use, K-17); the heartbeat veto bounds exposure. |
| K-10 | Statistical capacity | No edge claim. |
| K-11 | KILL 2027-01-25 | P90 first episode 11-23; one failed episode retried under G-2 closes by 12-23 to 12-27 (29–33 d margin); a second retry cannot be relied on. |
| K-12 | No eligible target live while `promote_enabled=false` | Stated in §3.3.4 and §6; the trigger path is gate-proven; readiness reports `NO_TARGET` as INFO. |
| K-13 | The interim post-verify line logs the manifest pin before the load | Interim only; WP3 activation waits for I-5a.1's signals and lines. |
| K-14 | A journal mismatch or missing tail blocks all rollbacks and keeps target flags set | Fail-closed by design (T7); RESUME and restrictive writes stay open (L-48); clears when verification passes again. |
| K-15 | A genuine fault on r0001 that never clears, or fq_v1 ageing past E5 before the deferred close | r0001 stays HALTED or remains champion; drills stay blocked by G-1; the venue may have no sender (fail-safe, daily CRITICAL). The ~4-day episode bounds the probability; ROOT_ADMIT of a reviewed root is the recovery. **n and KILL-clock effect:** while the abandoned interval is open every r0001 fill is `drill=true`, so n and the KILL-clock counter do not advance; the open-interval days are journaled daily and handed to AUT-4's `eta_date` (§3.6.7); the 2027-01-25 date does not move, so a long-open interval can make the KILL fire on frozen evidence, which is the conservative direction. |
| K-16 | A post-verify false positive (missing line) HALTs a healthy target with `ROLLBACK_FAILED` | Grace to 17:30 for a missing line; a mismatch HALTs at once. Accepted fail-closed cost: the class never freezes the venue. |
| K-17 | **Single-use child (V10):** a pre-effect failure after arming spends the episode's `DRILL_ADMIT` and delays the retry 30 d | The arm gate (15:30) screens every 16:45 check it can see in advance (G-1..G-7, G-9, G-11, G-12 incl. the MINT ceiling, G-13), leaving only the post-STOP reconciliation, the binding intent probe, the fresh mirror and V11 re-verification for 16:45. The ETA states the 30 d (12-23 P90). |
| K-18 | A HALTED `ROLLBACK_FAILED` family with no exit occupies the venue slot, so ROOT_ADMIT cannot seat a new root | Fail-safe (entries stopped, exits live), daily CRITICAL. It exits by RESUME under its trigger class, a later rollback, or RETIRE on a TERMINAL cause or exhausted model budget (§3.5.2). |
| K-19 | The first-LAUNCH SWAP_CANCEL misses 17:00 (16:52:30 and 16:57:30 both fail) | G folds CHAMPION unloaded: HALT `rollback_failed` (or the drill abort), no sender that day, recorded by AUT-5 as a lost live day (V19). For the drill's closing pair, see K-20. |
| K-20 | **Failed drill close strands the root (E-5):** the closing ROLLBACK takes effect and fails after 17:00, leaving `fq_v1` HALTED `ROLLBACK_FAILED` with `trigger_cause_class=DRILL`; its normal RESUME would charge the spent `drill_resumes` (≈ 28 days with no sender) | The E-5 restorative RESUME (§3.6.6 step 4). **Outage bound:** close day C 17:00 → C+2 16:50, ≤ 47 h 50 min, 2 sessions (cooldown applied conservatively, A-7). **ETA effect:** ≤ 2 lost live days handed to AUT-4's `eta_date`; the episode is `failed`, and the retry follows G-2 unchanged (P90 bundle 12-24, 32-day margin). **Residual:** after a genuine fault, a byte mismatch, an open `target_load_failed` record or a second failure in the episode, no restorative RESUME is written; the root stays HALTED (fail-safe, exits live, daily CRITICAL) and exits by §3.5.2 steps 1–3 or ROOT_ADMIT. |
| K-21 | **Mint starvation of the arm (A-4):** an AUT-3 MINT on the fq_v1 lineage the same UTC day (refit slot 06:00 precedes 15:30) makes `MAX_MINTS_PER_LINEAGE_PER_DAY` (≤ 1) refuse the drill MINT | Each starved day is an uncharged pre-arm slip of exactly one day. **Bound:** starvation lasts exactly as many consecutive days as AUT-3 mints on that lineage; AUT-7 cannot bound AUT-3's mint frequency, so readiness journals the consecutive starved-day count daily and sends CRITICAL `DRILL_ARM_MINT_STARVED` once per day when the next possible bundle (today + 1 + 4 d) would leave less than one G-2 retry span (30 d + 4 d) before the 2027-01-25 KILL. The drill MINT at 15:30 never starves AUT-3, whose next refit is the next UTC day. |

## 9. Binding-constraint compliance

- **Nautilus:** untouched. Only the existing native `Actor` pattern is consumed (AUT-5).
- **Caps:** never read, assigned or derived. The drawdown headroom (G-9) is a `pins.py` risk floor with a policy value, not an operator cap. `test_autonomy_never_reads_or_writes_operator_controls` covers every AUT-7 module.
- **allow_short:** stays `False`. The child equals the root on every size and side key.
- **NO-SEND:** unchanged. The gate drill runs under `scripts/ci/run_tests_no_egress.sh`. The only egress is `deliver_with_proof` on the existing `alerts.env` key (`test_autonomy_alert_egress_not_widened`).
- **Master enablement and permit:** untouched. G-7 only reads a permit-liveness verdict. Rollback and drill change only which allowlisted family the resolver names.
- **PREREG via ruling:** the drill clause, cadence, windows and the policy values of the three P7-7 constants live only in the AUT-5 sha-pinned policy block under `pins.py` ceilings. AUT-7 adds no constant of its own.
- **Safety tests:** none weakened; the §4.7 list stays green. Every r3 test renamed or replaced in r4 (`test_no_fallback_to_older_target_on_byte_failure`, `test_no_dwell_constant_in_rollback_module`, `test_rollback_failed_class_is_never_resumed_and_exits_by_retried_rollback`, `test_drill_retry_after_cancel_writes_new_pair_at_next_daily_reusing_r0001`, `test_marker_detector_field_selects_detector`) was a planned, unwritten test that contradicted frozen ARCH. Its replacement asserts the ARCH rule, so nothing in the repo is weakened. r5 only adds tests and tightens predicates (E9 clause ii, G-2 strict `>`, G-12 ruling check, G-13, the fresh mirror, the stale-marker sweep). `test_autonomy_rollback_introduces_no_cause_code` (planned, unwritten) asserts that AUT-7 writes only `rollback_failed` and `target_integrity` as `cause_code` and only the errata E-5 `drill_close_restore` as a RESUME cause; that admits exactly the binding errata value. The E-5 restorative RESUME bypasses no cap: it is store-capped (`drill_close_restores`), never touches operator controls, and AUT-7 adds a per-episode limit and the cooldown on top.

## 10. Self-score

| Axis | Score | Note |
|---|---|---|
| Fidelity | 20/20 | Every Rev 9.2 §10 AUT-7 obligation is mapped (§1) and conformed, plus errata E-2 (fresh mirror) and E-5 (restorative RESUME). The remaining A-items are non-blocking requests to state what the plan already conforms to. |
| Correctness | 19/20 | The H-1 strand is closed with a stated outage bound; E9 now catches a genuine FAIL hidden behind first-cause-wins; G-2's boundary is strict and pinned. The I-5a.1 signal names are still AUT-5a's to fix. |
| Specificity | 14/15 | Exact modules, rows, slots, marker read and sweep, predicates and full test paths. |
| Acceptance | 19/20 | Scorer-runnable checks for every criterion, obligation and r5 item. The trigger leg stays gate-proven while `promote_enabled=false`. |
| Autonomy-safety | 15/15 | No venue freeze from a rollback; selection never loads corrupt bytes; no stale mirror or stale marker is ever read; the restorative RESUME is capped per day and per episode and never follows a genuine fault. K-15, K-17, K-18, K-20 and K-21 are stated residuals. |
| Reuse | 9/10 | ARCH-0 journal, the C5 TARGET_INELIGIBLE and RESUME rows, resolver binding, exit gate, probe, exec-store mirror, AUT-6 fee verdict and ROOT_ADMIT reused; no new unit. |
| **Total** | **96/100** | r4 self-scored 93 (reviewers 93/90). r5 applies G1–G8 and E-5 and gains 3 points. |

## 11. ARCH assumptions and open clarifications (against Rev 9.2)

r3's C-1..C-10 and N-1..N-4 are resolved by Rev 9.2 and deleted (§R4). Still open, all **non-blocking**. In each case the plan already conforms to the ARCH text, and the item only asks ARCH or AUT-5 to state it.
- **C-11.** §4.4 has no position-ownership precondition. AUT-7 applies `position_handoff_ok` to its own swaps (stricter, always true for FQ); ARCH may state it for PROMOTE too.
- **N-5 (cross-plan).** AUT-5's plan should consume the §5.3 timeline and §3.6.5 unchanged.
- **A-1 (KIND_MASK).** C5 "Failed rollback" has the intraday pass write SWAP_CANCEL + TARGET_INELIGIBLE, while C5 "Demotion latency" lists the intraday restrictive kinds as DEMOTE, HALT, SWAP_CANCEL and ATTEST. AUT-7 follows the more specific failed-rollback text: AUT-5's intraday mask must admit TARGET_INELIGIBLE (restrictive, never counted), and its prelaunch mask TARGET_INELIGIBLE and HALT.
- **A-2 (TARGET_INELIGIBLE clear).** ARCH says the row is "cleared only by AUT-7's re-verification rule" but names no clearing row. AUT-7's rule is two clean daily re-verifications ≥ 24 h apart, journaled and verified against the export (§3.5 R2). If ARCH prefers an on-chain clear, it must add a row kind.
- **A-3 (first-LAUNCH failure after 17:00).** TARGET_INELIGIBLE is CHALLENGER→CHALLENGER, so it cannot mark a target that folds CHAMPION after 17:00. AUT-7 writes the `rollback_failed` HALT (whose `demoted_for_cause` already bars it as a target) and journals `target_integrity`.
- **A-4 (drill MINT and the mint ceiling).** C3 says a no-new-lineage MINT increments no lineage counter; C5 lists a mint-rate ceiling on ∅→SHADOW. AUT-7 treats `MAX_MINTS_PER_LINEAGE_PER_DAY` as applicable (G-12), so a same-day AUT-3 mint makes the arm a pre-arm failure (uncharged, retried next day). **Starvation bound:** the arm is delayed exactly one day per consecutive AUT-3 mint day on the fq_v1 lineage, which AUT-7 cannot bound itself; readiness journals the count and escalates under K-21. ARCH or AUT-3 may instead exempt the no-new-lineage drill MINT from the ceiling.
- **A-5 (single-use child).** V10's d0 rule makes a pre-effect retry mint a new child and wait for the 30 d `DRILL_ADMIT` window. §5.3's "6 with one retry" still holds; the extra calendar cost is in §6.
- **A-6 (other-detector marker).** C6 says "PASS only when the marker is absent". AUT-7 reads a marker naming the other detector as ERROR (`marker_other_detector`), never PASS and never FAIL. No RESUME depends on that verdict.
- **A-7 (E-5 and the cooldown).** E-5 lists its conditions and exempts the restorative RESUME from every budget, but does not say whether `RESUME_COOLDOWN_H` applies. AUT-7 applies it (the conservative reading), which sets the outage bound at ≤ 47 h 50 min instead of ≈ 24 h. If ARCH exempts it, the bound halves and no other text changes.
- **A-8 (E-5 AUT-7-stricter conditions).** AUT-7 also refuses the restorative RESUME on an open `target_load_failed` record and after one restorative RESUME per episode. Both are stricter than E-5 and only narrow it.

## §R5 Disposition (r4 → r5; review `reviews/AUT-7-r4-merged.md`, final 90; errata E-5)

**8 review items (G1–G8, 12 sub-items) and errata E-5, all APPLIED; 0 rejected; 0 deviations from frozen ARCH Rev 9.2 (sha `1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42`).** Every change tightens or adds; none relaxes a predicate, a cap or a test. r4 stays unchanged at `docs/plans/backlog/AUTONOMY_2026-10-03/AUT-7-rollback_plan_r4.md`.

| # | Item | r4 position | r5 change (where) | New tests |
|---|---|---|---|---|
| R5-1 | G1 [arch H-1] + errata E-5 | a closing ROLLBACK that took effect and failed after 17:00 HALTed the root with `trigger_cause_class=DRILL`; its RESUME charged the spent `drill_resumes`, stranding the venue ≈ 28 days | restorative RESUME `cause=drill_close_restore`, store-capped `drill_close_restores`, no budget charged, never for the child or after a genuine fault; AUT-7 adds the cooldown (A-7), an open-load-failure refusal and one per episode (A-8); outage bound ≤ 47 h 50 min; ETA effect (§1, §2, §3.1, §3.3.4, §3.4, §3.5 R5, §3.5.1, §3.5.2 step 0, **§3.6.6 step 4**, §3.6.7, §5, §6, **K-20**) | `test_drill_close_target_failure_after_1700_exit_path`, `test_restorative_resume_never_for_child_or_after_genuine_fault`, `test_restorative_resume_charges_no_drill_or_production_budget_and_is_capped_per_day_and_episode`, `test_restorative_resume_refused_on_byte_mismatch_open_load_failure_or_cooldown` |
| R5-2 | G2 [sec 1] | E9 read only F's standing halting class; a genuine FAIL after the DRILL HALT writes no row (V12), so it was invisible | E9 clause (ii) via the shared `genuine_cause_since_drill_promote`: any accepted non-DRILL DEMOTE/HALT-mapped FAIL or exec-store halt naming F since DRILL_PROMOTE fails E9; the same predicate drives the marker pre-check, the genuine-fault test and E-5 (§3.1, §3.3.2, §3.6.5, §3.6.6) | `test_drill_close_refused_when_genuine_fail_follows_drill_halt`, `test_drill_close_refused_when_exec_store_halt_follows_drill_promote` |
| R5-3 | G3 [arch M-1] | "if F's cause is any class other than DRILL, shas must differ" | E9 passes iff the class is `DRILL`, or `ROLLBACK_FAILED` with `trigger_cause_class=DRILL` (or the abort-close CHAMPION child), with clause (ii); otherwise G's sha ≠ F's (§3.3.2) | `test_e9_passes_only_for_drill_or_drill_triggered_rollback_failed_else_sha_must_differ` |
| R5-4 | G4 [sec 2] | a marker left after a commit-then-crash or an expired window made both detectors ERROR | every intraday pass first sweeps a marker whose step row is committed or whose window expired, journals `marker_swept`, then evaluates (§3.1, §3.6.5, §3.7) | `test_intraday_pass_sweeps_committed_or_expired_marker_before_evaluating` |
| R5-5 | G5 [sec 3] | no proof that the incumbent actually booted its row's bytes before a drill | gate **G-13** (newest `registry_composed` line at the incumbent's last LAUNCH carries the row's artefact sha), in both arm and start gates; WP6 depends on WP3 live (§3.4, §3.6.3, §4 WP6, §5 Order, §6) | `test_drill_gates_require_incumbent_composed_line_with_row_sha` |
| R5-6 | G6 [sec 4] + errata E-2 | E8 read "the engine mirror" without a freshness rule; G-12 did not check the child's ruling | the 16:45 pass mirrors the exec store first; G-1, E8, E9 and E-5 read only that fresh mirror, never the 16:41 one; G-12 adds the E3/E7 live-orders ruling check on the child (§2, §3.1, §3.3.2, §3.4, §3.6.3, §5) | `test_prelaunch_pass_mirrors_exec_store_before_g1_e8_e9`, `test_e8_reads_only_fresh_prelaunch_mirror_never_1641_mirror`, `test_drill_start_gate_g12_checks_child_live_orders_ruling` |
| R5-7 | G7 [arch M-2] | an abandoned episode's effect on n and the KILL clock was implied, not stated | open-ended drill interval stated, its end conditions named, open-interval days journaled daily and handed to AUT-4's `eta_date` (§3.6.6, §3.6.7, §5, §6, K-15) | `test_abandoned_episode_interval_open_ended_and_reported_to_eta` |
| R5-8a | G8 [arch L-1] | G-2 used `≥` on the 15:30 nominal | strict `>` evaluated at write time (`ts_ns` of the arm transaction), boundary pinned (§3.6.3) | `test_drill_start_gate_window_boundary_is_strict_at_write_time` |
| R5-8b | G8 [arch L-2] | G-7 said "before STOP at 16:45" | STOP is 16:40 (G22) (§3.6.3) | `test_g7_permit_pass_taken_before_1640_stop` |
| R5-8c | G8 [arch L-3] | A-4 had no starvation bound | one-day slip per consecutive AUT-3 mint day; daily journal; KILL-margin CRITICAL from existing values only (§11 A-4, **K-21**) | — (readiness reason codes covered by `test_readiness_reports_every_predicate_reason`) |
| R5-8d | G8 [arch L-4] | §3.3.3 INCONCLUSIVE read as covering both branches | INCONCLUSIVE applies only to branch (a); an owned handoff (b) needs no metric (§3.3.3) | `test_handoff_inconclusive_only_when_branch_b_fails` |
| R5-9 | Housekeeping | — | header round r5; errata E-1..E-5 cited; §7 rows added; §9 notes the E-5 cause value and no weakening; §10 re-scored; §11 A-7, A-8 added | — |

**Counts:** 12 review sub-items + E-5 applied; 16 new RED tests; 1 new gate (G-13); 2 new risks (K-20, K-21); 2 new clarifications (A-7, A-8); 0 tests weakened or removed; 0 caps read, assigned or bypassed.

## §R4 Rebase disposition (onto FROZEN ARCH Rev 9.2, sha `1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42`, plus `reviews/ARCH-ERRATA-rev9_2.md`)

**20 changes, all CONFORMED to ARCH; 0 deviations retained.** Where r3 contradicted Rev 9.2, the plan now follows ARCH. r3 stays unchanged at `docs/plans/backlog/AUTONOMY_2026-10-03/AUT-7-rollback_plan_r3.md`. Its §R3 dispositions T1–T8 and the r2 K-ids still stand, except where a row below supersedes them (T5 retry, T6 dwell, T8 interface, K5 retry).

| # | ARCH Rev 9.2 source | r3 position | r4 change (where) |
|---|---|---|---|
| R4-1 | README Items table (FROZEN Rev 9.2); PLAN_TEMPLATE "ARCH basis"; errata E-1..E-4 | Rev 6, sha `81c3c79f…` | Header and §1 rebased; Rev 9.2 §10 obligations quoted verbatim and mapped to sections; sha cited; E-3 tag reading adopted; E-2 noted as AUT-5's (AUT-7 never writes ROOT_ADMIT); E-1/E-4 have no AUT-7 surface (§0, §1) |
| R4-2 | C5 HALT row and "Failed rollback" (P7-3, P7-8); RESUME row | `ROLLBACK_FAILED` "never RESUMEs" (§3.5.2); no `trigger_cause_class` | HALT carries `trigger_cause_class`; the family RESUMEs only under that class, charged to it; exit order RESUME → retried rollback → RETIRE then ROOT_ADMIT; the production trigger includes a `rollback_failed` HALT with a model trigger class (§1, §3.3.1, §3.3.4, §3.5.1, §3.5.2) |
| R4-3 | C5 TARGET_INELIGIBLE row (V11, P7-13); "selection moves on" | journal-only `target_integrity` (N-4); "no fallback past an integrity failure" (R2) | TARGET_INELIGIBLE row written at selection, ACTIVATE or first LAUNCH; selection **moves on** to older candidates; journal mirror; AUT-7 clearing rule; `target_integrity_ineligible` epoch flag (§3.2, §3.3.2, §3.5 R2, §3.5.1) |
| R4-4 | C5 ACTIVATE and ROLLBACK rows (V11); "First LAUNCH of a new pair" | bytes checked at selection only; post-launch byte drift handled as R5 with no cause | manifest **and** artefact shas re-verified at selection and ACTIVATE (incl. the drill pair, G-12); first-LAUNCH failure → 16:52:30 SWAP_CANCEL (`target_integrity`) + TARGET_INELIGIBLE; `launch_precheck_failed` → SWAP_CANCEL with no cause (§3.3.4, §3.4, §3.5 R5/R6) |
| R4-5 | C5 "Champion's own bytes" and artefact handoff (P7-10) | AUT-7 wrote HALT `rollback_failed` with class INTEGRITY (R7b) | R7b is the AUT-5 engine's INTEGRITY HALT; AUT-7 only classifies it and writes no INTEGRITY row; one AUT-7 HALT shape (`ROLLBACK_FAILED`) (§3.5 R7b, §3.5.1) |
| R4-6 | C5 `lineage_counters` `drill_demotes`, `drill_halts`; §4.5 drill row (V15) | budget items enforced only at the marker writer (N-2) | store-enforced counters (≤ 1, refused above), with a marker-writer pre-check; a refusal aborts (§3.6.5, §3.6.7; `test_drill_demote_and_halt_counters_capped`) |
| R4-7 | §4.2 Child identity (V10, U1, R9.2-Z1): d0 tied to the first →CHAMPION row; ROLLBACK and RESUME exempt | child kept the root's d0 (3 keys); retry reused r0001 | child changes **4** keys with d0 = D; the child is single-use; a pre-effect retry RETIREs it and mints a new child after the 30 d `DRILL_ADMIT` window; G-2 adds the ADMIT term; G-12 added; E11 records the ROLLBACK exemption; P90 recomputed (12-23/12-24/12-27) (§3.3.2, §3.6.3, §3.6.4, §3.6.5 Retry, §6, K-17, A-5) |
| R4-8 | C6 `DRILL_INJECT` (U7, V12, Z2) | marker read by path; another detector's marker → PASS | fixed `registry/drill/marker.json` read via `O_DIRECTORY\|O_NOFOLLOW` + `fstat` + `openat`; PASS only on marker `ENOENT`; directory `ENOENT` → ERROR; other-detector marker → ERROR; ERROR never resumes; first-cause-wins pre-check (§3.6.5, A-6) |
| R4-9 | §4.4 "no intraday RESUME horizon exists" (P7-9) | C-9 open contradiction | C-9 deleted; RESUME only at 16:45 (`test_resume_written_only_at_prelaunch`) (§3.4, §11) |
| R4-10 | §4.5 P7-7: `ROLLBACK_MIN_DWELL_H` ≥ 24, `ROLLBACK_TARGET_MAX_AGE_D` ≤ 30, `DRILL_MIN_DRAWDOWN_HEADROOM_FRAC` ≥ 0.5 | dwell deleted (T6); age cap and headroom as open asks (C-7) | the three ceilings consumed; `dwell_ok` delays and never refuses, proven never to delay past the next LAUNCH; drill dwell 24 h 05 min; C-7 deleted (§3.3.2 E5, §3.3.4, §3.6.3 G-9) |
| R4-11 | C5 "Fee verified" (P7-11) | fee PASS produced after STOP, citing an AGREE line within 4 h and a θ match | newest accepted `fee_schedule` DRIFT PASS within `ATTEST_VERDICT_VALIDITY_H`; none = unverified; θ covered by §4.2 (E6, G-6) |
| R4-12 | C5 Pickup "Artefact handoff" (P7-10) | I-5a.3 = bytes passed to composition | I-5a.3 = store path plus row sha, re-verified by sha at load (`test_node_loads_artefact_from_store_by_row_sha`); F-2 and the WP3 activation gate restated (§2, §4 WP3, §5) |
| R4-13 | C5 ROOT_ADMIT row (V6); §5.3 After the KILL | "only a reviewed new root recovers" | recovery after the KILL or a TERMINAL event is AUT-5's ROOT_ADMIT; interplay with a HALTED `ROLLBACK_FAILED` family stated (K-18) (§3.3.1, §3.5.2, §3.6.6, §5) |
| R4-14 | C5 entry veto `registry_attest_expired` armed only by post-→CHAMPION/RESUME ATTESTs (V5) | `last_attest_ns` = any ATTEST while CHAMPION | `last_attest_ns`, E4 and G-3 count only ATTESTs after the latest →CHAMPION or RESUME row; the first post-swap ATTESTs are bundle evidence (§3.2, §3.3.2, §3.6.3, §3.6.5, §6) |
| R4-15 | §5.2 launch-window table (V7) | intraday "15:00/17:05" times; no slot mapping | actions mapped to §5.2 firings: marker 15:02:30, commit 15:07:30, 16:47:30 yield, 16:52:30 guaranteed and 16:57:30 best-effort, post-verify from 17:02:30, missing line 17:32:30; `test_aut7_actions_only_in_listed_engine_slots` (§3.6.5, §3.7) |
| R4-16 | §4.4 W8 horizon split | 15:30 arm had no reconciliation check | 15:30 pending write requires the newest intraday RECONCILIATION PASS; 16:45 the post-STOP PASS (G-5, §3.4) |
| R4-17 | C5 columns and per-mode writes | KIND_MASK without TARGET_INELIGIBLE; no column list | KIND_MASK adds TARGET_INELIGIBLE (prelaunch, intraday) and HALT (prelaunch); columns `trigger_cause_class`, `drill`, `drill_clause_sha256`, `paired_transition_id` consumed (§3.1, §5, A-1) |
| R4-18 | §4.7 Rev 8/9/9.1 test names | r3 local names | ARCH names adopted (`test_rollback_failed_never_freezes_venue`, `test_target_byte_mismatch_ineligible_without_freeze`, `test_target_manifest_mismatch_marks_ineligible`, `test_resume_written_only_at_prelaunch`, `test_rollback_fee_check_uses_verdict_not_node_memory`, `test_drill_marker_read_error_never_resumes`, `test_drill_demote_and_halt_counters_capped`, `test_drill_timeline_matches_aut7_sequence`); r3-only tests that contradicted ARCH are replaced (§4, §9) |
| R4-19 | Task directive: delete resolved contradictions | §11 C-1, C-3..C-10 resolved/open; N-1..N-4 | C-1..C-10 and N-1..N-4 deleted as resolved by Rev 9.2; C-11 and N-5 kept; A-1..A-6 added as non-blocking clarifications already conformed (§11) |
| R4-20 | PLAN_TEMPLATE programme-wide rules; `reviews/*-decision.md` | relative test shorthands; runtime paths under `~` | every path absolute (`/home/jon/.local/share/breezy/…`) or repo-root-relative, with full `path::test` names; systemd rule stated (no new unit; ARCH unit tests consumed, §3.7); ROLLBACK-FAILURE consumed via ARCH C5, and ALPHA/HOLDOUT confirmed as having no AUT-7 surface (§0, §4) |

**Resolved r3 items deleted from §11:** C-1 (P7-1), C-3 (P7-3 + decision, now C5), C-4 (P7-4), C-5 (P7-5), C-6 (P7-6), C-7 (P7-7 ceilings), C-8 (`ROLLBACK_FAILED` never `RECOVERABLE_INFRA`, P7-8), C-9 (intraday RESUME clause removed), C-10 (P7-10 handoff); N-1 (`ROLLBACK_FAILED` in C5), N-2 (V15 counters), N-3 (C5 "on the champion if it still folds CHAMPION … halts only that family"), N-4 (TARGET_INELIGIBLE row).
