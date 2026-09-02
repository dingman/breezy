# CLI-Basis Candidate #2 — Archive-Side `P(win | setup)` — Pre-Registration

Registered at: 2026-09-02T05:57:41Z

**This document is written BEFORE the outcome statistic below has been
computed.** Only plumbing (registry loading, archive/ASOS cache-hit checks
for the four dense stations, per L-1) was smoke-tested to confirm the
2021-2025 archive is readable offline, zero network, before this file was
written — no hit rate, Wilson bound, or verdict was viewed first.

## Why this statistic, and why it is registered separately from the offer-gate scan

`cli_basis_offer_gate_scan.py`'s pre-registered `n >= 50` admissible dense
station-day rule needs roughly 625 dense station-days at the measured
qualifying-setup rate (~1 in 12) — about five months at four stations. That
timeline is not compatible with this programme, and the fix is NOT to lower
that bar (LESSONS: changing a bar to reach a verdict is never acceptable
here) — it is to decompose the edge into two **independently estimable**
factors that do not both have to survive the same tiny forward-tape window:

    EV = P(win | setup) * $1 − ask − fee

* **`P(win | setup)`** — given ASOS headroom is 1-or-2 at some instant, how
  often does the CLI final actually reach the strike? This needs NO prices
  and NO forward tape capture at all — it is answerable on the full 2021-2025
  archive, today, at n in the thousands per station. **This document.**
