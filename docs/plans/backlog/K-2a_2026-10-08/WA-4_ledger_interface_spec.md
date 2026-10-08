# WA-4: Kalshi hypothesis ledger interface spec (desk spec, lands in WB-4)

**Status:** desk spec written 2026-10-08. **READY**: the architect review returned CHANGES, and the binding amendments W1–W14 at the end of this file are applied.

K-2a touches no file under `src/`, `tests/` or `scripts/`.

**Governed by:**
- K-2a plan r2 §5 and §7 WA-4, amendments B2 and B3, and the r2.1 deltas R2–R4.
- The WA-3 draft, with its binding amendments F1 and F2.

**Acceptance:**
- `hypothesis_ledger.py` bytes are unchanged.
- The only contract edits are the two D6(i) rows in §7.

Citations of the form `:NNN` mean `src/breezy/analysis/hypothesis_ledger.py` at 268f0ca8.

## Deviations from the brief and R2 (for review)

Each deviation is forced by an existing guard or by the §0 allowed-edit list.

- **D1. Extra imports.** The spec adds two imports, `HypothesisRecord` (annotation only) and `may_gate_re_arm`.
  - The R3-5 barrier (`tests/unit/test_hypothesis_triage.py:1568-1580`) forbids reading `.re_arm_gating` anywhere outside `hypothesis_ledger.py`.
  - So PM.us re-arm α can only be totalled through `may_gate_re_arm`.
- **D2. Field name.** The K re-arm field is named `k_re_arm_gating`.
  - R3-5 exempts files by name only.
  - Widening that exemption would be a PM.us test edit, which §0 does not allow.
  - K therefore gets its own barrier test (R18).
- **D3. No `dataclasses.replace` in the K module.**
  - Importing `HypothesisRecord` puts the K module under the R3-4 scan (`:1502`).
  - `replace_record_status_k` therefore rebuilds the record via `from_dict`.
- **D4. `break_even` is duplicated, not imported.** G1 needs cent rounding, and the PM.us function has none.
- **D5. No separate constants module.** It would need its own D6(i) rows.
- **D6. A missing PM.us ledger file makes K registration refuse.** PM.us itself treats a missing ledger as empty.

The G5 climate-date definition of n is also up for confirmation.

## 1. Module, path and imports

**Module:** `src/breezy/analysis/hypothesis_ledger_kalshi.py`, i.e. `breezy.analysis.hypothesis_ledger_kalshi`.
- The core is pure: no I/O apart from the K reader and writer.
- The K constants live in this module, mirroring PM.us `:125-216`.

**I/O shell:** `scripts/analysis/hypothesis_register_kalshi.py`, mirroring `scripts/analysis/hypothesis_register.py:264-301`.

**Ledger path:**
- `KALSHI_LEDGER_RELPATH: Final = Path("hypothesis_kalshi/hypothesis_ledger_kalshi.jsonl")`, plus `kalshi_ledger_path(derived_root) -> Path`.
- It lives in its own directory, never `<derived>/hypothesis/`. That keeps PM.us triage (`hypothesis_triage.py:154`) and its scans away from K files.

**Imported from `breezy.analysis.hypothesis_ledger` (nothing else):**

| Name | Why |
|---|---|
| `HYPOTHESIS_LEDGER_SCHEMA_VERSION`, `_V2`, `_V3` | Disjointness assertion (G2) |
| `parse_stratum_filter` | Pure filter validation (R2) |
| `recompute_mde` | Adopted (G1) |
| `HypothesisRecord` (annotation only), `may_gate_re_arm` | Snapshot of the PM.us budget for B2/F1 (§5). PM.us re-arm α is classified only through `may_gate_re_arm` (D1) |

**Deliberately not imported:**
- `break_even`: G1 duplicates it as `break_even_k`.
- `register_hypothesis`, `to_dict`/`from_dict`, the PM.us writer, and every PM.us constant.

`read_hypothesis_ledger` is imported only by the script shell. The shell reads the PM.us ledger once per call (R2, F1(5)).

