# Ruling: NO-side position shape on `/v1/portfolio/positions` (2026-09-16)

**Status: SIGNED** (prediction-market-reviewer 2026-09-16: SIGN-WITH-EDITS, edits applied; signed by the commit that adds this file). This is the artefact
`mark_no_side_position_captured_cli` records (`--ruling-path` + `--ruling-sha`); writing that key ends the
bounded first-order containment window of the NO-side amendment §8 item 4 (S5 plan E2-1(ii), E3-6, E4-3).

**Related:** `docs/plans/NO_SIDE_S5_EXEC_2026-09-14.md` E2-1, E5-4; `docs/evidence/PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md`
§8; `docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md` Appendix A.1/A.2; memory note
"venue-nets-no-holding-as-short-yes".

---

## 1. What was unknown

Every `/v1/portfolio/positions` response captured on this host before 2026-09-16 was `{"positions":{}}`. The
adapter therefore mapped positions by slug onto the YES instrument only (`_map_position`, client.py; `_find_instrument`
YES-only bijection) and merely REPORTED a negative `netPosition`. How a held NO is signed, denominated and keyed was
undecidable, so the first live NO order (MIA 2026-09-15 18:12Z, `CGW8DJ23PVB2`) opened the containment: no further NO
arm account-wide until the shape is captured and ruled.

## 2. Evidence (values, captured while the four 2026-09-15 positions were open)

`scripts/venue/polymarket_us_positions_value_capture.py` → `PRIVATE_v1_portfolio_positions_open_positions_20260916.positions.json`
(0600, gitignored; HTTP 200, 4 positions, redacted keys `eventId`, `id`); shape-only twin
`PRIVATE_v1_portfolio_positions_open_positions_20260916.probe.json`.

| slug | `marketMetadata.outcome` | `netPosition` | `qtyAvailable` | `qtyBought` / `qtySold` | `avgPx` | `cost` | `cashValue` | `realized` | `expired` |
|---|---|---|---|---|---|---|---|---|---|
| tc-temp-mdwhigh-2026-09-15-gte80lt81f | Yes | 1 | 1 | 1 / 0 | 0.1200 | 0.1200 | 0.0100 | 0 | False |
| tc-temp-mdwhigh-2026-09-15-gte82lt83f | Yes | 1 | 1 | 1 / 0 | 0.2500 | 0.2500 | 0.0100 | 0 | False |
| tc-temp-miahigh-2026-09-15-gte92lt93f | **No** | **−1** | **−1** | **0 / 1** | 0.0900 | 0.0900 | 0.0100 | 0 | False |
| tc-temp-sfohigh-2026-09-15-gte71lt72f | Yes | 1 | 1 | 1 / 0 | 0.4500 | 0.4500 | 0.0100 | 0 | False |

Cross-checks: the MIA NO fill was submitted at instrument price 0.09 (wire 0.91) with fill commission 0.00 in the trade log
(`PositionOpened avg_px_open=0.09`); the position payload's own `fees` field is `null` for this leg, not `0`. The YES fills
were 0.11 / 0.24 / 0.44 with fee 0.01 each (payload `fees` 0.0100). Closing-order preview 03:19Z (Appendix A.2): NO + `ORDER_ACTION_SELL` echoes
`side=ORDER_SIDE_BUY`, `intent=ORDER_INTENT_SELL_SHORT` — the venue treats closing a NO as buying back the YES it nets short.

## 3. Ruling

1. **Keying.** One position object per market slug; the leg is `marketMetadata.outcome` (`"Yes"` / `"No"`).
2. **Sign.** A held NO is reported as a **short of YES**: `netPosition = −q`, `qtyAvailable = −q`, `qtySold = q`,
   `qtyBought = 0`. A held YES is `netPosition = +q`, `qtyBought = q`.
3. **Breezy mapping.** `outcome == "No"` with `netPosition < 0` → **LONG |netPosition| on the NO leg instrument**
   (`<slug>^no.POLYMARKET_US`), `outcome == "Yes"` with `netPosition > 0` → LONG on the YES instrument (unchanged).
   Breezy stays long-only per instrument; `allow_short` stays False.
4. **Contradictions fail closed.** `outcome == "No"` with a positive `netPosition`, or `"Yes"` with a negative one, or
   an absent `outcome` with a negative `netPosition`, is a mapping error for that position (reported, never guessed).
5. **Denomination.** `avgPx` and `cost` are in the **held leg's** price and are **fee-inclusive** (YES 0.12 = 0.11 + 0.01).
   NO-denomination of the NO leg is confirmed by the fill-price match (instrument price 0.09 = `avgPx` 0.0900, not the wire
   0.91); the fee argument alone cannot distinguish, because the venue fee `Θ·C·p·(1−p)` is symmetric under `p ↔ 1−p`. They
   are NOT complemented when mapping the NO leg. `cashValue` is the venue mark, not a fill.
6. **Closing.** The order that returns `netPosition −q → 0` is NO + `ORDER_ACTION_SELL` at wire `1 − p`; its echo is
   `(ORDER_SIDE_BUY, ORDER_INTENT_SELL_SHORT)`; the exit echo table in `leg_prices.py` is pinned to this pair.
7. **Reconciliation.** Venue `netPosition` is compared to Breezy positions only after applying the leg sign; a NO LONG on
   `<slug>^no` and a YES LONG on `<slug>` are different instruments and never sibling-collide in the never-arm walk.

## 4. Consequences

- `parse_position_status_report` / `_map_position` implement §3 (this ruling's paired code change, tested per leg, L-44).
- Containment: `exec/polymarket_us/no_side/position_shape_captured` is written by the CLI with this file's path and the
  sha of the commit that added it; NO arming resumes under the registered amendment thereafter.
- `derive_position_cost_basis` (reports.py) returns `None` whenever `qtySold != 0`, which by §3.2 is every NO holding, and
  `avgPx` has no pricing consumer in the adapter today: §3.5 governs future consumers (audit, dashboards, reconciliation).
  Do not "fix" the cost-basis fallback for NO legs via `cost/qtySold` without re-reading §3.5. `Position.unrealized_pnl`
  on `<slug>^no` is correct only because that instrument's quotes are NO-denominated (`no_ask = 1 − yes_bid`, S2).
- Unchanged: the two operator caps; PREREG v3 §3/§5/§9; the NO fill of 2026-09-15 stays residual by amendment §8.

## 5. Open

- `qtyAvailable` semantics after a partial close and `realized` sign on a closing fill are unobserved (no close has ever
  been sent); they are retired by PREREG v4 §11 step 3 (1-contract positive control), not by this ruling.
