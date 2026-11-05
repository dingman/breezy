# Venue fee schedule pin — 2026-09-18

Descriptive only (L-21): theta is a venue fact. This note does not compare it
to a price, a base rate, or an edge claim.

The pin is `Decimal("0.06")`. No refusal is weakened. The 2026-09-17 move to
`0.0695` is recorded here, never absorbed as a code fix.

## Declared taker theta

Source: `docs/evidence/venue/polymarket_us/docs_snapshots/fees_2026-08-25.md:27`

|                  | Theta   | Max (p = $0.50) |
| ---------------- | ------- | ---------------- |
| **Taker Fee**    | 0.06    | $1.50           |

Adapter constant (public because the schedule-pin capture test is the only
legal cross-package reader — nothing in `src/` may import it):

`src/breezy/adapters/polymarket_us/fees.py`
`DOCUMENTED_TAKER_FEE_COEFFICIENT = Decimal("0.06")`

## Tracked wire corpus (capture-date keyed)

Refresh policy: the wire-theta exact-set is keyed by capture date. The
tracked raw corpus is the 2026-08-25 SHA256SUMS snapshot under
`docs/evidence/venue/polymarket_us/raw/`. A new capture date is a new
member of the exact-set, added in the same commit that vendors the
payloads — widen, never relax `==`.

Exact-set asserted by `tests/unit/test_polymarket_us_fee_schedule_pin.py`:

```
{("2026-08-25", Decimal("0.06"))}
```

729 captured market objects, every `feeCoefficient` is `0.06`. This corpus
is now demonstrably stale relative to the live wire (see 2026-09-17 below).

Do **not** copy the 2026-09-17 runtime tape or recorder definitions into
`docs/evidence` in this item. That is a separate evidence-capture follow-on.

WP-0d's "capture-test extend" was read as "reuse the existing drift-capture
PATTERN", not "edit `test_polymarket_us_fee_coefficient_source.py`" (which
importlib-loads a script at import time at `:61`).

## 2026-09-17 diagnosis: drifted theta = 0.0695

The live family refused correctly. The journal cannot tell absent-theta from
drifted-theta (both land on `fee_schedule_mismatch`); the offer tape can,
and did.

### Journal (exactly 3 lines)

From `~/.local/share/breezy/logs/breezy-trade-20260917T165020Z.log`:

```
2026-09-17T17:00:00.610319588Z [WARN] BREEZY-L001.breezy: breezy alert event=FEE_SCHEDULE_MISMATCH_REFUSALS site=ContinuousRungHoldStrategy-MIA severity=WARN detail=1 order(s) refused as fee_schedule_mismatch
2026-09-17T18:00:00.205243888Z [WARN] BREEZY-L001.breezy: breezy alert event=FEE_SCHEDULE_MISMATCH_REFUSALS site=ContinuousRungHoldStrategy-MDW severity=WARN detail=1 order(s) refused as fee_schedule_mismatch
2026-09-17T20:00:01.279717350Z [WARN] BREEZY-L001.breezy: breezy alert event=FEE_SCHEDULE_MISMATCH_REFUSALS site=ContinuousRungHoldStrategy-SFO severity=WARN detail=1 order(s) refused as fee_schedule_mismatch
```

A whole-log search for `fee_coefficient` / `fee schedule` / `feeCoefficient`
outside those three lines returns zero hits: the journal carries no theta
and no instrument.

### Offer tape 2026-09-17 (exactly 6 rows, all `0.0695`)

Path: `~/.local/share/breezy/catalog/quote_tape/decisions/offer_tape_2026-09-17.jsonl`.
Quoted verbatim:

```
{"admission_reason": null, "ask": "0.26", "break_even": null, "climate_day": "2026-09-17", "decision": "refuse", "exit_decision": null, "exit_limit_price": null, "exit_reason_code": null, "exit_rule": null, "expected_settlement_value": null, "fee_coefficient": "0.0695", "hour_lst": 12, "illegal_cell": false, "instrument_id": "tc-temp-miahigh-2026-09-17-lt84f^no.POLYMARKET_US", "m_code": 0, "minutes_since_window_open": 0, "observed_at_ns": 1789648500000000000, "p_bound": null, "prior_eligible_snaps": 0, "quote_age_ns": null, "reason": "fee_schedule_mismatch", "running_max_exact": false, "running_max_lower": "82", "running_max_upper": "83", "shadow_fill_event": false, "shadow_rest_margin": null, "shadow_rest_price": null, "shadow_rest_reason": "fee_schedule_mismatch", "shadow_rest_state": "NONE", "side": "NO", "size": 51, "source": "no_side_shadow", "staleness_ns": 1500508471934, "station": "MIA", "trigger": "no_side_shadow", "ts_event": 1789664400508471934, "width_code": 2}
{"admission_reason": null, "ask": "0.8", "break_even": null, "climate_day": "2026-09-17", "decision": "refuse", "exit_decision": null, "exit_limit_price": null, "exit_reason_code": null, "exit_rule": null, "expected_settlement_value": null, "fee_coefficient": "0.0695", "hour_lst": 12, "illegal_cell": false, "instrument_id": "tc-temp-miahigh-2026-09-17-lt84f.POLYMARKET_US", "m_code": 0, "minutes_since_window_open": 0, "observed_at_ns": 1789648500000000000, "p_bound": null, "prior_eligible_snaps": 0, "quote_age_ns": null, "reason": "fee_schedule_mismatch", "running_max_exact": false, "running_max_lower": "82", "running_max_upper": "83", "shadow_fill_event": false, "shadow_rest_margin": null, "shadow_rest_price": null, "shadow_rest_reason": "fee_schedule_mismatch", "shadow_rest_state": "NONE", "side": "YES", "size": 117, "source": "quote", "staleness_ns": 1500508471934, "station": "MIA", "trigger": "quote_tick", "ts_event": 1789664400508471934, "width_code": 2}
{"admission_reason": null, "ask": "0.51", "break_even": null, "climate_day": "2026-09-17", "decision": "refuse", "exit_decision": null, "exit_limit_price": null, "exit_reason_code": null, "exit_rule": null, "expected_settlement_value": null, "fee_coefficient": "0.0695", "hour_lst": 12, "illegal_cell": false, "instrument_id": "tc-temp-mdwhigh-2026-09-17-gte80lt81f^no.POLYMARKET_US", "m_code": -2, "minutes_since_window_open": 0, "observed_at_ns": 1789666800000000000, "p_bound": null, "prior_eligible_snaps": 0, "quote_age_ns": null, "reason": "fee_schedule_mismatch", "running_max_exact": false, "running_max_lower": "78", "running_max_upper": "80", "shadow_fill_event": false, "shadow_rest_margin": null, "shadow_rest_price": null, "shadow_rest_reason": "fee_schedule_mismatch", "shadow_rest_state": "NONE", "side": "NO", "size": 100, "source": "no_side_shadow", "staleness_ns": 1200068983839, "station": "MDW", "trigger": "no_side_shadow", "ts_event": 1789668000068983839, "width_code": 0}
{"admission_reason": null, "ask": "0.53", "break_even": null, "climate_day": "2026-09-17", "decision": "refuse", "exit_decision": null, "exit_limit_price": null, "exit_reason_code": null, "exit_rule": null, "expected_settlement_value": null, "fee_coefficient": "0.0695", "hour_lst": 12, "illegal_cell": false, "instrument_id": "tc-temp-mdwhigh-2026-09-17-gte80lt81f.POLYMARKET_US", "m_code": -2, "minutes_since_window_open": 0, "observed_at_ns": 1789666800000000000, "p_bound": null, "prior_eligible_snaps": 0, "quote_age_ns": null, "reason": "fee_schedule_mismatch", "running_max_exact": false, "running_max_lower": "78", "running_max_upper": "80", "shadow_fill_event": false, "shadow_rest_margin": null, "shadow_rest_price": null, "shadow_rest_reason": "fee_schedule_mismatch", "shadow_rest_state": "NONE", "side": "YES", "size": 125, "source": "quote", "staleness_ns": 1200068983839, "station": "MDW", "trigger": "quote_tick", "ts_event": 1789668000068983839, "width_code": 0}
{"admission_reason": null, "ask": "0.73", "break_even": null, "climate_day": "2026-09-17", "decision": "refuse", "exit_decision": null, "exit_limit_price": null, "exit_reason_code": null, "exit_rule": null, "expected_settlement_value": null, "fee_coefficient": "0.0695", "hour_lst": 12, "illegal_cell": false, "instrument_id": "tc-temp-sfohigh-2026-09-17-gte69lt70f^no.POLYMARKET_US", "m_code": -1, "minutes_since_window_open": 0, "observed_at_ns": 1789673400000000000, "p_bound": null, "prior_eligible_snaps": 0, "quote_age_ns": null, "reason": "fee_schedule_mismatch", "running_max_exact": false, "running_max_lower": "68", "running_max_upper": "69", "shadow_fill_event": false, "shadow_rest_margin": null, "shadow_rest_price": null, "shadow_rest_reason": "fee_schedule_mismatch", "shadow_rest_state": "NONE", "side": "NO", "size": 99, "source": "no_side_shadow", "staleness_ns": 1801220111398, "station": "SFO", "trigger": "no_side_shadow", "ts_event": 1789675201220111398, "width_code": 0}
{"admission_reason": null, "ask": "0.28", "break_even": null, "climate_day": "2026-09-17", "decision": "refuse", "exit_decision": null, "exit_limit_price": null, "exit_reason_code": null, "exit_rule": null, "expected_settlement_value": null, "fee_coefficient": "0.0695", "hour_lst": 12, "illegal_cell": false, "instrument_id": "tc-temp-sfohigh-2026-09-17-gte69lt70f.POLYMARKET_US", "m_code": -1, "minutes_since_window_open": 0, "observed_at_ns": 1789673400000000000, "p_bound": null, "prior_eligible_snaps": 0, "quote_age_ns": null, "reason": "fee_schedule_mismatch", "running_max_exact": false, "running_max_lower": "68", "running_max_upper": "69", "shadow_fill_event": false, "shadow_rest_margin": null, "shadow_rest_price": null, "shadow_rest_reason": "fee_schedule_mismatch", "shadow_rest_state": "NONE", "side": "YES", "size": 3, "source": "quote", "staleness_ns": 1801220111398, "station": "SFO", "trigger": "quote_tick", "ts_event": 1789675201220111398, "width_code": 0}
```

