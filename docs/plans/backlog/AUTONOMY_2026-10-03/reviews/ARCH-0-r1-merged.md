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

### Build-time rulings (seam A 4a review, 98c8458c)
- **A4-R1 (HIGH).** The judged-file set uses A6-R2's "a component starting with `autonomy`" under `src/breezy/`, not an exact component match.
- **A4-R2 (HIGH).** The one-writer scan resolves aliases for every tracked writer module. It flags attribute references (not only calls), `getattr`/`__import__`/star imports, `os.write`/`pwrite`/`fdopen` (non-read mode), `copy_file_range`, `sqlite3.connect`, `logging.FileHandler`, and `subprocess`. It fails closed on `open(**kw)` and non-literal `Path.open` modes. `json`/`pickle.dump` to a passed fp stays out of scope: the opener is the write site.
- **A4-R3.** The one-writer gate must not go red when `registry_store` lands (6e).
- **A4-R4.** `ensure_dir` is owned by seam 6d. The transitional `walk_dirs` `os.mkdir` row carries owner 6d and a strict-xfail retirement stub.
- **A4-R5.** Known launch-window overlaps are strict-xfail params owned by `coordinator O-1`, per plan r1 l.384 and AUT-6 r15 O-1. They are not a green exemption. The overlapping units are `breezy-quote-tape-ingest-frequent` (`*:0/15`, `TimeoutStartSec=1800`) and `breezy-discovery-pull` (16:52, 1800 s). Drop-ins are read. The coordinator owns the reschedule as a separate deploy change.
- **A4-R6.** A strict-xfail `test_envelope_pending_names_empty` is owned by 8d. Every `BLOCKS_KINDS_FLOOR` key needs a ledger row.
- **A4-R7 (LOW).** Drop the `_publish_by_link` row. Add a floor header note. Share one collect-only run.

### Build-time rulings (seam B2b-3 build)
- **B7-R1.** AC-2 step order stays as written: env-row check, then the degraded check. The wrapper's degraded exec (`_exec_degraded`) also sets `BREEZY_AUTONOMY_BWRAP_ROW=<row>`, so a genuine notifier-fallback run reports `degraded` rather than `env_row`. This change lands in WP-B2c. It is dormant until then, while `NOTIFIER_FALLBACK_ROWS` is empty.
- **B7-A1 (accepted deviations).**
  - `self_probe_plan` lives in `self_probe.py`.
  - The probe derives its `/run` allowlist itself, because `CREDENTIALS_DIRECTORY` is unset in the sandbox (B6-R8).
  - The phase-2 harness passes `PYTHONPATH` via `/usr/bin/env` inside the sandbox, because B6-R8 strips `PYTHON*` from the wrapper environment. Consumer phase-2 tests do the same.
  - The registry-count test sums the per-file collect counts and still requires equality.
  - V12 (real notify delivery) stays manual, because `socket` is a denied import in phase 2.

### Coordinator O-1 (launch-window overlaps found by seam A 4a)
- **O1-R1.** `breezy-quote-tape-ingest-frequent.timer` drops its 16:30, 16:45 and 17:00 firings, and `breezy-quote-tape-ingest.service` sets `TimeoutStartSec=780` (the 600 s deadline plus the 180 s tail). The 16:15 worst case is 16:15 + 780 + 90 = 16:28. Neither the node launch nor KILL coverage reads the ingest catalog, so a 60-minute catalog lag is free. Its 4a `known_overlap` param flips to pass.
- **O1-R2.** `breezy-discovery-pull` (16:52, AUD-02 evidence) has been failing on timeout since 10-02. The cause is inferred as a byte-0 read of about 2.5 GB of node logs in a 256M cgroup, and it is being fixed TDD-first. Its launch-window status stays a strict-xfail owned by O-1 until a separate decision on adding a launch-path row to the ARCH §5.2 table. That decision also has to reconcile the window-end readings: 17:00 (E-V6), 17:05 SELF_CHECK, or 17:10.

### Build-time rulings (seam A 5a ARCH review, 52d2e5e0)
- **A5-R1 (M-1).** The WP-5 STOP condition ("a non-integer JSON number in C4") means a JSON *float* only. ARCH non-integer quantities (`power`, `mde`, `eta_to_verdict_days`, `alpha_spent`, `alpha_k`, decimal `metrics`, `runtime_s`, `own_outcome_max_abs_delta_p`) are canonical `decimal_str` strings (prec-38). That is the only encoding consistent with AC 5's no-float parse. Producers AUT-3, AUT-4, AUT-5 and AUT-6 write strings and never floats.
- **A5-R2 (H-1).** A verdict `metrics` value is one of:
  - a canonical decimal string;
  - a text string (closed character set `[A-Za-z0-9_:.()=,-]`, ≤ 128 characters);
  - a bool;
  - null.
  Names remain sorted and unique. This covers `day_status=NO_INPUT`, `unknown_reason`, `cause_class`, `exec_snapshot_advisory`, `nomination_transition_id`, a null `statistic`, and `INCONCLUSIVE(...)` reasons.
- **A5-R3 (H-2).** Verdict `inputs` are ordered and unique by `(path_role, sha256)`. Several inputs may share a role, for example one `refit_run` per model class, or several `tape_snapshot` inputs.
- **A5-R4 (H-3).** Lineage reasons:
  - `NO_CHANGE` reasons form the closed set {`below_delta`, `existing_sha`}.
  - The reason regex is `\A[a-z0-9_]{1,64}(:[0-9a-f]{64})?\Z`, which admits `engine_refused:<sha256>`.
- **A5-R5 (LOW).** The following are adopted:
  - full-length shas only;
  - structural `train_end_exclusive_utc <= forward_eval_start_utc`;
  - refuse `valid_until_ns < produced_at_ns`;
  - `own_outcome_gate_decisions_changed` is null exactly when `own_outcome_label_set_sha256` is null;
  - `params` frozen on construction;
  - refuse a non-null `policy_ruling_sha256` combined with the `no_policy_ruling` assumption.
- **A5-R6.** Plan r5 l.671 is read with the dependency list at l.823: `lineage` may import `wire`, `canonical`, `single_read`, `paths` and `pins`.