**R3-4 consequence.** Because the K module imports `HypothesisRecord`, the R3-4 scan (`test_hypothesis_triage.py:1502-1520`, `:1451-1460`) covers it.
- The K module never calls `dataclasses.replace`.
- `replace_record_status_k` rebuilds the record via `from_dict({**r.to_dict(), "status": s}, constants=...)`, which also re-validates it.

## 2. G1: MDE and break-even

**MDE: adopt `recompute_mde` (`:863-874`).**
- It is hard-wired to `VARIANCE_BOUND=0.25` (`:196`) and `POWER=0.80` (`:192`).
- Both values are venue-free:
  - The Popoviciu bound holds for any contract that pays {0,1} minus a constant break-even.
  - The §5 n_K formula already uses 0.5 = √0.25 and z(0.8).
- `KConstants` carries `variance_bound=0.25` and `power=0.80`.
- A **cross-set equality test** asserts that both equal the PM.us constants. If PM.us ever changes them, K goes red and must decide explicitly; it never inherits a change silently.

**Break-even: duplicate it.**
- PM.us `break_even` (`:855-860`) has no rounding.
- The K register must not check `EVIDENCED_FEE_THETA` (`:1100`).

Signature:

```
break_even_k(*, reference_ask: Fraction, theta_k: Fraction,
             fee_rounding: Literal["CEIL_CENT_PER_ORDER", "NONE"],
             slippage: Fraction, contracts: int = 1) -> Fraction
```

Computation, all in Fraction arithmetic:
- `raw = theta_k·C·a·(1−a)`
- `fee = Fraction(ceil(raw·100), 100)` for `CEIL_CENT_PER_ORDER`, or `raw` for `NONE`
- result = `a + fee(a)/C + slippage`

**Where θ_K comes from.** θ_K and the rounding mode come only from the WA-3 §7 sourcing artefact. That artefact combines the series `fee_type`/`fee_multiplier`, the published fee schedule, and a golden vector.

Until the artefact exists:
- `theta_k=None`, `fee_rounding=None`, `theta_k_verified=False`.
- The K register refuses NORMAL intake with `ThetaKNotSourcedError`.

Once θ_K is sourced, the register refuses with `StaleFeeThetaKError` when either holds:
- `Fraction(str(mde_fee_theta)) != theta_k`
- `mde_fee_rounding != fee_rounding`

## 3. G2: mutual unreadability

Two independent locks; either one is sufficient:
1. `KALSHI_LEDGER_SCHEMA_VERSION: Final[int] = 101`, which is disjoint from {1, 2, 3}.
2. A mandatory field `ledger_family: Literal["KALSHI"]`.

**PM.us code reading a K line refuses at:**
- `HypothesisRecord.from_dict` `:643-647` (unknown version).
- `read_hypothesis_ledger` `:1386-1390`.
- A K line forged to version 3 still fails at `:655-659`, on its unexpected keys (`ledger_family`, `min_climate_day_clusters`, `mde_fee_rounding`, `k_re_arm_gating`).
- None of this needs a PM.us edit.

**K code reading a PM.us line:** `KalshiHypothesisRecord.from_dict` refuses any of:
- a version other than 101;
- a missing `ledger_family`, or any value other than `KALSHI`;
- any PM.us-only key (`min_station_days`, `re_arm_gating`).

**Writer guard:** `write_kalshi_hypothesis_ledger` refuses unless `path.name == "hypothesis_ledger_kalshi.jsonl"`.

## 4. G3: K constants

Defined as `@dataclass(frozen=True, slots=True, kw_only=True) class KConstants`, with a module-level `K_CONSTANTS: Final`.

