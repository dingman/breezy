# AUT-4: Evaluation (offline screening, forward shadow, live sequential). Plan r11

## 0. Header

| Field | Value |
|---|---|
| ID | AUT-4 |
| Title | Evaluation: the `OFFLINE_CHALLENGER` (screening, no α), `FORWARD_SHADOW` (confirmatory, α per nomination) and `LIVE_SEQUENTIAL` C4 producers; the nomination-column function (`k_life`, `alpha_k`, `n_min_eff`, `n_cap`, `nomination_feasible`); the feasibility record with the window cap; the `engine_input/v1` schema; evaluator self-monitoring |
| Round | **r11** (2026-10-03), blocker-exit and test-naming patch. r10 stays unchanged at `docs/plans/backlog/AUTONOMY_2026-10-03/AUT-4-evaluation_plan_r10.md`. This round closes the 6 items of `reviews/AUT-4-r10-merged.md` (prediction-market-reviewer 95, mle-reviewer 94; 0 CRIT/HIGH). Both reviewers verified FH1/W5, the W5 move's safety and the R-1 neutrality, and agreed I-5 = (a), ER-1 ADOPT and ER-2 ADOPT; r11 records all three. r11 measured one fact (§3.9a): on the project interpreter (Python 3.13.13), a `SystemExit(3)` raised in an `atexit` handler leaves exit code 0, and `os._exit(3)` in the same place gives 3. r11 edits are tagged **(r11, Fn)**. The **§R11 Disposition** table is appended at the end of this file. Every r6–r10 closure stands. r10 header text follows: **r10** (2026-10-03), runtime-closure and ruling patch. r9 stays unchanged at `docs/plans/backlog/AUTONOMY_2026-10-03/AUT-4-evaluation_plan_r9.md`. This round closes every item of `reviews/AUT-4-r9-merged.md` (prediction-market-reviewer 91, mle-reviewer 86; NOT READY on one HIGH): the coordinator rulings R-1, R-2 and R-3, plus FH1, FM1–FM5 and FL1. It records a third read-only measurement (§0c), the first taken after a *run* as well as after import. That measurement confirms FH1 as a certain finding: under r9's W1–W4, the golden replay loads `order_enablement`, 8 exec modules, `transport` and `write_transport` at run time, through a function-local import at `forecast_quantile_ladder/strategy.py:308`. r10 therefore adds one cut, W5 (§3.9a). ER-1 and ER-2 are restated in §10 with the ruled text. r10 edits are tagged **(r10, R-n)**, **(r10, FH1)**, **(r10, FMn)** or **(r10, FL1)**. The **§R10 Disposition** table is appended at the end of this file. Every r6–r9 closure stands, except where §R10 names a refinement. r9 header text follows: **r9** (2026-10-03), closure-decision and live-path-gate patch. r8 stays unchanged at `docs/plans/backlog/AUTONOMY_2026-10-03/AUT-4-evaluation_plan_r8.md`. This round closes BH1, BH2, BM1 and BL1 of `reviews/AUT-4-r8-merged.md` (prediction-market-reviewer 92, mle-reviewer 88; NOT READY on three HIGH). It records a second read-only measurement (§0b), in which the WP1 moves were simulated on scratch copies of HEAD. On that evidence it takes E-7b branch (b) now (N-1 declared), replaces r8's M1–M3 with the measured minimal cut set W1–W4 (§3.9a), adds the live-path gates for the two lazy package `__init__`s (§3.9b), pins a numeric private-`/tmp` cap, and sequences E-7c ahead of every AUT-4 row. r9 edits are tagged **(r9, BH1)**, **(r9, BH2)**, **(r9, BM1)** or **(r9, BL1)**. The **§R9 Disposition** table is appended at the end of this file. The r7 and r8 closures (AH1–AH5, LOW-1, LOW-2, E-7b, E-7c, the quarantine bind, the `lint-imports` gate, `--tmpfs /tmp` on every row) stand unchanged except where §R9 names a refinement. r8 header text follows: **r8** (2026-10-03), review and errata patch. r7 stays unchanged at `docs/plans/backlog/AUTONOMY_2026-10-03/AUT-4-evaluation_plan_r7.md`. This round applies AH1–AH5 and both LOWs of `reviews/AUT-4-r7-merged.md` (PM 94, MLE 93; final 93; zero CRITICAL or HIGH). It consumes errata **E-7b** (closes O-1) and **E-7c** (private `/tmp`) from `reviews/ARCH-ERRATA-rev9_2.md`, records a read-only import-closure measurement taken at planning time (§0a), and disposes everything in **§R8**. r8 edits are tagged **(r8, AHn)**, **(r8, LOW-n)**, **(r8, E-7b)** or **(r8, E-7c)**. r7 header text follows: **r7** (2026-10-03), reuse and errata patch. r6 stays unchanged at `docs/plans/backlog/AUTONOMY_2026-10-03/AUT-4-evaluation_plan_r6.md`. This round closes the four reuse conditions of the native/existing-code pressure test (`reviews/AUT-NATIVE-pressure-test-2026-10-03.md`, prediction-market-reviewer: PASS with reuse conditions; RC-1..RC-4), applies the post-READY build items of `reviews/AUT-4-r6-final.md` (errata E-7/E-8, E-7a, E-8a, E-9, E-10; the `eval_replay_path` metric-name registration consumed by AUT-6 r13 #16) and disposes all of them in **§R7**. r7 edits are tagged **(r7, RC-n)** or **(r7, E-x)**. Everything else in r6 stands. r6 header text follows: **r6** (2026-10-03), last-polish patch. r5 stays unchanged at `docs/plans/backlog/AUTONOMY_2026-10-03/AUT-4-evaluation_plan_r5.md`. This round applies items L1–L4 of `reviews/AUT-4-r5-merged.md` (prediction-market-reviewer 95 READY, mle-reviewer 93; final 93; zero CRITICAL or HIGH) and disposes them in **§R6**; everything else in r5 stands. r5 header text follows: **r5** (2026-10-03), final polish. r4 stays unchanged at `docs/plans/backlog/AUTONOMY_2026-10-03/AUT-4-evaluation_plan_r4.md`. This round applies every item K1–K10 of `reviews/AUT-4-r4-merged.md` (prediction-market-reviewer 94, mle-reviewer 91; zero CRITICAL or HIGH; both endorse I-1 and I-2) and disposes them in **§R5**. The r4 rebase (§R4) stands except where §R5 supersedes it |
| ARCH consumed | **FROZEN Rev 9.2**: `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/snapshots/ARCH_rev9_2.md`, 150 189 B, sha256 **`1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42`** (verified with `sha256sum` on 2026-10-03; equals the README Items-table freeze), **plus** `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-ERRATA-rev9_2.md` (E-1..E-10, E-7a, E-8a. E-3 touches this plan: Z labels cited here without the `R9.2-` prefix keep their pre-9.2 meaning, so "Z1" is the subject-sha binding and "Z4" the slot-anchored validity, exactly as ARCH C4 still cites them. **(r7)** E-7, E-7a, E-8a, E-9 and E-10 are consumed in §3.9a; E-1, E-2, E-4, E-5, E-6 and E-8 have no AUT-4 surface beyond what §3.9a states. **(r8)** E-7b (the venue-adapter import closure of the `eval-offline` replay children; closes O-1) and E-7c (private `/tmp` on every row) are consumed in §3.9a). No older snapshot is cited as a basis. **(r9)** E-7b is consumed through its branch (b), under the condition E-7b itself states (a WP1 measurement showing the replay needs non-exec adapter modules consumed by the native `BacktestEngine`; §0b, §3.9a). E-7c is consumed with a numeric per-row cap, which needs one wording addition (errata request ER-1, §10). **(r10, R-2, R-3)** ER-1 and ER-2 are restated in §10 with the coordinator's ruled text. ER-1 now gives the wrapper a default for rows that carry no size (R-2). ER-2 is a waiver for the eval-offline row only, with conditions (R-3) |
| Coordinator decisions | `reviews/ALPHA-decision.md` **as amended** (α per nomination; `k_life` never resets; ≤ 1 nomination per window; K_LIFETIME 4), `reviews/HOLDOUT-decision.md` (consumed through ARCH C4.1 by name), `reviews/ROLLBACK-FAILURE-decision.md` (no AUT-4 surface; an accepted LIVE FAIL feeds AUT-7 only through the engine). All binding |
| Repo HEAD read | **(r10)** `f45f5a65` re-checked: `git rev-parse HEAD` = `f45f5a6558cd6e9f78b8216634ca55d30255952c`, and `git status --porcelain src scripts tests` is empty. The §0c measurement ran on `git archive HEAD` copies under `/tmp/claude-1000/-home-jon-breezy/2a769d76-4e5c-4b60-a17d-c8cdb8a404e5/scratchpad/aut4-r10/`. Every r10 code citation was checked at that sha, with codegraph or a direct read. **(r9)** `f45f5a65` re-checked: `git rev-parse HEAD` = `f45f5a6558cd6e9f78b8216634ca55d30255952c`, and `git status --porcelain src scripts` is empty. The §0b measurement ran on `git archive HEAD` copies in the session scratchpad. Every r9 code citation was checked at that sha with codegraph or a direct read. **(r8)** `f45f5a65` (branch `feat/data-capture-and-risk`; re-checked with `git rev-parse` on 2026-10-03). Every r8 code citation was checked with codegraph at that sha, and the §0a closure measurement was taken there. r7 read the same sha; r6 read `4b8347a6` |
| Current score | 2 |
| Target | 3 |
| Upstream | ARCH-0 (Wave 0: C1–C6 types, `verdict/v1` writer and identity, C5 store with the nomination columns and `lineage_counters`, registry read API, `pins.py` ceilings, the C4.1 ruling filed); AUT-1 (C1 including `forecast_input_sha256`, `depth_ref`/`quote_ref`, `LifecycleEvent`); AUT-2 (C2 admissible rows, the 14:15Z label slot, RECONCILIATION); AUT-3 (C3 candidates at ≤ 1 MINT per lineage per day; `refit_run/v1`); AUT-5 (the engine that writes the nomination PROMOTE row and the `engine_input/v1` journal; the policy ruling and its `autonomy-policy/v1` block; `DEFAULT_RESTRICTIVE_CLASS`); AUT-6 (`deliver_with_proof`; the intraday producer that runs `eval_staleness`; the memory-sum HEALTH verdict); AUT-7 (the drill child, screened only) |
| Downstream | AUT-5 (consumes every C4 verdict; calls `compute_nomination_columns` when it writes a SHADOW→CHALLENGER PROMOTE; files the policy ruling whose AUT-4 sections are drafted in §3.10); AUT-7 (an accepted LIVE_SEQUENTIAL FAIL is a DEMOTE cause and thus a rollback input) |
| Status | PLANNING. Nothing is implemented. Every ruling text below is a DRAFT for the peer-review loop; none is decided here. **(r5)** New cross-plan requests: AUT-5 (K3 transaction call and contract test; K4 newest-per-(family, kind) consumption), AUT-3 (K8 reproducibility-rerun end ≤ 10:45Z; **(r6, L1/L2)** stated as: keep the 09:35Z start with `TimeoutStartSec` ≤ 4139 s), ARCH-0 owner review of `src/breezy/persistence/autonomy/sample_size.py` (K2). **(r7)** New: AUD-18 owner review of the behaviour-preserving delegation of `hypothesis_ledger.recompute_mde` to `sample_size.mde_one_sided` (RC-1); ~~a coordinator ruling O-1~~ **(r8, AH1) closed by E-7b**; the E-7a `AUTONOMY_BWRAP_TABLE` rows for the two AUT-4 units and the fixture unit (owner of the table as filed). **(r8)** New:
- ARCH-0 makes `src/breezy/persistence/__init__.py` lazy, or else AUT-4 takes the RC-1 fallback (AH5, §2).
- ~~The owners of three package `__init__`s on the live path review the WP1 branch-(a) moves M1–M3 (§3.9a): the adapter package, `current_rung_hold` and `ladder_ev`.~~ **(r9) Superseded** by the W1–W4 request below. M1, M2 and the `ladder_ev` request are withdrawn on measurement (§0b).
- ~~Question N-1 goes to the coordinator only if those moves are refused (§3.9a).~~ **(r9)** N-1 is declared now as the E-7b (b) named exception (§3.9a). The coordinator is asked for a ruling only under fallback F-1.

**(r9)** New:
- Owner review of the cut set W1–W4 (§3.9a):
  - the adapter-package owner reviews W1, the lazy `src/breezy/adapters/polymarket_us/__init__.py`;
  - the `current_rung_hold` owner reviews W2, the lazy `src/breezy/strategy/current_rung_hold/__init__.py`, and W3, the helper move out of `composition.py`;
  - the `forecast_quantile_ladder` owner reviews W4, two import lines in `strategy.py`.
- The `AUTONOMY_BWRAP_TABLE` and wrapper owner adds a per-row `tmpfs_size_bytes` (ER-1). Its E-7c deliverable becomes a sequenced build gate ahead of every AUT-4 row (BM1).
- The E-7b (b) named exception goes on the eval-offline row only, scoped to the 11 measured non-exec modules (§3.9a). **(r10, R-1)** It now has 8 modules.

**(r10)** New:
- The `forecast_quantile_ladder` owner also reviews W5 (§3.9a). `_d_plus_1_climate_days` and `_VENUE` move verbatim out of `forecast_quantile_ladder/composition.py` into the new `forecast_quantile_ladder/d_plus_1.py`, and the function-local import at `strategy.py:308` is re-pointed to it.
- The owner of the `scripts/analysis/nbp_shadow_parity*` scripts reviews the R-1 edit, as part of WP1 under G36: one import line in `nbp_shadow_parity_pure.py` moves into `permit_window_for_day`.
- The table and wrapper owner adopts ER-1 as ruled (R-2): a wrapper default for rows that carry no `tmpfs_size_bytes`.
- The coordinator files ER-1 and ER-2 with the ruled text (R-2, R-3). |

**Headline (read first).**
- AUT-4 can reach score 3 as *machinery* before the 2027-01-25 KILL. The proof window opens only after the §6.4 prerequisites: the C4.1 ruling (Wave 0), the FQ boundary ruling R-B `PREREG_FQ_v1`, the AUT-5 policy ruling, ARCH-0's Wave 0 surfaces, and AUT-6's memory-sum PASS. No ARCH revision is awaited: Rev 9.2 already carries every item r3 listed as P4-7..P4-15.
- If R-B is not filed by **2026-12-01**, AUT-4 is declared **score 2**, because "every live family is evaluated on pre-registered sequential tests" would be false for FQ.
- **(r4) α is charged per nomination, and today no nomination is feasible.** A nomination is the engine's SHADOW→CHALLENGER PROMOTE on an accepted OFFLINE_CHALLENGER PASS. Its FORWARD_SHADOW n_min_eff (≥ 403 independent station-days at α_1, deff 1; 605 at deff 1.5; larger at deeper k) exceeds n_cap = ⌊4 × 28 × 0.8⌋ = 89, and exceeds the 120-day ceiling (≤ 480 at uptime 1.0). So every nomination is **infeasible**: `nomination_feasible=false`, `alpha_k = 0`, `k_life` unchanged, `infeasible_nominations` incremented, the window's single slot used, and every FORWARD_SHADOW for that nominee is `INCONCLUSIVE(window_cap_below_n_min)` by construction. Verdicts still flow daily, so the machinery is exercised; **no promotable path is claimed**, consistent with `promote_enabled=false`.
- Consequently, under today's σ and X, `k_life` stays 0 and no α is spent; K_LIFETIME (≤ 4) binds only once a nomination becomes feasible. r3's "k_life reaches 6 in two windows, then every candidate is nominal" is withdrawn: ARCH has no nominal tier and refuses a nomination past K_LIFETIME.
- OFFLINE_CHALLENGER is **screening only** (no α), scored on external weather on forward days (≥ 2026-10-02) after the candidate's training end, never on the C4.1 frozen holdout.
- The only verdict that can reach a decisive terminal state before the KILL is LIVE_SEQUENTIAL on FQ under R-B. Its probability of reaching n_max = 160 is 0.67–0.89 at node uptime ≥ 70% (§6.3). At n = 160 the power is ≈ 0.69 against a +0.10 effect; the 80%-power MDE is ≈ +0.113.
- **(r4)** A LIVE_SEQUENTIAL FAIL DEMOTEs even before the policy ruling is filed, through ARCH's restrictive fallback (`no_policy_ruling` + `DEFAULT_RESTRICTIVE_CLASS`). r3's "no autonomy DEMOTE before a policy ruling" gap is closed by ARCH.
- **(r5)** Every input to `compute_nomination_columns` is a pinned policy-block value (K1); the sample-size primitives are defined once in `src/breezy/persistence/autonomy/sample_size.py` (K2); resampling seeds are derived per (subject, slot, role), so a same-slot recompute is bit-identical (K7); `EVAL_OFFLINE_TIMEOUT_START_S` = 6299 (K5).
- **(r7)** Reuse tightened: one σ-parameterised normal-approximation core (`sample_size.mde_one_sided`/`n_min_one_sided`/`power_one_sided`) is now the single definition behind both AUT-4 and the AUD-18 `hypothesis_ledger.recompute_mde`, which delegates to it bit-identically; the fill-rate bound reuses `current_rung_hold_v2._wilson_interval`; the nomination α ledger is ARCH C5's, not the hypothesis ledger's (reasons in §2); the PREREG precommit check reuses `hypothesis_register`'s freeze-commit validation and fail-closed dirty-tree check and adds only the disclosure comparison nothing in the repo performs.
- **(r7)** Both AUT-4 units run under the shared E-7a bwrap wrapper with a table row each; C5 and the production state root are read-only by mount, not by convention; the fixture path gets its own row bound only to the fixture root.
- **(r8)** E-7b closes O-1, and its branch (a) comes first. **(r9)** That remains the evaluation order. The measurement that (a) requires has now been made, and it shows (a) cannot reach zero, so (b) is taken (next bullets).
  - A read-only measurement taken at planning time (§0a) finds 33 adapter modules in the replay closure, among them `exec.client`, `http` and `websocket`, reached through 26 direct edges, not through `symbology` alone.
  - ~~Branch (a) is therefore a WP1 move set (M1–M3, §3.9a) that includes three package `__init__`s, not one shim.~~ **(r9) Superseded:** see the next bullet.
  - eval-offline is not activated until its closure tests are green.
- **(r9, BH1) E-7b branch (b) is taken now (N-1 declared).**
  - The WP1 moves were simulated on scratch copies of HEAD (§0b). Zero adapter modules is unreachable without editing a fee model or a NO-SEND file, for two reasons:
    - the native `BacktestEngine`'s fee model, `PolymarketUSFeeModel` (`runtime/backtest_harness.py:153`, mandatory under barrier F2), imports `parsing`;
    - the parity module imports `safety.PERMIT_TTL_NS` (`scripts/analysis/nbp_shadow_parity_pure.py:43`).
  - The pure permit-type seam (a) is rejected:
    - it edits the permit-minting path;
    - measured with the seam applied, the closure still holds 8 exec modules and 2 venue HTTP modules.
  - With the four cuts W1–W4, the replay closure measures 11 adapter modules, 0 exec, 0 HTTP/WS and no `order_enablement`. Those 11 modules are the named exception. **(r10)** That was measured at import time only. At run time the same four cuts load 8 exec modules and `order_enablement` (§0c), so W5 is added. Under R-1 the exception has 8 modules.
- **(r9, BH2) Live-path gates.** W1–W4 edit live-path files, so WP1 also carries the following (§3.9b):
  - sha pins on the NO-SEND and permit files;
  - a fresh-process boot smoke per live entry;
  - a windowed supervisor restart, followed by a scripted permit-line check;
  - lazy-`__getattr__` tests;
  - Arrow-registration parity;
  - a golden replay;
  - a `sys.modules` and Nautilus-config diff.

  The planning-time measurement on the node, supervisor and recorder entries found 0 identity mismatches, 0 Arrow-registration differences and 0 config-type differences.
  - Every AUT-4 row gets a private `/tmp` (E-7c). The `fs_replay` scratch written there counts against the unit's memory.
- **(r10, FH1) r9's closure was an import-time closure, and it was not clean at run time. W5 fixes that.**
  - §0c ran the golden replay on a scratch copy with W1–W4 applied: the 9 fixture-free tests of `tests/unit/test_nbp_shadow_parity_live.py`, each driving `run_live_parity` through the native `BacktestEngine`. The run added 17 adapter modules, among them the 8 exec modules, `transport`, `write_transport` and `order_enablement`.
  - The cause is `ForecastQuantileLadderStrategy._d1_candidate_ids` (`strategy.py:299-317`). It runs at `on_start` and imports `forecast_quantile_ladder.composition` function-locally (`:308`). That module imports `current_rung_hold.composition` (`forecast_quantile_ladder/composition.py:36`), which imports `order_enablement` (`:45`) and the exec client.
  - W5 moves the pure `_d_plus_1_climate_days` out of `forecast_quantile_ladder/composition.py`. With W1–W5 and R-1 applied, the replay holds 8 adapter modules after import and 11 after the run. The 3 extra modules are `safety`, `credentials` and `secure`, loaded only through the R-1 site. Exec, HTTP/WS and `order_enablement` are absent both times.
  - Every eval-offline process now installs a `sys.meta_path` blocker first. The blocker records any attempt to load an exec, `factories`, HTTP, WS, transport or `order_enablement` module, and the run fails closed on that record. It cannot rely on the exception: §0c measured that an `ImportError` raised inside `on_start` is swallowed by the strategy's L-16 handler, and the replay then returns an empty result instead of failing.
- **(r10, R-1)** `PERMIT_TTL_NS` is now imported inside `nbp_shadow_parity_pure.permit_window_for_day`, not at module level. The named exception drops `safety`, `credentials` and `secure`, leaving 8 modules. The constant is not re-declared. The replay still calls that function at run time, so the 3 modules load then. They are declared as a separate set and attributed to that one site (§3.9a; I-5 in §10).
- Evidence class for any DONE claim: **"machinery proven, edge unproven"**.

**(r9) Hard invariants (restated; binding on every WP and every delegated brief).**
- Nautilus Trader 1.231.0 is immutable. It is never modified, patched, forked, bypassed or reimplemented, and it is extended only through its native extension points.
- `allow_short` stays `False`.
- No safety, settlement or contract test is weakened or deleted to go green. New tests only add.
- No value is assigned to the operator-reserved caps (max daily budget, max per position). AUT-4 never reads or writes them.
- Live-trading enablement and the NO-SEND execution-egress firewall are never touched. The following stay byte-identical and sha-pinned (§3.9b):
  - `src/breezy/runtime/order_enablement.py`;
  - `src/breezy/adapters/polymarket_us/{safety,operator_controls,write_transport}.py`;
  - `src/breezy/adapters/polymarket_us/exec/{client,submit_chain,endpoints}.py`;
  - `tests/unit/test_execution_egress_firewall_guard.py`.
- `promote_enabled` stays `false`.
- **(r10)** The permit-minting path is unchanged. `OrderSubmissionPermit.issue`, `issue_live_trading_permit` and every caller of either stay byte-identical, and the §3.9b pins hold. R-1 reads the TTL constant and mints nothing. W5 and the import blocker touch no permit line.
- **(r10)** R-1, W5, the import blocker and every r10 test leave `allow_short`, the operator caps, live enablement and the NO-SEND firewall untouched.

**Path convention (programme rule).** Code and test paths are repo-root-relative to `/home/jon/breezy`. Runtime stores are under `~/.local/share/breezy/` with `~` = `/home/jon`; the shorthand `$STATE` below means exactly `/home/jon/.local/share/breezy`.

### 0a. (r8) Import closures and constants measured at planning time (read-only, 2026-10-03, HEAD `f45f5a65`)

**Method.**
- One fresh process per module, all with interpreter `/home/jon/breezy/.venv/bin/python`, `PYTHONPATH=/home/jon/breezy/src:/home/jon/breezy` and `PYTHONDONTWRITEBYTECODE=1`.
- The closure is the `sys.modules` delta of one `importlib.import_module`.
- A direct edge is a module-level `import` or `from` statement (outside `if TYPE_CHECKING:`) in a non-adapter `breezy` module of that closure.
- The scripts and outputs are in the session scratchpad (`aut4r8_*.py`). Nothing was installed or written in the repo.
- The adapter counts agree with AUT-6 r12 §0 (19)–(20): 33 adapter modules for `symbology` and for the `nbp_shadow_parity` imports.

| Module imported | New modules | `breezy.adapters` modules | `…polymarket_us.exec*` | Venue HTTP/WS modules | `current_rung_hold` `__init__` | Nautilus |
|---|---|---|---|---|---|---|
| `breezy.adapters.polymarket_us.symbology` | 1122 | 33 | 8 | 4 | no | yes |
| `breezy.runtime.backtest_harness` | 1154 | 33 | 8 | 4 | no | yes |
| `breezy.strategy.ladder_ev.config` | 1160 | 33 | 8 | 4 | yes | yes |
| `breezy.strategy.forecast_quantile_ladder.strategy` | 1791 | 33 | 8 | 4 | yes | yes |
| `breezy.persistence` | 812 | 0 | 0 | 0 | no | yes |
| `breezy.analysis.hypothesis_ledger` | 50 | 0 | 0 | 0 | no | **no** |
| `breezy.settlement.current_rung_hold_v2` | 24 | 0 | 0 | 0 | no | no |

- **The 8 exec modules** are `exec`, `exec.client`, `exec.endpoints`, `exec.no_side_keys`, `exec.refusals`, `exec.reports`, `exec.submit_chain` and `exec_fault`.
- **The 4 venue HTTP/WS modules** are `http`, `transport`, `websocket` and `write_transport`.
- **Direct edges into the adapters from the replay closure: 26 from `breezy` modules, plus `scripts/analysis/nbp_shadow_parity.py:55` → `symbology`.** They fall into three groups:
  - **G1, symbology and fees.**
    - `src/breezy/runtime/backtest_harness.py:153` → `fees`, `:154` → `symbology`.
    - `src/breezy/strategy/forecast_quantile_ladder/strategy.py:57` → `symbology`.
  - **G2, the `current_rung_hold` package.**
    - The replay reaches it through eager package `__init__`s: `strategy/ladder_ev/__init__.py:12` imports `.decision`, which imports `current_rung_hold.decision`. That executes `strategy/current_rung_hold/__init__.py`, which imports `.strategy` (`:30`) and `.trial_day_latch` (`:35`).
    - Edges to `exec.client`: `continuous_helpers:16`, `continuous_strategy:36`, `trial_day_latch:68`.
    - Edges to `exec`: `continuous_strategy:35`, `exit_wiring:28`.
    - Edge to `exec.no_side_keys`: `continuous_no_side:16`.
    - Further edges to `operator_controls`, `parsing`, `errors`, `symbology` and `fees`, from `continuous_no_side`, `continuous_strategy`, `composition`, `monitor_wiring`, `resting_decider` and `strategy`.
    - `runtime/order_enablement.py:48,49,53` → the adapter package, `operator_controls` and `safety`.
  - **G3, the eager adapter package `__init__`** (`src/breezy/adapters/polymarket_us/__init__.py:69-147`).
    - Importing any adapter submodule executes it.
    - It imports `http`, `websocket`, `transport`, `factories`, `data`, `signing` and `credentials`.
    - So today no adapter import, however pure the module, avoids loading the venue HTTP and WS clients.
- **`breezy.persistence`.**
  - `src/breezy/persistence/__init__.py:9-30` re-exports `breezy.persistence.catalog`.
  - `catalog.py:197-204` imports Nautilus (`Data`, `CustomData`, `ParquetDataCatalog`), `breezy.domain.*` and `persistence.filesystem_probe`.
  - The delta has 0 adapter modules and no `breezy.runtime` or `breezy.strategy` module. Its `breezy` modules are `persistence`, `persistence.catalog`, `persistence.filesystem_probe` and 11 `breezy.domain` modules.
- **z constants (for LOW-1).**
  - `NormalDist().inv_cdf(0.975)` = 1.9599639845400536, against `Z_ALPHA_TWO_SIDED_095` = 1.9599639845400545 (`src/breezy/analysis/nbp_calibration.py:288`): −4 ulp.
  - `inv_cdf(0.80)` = 0.8416212335729144, against `Z_POWER_080` = 0.8416212335729143 (`:289`): +1 ulp.
  - The sums are 2.801585218112968 and 2.801585218112969, 1 ulp apart.
- **Replay-runner state paths (for AH4).**
  - `scripts/analysis/replay_daily_runner.py:187-197` puts the runner's replay state under `_DERIVED_ROOT / "replay"`, i.e. `$STATE/derived/replay/`.
  - The runner has no oversize quarantine. Its only quarantine is the fee-void rename at `:1132-1149`.
  - Its scratch is `tempfile.mkdtemp(prefix="breezy-replay-daily-")` (`:1090-1091`), removed in a `finally` (`:1639-1642`).

### 0b. (r9, BH1) Closures re-measured with the WP1 moves simulated (read-only, 2026-10-03, HEAD `f45f5a65`)

**Method.**
- **Copies.** `git archive HEAD src scripts` was extracted into fresh directories under the session scratchpad (`aut4r9/`), plus `tests` and `pyproject.toml` for one probe.
- **Simulation.** A script (`simulate.py`, `simulate2.py`) applied the candidate moves to those copies only.
- **What was not done.** Nothing was installed, and no `uv` or `pip` was run. No file in the repo was written.
- **Interpreter.**
  - Interpreter `/home/jon/breezy/.venv/bin/python`, with `PYTHONPATH=<copy>/src:<copy>` and `PYTHONDONTWRITEBYTECODE=1`.
  - The probe asserts that `breezy.__file__` lies inside the copy, so the editable install of the primary tree is never measured by mistake.
- **Closure and direct edges.** Both are defined as in §0a: the closure is the `sys.modules` delta of one `importlib.import_module` in a fresh process.
- **Counts.**
  - r9 counts are exactly 1 lower than §0a on every shared row, because the r9 probe imports `json` and `ast` before its snapshot. Examples: `backtest_harness` 1153 against 1154, `breezy.persistence` 811 against 812, `hypothesis_ledger` 49 against 50.
  - Adapter counts agree exactly.
- **Proxies.**
  - For `fs_replay`: `scripts.analysis.nbp_shadow_parity`, which defines `run_live_parity` (:275). WP1 moves it byte-identically.
  - For its strategy: `breezy.strategy.forecast_quantile_ladder.strategy`.
  - For its engine: `breezy.runtime.backtest_harness`.
  - For eval-live: `breezy.persistence`, `breezy.analysis.hypothesis_ledger` and `breezy.settlement.current_rung_hold_v2`.
- **The W3 module in simulation.** It is a stub that carries the moved code's exact import lines, because only the import closure is measured.

**Scenarios** (the W-cuts are defined in §3.9a; "replay" is the `nbp_shadow_parity` proxy):

| Scenario | Moves applied | Replay: new modules / adapter / exec / venue HTTP-WS / `order_enablement` | FQ strategy: adapter / exec |
|---|---|---|---|
| HEAD | none | 1798 / 33 / 8 / 4 / yes | 33 / 8 |
| A | r8 M1 (symbology and its errors into `domain`) + r8 M3 (three lazy `__init__`s) | 1786 / 25 / 8 / 2 (`transport`, `write_transport`) / yes | 25 / 8 |
| B | A + the permit-type seam (a): `OrderSubmissionPermit` in a dependency-free module, importers re-pointed | 1786 / 25 / 8 / 2 / **no** | 25 / 8 |
| C | A + W3 | 1759 / 25 / 8 / 2 / no | 25 / 8 |
| D | A + W3 + W4 | 1702 / 11 / 0 / 0 / no | 0 / 0 |
| E1 | W1 + W2 + lazy `ladder_ev` + W3 + W4 (no M1) | 1700 / 11 / 0 / 0 / no | 5 / 0 |
| **E2 (chosen)** | **W1 + W2 + W3 + W4** | **1705 / 11 / 0 / 0 / no** | **5 / 0** |
| E3 | E2 without W2 | 1762 / 25 / 8 / 2 / yes | 25 / 8 |
| E4 | E2 without W3 (lazy `ladder_ev` added) | 1783 / 25 / 8 / 2 / yes | 25 / 8 |
| E5 | E2 without W1 (lazy `ladder_ev` added) | 1760 / 33 / 8 / 4 / no | 33 / 8 |

`backtest_harness` under E2: 1086 new modules, 8 adapter modules (package `__init__`s, `fees`, `parsing`, `errors`, `redaction`, `symbology`, `tape_records`), 0 exec, 0 HTTP/WS.

**Findings.**
1. **BH1 is a certain finding.**
   - `runtime/order_enablement.py:48,49,53` imports the adapter package (`write_transport`), `operator_controls` and `safety`.
   - `current_rung_hold/composition.py:45`, `continuous_strategy.py:54` and `strategy.py:119` import it for `OrderSubmissionPermit`.
   - `fees.py:44,49` imports `errors` and `parsing`.
2. **The permit-type seam does not clear exec (scenario B).**
   - With the seam, `order_enablement` leaves the closure, but exec stays at 8 and HTTP/WS at 2.
   - Cause: `composition.py:53,63,64` import `continuous_strategy`, `strategy` and `trial_day_latch`, which import `exec.client` (`continuous_strategy.py:36`, `trial_day_latch.py:68`). `exec/client.py:270` then imports `write_transport`.
3. **The replay needs neither the composition root nor the trial-day latch.**
   - It reaches `composition` only for the pure helper `bucket_station_instrument_ids`: imported at `forecast_quantile_ladder/strategy.py:65`, called at `:314`.
   - It reaches `trial_day_latch` only through `persistent_latch.py:35`. That module is imported at `forecast_quantile_ladder/strategy.py:79` solely for the annotation `SupportsQuantileLatch` (`:144`; the module has `from __future__ import annotations` at `:36`).
4. **Zero is unreachable without editing a fee model or a NO-SEND file.** With all four cuts applied, the 11 remaining modules come from three edges:
   - `backtest_harness.py:153` → `fees`. `PolymarketUSFeeModel` is the native engine's fee model, which barrier F2 makes mandatory for every venue (`tests/unit/test_polymarket_us_fee_guard.py`; adapter `__init__` docstring, `src/breezy/adapters/polymarket_us/__init__.py:40-49`). It imports `parsing` (`fees.py:49`), which imports `symbology`, `tape_records` and `errors` (`parsing.py:140-156`). `errors` imports `redaction` (`errors.py:14`).
   - `:154` → `symbology`.
   - `nbp_shadow_parity_pure.py:43` → `safety`, for the replay's nominal permit window (`:146-155`). `safety` imports `credentials` (`safety.py:126`), which brings in `secure`.
5. **Moves that buy nothing are withdrawn.**
   - M1 (moving `symbology` into `domain`): once `fees` stays, `fees` → `parsing` keeps `symbology` and `errors` in the closure, so D and E2 hold the same 11 modules.
   - A lazy `ladder_ev/__init__`: E1 and E2 hold the same 11 modules.
   - W1, W2 and W3 are each necessary (E5, E3, E4). W4 is necessary (C).
6. **eval-live proxies under E2.**
   - `breezy.persistence`: 811 modules, 0 adapter.
   - `hypothesis_ledger`: 49 modules, 0 adapter, no Nautilus.
   - `current_rung_hold_v2`: 23 modules, 0 adapter.

**Live-entry probes (E2 against HEAD).** Each probe ran in a fresh process per entry, over the 35 `STAGE0_ENTRY_MODULES` of `tests/unit/test_runtime_import_isolation.py:69-140`.
- **Imports.** All 35 entries import cleanly in both trees.
- **Exported-name identities.** Every `__all__` name of the two lazy packages was resolved eagerly and compared as `module.qualname`. There are 0 mismatches on:
  - `breezy.app.trade` (85 names);
  - `breezy.runtime.trade_supervisor`, `breezy.runtime.quote_tape_cli` and `breezy.runtime.quote_tape_ingest_cli` (61 names each).
- **Nautilus config types** (the transitive `NautilusConfig` subclass set).
  - The set is equal on the node, supervisor, recorder and preflight entries.
  - On ingest it loses 3: `PolymarketUSDataClientConfig`, `PolymarketUSExecClientConfig` and `PolymarketUSSecretsRefConfig`. `quote_tape_ingest_cli.py` names none of them.
- **`breezy*` module delta.** Node +1 (the W3 module), supervisor 0, recorder 0, ingest −33.
- **Arrow registrations** (the keys of `nautilus_trader.serialization.arrow.serializer._SCHEMAS`). They are equal on 27 of 35 entries, and every live entry is among those 27. The other 8 are offline scripts, each losing registrations of types it never names:

  | Entry | Registrations lost |
  |---|---|
  | `scripts.analysis.replay_daily_runner` | the four `tape_records` types (`QuoteTapeGap`, `DepthTruncation`, `VenueClockOffset`, `VenueSettlementSnapshot`) |
  | `scripts.analysis.nbp_learning_nightly` | the same four |
  | `scripts.analysis.nbp_market_comparison` | the same four |
  | `scripts.analysis.nbp_shadow_parity_pure` | the same four, plus `monitor_records.PositionMarkRecord` |
  | `scripts.analysis.nbp_shadow_parity` | `PositionMarkRecord` only |
  | `scripts.analysis.cli_basis_offer_gate_scan` | the three Nautilus `greeks_data` types |
  | `scripts.analysis.asos_cache_freshness_check` | the same three |
  | `scripts.analysis.structural_dead_stop` | the same three |

  - **Why nothing reads them.** A grep for each lost type name in the losing script returns 0. The two scripts that do name `tape_records` types (`cli_basis_offer_gate_scan.py:171`, `structural_dead_stop.py:67`) import them directly and lose only the Greeks types.
  - **Re-registering inside the lazy `__init__`s was rejected (simulated as E2r).** It made 11 other entries gain registrations, and it still missed every entry that no longer imports the adapter package.
- **`dir()`.**
  - At HEAD a cold import gives 96 names on the adapter package (25 submodules bound as attributes) and 41 on `current_rung_hold` (6 submodules).
  - A naive lazy `__init__` gives 76 and 39, which is why §3.9b adds the `__dir__` and submodule rules.
  - `hasattr(pkg, "issue_live_trading_permit")` is `False` in both trees. `from pkg import *` binds 61 and 24 names in both.
  - One function-local package import exists: `strategy/current_rung_hold/set_family_halt_cli.py:323`, `from breezy.adapters.polymarket_us import factories`.
- **bwrap (for BL1).** Host bwrap 0.11.1 accepts `--size BYTES` before `--tmpfs`. A 2 MB write into a 1 MiB `/tmp` fails with `ENOSPC`.

**Scripts and outputs:** `aut4r9/{measure,simulate,simulate2,entry_probe,cfg_probe}.py`, `*.json` and `entries_*.jsonl` in the session scratchpad.

### 0c. (r10, FH1, R-1) Import-time and run-time closures re-measured with W1–W5 and R-1 simulated (read-only, 2026-10-03, HEAD `f45f5a65`)

**Method.**
- **Copies.** `git archive HEAD src scripts tests pyproject.toml` was extracted twice under `/tmp/claude-1000/-home-jon-breezy/2a769d76-4e5c-4b60-a17d-c8cdb8a404e5/scratchpad/aut4-r10/`: `base/` (the HEAD control) and `r10/`. `apply_r10.py` applied the cuts to `r10/` only:
  - W1 and W2 with r9's `lazify_lib.py`;
  - W3 as a real verbatim move, with the four definitions cut out by their AST line spans (r9 used a stub);
  - W4, W5 and R-1 exactly as §3.9a states them.

  `ruff check --select F,I` is clean on every edited file after an isort fix.
- **Interpreter.** `/home/jon/breezy/.venv/bin/python`, with `PYTHONPATH=<copy>/src:<copy>` and `PYTHONDONTWRITEBYTECODE=1`. Every probe asserts that `breezy.__file__` lies inside the copy.
- **What was not done.** No `uv` or `pip` was run, and nothing in the repo was written.
- **Import time.** r9's `measure.py`, unchanged.
- **Run time.** `runtime_probe.py`:
  - imports `tests.unit.test_nbp_shadow_parity_live` and snapshots `sys.modules`;
  - runs that module's 9 fixture-free tests, each of which drives `run_live_parity` through the native `BacktestEngine`;
  - snapshots `sys.modules` again.

  It omits `test_harness_slippage_equals_the_deployed_composition_floor`, which imports the deployed composition on purpose. An optional mode installs a `sys.meta_path` blocker for the FH1 list.
- **Attribution.** `who.py` records the import stack at the first load of a named module.
- **Runner.** `runner_probe.py` imports `replay_daily_runner`, then the targets of its three function-local imports (`:1974`, `:1842`, `:1679`).

**Import time** (new modules / adapter / exec / venue HTTP-WS / `order_enablement`):

| Module | HEAD | r10 (W1–W5 + R-1) |
|---|---|---|
| `scripts.analysis.nbp_shadow_parity` (replay proxy) | 1798 / 33 / 8 / 4 / yes | **1701 / 8 / 0 / 0 / no** |
| `scripts.analysis.nbp_shadow_parity_pure` | 1793 / 33 / 8 / 4 / yes | 1647 / 5 / 0 / 0 / no |
| `breezy.runtime.backtest_harness` | 1153 / 33 / 8 / 4 / no | 1086 / 8 / 0 / 0 / no |
| `breezy.strategy.forecast_quantile_ladder.strategy` | 1790 / 33 / 8 / 4 / yes | 1643 / 5 / 0 / 0 / no |
| `scripts.analysis.replay_daily_runner` | 1162 / 33 / 8 / 4 / yes | 1035 / 0 / 0 / 0 / no |

The 8 replay modules under r10 are `breezy.adapters`, `breezy.adapters.polymarket_us`, `fees`, `parsing`, `errors`, `redaction`, `symbology` and `tape_records`.

**Run time** (the 9 golden-replay tests; the modules the run adds on top of the import-time closure):

| Tree | Blocker | Tests | Adapter modules added by the run | exec | HTTP/WS | `order_enablement` |
|---|---|---|---|---|---|---|
| HEAD | off | 9 pass | 0 (all 33 already loaded at import) | (at import) | (at import) | loaded at import |
| W1–W4 + R-1 (r9's cut set) | off | 9 pass | **17**: `account_activity`, `credentials`, the 8 exec modules, `leg_prices`, `operator_controls`, `safety`, `secure`, `signing`, `transport`, `write_transport` | 8 | 2 | **loaded** |
| W1–W4 + R-1 | on | **0 of 9 pass**: each fails on `IndexError` (an empty decision tuple), not on `ImportError`. The blocker recorded `order_enablement` | 3 | 0 | 0 | blocked |
| **W1–W5 + R-1 (r10)** | off | 9 pass | **3**: `safety`, `credentials`, `secure` | 0 | 0 | absent |
| W1–W5 + R-1 | on | 9 pass; the blocker records nothing | 3 (the same) | 0 | 0 | absent |

**Findings.**
1. **FH1 is a certain finding.** `who.py` gives this stack:
   - `run_live_parity` → `engine.run()`;
   - → `strategy.py:282` `_subscribe_ids` → `:332` `_d1_candidate_ids`;
   - → `:308`, the function-local `from breezy.strategy.forecast_quantile_ladder.composition import _d_plus_1_climate_days`;
   - → `forecast_quantile_ladder/composition.py:36` → `current_rung_hold/composition.py`;
   - → `order_enablement` (`:45` at HEAD) → `exec.client`.

   r9's §0b E2 row was an import-time measurement, and its "0 exec" held only at import.
2. **A blocker that relies on its exception does not fail closed.** `_subscribe_ids` is wrapped in `except Exception` (L-16, `strategy.py:280-288`). The blocked import therefore becomes a logged error, and the replay returns an empty result. So the blocker must record each attempt, and the entry must fail on that record (§3.9a).
3. **R-1 removes `safety`, `credentials` and `secure` from the import-time closure (8 modules, not 11), but not from the run-time closure.**
   - `run_live_parity` checks the permit stub before `engine.run()`: `nbp_shadow_parity.py:378` → `:188` → `:183` → `nbp_shadow_parity_pure.py:196` → the R-1 import.
   - `PERMIT_TTL_NS` is defined only in `safety.py:172`. That file is sha-pinned, and R-1 forbids re-declaring the constant.
   - So this residual cannot be removed under the rulings. It is stated as I-5 (§10).
4. **W5 is necessary and sufficient for the run-time result.** Without it, the run adds 17 adapter modules. With it, the run adds 3, all of them attributed to the R-1 site.
5. **`replay_daily_runner`.**
   - It has 0 adapter modules at import (33 at HEAD).
   - When it runs, its function-local imports add 15 more: `fees` (`:1974`, in `main`) and `scripts/venue/fee_drift_evidence_pull.py` (`:1679`). The latter imports `provider`, `symbology`, `transport` and `current_rung_hold.fee_drift_probe`, so `http` and `transport` are among the 15. No exec module and no `order_enablement` is loaded.
   - The runner runs under `breezy-replay-daily` and never inside an AUT-4 row. eval-offline never imports or spawns it (test in §3.9a). Its child drivers (`current_rung_hold_paper_replay.py`, `:820`) are CRH replays outside AUT-4's sandbox.
6. **Live entries under r10** (one fresh process each).
   - The `breezy*` module delta is: node +{`instrument_buckets`, `d_plus_1`}; supervisor, recorder, preflight and exec-store path 0; ingest −33.
   - Arrow registrations are equal on all six entries.
7. **FM2: the import delta of a real W3 move.**
   - Ruff F401 forces exactly 7 imported names out of `composition.py`: `VenuePayloadError`, `instrument_id_to_slug`, `leg_of`, `parse_weather_slug`, `Measure`, `WeatherFactsUnavailableError` and `read_weather_bucket_facts`.
   - It allows only 2 of the 4 moved names back: `InstrumentStationMismatchError` (in `__all__`) and `_bucket_station_instrument_ids` (called by `resolve_station_instrument_ids` and the builder).
   - Importing `bucket_station_instrument_ids` or `_facts_from_instrument` back raises F401; this was measured. r9's "composition imports all four back" is withdrawn.
   - W5's delta: `Iterable` and `local_standard_date` go out (F401), and `_d_plus_1_climate_days` and `_VENUE` come back in.
8. **FM4: cold imports.** All 65 modules import cleanly as the first import of a fresh process: the 33 under `breezy.adapters.polymarket_us`, the 31 under `current_rung_hold` (`instrument_buckets` included) and `d_plus_1`.
9. **Tests on the copy.** These modules were run under `scripts/ci/run_tests_no_egress.sh`, with `BREEZY_PYTHON` set:
   - `test_nbp_shadow_parity_{pure,live,no_side_synthetic,contract,load}.py`;
   - `test_d1_cache_union.py` and `test_sl13c_d_plus_1_resolution.py`;
   - `test_current_rung_hold_composition.py`;
   - `test_polymarket_us_package_exports.py` and `test_nbp_market_comparison.py`.

   Both `base/` and `r10/` gave 143 passed and 4 failed, with the same 4 failures: each is a `FileNotFoundError` on `deploy/families/*.json`, which the archive did not include. So the cuts change no outcome in these modules.
10. **FM5: the real tape slice exists.** The SFO 2026-09-01 slice is in the quote-tape catalog at `/home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us/data/order_book_depths/tc-temp-sfohigh-2026-09-01-*` (6 instruments, 1.5 MB on disk).

**Scripts and outputs:** `aut4-r10/{apply_r10,runtime_probe,who,runner_probe}.py`, plus `imp_*.json`, `rt2_*.json`, `runner_*.json`, `cold_r10.txt` and `gate_{base,r10}.txt`, all in the session scratchpad.

---

## 1. Goal state

**README AUT-4 score-3 criterion (verbatim).**
> - Every candidate from AUT-3 is evaluated automatically against the current champion on pre-registered, cost-aware metrics: out-of-sample Brier/CRPS, traded-rung calibration, and EV net of fees and slippage.
> - Every live family is evaluated daily on AUT-2 labels with the pre-registered sequential tests.
> - Every result is a machine-readable, schema-versioned verdict that AUT-5 consumes.
> - Every verdict states its own power or `n_min` and its time to verdict.
>
> **Live proof:** 7 consecutive days of automatic offline and live verdicts for every live family and every new candidate, each consumed by the AUT-5 policy engine as its input record.

The plan also meets README "Scale" criteria (a)–(f) and the ARCH §5.3 window rule:
- a day counts only if it has ≥ 1 real fill or a tagged canary fill;
- a window needs ≥ 5 real fills;
- canary and drill fills never count toward any n, look or the KILL clock.

**ARCH Rev 9.2 §10 obligations for AUT-4 (verbatim).**
> the replay-sufficiency check that admits forward-shadow tape days; station-day clustering; the measured qualifying station-days per day; the feasibility record (`n_min`, MDE at α_K, `eta_date`) handed to the policy ruling; lifetime nomination and α accounting (`k_life`, `alpha_k`, `n_min_eff`, `n_cap`, the window-cap rule, `BOOTSTRAP_B_MAX`; C4); the `engine_input/v1` schema and contract test (P4-9); `verdict_id` without `produced_at_ns` (P4-11); the two ruling-sha fields (P4-10) and the five `assumptions` tags (P4-12); the calibration non-inferiority margin and measured false-fail rate (P4-6); the FQ boundary ruling draft (P4-2); the slippage source and its `assumptions` tag; the live-sequential producer over admissible labels; `TimeoutStartSec` on its oneshots; the relative calibration test and `MIN_CALIBRATION_BUCKETS` (V16); the nomination columns (V4).

Also absorbed from ARCH Rev 9.2: §4.5 Z4 (`MAX_VERDICT_VALIDITY_H` ≤ 26), W1 (ATTEST cadence invariant), W7 (`forward_window_days` 28–120, tumbling), the K_LIFETIME / per-window / mint-rate / `BOOTSTRAP_B_MAX` / `MIN_CALIBRATION_BUCKETS` ceilings; C4.1; §5.2 locks, launch-window rule and memory (14G); §5.3 evidence rules.

| Obligation | Section / WP |
|---|---|
| Replay sufficiency | §3.4, WP3 |
| Station-day clustering | §3.2, WP2 |
| Measured qualifying rate | §6.3, WP0 |
| Feasibility record (`n_min`, MDE at α_K, `eta_date`, `n_cap`) | §3.8, WP7b |
| Nomination and α accounting (`k_life`, `alpha_k`, `n_min_eff`, `n_cap`, `nomination_feasible`, window cap, `BOOTSTRAP_B_MAX`) | §3.5, §3.2, WP5 |
| `engine_input/v1` schema and contract test | §3.13, WP8 |
| `verdict_id` without `produced_at_ns` | §3.1, WP2 |
| Two ruling-sha fields; five `assumptions` tags | §3.1, §3.1a, WP2/WP4 |
| Calibration NI margin, measured false-fail rate, `MIN_CALIBRATION_BUCKETS` | §3.10 R-C, WP0, WP2 |
| FQ boundary ruling draft | §3.10 R-B, WP7a |
| Slippage source and tag | §3.7, WP6 |
| Live-sequential producer over admissible labels | §3.6, WP4 |
| `TimeoutStartSec` on its oneshots | §3.9, WP4/WP6 |
| Nomination columns (V4) | §3.5, WP5 |

---

## 2. L-1 null hypothesis and reuse

The null hypothesis is that Nautilus or existing Breezy already provides each need. Rows unchanged from r3 are listed briefly; rows changed in r4 are marked **(r4)**.

| Need | Checked | Verdict |
|---|---|---|
| Statistics over shadow decisions (Brier, permutation, α ledger) | `.venv/lib/python3.13/site-packages/nautilus_trader/analysis/analyzer.py:38` `PortfolioAnalyzer`: realised-PnL statistics over *filled* positions. Nothing native does Brier, cluster permutation, LD-OBF or α spending | **The gap is real** for the statistics |
| Forward-shadow replay | `scripts/analysis/nbp_shadow_parity.py:275` `run_live_parity` (native `BacktestEngine` via `BreezyBacktestConfig`, `submit_veto` always refusing, Depth10) — re-verified by codegraph at `4b8347a6` | **Reuse.** Move it (WP1) |
| Tape read | Native `ParquetDataCatalog` (`scripts/analysis/nbp_shadow_parity.py:512`) | **Reuse** |
| Sequential looks and boundaries | `scripts/analysis/family_tally_v2.py:625` `run_sequential_looks` (codegraph-verified); `scripts/analysis/crh_group_sequential_boundaries.py:243`; `scripts/analysis/aud07_live_rule_crossing_sim.py:158,210`; `src/breezy/settlement/current_rung_hold_v2.py:296,346,365,433,470`; `src/breezy/persistence/gs_boundary_artefact.py:219` | **Reuse**, moved byte-identically (G36) |
| Brier, reliability, calibration leg, cluster bootstrap | `scripts/analysis/forecast_conditional_scoring.py:110,139,237,267,278,303,392,428` (`evaluate_calibration_leg` at `:392`, codegraph-verified); `src/breezy/settlement/roi_bound.py:93` `B_RESAMPLES`, `:97` `SEED` | **Reuse.** R-C reuses the reliability binning (`:303`) and the pinned seed |
| Market baseline, look-ahead guard | `scripts/analysis/wp7b_market_as_forecaster.py:169,232,372,475,707` | **Reuse**, moved (G36) |
| Replay sufficiency | `src/breezy/analysis/replay_sufficiency.py:651,694,207` | **Reuse**, plus a kind-keyed FQ window |
| Forecast vintage at decision | `src/breezy/strategy/ladder_ev/forecast_state.py:179-221,306-321`; `src/breezy/persistence/nbp_derived_store.py:142-153,196-243` | **Reuse** |
| Per-child timeout, peak RSS, remaining-budget launch | `scripts/analysis/replay_daily_runner.py:1014-1085` `_run_subprocess_with_rss`; `:1395-1484`; `:1818-1819`; `deploy/systemd/replay-daily-run.sh:48-50` | **Reuse the pattern** in `src/breezy/analysis/autonomy/subprocess_rss.py` and `budget.py` |
| Oneshot runtime bound | ARCH G29/G32; host systemd 259 `man systemd.service`; `deploy/systemd/breezy-replay-daily.service:62` `TimeoutStartSec=1800` | **Reuse `TimeoutStartSec`**; never `RuntimeMaxSec` |
| Holdout split and single-look marker | `src/breezy/analysis/nbp_calibration.py:273-278` `DEFAULT_SPLITS` (no holdout end, G37); `:353` `open_holdout` (codegraph-verified) | **Consume C4.1 by name.** AUT-4 never calls `open_holdout`; AUT-3 owns the `holdout_end_exclusive` widening |
| Slippage floor | `docs/evidence/RULING_AUD-12a_slippage_allowance_2026-09-27.md` (0.01) | **Reuse** as the floor (R-E) |
| Live IOC fill outcome | C1 `TrySubmit` + `LifecycleEvent` (production); exec store `retirement_reason` for the WP0 baseline only | AUT-4 never imports the exec store |
| **(r4)** Nomination bookkeeping | ARCH C5: the PROMOTE row's nomination columns (`k_life`, `alpha_k`, `n_min_eff`, `n_cap`, `nomination_feasible`), `lineage_counters.nominations`/`infeasible_nominations`/`alpha_spent`, the store's K_LIFETIME and distinct-k checks | **Consume.** AUT-4 supplies only the pure arithmetic that fills the columns (§3.5); it keeps no ledger of its own. r3's flock-serialised `assign_k_life` is deleted |
| **(r4)** Verdict writer, identity, registry reader, `pins.py`, engine input journal writer | ARCH-0 `src/breezy/persistence/autonomy/` (C4 identity excludes `produced_at_ns`); AUT-5 engine writes `engine_input/v1` | **Consume.** AUT-4 writes no new store; it owns the journal *schema and contract test* only |
| Run wall time and peak RSS | `resource.getrusage`; cgroup v2 `memory.peak`; systemd `ExecStopPost=` with `$SERVICE_RESULT`/`$EXIT_STATUS` | **Reuse**; only the small run-record writer is new (§3.11) |
| **(r7, RC-1)** One-sided normal-approximation MDE, power and `n_min` | `src/breezy/analysis/hypothesis_ledger.py:861` `recompute_mde` (`(z(1−α)+z(POWER))·√VARIANCE_BOUND/√n`, stdlib `NormalDist`, `POWER` :190 = 0.80, `VARIANCE_BOUND` :194 = 0.25, 15 callers in that module, tests in `tests/unit/test_hypothesis_ledger.py`, `test_hypothesis_triage.py`, `test_hypothesis_register.py`); `src/breezy/analysis/nbp_calibration.py:309` `compute_n_min` (the same inverse at a pinned two-sided 0.05, with the `N_MIN_CEILING` feasibility status of ruling S12 A-3) | **Reuse by extraction (see below).** The formula is lifted once, σ-parameterised, into `sample_size`; `recompute_mde` delegates to it with σ = √`VARIANCE_BOUND` = 0.5, bit-identically. `compute_n_min` is not edited; an equivalence test pins it to `n_min_one_sided(σ, x, 0.025)` |
| **(r7, RC-2)** Wilson score bound for `p_fill_LB` | `src/breezy/settlement/current_rung_hold_v2.py:370` `_wilson_interval(hit_count, sample_count, *, z)` (two-sided, clamped, equivalence-asserted against `scripts/analysis/archive_correction_probe.py:352` on 200 random pairs in `tests/unit/test_current_rung_hold_v2_strata.py`); `src/breezy/strategy/ladder_ev/density_table.py:152` `_wilson_lower` (the same formula, lower bound only) | **Reuse `current_rung_hold_v2._wilson_interval`.** No new Wilson. Already in `src/`, so nothing is promoted |
| **(r7, RC-3)** Nomination α ledger | `hypothesis_ledger.alpha_remaining` (:825) and `is_variant_eligible` (:839) | **Do not serve; not reused as code** (reasons below). The ledger is ARCH C5's `lineage_counters` plus the PROMOTE row columns (row above); AUT-4 keeps only the arithmetic |
| **(r7, RC-4)** PREREG precommit and disclosure | `scripts/analysis/hypothesis_register.py:456` `_git_tree_is_dirty` (fail-closed `git status --porcelain`), its 40-hex `--freeze-commit` validator `_FREEZE_COMMIT_RE` (:240), `HypothesisRecord.freeze_commit` (`hypothesis_ledger.py:510`); `src/breezy/persistence/gs_boundary_artefact.py:219` `load_boundary_artefact(path, *, expected_sha256)` (sha-pinned LD-OBF boundary artefact with reference-row replay); `scripts/analysis/family_tally_v2.py:1005` `_mixed_side_disclosure_line` (a report line, not a precommit check). A repo-wide search (`/usr/bin/grep -rn "st_birthtime\|statx\|pre_commit_pnl\|committer"` over `src/` and `scripts/`) finds no tool that lists artefacts born before a commit and requires their disclosure | **Reuse the freeze-commit and dirty-tree checks and the boundary-artefact loader; build only the disclosure comparison** (§3.10 R-B, WP7a) |
| **(r9, BH2)** Fresh-process per-entry import smoke; Arrow-registration reachability | `tests/unit/test_runtime_import_isolation.py:69-140` `STAGE0_ENTRY_MODULES` (35 entries, kept complete by the meta-test `test_entry_module_list_covers_every_entry_point`, `:218`); T9 `test_entry_module_imports_cleanly` (`:464-474`), one `subprocess.run([sys.executable, "-c", ...])` per entry | **Reuse.** The §3.9b boot smoke, Arrow parity and module diff import this tuple and use the T9 subprocess shape. Nothing is copied |
| **(r9, BH2)** Byte-identity pin of a NO-SEND file | `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py:22-36,114-121`: `hashlib.sha256(path.read_bytes()).hexdigest()` compared with a module constant, with a "re-verify with a real reviewer before ever updating this pin" message (`_EXEC_CLIENT_SHA256`, `76784ce8…`) | **Reuse the pattern** for the §3.9b pins |
| **(r9, BH2)** Permit-line parsing | `src/breezy/runtime/trade_supervisor_core.py:94` `PERMIT_ISSUED_MARKER`, `:95` `PERMIT_NOT_ISSUED_MARKER`, `:155` `PERMIT_NOT_REQUESTED_MARKER`, `:700` `parse_permit_expiry_ns`, `:709` `permit_expiry_valid`; `src/breezy/runtime/trade_supervisor.py:787-798` (node log name and its regex), `:814` `find_adopted_node_log`, `:2479` (log dir `$STATE/logs`) | **Reuse.** The §3.9b check script adds only file selection and exit codes |
| **(r10, FH1)** A run-time import blocker | `tests/unit/test_runtime_import_isolation.py:255-277` `_FINDER_PREAMBLE`: an `importlib.abc.MetaPathFinder` that appends each blocked name to a class-level `blocked` list, raises `ImportError`, and carries a positive control. No `meta_path` finder exists in `src/` or `scripts/` (searched) | **Reuse the shape** (record, raise, positive control) in `src/breezy/analysis/autonomy/import_blocker.py`. What is new is the fail-closed exit on a non-empty record (§3.9a), because §0c measured that the raise alone is swallowed |
| **(r9, BH1)** A lazy package `__init__` | `src/breezy/runtime/__init__.py:15-25`: a PEP 562 facade was *deleted*, not made lazy, because it had zero consumers | **Not the precedent here.** The adapter and `current_rung_hold` `__init__`s have consumers (61 and 24 exported names; `tests/unit/test_polymarket_us_package_exports.py`), so they are made lazy with identical objects, not emptied |

**(r7) Reuse decisions in detail.**

- **RC-1, `recompute_mde` parameterised by σ.** The engine calls `compute_nomination_columns`, which needs `n_min_one_sided`, and the engine must not import `breezy.analysis` (G15; `pyproject.toml` contract "The live trading path never imports the offline analysis layer" lists `breezy.persistence`). So the shared definition cannot live in `hypothesis_ledger`; it must live at or below `breezy.persistence`. The import the other way is legal: the layers contract puts `analysis` above `persistence`, and the two AUD-18 D6(i) contracts on `hypothesis_ledger` forbid only `runtime`, `adapters` and `strategy` (the module already imports `breezy.settlement.current_rung_hold_v2`, `hypothesis_ledger.py:48`). Therefore:
  - `src/breezy/persistence/autonomy/sample_size.py` defines `mde_one_sided(sigma, n, alpha, power=0.80)` as `float(z(1−alpha) + z(power)) * float(sigma) / (float(n) ** 0.5)`, the exact operation order of `recompute_mde` (:870-874), refusing `n ≤ 0` or `sigma ≤ 0`; `n_min_one_sided(sigma, mde, alpha, power=0.80) = ⌈(float(z(1−alpha)+z(power))·sigma/mde)²⌉` (its inverse); `power_one_sided(sigma, n, alpha, delta) = Φ(delta·√n/sigma − z(1−alpha))`. One private `_z_sum(alpha, power)` feeds all three.
  - `hypothesis_ledger.recompute_mde` keeps its signature, keyword names and docstring formula.
    - **(r8, AH2)** It also keeps its own guard, `if n_station_days <= 0: raise ValueError("recompute_mde is undefined for n_station_days <= 0")` (`hypothesis_ledger.py:868-869`), word for word, ahead of the delegation. Its body is therefore that guard followed by `return mde_one_sided(float(VARIANCE_BOUND ** 0.5), n_station_days, per_variant_alpha, POWER)`.
    - Callers see exactly today's error text. `sample_size`'s own `n ≤ 0` refusal, which has different wording, cannot be reached through `recompute_mde`. Test `test_recompute_mde_nonpositive_n_message_pinned` (WP2) pins the message.
    - √0.25 = 0.5 exactly, so every result is bit-identical. Its 15 in-module callers and the three test modules are untouched.
    - The module docstring's "one reused import from below `analysis`" sentence gains `sample_size`.
  - `eval_stats` imports `mde_one_sided` and `power_one_sided` from `sample_size` and defines neither.
  - `nbp_calibration.compute_n_min` is **not** edited (it is a ruling-S12 gate with its own pinned literals and status); `test_n_min_one_sided_matches_nbp_compute_n_min_at_alpha_0_025` pins the agreement instead. **(r8, LOW-1)** That test is a grid sweep, not a point check, because the pinned literals and `NormalDist` differ by 1 ulp in the z-sum (§0a), so a `ceil` boundary flip is possible. How the test handles it is in WP2. AUT-4 never consumes `compute_n_min`, so a flip changes no AUT-4 number.
  - **Fallback if the AUD-18 owner refuses the edit:** `recompute_mde` stays as it is, and `test_recompute_mde_equals_sample_size_mde_at_sigma_half` asserts bit-equality over the same grid (the `current_rung_hold_v2._wilson_interval` precedent: restated, equivalence-asserted). The plan does not depend on which branch is taken.
  - **(r8, AH5) The real import closure of `sample_size`.**
    - Importing `breezy.persistence.autonomy.sample_size` first executes `src/breezy/persistence/__init__.py`. That file re-exports `breezy.persistence.catalog`, which imports Nautilus, `breezy.domain.*` and `filesystem_probe` (§0a).
    - Measured: `import breezy.persistence` adds 812 modules, Nautilus among them, while `hypothesis_ledger` today adds 50 and no Nautilus. r7's claim that `hypothesis_ledger` "gains only `sample_size`" was therefore false: the delegation as r7 wrote it would pull Nautilus and pyarrow into AUD-18's pure core.
    - It breaks no import contract. The closure has 0 adapter modules and no `breezy.runtime` or `breezy.strategy` module, so both AUD-18 D6(i) contracts (`allow_indirect_imports = false`, `pyproject.toml:177-208`), the layers contract and the "live path never imports analysis" contract stay kept. It is, however, weight nobody asked for. The rule:
      - **Primary.** AUT-4 asks ARCH-0 to keep `src/breezy/persistence/__init__.py` lazy: a PEP 562 module `__getattr__` imports `catalog` on first attribute access, `__all__` is unchanged, and every `from breezy.persistence import X` returns the identical object. `src/breezy/persistence/autonomy/__init__.py` stays import-light as before. With that change, `hypothesis_ledger`'s closure gains exactly `breezy.persistence`, `breezy.persistence.autonomy` and `breezy.persistence.autonomy.sample_size`, and no `nautilus_trader` module.
      - **If ARCH-0 declines,** AUT-4 takes the RC-1 fallback above: `recompute_mde` is not edited, and its closure stays at today's 50 modules. The engine, `eval_stats`, `nomination` and both units still import `sample_size` and carry the Nautilus closure. They already carry it for other reasons (the engine lives in `breezy.persistence`; eval-offline runs the native `BacktestEngine`), and it adds 0 adapter modules.
    - **Two gates, two proofs.** `lint-imports` is static and counts function-local imports (AUT-6 r12 §0 (18)), so it proves the contracts but not the runtime closure. The fresh-process test proves the runtime closure. Both are WP2 GREEN gates.
- **RC-2, the Wilson helper.** `fill_model.py` imports `from breezy.settlement.current_rung_hold_v2 import _wilson_interval as wilson_interval` (private-name imports have repo precedent, e.g. `monitor_evidence.py:51`) and uses its lower element with `z = NormalDist().inv_cdf(1 − α_k/3)`, which is the one-sided (1 − α_k/3) Wilson lower bound. It is chosen over `density_table._wilson_lower` because it sits in the `settlement` layer (pure, below `persistence`, no strategy or Nautilus closure, which matters for the E-7a import closure of a wrapped unit), and because it is already equivalence-tested against the repo's original Wilson. `current_rung_hold_v2.py` is not edited (it is PREREG v2 settlement code; `tests/unit/test_family_tally_v2.py:1971` scopes its edits), so no public alias is added. Its `(0.0, 0.0)` return at `n = 0` is unreachable because (b) refuses below `N_IOC_MIN` = 30.
- **RC-3, why `alpha_remaining`/`is_variant_eligible` do not serve the nomination ledger.**
  1. *Different allocation rule.* `alpha_remaining` returns `per_variant_alpha − Σ alpha_spent_cumulative` for one `(hypothesis_id, variant_id)`, where `per_variant_alpha = programme_alpha / MAX_HYPOTHESES / k_variants` is a Bonferroni split fixed at registration (`register_hypothesis`, :1118-1119). ARCH C4 charges α geometrically per **feasible nomination**, `α_k = α_total·2^−k_life`, with `k_life` unbounded in advance (≤ K_LIFETIME) and never reset; the number of nominations is not known at registration, which is exactly why a geometric rule is used. No `HypothesisRecord` can express it.
  2. *Different store and owner.* ARCH C5 makes `lineage_counters.nominations`/`infeasible_nominations`/`alpha_spent` and the PROMOTE row columns the ledger, written by the single engine writer under `engine.lock` with the store's K_LIFETIME and distinct-k checks. `hypothesis_ledger.jsonl` is AUD-18's programme register under `<derived_root>/hypothesis/`.
  3. *Import law.* The engine (in `breezy.persistence`) may not import `breezy.analysis.hypothesis_ledger` (the "live path never imports analysis" contract above).
  4. *Look policy.* `register_hypothesis` refuses any `look_policy` other than `SINGLE_LOOK` (:1075-1079, "LD_OBF is WITHDRAWN under this programme's alpha budget"); R-B's LIVE_SEQUENTIAL is LD-OBF under its own family PREREG (ARCH C4 `family_prereg_sha256`), so AUT-4's live α is outside that register by construction.
  - *Where they can be reused:* their rules, not their code. `is_variant_eligible`'s single-look invariant is AUT-4's FORWARD_SHADOW single-look rule (§3.1), enforced from the verdict store and the row's columns; `alpha_remaining`'s no-cross-variant-pooling rule is AUT-4's per-lineage budget (no pooling across lineages, ARCH C4). The test shapes are mirrored: `test_alpha_never_pooled_across_lineages` (after `test_alpha_remaining_has_no_cross_variant_pooling`) and `test_nominee_single_look_never_reopened` (after `is_variant_eligible`'s already-looked rule). The two ledgers are disjoint: AUT-4 never imports `hypothesis_ledger` or `hypothesis_register` and never writes `hypothesis_ledger.jsonl` (`test_aut4_never_imports_or_writes_hypothesis_ledger`).
- **RC-4, the PREREG precommit tooling.** Nothing existing compares artefact birth times with a design commit and demands disclosure, so `scripts/analysis/prereg_precommit_check.py` remains, but it is reduced to that comparison. It imports `_git_tree_is_dirty` from `scripts/analysis/hypothesis_register.py` (script-to-script reuse has precedent: `k1_cheap_open_settlement.py` reuses `settlement_alignment_study.wilson_lower_bound`) and refuses on a dirty tree; it validates the design commit by importing the module constant `_FREEZE_COMMIT_RE` (`hypothesis_register.py:240`, `^[0-9a-f]{40}$`), the same rule `--freeze-commit` uses, so `hypothesis_register.py` is not edited; and the R-B boundary is committed as a `gs_boundary_artefact` file, loaded with `load_boundary_artefact(path, expected_sha256=…)`, so R-B adds no boundary-file format of its own.

---

## 3. Design

### 3.1 Contracts; rules common to every producer

**Contracts.**
- **Consumes:**
  - C1: `DecisionRecord` Take/TrySubmit (`eval_ns`, `depth_ref` or `quote_ref`, `p_hat`, `forecast_input_sha256`), `LifecycleEvent`, `drill`, `source`.
  - C2: admissible `window_complete` rows with `p_source=c1_decision` only (a null `decision_id` row is never admissible; `canary`, `drill`, `voided_pair` rows never count).
  - C3: `forward_eval_start_utc`, `train_end_exclusive_utc`, `leakage_assertions` (incl. `no_sealed_holdout_rows_in_train`).
  - C5, read-only (`mode=ro` with `PRAGMA query_only=ON`, **(r7, E-7 rule 3)**; the C5 registry is a rollback-journal store, so E-7a rule 3 does not apply to it): the fold at `now`; the nominee's SHADOW→CHALLENGER PROMOTE row and its nomination columns; `lineage_counters` (`nominations`, `infeasible_nominations`, `alpha_spent`, `holdout_opens`); the bound artefact sha.
  - C6: the `Evaluator` slot (`offline`, `forward_shadow`, `live`).
- **Provides:**
  - C4 kinds `OFFLINE_CHALLENGER`, `FORWARD_SHADOW`, `LIVE_SEQUENTIAL`;
  - `HEALTH` detectors `eval_completeness`, `feasibility_consistency`, `eval_excluded_fraction`, `eval_n_stalled`, `eval_resource_creep`, **(r4)** `eval_replay_path`;
  - the detector function `eval_staleness`, evaluated by the AUT-6 intraday producer into an intraday HEALTH verdict (§3.9);
  - **(r4)** `compute_nomination_columns`, called by the AUT-5 engine (§3.5);
  - the `engine_input/v1` schema and contract test (§3.13).

**Bound subject sha (Z1).** `subject_artefact_sha256` is the family's bound sha from its BOOTSTRAP or MINT row (for the drill child, the incumbent's sha, by the C3 no-new-lineage rule).

**Validity anchored to the slot (Z4).**
- `valid_until_ns = slot_start_ns(today) + 26·3600·10⁹`, where `SLOT_UTC` equals the unit's `OnCalendar` (contract test).
- The producer refuses (ERROR) if `produced_at_ns < slot_start_ns`.
- The late bound is `TimeoutStartSec`, which includes the flock wait run inside `ExecStart`.
- Timers set `AccuracySec=1s`, `RandomizedDelaySec=0`, `Persistent=false`.
- Tests: `tests/unit/autonomy/test_verdict_validity.py::test_validity_anchored_to_slot_never_exceeds_ceiling`, `::test_worst_case_start_jitter_bounded`, `::test_offline_successor_lands_before_predecessor_expiry` (asserts `TimeoutStartSec + AccuracySec ≤ 7200 s − 900 s` for `breezy-autonomy-eval-offline`).

**(r4) Verdict identity (ARCH C4, P4-11).**
- `verdict_id = sha256(canonical body − {verdict_id, produced_at_ns})`, computed by the ARCH-0 `verdict/v1` identity function; AUT-4 calls it and never chooses. `valid_until_ns` stays in the body and is slot-anchored, so a recompute on identical inputs in the same slot yields the same id and the store treats the byte-equal body as an idempotent no-op; the store refuses a different body under an existing id (ARCH `test_differing_body_same_id_refused`).
- r3's `recompute_key` fallback is deleted.
- Test `tests/unit/autonomy/test_verdict_identity.py::test_recompute_same_slot_same_inputs_same_verdict_id`.

**(r5, K7) Resampling seeds are derived, never shared.** Every permutation and bootstrap draw (the §3.2 permutation test, the §3.5 screening bootstrap, the R-C paired bootstrap, the (b) `LB_ev` sign-flip) uses
`seed = roi_bound.SEED XOR int(sha256(subject_artefact_sha256 ‖ slot_date ‖ role).hexdigest()[:8], 16)`,
where `roi_bound.SEED` is `src/breezy/settlement/roi_bound.py:97` (20260904), `‖` is the byte `0x1F` between UTF-8 fields, `slot_date` is the ISO UTC date of `slot_start_ns`, and `role` is a closed literal from `{screen_brier_bootstrap, fs_a_permutation, fs_b_ev_signflip, fs_c_calibration_bootstrap}` (`src/breezy/analysis/autonomy/seeding.py::derive_seed`). So a same-slot recompute on identical inputs is bit-identical (which the verdict-identity rule above needs), and different subjects, days and statistics never reuse one draw stream. The R-B H0 MC keeps its own committed design seed. Tests `tests/unit/autonomy/test_seeding.py::test_same_slot_recompute_bit_identical` (two full producer runs in one slot on fixture inputs give byte-equal verdict bodies, p-values and bounds included), `::test_seed_differs_by_subject_slot_and_role`, `::test_role_is_closed_literal`.

**(r5, K9) Decimal serialisation.** `alpha_k` and `alpha_spent` are JSON strings in the canonical form `format(d.normalize(), "f")` (zero is exactly `"0"`; α_1 is `"0.0125"`), produced by the ARCH-0 `verdict/v1` writer ("money is a string-decimal"); AUT-4 never emits a float for either. Test `tests/unit/autonomy/test_verdict_schema.py::test_decimal_fields_canonical_string`. The §7 store queries compare with `tonumber`, so they hold whatever the exact canonical string.

**`inputs[]` roles** (`{path_role, sha256}`, no paths; each must resolve under its role's root for engine acceptance): `label_set`, `archive_dataset`, `tape_snapshot`, `boundary_artefact`, `fs_replay_output`, `sigma_source`, **(r4)** `screen_verdict` (the accepted OFFLINE_CHALLENGER PASS the nomination cites), `registry_export` (the newest `$STATE/evidence/registry/registry_<venue>_<date>.jsonl` whose chain carries the nomination row). The nomination row's `transition_id` is recorded as `metrics.nomination_transition_id`.

**(r4) Two ruling-sha fields (ARCH C4, P4-10).**
- `policy_ruling_sha256`: the AUT-5 policy ruling's sha on every AUT-4 verdict, null only with `assumptions ∋ no_policy_ruling`.
- `family_prereg_sha256`: `LIVE_SEQUENTIAL` only, the family's registered boundary ruling (`PREREG_FQ_v1` for FQ); null on every other kind.
- r3's Rev 5 fallback (policy sha in one field, PREREG in `inputs[family_prereg]`, the `accepted_family_preregs` policy key) is deleted.

**(r4) `assumptions` (closed five-tag enum, ARCH C4, P4-12).** Only `slippage_champion_proxy`, `slippage_floor_aud12a`, `fill_survivorship_unmodelled`, `no_policy_ruling`, `drill`. r3's proposed `fixture_candidate` and `fill_selection_sensitive` tags are withdrawn: the fixture path is isolated by state root (§6.1) and flagged `metrics.fixture_candidate=true`; fill-selection sensitivity is `metrics.fill_selection_sensitive` and handled by a policy key inside the producer (§3.7). `sigma_source_contaminated` is a metric, never an assumption.

**Single-look discipline (FORWARD_SHADOW only).**
- A **feasible** nominee's FORWARD_SHADOW is evaluated confirmatorily **once**, at the first run where n ≥ n_min_eff for every predicate, inside its window. Before that it is `UNDERPOWERED`, counts only. FAIL or INCONCLUSIVE at the look is final.
- An **infeasible** nominee (`nomination_feasible=false`) never gets a look: every daily verdict is `INCONCLUSIVE(window_cap_below_n_min)`, counts only.
- OFFLINE_CHALLENGER is screening without α and may be recomputed daily; it never claims a type-I level.

**Nothing to evaluate (ARCH C4 invariant, U10; r5 K6 made exact).** The invariant is per producer.
- `eval_offline` with no SHADOW candidate and no drill child writes exactly one `OFFLINE_CHALLENGER` verdict `INCONCLUSIVE` with `metrics.day_status=NO_INPUT` and the venue **champion** as subject (`comparator_family_id` = the champion too; `n = 0`; `n_min` = `SCREEN_MIN_STATION_DAYS`). It always also writes the `eval_replay_path` HEALTH verdict, so the producer is never silent.
- The FORWARD_SHADOW lane of `eval_offline` writes **nothing** when no open-window nominee exists: a FORWARD_SHADOW verdict needs the four C4 fields from a nomination row (I-1), so a NO_INPUT FORWARD_SHADOW would carry nulls ARCH forbids.
- `eval_live` always has ≥ 1 fold family (the champion), so it writes one LIVE_SEQUENTIAL per CHAMPION or HALTED family and never needs NO_INPUT.
- Tests `tests/unit/autonomy/test_offline_challenger.py::test_no_input_is_offline_challenger_on_champion`, `tests/unit/autonomy/test_forward_shadow.py::test_no_nominee_writes_no_forward_shadow`; completeness per §3.11.

**Fail-closed.**
- Any missing, stale, unknown-version or unverifiable input, any leakage assertion failure, any producer exception: `ERROR`, plus a CRITICAL through `deliver_with_proof`.
- `UNDERPOWERED`, `INCONCLUSIVE` and `ERROR` never promote. An `ERROR` verdict is never "fresh" for `eval_staleness`.
- A FORWARD_SHADOW verdict whose `k_life` differs from the nomination row's column is `ERROR`; the engine journals it `k_exceeded` (ARCH C4 "No `k_exceeded` in operation").

**Payload hygiene.** No paths in verdicts. `test_autonomy_payload_hygiene_scan` covers the AUT-4 writers.

### 3.2 Clustering, the design effect, the permutation test and the draw cap

- **Unit.** The independent station-day `(station, climate_day)` (Y14). `assert_nondegenerate_clustering` (`scripts/analysis/forecast_conditional_scoring.py:288-299`, moved) refuses a degenerate key.
- **Primary statistic.** A studentised date-cluster sign-flip permutation test, one-sided at α_k: per-station-day paired differences are summed per climate date; each date's sign is flipped as a block. **(r5)** Seeded by `derive_seed(subject, slot_date, role)` (§3.1, K7).
- **(r4) Draw cap `BOOTSTRAP_B_MAX` (ARCH §4.5, a `pins.py` literal).**
  - `B = min(BOOTSTRAP_B_MAX, max(10 000, ⌈200/α⌉))` for the level α actually tested.
  - Proposed literal (for the ARCH-0 owner; the value is left to the policy ruling's peer review by ARCH §8, within the code ceiling): **2¹⁹ = 524 288**. With K_LIFETIME = 4, the deepest level any test uses is α_4/3 = 0.025·2⁻⁴/3 ≈ 5.21·10⁻⁴ (the (b) component, §3.7), and ⌈200/(α_4/3)⌉ = 384 000 ≤ 2¹⁹. So **every** test that can be run gets its full Monte-Carlo B; the tail branch is unreachable in operation.
  - The ARCH-required tail beyond the cap is kept as a guard: `p_H = exp(−T²/(2·Σ_d D_d²))` (Hoeffding bound on the unstudentised date-sum sign-flip statistic, a valid conservative upper bound), reported as `metrics.p_method = "hoeffding_tail"`; reaching it raises a defect alert.
  - Flips are generated in chunks of 16 384 (≈ 16 MB at C = 120 dates). Exact enumeration when C ≤ 20.
  - Test `tests/unit/autonomy/test_permutation.py::test_b_capped_and_tail_beyond_cap`, `::test_b_max_covers_k_lifetime_over_three`.
- **Cluster floor.** The test runs only if `C ≥ C_min(α) = ⌈log2(10/α)⌉` (**(r5)** `sample_size.c_min`, K2), else `UNDERPOWERED(min_clusters)`. C_min at α_1…α_4 = 10, 11, 12, 13; at α_k/3 for (b): 12 … 15.
- **Design effect.** `deff = 1 + (m̄ − 1)·ρ̂` (**(r5)** `sample_size.deff`, K2), ρ̂ measured out-of-fold on archive days before 2026-07-01 (WP0) and **pinned in the policy block** as `deff_pinned` (§3.5); `n_min_eff` per predicate = `max(⌈deff_pinned·n_min⌉, 4·C_min)`.
- **Cluster sensitivity.** The same test with station-day blocks; disagreement gives `INCONCLUSIVE(cluster_sensitivity)`, final at the look.
- **Family pin.** `event_family="rung_2f_traded"`; the median binary is refused. `calibration_leg_rung` and `underconfidence_mean_signed_dev` are always reported.

### 3.3 Modules (analysis layer, never imported by live packages; one persistence addition)

| Path | Purpose |
|---|---|
| **(r4)** `src/breezy/analysis/stats/sequential_looks.py`, `group_sequential_boundaries.py`, `scoring_core.py`, `market_baseline.py`, `drift_freshness.py` | ARCH G36 / AUT-4a: the `scripts/analysis/` statistics moved **byte-identically** into the §4.3 pin closure; the scripts stay as thin CLI wrappers; a test pins the moved source |
| `src/breezy/analysis/autonomy/shadow_replay.py`, `subprocess_rss.py` | Moved `run_live_parity` path; per-child timeout and RSS share |
| **(r10, FH1)** `src/breezy/analysis/autonomy/import_blocker.py` | The eval-offline `sys.meta_path` blocker and recorder: `install()`, `attempts()`, `assert_clean_or_exit()`, `BLOCKED_PREFIXES`, `EXIT_INTEGRITY` (§3.9a) |
| `src/breezy/analysis/autonomy/eval_stats.py` | `eta_days`, `eta_date`. **(r5, K2; r7, RC-1)** `mde_one_sided`, `power_one_sided`, `n_min_one_sided`, `c_min`, `deff` and `n_min_eff` are **imported** from `breezy.persistence.autonomy.sample_size`, never redefined |
| **(r5, K2; r7, RC-1)** `src/breezy/persistence/autonomy/sample_size.py` | The single definition of `mde_one_sided(sigma, n, alpha, power=0.80)` (lifted from `hypothesis_ledger.recompute_mde`, §2), `n_min_one_sided(sigma, mde, alpha, power=0.80)`, `power_one_sided(sigma, n, alpha, delta)` (stdlib `statistics.NormalDist`, no numpy/scipy), `c_min(alpha) = ⌈log2(10/alpha)⌉`, `deff(m_bar, rho)` and `n_min_eff(n_min, deff, c_min)`. Its own source imports stdlib and `decimal` only. **(r8, AH5)** Its runtime closure is not stdlib-only, because Python first executes `src/breezy/persistence/__init__.py`, which imports `catalog`, Nautilus and `breezy.domain` (§0a). AUT-4 addition to the ARCH-0 package under the ARCH-0 owner's review (same basis as `nomination.py`, I-2). `src/breezy/persistence/autonomy/__init__.py` stays import-light (no re-exports). Whether `hypothesis_ledger` gains only this module depends on the parent `__init__`: see §2 AH5 (a lazy `persistence/__init__`, or the RC-1 fallback). Tests `tests/unit/autonomy/test_eval_stats.py::test_sample_size_primitives_single_definition` (asserts `eval_stats.n_min_one_sided is sample_size.n_min_one_sided`, likewise **(r7)** `mde_one_sided`, `power_one_sided`, `c_min`, `deff`, `n_min_eff`); **(r7)** `tests/unit/autonomy/test_sample_size.py` (§4 WP2) |
| **(r5, K7)** `src/breezy/analysis/autonomy/seeding.py` | `derive_seed(subject_sha, slot_date, role) -> int` with the closed role literal (§3.1) |
| `src/breezy/analysis/autonomy/permutation.py` | `date_cluster_signflip(diffs_by_date, alpha, seed, b)`; reads `pins.BOOTSTRAP_B_MAX`; chunking; tail guard |
| **(r4)** `src/breezy/analysis/autonomy/calibration_ni.py` | `relative_calibration_ni(cand, champ, dates, alpha, margin, seed, b)` → `(ece_diff_ub, n_buckets_paired)`; `false_fail_rate(...)` for WP0 (§3.10 R-C) |
| `src/breezy/analysis/autonomy/metric_registry.py` | Closed metric names and the per-kind required-field table (§3.1a); **(r4)** `nomination_transition_id`, `fixture_candidate`, `fill_selection_sensitive`, `day_status`, `msd_diff`, `outcome_reason`; **(r7)** the `eval_replay_path` names of §3.11a (`EVAL_REPLAY_PATH_METRICS`) |
| `src/breezy/analysis/autonomy/windows.py`, `leakage.py`, `tape_admission.py` | Forward-window arithmetic (anchor, tumbling, `window_end`), leakage assertions, FQ tape admission |
| **(r4)** `src/breezy/persistence/autonomy/nomination.py` | `compute_nomination_columns(policy_block, lineage_counters, window_state) -> NominationColumns(k_life, alpha_k, n_min_eff, n_cap, nomination_feasible)`: pure, stdlib + `Decimal`, imports only `pins` and **(r5)** `sample_size`; **(r5, K1)** arithmetic only: every statistical input is a named policy-block key (§3.5), nothing is estimated or read from a store. Authored by AUT-4 WP5 as an addition to the ARCH-0 package under the ARCH-0 owner's review, because the AUT-5 engine must call it and must not import `breezy.analysis` (G15). Replaces r3's `alpha_ledger.py` |
| `src/breezy/analysis/autonomy/fill_model.py` | Live IOC fill rate (unresolved AMBIGUOUS = miss); slippage proxy; the joint (b) bound at α_k/3 per component; `N_IOC_MIN` refusal; worst-case survivorship bound. **(r7, RC-2)** `p_fill_LB` is the lower element of the reused `current_rung_hold_v2._wilson_interval` at `z = NormalDist().inv_cdf(1 − α_k/3)`; the module defines no Wilson |
| `src/breezy/analysis/autonomy/budget.py` | `REPLAY_PARALLELISM` (P, from WP0), **(r5, K5)** `EVAL_OFFLINE_TIMEOUT_START_S = 6299`, `SCREEN_BUDGET_S = 900`, `SCORING_RESERVE_S = 600`, `SAFETY_S = 300`, `FLOCK_WAIT_S = 900`, `FS_REPLAY_CHILD_TIMEOUT_S` (derived, §3.12), `MAX_BACKLOG_DAYS_PER_RUN = 3` |
| `src/breezy/analysis/autonomy/run_record.py` | Producer run record and the `ExecStopPost` entry (§3.11) |
| `src/breezy/analysis/autonomy/evaluators/forecast_quantile_ladder.py`, `feasibility.py`, `health.py` | The FQ `Evaluator`, the feasibility record, the HEALTH detectors |
| `src/breezy/analysis/autonomy/producers/eval_live.py`, `eval_offline.py`, `fs_replay.py` | Producer entry modules (pinned as `eval_live`, `eval_offline`, `fs_replay` in `PRODUCER_SOURCE_SHA256`). `fs_replay` output: `$STATE/derived/autonomy/fs_replay/<family>/<closure_sha12>/<day>/<station>.jsonl` (0444, tmp + rename) |

`breezy.analysis.autonomy` imports `breezy.persistence.autonomy`, never the reverse; `breezy.persistence.autonomy ↛ breezy.adapters` (ARCH contract) is untouched.

#### 3.1a Required fields per verdict kind

`—` means null with the literal reason.

| Field | OFFLINE_CHALLENGER (screen) | FORWARD_SHADOW (nominee) | LIVE_SEQUENTIAL | AUT-4 HEALTH |
|---|---|---|---|---|
| `n`, `n_unit` | forward station-days (weather-only) after `train_end_exclusive_utc`, ≥ 2026-10-02 | admissible station-days after the nomination date, inside the window, with ≥ 1 scorable rung event | combined station-day draws | — `HEALTH_NO_TEST` |
| `n_min` | `SCREEN_MIN_STATION_DAYS` (policy) | the row's `n_min_eff` | n at the first registered look (10); `metrics.n_max` = registered n_max; or reason `no_registered_boundary` | — |
| `power`; `mde` | — `SCREEN_NO_ALPHA`; the screen threshold `X_SCREEN` | 0.80 (design); `mde_one_sided(σ_pinned, n_min_eff, α_k)` for (a) | registered design power; registered MDE at n_max | — |
| `comparator_family_id` | champion | `MARKET_ASK_IMPLIED` for (a)/(b); champion for (c) | `BREAK_EVEN` | — |
| `alpha_spent` | lineage cumulative from `lineage_counters.alpha_spent` (unchanged by screening) | the same, which includes this nominee's `alpha_k` (0 if infeasible) | LD-OBF cumulative α at the information fraction (`metrics.alpha_scope="family_prereg"`) | — |
| **(r4)** `k_life`, `alpha_k`, `n_min_eff`, `n_cap` | null (ARCH: FORWARD_SHADOW only) | copied from the nomination row columns, never recomputed | null | null |
| **(r4)** `policy_ruling_sha256` | policy sha, or null + `no_policy_ruling` | the same | the same | the same |
| **(r4)** `family_prereg_sha256` | null | null | the family's registered boundary ruling sha; null with outcome `INCONCLUSIVE(no_registered_boundary)` | null |
| `eta_to_verdict_days` | `eta_days(SCREEN_MIN_STATION_DAYS, n, rate)` | `eta_days(n_min_eff, n, rate)`, or null with reason `window_cap_below_n_min` | from the registered looks | — |

**Before a ruling is filed.** With no policy ruling, `policy_ruling_sha256 = null` and `assumptions ∋ no_policy_ruling`: the engine rejects OFFLINE and FORWARD_SHADOW verdicts as `no_ruling` (nothing widens), and accepts a LIVE_SEQUENTIAL FAIL for DEMOTE through `DEFAULT_RESTRICTIVE_CLASS` (§3.6). With no family boundary: `INCONCLUSIVE(no_registered_boundary)`, which never acts. Test `tests/unit/autonomy/test_verdict_schema.py::test_verdict_v1_schema_complete_per_kind`.

### 3.4 Replay sufficiency for forward-shadow tape days

Unchanged from r3 §3.4 (conditions 1–9; excluded-day bias guard with `EXCLUDED_FRACTION_MAX`; oversize quarantine shared with `scripts/analysis/replay_daily_runner.py`; the separate FQ census file). Condition 7 now reads "forward day outside the C4.1 frozen holdout [2026-07-01, 2026-10-02)". Condition 9 (one `fs_replay` closure; `PENDING_RECLOSURE`; `INCONCLUSIVE(mixed_closure)` breach guard) stands. **(r4)** A C1 row with `quote_ref` but no `depth_ref` (U8) is excluded from the Depth10-matched slippage proxy by name (`no_depth_ref`) but still scored for (a). Tests: `tests/unit/autonomy/test_tape_admission.py::test_n_counts_current_closure_days_only`, `::test_mixed_fs_replay_closure_is_inconclusive`, `::test_frozen_holdout_day_refused`.

### 3.5 OFFLINE_CHALLENGER (screening) and the nomination columns

**(r4) OFFLINE_CHALLENGER is the screening stage (ARCH C4).**
- Subjects: every SHADOW family of an allowlisted lineage in the fold (one MINT per lineage per day at most, AUT-3), plus the AUT-7 drill child.
- Data: external weather only, on forward climate days ≥ max(2026-10-02, the candidate's `train_end_exclusive_utc`), never inside C4.1's frozen window, never a day ≥ the candidate's nomination date (screening days are never confirmation days).
- Statistic: `brier_rung_diff_vs_champion` on the traded rung family, with the pinned cluster bootstrap (`src/breezy/settlement/roi_bound.py:93` `B_RESAMPLES`), date-clustered, **(r5, K7)** seeded by `derive_seed(subject, slot_date, "screen_brier_bootstrap")`. `crps_tmax_diff_vs_champion` and `underconfidence_mean_signed_dev` are reported.
- Outcomes at the ruling's fixed thresholds (R-D):
  - `UNDERPOWERED(screen_min_days)` while n < `SCREEN_MIN_STATION_DAYS`;
  - `INCONCLUSIVE(NOT_DISTINCT)` if max|Δp| vs the champion on the pinned grid ≤ AUT-3's delta (always for the drill child, with `assumptions ∋ drill`);
  - `PASS` iff mean improvement ≥ `X_SCREEN` **and** the pinned-bootstrap 95% upper bound of Δbrier < 0;
  - otherwise `FAIL(stage=screen)`.
- It charges **no α** and makes no type-I claim; daily recomputation is permitted. Rows from archive days before 2026-07-01 are used only by WP0 to measure σ, ρ̂ and the calibration false-fail rate for the policy block, never per candidate. r3's archive pre-screen, `prescreen_fold_wins` and confirmatory "stage 2" are deleted.

**(r4) Nomination (ARCH C4 "Two limits, one index"; C5 PROMOTE row).**
- A nomination is the AUT-5 engine's SHADOW→CHALLENGER **PROMOTE** on an accepted OFFLINE_CHALLENGER PASS, refused by the store when the lineage's current window already holds a nomination (`MAX_NOMINATIONS_PER_FORWARD_WINDOW` = 1) or when α-charging nominations have reached K_LIFETIME (`MAX_NOMINATIONS_PER_LINEAGE_LIFETIME` ≤ 4). Drill rows (DRILL_ADMIT) are never nominations.
- The engine, holding `registry/engine.lock` in one `BEGIN IMMEDIATE` transaction, calls AUT-4's pure `compute_nomination_columns` and writes the five required columns:
  - **(r5, K1) Inputs are pinned block values only:** `alpha_total`, `stations`, `forward_window_days`, `uptime_floor`, `deff_pinned`, `sigma_pinned` (a), `sigma_b_pinned` (b), `mde_a`, `mde_b`, `mde_c`, `n_min_c` (a table keyed k = 1…K_LIFETIME), plus `lineage_counters.nominations` and the window state (`window_index`, `window_end`, `nomination_in_window`). The function reads no store, estimates nothing, and refuses (raises) on a missing key.
  - `n_cap = ⌊stations · forward_window_days · uptime_floor⌋`. **(r5)** `stations` is the pinned block value; `feasibility_consistency` FAILs if it differs from the committed root manifest's station count (§3.8).
  - At the candidate level α_k* = alpha_total·2^−(nominations+1): (a) `n_min_a = n_min_one_sided(sigma_pinned, mde_a, α_k*)`, C_min(α_k*); (b) `n_min_b = n_min_one_sided(sigma_b_pinned, mde_b, α_k*/3)`, C_min(α_k*/3); (c) `n_min_c = n_min_c[k*]` (R-C, simulated by WP0 and pinned, because it has no closed form; `mde_c` is the ΔECE distance below the margin at which its power is stated).
  - `n_min_eff = max over (a), (b), (c) of n_min_eff(n_min_x, deff_pinned, C_min_x)` with `n_min_eff(n, d, c) = max(⌈d·n⌉, 4·c)` (`sample_size`, K2).
  - If `n_min_eff > n_cap`: `nomination_feasible = false`, `alpha_k = 0`, `k_life = lineage_counters.nominations` (unchanged), the store increments `infeasible_nominations`; the window's slot is used.
  - Else: `nomination_feasible = true`, `k_life = nominations + 1`, `alpha_k = α_total·2^−k_life` (`Decimal`), and the store increments `nominations` and sets `alpha_spent = α_total·(1 − 2^−k_life)`.
- `k_life` never resets across windows or epochs; only a new lineage root (a reviewed commit) starts a fresh budget. Two pending nominees never share a k (single engine writer, CAS, and ≤ 1 per window).
- FORWARD_SHADOW reads all five columns from the row and never recomputes them; a mismatch between a verdict's `k_life` and the row is `ERROR` (`k_exceeded`).
- **(r5, K3) AUT-5 request (binding on the engine once accepted).** The engine calls `compute_nomination_columns(policy_block, lineage_counters, window_state)` **inside** the same `BEGIN IMMEDIATE` transaction that inserts the SHADOW→CHALLENGER PROMOTE row (after the CAS read of `lineage_counters`, before the insert), passing the named keys above from the verified policy block; the five columns are written exactly as returned, and no other code path writes them. Contract tests (AUT-4, `tests/contract/test_nomination_columns_contract.py`): `::test_promote_row_columns_written_only_via_compute_nomination_columns` (the function is replaced by a spy returning sentinel columns; the committed row must carry the sentinels, and a PROMOTE write with the spy never called fails the test), `::test_called_inside_begin_immediate_with_named_keys` (the spy asserts an open `BEGIN IMMEDIATE` transaction on the registry connection and the exact key set), `::test_missing_policy_key_refuses_nomination`.
- Tests (RED first, WP5): `tests/unit/autonomy/test_nomination.py::test_feasible_nomination_charges_alpha_k_life`, `::test_infeasible_nomination_charges_no_alpha`, `::test_infeasible_nomination_uses_window_slot`, `::test_k_life_never_resets_across_windows`, `::test_n_cap_formula_floor`, `::test_n_min_eff_from_pinned_sigma_and_ruling_mde`, `::test_columns_are_pure_function_of_block_and_counters`, **(r5)** `::test_inputs_are_named_block_keys_only`, `::test_n_min_b_at_alpha_over_3_and_n_min_c_table`; `tests/unit/autonomy/test_forward_shadow.py::test_fs_reads_columns_never_recomputes`, `::test_k_life_mismatch_is_error_k_exceeded`. AUT-4 also supplies fixtures for ARCH's `test_two_pending_nominees_get_distinct_k`, `test_window_cap_below_n_min_is_inconclusive`, `test_infeasible_nomination_charges_no_alpha`, `test_nomination_refused_past_k_max_lifetime`, `test_alpha_index_never_resets`.

**Windows (W7).** Tumbling per lineage from the policy block's `forward_window_anchor_date` (proposed 2026-10-02) with `forward_window_days` (proposed 28; pins 28–120). A nominee uses only forward climate days strictly after its nomination's UTC date and ≤ its window end.

**Window-end rules.**
- Infeasible nominee: every daily FORWARD_SHADOW is `INCONCLUSIVE(window_cap_below_n_min)`, decided at nomination and immutable; after the window end the producer restates the final outcome without replay.
- Feasible nominee whose n has not reached n_min_eff by the window end: `INCONCLUSIVE(window_end_underpowered)`, final.
- Tests: `tests/unit/autonomy/test_forward_shadow.py::test_window_cap_below_n_min_is_inconclusive_by_construction`, `::test_no_forward_day_past_window_end`, `::test_no_forward_day_on_or_before_nomination_date`, `::test_window_end_underpowered_final`.

**Today.** FORWARD_SHADOW (a) n_min_eff ≥ 403 at α_1 (deff 1; 605 at deff 1.5) > n_cap 89 (28 days, floor 0.8) and > 480 (120 days, floor 1.0): every nomination infeasible, `k_life` stays 0, no α spent.

**Holdout (C4.1).** `RULING_holdout_freeze_and_forward_window_2026-10-03` is consumed by name and never restated; `open_holdout` (`src/breezy/analysis/nbp_calibration.py:353`) is never called by AUT-4; the contamination of [2026-07-01, 2026-10-01) is disclosed and `metrics.sigma_source_contaminated = true` wherever σ comes from that window. Until the ruling is filed (Wave 0): `INCONCLUSIVE(SEALED_WINDOW)`.

### 3.6 LIVE_SEQUENTIAL over admissible labels

As in r3: inputs are admissible `window_complete` C2 rows with `p_source=c1_decision`, combined by `combine_station_day` (L-40); the registered boundary via the moved `src/breezy/analysis/stats/group_sequential_boundaries.py`; mapping CONTINUE→UNDERPOWERED, SURVIVE→PASS (only at n_max), KILL→FAIL, refusal→ERROR; families enumerated from the fold (CHAMPION and HALTED); prefix exclusion (`climate_day < D0′`); `n_min` = first-look n (10); a FAIL from the R-B loss stop before that look carries `metrics.stop_reason = "loss_stop"`. ARCH: never a new α-spend; canary and drill never counted.

**(r4) Changes.**
- A family with no registered boundary gets `INCONCLUSIVE(no_registered_boundary)` (ARCH name), which never acts.
- `family_prereg_sha256` carries the boundary ruling's sha; `policy_ruling_sha256` the policy sha. The engine accepts the verdict only if both match (ARCH C4 Engine acceptance).
- **Restrictive fallback (ARCH C4, P4-10; AUT-5 M10).** With no filed or verifiable policy ruling, the verdict carries `policy_ruling_sha256 = null`, `assumptions ∋ no_policy_ruling`, and `declared_action_class` = the literal `DEFAULT_RESTRICTIVE_CLASS["live_sequential"]` (AUT-4 requests `DEMOTE`, cause class `RECOVERABLE_MODEL`, from the AUT-5/ARCH-0 `pins.py` owner). The engine accepts a FAIL for DEMOTE only, never a widening row. So a KILL DEMOTEs from the day R-B is filed, policy or not.
- Unit: `breezy-autonomy-eval-live` takes the **studies flock** (§3.9), not its own lock.
- Tests: `tests/unit/autonomy/test_eval_live.py::test_n_min_is_first_look_n`, `::test_loss_stop_fail_labelled`, `::test_no_registered_boundary_inconclusive_never_acts`; `tests/integration/autonomy/test_live_fail_demotes.py::test_live_fail_accepted_with_both_ruling_shas_and_demotes`, `::test_live_fail_without_policy_demotes_via_default_restrictive_class`, `::test_family_prereg_sha_mismatch_is_error`.

### 3.7 FORWARD_SHADOW and the slippage source

**(r4) Subjects.** Only CHALLENGER families with a SHADOW→CHALLENGER PROMOTE (nomination) row, whose four C4 fields come from that row. r3's champion baseline and drill-child FORWARD_SHADOW verdicts are withdrawn, because neither has a nomination and ARCH C4 makes the four fields part of every FORWARD_SHADOW. Their purposes move:
- the daily replay→admission→scoring path is exercised by the HEALTH detector `eval_replay_path` on the champion (§3.11), which carries admitted days, exclusions by reason, parity results and the closure sha, and never feeds a promotion;
- the drill child is screened only (OFFLINE `INCONCLUSIVE(NOT_DISTINCT)`, `assumptions ∋ drill`).
CHALLENGERs reached by SUPERSEDE or DISPLACED are rollback targets, not nominees, and get no FORWARD_SHADOW.

**Replay.** Per-(closure, artefact sha, station-day) `fs_replay` child; the cache key includes `artefact_sha256` and the manifest-modulo-allowlist sha, so the champion's `eval_replay_path` replay and any byte-identical subject share one output. Replays per day ≤ 4 stations × (1 open-window nominee + champion) per lineage (§3.12).

**Predicates** (intersection-union; each at α_k from the row; a feasible nominee only):
- **(a)** `brier_rung_diff_vs_market < 0` by the §3.2 test, against the market-implied baseline (moved `wp7b_market_as_forecaster`).
- **(b)** Joint lower bound on effective EV per take, as r3 §3.7(b): `ev_eff = p_fill·ev_cond`, `ev_cond = held − ask − θ·ask·(1−ask) − slippage_proxy`; three components each at α_k/3 (Bonferroni): `LB_ev` (date-cluster sign-flip), `UB_slip` (floored 0.01), `p_fill_LB` (Wilson via the reused `current_rung_hold_v2._wilson_interval`, **(r7, RC-2)**; trailing 28 days of live FQ IOCs); `N_IOC_MIN` = 30 and `N_PROXY_MIN` = 30 gate the look (below); C_min at α_k/3; `LB_ev` seeded by `derive_seed(…, "fs_b_ev_signflip")`.
- **(c) (r4)** Relative calibration non-inferiority to the champion, the R-C test (§3.10): one one-sided paired test over the same station-days' paired calibration buckets against the ruling margin `CALIBRATION_NI_MARGIN`; `INCONCLUSIVE(calibration_buckets_below_min)` below `MIN_CALIBRATION_BUCKETS` paired buckets; the absolute leg (`evaluate_calibration_leg`, `scripts/analysis/forecast_conditional_scoring.py:392`, moved) reported, never required.
- **(d)** `n ≥ n_min_eff` (the row's value) in independent station-days.
- **Look rule (r5, K9).** The look fires once, at the first run inside the window where (d) holds **and** `n_ioc ≥ N_IOC_MIN` **and** `n_proxy ≥ N_PROXY_MIN`. Until then the verdict is `UNDERPOWERED` (counts only). The two counts are ancillary: they count the champion's live IOCs and admissible champion fills, not a function of the nominee's paired differences, so conditioning the look time on them leaves the level of (a)–(c) unchanged. **(r6, L3)** Stated as an invariant: the look time is a function of champion data and the station-day admissibility calendar only. `n_ioc` and `n_proxy` are computed by `forward_shadow.look_counts(champion_rows, window)`, whose signature takes no nominee input; (d)'s `n` counts admissible paired station-days, which depends on which station-days are admissible, never on the nominee's paired-difference values or outcomes. Test `tests/unit/autonomy/test_forward_shadow.py::test_look_time_independent_of_nominee_outcomes`: hold the champion rows and the admissibility calendar fixed, replace the nominee's per-station-day outcomes with (i) the original, (ii) a sign-flipped copy, and (iii) a seeded random redraw; it asserts the look `slot_start` (or window-end INCONCLUSIVE) is identical in all three. A companion check `::test_look_counts_signature_takes_no_nominee_input` inspects `look_counts` and fails if a nominee parameter is added. If the window ends first, the verdict is `INCONCLUSIVE(fill_rate_underpowered)` or `INCONCLUSIVE(PROXY_UNDERPOWERED)` (first unmet count in that order), final; otherwise §3.5 window-end rules. Test `tests/unit/autonomy/test_forward_shadow.py::test_look_waits_for_n_ioc_min_inside_window`, `::test_window_end_before_n_ioc_min_is_fill_rate_underpowered_final`, **(r6, L3)** `::test_look_time_independent_of_nominee_outcomes`, `::test_look_counts_signature_takes_no_nominee_input`.

**Slippage source (Y12).** `slippage_point = max(0.01, mean_slip)` from C2 `slippage` over admissible champion fills (trailing 28 days, matched via C1 `depth_ref`). `assumptions ⊇ [slippage_champion_proxy, slippage_floor_aud12a, fill_survivorship_unmodelled]`. Without the policy ruling's acceptance of `slippage_champion_proxy` for the challenger's policy class, the verdict is `INCONCLUSIVE`.

**Survivorship** (direction as derived in r3 §3.7 and §R3 F4; unchanged): the estimator is anti-conservative if IOC misses concentrate in favourable decisions. `metrics.ev_eff_worst_case` (Manski bound) is reported. **(r4)** If `ev_eff_worst_case ≤ 0` while (b) passes, the producer sets `metrics.fill_selection_sensitive = true` and applies the policy key `ACCEPT_FILL_SELECTION_SENSITIVE` (bool, R-E): if false, (b) gives `INCONCLUSIVE(fill_selection_sensitive)`. No new `assumptions` tag.

Tests: `tests/unit/autonomy/test_forward_shadow.py::test_b_joint_bound_bonferroni_alpha_over_3`, `::test_fewer_than_n_ioc_min_inconclusive`, `::test_worst_case_survivorship_bound_reported`, `::test_fill_selection_sensitive_inconclusive_unless_accepted`, `::test_only_nominated_challengers_get_forward_shadow`, `::test_calibration_leg_relative_inconclusive_below_min_buckets` (the ARCH test name, AUT-4 implementation).

### 3.8 Feasibility record

`$STATE/evidence/autonomy/feasibility/feasibility_<YYYY-MM-DD>.json` (0444, daily, written by `eval_offline`), handed to the policy ruling (ARCH §4.2 Y12). Keys:
- `n_min` (independent station-days) per predicate at α_1 … α_K; the measured replay-sufficient qualifying station-days per day and its source; `sigma_pinned`, `deff_pinned`, their sources and `sigma_source_contaminated`;
- **(r4)** `mde_at_alpha_K` with α_K = α_total·2^−K_LIFETIME (= 0.025/16 at K_LIFETIME 4);
- `n_cap_forward_shadow`, `uptime_floor`, `forward_window_days`, `forward_window_anchor_date`, `bootstrap_b_max`, `k_lifetime`, `min_calibration_buckets`, `calibration_ni_margin`, `calibration_false_fail_rate`;
- `eta_date`, `kill_date` (2027-01-25), `drill_lost_live_days` (from AUT-5's drill accounting, ARCH §5.3 V19), and `promote_eligible_by_eta = (eta_date ≤ kill_date − forward_window_days)` with those lost days counted;
- `live_mde_at_n_max`, `live_power_at_n_max_by_delta`;
- **(r4)** `lineage: {nominations, infeasible_nominations, alpha_spent}` and `per_nominee: [{family_id, nomination_transition_id, k_life, alpha_k, n_min_eff, n_cap, nomination_feasible, window_end, eta_date}]`; `per_screen_candidate: [{family_id, screen_outcome, n, projected_n_min_eff, projected_n_cap, projected_feasible}]` (projections from `compute_nomination_columns` on the same pinned block and counters, descriptive).

**`feasibility_consistency`** FAILs if the block's `stations` differs from the committed root manifest's station count (r5, K1), or if `promote_enabled = true` in the policy block and any of: `promote_eligible_by_eta = false`; any live nominee has `nomination_feasible = false` or `eta_date > window_end`. Test `tests/unit/autonomy/test_feasibility.py::test_consistency_uses_row_columns_and_eta_bound`, `::test_record_reports_mde_at_alpha_K`, `::test_record_reports_live_power_at_n_max`, `::test_eta_bound_counts_drill_lost_days`, **(r5, K2)** `::test_projection_equals_engine_written_columns` (a fixture engine pass writes a nomination row; the record's `per_screen_candidate.projected_*` for that candidate, computed beforehand, equal the row's `n_min_eff`, `n_cap`, `nomination_feasible` exactly, and its `per_nominee` entry equals all five columns), `::test_stations_key_matches_root_manifest`.

### 3.9 Schedule, locks and the ATTEST interaction

| Unit (Type=oneshot) | OnCalendar (UTC) | Lock (`flock -w`, inside ExecStart) | **TimeoutStartSec** | Worst end | Memory |
|---|---|---|---|---|---|
| `breezy-autonomy-eval-offline` | 11:00 | `breezy-studies.lock`, 900 s | **(r5)** 6299 (includes the wait) | **(r5)** 12:45:00 (11:00:00 + 1 s AccuracySec + 6299 s) | **(r4)** `MemoryHigh=12G`, `MemoryMax=14G` (§5.2), in `breezy-studies.slice` |
| `breezy-autonomy-eval-live` | 14:45 | **(r4)** `breezy-studies.lock`, 300 s | 1500 | 15:10:01 | `MemoryHigh=768M`, `MemoryMax=1G`, in `breezy-studies.slice` |

- Both units: **(r7, E-7a)** `OnFailure=breezy-autonomy-failed@%n` (AUT-6's wrapped notifier, replacing r6's `breezy-study-failed@%n`), `ExecStopPost=` run record (§3.11) with `TimeoutStopSec=60`, every `ExecStart=`/`ExecStopPost=` through `deploy/systemd/breezy-autonomy-bwrap` (§3.9a), `EnvironmentFile=-%h/.config/breezy/alerts.env` (G27). Neither sets `RuntimeMaxSec` (G32).
- **Launch window.** Both [start, start + W + TimeoutStartSec + TimeoutStopSec] intervals (11:00:00–12:46:00, 14:45:00–15:11:01) are disjoint from [16:30Z, 17:10Z) and end before the 15:30Z daily engine pass. Neither is a launch-path unit.
- **No offline expiry gap (r5, K5).** Previous verdict valid to 13:00:00 next day; successor lands by 12:45:00, exactly 900 s before. `test_offline_successor_lands_before_predecessor_expiry` asserts `TimeoutStartSec + AccuracySec ≤ 7200 − 900`, i.e. 6299 + 1 = 6300 ≤ 6300; r4's 6300 failed it by 1 s. The assertion is kept, never loosened.
- **eval-live contention.** AUT-2's 14:15Z label run holds the studies flock until ≤ 14:40Z; eval-live waits ≤ 300 s inside its 1500 s bound, so it ends ≤ 15:10Z, 20 min before the engine. If the label run overruns past 14:50Z, eval-live times out on the lock, writes no verdict, and `eval_staleness` FAILs by 15:25Z (fail-closed, alerted).
- Neighbouring slots (other plans): AUT-3 reproducibility rerun 09:35Z (12G, studies flock; **(r6, L2)** the one start time used throughout this plan); AUT-2 labels 14:15; engine 15:30; canary 15:45; post-STOP RECONCILIATION 16:41–16:43; pre-launch 16:45.
- **(r5, K8) Pre-11:00 studies end by 10:45Z.** Every unit that takes the studies flock with an `OnCalendar` before 11:00Z must satisfy `start + AccuracySec + TimeoutStartSec + TimeoutStopSec ≤ 10:45:00Z`, leaving eval-offline's 900 s wait a ≥ 30 min margin (it then holds the lock by 11:00 at the latest in the worst case, well inside the wait the §3.12 budget assumes). Contract test `tests/contract/test_autonomy_units.py::test_pre_offline_studies_units_end_by_1045z` parses every `deploy/systemd/breezy-*.service`/`.timer` pair in `breezy-studies.slice` or naming `breezy-studies.lock`. AUT-3 r3's rerun (09:35Z, 4800 s, worst end ≈ 10:57Z) violates it. **(r6, L1/L2)** With `AccuracySec=1s` and `TimeoutStopSec=60s` the bound is `TimeoutStartSec ≤ 10:45:00 − start − 1 − 60`. AUT-4 requests that AUT-3 keep its 09:35:00Z start with `TimeoutStartSec` ≤ **4139 s** (09:35:00 + 1 + 4139 + 60 = 10:45:00). r5's figures (4140 s from 09:35Z; 4800 s from 09:24Z) were each 1 s over, because they left out `AccuracySec`. For reference only, not requested: the contract test would also accept a 09:24:00Z start with ≤ 4799 s. Widening eval-offline's flock wait was rejected: each extra second comes out of the 3599 s replay budget (§3.12).
- Contract tests: `tests/contract/test_autonomy_units.py::test_units_do_not_contend_on_flock`, `::test_eval_live_starts_after_label_slot_ends`, `::test_consumption_instants_inside_validity`, `::test_aut4_units_outside_launch_window` (with W, TimeoutStartSec and TimeoutStopSec), and the programme deploy test `tests/deploy/test_autonomy_oneshots_never_set_runtime_max_sec.py::test_no_autonomy_oneshot_sets_runtime_max_sec` (fails if any `deploy/systemd/breezy-autonomy-*.service` with `Type=oneshot` sets `RuntimeMaxSec`; complements ARCH `test_oneshot_units_use_timeout_start_sec_not_runtime_max_sec`).

**(r4) ATTEST (ARCH C5 ATTEST row, P4-7, W1).**
- ATTEST cites only intraday `HEALTH` and `RECONCILIATION` verdicts listed in `attest_required_detectors`; a daily 26 h AUT-4 verdict is never citable.
- AUT-4 supplies `health.eval_staleness(fold, verdict_store, now_ns)`; the AUT-6 intraday producer evaluates it and writes an intraday `HEALTH` verdict (detector `eval_staleness`) with `ATTEST_VERDICT_VALIDITY_H` (≤ 8 h) validity. AUT-4 drafts, for the AUT-5 policy, that `(HEALTH, eval_staleness)` is a member of `attest_required_detectors`; once it is, a dead evaluator withholds ATTEST and the node's `registry_attest_expired` veto stops entries.
- **Freshness.** A producer's newest verdict is fresh only if unexpired **and** outcome ≠ `ERROR`. `eval_staleness` FAILs if any CHAMPION or HALTED family lacks a fresh LIVE_SEQUENTIAL verdict after 15:25Z (14:45 + 1500 s + 15 min), or if any AUT-4 producer's newest verdict is not fresh.
- **(r5, K4) Today's slot.** At and after 15:25Z, `eval_staleness` also FAILs unless, for every producer in the policy key `eval_staleness_producers` (drafted `[eval_live]` until the eval-offline timer is enabled, then `[eval_live, eval_offline]`, amended in the enabling commit), the newest verdict's `slot_start_ns` falls on **today's UTC date**. An unexpired verdict from yesterday's slot (eval-offline's is valid to 13:00) therefore no longer passes at 15:25Z. "Newest" = max `slot_start_ns`, then max `produced_at_ns`. Before 15:25Z only the unexpired-and-not-ERROR rule applies. Tests `tests/unit/autonomy/test_health.py::test_staleness_fails_when_newest_slot_not_today`, `::test_staleness_producer_set_from_policy_key`.
- **(r5, K4) Engine consumption, AUT-5 request.** The engine acts only on the newest verdict per (subject family, kind) (per (subject family, kind, detector) for HEALTH), ordered as above. Older live verdicts it reads are journaled with their computed `acceptance` and `acted=false`; no new `reject_reason` is added to ARCH's closed set. Contract test `tests/contract/test_engine_input_journal_contract.py::test_engine_acts_on_newest_verdict_per_family_kind`.
- **Invariant (ARCH §4.5):** `ATTEST_PERIOD_H + L_max + ATTEST_MARGIN_H ≤ ATTEST_VERDICT_VALIDITY_H`, L_max = 60 min + 150 s = 1.04 h: 6 + 1.04 + 0.5 = 7.54 ≤ 8. Test `tests/unit/autonomy/test_health.py::test_attest_cadence_has_no_expiry_gap_with_eval_staleness`.

### 3.9a (r7) Sandboxing, per-command bounds and timing errata (E-7, E-7a, E-8a, E-9, E-10)

**E-7a rule 1: every AUT-4 unit through the shared wrapper.** AUT-4 asks the `AUTONOMY_BWRAP_TABLE` owner for three rows; each is `--ro-bind / /` plus `--bind` on exactly these dirs, the E-7 credentials tmpfs, **(r8, E-7c)** `--tmpfs /tmp` with `TMPDIR=/tmp`, and a self-probe whose negative paths come from the table (a write under `$STATE/registry/` must FAIL; a write under the row's own first bind must SUCCEED; otherwise exit INTEGRITY with a delivered CRITICAL):

| Row (unit name) | `--bind` set | `unshare_pid` | Notes |
|---|---|---|---|
| `breezy-autonomy-eval-offline` | `$STATE/derived/verdicts`, `$STATE/derived/autonomy/fs_replay`, `$STATE/derived/autonomy/eval_runs/eval_offline`, `$STATE/evidence/autonomy/feasibility`, `$STATE/evidence/alerts`, **(r8, AH4)** `$STATE/derived/replay/oversize_quarantine` (resolved below), and its 0700 cache `$STATE/cache/autonomy/eval_offline` | true | `fs_replay` children are subprocesses inside this sandbox, so they inherit it. **(r8, E-7c)** Private `/tmp` (`--tmpfs /tmp`, `TMPDIR=/tmp`), which is where the children's scratch lands. **(r8, AH1)** Filed only once its closure test is green (E-7b, below). **(r9, BH1)** Filed under the E-7b (b) named exception (11 modules, below), with both closure tests green. **(r10, R-1, FH1)** The exception now has 8 modules at import time, plus the 3 declared R-1 run-time modules. The run-time closure tests and the import-blocker tests must also be green. **(r9, BL1)** `--size` 2 GiB |
| `breezy-autonomy-eval-live` | `$STATE/derived/verdicts`, `$STATE/derived/autonomy/eval_runs/eval_live`, `$STATE/evidence/alerts`, 0700 cache `$STATE/cache/autonomy/eval_live` | true | **(r8, E-7c)** Private `/tmp` (`--tmpfs /tmp`, `TMPDIR=/tmp`). **(r9, BL1)** `--size` 128 MiB |
| `breezy-autonomy-eval-offline-fixture` | only `/home/jon/.local/share/breezy-autonomy-fixture/` (its verdicts, journal, evidence, cache) | true | The §6.1 path 3 run: the production state root is read-only by mount, which turns r6's "fixture never writes production" from a convention plus a contract test into an enforced property. **(r8, E-7c)** Private `/tmp` (`--tmpfs /tmp`, `TMPDIR=/tmp`), **(r9, BL1)** `--size` 2 GiB. **(r8, LOW-2)** Positive/negative probe test below |

- **Same-bind rule.** Every temp file sits in the bind of its final name (the ARCH-0 verdict writer, `fs_replay` outputs, run records, the feasibility record).
- **Lock order.** `timeout -k` → `flock -w` → wrapper; the studies lock file is pre-created and opened by `flock` outside the sandbox, so it needs no bind.
- **No `/proc/locks` consumer.** AUT-4 code reads neither `/proc/locks` nor `/proc/<pid>`, so both rows keep `--unshare-pid` (E-7a rule 2's test covers it).
- **Network.** Left on, as E-7 rule 2 states, for outbox delivery through `deliver_with_proof`. NO-SEND is unchanged: no exec client, the refusing submit veto, `test_execution_egress_firewall_guard` byte-unchanged.
- **O-1: closed by E-7b (r8, AH1).** The coordinator ruled on 2026-10-03 (E-7b) as follows.
  - **(a) is required first.** WP1 measures the replay closure. The pure symbology and slug helpers move into an adapter-free module with delegating shims (AUT-6 AF1 precedent). The closure test then passes with no exception.
  - **(b) is permitted only if** WP1's measurement shows the replay needs non-exec adapter modules, such as instrument definitions the native `BacktestEngine` consumes. It is a named E-7a rule-2 exception on the `eval-offline` row only, scoped to the measured non-exec modules and guarded by `test_eval_offline_closure_has_no_adapter_exec_module`.
  - Narrowing E-7 in general is rejected.
  - r7's §6.4 row-10 wait for a ruling is dropped.
- **(r9, BH1) Decision: E-7b branch (b), with N-1 declared now.** This supersedes r8's "what the planning-time measurement adds", M1–M3 and the r8 N-1 text, which remain in r8.
  - **Certain finding.**
    - At HEAD the replay closure contains `runtime/order_enablement.py`.
    - That module imports `adapters.polymarket_us.write_transport`, a venue HTTP module, together with `operator_controls` and `safety` (`order_enablement.py:48-53`).
    - Three `current_rung_hold` modules import it for `OrderSubmissionPermit`: `composition.py:45`, `continuous_strategy.py:54` and `strategy.py:119`.
    - `fees.py:44,49` imports `errors` and `parsing`.
    - This section forbids editing `order_enablement`.
    - So r8's M1–M3 cannot reach 0 adapter modules. §0b measures 25 with them, including 8 exec modules.
  - **Option (a), the pure permit-type seam, is rejected.**
    - *It is not a pure move.* `OrderSubmissionPermit.issue` is a classmethod on the type and its only constructor (L-22; `order_enablement.py:1-7, 175-234`). Its body reads `write_transport.WRITE_CANONICAL_STRING_VERIFIED` (:206), both operator caps (:211-217) and `LiveTradingPermit` (:198). Making the type dependency-free means one of two things:
      - splitting `issue` off the type; or
      - making its imports function-local.

      Either one edits the minting path. That path is pinned by B11: `order_enablement.py:13-23`, and `tests/unit/test_polymarket_us_readonly_guard.py:1939-2046`, which allows exactly one production caller and one construction site. The hard invariants also forbid editing it.
    - *It is not sufficient.* §0b scenario B applies the seam. `order_enablement` leaves the closure, but `exec.client` and the venue `transport`/`write_transport` stay.
  - **Option (b), declared now.**
    - E-7b permits (b) when the measurement shows that the replay needs non-exec adapter modules consumed by the native `BacktestEngine`. §0b shows exactly that.
    - `PolymarketUSFeeModel` (`backtest_harness.py:153`) is the engine's fee model and is mandatory under barrier F2. Its own imports bring 6 more modules.
    - WP1 repeats the measurement as verify-first before the row is filed.
  - **What (b) still requires: the cut set W1–W4.**
    - The (b) guard (no exec, no HTTP/WS client) fails at HEAD, and it still fails after M1–M3 (§0b).
    - The minimal set that passes was found by removing one cut at a time (§0b, E2–E5):
    - **W1. Make the adapter package `__init__` lazy** (`src/breezy/adapters/polymarket_us/__init__.py:69-147`).
      - It becomes a PEP 562 `__getattr__` over the exact HEAD import map (61 names), and `__all__` is unchanged.
      - Without W1, any adapter import loads `http`, `websocket` and `transport` (E5).
    - **W2. Make `src/breezy/strategy/current_rung_hold/__init__.py` lazy** (:14-45; 24 names), in the same way.
      - Without W2, any `current_rung_hold.*` import runs `.strategy` and `.trial_day_latch` and loads `exec.client` (E3).
    - **W3. Move the pure instrument-bucketing helpers out of `composition.py`.**
      - *What moves.* Four definitions move verbatim to the new module `src/breezy/strategy/current_rung_hold/instrument_buckets.py`:
        - `InstrumentStationMismatchError` (:187);
        - `_facts_from_instrument` (:294);
        - `bucket_station_instrument_ids` (:341);
        - `_bucket_station_instrument_ids` (:359).
      - ~~*Names.* `composition.py` imports all four back under the same names, so callers see identical objects. That includes `tests/unit/test_current_rung_hold_composition.py:57`.~~ **(r10, FM2) Corrected on measurement (§0c finding 7).**
        - `composition.py` imports back only the two moved names it still uses or exports. One is `InstrumentStationMismatchError`, which is in `__all__` and is imported by `tests/unit/test_current_rung_hold_composition.py:57` and `tests/strategy/forecast_quantile_ladder/test_d1_cache_union.py:28`. The other is `_bucket_station_instrument_ids`, called by `resolve_station_instrument_ids` (:338) and by the builder.
        - Importing `bucket_station_instrument_ids` or `_facts_from_instrument` back would raise F401, so `composition` stops binding those two. The only importer of either is `strategy.py:65`, and W3 re-points it.
        - Ruff also forces 7 imports out of `composition.py`. They are listed in §3.9b (8).
      - *What stays in `composition.py`.* `resolve_station_instrument_ids` (:321), `_read_catalog_instruments` (:354), `phase1_sending_permit` (:257) and every permit-wiring line (:519-:760).
      - *The importer.* `forecast_quantile_ladder/strategy.py:65` imports from the new module.
      - ~~*Monkeypatching.* No test patches the moved names (searched).~~ **(r10, FM2) Corrected.**
        - `tests/strategy/forecast_quantile_ladder/test_d1_cache_union.py:299-302` and `:329-332` monkeypatch `breezy.strategy.forecast_quantile_ladder.strategy.bucket_station_instrument_ids`. That is the name bound in the strategy module, and `_d1_candidate_ids` looks it up as a global at call time (`strategy.py:314`).
        - W3 keeps that module-level name. `strategy.py:65` becomes `from breezy.strategy.current_rung_hold.instrument_buckets import bucket_station_instrument_ids`, so the patch target still exists and the patch still takes effect. The §3.9b (8) test pins this, and the file passes on the §0c copy.
        - No test patches a name that moves out of `composition`. The only patches on `composition` are of `resolve_alert_sink` and `_station_claims` (`test_current_rung_hold_composition.py:429,459,507,640`), and neither moves.
      - *Why it is needed.* Without W3 the replay loads `composition`, and through it `order_enablement` and `exec.client` (E4).
    - **W4. Move an annotation-only import under `TYPE_CHECKING`.**
      - *The edit.* `forecast_quantile_ladder/strategy.py:79` imports `SupportsQuantileLatch`, which is used only in the annotation at :144 (the module has `from __future__ import annotations` at :36). The import moves into an `if TYPE_CHECKING:` block.
      - *Why it is needed.* Without W4, the chain `persistent_latch.py:35` → `trial_day_latch.py:68` → `exec.client` remains (scenario C).
      - *Safety of the move.*
        - Nothing in `src/` or `scripts/` evaluates the strategy's annotations: the only `get_type_hints` call is `credentials.py:153`, on config types.
        - `forecast_quantile_ladder/composition.py:42`, which uses the name at runtime, is not edited.
    - **(r10, FH1) W5. Move the pure D+1 helper out of `forecast_quantile_ladder/composition.py`.**
      - *What moves.* `_d_plus_1_climate_days` (:83) and the constant `_VENUE` (:56) move verbatim to the new module `src/breezy/strategy/forecast_quantile_ladder/d_plus_1.py`. Its only Breezy imports are `breezy.ingest.gaps.local_standard_date` and `breezy.registry.sites.default_registry`, and both are already in the strategy's closure.
      - *Names.* `composition.py` imports both back: `_VENUE` is still used at :203 and :206, and `_d_plus_1_climate_days` at :175 and :224. Ruff F401 then forces `Iterable` and `local_standard_date` out of its imports (§0c finding 7). No test imports or patches `_d_plus_1_climate_days` (searched).
      - *The importer.* The function-local import at `strategy.py:308` is re-pointed to `d_plus_1`. It stays function-local, because only its module path changes, and its "Lazy:" comment is updated to say why.
      - *Why it is needed.* Without W5, `on_start` loads `composition` at run time, and through it `order_enablement`, the 8 exec modules, `transport` and `write_transport` (§0c finding 1). W5 is necessary and sufficient for the run-time result (§0c finding 4).
      - *Owner and gates.* The `forecast_quantile_ladder` owner reviews W5, as for W4. W5 is a live-path edit, because the node imports `forecast_quantile_ladder.composition` at boot (`app/trade.py:96`), so every §3.9b gate applies to it.
  - **Withdrawn from r8 on measurement (§0b, finding 5).**
    - M1 (moving `symbology` and its errors into `domain`): it changes nothing in the closure once `fees` stays.
    - M2 (moving `fees`): `fees` is not pure (`fees.py:49` → `parsing`), and it stays as the core of the exception.
    - The lazy `ladder_ev/__init__`.
    - The r8 test `test_moved_names_are_aliases_of_domain_objects` is not written, because its move is not made.
    - The net effect is fewer live-path edits: two `__init__`s, one helper move and two import lines.
  - **The named exception (E-7a rule-2 row text, eval-offline row only).** `E7B_EVAL_OFFLINE_ADAPTER_MODULES` holds ~~11~~ **(r10, R-1) 8** modules:
    - `breezy.adapters` and `breezy.adapters.polymarket_us`: package `__init__`s, lazy after W1.
    - `breezy.adapters.polymarket_us.fees`: the native `BacktestEngine` fee model (F2).
    - `….parsing`, `….errors`, `….redaction`, `….symbology` and `….tape_records`: the import closure of `fees`.
    - ~~`….safety`, `….credentials` and `….secure`: the constant `PERMIT_TTL_NS`, the replay's nominal permit window (`nbp_shadow_parity_pure.py:43,146-155`). It is moved byte-identically under G36.~~ **(r10, R-1) Removed from the exception.**
      - The edit: the module-level `from breezy.adapters.polymarket_us.safety import PERMIT_TTL_NS` at `nbp_shadow_parity_pure.py:43` becomes the first statement of `permit_window_for_day` (:151). Only that import moves. The constant is not re-declared, and no other line of the module changes.
      - The golden replays of §3.9b (6) and (6b) cover the edit. `tests/unit/test_nbp_shadow_parity_pure.py` and `test_nbp_shadow_parity_live.py` stay byte-unchanged and green.
      - **Semantics.** `permit_window_for_day` now reads `safety.PERMIT_TTL_NS` at call time, not at import. The value is the same `Final` constant. The only tests that patch it (`tests/unit/test_nbp_market_comparison.py:292-340`) patch `nbp_market_comparison`'s own `safety` reference, and that module never calls the parity functions. They pass on the §0c copy.
      - **Tests** (`tests/unit/test_r1_permit_ttl_import.py`):
        - `::test_parity_pure_has_no_module_level_safety_import` (AST);
        - `::test_permit_ttl_not_redeclared`: the AST shows no assignment to a name `PERMIT_TTL_NS` and no literal equal to 36 000 000 000 000 in the module;
        - `::test_permit_window_values_equal_head`: `permit_window_for_day`, `permit_covers` and `nominal_permit_expiry_upper_bound`, over every day from 2026-08-30 to 2026-09-25 and a seeded grid of `now_ns`, equal the values captured at the base sha.
    - **(r10, R-1, FH1) A declared run-time deferral that is not part of the exception: `E7B_EVAL_OFFLINE_DEFERRED_PERMIT_TTL` = {`….safety`, `….credentials`, `….secure`}.**
      - The replay calls `permit_window_for_day` before `engine.run()` (§0c finding 3), so these 3 modules load at run time.
      - The run-time closure test admits them only when the recorder attributes the first load of `….safety` to `permit_window_for_day`, or to its G36-moved copy. Any other loader fails the test. **(r11, F3)** Attribution is by the loader frame's module and function, never by frame depth.
      - None of the 3 is an exec, HTTP or WS module. `issue_live_trading_permit` keeps zero callers, and the sandbox has no operator env file.
      - This residual is stated as I-5 (§10).
    - **None of the 8, and none of the 3 deferred modules, can send or mint anything.**
      - None is exec, HTTP or WS.
      - `issue_live_trading_permit` has zero callers in `src/` and `scripts/` (B7; `test_permit_issuer_has_no_caller_in_this_slice`, `tests/unit/test_polymarket_us_readonly_guard.py:1676`).
      - The sandbox has the E-7 credentials tmpfs and no operator env file.
  - **(r9, BL1) Fallback F-1: the explicit fallback for N-1.**
    - **Trigger.** Any one of the following:
      - an owner refuses any of W1–W4, **(r10)** W5 or the R-1 edit;
      - a §3.9b gate fails and cannot be fixed without editing a pinned file;
      - WP1's re-measurement shows, with W1–W4 applied, any exec, HTTP/WS, `factories` or `order_enablement` module, or any adapter module outside the exception. **(r10, FH1)** The measurement is taken with W1–W5 and R-1 applied, at import time and after the golden replays. Any adapter module outside the exception and the declared deferral is a trigger, and so is a non-empty blocker record.
    - **Then:**
      - the eval-offline row is not filed and its timer stays disabled;
      - if any W was merged, it is reverted with `git revert` (explicit paths), followed by a supervisor restart inside the §3.9b window. **(r10, FM1)** The tree revert happens at once, at any hour, because the node reads source at spawn. Only the supervisor restart waits for the window (§3.9b (7));
      - eval-live goes ahead unaffected, because its closure has 0 adapter modules without any cut (§0b, finding 6).
    - **Consequence.**
      - OFFLINE_CHALLENGER, FORWARD_SHADOW and `eval_replay_path` produce nothing, so `eval_completeness` FAILs daily (ALERT).
      - AUT-4 cannot reach score 3, and PROGRESS records "AUT-4 eval-offline blocked: E-7b (b) guard unmet".
      - AUT-4 then asks the coordinator for a ruling and attaches the measured closure.
    - **Never in F-1:**
      - an unsandboxed run;
      - an E-7 narrowing (E-7b rejects it);
      - a widened exception;
      - any edit to an enablement, permit, exec or firewall file.
  - **(r9, BM1) The earlier fork, one sentence per branch.**
    - *E-7b branch (b) without W1–W4 is not safer.* Its own guard cannot pass, because the eager adapter `__init__` loads the venue HTTP and WS clients and `composition` loads `exec.client`. Filing it anyway would admit HTTP/WS and exec into a network-on sandbox, which is the E-7 narrowing that E-7b rejects.
    - *The permit-type seam (a) is not safer than (b) with W1–W4.* It edits the one construction path of the order capability and still leaves exec in the closure.
  - **Coordination with AUT-6 r12 WP5** (which moves `quantile_density` and `location_correction` into `domain`). It touches `ladder_ev`, which r9 no longer edits. WP1 rebases onto it if it lands first, and nothing else interacts.
- **Closure tests (r9 list).** Each test takes the fresh-process `sys.modules` closure of the `eval_offline` and `fs_replay` entry modules, cross-checked by the static walk of AUT-6 r12 §0 (18).
  - **`tests/unit/autonomy/test_closure.py::test_eval_offline_closure_adapter_set_equals_named_exception`.**
    - The `breezy.adapters*` set must equal `E7B_EVAL_OFFLINE_ADAPTER_MODULES` exactly. Growth fails, and shrinkage fails too, so a shrink needs a reviewed commit that narrows the set.
    - It is RED today, with 33 modules.
    - It replaces r8's planned (never written) `test_eval_offline_closure_has_no_adapter_module`, because zero is measured to be unreachable (§0b). The exec guard below stays.
  - **`::test_eval_offline_closure_has_no_adapter_exec_module`.** This is the E-7b guard, kept and strengthened. It asserts:
    - no `breezy.adapters.polymarket_us.exec*` module and no `factories`;
    - no module in the closure defines a `LiveExecutionClient` subclass;
    - none of `http`, `websocket`, `transport` or `write_transport` is loaded, and no other Breezy module defines a venue HTTP or WS client class;
    - **(r9)** `breezy.runtime.order_enablement` is absent;
    - **(r9)** an AST scan of every `breezy` and `scripts` module in the closure finds no call to `issue_live_trading_permit` or `OrderSubmissionPermit.issue`.

    I-3 (the HTTP/WS clause covers venue client modules only, because Nautilus's own `nautilus_pyo3` bindings always load) stands.
  - **`::test_closure_guards_fail_on_head_closure`.** This is the negative control. Both predicates above, applied to the recorded HEAD closure fixture (§0b: 33 adapter modules, 8 exec), must FAIL. So no test can report a clean closure without having been shown a dirty one.
  - **`::test_eval_live_closure_has_no_adapter_module`.** Kept; 0 measured.
  - **`::test_fixture_unit_closure_equals_eval_offline_closure`.** The fixture row runs the same entry modules.
  - **(r10, FH1) Run-time closure tests** (`tests/unit/autonomy/test_closure.py`). Each test runs in its own fresh subprocess, so one test's run cannot leave modules behind for another's snapshot.
    - `::test_eval_offline_runtime_closure_after_golden_replay`:
      - install the recorder (non-blocking mode), import the `fs_replay` entry, run the synthetic golden replay of §3.9b (6), then snapshot `sys.modules`;
      - the adapter set must equal `E7B_EVAL_OFFLINE_ADAPTER_MODULES ∪ E7B_EVAL_OFFLINE_DEFERRED_PERMIT_TTL` exactly;
      - no exec, `factories`, HTTP, WS, transport, `write_transport` or `order_enablement` module may be present;
      - planning value: 8 + 3 (§0c).
    - `::test_eval_offline_runtime_closure_after_sfo_golden`: the same check, after the real-tape golden of §3.9b (6b).
    - `::test_deferred_permit_ttl_load_attributed_to_r1_site`: ~~the recorder's stack for the first load of `….safety` ends in `permit_window_for_day`.~~ **(r11, F3)** In the recorder's stack for the first load of `….safety`, the loader frame is the innermost non-`importlib` frame. That frame must lie within module `nbp_shadow_parity_pure` (its `f_globals["__name__"]`, or the G36-moved copy's module name), with `co_name == "permit_window_for_day"`. The test never asserts an exact frame depth or index, so a Python or `importlib` change in stack depth cannot break it. As a positive control, the test re-runs with `permit_covers` called first, and the attribution must still name `permit_window_for_day` in that module. As a negative control, a synthetic loader that imports `….safety` from a scratch module must fail the predicate.
    - `::test_replay_daily_runner_smoke_runtime_closure_declared`:
      - a fresh-process smoke run of `replay_daily_runner.main` against the golden catalog fixture, with `--max-targets 1`;
      - every path argument (output root, skip-state path, catalog root) points under `tmp_path`, and a precondition asserts that none of them resolves under `$STATE`;
      - the snapshot's adapter set must equal `REPLAY_DAILY_RUNNER_RUNTIME_ADAPTERS`, re-measured at verify-first (planning value: the 15 modules of §0c finding 5), and must hold no exec module and no `order_enablement`;
      - the runner is not an AUT-4 row, so this test pins the runner's own set. It admits none of those modules into eval-offline.
    - `::test_eval_offline_never_imports_or_spawns_replay_daily_runner`: an AST scan of the eval-offline and `fs_replay` closures. It looks for any import of `replay_daily_runner` or `current_rung_hold_paper_replay`, and any `subprocess` argv literal naming either.
    - `::test_runtime_guard_fails_on_pre_w5_closure`: the negative control. The run-time predicate, applied to the recorded W1–W4 run-time fixture (17 adapter modules and `order_enablement`; §0c), must FAIL.
  - **(r10, FH1) The import blocker** (`src/breezy/analysis/autonomy/import_blocker.py`, in the shape of `_FINDER_PREAMBLE`, §2).
    - **What it blocks.** `BLOCKED_PREFIXES` is the FH1 list:
      - `breezy.adapters.polymarket_us.exec` (which also matches `exec_fault`);
      - `….factories`, `….http`, `….websocket`, `….transport` and `….write_transport`;
      - `breezy.runtime.order_enablement`.

      A name matches if it equals a prefix or starts with it.
    - **Where it runs.** `install()` is the first statement of `main()` in both `producers/eval_offline.py` and `producers/fs_replay.py`, before any `breezy.strategy` or `breezy.runtime` import. Each `fs_replay` child is a new process and installs its own blocker. `install()` first checks `sys.modules`, and fails if a blocked module is already loaded.
    - **(r11, F2) Out of scope: `importlib.reload`.** A reload of an already-loaded module does not pass through `sys.meta_path` finders the same way, so the blocker does not claim to cover it. It does not need to: a blocked module can only be reloaded if it is already in `sys.modules`, and the pre-install `sys.modules` check fails the run in that case. No eval-offline or `fs_replay` module calls `importlib.reload` (asserted by `tests/unit/autonomy/test_closure.py::test_eval_offline_closure_has_no_reload_call`, an AST scan of the `breezy` and `scripts` modules in both closures).
    - **How it fails closed.**
      - On a blocked name it appends the name and the importer stack to an in-process record, then raises `ImportError`.
      - The raise only stops the load; detection does not depend on it, because §0c measured that the strategy's L-16 handler swallows it.
      - ~~`assert_clean_or_exit()` checks the record on every exit path: normal return, exception and `atexit`.~~ **(r11, F1)** A `SystemExit` raised inside an `atexit` handler does not change the exit code (measured: `SystemExit(3)` in an `atexit` handler gives exit code 0 on Python 3.13.13; `os._exit(3)` gives 3). r11 therefore gates the output write, not the exit:
        - **Before every write.** Every durable write in `eval_offline` and `fs_replay` (each verdict, each per-station-day `fs_replay` file, the run record's success line) goes through one commit helper. That helper calls `assert_clean_or_exit()` as the statement immediately before `os.replace`, with no import in between. A non-empty record means the temporary file is unlinked and nothing is committed.
        - **At the end of `main()`.** `assert_clean_or_exit()` is the last statement before the verdict commit in `eval_offline.main()` and the last statement of `fs_replay.main()`.
        - **How it exits.** On a non-empty record, `assert_clean_or_exit()` logs the record, delivers the eval-offline CRITICAL (below), flushes `stdout` and `stderr`, and calls `os._exit(EXIT_INTEGRITY)`. Skipped `finally` blocks only leave scratch in the private `/tmp`, which is capped by `--size` and discarded when the unit exits.
        - **The `atexit` backstop.** `install()` also registers an `atexit` handler that calls `os._exit(EXIT_INTEGRITY)` when the record is non-empty, never `sys.exit`. It covers an attempt after the last check and the uncaught-exception path. It is a backstop, not the gate: no output can be committed after a dirty record, because the write gate runs first.
      - If the record is non-empty, the process exits `EXIT_INTEGRITY` and commits nothing after the first recorded attempt; eval-offline writes no verdict for the run. Each file committed earlier was committed under an empty record, and the run record names the `EXIT_INTEGRITY` child. The eval-offline producer delivers a CRITICAL through `deliver_with_proof`, and `eval_staleness` FAILs by 15:25Z.
    - **The tests install it too.** Each `test_eval_offline_runtime_closure_after_*` runs twice, once with the recorder only and once with the blocker. Both runs must end with an empty record.
    - **Tests** (`tests/unit/autonomy/test_import_blocker.py`):
      - `::test_blocker_rejects_each_blocked_prefix`;
      - `::test_blocker_fails_closed_when_import_error_is_swallowed`: the positive control. A child whose `try/except Exception` swallows a blocked import, and then calls the commit helper, must exit `EXIT_INTEGRITY` and write no output. **(r11, F1)** The test asserts both `returncode != 0` and `returncode == EXIT_INTEGRITY`, and that the output path does not exist and the output directory holds no temporary file;
      - **(r11, F1)** `::test_atexit_backstop_sets_exit_code`: a child records a blocked attempt after its last check and returns normally. It must exit `EXIT_INTEGRITY`, and no output file may exist;
      - **(r11, F1)** `::test_systemexit_in_atexit_does_not_set_exit_code`: the reason for the design, as a pinned fact. A child whose `atexit` handler raises `SystemExit(EXIT_INTEGRITY)` exits 0. If a future Python changes this, the test fails and the design is re-reviewed;
      - **(r11, F1)** `::test_blocker_never_calls_sys_exit`: an AST check that `import_blocker` has no `sys.exit` call and no `raise SystemExit`, and that its exit path is `os._exit`;
      - **(r11, F4)** `::test_no_live_entry_installs_or_references_blocker`. For each module of `LIVE_ENTRIES` (§3.9b (2)), in a fresh process: after the import, `breezy.analysis.autonomy.import_blocker` is not in `sys.modules`, and `sys.meta_path` holds no instance of the blocker's finder class. An AST scan of every `breezy` and `scripts` module in that closure finds no import of `import_blocker` and no reference to `sys.meta_path`. As a positive control, the same predicate applied to the `eval_offline` entry must FAIL;
      - `::test_install_refuses_preloaded_blocked_module`;
      - `::test_blocker_installed_first_in_eval_offline_and_fs_replay_entries`: an AST check that `install()` is the first statement of each `main`;
      - `::test_golden_replays_under_blocker_record_nothing`.
    - **Lint.** The read-only lint admits `import_blocker` as one judged `importlib.abc` site.
  - **Interpretation I-4** (for the peer loop; see §10). E-7b's branch (a) says that the symbology helpers "move ... with delegating shims". r9 does not perform that move, because §0b shows the shimmed module stays in the closure through `fees` → `parsing` under the (b) exception, so the move would add live-path churn for no closure gain. ER-2 asks for one clarifying sentence. **(r10, R-3)** ER-2 is now ruled AMEND, and its ruled text is in §10. I-4 is closed by that text, under the conditions it states.

**(r8, AH4) The quarantine bind, resolved read-only from `replay_daily_runner`.**
- **No oversize quarantine exists today.** At `f45f5a65` the runner's only quarantine is `_quarantine_fee_void_output_dir` (`scripts/analysis/replay_daily_runner.py:1132-1149`). It renames a fee-void output directory to a sibling `lag_<n>.fee_void.<stamp>` under `--output-root`'s `paper_replay/scored_trials/v3/<station>/<day>/` (`:1115-1122`). AUT-4 neither reads nor writes it.
- **The oversize quarantine is AUT-4's own WP3 deliverable** (r2 E17: append-only, one file per consumer). It sits where the runner keeps its replay state, `_DERIVED_ROOT / "replay"` (`:187-197`), i.e. `$STATE/derived/replay/`.
- **The bind** is the dedicated directory `$STATE/derived/replay/oversize_quarantine/`. It holds two files:
  - `eval_offline.jsonl`, written by eval-offline;
  - `replay_daily.jsonl`, written by the runner after WP3's edit. eval-offline only reads it.
- **Binding `$STATE/derived/replay/` itself is rejected:** it would make `replay_sufficiency.jsonl`, `replay_results.jsonl`, `replay_drift.jsonl` and `wrapper_skip_state` writable from inside the sandbox.
- **Setup.** WP3 creates the directory 0700 outside the sandbox before the row is filed. The read-only lint admits exactly one write site in it: `tape_admission.quarantine_oversize`, which opens `eval_offline.jsonl` in append mode.
- **Fail-closed.** If the directory is missing at unit start, bwrap cannot set up the bind and exits non-zero before the producer runs. The unit fails, `OnFailure=breezy-autonomy-failed@%n` delivers a CRITICAL, no verdict is written, and `eval_staleness` FAILs by 15:25Z. Test `tests/integration/autonomy/test_aut4_bwrap_rows.py::test_missing_bind_source_fails_unit_before_producer`, run on temporary trees.
- WP6 verify-first re-checks the path.

**(r8, E-7c, AH3) Private `/tmp` on every row.**
- **Why.** `--ro-bind / /` leaves `/tmp` read-only, so Nautilus, pyarrow and `tempfile` scratch writes would fail. Every AUT-4 row therefore gets `--tmpfs /tmp` and `TMPDIR=/tmp` from the shared wrapper.
- **Scratch only.** This space is private, discarded at exit, and never a path for durable state.
- **Durable writes stay in their bind.** A `tmp + rename` from `/tmp` into a bind would fail with `EXDEV` (AUT-6 r9 CA-1). Every AUT-4 writer therefore passes `dir=` set to the final directory, as `replay_sufficiency.py:1000` and `hypothesis_ledger.py:1361` already do. Lint `tests/unit/autonomy/test_aut4_readonly_lint.py::test_writers_mkstemp_in_final_dir` enforces it.
- **Memory.** tmpfs pages are charged to the unit's memory cgroup, so `fs_replay` scratch counts against eval-offline's `MemoryHigh`/`MemoryMax` (§3.12: S includes T; **(r9, BL1)** now bounded by the cap below).
- **(r9, BL1) Numeric cap.**
  - **The flag.** Each row's scratch is `--size <bytes> --tmpfs /tmp`. bwrap's `--size` applies to the next `--tmpfs`, and §0b verified it on host bwrap 0.11.1.
  - **The values.**
    - eval-offline: `EVAL_OFFLINE_TMPFS_BYTES` = 2 GiB = 2147483648.
    - The fixture row: the same value, because it runs the same closure.
    - eval-live: `EVAL_LIVE_TMPFS_BYTES` = 128 MiB = 134217728.
  - **Where the values live.** They are pinned in `budget.py` and carried as a per-row `tmpfs_size_bytes` in `AUTONOMY_BWRAP_TABLE` (ER-1). ~~A row without the value fails closed.~~ **(r10, R-2)**
    - Every AUT-4 row carries its value explicitly.
    - A row filed by another plan with no `tmpfs_size_bytes` gets the wrapper's default cap, `DEFAULT_TMPFS_SIZE_BYTES`, so no other plan's row breaks. The wrapper owner sets the default. AUT-4 does not depend on it.
    - Only a malformed value fails closed: one that is not an `int`, is ≤ 0, or is above the wrapper's maximum.
  - **Overflow is fail-closed.** The child gets `ENOSPC`, and then:
    - that station-day's output is not committed, because outputs are atomic per file;
    - the child exits non-zero, and the run record names it;
    - `eval_completeness` and `eval_replay_path` see the gap.
  - **Tests.**
    - `tests/integration/autonomy/test_aut4_bwrap_rows.py::test_tmpfs_cap_enforced_enospc`, per row: writing cap + 1 byte fails with `ENOSPC`. As a positive control, a write of cap / 2 succeeds.
    - `tests/unit/autonomy/test_fs_replay.py::test_child_scratch_enospc_commits_nothing`.
- **(r9, BM1) E-7c ownership becomes a sequenced build gate.** Each step requires the previous step's evidence:
  1. The wrapper owner merges `deploy/systemd/breezy-autonomy-bwrap` with `--tmpfs /tmp`, `TMPDIR=/tmp` and the per-row `--size` (ER-1). The wrapper's own `test_bwrap_wrapper_provides_private_tmp` must be green at that merge sha, with its pytest output in the merge evidence.
  2. The deployed wrapper is the merged blob. The output of `sha256sum /home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap` must equal that of `git -C /home/jon/breezy show <wrapper_merge_sha>:deploy/systemd/breezy-autonomy-bwrap | sha256sum`.
  3. Only then is any AUT-4 row filed: eval-live in WP4, eval-offline and the fixture row in WP6. Each row needs `test_each_aut4_row_has_private_tmp` and `test_tmpfs_cap_enforced_enospc` green.
  4. Only then is any AUT-4 timer enabled.

  Contract test `tests/contract/test_autonomy_units.py::test_aut4_rows_require_wrapper_private_tmp` checks two things:
  - every AUT-4 row in the table carries `tmpfs_size_bytes` equal to its `budget.py` constant;
  - the wrapper source passes `--size`, `--tmpfs /tmp` and `TMPDIR=/tmp`.
  - **(r10, R-2)** `::test_wrapper_applies_default_tmpfs_size_to_rows_without_one`: a synthetic row without `tmpfs_size_bytes` builds an argv with `--size <DEFAULT_TMPFS_SIZE_BYTES>` immediately before `--tmpfs /tmp`.
  - **(r10, R-2)** `::test_wrapper_malformed_tmpfs_size_fails_closed`: each of `"2G"`, `0`, `-1`, `True` and a value above the maximum exits non-zero before `bwrap` runs.

  The order is evidenced by `git merge-base --is-ancestor <wrapper_merge_sha> <row_filing_sha>` exiting 0 (§6.4 row 11, §7).
- **Cleanup.** Each child removes its scratch directory in a `finally`, following `replay_daily_runner.py:1639-1642`.
- **Tests.**
  - `tests/integration/autonomy/test_aut4_bwrap_rows.py::test_each_aut4_row_has_private_tmp` checks E-7c's three assertions on each of the three rows: a write under `/tmp` succeeds, the file is not visible on the host, and `$STATE/registry/` still returns `EROFS`.
  - `tests/unit/autonomy/test_fs_replay.py::test_child_scratch_dir_removed_on_success_and_failure`.
- **Ownership.** The wrapper's own `test_bwrap_wrapper_provides_private_tmp` belongs to the wrapper owner. AUT-4 consumes it and does not restate it.

**(r8, LOW-2) Fixture-row probe test.** `tests/integration/autonomy/test_aut4_bwrap_rows.py::test_fixture_row_positive_and_negative_probes`.
- **Setup.** The test builds the fixture row's argv from `AUTONOMY_BWRAP_TABLE`, mapping `$STATE` and the fixture root to two temporary trees through the wrapper harness's root substitution (the substitution the E-7a wrapper test uses; AUT-4 requests it from the table owner if it is missing). It then runs a probe child through the wrapper.
- **Positive probes.** Files created under the fixture root's `derived/verdicts/`, `evidence/engine_inputs/fixture/` and cache directories exist afterwards.
- **Negative probes.** Creating a file under `$STATE/derived/verdicts/`, `$STATE/registry/`, `$STATE/evidence/engine_inputs/` or `$STATE/derived/autonomy/fs_replay/` fails with `EROFS` and leaves no entry.
- **Positive control.** The same negative probe, run with the production verdict directory deliberately added to the bind set, must succeed. This proves the negative probes are not passing vacuously.

**E-7a rule 3 / E-8a: WAL reads.** WP6 verify-first lists every SQLite input of both producers with its `journal_mode`. A WAL-mode input is read only through the shared E-8 snapshot helper with `take_flock=False` into the row's 0700 cache (E-8a: AUT-4 never takes the intent flock; such reads are advisory where E-8a says so, and none feeds an engine widening). Rollback-journal stores (C5) use `mode=ro` + `PRAGMA query_only=ON`. Production AUT-4 units never read the exec store; WP0's one-off exec-store baseline read uses the helper with `take_flock=False`. Tests, if any WAL input exists: `tests/integration/autonomy/test_aut4_wal_reads.py::test_wal_input_read_sidecars_present_under_bwrap`, `::test_wal_input_read_sidecars_absent_under_bwrap`.

**E-7 rule 3 and E-7a rule 4: the read-only lint.** `tests/unit/autonomy/test_aut4_readonly_lint.py::test_aut4_entry_closures_have_no_unlisted_write_sites` walks the `eval_live`, `eval_offline`, `fs_replay` and `run_record` entry closures and fails on write-mode `open`, `sqlite3.connect` without `mode=ro`, `SqliteStateStore(`, `subprocess`, `os.system`, `ctypes` or `importlib` outside each unit's one-writer rows (the verdict writer, the `fs_replay` output writer, the run-record and feasibility writers, and the one judged `subprocess` site, `subprocess_rss.run_child`, and **(r9, BH2)** the two judged `importlib.import_module` sites, the W1 and W2 lazy `__getattr__`s, which import only names in their frozen `_LAZY` maps (pinned by `test_lazy_map_equals_head_eager_import_map`, §3.9b)); `::test_lint_non_vacuous_min_judged_sites` (≥ 1 judged site per entry point); `::test_lint_positive_controls_fire` (an injected write-mode `open` and an injected `subprocess` call each fail it). It is a lint, green at build; its completeness is not a READY criterion once `test_every_aut4_unit_execstart_and_onfailure_target_goes_through_wrapper` passes.

**E-7 rule 1: directives are configuration.** r6 claims no sandbox directive as a control and has no test that parses one (verified: r6 cites none of `ReadOnlyPaths`, `ReadWritePaths`, `ProtectHome`, `ProtectSystem`, `PrivateTmp`, `InaccessiblePaths`). Any such test added at build is named `*_config_*`. The unit-file tests of §3.9 parse `OnCalendar`, `TimeoutStartSec`, locks and slices, which are not sandbox directives, and keep their names.

**E-9: per-command bounds.** Each unit has one `ExecStart=` and one `ExecStopPost=`; the wrapper is a prefix, not a command.
- `eval-offline`: `ExecStart=timeout -k 20s 6270s flock -w 900 <studies lock> breezy-autonomy-bwrap breezy-autonomy-eval-offline …`; bound 6270 + 20 = 6290 s ≤ `TimeoutStartSec` 6299. The internal deadline `unit_start + EVAL_OFFLINE_TIMEOUT_START_S − SAFETY_S` = +5999 s stays 271 s inside the external bound, so the §3.12 budget (3599 s replay, 899/449 s children) is unchanged.
- `eval-live`: `timeout -k 20s 1470s flock -w 300 …`; 1490 s ≤ 1500.
- `ExecStopPost=`: `timeout -k 5s 50s breezy-autonomy-bwrap …`; 55 s ≤ `TimeoutStopSec` 60.
- Worst ends are unchanged (12:46:00 and 15:11:01 including `TimeoutStopSec`), because each command's bound sits inside the unit bound the r6 arithmetic already used; the 10–50 ms wrapper setup is re-checked, not re-derived (E-7a rule 5). `test_offline_successor_lands_before_predecessor_expiry` keeps its r5 inequality unchanged.
- Tests `tests/contract/test_autonomy_units.py::test_aut4_every_start_command_bounded_by_timeout_k`, `::test_aut4_sum_of_command_bounds_inside_unit_bounds`, `::test_internal_deadline_inside_per_command_bound`, `::test_every_aut4_unit_execstart_and_onfailure_target_goes_through_wrapper`, `::test_aut4_lock_order_timeout_flock_wrapper`.

**E-10.** (a) concerns the one-time L1 bootstrap; AUT-4 has no unit in it. (b) moves the 16:47:30 intraday pass's lock-timeout end to 16:48:01 (worst ≤ 16:49:50). AUT-4's units end by 12:46:00 and 15:11:01, and `eval_staleness` is a pure read of the C4 store inside AUT-6's intraday pass, so no AUT-4 row or bound moves.

### 3.9b (r9, BH2) Live-path gates for W1–W4 (r10: and W5)

W1–W4 touch modules that the node, the supervisor and the recorder import. Every gate below is RED-first and characterisation-based:
- the golden fixtures are captured at WP1's base sha, in one commit made before any W edit;
- they are never regenerated by WP1.

**(1) Exec-client sha pin and no-diff check.** The pin reuses the SL-13 pattern in `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py:22-36,114-121`:
- `_REPO_ROOT = Path(__file__).resolve().parents[2]`;
- `hashlib.sha256(path.read_bytes()).hexdigest()` is compared with a module constant;
- a failure carries the "re-verify with a real reviewer before ever updating this pin" message.

It is built as follows:
- **Test.** `tests/unit/test_wp1_live_path_pins.py::test_no_send_and_permit_files_byte_identical` is parametrised over the pinned files below. The values are as measured at `f45f5a65` with `sha256sum`.

  | File | sha256 |
  |---|---|
  | `src/breezy/adapters/polymarket_us/exec/client.py` | `76784ce814797bfb5480487ff0dad47cbe9c0b1727aef9ad1c7461cc33aa68a4` |
  | `src/breezy/adapters/polymarket_us/exec/submit_chain.py` | `14cec6e86fd1316344689a0ce46bfb840f9333da1563727929df7051c5db719c` |
  | `src/breezy/adapters/polymarket_us/exec/endpoints.py` | `de83465aa349383f5da8fe0ebcb868bf17fefe66ad3ceae8cfe4474a8272b36b` |
  | `src/breezy/runtime/order_enablement.py` | `4638e2c80e54ce566c9f08ab7e715b05ca7f40fc2bbfd5954fab36ab64f536b5` |
  | `src/breezy/adapters/polymarket_us/safety.py` | `c70e2dd2d70a743144351feb3b3a0c5115c272c9438e8918bf4da57186177653` |
  | `src/breezy/adapters/polymarket_us/operator_controls.py` | `d23a5434abe91b38c7a5125148db1645d887442a44a75af1be8fb2dc4f3c6e3b` |
  | `src/breezy/adapters/polymarket_us/write_transport.py` | `bd0cc5ac616e7e7c75dc22bf8a364dae5f38352fe873131b909c75da83ead296` |
  | `tests/unit/test_execution_egress_firewall_guard.py` | `129661102ec01f095216198f63cd77cd7c48e24d7c0bcf322f0e73640c077dee` |
  | `tests/unit/test_polymarket_us_readonly_guard.py` | `2e6faa1efe9f10c01e430d472b11ba43e7c8c44707d9fcda61223a41f6e6babe` |
  | `tests/unit/test_polymarket_us_package_exports.py` | `20c949a858cea423ad4ae0377ec6b34bdb79f3348c1981e5a6ac27a8d44640be` |

- **Agreement with the existing pin.** `::test_exec_client_pin_agrees_with_sl13_pin` imports `_EXEC_CLIENT_SHA256` from the SL-13 module and asserts that it equals this table's value, so two pins of one file can never diverge.
- **If a pinned file changes before WP1 starts.** Another reviewed commit may change one of these files between `f45f5a65` and WP1's base. In that case WP1's verify-first re-captures the values at its base sha and records them in the brief. WP1 itself never edits a pinned file or a pin.
- **No-diff gate.** `git -C <tree> diff --exit-code <wp1_base_sha> HEAD -- <the 10 paths above>` must exit 0 with empty output. The line is pasted into the merge evidence.
- **The existing firewall tests** run unchanged and green: the `test_execution_egress_firewall_guard.py` N1–N4 and E0–E3 tests, B7, B11 and `PERMANENTLY_UNEXPORTED`.

**(2) Boot smoke on every live entry: fresh process, eager resolution, identical classes.** The tests live in `tests/unit/test_wp1_live_entry_boot_smoke.py`.
- **The entries.** `LIVE_ENTRIES` = (`breezy.app.trade`, `breezy.runtime.trade_supervisor`, `breezy.runtime.quote_tape_cli`, `breezy.runtime.quote_tape_ingest_cli`, `breezy.runtime.quote_tape_preflight_cli`, `breezy.runtime.exec_state_db_path`). These are:
  - the node, recorder, ingest and preflight console scripts (`pyproject.toml:343,349,355,363`);
  - the supervisor (`pyproject.toml:400`; `deploy/systemd/breezy-trade-supervisor.service:139`);
  - the exec-store path guard that the deployed wrappers run.

  `::test_live_entries_subset_of_stage0` asserts `LIVE_ENTRIES ⊆ STAGE0_ENTRY_MODULES`.
- **`::test_live_entry_exports_resolve_eagerly_with_head_identities[entry]`.** One fresh `subprocess.run([sys.executable, "-c", PROBE], cwd=<tree>, timeout=120)` per entry, in the T9 shape (`test_runtime_import_isolation.py:464-474`). The probe:
  - imports the entry;
  - for each of the two lazy packages, calls `getattr` on every `__all__` name and every HEAD-bound submodule name. An `ImportError` therefore surfaces at boot in the gate, never at first use in production;
  - prints `{name: "module.qualname"}`, plus an `is` check of each object against `getattr(importlib.import_module(defining_module), attr)`.

  The test asserts equality with `tests/fixtures/wp1/live_entry_identities_<base12>.json`, captured at the base sha by the same probe. The planning-time measurement (§0b) found 0 mismatches.
- **`::test_function_local_package_imports_resolve`.** The one function-local package import (`set_family_halt_cli.py:323`, `from breezy.adapters.polymarket_us import factories`) resolves to `sys.modules["breezy.adapters.polymarket_us.factories"]` in a fresh process. The test also re-scans `src/` and `scripts/` and fails on any new function-local `from <lazy pkg> import` that is not listed.
- **(r10, FM1) Run against the deployed tree before the restart.** After the merge, and before step 3 of (7), the coordinator runs this file together with (3) and (4), from the primary tree that the node and the supervisor import:

  `cd /home/jon/breezy && PYTHONPATH=/home/jon/breezy/src BREEZY_PYTHON=/home/jon/breezy/.venv/bin/python scripts/ci/run_tests_no_egress.sh tests/unit/test_wp1_live_entry_boot_smoke.py tests/unit/test_wp1_arrow_registration_parity.py`

  The coordinator reads `EXIT=0`. A green run in a worktree says nothing about the deployed tree.

**(3) `sys.modules` and Nautilus config-type diff (PM MED).** The test is `::test_live_entry_module_and_config_delta_is_declared[entry]`, in the same fresh process.
- **What it compares.** The `breezy*` module set and the set of transitive `NautilusConfig` subclasses, both as `module.qualname`, against `tests/fixtures/wp1/live_entry_modules_configs_<base12>.json`.
- **What may differ.** Only `WP1_DECLARED_LIVE_DELTA`. Planning value (§0b):
  - node: +`breezy.strategy.current_rung_hold.instrument_buckets`, and **(r10, W5)** +`breezy.strategy.forecast_quantile_ladder.d_plus_1` (measured, §0c finding 6);
  - ingest: −33 `breezy*` modules, and −3 config types (`PolymarketUSDataClientConfig`, `PolymarketUSExecClientConfig`, `PolymarketUSSecretsRefConfig`);
  - every other entry: ∅.
- **How the delta is fixed.** WP1's verify-first re-measures it, and the declared delta must equal the measurement exactly.
- **Ingest.** `::test_ingest_never_references_dropped_config_types` is an AST scan of the ingest entry closure.

**(4) Arrow-registration parity.** The tests live in `tests/unit/test_wp1_arrow_registration_parity.py`.
- **What registers today.** Module-scope `register_arrow(` calls sit in:
  - `src/breezy/domain/forecast_point.py:675`, `station_observation.py:254`, `nws_climate_day.py:388`, `archived_raw_product.py:252`, `nws_raw_product.py:332` and `archived_climate_day.py:413`;
  - `src/breezy/strategy/current_rung_hold/monitor_records.py:249`;
  - `src/breezy/adapters/polymarket_us/tape_records.py:629-637`;
  - Nautilus's own `customdataclass` types (`greeks_data`).
- **`::test_arrow_registrations_per_entry_equal_head[entry]`.**
  - It runs over all 35 `STAGE0_ENTRY_MODULES`, imported from `test_runtime_import_isolation.py`, never copied.
  - It runs one fresh process per entry and compares the keys of `nautilus_trader.serialization.arrow.serializer._SCHEMAS`, as `module.qualname`, with `tests/fixtures/wp1/arrow_registrations_<base12>.json`.
  - **Every live entry must be strictly equal.** No allowance exists for them, and the planning measurement found them all equal.
  - An offline entry must be equal except for the pairs in `WP1_INTENDED_ARROW_LOSSES`. That set is closed and exact, re-measured at verify-first. Its planning value is the 8 entries and their types in §0b.
- **`::test_intended_arrow_losses_never_referenced`.** For each listed pair, no `breezy` or `scripts` module in that entry's fresh-process closure references the type: no `Name`, `Attribute` or import alias of its name.
- **`::test_intended_arrow_losses_exact_set`.** A listed loss that no longer occurs also fails, so the list cannot rot.
- **(r10, FL1) The reference test is widened.** `::test_intended_arrow_losses_never_referenced` also fails on two more kinds of reference:
  - a string literal equal to the type's name or its `module.qualname`, whether used as a `DataType` name, a catalog path segment or a `query("…")` argument;
  - a `data_cls=` keyword argument, or the first argument of `DataType(…)` or `catalog.query(…)`, that resolves to the type.

  As a positive control, `catalog.query(data_cls=QuoteTapeGap)` and the literal `"QuoteTapeGap"` are injected into a fixture module, and each must fail the test.
- **(r10, FL1) New entries.**
  - WP6 creates `breezy.analysis.autonomy.producers.eval_offline` and `breezy.analysis.autonomy.producers.fs_replay`, and appends both to `STAGE0_ENTRY_MODULES` in `tests/unit/test_runtime_import_isolation.py`. The edit only appends. `::test_stage0_tuple_head_entries_unchanged` asserts that the 35 HEAD entries are still present, unchanged and in order.
  - `::test_closure_referenced_arrow_types_registered[entry]` runs on both new entries. It collects every Arrow-serialisable type the entry's closure references, using the matcher above (`Name`, `Attribute`, string literal or `data_cls`). It does so after import and again after the golden replay, and each time asserts that every collected type is a key of `_SCHEMAS`.
- **(r10, FL1) Golden-catalog smoke of the 8 offline scripts.** The test is `tests/unit/test_wp1_offline_scripts_golden_catalog_smoke.py::test_offline_script_runs_on_golden_catalog[script]`.
  - It runs each of the 8 scripts in `WP1_INTENDED_ARROW_LOSSES` in a fresh process, under the no-egress gate, against a `tmp_path` copy of `tests/fixtures/wp1/golden_catalog/`.
  - That catalog holds one row of each lost type (the 4 `tape_records` types, `PositionMarkRecord` and the 3 Greeks types) plus the SFO slice of (6b).
  - Pass condition: the script's documented success or no-data exit code, and no Nautilus serializer `TypeError` or `KeyError` on stderr.
  - WP1 verify-first records each script's read-only invocation. A script that cannot run read-only on a fixture is listed by name with the reason, and gets an import-plus-catalog-read smoke instead.
- **Why an exact allowance is enough** (a refinement of BH2, see §R9):
  - Nautilus fails loudly on an unregistered type at catalog read or write (`runtime/__init__.py:47-51`, citing `serializer.py` `TypeError` and `KeyError`). Nothing degrades silently.
  - Re-registering inside the lazy `__init__`s was simulated and rejected (§0b, E2r).
  - Adding unused imports to 8 scripts would buy nothing a test can observe.

**(5) Lazy `__getattr__` tests.** These live in `tests/unit/test_lazy_package_inits.py`, which extends r8. Each test runs on both W1 and W2, in a fresh process.
- `::test_lazy_map_equals_head_eager_import_map`: `_LAZY` equals the `ImportFrom` name map of the HEAD `__init__`, read from `git show <base>:<path>` and recorded in `tests/fixtures/wp1/lazy_pkg_head_<base12>.json`. The maps hold 61 names for the adapter package and 24 for `current_rung_hold`.
- `::test_lazy_package_inits_return_identical_objects` (r8): every `__all__` name resolves to the same object as its defining module's attribute.
- `::test_non_export_raises_attribute_error`:
  - `getattr(pkg, "issue_live_trading_permit")` raises `AttributeError`;
  - `not hasattr(pkg, name)` holds for every entry of `PERMANENTLY_UNEXPORTED`, imported from `tests/unit/test_polymarket_us_package_exports.py:86`;
  - a random absent name also raises `AttributeError`, and the message names the module.
- `::test_dir_equals_head`: `sorted(dir(pkg))` after a cold import equals the HEAD golden, measured at 96 names for the adapter package and 41 for `current_rung_hold`.
  - `__dir__` returns the module globals, minus the private names `_LAZY`, `_HEAD_SUBMODULES`, `_importlib`, `__getattr__` and `__dir__`, united with `_LAZY` and `_HEAD_SUBMODULES`.
- `::test_import_star_equals_head`: `from pkg import *` binds exactly `__all__` (61 and 24 names), each identical to its HEAD object.
- `::test_head_bound_submodules_resolve_as_attributes`:
  - for the 25 adapter submodules and the 6 `current_rung_hold` submodules that a cold HEAD import binds, `getattr(pkg, sub) is sys.modules[f"{pkg.__name__}.{sub}"]`, with the submodule imported on demand;
  - any other submodule name raises `AttributeError` until it is imported, which is today's behaviour too.
- `::test_no_pkg_dot_submodule_attribute_use`: an AST scan of `src/`, `scripts/` and `tests/` for `import <lazy pkg> [as X]` followed by an `X.<submodule>.` attribute chain.
  - Planning value: two aliased imports exist (`tests/unit/test_polymarket_us_package_exports.py:24`, `tests/unit/test_polymarket_us_fee_model.py:487`). Both read only `__all__` names.
  - Every other dotted reference is in a docstring.
- `::test_lazified_inits_have_no_side_effect_statements` (r8, AST): each lazy `__init__` holds only the docstring, `from __future__`, the `_LAZY` and `_HEAD_SUBMODULES` literals, `__all__`, and the two functions. §0b's precondition check passed on both packages.
- `::test_reload_keeps_identity`: `importlib.reload(pkg)`, which is the path `test_the_package_imports_cleanly_from_a_cold_module_cache` uses, keeps every resolved name identical.

**(6) Golden replay.** The test is `tests/unit/autonomy/test_wp1_golden_replay.py::test_run_live_parity_output_byte_identical_across_wp1`.
- **Fixture.** The synthetic mini-tape of `tests/unit/test_nbp_shadow_parity_live.py`, driven by its `_run_live` helper (:295-307). The test imports it and does not edit that file.
- **Run.** A fresh subprocess.
- **Serialisation.** The returned `tuple[DecisionKey, ...]` (`DecisionKey` is a frozen dataclass, `nbp_shadow_parity_pure.py:224-225`) is written as `json.dumps([dataclasses.asdict(k) for k in keys], sort_keys=True, default=str)`. The live-against-batch `ParityReport.to_counts_dict()` is serialised the same way.
- **Golden.** The sha256 of those bytes is captured once, before any WP1 edit, in `tests/fixtures/wp1/fs_replay_golden.sha256`.
- **Three runs must match it:**
  - the script `scripts.analysis.nbp_shadow_parity.run_live_parity`, at the base sha (the capture);
  - the moved `breezy.analysis.autonomy.shadow_replay.run_live_parity`, after the G36 move and W1–W4;
  - the script wrapper, after W1–W4.
- **Positive control.** `::test_golden_hash_sensitive_to_a_decision_change`: the same probe with `fee_coefficient` changed must produce a different hash.
- **(r10, R-1)** The three runs straddle the R-1 edit, so the golden also pins it.
- **(r10, FH1)** Each of the three runs also writes its post-run `sys.modules` adapter set, and `test_eval_offline_runtime_closure_after_golden_replay` checks it (§3.9a).

**(6b) (r10, FM5) Real-tape golden through `backtest_harness`.** The test is `tests/unit/autonomy/test_wp1_golden_replay.py::test_sfo_2026_09_01_output_byte_identical_across_wp1`.
- **Fixture.** It is captured once, in the RED-capture commit, from the quote-tape catalog `/home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us/data/`. It holds:
  - the `binary_option` definitions and the `order_book_depths` rows of the 6 `tc-temp-sfohigh-2026-09-01-*` instruments (1.5 MB on disk at planning);
  - the NBP forecast points those decisions read;
  - the deployed calibration artefact, identified by sha.

  These are written with the native `ParquetDataCatalog` into `tests/fixtures/wp1/sfo_2026-09-01/`, together with a `SHA256SUMS` file.
- **Reads.** The capture reads production read-only. The test never reads `$STATE`. If the slice exceeds 5 MB, verify-first narrows it to the decision window and records the cut.
- **Why this slice.** SFO 09-01 is the one clean tape day (tape audit 2026-09-10), and it lies inside the pre-freeze window that `assert_pre_freeze_tape_day` admits.
- **Path.** The test loads the fixture with the script's own catalog loader (`nbp_shadow_parity.py:512`), which is the native catalog decode, and then runs `run_live_parity`. That builds the native `BacktestEngine` through `backtest_harness.build_backtest_engine`, with `PolymarketUSFeeModel` (`backtest_harness.py:153`, the F2 fee path). Output is serialised as in (6).
- **Runs.** The same three runs as in (6), each in a fresh subprocess, must match `tests/fixtures/wp1/sfo_2026-09-01_golden.sha256`.
- **Positive control.** `::test_sfo_golden_sensitive_to_fee_coefficient`. Verify-first picks a fee change that flips at least one decision key on this slice, and with it the hash must change. If no fee change flips a key, a slippage change is used instead, and the brief records which.

**(7) Supervisor restart and the scripted permit-line check.**
- **Why a restart is needed.**
  - The supervisor imports the adapter package once at start: `trade_supervisor` → `exec_state_db_path.py:40` → `factories`, and §0b found 33 adapter modules in its closure. So W1 is live in the supervisor only after a restart.
  - The node picks up W1–W4 at its next spawn.
  - The recorder and ingest pick them up at their next scheduled restart. Their probes found 0 identity and 0 Arrow differences, so no forced restart is planned.
- **Window.** Merge and restart only inside [01:00Z, 16:40Z) and never inside [16:30Z, 17:10Z):
  - after the MIDDAY_WATCH close and before STOP_PRIOR;
  - this follows the binding operational note "supervisor changes need a supervisor restart".
- **The node survives the restart.** `KillMode=process` (`deploy/systemd/breezy-trade-supervisor.service:151-163`) signals only the supervisor. The node keeps running and is adopted.
- **Steps.**
  1. Run the full gate on the merge sha and read `EXIT=0` before pushing.
  2. Record the current node pid from `$STATE/logs/breezy-trade-supervisor.log` (`trade_supervisor.py:801-802`; log dir `:2479`): take the newest `launch_*` or `*_adopted_live_node pid=` line.
  2a. **(r10, FM1)** Run the boot smoke against the deployed tree, as in (2), and read `EXIT=0`. Do not restart without it.
  3. Run `systemctl --user restart breezy-trade-supervisor.service`.
  4. Within 5 minutes, all of the following must hold:
     - `systemctl --user is-active breezy-trade-supervisor.service` prints `active`;
     - the supervisor log has `permit_watch_adopted_live_node pid=<recorded pid>` (`trade_supervisor.py:2068`);
     - the node pid is unchanged.
  5. **Positive control.** Run `PYTHONPATH=/home/jon/breezy/src /home/jon/breezy/.venv/bin/python /home/jon/breezy/scripts/ops/permit_line_check.py --log-dir /home/jon/.local/share/breezy/logs --pid <pid>` against the adopted node's log. It must report that node's boot permit status (exit 0). This proves the checker reads the right file before the result that matters.
  6. After the first node boot spawned by the restarted supervisor (normally 16:50Z), run `… permit_line_check.py --log-dir /home/jon/.local/share/breezy/logs --since <restart_utc>`. The expected output is one of:
     - exit 0 and `ISSUED issued_at_ns=<n> expires_at_ns=<n> ttl_s=<n>`, with the expiry in the future;
     - exit 0 and `NOT_REQUESTED`, when orders are not requested (for example under the A1 halt). This is recorded as such and never as proof of capability.
  7. **On any failure, revert.** Failures are: no adoption line; a changed pid; checker exit ≠ 0; or a `permit_absent_in_decision_window` CRITICAL that the node log does not explain (the self-check lesson). ~~Then: `git revert` the WP1 merge, by explicit paths; re-run the gate; repeat steps 3–4 inside the window.~~

     **(r10, FM1) The tree revert is immediate. Only the restart waits for the window.** The first boot after the restart is normally at 16:50Z, outside the window, so a step-6 failure usually comes outside it. Then:
     - **At once, at any hour:** `git revert` the W commits and the R-1 commit in the primary tree, by explicit paths. The node and its mid-day relaunches read source at spawn, so the next spawn takes the reverted code without any restart.
     - Prove that the revert restores the base: `git -C /home/jon/breezy diff --exit-code <wp1_base_sha> HEAD -- <W1–W5 and R-1 paths>` must exit 0, which shows the tree equals the gate-green base for those paths.
     - Run the full gate on the revert sha, and read `EXIT=0` before any push (the read-gate-before-push lesson).
     - The supervisor keeps running the W1 code it loaded. W1 preserves object identity (§3.9b (2)), so this does not block the revert. Restart the supervisor (steps 2a–5) inside the next [01:00Z, 16:40Z) window.

     AUT-4 never signals the node.
- **The check script, `scripts/ops/permit_line_check.py`** (new, read-only, stdlib plus `breezy.runtime.trade_supervisor_core` and `trade_supervisor`).
  - **File selection.** It selects node logs with `trade_supervisor.find_adopted_node_log` (`--pid`), or by the `_NODE_LOG_NAME_RE` shape and mtime ≥ `--since`.
  - **Parsing.** It parses with `PERMIT_ISSUED_MARKER`, `PERMIT_NOT_ISSUED_MARKER`, `PERMIT_NOT_REQUESTED_MARKER`, `parse_permit_expiry_ns` and `permit_expiry_valid`.
  - **Exit codes.**
    - 0: a valid ISSUED line, or NOT_REQUESTED.
    - 1: NOT_ISSUED, expired, or no marker.
    - 2: no matching or readable log.
  - **What it never does.** It never reads `operator.env`, a cap or a credential.
- **Tests** (`tests/unit/test_permit_line_check.py`):
  - `::test_issued_line_with_future_expiry_exits_0`;
  - `::test_expired_issued_line_exits_1`;
  - `::test_not_issued_marker_exits_1`;
  - `::test_not_requested_is_reported_distinctly`;
  - `::test_missing_or_unmatched_log_exits_2`;
  - `::test_markers_imported_from_supervisor_core`, an AST check that no marker appears in the script as a string literal.

**(8) W3 and W4 structural tests.**
- **W3, in `tests/unit/strategy/test_instrument_buckets_move.py`:**
  - `::test_moved_defs_ast_equal_to_head`: each of the four moved definitions has the same `ast.dump` as its HEAD definition.
  - `::test_composition_reexports_identical_objects`. **(r10, FM2)** Narrowed to the two names imported back: `composition.InstrumentStationMismatchError is instrument_buckets.InstrumentStationMismatchError`, the same for `_bucket_station_instrument_ids`, and `not hasattr(composition, n)` for `bucket_station_instrument_ids` and `_facts_from_instrument`.
  - `::test_composition_diff_is_only_the_helper_move`: the AST of `composition.py` equals HEAD's, minus the four definitions, **(r10)** minus the import delta below, plus one `ImportFrom`. So no permit-wiring line can move.
  - **(r10, FM2)** `::test_composition_import_delta_is_exact`.
    - The removed imported names are exactly {`VenuePayloadError`, `instrument_id_to_slug`, `leg_of`, `parse_weather_slug`, `Measure`, `WeatherFactsUnavailableError`, `read_weather_bucket_facts`}.
    - The added `ImportFrom` from `breezy.strategy.current_rung_hold.instrument_buckets` names exactly {`InstrumentStationMismatchError`, `_bucket_station_instrument_ids`}.
    - At RED time, the removed set is checked against the output of `ruff check --select F401` on a scratch copy (§0c finding 7).
  - **(r10, FM2)** `::test_fq_strategy_keeps_module_level_bucket_name`.
    - `breezy.strategy.forecast_quantile_ladder.strategy.bucket_station_instrument_ids is instrument_buckets.bucket_station_instrument_ids`.
    - In the AST of `_d1_candidate_ids`, the call is a bare global `Name`, so the monkeypatch at `test_d1_cache_union.py:299-302,329-332` still takes effect.
    - That file stays byte-unchanged and green.
- **(r10) W5, in `tests/unit/strategy/test_d_plus_1_move.py`:**
  - `::test_moved_def_and_constant_ast_equal_to_head` (`_d_plus_1_climate_days`, `_VENUE`);
  - `::test_fq_composition_import_delta_is_exact`: `Iterable` and `local_standard_date` go out; one `ImportFrom` of `_VENUE` and `_d_plus_1_climate_days` from `d_plus_1` comes in; otherwise the AST equals HEAD's minus the two moved definitions;
  - `::test_fq_composition_reexports_identical_objects`;
  - `::test_strategy_d_plus_1_import_repointed`: the only change in `_d1_candidate_ids` is the module path of its function-local import;
  - **(r11, F5)** `::test_d1_candidate_ids_resolves_to_composition_object`: the function-local `ImportFrom` in `ForecastQuantileLadderStrategy._d1_candidate_ids` (`strategy.py:308` at HEAD) is read from the AST. The object it names, `importlib.import_module(<its module>)._d_plus_1_climate_days`, must be the same object (`is`) as `breezy.strategy.forecast_quantile_ladder.composition._d_plus_1_climate_days`. So the strategy and composition (`composition.py:175`, `:224`) use one definition of D+1, which is the invariant the docstring at `strategy.py:303-304` states;
  - `::test_d_plus_1_module_imports_only_ingest_and_registry`: in a fresh process, importing `d_plus_1` adds no `breezy.adapters`, `breezy.runtime` or `breezy.strategy.current_rung_hold` module.
- **W4, in `tests/unit/strategy/test_fq_strategy_type_only_import.py`:**
  - `::test_supports_quantile_latch_import_is_type_checking_only`.
  - `::test_strategy_module_does_not_load_persistent_latch`: after a fresh-process import of the strategy, neither `breezy.strategy.forecast_quantile_ladder.persistent_latch` nor `…current_rung_hold.trial_day_latch` is in `sys.modules`.

**(9) (r10, FM4) Cold first-import order.** The test is `tests/unit/test_wp1_cold_imports.py::test_module_imports_first_in_fresh_process[module]`.
- **Parameters.** Every module under `breezy.adapters.polymarket_us` (33 at planning), every module under `breezy.strategy.current_rung_hold` (31, `instrument_buckets` included) and `forecast_quantile_ladder.d_plus_1`. The list is collected from the tree with `pkgutil.walk_packages` and is never written by hand.
- **Each case.** One fresh `subprocess.run([sys.executable, "-c", "import importlib; importlib.import_module(m)"])`, in the T9 shape. It must exit 0.
- **Planning result.** 65 of 65 pass (§0c finding 8). The test runs at every W merge sha.

**(10) (r10, FM3) Whole-diff allowlist.** This is a gate command that covers the whole diff, in addition to the per-file pins.
- **The allowlist.** `tests/fixtures/wp1/diff_allowlist.txt` is committed in the RED-capture commit. It lists:
  - the W1–W5 files: the two `__init__`s, `current_rung_hold/composition.py`, `instrument_buckets.py`, and `forecast_quantile_ladder/{composition,strategy,d_plus_1}.py`;
  - the R-1 file, `scripts/analysis/nbp_shadow_parity_pure.py`;
  - the G36 move set of §3.3, enumerated by path: `src/breezy/analysis/stats/*.py`, `src/breezy/analysis/autonomy/shadow_replay.py`, `subprocess_rss.py`, `import_blocker.py`, and the script wrappers it names;
  - `scripts/ops/permit_line_check.py`;
  - the new test files named in §3.9a, §3.9b and WP1, and `tests/fixtures/wp1/**`.
- **The gate.** `git -C <tree> diff --name-only <wp1_base_sha> HEAD | grep -v '^tests/fixtures/wp1/' | LC_ALL=C sort | LC_ALL=C comm -23 - <(grep -v '^tests/fixtures/wp1/' tests/fixtures/wp1/diff_allowlist.txt | LC_ALL=C sort)` must print nothing. The output goes into the merge evidence.
- **A check on the allowlist itself.** `tests/unit/test_wp1_diff_allowlist.py::test_allowlist_excludes_protected_paths` fails if the allowlist names any of these:
  - a file under `src/breezy/adapters/` other than the package `__init__.py`;
  - any of the ten §3.9b pinned files;
  - anything under `src/breezy/runtime/`;
  - `fees.py` or `parsing.py`;
  - anything under `exec/`, which covers `exec/refusals.py`, `exec/reports.py` and `exec/no_side_keys.py`;
  - anything under `deploy/`;
  - any test file that exists at the base sha.

**(11) (r10, FH1) Run-time closure and the blocker.** The §3.9a run-time closure tests and the `import_blocker` tests are WP1 gates at every W merge sha, and WP6 gates at the eval-offline row-filing sha.

### 3.10 Ruling drafts (NOT decided; for the AUT-5 policy ruling and its peer review)

**Holdout.** No AUT-4 text; ARCH C4.1 is consumed by name.

**R-B `PREREG_FQ_v1` (the FQ boundary ruling, P4-2).** Text unchanged from r3 §3.10 R-B (LD-OBF, one-sided α = 0.025, a look every 10 combined station-days, n_max and loss stop derived in the committed design JSON from FQ take counts, data-free σ₀ = 0.5 and tape asks; D0′ prefix exclusion; `scripts/analysis/prereg_precommit_check.py` disclosure, **(r7, RC-4)** reusing `hypothesis_register._git_tree_is_dirty` and `_FREEZE_COMMIT_RE`, with the boundary committed as a `gs_boundary_artefact` file loaded by `load_boundary_artefact(path, expected_sha256=…)`; the boundary from the moved `group_sequential_boundaries`, validated by a seeded H0 MC that replays the live look loop verbatim). **(r4)** Its sha is the value of `family_prereg_sha256` on every FQ LIVE_SEQUENTIAL verdict; "KILL (including the loss stop) → FAIL → DEMOTE (entry-only)" applies with or without the policy ruling (§3.6). Draft to the peer loop by ARCH's ≈ 2026-11-10; filing target 2026-10-24. The r3 disclosure limit (existence, not reads) stands.

**R-C, calibration non-inferiority (relative; r4 conformed to ARCH C4 (c), P4-15, V16, P4-6).**
> "On the verdict's own station-days, with the reliability bins of `forecast_conditional_scoring.py:303` (moved to `src/breezy/analysis/stats/scoring_core.py`), a bucket is **paired** when candidate and champion each hold ≥ 30 events in it. Statistic: ΔECE = ECE_cand − ECE_champ over paired buckets (n-weighted mean |obs − pred|). The conjunct holds iff the one-sided (1 − α_k) upper bound of ΔECE, from a paired date-cluster bootstrap (dates resampled jointly for both models; seed `derive_seed(subject, slot_date, "fs_c_calibration_bootstrap")` (§3.1, r5 K7); B per §3.2), is < `CALIBRATION_NI_MARGIN` (proposed 0.01).
> Fewer than `MIN_CALIBRATION_BUCKETS` paired buckets → `INCONCLUSIVE(calibration_buckets_below_min)`. `MIN_CALIBRATION_BUCKETS` is a `pins.py` floor (≥ 1) set from AUT-4's measured false-fail rate; the policy may only raise it (proposed policy value 3).
> `n_min_c` is the smallest n at which, under the out-of-fold archive differences, P(≥ `MIN_CALIBRATION_BUCKETS` paired buckets) ≥ 0.95 and the test's power at true ΔECE = `CALIBRATION_NI_MARGIN` − `mde_c` (proposed `mde_c` = the margin, i.e. true ΔECE = 0) is ≥ 0.80, computed by WP0 at α_1…α_K_LIFETIME and **pinned in the policy block as the table `n_min_c`** (r5, K1); it enters `n_min_eff`.
> The mean signed deviation difference (`metrics.msd_diff`) and the absolute leg (`evaluate_calibration_leg`, ε = 0.05) are reported and never gated."
>
> **Measured false-fail rate (P4-6).** WP0 runs the test with candidate = champion-equivalent perturbations (seeded resamples of the champion's own out-of-fold predictions on archive days before 2026-07-01) and reports the rejection rate at each candidate α; the margin and `MIN_CALIBRATION_BUCKETS` proposal must give a false-fail rate ≤ 0.20 at α_1, or the draft returns to review.

r3's second |MSD| leg (δ_M) is withdrawn: ARCH names one paired test and one margin.

**R-D, α and nominations (r4: ARCH C4 and the amended ALPHA decision adopted).**
> "α_total = 0.025 one-sided, charged **per feasible nomination** (SHADOW→CHALLENGER PROMOTE), lifetime-geometrically per lineage: α_k = α_total·2^−k_life; `k_life` counts α-charging nominations and never resets.
> K_LIFETIME = 4 (the `pins.py` ceiling `MAX_NOMINATIONS_PER_LINEAGE_LIFETIME` ≤ 4); `MAX_NOMINATIONS_PER_FORWARD_WINDOW` = 1. A nomination with `n_min_eff > n_cap` is infeasible: `alpha_k = 0`, no K_LIFETIME charge, the window slot used.
> Screening (OFFLINE_CHALLENGER) spends no α: `SCREEN_MIN_STATION_DAYS` = 28, `X_SCREEN` = 0.0152 (Brier), PASS also requires the pinned-bootstrap 95% upper bound of Δbrier < 0.
> Nominee selection when several SHADOW candidates hold an accepted PASS: the largest screen improvement, ties by MINT `seq`.
> `forward_window_days` = 28 (pins 28–120), `forward_window_anchor_date` = 2026-10-02; `uptime_floor` = 0.8; `alpha_total` = 0.025; `stations` = the committed root manifest's count at filing (4 today); `sigma_pinned`, `sigma_b_pinned`, `deff_pinned`, `mde_a`, `mde_b` (proposed = X_EV, 0.02 per contract), `mde_c` and the `n_min_c` table from the §3.8 record at filing; `BOOTSTRAP_B_MAX` = 2¹⁹ (within the pins literal); `eval_staleness_producers` per §3.9.
> X_EV = 0.02 per contract; `EXCLUDED_FRACTION_MAX` = 0.25; `N_PROXY_MIN` = 30; `N_IOC_MIN` = 30; `MIN_CALIBRATION_BUCKETS` = 3; `CALIBRATION_NI_MARGIN` = 0.01.
> CHALLENGER→CHAMPION PROMOTE requires accepted OFFLINE_CHALLENGER **and** FORWARD_SHADOW PASS and `promote_enabled` (ARCH C5)."

**R-E, slippage.** As r3, with the last clause replaced: "`ACCEPT_FILL_SELECTION_SENSITIVE` = [true | false]" (a policy key read by the producer, §3.7).

**R-F, feasibility.**
> "The §3.8 record at filing. With today's σ, X and window, every nomination is infeasible (n_min_eff ≥ 403 > n_cap 89), so every FORWARD_SHADOW is INCONCLUSIVE(window_cap_below_n_min) by construction, no α is spent, and `promote_enabled=false` (`eta_date` > KILL − `forward_window_days`; AUT-5 feasibility ETA 2027-05-06). PROMOTE is machinery-proven by the drill only. Evidence class: machinery proven, edge unproven."

**R-G, CHALLENGER admission.** As r2/r3.

**Detector → action class (draft for the policy map).** `offline_challenger`, `forward_shadow` → `NONE` (inputs to PROMOTE only); `live_sequential` → `DEMOTE` (`RECOVERABLE_MODEL`); `eval_completeness`, `feasibility_consistency`, `eval_excluded_fraction`, `eval_n_stalled`, `eval_resource_creep`, `eval_replay_path` → `ALERT`; `eval_staleness` → ATTEST-required (intraday HEALTH).

### 3.11 Evaluator self-monitoring

| Detector | Producer | FAIL condition | Proposed class |
|---|---|---|---|
| `eval_completeness` | each unit | a fold family or SHADOW/nominee lacks today's verdict of a required kind; **(r5, K6)** expected sets: OFFLINE_CHALLENGER = one per SHADOW candidate and drill child, or exactly one NO_INPUT on the champion when there are none; FORWARD_SHADOW = one per open-window nominee, **zero** when there is none (a FORWARD_SHADOW for a non-nominee, or a NO_INPUT FORWARD_SHADOW, FAILs); LIVE_SEQUENTIAL = one per CHAMPION/HALTED family; or `replay_backlog_days > 3 × MAX_BACKLOG_DAYS_PER_RUN` | ALERT |
| `eval_excluded_fraction` | eval_offline | as r2 | ALERT |
| `eval_n_stalled` | eval_live | as r2 | ALERT |
| `eval_resource_creep` | each unit | wall > 0.8 × TimeoutStartSec, or peak > 0.8 × `MemoryHigh` (cgroup) or > 0.8 × child share, on 2 of the last 3 runs; a killed run (`_stoppost.json` with `service_result ≠ success`) counts | ALERT |
| **(r4)** `eval_replay_path` | eval_offline | the champion's daily replay→admission→scoring path produced no admitted station-day for 3 consecutive tape days that the census marks replayable, or a parity failure | ALERT |
| `eval_staleness` | AUT-6 intraday producer | §3.9 | ATTEST-required |

**Run-record store** (unchanged from r3): `$STATE/derived/autonomy/eval_runs/<producer_id>/<YYYY-MM-DD>_<unit_start_ns>.json` plus `<…>_stoppost.json` (`$SERVICE_RESULT`, `$EXIT_STATUS`, cgroup `memory.peak`); 0444, one writer per file.

#### 3.11a (r7) `eval_replay_path` metric names (registered in `metric_registry`; consumed by AUT-6 r13 #16)

`metric_registry.EVAL_REPLAY_PATH_METRICS` is a closed, frozen name set registered before go-live; AUT-6 pins the same names as `AUT4_REPLAY_PATH_METRICS` at its WP7 verify-first (2), and a verdict missing any of them is AUT-6's `eval_replay_path_unparsable`. All are counts, dates or shas: never a price, an outcome or a P&L (the `ParityReport.to_counts_dict` rule, `scripts/analysis/nbp_shadow_parity_pure.py:374`).
- **Tape day:** `metrics.tape_day` (ISO date of the replayed D-1 tape day); `metrics.closure_sha256` (the `fs_replay` closure); `metrics.subject_role = "champion"`.
- **Admission:** `metrics.admitted_station_days` (int), `metrics.excluded_by_reason` (object, closed reason keys of §3.4).
- **Parity results:** `metrics.parity` (object) holding exactly the `ParityReport.to_counts_dict()` keys, verbatim: `n_live`, `n_batch`, `n_matched`, `n_live_only`, `n_batch_only`, `n_numeric_mismatches`, `n_mismatches`, and the closed `n_{live|batch}_{yes|no}_{NotDPlus1|NotExecutable|Refuse|Take}` counts; plus three Take-restricted counts AUT-6 judges: `n_take_live_only`, `n_take_batch_only`, `n_take_numeric_mismatches` (computed from the report's `live_only`, `batch_only` and `numeric_mismatches` filtered to kind `Take`). A tape day with no admitted station-day carries `metrics.parity = null` and `metrics.day_status = "NO_INPUT"`.
- `ParityReport` and `diff_decision_keys` move with `run_live_parity` in WP1 (byte-identical, G36), so the names come from code AUT-4 already moves.
- Tests `tests/unit/autonomy/test_metric_registry.py::test_eval_replay_path_metric_names_registered_and_closed`, `::test_eval_replay_path_parity_keys_equal_to_counts_dict_keys` (the registered parity keys equal `ParityReport(...).to_counts_dict().keys()` plus the three Take counts, so a WP1 move that changes a key fails here), `::test_eval_replay_path_verdict_carries_every_registered_name`.

### 3.12 Memory and runtime budget

**(r4) Memory (ARCH §5.2, 14G).**
- `MemoryHigh=12G`, `MemoryMax=14G` on eval-offline; internal budget parent 2G + max(screen 4G, P·S) ≤ 12G, with S = ⌈1.25·(R + T)⌉ (R = WP0 per-child peak RSS; **(r8, AH3)** T = the child's peak private-`/tmp` bytes, measured at WP6 verify-first, because tmpfs pages are charged to the unit's cgroup); P = 2 if S ≤ 5G, P = 1 if S ≤ 10G; hard fail above.
- **(r9, BL1) The cap bounds T, so the budget is restated.**
  - tmpfs pages are charged to the unit's cgroup, and `EVAL_OFFLINE_TMPFS_BYTES` bounds the scratch of all P children together (one `/tmp` per sandbox).
  - The budget is therefore `2G + max(screen 4G, P·S) + EVAL_OFFLINE_TMPFS_BYTES ≤ MemoryHigh 12G`, with `S = ⌈1.25·R⌉`. This supersedes r8's `S = ⌈1.25·(R + T)⌉`.
  - With the cap at 2 GiB: P = 2 if S ≤ 4G, P = 1 if S ≤ 8G, and a hard fail above.
  - WP6 verify-first still measures T and requires `P·T_peak ≤ 0.5 · EVAL_OFFLINE_TMPFS_BYTES`, or the WP returns to review.
  - eval-live: 128 MiB of tmpfs fits inside `MemoryHigh=768M`.
  - Test `tests/unit/autonomy/test_memory_budget.py::test_tmpfs_cap_inside_memory_budget` recomputes the inequality from the `budget.py` literals and both P branches.
- The unit's measured peak is recorded before its timer is enabled (ARCH §5.2). A peak reaching `MemoryHigh` means a named raised cap (≤ 16G) in a slot outside [16:30Z, 01:15Z) shared with no other heavy unit, through review, or the WP returns to review. Never 01:00–04:30Z.
- **Enablement gate:** eval-offline is a > 4G study, so its timer is enabled only after AUT-6's daily memory-sum HEALTH verdict PASSes (the quote-tape-ingest 12G/14G drop-in currently FAILs it by name; ARCH §5.2).

**(r4) Per-run replay budget.**
- `deadline = unit_start + EVAL_OFFLINE_TIMEOUT_START_S − SAFETY_S` (pattern of `deploy/systemd/replay-daily-run.sh:48-50`).
- Replay wall budget at the worst wait (**r5, K5**): 6299 − 900 (flock) − 900 (screen) − 600 (scoring) − 300 (safety) = **3599 s**.
- **`FS_REPLAY_CHILD_TIMEOUT_S = ⌊P × 3599 / (4·(MAX_NOMINATIONS_PER_FORWARD_WINDOW + 1))⌋`** = ⌊P × 3599 / 8⌋: **899 s at P = 2, 449 s at P = 1** (r5; r4 900/450). 4 is the station count; the open-window nominee (≤ 1 per lineage by ARCH) plus the champion's `eval_replay_path` replay. With more than one live lineage the denominator is 4·Σ(1 + 1), re-derived in the same reviewed commit. Test `tests/unit/autonomy/test_budget.py::test_child_timeout_derived_from_budget` recomputes it from the literals and `pins.MAX_NOMINATIONS_PER_FORWARD_WINDOW`.
- Launch rule, order (today first: champion, then the nominee; then backlog ≤ 3 days), atomic per-output partial commit, `BACKLOG_EXPIRED`, and the WP0 hard-fail rule (`t_p95 ≤ 0.8 × FS_REPLAY_CHILD_TIMEOUT_S`, i.e. ≤ 719 s at P = 2, ≤ 359 s at P = 1) as r3.
- Tests: `tests/unit/autonomy/test_memory_budget.py::test_replay_budget_partial_commit_resumes_backlog`, `::test_no_child_launched_past_deadline`, `::test_backlog_expired_past_window_end`.

### 3.13 Engine input journal (AUT-4 owns the schema; AUT-5 writes it)

**(r4) Conformed to ARCH C5 (P4-9).**
- Path: `$STATE/evidence/engine_inputs/<venue>/<YYYY-MM-DD>/<mode>_<ts_ns>.jsonl` (write-once, 0444, one file per pass, single-read rule).
- Schema `engine_input/v1`, exact-set, one row per verdict read: `pass_id`, `pass_mode`, `verdict_id`, `kind`, `subject_family_id`, `detector`, `acceptance`, `reject_reason` (closed: `expired`, `unpinned_producer`, `sha_mismatch`, `no_ruling`, `action_class_mismatch`, `subject_unbound`, `k_exceeded`, `input_unresolved`), `acted`, `transition_id`.
- Contract tests (AUT-4, in `tests/contract/test_engine_input_journal_contract.py`): `::test_schema_exact_set_and_closed_reject_reasons`, `::test_every_live_verdict_journaled_once_per_daily_pass` and `::test_cause_verdict_ids_subset_of_acted_rows` (the ARCH names), `::test_no_widening_row_without_journal`, `::test_fixture_journal_never_under_production_state_root`.
- The fixture path (§6.1) journals under its own state root `/home/jon/.local/share/breezy-autonomy-fixture/evidence/engine_inputs/fixture/<date>/`.

---

## 4. Work packages

**Gate commands for every WP** (run by the coordinator, never trusted from an agent): interpreter `PYTHONPATH=<tree>/src /home/jon/breezy/.venv/bin/python`; `scripts/ci/run_tests_no_egress.sh`, the full gate after every merge (L-43), launched with `-p LimitNOFILE=524288` and basetemp on `~/.cache`; `cd <tree> && lint-imports` printing "N kept, 0 broken"; the mypy ratchet. Never `uv`/`pip` (L-51), never `git stash`. Activation is immediate on merge unless a technical reason is stated.

**WP0: measurements (read-only).** r3 items (i)–(x), plus **(r4)**: (xi) σ and ρ̂ for the policy block's pinned values (archive before 2026-07-01, out-of-fold); (xii) the R-C false-fail rate at α_1…α_4 and the paired-bucket occupancy that fixes `MIN_CALIBRATION_BUCKETS`; (xiii) eval-offline per-child peak R and t_p95 against the **899/449 s** timeouts (r5); **(r5)** (xiv) `sigma_b_pinned` (sd of per-take `ev_cond`) and the `n_min_c` table at α_1…α_4 for the block (K1). GREEN: every number sourced; the §3.12 hard-fail rules evaluated; the R-C false-fail bound met or the draft returned.

**WP1 (= ARCH AUT-4a, Wave 1): the G36 move.** Functions moved byte-identically into `src/breezy/analysis/stats/` (§3.3); scripts kept as thin CLI wrappers; characterisation-pinned (L-33) with mutation evidence. RED first: `tests/unit/analysis/stats/test_moved_source_pinned.py::test_moved_functions_byte_identical`, `::test_script_wrappers_delegate`; the existing `tests/unit/test_aud07_live_rule_crossing_sim.py`, `tests/unit/test_nbp_shadow_parity_live.py` and the family-tally golden stay byte-unchanged and green.
- **(r9, BH1, BH2, E-7b (b)): the cut set W1–W4 and its live-path gates.** This supersedes r8's M1–M3 block. **(r10)** The cut set is now W1–W5 plus the R-1 edit, with the run-time gates of FH1.
  - **Verify-first (read-only).**
    - Re-run the §0b measurement at WP1's base sha: the HEAD closures, the E2 simulation on scratch copies, and the 35-entry probes.
    - **(r10, FH1)** Re-run §0c as well: the run-time closures after both golden replays, with and without the blocker; the `replay_daily_runner` smoke closure; the W3 and W5 F401 deltas; and the 65-module cold imports. Record the runner's default paths before writing its smoke test.
    - Record any drift from §0b. The exception set and `WP1_DECLARED_LIVE_DELTA`/`WP1_INTENDED_ARROW_LOSSES` follow the re-measurement only through review.
    - If, with W1–W4 applied, any exec, HTTP/WS, `factories` or `order_enablement` module remains, apply F-1 (§3.9a). **(r10)** The check uses W1–W5 and R-1, at import time and at run time.
    - Re-capture the §3.9b pins if any pinned file changed since `f45f5a65`.
    - List every function-local `from <lazy pkg> import`.
  - **RED-first captures, in one commit before any W edit.** All are `tests/fixtures/wp1/*_<base12>.json`:
    - live-entry identities;
    - Arrow registrations for the 35 entries;
    - live-entry modules and configs;
    - the lazy packages' HEAD import maps, `dir()` and bound submodules;
    - the pin table;
    - **(r10)** the SFO 2026-09-01 fixture and its golden hash (§3.9b (6b)), the golden catalog (§3.9b (4)), the recorded W1–W4 run-time fixture for the negative control (§3.9a), the base values for `test_permit_window_values_equal_head`, and `diff_allowlist.txt` (§3.9b (10));
    - plus `tests/fixtures/wp1/fs_replay_golden.sha256`.
  - **Files.** One commit per W, each gate-green:
    - W1: `src/breezy/adapters/polymarket_us/__init__.py`;
    - W2: `src/breezy/strategy/current_rung_hold/__init__.py`;
    - W3: the new `src/breezy/strategy/current_rung_hold/instrument_buckets.py`, and `src/breezy/strategy/current_rung_hold/composition.py` (defs move out and are imported back);
    - W4: `src/breezy/strategy/forecast_quantile_ladder/strategy.py`, lines :65 and :79;
    - **(r10)** W5: the new `src/breezy/strategy/forecast_quantile_ladder/d_plus_1.py`; `forecast_quantile_ladder/composition.py`, from which the definition and `_VENUE` move out and are imported back; and `strategy.py:308`;
    - **(r10)** R-1: one import line in `scripts/analysis/nbp_shadow_parity_pure.py`. It lands before the G36 move's byte-identity capture, so the moved copy matches the post-R-1 source;
    - **(r10)** the new `src/breezy/analysis/autonomy/import_blocker.py`;
    - the new script `scripts/ops/permit_line_check.py`.

    W1 is owner-reviewed by the adapter package's owner, W2 and W3 by `current_rung_hold`'s, and W4 by `forecast_quantile_ladder`'s. **(r10)** W5 is reviewed by `forecast_quantile_ladder`'s owner, and R-1 by the owner of the `nbp_shadow_parity` scripts.
  - **RED first.**
    - The §3.9a closure tests: `test_eval_offline_closure_adapter_set_equals_named_exception`, `test_eval_offline_closure_has_no_adapter_exec_module`, `test_closure_guards_fail_on_head_closure`, `test_eval_live_closure_has_no_adapter_module` and `test_fixture_unit_closure_equals_eval_offline_closure`.
    - All §3.9b tests, (1) through (8). **(r10)** Also (6b) and (9) through (11), the §3.9a run-time closure tests, `tests/unit/autonomy/test_import_blocker.py::*` and `tests/unit/test_r1_permit_ttl_import.py::*`.
    - `tests/unit/test_lazy_package_inits.py::*`.
  - **Must stay byte-unchanged and green:**
    - the ten §3.9b pinned files;
    - `tests/unit/test_runtime_import_isolation.py` (through WP1; under FL1, WP6 appends two entries, §3.9b (4)), `tests/unit/test_current_rung_hold_composition.py`, `tests/unit/test_nbp_shadow_parity_live.py` and `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py`;
    - **(r10)** `tests/strategy/forecast_quantile_ladder/test_d1_cache_union.py`, `tests/strategy/forecast_quantile_ladder/test_sl13c_d_plus_1_resolution.py`, `tests/unit/test_nbp_shadow_parity_pure.py` and `tests/unit/test_nbp_market_comparison.py`;
    - the adapter and `current_rung_hold` test modules.
  - **Gates.** The coordinator runs each and reads the output itself:
    - `cd <tree> && systemd-run --user --wait --pipe -p LimitNOFILE=524288 env PYTHONPATH=<tree>/src scripts/ci/run_tests_no_egress.sh`, with basetemp on `~/.cache`. Expect exit 0, and read `EXIT=0` before any push.
    - `cd <tree> && PYTHONPATH=<tree>/src lint-imports`. Expect "N kept, 0 broken". This must be the console script run from the tree root; `python -m importlinter` is a no-op.
    - `git -C <tree> diff --exit-code <wp1_base_sha> HEAD -- <the ten §3.9b paths>`. Expect exit 0 and empty output.
    - the mypy ratchet. Expect no new errors.
    - **(r10, FM3)** the whole-diff allowlist command of §3.9b (10). Expect empty output.
  - **Activation.**
    - Follow the §3.9b (7) runbook: a supervisor restart inside [01:00Z, 16:40Z), the adoption line with an unchanged pid, then the permit-line check after the first post-merge node boot. **(r10, FM1)** That includes step 2a, the boot smoke against the deployed tree, and the immediate tree revert of step 7.
    - The eval-offline row is still not filed by WP1. Its filing is WP6's, gated by §6.4 rows 10 and 11.
  - **If W1–W4 cannot be completed:** apply F-1 (§3.9a). **(r10)** The same holds for W5 and R-1.

**WP2: pure evaluation core.** **(r7, RC-1)** Also edits `src/breezy/analysis/hypothesis_ledger.py` (the `recompute_mde` body delegates to `sample_size.mde_one_sided`; AUD-18 owner review; fallback in §2). RED first, before that edit: capture the golden grid from the current `recompute_mde` at `f45f5a65`. Tests `tests/unit/autonomy/test_sample_size.py::test_recompute_mde_bit_identical_before_and_after_delegation` (α ∈ {`MIN_PER_VARIANT_ALPHA`, 0.00625, 0.0125, 0.025, 0.025·2^−k for k = 1…4, and the α_k/3 values} × n ∈ {1, 2, 10, 60, 89, 300, 403, 600, 1000}), `::test_recompute_mde_delegates_to_sample_size` (spy on `sample_size.mde_one_sided`, called with σ = 0.5 and `POWER`), `::test_n_min_inverts_mde`, `::test_power_at_mde_is_design_power`, `::test_n_min_one_sided_matches_nbp_compute_n_min_at_alpha_0_025`, `::test_hypothesis_ledger_import_closure_gains_only_sample_size`; `tests/unit/autonomy/test_nomination.py::test_alpha_never_pooled_across_lineages`; `tests/unit/autonomy/test_forward_shadow.py::test_nominee_single_look_never_reopened`; `tests/unit/autonomy/test_isolation.py::test_aut4_never_imports_or_writes_hypothesis_ledger`. `tests/unit/test_hypothesis_ledger.py`, `test_hypothesis_triage.py` and `test_hypothesis_register.py` stay byte-unchanged and green; `lint-imports` keeps both AUD-18 D6(i) contracts.
- **(r8, AH2) Error message.** `tests/unit/autonomy/test_sample_size.py::test_recompute_mde_nonpositive_n_message_pinned`.
  - For n ∈ {0, −1}, `recompute_mde` raises `ValueError` whose `str()` equals exactly `"recompute_mde is undefined for n_station_days <= 0"`, and a spy confirms `sample_size.mde_one_sided` is not called.
  - It passes before the edit (characterisation) and must pass after it. Its RED evidence is a mutation: with the guard deleted, the test fails on `sample_size`'s wording.
- **(r8, AH5) Closure test.** `::test_hypothesis_ledger_import_closure_gains_only_sample_size` is made exact.
  - In fresh processes, the `sys.modules` delta from importing `hypothesis_ledger` (after the edit minus before) must equal {`breezy.persistence`, `breezy.persistence.autonomy`, `breezy.persistence.autonomy.sample_size`} and contain no `nautilus_trader*` module.
  - It is RED against the r7 design while `persistence/__init__` is eager (§0a).
  - Under the RC-1 fallback it is replaced by `::test_hypothesis_ledger_closure_unchanged`, which pins today's 50-module set.
- **(r8, AH5) Explicit WP2 gate: `lint-imports`.**
  - Run `cd <tree> && lint-imports` from the tree, with the worktree's `PYTHONPATH`. Only the console script counts; `python -m importlinter` is a no-op.
  - Required output: "N kept, 0 broken". The kept set must include both AUD-18 D6(i) contracts, the layers contract, and "The live trading path never imports the offline analysis layer". The line is pasted into the merge evidence.
- **(r8, LOW-1) Grid sweep.** `::test_n_min_one_sided_matches_nbp_compute_n_min_at_alpha_0_025` becomes a full cross-product sweep.
  - **Grid.** σ ∈ {0.05, 0.099, 0.1, 0.25, 0.5, 1.0} plus 500 log-uniform draws on [0.01, 2]. X ∈ {0.005, 0.01, 0.0152, 0.02, 0.05, 0.1} plus 500 log-uniform draws on [0.001, 0.2]. Draws are seeded with `roi_bound.SEED`.
  - **Check (i).** The two z-sums agree within ±1 ulp: `abs(zs_a − zs_b) ≤ math.ulp(zs_a)`. The measured gap is exactly 1 ulp (§0a).
  - **Check (ii).** Compute `raw_a = ((Z_ALPHA_TWO_SIDED_095 + Z_POWER_080)·σ/X)²` and `raw_b`, the same expression inside `n_min_one_sided`.
    - If no integer lies in [min(raw_a, raw_b), max(raw_a, raw_b)], then `compute_n_min(σ, x=X).n_min == n_min_one_sided(σ, X, 0.025)` exactly.
    - If an integer does lie there (a `ceil` boundary flip), the two results may differ by at most 1, and the point is recorded as a boundary case. The test fails on any difference outside such a point, so every flip is explained.
  - **Positive control.** A constructed point X = zs_a·σ/√k for an integer k puts raw within ulps of k, so the boundary branch is exercised.
  - **Handling.** AUT-4 never consumes `compute_n_min`, so a flip changes no AUT-4 number. Files: `eval_stats.py`, `permutation.py`, `calibration_ni.py`, `metric_registry.py`, `windows.py`, `leakage.py`, `budget.py`, **(r5)** `seeding.py`, `src/breezy/persistence/autonomy/sample_size.py` (ARCH-0 owner review). RED first (r4 names): `tests/unit/autonomy/test_permutation.py::test_b_capped_and_tail_beyond_cap`, `::test_b_max_covers_k_lifetime_over_three`; `tests/unit/autonomy/test_calibration_ni.py::test_relative_calibration_one_sided_with_margin`, `::test_fewer_than_min_calibration_buckets_inconclusive`, `::test_n_min_c_enters_n_min_eff`, `::test_false_fail_rate_reported`; `tests/unit/autonomy/test_eval_stats.py::test_power_at_n_reported`; `tests/unit/autonomy/test_verdict_identity.py::test_recompute_same_slot_same_inputs_same_verdict_id`; `tests/unit/autonomy/test_verdict_schema.py::test_assumptions_closed_five_tags`, `::test_two_ruling_sha_fields_per_kind`; `tests/unit/autonomy/test_verdict_validity.py::test_offline_successor_lands_before_predecessor_expiry`; `tests/unit/autonomy/test_budget.py::test_child_timeout_derived_from_budget`; **(r5)** `tests/unit/autonomy/test_eval_stats.py::test_sample_size_primitives_single_definition`; `tests/unit/autonomy/test_seeding.py::test_seed_differs_by_subject_slot_and_role`, `::test_role_is_closed_literal`; `tests/unit/autonomy/test_verdict_schema.py::test_decimal_fields_canonical_string`.

**WP3: FQ tape admission and oversize quarantine.** As r3, plus `tests/unit/autonomy/test_tape_admission.py::test_frozen_holdout_day_refused`.
- **(r8, AH4)** The quarantine is the directory `$STATE/derived/replay/oversize_quarantine/`, with one append-only file per consumer: `eval_offline.jsonl`, and `replay_daily.jsonl` from the runner edit. This replaces r2's single `oversize_quarantine.jsonl`.
- WP3's deploy step creates the directory 0700 before the eval-offline row is filed.
- Test `tests/unit/autonomy/test_tape_admission.py::test_quarantine_writer_appends_only_own_file`.

**WP4: LIVE_SEQUENTIAL and the `eval-live` unit** (Wave 2). Unit per §3.9 (studies flock, `TimeoutStartSec=1500`) **(r7)** and §3.9a (wrapper row, `timeout -k 20s 1470s`, `OnFailure=breezy-autonomy-failed@%n`). RED first: the §3.6 tests, **(r7)** plus the eval-live cases of the §3.9a contract tests and the lint, **(r8)** `test_eval_live_closure_has_no_adapter_module` (from WP1) and the eval-live case of `test_each_aut4_row_has_private_tmp`. Activation: enable the timer on merge (≤ 1G, below the 4G enablement threshold). **(r9, BM1)** First, the §3.9a E-7c sequence must hold: steps 1–2 (the wrapper merged with private `/tmp` and `--size`, its test green, the deployed sha equal to the merged blob), then step 3 (the eval-live row filed, with `test_each_aut4_row_has_private_tmp` and `test_tmpfs_cap_enforced_enospc` green). Only then is the timer enabled.

**WP5: OFFLINE_CHALLENGER screening and the nomination columns** (Wave 3). Files: `src/breezy/analysis/autonomy/producers/eval_offline.py` (screen part), `src/breezy/persistence/autonomy/nomination.py` (with ARCH-0 review). RED first: the §3.5 tests, plus `tests/unit/autonomy/test_offline_challenger.py::test_screen_charges_no_alpha`, `::test_screen_never_reads_frozen_holdout_or_post_nomination_days`, `::test_drill_child_screen_not_distinct_with_drill_tag`, `::test_screen_fields_k_life_null`, **(r5)** `::test_no_input_is_offline_challenger_on_champion`; `tests/contract/test_nomination_columns_contract.py::*` (§3.5, K3; GREEN needs the AUT-5 engine write path, so it merges with or after AUT-5a); `tests/unit/autonomy/test_seeding.py::test_same_slot_recompute_bit_identical`.

**WP6: FORWARD_SHADOW, the `fs_replay` children and the `eval-offline` unit** (Wave 3). Unit per §3.9/§3.12. RED first: the §3.7 tests (incl. **(r5)** `::test_no_nominee_writes_no_forward_shadow`, `::test_look_waits_for_n_ioc_min_inside_window`, `::test_window_end_before_n_ioc_min_is_fill_rate_underpowered_final`, **(r6)** `::test_look_time_independent_of_nominee_outcomes`, `::test_look_counts_signature_takes_no_nominee_input`); **(r5)** `tests/contract/test_autonomy_units.py::test_pre_offline_studies_units_end_by_1045z` (GREEN needs the AUT-3 rerun change, §3.9); `tests/unit/autonomy/test_memory_budget.py::*` (§3.12); `tests/unit/autonomy/test_pins.py::test_aut4_producer_ids_registered_in_pins`; existing `test_execution_egress_firewall_guard`, unchanged. **(r7, RC-2)** `tests/unit/autonomy/test_fill_model.py::test_p_fill_lb_uses_settlement_wilson` (`fill_model.wilson_interval is current_rung_hold_v2._wilson_interval`), `::test_p_fill_lb_one_sided_z_at_alpha_k_over_3`, `::test_no_wilson_defined_in_autonomy_packages` (AST scan of `src/breezy/analysis/autonomy/` and `src/breezy/persistence/autonomy/`: no function whose name contains `wilson`). **(r7, E-7/E-7a/E-8a/E-9)** the §3.9a tests; the unit files `deploy/systemd/breezy-autonomy-eval-offline.service` and `breezy-autonomy-eval-offline-fixture.service` use the wrapper rows of §3.9a. **Verify-first:**
- the SQLite input list with journal modes;
- **(r8, AH4)** the quarantine directory is still `$STATE/derived/replay/oversize_quarantine` and exists 0700;
- **(r8, AH3, E-7c)** the `fs_replay` child's scratch writes. Run one champion replay child under the eval-offline row (`--tmpfs /tmp`, `TMPDIR=/tmp`) and record:
  - (i) every path the child writes outside its binds. Only `/tmp` is expected: `tempfile.mkdtemp` work directories in the `replay_daily_runner.py:1090-1091` pattern, and Nautilus or pyarrow temp files.
  - (ii) T, the child's peak `/tmp` bytes, which enters §3.12's S.
  - (iii) that no durable writer uses the default temp dir.
  - Any write outside `/tmp` and the row's binds fails the verify-first step and returns the WP to review.

**Tests:**
- the §3.9a `test_each_aut4_row_has_private_tmp`, `test_fixture_row_positive_and_negative_probes` and `test_missing_bind_source_fails_unit_before_producer`;
- `test_child_scratch_dir_removed_on_success_and_failure`;
- `test_writers_mkstemp_in_final_dir`;
- **(r9, BL1)** `test_tmpfs_cap_enforced_enospc`, `test_child_scratch_enospc_commits_nothing` and `test_tmpfs_cap_inside_memory_budget`;
- **(r9, BM1)** `tests/contract/test_autonomy_units.py::test_aut4_rows_require_wrapper_private_tmp`;
- **(r10, R-2)** `::test_wrapper_applies_default_tmpfs_size_to_rows_without_one` and `::test_wrapper_malformed_tmpfs_size_fails_closed`;
- **(r10, FL1)** two entries appended to `STAGE0_ENTRY_MODULES` (`eval_offline`, `fs_replay`), with `test_stage0_tuple_head_entries_unchanged` and `test_closure_referenced_arrow_types_registered[entry]`;
- **(r10, FH1)** the `install()`-first entry check (`test_blocker_installed_first_in_eval_offline_and_fs_replay_entries`), run on the real entry modules.

**Activation (technical reason stated).** The timer is enabled only after all three of:
1. the measured peak (S now includes T) is recorded and is below `MemoryHigh`;
2. AUT-6's memory-sum HEALTH PASSes (ARCH §5.2: no autonomy study above 4G until the sum passes);
3. **(r8, AH1; r9, BH1)** The eval-offline `AUTONOMY_BWRAP_TABLE` row is filed under the E-7b (b) named exception (§3.9a), with `test_eval_offline_closure_adapter_set_equals_named_exception`, `test_eval_offline_closure_has_no_adapter_exec_module` and `test_closure_guards_fail_on_head_closure` green at the filing sha, after WP1's W1–W4 and the §3.9b gates. **(r10, FH1)** The run-time closure tests, the import-blocker tests and `test_eval_offline_never_imports_or_spawns_replay_daily_runner` are also green at that sha, with W5 and R-1 merged. Otherwise F-1 applies.
4. **(r9, BM1)** The E-7c sequence of §3.9a, steps 1–3, is complete for the eval-offline and fixture rows.

**WP7a: R-B design commit, H0 MC and precommit check** (starts now; docs, evidence, a read-only script). **(r7, RC-4)** The script is only the disclosure comparison; it reuses `hypothesis_register._git_tree_is_dirty` (refuse on a dirty tree, fail-closed on a git error) and `_FREEZE_COMMIT_RE`, and the boundary is a `gs_boundary_artefact` file checked with `load_boundary_artefact`. Added RED tests `tests/unit/test_prereg_precommit_check.py::test_dirty_tree_refused_via_hypothesis_register_helper`, `::test_design_commit_not_40_hex_refused`, `::test_boundary_loaded_with_expected_sha`; `tests/unit/test_hypothesis_register.py` byte-unchanged. As r3 (`scripts/analysis/prereg_precommit_check.py` with RED tests `tests/unit/test_prereg_precommit_check.py::test_undisclosed_pre_commit_pnl_artefact_fails`, `::test_post_commit_artefact_ignored`, `::test_disclosed_artefact_passes`; design JSON `docs/evidence/PREREG_FQ_v1_design_<date>.json`; boundary + H0 MC as a capped unit run under `TimeoutStartSec`, outside 01:00–04:30Z and outside [16:30Z, 17:10Z)). Peer loop by ≈ 2026-11-10.

**WP7b: feasibility.** RED first: the §3.8 tests, including **(r5)** `::test_projection_equals_engine_written_columns` and `::test_stations_key_matches_root_manifest`.

**WP8: self-monitoring and the journal contract.** RED first: `tests/unit/autonomy/test_health.py::test_error_verdict_is_not_fresh`, `::test_resource_creep_counts_killed_run_from_stoppost_record`, `::test_backlog_growth_fails_completeness`, `::test_eval_replay_path_fails_on_three_dark_replayable_days`, `::test_attest_cadence_has_no_expiry_gap_with_eval_staleness`, **(r5)** `::test_staleness_fails_when_newest_slot_not_today`, `::test_staleness_producer_set_from_policy_key`, `::test_completeness_no_nominee_expects_zero_forward_shadow`, `::test_completeness_fails_on_forward_shadow_for_non_nominee`; `tests/unit/autonomy/test_run_record.py::test_stoppost_writes_service_result_and_memory_peak`; the §3.13 contract tests plus **(r5)** `::test_engine_acts_on_newest_verdict_per_family_kind`; `tests/deploy/test_autonomy_oneshots_never_set_runtime_max_sec.py::test_no_autonomy_oneshot_sets_runtime_max_sec`; **(r7)** the §3.11a `test_metric_registry.py` tests (merged before eval-offline go-live, because AUT-6 #16 pins the names).

**WP9: live-proof run** (§6). No code.

**Producer-pin rotation runbook.** Append-only per §4.3 (Z9); an `fs_replay` rotation triggers `PENDING_RECLOSURE` re-replay through the §3.12 backlog.

---

## 5. Association

| Contract | From → AUT-4 | AUT-4 → |
|---|---|---|
| C1 | AUT-1: Take/TrySubmit, `forecast_input_sha256`, `depth_ref`/`quote_ref`, `LifecycleEvent` | — |
| C2 | AUT-2: admissible rows (`p_source=c1_decision`), `slippage`, `realized_pnl`; label slot ends ≤ 14:40Z | — |
| C3 | AUT-3: lineage windows; ≤ 1 MINT per lineage per day; `refit_run/v1` outcomes | **(r5, K8; r6, L1/L2) request:** the reproducibility-rerun unit ends ≤ 10:45:00Z, satisfying `start + AccuracySec (1 s) + TimeoutStartSec + TimeoutStopSec (60 s) ≤ 10:45:00Z`: keep the 09:35:00Z start with `TimeoutStartSec` ≤ 4139 s; AUT-4 owns `test_pre_offline_studies_units_end_by_1045z` |
| C4 | — | AUT-5 engine (every kind; FORWARD_SHADOW with `k_life`, `alpha_k`, `n_min_eff`, `n_cap`; two ruling-sha fields); AUT-7 via accepted LIVE FAIL |
| C4.1 | ARCH-0 (filed in Wave 0) | consumed by name |
| C5 | AUT-5: fold, nomination row columns, `lineage_counters`, bound sha, registry export | **(r4)** `compute_nomination_columns`. **(r5, K3) request:** the engine calls it inside the PROMOTE's `BEGIN IMMEDIATE` transaction with the §3.5 named keys and writes the five columns only from its return; AUT-4 owns `tests/contract/test_nomination_columns_contract.py`. **(r5, K4) request:** the engine acts only on the newest verdict per (family, kind) (§3.9) |
| C6 | ARCH-0 Protocols | `FqEvaluator`; `eval_staleness` → AUT-6 |
| Engine input journal | AUT-5 writes it | AUT-4 owns schema and contract tests |
| Policy block | AUT-5 files it | AUT-4 drafts R-B…R-G and keys `SCREEN_MIN_STATION_DAYS`, `X_SCREEN`, `forward_window_days`, `forward_window_anchor_date`, `uptime_floor`, `sigma_pinned`, `deff_pinned`, **(r5, K1, pinned block values feeding `compute_nomination_columns`)** `alpha_total`, `stations`, `sigma_b_pinned`, `mde_a`, `mde_b`, `mde_c`, `n_min_c` (table k = 1…K_LIFETIME), **(r5, K4)** `eval_staleness_producers`, `X_EV`, `EXCLUDED_FRACTION_MAX`, `N_PROXY_MIN`, `N_IOC_MIN`, `MIN_CALIBRATION_BUCKETS`, `CALIBRATION_NI_MARGIN`, `ACCEPT_FILL_SELECTION_SENSITIVE`, the detector map, the `attest_required_detectors` entry for `eval_staleness` |
| `pins.py` | ARCH-0: `MAX_NOMINATIONS_PER_LINEAGE_LIFETIME`, `MAX_NOMINATIONS_PER_FORWARD_WINDOW`, `BOOTSTRAP_B_MAX`, `MIN_CALIBRATION_BUCKETS`, `DEFAULT_RESTRICTIVE_CLASS`, `MAX_VERDICT_VALIDITY_H` | AUT-4 registers producer ids `eval_live`, `eval_offline`, `fs_replay`; requests `DEFAULT_RESTRICTIVE_CLASS["live_sequential"] = DEMOTE`; proposes `BOOTSTRAP_B_MAX = 2¹⁹` |
| Memory | AUT-6 memory-sum HEALTH | eval-offline enabled only after it PASSes |
| Drill child | AUT-7 | OFFLINE screen verdicts tagged `drill` (§6.1 path 2) |
| Fixture engine pass | **AUT-5** (request): an engine pass runnable against the fixture state root | path 3 of §6.1 |
| **(r7)** AUD-18 hypothesis ledger | owner review of the `recompute_mde` delegation (RC-1) | `sample_size.mde_one_sided` as the shared definition; fallback equivalence test if refused |
| **(r7)** AUT-6 r13 #16 | consumes the `eval_replay_path` verdict | the §3.11a registered names (`EVAL_REPLAY_PATH_METRICS`), merged before eval-offline go-live |
| **(r7)** E-7a `AUTONOMY_BWRAP_TABLE` and wrapper | the table owner as filed; AUT-6's `breezy-autonomy-failed@` notifier; **(r8, E-7c)** `--tmpfs /tmp` + `TMPDIR=/tmp` on every row; the wrapper harness's root substitution (LOW-2) | three AUT-4 rows (§3.9a); **(r8)** O-1 closed by E-7b; the eval-offline row filed only with its closure test green |
| **(r8, AH5)** ARCH-0 `src/breezy/persistence/__init__.py` | a lazy (PEP 562) package `__init__`, `__all__` unchanged | the exact `hypothesis_ledger` closure test; if declined, the RC-1 fallback |
| ~~**(r8, AH1)** Owners of the three package `__init__`s (M1–M3)~~ **(r9, BH1) superseded:** the adapter-package owner (W1), the `current_rung_hold` owner (W2, W3), the `forecast_quantile_ladder` owner (W4; **(r10)** W5); **(r10, R-1)** the owner of the `nbp_shadow_parity` scripts (one import line) | review of the W1–W4 cut set (§3.9a); **(r10)** W5 and R-1 are reviewed the same way; no enablement, permit, exec or firewall file is edited | WP1 W1–W4 with the §3.9b live-path gates; F-1 if any W is refused |
| **(r9, BL1, BM1)** `AUTONOMY_BWRAP_TABLE` and wrapper owner | per-row `tmpfs_size_bytes` passed as `--size` before `--tmpfs /tmp` (ER-1); **(r10, R-2)** `DEFAULT_TMPFS_SIZE_BYTES` for rows without one, and fail-closed only on a malformed value; `test_bwrap_wrapper_provides_private_tmp` green and the wrapper deployed **before** any AUT-4 row is filed | the AUT-4 rows carry 2 GiB / 2 GiB / 128 MiB; `test_aut4_rows_require_wrapper_private_tmp` |
| **(r9, BH1)** E-7b (b) named exception | eval-offline row only | `E7B_EVAL_OFFLINE_ADAPTER_MODULES` (11 modules, §3.9a), guarded by the exact-set and exec tests |
| **(r8)** AUT-6 r12 WP5 | the `quantile_density`/`location_correction` move to `domain` | WP1 rebases onto it if it lands first |

**Order.**
- **Now, in parallel:** WP0, WP7a.
- **Wave 1 (after ARCH-0):** WP1 (AUT-4a), then WP2 and WP3.
- **Wave 2 (after AUT-2a):** WP4.
- **Wave 3 (after AUT-3 + AUT-5a):** WP5, WP6; then WP7b (after WP0 + WP6).
- **After AUT-6's intraday producer + AUT-5's journal writer:** WP8.

---

## 6. Live-proof protocol

### 6.1 Artefact

`docs/evidence/AUT4_LIVE_PROOF_<start>_<end>.md`, produced by a read-only script run by an agent that did not build AUT-4, over 7 consecutive qualifying days (≥ 1 real fill per day, ≥ 5 real fills in the window). Per day:
- LIVE_SEQUENTIAL per fold family (never `no_registered_boundary`), with both ruling shas;
- OFFLINE_CHALLENGER per SHADOW candidate (outcome, n, screen metrics);
- FORWARD_SHADOW per nominee with its four fields and `nomination_feasible` (from the row);
- consumption: every verdict id in `$STATE/evidence/engine_inputs/<venue>/<date>/daily_<ts_ns>.jsonl` with its `acceptance`/`reject_reason`;
- `eval_completeness` and `eval_replay_path` PASS, the `eval_staleness` intraday HEALTH verdicts cited in the ATTEST rows, timer-only runs, and `producer_code_sha` values in `pins.py`.

**Candidate coverage.** At least 3 of the 7 days carry ≥ 1 candidate verdict from one of:
1. **Real AUT-3 candidates:** OFFLINE screen verdicts, plus FORWARD_SHADOW for any nominee.
2. **The AUT-7 drill child** while SHADOW or CHALLENGER on the real venue: its OFFLINE `INCONCLUSIVE(NOT_DISTINCT)` (tagged `drill`), journaled by the real engine pass.
3. **The fixture-candidate path (r4: isolated by state root):** the same pinned `eval_offline` closure runs against `/home/jon/.local/share/breezy-autonomy-fixture/` (its own registry, verdict, journal and evidence trees), holding a deterministic recalibration child of the champion artefact, on real archive and tape days; AUT-5's engine runs a pass against that root. Verdicts carry `metrics.fixture_candidate = true`, never enter the production state root, and exercise screen → nomination row (feasible or not) → FORWARD_SHADOW → journal end to end.

A day with no candidate verdict is otherwise acceptable only if AUT-3's `refit_run/v1` record names `NO_CHANGE(below_delta)`, `NOT_FITTABLE(reason)` or `MINT_REFUSED_CEILING`.

**Score if AUT-3 nominates no real candidate.** Target stays 3, reached through path 2 or 3; the DONE claim states "machinery proven (drill/fixture candidate path), edge unproven; no real AUT-3 candidate was evaluated in the window".

### 6.2 Drills

As r3: SIGKILL `eval_offline` → `OnFailure` CRITICAL `delivered=true`; `eval_staleness` FAIL; ATTEST withheld; recovery; `_stoppost.json` with `service_result=signal`. Oversize tape day. Unpinned producer. Forced `TimeoutStartSec` overrun in a test unit (partial commit, backlog resumed). **(r4)** Added: a fixture nomination with `n_min_eff > n_cap` in the fixture root, showing `nomination_feasible=false`, `alpha_k=0`, `infeasible_nominations` +1 and daily `INCONCLUSIVE(window_cap_below_n_min)`.

### 6.3 Accrual, power and pre-KILL probability

**Measured inputs (2026-10-03),** as r3: FQ IOC fill rate 12/14 = 0.857 (Wilson 95% [0.601, 0.960]); 3.5 station-days with a take per climate day (n = 2 days); σ(fc − mkt) = 0.099 (contaminated window, disclosed); deff assumed 1.5 until WP0; accrual cap 4 station-days a day.

| Verdict | n_min_eff | n_cap | Outcome before the KILL |
|---|---|---|---|
| FORWARD_SHADOW (a), first nomination (α_1) | 605 at deff 1.5 (403 at deff 1) | ⌊4 × 28 × 0.8⌋ = 89 (≤ 480 at 120 days, floor 1.0) | **infeasible**: `alpha_k = 0`, `k_life` stays 0, `INCONCLUSIVE(window_cap_below_n_min)` |
| Any later nomination | ≥ the above (α never deepens while infeasible) | 89 | the same |
| OFFLINE_CHALLENGER screen | `SCREEN_MIN_STATION_DAYS` = 28 (no α) | not capped | PASS/FAIL in ≈ 7 forward days per candidate; a recalibration child (gain ≈ 0.006) is expected to FAIL `X_SCREEN` = 0.0152 |
| LIVE_SEQUENTIAL FQ under R-B | first look 10; n_max per WP7a (r2 value 160) | not windowed | see below |

**Reach probability of n_max = 160** (r2 seeded simulation, seed 20261003, 4000 runs): D0′ 2026-10-25: 0.34 / 0.73 / 0.89 / 0.96 at u = 0.5 / 0.6 / 0.7 / 0.8; D0′ 2026-11-10: 0.05 / 0.33 / 0.67 / 0.86.

**Power at n = 160** (normal approximation, σ₀ = 0.5, one-sided 0.025, LD-OBF final ≈ 2.02): δ = 0.05 / 0.10 / 0.113 / 0.15 → ≈ 0.22 / 0.69 / 0.80 / 0.96. The unconditional SURVIVE probability at δ = 0.10, D0′ 10-25, u = 0.7 is ≈ 0.61. WP7a replaces these with MC values.

**Consequences.** `promote_enabled=false`; PROMOTE is machinery-proven by the AUT-7b drill only; filing R-B early is the only lever for a decisive live verdict; **(r4)** no α is spent and K_LIFETIME is not consumed while every nomination is infeasible, so the lineage keeps its full budget for the day σ or X changes.

### 6.4 Hard prerequisites and ETA

| # | Prerequisite | Owner | Target | Interim behaviour |
|---|---|---|---|---|
| 1 | C4.1 `RULING_holdout_freeze_and_forward_window_2026-10-03` filed (Wave 0) | ARCH-0 | Wave 0 | `INCONCLUSIVE(SEALED_WINDOW)` |
| 2 | R-B `PREREG_FQ_v1` filed; design JSON and boundary committed; precommit check exits 0 | WP7a + peer loop | file 2026-10-24; peer loop ≤ 2026-11-10 | `INCONCLUSIVE(no_registered_boundary)` |
| 3 | AUT-5 policy ruling filed (block with the §5 keys) | AUT-5 | — | OFFLINE/FS rejected `no_ruling`; LIVE FAIL still DEMOTEs via `DEFAULT_RESTRICTIVE_CLASS` |
| 4 | **(r4)** ARCH-0 Wave 0 surfaces shipped: `verdict/v1` (identity without `produced_at_ns`, two ruling-sha fields, five-tag enum, FS fields), C5 nomination columns and counters, `pins.py` ceilings incl. `DEFAULT_RESTRICTIVE_CLASS["live_sequential"]`, `nomination.py` reviewed | ARCH-0 (+ AUT-4 WP5 for `nomination.py`) | Wave 0 / Wave 3 | WP4–WP6 cannot merge (their RED tests import these types) |
| 5 | **(r4)** AUT-5 engine writes `engine_input/v1` and calls `compute_nomination_columns`; a fixture-root engine pass | AUT-5 | Wave 3 | no consumption evidence; the proof window does not open |
| 6 | **(r4)** AUT-6 intraday producer runs `eval_staleness`; policy lists it in `attest_required_detectors` | AUT-6 / AUT-5 | Wave 1 / filing | dead-evaluator veto not live; `eval_staleness` still alerts |
| 7 | **(r4)** AUT-6 memory-sum HEALTH PASS | AUT-6 (+ ING-2 S3a) | — | eval-offline timer not enabled (ARCH §5.2) |
| 8 | WP4–WP6 and WP8 merged and active | AUT-4 | — | — |
| 9 | **(r5)** AUT-3 reproducibility rerun ends ≤ 10:45Z (K8); **(r6, L1/L2)** i.e. 09:35:00Z start with `TimeoutStartSec` ≤ 4139 s (the same request as §3.9 and §5); AUT-5 accepts the K3/K4 requests | AUT-3 / AUT-5 | Wave 3 | WP6 (unit contract test) and WP5 (nomination contract test) stay RED and do not merge |
| 10 | **(r7)** The three AUT-4 `AUTONOMY_BWRAP_TABLE` rows filed, **(r8, E-7c)** each with `--tmpfs /tmp` and `TMPDIR=/tmp`, and **(r9, BL1)** with `--size` set to 2 GiB, 2 GiB or 128 MiB. No ruling is awaited, because E-7b closed O-1. **(r9, BH1)** The eval-offline row is filed under the E-7b (b) named exception, with `test_eval_offline_closure_adapter_set_equals_named_exception`, `test_eval_offline_closure_has_no_adapter_exec_module` and `test_closure_guards_fail_on_head_closure` green after WP1's W1–W4 and the §3.9b gates. **(r10, R-1, FH1)** W5 and R-1 are merged too. The exception has 8 modules at import time, plus the 3 declared R-1 run-time modules, and the run-time closure tests and the import-blocker tests are green at the filing sha | table owner; AUT-4 WP1 (plus the W1–W4 owners) | Wave 1 (WP1) / Wave 3 | eval-offline timer not enabled. eval-live may run once its own row is filed and its closure test is green. If any W is refused, F-1 (§3.9a) |
| 11 | **(r9, BM1)** E-7c sequenced: (1) the wrapper merged with private `/tmp` and `--size`, and `test_bwrap_wrapper_provides_private_tmp` green at that sha; (2) the deployed wrapper's sha256 equals the merged blob; (3) the AUT-4 rows filed; (4) the AUT-4 timers enabled. Order evidenced by `git merge-base --is-ancestor <wrapper_sha> <row_sha>` | wrapper owner, then AUT-4 | before WP4 and WP6 activation | no AUT-4 row filed; no AUT-4 timer enabled |

**ETA.** Earliest 2026-11-23; planning date 2026-11-30; latest acceptable 2026-12-31. If R-B is not filed by 2026-12-01, score 2 is declared in PROGRESS. If prerequisite 7 has not passed by 2026-12-15, PROGRESS records "AUT-4 forward-shadow blocked on the memory sum" and the proof window does not open. **Evidence class: machinery proven, edge unproven.**

---

## 7. Score-3 verification checklist (independent scorer)

| Criterion | Check |
|---|---|
| (a) unattended | `systemctl --user list-timers 'breezy-autonomy-eval-*'`; `journalctl --user -u breezy-autonomy-eval-live.service -u breezy-autonomy-eval-offline.service --since <start>` shows timer-triggered runs only; `ls $STATE/derived/autonomy/eval_runs/*/` shows one producer record and one `_stoppost.json` per run |
| (b) family-agnostic | `test_families_enumerated_from_fold_not_list`, `test_refusing_plugin_family_gets_error`, ARCH `test_family_plugin_exact_set`; one LIVE_SEQUENTIAL per fold family per day |
| (c) fails closed | tests **(r5)** `test_staleness_fails_when_newest_slot_not_today`, `test_same_slot_recompute_bit_identical`, `test_promote_row_columns_written_only_via_compute_nomination_columns`, `test_underpowered_verdict_carries_no_effect_estimate`, `test_forecast_vintage_after_eval_ns_is_leakage_error`, `test_fewer_than_n_proxy_min_fills_inconclusive`, `test_fewer_than_n_ioc_min_inconclusive`, `test_window_cap_below_n_min_is_inconclusive_by_construction`, `test_infeasible_nomination_charges_no_alpha`, `test_k_life_mismatch_is_error_k_exceeded`, `test_error_verdict_is_not_fresh`, **(r6)** `test_look_time_independent_of_nominee_outcomes`, `test_look_counts_signature_takes_no_nominee_input`. Store queries over `$STATE/derived/verdicts/*/*/*.json`, each returning nothing: (1) `jq 'select(.n_min != null and (.outcome=="PASS" or .outcome=="FAIL") and .n < .n_min and .metrics.stop_reason != "loss_stop")'`; (2) `jq 'select(.kind=="LIVE_SEQUENTIAL" and .outcome=="PASS" and .n < .metrics.n_max)'`; (3) `jq 'select(.kind=="FORWARD_SHADOW" and .outcome=="PASS" and (.n_min_eff > .n_cap or (.alpha_k | tonumber) == 0))'` (**r5, K9:** `alpha_k` is a canonical string-decimal, §3.1; `tonumber` makes the query independent of its exact spelling); (4) `jq 'select(.kind=="OFFLINE_CHALLENGER" and .k_life != null)'` |
| (d) detected and delivered | the §6.2 SIGKILL drill: `$STATE/evidence/alerts/<date>/*_d.json` with `delivered=true`; the `eval_staleness` FAIL; no ATTEST row in that window; the `_stoppost.json` record |
| (e) RED→GREEN | RED and GREEN output per §4 test; the gate exits 0 at each merge sha; `lint-imports` "N kept, 0 broken"; WP1 mutation evidence |
| (f) live proof | the §6.1 file; every verdict id present once in that day's daily journal; candidate coverage ≥ 3/7 days with the path named; journal contract tests green |
| Nomination accounting | the registry export rows for each SHADOW→CHALLENGER PROMOTE carry all five columns; `lineage_counters.nominations` equals max `k_life`; `Decimal(alpha_spent) == Decimal("0.025")·(1 − 2^−nominations)` exactly, with `alpha_spent` read as the canonical string (§3.1) |
| Prerequisites | §6.4 rows: ruling files dated before `<start>`; `prereg_precommit_check.py` exit 0; ARCH-0 types at the cited merge shas; AUT-6 memory-sum PASS verdict id |
| Feasibility | daily record with `mde_at_alpha_K`, `n_cap`, `nomination_feasible`, `live_power_at_n_max_by_delta`; `feasibility_consistency` PASS |
| Schedule | `test_units_do_not_contend_on_flock`, `test_aut4_units_outside_launch_window`, `test_offline_successor_lands_before_predecessor_expiry`, `test_attest_cadence_has_no_expiry_gap_with_eval_staleness`, `test_no_autonomy_oneshot_sets_runtime_max_sec`, **(r5)** `test_pre_offline_studies_units_end_by_1045z`; `systemctl --user show -p TimeoutStartUSec breezy-autonomy-eval-offline.service` reports `1h 44min 59s` (6299 s); `/usr/bin/grep -L TimeoutStartSec deploy/systemd/breezy-autonomy-eval-*.service` is empty |
| Honesty | the DONE claim states "machinery proven, edge unproven" and names the candidate-coverage path |
| **(r7)** Reuse | `test_recompute_mde_bit_identical_before_and_after_delegation` (or the fallback equivalence test), `test_sample_size_primitives_single_definition`, `test_p_fill_lb_uses_settlement_wilson`, `test_no_wilson_defined_in_autonomy_packages`, `test_aut4_never_imports_or_writes_hypothesis_ledger`; the AUD-18 test modules byte-unchanged at the merge sha |
| **(r7)** Sandbox and bounds | `test_every_aut4_unit_execstart_and_onfailure_target_goes_through_wrapper`, the self-probe INTEGRITY line absent and its positive-control line present in each run's journal, `test_aut4_sum_of_command_bounds_inside_unit_bounds`, the lint green; `systemctl --user show -p OnFailure breezy-autonomy-eval-*.service` names `breezy-autonomy-failed@` |
| **(r7)** AUT-6 #16 names | `test_eval_replay_path_parity_keys_equal_to_counts_dict_keys` green; one live `eval_replay_path` verdict carries every `EVAL_REPLAY_PATH_METRICS` name |
| **(r8; r9, BH1)** Import closures | Green at the merge sha: `test_eval_offline_closure_adapter_set_equals_named_exception`, `test_eval_offline_closure_has_no_adapter_exec_module` (with the HTTP/WS, `order_enablement` and no-mint clauses), `test_closure_guards_fail_on_head_closure` and `test_eval_live_closure_has_no_adapter_module`. The §0b measurement repeated at that sha shows eval-offline with exactly the ~~11~~ **(r10, R-1)** 8 exception modules at import time, 0 exec, 0 HTTP/WS and no `order_enablement`, and eval-live with 0 adapter modules. `test_hypothesis_ledger_import_closure_gains_only_sample_size` is green (or `::test_hypothesis_ledger_closure_unchanged` under the fallback). `cd <tree> && lint-imports` prints "N kept, 0 broken". `test_execution_egress_firewall_guard` is byte-unchanged |
| **(r9, BH2)** Live-path gates | All §3.9b tests green at each W merge sha: the pins and `test_exec_client_pin_agrees_with_sl13_pin`; the boot smoke; the module and config delta; Arrow parity with its exact-allowance tests; the lazy `__getattr__` tests; the golden replay and its positive control; the W3 and W4 structural tests; `test_permit_line_check.py`. `git -C <tree> diff --exit-code <wp1_base_sha> HEAD -- <ten paths>` is empty. Restart evidence: a restart timestamp inside [01:00Z, 16:40Z), `permit_watch_adopted_live_node pid=<p>` with `<p>` unchanged, and the positive-control and post-boot `permit_line_check.py` outputs (ISSUED with a future expiry, or NOT_REQUESTED recorded as such) |
| **(r9, BL1, BM1)** Scratch cap and sequencing | `test_tmpfs_cap_enforced_enospc` on all three rows; `test_tmpfs_cap_inside_memory_budget`; `test_aut4_rows_require_wrapper_private_tmp`; `git merge-base --is-ancestor <wrapper_merge_sha> <aut4_row_filing_sha>` exits 0; the deployed wrapper's sha256 equals its merged blob |
| **(r8)** Scratch and binds | `test_each_aut4_row_has_private_tmp`, `test_fixture_row_positive_and_negative_probes` (with its positive control), `test_missing_bind_source_fails_unit_before_producer`, `test_child_scratch_dir_removed_on_success_and_failure`; the WP6 verify-first record of T, with S = ⌈1.25·(R + T)⌉ below `MemoryHigh` |
| **(r8)** Numerics | `test_recompute_mde_nonpositive_n_message_pinned`; the LOW-1 grid sweep with its boundary-case list and constructed positive control |
| **(r10, FH1, R-1)** Run-time closure | Green at the merge sha and at the row-filing sha: `test_eval_offline_runtime_closure_after_golden_replay`, `test_eval_offline_runtime_closure_after_sfo_golden`, `test_deferred_permit_ttl_load_attributed_to_r1_site`, `test_runtime_guard_fails_on_pre_w5_closure`, `test_replay_daily_runner_smoke_runtime_closure_declared`, `test_eval_offline_never_imports_or_spawns_replay_daily_runner`, `test_import_blocker.py::*` and `test_r1_permit_ttl_import.py::*`. The §0c measurement, repeated at that sha, shows eval-offline with 8 adapter modules after import and 11 after the run, where the 3 extra are attributed to `permit_window_for_day`. Exec, HTTP/WS and `order_enablement` are at 0 both times. No eval-offline run's journal shows a non-empty blocker record or an `EXIT_INTEGRITY` exit |
| **(r10, FM1–FM5, FL1)** WP1 hardening | The allowlist gate prints nothing, and `test_allowlist_excludes_protected_paths` passes. Also green: the W3 and W5 import-delta tests; `test_fq_strategy_keeps_module_level_bucket_name`, with `test_d1_cache_union.py` byte-unchanged and green; the 65-module cold-import test; the SFO golden and its positive control; the widened Arrow-loss test; the new-entry Arrow test; the golden-catalog smoke of the 8 scripts. The restart evidence includes the step-2a boot smoke with `EXIT=0` on the primary tree before the restart. If step 7 ran, the evidence also includes the revert sha and its base-equality `git diff --exit-code` output |
| **(r10, R-2, R-3)** Rulings | Green: `test_wrapper_applies_default_tmpfs_size_to_rows_without_one`, `test_wrapper_malformed_tmpfs_size_fails_closed` and `test_er2_waiver_scoped_to_eval_offline_row`. Every AUT-4 row carries an explicit `tmpfs_size_bytes`. ER-1 and ER-2 are filed in `reviews/ARCH-ERRATA-rev9_2.md` with the ruled text of §10 |

---

## 8. Risks and failure modes

| Risk | Mitigation |
|---|---|
| **Statistical capacity / KILL 2027-01-25** | Infeasible nominations stated, not hidden; no α spent while infeasible; power at n = 160 reported; R-B early is the only lever; score-2 date set |
| Type I inflation across windows | Lifetime `k_life` never resets; ≤ 1 nomination per window; K_LIFETIME ≤ 4; single look; LD-OBF for live; screening carries no type-I claim |
| Uncomputable deep tests | `BOOTSTRAP_B_MAX` 2¹⁹ ≥ ⌈200/(α_4/3)⌉; tail guard alerts if reached |
| k collision | single engine writer under `engine.lock` with CAS; FS copies from the row; mismatch is `ERROR`/`k_exceeded` |
| Joint-bound under-coverage in (b) | Bonferroni α_k/3; `N_IOC_MIN`; Manski worst case; `ACCEPT_FILL_SELECTION_SENSITIVE` |
| Calibration conjunct false-fails | relative paired test, one margin, `MIN_CALIBRATION_BUCKETS` fail-closed; WP0 false-fail bound ≤ 0.20 |
| R-B tuned on the prefix | data-free σ₀; take counts; tape asks; precommit disclosure; limit stated |
| Mixed closures | closure-keyed outputs; current-closure n; `mixed_closure` breach guard |
| **(r5)** Non-reproducible resampling across same-slot recomputes | per-(subject, slot, role) derived seed; `test_same_slot_recompute_bit_identical` |
| **(r5)** Engine and feasibility record drift apart | one `sample_size` definition; all inputs pinned block keys; projection-equals-columns test; transaction contract test |
| **(r5)** A stale-but-unexpired verdict keeps ATTEST alive | today's-slot rule at 15:25Z; newest per (family, kind) consumption |
| **(r5)** A pre-11:00 study holds the flock into eval-offline's budget | end ≤ 10:45Z contract test; AUT-3 rerun request |
| Label run overruns into eval-live | shared studies flock with a 300 s wait; a timeout writes no verdict and `eval_staleness` alerts by 15:25Z |
| Oneshot unbounded | `TimeoutStartSec` on both units; programme deploy test |
| Memory on the 30 GiB host | 14G/12G per ARCH §5.2; measured peak before enablement; memory-sum gate; ≤ 16G raised cap only by review in a free slot; never 01:00–04:30Z; stop the study, never the node |
| Fixture path contaminates production | separate state root; `fixture_candidate` metric; contract test that no fixture journal lands under `$STATE` |
| **(r7)** The `recompute_mde` delegation changes an AUD-18 number | bit-identity golden grid captured before the edit; three AUD-18 test modules byte-unchanged; owner review; fallback keeps the module untouched |
| **(r8; r9)** Replay children breach the E-7a adapter closure (measured: 33 adapter modules at HEAD, `exec.client` and HTTP/WS among them; 25 even after r8's M1–M3; §0b) | E-7b (b) declared on the measurement; W1–W4 bring the closure to 11 non-exec modules, 0 exec, 0 HTTP/WS; the exact-set test catches growth; the exec guard has a negative control on the HEAD closure; F-1 is explicit; no enablement, permit, exec or firewall file is edited (sha-pinned) |
| **(r9)** A lazy `__init__` defers an `ImportError` to first use on the live path | the boot smoke resolves every `__all__` name and every HEAD-bound submodule in a fresh process per live entry; the one function-local package import is resolved by test |
| **(r9)** A lazy `__init__` or the W3 cut drops an Arrow registration that something reads | strict parity on every live entry (measured equal); an exact allowance only for offline entries that never name the type; Nautilus fails loudly on an unregistered type |
| **(r9)** The supervisor keeps running pre-W1 code; a restart disturbs the node | a windowed restart in [01:00Z, 16:40Z) with `KillMode=process`; adoption line with an unchanged pid; a scripted permit-line check with a positive control; revert path |
| **(r9)** Scratch overflow | per-row `--size` cap (2 GiB / 2 GiB / 128 MiB); `ENOSPC` commits nothing and is visible to `eval_completeness`/`eval_replay_path`; the cap is inside the memory budget |
| **(r8)** Private-`/tmp` scratch exhausts eval-offline memory | T measured at WP6 verify-first and added to S; child scratch removed in `finally`; `MemoryMax` bounds it; tmpfs is never a durable path |
| **(r8)** `sample_size` drags Nautilus into AUD-18's pure core | lazy `persistence/__init__` or the RC-1 fallback; exact fresh-process closure test; `lint-imports` gate |
| **(r7)** A wrapper or table fault silences an evaluator | self-probe INTEGRITY with a delivered CRITICAL; wrapped `breezy-autonomy-failed@` with AUT-6's 126/127 fallback; `eval_staleness` FAILs by 15:25Z |
| Shared venv / concurrent agents | exact interpreter; no `uv`/`pip`/`stash`; worktree `PYTHONPATH`; per-agent scratchpads; explicit-path commits |
| **(r10, FH1)** A function-local or lazy import loads an exec, HTTP/WS or `order_enablement` module mid-run inside the sandbox. This was measured: under r9's cuts, `strategy.py:308` did exactly that | W5 removes the measured path. Run-time closure snapshots are taken after both golden replays and after a runner smoke run. A `sys.meta_path` blocker in every eval-offline process fails closed on its record, not on the swallowed exception. A negative control runs on the recorded pre-W5 closure |
| **(r10, R-1)** `safety` is still reachable at run time through the R-1 site | It is declared as a separate set and attributed by stack to `permit_window_for_day`, so any other loader fails. The mint function has no caller (B7). The credentials mount is a tmpfs. I-5 is stated for the peer loop |
| **(r10, FM1)** A failed post-restart permit check at 16:50Z cannot wait for the window | An immediate tree-only revert, checked equal to the base, because the node reads source at spawn. Only the supervisor restart waits for the window. The boot smoke runs against the deployed tree before any restart |
| **(r10, FM3)** An unpinned file outside the cut set changes in WP1, for example `fees.py`, `parsing.py` or `exec/refusals.py` | The whole-diff allowlist gate, plus a test that the allowlist names no protected path |

---

## 9. Binding-constraint compliance

- **Nautilus immutability:** only native `BacktestEngine`, `ParquetDataCatalog` and Actor composition, reused through the moved `run_live_parity`; nothing patched.
- **Caps:** never read, written or assigned. The R-B loss stop is a PREREG statistic in contract units. `test_autonomy_never_reads_or_writes_operator_controls` covers `breezy.analysis.autonomy` and `breezy.persistence.autonomy.nomination`.
- **allow_short=False:** untouched.
- **NO-SEND:** the refusing submit veto; no exec client; the exec store is never imported; `test_execution_egress_firewall_guard` unchanged. **(r8)** The M3 lazy `__init__`s edit no exec, enablement, permit or firewall module. Loading fewer adapter modules into the replay closure only shrinks what the replay can reach. **(r9)** W1–W4 replace M1–M3. The ten NO-SEND, permit and guard files are sha-pinned and diff-checked (§3.9b). The permit-type seam was rejected precisely because it would edit the minting path. **(r10)** W5 and R-1 edit no NO-SEND, permit or enablement file. The eval-offline run-time closure is now measured and gated, no longer inferred from import time, and the import blocker refuses exec, HTTP/WS and `order_enablement` in every eval-offline process.
- **Master enablement and permit:** never touched. The fixture path never writes the production registry.
- **PREREG via ruling:** R-B…R-G are drafts for the peer loop; C4.1 is consumed by name; no PREREG semantics change in this plan.
- **(r7) Sandbox:** every AUT-4 unit under the E-7a wrapper; C5 and the production root read-only by mount; credentials tmpfs; no directive claimed as a control (E-7 rule 1). **(r8)** E-7b branch (a) before (b), with closure tests; E-7c private `/tmp` on every row, never a durable path; the quarantine bind narrowed to its own directory. **(r9)** E-7b (b) is taken on measured evidence, scoped to 11 named non-exec modules and guarded by an exact-set test, an exec/HTTP/no-mint guard and a negative control. Every row has `--size`-capped private `/tmp` (BL1). E-7c is a sequenced gate ahead of every AUT-4 row (BM1).
- **(r9) `promote_enabled`:** stays `false`. Nothing in r9 changes the feasibility arithmetic or any promotion path.
- **(r9) Hard invariants:** restated in the header block after the headline and bound into every WP brief. **(r10)** Extended there with the unchanged permit-minting path.
- **Safety tests:** none weakened; **(r7)** the AUD-18 test modules and `test_offline_successor_lands_before_predecessor_expiry` unchanged; golden and contract tests byte-unchanged; the G36 move keeps the existing tests green; new tests only add.

---

## 10. Self-score

**(r11) Re-scored.**

| Axis | Max | r10 | r11 | Note |
|---|---|---|---|---|
| Fidelity | 20 | 19 | 20 | I-5 is accepted under (a) by both reviewers, so r10's −1 is withdrawn. ER-1 and ER-2 are ADOPTED |
| Correctness | 20 | 19 | 19 | F1 fixes a real exit-code defect, and the fix rests on a measurement on the project interpreter. Attribution is by module, not depth. −1: the r11 exit path and its four tests are new and unreviewed |
| Specificity | 15 | 15 | 15 | Every new test is named with its file; the malformed-size test is named in ER-1 |
| Acceptance | 20 | 16 | 16 | Unchanged dependencies |
| Autonomy-safety | 15 | 14 | 14 | The blocker now gates every commit and cannot be installed by a live entry (F4). −1 unchanged: the dead-evaluator veto depends on the policy listing `eval_staleness` |
| Reuse | 10 | 9 | 9 | Unchanged |
| **Total** | 100 | 92 | **93** | Reviewers scored r10 at 95 and 94 |

r10 self-score (historical, superseded by the r11 table above):

**(r10) Re-scored.**

| Axis | Max | r9 | r10 | Note |
|---|---|---|---|---|
| Fidelity | 20 | 20 | 19 | R-1, R-2 and R-3 are applied as ruled, and ER-1 and ER-2 are restated in the ruled words. −1 for I-5: R-1's goal is met at import time, but 3 modules still load at run time. They are declared and attributed, and how to read that is for the peer loop |
| Correctness | 20 | 19 | 19 | FH1 is confirmed and fixed on a run-time measurement, not an import-time one. The W3 import delta and the monkeypatch target are corrected from a real move and ruff output. 143 of 147 tests pass on the copy, the same as on HEAD (the 4 failures are archive artefacts in both). −1: W5 and the blocker are new and unreviewed |
| Specificity | 15 | 15 | 15 | Every cut, test, fixture path, command and measured count is named with file:line |
| Acceptance | 20 | 16 | 16 | W5 goes to the owner who already reviews W4. The R-1 review is one line. The immediate revert removes a wait for the window. The other dependencies are unchanged |
| Autonomy-safety | 15 | 14 | 14 | The run-time closure is gated, the blocker fails closed on its record, and there is a negative control on the pre-W5 closure. −1 unchanged: the dead-evaluator veto depends on the policy listing `eval_staleness` |
| Reuse | 10 | 9 | 9 | The blocker reuses `_FINDER_PREAMBLE`'s shape; the T9 subprocess shape and the stdlib `pkgutil` are reused. −1 unchanged |
| **Total** | 100 | 93 | **92** | Reviewers scored r9 at 91 and 86 |

r9 self-score (historical, superseded by the r10 table above):

**(r9) Re-scored.**

| Axis | Max | r8 | r9 | Note |
|---|---|---|---|---|
| Fidelity | 20 | 20 | 20 | E-7b is consumed through branch (b) under its own stated condition, measured; E-7c is consumed with a numeric cap (ER-1 asks only for a wording addition); I-4 is stated |
| Correctness | 20 | 19 | 19 | BH1 is decided on a simulated closure, not a claim. M1, M2 and the `ladder_ev` request are withdrawn on evidence. The Arrow-registration loss that BH2 suspected was measured and handled. −1: the r9 text is unreviewed |
| Specificity | 15 | 15 | 15 | Every cut, pin (full sha256), entry, test, command and expected output is named with file:line |
| Acceptance | 20 | 16 | 16 | Unchanged dependencies: rulings, memory sum, Wave 3, AUT-3/AUT-5 requests. Three owner reviews of live-path edits, plus a windowed restart, replace r8's three `__init__` reviews. F-1 is explicit |
| Autonomy-safety | 15 | 14 | 14 | Permit and NO-SEND files sha-pinned; exec guard with a negative control; the scratch cap fails closed. −1 unchanged: the dead-evaluator veto depends on the policy listing `eval_staleness` |
| Reuse | 10 | 9 | 9 | The boot smoke, entry list, pin pattern and permit parsers are reused, not copied. −1 unchanged |
| **Total** | 100 | 93 | **93** | Reviewers scored r8 at 92 and 88 |

r8 self-score (historical, superseded by the r9 table above):

**(r8) Re-scored.**
- **Fidelity** returns to 20: E-7b and E-7c are consumed, and O-1 is closed.
- **Correctness** stays at 19:
  - AH2 and AH5 correct two r7 statements: the error text would have changed, and "gains only `sample_size`" was false.
  - LOW-1's ulp gap is measured, not assumed.
  - −1, because the r8 text is unreviewed.
- **Acceptance** falls by 2: activating eval-offline now depends on the measured M1–M3 moves, which include three package `__init__`s owned outside AUT-4. The previous dependency was a ruling.
- The r5 rule that excludes unmeasurable values still applies.

| Axis | Max | r7 | r8 | Note |
|---|---|---|---|---|
| Fidelity | 20 | 19 | 20 | E-7b and E-7c consumed in §3.9a; O-1 closed; I-3 (scope of the HTTP/WS clause) stated for the peer loop |
| Correctness | 20 | 19 | 19 | AH2 keeps the exact `ValueError` text; AH5 states the real closure from a measurement; LOW-1 handles the 1-ulp `ceil` flip. −1: r8 text unreviewed |
| Specificity | 15 | 15 | 15 | Every edge, path, bind, test and measurement cited with file:line |
| Acceptance | 20 | 18 | 16 | −2 (unchanged): rulings, memory sum, Wave 3, AUT-3/AUT-5 requests. −2 (new): eval-offline activation needs M1–M3, owner-reviewed outside AUT-4, with N-1 as the only route if refused |
| Autonomy-safety | 15 | 14 | 14 | Bind narrowed; missing bind fails closed; private `/tmp` never durable. −1 unchanged: the dead-evaluator veto depends on the policy listing `eval_staleness` |
| Reuse | 10 | 9 | 9 | Unchanged; the M1–M3 moves are moves with aliases, not new code |
| **Total** | 100 | 94 | **93** | Reviewers scored r7 at 94 and 93 (final 93) |

r7 self-score (historical, superseded by the r8 table above):

**(r7) Re-scored.** Reuse rises by 1: the MDE/power/n_min core is now shared with AUD-18's `recompute_mde`, the Wilson bound is reused, the α-ledger non-reuse is argued from four pieces of evidence, and WP7a shrinks to the one comparison nothing in the repo performs. It stays at 9, not 10, because the permutation test, the calibration NI test, seeding and the nomination/journal contract code are still new (no existing equivalent was found). Fidelity loses 1 for O-1, an open coordinator ruling on an erratum's reach. Correctness stays at 19 (−1: the r7 text is unreviewed). The r5 rule excluding unmeasurable values still applies.

| Axis | Max | r6 | r7 | Note |
|---|---|---|---|---|
| Fidelity | 20 | 20 | 19 | E-7/E-7a/E-8a/E-9/E-10 consumed in §3.9a; the #16 names registered. −1: O-1 (adapter closure of replay children) awaits a coordinator ruling |
| Correctness | 20 | 19 | 19 | RC-1 bit-identity argued from the exact operation order and √0.25 = 0.5; E-9 bounds sit inside the r6 unit bounds. −1: r7 text unreviewed |
| Specificity | 15 | 15 | 15 | Every reused symbol cited with file:line; every bound, bind and metric name stated |
| Acceptance | 20 | 18 | 18 | Adds the AUD-18 review and O-1 as dependencies, offset by the fallback that removes the first |
| Autonomy-safety | 15 | 14 | 14 | Read-only C5 and fixture isolation now enforced by mount. −1 unchanged: the dead-evaluator veto still depends on the policy listing `eval_staleness` |
| Reuse | 10 | 8 | 9 | RC-1..RC-4 closed; −1: permutation, calibration NI, seeding and contract code are new |
| **Total** | 100 | 94 | **94** | |

r6 self-score (historical, superseded by the r7 table above):

**(r6, L4) Re-scored.** r5's two open Correctness deductions were for K8 and K9 being unreviewed. Both reviewers have now reviewed them: K8 had a 1 s off-by-one, fixed by L1, and K9's ancillarity argument lacked a test, added by L3. That restores 1 point. One point stays deducted because the L1 arithmetic and the L3 test are new in r6 and unreviewed. All other axes are unchanged, and the r5 rule that excludes unmeasurable values still applies.

| Axis | Max | r5 | r6 | Note |
|---|---|---|---|---|
| Fidelity | 20 | 20 | 20 | Unchanged |
| Correctness | 20 | 18 | 19 | L1 fixes the K8 off-by-one (4139 s from 09:35Z) in §3.9, §5 and §6.4 row 9; L3 makes the K9 ancillarity an invariant, backed by a nominee-outcome-independence test. −1: the L1/L3 text is new in r6 |
| Specificity | 15 | 15 | 15 | Unchanged; L2 gives one AUT-3 start time throughout |
| Acceptance | 20 | 18 | 18 | Unchanged dependencies (rulings, memory sum, Wave 3, AUT-3/AUT-5 requests) |
| Autonomy-safety | 15 | 14 | 14 | Unchanged |
| Reuse | 10 | 8 | 8 | Unchanged |
| **Total** | 100 | 93 | **94** | Reviewers scored r5 at 95 and 93 (final 93); 94 sits inside that range |

r5 self-score table (historical, superseded by the r6 table above):

**(r5, K10) Re-scored excluding unmeasurable values.** Values that only WP0/WP7a can measure (σ, `sigma_b_pinned`, ρ̂/deff, per-child R and t_p95, the R-C false-fail rate and `n_min_c` table, the MC power and reach probabilities) are **excluded from the score**: neither credited nor deducted. Each has a stated hard-fail rule that returns the WP to review if the measurement breaks the design (§3.10 R-C ≤ 0.20 false-fail; §3.12 t_p95 and memory rules; feasibility record). r4 deducted 3 points for them under Correctness.

| Axis | Max | r4 | r5 | Note |
|---|---|---|---|---|
| Fidelity | 20 | 19 | 20 | Every Rev 9.2 §10 obligation mapped; errata E-3 applied; I-1 and I-2 endorsed by both reviewers, so r4's −1 is withdrawn |
| Correctness | 20 | 17 | 18 | K1–K9 close every reviewer finding (single sample-size definition, transaction call, today's-slot staleness, 6299 s bound, NO_INPUT kind, derived seeds, 10:45Z rule, look waiting on ancillary counts). −2: the ancillary-count look rule (K9) and the 10:45Z rule (K8) are new in r5 and unreviewed |
| Specificity | 15 | 14 | 15 | Every constant, key, seed formula, unit bound and test named |
| Acceptance | 20 | 17 | 18 | Checklist queries robust to Decimal spelling; new contract tests. −2: the proof window still waits on rulings, the memory sum, Wave 3 and the AUT-3/AUT-5 requests (dependencies, not unmeasurables) |
| Autonomy-safety | 15 | 14 | 14 | Fail-closed; stale-unexpired verdicts no longer keep ATTEST alive. −1: the dead-evaluator veto still depends on the policy listing `eval_staleness` |
| Reuse | 10 | 8 | 8 | −2: new permutation, calibration-NI, seeding and journal/nomination contract code |
| **Total** | 100 | 89 | **93** | Reviewers scored r4 at 94 and 91 (final 91), above r4's self-score; 93 sits inside that range |

### Contradictions with ARCH

**None open.** P4-7 to P4-15 are resolved by ARCH Rev 9.2 and deleted from this plan (see §R4). No new contradiction was found. **(r8)** O-1 is closed by E-7b.
- ~~**N-1** (§3.9a) is a contingent question. It goes to the coordinator only if the M1–M3 moves are refused. It is not a contradiction.~~ **(r9)** N-1 is declared as the E-7b (b) named exception. That is a use of E-7b, not a contradiction of it. The coordinator is asked only under F-1.
- **(r9) I-4** (for the peer loop). E-7b (a) words the symbology move as "required first". r9 performs the measurement that (a) requires, but not the move itself, because §0b shows the shimmed module stays in the closure through `fees` → `parsing` under the (b) exception.

**(r11) Peer-loop outcome on r10** (`reviews/AUT-4-r10-merged.md`, both reviewers agreeing).
- **ER-1: ADOPTED.** The ruled text below stands unchanged. Its fail-closed test is now named (F6).
- **ER-2: ADOPTED.** The ruled text below stands unchanged, with its test `test_er2_waiver_scoped_to_eval_offline_row`.
- **I-5: ACCEPTED under option (a).** `safety`, `credentials` and `secure` are accepted as the named run-time set `E7B_EVAL_OFFLINE_DEFERRED_PERMIT_TTL`. The set is exact (growth and shrinkage both fail) and its admission requires stack attribution to `permit_window_for_day` in module `nbp_shadow_parity_pure` (F3). It is not folded into the import-time exception. I-5 is closed.

**(r10, R-2, R-3) Errata requests as ruled.** These supersede the r9 wording below.
- **ER-1 (E-7c; ruled R-2: ADOPT, with a default).** Add to E-7c:
  > "The shared wrapper passes `--size <bytes>` immediately before `--tmpfs /tmp`. `<bytes>` is the row's `tmpfs_size_bytes` when the row carries one, and the wrapper's `DEFAULT_TMPFS_SIZE_BYTES` otherwise, so a row filed without a size keeps working unchanged. A malformed `tmpfs_size_bytes` (not an `int`, ≤ 0, or above the wrapper's maximum) fails closed before `bwrap` runs. AUT-4's rows carry explicit per-row values."
  - Tests: §3.9a (BL1, R-2); §7. **(r11, F6)** The fail-closed test is named: `tests/contract/test_autonomy_units.py::test_wrapper_malformed_tmpfs_size_fails_closed` (each of `"2G"`, `0`, `-1`, `True` and a value above the maximum exits non-zero before `bwrap` runs). The default-size test is `tests/contract/test_autonomy_units.py::test_wrapper_applies_default_tmpfs_size_to_rows_without_one`.
- **ER-2 (E-7b; ruled R-3: AMEND, combining both reviews).** Add to E-7b:
  > "The branch-(a) symbology move is waived for the `eval-offline` row only, and only while two conditions hold: (i) the WP1 measurement shows that the shimmed module stays in that row's closure through a module inside the (b) named exception; and (ii) the (b) guard tests (`test_eval_offline_closure_adapter_set_equals_named_exception`, `test_eval_offline_closure_has_no_adapter_exec_module`, `test_closure_guards_fail_on_head_closure`) and the run-time closure tests are green. The waiver never extends to `order_enablement` or to any `exec*` module. It does not waive (b)'s condition that the replay needs non-exec adapter modules consumed by the native `BacktestEngine`."
  - Test: `tests/unit/autonomy/test_closure.py::test_er2_waiver_scoped_to_eval_offline_row`. Only the eval-offline row of `AUTONOMY_BWRAP_TABLE` may carry the `E7B_EVAL_OFFLINE_ADAPTER_MODULES` exception. The set may contain no `exec*` module, no `factories` and not `order_enablement`.
- **I-5 (r10, R-1 with FH1; ~~for the peer loop~~ (r11) ACCEPTED, option (a), see above).**
  - R-1 removes `safety`, `credentials` and `secure` from the import-time closure, as ruled.
  - They still load at run time, because the replay's permit stub calls `permit_window_for_day` (§0c finding 3).
  - Removing them at run time too would take either a re-declared constant, which R-1 forbids, or an edit to the sha-pinned `safety.py`, which the invariants forbid.
  - So r10 declares them as a separate run-time set, attributed by stack to the single R-1 site. It does not fold them back into the exception.
  - This states what R-1 achieves, as measured. It does not contradict R-1.

**(r9) Errata requests** (superseded by the ruled text above; kept for the record).
- **ER-1 (E-7c wording; needed).** Add to E-7c: "The shared wrapper passes `--size <row.tmpfs_size_bytes>` immediately before `--tmpfs /tmp`. Every row carries a `tmpfs_size_bytes`; a row without one fails closed."
  - Reason: E-7c says the wrapper "always adds `--tmpfs /tmp`" and names no size. The binding BL1 needs a numeric cap, which only the wrapper can apply.
- **ER-2 (E-7b wording; clarifying, optional).** Add to E-7b (a): "The symbology move is not required when the WP1 measurement shows the shimmed module remains in the closure through a module that is in the (b) exception."
  - Reason: this removes the I-4 reading question. If ER-2 is declined, I-4 stands for the peer loop, and the W-set does not change.
- **I-3** (the HTTP/WS clause is scoped to venue client modules, because any Nautilus import loads `nautilus_pyo3`) is an interpretation for the peer loop. It is not a contradiction.

---

## §R8 Disposition (review `reviews/AUT-4-r7-merged.md`; errata E-7b, E-7c in `reviews/ARCH-ERRATA-rev9_2.md`; ARCH Rev 9.2 sha `1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42`)

**9 items: 9 ACCEPTED, 0 rejected.**
- **Boundaries.** No ARCH contradiction is introduced. No README criterion, cap, enablement, permit, NO-SEND or `allow_short` surface is touched. No operator-reserved control is read, assigned or bypassed.
- **No test is weakened.**
  - These stay byte-unchanged: the AUD-18 test modules, `test_hypothesis_register.py`, `test_execution_egress_firewall_guard`, `test_offline_successor_lands_before_predecessor_expiry`, and the adapter and `current_rung_hold` test modules.
  - These r7 tests are strengthened: `test_eval_offline_closure_has_no_adapter_exec_module` (HTTP/WS clause), `test_hypothesis_ledger_import_closure_gains_only_sample_size` (now exact), and `test_n_min_one_sided_matches_nbp_compute_n_min_at_alpha_0_025` (now a grid).
- **New tests: 12.**
  - `test_eval_offline_closure_has_no_adapter_module` and `test_eval_live_closure_has_no_adapter_module`.
  - `test_moved_names_are_aliases_of_domain_objects`, `test_lazy_package_inits_return_identical_objects` and `test_lazified_inits_have_no_side_effect_statements`.
  - `test_recompute_mde_nonpositive_n_message_pinned`.
  - `test_each_aut4_row_has_private_tmp`, `test_fixture_row_positive_and_negative_probes` and `test_missing_bind_source_fails_unit_before_producer`.
  - `test_child_scratch_dir_removed_on_success_and_failure`, `test_writers_mkstemp_in_final_dir` and `test_quarantine_writer_appends_only_own_file`.
- **Cross-plan requests.**
  - Closed: 1 (O-1).
  - New: 3.
    - ARCH-0: a lazy `persistence/__init__`.
    - Owner review of three lazy package `__init__`s.
    - The table owner: the wrapper harness's root substitution, if it is missing.
  - Contingent: 1 (N-1).
- **New read-only evidence:** §0a.

| # | Finding | Disposition | Where |
|---|---|---|---|
| AH1 | [both] O-1: cite E-7b, mark it closed, drop the §6.4 row-10 wait, add E-7b's "no HTTP/WS client" clause to `test_eval_offline_closure_has_no_adapter_exec_module`. WP1 lists the closure measurement; for branch (a), also the symbology shim and the closure test | **ACCEPTED, with one measured addition.** O-1 is marked closed and E-7b is cited verbatim in substance. The row-10 wait is replaced by a build gate. The guard test gains the HTTP/WS clause, with I-3 stating its scope. WP1 lists the measurement, the shim (M1) and the closure tests. **Addition:** the measurement taken at planning time (§0a) shows 33 adapter modules reached through 26 edges. The symbology shim alone cannot clear them: `exec.client` arrives through the eager `current_rung_hold`/`ladder_ev` `__init__`s, and HTTP/WS through the eager adapter package `__init__`, which also blocks (b)'s guard. Branch (a) is therefore M1–M3, owner-reviewed, with N-1 as the fallback. No enablement, permit, exec or firewall file is edited | Header, headline, §0a, §3.9a, WP1, WP6, §5, §6.4, §7, §8, §9, §10 |
| AH2 | [MLE] Keep the `n ≤ 0` guard and its exact `ValueError` text in `recompute_mde`; pin it with a test | **ACCEPTED.** The guard and its text (`hypothesis_ledger.py:868-869`) stay ahead of the delegation, so `sample_size`'s refusal cannot be reached through `recompute_mde`. `test_recompute_mde_nonpositive_n_message_pinned` checks exact `str()` equality and that the spy is not called; its RED evidence is a mutation | §2, WP2, §7 |
| AH3 | [MLE] Consume E-7c in all three §3.9a rows; add the `fs_replay` child's scratch writes to WP6 verify-first | **ACCEPTED.** `--tmpfs /tmp` and `TMPDIR=/tmp` are on every row. WP6 verify-first records the child's write paths and T, its peak `/tmp` bytes. T enters S because tmpfs pages are charged to the cgroup. Durable writers use `mkstemp(dir=final dir)`, since a rename out of `/tmp` gives `EXDEV`. Scratch is removed in `finally`. Three tests | §3.9a, §3.12, WP6, §7, §8 |
| AH4 | [MLE] Resolve the quarantine path now, read-only, from `replay_daily_runner`, or mark the row "not filed until WP6 verify-first" with fail-closed behaviour | **ACCEPTED, resolved.** The runner has no oversize quarantine (only the fee-void rename, which AUT-4 does not touch). The path is rooted at its `_DERIVED_ROOT / "replay"` (`:187-197`) as the dedicated directory `$STATE/derived/replay/oversize_quarantine/`, one file per consumer. Binding the parent is rejected. A missing directory fails the unit before the producer runs (CRITICAL; `eval_staleness` FAIL), with a test; WP6 re-checks the path | §0a, §3.9a, WP3, WP6 |
| AH5 | [PM] State the real closure of `sample_size`; add `lint-imports` as an explicit WP2 gate; ask ARCH-0 to keep `persistence/__init__` lazy if needed | **ACCEPTED.** Measured: `import breezy.persistence` adds 812 modules including Nautilus, against 50 and no Nautilus for today's `hypothesis_ledger`. No contract breaks. ARCH-0 is asked for a lazy `__init__`; if it declines, the RC-1 fallback applies. The closure test is made exact. `lint-imports` ("N kept, 0 broken", run from the tree, four named contracts) is a WP2 GREEN gate. The note that `lint-imports` is static is stated | §2, §3.3, WP2, §5, §7, §8 |
| LOW-1 | [MLE] `compute_n_min` vs `n_min_one_sided`: a grid sweep over σ and X with ±1-ulp tolerance; a `ceil` flip must be impossible or handled | **ACCEPTED, handled.** The z-sum gap is measured at exactly 1 ulp, so a flip is possible. The sweep asserts the 1-ulp bound and exact equality away from integer brackets. Differences at a bracket are recorded and bounded by 1. A constructed positive control exercises the boundary. AUT-4 never consumes `compute_n_min` | §0a, §2, WP2, §7 |
| LOW-2 | [PM] Positive/negative probe test for the fixture row | **ACCEPTED.** `test_fixture_row_positive_and_negative_probes` covers the fixture-root writes (positive), `EROFS` on four production paths (negative), and a positive control against a vacuous pass | §3.9a, WP6, §7 |
| E-7b | [errata] Venue-adapter import closure of the offline replay children | **CONSUMED.** Branch (a) first, (b) only on WP1 evidence, general narrowing rejected; the guard's full clause is applied. See AH1 for the measured scope of (a) | §3.9a, WP1, §6.4 |
| E-7c | [errata] Scratch space under the shared wrapper | **CONSUMED.** Every row has a private `/tmp` and `TMPDIR=/tmp`, never durable. E-7c's three assertions are run per row; the wrapper's own test belongs to its owner | §3.9a, WP6 |

---

## §R7 Disposition (pressure test `reviews/AUT-NATIVE-pressure-test-2026-10-03.md`; build items `reviews/AUT-4-r6-final.md`; ARCH Rev 9.2 sha `1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42` + `reviews/ARCH-ERRATA-rev9_2.md`)

**10 items: 10 ACCEPTED, 0 rejected.** No ARCH contradiction is introduced; O-1 is raised for a ruling. No README criterion, cap, enablement, permit, NO-SEND or `allow_short` surface is touched. No test is weakened: the AUD-18 test modules, `test_hypothesis_register.py` and `test_offline_successor_lands_before_predecessor_expiry` stay byte-unchanged. New tests: 30. Cross-plan requests: 3 new (AUD-18 owner review; three `AUTONOMY_BWRAP_TABLE` rows; O-1 coordinator ruling).

| # | Finding | Disposition | Where |
|---|---|---|---|
| RC-1 | [native pm] Reuse `hypothesis_ledger.recompute_mde` (:861), parameterised by σ, for `eval_stats.mde_one_sided`/`power_one_sided` and `sample_size.n_min_one_sided` | **ACCEPTED, shared by extraction.** The engine cannot import `breezy.analysis` (G15 and the import-linter contract), so the σ-parameterised formula moves down into `sample_size` and `recompute_mde` delegates to it with σ = 0.5, bit-identically (golden grid plus spy test). `n_min_one_sided` and `power_one_sided` share its `_z_sum`. `nbp_calibration.compute_n_min` is pinned by an equivalence test, not edited. Fallback if the AUD-18 owner refuses: an equivalence test only | §2, §3.3, WP2, §5, §7, §8 |
| RC-2 | [native pm] Name the single Wilson helper `fill_model.py` reuses; no new Wilson | **ACCEPTED.** `src/breezy/settlement/current_rung_hold_v2.py:370` `_wilson_interval`, which is already in `src/` (nothing promoted). It is preferred to `density_table.py:152` because of its layer (settlement, no strategy closure) and its existing equivalence test. One-sided z = z(1 − α_k/3). AST test forbids a Wilson in the autonomy packages | §2, §3.3, §3.7, WP6, §7 |
| RC-3 | [native pm] State why `alpha_remaining` (:825) / `is_variant_eligible` (:839) do or do not serve the nomination α ledger; reuse where they can | **ACCEPTED: they do not serve it.** Four reasons: a Bonferroni split fixed at registration against a geometric per-nomination rule; ARCH C5 owns the ledger; the engine cannot import analysis; `register_hypothesis` refuses LD-OBF. Their rules are reused as tests (no cross-lineage pooling; single look never reopened), and an isolation test keeps the two ledgers disjoint | §2, WP2 |
| RC-4 | [native pm] Check existing PREREG precommit and disclosure tooling before WP7a's script; reuse it if it exists | **ACCEPTED.** None performs the birth-time disclosure comparison (searched). Reused: `hypothesis_register._git_tree_is_dirty`, its 40-hex freeze-commit rule, and `gs_boundary_artefact.load_boundary_artefact` for the committed boundary. The script shrinks to the comparison | §2, §3.10 R-B, WP7a |
| E-7/E-8 | [r6-final] AST read-only test; rename sandbox-parse tests to `*_config_*` | **ACCEPTED.** The read-only lint over the four entry closures with positive controls; r6 has no sandbox-directive-parsing test, so nothing is renamed, and any later one is `*_config_*`. C5 reads add `PRAGMA query_only=ON`. E-8 itself has no AUT-4 surface | §3.1, §3.9a, WP6 |
| E-7a | [r6-final] Universal bwrap via the shared wrapper and table; WAL via the snapshot helper; AST check is a lint | **ACCEPTED.** Three table rows (eval-offline, eval-live, fixture), the same-bind rule, `timeout -k` → `flock -w` → wrapper, the wrapped `breezy-autonomy-failed@` notifier, the wrapper test, a WAL input inventory with snapshot reads, and the lint per rule 4. O-1 raised for the replay children's adapter closure | §3.9, §3.9a, WP4, WP6, §6.4 row 10 |
| E-8a | [r6-final via AUT-6 r11] Snapshot helper API; node-up reads advisory | **ACCEPTED.** AUT-4 passes `take_flock=False` everywhere and never takes the intent flock; production units never read the exec store; WP0's baseline read is advisory | §3.9a |
| E-9 | [r6-final] Bound each command and sum the bounds | **ACCEPTED.** `timeout -k` bounds of 6290 s, 1490 s and 55 s, each inside its unit bound; the internal deadline is inside the external bound; worst ends unchanged; 5 contract tests | §3.9a |
| E-10 | [errata] Two timing readings | **ACCEPTED, no row moves.** (a) has no AUT-4 unit; (b) ends ≤ 16:49:50, disjoint from AUT-4's 12:46:00 and 15:11:01 ends | §3.9a |
| MN-1 | [r6-final, from AUT-6 r13] Register the `eval_replay_path` tape-day and parity-result metric names in `metric_registry` before go-live | **ACCEPTED.** `EVAL_REPLAY_PATH_METRICS`: `tape_day`, `closure_sha256`, `subject_role`, `admitted_station_days`, `excluded_by_reason`, `parity` (the `ParityReport.to_counts_dict` keys verbatim plus three Take counts), counts only; 3 tests including key equality with `to_counts_dict` | §3.3, §3.11a, WP8, §5, §7 |

---

## §R6 Disposition (review `reviews/AUT-4-r5-merged.md`; ARCH Rev 9.2 sha `1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42` + `reviews/ARCH-ERRATA-rev9_2.md`)

**4 items: 4 ACCEPTED, 0 rejected.** No ARCH contradiction is introduced. No README criterion, cap, enablement, permit, NO-SEND or `allow_short` surface is touched. No test is weakened: `test_pre_offline_studies_units_end_by_1045z` keeps its r5 inequality, and only the requested constant changes. 2 new tests. Cross-plan requests: 0 new, 1 amended (AUT-3: 4139 s at 09:35Z).

| # | Finding | Disposition | Where |
|---|---|---|---|
| L1 | [pm 1, mle 1] K8 off-by-one: `TimeoutStartSec` ≤ 4139 s from 09:35Z or ≤ 4799 s from 09:24Z, so that `start + 1 + TimeoutStartSec + TimeoutStopSec ≤ 10:45:00`; §5 and §6.4 row 9 must match | **ACCEPTED.** The bound is written as `TimeoutStartSec ≤ 10:45:00 − start − 1 − 60`. The request is 4139 s at 09:35Z, worded the same way in §3.9, §5 and §6.4 row 9 and in the header status. 4799 s at 09:24Z is recorded as accepted by the test but is not requested (see L2). r5's 4140/4800 were each 1 s over because they left out `AccuracySec` | Header, §3.9, §5, §6.4 |
| L2 | [pm 2] Use 09:35Z consistently for the AUT-3 rerun | **ACCEPTED.** The neighbouring-slots line now reads 09:35Z (r5 had ≈ 09:30), and every request names only the 09:35Z start | §3.9, §5, §6.4 |
| L3 | [mle 2] State that the K9 look-time counts are functions of champion data only; test that the look time is independent of the nominee's outcomes | **ACCEPTED.** Invariant: the look time depends only on champion data and the admissibility calendar. `look_counts(champion_rows, window)` takes no nominee input. Tests `test_look_time_independent_of_nominee_outcomes` (original, sign-flipped and redrawn nominee outcomes give the same look slot) and `test_look_counts_signature_takes_no_nominee_input` | §3.7, WP6, §7 |
| L4 | [mle 3] Re-score | **ACCEPTED.** 93 → 94 (Correctness 18 → 19); unmeasurables are still excluded | §10 |

---

## §R5 Disposition (review `reviews/AUT-4-r4-merged.md`; ARCH Rev 9.2 sha `1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42` + `reviews/ARCH-ERRATA-rev9_2.md`)

**10 items, 10 ACCEPTED, 0 rejected.** No ARCH contradiction introduced; no README criterion, cap, enablement, permit, NO-SEND or `allow_short` surface touched; no test weakened (r4's `test_offline_successor_lands_before_predecessor_expiry` assertion is kept and the constant fixed to meet it). New tests: 22. New cross-plan requests: 3 (AUT-5 ×2, AUT-3 ×1) plus one ARCH-0 owner review.

| # | Finding | Disposition | Where |
|---|---|---|---|
| K1 | [pm M1] Pin `n_min_c`, `alpha_total`, `stations`, per-predicate MDEs for (b), (c) in the §5 keys; `compute_nomination_columns` arithmetic only | **ACCEPTED.** Keys `alpha_total`, `stations`, `sigma_b_pinned`, `mde_a`, `mde_b`, `mde_c`, `n_min_c` (table k = 1…K_LIFETIME) added to the policy block; the function reads only named keys, raises on a missing one; `stations` checked against the root manifest by `feasibility_consistency`; WP0 (xiv) measures `sigma_b_pinned` and `n_min_c` | §3.3, §3.5, §3.8, §3.10 R-C/R-D, §4 WP0, §5 |
| K2 | [pm M2] Define `n_min_one_sided`, `c_min`, `deff` once in `src/breezy/persistence/autonomy/` (stdlib `NormalDist`); `eval_stats.py` imports; projection-equals-columns test | **ACCEPTED.** New `src/breezy/persistence/autonomy/sample_size.py` (also `n_min_eff`), ARCH-0 owner review as for `nomination.py` (I-2); identity test `test_sample_size_primitives_single_definition`; `test_projection_equals_engine_written_columns` | §3.2, §3.3, §3.8, WP2, WP7b |
| K3 | [pm M3] AUT-5 request: call inside `BEGIN IMMEDIATE` with named keys; contract test failing when columns are written without the call | **ACCEPTED.** Request written in §3.5 and §5; `tests/contract/test_nomination_columns_contract.py` (3 tests, spy-based); §6.4 row 9 | §3.5, §5, §6.4, WP5 |
| K4 | [mle 1] 15:25Z `eval_staleness` requires today's `slot_start` date for every producer; engine consumes newest per (family, kind) | **ACCEPTED.** Today's-slot rule over the policy key `eval_staleness_producers` (needed so the not-yet-enabled eval-offline does not FAIL ATTEST every day before prerequisite 7); "newest" ordering defined; engine request uses `acted=false`, never a new `reject_reason` (ARCH's set is closed) | §3.9, §5, WP8 |
| K5 | [mle 2] `EVAL_OFFLINE_TIMEOUT_START_S` = 6299 or loosen the assertion; recompute budget and worst end | **ACCEPTED, constant option** (the assertion is not loosened). Replay budget 3599 s; child timeouts 899/449 s; WP0 hard-fail 719/359 s; worst end 12:45:00; launch interval 11:00:00–12:46:00 | §3.3, §3.9, §3.12, WP0, §7 |
| K6 | [mle 3] NO_INPUT is OFFLINE_CHALLENGER on the champion; FS lane writes nothing without a nominee; cover in `eval_completeness` | **ACCEPTED.** Per-producer invariant stated; expected sets in `eval_completeness`; 4 tests | §3.1, §3.11, WP5/WP6/WP8 |
| K7 | [mle 4] Seed `SEED XOR int(sha256(subject_sha ‖ slot_date ‖ role)[:8])`; same-slot recompute bit-identical test | **ACCEPTED.** `seeding.derive_seed` with `‖` = 0x1F, hex `[:8]` base 16, closed role set; applied to the permutation, screening bootstrap, R-C bootstrap and (b) sign-flip; R-B MC keeps its design seed | §3.1, §3.2, §3.3, §3.5, §3.7, R-C, WP2/WP5 |
| K8 | [mle 5] Contract test that pre-11:00 studies units end by 10:45Z, or widen the flock wait | **ACCEPTED, contract-test option**; widening rejected (costs replay budget). AUT-3 r3's rerun (worst end ≈ 10:57Z) violates it: request to start 09:24Z with 4800 s or cap at 4140 s from 09:35Z | §3.9, §5, §6.4, WP6, §7 |
| K9 | [pm LOW] Single-look `fill_rate_underpowered` final by design, or wait for `N_IOC_MIN` inside the window; pin Decimal in query (3) | **ACCEPTED, wait option** (extended to `N_PROXY_MIN`, the same kind of ancillary count): the look waits for both counts; window end first → final INCONCLUSIVE. Decimal fields canonical `format(d.normalize(), "f")`; query (3) uses `tonumber`; the accounting check reads the string as `Decimal` | §3.1, §3.7, §7 |
| K10 | [mle 6] Re-score excluding unmeasurable values | **ACCEPTED.** Unmeasurables neither credited nor deducted; 93 | §10 |

---

## §R4 Rebase disposition (onto ARCH Rev 9.2, sha `1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42`, plus `reviews/ARCH-ERRATA-rev9_2.md`)

**36 changes, all CONFORMED to ARCH or a binding decision; 0 rejected.** Every r3 contradiction was resolved by conforming the plan to ARCH. No README criterion changed. No cap, enablement, permit, NO-SEND or `allow_short` surface is touched. The r3 dispositions (§R3, F1–F14) stand except where a row below supersedes them.

**Resolved contradictions deleted from the plan.**

| r3 item | Resolved by (ARCH Rev 9.2) | r4 effect |
|---|---|---|
| P4-7 (detector-level ATTEST set) | C5 ATTEST row: `attest_required_detectors`, intraday HEALTH and RECONCILIATION only | §3.9; prerequisite removed |
| P4-8 (k vs K_max) | C4 "Two limits, one index"; already superseded in r3 | §3.5 |
| P4-9 (engine input journal) | C5 `engine_input/v1` | §3.13 conformed |
| P4-10 (two ruling shas) | C4 `policy_ruling_sha256` + `family_prereg_sha256`; restrictive fallback | §3.1, §3.6; Rev 5 fallback deleted |
| P4-11 (`verdict_id`) | C4 identity minus `verdict_id`, `produced_at_ns` | §3.1; `recompute_key` deleted |
| P4-12 (assumptions enum) | C4 closed five-tag enum | §3.1; r3's two extra tags withdrawn |
| P4-13 ("evaluated MINT") | ALPHA amendment + C4: α per nomination; a mint never nominated spends no α | §3.5 |
| P4-14 (C5 lifetime counter) | C5 `lineage_counters.nominations` + PROMOTE `k_life` column | §3.5 |
| P4-15 (absolute calibration leg) | C4 (c) relative NI, `MIN_CALIBRATION_BUCKETS` | §3.7, §3.10 R-C |

**Change log.**

| # | Change | ARCH / decision basis | Where |
|---|---|---|---|
| R4-1 | Basis Rev 5 → FROZEN Rev 9.2 sha `1b288d0e…` + errata; E-3 Z-label reading stated | README Items; PLAN_TEMPLATE ARCH-basis rule | §0 |
| R4-2 | OFFLINE_CHALLENGER becomes no-α screening on forward days after training end; archive pre-screen and confirmatory "stage 2" deleted; archive OOF used only for WP0 measurements | C4 Evaluation protocol | §3.5, §3.1a |
| R4-3 | Nomination = engine's SHADOW→CHALLENGER PROMOTE; AUT-4 supplies pure `compute_nomination_columns`; r3's flock-serialised `assign_k_life` and `alpha_ledger.py` deleted | C4, C5 nomination columns (V4); §5 AUT-4 owns α accounting | §3.3, §3.5 |
| R4-4 | Infeasible nomination charges no α and no K_LIFETIME, uses the window slot; `nomination_feasible` | C4 window-cap rule | §3.5, §6.3 |
| R4-5 | K_LIFETIME ≤ 4 and ≤ 1 nomination per window; `K_LIFETIME_EFFECTIVE`=6 and the nominal tier deleted | C4; §4.5; ALPHA amendment | §3.5, R-D |
| R4-6 | `mints_in_window`, K_max per window and `NO_CHANGE(k_max_reached)` deleted; mint rate is AUT-3's 1/day | C3 `refit_run/v1`; ALPHA amendment | §3.5, §5, §6.1 |
| R4-7 | `k_exceeded` redefined: FS `k_life` ≠ row → `ERROR`; `ERROR(mints_in_window_exceeded)` deleted | C4 "No `k_exceeded` in operation" | §3.1 |
| R4-8 | `BOOTSTRAP_B_MAX` is the pins literal; proposed 2¹⁹ covers α_4/3; tail kept as a guard; C_min table k = 1..4 | §4.5; C4 draw cap | §3.2 |
| R4-9 | C4 fields `k_life`, `alpha_k`, `n_min_eff`, `n_cap` on FORWARD_SHADOW only, copied from the row; null elsewhere; `mints_in_window` field removed | C4 Measurement | §3.1a |
| R4-10 | FS subjects are nominees only; champion baseline moved to HEALTH `eval_replay_path`; drill child screened only | C4 field rule; C5 DRILL_ADMIT (no nomination) | §3.7, §3.11 |
| R4-11 | Nominee uses only days after its nomination date inside its window | C4 multiple testing | §3.5 |
| R4-12 | FS (c) is one one-sided paired relative test, ruling margin, `MIN_CALIBRATION_BUCKETS`, reason `calibration_buckets_below_min`; |MSD| leg withdrawn; WP0 measures the false-fail rate | C4 (c), §4.5 V16, P4-6 | §3.7, R-C, WP0 |
| R4-13 | Two ruling-sha fields; `prereg_ruling_sha256` renamed; `accepted_family_preregs` deleted | C4 Provenance, P4-10 | §3.1, §3.6 |
| R4-14 | Restrictive fallback: a LIVE FAIL without policy DEMOTEs via `DEFAULT_RESTRICTIVE_CLASS`; r3's "honest gap" withdrawn | C4 Engine acceptance | §3.6, headline |
| R4-15 | No-boundary outcome renamed `no_registered_boundary` | C4 LIVE_SEQUENTIAL | §3.1a, §3.6 |
| R4-16 | `verdict_id` excludes `produced_at_ns`; `recompute_key` deleted | C4 Storage, P4-11 | §3.1 |
| R4-17 | `assumptions` limited to five tags; `fixture_candidate` and `fill_selection_sensitive` become metrics, the latter gated by policy key `ACCEPT_FILL_SELECTION_SENSITIVE` | C4, P4-12 | §3.1, §3.7, R-E |
| R4-18 | Engine input journal path and fields conformed; fixture journal under its own state root | C5 `engine_input/v1` | §3.13 |
| R4-19 | ATTEST cites only intraday HEALTH/RECONCILIATION; `eval_staleness` is an intraday HEALTH verdict; P4-7 prerequisite removed | C5 ATTEST row, §4.5 W1 | §3.9 |
| R4-20 | C4.1 consumed by name, filed in Wave 0; frozen window is [2026-07-01, 2026-10-02) | C4.1; HOLDOUT decision | §3.4, §3.5, §6.4 |
| R4-21 | eval-offline `MemoryHigh=12G`/`MemoryMax=14G`; peak measured before enablement; enabled only after AUT-6 memory-sum PASS | §5.2 Memory (V14, U6) | §3.9, §3.12, WP6 |
| R4-22 | eval-live takes the studies flock, not its own lock; contention with the label run bounded | §5.2 Locks | §3.6, §3.9 |
| R4-23 | Child timeout denominator 4·(`MAX_NOMINATIONS_PER_FORWARD_WINDOW`+1) = 8 → 900/450 s | C4 ≤ 1 nomination per window | §3.12 |
| R4-24 | G36 statistics moved byte-identically into `src/breezy/analysis/stats/` as WP1 = AUT-4a (Wave 1) | G36, §5.1 | §3.3, WP1 |
| R4-25 | `promote_enabled` bound `eta_date ≤ KILL − forward_window_days` with drill lost days; `feasibility_consistency` updated | §4.2 Y12, V19 | §3.8 |
| R4-26 | MDE at α_K = α_total·2^−K_LIFETIME in the feasibility record | C4; §4.2 | §3.8 |
| R4-27 | `INCONCLUSIVE` + `metrics.day_status=NO_INPUT` when nothing to evaluate | C4 Invariants (U10) | §3.1 |
| R4-28 | C2 inputs restricted to `p_source=c1_decision`; `voided_pair` excluded; `quote_ref`-only rows excluded from slippage by name | C2, C1 (U8) | §3.1, §3.4 |
| R4-29 | §6.4 prerequisites rewritten: ARCH Rev 7 items removed; ARCH-0 Wave 0, AUT-5 journal/fixture pass, AUT-6 ATTEST and memory sum added; Rev 7 deadline line removed | Rev 9.2 has every item | §6.4 |
| R4-30 | Contradictions P4-7..P4-15 deleted; "None open" | Rev 9.2 | §10 |
| R4-31 | Programme rules: deploy test against `RuntimeMaxSec` on autonomy oneshots; launch-window disjointness including W, TimeoutStartSec and TimeoutStopSec | PLAN_TEMPLATE systemd rule; §5.2 | §3.9, WP8 |
| R4-32 | All code, test and store paths made repo-root-relative or absolute (`$STATE` defined) | PLAN_TEMPLATE paths rule | throughout |
| R4-33 | Headline, §6.3 table and consequences rewritten: `k_life` stays 0 while infeasible; screening ETA ≈ 7 days | C4 window-cap rule | headline, §6.3 |
| R4-34 | R-D and R-F redrafted (K_LIFETIME 4, 1 per window, screening thresholds, nominee selection, keys); detector→class map drafted | C4; §4.2; §8 | §3.10 |
| R4-35 | R-B tied to `family_prereg_sha256`; peer-loop date ≈ 11-10 per ARCH; filing target 10-24 kept | C4 LIVE_SEQUENTIAL (P4-2) | §3.10, §6.4 |
| R4-36 | Self-score re-derived (89) | PLAN_TEMPLATE §10 | §10 |

**Interpretations stated (not contradictions; for the peer loop).**
- **I-1.** ARCH C4 lists `k_life`, `alpha_k`, `n_min_eff`, `n_cap` "for `FORWARD_SHADOW`". A subject with no nomination row has no values for them, so r4 produces FORWARD_SHADOW only for nominees (R4-10). If the ARCH owner instead intends FORWARD_SHADOW on non-nominees with these fields null, only `eval_replay_path` would move back to the FORWARD_SHADOW kind; no other section changes.
- **I-2.** `compute_nomination_columns` lives in `src/breezy/persistence/autonomy/nomination.py` because the engine calls it and must not import `breezy.analysis` (G15). It is an AUT-4 addition to an ARCH-0 package, reviewed by the ARCH-0 owner, not a change to any contract.

---

## §R9 Disposition (review `reviews/AUT-4-r8-merged.md`; errata E-7a, E-7b, E-7c, E-8a, E-9 in `reviews/ARCH-ERRATA-rev9_2.md`; ARCH Rev 9.2 sha `1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42`)

**4 items: 4 ACCEPTED, 0 rejected.** BH2 is accepted with one measured refinement (row BH2, Arrow parity).

**Boundaries.**
- No ARCH contradiction is introduced.
- Two errata wording requests are filed: ER-1 is needed, ER-2 is optional.
- No README criterion, cap, enablement, permit, NO-SEND, `allow_short` or `promote_enabled` surface is touched. The permit and NO-SEND files are now sha-pinned.

**No regression of r7 or r8 closures.**
- AH1–AH5, LOW-1, LOW-2, E-7b, E-7c, the quarantine bind, the WP2 `lint-imports` gate and `--tmpfs /tmp` on every row stand as written in r8.
- r9 adds a size to `--tmpfs` and adds `lint-imports` to the WP1 gates.

**No test is weakened.**
- Every pinned and guard test file stays byte-unchanged.
- r8's planned `test_eval_offline_closure_has_no_adapter_module` was never written. It is replaced by an exact-set test, and the E-7b exec guard is strengthened (`order_enablement` absent; no mint call) and gains a negative control.
- r8's planned `test_moved_names_are_aliases_of_domain_objects` is dropped together with M1.

**New tests: 37**, all in §3.9a, §3.9b, §3.12 and WP6.

**Cross-plan requests.**
- New: 4. Three owner reviews (W1; W2 + W3; W4), and the table/wrapper owner (ER-1 plus the BM1 sequencing).
- Withdrawn: 1, r8's `ladder_ev` owner review.
- Contingent: F-1.

**New read-only evidence:** §0b.

| # | Finding | Disposition | Where |
|---|---|---|---|
| BH1 | [HIGH, MLE] The eval-offline closure cannot reach 0 adapter modules: `order_enablement.py:44-53` imports `write_transport`, `operator_controls` and `safety`; `current_rung_hold/{composition,continuous_strategy,strategy}` import it for `OrderSubmissionPermit`; §3.9a forbids editing it; `fees` imports `errors` and `parsing`. State it as certain; choose (a) the pure permit-type seam or (b) N-1 declared now; re-measure with M1–M3 simulated | **ACCEPTED: (b) chosen, measured.** The finding is stated as certain, with file:line (§3.9a, §0b finding 1). The closure was re-measured on scratch copies with the moves simulated (§0b). r8's M1–M3 leave 25 adapter modules, including 8 exec and 2 HTTP. **(a) is rejected on two grounds.** It is not a pure move: `issue` is the type's only constructor and reads `write_transport`, the caps and `LiveTradingPermit`, under B11 and L-22. And it is insufficient: scenario B still has 8 exec and 2 HTTP. **(b) is declared now.** The minimal cut set W1–W4 (lazy adapter `__init__`; lazy `current_rung_hold/__init__`; the bucketing helpers moved out of `composition`; one annotation import under `TYPE_CHECKING`) gives 11 non-exec adapter modules, 0 exec, 0 HTTP/WS and no `order_enablement`. Those 11 are the named exception, justified per module. M1, M2 and the `ladder_ev` `__init__` are withdrawn on evidence. The guard gains clauses and a negative control. Since (a) was not chosen, no permit edit exists; the permit and NO-SEND files are nevertheless sha-pinned and diff-checked | Headline, §0b, §2, §3.9a, §3.9b (1), WP1, WP6, §5, §6.4, §7, §8, §9, §10 |
| BH2 | [HIGH, PM + MLE] M3 live-path gates: exec-client sha pin reusing the SL-13 pattern plus no-diff; boot smoke per live entry, fresh process, identities, eager resolution; permit check after a windowed supervisor restart; lazy `__getattr__` tests (non-export, `dir()`, `import *`, submodule attributes, `pkg.sub` grep); `register_arrow` set equal before and after; golden replay; `sys.modules` and Nautilus config diff | **ACCEPTED, with one measured refinement.** Each requested gate is in §3.9b (1)–(8), with named tests, fixtures captured at the base sha, and gate commands. **Refinement:** the planning-time measurement found that strict `register_arrow` equality holds on 27 of 35 entries, including every live entry. 8 offline scripts lose registrations of types they never name, and re-registering in the `__init__`s was simulated and rejected. The gate is therefore strict equality on live entries, plus an exact, closed, never-referenced allowance for those offline pairs. Nautilus fails loudly on an unregistered type. The supervisor's closure was measured (33 adapter modules, through `exec_state_db_path.py:40`), which is why W1 needs a restart. The restart runbook uses `KillMode=process`, the window [01:00Z, 16:40Z), the `permit_watch_adopted_live_node` line (`trade_supervisor.py:2068`), and a new read-only `scripts/ops/permit_line_check.py` built on the supervisor-core markers, with a positive control | §0b, §2, §3.9b, WP1, §7, §8 |
| BM1 | [MEDIUM] (PM) One sentence rejecting branch (b) of the earlier fork or saying why it is not safer; (MLE) make the wrapper's `/tmp` ownership (E-7c) a sequenced build gate before AUT-4 rows go live | **ACCEPTED.** §3.9a gives one sentence per branch. E-7b (b) without W1–W4 is not safer, because its guard cannot pass and filing it would admit HTTP/WS and exec into a network-on sandbox, the narrowing E-7b rejects. The permit seam is not safer, because it edits the minting path and leaves exec. E-7c is a four-step sequenced gate: wrapper merged and its test green, deployed sha equal to the merged blob, rows filed, timers enabled. Order is evidenced by `git merge-base --is-ancestor`, enforced by a contract test, and listed as §6.4 row 11 | §3.9a, WP4, WP6, §5, §6.4, §7 |
| BL1 | [LOW] Pin a numeric memory cap for the `/tmp` tmpfs scratch; state the N-1 fallback explicitly | **ACCEPTED.** `--size`: 2 GiB on eval-offline and fixture, 128 MiB on eval-live (bwrap 0.11.1 verified to give `ENOSPC`). It is inside the restated §3.12 budget, overflow is fail-closed, and three tests cover it. ER-1 carries the per-row size into E-7c. F-1 is stated in full: its trigger, the revert, eval-live's independence, the daily `eval_completeness` FAIL, score 3 unreachable, the coordinator ruling, and what F-1 never does | §3.9a, §3.12, WP6, §6.4, §10 |

---

## §R10 Disposition (review `reviews/AUT-4-r9-merged.md`; coordinator rulings R-1, R-2 and R-3; ARCH Rev 9.2 sha `1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42` + `reviews/ARCH-ERRATA-rev9_2.md`)

**10 items: 10 ACCEPTED, 0 rejected.** One item is accepted with a measured addition: FH1 needs a fifth cut, W5. One ruling is accepted with a measured statement of its reach: R-1, see I-5.

**Boundaries.**
- No ARCH contradiction is introduced.
- ER-1 and ER-2 are restated with the ruled text.
- No README criterion, cap, enablement, permit-minting, NO-SEND, `allow_short` or `promote_enabled` surface is touched. The ten §3.9b pins are unchanged, and R-1 and W5 edit none of the pinned files.

**No regression of r6–r9.**
- These stand as written: r6's E-7/E-8/E-7a/E-9/E-10 items; r7's RC-1..RC-4 and MN-1; r8's AH1–AH5, LOW-1, LOW-2, the quarantine bind, the WP2 `lint-imports` gate and `--tmpfs /tmp`; r9's BH1, BH2, BM1, BL1 (E-7b (b), W1–W4, the §3.9b gates (1)–(8), the `--size` caps, the E-7c sequence and F-1).
- r10 narrows two r9 statements on measurement, and both corrections are struck through in place:
  - the exception goes from 11 modules to 8 (R-1);
  - W3's "imports all four back" and "no test patches the moved names" are corrected (FM2).
- r10 widens one planned r9 test: the Arrow-loss reference test (FL1).

**No test is weakened.**
- Every pinned and guard file stays byte-unchanged.
- `test_runtime_import_isolation.py` is only appended to, in WP6, and a test pins its 35 HEAD entries.
- `test_composition_reexports_identical_objects` is narrowed to the two names that `composition` still binds. It is a planned test that has not been written, and a new test asserts that the other two names are absent.

**New tests: 31.**

**Cross-plan requests.**
- New: 3. The R-1 owner review; ER-1 as ruled, to the table/wrapper owner (the default); and ER-1/ER-2 filing by the coordinator.
- Extended: 1. The `forecast_quantile_ladder` owner reviews W5 as well as W4.
- Withdrawn: 0.

**New read-only evidence:** §0c.

| # | Finding | Disposition | Where |
|---|---|---|---|
| R-1 | [ruling; both reviewers] Make `nbp_shadow_parity_pure.py:43`'s `PERMIT_TTL_NS` import function-local; re-measure; drop `safety`, `credentials` and `secure` from the named exception; the golden replay covers the edit; do not re-declare the constant; fix the "moved byte-identically" wording | **ACCEPTED, as ruled, and measured.** The import moves into `permit_window_for_day` (:151), and only that line changes. The "moved byte-identically" wording is struck. Re-measured: the replay's import-time closure is 8 adapter modules (`adapters`, `polymarket_us`, `fees`, `parsing`, `errors`, `redaction`, `symbology`, `tape_records`), 0 exec, 0 HTTP/WS, no `order_enablement`. The exception is now those 8. Three tests pin the edit: no module-level import, no re-declaration, and window values equal to HEAD's. Both goldens cover it. **Measured reach:** the replay calls the function before `engine.run()`, so the 3 modules still load at run time. They are declared separately, attributed by stack to the R-1 site, and stated as I-5 | Header, headline, §0c, §3.9a, §6.4, §7, §8, §10 |
| R-2 | [ruling] ER-1 conflict (PM ADOPT, MLE AMEND): the wrapper applies a default tmpfs cap to any row without a per-row `--size`; AUT-4 rows carry explicit values; fail-closed only on a malformed value; restate ER-1 | **ACCEPTED.** ER-1 is restated with the ruled text (§10). §3.9a BL1 is rewritten: explicit AUT-4 values; `DEFAULT_TMPFS_SIZE_BYTES`, owned by the wrapper owner, for other rows; fail-closed only on a malformed value. Two contract tests are added. The r9 sentence "a row without the value fails closed" is struck | §3.9a, WP6, §5, §7, §10 |
| R-3 | [ruling] ER-2 AMEND: waiver for the eval-offline row only; needs the WP1 measurement and the (b) guard tests green; never reaches `order_enablement` or `exec*`; does not waive (b)'s "needs" condition | **ACCEPTED.** ER-2 is restated with all four conditions, and the run-time closure tests are added to its green set. `test_er2_waiver_scoped_to_eval_offline_row` pins the scope. I-4 is closed by the ruled text | §3.9a, §7, §10 |
| FH1 | [HIGH, MLE] The closure guard sees import time only (`plan:655`). The `_LAZY` maps and function-local imports can load HTTP, exec or `write_transport` mid-run. (a) Re-snapshot after the golden replay and after a `replay_daily_runner` smoke run. (b) Add a `sys.meta_path` blocker for `exec*`, `factories`, `http`, `websocket`, `transport`, `write_transport` and `order_enablement`, in the eval-offline entry and in the test | **ACCEPTED; confirmed by measurement; one cut added.** §0c ran the golden replay on a copy with r9's W1–W4. The run added 17 adapter modules, among them 8 exec, `transport`, `write_transport` and `order_enablement`, via `strategy.py:308` → `forecast_quantile_ladder.composition` → `current_rung_hold.composition` → `order_enablement`. **W5** moves the pure `_d_plus_1_climate_days` (with `_VENUE`) into `forecast_quantile_ladder/d_plus_1.py`. After W5 the run adds only the 3 R-1 modules. (a) There are six run-time tests: both goldens; the R-1 attribution; the runner smoke, with every path under `tmp_path` and its 15 measured modules pinned (no exec, no `order_enablement`; the runner is not an AUT-4 row); never-imports-or-spawns-the-runner; and a negative control on the pre-W5 closure. (b) `import_blocker.py` is installed first in both entries and in each `fs_replay` child. It **fails closed on its record**, because §0c measured that the strategy's L-16 handler swallows the `ImportError` and the replay then silently returns nothing. Five blocker tests, including a positive control for the swallowed-import case | Headline, §0c, §2, §3.3, §3.9a, §3.9b (11), WP1, WP6, §6.4, §7, §8, §9 |
| FM1 | [PM] Revert path: the first post-restart boot is ~16:50Z, outside the window; allow an immediate tree-only `git revert` (the node reads source at spawn); only the restart waits; run the boot smoke against the real deployed tree before the restart | **ACCEPTED.** §3.9b (7) step 7 is rewritten. The revert is immediate, at any hour, and is proven equal to the base with `git diff --exit-code`. The gate is then run and its `EXIT=0` read before any push. The supervisor restart waits for the next window, and W1's identity preservation makes that safe. A new step 2a runs the boot smoke and Arrow parity from `/home/jon/breezy` under the no-egress gate before any restart | §3.9a F-1, §3.9b (2), (7), WP1, §7, §8 |
| FM2 | [PM] W3 structural test: assert the exact import delta forced by ruff F401; assert that `strategy.py:65` keeps the module-level name `bucket_station_instrument_ids`, which `test_d1_cache_union.py:300,330` patches; correct "no test patches moved names" | **ACCEPTED, measured on a real move.** Ruff F401 removes exactly 7 names from `composition.py` and lets only `InstrumentStationMismatchError` and `_bucket_station_instrument_ids` back. Re-importing the other two is F401 (measured). `test_composition_import_delta_is_exact` and `test_fq_strategy_keeps_module_level_bucket_name` are added. The patch target is `tests/strategy/forecast_quantile_ladder/test_d1_cache_union.py:299-302,329-332` (path corrected from `tests/unit/`), and it passes on the copy. The false r9 sentences are struck. W5 gets the same treatment | §0c, §3.9a, §3.9b (8) |
| FM3 | [PM] Whole-diff allowlist: `git diff --name-only <base> HEAD` ⊆ {W1–W4 files, new tests, fixtures, `permit_line_check.py`}, covering the unpinned `fees.py`, `parsing.py` and `exec/refusals|reports|no_side_keys.py` | **ACCEPTED.** `diff_allowlist.txt` is committed in the RED-capture commit. It covers W1–W5, R-1, the enumerated G36 move set, `permit_line_check.py`, new tests and fixtures. The `comm -23` gate must print nothing. `test_allowlist_excludes_protected_paths` forbids `fees.py`, `parsing.py`, `exec/**`, `src/breezy/runtime/**`, the ten pinned files, `deploy/**` and existing tests | §3.9b (10), WP1, §7, §8 |
| FM4 | [MLE] Cold-import order: a fresh-process first-import test for every module under both lazy packages and for `instrument_buckets` | **ACCEPTED.** The test is parametrised by `pkgutil.walk_packages` over both packages, `instrument_buckets` and `d_plus_1`, one fresh subprocess per module. Measured: 65 of 65 import cleanly | §0c, §3.9b (9), WP1, §7 |
| FM5 | [MLE] Golden-replay breadth: a golden over a clean real-tape slice through `backtest_harness`, covering catalog decode and the `BacktestEngine` fee path; SFO 09-01 | **ACCEPTED.** Section (6b) adds it. The SFO 2026-09-01 fixture is captured read-only from `.../quote_tape/polymarket_us/data/` (6 instruments, 1.5 MB measured). It is loaded through the script's own catalog loader and run through `build_backtest_engine` with `PolymarketUSFeeModel`. Three runs must match one hash, and a positive control picks a fee change that flips a key | §0c, §3.9b (6b), §3.9a, WP1, §7 |
| FL1 | [LOW] Add the new eval-offline and `fs_replay` entries to `STAGE0_ENTRY_MODULES` and assert that every `register_arrow` type referenced in their closure is registered; extend the Arrow-loss reference test to string literals and `data_cls`; a golden-catalog smoke of the 8 offline scripts | **ACCEPTED.** WP6 appends both entries, and `test_stage0_tuple_head_entries_unchanged` pins the HEAD 35. `test_closure_referenced_arrow_types_registered` checks after import and after the replay. The reference matcher now covers string literals, `data_cls=`, `DataType(…)` and `query(…)`, with a positive control. The 8-script smoke runs on a golden catalog holding one row of each lost type | §3.9b (4), WP6, §7 |

## §R11 Disposition (review `reviews/AUT-4-r10-merged.md`; ARCH Rev 9.2 sha `1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42` + `reviews/ARCH-ERRATA-rev9_2.md`)

**6 items: 6 ACCEPTED, 0 rejected. Rulings recorded: I-5 ACCEPTED under (a); ER-1 ADOPTED; ER-2 ADOPTED.**

**Boundaries.**
- No ARCH contradiction is introduced, and no r6–r10 closure is reopened. r10's FH1/W5, R-1, R-2 and R-3 text stands, except where a row below names a refinement.
- Hard invariants, restated: Nautilus Trader is unmodified; `allow_short` stays `False`; no safety, settlement or contract test is weakened or deleted; the operator caps (max daily budget, max per position) are untouched; live enablement and the NO-SEND firewall are untouched; the permit-minting path is unchanged (`issue_live_trading_permit` keeps zero callers); `promote_enabled` stays `false`. The ten §3.9b pins are unchanged, and r11 adds no edit to any live-path file: every r11 change is in AUT-4's own `import_blocker`, its producers, or new tests.

| # | Item | Disposition | Where |
|---|---|---|---|
| F1 | [MED, MLE] `SystemExit` in an `atexit` handler does not change the exit code. Run `assert_clean_or_exit()` before output is written and gate the write on an empty record; use `os._exit(EXIT_INTEGRITY)` for a hard exit; the swallowed-import test asserts a non-zero exit and no output file | **ACCEPTED, measured.** On Python 3.13.13, `SystemExit(3)` in `atexit` gives exit code 0 and `os._exit(3)` gives 3. One commit helper runs `assert_clean_or_exit()` immediately before every `os.replace`; the check is also the last step before the verdict commit. The exit is `os._exit(EXIT_INTEGRITY)` after the CRITICAL and a flush. The `atexit` handler is a backstop that also uses `os._exit`. The positive control asserts `returncode == EXIT_INTEGRITY` (non-zero), no output file and no temporary file. Added: `test_atexit_backstop_sets_exit_code`, `test_systemexit_in_atexit_does_not_set_exit_code`, `test_blocker_never_calls_sys_exit` | §3.9a (import blocker) |
| F2 | [LOW, MLE] State that `importlib.reload` is out of scope; the pre-install `sys.modules` check covers already-imported modules | **ACCEPTED.** Stated, with the reasoning, and backed by `test_eval_offline_closure_has_no_reload_call` | §3.9a (import blocker, "Where it runs") |
| F3 | [LOW, MLE] I-5 attribution: assert the loader frame lies within module `nbp_shadow_parity_pure`, not an exact frame depth | **ACCEPTED.** The loader frame is the innermost non-`importlib` frame; the predicate is module name (or the G36 copy's) plus `co_name == "permit_window_for_day"`, never a depth. A negative control with a scratch loader is added | §3.9a (R-1 deferral; run-time closure tests) |
| F4 | [LOW, PM] Test that no `LIVE_ENTRIES` module installs or references the `sys.meta_path` blocker | **ACCEPTED.** `test_no_live_entry_installs_or_references_blocker`: fresh process per `LIVE_ENTRIES` module, no `import_blocker` in `sys.modules`, no blocker finder on `sys.meta_path`, and an AST scan finding no import of it and no `sys.meta_path` reference. The `eval_offline` entry is the positive control | §3.9a (import blocker tests) |
| F5 | [LOW, PM] Structural test that `strategy._d1_candidate_ids` resolves to the same function object as `composition._d_plus_1_climate_days` | **ACCEPTED, verified against code.** At HEAD the strategy imports `_d_plus_1_climate_days` function-locally (`strategy.py:308`) and composition calls it at `:175` and `:224`. `test_d1_candidate_ids_resolves_to_composition_object` reads the import from the AST and asserts `is` identity | §3.9b (8), W5 |
| F6 | [LOW, MLE] Make sure the malformed `--size` fail-closed test (ER-1) is named | **ACCEPTED.** ER-1 in §10 now names `tests/contract/test_autonomy_units.py::test_wrapper_malformed_tmpfs_size_fails_closed` and the default-size test. §3.9a, WP and §7 already name it | §10 (ER-1) |
| I-5 | Ruling: option (a) | **RECORDED.** `E7B_EVAL_OFFLINE_DEFERRED_PERMIT_TTL` is an exact named run-time set, admitted only with stack attribution (F3). I-5 is closed | §10 |
| ER-1 | Ruling: ADOPT | **RECORDED.** The ruled text is unchanged | §10 |
| ER-2 | Ruling: ADOPT | **RECORDED.** The ruled text is unchanged | §10 |
