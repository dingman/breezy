# Grok live-small spec — rev 3 delta (2026-09-04)

Amends `grok_live_small_spec_rev2_2026-09-04.md` §5 (`stale_observation_hours`
table) and PREREG v1 §3/§4. One change: the `current_rung_hold` observation
staleness bound moves from 45 minutes to **50 minutes**, computed from integer
minutes. Trigger: the 2026-09-04 paper replay
(`paper_replay_current_rung_hold_2026-09-04.md`) refused every lag-45 arm
`observation_unavailable` because receipt = observed + 45 made the observation
fresh for exactly one nanosecond under a 45-minute bound. Consultation was
read-only; Grok edited nothing. Verification of the cited code lines by the
delegate: `config.py:201`, `decision.py:264-270`,
`test_current_rung_hold_decision.py:40,135-142` confirmed; the
`running_extreme.py` lines were cited under the wrong subpath (the module is
`src/breezy/strategy/weather_common/running_extreme.py`) and are otherwise as
described.

Ruling as returned by Grok (verbatim from the delegate transcript; the
evidence-brief portion before it was garbled in transit and is omitted):

---

**Ruling: (A).** The bound gives. Pin `stale_observation_hours` at **50 minutes** (`50/60` h). Compute the nanosecond bound from integer minutes, not from a repeating float hours value. Keep both lag arms. Do not re-measure `P_HOLD_LOWER`.

This is a bound-vs-lag identity collision, not a wrong NWS latency and not a reason to drop the pessimistic arm.

---

## What collides

Paper replay stamps **receipt on the observation**:

```
received_at_ns = observed_at_ns + lag_minutes
```

(`src/breezy/runtime/paper_replay.py:34-35,188,216`; `tests/unit/test_current_rung_hold_paper_replay.py::test_received_at_ns_is_synthesized_as_observed_plus_lag`). That is the live A1 rule PREREG §3 restates (`docs/specs/PREREG_v1_current_rung_hold_2026-09-04.md:72-75`; BL-24 A1 at `docs/plans/BL24_LIVE_RT_2026-09-04.md:119`), not the archive study’s `find_lagged_entry(..., not_before=t+lag)` (`scripts/analysis/mb_current_rung_edge_study.py:479-490`).

Eligibility and age then use **measurement**, never receipt (A6: never subtract `assumed_publication_lag_ns`):

| Gate | Rule | File |
|---|---|---|
| Eligible | `observed_at_ns <= now_ns AND received_at_ns <= now_ns` | `running_extreme.py:278-281,307-323` |
| Age | `now_ns − max(eligible observed)` | `running_extreme.py:323` |
| Refuse | `staleness_ns > int(stale_observation_hours * 3.6e12)` | `decision.py:264-270` |
| Bound | `stale_observation_hours = 0.75` → **45 min exactly** (`2.7e12` ns) | `config.py:201`; `decision.py:149` |

Equality is still fresh (`>` not `>=`; `tests/unit/test_current_rung_hold_decision.py:140-142`). So lag 45 is eligible only at `now = observed + 45 min` (one nanosecond) and every later quote in the 5-minute gap is `observation_unavailable`.

Lag 30 has a 15-minute open window (`45 − 30`). That is why lag 30 decided and lag 45 did not.

---

## Why not (C)

45 minutes is **not** the measured NWS 5-min latency.

| Number | What it is | Source |
|---|---|---|
| **21 min** | One NWS poll, KMDW 5-min, 2026-09-04 ~01:36Z | `docs/evidence/observation_source_latency_2026-09-04.md:8`; pinned as provenance-only `NWS_API_ASSUMED_PUBLICATION_LAG_NS` (`observation_composition.py:17-19,46-47`; A6 `BL24_LIVE_RT_2026-09-04.md:124`) |
| **19.3–43.3 min** | IEM CSV, batchy; **not** the live source (A12) | `docs/evidence/iem_asos_live_latency_2026-09-04.md:9-16,23-26` |
| **45 min** | KNYC hourly (station **excluded**) | `observation_source_latency_2026-09-04.md:9-16`; `config.py:16-25` |
| **45 min lag arm** | Spec’s **pessimistic envelope** (IEM 43; slow batch), not a second NWS draw | rev2 `:50` |
| **0.75 h bound** | “measured upper + one 300 s poll + pad”; “Do not set below 45 min” | rev2 `:19,110` |