| PM.us constant (cite) | K field and value | Disposition and why |
|---|---|---|
| PROGRAMME_ALPHA `:177`, check `:961-968` | `programme_alpha: Fraction \| None = None` | Value frozen at WB-7b (F1(3)). None means NORMAL intake is refused (`KBudgetNotFrozenError`) |
| RE_ARM_GATING_PROGRAMME_ALPHA `:158`, `:1041`, `:580-588` | `re_arm_alpha: Fraction \| None = None` | F1(3). A value ≤ 0 turns a re-arm-gating request into a zero-look record (F2) |
| MAX_HYPOTHESES `:181`, `:815-824`, `:1118` | `max_hypotheses: int = 3` | One slot per class (WA-3 §1) |
| MAX_VARIANTS_PER_HYPOTHESIS `:183`, `:1070` | `max_variants: int = 4` | Mirrors PM.us (N5, WA-3 §2) |
| MIN_PER_VARIANT_ALPHA `:186` (enforced nowhere) | `r4_floor: Fraction = Fraction("0.003125")` | R4 plus the WA-3 fix. If `programme_alpha ≤ 0` or `< max_h·max_v·r4_floor`, the record is zero-look and the route goes to N-2. Exactly 0.0375 passes. `min_per_variant_alpha` is asserted as `programme_alpha/3/4`, never re-derived |
| EVIDENCED_FEE_THETA `:204`, `:1100` | `theta_k`, `fee_rounding`, `theta_k_verified=False` | **Dropped.** PM.us θ is banned for K (§5) |
| HORIZON_TOLLING_LANDED `:166`, gate `:1176-1181` | `horizon_tolling_landed: bool = False` | **Mirrored.** K triage must implement tolling itself. The flag flips only in its own reviewed RED→GREEN commit, before WB-7b |
| PATH_B_SOURCE_GATE_LANDED `:174`, gate `:1182-1188` | `path_b_source_gate_landed: bool = False` | **Mirrored, starts False.** K replay and triage sources must first be scoped to the Kalshi family |
| RULED_HORIZON_DAYS `:153`, check `:571-579` | `ruled_horizon_days = frozenset({120, 180})` | Mirrored (§5 horizon). It is K's own set: a later ruling adds a K row only, with no cross-equality to PM.us |
| PINNED_ORDER_QUANTITY `:202`, `:1080` | `pinned_order_quantity = 1` | Mirrored, with extra force: per-order cent rounding makes per-contract break-even depend on C, so C = 1 pins break-even |
| MDE_MISMATCH_TOLERANCE `:216`, `:1123` | `mde_tolerance = 1e-4` | Mirrored. Same `recompute_mde`, so the same numeric slack |
| Plausibility bound: caller-supplied `:888`, checked `:1129` | `plausibility_bound_by_class: tuple[tuple[str, float], ...] = ()` | **Changed.** The caller's value must equal the frozen per-class value (KC-1 = bound_K from WB-7). A class with no bound refuses (`NoPlausibilityBoundError`), so KC-2 and KC-3 stay refused until sourced |
| STATION_DAY_STATISTIC `:199`/`:1085`, MAX_SINGLE_DAY_LEG_SHARE `:212`/`:1090`, ZERO_TAKE `:207`, POOLED_PNL_VETO `:209`, SINGLE_LOOK `:1075`, status set `:218-229` | Same values | Mirrored. These are venue-free design pins |
| VARIANCE_BOUND `:196`, POWER `:192` | `variance_bound=0.25`, `power=0.80` | Cross-set equality test (G1) |
| (new) | `combined_alpha_cap=Fraction("0.05")`, `combined_re_arm_cap=Fraction("0.025")`, `classes=("KC-1","KC-2","KC-3")` | B2 / F1 |

## 5. G4: combined budget, enforced at runtime (F1(5))

All arithmetic uses `Fraction(str(x))` (F1(6)).

**Types and helpers:**
- `PmBudgetSnapshot(look_alpha: Fraction, re_arm_alpha: Fraction)`.
- `pm_budget_snapshot(pm_records: Sequence[HypothesisRecord]) -> PmBudgetSnapshot`:
  - `look_alpha` is the sum of `allocated_alpha` over records that are not zero-look.
  - `re_arm_alpha` is the same sum over records where `may_gate_re_arm(r)` is true.
- `combined_budget_breach(snap, constants) -> str | None` returns a breach when any of these holds. K_reserved is the whole frozen budget (F1(4)).
  - `snap.look_alpha + programme_alpha > combined_alpha_cap`
  - `snap.re_arm_alpha + re_arm_alpha > combined_re_arm_cap`
  - either K budget value is None