### Build-time rulings (seam A 5b ARCH/security review, 3081a8fa)
- **A5b-R1 (H1).** Demand slots are counted per writer class.
  - The engine's (family, reason) slot counts only engine-written files.
  - A producer's slot counts only producer files.
  - A standing producer `integrity_floor` file never blocks an engine write.
- **A5b-R2 (M1).** The engine is never refused for count. An engine write past `DEMAND_FILES_MAX` is made anyway; the resulting venue veto is the restrictive outcome. Producers keep `SLOTS_FULL`.
- **A5b-R3 (M2).** Demand writers are not serialised: AUT-5 r7:1272 has no lock, and the producer runs under its own lock. The invariant is "every interleaving ends restrictive", pinned by a two-writer interleaving test.
- **A5b-R4 (M3).** The AUT-6 r15 AC1 `O_TMPFILE` publish requirement is an ARCH-0 obligation, because ARCH-0 owns the only `registry/demand/` writer.
  - `single_read` gains an `O_TMPFILE` + `linkat` + directory-fsync publish path.
  - On an unsupported filesystem it refuses with a distinct reason; the caller maps that to CRITICAL / exit 3.
  - Demand writes use this path.
  - The reader's `.tmp.` listing exception is withdrawn (r15:2076). Any non-conforming name in `registry/demand/` is a venue veto.
- **A5b-R5 (LOW, all adopted).**
  - A `stops(family_id)` helper that honours `venue_veto`.
  - Journal `head_matches(chain, head)`, plus docstrings stating that empty-vs-external-head is a mismatch and that restrictive writes are never gated on a journal append.
  - Drill marker read returns the raw-bytes sha256, and `fstat` errors become `MarkerError`.
  - The demand writer refuses early when the listing is over cap.
  - The plan's File-plan dependency cells (l.667, 673, 674) are read with the real imports (`canonical`, `paths`).

### Build-time rulings (seam A 6a ARCH review, 534f8661)
- **A6a-R1 (H1).** `family_prior_seq` and `expected_prior_seq` are required, with no default. The chain walk tracks the last `venue_seq` per family. It raises `ChainBroken` when `family_prior_seq` does not equal the family's previous `venue_seq` (0 on the family's first row), per ARCH l.417.
  - **Why:** a wrong value would let a legitimate repeat ATTEST, RESUME or HALT collide on its Y9 id. The store would then silently log it as a no-op.
- **A6a-R2 (M1).** The chain walk refuses a row whose stored `transition_id` differs from `computed_transition_id()`.
- **A6a-R3 (M2).** Literal hex goldens freeze `canonical_row` and the Y9 preimage encoding. The self-referential golden is replaced.
- **A6a-R4 (M3).** Duplicate `cause_verdict_ids` or `voids_transition_ids` are refused with `BAD_VALUE`.
- **A6a-R5 (LOW).**
  - `policy_ruling_id` and `policy_ruling_sha256` are both empty or both non-empty. An empty pair is valid for C5, per AUT-5 r7:207; ruling A5-R5 governs C4 only.
  - A malformed `evidence_journal_heads` pair raises `WireRefused`.
  - `hwm_from` and `hwm_to` are documented as holding `export_seq`, unless the ARCH W4 or AUT-5a text says otherwise. The implementer verifies this and cites the source.
  - `compute_transition_id` validates its inputs.
  - The pattern-equality test also compares flags.
- **A6a-A1.** `transition_id` lives in `schemas`, and 6b re-exports it under the plan's name `transitions.transition_id`. The local pattern copies in `schemas` follow the plan's import list. Their comment must state that the copies exist because of that list, not because of a contract: `paths` is reachable transitively.

### Build-time rulings (seam A 6b ARCH review, 15428bfa)
- **A6b-R1 (HIGH).** Widening is decided per row. A PROMOTE widens only when `to_state is CHAMPION`. A SHADOW→CHALLENGER nomination is not widening (AUT-5 r7:166, ARCH:942). Without this, AUT-4 forward shadow cannot start before L2, against the ARCH:1058 wave order. `rows_admissible` uses `is_widening_row`. `WIDENING_KINDS` stays the kind set used for the pins subset check.
- **A6b-R2 (MED-1).** A PROMOTE, DRILL_PROMOTE, ROLLBACK or ROOT_ADMIT row whose `to_state` is CHAMPION but which has no `effective_launch_date` folds to `FoldInvalid(head_missing_launch_date)`. Per ARCH:476-479 these rows are always pending until LAUNCH. Erratum E-16 adds this reason to the fold's closed set.
- **A6b-R3 (MED-2).** ACTIVATE cites its pair through `paired_transition_id`, which holds the transition id of the →CHAMPION head. Erratum E-16 amends ARCH l.418 so that `paired_transition_id` is also non-null on ACTIVATE. 6e's column rules follow E-16.
- **A6b-R4 (item 6).** `ALLOWED[ROOT_ADMIT]` includes `(None, CHAMPION)`, per A4-R6 and plan r5:200. Erratum E-16 records it against ARCH:468/479.
- **A6b-R5 (item 9).** `test_family_introduced_by_other_kind_is_invalid` moves from 7b to 6b. The fold must be total.
- **A6b-R6 (MED-3, LOW).**
  - Fix the ROLLBACK-pair test timestamps and assert the HALTED champion.
  - Rename the ALLOWED-table test to "ARCH + A4-R6".
  - Fold consumers are blocked by a guard test until 7a lands SWAP_CANCEL voiding: nothing outside `persistence/autonomy` may import `fold` until then.
  - Add a planted positive control for the `[fold]` scan and a monkeypatched-pins window test.
  - Never apply immediate rows with `ts_ns > now_ns`.
  - Make `head_venue_seq` the sealed `rows[-1].venue_seq`.
  - Label the invalid-chain RESUME test as an invalid-chain pin.
  - Document RETIRE as neutral.

### Build-time notes (seam A 6d build, b96c0d50)
- **A6d-A1.** Accepted under review:
  - `write_root_copy` takes the keyword `composition_kind`.
  - `read_manifest_facts(family_id, sha, *, paths, repo_root)` is bound with `functools.partial` in 6e.
  - `FamilyBytes`, `ByteBindingFailure` and `verify_family_bytes` are deferred to 8c, where their tests live.
  - The 0500 seal belongs to AUT-5a.
