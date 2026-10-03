# AUT-7 — Rollback (incl. AUT-7a gate drill, AUT-7b live promotion/rollback drill) — plan r1

## 0. Header

| Field | Value |
|---|---|
| ID | AUT-7 (sub-items AUT-7a gate drill, AUT-7b live drill) |
| Title | Rollback: immutable champion history, automated rollback, fail-closed failure, scheduled drills |
| Round | r1 (2026-10-03) |
| ARCH consumed | `AUTONOMY_ARCHITECTURE.md` Rev 4, sha256 `175310117eec39b22fc8229788a7d6182c6395438db23ec65ceb78b964dd508e` (frozen scratchpad copy is byte-identical); code evidence at `4b8347a6` |
| Current score | 2 (README: sha-pinned manifests make rollback a manifest swap; no previous-champion pointer, no trigger, no drill) |
| Target | 3 |
| Upstream | ARCH-0 (C5 store, chain, fold, resolver, `pins.py`), AUT-5 (engine modes, policy ruling + drill clause, watch actor, lineage allowlist), AUT-6 (`deliver_with_proof`, intraday producer), AUT-1 (C1 `drill` flag writer), AUT-2 (C2 `excluded_reason=drill`, `RECONCILIATION` verdict) |
| Downstream | AUT-5 live proof (the AUT-7b drill is its PROMOTE/DEMOTE/RESUME evidence, README AUT-5), AUT-6 (DEMOTE action class proven through the live path), AUT-4 (live n / KILL exclusion of drill fills) |

Planning only. Nothing here is implemented. All times are UTC.

## 1. Goal state

**README score-3 criterion (verbatim):**
- The registry keeps an immutable champion history.
- An automated rollback to the last good champion fires on the AUT-5 or AUT-6 triggers and takes effect within one supervisor cycle, with no code change.
- A failed rollback fails closed by halting the family.
- Drills run on a schedule in the gate and live.

**Live proof (verbatim):** "tracked as AUT-7b, with its own clock of at least 4 trading days: one live rollback drill through the production path, restoring the prior champion and its byte-identical artefact sha, logged, alerted and reversed, with no human commit (ARCH §5.3). After the 2027-01-25 KILL, the state defined in ARCH §5.3 applies."

**ARCH §10 AUT-7 obligations (verbatim):** "rollback-target selection (most recent `rollback_eligible`, not `terminal_frozen`, bytes re-verified); failed rollback → HALT; the gate drill (AUT-7a); the live drill steps for AUT-7b — mint the byte-identical child `pm_us_crh_fq_v1_r0001` (C3 no-new-lineage), DRILL_ADMIT it to CHALLENGER, DRILL_PROMOTE at LAUNCH, write the drill marker so `DRILL_INJECT` demotes it through the live path, remove the marker so the verdict PASSes, RESUME, ROLLBACK to `fq_v1` — with dates, the drill budget, and the evidence (chain, export, node log, delivery journal)."

Mandate from ARCH also consumed unchanged: C3 no-new-lineage (Y2); C5 rows ROLLBACK, DRILL_ADMIT, DRILL_PROMOTE, SWAP_CANCEL, SUPERSEDE/DISPLACED, RESUME, RETIRE; the node HWM; §4.5 `MAX_ROLLBACKS_PER_VENUE_30D ≤ 2`, `DRILL_BUDGET_PER_VENUE_30D ≤ 1`, `RESUME_COOLDOWN_H ≥ 24`; C6 `DRILL_INJECT`; §5.3 drill contract.

## 2. L-1 null hypothesis and reuse

| New component | Capability checked first (file:line) | Verdict |
|---|---|---|
| Champion history | Nautilus has no artefact registry or champion state (ARCH §2 L-1; `trade_supervisor.py:15-21`). C5 `transitions` (ARCH-0) is already the append-only, hash-chained, trigger-protected source of truth. | **No new store or table.** History is a pure fold over the verified venue chain (`champion_history`), never the `families`/`projection` caches (Y4). |
| Rollback-target byte verification | `load_family_manifest` hashes raw bytes once (`family_manifest.py:295-296`); `load_live_calibration` re-hashes the artefact (`calibration_artefact.py:251-257`), but it lives in the strategy layer, which `persistence` must not import (G15). AUT-5's resolver already does byte binding for LAUNCH (C5 Pickup Y6). | **Reuse the resolver's byte-binding function** (`resolver.verify_family_bytes`) so the engine verifies a target with the exact code the node runs at LAUNCH. No second verifier. |
| Rollback write | C5 ROLLBACK row + SUPERSEDE/DISPLACED partner through the AUT-5 store API (CAS, idempotent `transition_id`, Y9). | Reuse. AUT-7 adds a planner, not a writer. |
| "Halt the family" on failure | Exec-store `record_policy_halt` (`trial_day_latch.py:1155-1191`) needs the node's flock (G6, `_require_held` `:1176`), blocks exits (G5) and is cleared only by the operator CLI (`trial_day_latch.py:1246`). | **Rejected** for rollback failure. Use the registry HALT row (entry-only, exits stay live, ARCH C5). |
| Launch-time pickup | Supervisor schedule `STOP_PRIOR_UTC 16:40`, `LAUNCH_UTC 16:50`, `RELAUNCH_CUTOFF_UTC 17:00` (`trade_supervisor_core.py:37-44`); AUT-5a resolver at LAUNCH and `BREEZY_FAMILY_SOURCE=registry` in the committed unit. | Reuse. A rollback is only registry rows; no file under the repo changes. |
| Open-intent precondition | `probe_open_intent` (`trade_supervisor.py:402-420`) asserts no live node (`trade_supervisor_core.py:554-560`). | Reuse at the 16:45 pre-launch pass only (node stopped at 16:40). The 15:30 daily pass treats the precondition as advisory (§3.4, C-6). |
| Drill child manifest | `deploy/families/pm_us_crh_fq_v1.json` (805 B, REGISTERED, `density_artefact_sha256 9c0b6d6e…923a5e`); child-id regexes `settings.py:114` (`^[a-z0-9_:]+$`) and `trial_day_latch.py:301` (`^[A-Za-z0-9_-]{1,64}\Z`) both accept `pm_us_crh_fq_v1_r0001`. | Reuse the committed root bytes; the child differs only in §4.2-allowlisted keys. |
| Drill artefact (no-new-lineage) | No content-addressed copy of fq_v1's artefact exists; it is only at `deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json`. The node reads the artefact **CWD-relative** (`app/trade.py:788`, `str(manifest.density_artefact_path)`), the supervisor sets `cwd=repo_root` (`app/trade.py:113-118`). | The child keeps `density_artefact_path` and `density_artefact_sha256` **byte-equal** to the root, so it cites the existing committed bytes. No copy, no C3 writer, no `lineage_counters` change (Y2). Finding F-1 below. |
| DRILL_INJECT detector | C6 defines it as a dedicated `VERDICT` detector reading `registry/drill/marker.json`. Native Nautilus has no fault injection facility. | New, tiny (single-read marker → FAIL/PASS). |
| Periodic node pickup of DEMOTE/RESUME | `RegistryWatchActor` (AUT-5, the `FeeDriftProbeActor` loop-thread bridge `fee_drift_probe.py:358-372`). | Reuse; AUT-7 adds no node code. |
| Delivery proof | `deliver_with_proof` (AUT-6, §4.6); `emit_alert` swallows failures (`health.py:479-510`, G25). | Reuse; every AUT-7 alert goes through `deliver_with_proof` so the journal proves delivery. |