**Where the check runs:**
- `register_hypothesis_k` calls the check first. A breach raises `CombinedBudgetExceededError`, naming both terms.
- `may_gate_re_arm_k` returns False on any breach (fail-closed).
- K triage (WB-4) alerts on the same helper every night.

**Shell behaviour:** `register_and_persist_k` re-reads the PM.us ledger on every call. A missing PM.us ledger file means **refuse**, never "treat as empty" (D6).

**Record checks.** Re-arm and allocation checks compare `Fraction(str(stored_float))` against `Fraction(str(float(cap / max_h)))`. A test proves that every register output round-trips through `__post_init__` and `may_gate_re_arm_k`.

## 6. G5: the unit of n

The PM.us field is renamed **`min_climate_day_clusters: int`** for K.
- One cluster is one distinct climate date. It pools every admitted station-day on that date (the §4 n_min "distinct climate dates", §5).
- K has no `min_station_days` field. `from_dict` refuses that key, and the register signature has no such parameter.
- The single call site is `recompute_mde(..., n_station_days=min_climate_day_clusters)`. The PM.us keyword name there is a known misnomer, and the docstring says so.

## 7. G7: sha256 pin and the D6(i) widenings

**The pin:**
- It lives in a new `tests/unit/test_hypothesis_ledger_sha256_pin.py`, which is **WB-4's first commit** (A3a), before any K file exists.
- It holds `HYPOTHESIS_LEDGER_SHA256: Final[str]`, a **whole-file** hash: `hashlib.sha256(path.read_bytes())`, with no normalisation.
- Value at 268f0ca8, for information only: `c574ba722cc4a89a8d2bc442eef9918bf3b8182161bda9f0da5de5a43ed39214`. WB-4 recomputes it at its own base.
- Non-vacuity check: flipping one byte in a temporary copy must change the digest.
- **Change rule:** the pin changes only by editing that one line, in the same reviewed commit as the PM.us edit it covers, citing the ruling.

**D6(i) rows.** Add one row each to `pyproject.toml:176-213`:

| Contract | Edit |
|---|---|
| `"AUD-18 D6(i): the hypothesis ledger stays outside the live import graph, both ways"` | add `"breezy.analysis.hypothesis_ledger_kalshi"` to `source_modules` |
| `"AUD-18 D6(i): the live import graph never reaches into the hypothesis ledger"` | add the same module to `forbidden_modules` |

`lint-imports` (the console script, run with CWD = tree) must report an unchanged kept count and 0 broken.

## 8. The record: `KalshiHypothesisRecord` (frozen, slots, kw_only)

Fields follow the PM.us order (`:492-529`). Fields new or renamed for K are marked.

| Field | Note |
|---|---|
| `schema_version` | = 101 |
| `ledger_family` | **new**; = "KALSHI" |
| `hypothesis_id` | |
| `hypothesis_class` | must be in `classes` |
| `registered_at` | |
| `k_variants` | |
| `allocated_alpha` | |
| `per_variant_alpha` | |
| `min_climate_day_clusters` | **renamed** (G5) |
| `max_single_day_leg_share_cap` | |
| `mde_at_allocated_alpha` | |
| `mde_plausibility_bound` | |
| `power_is_primary_only` | |
| `mde_reference_ask` | |
| `mde_fee_theta` | |
| `mde_fee_rounding` | **new** |
| `mde_slippage_allowance` | |
| `mde_variance_bound` | |
| `mde_variance_bound_justification: str \| None` | |
| `station_day_statistic` | |
| `order_quantity` | |
| `look_policy` | |
| `freeze_commit` | |
| `status` | |
| `is_zero_look` | |
| `variant_stratum_filters: tuple[str, ...]` | always present; length = k for a look-taking record |
| `horizon_days: int \| None` | |
| `k_re_arm_gating: bool` | **renamed** (D2); never null |
| `constants: KConstants` | `field(default=K_CONSTANTS, compare=False, repr=False)`; excluded from `to_dict` |

**Validation in `__post_init__`:**
- It is keyed on `self.constants`, never on PM.us `MAX_HYPOTHESES` (B3).
- It mirrors `:532-596`.
- A look-taking record with `k_re_arm_gating` set requires `allocated·max_h ≤ re_arm_alpha` and `per_variant·k ≤ allocated`.

