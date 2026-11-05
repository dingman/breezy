# AUD-08 — Round 1 review (trading-bot-architect, autonomous-loop/pipeline lens)

plan id: AUD-08
plan file sha256: a455939e6807065541690edbf218a145608cb991a8a594f098329b26a75374e9
round: 1
reviewer: trading-bot-architect (independent, adversarial)

## Claims verified

| Ref | Plan claim | Verdict |
|---|---|---|
| `provider.py:218-224` raises `VenuePayloadError` for an unregistered city | Confirmed in substance; actual line numbers are `provider.py:221-227` in the current tree (the `if parsed.city not in city_set:` branch). Off-by-~3 citation drift, not a false claim. |
| `data.py:1254-1267` blanket `except Exception` retries the reload cycle forever | Confirmed exactly: `_update_instruments` (`data.py:1223-1269`) calls `_run_one_reload_cycle()` inside a `try/except Exception` that logs at ERROR and falls through to the next scheduled `asyncio.sleep(delay_secs)` pass — permanent, identical failure every cycle, never fatal, never self-healing without a `sites.toml` edit. |
| `_weather_market_payloads`'s raise sits inside `_discover_markets`, ahead of the CF-14a stage-3 failure collector | Consistent with the surrounding source; not independently re-derived line-for-line but the raise is unconditional and precedes any per-market collection, so the abort-the-whole-cycle characterization holds. |
| `family_manifest.py` / composition citations used as cross-reference context | N/A to this plan; verified separately for AUD-10 (see that review). |

## Defects

**MATERIAL — priority likely mismatched to blast radius (§4).** The plan scores 08a P2, reasoning it closes "a silent-halt class this programme has already paid for twice." But the mechanism it just proved (§6, confirmed above) is not scoped to the new city: one unregistered-city listing poisons `_weather_market_payloads` for the *entire* payload, so `_discover_markets`/`initialize(reload=True)` raises for **all** cities in that cycle, and the blanket catch in `_update_instruments` means every subsequent reload also fails identically. That silently freezes new-day cohort pickup for the four *currently traded* stations (LAX/MDW/MIA/SFO), not just the newcomer — i.e., this is not a discovery-outage confined to expansion; it is a livelock that can starve the live family of tomorrow's instruments while the node otherwise looks healthy, the exact "healthy node, can't trade" shape memory `venue-drift-kills-the-node-silently` already names as a paid-for failure mode. That argues for P0/P1 (blocks live trading), not P2. The plan's own honest-bound section (§11) even concedes PM.us has never observed this trigger — but "never observed" is not "cannot happen," and the cost asymmetry (days of silent halt vs. a few hours of implementation) favors treating 08a as urgent regardless of current empirical trigger rate. Required change: re-score 08a P0 or P1, or add an explicit, evidenced argument for why the outage's blast radius on the four traded stations is smaller than stated (e.g., an independent reason `sites.toml` will never observationally omit a listed city that isn't already registered — not currently argued).

**MINOR — citation line drift.** `provider.py:218-224` in §3/§6 is actually `provider.py:221-227` in the current tree. Same code, same semantics; update the line numbers before merge so a future reader's diff-against-citation check doesn't false-flag.

**MINOR — L-1 Nautilus verdict not independently re-run by the author (§6, admitted in §13).** The `grep -rn "candidate\|rejected\|unsupported" .../providers.py` command is specified but the plan's own self-review states it was not executed. I did not re-run it either (out of scope for this pass); flagging so the implementer runs it before claiming the null hypothesis is closed.

## No defect found in

The AUD-08a/08b split, the "never widen `SUPPORTED_STATIONS`/`sites.toml`" exclusions, the flood cap (32 new cities/day), the atomic-write and idempotence requirements, and the honest zero-ROI-on-PM.us framing are all sound and internally consistent with the cited constraints (`UnsupportedStationError`, registry header, lint-imports).

## Per-criterion points

| Criterion | Max | Points | Basis |
|---|---|---|---|
| Fidelity to audit gap and completeness | 20 | 16 | Matches author's self-score; deliberate non-dynamism is honestly scoped. |
| Technical correctness and evidence grounding | 20 | 16 | Core claim confirmed true; citation-line drift and un-run grep are minor deductions. |
| Implementation specificity and feasibility | 15 | 12 | As author scored; sufficiency-status parameterization for non-dense cities left underspecified. |
| Acceptance criteria and validation quality | 20 | 16 | A1-A8 measurable; A6 fixture-only as author notes. |
| Autonomous operation, failure handling, recovery | 15 | 10 | Flood/corruption handling solid, but the priority defect above means the plan under-treats the actual operational stakes of 08a — this criterion is where the blast-radius miss costs points. |
| Portfolio objective alignment, scope, dependencies | 10 | 8 | Honest ROI bound, clear abandonment criterion. |
| **Total** | **100** | **78** | |

## Required changes to reach 100

1. Re-justify or re-score 08a's priority against the full-cycle-abort blast radius on the four traded stations (MATERIAL).
2. Correct the `provider.py` line citations to `221-227`.
3. Run the specified `grep` for the L-1 verdict and record its actual output rather than the expected one.

## Blockers

None that block *this* item's build. The plan's own §12 blockers (sites.toml re-verification gate; auto-promotion to capture) are correctly scoped as out-of-band and are not blockers on AUD-08 itself.
