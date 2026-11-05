# AUD-04 ROI-LEDGER delta r2.3 (2026-11-04): supersedes r2.2 where they conflict. Status: DRAFT, round-2 peer review pending

Applies on top of `docs/plans/backlog/AUDIT_2026-09-21/AUD-04-portfolio-roi-measurement.md`, `docs/plans/backlog/AUDIT_2026-09-21/AUD-04-AMENDMENT-2026-09-21.md` and `docs/plans/backlog/AUDIT_2026-09-21/AUD-04-ROI-LEDGER-delta-2026-11-04_r2_2.md`. Where r2.2 and this file conflict, this file wins. Every r2.2 section not mentioned below stands. This delta answers round-1 review: python-reviewer APPROVE with non-blocking notes; prediction-market-reviewer and architect REQUEST_CHANGES (items 1 to 8). The coordinator's rulings are applied.

Companion amendment deltas (written with this file):
- #5: `docs/plans/backlog/GAPS_2026-11-01/size_under_caps/plan_r5_delta.md`. Capital moves to native Nautilus.
- #7: `docs/plans/backlog/GAPS_2026-11-01/auto_promote_retire/plan_r6_delta.md`. Residual P&L basis.

## 0 Goal state (L-3), restated

**GOAL STATE:** `read_roi_for_decision(path, now)` returns a per-family **statistics** view (`RoiDecisionView`) from the production v6 report. It returns a typed report-level refusal only for:
- an unreadable or malformed report;
- schema;
- `generated_at` validity, future or age;
- label identity.

Inside a served view, each family is either served (`FamilyDecisionStats`) or refused on its own (`FamilyDecisionRefusal`). One family never blocks another.

**#4 owns no capital.** Spendable capital and open exposure belong to #5. #5 reads them natively:
- `Account.balance_free` (`nautilus_trader/accounting/accounts/base.pyx:262`);
- the exec client's R4-3 committed-cost ledger.

The details are in the #5 r5 delta.

**WALK:** timer 17:40Z → `_run` computes freshness, the label gate and per-family stats → writes v6 (atomic, 0600; the latch is written AFTER the report) → consumer → report-level gates → per-family gates → view.

**Reachability (AC 23):** the first live v6 report must give one of two outcomes:
- (i) a `RoiDecisionView` serving at least one non-`UNKNOWN` family; or
- (ii) a refusal whose reason is `LABELS_GATED`, with every other report-level gate shown passing from the JSON, and at least one non-`UNKNOWN` `family_decision_stats` row whose family gates pass.

Outcome (ii) is recorded as an external dependency on OPS-4. Any other refusal means #4 is NOT done.

## 1 S0 live measurement (coordinator-run, recorded; counts only)

| Report | Facts |
|---|---|
| `/home/jon/.local/share/breezy/derived/PRIVATE_portfolio_roi_2026-11-03.json` (v5) | `roi_status=GATED_IDENTITY` (`roi_accounting_status` the same) |
| | `n_fills=34`, `n_scored=7`, `n_residual=2`, `n_unreconciled=25` |
| | `disclosures`: `n_labels_gated=25`, `n_fee_unverified=2`, `n_settlement_disagree=0`, `n_cli_final_unavailable=0` |
| | `family_pnl` has 4 rows: `UNKNOWN` (25 fills), `pm_us_crh_cont` (5), `pm_us_crh_v2` (1), `pm_us_crh_v4` (3) |
| | `fill_pnl` by (family, source): `UNKNOWN`/NONE/LABELS_GATED 25; `pm_us_crh_cont`/LEGACY 4; `pm_us_crh_v4`/LEGACY 3; `pm_us_crh_cont`/RESIDUAL 1; `pm_us_crh_v2`/RESIDUAL 1 |
| | Both RESIDUAL rows are `fee_unverified=True`. Every LEGACY row is fee-verified and CLI `AGREE` |
| | The service exits 1 on CRITICAL `PORTFOLIO_ROI_LABEL_IDENTITY`. The JSON is still written before the exit (file mtime 17:41Z) |
| Today's report `PRIVATE_portfolio_roi_2026-11-04.json` | See §1a |
| Input-freshness latch `.../derived/portfolio_roi/.input_freshness.json` | `streak=8`, `last_alert_severity=WARN` |
| | The log shows `PORTFOLIO_ROI_INPUTS_FROZEN ... days_since_newest_input=27` on 11-02 |
| | The newest fill climate day in `fill_pnl` is 2026-10-06. Nothing has traded since then (trading has been disarmed since the 10-19 block audit), so `input_freshness_status` would be `STALE` today |

