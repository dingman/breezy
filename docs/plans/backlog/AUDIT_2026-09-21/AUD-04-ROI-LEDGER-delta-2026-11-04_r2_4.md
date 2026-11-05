# AUD-04 ROI-LEDGER delta r2.4 (2026-11-04): supersedes r2.3 where they conflict. Status: FINAL-ROUND DRAFT (round-2 review answered)

Applies on top of `docs/plans/backlog/AUDIT_2026-09-21/AUD-04-portfolio-roi-measurement.md`, `docs/plans/backlog/AUDIT_2026-09-21/AUD-04-AMENDMENT-2026-09-21.md`, `docs/plans/backlog/AUDIT_2026-09-21/AUD-04-ROI-LEDGER-delta-2026-11-04_r2_2.md` and `docs/plans/backlog/AUDIT_2026-09-21/AUD-04-ROI-LEDGER-delta-2026-11-04_r2_3.md`. Where r2.3 and this file conflict, this file wins. Every r2.3 section not changed below stands.

This answers round 2: python-reviewer APPROVE (non-blocking notes adopted, item 10); prediction-market-reviewer and architect REQUEST_CHANGES (items 1 to 9, 11). Coordinator rulings are applied. Scope is unchanged: no item adds a consumer, a capital field or a new refusal class.

Companion amendment deltas (edited in place with this file):
- #5: `docs/plans/backlog/GAPS_2026-11-01/size_under_caps/plan_r5_delta.md`
- #7: `docs/plans/backlog/GAPS_2026-11-01/auto_promote_retire/plan_r6_delta.md`

All line citations below were read at `0bbddc14`. S0 re-verifies them at the build HEAD.

## Erratum r2.4-e1 (2026-11-04, round-3 review)
Round 3: prediction-market-reviewer and architect each raised B1. The edits are in place in this file and in #7 r6. Code read at `0bbddc14`.

**B1. The count missed resting orders.** The `arm_ns > max(fill.ts_event)` rule undercounts. Example: anchor A is armed at t1 and fills late, but the fill is never booked (`_book_resting_fill`, `src/breezy/adapters/polymarket_us/exec/client.py:9620-9728`, can return `False` and write nothing at `:9645-9654`). Anchor B is armed at t3 and fills at t4. The old count read 0, so #7 eligibility wrongly passed under STALE.

**Terminal-close finding (measured).** No durable per-`client_order_id` terminal-close record exists, so none is used:
- The counter ingest handles only `OrderSubmitted`, `OrderFilled` and `OrderDenied` (`src/breezy/runtime/exec_par_counter_ingest.py:415-422`). `OrderCanceled` and `OrderExpired` are ignored and nothing is written for them.
- `DenialRow` (`src/breezy/runtime/exec_par_records.py:299-304`) is written from `OrderDenied`, which fires before submit, so a denied order never has an anchor to close.
- `AmbiguousRow` (`exec_par_records.py:308-322`) is keyed by `intent_id`, not `client_order_id`, and it is kept on resolution. It cannot be joined to an anchor.
- In the exec store, a bound rest's terminal path tombstones `resting/<venue_order_id>` to `b""` (`client.py:9027-9042`). The same tombstone is written on fill (`:9717`) and on an unfilled cancel or expiry (`:9057`). It is keyed by venue id, so it does not distinguish the two outcomes. An IOC miss writes no row at all.

**Consequence (accepted as fail-closed).** A cancelled, expired or IOC-missed anchor keeps counting for good. Once any entry goes unfilled, the count stays above 0. Under STALE, that permanently blocks the permissive #7 eligibility path. It never blocks LOSS_STOP, refusals, entry withholding or #5 (§1.5).
- It clears when freshness returns to `OK`. That path does not depend on this count (L-48).
- A permanent clear needs a durable terminal-close record per `client_order_id`, for example `exec_par/close/<coid>` written from `OrderCanceled`/`OrderExpired`/`OrderRejected` in `on_event`. That would be a separate backlog item and is NOT in #4 scope. If one is added, the rule below gains "and not terminally closed" with no other change.

