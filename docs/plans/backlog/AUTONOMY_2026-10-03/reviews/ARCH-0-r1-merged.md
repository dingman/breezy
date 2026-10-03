# ARCH-0 round 1, merged coordinator rulings (2026-10-03)

Inputs: `ARCH-0-seamA_plan_r1.md`, `ARCH-0-seamB_plan_r1.md`; reviews `ARCH-0-seamA-r1-{python,security,architect}.md`, `ARCH-0-seamB-r1-{security,architect}.md`.
Every r1 verdict is REQUEST_CHANGES (MEDIUM). There are no REJECTs.

## Seam B: rulings for r2

- **B-R1 (ER-B1): AMEND, as the architect proposes.**
  - The two reviews agree on the CRITICAL: phase 2 aborts at the N2 barrier (`tests/conftest.py:292-380`).
  - The amended gate:
    - `scripts/ci/run_tests_no_egress.sh` remains THE gate. It runs phase 1, then an un-nested phase 2, and reads both exit codes.
    - The `bwrap_host` marker and its phase-1 skip / phase-2 fail-not-skip are registered from the root conftest, or a `tests/support` plugin it loads. This is an L-54 pin-searched edit.
    - Phase 2 collects `-m bwrap_host tests/`.
  - The phase-2 pytest parent must be **prevented**, not just detected, from loading order-path code:
    - a meta-path import blocker, installed before collection, that refuses `breezy.adapters*`, `nautilus_trader*` and every `find_execution_egress_modules()` hit;
    - an exact-set N2 widening (L-12) that accepts `BREEZY_BWRAP_HOST_PHASE=1` only with the blocker installed, collection restricted to `bwrap_host` items, and `BREEZY_TEST_OS_EGRESS_BLOCK` absent;
    - a session-end `sys.modules` assertion;
    - `--unshare-net` on every bwrap child.
  - Consumer obligation: Nautilus work runs only in bwrap children.
  - The planner may substitute security's stdlib-only runner instead, provided it still runs the consumers' real-namespace tests.
  - Security sign-off is required in the r2 review.
- **B-R2 (ER-B2): ADOPT with the architect's amendments (a)–(c).** The header digest is recorded as an E-8 amendment.
- **B-R3: drop the shared denylist lint** (AC6 ruling, `reviews/AUT-6-r9-merged.md:11-15`). Export `SHARED_WRITE_SITES` so consumers can use it in their allowlists.
- **B-R4: self-probe follows AUT-6 r15 O-5** (l.260-261) and the security finding #2:
  - the env-row check runs before any open;
  - negatives use `O_TMPFILE` and require exactly EROFS; no named file is ever created under `state/`, the data root or the repo;
  - positives are `tmpfile`/`subdir` per bind;
  - the reason vocabulary is AUT-6's.
- **B-R5: bind and config integrity.**
  - Validate each bind with a per-component `O_PATH|O_DIRECTORY|O_NOFOLLOW` walk; check `st_dev`/`st_ino` against `state/` and its ancestors; pass the validated fd with `--bind-fd`.
  - Open `config_ro_binds` with nofollow and refuse anything that resolves under `~/.config/breezy` or has a hardlink alias.
  - The AUT-6 directory re-bind of `~/.config/systemd/user` is a named exception, `E7_CONFIG_DIR`, with the same checks.