What the numbers mean under r2.2:
- r2.2 refuses on `INPUT_FRESHNESS` first, then on `FEE_UNVERIFIED` (the two residuals), then on `LABELS_GATED`, then on `FAMILY_UNKNOWN`.
- Four independent refusals, so #5 and #7 could never get a view.

Under r2.3, with labels clear:
- `pm_us_crh_cont` (n_a=4) and `pm_us_crh_v4` (n_a=3) are served;
- `pm_us_crh_v2` is served with n_a=0 and its residual block;
- `UNKNOWN` is refused at family level only.

### 1a Today (2026-11-04)
The 17:40Z run had not produced `PRIVATE_portfolio_roi_2026-11-04.json` when this was drafted (17:32Z). OPS-4 S3b (`40dec67b`) is meant to drive `n_labels_gated` to 0 at this run, and that is UNVERIFIED here. The S4 readout (AC 21) records today's `roi_status` and `n_labels_gated` from the file. The coordinator's return carries the value if it was read after 17:41Z.

### 1b Item 3 decision: close as "built + refusal attributable to OPS-4"
**Recommendation:** close #4 when AC 1 to 22 are green and AC 23 holds, including outcome (ii). Do not wait for OPS-4.

Reasoning:
1. Label identity is OPS-4's deliverable. Waiting couples two backlog items and proves nothing more about #4.
2. Refusing while labels are gated is the correct behaviour: a decision on a family whose fills are unlabelled could miss a loss.
3. AC 23(ii) still demands evidence. The only blocker must be label identity, and at least one real family must pass its own gates in the same JSON. That rules out "closed while refusing for a #4 defect".
4. #5 and #7 have other hard dependencies anyway (#11, S0 rulings), so #4 is not on their critical path once built.

Record in `docs/core/PROGRESS.md` (coordinator): "#4 DONE-WITH-EXTERNAL-DEPENDENCY: OPS-4 label identity".

## 2 Decisions on round-1 items

