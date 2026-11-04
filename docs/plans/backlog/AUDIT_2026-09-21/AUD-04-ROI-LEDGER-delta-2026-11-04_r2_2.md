# AUD-04 ROI-LEDGER delta r2.2 (2026-11-04) — supersedes r2.1 (`AUD-04-ROI-LEDGER-delta-2026-11-01_r2.md`); status: DRAFT, peer review pending

Applies on top of `AUD-04-portfolio-roi-measurement.md` + `AUD-04-AMENDMENT-2026-09-21.md`. r2.1 was APPROVED but a drift check at HEAD `0bbddc14` found it not implementable. Every finding below was re-verified by this author against source at that HEAD (codegraph + direct read), not taken from the drift note.

GOAL STATE (L-3): `read_roi_for_decision(path, now)` exists in `src/breezy/` and returns a `RoiDecisionView` only for a fresh, ungated, schema-6 report written by the production writer, and a typed refusal otherwise. #5 SIZE-UNDER-CAPS and #7 AUTO-PROMOTE-RETIRE can import it from the live or offline path. WALK: timer 17:40Z → `_run` computes freshness and decision stats → writes v6 JSON (atomic, 0600) → consumer calls the accessor → gates → view or refusal.

## 0 Drift findings, verified

| # | Finding | Verified at HEAD | Resolution in this delta |
|---|---|---|---|
| D1 | v5 JSON has no `generated_at`, so the r2.1 age gate can never pass on v5 | `_portfolio_roi_json_dict` `portfolio_roi_report.py:2783-2876` has no time-of-generation key; there is no `generated_at` anywhere in the file | v6 adds an aware-UTC `generated_at`. The accessor accepts schema 6 ONLY; v5 is refused with `SCHEMA_VERSION` |
| D2 | "D8 status OK" is not in the JSON | `days_since_newest_input(...)` is called at `:4689-4693`, after `write_portfolio_roi_json` at `:4676`; its value reaches only the latch via `apply_freshness_ladder` (`:4696-4699`, file `.input_freshness.json` `:3533`) | v6 emits `days_since_newest_input` and `input_freshness_status`. The pure computation (`:4687-4693`) moves above `build_portfolio_roi_report_data` (`:4632`); the latch read/ladder/write stay where they are |
| D3 | An import-linter contract cannot enforce r2.1 A3 | Confirmed: `scripts/` is not a package (the contracts' `root_packages = ["breezy", "nautilus_trader"]`, `pyproject.toml:71`), forbidden contracts name modules, and import-linter refuses an absent source module (`pyproject.toml:188-191,249-251`). No sizing or retire module exists | §1 D3: the accessor moves to `breezy.persistence.portfolio_roi_decision`, with one new forbidden contract whose source is that real module. Consumer-side contracts are deferred to #5/#7 |
| D4 [HIGH] | r2.1 A3/A5 feed decisions from `family_pnl`, which E-TE1-a forbids | `accounting.py:9-11`: "no verdict, tally or ROI-for-decision is built from these sums (E-TE1-a narrows AUT-2 D3 to statistics). Only `scripts/analysis/portfolio_roi_report.py` may import this module". The AST guard is `tests/support/te1_accounting_guard.py` (TARGET `:25`), run by `test_only_the_report_references_the_accounting_module` (`tests/unit/test_te1_accounting.py:294-311`, `_ALLOWED` = report + accounting.py). Ruled in TE-1 plan R1 (`docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/TE-1_plan_r3_3.md:101`, filed `:385`), first in r2 `:75` in response to arch A1 (`TE-1_plan_r2.md:13`). It landed in `42802b47` (WP-B). Mirror docstring: `label_store.admissible_rows` `src/breezy/persistence/autonomy/label_store.py:410-417`. **Why:** the accounting set (`accounting_rows`) is deliberately WIDER than the statistics set (it includes pre-epoch UNATTRIBUTED rows), so any decision built from it reads rows the statistics selector excludes | §1 D4: Option B, a decision view built from admissible statistics. No erratum is filed; the TE-1 guard and docstring are unchanged |
| D5 | Balance `observed_at` is not emitted | `BalancePoint(ts_iso, account_id, total_usd)` exists (`:900-906`) and feeds only `daily_balances`/`balance_timestamps_ns` (`:4431-4442`); no balance key in the JSON | §1 D5: v6 emits no balance; `available_capital` is always `None` |
| D6 | Exact `== 5` pins; the study reads through `read_portfolio_roi_report` | `tests/unit/test_portfolio_roi_report.py:290,430,2241,2302,4486,5236,5258,5982,5983({1,2,3,4,5}),5994,5995`; `tests/unit/test_te1_accounting.py:882,1332,1334`; the study imports the reader at `current_rung_hold_exit_window_study.py:103-104` and calls it at `:1383`; its fixture stamps `prr.PORTFOLIO_ROI_SCHEMA_VERSION` (`tests/unit/test_current_rung_hold_exit_window_study.py:639`) | §3: values move 5→6 and the known set widens to {1..6} (L-12). Comparisons stay `==`; the reader still refuses unknown versions |
| D7 | Line citations | `assert_ledger_partition` is at **:391** (r2.1 said :385, wrong). `leg_of_symbol` is DEFINED at **`src/breezy/domain/instrument_leg.py:58`**; r2.1's `accounting.py:619` is a call site. **n_\* correction refined:** the JSON keys are `n_fills :2788`, `n_scored :2789`, `n_residual :2790`, `n_unreconciled :2791`, so r2.1's :2789/:2790/:2791 were correct and the drift note's ":2788-2790" is off by one. Re-confirmed: `PORTFOLIO_ROI_SCHEMA_VERSION :2129`, `_KNOWN_... :2139`, reader `:3068`, `FamilyPnlRow accounting.py:320`, `family_pnl :703`, `Disclosures.n_labels_gated :368` (set `:766`) | Cited correctly throughout this delta |
| D8 | `RoiDecisionView` fields unspecified; `asdict` trips a credential contract | `tests/unit/test_polymarket_us_credential_serialization.py:19-26`; banned helpers precedent `tests/unit/test_autonomy_envelope.py:651` | §1 D8 gives exact fields; an AST test forbids `asdict`/`astuple` in the module |

## 1 Trade-offs and choices

### D3 — where the accessor lives and what enforces it
| Option | For | Against |
|---|---|---|
| (a) pure module in `src/breezy/` with a contract on that real module | A target exists today, so `lint-imports` actually checks it. Importable by both the live path (#5 sizes live under the 2026-11-02 ruling) and offline (#7) | One new module |
| (b) leave it in the script and defer all enforcement | Zero new modules | The live path cannot import `scripts/`; #5 would be blocked or would reimplement the reader (parallel architecture) |
| (a) inside `breezy.analysis` | Next to the accounting code | **Disqualified:** contract "The live trading path never imports the offline analysis layer" (`pyproject.toml:152-160`) bars every live layer from `breezy.analysis` |

**CHOICE: (a) at `breezy.persistence.portfolio_roi_decision`** (layer `persistence | registry | normalize`, `pyproject.toml:97`). `persistence` already hosts readers of report-side artefacts (`external_capital_flows.py`, whose docstring at `:1-12` sets the same cross-layer vocabulary-copy precedent). The layers contract only lets it import `settlement`/`domain`; it needs neither, only the stdlib. It is a source module of the live-path contract (`:156-158`), so **it can never import `breezy.analysis.labeling.accounting`**: the contract that already exists blocks the E-TE1-a breach structurally.
**Enforcement with a real target:** a new forbidden contract, named outside the `ARCH-0 autonomy (` prefix so `tests/unit/test_autonomy_contracts.py:69` (`len == 3`) is untouched:
```toml
[[tool.importlinter.contracts]]
name = "AUD-04 ROI decision accessor is stdlib-only"
type = "forbidden"
source_modules = ["breezy.persistence.portfolio_roi_decision"]
forbidden_modules = ["nautilus_trader", "pyarrow", "breezy.analysis", "breezy.adapters", "breezy.runtime", "breezy.strategy", "breezy.app"]
allow_indirect_imports = false
```
**Deferred (YAGNI, no module to name):** a contract forbidding sizing/retire modules from importing anything but the accessor. #5/#7 append their own module to a contract when they create it. Until then two existing guards already cover the dangerous half: the TE-1 AST guard (no `src/`/`scripts/` module but the report may reference `accounting`), and the live-path contract.

### D4 — E-TE1-a versus decision inputs
| Option | For | Against |
|---|---|---|
| A. Narrow erratum: `family_pnl` sums are admissible for decisions iff `n_unreconciled == 0`, `n_fee_unverified == 0`, `n_labels_gated == 0` | Reuses an existing table; no new rows | (1) Reopens a ruled boundary: the accounting set includes pre-epoch UNATTRIBUTED rows the statistics selector excludes (`label_store.py:414-416`), and the erratum would have to argue they are zero. (2) The guard must WIDEN `_ALLOWED` with a consumer that does not exist yet. (3) **Decisive:** every live FQ fill sits in the UNRECONCILED bucket until C2 labels feed it (`portfolio_roi_report.py:2159-2162`), so `n_unreconciled == 0` is never true for the live family and the view would be permanently refused. Dropping that condition puts back exactly the wider set E-TE1-a excludes |
| B. Decision view from admissible statistics | Built from the selectors the `roi` statistic already uses: `admissible_scored_trials` (legacy, `persistence/realized_draws.py`, imported `:137`) and `_LabelView.c2_rows()` (`row.admissible`, entry, non-legacy; `:4218-4224`). No accounting import. TE-1 guard untouched | One new row type plus one pure function; per-family figures differ from `family_pnl` (disclosed) |

**CHOICE: B.** No erratum. The TE-1 guard, its `_ALLOWED` set and the `accounting.py` docstring stay byte-unchanged; none needs widening. The accessor reads three `disclosures` COUNTS (`n_fee_unverified`, `n_labels_gated`, `n_settlement_disagree`) only to REFUSE. It never builds a figure from them and never reads a sum, so no verdict, tally or ROI-for-decision is built from accounting (a clarification, not an erratum). Wilson inputs are the admissible `n_admissible`/`n_wins` (the PREREG n, not the portfolio set), which closes r2.1 A5's open "statement of which n".

### D5 — available capital
| Option | For | Against |
|---|---|---|
| Emit the latest `BalancePoint` with `observed_at`; `available_capital` = balance if ≤ 24 h old | #5 gets a non-None bankroll | (1) Whether `currentBalance` includes position value is UNVERIFIED (`AUD-04-portfolio-roi-measurement.md:801-804`), so it may overstate spendable cash. (2) The account is shared with manual trading (ruling 10-29: the bot ignores foreign positions), so balance ≠ bot capital. (3) Once-per-boot proxy, lagged ≤ 1 day. (4) L-1: Nautilus natively holds live free balance, `Account.balance_free` (`nautilus_trader/accounting/accounts/base.pyx:262`, 1.231.0) — NATIVE EXISTS. A lagged log-line copy in an offline file would be a second, worse source |
| `available_capital` always `None` in v6 | Fail-closed; no semantic claim made; #5's rule "`available_capital is None` → zero" (`size_under_caps/plan_r1.md:77`) applies | #5 proposes zero until it sources capital itself |

**CHOICE: always `None`.** The field stays in the view because #5's code names it. A test pins it `None` on every v6 view. Populating it is a later additive version, after #5 rules between `Account.balance_free` (native, preferred per L-1) and a verified ledger figure. That is a #5 decision, recorded as an open unknown.

### D1/D2 — fail-closed version and freshness
The accessor accepts `{6}` only. A v5 report cannot satisfy the age gate, so accepting it with `None` fields (r2.1) would be refusal by other means. A schema refusal is explicit.

### Typed refusal
#5 r3 asks for "typed refusal otherwise" (`size_under_caps/plan_r3_delta.md:10`), so the accessor returns `RoiDecisionView | RoiDecisionRefusal`, never `None`. Consumers branch on `isinstance(result, RoiDecisionView)`; the refusal carries a reason enum only (dimensionless, no amounts).

### D8 — exact types (all `@dataclass(frozen=True, slots=True, kw_only=True)`; no `dataclasses.asdict`/`astuple` anywhere in the module)
```python
class FamilyDecisionStats:            # one row of v6 `family_decision_stats`; writer AND reader type
    family_id: str
    n_admissible: int                 # settled admissible rows counted (legacy admissible + complete C2)
    n_wins: int                       # legacy ScoredTrial.held / C2 LabelRow.settled_outcome is True
    net_pnl: Decimal                  # USD after fees, sum over the same rows
    n_incomplete: int                 # admissible C2 rows with settled_outcome or realized_pnl None (not in n/wins/net)
    def to_json(self) -> dict[str, object]: ...            # explicit dict; net_pnl as str
    @classmethod
    def from_json(cls, raw: Mapping[str, object]) -> FamilyDecisionStats: ...  # strict; raises _Malformed

class RoiDecisionView:
    schema_version: int                       # always 6 today
    generated_at: datetime                    # aware, normalised to UTC
    settled_through: str                      # ISO day, the report's settlement cutoff (existing key)
    source_sha256: str                        # sha256 hex of the exact bytes parsed (provenance pin for #5/#7 evidence)
    family_stats: tuple[FamilyDecisionStats, ...]   # sorted by family_id; every n_incomplete == 0
    available_capital: Decimal | None         # ALWAYS None in schema 6 (D5)

class RoiDecisionRefusalReason(StrEnum):
    UNREADABLE, MALFORMED, SCHEMA_VERSION, GENERATED_AT_INVALID, REPORT_STALE, REPORT_FROM_FUTURE,
    ROI_STATUS, INPUT_FRESHNESS, FEE_UNVERIFIED, LABELS_GATED, SETTLEMENT_DISAGREE,
    FAMILY_INCOMPLETE, FAMILY_UNKNOWN

class RoiDecisionRefusal:
    reason: RoiDecisionRefusalReason

DECISION_SCHEMA_VERSIONS: Final[frozenset[int]] = frozenset({6})
MAX_DECISION_REPORT_AGE: Final[timedelta] = timedelta(hours=24)
INPUT_FRESHNESS_OK: Final[str] = "OK"
INPUT_FRESHNESS_STALE: Final[str] = "STALE"
def read_roi_for_decision(path: Path, now: datetime) -> RoiDecisionView | RoiDecisionRefusal
```
Gate order (first failure wins). File unreadable or not a JSON object → `UNREADABLE`. `schema_version` (int, not bool) ∉ {6} → `SCHEMA_VERSION`. `generated_at` missing, non-str, unparseable by `datetime.fromisoformat`, or naive → `GENERATED_AT_INVALID`. `generated_at > now` → `REPORT_FROM_FUTURE`. `now - generated_at > 24 h` → `REPORT_STALE` (exactly 24 h is accepted). `roi_status != "OK"` → `ROI_STATUS`. `input_freshness_status != "OK"` → `INPUT_FRESHNESS`. `disclosures` null or missing, or any of the three counts not an int → `MALFORMED`; `n_fee_unverified != 0` → `FEE_UNVERIFIED`; `n_labels_gated != 0` → `LABELS_GATED`; `n_settlement_disagree != 0` → `SETTLEMENT_DISAGREE`. Rows malformed (negative, bool-as-int, `n_wins > n_admissible`, non-finite or non-decimal `net_pnl`, duplicate `family_id`) → `MALFORMED`; any `n_incomplete != 0` → `FAMILY_INCOMPLETE`; any `family_id == "UNKNOWN"` → `FAMILY_UNKNOWN`. A naive `now` raises `ValueError` (a caller bug, never a data refusal). The function never makes a network call; it reads the file once.

Two literals are copied across the layer boundary, following the `external_capital_flows.py:7-12` precedent: `"OK"` (= `ROI_STATUS_OK` `:2142`) and `"UNKNOWN"` (= `UNKNOWN_TRIAL_FAMILY_LABEL` `:778`). Tests pin both equal to the script's constants.

### Dropped from r2.1 (no consumer)
| r2.1 item | Why dropped |
|---|---|
| Accept schema 5 with `None` fields | D1: v5 can never pass the age gate; refusing it is explicit |
| Per-family `n_scored`/`n_residual`/`n_unreconciled` | Replaced by `n_admissible`, the n decisions use. The report-level partition stays (`:2789-2791`) |
| Per-family open exposure (D9 anti-join) | #5 R4-3 keeps committed position cost in the exec client under its lock (`size_under_caps/plan_r4_delta.md` R4-3). A daily offline copy would be a second, staler source. The report-level `roi_status` already refuses on `GATED_UNSETTLED_CAPITAL` |
| `breakeven_p` per family and leg | #5 computes exact final-q break-even from `fee_total(q)` (R3, R4-4); #7 r1 deleted the Wilson-LB-vs-mean(BE) retire rule (`auto_promote_retire/plan_r1.md:10,86`) |
| Per-leg YES/NO rows | No consumer. L-44 is met by tests that a NO-leg win and a NO-leg loss count correctly. Leg comes only from the scorer's `held` (`trial_scorer.py:207-209`, via `leg_of_symbol`) and the label's `settled_outcome`; this delta adds no leg derivation |
| `available_capital` from balance | D5 |
| A4 θ-per-fill counts | No consumer; fee quality is gated by `n_fee_unverified` in the accessor |
| Sizing/retire import contract | D3: no module to name |

## 2 Acceptance Criteria (numbered, testable)
1. `PORTFOLIO_ROI_SCHEMA_VERSION == 6` and `_KNOWN_PORTFOLIO_ROI_SCHEMA_VERSIONS == frozenset({1, 2, 3, 4, 5, 6})`. `read_portfolio_roi_report` reads v1..v6 and raises `UnknownPortfolioRoiSchemaError` on 7 and 999.
2. A v6 JSON carries `generated_at == datetime.fromtimestamp(now_ns // 1_000_000_000, tz=UTC).isoformat()` (ends `+00:00`), stamped from the run's injected `now_ns`, never from a second clock read.
3. A v6 JSON carries `days_since_newest_input` (int or null) and `input_freshness_status` (`"OK"` iff `is_input_fresh(days)`, else `"STALE"`; null days → `"STALE"`). The value is computed ONCE before the write, and the same variable feeds `apply_freshness_ladder`. Ladder and latch behaviour are unchanged: existing ladder tests pass unmodified.
4. A v6 JSON carries `family_decision_stats`, built from `admissible_scored_trials(scored_trials, residual_trial_ids=residual_ids)` plus `labels.c2_rows()` only. Residual settlements and non-admissible rows are absent. For complete inputs, Σ `net_pnl` == `total_realised_pnl_admissible(scored_trials, residual_trial_ids=residual_ids) + c2_pnl`. Unit: USD in both, the same unit as the `roi` numerator terms (`:4396`, `:852`) (L-2).
5. Additive only: every v5 key is still emitted with an identical value for identical inputs. The study (`current_rung_hold_exit_window_study.py`) reads a v6 report unchanged.
6. `read_roi_for_decision` returns a `RoiDecisionView` for a v6 report written by `write_portfolio_roi_json` (production writer, L-24) when all gates pass, and the matching `RoiDecisionRefusal` reason for each gate in §1 D8, each tested on its own.
7. A v5 report written by the production writer → `SCHEMA_VERSION`.
8. `available_capital is None` on every view; the view's fields are exactly those in §1 D8, pinned by `dataclasses.fields` names (`fields()`, not `asdict`).
9. An AST scan of `portfolio_roi_decision.py` finds no `asdict`/`astuple` name or attribute and no import outside the stdlib plus `__future__`.
10. `lint-imports` passes with the new contract. RED proof: in a scratch worktree, planting `import nautilus_trader` in the module makes `lint-imports` exit non-zero naming the contract. Revert, then record both outputs.
11. `tests/support/te1_accounting_guard.py`, `_ALLOWED` in `test_te1_accounting.py` and the `accounting.py` docstring are byte-unchanged (`git diff --stat` shows none). `test_only_the_report_references_the_accounting_module` passes with the new module present.
12. Every changed pin keeps `==`. No pin set loses a member, and no `skip`/`xfail` is added.
13. New test files are classified in `scripts/ci/gate_reviewed.json` and have a measured entry in `scripts/ci/gate_durations.json["files"]`.
14. The full gate `scripts/ci/run_tests_no_egress.sh` exits 0 (EXIT CODE read, not the tail). `ruff`, `mypy` (strict; `scripts/analysis` and `src/breezy/persistence` are in scope) and `lint-imports` pass after each slice.
15. Read-only A1 (after the first 17:40Z v6 run): the latest `PRIVATE_portfolio_roi_<day>.json` has `schema_version == 6` and the four new keys. Record `roi_status`, `input_freshness_status`, the count of `family_decision_stats` rows, the count of `UNKNOWN` rows, `n_fee_unverified`, `n_labels_gated`, `n_settlement_disagree`, and the accessor's result TYPE plus refusal reason. Counts and names only, never an amount.
16. Read-only A2: `systemctl --user` shows `breezy-portfolio-roi.timer` active (waiting) with its last run < 24 h; `n_labels_gated > 0` is a WARNING, not a pass.
17. Read-only A6: the Markdown still labels the I4 balance series as a once-per-boot, lagged ≤ 1 day proxy (cash or cash+positions UNVERIFIED), and AC 8 holds on the live report.

## 3 File-by-File Plan
| Path | New/Mod | Exact change |
|---|---|---|
| `src/breezy/persistence/portfolio_roi_decision.py` | NEW | Module docstring: purpose, the E-TE1-a clarification (§1 D4), the vocabulary-copy note, no I/O except the one file read. Contents exactly §1 D8: `FamilyDecisionStats` (+`to_json`/`from_json`), `RoiDecisionView`, `RoiDecisionRefusalReason`, `RoiDecisionRefusal`, the four constants, private `_ROI_STATUS_OK = "OK"`, `_UNKNOWN_FAMILY = "UNKNOWN"`, `read_roi_for_decision`. Stdlib only (`json`, `hashlib`, `datetime`, `decimal`, `dataclasses`, `enum`, `pathlib`, `typing`, `collections.abc`). Helpers are each under 50 lines |
| `scripts/analysis/portfolio_roi_report.py` | MOD | (1) `:2115-2129` comment and constant: v6 adds `generated_at`, `days_since_newest_input`, `input_freshness_status`, `family_decision_stats` (additive), so `= 6`. (2) `:2139` set `{1,2,3,4,5,6}`. (3) Reader docstring `:3081-3085`: "accepts 1..6". (4) `PortfolioRoiReportData` (`:2501`): add `generated_at_ns: int` (required, no default, L-17), `days_since_newest_input: int \| None`, `input_freshness_status: str`, `family_decision_stats: tuple[FamilyDecisionStats, ...]`. (5) `build_portfolio_roi_report_data` (`:2621`): add required `generated_at_ns: int` and `days_since_newest_input: int \| None = None`, `family_decision_stats: Sequence[FamilyDecisionStats] = ()`. Status derived inside the function as `INPUT_FRESHNESS_OK if is_input_fresh(days) else INPUT_FRESHNESS_STALE`, the one derivation. (6) `_portfolio_roi_json_dict` (`:2783`): four keys; `generated_at` = ISO of `generated_at_ns // 1e9` floored seconds, UTC; rows via `row.to_json()`. (7) NEW pure `family_decision_stats(*, admissible_trials, c2_rows, registered_manifests) -> tuple[FamilyDecisionStats, ...]`: legacy family from `_family_id_of_trial` (`:806`), win `trial.held`, net `trial.pnl`; C2 family `row.family_id`, complete iff `settled_outcome` and `realized_pnl` are both not None, else `n_incomplete += 1`; grouped, then built immutably, sorted. (8) `_run`: move `:4687-4693` to just before `:4632`; compute `family_decision_stats(...)` there from `admissible_scored_trials(scored_trials, residual_trial_ids=residual_ids)` and `c2_rows`; pass `generated_at_ns=now_ns`, `days_since_newest_input=freshness_days`, and the stats into the build call; `:4696` keeps using the same `freshness_days`. Import `FamilyDecisionStats`, `INPUT_FRESHNESS_OK`, `INPUT_FRESHNESS_STALE` from the new module. No change to the accounting call, Markdown, journal line, alerts or exit codes |
| `pyproject.toml` | MOD | Append the §1 D3 contract after the AUD-18 pair (`:200-209`). No other edit |
| `tests/unit/test_portfolio_roi_decision.py` | NEW | §4 |
| `tests/unit/test_portfolio_roi_report.py` | MOD | Pins `:290,430,2241,2302,4486,5236,5258,5982,5994,5995` `== 5` → `== 6`; `:5983` → `frozenset({1, 2, 3, 4, 5, 6})`; rename `test_schema_version_is_five_and_every_prior_version_stays_readable` → `..._is_six_...`. Its 4 `build_portfolio_roi_report_data(`/`PortfolioRoiReportData(` call sites pass `generated_at_ns`. Add §4 report tests |
| `tests/unit/test_te1_accounting.py` | MOD | `:882,1332,1334` `== 5` → `== 6`; rename `test_schema_v5_reader_accepts_1_to_5_and_rejects_v5_missing_keys` → `test_schema_reader_accepts_1_to_6_and_rejects_v5_plus_missing_keys` (body unchanged except the values); its 3 call sites pass `generated_at_ns`. The guard tests `:294-330` stay untouched |
| `scripts/ci/gate_reviewed.json` | MOD | Add `tests/unit/test_portfolio_roi_decision.py` to the group `scripts/ci/gate_classify.py` assigns from its flagged tokens. Expected: the "deadline/timeout_s/clock tokens are domain parameters … injected-clock values" group (every `now` is injected). Never invent a new reason |
| `scripts/ci/gate_durations.json` | MOD | `files["tests/unit/test_portfolio_roi_decision.py"]` = measured duration from one host run |
| `docs/core/PROGRESS.md`; r2.1 header | MOD at close | Coordinator only: row #4 points at r2.2; r2.1 header gets "SUPERSEDED by r2.2". Not part of the build |

Not touched: `accounting.py`, `te1_accounting_guard.py`, `label_store.py`, `operator_controls.py`, any `deploy/` unit, `current_rung_hold_exit_window_study.py` and its tests (expected green unchanged; verified in S1), any evidence artefact (L-75).

## 4 Test Strategy
`tests/unit/test_portfolio_roi_decision.py` (NEW, 22 tests). Every report is created by `write_portfolio_roi_json` from `PortfolioRoiReportData` built via `build_portfolio_roi_report_data`, never hand-written (L-24). The exception is the malformed-input tests, which mutate the production writer's output with `json` round-trip edits to plant one defect each.
1. `test_a_fresh_ungated_v6_report_yields_a_decision_view`
2. `test_v5_report_is_refused_with_schema_version` (writer monkeypatched to stamp 5, keys as v5)
3. `test_unknown_or_non_int_schema_version_is_refused` (param: 7, 999, missing, `true`)
4. `test_missing_unparseable_or_naive_generated_at_is_refused` (param: 3 cases)
5. `test_report_older_than_24h_is_refused_and_exactly_24h_is_accepted`
6. `test_report_from_the_future_is_refused`
7. `test_naive_now_raises_value_error`
8. `test_each_non_ok_roi_status_is_refused` (param over `GATED_IDENTITY`, `GATED_UNSETTLED_CAPITAL`, `GATED_ACCOUNTING_ONLY`, `GATED_UNLABELLED_FQ`)
9. `test_stale_or_missing_input_freshness_is_refused`
10. `test_fee_unverified_fill_refuses`
11. `test_labels_gated_fill_refuses`
12. `test_settlement_disagreement_refuses`
13. `test_null_or_missing_disclosures_is_malformed`
14. `test_incomplete_c2_row_refuses_with_family_incomplete`
15. `test_unknown_family_row_refuses_with_family_unknown`
16. `test_malformed_family_rows_are_refused` (param: negative n, bool n, wins > n, `"NaN"` net, duplicate family_id)
17. `test_missing_file_non_json_or_non_object_is_unreadable`
18. `test_available_capital_is_none_on_every_v6_view`
19. `test_source_sha256_is_the_hash_of_the_bytes_read`
20. `test_view_fields_are_exactly_the_specified_set` (`dataclasses.fields` names; frozen: assignment raises)
21. `test_module_has_no_asdict_and_imports_only_stdlib` (AST; plus a planted-source positive control proving the scanner flags `asdict` and `import nautilus_trader`; per L-80 a planted `"as" + "dict"` getattr is also flagged)
22. `test_copied_literals_equal_the_report_constants` (`"OK"` == `prr.ROI_STATUS_OK`; `"UNKNOWN"` == `prr.UNKNOWN_TRIAL_FAMILY_LABEL`; the three disclosure keys ⊂ `accounting.Disclosures().to_json()`. A test may import accounting because the guard scans `src/` and `scripts/` only)

`tests/unit/test_portfolio_roi_report.py` (MOD, 7 new tests):
- `test_v6_json_carries_utc_generated_at_from_now_ns`
- `test_v6_json_carries_input_freshness_computed_before_the_write` (no input → null/STALE; fresh → int/OK; 4 days → STALE)
- `test_json_freshness_and_the_ladder_see_the_same_days_value` (drive `_run`, read JSON and latch)
- `test_family_decision_stats_use_admissible_legacy_and_c2_rows_only` (a residual trial and a non-admissible C2 row are absent)
- `test_family_decision_stats_sum_to_the_admissible_numerator`
- `test_family_decision_stats_count_yes_and_no_leg_wins_and_losses` (L-44: one `^no` fixture held=True counts a win, one `^no` held=False does not; both YES cases too)
- `test_c2_row_without_outcome_counts_incomplete_not_n`

Failure paths covered: every refusal reason (1 test or parametrisation each), malformed and unreadable input, caller-bug `ValueError`, version refusal on both readers, contract RED (AC 10), guard positive controls (21). Run focused tests, then the touched-file suites, then the full gate through `scripts/ci/run_tests_no_egress.sh`, with basetemp in the worktree (memory: tmpfs fills RAM) and the EXIT CODE read.

## 5 Execution Order (slices; each RED → GREEN, then `ruff`, `mypy`, `lint-imports`, focused tests, commit by explicit path)
- **S0 (read-only, ≤ 15 min):** re-verify every line cited in §0 and §3 at the build HEAD; any drift is fixed in this delta first (L-4).
- **S1 writer v6.** Create the new module with `FamilyDecisionStats` and the two status constants only. RED: the 7 new report tests plus the bumped pins fail at v5. GREEN: the report changes in §3. Run the study suite and `test_te1_accounting.py` unmodified except pins.
- **S2 accessor.** RED: the 22 accessor tests fail (symbol absent). GREEN: `read_roi_for_decision` and the types. Add the contract; record the AC 10 RED proof.
- **S3 integrate.** Classify the new test file and measure its duration, then run the full no-egress gate on the integration branch `feat/data-capture-and-risk` after the merge (L-43). Push only after reading the gate EXIT. Implementer route per `CLAUDE.md` (grok, then Codex, then Claude sub-agents) with the invariants in the brief; the host gates and commits (L-79).
- **S4 (read-only, after the next 17:40Z run):** AC 15–17. Close #4 when AC 1–14 are green and A1/A2 hold on the first v6 report. A refusal on the live report does NOT block closing #4 (fail-closed is the deliverable), but its reason is recorded for #5/#7.

## 6 Risk Register
| Risk | Likelihood | Effect | Mitigation |
|---|---|---|---|
| Historical `n_fee_unverified` / `n_settlement_disagree` are non-zero. These counts cover ALL fills; TE-1 P18 says two fee-unreconciled fills exist (the residuals), so the view may be refused indefinitely | HIGH | #5/#7 get a permanent refusal (safe, but no consumption) | A1 records the live values. A narrowing of these gates to the admissible set is its own peer-reviewed delta; never relax inline |
| Legacy admissible trials resolve to `UNKNOWN` family | MED | `FAMILY_UNKNOWN` refusal | A1 counts them; any fix goes in family binding, never in the gate |
| Age gate flaps around 24 h: one daily run, stamped at the run's `now_ns` | MED | Minutes of `REPORT_STALE` near 17:40Z; a failed run refuses after 24 h | Intended fail-closed; consumers treat a refusal as zero/no-act; `OnFailure=` alerts a failed run |
| Readers mistake `family_decision_stats` for `family_pnl` | MED | A "mismatch" gets hand-reconciled | Docstrings state the two sets; the accessor exposes only the admissible view |
| Data-class field addition breaks hidden constructors | LOW | RED in unrelated suites | Only 7 call sites (grep at HEAD); S1 runs the touched suites |
| The study regresses on v6 | LOW | AUD-07 cross-check breaks | It reads only pre-existing keys; its suite is in S1's focused run |
| Reviewers read the disclosure-count gates as an E-TE1-a breach | LOW | Plan bounce | §1 D4 clarification: counts refuse only; no sum is read or built |
| A contract cannot be checked without the module | n/a | — | The module ships in S1 before the contract lands in S2 |

## 7 LESSONS Compliance (headers grepped at HEAD, `docs/core/LESSONS.md`)
- **L-1 (:8):** file-report accessor = GENUINE GAP: Nautilus has no reader for a Breezy report file. Live free balance = NATIVE EXISTS (`base.pyx:262` `balance_free`), DECLINED here because its consumer is #5 and the semantics are unresolved (D5).
- **L-4 (:26):** every changed fact (version, known set, line citations) is swept across the §0 sites; S0 re-sweeps.
- **L-12 (:56):** pins are widened or moved 5→6 with `==` kept; the TE-1 `_ALLOWED` set is not widened because D4-B needs no widening; the new contract is added, none relaxed.
- **L-17 (:80):** `generated_at` is REQUIRED from v6. v5 lacks it by lifecycle, so v5 is refused, never defaulted to mtime or now.
- **L-22 (:98):** the refusal is the accessor's only non-view return. There is no flag a caller can pass to skip a gate, and no partial view exists.
- **L-43 (:194):** full gate on the integration branch after every merge.
- **L-44 (:200):** NO-leg win/loss fixtures in the stats test; leg comes only via `leg_of_symbol` through the scorer.
- **L-51 (:224):** worktree uses `/home/jon/breezy/.venv/bin/python` with `PYTHONPATH=<wt>/src`; no installer; no `git stash`.
- **L-75 (:308):** no evidence artefact is edited; v6 fields come only from the writer.
- **L-79 (:326):** an external implementer authors; the host gates, produces RED/GREEN and commits.
- **L-80 (:332):** the AST guard (test 21) rejects reconstructed `asdict`; a guard trip is fixed by renaming, never by hiding.

## 8 Invariants (binding on every implementer brief)
- Nautilus Trader is immutable: no modify, patch, fork or bypass. `Account.balance_free` is cited, not wrapped here.
- `allow_short` stays `False`; nothing here touches order or position code.
- Leg sign comes only via `leg_of_symbol` (`src/breezy/domain/instrument_leg.py:58`); this delta adds no leg derivation.
- NO-SEND egress firewall: the report and the accessor make no network calls. The accessor is stdlib-only (contract plus AST test). All tests run via `scripts/ci/run_tests_no_egress.sh`.
- Operator caps (day, position, month): never assigned, defaulted, proposed or read here, and their environment variables are never named. Live-trading enablement is untouched.
- Never weaken or delete a safety, settlement, contract or pin test: the TE-1 guard is byte-unchanged and every pin keeps `==`.
- New test files are classified in `gate_reviewed.json` and timed in `gate_durations.json`.
- Run `lint-imports` after every slice; `python -m importlinter` is a no-op (memory).
- Report files are never hand-edited (L-75); private money figures never enter git or alerts.

## 9 Confidence
0.80 overall. Code facts: 0.95 (all re-read at `0bbddc14`). D4-B soundness: 0.85 (selectors reused verbatim; residual exclusion matches `total_realised_pnl_admissible`). Usefulness to consumers on day one: 0.5, because of the HIGH risk above. **Open unknowns:**
1. Live values of `n_fee_unverified`/`n_settlement_disagree`/`UNKNOWN` rows, which decide whether the first view is a refusal (A1).
2. Whether any admissible C2 row is ever incomplete (the `n_incomplete` guard covers either answer).
3. #5 must re-source spendable capital (`balance_free` versus a verified ledger figure) and update `plan_r1.md:77-78` / `plan_r3_delta.md:46` for the typed refusal. That is a cross-item note for #5's owner, not this build.
4. `gate_classify.py`'s exact group for the new file (decided by running it).
