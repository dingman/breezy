# Ruling: the v3 family tally over-admits a residual fill, and a fourth residual bucket is unregistered

**Date:** 2026-09-20
**Family:** `pm_us_crh_cont` (PREREG v3, continuous rung hold)
**Severity:** HIGH — inflates `n` on a sequential test that is spending alpha.
**Status:** RULED. Fixes ordered below.

## Finding 1 — the tally admits a fill its own scorer classified as residual

Measured on the live store
`~/.local/share/breezy/derived/scored_trials/pm_us_crh_cont`:

The trial
`continuous_rung_hold/trial/MIA/2026-09-15/tc-temp-miahigh-2026-09-15-gte92lt93f^no.POLYMARKET_US`
appears **twice, in contradiction**:

- as a scored parquet row with `excluded_reason = None`
  (`scored_trials_20260917T141539174141881Z.parquet`), and
- in `excluded_fills.jsonl` with
  `reason = "no_side_first_order_residual"`, `venue_order_id = CGW8DJ23PVB2` —
  a reason that IS a member of `RESIDUAL_EXCLUSION_REASONS`.

**`family_tally_v2` never consults the sidecar.** `:591` admits on
`row.excluded_reason is None` alone. So the fill counts toward `n`.

**Worse, the contradiction is then hidden.** `coverage_rows` (`:819`) skips any
residual entry whose `trial_id` already has a scored row — "dropped as
already-scored" (`:853`). That is the exact inverse of §5: the one record that
would reveal the over-admission is the one discarded from the coverage report.

**Measured effect:** the registered tally admits **4**; PREREG §5 admits **3**.
`n` is inflated by 25% on a sequential test. At the current sample this is
nowhere near a boundary, so no prior verdict flips — but the defect is
systematic, silent, and grows with every NO-side fill.

The WP-31 loader (`breezy.persistence.realized_draws`, `f568ffa`) applies §5
correctly: 3 admissible fills → 2 station-day draws.

## Finding 2 — `no_side_first_order_residual` is an UNREGISTERED bucket

`src/breezy/persistence/residual_fills.py` states the bucket is additive under
"PREREG amendment §8". That citation is wrong:

- PREREG v3 **§8 is "Boundary Artefact"**, unchanged from v2.
- PREREG v3 contains **no mention of NO-side anywhere** (`grep` over the whole
  document returns zero hits for `no_side` / `NO-side` / `NO side`).
- §5 registers **exactly three** mutually exclusive buckets: `duplicate_fill`,
  `q≠1`, `fee_unreconciled`. The code carries five reasons; `partial_fill` and
  `multi_fill` are a faithful spelling of `q≠1`, but
  `no_side_first_order_residual` is a **fourth bucket with no registration**.

A residual classifier on a registered sequential test was extended without
amending the registration, and the code then cited a section that says
something else. This is a registration-discipline failure independent of
Finding 1.

## Rulings

**R1. The tally must consult the residual sidecar.** A `trial_id` in
`residual_trial_ids(...)` is NOT admissible regardless of its parquet
`excluded_reason`. This is a defect fix bringing code into line with the
registration — it is NOT a spec change, and it does not require re-registration.

**R2. `coverage_rows` must stop dropping a residual whose `trial_id` has a
scored row.** That case is precisely the contradiction that must surface. It
becomes a loud, reported reconciliation failure, not a silent skip.

**R3. `no_side_first_order_residual` must be registered by a dated amendment to
PREREG v3 §5**, stating the bucket, its first-match-wins position in the
ordering, and the date from which it applies. The false "§8" citation in
`residual_fills.py` is corrected to point at that amendment. Until the
amendment lands, the bucket is honoured in code (it is the conservative
direction — it only ever REMOVES fills from `n`) but is recorded here as
unregistered.

**R4. No fix may reduce residual strictness to resolve the contradiction.**
The admissible direction is always the one that shrinks `n`. Where attribution
is ambiguous, fail closed.

## Known, recorded, not fixed

`ScoredTrial` carries no `venue_order_id`, so a `duplicate_fill` naming a
`trial_id` that also has a scored row cannot be attributed from the parquet
alone. The WP-31 loader fails closed (drops the `trial_id`; `n` shrinks, never
inflates). Closing this properly is a schema change and is deferred.