**Changes in this file:**
1. The count is renamed `n_orders_since_newest_fill` → `n_open_anchors_without_fill`, and the rule is replaced (§1.4). This applies to §0, §1.4, §1.5, §12 (type and gate step 6), AC 3, 5, 17 and 21, accessor tests 9 and 12, report test 3, §15 and §17.
2. §1.4: the S0 positive control gets an exact threshold. The old `venue_id/`-after-epoch comparison is withdrawn, because `venue_id/` rows carry no timestamp (this file's own §1.4 table).
3. §1.4: discloses that `record_posted` writes BUY entries only (`exec_par_counter_ingest.py:425-430,446-448`), so SELL exit fills are outside the count. §17 gains a LOW row.
4. §14: adds report test 16 (an older anchor with no fill for its coid, plus a newer anchor with a fill → the count includes the older one). That makes 36 new tests.
5. §15/§16: adds the production call `build_portfolio_roi_report_data(` (`scripts/analysis/portfolio_roi_report.py:4632`), which must pass the real computed `label_gate_status`.
6. §16: the lint-imports claim is corrected. `root_packages = ["breezy", "nautilus_trader"]` (`pyproject.toml:71`), so lint-imports cannot see `scripts/`.
7. §17: the LOW "clears on the next fill" row is replaced, because the next fill no longer clears an unfilled anchor.
8. Companion #7 r6 R6-2/R6-5: rename and reworded rule; the false "proves no order could have produced an unseen fill" claim is dropped; entry is withheld on `n_other_excluded > 0`; a `FAMILY_PARTITION` block is read restrictively only.
9. Companion #5 `size_under_caps/plan_r5_delta.md:64` was not edited (out of this erratum's file scope). Its `n_orders_since_newest_fill` is read as `n_open_anchors_without_fill`. That reference is a "#5 reads none" exclusion, so its meaning is unchanged.

## Erratum r2.4-e2 (2026-11-04, post-merge acceptance)
Production at K=1 writes no `exec_par/order/` anchors: `build_exec_watcher` builds no counter ingest at K=1. Zero rows therefore do not prove zero orders (L-8). `n_open_anchors_without_fill` ships `None` when no decodable anchor rows exist, including when there are no fills; all existing `None` conditions and the counting rule when anchors exist stand.

Consequence: #7 eligibility under STALE is blocked until an anchor writer is live at K=1 or freshness is OK. A K=1 anchor writer is a separate candidate, not part of #4.

## 0 Goal state (L-3): r2.3 §0 stands, with two changes
- WALK: `_run` also computes `n_open_anchors_without_fill` in the ledger pass (item 1; renamed by erratum e1).
- "#4 DONE" is never written. On outcome (ii), the PROGRESS entry is the §1b text below. #4 is BUILT, and its consumers stay BLOCKED until OPS-4 clears label identity.

## 1 Item 1: freshness stays disclosure-only, with a corrected justification (L-8, L-48)

### 1.1 Why r2.3's justification was wrong
None of r2.3's three guards detects a fill the venue executed but the node never recorded:
- `assert_ledger_partition` (`scripts/analysis/portfolio_roi_report.py:391`) partitions only the fills that were decoded.
- `labels_consumable` (`src/breezy/persistence/autonomy/label_store.py:201-210`) proves only that the label run is fresh.
- `generated_at` proves only that the report ran.

### 1.2 The real guard
The real guard is the exec client's reconciliation latch, `src/breezy/adapters/polymarket_us/exec/client.py:188-216`:
- Invariant 1: a reconcile mismatch appends a node-global refusal, and the refusal never self-clears.
- Invariant 2: native cash and PnL are non-authoritative while the refusal is latched.

So a venue fill missing from the durable records latches trading off at the next reconciliation. S0 confirms that a venue fill with no `FILL_KEY_PREFIX` record reaches `_refuse`, and cites the line.

### 1.3 Why freshness is not a refusal (L-48)
As a report-level refusal, input freshness would block its own only clearing path, a new fill.

r2.3's §2a fallback ("keep INPUT_FRESHNESS report-level") is WITHDRAWN. No fallback in this plan re-introduces a report-level or family-level freshness refusal.

The only freshness-sensitive rule is the #7 eligibility guard in §1.5. It is permissive-path only. Freshness never gates sizing or LOSS_STOP.

### 1.4 The new disclosed count: `n_open_anchors_without_fill: int | None` (erratum e1; was `n_orders_since_newest_fill`)
It is computed in the SAME pass as the ledger read. `read_ledger_fills_with_counts` (`portfolio_roi_report.py:328-363`) already runs `SELECT key, value FROM state` over every row (`:342`), and the count is taken from those same rows. `LedgerReadResult` gains a field that defaults to `None`, so its existing direct constructions (`tests/unit/test_portfolio_roi_report.py:2489,2499,2508`) stay valid. A `None` default is fail-closed (§1.5).

**Choosing the timestamp source (measured):**

| Candidate | Verdict | Evidence |
|---|---|---|
| `venue_id/` (`client.py:443`) | **REJECTED: no timestamp** | The value is only the `ClientOrderId` bytes (`record_venue_order_id`, `client.py:6679-6693`) |
| `resting/` (`client.py:507`) | REJECTED | Only BOUND resting orders are written (`_bind_resting_order`, `:8675-8683`), and the row carries `expireTimeNs`, not the creation time |
| EXEC-PAR `EpochRow` | REJECTED | It carries boot and stop times (`src/breezy/runtime/exec_par_records.py:164-169`), not orders |
| **EXEC-PAR posted-entry anchors** `exec/polymarket_us/exec_par/order/<coid>` | **CHOSEN** | `OrderAnchor.arm_ns` (`exec_par_records.py:280-294`), written by `record_posted` (`src/breezy/runtime/exec_par_counter_ingest.py:227-267`) under `EXEC_PAR_PREFIX` (`exec_par_records.py:129`), in the same state DB namespace. Decoded with the public `decode_record(OrderAnchor, raw)` (`exec_par_records.py:656`), the latch's own codec. No latch is held, because the read is the report's existing read-only fetch |

**Rule (erratum e1):**
- `fill_coids` is the set of `client_order_id`s over the decoded `DurableFillRecord`s. `newest` is `max(fill.ts_event)`.
- `n_open_anchors_without_fill` = |{anchor : `anchor.client_order_id ∉ fill_coids`} ∪ {anchor : `anchor.arm_ns > newest`}|. It counts each anchor once. If there are no fills, it counts every anchor.
- There is NO terminal-close exclusion, because no durable per-coid terminal-close record exists (Erratum e1 finding). A cancelled, expired or IOC-missed anchor counts for good. That is accepted as fail-closed: it blocks only the permissive #7 eligibility path under STALE.
- An undecodable fill row adds no coid to `fill_coids`, so its anchor counts. That is the conservative direction.
- It is `None` when any anchor row fails to decode.
- It is `None` when the S0 positive control below fails.

**What a 0 means, and what it does not.** A 0 means every anchored BUY entry has a durable fill record, and none was armed after the newest one. It does NOT prove that no unseen fill exists. The guard against unseen fills is still the reconciliation latch (§1.2).

**Exits are outside the count (disclosed).** `record_posted` writes BUY entries only: `_entry_order` returns `None` for a non-BUY order (`src/breezy/runtime/exec_par_counter_ingest.py:425-430`), and `_on_filled` skips non-BUY fills (`:446-448`). So a SELL exit order or fill never enters the count. Exits are unarmed today (§17 LOW row).

**S0 positive control (L-8), exact threshold.** `record_fill` cannot write without an anchor (`_anchor` raises, `exec_par_counter_ingest.py:339-343`). So an ingest gap shows up as a fill with no anchor.
- Epoch: `epoch_ns` = the earliest `EpochRow.boot_ts` under `exec_par/epoch/` (`exec_par_records.py:135,164-169`).
- Check: take every decoded BUY `DurableFillRecord` with `ts_event ≥ epoch_ns`. Its `client_order_id` must have an `exec_par/order/<coid>` anchor.
- Threshold: if ≥ 1 such fill lacks an anchor, or no `EpochRow` exists, the field ships as `None` until the ingest is wired. That is recorded as a #7 eligibility blocker under STALE, never as a silent 0.
- The `venue_id/`-after-epoch comparison in r2.4 is WITHDRAWN, because `venue_id/` rows carry no timestamp (table above).
- Residual: an unfilled post-epoch order whose anchor was dropped is invisible to this control. It is bounded because posts and fills go through the same `on_event` ingest (`:415-422`).

### 1.5 Consumer rule (in #7 r6 R6-2)
Eligibility requires `input_freshness_status == "OK"` OR `n_open_anchors_without_fill == 0`. A `None` count is treated as non-zero. Because unfilled anchors count for good (§1.4), in practice the STALE branch passes only before any entry has gone unfilled. Accepted as fail-closed.
- LOSS_STOP is unchanged.
- #5 never reads either field.
- A STALE view is never new evidence for #7 (#7 r6 R6-2).

### 1.6 #5 cross-reference
The #5 R5-1 balance-freshness rule ("`ts_event` ≥ newest booked fill") cannot see an unbooked fill. That blind spot is bounded by the same latch, which #5 already treats as a sizing refusal.

## 2 Item 2: `label_gate_status` is an EXACT set (L-12, L-14)
The value set is derived from the producers, not recalled:
- `_gate_status_of` (`portfolio_roi_report.py:4233-4247`) returns `None`, `GATED_IDENTITY` or `GATED_UNSETTLED_CAPITAL`.
- `_run` (`:4397-4403`) adds `GATED_UNLABELLED_FQ`.

The constants are `ROI_STATUS_GATED_UNSETTLED_CAPITAL` (`:2143`), `ROI_STATUS_GATED_IDENTITY` (`:2147`) and `ROI_STATUS_GATED_UNLABELLED_FQ` (`:2163`).

| Raw value | Result |
|---|---|
| `null`, `"GATED_UNSETTLED_CAPITAL"` | serves; disclosed on the view |
| `"GATED_IDENTITY"`, `"GATED_UNLABELLED_FQ"` | `LABELS_GATED` (report-level) |
| any other string, a missing key, or a type other than `str`/`None` | `MALFORMED` |

Why pending labels serve: the label run counts pending labels in `RunMarker.pending` (`label_store.py:475-495`). Open fills are counted separately in `RunMarker.open` and are not gated. A pending fill has no admissible P&L row, so it changes no figure the view reads. `disclosures.n_labels_gated != 0` still refuses `LABELS_GATED` (r2.3 unchanged).

The accessor's `_label_gate(raw: object) -> str | None` accepts `str | None` only. The two sets are module constants: `LABEL_GATE_SERVES = frozenset({None, "GATED_UNSETTLED_CAPITAL"})` and `LABEL_GATE_REFUSES = frozenset({"GATED_IDENTITY", "GATED_UNLABELLED_FQ"})`. A test pins both with `==`, against the script constants and against the set of values the producers can return (L-12: widen only, in its own re-pin item).

**Builder argument (python note):** `label_gate_status` is a REQUIRED keyword on `build_portfolio_roi_report_data` and on `PortfolioRoiReportData`. It is not defaulted, because a default of `None` would fabricate "not gated" (L-14). The direct-construction sites are listed as pin edits. Each gains `label_gate_status=None` explicitly, and no assertion changes:
- `tests/unit/test_portfolio_roi_report.py:251,5149,5155,5946`
- `tests/unit/test_te1_accounting.py:898,899,909` (via its kwargs). The TE-1 guard file stays byte-unchanged.

## 3 Item 3: YAGNI trim [RULING]
Dropped from the view and the v6 row:
- `fees_total`. AC 4's Σ`net_pnl` equality, on a fixture with fees > 0, already proves fees are counted once.
- `global_n_fee_unverified` and `global_n_settlement_disagree`. They stay in the v5 `disclosures`, unchanged.
- `source_sha256`.

**`n_wins`: DROPPED.**
- `/usr/bin/grep -n 'n_wins\|n_win'` over `size_under_caps/plan_r0..r5` and `auto_promote_retire/plan_r0..r6` and `review_status.md` gives 0 matches.
- #7's win term is per-row inside S, on #7's OWN exact prefix (`auto_promote_retire/plan_r1.md:84`; r6 R6-1, "n_a, S … stay on #7's own exact prefix").
- #5 reads no statistic.

The malformed check `n_wins > n_admissible` goes with it. The YES/NO-leg test (L-44) is kept and asserts the sign of `net_pnl`.

## 4 Item 4: `n_other_excluded` [#7 B1]
Disclosed on every row, served or refused (r2.3 field). #7 eligibility requires `n_other_excluded == 0`.

**The S0 exception check is disproved structurally, so the strict rule binds.** A C2 `UNATTRIBUTED` row with `realized_pnl` set books `PnlSource.C2`/`SETTLED_NWS_IMPLIED` with `net` set and `family_id = row.family_id` (`src/breezy/analysis/labeling/accounting.py:556-577`, `PRE_EPOCH_BRIDGE` basis). It is an accounting row and not a `c2_rows()` row, so it lands in F's `n_other_excluded` and carries P&L. S0 re-reads `_c2_booking` at the build HEAD. If it still sets `net` on that path, the exception stays closed.

## 5 Item 5: n_p without accounting `fill_rows` [#7 B2]
`n_p = n_admissible + n_incomplete + n_residual`. All three terms are report-native:
- `n_admissible`: complete rows of `admissible_scored_trials(...)` plus complete `labels.c2_rows()`.
- `n_incomplete`: §6.2.
- `n_residual`: `ResidualSettlement` plus `ResidualPending` for F (§10.1).

`n_fills_attributed`, the count of accounting `fill_rows` with `family_id == F`, is used ONLY in the partition check: `n_other_excluded = n_fills_attributed − n_p`, and a value below 0 is `FAMILY_PARTITION`.

The two CLI-disagree counts remain fill_rows-sourced fail-closed refusal or withhold counts (r2.3 narrow clarification, unchanged). They never enter n_p, a numerator or a denominator. No erratum.

On the 11-03 inputs: `pm_us_crh_cont` n_p = 4 + 0 + 1 = 5 with other 0; `pm_us_crh_v4` 3 + 0 + 0 = 3 with other 0; `pm_us_crh_v2` 0 + 0 + 1 = 1 with other 0.

## 6 Item 6 [PM a]: a refused family never blinds LOSS_STOP

### 6.1 The restrictive block
A per-family refusal carries `restrictive: FamilyRestrictiveBlock | None`, for RESTRICTIVE use only:
- It is set for `FAMILY_FEE_UNVERIFIED`, `FAMILY_SETTLEMENT_DISAGREE`, `FAMILY_INCOMPLETE` and `FAMILY_PARTITION`.
- It is `None` for `FAMILY_UNKNOWN` and `NOT_IN_REPORT`, which have no registered family to stop.
- Its values are exactly what the served row would have carried (AC 24).
- A report-level refusal carries no block. #7 then withholds entry, which is already restrictive (r6 unchanged).

The rules are typed and tested:
- #7 LOSS_STOP may read the block.
- #7 eligibility reads only a served `FamilyDecisionStats`.
- #5 reads neither. The #5 R5-4 AST check names `restrictive`.

### 6.2 `n_incomplete`
`n_incomplete` = F's admissible C2 rows (`labels.c2_rows()`) with `realized_pnl is None`. These are booked `C2`/`UNSETTLED` (`accounting.py:565`), the `n_null_pnl_final` defect class (`:753`). It is a data-quality count.

An unsettled admissible fill (an open position) is NOT in `n_incomplete`:
- It has no final label row. The label run counts it in `RunMarker.open` or `RunMarker.pending`.
- Accounting books it `OPEN` under `UNKNOWN` (`accounting.py:599-601`), or `OPEN` with `PnlSource.NONE` for a pre-epoch `UNATTRIBUTED` row (`:561-564`, in `n_other_excluded`).
- So an open position never refuses F for sizing.

`net_pnl` is always Σ over F's COMPLETE admissible rows, whether the family is served or refused.

**S0 check:** confirm that the label writer emits no admissible row with `realized_pnl None` before settlement. If it does, the S0 FAIL is recorded, and these consequences are explicit:
- An open position then counts in `n_incomplete`.
- It refuses F for #7 eligibility and for #5 sizing until it settles. That is recorded as a #5 blocker, never silent.
- LOSS_STOP still reads F's settled `net_pnl` and residual block from `restrictive`.

## 7 Item 7: #5 capital. See #5 r5 R5-1 (edited in place). #4 owns no capital (r2.3 unchanged)

## 8 Item 8: AC 23(ii) close (L-3, L-70)
r2.3 §1b's recommendation stands. The PROGRESS text and the re-entry replace its last line.

**`docs/core/PROGRESS.md` entry (coordinator):**
> "#4 ROI-LEDGER BUILT: AC 1-22 and 24 green; AC 23 outcome (ii) LABELS_GATED (OPS-4 label identity). NOT consumer-ready: #5 and #7 stay BLOCKED until OPS-4 clears label identity. Re-check armed: <mechanism> at <wake time>Z."

**Re-entry:**
- The re-check is a session cron (CronCreate), set for 17:50Z after the next `breezy-portfolio-roi.timer` 17:40Z run and verified with CronList.
- If the cycle is headless, the host cycle timer is the re-entry instead, verified with `systemctl --user list-timers`.
- The wake time goes into PROGRESS.md. A close without a verified re-entry is a defect (L-70).

**Each re-check:**
- It runs the AC 21 read-only readout.
- If the result is still outcome (ii), it re-arms at the next 17:50Z.
- When outcome (i) holds, it records outcome (i) with the readout and replaces the entry with "#4 ROI-LEDGER consumer-ready (outcome (i) <date>); #5/#7 unblocked on #4".

## 9 Item 9: AC 20 uses the production marker writer (L-24)
`test_run_end_to_end_output_is_served_by_the_accessor` creates label state only through the production writers:
- `breezy.persistence.autonomy.label_store.write_labels` (`label_store.py:314`)
- `write_marker(data_root, RunMarker(...), day=..., now_ns=...)` (`label_store.py:527`)

The marker is never hand-built JSON. A grep in AC 20 asserts that the test file contains no literal marker body or `store.set`.

## 10 Item 10: python notes adopted

### 10.1 Residual family resolution: add `climate_day` additively
Per-family `n_residual`, `n_residual_pending` and `residual_pnl` are taken report-native, so `n_residual` can enter n_p (item 5).

I chose to add `climate_day` rather than count `fill_rows`, because RESIDUAL `fill_rows` counts could not enter n_p.

`ResidualPending` (`portfolio_roi_report.py:1216-1227`) gains a REQUIRED field `climate_day: str`:
- Its only producer, `residual_settlement` (`:1230-1248`), sets it from `FilledTrial.climate_day` (`src/breezy/settlement/trial_scorer.py:83`, the field documented at `:104`).
- The family comes from `_family_label(trial_id, climate_day, registered_manifests)` (`:822-830`), the same resolver `build_fill_pnl` uses at `:4580`.
- `ResidualSettlement` already has `climate_day` (`:1196`).
- Pin edits (argument additions only): `tests/unit/test_portfolio_roi_report.py:3518,4346`.

### 10.2 `label_gate_status` is required (§2), with the pin edits listed

### 10.3 `n_residual_fee_unverified` source
The source is `fee_reconciled_by_trial_id_pooled` (`portfolio_roi_report.py:4503-4507`, state DB), read for each of F's residual trial_ids, settled and pending:
- An absent entry counts as unverified. That is the `(False, "", False)` default used by `fee_unverified_residual_disclosure` (`:705`, `:735-737`).
- S0 positive control: Σ over families == v5 `disclosures.n_fee_unverified` (11-03: 2).

### 10.4 Age gate
`MAX_DECISION_REPORT_AGE = timedelta(hours=26)` matches `MARKER_STALE_H = 26` (`src/breezy/persistence/autonomy/label_store.py:84`; `LABEL_MARKER_STALE_H`, `src/breezy/analysis/labeling/constants.py:59`). The accessor keeps its own literal, and a test pins equality, so the accessor imports no label store.

## 11 Item 11: #7 r6 header now states that `plan_r3_delta.md` is superseded entirely (`auto_promote_retire/plan_r4_delta.md:19`)

## 12 Types (replace r2.3 §3)
All types are `@dataclass(frozen=True, slots=True, kw_only=True)`. No `dataclasses.asdict`/`astuple` appears.
```python
class FamilyDecisionStats:        # writer AND reader type; one flat v6 `family_decision_stats` row
    family_id: str
    n_admissible: int; net_pnl: Decimal; n_incomplete: int            # net_pnl over COMPLETE admissible rows
    n_fee_unverified: int; n_settlement_disagree: int                 # admissible rows
    n_residual: int; n_residual_pending: int; residual_pnl: Decimal   # report-native (§10.1)
    n_residual_fee_unverified: int; n_residual_settlement_disagree: int
    n_fills_attributed: int; n_other_excluded: int                    # partition check only (§5)
    def to_json(self) -> dict[str, object]: ...
    @classmethod
    def from_json(cls, raw: Mapping[str, object]) -> FamilyDecisionStats: ...  # strict; raises _Malformed

class FamilyRestrictiveBlock:     # RESTRICTIVE use only (#7 LOSS_STOP); never eligibility or sizing
    net_pnl: Decimal; n_residual: int; n_residual_pending: int; residual_pnl: Decimal
    n_residual_fee_unverified: int; n_residual_settlement_disagree: int

class FamilyRefusalReason(StrEnum):
    FAMILY_FEE_UNVERIFIED, FAMILY_SETTLEMENT_DISAGREE, FAMILY_INCOMPLETE, FAMILY_UNKNOWN, FAMILY_PARTITION, NOT_IN_REPORT
class FamilyDecisionRefusal:
    family_id: str; reason: FamilyRefusalReason
    restrictive: FamilyRestrictiveBlock | None        # set iff reason not in {FAMILY_UNKNOWN, NOT_IN_REPORT}

class RoiDecisionView:
    schema_version: int; generated_at: datetime; settled_through: str
    roi_status: str; label_gate_status: str | None                      # disclosure only
    days_since_newest_input: int | None; input_freshness_status: str   # disclosure only
    n_open_anchors_without_fill: int | None                            # disclosure only (§1.4, erratum e1)
    family_stats: tuple[FamilyDecisionStats, ...]                      # served, sorted by family_id
    family_refusals: tuple[FamilyDecisionRefusal, ...]                 # sorted by family_id
    def for_family(self, family_id: str) -> FamilyDecisionStats | FamilyDecisionRefusal: ...

class RoiDecisionRefusalReason(StrEnum):
    UNREADABLE, MALFORMED, SCHEMA_VERSION, GENERATED_AT_INVALID, REPORT_FROM_FUTURE, REPORT_STALE, LABELS_GATED
class RoiDecisionRefusal: reason: RoiDecisionRefusalReason

DECISION_SCHEMA_VERSIONS: Final = frozenset({6}); MAX_DECISION_REPORT_AGE: Final = timedelta(hours=26)
LABEL_GATE_SERVES: Final = frozenset({None, "GATED_UNSETTLED_CAPITAL"})
LABEL_GATE_REFUSES: Final = frozenset({"GATED_IDENTITY", "GATED_UNLABELLED_FQ"})
INPUT_FRESHNESS_OK: Final = "OK"; INPUT_FRESHNESS_STALE: Final = "STALE"
def read_roi_for_decision(path: Path, now: datetime) -> RoiDecisionView | RoiDecisionRefusal
```

**Report-level gate order.** r2.3 stands, with two changes:
- Step 6: `disclosures`, `roi_status`, `input_freshness_status` or `n_open_anchors_without_fill` missing or mistyped means MALFORMED. `label_gate_status` is MALFORMED when it is absent, not `str | None`, or a string outside `LABEL_GATE_SERVES ∪ LABEL_GATE_REFUSES`.
- Step 8 drops the `n_wins` check.

**Per-family gate order.** r2.3 stands. Steps 2 to 5 attach `restrictive`.

The copied literals are `"OK"`, `"UNKNOWN"`, the three gate strings and `26`. All of them are pinned equal to their source constants.

## 13 Acceptance Criteria (replace r2.3 §4; 24 ACs)
1. r2.3 AC 1.
2. r2.3 AC 2.
3. `days_since_newest_input` and `input_freshness_status` are computed once, before the write, and feed `apply_freshness_ladder`. The ladder tests pass unmodified. `n_open_anchors_without_fill` is computed in the same `SELECT key, value FROM state` pass as the fills, by the §1.4 erratum-e1 rule. An undecodable anchor, or a failed S0 positive control, gives `None`.
4. `family_decision_stats` uses only the §5/§10 sources. For complete inputs: Σ`net_pnl` == `total_realised_pnl_admissible(...) + c2_pnl` and Σ`residual_pnl` == `total_realised_pnl_residual(...)` (USD both, L-2). This is proven on a fixture with fees > 0, so there is no second subtraction (this absorbs r2.3 AC 15).
5. Additive only. Every v5 key keeps an identical value. v6 adds exactly `generated_at`, `days_since_newest_input`, `input_freshness_status`, `n_open_anchors_without_fill`, `label_gate_status` and `family_decision_stats`.
6. r2.3 AC 6.
7. r2.3 AC 7.
8. The view, row, block and refusal fields are exactly the §12 sets. There is no capital, `fees_total`, `n_wins`, `global_n_*` or `source_sha256` field.
9. to 14. r2.3 AC 9 to 14. AC 12 adds the §2 and §10.1 argument-only pin edits, and no assertion changes.
15. `label_gate_status` exact set (§2): serves on {null, `GATED_UNSETTLED_CAPITAL`}; `LABELS_GATED` on {`GATED_IDENTITY`, `GATED_UNLABELLED_FQ`} or `n_labels_gated > 0`; MALFORMED otherwise. Both sets are pinned `==` to the script constants.
16. r2.3 AC 16.
17. r2.3 AC 17. A v5 global count > 0 and a STALE freshness (with a count of 0, > 0 or `None`) each still yield a view.
18. `n_p = n_admissible + n_incomplete + n_residual` from report-native sources. `n_other_excluded = n_fills_attributed − n_p`, and a value below 0 is `FAMILY_PARTITION`. `fill_rows` supplies only `n_fills_attributed` and the two CLI-disagree counts.
19. r2.3 AC 19.
20. The `_run` end-to-end output, read through `read_roi_for_decision`, returns a `RoiDecisionView`. Label state comes from `write_labels` and `write_marker` only (§9).
21. r2.3 AC 21, plus `label_gate_status` and `n_open_anchors_without_fill`.
22. r2.3 AC 22.
23. Reachability §0 (i) or (ii). For (ii), the §8 PROGRESS entry is written and the re-entry is armed and verified.
24. Every family refusal with a block carries `restrictive` values equal to the row's own. `FAMILY_UNKNOWN` and `NOT_IN_REPORT` carry `None`.

## 14 Tests (replace r2.3 §6; 36 new, down from 42; erratum e1 adds report test 16)
**Accessor tests: `tests/unit/test_portfolio_roi_decision.py` (20; was 26).** Every report comes from the production writer.
1. fresh view; disclosure fields echoed
2. AC 7 rewrite → `SCHEMA_VERSION`
3. unknown or non-int schema
4. `generated_at` invalid (3 cases)
5. age boundary: 26 h accepted, 26 h + 1 s refused, now == generated_at accepted
6. future
7. naive now raises
8. `label_gate_status` exact set (param: null and UNSETTLED_CAPITAL serve; IDENTITY, UNLABELLED_FQ and `n_labels_gated > 0` refuse; unknown string, missing key and int are MALFORMED)
9. disclosure-only inputs serve (param: non-label `roi_status`; STALE with a count of 0, > 0 or `None`; v5 global counts > 0)
10. a family refusal isolates A from B (param: fee, CLI, incomplete, partition), and A carries `restrictive` equal to its row
11. `UNKNOWN` is refused with `restrictive is None`, and the others are served
12. malformed rows (param: negative, bool, `NaN`, `Infinity`, `-0`, duplicate, non-int `n_open_anchors_without_fill`)
13. null or missing `disclosures`, `roi_status` or `input_freshness_status` → MALFORMED
14. unreadable
15. absent family → `NOT_IN_REPORT` with `restrictive is None`
16. exact field sets, frozen
17. AST no-`asdict`, with a positive control
18. copied literals (incl. `LABEL_GATE_*` and `MAX_DECISION_REPORT_AGE == timedelta(hours=label_store.MARKER_STALE_H)`)
19. old `settled_through` with fresh `generated_at` is served and echoed
20. residual flags > 0 still serve; the residual block round-trips

Dropped: `source_sha256`, the `n_wins` case, and r2.3 cases 10 to 14, 16 and 18, which are merged into 8 to 10 and 13.

**Report tests: `tests/unit/test_portfolio_roi_report.py` (16; was 16 in r2.3, 15 in r2.4).**
1. floored UTC `generated_at`
2. freshness computed before the write (null, fresh, 4 days); the JSON and the ladder see the same value
3. `n_open_anchors_without_fill` (param: no anchors → 0; an anchor whose coid has a fill and is older than the newest fill → 0; an anchor armed after the newest fill → 1; an anchor with no fill for its coid → 1; no fills → all; undecodable anchor → `None`; a post-epoch BUY fill with no anchor → `None` (S0 control); a SELL order is never counted)
4. admissible-only stats; sums equal the numerator; fees > 0 counted once
5. YES/NO-leg `net_pnl` signs (L-44, via `held`/`settled_outcome` only)
6. a C2 `realized_pnl None` row → `n_incomplete`; an open unlabelled fill is not in F
7. per-family fee-unverified (state-DB map; C2 `fee_reconciled None`)
8. per-family CLI disagree, split LEGACY/C2 versus RESIDUAL
9. residual block: sums equal the total; pending is counted via `ResidualPending.climate_day`; `n_residual_fee_unverified` comes from the pooled map, absent = unverified
10. partition and n_p on an 11-03-shaped fixture
11. `label_gate_status` values written (null, IDENTITY, UNLABELLED_FQ, UNSETTLED_CAPITAL)
12. latch after report (AC 19)
13. `_run` end-to-end → accessor view, using `write_labels`/`write_marker` (AC 20)
14. the v5 reader on v6 output parses no v6 key
15. `residual_settlement` sets `ResidualPending.climate_day` from `FilledTrial.climate_day` (the producer, L-24)
16. `test_older_unfilled_anchor_counts_despite_a_newer_filled_anchor` (erratum e1, B1): anchor A has no `DurableFillRecord` for its coid; anchor B is armed later and has a fill with `ts_event` after both arms. The count is 1 and includes A. Under the r2.4 rule it would have been 0.

## 15 File-by-file (delta to r2.3 §5)
| Path | Change |
|---|---|
| `src/breezy/persistence/portfolio_roi_decision.py` (NEW) | §12 contents |
| `scripts/analysis/portfolio_roi_report.py` | r2.3, plus: `LedgerReadResult.n_open_anchors_without_fill` computed in `read_ledger_fills_with_counts`; `ResidualPending.climate_day`; a required `label_gate_status`; `fees_total` and `n_wins` removed from the stats builder |
| `scripts/analysis/portfolio_roi_report.py:4632` (production call `build_portfolio_roi_report_data(` in `_run`) | passes `label_gate_status=` the REAL computed value (the `_gate_status_of` result, plus `GATED_UNLABELLED_FQ` from `_run`, §2). It never passes a literal `None` (L-14), and it passes `n_open_anchors_without_fill=ledger_result.n_open_anchors_without_fill` |
| `tests/unit/test_portfolio_roi_decision.py` (NEW) | 20 tests |
| `tests/unit/test_portfolio_roi_report.py` | r2.2 pins; argument edits at `:251,3518,4346,5149,5155,5946`; 15 new tests |
| `tests/unit/test_te1_accounting.py` | r2.2 pins; the `label_gate_status` kwarg at `:898,899,909` |

## 16 Execution order (delta to r2.3 §7)
**S0 additions (read-only, counts only):**
- §1.2: the latch path for an unbooked venue fill.
- §1.4: the anchor positive control.
- §4: `_c2_booking`.
- §6.2: no pre-settlement admissible label row.
- §10.3: the Σ fee-unverified check.

S1 to S4 are as r2.3. S4 performs §8. `lint-imports` runs after every slice.

**S1 checklist addition (erratum e1):** the production call `build_portfolio_roi_report_data(` at `scripts/analysis/portfolio_roi_report.py:4632` passes the real computed `label_gate_status`, never a literal or a default. Report test 11 and AC 20 exercise it through `_run`.

**Import note (erratum e1):** lint-imports cannot confirm the `scripts/` → `breezy.runtime.exec_par_records` import, because `root_packages = ["breezy", "nautilus_trader"]` (`pyproject.toml:71`). No contract governs `scripts/`. The import is a pure codec module (`decode_record`, `OrderAnchor`, `EpochRow`, the key prefixes).

## 17 Risk register (changes to r2.3 §8)
- RESOLVED: "item 2a rejected" (§1.3, no fallback refusal).
- NEW MED: the anchor ingest is unwired in production (the §1.4 S0 threshold fails), so `n_open_anchors_without_fill` is `None`. Mitigation: fail-closed; it blocks #7 eligibility only under STALE; S0 records it.
- NEW LOW (replaced by erratum e1): a cancelled, expired or IOC-missed anchor keeps `n_open_anchors_without_fill` > 0 for good, because there is no durable terminal-close record. Mitigation: fail-closed. It blocks only #7 eligibility under STALE, and it clears only on OK freshness, a path this count does not block (L-48). A future per-coid close record (out of scope) would clear it.
- NEW LOW (erratum e1): SELL exit orders and fills are outside the count, because `record_posted` writes BUY entries only (`exec_par_counter_ingest.py:425-430,446-448`). Exits are unarmed today. Mitigation: arming exits must first extend the count, or #7 must treat STALE as ineligible outright.
- NEW MED: §6.2 S0 FAIL means an open position refuses #5 sizing for F. Mitigation: the blocker is recorded, never silent.

## 18 Invariants (binding on every implementer brief; restated)
- Nautilus Trader is immutable.
- `allow_short` stays `False`.
- Leg sign comes only via `leg_of_symbol` (`src/breezy/domain/instrument_leg.py:58`). This delta adds no leg derivation.
- NO-SEND: the report and the accessor make no network calls; the anchor count reads the existing read-only DB fetch; every test runs via `scripts/ci/run_tests_no_egress.sh`.
- Never assign, default or propose the operator day, position or month caps, and never name their environment variables. Live-trading enablement is untouched.
- Never weaken a safety, settlement, contract or pin test. The TE-1 guard is byte-unchanged, pins keep `==`, and the listed pin edits only add arguments.
- New test files are classified in `scripts/ci/gate_reviewed.json` and timed in `scripts/ci/gate_durations.json`.
- `lint-imports` runs after every slice (`python -m importlinter` is a no-op).
- No `dataclasses.asdict`/`astuple`.
- Report files are never hand-edited. No dollar figure enters git, the plan or an alert.

## 19 Confidence
0.85 overall.

| Area | Confidence |
|---|---|
| Code facts | 0.92 (read at `0bbddc14`) |
| Freshness rule | 0.85 (the anchor wiring is S0) |
| Gate scope | 0.88 |
| Reachability | 0.7 (OPS-4) |