- **AUT-5a obligation.** The autonomy manifest reader never passes `allow_draft`, so a DRAFT family manifest reads as absent. Any family AUT-5a bootstraps, including `pm_us_crh_fq_v1` if it is still DRAFT, must first be committed as REGISTERED.
- **A6d-A2 (security review: APPROVE).**
  - Correction to A6d-A1: `deploy/families/pm_us_crh_fq_v1.json` is already REGISTERED (ad76d2f2). The AUT-5a obligation binds only for a DRAFT seed.
  - Adopted now:
    - (L1) `ensure_dir` fsyncs the parent after `mkdir`.
    - (L2) `write_root_copy` publishes via `write_once_tmpfile`, so no named temp file is left in `<sha>/`.
    - (L4) the unreadable-source test uses the real manifest sha, and `ensure_dir` gets a non-default-mode test.
  - Carried:
    - (M1) Before 8b is built, confirm it needs only `read_manifest_facts`; otherwise `verify_family_bytes` moves into 8b.
    - (M2) 8c reads root manifests repo-only (E-14 3a), with a test; the engine never writes a registry copy of a root.
    - (L3) The path-based PREREG guard after an fd read is accepted. It is same-uid only, per ARCH:408.

### Build-time rulings (seam A 6e build)
- **A6e-R1.** `test_family_artefact_binding_immutable` moves to seam 7d (validate II), which owns the binding rule. It stays a pending envelope name until then.
- **A6e-R2.** Until 7c/7d wire `transitions.validate` into `append`, the store applies only structural checks:
  - the chain verifies;
  - the extension verifies;
  - the extended chain folds;
  - the row shape conforms to E-16(a).

  A guard test therefore forbids any module outside `persistence/autonomy` from importing `registry_store` until 7d lands. This follows the fold-consumer guard pattern, and 7d removes the guard.
- **A6e-R3.** 6f puts `RegistryReader`, `write_export` and `newest_export` in a sibling module, `registry_export.py`, because `registry_store.py` is already at 728 lines against an 800-line cap. The one-writer table names the export writer row in that module.
- **A6e-A1 (accepted).** Accepted build choices:
  - The store does not take `engine.lock` (AUT-5a owns it); `BEGIN IMMEDIATE` plus a 5 s busy timeout serialises writers.
  - Refusals the closed `RefusalReason` set cannot name map to `engine_inconsistency`, which fails closed.
  - Id lists are stored comma-joined as hex.
  - `trigger_cause_class` is checked only as allowed-on, not required-on. 7c/7d may tighten this.
- **A6e reviews (database + ARCH, 3f022a8a): REQUEST_CHANGES. Merged rulings follow.**
  - **A6e-R4 (HIGH).**
    - `_check_batch` refuses any row whose `transition_id` differs from `computed_transition_id()`.
    - A replay compares every stored column against the batch, except `seq`, `venue_seq`, `ts_ns`, `invocation_id`, `expected_prior_seq` and the two chain hashes. A mismatch raises `ReplayMismatch`.
    - The Y9 "logged no-op" applies only when the bodies match (erratum E-17a). A stale-fold retry must never be reported as committed.
  - **A6e-R5 (HIGH, reproduced by probe).** The insert guard refuses an existing `transition_id`. This closes the `INSERT OR REPLACE` delete on a connection without `recursive_triggers`. It is tested on a default connection at head+1. Same-uid `DROP TRIGGER` remains the ARCH l.408 residual.
  - **A6e-R6.** The writer uses `synchronous=EXTRA` (3) and reads it back. In DELETE journal mode, FULL does not fsync the directory after the journal unlink, so a committed HALT could roll back after a power cut (erratum E-17b amends Y5/AUT-5 §3.2). The two reviews disagreed here; the ARCH reviewer's reading matches SQLite's documented semantics.
  - **A6e-R7.** Every failure escaping `append` is a `RegistryRefused` subclass. `ChainBroken` maps to `ChainRefused(chain_broken)`. `WireRefused`, `ValueError` and `TypeError` map to `RowRefused`.
  - **A6e-R8.**
    - CAS runs before the clock check (amending plan AC 10 order 7→8).
    - The engine's retry contract is `isinstance(CasMismatch)`, which is documented and tested.
    - `StoreUnavailable` splits into `StoreBusy` (retryable, Y19 60 s) and `StoreDrifted` (not retryable). Drifted covers schema drift, a foreign database, an integrity error and an I/O error.
  - **A6e-R9.** Row skew is one-sided: `ts_ns <= now_ns`. A future-stamped head could otherwise delay a committed HALT by up to 300 s (erratum E-17c).
  - **A6e-R10.** Column rules:
    - `halt_cause_class` is allowed only on DEMOTE/HALT. Required-on is left to 7c/7d.
    - `voids_transition_ids` is required and non-empty on SWAP_CANCEL. A cancel without a target is malformed, not merely restrictive; its refusal routes to the Z11 demand path.
    - The `cause_code` value set is validated per kind: `drill_close_restore` only on RESUME, `target_integrity` on TARGET_INELIGIBLE.
  - **A6e-R11 (LOW).**
    - The schema comparison ignores `sqlite_stat*`.
    - `ROLLBACK` in `finally` is suppressed so that `close()` always runs and the original error survives.
    - `_open` re-checks the 0600 file mode and 0700 directory mode on every open.
    - The transition-table test asserts the refusal message.
    - The vacuous closed-reason test is replaced by a test that triggers each refusal.
  - **A6e-A2 (fail-closed, as specified).** Schema drift, a non-verifying stored chain, or a stored head lacking `effective_launch_date` refuses every later append on that venue, restrictive writes included. Readers refuse the same database, so the node is vetoed. Y19 plus the Z11 demand file is the clearing path. No bypass exists, by design. The engine never mixes restrictive and widening rows in one batch (plan 10.5).

