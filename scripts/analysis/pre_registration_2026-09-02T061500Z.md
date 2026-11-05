# CLI-Basis Candidate #2 — Per-Hour Profile & Admissibility Rule — Pre-Registration

Registered at: 2026-09-02T061500Z

**Sequencing, stated plainly.** This document does not precede a first look at
any data whatsoever — it follows the diagnostic run explicitly called for by
the ⚠ banner on `cli_basis_setup_win_rate_2026-09-02T060103Z.md`
(`P(win | setup)` and `P(R_h == R_23)`, both broken out by local-standard
hour 0..23, per dense station). That diagnostic is EXPLORATORY by design —
the coordinator's brief instructs producing it FIRST, precisely so the
admissibility rule below can be chosen from evidence rather than guessed.
What this document fixes BEFORE being computed is the one number that
matters for a verdict: the CORRECTED pooled/per-station `P(win | setup)`
under the rule below. The admissibility rule's floor itself
(`ADMISSIBLE_HOUR_FLOOR = 17`) was fixed in code from a PRIOR, independently
published finding — `cli_basis_boundary_study.STUDY_HOURS[0]`, already
measured and PASSED — not reverse-engineered from today's diagnostic; the
diagnostic corroborates that choice rather than producing it circularly (see
"Why 17, not a different floor" below).

## What the diagnostic showed

Per dense station (LAX, MDW, MIA, SFO), `P(win | setup)` at local-standard
hour `h` starts at 87-99% at `h = 0` and falls MONOTONICALLY as `h`
increases, flattening out around `h = 16-17` onto a plateau that holds
through `h = 23` (LAX ~14.0-14.6%, MDW ~8.0-10.8%, MIA ~13.3-13.5%, SFO
~11.8-12.4%; margins 1-and-2 pooled, so roughly half the boundary study's
own margin-1-only ~15-26% at hour 23, consistent with margin 2 being a
strictly harder, rarer threshold).

`P(R_h == R_23)` — the fraction of days where the running max at hour `h`
already equals its end-of-day value — starts at 1-10% at `h = 0` (station-
dependent: LAX/MIA/SFO near 1-2%, MDW's colder-climate diurnal profile
starts higher at ~10%) and rises to 95-99%+ by `h = 16-17`, reaching 100% by
construction at `h = 23`. The two curves move together, station by station:
where convergence is low, the win rate is high (and spurious); where
convergence has saturated, the win rate has flattened onto its stable floor.
**This is the mechanism the ⚠ banner named, now measured rather than
asserted**: an early-hour "setup" is overwhelmingly a day that has not yet
peaked, and its apparent win is ordinary diurnal warming reaching the
strike, not a CLI-vs-ASOS basis event.

## Candidates weighed for the admissibility rule

1. **Fixed local-standard hour >= 17** (adopted). Implementable LIVE: the
   clock hour is known at every instant with zero dependency on how the rest
   of the day turns out. Directly addresses the flagged defect (removes
   every pre-convergence hour). Reuses, rather than re-derives, the window
   the already-PASSED boundary study measured
   (`cli_basis_boundary_study.STUDY_HOURS = (17, ..., 23)`), so this study's
   corrected number is comparable to that one cell-for-cell. The adversarial
   review on the boundary study noted that hours 17-23 barely discriminate
   AMONG THEMSELVES (`P(R_17 == R_23)` already 99.4% at LAX) — true, and
   irrelevant here: that finding is about the marginal information within
   17-23, not about whether 17 is doing useful work relative to the hours
   BEFORE it, which this diagnostic shows it very much is (the entire drop
   from ~99% to ~14% at LAX happens across hours 0-16).
2. **Restrict to instants at/after the day's own realized diurnal peak.**
   REJECTED as un-implementable live: at trade time, whether today's peak has
   already occurred is exactly the fact not yet known — a rule keyed on it
   can only be evaluated in hindsight, on the archive, never at decision
   time. Using it to define the traded population would silently smuggle
   lookahead into what is supposed to be an at-the-instant entry condition.
3. **Require `P(R_h == R_23)` (or a live proxy for it) above a fixed
   threshold, evaluated per station.** Live-implementable in principle IF the
   proxy is built from information available at the instant (e.g., "hours
   since the running max last increased" rather than the realized `R_23`
   itself) — genuinely more general than a fixed clock hour, since it would
   adapt to season and to a station's own diurnal-peak timing rather than
   using one wall-clock cutoff for every day of the year. NOT adopted here:
   it requires its own admissibility floor (how many stall-hours is enough?)
   tuned and pre-registered per station, which this task's time budget does
   not cover, and the archive-derived `P(R_h == R_23)` diagnostic above
   already shows candidate 1 removes the same population candidate 3 would
   target (both curves inflect at the same hours). Recorded as the natural
   next refinement, not dismissed on principle.

## Corrected statistic (fixed in advance of this run's headline number)

Pooled over the four dense stations, restricted to `SetupCase.hour >= 17`
(`is_admissible_hour`), margins `{1, 2}` pooled (unchanged from the
challenged study), using the SAME, unmodified `summarize_station` /
`pool_stations` / `pooled_verdict` pipeline the challenged study used:

    P(CLI_final_tmax_f(S, d) >= R_h(S, d) + m)   for m in {1, 2}, h >= 17

## Bar and power (unchanged, restated not re-derived)

Identical to the challenged study's own: PASS bar Wilson-95%-lower
`>= 0.06285`; admissible only at pooled `n >= 100`; FAIL if Wilson-95%-upper
`< 0.06285`; UNDERPOWERED otherwise. See
`pre_registration_2026-09-02T055741Z.md` for the derivation; not
re-litigated here.

## Verdict rule (fixed in advance)

- **PASS** — pooled `n >= 100` AND pooled Wilson-95%-lower `>= 0.06285`,
  under the `h >= 17` restriction.
- **FAIL** — pooled `n >= 100` AND pooled Wilson-95%-upper `< 0.06285`.
- **UNDERPOWERED** — otherwise.

This verdict, like the challenged study's, is necessary but never
sufficient for a GO — the offer-gate scan's own unchanged `n >= 50`
admissible-dense-station-day rule remains the sole, unweakened gate on
AVAILABILITY (Item 3's crucial asymmetry, unchanged by this correction).

## Null hypothesis — existing capability, checked before writing new code

See `scripts/analysis/cli_basis_hourly_profile_study.py`'s own module
docstring for the full NATIVE-EXISTS-AND-REUSED / GENUINE-GAP inventory,
cited path:line per item. Summary: the running-max fold, CLI-final loader,
hour-coverage helper, non-sentinel-final predicate, `SetupCase`/
`build_setup_cases`, the pooling/verdict pipeline, and the Wilson bound are
ALL reused verbatim via import from `pmr_climatology_study`,
`settlement_alignment_study`, `cli_basis_boundary_study`,
`cli_basis_setup_win_rate_study`, and `k1_cheap_open_settlement`. The only
GENUINE GAPS are: per-`(station, hour)` aggregation of `SetupCase` (margins
pooled), the `P(R_h == R_23)` fold, the `is_admissible_hour` predicate, and
the filter that applies it before handing off to the unmodified pooling
pipeline. `cli_basis_boundary_study.py` and
`cli_basis_setup_win_rate_study.py`'s existing `build_setup_cases` are
neither modified (L-12: widen via a new, narrower variant, never by
relaxing the original in place).
