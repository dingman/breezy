**Score 93/100. Verdict: READY-WITH-CHANGES.** There are no BLOCKERs and no HIGHs. Two MED and one LOW remain; all three are S0-9 wording that I think can be fixed in a few lines. I did not run any tests. The checks below are greps and source reads only.

## 1. Merge rulings and r3.1-python findings in r3.2

| Item | Where in r3.2 | Status |
|---|---|---|
| 1 | S0-9 table at :191-204. The anchored regex is at :195, `:4708` is listed as a non-hit at :203, and `not_wired` is added at :201. | applied |
| 2 | P26 at :78. The general re-pin rule is at :105-107. WP-A, WP-B and WP-C re-pins are at :109-111, and the dedupe move is in WP-A at :244. Rollback carries both producers at :429, :494 and :498. | applied |
| 3 | WP-A widening row at :254-257, with a rename and no deletion. The `producer_unpinned` assertion and the `label_run.py:7` docstring update are at :240. | applied |
| 4 | `factory(args) -> UnitWiring` at :228. All 7 sentinels are at :229-236. `_resolve_factory` is used by both `main` and `_measure_main` at :238-239. | applied |
| 5 | The import-linter contract is dropped. The AST guard uses the fully qualified name at :308-312. | applied |
| 6 | Derivation order and tests at :130-134 and :352-353. | applied |
| 7 | The abort path at :426-433 states exit 0. | applied |
| 8 | S0-5 at :183 and the WP-B runtime assertion at :303-305. | applied |
| 9 | Risks at :461. | applied |
| 10 | R5 at :121-125 and WP-B at :301. | applied |
| 11 | S0-1 at :168. | applied |
| 12 | `sys.executable` and `PYTHONPATH` at :278. | applied |
| 13 | P36 at :88 and S0-12 at :206. | applied |
| r3.1-python M-1 (`\bnot_wired\b`) | :201 | applied |
| r3.1-python note: `missing_aut6_reading()` | :233 | applied |
| r3.1-python note: module-attribute call | :256 | applied |

## 2. Code premises checked

- **`not_wired` branches:** `label_run.py:858` and `:893` match, and the docstring is `:7`. The test is `test_aut2_label_run.py:581-591`.
- **`UnitWiring` and `UnitFactory`:** `UnitWiring` is frozen with 7 fields (`label_run.py:684-697`), and `UnitFactory = Callable[[Namespace], UnitWiring]`.
- **Pin state:** `autonomy_health_cli.producer_pin_state` is at `:90-96`, and `pins.py:19-21` pins only `aut6.health`.
- **Test lines:** `test_autonomy_closure.py:90` is `== {"breezy.runtime.autonomy_health_cli"}`. `test_autonomy_pins.py:101`, `:599`, `:688` and `:745` match.
- **Wrapper:** `portfolio-roi-run.sh:103-109` prints the NO_INPUT token and `exit 0`. An absent marker exits 1 at `:112-115`.
- **Report script:**
  - `_LabelView.c2_rows` is at `:4068`.
  - `_gate_status_of` is at `:4077`.
  - `_unlabelled_fq_fills` is defined at `:4109`.
  - `total_realised_pnl_all_settled` is at `:4241`.
  - The overlap guard is at `:4206`.
  - `_LABEL_GATED_STATUSES` is at `:2217`.
- **Schema version:** `PORTFOLIO_ROI_SCHEMA_VERSION = 4` is at `:2198`, and the known set is at `:2208`.
- **Other symbols:** `missing_aut6_reading` exists in `memory_gate.py:89`. `admissible_rows` is at `label_store.py:408`. `_marker_ns` is at `:544`. `oldest_marker_ns` does not exist yet, which is consistent with the plan adding it.

## 3. S0-9 patterns re-run, with `--exclude-dir=__pycache__`

| Pattern | Result |
|---|---|
| Schema regex | Exactly the 10 P27 lines: 283, 423, 2234, 2295, 4424, 5165, 5187, 5909, 5921 and 5922. |
| `frozenset({1, 2, 3, 4})` | Only `test_portfolio_roi_report.py:5910`. |
| `\bnot_wired\b` | Exactly `label_run.py:7`, `:858`, `:893` and `test_aut2_label_run.py:591`. |
| `NO_INPUT -- upstream skipped` | `test_autonomy_units_programme.py:38` and `:266`, plus `test_portfolio_roi_run_no_input.py:70`. All are covered by WP-C rows. |
| `\{"aut6\.health"\}` | Only `test_autonomy_pins.py:101`. |
| `CLOSURE_MODULES` | Also hits `test_autonomy_pins.py:747` and `:764`, which WP-A's list at :253 does not name. |
| `breezy-autonomy-failed@` | About 40 hits across roughly 15 unrelated test files and fixtures. |

## Findings

- **[MED] S0-9 `breezy-autonomy-failed@` row (plan :200 and :191).**
  - The pattern returns about 40 hits in unrelated files, for example `test_capture_units.py`, `test_recorder_watchdog.py` and the `capture_units` fixtures.
  - The rule "every hit must be in a widening list or known non-hits" therefore cannot be satisfied as written.
  - Fix: restrict the pattern to the label unit, or add a "hits expected, WP-C reviews only the label and deploy rows" clause. The fixture hit at `fixtures/aut2_units/breezy-label-outcomes.service:12` is the one that matters.
- **[MED] `CLOSURE_MODULES` hits at `test_autonomy_pins.py:747` and `:764` (plan :199 and :253).**
  - These two tests, `regen.regenerate(...) == committed` and a `render_manifest` drift check, will also move when the manifest gains the `aut2.label` entry.
  - The plan lists only `:688` and `:745`. `:747` is on the same assertion as `:745`, and `:764` reads the same manifest.
  - Fix: name 747 and 764 in the WP-A list, or state that they follow the regenerated manifest.
- **[LOW] Plan :408 (WP-D).**
  - `_measure_main` runs the `is_measure_unit` and MemAvailable gates before the producer-pin refusal. The plan assumes `aut2.label` is already pinned from WP-A, so this is fine, but the ordering is worth a sentence.

## Goal-state check

- I found no blocker to reaching the 34 / 4 / −2.63 / FQ −2.17 / crh −0.46 / fees 0.27 numbers.
- `portfolio_roi` NO_INPUT is cleared by the wrapper change in WP-C and the `GATED_ACCOUNTING_ONLY` / `roi_accounting_status=OK` path.
- The plan's per-fill statuses, drills and hard stops are internally consistent.
- Nothing in the plan violates the binding invariants:
  - The plan touches no arming, halts or operator caps.
  - Every test change is either stricter or a reviewed row.
  - The `not_wired` test is renamed rather than deleted.
  - The NO-SEND guard stays in the focused gate (:438).

Relevant file: `/home/jon/breezy/docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/TE-1_plan_r3_2.md`