### Build-time rulings (seam A 6f/7e ARCH review, 26447421)
- **A6f-R1 (M1).** `newest_export` refuses any repeated `export_seq` across all candidates, not only a repeat of the running maximum.
- **A6f-R2 (M2).** Every export carries every row of its venue from genesis (`venue_seq` 1) to the trailer, contiguous and hash-linked: `prev_transition_hash` equals the previous `transition_hash`. `write_export` and `newest_export` both enforce this. AUT-5 r7 B9 counter floors and reset-CLI step 2 fold a single file (erratum E-18a). The 64 MiB cap is far above the projected size.
- **A6f-R3 (M3).** A corrupt or tampered export blocks `newest_export` by design (fail closed). The clearing path is erratum E-18b: an AUT-5a-owned incident procedure.
- **A6f-R4 (L2).** `COLUMNS`, the DDL objects, the identity constants, the master-select statement and the row decoder move into a new pyarrow-free module, `registry_schema.py`, under public names. `registry_store` and `registry_export` import from it. `registry_export` leaves `PYARROW_REACHING` and joins contract (c).
- **A6f-R5 (L1, L3, L5).**
  - A real hot-journal integration test.
  - The misnamed HWM test either calls `hwm_check` or is renamed.
  - The `_connect` docstring records the same-uid parent-symlink residual (ARCH l.408).
- **A7e-R1 (L4).** The `HwmAbsent(` construction ban resolves import aliases, with a planted alias control.
- **A7e-A1.** The HWM "genesis head" written at the AUT-5a cut-over is the BOOTSTRAP row at `venue_seq` 1. A `venue_seq` of 0 is unconstructible. The unversioned exact-key HWM wire format is accepted, because any shape change decodes as `HwmUnreadable` (fail closed).

### Build-time rulings (seam A 7a ARCH review, 3d2523c0)
- **A7a-R1 (MED-1).** `drill_child` is set when a DRILL_ADMIT row applies, per AUT-7 r5:109; DRILL_ADMIT is immediate. The episode still starts when DRILL_PROMOTE takes effect. A child whose pair lapsed or was voided stays `drill_child`, and this is tested.
- **A7a-R2 (MED-2).** Y8 extends to the post-launch window [LAUNCH, launch-window end), per erratum E-19a. Within that window, a cause on the incoming family of an activated pair is written only as a SWAP_CANCEL with `pair_cause_incoming`, never as a DEMOTE or HALT of the incoming family. 7c `validate` refuses such a DEMOTE or HALT. The restrictive path stays available through the SWAP_CANCEL. 7a adds a fold test that pins the result of the forbidden sequence (two senders) as an invalid-chain pin.
- **A7a-R3 (MED-3).** `demoted_for_cause` is scoped per champion epoch, per AUT-7 r5:105-109 and erratum E-19b:
  - The fold exposes `demoted_cause_ns` (the latest cause instant) and `champion_epoch_start_ns`.
  - `demoted_for_cause` is true iff a cause falls inside the current champion epoch.
  - RESUME opens a new epoch.
  - The Y8 FORWARD_SHADOW clear is evaluated by `validate` over verdicts.
  - Without this, `fq_v1` would become permanently ineligible for drills and ROLLBACK after any recoverable DEMOTE+RESUME, including the E-5 restore.
