# AUD-06b review — round 5 (delta, FINAL) — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-06b-bounded-allocation-sizing.md
sha256: d3d26c2fba84fb0d812c7030b4770bf76ae1110d316e5c42b321c8b21a90dec0
Round: 5 (delta review of the mle-named defect's fix, plus the other reviewer's material finding)

## Fix verification: the fifth (evidence-writer) test

§6 D6-R's R2 row now separately names which test enforces which half instead of claiming both are
covered by one test: `test_no_alert_payload_detail_carries_a_quantity_and_a_price_together` for the
alert-payload half, and the **new** `test_no_evidence_artefact_writer_copies_the_duplicate_fill_records_qty_and_price_together`
for the evidence-writer half — scanning every module under `scripts/analysis/` and `scripts/venue/`
that writes a `docs/evidence/**` artefact, plus `persistence/residual_fills.py`/`realized_draws.py`,
forbidding the qty+price PAIR with a negative control for either value alone. This closes the gap I
named in round 4 (a claimed-but-untested enforcement mechanism).

**Source re-verified:** `DUPLICATE_FILL_KEY_PREFIX = "continuous_rung_hold/duplicate_fill/"` at
`trial_day_latch.py:290` — CONFIRMED. The persisted payload (`{"v":1,"qty":str(qty),"fillPx":
str(fill_px),"fee":str(fee),"tsNs":ts_ns,"station":station,"climateDay":climate_day}`) at
`trial_day_latch.py:893-904` — CONFIRMED, `qty`/`fillPx`/`fee` keys present exactly as cited (found at
`:896-898` within the cited range).

## Verification of the other reviewer's MATERIAL finding and its fix (the widened grep/enumeration)

Independently re-ran the exact cited command myself, without trusting either the plan's or the reviser's
re-run: `/usr/bin/grep -rn --binary-files=without-match "qty=" src/breezy/strategy
src/breezy/adapters/polymarket_us/exec src/breezy/runtime` returns **58 matches** — CONFIRMED exact
against the plan's restated count. Spot-checked three of the newly-added sites directly against source,
all exact:
- `cli_settlement_print_lock/strategy.py:938` — `f"ORDER {contract.instrument_id} qty={signed_delta:+.1f}
  " f"limit={limit_price} intent=LONG_YES edge={decision.edge:.3f} ..."` — CONFIRMED, qty+limit+edge
  co-emitted, matching R7's disposition and independently confirming the plan's own finding that `edge`
  belongs on the widened forbidden-token list.
- `runtime/backtest_harness.py:845` — `f"{position.instrument_id} qty={position.quantity} "
  f"(avg_px_close={position.avg_px_close})"` — CONFIRMED, matching R8.
- `monitor_records.py:355-360` — `fill_px`/`held_qty` co-persisted in one `to_dict()` mapping —
  CONFIRMED, matching the newly-found R11 class.

## A new, minor defect found on this pass: the file count in the "complete enumeration" claim is wrong

I ran `/usr/bin/grep -rl --binary-files=without-match "qty=" src/breezy/strategy
src/breezy/adapters/polymarket_us/exec src/breezy/runtime | wc -l` — the file count is **20**, not the
**14** the plan's §6 D6-R lead-in states ("It returns 58 text matches across 14 files"). I then checked
whether the underlying R1-R13 accounting actually covers all 20 files, since the previous MATERIAL
finding was specifically about the completeness claim not matching reality: enumerating every file
named across R1-R13 (`continuous_strategy.py`, `strategy.py` [current_rung_hold], `backtest_only.py`,
`cli_settlement_print_lock/strategy.py`, `backtest_harness.py`, `running_extreme_lock/strategy.py`,
`forecast_mispricing/strategy.py`, `calibration_mean_reversion/strategy.py`,
`forecast_revision/strategy.py`, `forecast_revision/decision.py`, `exit_authorization.py`,
`monitor_records.py`, `monitor_evidence.py`, `position_monitor.py`, `exit_decider.py`,
`paper_replay.py`, plus R13's four adapter/exec/runtime files) totals exactly **20**, matching my grep
byte-for-byte. **The detailed row-level accounting is genuinely complete and correct** — the match count
(58) is right, every file is actually covered by an R-row — but the **summary sentence's file count is
a transcription/arithmetic error** (14 instead of 20). Given the entire point of this revision's fix is
to make the completeness claim "checkable, not asserted," a checkable headline number that itself fails
a check is a real, if narrow, defect — precisely the same class of error (a stated summary number not
matching the artefact) that produced the original MATERIAL finding, now recurring in miniature in the
fix for it.

## Fresh review — no other new defect found

The `_REGISTERED_CONSTANT_QTY_SITES` expression-pinned allowlist mechanism, the widened forbidden-token
list (`avg_px_open`, `avg_px_close`, `limit`, `fee`, `edge`), and AC #5's grep-output-plus-row-mapping
requirement were all independently re-checked and are sound.

## Per-criterion points (cap in parentheses)

- Fidelity to the gap and completeness (20): **20** — the co-emission surface is now genuinely,
  verifiably complete (58/58 matches accounted for across all 20 files); unaffected by the headline
  typo.
- Technical correctness and evidence grounding (20): **19** — every load-bearing citation independently
  re-verified exact; 1 point withheld for the "14 files" vs. actual 20-file discrepancy in the plan's
  own "checkable, not asserted" completeness claim.
- Implementation specificity and feasibility (15): **15** — the fifth test, the widened scope, and the
  allowlist mechanism are all concretely specified and independently verified against source.
- Acceptance criteria and validation quality (20): **19** — AC #5's grep-to-table mapping requirement is
  strong; 1 point withheld because it requires the match COUNT and per-match row mapping but not that
  the plan's own prose file-count matches `len(set(files))` from the same command, which is exactly
  where the residual error above slipped through.
- Autonomous operation, failure handling, recovery (15): **15** — unaffected.
- Portfolio objective alignment, scope, dependencies (10): **10** — unaffected.

**Total: 98/100**

## Remaining defect and required change

1. **MINOR.** §6 D6-R's lead-in states the grep returns matches "across 14 files"; the actual file count
   (independently re-run) is 20, and the underlying R1-R13 accounting correctly covers all 20 — only the
   summary sentence is wrong. **Required change:** correct "14 files" to "20 files" in §6, and extend the
   scope-equals-command-scope test (already specified for the directory trees) to also assert the
   reported file count in the evidence pack equals `len(set(f for _, f, _ in matches))` from the same
   grep run, so a future drift in this exact number is caught mechanically rather than by re-review.

## Blockers

- **BLOCKER-A (AUD-06a):** the validated qty envelope and its staleness predicate — unchanged, genuine.
- **BLOCKER-B (AUD-02):** a demonstrated edge for this family, itself downstream of AUD-05 — unchanged,
  genuine.
- **BLOCKER-C (operator):** R-12, the session order-count ceiling question — unchanged, genuine,
  operator-only.
- **BLOCKER-D (operator):** the per-position spend question — unchanged, genuine, operator-only.
