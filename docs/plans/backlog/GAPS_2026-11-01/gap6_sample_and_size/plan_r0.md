# GAP-6 SAMPLE-AND-SIZE — plan r0 (2026-11-01)
Status: r0, peer review pending. Reviewers: **architect** + **prediction-market-reviewer**. Written read-only; the coordinator lands it.

## 1 Objective
- The single objective (realised win rate > price + fee, proven) is limited by **n per calendar day**. PM.us has 5 stations, HIGH only in the tape. At qty 1 the MDE is 19.8¢ at 26 days, and D_c is 55 d for 10¢ at R=3 (r1 delta D6). Waiting is the only PM.us lever.
- This gap adds the one structural **station-day multiplier**: Kalshi's 24 cities × HIGH/LOW (48 series, `KALSHI_DAILY_TEMP_SERIES_ENUMERATION_2026-09-04.md:12-40`).
  - The first measurement is a **book count**: are executable tail NO asks actually there? No model is used.
- It also writes the **size arithmetic** so the operator can make the q decision. q is never assigned here.

## 2 Preconditions and dependencies
- Independent of GAPs 1–5. This is a parallel multiplier: it reads no forecast, no PM.us tape and no exec code.
- Facts already in hand, so these are not re-measured:
  - **Settlement:** Kalshi `expiration_value` equals the NWS CLI final on 5185/5186 station-side-days, 24 cities, 07-05..10-30 (`docs/evidence/STRAT_DESIGN_2026-10-31/card_e_cli_vs_twc.md`). The K-2a Stage 0 n≥381 admission is therefore met venue-wide in substance. A peer ruling must say so before K-2a §3 is retired.
  - **Wire facts** (S0 §6.1–6.2): one book per ticker. A YES bid at X is a NO ask at 1−X. Depth arrives as `count_fp` levels sorted ascending. Fixture example: YES level `["0.0100","6677.00"]` = NO ask 0.99 × 6677.
  - **Nautilus 1.231.0 has no Kalshi adapter** (`docs/reference/nautilus/digests/prediction-markets-native-support.md:307`, fact 28). The adapter is a real gap and is K-2a WB-6.
  - **Branch `wip/kalshi-s4-registry`** is still a single commit: `.git/packed-refs:167` points at `58280b6` (base d2faeab, 8 files, +618/−17). `sites.toml` covers only the 4 shared cities (K-1 memo §5; K-2a §6). Phase 1 reuses nothing from it. The disposition stays the K-2a plan: fresh branch plus hand port.
- **Governance precondition:** RA-13 §4 / K-2a §0 allow Kalshi K-2b work only after a programme KILL. Running this capture needs the operator decision in §8 D-1 (r1 delta decision 3, "Kalshi capture in parallel"). Card E's settled-market fetch is the precedent for a desk GET.

## 3 Scope
- **New:** `scripts/analysis/kalshi_depth_census.py` with two subcommands:
  - `capture`: GET-only order-book snapshots.
  - `census`: book counts.
  - Transport: reuses `KalshiHttp` (`scripts/analysis/k1_kalshi_prior.py:213, :880-937`) for pacing and 429 backoff. `k1_kalshi_prior.py` stays byte-unchanged.
- **Endpoints:** `GET /events?series_ticker=&status=open&with_nested_markets=true` to discover markets, then `GET /markets/{ticker}/orderbook` for each market. The batch endpoint is used only if its parameter limits are verified first (§9).
- **Stored per market per sweep (projected, deny-by-default keys):** ticker, event_ticker, series_ticker, strike_type, floor/cap_strike, ts, YES-bid levels and NO-bid levels (top 10 each).
  - No raw responses are stored. Each day is one immutable `<UTC-date>.jsonl` written create-exclusive under `~/.local/share/breezy/kalshi_depth/`.
- **Why not reuse the PM.us recorder natively:** the PM.us recorder is a `LiveMarketDataClient` bound to the PM.us WebSocket and instruments. A Kalshi equivalent needs a provider, instruments and a data client, which is WB-6. It is a template, not a reuse.
  - Phase 1 is therefore a script, not an adapter.
  - Phase 2 (only after PASS) converts to `OrderBookDepth10` in a `ParquetDataCatalog` through WB-6. Composite ids use `^`/`:` separators, never `~`.
- **NOT in scope:**
  - any `src/breezy/adapters/kalshi/` file;
  - any egress-pin, permit, ledger or NO-SEND edit;
  - auth or account work, and any order;
  - forecasts or edge estimates;
  - the PM.us code paths;
  - rebasing `wip/kalshi-s4-registry`.