**Finding F-1 (pre-existing, verified 2026-10-03).** `_assert_artefact_path_contained` computes `allowed_root = manifest_dir / "deploy/families"` (`family_manifest.py:169,276-279`). For `deploy/families/x.json` that is `…/deploy/families/deploy/families` (a nonexistent directory, checked with the venv interpreter), so the check passes on a lexical phantom while the real read is CWD-relative (`app/trade.py:788`). Containment holds today only because the supervisor fixes the CWD. AUT-7 depends on this read semantics staying CWD/repo-root-relative for the drill child. AUT-5's four-site containment widening (C5 Pickup 3) must fix the base explicitly. Handed to AUT-5 as an input, with no AUT-7 edit to `family_manifest.py`.

## 3. Design

### 3.1 Modules (all new, in `src/breezy/persistence/autonomy/`, inside the engine's import closure, so `ENGINE_SOURCE_SHA256` is re-pinned in the same commit, §4.3)

| File | Purpose | Key interfaces |
|---|---|---|
| `rollback.py` | Champion history, target selection, trigger rule, planner, failure classification. Pure functions over the verified chain plus injected I/O ports. | `champion_history(chain: VerifiedVenueChain, now_ns) -> tuple[ChampionEpoch, ...]`; `select_rollback_target(history, chain, now_ns) -> TargetSelection`; `rollback_trigger(fold, chain, now_ns) -> RollbackTrigger \| None`; `plan_rollback(trigger, selection, ports) -> RollbackDecision`; `classify_failure(exc_or_refusal) -> RollbackFailure` |
| `drill.py` | The AUT-7b drill sequencer (a state machine derived from the chain, never stored separately), child-manifest composer, marker writer/remover, drill-episode intervals. | `drill_state(chain, now_ns) -> DrillState`; `compose_drill_child(root_bytes, child_id, d0, policy_ruling_id) -> bytes`; `next_drill_step(state, clause, now_ns, ports) -> DrillStep`; `drill_episodes(chain) -> tuple[DrillEpisode, ...]`; `is_drill_fill(episodes, family_id, ts_ns) -> bool` |
| `drill_inject.py` | The `DRILL_INJECT` C6 `VERDICT` detector. | `DrillInjectDetector.id = "DRILL_INJECT"`, `kind = "VERDICT"`, `evaluate(marker_path) -> DetectorOutcome` (FAIL while a well-formed marker exists, PASS when absent, `ERROR` on symlink/oversize/unparseable) |
| `rollback_journal.py` | Append-only evidence: `~/.local/share/breezy/evidence/rollback/rollback_<venue>_<ts_ns>.json` (0444, `mkstemp`+`os.replace`, schema `rollback-journal/v1`, exact-set, no paths, no env values). | `write_rollback_journal(record) -> str (sha256)` |

**Engine wiring** is a call from AUT-5's engine binary into `rollback.step(mode, ...)` and `drill.step(mode, ...)`. AUT-7 edits no `app/trade.py`, `settings.py` or `trade_supervisor*.py` (ARCH §5.1: AUT-5a alone).

### 3.2 Immutable champion history (criterion 1)