## 9. Signatures

All parameters are keyword-only. Every function takes `constants: KConstants = K_CONSTANTS`, and callers can always inject it explicitly.

**`register_hypothesis_k`:**

```
register_hypothesis_k(
    *, hypothesis_id, hypothesis_class, registered_at, k_variants,
    freeze_commit,
    existing_records: Sequence[KalshiHypothesisRecord],
    pm_snapshot: PmBudgetSnapshot,
    min_climate_day_clusters, max_single_day_leg_share_cap,
    mde_at_allocated_alpha, mde_plausibility_bound, power_is_primary_only,
    mde_reference_ask, mde_fee_theta, mde_fee_rounding,
    mde_slippage_allowance, mde_variance_bound,
    mde_variance_bound_justification=None,
    station_day_statistic, order_quantity, look_policy,
    variant_stratum_filters: tuple[str, ...],
    k_re_arm_gating: bool,
    horizon_days: int | None = None,
    programme_alpha_override: float | None = None,
    constants=...,
) -> KalshiHypothesisRecord
```

Checks run in this order, mirroring PM.us `:945-1217`:
1. Duplicate id.
2. `programme_alpha_override`: it may only narrow the budget, and a re-arm-gating record requires override ≤ `re_arm_alpha`.
3. Combined-budget breach.
4. θ_K.
5. Input pins.
6. R4.
7. Slot, with at most one look-taking record per class.
8. Allocation, in Fraction arithmetic.
9. Power check against the class bound (F2).
10. Tolling and Path-B gates.

There is no CLOSED disposition (YAGNI).

**Other functions:**
- `programme_budget_remaining_k(records, *, constants) -> int`
- `may_gate_re_arm_k(record, *, pm_snapshot, constants) -> bool`
- `replace_record_status_k(record, *, status) -> KalshiHypothesisRecord`
- `read_kalshi_hypothesis_ledger(path, *, constants) -> tuple[...]`
- `write_kalshi_hypothesis_ledger(path, records) -> None`: atomic, mirroring `:1355-1370`.
- Shell: `register_and_persist_k(*, k_path, pm_path, require_status=None, **kw)`.

## 10. G6: parity tests (R3)

`tests/unit/test_hypothesis_ledger_kalshi_parity.py` builds `PM_MIRROR = KConstants(...)` as a **literal frozen dataclass** with these values:
- programme α 0.05 and re-arm α 0.025;
- max_h 4 and max_v 4;
- θ 0.0695 with `NONE` rounding;
- both flags False;
- plausibility bounds taken from the PM.us vectors.

It is passed as `constants=PM_MIRROR`, together with an empty `pm_snapshot`.

Rules for the parity file:
- No `monkeypatch` anywhere. A test greps the file for that string.
- A guard test asserts that every `PM_MIRROR` literal equals its PM.us constant.

What the parity suite checks:
- Each PM.us V3 register vector runs through both modules, **including a re-arm-gating case** (WA-3 §5). The two results must agree on status, allocated, per_variant, mde and is_zero_look. Where PM.us raises, the K error class must be the one a declared mapping table assigns to the PM.us class.
- `may_gate_re_arm` and `may_gate_re_arm_k` must agree on constructed records.
- `break_even_k` with `NONE` rounding must equal `break_even` within 1e-12.

## 11. RED test list

All tests live in `tests/unit/test_hypothesis_ledger_kalshi.py` unless another file is named.

**Pin and import contracts**
- R1. The pin file is green at the WB-4 base. Its non-vacuity check (one flipped byte changes the digest) also passes (§7).
- R2. `lint-imports`: both D6(i) contracts list the K module, and the kept count is unchanged.
- R3. AST check: the K module's imports from PM.us are a subset of the §1 set.

**Mutual unreadability (G2)**
- R4. PM.us `from_dict` and `read_hypothesis_ledger` refuse a K line, including a K line forged to v3.
- R5. The K `from_dict` and reader refuse PM.us v1, v2 and v3 fixture lines (`tests/fixtures/hypothesis/*.jsonl`).
- R6. The K version is disjoint from {1, 2, 3}. The writer refuses the PM.us filename. The K path differs from the PM.us `ledger_path`.