## 4 Steps
| # | Step | Inputs → outputs | Runs | Est. |
|---|---|---|---|---|
| S1 | Freeze the census PREREG (§5) | → `docs/plans/backlog/GAPS_2026-11-01/gap6_sample_and_size/prereg_census.md` + sha256 | coordinator; PM-reviewer co-sign | 0.5 d |
| S2 | Build `capture`/`census` RED-first (§6) | S1 → script + tests | Grok → Codex → Claude tdd-guide route; Claude runs the gate | 1 d |
| S3 | Launch capture: hourly sweep of all open events of the 48 series (~576 markets → ~14k GET/day, ≈0.16 rps mean, ≤4 rps peak) | → daily JSONL | bot script via `systemd-run --user`, MemoryMax=2G, `-p LimitNOFILE=524288`, stall watch armed in the launch turn | 21 cal. days |
| S4 | CLI truth backfill (tmax and tmin) for 19 new stations, plus the 5 cached stations extended past 2026-08-24 to now. **Not needed for the S5 count**; needed for any later win-rate read | AFOS CLI text via the Card E loader / `iem_cli_window_text` path (never `iem_cli_fetch.fetch`) → `settlement-alignment-cache` sibling, sha-manifested | sub-agent build, bot run | 1 d + run |
| S5 | ONE census look at day 21 | S3 files → `docs/evidence/kalshi_depth/CENSUS_<date>.{md,json}`, machine-written (L-75) | bot script | 1 h |
| S6 | Fee θ verification (below) | → `docs/evidence/venue/kalshi/FEE_THETA_<date>.md` | sub-agent desk work + operator browser step if needed | 0.5 d |

**Census definitions (frozen in S1):**
- NO ask = 1 − YES bid, taken level by level.
- A **tail-eligible station-side-day** is one where, at ≥1 complete sweep, some rung has a NO ask in **[0.97, 0.99]** inclusive with size ≥ 1.00 contract.
- The census reports, per station × side × local hour:
  - the count of such rungs;
  - displayed size at each level;
  - best NO ask;
  - the strike_type mix: `greater`/`less` edge markets vs `between`.
- Shared cities (NYC, MIA, MDW, LAX, SFO) are reported **separately**. Against PM.us they add zero independent n (K-1 memo §1).

**θ method (S0 §5.2 / §5.4):**
1. The series objects say `fee_type=quadratic`, `fee_multiplier=1`. Pull `get-series-fee-changes` for all 48 series (public GET) and record any multiplier change.
2. The coefficient is not in the API docs. Valid sources are:
   - (a) the operator fetches the fee-schedule PDF in a browser; or
   - (b) the first real fill's `average_fee_paid`, back-solved as fee/(p(1−p)·count). This needs an account, so it is operator-only and later.
   - Third-party 0.07 is inadmissible.
3. Rounding decides the tail economics. Ceil-to-6dp gives 0.137¢ at p=0.98; ceil-to-cent gives 1¢, which is half of a 2¢ gross margin.
   - Until both θ and rounding are verified, every hurdle is reported under **both** rounding hypotheses. No economic verdict is drawn.

## 5 Pre-registered acceptance and KILL (frozen at S1, before S3 starts)
- **Sweep complete:** ≥ 95% of markets listed in that sweep's open events returned a parseable book.
- **Day covered:** ≥ 20 of 24 hourly sweeps complete.
- **Capture ACCEPTED:** ≥ 14 covered days within the 21-day window. Otherwise the result is INCONCLUSIVE with no look spent. Re-arm once, then go to N-0.
- **KILL:** tail-eligible NO asks are **absent on > 74% of covered new-station HIGH station-days**.
  - Rationale: if 19 new stations × availability falls below 5/day, Kalshi gives no more tail supply than PM.us's nominal 5 station-days/day (5/19 = 26%).
  - LOW is reported, never pooled into the gate, because it shares a weather day with HIGH.
- **PASS:** availability ≥ 26% under the same rule. PASS means "supply exists", **not** "edge exists". It hands to K-2a WB-6 / GAP-4-style PREREGs.
- **One look** (L-34) at day 21. Interim reads are coverage only, never counts. A dry run on fixtures is not a look.