- **B-R6: credential and escape surface (security #4).**
  - Mount `--tmpfs /run/user/<uid>`; `Type=notify` rows re-bind only the `NOTIFY_SOCKET` path.
  - Hide `~/.ssh`, `~/.aws`, `~/.gnupg` and `~/.netrc`, using a list derived from a live listing (L-14) and pinned.
  - Pass `--disable-userns`.
  - The sandbox protects against bugs, not against a hostile process running as the same uid. State this as a residual.
- **B-R7:** address every other finding from both reviews (security 6–13, architect 5–17), or say why one is rejected. Use AUT-4's test names and paths for the E-13 tests.
- **B-R8: placement stays at `runtime/autonomy_sandbox/`.**
  - Use the architect's seam-A Q5 rationale (the write-site scan, all callers sitting at runtime or above, deploy configuration) instead of the import-time argument, which seam A's lazy `__init__` removes.
  - Add the forbidden contract `runtime.autonomy_sandbox ↛ nautilus_trader, breezy.adapters, breezy.strategy`, plus a fresh-subprocess import test.

## Seam A: rulings for r2

- **A-R1: fix every HIGH.**
  - python-reviewer B1–B5.
  - security H1–H7. Resolver and replay must refuse unenabled widening rows. Add `lineage_policy_authorized` in `live_orders_gate`. Freeze the policy object, with private test seams. HWM is tri-state. All IO walks with `openat` (resolves python B5 as well). `parse_family_manifest` callers keep the prereg-directory check, and a golden-corpus equality test is added. `GuardResult` enum.
  - architect H1–H6. Add `_ADMISSION_IMPLEMENTED`, and write a binding WP1b note for the AUT-5a brief that names the RESUME subset before L1. Add the register_arrow reachability audit for the lazy `__init__`. Nothing in the contract (b) list imports `breezy.domain`. Fix the WP dependency table. Add the module-classification test. Owner-placeholder bodies become stubs, with the `owner_symbol` column and a staleness test.
- **A-R2: fix every MEDIUM, or reject it with a reason.** This covers security M1–M11, architect M1–M6, and the python non-blocking items that the security or architect reviews also raised.
- **A-R3: tests become real in ARCH-0 when ARCH-0 implements their logic** (security Q5 list), plus `test_resolver_refuses_chain_with_unenabled_widening_row`, the policy-ruling sha tests and `test_hwm_absent_with_rows_refuses`. A test stays carried only when its subject code is owned by a later area.
- **A-R4 (E-14): AMEND then ADOPT,** with the architect's five amendments (M5). The plan includes the exact erratum text. WP-B holds `paths.root_record` until the coordinator files it.
- **A-R5: re-size honestly.** Expect 6–7 WPs. Give each its named split seam and a dependency table.
- **A-R6: out of ARCH-0 scope.**
  - The halt and intent decoders (`halt_rows.py` vs `domain/family_halt.py`) belong to AUT-5a. AUT-6 aliases them. Seam B's snapshot helper exposes bytes only.
  - Also out of scope: the `policy` parser (AUT-5 WP3), `demand.archive` (AUT-5 WP4), and AUT-2's Wave-0 egress review (AUT-2a).
  - Each goes into the stub table with its owner.

## Seam B round 2: merged rulings for r3 (reviews `ARCH-0-seamB-r2-{security,architect}.md`)

Security signed off E-7d as YES-WITH-CONDITIONS. The architect voted E-7d AMEND and E-7e AMEND. The plan still REQUEST_CHANGES on both sides.

- **B3-R1: host sockets** (security F1, HIGH).
  - Every row mounts `--tmpfs /run` after `--ro-bind / /`. The ro re-binds are an exact set, measured row by row: `/run/systemd/resolve` (only if a row resolves DNS) and `NOTIFY_SOCKET`.
  - `/var/run` is a symlink to `/run`; the plan must verify this.
  - Self-probe negatives: docker, snapd and lxd sockets → ENOENT, and no `S_ISSOCK` under `/run` outside the allowlist (`host_socket_visible`).
  - Add a phase-2 test.
- **B3-R2: user-bus consumers** (architect F1, HIGH).
  - Prefer an option with no bus inside the sandbox. A bounded, unwrapped `ExecStartPre` runs the literal read-only `systemctl --user show|list-units|list-timers` and `journalctl` argvs. It writes their output to a file in the row's bind, and the sandboxed step reads that file.
  - If that cannot serve a consumer (for example, a mid-run poll), add `E7A_R2_USER_BUS` instead. It is an exact row set and ro-binds only `/run/user/<uid>/systemd/private`. The residual (the bus can start units that escape the sandbox) must be stated, and the consumer's AC6 allowlist must restrict calls to literal read-only argvs.
  - Choose per consumer and list every choice in E-7e(f). The r3 security review rules on it.
- **B3-R3: measure the PROC-row argv** (architect F2).
  - Measure `--unshare-user` + `--proc /proc` without `--unshare-pid` (M14).
  - If the mount fails, omit `--proc` for those rows. The host `/proc` then comes through `--ro-bind / /`. Re-verify security's `/proc/<pid>/environ` EACCES result under that exact shape.
- **B3-R4: phase-2 admission before import** (security C-1).
  - Check `config.args` at sessionstart; `pytest_ignore_collect` refuses non-registry paths.
  - Add a test with an import-time witness.
- **B3-R5: script dispatch** (security F3 = architect F4).
  - Phase 1 becomes an `if/elif/else` chain. Exactly one phase-1 run, tested.
  - `--collect-only` is matched by exact token only. `-k --co` and `--collectonly` are covered.
  - State the unshare-only host behaviour.
- **B3-R6: lint the phase-2 file imports** (security C-2). Deny `socket`, `http*`, `urllib*`, `requests`, `httpx`, `aiohttp`, `websockets`, `ctypes`, `runpy`, `os.exec*`, `os.system`, `os.popen` and `spec_from_file_location`. Apply this to the registry files and to the support modules they import.
- **B3-R7: supervisor `intent_lock_is_free` interplay** (security F4). Add a test, and state in the AC what happens between 16:45 and 16:48.
- **B3-R8: B2a must be green at its own sha** (architect F8). Ship a witness file. B2b only widens the gate. File E-7d before B2a merges.
- **B3-R9: consumer changes in E-7e(f) must be complete** (architect F3, F5, F7, F9). This covers:
  - AUT-6 real-bwrap tests move to `tests/integration`;
  - `--tmpfs ~/.config` assertions are rewritten;
  - recorder-shaped units are linted on wrapper-naming lines only;
  - AUT-5 per-mode `#stage-s` rows with exact instance names;
  - AUT-1 `alerts.env` re-bind removed and its OnFailure switched;
  - AUT-3 refit-repro moves under the data root;
  - AUT-4 tests join the registry.
- **B3-R10: smaller fixes.**
  - Drop the live-listing negatives and keep AUT-6's ownership precondition (architect F6).
  - `XDG_CACHE_HOME=/tmp/.cache`.
  - Basetemp cleanup.
  - The `operator.env` visibility residual: state it without naming or reading values.
  - Mutation-pin `BWRAP_HOST_EXPECTED_TESTS`.
  - The PROC-row `--unshare-user` /proc test.
  - Hygiene: no chatter, literal paths.

## Seam A round 2 — merged rulings for r3 (reviews `ARCH-0-seamA-r2-{security,architect}.md`; both REQUEST_CHANGES, no CRITICAL, both expect to converge)

- **A3-R1 Root anchor (sec F1 HIGH):** BOOTSTRAP/ROOT_ADMIT (and any row resolving to a root) read `deploy/families/<id>.json` under ReadPolicy.REPO; sha == row.manifest_sha256; E-14 rule 3 `committed_path == "deploy/families/<family_id>.json"` exactly.
- **A3-R2 HWM (sec F2 HIGH, F3; arch F2 HIGH):** mid-chain hash check at `hwm.venue_seq`; single `hwm_reading_from_bytes`; exports-dir listing error → `export_unreadable`; state both rollback windows in R14; binding note: node writes HWM at boot after first verified resolve. Stage S: separate `resolve_shadow_family` returning a `ShadowResolution` type that cannot satisfy the sending port (type + AST test). Production clearing path for `HwmAbsent`-with-rows: L1 cut-over writes the initial HWM under the exec flock while the node is down AND `breezy-registry-hwm-reset` is named as the recovery path (L-48 row).
- **A3-R3 ResolvedFamily (arch F1 HIGH):** add `registry_seq`, `chain_head`, single-read manifest + artefact handle (`FamilyBytes`); test pinning ARCH C5 pickup fields.
- **A3-R4 Fix all MEDIUMs:** sec F4 (runtime arrow-registry equivalence per entry — make it a one-time WP-1 evidence artefact + permanent fresh-process smoke, per arch F10c), F5 (ban StagePolicy construction/`replace` outside stage_policy), F6 (corpus 100% branch coverage gate incl. artefact + symlink fixtures; `dir.exists()` semantics stated), F7 (entry-guard key-format contract test vs the pinned client; `open_intent_blocks` global-scope docstring), F8 (child-ness from chain lineage, regex only a consistency check); arch F3 (COALESCE genesis seq), F4 (shared `rows_admissible` predicate for resolver + watch actor), F5 (RegistryUnreadable reasons incl. busy), F6 (complete amendment list b), F7 (fix the AUT-6 citation), F8 (freeze `LegFill` with `ts_event_ns`), F9 (E-14 child scope + write-order amendments).
- **A3-R5 Schedule (arch F10):** WP-1b lineage gate moves to just before WP-8; declare Wave-1 early-start points (AUT-1a/2a/4a/6 after WP-5; AUT-5a/7a after WP-8) with the stub-table signatures frozen; every split-seam commit is gated on its own.
- **A3-R6 LOWs:** all (sec 9–11; arch 11–16), incl. no chatter line, no cycle (StageView in schemas).

## Seam A round 3, merged rulings for r4

Reviews: security APPROVE; architect REQUEST_CHANGES (1 HIGH). Findings are in `ARCH-0-seamA-r3-{security,architect}.md`.

- **A4-R1 (sec F2a = arch F1, HIGH): keep pyarrow-reaching types out of `schemas`.**
  - Move `FamilyBytes`, `ResolvedFamily`, `ShadowResolution` and `ResolverRefusal` into the pyarrow-reaching modules.
  - `schemas` keeps a local closed `LiveOrdersRefusal` enum. The resolver maps `LiveOrdersReason` onto it.
  - Add a planted-control test.
  - Update the stub-table module locations.
- **A4-R2 (sec F2b = arch F2): the store's admission check calls `transitions.rows_admissible`.** It does not keep a second copy of the predicate. Add a `[store]` param to the shared-predicate test.
- **A4-R3 (sec F1): HWM indexing.**
  - `venue_seq ≥ 1`, `export_seq ≥ 0`, and the head field must be 64-hex.
  - Compare against `rows[venue_seq-1]`.
  - Unknown input → `hwm_unreadable`.
  - Add the two tests.
- **A4-R4 (arch F3): HWM pickup.**
  - `ResolvedFamily` gains a pure `hwm: Hwm` field equal to `next_hwm(...)`. Also add `verified_export_seq`.
  - Swap AC 17 steps 3 and 4. "No export" means `newest_export_seq=0`.
  - The tick carries `export_seq` forward and never lowers it.
- **A4-R5 (sec F3): StagePolicy construction ban.**
  - Ban the forms `replace`, `copy`, `__class__`, `type(x)(…)` and `object.__new__` in the autonomy packages, with alias resolution and planted controls.
  - `_append` and `_resolve` assert `stage is STAGE` except under a test seam.
- **A4-R6 (sec F4): introducing-row kinds.** A family introduced by any kind other than BOOTSTRAP, ROOT_ADMIT or MINT invalidates the chain. A BOOTSTRAP or ROOT_ADMIT row with `lineage_root != family_id` is also invalid.
- **A4-R7 (arch F4): freeze the `LineageTallies` fields** from ARCH :431-434, marking each fold-derived or not. `holdout_opens` stays an AUT-5 WP4 cache dependency for AUT-4. Correct amendment (b) item 29.
- **A4-R8 (arch F5): `LegFill` stays netting-only.** AUT-2 owns `CostedFill` for `average_cost_basis`. Amend AUT-2 :116 in (b).
- **A4-R9 (arch F6): E-14 rule 7.**
  - Pin bootstrapped root manifest bytes (`BOOTSTRAPPED_ROOT_MANIFEST_SHA256`, empty until bootstrap) and add a CI test.
  - Name the clearing paths: revert the edit, or bootstrap a new root through ROOT_ADMIT.
  - Add an L-48 row.
- **A4-R10 (arch F7): honest sizing.**
  - Split 3a, 6d, 7b and 8c so every gated seam is about 1,000 lines or fewer.
  - Recount the seams and totals from the table itself, and restate the Wave-0 wall clock.
  - Fix the section header.
- **A4-R11: all LOW findings** (sec 5–9; arch 8–15). The sec 5 reset CLI `--expect-head` item goes into the AUT-5a binding note. Arch F10 pins the cut-over slot relative to the E-8 16:45–16:48 hold.

## Seam B round 3: merged rulings for r4

Both reviews (`ARCH-0-seamB-r3-{security,architect}.md`) returned REQUEST_CHANGES, but the plan is converging:
- Security signs off E-7d YES-WITH-CONDITIONS (C-1 = F2, C-2 = F7).
- The architect ADOPTs E-7d and asks to AMEND E-7e.

Rulings for r4:

- **B4-R1: bus-snapshot directory discipline** (sec F1, HIGH).
  - Open the subdir with `O_DIRECTORY|O_NOFOLLOW` and require `fstat` to show owner = us, the same device, and a dev/ino distinct from `state/`, its ancestors and the data root.
  - Create files through `dir_fd`.
  - The sweep removes only regular files matching `^[0-9a-f]{32}\.json$`, via `unlinkat`.
  - Take the flock on the validated fd.
  - Add tests and a mutation.
  - `bus_snapshot_bind` must be a `cache/…` bind (arch N7).
- **B4-R2: remove `--bus-action`** (sec ruling (d) REJECT).
  - Delete AC-9.4, `BusAction`, `E7A_R2_BUS_ACTION`, `BUS_ACTION_TARGET_UNITS`, and E-7e(h) para 2.
  - The AUT-1 drill and guard stay unwrapped as a stated E-7a rule-5 residual. If AUT-1 later wraps them, it re-files under the security conditions (`--kill-whom=main`, directory discipline, SIGCONT on every path).
  - Arch N3(b) is moot while the drill is unwrapped. Record that.
- **B4-R3: the snapshot step must never block the main step** (arch N1, HIGH).
  - Run `--bus-snapshot` under a monotonic budget below the outer timeout, so a file is always written.
  - AC-5 requires the `-` prefix on the `--bus-snapshot` ExecStartPre.
  - Map missing or stale snapshots: health → UNKNOWN; failed@ and daily → page.
  - Add tests and a mutation.
- **B4-R4: complete the consumer list** (arch N2, N3a, N3c, N6).
  - Re-search `OnFailure=` across AUT-1..7. AUT-2 l.408/423/953, AUT-3 l.267 and AUT-6 l.1046 must be listed.
  - Admit `run-*` with a fixed property set for AUT-6 health.
  - Fix the `-p` grammar.
  - Re-check E-9 per consumer.
- **B4-R5: studies lock** (arch N4 vs sec F5). Choose arch N4.
  - `ExecStartPre=-/usr/bin/timeout -k 1 4 /usr/bin/touch %t/breezy-studies.lock`, allowed only on `E7_STUDIES_LOCK` units. `touch` keeps the inode.
  - The wrapper keeps "never creates a bind source".
  - Add a test.
- **B4-R6: gate conditions.**
  - C-1 (sec F2): load the plugin with `-p` in phase 1 too. The plugin confirms collect-only through a 0600 file under `$GATE_DIR` that the script reads. Add a test using `--noconftest -k --co`.
  - C-2 (sec F7): `env -u PYTEST_PLUGINS -u PYTEST_ADDOPTS`, and no admission if either is set.
- **B4-R7: AUT-2 credential.**
  - Adopt arch N11: a row field `credential_env` emitted by the wrapper as `--setenv`. No separate env file.
  - Keep the sec (e) conditions: the inline-key var must be absent, there are no `env.py` or firewall-test edits, the existing `require_key_file_mode` kwarg is used, and reconcile stays GET-only (consumer test).
- **B4-R8: non-blocking items, all to be applied.**
  - sec F3/arch N8: instance re-validation plus `--` before the units.
  - sec F4.
  - sec F6/arch N5: residual notes, the namespace-pid hazard, and E-7a rule 2 test sentence.
  - sec F8.
  - arch N9: the cite.
  - arch N10: split B2b into B2b-1 and B2b-2, serialise B2c → B3, and keep every seam ≤ ~1,000 lines.
  - Optional: arch §4 `$MONITOR_*` refinement for failed@.

## Seam A round 4 (coordinator rulings, 2026-10-03)

Inputs: reviews/ARCH-0-seamA-r4-security.md (APPROVE, N1–N4 non-blocking), reviews/ARCH-0-seamA-r4-architect.md (APPROVE, N1–N7 non-blocking; scores scope 6, feasibility 7). Both reviewers APPROVE; E-14 incl. rule 7 ADOPTED by architect. r5 is a text-only consolidation — no design change, no new modules, no scope growth.

- **A5-R1 (sec N1, cut-over deadline).** Note 6d: one monotonic deadline computed at start; `flock -w min(5, remaining)`; clock re-check after acquire and before write; a write completing after 16:44:55 is an abort. Key deletion on abort runs only while holding the lock that wrote it; if the lock was never acquired there is no key to delete. Tests: `test_l1_cutover_lock_acquired_at_164454_aborts`, `test_l1_cutover_late_write_completion_aborts`, `test_l1_cutover_abort_leaves_no_key_and_no_registry`.
- **A5-R2 (sec N2, monotone HWM writes).** `hwm.write_monotone(store, new)`: under the intent flock, re-read via `hwm_reading_from_bytes`, skip/refuse unless `new.venue_seq ≥ cur.venue_seq` and `new.export_seq ≥ cur.export_seq` (and equal hash when seqs are equal). Sole writer API for node boot, ticks and cut-over (cut-over writes onto Absent); the reset CLI is the only bypass. Pure decision part lands in seam 7e (`test_hwm_write_never_lowers`); the store-binding is an AUT-5a obligation in binding note 6.
- **A5-R3 (sec N3 + arch N4a/b/c, AC 31).** Hash via `entry_points.REPO_ROOT`, never an absolute path. Base ref named = `origin/feat/data-capture-and-risk` merge-base; ref unavailable or shallow → FAIL, not skip; `pins.py` absent at base (seam 3a) → treated as empty mapping. State that the test is CI hygiene, not a control; runtime anchor is `manifest_sha_mismatch`. State that until ROOT_ADMIT is enabled the only clearing path is revert, and from the stage-S bootstrap onward the live fq manifest is frozen.
- **A5-R4 (sec N4, tick re-read).** Note 5: each tick re-reads from the last verified seq; consecutive refused ticks produce an identical in-memory fold (`test_watch_actor_refused_ticks_idempotent`).
- **A5-R5 (arch N1, test placement).** Move `test_bootstrap_seed_genesis_only`, `test_store_refuses_second_bootstrap_per_venue` (from 6e) and `test_drill_mint_not_counted` (from 7c) to 7d. Re-audit every Test Strategy row: a test sits in the seam that lands the last code it exercises.
- **A5-R6 (arch N2, export listing filter).** `newest_export` filters `\Aregistry_<venue>_\d{4}-\d{2}-\d{2}(_hwm\d+)?\.jsonl\Z` (venue-scoped); `hwm_reset_*.json` and other-venue export names are known and ignored; any other name → `export_unreadable` (fail-closed) — confirm against AUT-5 r7 `:189`/`:487` naming and cite.
- **A5-R7 (arch N3, step ownership).** AC 17 step 1 belongs to the public sending entry only. AC 18 states the shadow step set explicitly (0, 2, 3, 5–8 run; 4 skipped; 9–12 not run — `ShadowResolution` carries no bytes).
- **A5-R8 (arch N5).** Record under binding note 1b that `nominations` = max `k_life` over feasible rows vs ARCH "max `k_life`" is a WP1b question; an erratum is owed if they differ.
- **A5-R9 (arch N6, ban collateral).** Add §ERRATA (b) items for AUT-3 r6 (`:137` `dataclasses.replace(row, split=...)`), AUT-4 and AUT-6: the AC 15(ii) ban applies; an exemption is a reviewed literal row `(module, lineno-free call description, reason)` in the test's exemption set, added in the consumer's own commit. The blanket ban is KEPT as written in AC 15(ii) (security r3 F3: AST cannot see argument types, so narrowing would reopen the hole); consumers that need `dataclasses.replace`/`copy.*` on their own records use the exemption row. The exemption set stays empty at ARCH-0.
- **A5-R10 (arch N7).** Every bootstrap (production and shadow) creates `evidence/registry/`; binding note 6d/9 updated; `test_shadow_bootstrap_creates_export_dir`.
- **A5-R11 (scope 6 / feasibility 7).** Accepted as structural: scope is fixed by frozen ARCH §5.1 Wave 0 and the binding rulings; feasibility 7 was driven by arch N1 which A5-R5 fixes. No further review round for design; r5 gets a single text-verification pass (fixes landed, no new contradictions) rather than full review.

## Seam B round 4 (coordinator rulings, 2026-10-03)

Inputs: reviews/ARCH-0-seamB-r4-security.md (APPROVE; E-7d ADOPT; E-7e ADOPT-WITH-AMENDMENT; N1–N3 low), reviews/ARCH-0-seamB-r4-architect.md (APPROVE, all scores ≥8; E-7d ADOPT; E-7e ADOPT-WITH-AMENDMENT B-1/B-2; non-blocking 1–5). Seam B CONVERGED. r5 is a text-only consolidation; no further review round (a single verification that the amendments landed).

- **B5-R1 (arch B-1, AUT-3 reproduce-am).** E-7e(f) AUT-3 parenthetical replaced verbatim with the architect's text: reproduce-am `TimeoutStartSec` 4139 → 4134; 09:35:00 + 1 + 5 + 4134 + 60 = 10:45:00Z; AM eligibility `runtime_s × 1.2 + 600 ≤ 4134` (`runtime_s ≤ 2945`); AUT-4's K8 test sums pre lines.
- **B5-R2 (arch B-2, AUT-6 health).** E-7e(f) health clause replaced verbatim with the architect's text including the `install -d` bound, "≤ start + 145 s", and the explicit amendment of ARCH §5.2 l.1089 `aut6.health` to "≤ 145 s | start + 145 s"; passes end ≤ slot + 146 s, before the next slot; `HEALTH_PASS_BUDGET_S=90` unchanged.
- **B5-R3 (arch L-46 miss).** E-7e(f) "Every plan" gains: "This supersedes ARCH §5.2 l.1066's `OnFailure=breezy-study-failed@` for autonomy-owned studies (E-7a rule 1); AUT-2 l.1199 is amended accordingly." Add AUT-2 l.1199 to the Consumer Surface table. Classify AUT-1 l.147, 167, 222, 602, 738, 1015, 1044, 1579, 1598 in the L-46 list (read each; descriptive or host-step unless shown otherwise) so "every hit classified" is true.
- **B5-R4 (sec N1).** E-7e(c) and `validate_table`: `credential_env` keys must not be `PATH`, `HOME`, `TMPDIR`, `XDG_*`, `LD_*`, `PYTHON*` or `BREEZY_AUTONOMY_*`; test `test_credential_env_key_denylist`.
- **B5-R5 (sec N2).** E-7d Residual gains: "Phase 2 runs `python -m pytest` without `-I` because worktrees need `PYTHONPATH`; a caller-controlled `PYTHON*` variable or `sitecustomize` imports before the blocker. This is operator-controlled environment, the same exposure as phase 1."
- **B5-R6 (arch non-blocking 1–5).** (1) V11 moves to WP-B2b-3. (2) WP-B2b-2 owns the AC-5 snapshot pre-line form, test and mutation; B2c's scope drops it. (3) AUT-1 audit E-9 states its basis: the `flock -w` runs inside ExecStart's `timeout` (≤ 1500) so it is not added; AUT-1 l.881 restated. (4) Daily and failed@ sums include the `install -d` bound with derivation shown; failed@ reads "≤ 20 s before its page". (5) AUT-6 health's `show -- 'breezy-*'` consumer filters on `Id` ending `.service` (M40).
- **B5-R7.** Seam B r3 security note on the `touch` mtime (N3, INFO) recorded as benign; no change.

## Seam A round 5 (coordinator rulings on r5 flags, 2026-10-03)

- **A6-R1 (R25, `.tmp.` leftover).** `newest_export` adds exactly `\A\.tmp\.[0-9a-f]{16}\Z` (the `write_once` temp name, AC 7 step 3) to the known-and-ignored set. Safe because `write_once` publishes only by `os.link` to the final name, so a temp name is never an export; ignoring it cannot hide or admit an export. Every other unknown name stays `export_unreadable`. Test `test_newest_export_ignores_write_once_temp_name` plus a control that `.tmp.x` (not 16 hex) still refuses. R25 closed.
- **A6-R2 (R26, ban scope).** AC 15(ii) scope widens from the three named packages to every package under `src/breezy/` whose dotted path has a component starting with `autonomy` (today: `persistence/autonomy`, `strategy/autonomy`, `analysis/autonomy`, and AUT-3's planned `analysis/autonomy_refit`). The test derives the set by walking `src/breezy/` so new autonomy packages are covered automatically. AUT-3 r6 `:137` therefore needs a reviewed exemption row in AUT-3's own commit ((b) item 42 updated). R26 closed.

## Build-time rulings (seam A 3a pins review, 2026-10-03)

The architect verified pins.py and veto.py (seam A 3a) against ARCH §4.5, C5 and the errata: CONFIRMED, no value defect. These consumer obligations are recorded for the AUT-5a brief:
- **P-1 (engine demand reason).** AUT-5 r7 :304 makes the engine write a demand file whose `reason` must be in `DEMAND_REASONS`, which is currently `{"integrity_floor"}`. AUT-5 WP1 either uses `integrity_floor` explicitly or widens `DEMAND_REASONS` in a reviewed pins commit. Any other reason vetoes the whole venue (fail-safe, but too broad).
- **P-2 (halt map wildcard).** The `HALT_REASON_CLASS_MAP` key `policy_halt:*` must be resolved explicitly by the engine-mirror consumer, so that a `policy_halt` with any A1 detail maps to TERMINAL (ARCH :705) and never falls through to `unreadable_or_unknown`/INTEGRITY. The consumer also supplies `halts_all` and the read-failure-after-H rule. Test: `test_policy_halt_any_detail_maps_terminal`.
- **P-3 (detector-id disagreement).** AUT-4 r11 :592/:1365 (`live_sequential` → DEMOTE) and AUT-6 r15 :464 (`aut6.*` ids) disagree with the pinned `DEFAULT_RESTRICTIVE_CLASS`, which follows the owner AUT-5 r7 :224. Settle this in the AUT-5 policy ruling review before AUT-4 or AUT-6 code against the map.

## Build-time rulings (seam B2b-1 security review, 2026-10-03)

- **B6-R1 (HIGH, binding).** AC-1.3(7)(b) is tightened. `$NOTIFY_SOCKET` must EQUAL `/run/user/<uid>/systemd/notify` exactly (plus S_ISSOCK and owner), not merely sit under `/run/user/<uid>/systemd/`. Otherwise `systemd/private`, the manager's control socket, could be bound and a sandbox could start units, breaking E-7e(c) "no row exposes `/run/user/<uid>/systemd/private`". Test: `test_notify_socket_private_refused`. E-7e(c) is read with this exact-path meaning.
- **B6-R2 (MEDIUM).** Data binds also require owner == uid and no 0o022 bits. Config binds (`config_ro_binds`/`config_ro_dirs`) are permitted only on rows carrying `E7_CONFIG_DIR`, only for paths in the exact `CONFIG_RO_ALLOWLIST = {".config/systemd/user"}` (widened only by a reviewed edit), and the nested-bind check covers config-vs-config and config-vs-data.
- **B6-R3 (LOW).** Bus-read `-p`/`--property` values may not name any property containing `Environment` or `Credential` (case-sensitive substring; covers `Environment`, `EnvironmentFiles`, `LoadCredential`, `SetCredential`, `ImportCredential`). The `credential_env` denylist adds `GLIBC_TUNABLES`, `GCONV_PATH`, `LOCPATH`, `NOTIFY_SOCKET`, `CREDENTIALS_DIRECTORY`, `BASH_ENV`, `NODE_OPTIONS` and the prefix `SSL_CERT_`. Credential files require `st_nlink == 1`.
- **B6-A1 (seam A 3c build).** `FillReader.fill_index` raises `FillIndexAbsent` for a missing key rather than returning a sentinel. This is documented on the Protocol, and AUT-5a's `PolymarketUsFillReader` matches it. `test_reconciliation_and_entry_guard_never_read_canary_store[entry_guard]` moves to AUT-2 (canary store, Z14), with the `[adapter_reader]` param going to AUT-5a.
- **B6-R4 (B2b-2 build, coordinator).** The unit-lint scope is set by exact sets, not a name prefix. The full AC-5 lint applies to `AUTONOMY_OWNED_UNITS` ∪ every row's `units`, except the units in `WRAPPER_LINE_ONLY_UNITS` (unit → owning-plan citation; empty in seam B; AUT-1 adds the recorder in its own commit), which get only their wrapper lines linted. `validate_table` requires that set to be ⊆ the row units and disjoint from the owned and residual sets. A unit that names the wrapper but appears in no row is a `wrapper_unit_not_in_row` error. Reason: a prefix heuristic would let a non-prefixed consumer unit, such as an AUT-2 label unit, escape the full lint.

### Build-time rulings (seam B2b-2 security review, d137c981)
- **B6-R5 (HIGH).** Every linted Exec value refuses a token that equals or contains `;`. systemd treats a standalone `;` word as a command separator, so without this check an unwrapped second command could ride on a wrapped line.
- **B6-R6 (HIGH).** The lint scope covers instance files (`name@x.service` → entry `name@`) and every `*.service.d/` directory that applies to an in-scope unit. That means the unit stem, any dash-truncated prefix of it, or the top-level `service.d`. Any `Exec*` directive in such a drop-in is an error (`drop_in_exec`). This completes B6-R4's "every unit any row lists".
- **B6-R7 (MEDIUM).** `ExecStart`/`ExecStopPost` allow no prefix character (`@ - : | + !`). `ExecStartPre` keeps only the planned `-` on the bus-snapshot line. `ExecStop`, `ExecReload`, `ExecCondition` and `ExecStartPost` are forbidden on fully linted units.
- **B6-R8 (MEDIUM, partial).**
  - **Adopted:** argv adds `--unshare-ipc`, `--unshare-uts` and `--unshare-cgroup-try`. It also `--unsetenv`s every present credential_env name and every name with the prefix `SSL_CERT_`, `LD_` or `PYTHON`. `NOTIFY_SOCKET` is kept only on `E7A_R2_NOTIFY` rows.
  - **Not adopted:** `--clearenv`, because consumer units pass config via `Environment=`.
  - **Deferred:** `--unshare-net`. Network policy is per consumer row; see erratum E-15.
- **B6-R9 (LOW).** The wrapper's `main` maps any unexpected exception to reason `internal`, exit 78, with no traceback or path.
