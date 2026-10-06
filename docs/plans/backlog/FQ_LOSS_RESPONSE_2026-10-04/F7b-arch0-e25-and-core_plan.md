# Implementation plan: ARCH-0-E25 (Slice 1) and F7b-core (Slice 2)

## Overview
Slice 1 extends the `verdict/v1` exact-set reader to accept E-25's three identity-body keys. It also adds the per-lineage infeasible-nomination ceiling and the stdlib+Decimal e-LOND module, and classifies that module in import contracts (b) and (c). Slice 2 adds the pure e-process and KILL CS cores, the sealed `evidence_row` loader, and `FqEvaluator`, which replaces the FQ entry in `OFFLINE_PLUGINS`. In Slice 2 every path that has no registered source, or that needs `market_baseline`, refuses with a named reason. Slice 1 merges first; Slice 2 rebases onto it for `elond`.

Everything was checked against the code at HEAD `da406562` on `feat/data-capture-and-risk`. Line numbers are verified.

---

## 0. Where E-25 / r3 text and the code disagree (for peer review)

| # | Spec text | Code / artefact | Proposed resolution |
|---|---|---|---|
| D1 | r3 §R12-2 :417 and §R12-3 :471: "replaces the `"forecast_quantile_ladder": RefusingPlugin()` entry at `offline_plugins.py:18`" | `offline_plugins.py:80` is `FqOfflinePlugin()` (F4 FQ-R41). Line 18 is a blank import line. | Replace `:80`, per F4-open-items:39-41. |
| D2 | E-25 rule 1: "three **nullable** additions"; `test_kind` "never null on FORWARD_SHADOW" | Every existing FS fixture builds a verdict without `test_kind`, so each becomes a refused construction: `test_autonomy_verdict.py:77-92`, `test_verdict_schema.py:52-71` (loop), `:77`, `:95`, `:106`, `test_registry_fold_validate.py:665`, `test_registry_replay.py:109`, `:433` | Follow r12 §R12-4: fixture SCOPE adds `test_kind=fixed_n` to FS fixtures. No assertion is edited. |
| D3 | E-25 rule 3: ties ordered by "(station, rung id)" | MC `_take_key` is `(station, rung_id, side)` (`fq_mc_eprocess.py:86-96`) | Production sorts by `(decision_ts_ns, station, rung_id, side)`. Side is G-measurable and is needed for mixed-side takes at the same instant. Otherwise the stable sort falls back to arrival order, which E-25 forbids. Record this as a clarification of E-25. |
| D4 | E-25 rule 4 policy key is `alpha_schedule` | The design JSON key is `gamma_schedule` (`F5_prereg_v2_design.json:4`) | Same value, `elond_heavy_tailed_v1`. `elond` uses the E-25 name. Leave the key mapping to the AUT-5 r8 policy loader and note it there. |
| D5 | E-25 Consumption (ARCH-0) names only `verdict.py`, `pins`, `elond` | `analysis/autonomy/metric_registry.py:41-67` (`NULL_COLUMNS_BY_KIND`) mirrors the verdict kind rules, and `test_verdict_schema.py` asserts that the two agree | Slice 1 also widens `NULL_COLUMNS_BY_KIND`. This is the only analysis-layer file Slice 1 touches. |
| D6 | §R12-1 WP1s moves five modules, including `market_baseline` and `drift_freshness` | `analysis/stats/` holds only `group_sequential_boundaries`, `scoring_core` and `sequential_looks`. No `scripts/analysis/market_baseline.py` exists anywhere. | Per ruling R3, this is a deferred item (§3). |
| D7 | E-25 PASS/KILL: "n ≥ `earliest_look_n`" | The MC `n_cum` is the cumulative **full** take count `n_d`, including takes past `m_cap` (`fq_mc_eprocess.py:119-126`; `fq_mc_type1.py:54`). The MC gates KILL on the same look (`:213`, `:221`). | Production n = Σ N_d (all takes, voids included). The cross-check test pins this. |
| D8 | E-25 PASS needs "the calibration guard sufficient and not failing" | The F5 design JSON pins no guard thresholds: no Spiegelhalter-Z bound, no minimum sample, no slope band | The guard returns `INSUFFICIENT(guard_thresholds_unpinned)`, so PASS is unreachable. This is fail-closed. Raise it as an F5 pin request. |
| D9 | E-25: "hedged CS … UB < 0" | The MC fixes the grid at `KILL_GRID_POINTS=5` over [0, X_max], uses a per-m λ cap of `min(0.5, 0.5/max(X_max−m, 0.5))`, θ=½ and the bar `log(2/α_kill)` (`fq_mc_eprocess.py:38`, `:153-169`, `:201`, `:221`). None of these is in E-25 or the JSON. | Production copies these exactly as module constants, and the cross-check enforces them. A stats peer must confirm that UB<0 on the grid ⇔ UB<0 (quasi-convexity). |
| D10 | `eta_ns` "(int, `e_process` only)" | LIVE_SEQUENTIAL has no nomination index k | Ambiguous. Default: allowed (nullable) iff `test_kind == e_process`, on any kind. The peer review should decide whether to restrict it to FS. |
| D11 | `window_end` is "FORWARD_SHADOW only"; nullability on FS is unspecified | — | Default: nullable on FS, refused on every other kind. The stricter alternative is non-null on FS. |
| D12 | `load_evidence_rows(store_kind)` "takes no path argument" | Every store reader needs a data root (`AutonomyPaths`/`ShadowPaths`) | Signature: `load_evidence_rows(store_kind, *, root: AutonomyPaths \| ShadowPaths)`. The root is a typed object, never a `Path`. The test asserts that no parameter is annotated `Path`/`str` and none is named `*path*`. |
| D13 | `test_elond_schedule_refused_for_fixed_n_lineage` is listed in `test_elond.py` (§R12-3 :476), but rule 4 says the **policy loader** refuses | No policy loader exists (grep for `alpha_schedule`/`alpha_spending` in `src/` returns nothing) | `elond.require_schedule_pairing(schedule, test_kind)` as a pure function. The AUT-5 r8 loader will call it later. |
| D14 | Ruling R3 says to move `test_policy_loader_refuses_fq_lineage_fixed_n` to "AUT-4 row 10" | E-25 Consumption gives policy keys and WP3 tests to **AUT-5 r8** | Move it to AUT-5 r8 WP3, and flag the change in R3's wording. |

---

## Slice 1: ARCH-0-E25