## 6 Tests (RED first) and gate
- `test_projection_drops_every_non_book_key`
- `test_no_ask_is_one_minus_yes_bid_levelwise`
- `test_tail_band_edges_inclusive_097_099`
- `test_size_below_one_contract_is_not_eligible`
- `test_sweep_and_day_coverage_rules`
- `test_daily_file_is_create_exclusive`
- `test_get_only_and_host_allowlist_is_api_elections_kalshi_com`
- `test_no_socket_opened_at_import`
- `test_census_never_imports_iem_cli_fetch_fetch`
- `test_census_refuses_second_look_without_force_flag_absent`

Notes on the tests:
- Every test uses a stub transport.
- The fixtures are the S0 orderbook and market fixtures.
- Gate: `scripts/ci/run_tests_no_egress.sh` on the primary tree, then `lint-imports` from the tree root. Read EXIT before any push.
- Basetemp goes inside the worktree. Delete it after reading EXIT.
- Whole-tree guards to name in briefs: import gates, the asdict scan, the operator-control assignment scan.

## 7 Pins, isolation, risks
- **Binding:**
  - Nautilus immutable.
  - `allow_short=False`.
  - No safety, settlement, contract, pin or NO-SEND test weakened.
  - Both caps never assigned.
  - Live enablement and the egress firewall untouched.
  - No credentials (unauthenticated GETs).
  - No order ids.
  - Holdout ruling cl.1–cl.4 does not apply: no forecast is scored, and the capture window is ≥ 11-01 forward.
- **Risks:**
  - Unauthenticated rate tier is undocumented (S0 §1.7). Mitigation: 4 rps cap and pinned backoff; a 429 storm counts as an incomplete sweep, never a retry loop.
  - Disk is about 1 MB/sweep projected (unmeasured). Mitigation: disk monitor; refuse below 10 GB free.
  - Title/rules drift (ENUM:46). Mitigation: identity comes from `series_ticker`, never ticker parsing.
  - Displayed size is not fillable size (a cancel race), so census availability is an **upper bound**.
  - A 0.97–0.99 NO buy has a ~97–99% break-even. That clears the operator's 70% preference trivially, while a single loss erases 30–50 wins.

## Size math (b) — arithmetic only, no q proposed
- **Monthly $ = N_elig/month × edge per contract × q.**
- **Kalshi:** N_elig = Σ_stations listed-days × tail availability (S5) × take rate. The take rate is unmeasured and needs a GAP-4-style family.
- The coordinator's table implies N_elig = 57/month:

| edge | $/month | q to clear $10 | q to clear $65 |
|---|---|---|---|
| 5¢ | $2.85 × q | ≥ 3.51 | ≥ 22.8 |
| 10¢ | $5.70 × q | ≥ 1.75 | ≥ 11.4 |
| 15¢ | $8.55 × q | ≥ 1.17 | ≥ 7.6 |

- For a 0.97–0.99 NO tail the gross margin per contract is ≤ 3¢ before fee, so **none of the table's rows apply to that cell**. Its row is ≤ 3¢ × N_elig × q.
- **Where the caps bind** (`src/breezy/adapters/polymarket_us/operator_controls.py`):
  - `BREEZY_MAX_POSITION_COST_USD` (`:150`) refuses if price × q > cap (`:541-547`). So q ≤ cap / price per order, about cap / 0.98 at the tail.
  - `BREEZY_MAX_DAILY_BUDGET_USD` (`:145`) refuses if day spend + cost > budget (`:540, :561-565`), plus the exposure headroom (`:566`).
  - Kalshi is not on this ledger today. K-2a WB-9b would share ONE ledger, so adding Kalshi never raises total spend.

## 8 Operator decisions
- **D-1:** authorise the Kalshi depth capture in parallel with PM.us work. This needs a ruling line amending RA-13 §4 / K-2a §0, scoped to GET-only desk capture with no `src/` change.
- **D-2:** confirm that a capture script is outside the 10-21 "existing harness only" ruling, or grant it. It is capture, not an evaluator.
- **D-3:** θ source: browser PDF fetch (operator) vs waiting for a first fill.
- **D-4:** size q. This is an **OPERATOR DECISION recorded here as a decision item; no value appears in this plan.**

## 9 Citations not verified
- The table's N_elig = 57/month is back-derived from the coordinator's $2.85/5¢ figures. It is not in `plan_r1_delta.md`.
- Whether Card E persisted its 24-city IEM CLI texts (usable for S4) is unchecked.
- The batch orderbook endpoint's limits, the ~576 market count and ~1 MB/sweep are estimates.
- Whether the public `get-series-fee-changes` endpoint needs auth is unverified.
- `git log` / `git diff --stat` were not run (no shell). Branch state is from `.git/packed-refs:167` plus the K-1 memo §5 and K-2a §6 `git show` records.