- **A7a-R4 (MED-4).** No transition kind can clear the venue INTEGRITY freeze. Until erratum E-19c is resolved by AUT-6 (the W15 owner), the freeze is permanent: a known, fail-closed spec gap.
- **A7a-R5 (LOW).**
  - Replace the vacuous lapsed-flag loop with a lapsed DRILL_PROMOTE+SUPERSEDE pair.
  - Delete the vacuous asserts at test:129 and test:326, and the duplicate at test:178.
  - Document that `senders` is data only: consumers must not take `senders[0]` before the resolver check.
  - `halted_since_ns` (AUT-6 #30) moves to 7b.

### Build-time rulings (seam A 7b ARCH review, 027dc6d9)
- **A7b-R1 (HIGH, H1).** Windowed counters are sorted tuples of effective instants (ns), per erratum E-21, with the reviewer's recommended shape:
  - **LineageTallies:**
    - `nomination_instants` (new).
    - `rollbacks` and the six `drill_*` counters become tuples.
    - `model_resumes` (new): RECOVERABLE_MODEL resumes, including a ROLLBACK_FAILED halt whose trigger class is RECOVERABLE_MODEL.
    - `nominations`, `infeasible_nominations`, `alpha_spent` and `terminal_frozen` stay lifetime scalars.
  - **VenueTallies:**
    - `infra_resumes` and `drill_close_restores` become tuples.
    - `sender_changes` (new): every Z3 logical change.
  - **Use:** budgets are in-window slice lengths, evaluated in 7c/7d. Venue caps sum the slices across lineages.
  - **Rationale:** plan r5:214-221 (ints) is superseded. An int carried across HWM_RESET can only lock a budget or refund it.
- **A7b-R2 (M2).** `carried_counters` merges as follows:
  - lists by sorted multiset union, keeping each instant at its higher multiplicity;
  - ints by max;
  - bools by OR.
  
  The 7d B9 check is "export ⊆ carried" as multisets.
- **A7b-R3 (M1).** An introducing row (MINT, BOOTSTRAP or ROOT_ADMIT) with a null `lineage_root_family_id` is `FoldInvalid(root_lineage_mismatch)`, per E-14 rule 3. The two default-to-own-lineage tests are inverted.
- **A7b-R4 (LOW).**
  - Add `promotions == ()` assertions to the nomination tests.
  - Rename the vacuous α test, or give it a nonzero `alpha_k` on an infeasible row.
- **7c obligations:**
  - refuse a nonzero `alpha_k` on an infeasible nomination (AUT-4 r11:567);
  - refuse a ROLLBACK whose `drill` column disagrees with an open episode.
- **Open (pre-Kalshi):** lineage counters are venue-independent (ARCH:413), but the fold runs per venue. The consumer of `K_LIFETIME` and α must merge lineages across venue folds before a second venue goes live.

### Build-time rulings (seam A 7c ARCH review)
- **A7c-R1 (HIGH-1).** The E-5 drill-close restore is subject to `RESUME_COOLDOWN_H` (AUT-7 r5:409, :866; ARCH:487). The cooldown delays the restore to the next eligible pass; it does not strand the venue. The exemption is removed and the test flipped.
- **A7c-R2 (HIGH-2).**
  - A DRILL-class DEMOTE/HALT is refused unless the family is CHAMPION with no standing non-DRILL cause.
  - A `ROLLBACK_FAILED` row whose trigger class is DRILL counts as DRILL-class.
  - A generic rule, landing in 7c: every row's `from_state` must equal the fold's current state for its family (∅ for an introducing row). This closes the V12 "first cause wins" laundering, where a model-halted family is re-halted as DRILL to obtain a budget-free restore.
- **A7c-R3 (HIGH-3).** Seam 7d scope adds the fold-decidable ROLLBACK rules:
  - target `rollback_eligible`, not `target_ineligible`, not `terminal_frozen`;
  - `ROLLBACK_TARGET_MAX_AGE_D`;
  - `MAX_ROLLBACKS_PER_VENUE_30D`;
  - `terminal_frozen` refuses PROMOTE.
  
  Plan l.189: `validate` implements every fold-decidable C5 rule.
- **A7c-R4 (MED-1).** E-5 binds to the actual failed close:
  - the latest drill episode is closed;
  - the family's `halted_since_ns >= episode.end_ns`;
  - the family is the incumbent that the episode's DRILL_PROMOTE superseded (the root, per AUT-7 r5:242).
- **A7c-R5 (MED-2).**
  - A family's artefact binding is immutable (ARCH:367): the fold binds the introducing row's sha.
  - `validate` refuses a row carrying a different non-null sha.
  - `test_family_artefact_binding_immutable` lands in 7c, superseding A6e-R1's 7d placement.
- **A7c-R6 (MED-3), obligation for AUT-5/AUT-7.** A `validate` refusal of a DRILL-class restrictive row must not enter the Y19 retry/demand-file path, which would veto the venue. The drill aborts instead (AUT-7 r5:400-403).
- **A7c-R7 (MED-4).** `_drill_entry` checks that the incumbent is not `demoted_for_cause` (ARCH:475, :477, W2).
- **A7c-R8 (LOW).**
  - Docs say "integrity freeze" and note that the engine owns the live exec-store halt check.
  - When `verdicts` is supplied, RESUME requires each cited verdict to be a PASS produced after `halted_since_ns`.
  - A HALTED family with `halted_since_ns is None` is refused, never exempt from the cooldown.
  - `lint-imports` and the pyarrow-free contracts are verified after `transitions` gains the `validate`→`verdict` edge.
- **A7c-A1 (accepted).**
  - Private window lengths, pinned by boundary tests.
  - d0 ordering skips the root, safe while root d0 ≤ child launch.
  - Uncited RESUME refused.
- **A7c-A2 (accepted deviation).** The generic `from_state` rule has exactly one exemption. A post-launch SWAP_CANCEL in [LAUNCH, 17:00) may name an effective pair's incoming family as CHALLENGER while the fold already shows it CHAMPION. Without this exemption, the E-19a alternative path, which must stay open, would be refused. It is pinned by `test_the_swap_cancel_alternative_is_accepted_in_the_launch_window`.

### Integration rulings (seam B rebased onto seam A gates)
- **B8-R1.** The seam A judged-file predicate (A6-R2/A4-R1, "a component starting with `autonomy`") excludes exactly the package `breezy.runtime.autonomy_sandbox`, through one explicit, reasoned exclusion row with a planted control test. That package is ARCH-0 seam B's own runtime. It is governed by seam B's gates:
  - the stdlib-only import contract;
  - `WRAPPER_CODE_FILES` / `SHARED_WRITE_SITES` (`test_autonomy_write_sites`);
  - the unit lint;
  - the security reviews.
  
  It legitimately `execv`s bwrap and names host paths (`/run/user/<uid>`, `/usr/bin/bwrap`). No other `autonomy*` package is exempt, so AUT-1's `autonomy_capture` and AUT-3's `autonomy_refit` stay judged.
- **B8-R2.** `test_three_arch0_contracts_are_strict_forbidden` counts the seam A contracts by their exact `ARCH-0 autonomy (` name prefix. Seam B's stdlib-only contract is pinned by seam B's own test.
- **B8-R3.** The wrapper `deploy/systemd/breezy-autonomy-bwrap` must be exactly 0755 on disk. A checkout under umask 002 yields 0775, which is group-writable, and the test correctly fails. The worktree file is chmod'ed 0755. **Obligation for B3/install:** the install step sets 0755 explicitly, and the V-steps verify it on the primary tree. The test is not relaxed.

### Build-time rulings (seam A 7d ARCH review, 66d5e113)
- **A7d-R1 (M1).** Drill ROLLBACKs are subject to `ROLLBACK_MIN_DWELL_H` (ARCH:913, AUT-7 r5:185). They are exempt only from the rollback budget (ARCH:943). The affected drill fixtures are re-planted, and the misnamed exemption test is fixed to exercise the rule.
- **A7d-R2 (M2).**
  - `_cancellable` mirrors the fold's `_cancel_voids` exactly. A member of a non-voided pair is cancellable if `ts < launch`, or if the pair was activated and `ts < window_end`.
  - `ValidateRefused` carries the `Refusal` rule and `row_index`, so the engine can tell a deterministic validate refusal from a retryable one.
  - **Obligation (AUT-5), extending A7c-R6:** a deterministic `validate` refusal of a restrictive row never enters the Y19 retry/demand path. The engine records it and takes the next restrictive alternative instead.
- **A7d-R3 (LOW).**
  - (L1) The launch projection applies batch partners at their head's LAUNCH, as the fold does.
  - (L2) Only immediate introducers count as "held" for the MINT exemption.
  - (L3) An ATTEST with `until <= ts` is refused.
  - (L4) The manifest-isolation test is parametrized over every restrictive kind and ATTEST.
  - (L4) The weak assertion at :752 is fixed, and the duplicate at :321 removed.
  - (L4) A test asserts `_RESTRICTIVE == transitions.RESTRICTIVE_KINDS`.
  - (L4) The restrictive single-sender probe is extended with DISPLACED, ROLLBACK, DRILL_PROMOTE and ROOT_ADMIT pairs, a second pair written in the launch window, and every restrictive cause class.
  - (L5) An AST guard confines `_append(..., _fixture_stage=True)` to `tests/`.
- **A7d-R4 (L6).** `fold.py` is at 776/800 lines. Pair handling moves to a sibling `fold_pairs.py` before any further fold growth. This is done in this fix pass, as a behaviour-preserving move.
- **Carried obligations.**
  - (AUT-5) When `RuleSetPending` is lifted for HWM_RESET, `_validate` passes `export_counters`.
  - (AUT-5) The ROOT_ADMIT cooldown after TERMINAL, and the `MIN_DAYS_BETWEEN_PROMOTES` M-rate, are owned by the engine. Both are inert in v1.
  - A same-artefact MINT with a different manifest is free. This is accepted (ARCH:255-257) and noted.

### Seam A 8a security review (5904ca6d): APPROVE, live behaviour identical
- The extraction is statement-equivalent. The call order is unchanged. The new `lineage_policy_authorized` is inert: its allowlist is empty, it has no caller, and it can never return `authorized=True`. The only import added is `re`. The FQ tests are unmodified.
- **Carried to 8c:**
  - (L1) An AST test asserts that nothing in `src/` outside `live_orders_gate` references `_lineage_policy_authorized`. The resolver calls only the public function.
  - (L2) When AUT-5 WP9 adds the first lineage allowlist row, its review confirms that the root id does not itself match `CHILD_FAMILY_ID_RE`.
- **Activation:** 8a merges outside 16:30–17:10Z. It goes live at the node's next 16:50Z LAUNCH (AC 30). 8c merges only after a boot line timestamped after that relaunch.
- **B8-R3 follow-up (gate B5).** Every checkout or rebase under this host's umask 0002 rewrites the wrapper as 0775. The rebased seam B full gate failed only `test_wrapper_script_is_mode_0755_…`. Every other test passed (phase 2: 27/27). The wrapper was chmod'ed 0755, its test file was re-run green, and seam B was merged. The primary-tree copy was chmod'ed 0755 after the merge.
- **WP-B3 obligation (binding).** Install the wrapper with `install -m 0755` to a location outside the git checkout, and point the units at that copy. The repo file's mode then never decides the deployed mode. The V-steps verify the installed copy's mode and owner.

### Build-time rulings (seam A 8b ARCH review)
- **A8b-R1 (H1).** ROLLBACK and ROOT_ADMIT citations are judged by role, per erratum E-22.
  - Each cited verdict is resolved in its *subject* family's directory. The search is limited to three places: the row's family, its batch partner (F, the outgoing family), and the prior fold's senders.
  - F's halting causes must be FAIL verdicts whose subject is F and whose artefact is F's bound sha.
  - The fee verdict must be a DRIFT `fee_schedule` PASS for the champion.
  - An empty citation list is allowed only when F's standing halt carries no verdict (an exec-store mirror, or a `rollback_failed` HALT).
  - Tests must cover ROLLBACK and ROOT_ADMIT, the live drill's closing ROLLBACK to `fq_v1`, DRILL_PROMOTE citing nothing, and the E-5 restore citing nothing.
- **A8b-R2 (H2).** Replay finds an artefact's model class by probing a closed, pinned set of model-class components and requiring exactly one match.
  - The set is `pins.MODEL_CLASS_COMPONENTS`, which includes `density_table` and `rung_recalibration`.
  - Zero matches or more than one match gives `ARTEFACT_UNREADABLE`.
  - Tests must include a non-`density_table` child.
- **A8b-R3 (M1).** The store folds at `batch[0].ts_ns`, not `now_ns`, so that its judgement is deterministic and replayable. Add a store/replay parity test, including a multi-row transaction and a row stamped before LAUNCH but committed after it.
- **A8b-R4 (M3).** Add a timing test: replay of a 2,000-row chain (≈ one year) completes within a pinned bound on this host. If the quadratic re-fold misses the bound, replay folds incrementally.
- **A8b-R5 (LOW).**
  - (L1) Report a prefix FoldInvalid at the first row of the previous batch, and document this.
  - (L2) Add a docstring to the FoldInvalid mapping tests, and make the shadow-paths assertion exact.
  - (L3) Memoise artefact reads by `(model_class, sha)`. `ARTEFACT_MAX_BYTES` moves to `pins`.
  - (L4) The store's manifest reader binds `repo_only` for roots too, for parity.
  - (L5) The fd-relative `os.listdir` is accepted.
- **Obligations.**
  - (AUT-5a, M2) The engine passes resolved verdicts to `append`, so that the A7c-R8 RESUME check runs at write time as it does in replay.
  - (8c, item 7) The resolver checks HWM_RESET carried counters against the newest export (B9). Replay's prior-fold floor is necessary but not sufficient.
  - (8c/AUT-5/AUT-6) Every replay caller also calls `rows_admissible`. The replay docstring says so.
- **8a merged 2026-10-04 05:02Z (cb37ca69, outside 16:30–17:10Z).** It was full-gated green together with seam B in gate A12 (phase1 rc=0, phase2 rc=0, no failures). The security review found live behaviour identical. Per AC 30 it activates at the node's next 16:50Z LAUNCH. No mid-day restart, for two reasons: the plan designates the 16:50Z relaunch as the activation evidence, and the change has no live behavioural effect. 8c merges only after a boot line timestamped after 2026-10-04 16:50Z.

### Build-time rulings (seam B WP-B2c security review, 692f2bda): APPROVE with findings
- **B9-R1 (M1).** A `show` bus read must carry at least one `-p`/`--property` and a `--` followed by unit tokens. An unbounded `show` would dump `Environment=` and the credential properties.
- **B9-R2 (M2).**
  - The reader refuses a snapshot whose `ts_ns` lies outside `[now − (budget_s + 60 s), now + 5 s]`, with `bus_snapshot_stale`.
  - The snapshot is not authentic against its own row, because the row can write its own bind. Consumers must never treat it as a cross-trust attestation.
- **B9-R3 (M3).** The deadline clock starts at entry to `_write`. Bus rows require `TimeoutStartSec ≥ budget_s + 10`, checked by the unit lint.
- **B9-R4 (M4).** Add tests for:
  - the reader's FIFO guard (`mkfifo`);
  - the `MAX_DOCUMENT_BYTES` cap;
  - `_parse_read` type strictness (bool rc, non-str argv, extra keys);
  - hardlinked snapshot and sweep entries;
  - `ts_ns` bounds.
- **B9-R5 (budget floor).**
  - `BUS_SNAPSHOT_BUDGET_RANGE_S` becomes `(5, 25)`.
  - `_check_bus` requires `budget_s ≥ 2 + 1.5 × len(bus_reads)`.
- **B9-R6 (LOW).**
  - The sweep counts skips and emits one `sweep_skipped=N` reason code; exit stays 0.
  - A `pid ≤ 1` or `pid == os.getpgrp()` refuses the kill.
  - The writer caps the total document size and reads stdout in chunks, cut off past `MAX_STDOUT_BYTES`.
- **Notes for consumers.**
  - `RUN_TRANSIENT_SHOW_ARGV` carries `ExecStart` command lines, so consumers must not log the snapshot.
  - The degraded state is not attested. Revisit when `NOTIFIER_FALLBACK_ROWS` becomes non-empty; until then a forged one gives `degraded_forged`, which fails closed.

### Build-time rulings (seam B WP-B3 security review, 31c796d2)
Live store never written: confirmed. Blocked past deadline: possible before these fixes.
- **B10-R1 (HIGH, H-1).** The intent flock is released inside the helper on every path, success or failure, before anything is yielded to the caller. A test asserts that `_is_held(lock) is False` inside the `with` body for every failure reason: DEADLINE, FINGERPRINT_UNSTABLE, COPY_ERROR and the others.
- **B10-R2 (M-1).** The copy loop checks the monotonic deadline after every chunk and aborts with DEADLINE. A truly uninterruptible read of a local regular file is accepted as a hardware-fault residual and documented. `release_deadline_ns` is validated to be no later than today's `pins.SCHEDULE_LAUNCH_UTC` instant minus 120 s (L-2), derived from `pins`, never a literal.
- **B10-R3 (M-2).** The fingerprint also digests database page 1, which includes the file-change counter. The remaining same-tick residual applies only to `take_flock=False` (advisory) results, and is documented.
- **B10-R4 (LOW).**
  - (L-1) Recovery connects through `/proc/self/fd/N/<name>`, not `realpath`. The hygiene-scan allowlist adds that literal for `wal_snapshot` only, with a control.
  - (L-3) `--exec-snapshot` is capped at 50.
  - (L-4) Add a `builtins.open` spy and an `mmap` spy to the source-never-written test.

### Build-time rulings (seam A 8c, 1d32a415: ARCH REQUEST_CHANGES, SEC APPROVE)
Both reviewers confirm the resolver never yields permit semantics. `ResolvedFamily` has no permit or `enabled` field, and `_root_gate` hard-codes `permit_present=False`.
- **A8c-R1 (ARCH M1, a child is judged against unpinned root bytes).** `_child_problem` requires `sha256(root_raw) == view.families[root].manifest_sha256`. Otherwise it returns `manifest_sha_mismatch`. Add a test: an edited root file plus a matching child is refused.
- **A8c-R2 (ARCH M2 + SEC M1, consumer guard).** Do both:
  - (a) Invert the AST guard to scan all of `src/` and `scripts/`, with an importer allowlist of `breezy.persistence.autonomy.*` (and tests). Resolve `level>0` imports against the module path. Flag `autonomy.resolver` attribute access on an imported `autonomy` package. Planted controls: relative import, package-attribute access, `app/` importer.
  - (b) Add an import-linter forbidden contract named `AUT-1 resolver consumers (removed by AUT-5a)`, outside the `ARCH-0 autonomy (` prefix so B8-R2's count stays 3. It has sources app/strategy/runtime/adapters, forbids `breezy.persistence.autonomy.resolver`, and sets `allow_indirect_imports = false`.
  - AUT-5a amends both when it lands the sanctioned consumer.
- **A8c-R3 (SEC M2 + ARCH L2, never raises).**
  - `WireRefused` from `check_venue` → `registry_unreadable`, detail `venue_malformed`.
  - `OSError`/`RuntimeError` from `_verify_ruling_file` → `ruling_refused`, detail `ruling_missing`.
  - `SKIP_SHADOW` `NotImplementedError` stays (8d); the docstring is narrowed to say so.
  - Test each case.
- **A8c-R4 (SEC M3, manifest density vs bound artefact).** Verify first. If no admissible chain can make `manifest.density_artefact_sha256` differ from the bound artefact sha (for a non-sentinel kind), assert equality with reason `artefact_sha_mismatch` (or the nearest existing closed reason) and add a test. If a legitimate path exists (for example an allowlisted manifest update), STOP and report it with the path; do not improvise.
- **A8c-R5 (ARCH M3 + budget; reconciles ARCH "tighten" vs SEC "loosen").**
  - Patch `RegistryReader.read_venue_rows`, never `_read_chain`, in the budget test and in `registry_resolver_world.serving`, so step 2 always runs.
  - The 5 s wall-clock bound stays, because this host is memory-pressured.
  - Regression detection uses a deterministic op count (fold invocations for 2k rows, pinned exactly) rather than a tighter clock.
- **A8c-R6 (LOW, adopt now).**
  - (ARCH L3) The d0/prefix rule skips heads the fold reports VOIDED or LAPSED.
  - (ARCH L4 / SEC L3) The resolver takes a `busy_timeout_ms` kwarg with default pin `RESOLVE_BUSY_TIMEOUT_MS = 2000`.
  - (ARCH L5) Test `""` → `UNSET`.
  - (ARCH L6) Fix the B9 test docstring to read "necessary, not sufficient".
  - (ARCH item 7) Add the real-run halves to `test_two_senders…` and `test_a_reset_below_the_newest_export…`.
  - (ARCH L7) `replay` passes a memoised read into `family_bytes.probe_artefact`; a single `_UNREADABLE` tuple.
  - Docstrings: `entries_allowed` is NOT a trade permit (SEC); the export race self-heals on retry (SEC L4).
- **A8c-R7 (split, both reviewers).** Make a move-only `byte_binding.py` holding `FamilyBytes`, `ByteBindingFailure`, `verify_*`, the allowlist, `manifest_equal_modulo_allowlist`, `probe_artefact` and `read_artefact`, so `registry_store` no longer pulls in `live_orders_gate`. Land it as its own commit before the R1–R6 fixes.
- **Accepted / carried.**
  - ARCH L1 / SEC L1: the lineage reason mapping is fail-closed and noted for AUT-5 WP9.
  - SEC L5: the path-based PREREG eligibility check is a guard only.
  - AUT-5a binding note: a `read_family_source` ValueError = refuse boot, never fall back to UNSET; the node re-verifies `artefact_raw` by sha on load; log resolve duration at LAUNCH (E-23).
- **A8c-R4 resolved (architect adjudication after the implementer's STOP).**
  - **Finding.** The STOP path (MINT M1/A → PROMOTE M2/B) is not legitimate:
    - an FQ artefact is complete and never composed (AUT-3 r6:85, :90);
    - a family is bound to one artefact (ARCH:366-367);
    - a new density means a new child (AUT-3 r6:85);
    - the §4.2 allowlist applies only between a child and its root.
  - **8c (blocker).** `byte_binding.verify_bound_bytes` refuses `manifest.density_artefact_sha256 != bound artefact sha` → `artefact_sha_mismatch`. It applies to every kind; sentinel roots bind the sentinel file, so the check still holds.
    - Fixtures: the replay/resolver world uses the real FQ artefact bytes at the root manifest's `density_artefact_path` (sha `9c0b…`). Child fixtures pin their own artefact sha.
    - Tests: density pin ≠ bound (root and child); repin within a family refused; `rung_recalibration` child positive control.
  - **8d obligation (store half, before any MINT writer).**
    - `ManifestFacts` gains `density_artefact_sha256`.
    - `Rule.MANIFEST_DENSITY_NOT_BOUND` on BOOTSTRAP/MINT → `artefact_sha_mismatch`.
    - `Rule.MANIFEST_BINDING_IMMUTABLE` → `manifest_sha_mismatch`.
    - `fold.py:322` becomes `setdefault`; the Rule exact-set test is updated.
    - The engine writes the family file before its MINT row.
  - **AUT-5a obligation.**
    - The node loads its artefact from the store by row sha (`artefact_store_relpath`), not from `manifest.density_artefact_*`.
    - It re-asserts equality at composition → CRITICAL `registry_boot_load_failed`.
    - The BOOTSTRAP CLI checks the manifest pin against the artefact (ARCH:260).
  - Erratum E-24.
- **B10-R5 (gate B7, 3d64e3ae).** `wal_snapshot.py` names `exec_polymarket_us.sqlite`, so the firewall classifies it as venue-touching (C5). Rule V1 then rejects the `("delete",)` journal-mode comparison at :493.
  - The firewall is correct and stays untouched. The literal is not relocated to dodge it, and the module is not made to look non-venue.
  - The module still sets the journal mode with `PRAGMA journal_mode=DELETE`.
  - It then verifies the snapshot's on-disk header: bytes 18 and 19 must both be 1, meaning not WAL format. The existing `-wal`/`-shm` absence check stays.
  - The B3 focused gate gains `tests/unit/test_polymarket_us_readonly_guard.py` and `tests/unit/test_polymarket_us_write_transport.py`.

### Post-merge rulings (seam B V-steps on the primary tree, b2c8895a)
- **V1** was done: `install -d -m 0700` of the cache dirs.
- **V2 FAILED:** `bwrap: execvp /home/jon/breezy/.venv/bin/python3: No such file or directory`.
  - The venv interpreter chain (`python` → `~/.local/share/uv/python/cpython-3.13-linux-x86_64-gnu`, a symlink, → `cpython-3.13.13-…`) and the `pyvenv.cfg` `home` both go through a symlink under home that the sandbox never recreates. Only the resolved `python_prefix` is bound.
  - The phase-2 harness never execs the production interpreter path, so no test caught it.
  - No live impact: no unit consumes the wrapper yet.
- **B11-R1.** Recreate each interpreter/`home` symlink hop under home with bwrap `--symlink` (never a bind).
  - A pure hop derivation that fails closed when a target is outside `python_prefix`, on a loop, or past 8 hops.
  - Add a phase-2 namespace test that execs the production venv interpreter through the `default_roots()` argv.
  - V2–V21 re-run after the merge.
- **B12 (security review of f91e1e1f, REQUEST_CHANGES; no escape found).** All findings are adopted.
  - **B12-R1 (M1).** In the walk, only EINVAL means "not a link". Every other errno raises `InterpreterLinkError`. A start path that vanishes while `.venv` exists also refuses.
  - **B12-R2 (M2).**
    - Compare against resolved `home` and resolved `data_root`.
    - Refuse a hop that equals `home`, or that is an ancestor of any bound root.
  - **B12-R3 (M3).** Parse `pyvenv.cfg` the way CPython does: strip, lowercase keys, last `home` wins. If `pyvenv.cfg` exists but yields no absolute home, refuse.
  - **B12-R4 (L4, L5).**
    - Build the exclusion list from `_home_rebinds` plus every `opened.*` destination.
    - Emit a LINK path only if it lies under `roots.python_prefix.parent`; refuse otherwise.
  - **B12-R5 (L6).** Derive the hops once in `_exec_wrapped` and pass them to both `argv_for` calls.
  - **B12-R6 (tests).**
    - Add an exactly-8-hops pass case.
    - Add not-emitted cases: a hop outside home, under `data_root`, and under the prefix.
    - Add `..` cases, in a target and in `home`.
    - Add bad-cfg cases: relative, duplicate, uppercase, garbage.
    - Add a non-EINVAL errno case and a symlinked home/ancestor case.
    - Assert ordering against the remount-ro entries.
    - Rename the namespace test to `test_production_roots_argv_execs_the_venv_interpreter`.
    - The end-to-end proof through the wrapper `main` is real-host V2 after merge.
  - **Accepted availability change.** `interpreter_link` refuses before preflight, even for degradable notifier rows. This is fail-closed by design, and the notifier never runs unwrapped on it.