Live `L_extra = 0` with real ~21 min NWS receipts is fine under 0.75 h (age at arrival ≈ 21 < 45). The empty set is the **paper arm that synthesizes receipt = observed + 45**. Replacing 45 with 21 would treat one KMDW poll as the family lag and throw away the slow-tail selector test. A6 forbids using that 21 min figure in staleness anyway.

---

## Why not (B)

Dropping lag 45 would leave only lag 30. PREREG would lose:

- The requirement that **both** live-family arms agree (`K_B_REQUIRED_LAGS_LIVE = (30, 45)`, `mb_current_rung_edge_study.py:191-195`; rev2 `:50,129`; PREREG `:73-75`).
- The anti-L-21 check: hold is lag-invariant, the **selector is not** (rev2 `:52`). Cheap 0.06 asks that lasted 15 min on 09-01 are the trap, not evidence they last 45.
- Coverage of the slow tail of the receipt mixture (rev2 `:50`; PREREG `:169-171`). A lag-30 SURVIVE would license live even if the mispricing is already gone at 45.

The 09-01 paper tape already shows the selector is the thing being tested: lag 30 took MDW at ask 0.06 and did **not** hold (`docs/evidence/paper_replay_current_rung_hold_2026-09-04.md:39-42`). That arm must remain comparable at 45, not structurally empty.

---

## New bound

```
stale_observation_hours = 50 / 60    # 50 minutes
bound_ns = 50 * 60 * 1_000_000_000  # 3_000_000_000_000, integer minutes→ns
```

**Derivation:** `max(K_B_REQUIRED_LAGS_LIVE) + dense ASOS cadence`

- max live lag = **45 min** (`mb_current_rung_edge_study.py:195`)
- cadence = **5 min** (`running_extreme.py:14`, ~288 rows/day; `observation_source_latency_2026-09-04.md:8`)
- 45 + 5 = **50 min**

That is the shortest bound that leaves a positive open interval after a lag-45 receipt so quote ticks in the 5-minute gap are not refused. Do **not** write `0.8333…`: `0.75` was exact in binary (`3/4`); `50/60` is not. Decision code must use integer minutes → ns (today `int(0.75 * 3_600_000_000_000)` is safe only because 0.75 is dyadic; `decision.py:264`).

Ingest rebuild stays in lockstep: `DEFAULT_STALENESS_BOUND_SECONDS` is 2700 citing rev2 §5 (`nws_observation_config.py:43-44`) → **3000**. Poll stays 300 s (`:41`).

Live loosening is one 5-minute cycle past today’s 45-minute envelope. A healthy NWS 5-min feed’s newest eligible row is ~21 min old (`observation_source_latency_2026-09-04.md:8`). 50 min only binds when the feed is already past the current bound. Direction matches rev2’s “Do not set below 45 min” (`:110`).

---

## `P_HOLD_LOWER` stays valid — not keyed by lag

The user prompt’s “keyed by lag/m_code” is wrong on lag.

- Key is `(station, season, hour_lst, width_code, m_code)` (`archive_table.py:15`).
- Corpus `3b410fb9…f04d48` (`archive_table.py:32`; PREREG `:15`).
- Generator is **Part A only** — hour-end `R` vs CLI, no lag (`generate_current_rung_hold_archive_table.py:5-8`; `build_archive_table` at `mb_current_rung_edge_study.py:384-401` via `build_hold_cases`).
- Hold event is lag-invariant (rev2 `:52`). Lag changes **which ask** is seen, not the cell’s Wilson-lower hold rate.

Widening the bound does not change those cells. Do not regenerate the table. A new corpus would be a PREREG restart (`PREREG:148-151`); this is not that.

PREREG is still **DRAFT** (`PREREG:3`). Amend v1 in place with the new pin. Once the draft line is removed, the same change is PREREG v2 and `n` resets.

---

## Measured 09-01 paper replay (instance `5a111bca…`)