`ChampionEpoch` (frozen dataclass, explicit serialisation): `venue`, `family_id`, `lineage_root_family_id`, `manifest_sha256`, `artefact_sha256` (from the family's BOOTSTRAP/MINT row; immutable per family id, Z1), `entered_venue_seq`, `entered_kind` (`BOOTSTRAP`\|`PROMOTE`\|`DRILL_PROMOTE`\|`ROLLBACK`\|`RESUME`), `effective_from_ns` (the LAUNCH instant the fold made it effective), `left_venue_seq \| None`, `left_kind` (`SUPERSEDE`\|`DEMOTE`\|`HALT`\|`DISPLACED`\|`RETIRE`\|None), `rollback_eligible`, `demoted_for_cause`, `drill_episode` (bool).

- **Derivation.** It is a pure fold over `transitions` rows from genesis, verified by the AUT-5 chain verifier (hash links, export prefix). It is the same fold rule as `resolve_champion` (Y8): pending, lapsed and voided pairs never create an epoch (Z3).
- **Derived flags, never cached.** `rollback_eligible` is set by a SUPERSEDE whose subject is not a drill-episode family, cleared by DEMOTE/HALT, and never set by DISPLACED. `demoted_for_cause` is set by DEMOTE/HALT and by a cause on an incoming family (Y8). A "drill-episode family" is **exactly the subject of a DRILL_ADMIT row**. The incumbent superseded by a DRILL_PROMOTE is therefore `rollback_eligible` (required for the drill's ROLLBACK target).
- **Immutability.** History adds no new mutable state. It inherits the chain's `BEFORE UPDATE/DELETE → RAISE(ABORT)` triggers, the per-venue hash chain, the 0444 daily export and the node HWM (C5). The daily engine pass also renders `evidence/registry/champion_history_<venue>_<date>.json` (0444) for humans. Readers never consume this render; a test pins that it equals the fold.

### 3.3 Automated rollback (criterion 2)

**Trigger (code-fixed literal, no new policy key).** `rollback_trigger` fires when all of the following hold at the fold at `now`:
1. The venue's {CHAMPION, HALTED} slot holds family F in **HALTED**.
2. F's halting row is a DEMOTE or HALT whose cause class is `RECOVERABLE_MODEL`. These are the AUT-5 live-sequential and drawdown causes and the AUT-6 forecast, calibration, fill-rate and slippage drift causes, per the policy's `detector → action_class` map.
3. F is not a drill-episode family (the drill has its own sequence, §3.6).
4. No pending pair exists on the venue (Y8).

Causes that never trigger a rollback, with the reason:

| Cause class | Why no rollback |
|---|---|
| `RECOVERABLE_INFRA` | A feed, permit or unit fault hits any family equally. AUT-5's RESUME path is the cure. |
| `TERMINAL` | The lineage is `terminal_frozen`, so the store refuses ROLLBACK into it. The champion RETIREs (ARCH §5.3). |
| `INTEGRITY` | The venue is frozen for ROLLBACK until the operator CLI clears it (L-48 clearing path owned by AUT-5). |

**Target selection.** Walk `champion_history` backwards from F's epoch. The target is the **first** (most recent) epoch whose family G is all of:
- at fold state CHALLENGER;
- `rollback_eligible`, not `demoted_for_cause` and not a drill-episode family;
- in a lineage that is not `terminal_frozen`;
- a `composition_kind` in `LIVE_GATE_ROUTED_KINDS`;
- under a root in `_LINEAGE_POLICY_ALLOWLIST` or `_LIVE_ORDERS_ALLOWLIST` (`live_orders_gate.py:76-84`).

Then G's bytes are re-verified with `resolver.verify_family_bytes(G's BOOTSTRAP/MINT row)`: single-read manifest and artefact, sha equality to the row, the child-id regex and root, §4.2 equality against the committed root, and `O_NOFOLLOW`.
- **No fallback to an older target.** If the first candidate fails, the rollback fails (§3.5). This is deterministic and consistent with "no fallback to the lineage root" (C5 failure behaviour).
- **Budget.** `MAX_ROLLBACKS_PER_VENUE_30D` (≤ 2) is counted from history at effect (Z3), and pending pairs count as reservations.

**Write.** One `BEGIN IMMEDIATE` transaction through the AUT-5 API holds a ROLLBACK row (G: CHALLENGER→CHAMPION, `artefact_sha256`, `manifest_sha256` and `lineage_root_family_id` required, Y6) and its partner DISPLACED row (F: HALTED→CHALLENGER, `rollback_eligible` stays false). It carries `effective_launch_date` = the next LAUNCH date and `cause_verdict_ids` = F's halting cause ids. The `transition_id` is deterministic (Y9), so a crash-retry is a logged no-op.

**Effect within one supervisor cycle.** The planner runs in two engine modes:
- **Daily pass (15:30).** Proposes the pair for today's LAUNCH. The open-intent precondition is advisory here (§3.4).
- **Pre-launch pass (16:45, node stopped).** First runs `rollback_trigger`. If a trigger stands with no pair, it writes the pair **and** then runs the binding §4.4 checks (G30 probe, `RECONCILIATION` PASS in horizon, no INTEGRITY freeze). It writes `ACTIVATE` in the same pass, inside the C5 window [16:40, 16:50) (C5 fold Y8).

So any qualifying DEMOTE committed before 16:45 on day D takes effect at D's 16:50 LAUNCH. One committed in [16:45, 16:50) or during the session takes effect at the next LAUNCH. Worst case ≤ 24 h 05 min, and entries are already vetoed within ≤ 15 min of the cause (C5 latency SLO). Nothing swaps mid-day (C5 Pickup: the mid-day relaunch keeps its env). **No code change**: the supervisor resolves the fold at LAUNCH and passes the id to the child (G2). Rollback writes only under `~/.local/share/breezy/{registry,evidence}`.

### 3.4 Preconditions per mode

| Check | Daily 15:30 | Pre-launch 16:45 | Supervisor LAUNCH 16:50 |
|---|---|---|---|
| Open/AMBIGUOUS intent | advisory `mode=ro` read; skip the proposal if OPEN | binding: `probe_open_intent` (node down) | binding re-check (C5 §4.4) |
| `RECONCILIATION` PASS within horizon (AUT-2) | required | required | — |
| Target bytes (`verify_family_bytes`) | required | required (re-run) | resolver re-runs at boot (Y6) |
| Budgets, lineage freeze, INTEGRITY freeze | required | required | resolver refusals |

### 3.5 Failed rollback fails closed (criterion 3)

| # | Failure | Detected by | Effect |
|---|---|---|---|
| R1 | No eligible target, budget exhausted, or venue INTEGRITY-frozen | planner | F already HALTED, so it stays HALTED (entries vetoed, exits live). Journal + CRITICAL `ROLLBACK_UNAVAILABLE`. If the outgoing family is CHAMPION (drill / planned rollback): registry **HALT** row on it |
| R2 | Target byte re-verification fails (sha, symlink, missing, strict-load, §4.2 inequality) | planner via `verify_family_bytes` | No pair. CRITICAL `ROLLBACK_TARGET_CORRUPT`. Outgoing HALTED, cause class **INTEGRITY** (venue frozen; L-48 clearing path = AUT-5 operator CLI) |
| R3 | CAS failure on the pair | store | Retry once, re-evaluate, then CRITICAL. Outgoing stays HALTED. In the drill case, HALT is restrictive: retried until committed plus a demand file (Y19, Z11) |
| R4 | §4.4 fails at pre-launch | pre-launch pass | `SWAP_CANCEL` voids the pair (always permitted). The incumbent is the HALTED F: it boots entries-vetoed (Z7). CRITICAL `ROLLBACK_CANCELLED`. Retried on the next pre-launch pass while the trigger stands. After 3 consecutive cancelled attempts, R2 handling (INTEGRITY) |
| R5 | Resolver refuses at LAUNCH after ACTIVATE (byte drift 16:45→16:50, chain or HWM fault) | supervisor resolver | Existing C5 path: no permit-bearing composition, `REGISTRY_UNAVAILABLE`, supervisor triggers the intraday pass. Its `SWAP_CANCEL` (post-launch, Z8) plus a HALT row on a CHAMPION outgoing family are written **in one transaction**. The supervisor relaunches the HALTED incumbent entries-vetoed |
| R6 | Post-effect mismatch: the node's resolved-family boot line names a different `artefact_sha256` than the ROLLBACK row | rollback verifier in the daily pass (reads node log file, memory note `trade-node-dies-with-the-session`) | HALT row on the target (restrictive). CRITICAL `ROLLBACK_POST_VERIFY_FAILED` |

**Every failure ends with no family sending new entries on a rolled-back path.** It never falls back to an unverified family. The journal row records `{trigger, target, decision, failure_code, chain_head}`.

**HALT row cause for R1/R2/R5/R6.** C5 admits HALT only for an accepted verdict or a mirrored exec-store halt. An engine-detected rollback failure has neither. AUT-7 needs ARCH to admit `HALT` with `decided_by=engine`, `cause_verdict_ids=[]` and a closed-enum `cause_code ∈ {rollback_unavailable, rollback_target_corrupt, rollback_post_verify_failed, drill_step_failed}`, class INTEGRITY for corruption and RECOVERABLE_INFRA otherwise. This is a restrictive widening, always permitted and never capped. See contradiction C-3.

### 3.6 Drills (criterion 4)

**AUT-7a — gate drill.**
- `tests/integration/autonomy/test_rollback_drill_gate.py` runs the full AUT-7b sequence and the R1–R6 failure matrix in-process, in **every** gate run (`scripts/ci/run_tests_no_egress.sh`, after every merge, L-43).
- It uses a fake clock, a tmp `HOME` registry, a tmp exec store written through the real writer path (L-42), the real AUT-5 store, resolver, fold and engine modes, the real `DrillInjectDetector` and intraday producer, and the real `RegistryWatchActor.tick_once` on the loop thread. Supervisor LAUNCH is a port that calls the real resolver.
- It also runs the production default port once (L-55).

**Production readiness check.** Every daily pass, `rollback.readiness()` runs target selection and `verify_family_bytes` for the current champion's would-be target without writing a row. It journals `evidence/rollback/readiness_<venue>_<date>.json`. A present-but-corrupt target sends CRITICAL `ROLLBACK_TARGET_CORRUPT` through `deliver_with_proof` before a real rollback ever needs it. Absence of a target is INFO (true until the first SUPERSEDE).

**AUT-7b — scheduled live drill.**
- **Schedule.** Driven by the policy drill clause (AUT-5 owns the block; AUT-7 proposes these values, each within ceilings): `drill_cadence_days: 60` (stricter than the ≤ 1 per 30 d ceiling), `drill_first_eligible_date` (set at ruling time ≥ AUT-5b activation + 3 days of soak, §6), `drill_start_pass: "daily"`, `drill_inject_utc: "15:00"` on D+1, `drill_demote_slo_min: 15`, `drill_max_episode_days: 6`, and RETIRE reason `drill_episode_closed`.
- **Start gate.** A drill starts only if all hold: the fold names the lineage root CHAMPION and not HALTED; no pending pair; `drill_budget` unspent in the trailing 30 d; ≥ 1 ATTEST row exists for the champion (Z5); the AUT-6 canary has a `delivered=true` row; and a `RECONCILIATION` PASS is within horizon.
- **Child manifest.** `compose_drill_child` emits the root's exact JSON with only these keys changed:
  - `family_id = pm_us_crh_fq_v1_r<NNNN>`;
  - `trial_id_prefix = forecast_quantile_ladder/trial/pm_us_crh_fq_v1_r<NNNN>/`;
  - `d0_climate_day` = D's climate day;
  - `live_orders_ruling` = the policy ruling id.
  
  `density_artefact_path` and `density_artefact_sha256` stay byte-equal, and every size, price, station and θ key is unchanged (§4.2). It is written 0444 to `registry/families/<child>.json` via the AUT-5 child-write API. The kind-scoped persistent latch (G28, `fq/persistent_latch.py:68`) and `rung_net_position_held` (C5 Y16) stop the child from re-taking any rung fq_v1 holds.

**Drill sequence for D = the first eligible day.** Every step is engine-written, `decided_by=engine`, and charged only to the drill budget (Z3).

| When | Mode | Row(s) / action | Proof artefact |
|---|---|---|---|
| D 15:30 | daily | `MINT` r0001 ∅→SHADOW, no C3 record (Y2); `DRILL_ADMIT` SHADOW→CHALLENGER; `DRILL_PROMOTE` r0001→CHAMPION + `SUPERSEDE` fq_v1→CHALLENGER (`rollback_eligible=true`), `effective_launch_date=D` | chain rows; journal; `DRILL_STARTED` via `deliver_with_proof` |
| D 16:45 | pre-launch | §4.4 → `ACTIVATE` (or `SWAP_CANCEL`: the pair lapses, is **not charged**, and the drill retries on the next eligible day) | chain |
| D 16:50 | supervisor | resolves r0001; node boots it; **drill episode opens** (C1 `drill=true`) | node log resolved-family line `family_id=pm_us_crh_fq_v1_r0001 artefact_sha256=9c0b6d6e…` |
| D+1 15:00 | intraday | writes `registry/drill/marker.json` (0444, schema `drill-marker/v1`: `episode_id`, `child_id`, `ts_ns`, `clause_sha256`) | marker sha in journal |
| ≤ D+1 15:05 | intraday producer (AUT-6) | `DRILL_INJECT` → C4 `HEALTH` FAIL, `declared_action_class=DEMOTE` (mapped only while the clause is active) | verdict file |
| ≤ D+1 15:08 | intraday engine | `DEMOTE` r0001 CHAMPION→HALTED; unlink the marker | chain; `DRILL_DEMOTED` |
| ≤ D+1 15:09 | node watch actor | `entry_veto = registry_halted` on the next 60 s tick; exits live | C1 `EntryVeto` record; node log veto line |
| D+1 15:10 | producer | marker absent → `DRILL_INJECT` PASS (Z2) | verdict file |
| D+1 16:50 | supervisor | HALTED r0001 boots entries-vetoed (Z7) | node log |
| D+2 15:30 | daily | `RESUME` HALTED→CHAMPION (cooldown ≥ 24 h satisfied, cause PASS, no pending pair, §4.4) | chain; `DRILL_RESUMED`; veto clears on the next tick |
| D+3 15:30 | daily | `ROLLBACK` fq_v1 CHALLENGER→CHAMPION (re-verified sha `9c0b6d6e…`) + `SUPERSEDE` r0001→CHALLENGER (never eligible), `effective_launch_date=D+3` | chain; `DRILL_ROLLBACK_PROPOSED` |
| D+3 16:45 / 16:50 | pre-launch / supervisor | `ACTIVATE`; node boots fq_v1; **drill episode closes** | node log line `family_id=pm_us_crh_fq_v1 artefact_sha256=9c0b6d6e…` |
| D+4 15:30 | daily | `RETIRE` r0001 (`drill_episode_closed`); ATTEST fq_v1; R6 post-verify | chain; export `registry_polymarket_us_<D+4>.jsonl` |
| D+4 15:50 | `breezy-autonomy-drill-report.service` | assembles the evidence bundle (§6) | `evidence/drills/drill_polymarket_us_<episode_id>.json` |

**Abort rule.** Any step that fails its SLO is handled by the R-matrix with the drill as the outgoing family (`cause_code=drill_step_failed`). Examples: no DEMOTE within `drill_demote_slo_min` of the marker; RESUME refused; byte mismatch.
- r0001 is HALTED at once.
- The unused drill ROLLBACK runs at the next LAUNCH under R1–R5.
- A failed ROLLBACK leaves r0001 HALTED and the venue with no new-entry sender.

**Drill fills.** `drill_episodes()` gives `[DRILL_PROMOTE effective_ns, closing ROLLBACK effective_ns)` per child. `is_drill_fill` is true for any fill of a drill-admitted family id **or** any fill inside an episode interval. This gives two independent ways to identify a drill fill.
- AUT-1 stamps C1 `drill=true` from the watch actor's fold.
- AUT-2 re-derives it from the chain for C2 (`excluded_reason=drill`, `admissible=false`).
- AUT-4's live sequential and the KILL-clock consumer exclude them.
- They still spend the venue daily budget (Z18, G21).

**Drill budget per 30 d per venue (ceiling).** 1 DRILL_ADMIT, 1 DRILL_PROMOTE, 1 drill RESUME, 1 drill ROLLBACK, counted at effect. A lapsed or cancelled pair is not charged. The drill MINT adds no lineage counter (Y2).
- **Money.** No extra money: the child is byte-identical to fq_v1 and replaces it inside the same caps.
- **Statistical cost.** About three sessions of drill-tagged fills (D, most of D+1, D+2 after 15:30 and D+3) leave live n. At ~5 fills/day that is ≈ 15 fills per drill, plus ≈ 1 session of vetoed entries (≈ 5 fills of opportunity).

### 3.7 Units

| Unit | Type | Lock | Limits |
|---|---|---|---|
| (none new for rollback) | runs inside `breezy-autonomy-engine*` (AUT-5) | `engine.lock` | inside the engine's cap (own-lock units ≤ 4G total, §5.2) |
| `breezy-autonomy-drill-report.service` + `.timer` (daily 15:50; exits 0 with `NO_INPUT` when no episode closed) | oneshot, read-only on registry, writes `evidence/drills/` | own lock `drill-report.lock` | `MemoryMax=512M`, `RuntimeMaxSec=600`, `OnFailure=breezy-study-failed@`, `EnvironmentFile=-%h/.config/breezy/alerts.env` (G27), `ProtectSystem=strict`, `ReadWritePaths=` evidence dir only |

## 4. Work packages

Gate commands for every WP:
- `scripts/ci/run_tests_no_egress.sh <focused paths>`, then the full `scripts/ci/run_tests_no_egress.sh`, reading EXIT before any push;
- `cd <tree root> && lint-imports`, which must print "N kept, 0 broken" (the console script, never `python -m importlinter`);
- mypy ratchet `tests/unit/test_mypy_ratchet.py`, which runs in the gate.

Worktrees export `PYTHONPATH=<worktree>/src` and use the exact interpreter. Never use `uv` or `pip`. Never `git stash`. Each WP is RED-first: the commit message carries the RED output and the GREEN output.

### AUT-7.WP1 — champion history (Wave 1, against ARCH-0 stubs)
- **Scope:** `rollback.champion_history`, `ChampionEpoch`, derived flags, the human render.
- **Files:** `src/breezy/persistence/autonomy/rollback.py`; `tests/unit/autonomy/test_rollback_champion_history.py`.
- **RED first:**
  - `tests/unit/autonomy/test_rollback_champion_history.py::test_history_is_a_pure_fold_of_the_verified_chain`
  - `::test_history_never_reads_projection_or_families_cache` (corrupt both caches; history unchanged)
  - `::test_history_refuses_unverified_or_export_divergent_chain`
  - `::test_pending_lapsed_and_voided_pairs_create_no_epoch`
  - `::test_drill_promote_supersede_makes_incumbent_rollback_eligible`
  - `::test_drill_admit_subject_is_never_rollback_eligible`
  - `::test_demote_clears_and_displaced_never_sets_rollback_eligible`
  - `::test_every_champion_epoch_appears_in_history` (family-agnostic, parametrized over every `_COMPOSITION_KINDS` member with a synthetic chain)
  - `::test_history_render_equals_fold`
- **GREEN:** all pass. `test_rollback_module_has_no_family_literals` (AST: no `pm_us_*` string literal in `rollback.py`/`drill.py` except in `drill.py`'s regex-built child id).
- **Activation:** pure library, live when the engine imports it (WP3). Engine pin updated in the same commit.

### AUT-7.WP2 — trigger, target selection, byte re-verification (Wave 1)
- **Scope:** `rollback_trigger`, `select_rollback_target`, `plan_rollback`, `classify_failure`, `rollback_journal.py`.
- **RED first** (`tests/unit/autonomy/test_rollback_planner.py`):
  - `::test_trigger_fires_on_recoverable_model_demote_of_champion`
  - `::test_trigger_silent_for_infra_terminal_integrity_and_drill_family`
  - `::test_trigger_refused_while_pair_pending`
  - `::test_target_is_most_recent_eligible`
  - `::test_target_excludes_demoted_for_cause_terminal_frozen_and_unrouted_kind`
  - `::test_no_fallback_to_older_target_on_verify_failure`
  - `::test_rollback_budget_counted_at_effect_with_reservations`
  - `::test_rollback_budget_exhausted_yields_unavailable`
  - ARCH-named `tests/unit/autonomy/test_rollback_restores_byte_identical_artefact.py::test_rollback_restores_byte_identical_artefact`
  - `::test_target_symlink_or_missing_or_sha_mismatch_is_corrupt`
  - `tests/unit/autonomy/test_rollback_journal.py::test_journal_exact_set_atomic_0444_no_paths` (with the §3 payload hygiene scan)
- **GREEN:** all pass. `verify_family_bytes` is imported from the AUT-5 resolver, never reimplemented (`test_rollback_uses_resolver_byte_binding`, AST).
- **Activation:** with WP3.

### AUT-7.WP3 — engine integration, fail-closed matrix, readiness (Wave 1 code against the AUT-5a engine stub; live after AUT-5a)
- **Scope:** the `rollback.step(mode)` calls in the daily, pre-launch and intraday modes; pre-launch pair + `ACTIVATE` in one pass; R1–R6 handling; `deliver_with_proof` for `ROLLBACK_*`; daily readiness journal.
- **RED first** (`tests/integration/autonomy/test_rollback_engine.py`, fake clock):
  - `::test_demote_before_1645_rolls_back_at_same_day_launch`
  - `::test_demote_in_session_rolls_back_at_next_launch`
  - `::test_rollback_requires_no_code_change` (repo tree mounted read-only in the test; the rollback path writes only the tmp registry and evidence dirs, and the supervisor port resolves the new id)
  - `::test_failed_rollback_halts_family` (parametrized R1–R6)
  - `::test_post_launch_resolver_refusal_cancels_and_halts_in_one_transaction`
  - `::test_prelaunch_cancel_three_times_escalates_to_integrity`
  - `::test_readiness_alerts_on_corrupt_target_without_writing_a_row`
  - `::test_rollback_alerts_journal_delivery` (fake webhook non-2xx → `delivered=false` journaled + retried, G25)
  - `::test_daily_pass_never_calls_probe_open_intent_while_node_live`
- **GREEN:** all pass. The existing envelope tests stay unweakened (§4.7 list). `test_damping_ceilings` is still green.
- **Activation:** on merge, after AUT-5a's engine units are live. The engine restart follows memory note `activate-code-immediately`, in the 01:00–16:40 window, never touching the node.

### AUT-7.WP4 — drill library and DRILL_INJECT (Wave 1)
- **Scope:** `drill.py`, `drill_inject.py`, marker schema, episode intervals, child composer.
- **RED first** (`tests/unit/autonomy/test_drill.py`), ARCH-named first:
  - `::test_drill_promote_refuses_non_champion_sha`
  - `::test_drill_inject_mapped_only_in_clause`
  - `::test_drill_budget_separate`
  - `::test_drill_flag_spans_promote_to_rollback`
  - `::test_drill_admit_charges_only_drill_budget`
  - `::test_drill_inject_passes_when_marker_absent`

  then:
  - `::test_drill_child_equals_root_modulo_allowlist` (byte diff of the JSON limited to the 4 keys; artefact path and sha byte-equal)
  - `::test_drill_child_writes_no_c3_lineage_and_no_counter`
  - `::test_drill_resume_and_rollback_charge_only_drill_budget` (see C-2)
  - `::test_drill_start_gate_requires_attest_canary_reconciliation`
  - `::test_drill_marker_symlink_oversize_unparseable_is_error_not_pass`
  - `::test_is_drill_fill_by_family_id_or_interval`
  - `::test_drill_state_is_derived_from_chain_after_restart` (crash between steps, re-derive, idempotent next step)
- **GREEN:** all pass. The producer pin covers `drill_inject.py` (`test_code_identity_pins_cover_import_closure`).
- **Activation:** with WP6.

### AUT-7.WP5 — AUT-7a gate drill (Wave 1, completes after AUT-5a/AUT-6 interfaces land)
- **Files:** `tests/integration/autonomy/test_rollback_drill_gate.py`.
- **RED first:**
  - `::test_gate_drill_full_episode`: the exact §3.6 row sequence and kinds; byte identity of the restored sha; `drill=true` on every C1 record from D 16:50 to D+3 16:50; C2 `excluded_reason=drill`; latency marker→veto ≤ 15 min; venue budget charged.
  - `::test_gate_drill_failure_matrix` (R1–R6 injected at each step → child HALTED, alert journaled, no sender on an unverified path).
  - `::test_drill_fills_excluded_from_n_and_kill_clock` (ARCH-named; through the AUT-2/AUT-4 interfaces).
  - `::test_gate_drill_runs_production_default_port_once` (L-55).
- **GREEN:** passes in the full gate. It is listed in the T1 lane (`scripts/ci/tier_lanes.py`) so it runs on every merge.
- **Activation:** the gate is the schedule. It is live on merge.

### AUT-7.WP6 — live drill wiring and evidence report (Wave 3, after AUT-5b policy ruling + allowlist widening)
- **Scope:** `drill.step(mode)` in the engine modes; `breezy-autonomy-drill-report.service/.timer`; `deploy/systemd/README.md` rollback and drill section; proposed drill-clause values handed to AUT-5's ruling.
- **RED first:**
  - `tests/unit/autonomy/test_drill_report.py::test_report_requires_chain_export_nodelog_journal_items`
  - `::test_report_refuses_on_missing_or_mismatched_node_log_line`
  - `::test_report_exits_zero_no_input_when_no_episode`
  - `tests/unit/test_systemd_units.py::test_drill_report_unit_limits_and_alerts_env` (MemoryMax, RuntimeMaxSec, OnFailure, `EnvironmentFile=-…alerts.env`)
  - `::test_drill_report_not_in_self_heal_allowlist`
- **GREEN:** all pass, plus a gate-drill rerun.
- **Activation:** install the timer on merge (the coordinator runs the reviewed install step). The drill then starts on its own at `drill_first_eligible_date`.

### AUT-7.WP7 — AUT-7b execution (live, no code)
- **Scope:** the engine runs §3.6 unattended. The coordinator only observes: Monitor on the chain export and the report file (memory note `every-background-job-needs-a-watch`).
- **GREEN:** the §6 bundle is complete and an independent scorer signs it.

## 5. Association

| Contract | Consumed from | Interface AUT-7 needs (blind assumption; if absent, AUT-7 raises it in AUT-5/AUT-6 review, never forks it) |
|---|---|---|
| C5 | ARCH-0/AUT-5 | `VerifiedVenueChain` (verified rows + head); `resolve_champion(venue, now)`; store `write_transitions(rows, expected_prior_seq)` (atomic multi-row, CAS, idempotent); `write_child_manifest(child_id, bytes)` (0444, `registry/families/`); `resolver.verify_family_bytes(row)`; lineage and drill counters; the HALT `cause_code` widening (C-3) |
| C5 engine | AUT-5 | mode hooks `daily`, `prelaunch`, `intraday` calling `rollback.step` and `drill.step`; pre-launch may write a pair before its ACTIVATE step (C-4); the engine writes the drill marker (intraday, clause-gated) |
| C5 policy | AUT-5 ruling | `drill_clause` (§3.6 values), `drill_clause_sha256`, RETIRE reason `drill_episode_closed`, `DRILL_INJECT → DEMOTE` mapping, `RECOVERABLE_MODEL` class map for drift and sequential detectors |
| C4 | AUT-6 intraday producer; AUT-2 | the producer evaluates `DrillInjectDetector` for the champion family; `RECONCILIATION` PASS verdict with horizon |
| C1 | AUT-1 | `CaptureAdapter` sets `drill` from `drill.is_drill_fill` / the watch actor fold; `EntryVeto` records for `registry_halted` |
| C2 | AUT-2 | `excluded_reason=drill` from `drill_episodes(chain)` |
| C4 live / KILL | AUT-4 | live sequential and the KILL-clock consumer read only `admissible` labels; KILL clock keyed on the lineage root, not the current champion id (risk K-3) |
| §4.6 | AUT-6 | `deliver_with_proof(sink, payload) -> DeliveryProof` and the delivery journal |

**Provided:**
- `champion_history`, `select_rollback_target` and `rollback.readiness` → AUT-5 (engine) and AUT-6 (a `HEALTH` detector may read readiness);
- `drill_episodes` and `is_drill_fill` → AUT-1, AUT-2, AUT-4;
- `DrillInjectDetector` → AUT-6;
- the executed AUT-7b drill → AUT-5's and AUT-6's live proofs.

**Order:**
- WP1, WP2 and WP4 run in parallel in Wave 1 against ARCH-0 stubs.
- WP3 and WP5 complete when AUT-5a (engine modes, resolver) and AUT-6 (`deliver_with_proof`, producer) land.
- WP6 follows AUT-5b (ruling filed, `_LINEAGE_POLICY_ALLOWLIST` committed, DRILL rows enabled), AUT-1 (drill flag) and AUT-2b (drill exclusion).
- WP7 follows the §6 soak preconditions.

## 6. Live-proof protocol

**Preconditions (soak, all observed, none hand-made):**
- AUT-5a watch actor live ≥ 3 sessions with no `registry_unreadable`;
- ≥ 1 ATTEST row for fq_v1;
- AUT-6 canary `delivered=true` row (`alerts_undeliverable` armed, §5.1);
- a `RECONCILIATION` PASS within horizon;
- the WP3 readiness journal running daily.

**Artefacts (AUT-7b evidence bundle):** `~/.local/share/breezy/evidence/drills/drill_polymarket_us_<episode_id>.json` (0444), cross-referencing:
1. The chain export rows `registry_polymarket_us_<D..D+4>.jsonl`: MINT, DRILL_ADMIT, DRILL_PROMOTE+SUPERSEDE, ACTIVATE, DEMOTE, RESUME, ROLLBACK+SUPERSEDE, ACTIVATE, RETIRE, all `decided_by=engine`, contiguous `venue_seq`, chain head verified.
2. The node log files: the resolved-family boot line for r0001 at D, the HALTED boot at D+1, and fq_v1 at D+3, each with `artefact_sha256=9c0b6d6e66a587c1b4e14e5f95ff5cedb3c7195f62f8ad4238191fdd75923a5e`; the `registry_halted` veto set and cleared lines.
3. Verdict files: DRILL_INJECT FAIL then PASS.
4. Delivery journal `evidence/alerts/delivery_<date>.jsonl`: `delivered=true` for DRILL_STARTED, DRILL_DEMOTED, DRILL_RESUMED, DRILL_ROLLBACK_PROPOSED and the R6 post-verify OK.
5. `git log --since=D --until=D+5 --format=%H -- deploy src` empty or unrelated, so no commit is in the loop.
6. Drill fills: C1 `drill=true` and C2 `excluded_reason=drill`; the live n and the KILL-clock counter unchanged by them.

A summary is copied to `docs/evidence/AUT-7b_drill_<D>.md` by the coordinator after the fact. Documentation is outside the loop.

**Clock and ETA (honest, build pace not guaranteed):**

| Milestone | Earliest | P50 | P90 |
|---|---|---|---|
| ARCH-0 merged (Wave 0, size M, review) | 2026-10-09 | 10-12 | 10-17 |
| WP1/2/4 merged; WP3/5 merged after AUT-5a/AUT-6 | 10-16 | 10-21 | 10-28 |
| AUT-5b ruling filed + allowlist widening; AUT-2b; WP6 | 10-27 | 11-04 | 11-14 |
| Soak preconditions met → `drill_first_eligible_date` D | 11-02 | 11-09 | 11-19 |
| AUT-7b closes (D+4 report) = **live proof** | **2026-11-06** | **2026-11-13** | **2026-12-23** |

The P90 includes one drill that took effect then failed: it consumes the 30-day drill budget, so the retry is ≥ D+30. A pre-effect SWAP_CANCEL is not charged and only slips a day.
- All dates are before the 2027-01-25 KILL. If the KILL fires TERMINAL first, the lineage is `terminal_frozen`, DRILL_PROMOTE is refused, and AUT-7b cannot complete until a reviewed new lineage root exists (ARCH §5.3).
- The drill needs **no natural fill**: its proof is chain, log and journal evidence, so the ~5 fills/day rate does not gate it.

**Evidence class:** "machinery proven, edge unproven". The drill child is byte-identical, so it says nothing about edge.

## 7. Score-3 verification checklist (independent scorer)

| Criterion | Check |
|---|---|
| History immutable | `sqlite3 'file:…/registry.sqlite?mode=ro' "UPDATE transitions SET kind=kind"` → ABORT (trigger); `test_history_never_reads_projection_or_families_cache` green; `champion_history_<venue>_<date>.json` equals the fold (`test_history_render_equals_fold`) |
| (a) unattended | bundle item 1 (`decided_by=engine` on every row); item 5 (no commit) |
| (b) family-agnostic | `test_every_champion_epoch_appears_in_history`, `test_rollback_module_has_no_family_literals`; a family can send only as CHAMPION (C5 resolver), so every sender is in the history by construction |
| Trigger within one cycle, no code change | `test_demote_before_1645_rolls_back_at_same_day_launch`, `test_demote_in_session_rolls_back_at_next_launch`, `test_rollback_requires_no_code_change`; live: D+3 15:30 ROLLBACK row → D+3 16:50 node boot line |
| (c) fails closed | `test_failed_rollback_halts_family[R1..R6]`, `test_gate_drill_failure_matrix`, `test_post_launch_resolver_refusal_cancels_and_halts_in_one_transaction` |
| (d) detected + delivered | `test_rollback_alerts_journal_delivery`; live journal rows (bundle item 4); readiness journal daily |
| (e) RED→GREEN | WP commit messages carry RED then GREEN output; full gate EXIT=0 logs per merge |
| Drills scheduled | gate: `test_rollback_drill_gate.py` in the T1 lane (`tier_lanes.py`); live: `drill_cadence_days` in the sha-pinned policy block + `systemctl --user list-timers breezy-autonomy-drill-report.timer` + the engine journal of drill-start decisions |
| (f) live proof | `evidence/drills/drill_polymarket_us_<episode_id>.json` complete; restored sha equals `9c0b6d6e…923a5e`; ≥ 4 trading days D…D+3 |
| Drill exclusion | `test_drill_fills_excluded_from_n_and_kill_clock`; live: C2 rows `excluded_reason=drill` and the AUT-4 live-sequential `n` unchanged across the episode |

## 8. Risks and failure modes

| ID | Risk | Mitigation |
|---|---|---|
| K-1 | Fee drift during the drill: the exec-store `policy_halt` on r0001 is TERMINAL and freezes the **whole fq_v1 lineage**, so the drill's ROLLBACK is refused and the venue has no sender | Accepted fail-closed cost (ARCH §7 Z20 analogue). The start gate requires the fee probe `is_fee_verified` true at D 15:30. Recovery is a reviewed new lineage root. |
| K-2 | Drill costs ≈ 15 admissible fills plus ≈ 1 vetoed session per drill | Proposed cadence 60 d (stricter than the 30 d ceiling): at most 2 drills before the KILL. Budget accounted in the ETA. |
| K-3 | The champion-scoped KILL clock (`promotion_criteria.py:135` `champion_kill_clock_path`) would follow r0001 while it is champion | AUT-2/AUT-4 must key it on `lineage_root_family_id` and exclude drill intervals; `test_drill_fills_excluded_from_n_and_kill_clock` pins it. |
| K-4 | An AMBIGUOUS intent open at 16:45 cancels the drill or a real rollback (Z19) | A lapse is not charged; retried the next day. R4 escalates after 3 attempts. AUT-2 measures the rate. |
| K-5 | Byte drift of a committed root (a reviewed commit edits `deploy/families/pm_us_crh_fq_v1.json` or its artefact) poisons the rollback target | The daily readiness journal alerts CRITICAL the same day. R2 halts rather than rolling back to unverified bytes. |
| K-6 | F-1 containment base is phantom | AUT-5 fixes it in its widening. AUT-7 relies only on CWD-relative reads by the resolver, pinned by `test_drill_child_equals_root_modulo_allowlist` reading through the resolver. |
| K-7 | Memory on the 31 GB host | Rollback runs inside the engine (≤ 4G own-lock budget). The drill report is capped at 512M, `RuntimeMaxSec=600`. Nothing heavy runs in 01:00–04:30. |
| K-8 | Shared venv and concurrent agents | Exact interpreter, no `uv`/`pip`, no `git stash`, per-agent scratchpads, `PYTHONPATH` in worktrees, disjoint files (AUT-7 never edits `app/trade.py`, `settings.py`, `trade_supervisor*.py`). Full gate after every merge. |
| K-9 | Engine crash mid-drill | Drill state is re-derived from the chain (`test_drill_state_is_derived_from_chain_after_restart`). Idempotent `transition_id`s. The dead-man and heartbeat veto bound exposure (§4.6). |
| K-10 | Statistical capacity | The rollback and the drill make no edge claim. Promotion evidence stays AUT-4's. |
| K-11 | KILL 2027-01-25 | All ETAs precede it. Post-KILL behaviour per ARCH §5.3 (above). |

## 9. Binding-constraint compliance

- **Nautilus:** untouched. Only an existing native `Actor` pattern is consumed (AUT-5); no Nautilus file or behaviour changes.
- **Caps:** never read, assigned or derived. Drill fills spend the venue budget inside them (Z18). `test_autonomy_never_reads_or_writes_operator_controls` covers both new modules.
- **allow_short:** stays `False`. The child manifest is equal to the root on every size and side key.
- **NO-SEND:** unchanged. The gate drill runs under `run_tests_no_egress.sh`, and the only new egress is `deliver_with_proof` on the existing `alerts.env` key (`test_autonomy_alert_egress_not_widened`).
- **Master enablement and permit:** untouched. A rollback or drill changes only which allowlisted family the resolver names. The permit authority and minting are unchanged (§4.1).
- **PREREG via ruling:** drill clause, cadence and RETIRE reason live only in the AUT-5 sha-pinned policy ruling. The rollback trigger is a code literal reviewed in this plan, and it never invents statistical semantics.
- **Safety tests:** none weakened. The §4.7 existing list stays green and new tests only add pins.

## 10. Self-score

| Axis | Score | Note |
|---|---|---|
| Fidelity | 18/20 | Every README and §10 item is covered. It depends on 3 ARCH clarifications (C-2, C-3, C-4). |
| Correctness | 17/20 | Line evidence verified at `4b8347a6`. The AUT-5 interfaces are blind assumptions. |
| Specificity | 14/15 | Exact modules, rows, times, tests and units. |
| Acceptance | 18/20 | The checklist is scorer-runnable. The live proof depends on AUT-5b timing. |
| Autonomy-safety | 14/15 | Fail-closed matrix R1–R6. K-1 is an accepted availability cost. |
| Reuse | 9/10 | No new store; resolver byte binding reused. |
| **Total** | **90/100** | |

### Contradictions and clarifications raised against ARCH Rev 4

- **C-1.** C5 resolver refusals include "a `live_orders_ruling` that is not the policy ruling". The committed root `pm_us_crh_fq_v1.json` names `RULING_operator_fq_live_real_orders_2026-10-01` (authorised by the G4 triple, `live_orders_gate.py:76-84`). Read literally, this refuses fq_v1 at BOOTSTRAP and as the drill's ROLLBACK target. Fix: apply the rule to children only; roots resolve through `_LIVE_ORDERS_ALLOWLIST`.
- **C-2.** Z10 lists `DRILL_INJECT` under `RECOVERABLE_MODEL`, which consumes `MAX_RECOVERABLE_RESUMES_PER_LINEAGE_14D`. §4.5 says drill rows count only against the drill budget. This plan follows §4.5. ARCH should give drill causes an explicit exemption or their own class.
- **C-3.** C5 admits CHAMPION→HALTED only for an accepted verdict or a mirrored exec-store halt. The README's "failed rollback halts the family" needs an engine-caused HALT (`cause_code` closed enum, §3.5).
- **C-4.** "Within one supervisor cycle" needs the pre-launch pass to write a ROLLBACK pair and its ACTIVATE in the same pass. ARCH describes pre-launch as ACTIVATE/SWAP_CANCEL only. The engine mode that writes the drill marker is also unstated.
- **C-5.** C3 no-new-lineage says the drill MINT "cites the existing content-addressed directory". No such directory exists for fq_v1's artefact, so the child cites the committed path byte-equal (F-1 explains the read semantics).
- **C-6.** §4.4 cites the G30 probe as the intent check. `probe_open_intent` refuses while a node is live (`trade_supervisor_core.py:554-560`), so the 15:30 daily pass can only check advisorily. The binding check is at 16:45.