### Offer tape 2026-09-16 baseline

`offer_tape_2026-09-16.jsonl`: **53624** rows, **all** `fee_coefficient` =
`"0.06"`.

Open, out of scope: why 2026-09-17 holds 6 rows against 2026-09-16's 53624.

### Re-parse of recorder instrument definitions (step 1a)

The recorder stores parquet `BinaryOption` under
`~/.local/share/breezy/catalog/quote_tape/polymarket_us/data/binary_option/<slug>.POLYMARKET_US`,
not JSON market payloads, so `parse_binary_option` cannot be re-invoked on
wire JSON. The catalogued instruments **are** the persisted output of
`parse_binary_option`.

Command (read-only):

```
.venv/bin/python -c '
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
cat = ParquetDataCatalog("/home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us")
by_id = {str(i.id): i for i in cat.instruments()}
'
```

then read `instrument.info["fee_coefficient"]`, `maker_fee`, `taker_fee`,
and `info["fee_schedule_status"]` for the six refused slugs.

| Outcome | Meaning | This run |
|---|---|---|
| `0.0695` | Wire drift confirmed; tape agrees with the parser output. | **THIS RUN** — all six slugs `fee_coefficient='0.0695'`, status `KNOWN`, `maker_fee=taker_fee=Decimal('0.0695')` |
| `0.06` | Tape writer, not the venue, produced `0.0695`. | not this run |
| absent / UNKNOWN | Definitions predate the theta field on that path. | not this run |

## In-scope pin sites (live decision path)

The guards read `instrument.maker_fee`, not `info[fee_coefficient]`. That is
safe only because `parsing.py:1460-1461,1537-1538` write theta onto both
flat fields. Cited, not rewritten:
`test_the_flat_fee_fields_carry_theta_not_a_zero_and_not_a_notional_rate`
and `test_the_flat_fields_are_theta_itself_and_not_a_notional_rate` in
`tests/unit/test_polymarket_us_parsing.py`.

| Site | What is pinned |
|---|---|
| `fees.py` `DOCUMENTED_TAKER_FEE_COEFFICIENT` | `Decimal("0.06")` |
| `current_rung_hold/config.py:226` `required_fee_coefficient` | `Decimal("0.06")` |
| `ladder_ev/config.py:131` `required_fee_coefficient` | float `0.06` |
| `strategy.py:708` `_guarded_fee_coefficient` | reads `maker_fee` after the venue guard; not a literal |
| `continuous_strategy.py:2451` `_guarded_fee_coefficient` | the copy that fired on 2026-09-17; same shape, not refactored |
| `scripts/analysis/resting_bid_core.py:134` `TAKER_FEE_COEFFICIENT` | `Decimal("0.06")` |

`decision.py` refusal stays `!=`. No `isclose`, no tolerance, no range.

Maker rebate `MAKER_FEE_COEFFICIENT = Decimal("-0.0125")` is a different
coefficient and is not fused with theta. Taker rebate tiers change the
effective fee, not theta; out of scope.

## Study-script copies (out of the live path; asserted so the exclusion is visible)

Venue-keyed exact-set in the capture test. Kalshi's `0.07` is a required
member. `k1_cheap_open_settlement.py:1450` is an inline fallback, named
only, not asserted.

## Classifier

`is_venue_touching("src/breezy/adapters/polymarket_us/fees.py", tree)` is
**True** (C1 path prefix). `EGRESS_SCAN_ROOTS = ("src", "scripts")`; the new
test file is not in that scan.

## Continuation

A live pre-registered family is refusing every order because the venue moved
theta. Resolving that is a new family revision plus D0, **never** an
in-place pin edit of `required_fee_coefficient` or of this constant. This
item ships the pin and the record; it does not retune a running family.