### Acceptance criteria
- [ ] `Verdict.from_wire` (`verdict.py:340`) requires exactly `_KEYS` + {`test_kind`, `eta_ns`, `window_end`}. A wire object missing any one of them is refused MISSING_KEY. The fail-closed reading of E-25 (:671) is lifted only by this change.
- [ ] All three keys are in `_body()` (`:295-323`), so they are in the identity hash. `_BODY_EXCLUDED` (`:185`) is unchanged.
- [ ] Kind rules are enforced at construction (D2, D10, D11):
  - FS: `test_kind` is non-null.
  - LIVE_SEQUENTIAL: `test_kind` ∈ {null, `e_process`}.
  - Every other kind: `test_kind` is null.
  - `eta_ns` is non-null only when `test_kind == e_process`.
  - `window_end` is non-null only on FS.
  - `test_kind == e_process` ⇒ `n_min_eff is None` (E-25 rule 2).
- [ ] `pins.MAX_INFEASIBLE_NOMINATIONS_PER_LINEAGE_LIFETIME = 4` exists and is a pinned ceiling.
- [ ] `persistence/autonomy/elond.py` provides `gamma`, `alpha_k`, `require_schedule_pairing` and `promotions_before`. It imports only the stdlib plus `persistence.autonomy.pins`, and its values match the F5 MC on duplicated vectors.
- [ ] `elond` is listed in contracts (b) and (c). `test_autonomy_contracts.py` passes unedited. `lint-imports` reports "N kept, 0 broken".
- [ ] The two golden ids are re-derived from the literal spec body. `EXPECTED_KEYS` is widened by exactly three. No assertion is loosened.

### File-by-file
1. **`src/breezy/persistence/autonomy/verdict.py`**
   - Add `class TestKind(StrEnum)` {`FIXED_N="fixed_n"`, `E_PROCESS="e_process"`} after `VerdictOutcome` (`:110-115`), and add it to `__all__` (`:67-81`).
   - `_KEYS` (`:178-184`): append `"test_kind", "eta_ns", "window_end"`.
   - Add `_WINDOW_END_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z", re.ASCII)` beside `:90-94`, with a `date.fromisoformat` round-trip check.
   - `_INT_COLUMNS` (`:187`): add `"eta_ns"`, so `check_int` runs with minimum 0.
   - Keep `_FORWARD_SHADOW_ONLY` (`:189`) byte-unchanged. Add `_E_PROCESS_ONLY: Final = ("eta_ns",)` and `_FORWARD_SHADOW_ONLY_ANY_TEST: Final = ("window_end",)` beside it.
   - Dataclass fields (`:208-232`): add `test_kind: TestKind | None = None`, `eta_ns: int | None = None` and `window_end: str | None = None`.
   - `__post_init__` (`:234-254`): type-check `test_kind`.
   - Add `_check_test_kind_rules()`, called from `_check_kind_rules` (`:264-275`), with the rules listed in the acceptance criteria.
   - `_body()` (`:296-323`): add `"test_kind": None if … else self.test_kind.value`, `"eta_ns"` and `"window_end"`.
   - `from_wire` (`:339-381`):
     - `test_kind`: null → None, otherwise `TestKind(require_enum(...))`.
     - `eta_ns=optional_int(obj, "eta_ns")`.
     - `window_end=optional_str(obj, "window_end")`.
   - The `require_exact_keys(obj, required=_KEYS)` call stays as it is: no `optional=` (ruling R1).
2. **`src/breezy/analysis/autonomy/metric_registry.py:58-67`**: widen `NULL_COLUMNS_BY_KIND` (D5).
   - OFFLINE_CHALLENGER: add {`test_kind`, `eta_ns`, `window_end`}.
   - LIVE_SEQUENTIAL: add {`window_end`}.
   - HEALTH (`_HEALTH_NULL` `:42-54`): add all three.
   - FORWARD_SHADOW: unchanged.
   - `FORWARD_SHADOW_ONLY_COLUMNS` (`:41`): unchanged.
3. **`src/breezy/persistence/autonomy/pins.py`**: after `:39`, add `MAX_INFEASIBLE_NOMINATIONS_PER_LINEAGE_LIFETIME: Final = 4  # E-25 rule 6 <= 4`.
4. **NEW `src/breezy/persistence/autonomy/elond.py`** (stdlib + `decimal` + `pins` only)
   - `SCHEDULES = frozenset({"halving_v1", "elond_heavy_tailed_v1"})`.
   - Use a module-local `Context(prec=34)`, never the ambient context.
   - `gamma(t: int, T: int = pins.MAX_NOMINATIONS_PER_LINEAGE_LIFETIME) -> Decimal`: g(t) = 1/(t·ln²(t+1)), normalised over 1..T. Refuse bool, t∉[1,T], and T > pins ceiling.
   - `alpha_k(k, R, schedule, alpha_total) -> Decimal`:
     - `halving_v1` = α_total·2^−k.
     - elond = α_total·γ_k·(R+1).
     - Quantize to 1e-18 with **ROUND_FLOOR**, so Σα_k ≤ α_total holds exactly at R=0 and `decimal_str` (`canonical.py:25-37`) accepts the value.
     - R must be an int ≥ 0 (bool refused). `alpha_total` must be a Decimal in (0, 1).
   - `require_schedule_pairing(schedule, test_kind) -> None`: raise on `elond_heavy_tailed_v1`+`fixed_n` and on `halving_v1`+`e_process` (D13).
   - `promotions_before(promotions: Sequence[int], ts_ns: int) -> int`: count of `instant < ts_ns`. R is fed from fold `promotions` (`fold_tallies.py:87`, charged only on `Kind.PROMOTE`, `fold.py:397-398`).
   - Reference values for the reviewer (the implementer re-derives them to full precision; these are not the source): γ ≈ (0.75259, 0.14979, 0.06272, 0.03490); α_k at R=0 ≈ (0.018815, 0.003745, 0.001568, 0.000872).