### Item 1: capital leaves #4 (coordinator option (b))
- `available_capital` is **removed** from `RoiDecisionView` (YAGNI: no consumer once #5 sources capital natively). This supersedes r2.2 §1 D5 and AC 8.
- #5 r5 sources spendable capital from `Account.balance_free(USD)`. The PM.us exec client fills it from venue `buyingPower`:
  - `parse_account_balances` (`src/breezy/adapters/polymarket_us/exec/reports.py:1015`) maps free to `buyingPower`;
  - `_publish_account_state` (`src/breezy/adapters/polymarket_us/exec/client.py:5648`) publishes it at connect (`:2739`) and on native `QueryAccount` (`_query_account` at `:5639`; `Strategy.query_account` at `nautilus_trader/trading/strategy.pyx:1492`).
- **R4-3 does hold committed cost.** `docs/plans/backlog/GAPS_2026-11-01/size_under_caps/plan_r4_delta.md:12` books `{(instrument_id, leg): Σ cumulative_cost}`, with no day filter and restart-safe, through `seed_position_committed(...)` under `self._lock`. So **#4 keeps NO per-family open-exposure count**. r2.2's drop of D9 stands, now with the right citation.
- The `docs/plans/backlog/GAPS_2026-11-01/size_under_caps/plan_r1.md:76` rule ("realised P&L, open cost basis and available capital come ONLY from the accessor") is superseded by the #5 r5 delta. #5 reads NO money field from the view. It uses the view only as a per-family data-quality precondition.

### Item 2: gate scope narrowed to the rows actually read
**Report-level refusals.** Only these refuse the whole view: `UNREADABLE`, `MALFORMED`, `SCHEMA_VERSION`, `GENERATED_AT_INVALID`, `REPORT_FROM_FUTURE`, `REPORT_STALE`, `LABELS_GATED`.

`LABELS_GATED` fires iff `label_gate_status ∈ {GATED_IDENTITY, GATED_UNLABELLED_FQ}` or `disclosures.n_labels_gated != 0`.

`label_gate_status` is a new v6 key. It holds the existing `label_status` variable (`scripts/analysis/portfolio_roi_report.py:4397-4403`: `labels.gate_status`, else `GATED_UNLABELLED_FQ`, else null). The key is needed because `roi_status` conflates two things:
- pending labels map to `GATED_UNSETTLED_CAPITAL` (`_gate_status_of` `:4234-4247`);
- identity failures map to `GATED_IDENTITY`.

**Family-level refusals.** These exclude only that family: `FAMILY_FEE_UNVERIFIED`, `FAMILY_SETTLEMENT_DISAGREE`, `FAMILY_INCOMPLETE`, `FAMILY_UNKNOWN`, `FAMILY_PARTITION`. `view.for_family(id)` returns `FamilyDecisionRefusal(NOT_IN_REPORT)` for an absent family.

**Disclosure only, never a refusal:**
- `roi_status` (incl. `GATED_UNSETTLED_CAPITAL`, `GATED_ACCOUNTING_ONLY`);
- the global `n_fee_unverified` and `n_settlement_disagree`.

All of these are carried on the view.

**Why this is NOT a safety relaxation.** A decision reads only that family's admissible rows. So:
- a fee or CLI defect on another family's row, or on a residual row, cannot change any figure the decision reads;
- unsettled capital is not in a settled-only statistic (it is #5's exposure, read natively);
- `GATED_ACCOUNTING_ONLY` means only that booked P&L sits outside the admissible set (`:2147-2149`), which is exactly the set the view never reads.

The gates are re-scoped to the rows read, and still fail closed on those rows:
- missing fee evidence counts as unverified;
- the CLI counts take a superset of the admissible rows;
- any partition mismatch refuses.

Label identity stays report-level because an unlabelled fill has no family. It could belong to a served family and hide a loss, so no family can be cleared while one exists.

**Per-family counts, over the same rows** (emitted per `family_decision_stats` row):

| Count | Source |
|---|---|
| `n_fee_unverified` (admissible) | Legacy rows: the non-accounting `fee_reconciled_by_trial_id_pooled` (`:4503-4507`, state DB); an absent entry is unverified (same default as `:735`). C2 rows: `LabelRow.fee_reconciled is None` |
| `n_settlement_disagree` (admissible) | Accounting `fill_rows` (`:4577`) with `cli_final_check == DISAGREE`, `source ∈ {LEGACY, C2}`, grouped by `family_id`. COUNT only. `FillPnlRow` has no trial_id, so this counts a SUPERSET of the admissible rows: never fewer refusals |
| `fees_total` | Σ legacy `ScoredTrial.fee` (`src/breezy/settlement/trial_scorer.py:154`; qty 1) + Σ C2 `fee_reconciled`, over the complete admissible rows |

**Fees are netted once.** `net_pnl` is NET of fees. Legacy `ScoredTrial.pnl = 1{held} − fill_px − fee` (`trial_scorer.py:206`). C2 `realized_pnl = qty*payoff − cumulative_cost − fee_reconciled` (`src/breezy/analysis/labeling/fq_scorer.py:7`). `fees_total` is disclosure only and is never subtracted (test R8).

**UNKNOWN never blocks.** An `UNKNOWN` row is always a family-level `FAMILY_UNKNOWN`.

**Global counts** stay in the view as disclosure (`global_n_fee_unverified`, `global_n_settlement_disagree`).

### Item 2a: input freshness becomes disclosure, not refusal (NEW, measured; a DEVIATION from the ruling, for round-2 ratification)
§1 shows `input_freshness_status` is STALE whenever nothing has traded for more than 3 days:
- `days_since_newest_input` is the age of the newest fill or scored trial (`:3547-3558`; threshold `:3531`);
- the live latch streak is 8.

As a report-level refusal it deadlocks the goal state:
1. no trade, so the view refuses;
2. so #5 sizes zero and #7 cannot qualify;
3. so no trade.

The integrity property it was standing in for (no unseen fills) is already enforced, and fails closed, by three things:
- `assert_ledger_partition` (`:391`). Every decoded fill sits in exactly one bucket, or no report is written, so the view refuses `UNREADABLE`/`REPORT_STALE`.
- The label marker's own `labels_consumable(..., now_ns)` freshness (`:4243`), which gives `LABELS_GATED`.
- The 26 h `generated_at` age, which proves a fresh read of the ledger.

What changes:
- The view carries `days_since_newest_input` and `input_freshness_status` as disclosure.
- The ladder, latch and `PORTFOLIO_ROI_INPUTS_FROZEN` alert are unchanged.

**Fallback if round 2 rejects this:** keep `INPUT_FRESHNESS` report-level, and widen AC 23(ii) to "LABELS_GATED or INPUT_FRESHNESS with newest fill day ≥ 3 days old". That records the deadlock as an open #5/#7 blocker. It is never a silent pass.

### Item 3: §1b, close with OPS-4 as a named external dependency

### Item 4: #7 residual P&L. Choose (b), a disclosed per-family residual block
Fields added to each `family_decision_stats` row:

| Field | Meaning |
|---|---|
| `n_residual` | Settled + pending residual fills |
| `n_residual_pending` | Pending residual fills |
| `residual_pnl` | Signed USD, Σ `ResidualSettlement.realised_pnl` over the family's settled residuals |
| `n_residual_fee_unverified` | Residual fills without fee evidence |
| `n_residual_settlement_disagree` | RESIDUAL `fill_rows` with `cli_final_check == DISAGREE` (count) |
| `n_fills_attributed` | Count of `fill_rows` with this `family_id` |
| `n_other_excluded` | `= n_fills_attributed − n_admissible − n_incomplete − n_residual`. A value below 0 means `FAMILY_PARTITION` |

On the 11-03 inputs: `pm_us_crh_cont` 5 = 4 + 0 + 1 + 0; `pm_us_crh_v4` 3 = 3 + 0 + 0 + 0; `pm_us_crh_v2` 1 = 0 + 0 + 1 + 0.

Residual flags NEVER refuse the family. They are disclosure, so #7 can apply its asymmetric rule (#7 r6): permissive actions need them at 0; restrictive actions may read flagged losses.

Why not option (a), admissible-only for #7:
- a LOSS_STOP that ignores real residual losses is anti-conservative;
- #7's binding `docs/plans/backlog/GAPS_2026-11-01/auto_promote_retire/plan_r1.md:81-94` (n_p partition, `total_pnl` incl. residual, portfolio LOSS_STOP) would be weakened.

**E-TE1-a reading.** The origin is `docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/TE-1_plan_r3_3.md:101`: "E-TE1-a narrows AUT-2 D3 to *statistics* … No verdict is built from accounting sums". Its guard is `src/breezy/analysis/labeling/accounting.py:9-11`. What it forbids is a verdict from the ACCOUNTING module's SUMS (`family_pnl` over `accounting_rows`, a wider set that includes pre-epoch UNATTRIBUTED rows).
- The residual block's money comes from `total_realised_pnl_residual` over `ResidualSettlement` (`scripts/analysis/portfolio_roi_report.py:862-874`). That is a report-native FU-3c term, which predates TE-1 and is not an accounting output. Its rows are the registered family's own PREREG v3 §5 residual-classified fills, not UNATTRIBUTED rows.
- So a LOSS_STOP reading residual losses is NOT the forbidden "ROI-for-decision".

**Narrow clarification (no erratum):** accounting `fill_rows` may supply per-family COUNTS (`n_settlement_disagree`, `n_residual_settlement_disagree`, `n_fills_attributed`), and only for a fail-closed refusal, a partition check or disclosure. They are never a numerator, a denominator or a test's n.

**The TE-1 AST guard is NOT widened.** `tests/support/te1_accounting_guard.py`, `_ALLOWED` and the `accounting.py` docstring stay byte-unchanged. Only the report touches `accounting`. The accessor reads JSON keys, and the TE-1 guard plus the live-path contract keep it from importing accounting.

### Item 5: the reader gets NO v6 required-key rule
- `read_portfolio_roi_report` and `PortfolioRoiReportView` (`:2894`, `:3068`) do NOT parse any v6 key. The accessor is the only v6 consumer.
- There is no `_MIN_SCHEMA_VERSION_WITH_DECISION_STATS`. The reader reads key-by-key with `_require_*` and tolerates extra keys.
- The study fixture `tests/unit/test_current_rung_hold_exit_window_study.py:639` stamps `prr.PORTFOLIO_ROI_SCHEMA_VERSION` (6 after S1) and carries the v5 keys. The `>= 5` accounting requirement (`:3173`) is still met, so the fixture **stays green unmodified**. This is proven by AC 16: the file is in the S1 focused run and `git diff --stat` shows no change.

### Item 6: L-24 end-to-end test
`test_run_end_to_end_output_is_served_by_the_accessor` drives `_run` (`:4330`) with temp dirs, an injected `now_ns` and a consumable label marker. It then calls `read_roi_for_decision(path, now=datetime.fromtimestamp(now_ns // 10**9, UTC))`, which must return a `RoiDecisionView` serving the fixture family.

### Item 7: age gate is 26 h
`MAX_DECISION_REPORT_AGE = timedelta(hours=26)`: the 24 h cadence plus 2 h margin for run duration and timer jitter.
- Boundary test: 26 h is accepted, 26 h + 1 s is refused, and `now == generated_at` is accepted.
- `generated_at` is floored to whole seconds (`now_ns // 1_000_000_000`), so it is never later than the real write time.

### Item 8
- The AST stdlib-import scan is DROPPED. The lint-imports contract (r2.2 §1 D3) and the AST `asdict`/`astuple` check stay.
- New AC: the latch write stays after the report write.
- `settled_through` is pinned as provenance only. It is the report's settlement cutoff (11-03: `2026-10-27`). It is echoed on the view and never used for age, which comes from `generated_at` only (test 25).
- All plan references are written as full paths.

### Python-reviewer notes (all adopted)
- AC 7 is reworded.
- Item 5's reader statement is adopted.
- `__all__`: the new module's `__all__` lists every public name. The report's `__all__` (`:183`) gains `family_decision_stats`, members added only (L-12).
- `generated_at` is floored, and `now == generated_at` is tested.
- Decimal parsing rejects `NaN`, `Infinity`, `-Infinity`, `sNaN` and negative zero (`is_zero() and is_signed()`). The writer canonicalises zero to `"0"`.
- `test_only_the_report_references_the_accounting_module` is run explicitly after S2 (AC 11).

## 3 Types (replace r2.2 §1 D8)
All types are `@dataclass(frozen=True, slots=True, kw_only=True)`. No `dataclasses.asdict`/`astuple` appears anywhere in the module.
```python
class FamilyDecisionStats:        # writer AND reader type; one v6 `family_decision_stats` row
    family_id: str
    n_admissible: int; n_wins: int; net_pnl: Decimal; fees_total: Decimal; n_incomplete: int
    n_fee_unverified: int; n_settlement_disagree: int               # admissible rows (§2 item 2)
    n_residual: int; n_residual_pending: int; residual_pnl: Decimal  # residual block (item 4)
    n_residual_fee_unverified: int; n_residual_settlement_disagree: int
    n_fills_attributed: int; n_other_excluded: int
    def to_json(self) -> dict[str, object]: ...                     # explicit dict; Decimals as canonical str
    @classmethod
    def from_json(cls, raw: Mapping[str, object]) -> FamilyDecisionStats: ...  # strict; raises _Malformed

class FamilyRefusalReason(StrEnum):
    FAMILY_FEE_UNVERIFIED, FAMILY_SETTLEMENT_DISAGREE, FAMILY_INCOMPLETE, FAMILY_UNKNOWN, FAMILY_PARTITION, NOT_IN_REPORT
class FamilyDecisionRefusal: family_id: str; reason: FamilyRefusalReason

class RoiDecisionView:
    schema_version: int; generated_at: datetime; settled_through: str; source_sha256: str
    roi_status: str                                   # disclosure only
    days_since_newest_input: int | None; input_freshness_status: str   # disclosure only (item 2a)
    global_n_fee_unverified: int; global_n_settlement_disagree: int    # disclosure only
    family_stats: tuple[FamilyDecisionStats, ...]     # served, sorted by family_id
    family_refusals: tuple[FamilyDecisionRefusal, ...]  # sorted by family_id
    def for_family(self, family_id: str) -> FamilyDecisionStats | FamilyDecisionRefusal: ...

class RoiDecisionRefusalReason(StrEnum):
    UNREADABLE, MALFORMED, SCHEMA_VERSION, GENERATED_AT_INVALID, REPORT_FROM_FUTURE, REPORT_STALE, LABELS_GATED
class RoiDecisionRefusal: reason: RoiDecisionRefusalReason

DECISION_SCHEMA_VERSIONS: Final = frozenset({6}); MAX_DECISION_REPORT_AGE: Final = timedelta(hours=26)
INPUT_FRESHNESS_OK: Final = "OK"; INPUT_FRESHNESS_STALE: Final = "STALE"
def read_roi_for_decision(path: Path, now: datetime) -> RoiDecisionView | RoiDecisionRefusal
```

**Report-level gate order** (first failure wins):
1. Unreadable or not a JSON object.
2. `schema_version` (an int, not a bool) ∉ {6}.
3. `generated_at` invalid or naive.
4. `generated_at > now` means `REPORT_FROM_FUTURE`.
5. `now − generated_at > 26 h` means `REPORT_STALE`.
6. `disclosures`, `label_gate_status`, `roi_status` or `input_freshness_status` missing or mistyped means `MALFORMED`.
7. Label gate means `LABELS_GATED`.
8. Any row malformed (negative, bool-as-int, `n_wins > n_admissible`, bad Decimal, duplicate `family_id`) means `MALFORMED`.

**Per-family gate order:**
1. `UNKNOWN`.
2. `n_incomplete != 0`.
3. `n_fee_unverified != 0`.
4. `n_settlement_disagree != 0`.
5. `n_other_excluded < 0`.

A naive `now` raises `ValueError`. The function reads the file once and makes no network call.

The copied literals are `"OK"`, `"UNKNOWN"`, `"GATED_IDENTITY"` and `"GATED_UNLABELLED_FQ"`. All of them are pinned equal to the script's constants.

## 4 Acceptance Criteria (replace r2.2 §2; 23 ACs)
1. `PORTFOLIO_ROI_SCHEMA_VERSION == 6` and the known set is `{1..6}`. `read_portfolio_roi_report` reads v1..v6 and raises on 7 and 999. It parses no v6 key.
2. `generated_at == datetime.fromtimestamp(now_ns // 1_000_000_000, tz=UTC).isoformat()`, from the injected `now_ns` only.
3. `days_since_newest_input` and `input_freshness_status` are computed once, before the write. The same variable feeds `apply_freshness_ladder`. Ladder tests pass unmodified.
4. `family_decision_stats` is built only from `admissible_scored_trials(...)`, `labels.c2_rows()`, the residual settlements/pending and the §2 count sources. For complete inputs: Σ`net_pnl` == `total_realised_pnl_admissible(...) + c2_pnl`, and Σ`residual_pnl` == `total_realised_pnl_residual(residual_settlements)` (USD both, L-2).
5. Additive only. Every v5 key keeps an identical value for identical inputs. v6 adds exactly `generated_at`, `days_since_newest_input`, `input_freshness_status`, `label_gate_status` and `family_decision_stats`.
6. The accessor returns a view for production-writer output when all report gates pass. Each report-level and family-level reason is tested on its own.
7. v6 writer output with `schema_version` rewritten to 5 and the v6-only keys removed is refused with `SCHEMA_VERSION`.
8. View and row fields are exactly the §3 sets (via `dataclasses.fields` names). There is no capital field.
9. An AST scan finds no `asdict`/`astuple` name, attribute or reconstructed getattr (L-80), with a planted positive control.
10. `lint-imports` passes with the r2.2 §1 D3 contract. The RED proof (a planted `import nautilus_trader`) is recorded.
11. The TE-1 guard, `_ALLOWED` and the `accounting.py` docstring are byte-unchanged. `test_te1_accounting.py::test_only_the_report_references_the_accounting_module` is run explicitly after S2 and passes.
12. Pins move 5 to 6 with `==` kept. No member is lost and no skip/xfail is added (r2.2 §3 pin list).
13. Each new test file is classified in `scripts/ci/gate_reviewed.json` and measured in `scripts/ci/gate_durations.json["files"]`.
14. `scripts/ci/run_tests_no_egress.sh` exits 0 (the exit code is read). `ruff`, strict `mypy` and `lint-imports` pass after every slice.
15. Fees: `net_pnl` == Σ row net P&L exactly. `net_pnl + fees_total` == Σ gross. A fixture with fees > 0 proves there is no second subtraction.
16. `tests/unit/test_current_rung_hold_exit_window_study.py` is green and byte-unmodified after S1.
17. Gate scope: `GATED_UNSETTLED_CAPITAL`, `GATED_ACCOUNTING_ONLY`, a global count > 0 and a STALE freshness each still yield a view. The label gate refuses report-wide. A defect on family A refuses A only and B is still served. `UNKNOWN` never blocks.
18. The partition `n_fills_attributed == n_admissible + n_incomplete + n_residual + n_other_excluded` holds for every row written. A negative `n_other_excluded` is refused with `FAMILY_PARTITION`.
19. Latch ordering: if `write_portfolio_roi_json` raises, `.input_freshness.json` is unchanged. In `_run` the latch write follows the report write.
20. The `_run` end-to-end output, run through `read_roi_for_decision`, returns a `RoiDecisionView` (L-24).
21. Read-only S4 after the first v6 run, counts and names only, never an amount. Record:
    - `schema_version`, `roi_status`, `label_gate_status`, `input_freshness_status`;
    - `n_labels_gated`, the global counts;
    - the number of served and refused families with their reasons;
    - the accessor's result type and reason.
22. Read-only: `breezy-portfolio-roi.timer` is active with its last run < 26 h. The Markdown balance-proxy caveat (r2.2 AC 17) still holds.
23. Reachability: §0 (i) or (ii). For (ii), §1b's PROGRESS entry is made.

## 5 File-by-file (deltas to r2.2 §3)
| Path | Change |
|---|---|
| `src/breezy/persistence/portfolio_roi_decision.py` (NEW) | Contents are §3. `__all__` lists every public name. The module docstring states the item-4 clarification and that the module owns no capital |
| `scripts/analysis/portfolio_roi_report.py` | As r2.2 §3, plus the following. (a) `label_gate_status` is threaded into `PortfolioRoiReportData` (required) and the JSON. (b) `family_decision_stats(*, admissible_trials, c2_rows, residual_settlements, residual_pending, fee_reconciled_by_trial_id, fill_rows, registered_manifests)` is pure and builds the §3 rows, with families via `_family_id_of_trial`/`_family_label` (`:806-831`). (c) In `_run`, the stats are computed after `fill_rows` (`:4577`) and before the build call (`:4632`). (d) `__all__` gains `family_decision_stats`. S0 verifies that `ResidualPending` (`:1483`) carries `trial_id` and `climate_day`; if it does not, its family is `UNKNOWN` |
| `tests/unit/test_portfolio_roi_decision.py` (NEW) | 26 tests (§6) |
| `tests/unit/test_portfolio_roi_report.py` | r2.2 pin edits, plus 16 new tests (§6) |
| `tests/unit/test_te1_accounting.py` | r2.2 pin edits only |
| `pyproject.toml`, `scripts/ci/gate_reviewed.json`, `scripts/ci/gate_durations.json` | As r2.2 |

Not touched (beyond r2.2's list):
- `tests/unit/test_current_rung_hold_exit_window_study.py`;
- `src/breezy/adapters/**`;
- the #5/#7 code (their deltas are plans only).

## 6 Tests (replace r2.2 §4; 42 new)
**Accessor tests (26).** Every report comes from the production writer via `build_portfolio_roi_report_data`. A malformed case mutates one key of the writer's output.
1. fresh view
2. AC 7 rewrite → `SCHEMA_VERSION`
3. unknown or non-int schema
4. `generated_at` invalid (3 cases)
5. age 26 h is accepted, 26 h + 1 s is refused, now == generated_at is accepted
6. future
7. naive now raises
8. label gate refuses report-wide (param: `GATED_IDENTITY`, `GATED_UNLABELLED_FQ`, `n_labels_gated > 0`)
9. non-label `roi_status` values still serve
10. STALE freshness is disclosed, not refused
11. global fee/CLI counts are disclosed, not refused
12. family fee-unverified: A refused, B served
13. family CLI disagree: A refused, B served
14. family incomplete: A refused, B served
15. `UNKNOWN` is refused and others are served
16. `FAMILY_PARTITION`
17. malformed rows (param: negative, bool, wins > n, `NaN`, `Infinity`, `-0`, duplicate)
18. null or missing disclosures, or a missing `label_gate_status`
19. unreadable
20. `for_family` on an absent family → `NOT_IN_REPORT`
21. `source_sha256`
22. exact field sets, frozen
23. AST no-`asdict` with a positive control
24. copied literals equal the constants
25. old `settled_through` with fresh `generated_at` is served, and `settled_through` is echoed
26. residual flags > 0 still serve the family, and the residual block round-trips

**Report tests (16).**
1. floored UTC `generated_at`
2. freshness computed before the write (null, fresh, 4 days)
3. JSON and ladder see the same days value
4. admissible-only stats
5. sums equal the admissible numerator
6. YES/NO-leg wins and losses (L-44, via `held`/`settled_outcome` only)
7. incomplete C2 row
8. fees counted once (AC 15)
9. per-family fee-unverified from the state-DB map and C2 `fee_reconciled None`
10. per-family CLI disagree split LEGACY/C2 versus RESIDUAL
11. residual block: per-family sums equal the residual total, and pending is counted
12. the partition reconciles on an 11-03-shaped fixture
13. `label_gate_status` values (null, IDENTITY, UNLABELLED_FQ, UNSETTLED_CAPITAL)
14. latch after report (AC 19)
15. `_run` end-to-end → accessor view (AC 20)
16. the v5 reader on v6 output parses no v6 key

Existing tests run unmodified: the study suite (AC 16), the TE-1 guard (AC 11) and the ladder tests (AC 3).

## 7 Execution order (delta to r2.2 §5)
- **S0:** re-verify every new citation (`:4397-4403`, `:4503-4507`, `:4577`, `:862`, `:1483`, `ResidualPending` fields) and r2.2's citations at the build HEAD.
- **S1:** writer v6 with all 16 report tests. The study suite and the TE-1 suite run unmodified except pins.
- **S2:** the accessor with its 26 tests, then the contract RED proof, then `test_only_the_report_references_the_accounting_module` explicitly.
- **S3:** as r2.2.
- **S4:** AC 21 to 23, then the §1b close decision.

`lint-imports` runs after every slice.

## 8 Risk register (changes to r2.2 §6)
- r2.2's HIGH "global counts refuse indefinitely" is RESOLVED by item 2.
- r2.2's MED "legacy UNKNOWN refuses" is RESOLVED: family-level only.
- NEW MED: item 2a is rejected in round 2. Mitigation: the §2 fallback; the deadlock is recorded, never a silent pass.
- NEW MED: the state-DB fee map lacks a legacy admissible trial, giving a false `FAMILY_FEE_UNVERIFIED`. Mitigation: fail-closed by design; S4 compares the result against the accounting `fill_pnl.fee_unverified` count for the same family.
- NEW LOW: the CLI superset over-refuses (a scored trial that is also a residual id). Mitigation: conservative by design, and disclosed.

## 9 Invariants (binding on every implementer brief; restated)
- Nautilus Trader is immutable. `Account.balance_free` and `QueryAccount` are cited for #5, never wrapped here.
- `allow_short` stays `False`. Leg sign comes only via `leg_of_symbol` (`src/breezy/domain/instrument_leg.py:58`); this delta adds no leg derivation.
- NO-SEND: the report and the accessor make no network calls, and every test runs via `scripts/ci/run_tests_no_egress.sh`.
- Never assign, default or propose the operator day, position or month caps, and never name their environment variables. Live-trading enablement is untouched.
- Never weaken a safety, settlement, contract or pin test. The TE-1 guard is byte-unchanged and pins keep `==`. The item 2 and item 2a narrowings are justified in §2 and are not test edits.
- New test files are classified in `scripts/ci/gate_reviewed.json` and timed in `scripts/ci/gate_durations.json`.
- `lint-imports` runs after every slice; `python -m importlinter` is a no-op.
- No `dataclasses.asdict`/`astuple`.
- Report files are never hand-edited (L-75). No dollar figure enters git, the plan or an alert.

## 10 Confidence
0.80 overall.

| Area | Confidence |
|---|---|
| Code facts | 0.92 (new citations read at `0bbddc14`; `ResidualPending` fields S0-verified) |
| Gate-scope soundness | 0.85 |
| Item 2a | 0.75: sound, but a deviation that needs ratification |
| Reachability | 0.7: depends on OPS-4 today |