From `docs/evidence/paper_replay_current_rung_hold_2026-09-04.md:27-48` (not inferred):

| Station | Lag 30 | Lag 45 |
|---|---|---|
| MDW | 1 scored take, ask 0.06, `held=False`, pnl −0.06 | counted `observation_unavailable` 1 |
| SFO | counted `edge_below_break_even` 1 | counted `observation_unavailable` 1 |
| LAX | counted `illegal_cell` 1 | counted `observation_unavailable` 1 |
| MIA | wait-states only (`not_executable` 1917, `rung_not_current` 2) | same wait-state counts; **no** counted `observation_unavailable` |

The memo’s prose (`:44-48`) already names the fix: lag 45 is a staleness-refusal arm **unless the spec revises the bound**. MIA did not print that counted reason; the identity still kills any tick whose first eligible observation is the lag-45 receipt.

---

## Rev 3 delta (quotable)

Changelog row replacing rev2 `:19`:

> **§5 `stale_observation_hours=0.75`.** Falsified: bound = max live lag, so A1 `received = observed + lag` at lag 45 is eligible only at equality (`running_extreme.py:307-323` ∩ `decision.py:267-268`). 09-01 paper replay instance `5a111bca` lag-45 arms on SFO/MDW/LAX counted `observation_unavailable` (`paper_replay_current_rung_hold_2026-09-04.md:34-48`). **Replacement: `50/60` h (50 min) = `max(K_B_REQUIRED_LAGS_LIVE) + 5 min ASOS cadence`.** Bound_ns from integer minutes (`50 * 60 * 1e9`), never `int(hours * 3.6e12)` on a non-dyadic hours value. `K_B_REQUIRED_LAGS_LIVE` stays `(30, 45)`. `P_HOLD_LOWER` (corpus `3b410fb9…f04d48`, key `(station, season, hour_lst, width_code, m_code)`) is lag-invariant Part A and is **not** re-measured. Live `L_extra=0` unchanged; `allow_short` stays False; operator caps unset.

§5 table, LAX/MDW/MIA/SFO row:

> **`50/60` h (50 min).** Identity: an observation is eligible only once `now ≥ received = observed + lag`, and stale once `now − observed > bound` (A6: age is measurement, never receipt). Bound must exceed every live-family lag by at least one 5-minute cadence or the lag-45 arm is empty after a single nanosecond. 50 min = 45 min max lag + 5 min cadence. Do not set below 50 min while lag 45 remains a required arm. Default `None` still refuses every OBSERVATION order — this config **must** set `50/60`. Ingest `DEFAULT_STALENESS_BOUND_SECONDS` moves 2700 → 3000 with this pin.

---

## Test that must WIDEN (never loosen)

**Widen** `tests/unit/test_current_rung_hold_decision.py`:

- Move `_STALE_BOUND_NS` (`:40`) from `int(0.75 * 3_600_000_000_000)` to `50 * 60 * 1_000_000_000`.
- Keep `test_a_running_max_exactly_at_the_stale_bound_is_not_refused` (`:140-142`): age **equal** to the **new** bound is still a Take.
- Keep `test_a_stale_running_max_is_refused_observation_unavailable` (`:135-137`): age `bound + 1` ns still refuses. Do not accept older than the new bound.

**Add (this is the characterizing widen):** lag-45 receipt, quote at `received_at_ns + 5 min − 1 ns` (age = 50 min − 1 ns) is **not** `observation_unavailable`. Today that tick is refused; after A it must pass the stale gate (other refusals may still fire). Mirror it on the paper-replay path next to `test_received_at_ns_is_synthesized_as_observed_plus_lag` so `received = observed + 45 min` and the decision bound cannot silently re-collapse.

Also move `DEFAULT_STALENESS_BOUND_SECONDS` 2700 → 3000 (`nws_observation_config.py:44`) with whatever test pins that constant. Do not loosen rebuild trust past 50 min.

Not a license: `allow_short` stays False (`config.py:207,228-230`); operator caps stay absent (`config.py:41-51,191-193`); `orders_enabled` stays False (`config.py:213,237-240`). Nautilus untouched.