5. **`pyproject.toml`**: append `"breezy.persistence.autonomy.elond"` to contract (b) `source_modules` (`:241-285`) and contract (c) (`:295-332`).
6. **Tests: SCOPE edits (fixtures and pins only)**
   - `tests/unit/test_autonomy_verdict.py`:
     - `EXPECTED_KEYS` (`:46-54`): add exactly three keys.
     - `forward_shadow()` fixture (`:77-92`): add `"test_kind": TestKind.FIXED_N`.
     - Re-pin the goldens at `:272` and `:427`. Derive each as the sha256 of the hand-written literal body, with sorted keys, compact separators and the three new keys as `null`. Do this in a scratchpad with `hashlib`/`json` only, never through `Verdict`. Record the derivation command in the test comment.
   - `tests/unit/autonomy/test_verdict_schema.py`: `_verdict()` (`:37-40`) supplies `test_kind=FIXED_N` when the kind is FS.
   - `tests/unit/test_registry_fold_validate.py:665`, `tests/unit/test_registry_replay.py:109` and `:433`: FS fixtures gain `test_kind=fixed_n`.
   - Verify-first: list every `Verdict(` construction with an FS kind through codegraph callers of `Verdict` (`projectPath=/home/jon/breezy`), including `test_registry_replay_roles.py:62` parametrisation.
   - `tests/unit/test_autonomy_pins.py` `DAMPING` (`:179-190`): add `"MAX_INFEASIBLE_NOMINATIONS_PER_LINEAGE_LIFETIME": ("<=", 4)`.

### RED-first tests (ADD)
- **`tests/unit/test_autonomy_verdict.py`**
  - `test_c4_e_process_n_min_eff_null_with_eta_ns_window_end`
  - `test_test_kind_closed_enum_and_kind_rules`
  - `test_eta_ns_only_when_test_kind_e_process`
  - `test_window_end_forward_shadow_only_and_iso_date`
  - `test_live_sequential_test_kind_null_or_e_process_never_fixed_n`
  - `test_each_new_key_moves_verdict_id` (identity body)
  - `test_exact_set_reader_refuses_wire_without_new_keys` (MISSING_KEY is also covered automatically, because `test_from_wire_refuses_a_missing_key` is parametrised over the widened `EXPECTED_KEYS`)
- **`tests/unit/autonomy/test_verdict_schema.py`**
  - `test_verdict_e_process_fields_null_on_other_kinds`: the registry and `Verdict` agree.
- **NEW `tests/unit/autonomy/test_elond.py`**
  - `test_elond_alpha_matches_pinned_gamma_schedule` (FQ-R26): T=4 from the design JSON, compared against pins.
  - `test_gamma_heavy_tailed_normalised`: Σγ = 1 within 1e-30, and γ is decreasing.
  - `test_elond_sum_alpha_le_alpha_total_at_zero_discoveries`: exact Decimal comparison.
  - `test_elond_matches_f5_mc_reference_vectors` (cross-check):
    - Literal float vectors for `gamma_schedule(4)` and `alpha_k(k, promotions=R)` for k=1..4 and R∈{0,1,3}, copied from one scratch run of `scripts/analysis/fq_mc_eprocess.py:61-70`. The comment records the script's git blob sha.
    - Production agrees within a relative 1e-12.
    - The test never imports `scripts/`.
  - `test_halving_v1_matches_arch_geometric`: α_total·2^−k, consistent with `tests/unit/autonomy/test_permutation.py:49-53`.
  - `test_elond_refuses_out_of_range_and_bool_inputs`
  - `test_elond_schedule_refused_for_fixed_n_lineage` (pure pairing, D13)
  - `test_elond_r_counts_only_effective_champion_promotes`:
    - `promotions_before` boundaries: strictly before `ts_ns`.
    - One fold-driven case: PROMOTE counts; DRILL_PROMOTE and ROLLBACK do not.
    - Uses the existing registry world fixture (`tests/unit/registry_resolver_world.py`). Verify-first: the helper exists.
  - `test_elond_single_definition_in_persistence`: an AST scan of `src/` finds no other `def gamma`/`def alpha_k`. The `is`-identity half is added only if a later slice re-exports.
  - `test_elond_imports_stdlib_decimal_and_pins_only`: AST.
- **`tests/unit/test_autonomy_pins.py`**: covered by the `DAMPING` row (SCOPE). Also ADD `test_max_infeasible_nominations_is_int_ceiling_4`.

### Risks
- **Fixture churn (D2) [MEDIUM].** The verify-first enumeration is blocking. Any FS fixture whose edit would need an *assertion* change → STOP for a ruling.
- **Decimal ln determinism [LOW].** Use a local context and floor-quantize. The cross-check catches drift.
- **Hidden verdict consumers [LOW].** `replay.py:130` and `:264`, and `validate.py:439`, read only `kind`/`outcome`; they are unaffected. Verify with `codegraph_explore Verdict.from_wire` callers.
- **Stored verdicts [nil].** The coordinator verified that none exist. Verify-first #2 from F1 r3:512 stays recorded.