**Constants and fees (G1, G3)**
- R7. VARIANCE_BOUND and POWER equal their PM.us values (G1).
- R8. `break_even_k` cent-ceil arithmetic on synthetic vectors: raw 0.0175 → 0.02, and a tiny raw → 0.01. Results are exact Fractions.
- R9. θ unset → `ThetaKNotSourcedError`. 0.0695 against a different θ_K → `StaleFeeThetaKError`.
- R10. K budget constants not frozen (None) → NORMAL intake refused.

**Register rules**
- R11. R4 floor: 0.0374 → zero-look; 0.0375 → passes; ≤ 0 → zero-look.
- R12. F2: the power check runs at allocated/k. A result above the class bound → UNDERPOWERED, and no slot is used.
- R13. A class with no plausibility bound refuses. A caller bound that differs from the frozen bound refuses.
- R14. With both K flags False, the tolling and Path-B gates block REGISTERED. A zero-look outcome still passes.

**Combined budget (G4)**
- R15. Combined budget on PM.us + K fixture ledgers: exactly at the cap passes; cap + ε refuses at the register; `may_gate_re_arm_k` returns False on a breach.
- R16. Float trap: `0.0006 + 0.0459 + 0.0035` sums to 0.05000000000000001 in floats but exactly 0.05 in Fractions, so it must PASS. The same shape is tested for 0.025.
- R17. A missing PM.us ledger → `register_and_persist_k` refuses, and the K file's bytes and mtime are unchanged.

**Barriers and record invariants**
- R18. K-R3-4: no `dataclasses.replace` on K records outside the K module. K-R3-5: no `.k_re_arm_gating` read outside the K module.
- R19. A record keyed on K constants refuses re-arm when `allocated·3 > re_arm_alpha`. It accepts a record valid under 3 slots that PM.us would refuse under `MAX_HYPOTHESES`=4 (B3).
- R20. Every register output round-trips byte-identically through `to_dict`/`from_dict` and passes `may_gate_re_arm_k` over a grid of caps.
- R21. At most one look-taking record per class; slots are exhausted at 3.
- R22. G5: `from_dict` refuses `min_station_days`, and the register raises TypeError for it.

**Parity and regression**
- R23. The parity suite (§10): the vectors, the re-arm case, and the literal-equality guard.
- R24. The existing PM.us tests and fixtures, and the R3-4/R3-5 tests, stay byte-unchanged and green.

---
## Review amendments (BINDING): architect review, 2026-10-08

**Rulings.**
- Deviations D1–D6: all ACCEPTED.
- G5 (n counts distinct climate dates): ACCEPTED.
- The pin plus the two D6(i) rows are confirmed as the minimal contract edits.

**Facts the coordinator checked in the primary tree, 2026-10-08:**
- `hypothesis_ledger.py` is unchanged from 268f0ca8 to 79a20837.
- Its sha256 is `c574ba72…ed39214`, which matches §7.
- `0.0006+0.0459+0.0035` evaluates to `0.05000000000000001`, which is greater than 0.05. The R16 trap is real.
- `Fraction(str(float(0.02/3)))*3 > 0.02` is True. The product-form trap is real.

Where these amendments conflict with the text above, they govern.

- **W1. Citations.**
  - §3: a K line forged to v3 is refused first at `:650-654`, because keys are missing (`min_station_days`, `re_arm_gating`).
  - R4 asserts the class `HypothesisLedgerRecordError`, not the message.
  - §4: the plausibility parameter is at `:889`.
- **W2. R16 must check that its own trap is real.** It first asserts that the float sums exceed 0.05 (and 0.025 for the second vector). Only then does it assert that the Fraction path passes.
- **W3. `replace_record_status_k` keeps the record's constants.** It is `from_dict({**r.to_dict(), "status": s}, constants=r.constants)`.
- **W4. Canonical derivations replace the product checks in §8 and R19.**
  - `allocated := float(budget_frac / max_h)` and `per_variant := float(Fraction(str(allocated)) / k)`.
  - `__post_init__` requires `per_variant == float(Fraction(str(allocated)) / k)` exactly.
  - For re-arm records it requires `Fraction(str(allocated)) ≤ Fraction(str(float(re_arm_alpha / max_h)))`.
  - R20's grid covers k ∈ {1, 2, 3, 4} × caps {0.02, 0.025, 0.0375, 0.05, 1/60}, each cap also at ±1 ulp.