* **`P(offer at <= $0.05, size >= floor | setup)`** — whether the venue
  actually prices the tail as dead often enough, in size, to be tradeable.
  This intrinsically needs the forward quote tape (capture only began
  2026-09-01) and stays governed by the EXISTING, UNCHANGED offer-gate
  pre-registration (`n >= 50` admissible dense station-days,
  `cli_basis_offer_gate_scan.py`'s own docstring). **Not this document, and
  not weakened by it.**

**The crucial asymmetry, stated before either number is computed:** a strong
`P(win | setup)` tells us the BET is good. It says NOTHING about whether the
bet is AVAILABLE — and L-9 already killed three prior strategy families on
availability (the rung that would win was never offered), not on probability.
A GO verdict below is never to be read, by itself or by any later reader of
this file, as license to build execution logic; it only removes one of the
two independent gates. The offer-gate scan's own gate is unchanged and still
binding.

## Question

Pooled over the four DENSE stations (LAX, MDW, MIA, SFO — NYC excluded, same
contamination finding as the offer-gate scan and the boundary study: NYC's
hourly cadence inflates any running-max-based hit rate), at ANY local-standard
hour (no 17-23 restriction — the offer-gate scan already established that the
running max has converged by then, `P(R_17 == R_23)` = 99.40% LAX / 95.49%
NYC, so an hour filter adds no discrimination and would only shrink `n` for
no reason):

    P(CLI_final_tmax_f(S, d) >= R_h(S, d) + m)   for m in {1, 2}

evaluated at every `(S, d, h)` where local-standard hour `h` is **complete**
(>= 1 real observation, not a carried-forward gap) and a non-sentinel CLI
final exists for `(S, d)`. `m in {1, 2}` mirrors
`cli_basis_offer_gate_scan.QUALIFYING_HEADROOM` exactly — the offer-gate scan
does not distinguish headroom 1 from headroom 2 when it counts a qualifying
event, so this statistic pools both margins into ONE archive-side estimate of
"the setup", rather than reporting two numbers nobody downstream would
combine correctly on their own.

`R_h(S, d)` is `pmr_climatology_study.build_running_max_days`'s
`running_max_f[h]`, reused verbatim (see "Null hypothesis" below) — the same
definition the already-PASSED boundary study and the offer-gate scan both
use, so this cannot end up with a third, silently-diverging running-max fold.

## Bar (identical derivation to the boundary study's, restated, not re-litigated)

Same worked figures as `pre_registration_2026-09-02T044737Z.md`: ask $0.05,
`theta = 0.06` (the fee module's own worked example,
`src/breezy/adapters/polymarket_us/fees.py`), one-cent tick buffer.

    break_even_win_rate = ask + fee(at ask) + tick
                        = 0.05 + (0.06 * 0.05 * 0.95) + 0.01
                        = 0.06285

**PASS bar: the pooled (across the 4 dense stations) Wilson 95% LOWER bound
on `P(win | setup)` is >= 0.06285.** Per-station bounds are ALSO reported
individually — a pooled PASS built on one outlier station is a different,
weaker finding than a PASS that holds station-by-station, and both are shown
rather than only the pooled headline.

## Power

**ADMISSIBLE** only at `n >= 100` cases (pooled across stations and both
margins) — identical floor to the already-PASSED boundary study, for the same
reason (an underpowered verdict describes the sample, not the world). Given
~5 years x 4 stations x up to 24 candidate hours x 2 margins, `n` is expected
in the low thousands; this floor exists to make the rule meaningful in
principle, not because it is expected to bind. Reported regardless of
verdict, per-station AND pooled.

## Verdict rule (fixed in advance)

- **PASS** — pooled `n >= 100` AND pooled Wilson-95%-lower `P(win | setup)`
  >= 0.06285.
- **FAIL** — pooled `n >= 100` AND pooled Wilson-95%-upper `P(win | setup)`
  < 0.06285 (the mirror-image kill condition, stated so a PASS is not the
  only reachable verdict).
- **UNDERPOWERED** — pooled `n < 100`, or neither PASS nor FAIL condition
  above holds (the bound straddles the bar).

**This verdict, by itself, NEVER authorizes execution.** Per the asymmetry
above, a PASS here only clears the probability half of the two-factor gate;
the offer-gate scan's own `n >= 50` admissible-dense-station-day rule remains
the sole, unweakened gate on availability, and both must clear before any
execution logic is built.

## Null hypothesis — existing capability, checked before writing new code

- `pmr_climatology_study.build_running_max_days` / `load_cli_records` /
  `RunningMaxDay` / `CliRecord` — the running-max fold and CLI-final archive
  loader. NATIVE-EXISTS-AND-REUSED, reused verbatim via import — same
  functions the already-PASSED boundary study and the offer-gate scan both
  depend on.
- `settlement_alignment_study.load_sites` / `metar_temperatures` /
  `SiteSpec` — registry and ASOS archive parsing. NATIVE-EXISTS-AND-REUSED.
- `cli_basis_boundary_study.hour_coverage` / `is_non_sentinel_final` — this
  study's own per-hour true-coverage helper (as opposed to the carried-
  forward running value) and non-sentinel-final predicate. Reused verbatim
  via IMPORT ONLY; `cli_basis_boundary_study.py` itself is NOT modified by
  this effort (it is not among the files this task owns, and it already
  carries its own PASSED, pre-registered gate that must not be touched).
- `k1_cheap_open_settlement.wilson_interval` — the two-sided Wilson bound,
  reused verbatim via import, matching the offer-gate scan's own choice, so
  this repo does not grow a third disagreeing Wilson implementation.
- A join generalizing `cli_basis_boundary_study.BoundaryCase` from a FIXED
  `margin=1` restricted to local-standard hours 17-23, to a PARAMETERIZED
  `margin in {1, 2}` with NO hour restriction, pooled across stations — does
  NOT exist upstream (the existing `BoundaryCase`/`build_boundary_cases` pair
  hardcodes `threshold_f = running_f + 1` and the `STUDY_HOURS` window in its
  own pre-registration, and must not be widened in place — L-12: widen an
  exact-set barrier via a NEW, narrower variant, never by relaxing the
  original). GENUINE GAP, built as a new, narrow join in
  `cli_basis_setup_win_rate_study.py`, re-deriving nothing the pieces above
  already provide.