### Out of scope (Slice 1)
`nomination.py`, the policy loader and its keys (`alpha_schedule`, `max_infeasible_nominations`, `n_e_power`, …), `NOMINATION_FIELDS` (`registry_shape.py:41`, `:73-75`, unchanged per E-25 rule 7), the Σα≤α_total scoping (verify-first #3 belongs with nomination), and `eta_ns ≤ window_end` `feasibility_consistency` (AUT-4 §3.8).

### Focused gate (Slice 1)
- Run from the tree with `PYTHONPATH=<tree>/src` and the repo interpreter.
- Tests:
  - `tests/unit/test_autonomy_verdict.py`
  - `tests/unit/autonomy/test_verdict_schema.py`
  - `tests/unit/autonomy/test_verdict_identity.py`
  - `tests/unit/autonomy/test_elond.py`
  - `tests/unit/test_autonomy_pins.py`
  - `tests/unit/test_autonomy_contracts.py`
  - `tests/unit/test_registry_fold_validate.py`
  - `tests/unit/test_registry_replay.py`
  - `tests/unit/test_registry_replay_roles.py`
  - `tests/unit/autonomy/test_permutation.py`
  - Firewall guards: `tests/unit/test_execution_egress_firewall_guard.py`, `tests/contract/test_us_source_ingest_egress_guard.py`, `tests/unit/test_autonomy_envelope.py`
- `lint-imports`, run from inside the tree, must report "N kept, 0 broken".
- `scripts/ci/regen_closure_manifest.py --check`
- Then the full gate via `scripts/ci/run_tests_no_egress.sh`. Read EXIT before any push.

---

## Slice 2: F7b-core (rebased on Slice 1)

### Acceptance criteria
- [ ] `eprocess.py`, `confidence_sequence.py` and `evidence_row.py` exist under `src/breezy/analysis/autonomy/`, along with the `evaluators/` package and `evaluators/forecast_quantile_ladder.py`. None imports `scripts/`.
- [ ] On shared duplicated fixtures, the production Y_d/Z_d, λ_d/μ_d, e_a, e_b and KILL first-n agree with `fq_mc_eprocess.py` within 1e-12.
- [ ] `OFFLINE_PLUGINS["forecast_quantile_ladder"]` is `type(...) is FqEvaluator`, and the following hold:
  - `label()` routes to `ForecastQuantileLadderScorer` with `has_scorer=True`.
  - `refusing` stays True and `is_complete` stays False. The plug-in stays a refusing plug-in: F4-open-items:41 and r3 §R12-3 :468-471 give no completeness, and mint/compose must still refuse.
  - `forward_shadow` is the only member added. `offline`, `live`, `decision_record`, `order_tags`, `refit` and `detectors` still raise `PluginRefused`.
- [ ] `FqEvaluator.forward_shadow` refuses with a named `PluginRefused` in each of these cases:
  - `evidence_not_loaded`: `tape` is not `type(...) is LoadedEvidence`.
  - `store_kind_not_accepted`: anything other than `shadow`.
  - `no_registered_forward_shadow_source`: E-25 rule 6b; the registry is an empty `Final` frozenset.
  - Because the registry is empty, it never yields a verdict input in production. `test_every_offline_plugin_is_incomplete_and_refuses_everything_but_label` (`test_autonomy_plugins.py:216-225`) stays **byte-unchanged**: `forward_shadow(None, None, None)` raises.
- [ ] Every path that needs `market_baseline` (BSS on all decisions) refuses as `UNAVAILABLE(market_baseline_absent)`.
- [ ] A backtest-only input can never produce PASS.

### File-by-file
1. **NEW `analysis/autonomy/eprocess.py`** (pure, float)
   - `EProcessDesign` (frozen dataclass): `m_cap` ∈ {2, 3}; `x_max` > 0; `lambda_max` and `mu_max` ∈ (0, 0.5]; `earliest_look_n`; `betting_rule_e_a`/`_e_b` == the literal `"agrapa_v1:prior_pseudo_days=1,prior_second_moment=0.25"`, any other value refused.
     - Values arrive as parameters (the future policy block). Production never reads the docs JSON. `test_design_fixture_matches_f5_design_json` reads the JSON in test code only.
   - `TakeInput`: `decision_ts_ns`, `station`, `rung_id`, `side`, `h: int | None` (None = void), `be > 0`, `ask_prob`, `p_model`.
   - `take_x(h, be, x_max)` = min(h/BE−1, X_max). `order_takes` uses D3's key.
   - `daily_statistic(takes, design) -> DayStat(y, z, n_takes, uncounted)`:
     - The denominator is `design.m_cap` and is never derived from listings or the day's data (FQ-R39).
     - Voids enter as 0 in their slot.
     - Takes past the cap go into `uncounted`.
   - `agrapa_fraction(sum, sum2, n_prev, cap)`, as in `fq_mc_eprocess.py:99-109`.
   - `run_eprocess(days, design) -> tuple[DayState, ...]`:
     - Each `DayState` carries `lambda_d`, `mu_d` (computed **before** the day's statistic is added), `e_a`, `e_b`, `n_cum` (D7) and `eprocess_uncounted_takes`.
     - The factor floor ≥ 0.5 is asserted.
2. **NEW `analysis/autonomy/confidence_sequence.py`**
   - `KILL_GRID_POINTS = 5`, the per-m λ cap and the bar `log(2/α_kill)`, all exactly as `fq_mc_eprocess.py:153-169`, `:201`, `:221` (D9).
   - `kill_first_n(ys, n_cum, *, x_max, alpha_kill, earliest_look_n)` works on **clipped, haircut Y_d**.
   - `alpha_kill` is a separate parameter. No return field adds into `alpha_spent`.
   - Diagnostic BSS-on-takes:
     - Point BSS = 1 − Σ(p−y)²/Σ(a−y)².
     - A day-clustered interval through `analysis/stats/scoring_core.py` `bootstrap_cluster_draws` with `CLUSTER_DATE`. Verify-first: its `Trial` type fits. If it does not, ship the point value only and record the deferral.
     - Diagnostic only; never an outcome input.
3. **NEW `analysis/autonomy/evidence_row.py`**: per §R12-3 :436-457.
   - `EvidenceRow` and `LoadedEvidence`: frozen, `@final`, `__init_subclass__` raises, a module-private token `InitVar`, and every copy/pickle dunder raises.
   - `StoreKind` is a closed mapping {`c2_label_store`→`live`, `node_c1_shadow_takes`→`shadow`, `harness`/`fs_replay`→`backtest`}.
   - `load_evidence_rows(store_kind, *, root)` (D12) enforces `ref_ts < take_ts` at load.
   - The module-level `_READERS: MappingProxyType` maps each store kind to a reader. In Slice 2 every reader raises `EvidenceUnavailable(<named reason>)`, because none of their backing paths has an owner WP merged. Tests monkeypatch `_READERS` to feed raw dicts through the real validate-and-seal path.
4. **NEW `analysis/autonomy/evaluators/__init__.py`**: docstring only.
5. **NEW `analysis/autonomy/evaluators/forecast_quantile_ladder.py`**
   - `FqEvaluator(RefusingPlugin)`:
     - `has_scorer: ClassVar[bool] = True`.
     - `label`, moved verbatim from `offline_plugins.py:43-51`.
     - `forward_shadow`, which runs the guard chain above and then calls the pure `evaluate_e_process(...)`.
     - No other members: helpers are module-level, so the override policing stays tight.
   - Pure `evaluate_e_process(loaded, *, design, alpha_k, window_end, last_settled_day) -> FqShadowEvaluation`:
     - Every row is checked `type(r) is EvidenceRow`.
     - PASS = min(e_a, e_b) ≥ 1/α_k at n ≥ `earliest_look_n` **and** guard OK. Under D8 the guard is never OK, so this resolves to UNDERPOWERED.
     - FAIL = KILL.
     - `INCONCLUSIVE(window_end_no_crossing)` once `last_settled_day ≥ window_end`.
     - Backtest-tagged input caps the outcome at UNDERPOWERED (rule 8).
   - Metrics:
     - `eprocess_uncounted_takes`
     - reliability slope via `brier_decomposition.murphy_decomposition` (`:177`) and `bin_by_edges` (`:106`)
     - Spiegelhalter Z, reported only
     - net P&L per day
     - `bss_all_decisions = "UNAVAILABLE(market_baseline_absent)"`
     - `pit_per_rung = "UNAVAILABLE(pit_spec_absent)"` (open item: r3 never defines per-rung-position PIT)
6. **`analysis/autonomy/offline_plugins.py`**
   - Import `FqEvaluator`. Replace `:80` with `"forecast_quantile_ladder": FqEvaluator(),`.
   - Delete `FqOfflinePlugin` (`:38-51`); it is an orphan this change creates. Update `__all__` (`:24-29`) and the module docstring (`:1-14`).
   - Move `_batch` (`:32-35`) to `analysis/labeling/scoring_batch.py` as `require_scoring_batch`. Both `FqEvaluator` and `_LegacyCrhOfflinePlugin` use it, which avoids a circular import.
   - Alternative for the peer review: `FqEvaluator(FqOfflinePlugin)` would force an `offline_plugins` ↔ `evaluators` import cycle, so it is rejected.
7. **Deliberate test changes (SCOPE, documented in the commit body)**
   - `tests/unit/test_autonomy_plugins.py`:
     - `:18`, `:152-157`: `EXPECTED_OFFLINE_TYPES["forecast_quantile_ladder"] = FqEvaluator`.
     - `:228-242`: replace the flat `ALLOWED_SUBCLASS_NAMES` check with `ALLOWED_OWN_NAMES_BY_CLASS = {FqEvaluator: {"label", "has_scorer", "forward_shadow"}}`. Every other class defaults to `{"label", "has_scorer"}`.
     - `_override_violations(klass)` subtracts only that class's allowance from the policed set.
     - ADD a planted case: an `FqEvaluator` lookalike overriding `live` or `offline`, or adding a helper, is caught.
     - `:216-225` stays byte-unchanged.
   - `tests/unit/test_aut2_offline_plugins.py:15`, `:58`: `FqOfflinePlugin` → `FqEvaluator`. Assertion form unchanged.

### RED-first tests (ADD)
- **`tests/unit/autonomy/test_eprocess.py`**
  - `test_eprocess_daily_denominator_fixed_before_first_decision`
  - `test_eprocess_m_d_is_pinned_m_cap_independent_of_listing_count`
  - `test_eprocess_uncounted_takes_disclosed_never_entered`
  - `test_eprocess_upside_clipped_at_x_max_downside_never_clipped`
  - `test_eprocess_same_instant_ties_ordered_by_station_then_rung_id` (side as the last key, D3)
  - `test_eprocess_void_take_enters_as_zero_never_dropped`
  - `test_lambda_uses_settled_days_only_denominator_fixed_at_decision`
  - `test_capital_nonnegative_bets_predictable`
  - `test_e_b_is_betting_process_not_cs_derived`
  - `test_eprocess_null_mc_intraday_dependent_take_count`
  - `test_eprocess_null_mc_mixed_side_same_station_day`
  - `test_h0_crossing_rate_le_alpha_exact_null`
    - The three MC tests above use stdlib `random`, a fixed seed and the Wilson upper bound ≤ α_k. Size them to stay under ~10 s.
  - `test_eprocess_matches_f5_mc_reference_on_shared_fixtures` (cross-check):
    - Fixed takes per day → Y/Z/λ/μ/e_a/e_b/n_cum vectors.
    - The literal vectors come from one scratch run of `fq_mc_eprocess.items_to_yz` / `eprocess_scan`, with the provenance sha in a comment.
  - `test_design_fixture_matches_f5_design_json`
  - `test_betting_rule_other_than_agrapa_v1_refused`
- **`tests/unit/autonomy/test_confidence_sequence.py`**
  - `test_kill_cs_uses_clipped_haircut_y`
  - `test_cs_reject_only_when_ub_lt_0`
  - `test_cs_range_normalised_kill_side_lambda_usable`
  - `test_alpha_kill_pinned_separately_never_charged`
  - `test_kill_matches_f5_mc_reference_on_shared_fixtures` (cross-check against `kill_first_n`)
  - `test_bss_on_takes_uses_ask_comparator`
  - `test_bootstrap_clusters_by_calendar_day` (conditional on the `scoring_core` verify-first)
- **`tests/unit/autonomy/test_evidence_row.py`**
  - `test_evidence_row_single_loader_contract`
  - `test_load_evidence_rows_accepts_no_path_argument`
  - `test_evidence_row_cannot_be_forged_via_replace_or_pickle`
  - `test_evidence_row_copy_refused`
  - `test_evidence_row_object_setattr_banned_by_ast`
  - `test_evidence_row_is_final_subclass_refused`
  - `test_evidence_row_object_new_path_refused_by_consumers_and_banned_by_ast`
  - `test_consumers_require_exact_type_evidence_row`
  - `test_loader_returns_sealed_loaded_evidence_and_consumers_require_it`
  - `test_no_pickle_load_or_setstate_in_analysis_autonomy_ast` (verify-first: existing `analysis/autonomy/*` modules are clean)
  - `test_ref_ts_lt_take_ts_enforced_at_load`
  - `test_untagged_row_refused`
  - `test_every_store_reader_refuses_until_its_owner_lands`
- **`tests/unit/autonomy/test_fq_evaluator.py`**
  - `test_backtest_only_input_never_yields_pass`
  - `test_backtest_rows_reject_only`
  - `test_fq_evaluator_refuses_untagged`
  - `test_fq_evaluator_refuses_unknown_tag`
  - `test_forward_shadow_refuses_without_registered_forward_shadow_source`
  - `test_forward_shadow_refuses_non_loaded_evidence`
  - `test_calibration_guard_insufficient_blocks` (D8)
  - `test_market_baseline_paths_refuse_with_named_reason`
  - `test_pass_requires_both_e_a_and_e_b_at_alpha_k` (IUT)
  - `test_no_pass_or_fail_below_earliest_look_n`
  - `test_label_still_routes_to_fq_scorer`
  - `test_fq_evaluator_is_refusing_and_incomplete`

### Tests MOVED out of Slice 2 (modules absent)
- **To AUT-4 row 10:**
  - `tests/unit/autonomy/test_nomination.py`:
    - `::test_e_process_feasible_from_pinned_power_table`
    - `::test_e_process_row_n_min_eff_is_fixed_n_disclosure`
    - `::test_infeasible_nominations_capped_per_lineage`
    - `::test_e_process_nomination_infeasible_without_forward_shadow_source`
    - E-25's `test_alpha_frozen_at_test_start_per_lineage_no_pooling` and `test_infeasible_nomination_burns_no_k_slot`
  - `tests/unit/autonomy/test_forward_shadow.py`:
    - `::test_e_process_fs_copies_row_columns_except_n_min_eff`
    - `::test_e_process_terminal_outcome_final`
    - `::test_e_process_window_end_no_crossing_inconclusive`
    - r3's `test_nominee_single_look_never_reopened`
  - `tests/unit/autonomy/test_eval_live.py`:
    - `::test_live_sequential_e_process_win_pass_kill_fail`
    - `test_eval_live_refuses_untagged` and `…_unknown_tag`
    - `test_shadow_rows_never_enter_live_sequential`
  - `tests/contract/test_nomination_columns_contract.py::test_called_inside_begin_immediate_with_e_process_keys`
  - Untagged/unknown-tag refusals for `eval_offline_fs` and `parity_gate`, and every §R12-5 parity-detector test (F1 r3:479-490, :506).
- **To AUT-5 r8 WP3 (D14):** `test_policy_loader_refuses_fq_lineage_fixed_n`.
- **Already F5-owned:** `test_n_e_power_is_joint_power_of_min_ea_eb` (`tests/unit/test_fq_resume_n_mc.py:275`). Do not duplicate it.

### Deferred items
- **market_baseline (D6):** `bss_all_decisions` refuses until AUT-4 WP1r moves `market_baseline` into `analysis/stats/`. That module currently does not exist anywhere.
- **Forward-only shadow source registration (E-25 6b):** needs an F5 ruling.
- **Calibration-guard thresholds (D8) and the per-rung PIT definition:** F5/F1 pin requests.
- **Wiring the real store readers in `_READERS`:** each lands with its consumer's WP.

### Risks
- **MC cross-check fragility [MEDIUM].** The MC is numpy-vectorised; production is scalar. Pin the summation order per day, using a slice sum as at `:83`, and compare at 1e-12 relative, not bit-exactly.
- **Override-policy loosening [MEDIUM].** Mitigation: the per-class allowance names one class and one member, and a new planted-violation test proves it is still enforced.
- **Dead-in-production evaluator [accepted].** The refusal is deliberate under E-25 6b and D8, and it is tested.
- **Import cycle [LOW].** Resolved by moving `_batch`. `lint-imports` must keep "live path never imports analysis" (`pyproject.toml:152-160`).
- **The `analysis/autonomy` AST bans may flag existing code [LOW].** Verify-first before RED.

### Out of scope (Slice 2)
`nomination.py`, `forward_shadow.py`, `eval_live.py`, `eval_offline.py`, the parity detector, the policy loader, the AUT-S screen (F11), any verdict writing, and any change to `NODE_PLUGINS`, `app/`, `strategy/`, the exec client or enablement.

### Focused gate (Slice 2)
- The Slice 1 focused set, plus:
  - `tests/unit/autonomy/test_eprocess.py`, `test_confidence_sequence.py`, `test_evidence_row.py`, `test_fq_evaluator.py`
  - `tests/unit/test_autonomy_plugins.py`, `tests/unit/test_aut2_offline_plugins.py`
  - `tests/unit/test_brier_decomposition.py`
  - `tests/unit/test_fq_resume_n_mc.py`, `tests/unit/test_prereg_precommit_check.py`
  - The three firewall/exec-import-pin guards
- Run `lint-imports` from the tree, then `scripts/ci/run_tests_no_egress.sh` (full). Activation is offline with no respawn.

---

## Merge order and briefing notes
1. Slice 1, then its full gate, then merge. Slice 2 rebases onto it, re-runs its gate, then merges.
2. Each implementer brief must restate:
   - Nautilus is immutable.
   - `allow_short=False`.
   - Never weaken a safety, settlement or contract test.
   - Never set the operator caps.
   - Never touch enablement or the NO-SEND firewall.
   - Run ruff format only on the files you touch.
   - Use `PYTHONPATH=<worktree>/src` and the explicit interpreter path, and never run `uv sync`.
3. Open questions for the peer loop: D3, D8, D9, D10, D11, D12 and D14, plus the `FqEvaluator` class structure in Slice 2 step 6.

Key paths:
- `/home/jon/breezy/src/breezy/persistence/autonomy/verdict.py`
- `/home/jon/breezy/src/breezy/persistence/autonomy/pins.py`
- `/home/jon/breezy/src/breezy/analysis/autonomy/metric_registry.py`
- `/home/jon/breezy/src/breezy/analysis/autonomy/offline_plugins.py`
- `/home/jon/breezy/pyproject.toml`
- `/home/jon/breezy/tests/unit/test_autonomy_verdict.py`
- `/home/jon/breezy/tests/unit/autonomy/test_verdict_schema.py`
- `/home/jon/breezy/tests/unit/test_autonomy_plugins.py`
- `/home/jon/breezy/tests/unit/test_aut2_offline_plugins.py`
- `/home/jon/breezy/tests/unit/test_autonomy_pins.py`
- `/home/jon/breezy/tests/unit/test_autonomy_contracts.py`
- `/home/jon/breezy/scripts/analysis/fq_mc_eprocess.py`
- `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F5_prereg_v2_design.json`
---
## Coordinator provisional rulings (peers may overturn with evidence)
- **D1:** replace the FQ entry at `:80`.
- **D2:** fixtures only: FS fixtures gain `test_kind=fixed_n`. Any assertion edit → STOP.
- **D3:** the tie key is (decision_ts_ns, station, rung_id, side). This is a clarification of E-25.
- **D4:** keep the E-25 name `alpha_schedule`; the loader maps it.
- **D5:** widen `NULL_COLUMNS_BY_KIND` in Slice 1.
- **D7:** n is Σ N_d over all takes, voids included.
- **D8:** the calibration guard fails closed (PASS unreachable), and an F5 pin request is filed.
- **D9:** copy the MC constants exactly. Needs the stats peer's confirmation.
- **D10:** `eta_ns` is nullable, and only when test_kind is e_process.
- **D11:** `window_end` is nullable on FS and refused elsewhere.
- **D12:** the loader takes a typed root object, never a path.
- **D14:** the policy-loader test moves to AUT-5 r8 WP3.
- **Slice 2 step 6:** `FqEvaluator(RefusingPlugin)`; `_batch` moves to `scoring_batch.require_scoring_batch`.

---
## r2 rulings (coordinator, 2026-10-06, after round-1 reviews)

Round 1 verdicts:
- architect: REQUEST_CHANGES
- prediction-market-reviewer: REQUEST_CHANGES (7/6/7/7/8)
- python-reviewer: MEDIUM

These rulings are BINDING over the plan text and the provisional rulings above.

### Slice 1
- **F7B-R1. Enum rename.** The enum is `StatTestKind`, not `TestKind`, so pytest does not try to collect it.
- **F7B-R2. Strict D10/D11.**
  - `eta_ns` is non-null only on FORWARD_SHADOW with `test_kind == e_process`. It is refused on LIVE_SEQUENTIAL and on every other kind.
  - `window_end` is **required** on FS `e_process`, nullable on FS `fixed_n`, and refused on every other kind.
  - `NULL_COLUMNS_BY_KIND`:
    - LIVE_SEQUENTIAL gains `eta_ns` and `window_end`.
    - OFFLINE_CHALLENGER and HEALTH gain all three.
  - Add a registry constant `FORWARD_SHADOW_E_PROCESS_ONLY_COLUMNS = ("eta_ns", "window_end")` with an agreement assertion.
  - `check_int` must accept None for `eta_ns`; test this.
- **F7B-R3. Test helpers.**
  - The `_verdict()` helpers in `test_verdict_schema.py` and `test_registry_fold_validate.py:665` default `test_kind` from the kind: `fixed_n` for FS, None otherwise. Overrides are still accepted. No assertion is edited; any assertion edit → STOP.
  - Goldens are re-derived outside `Verdict`.
- **F7B-R4. Verify-firsts at implementation time.**
  - Re-check that `$STATE/derived/verdicts/` is empty. If it is not → STOP.
  - Run §R12-3 verify-first #3 (Σα ≤ α_total checks) with grep and record the result in the commit body.
  - The `is`-identity half of `test_elond_single_definition_in_persistence` is an explicit deferral to the first slice that re-exports `elond`. Scope the AST scan to `persistence/` and `analysis/`.
- **F7B-R5. Decimal.** `elond` uses `ctx.ln`, `ctx.divide` and `ctx.multiply` on a module-local `Context(prec=34)`. It never uses the ambient context.
- **F7B-R6. Gates.**
  - The focused gate adds **all** `tests/unit/test_autonomy_*.py`, `test_r2_2_citation_map.py`, `test_strategy_module_gate.py`, `test_nautilus_native_import_gate.py`, `test_runtime_import_isolation.py` and `test_mypy_ratchet.py`.
  - `regen_closure_manifest --check`: re-pin by regen when `elond` lands. That is a re-pin, never a loosening.
  - Run `cd <wt> && PYTHONPATH=$PWD/src lint-imports`; it must report "N kept, 0 broken".

### Slice 2
- **F7B-R7. FqEvaluator overrides nothing new.** `FqEvaluator(RefusingPlugin)` defines only `label` and `has_scorer`.
  - `evaluate_e_process` and the guard chain are pure module-level functions, tested directly.
  - `forward_shadow` stays refusing; the override arrives with the WP that registers a forward-only source.
  - `ALLOWED_SUBCLASS_NAMES` and the policing test stay **byte-unchanged**. Only `EXPECTED_OFFLINE_TYPES` and the rename in `test_aut2_offline_plugins.py` change.
  - `_batch` → `scoring_batch.require_scoring_batch` is kept.
- **F7B-R8. Evidence loading.**
  - **Signature.** `load_evidence_rows(store_kind)` takes only the store kind, as in the spec. Each reader resolves its own root when its owner WP wires it.
  - **Test patching.** Tests patch with `monkeypatch.setattr(evidence_row, "_READERS", MappingProxyType({...}))`. The loader reads the module global at call time. A test proves the patched reader is used.
- **F7B-R9. `__setstate__` AST rule (clarification of the §R12-3:451 vs :456 conflict).** A `__setstate__` is allowed only in `evidence_row.py`, and only when its whole body is a single `raise TypeError(...)`. A planted non-raising `__setstate__` must be caught.
  - The rest of the sealing stays as §R12-3 requires.
  - The docstring states plainly that `_TOKEN` is importable, so this is an accident guard enforced by AST bans.
- **F7B-R10. D9 restated.**
  - The KILL test's validity rests on the **m=0** hedged capital: a supermartingale under H0, by Ville, with P ≤ α_kill/2.
  - The other grid points (KILL_GRID_POINTS=5 over [0, X_max]) only add conservatism.
  - The plan's "⇔ UB<0" and "confidence sequence UB" wording is withdrawn. The module docstring states the m=0 argument and that the false-KILL bound is ≤ α_kill/2.
  - The constants are copied from the MC (grid 5, per-m λ cap, θ=½, bar log(2/α_kill)) and filed as an F5 pin request together with D8.
- **F7B-R11. D8 guard.**
  - **Design field.** Guard thresholds are an optional field `guard: GuardThresholds | None`, with `n_guard_min`, `spiegelhalter_abs_z_max`, `slope_band`, `bin_edges` and `pooling` ∈ {pooled, per_side}.
  - **Unpinned.** When the field is None, the guard returns `INSUFFICIENT(guard_unpinned)`. This is a named reason, distinct from `window_end_no_crossing`.
  - **Joint evaluation.** The guard is evaluated **per settled day jointly with the crossing**: PASS needs crossing and guard-OK on the same day, at n ≥ earliest_look_n.
  - **Tests inject thresholds** to exercise the PASS, IUT and finality branches.
  - **F5 pin request.** File one covering: `n_guard_min`, the |Z| ceiling, the slope band, bin edges plus the CI rule, pooled vs per-side, and the D9 constants.
- **F7B-R12. Terminal precedence.**
  - Days are processed sequentially, and the first terminal event wins.
  - If PASS and KILL fall on the same day, the result is **FAIL**.
  - A guard-blocked crossing is not terminal; the process continues.
  - Test: `test_terminal_precedence_same_day_kill_wins_and_first_event_final`.
- **F7B-R13. Day set.**
  - Days are built from the calendar between the first eligible day and `last_settled_day`. They must be contiguous (a gap → refuse). Zero-take days have Y=0, as in the MC, where `n_prev` counts every day.
  - λ_d and μ_d use days strictly before d only.
  - n_cum counts all takes, voids included (D7, stated).
  - Duplicate `(ts, station, rung_id, side)` → refuse.
  - String keys compare as ASCII bytes.
- **F7B-R14. Numerics.**
  - e_a and e_b accumulate in log space.
  - PASS compares `min(log e_a, log e_b) ≥ -log(float(alpha_k))`, converted once.
  - KILL compares against `log(2/alpha_kill)` the same way. Boundary tests exist for both.
  - `EvidenceRow` numeric fields are Decimal at the seal; the float conversion happens once, in `TakeInput` construction.
  - e_b uses the **haircut** ask (r3 / F5 haircut, 1 tick × 0.01), as the MC does; verify against `fq_mc_eprocess.py` and state it.
- **F7B-R15. Void independence.**
  - The docstring documents that a void must be independent of h given G.
  - `test_void_path_never_reads_outcome` uses an AST check or a sentinel.
- **F7B-R16. Null-validity tests.**
  - **Exact enumeration.** Replace the Wilson-UB MC sizing with an exact enumeration over a tiny tree: 2–3 days, Bernoulli at BE, using `fractions.Fraction`. Assert E[e_a] = E[e_b] = 1, or ≤ 1 under clipping.
  - **Least-favourable null.** One seeded MC with λ forced to 0.5, a heavy upside and the clip active. It asserts the crossing rate ≤ α_k + 3·SE, has a fixed seed and runs in under 10 s.
  - **Mutation tests.** These must FAIL the enumeration or MC:
    - λ uses the current day;
    - voids are dropped;
    - ordering depends on the outcome.
- **F7B-R17. Backtest input refused.** `evaluate_e_process` refuses backtest-tagged input outright (`store_kind_not_accepted`). The rule-8 UNDERPOWERED cap stays as a second line; test both.
- **F7B-R18. Spiegelhalter Z.** It is the blocking guard component when the guard is pinned (§R12-3:469) and is reported otherwise.
- **F7B-R19. Commit split.** Slice 2 ships as three commits: the pure cores (eprocess, kill test), evidence_row, then the evaluator plus the plugin swap.
- **F7B-R20. Erratum.** Ruling R3's "AUT-4 row 10" for the policy-loader test reads **AUT-5 r8 WP3** (D14).

**STATUS:**
- **Slice 1 READY.** Round-1 issues were resolved by R1–R6 as the reviewers stated them.
- **Slice 2** goes to a round-2 review (stats + architect) on R7–R19 before build.

---
## r3 rulings (coordinator, 2026-10-06, after the round-2 reviews of Slice 2)

Round-2 reviews: stats REQUEST_CHANGES, architect REQUEST_CHANGES. Each fix below is adopted as the reviewer stated it. These rulings are BINDING over the plan body and R7–R20.

- **F7B-R21 (supersedes the R14 haircut clause).**
  - BE and X use the haircut ask: `ask + haircut + fee`, as in `_break_even` in `fq_mc_livedata.py`.
  - The **Z comparator** (`(ask−h)² − (p−h)²`, `fq_mc_eprocess.py:139`) and BSS-on-takes use the **raw executable quote**, with no haircut.
  - Cross-check fixtures carry `raw_ask` and the haircut `be` as distinct fields.
  - `test_bss_on_takes_uses_ask_comparator` asserts that the raw ask is used.
  - e_b's validity requires the comparator to be G-measurable at decision time. The docstring says so.
- **F7B-R22 (supersedes the R10 null wording).**
  - The m=0 KILL capital `∏(1−λ(Y−m))`, with λ ≥ 0 predictable, is a supermartingale when E[Y|F] ≥ 0, i.e. under the **no-loss null**.
  - False-KILL ≤ α_kill/2 therefore holds whenever the true edge is non-negative. Under the PASS null (E[Y] ≤ 0) the capital grows, and KILL is intended.
  - Requiring all 5 grid points only adds conservatism. The per-m λ cap guarantees `1−λ(Y−m) > 0`.
  - Add an enumeration test at E[Y]=0 asserting E[m=0 capital] ≤ 1.
- **F7B-R23 (R13 voids and unsettled takes).**
  - `h=None` means a **venue-declared void** only, carried as an explicit `void=True` field.
  - A take with unknown h on a day ≤ `last_settled_day` is refused (`unsettled_take_in_settled_day`), never scored as 0.
  - Test: `test_unsettled_take_refused_not_voided`.
- **F7B-R24 (R13 gap definition).**
  - A calendar day is **covered** only with a settled-coverage marker, per the "covered means recorder capture only" rule. The marker is supplied with the evidence: `LoadedEvidence.covered_days`.
  - A day in range without the marker is a gap, and the evaluator refuses (`coverage_gap`).
  - A covered day with zero takes is Y=0.
  - Tests:
    - `test_uncovered_day_is_gap_refused`
    - `test_covered_zero_take_day_is_y0`
- **F7B-R25 (contract classification for Slice 2's new modules).**
  - Add one import-linter `forbidden` contract with `allow_indirect_imports = false`.
    - Name it outside the `ARCH-0 autonomy (` prefix, so `test_three_arch0_contracts_are_strict_forbidden` stays at three.
    - Its source modules are `breezy.analysis.autonomy.eprocess` and `breezy.analysis.autonomy.confidence_sequence`, listed by module.
    - It forbids `nautilus_trader`, `breezy.strategy`, `breezy.runtime`, `breezy.adapters` and `breezy.app`, plus `pyarrow` unless the verify-first shows `analysis/stats/scoring_core.py` reaches it. If it does, the BSS interval uses an injected callable, or ships point-only as R2-step-2 already allows.
  - `evidence_row`, `evaluators.forecast_quantile_ladder` and `labeling.scoring_batch` each get an explicit classification row: either "never reaches nautilus/strategy/runtime/adapters", or a reasoned exemption (`scoring_batch` → `label_store` is PYARROW_REACHING).
  - Add a membership test with a planted-unclassified-module case, modelled on `test_autonomy_contracts.py:134-148`.
  - `regen_closure_manifest --check` stays in the gate as a positive control and is expected to show no diff.
- **F7B-R26 (body text struck).** Under R7, the Slice 2 body text describing a `forward_shadow` override and `ALLOWED_OWN_NAMES_BY_CLASS` is VOID: §Slice 2 acceptance bullets 3–4, step 5 (`forward_shadow` member), step 7 (`ALLOWED_OWN_NAMES_BY_CLASS`, planted lookalike), and the "Override-policy loosening" risk.
  - `test_forward_shadow_refuses_without_registered_forward_shadow_source` and `…_non_loaded_evidence` target the **module-level guard chain** (`check_forward_shadow_inputs(...)`), not a plugin member.
  - The inherited `forward_shadow` raises a plain `PluginRefused`. This is unchanged and covered by the existing byte-unchanged test.
- **F7B-R27 (R17).** The rule-8 UNDERPOWERED cap lives in a private `_cap_backtest_outcome()` that is tested directly. `evaluate_e_process` refuses backtest input before reaching it.
- **F7B-R28 (R8).** The "patched reader is used" test includes a planted case showing that a default-argument or closure binding of `_READERS` would be caught: the loader reads `evidence_row._READERS` by global name at call time.

**STATUS: Slice 2 READY (2026-10-06).** Round 2 surfaced only fixes the reviewers specified exactly; each is adopted verbatim above. The post-build code review (prediction-market-reviewer + python-reviewer + architect) re-checks R21–R28 against the code. Build order: Slice 1 merges first, then Slice 2 rebases onto it.