- **W5. An unfrozen budget fails first, with its own error.** If `programme_alpha` or `re_arm_alpha` is None, raise `KBudgetNotFrozenError` before the combined-budget check. Drop the None clause from `combined_budget_breach`. R10 asserts that exact class.
- **W6. Failing R4 writes a recorded zero-look row.**
  - The row is persisted as `UNDERPOWERED_NOT_REGISTERED`, with `is_zero_look=True` and allocated 0.0. Its route is N-2.
  - R4 is evaluated **before** the θ_K check, so N-2 can be recorded without θ_K.
  - Add the `KConstants` field `min_per_variant_alpha = programme_alpha / max_h / max_v`, frozen at WB-7b.
- **W7. G5 uses one unit end to end.** The power check, the confirmatory statistic and the leg-share cap all count one observation per climate date. The observation is the mean over that date's admitted station-days. "Single day" means one climate date.
- **W8. Missing or truncated ledgers.**
  - A missing K ledger reads as empty.
  - A missing PM.us ledger refuses, in both the register and K triage.
  - The PM.us path is `ledger_path(derived_root)`, using the same `derived_root` as K.
  - WB-7b freezes the set of PM.us `hypothesis_id`s. If any frozen id is absent, the snapshot refuses.
- **W9. Add `may_take_look_k(record, *, pm_snapshot, constants) -> bool`.**
  - It returns False on any breach.
  - WB-4 triage calls it before every look, and nightly triage alerts on any breach (F1(5): Kalshi always yields).
- **W10. Parity can reach REGISTERED (amends the §10 "no monkeypatch" rule).** With both flags False, PM.us cannot return REGISTERED, so parity would never compare allocations. Allowed, and nothing else:
  - exactly `monkeypatch.setattr(<pm module>, "HORIZON_TOLLING_LANDED" | "PATH_B_SOURCE_GATE_LANDED", True)`, on the PM.us side only;
  - a K-side `PM_MIRROR_LANDED` constant with both K flags True, injected explicitly.

  A grep test permits only those two setattr targets and refuses any patch of a K symbol. At least one REGISTERED vector, and one re-arm-gating REGISTERED vector, must compare allocated, per_variant, mde and status.
- **W11. Parity vectors.**
  - Each vector's class maps to exactly one bound.
  - Vectors that hit the one-look-taking-per-class rule, or a class-bound conflict, are listed as `DIVERGENT_BY_DESIGN`, with a reason, in the error-mapping table.
- **W12. Check order (coordinator ruling).** The θ_K check moves **after** the input pins, matching PM.us (`:1070-1099` come before `:1100`). The §9 order becomes:
  1. duplicate id
  2. override
  3. not-frozen (W5)
  4. combined breach
  5. input pins
  6. R4 (W6)
  7. θ_K
  8. slot
  9. allocation
  10. power
  11. tolling and Path-B
- **W13. The pin's failure message states the change rule.** It says: edit this one line in the same reviewed commit as the PM.us edit, citing the ruling. Known future trips are RA-9f and the PATH-B flag flip.
- **W14. New RED tests.**
  - R25: two stations on one date count as n = 1, and the triage draw builder gives one observation per date.
  - R26: a missing K ledger reads as empty.
  - R27: a truncated or empty PM.us ledger refuses.
  - R28: a breach produces no look row and raises an alert.
  - R29: `break_even_k` on an exact-cent raw value (θ 0.08, a 0.5 gives fee 0.02 with no bump), and raw = 0 at a ∈ {0, 1}.
  - R30: with `re_arm_alpha ≤ 0`, a re-arm request is zero-look and `may_gate_re_arm_k` returns False.
  - R31 (WB-7b freeze commit): the `K_CONSTANTS` budget values equal the Kalshi PREREG values.
