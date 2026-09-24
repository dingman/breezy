# Review — RULING_venue_reconciliation_R1_R2_2026-09-21.md

Status: PROPOSED — adversarial peer review. Blind — no other agent's output consulted.

## Verdict: ENDORSE-WITH-REQUIRED-CHANGES

## Verified as correct (no defect)

- Finding 8 (order_side hardcode) is real: confirmed at plan
  `docs/plans/RECONCILIATION_NATIVE_REPORTS_2026-09-12.md:66`
  (`order_side=BUY` unconditional). `generate_order_status_reports`/
  `generate_fill_reports` are currently both `return []` stubs
  (`src/breezy/adapters/polymarket_us/exec/client.py:2500-2549`), so this is a
  plan-text defect, correctly caught pre-implementation, not a live bug.
  `on_order_filled` (`continuous_strategy.py:2271-2278`) does branch on
  `event.order_side is OrderSide.SELL` to route to `_on_exit_order_filled`
  vs. the entry `consume_if_absent` path — the failure mechanism the ruling
  describes is mechanically accurate. R-2's conditioning on this fix is sound.
- Finding 6 (no double-spend): confirmed — `authorize_order_cost` is called
  only from `exec/client.py` (submit/resolver paths); zero call sites in
  `src/breezy/strategy/`.
- Finding 7 (idempotency): confirmed — `consume_if_absent`
  (`trial_day_latch.py:780-825`) is a true read-check-write under a
  process-wide flock; a replayed `venue_order_id` is a no-op, matching the
  "n grows only via the create path" operating rule.
- R-1/R-2 correctly scoped as non-operator-reserved.

## Required changes

### [HIGH] R-1's fee-fallback is not keyed to fill time — the ruling's own overturn condition already holds today

File: `docs/evidence/RULING_venue_reconciliation_R1_R2_2026-09-21.md:48-58` (RULING R-1),
cross-ref `src/breezy/adapters/polymarket_us/fees.py:277-316` (`polymarket_us_fee`
reads `theta = _fee_coefficient(instrument)` off whichever `Instrument` object is
in the Nautilus cache **at the moment the generator runs**, not off any value
tied to `record.tsEvent`), and
`docs/evidence/venue/polymarket_us/FEE_SCHEDULE_PIN_2026-09-18.md:47-113`
(confirmed platform-wide θ drift 0.06→0.0695 on 2026-09-17, observed
identically across MIA/MDW/SFO — i.e. drift is schedule-wide, not
per-market-at-listing).

Issue: the ruling states the O4 fallback is "a byte-identical continuation of
current behaviour (0.01 modelled), not a regression to 0.00" and requires only
that it be "computed identically to the existing native-inference call
(`fees.py:200-239`)". But `polymarket_us_fee` takes `theta` from whatever
Instrument object the cache holds when the generator executes — i.e. at
reconciliation-boot time, not fill time. The one durable record in the store
today (`CEBPX0EVTTMX`, SFO 2026-09-11) predates the 09-17 drift; if the
Instrument for that slug is (re)loaded by the provider on or after
2026-09-21, nothing in the ruling establishes that it still carries
`theta=0.06` rather than the now-current `0.0695`. The ruling's own §7 names
this exact scenario as what "would overturn" R-1 ("a fill that predates the
correction... inherits the same staleness O2 would have") — but treats it as
a future hypothetical, when the drift is an already-verified, dated fact and
the only existing record already predates it. This was not checked before
ruling "byte-identical."

Failure: On the next reconciling boot, O4's modelled fallback silently books
`commission = Money(0.0695 * 1 * 0.22 * 0.78 ...)` for a fill that actually
paid 0.06-basis fees, tagged `feeSource="modelled"` with no marker that the
coefficient is wrong for that fill's date. Any future `exit_guard`/
`SettlementExitActor` consumer (finding 4's own stated audience for
`feeSource`) reads a `Position.realized_pnl` that is fee-INCORRECT while
trusting the `"modelled"` tag as "known, not attested" rather than "known
wrong" — exactly the silent-degradation failure mode this whole ruling exists
to prevent, just moved one layer down.

Fix: Add to R-1's binding text: the modelled fallback commission MUST be
computed from the fee coefficient in effect at `record.tsEvent`, not from
whatever `Instrument.taker_fee` the Nautilus cache holds at reconciliation
time. Concretely: either (a) persist `feeCoefficientAtFill` onto
`DurableFillRecord` in B0 (same optional-on-read pattern as `trade_id`) and
compute the fallback from it, or (b) if that is out of scope for B0, the
ruling must require a pre-B1 verification step — confirm, for the one
existing record, that the Instrument object reconciliation would actually
load on the next boot still reports `theta=0.06` for that slug — and gate
O4's "byte-identical" claim on that check passing, not assume it. Absent
either, `feeSource="modelled"` must not be asserted as continuity with
"today's 0.01" in the plan text (§6 consequence for `:118-123`).

### [MEDIUM] "Byte-identical to today's 0.01" is asserted, not verified, against current (post-drift) instrument state

File: `docs/evidence/RULING_venue_reconciliation_R1_R2_2026-09-21.md:48-53`.
This is the same root cause as the HIGH item above but scoped narrower: the
ruling should not present the fallback's output value as a known fact ("0.01
modelled") when it has not re-run `polymarket_us_fee` against the Instrument
object as it would actually be loaded today, 4 days after the confirmed
drift. Downgrade the claim to "intended to match" pending the HIGH fix, or
verify it directly before finalizing.

## Not independently re-verifiable this session

- Whether a freshly-provider-loaded Instrument for the specific SFO
  2026-09-11 slug would report `theta=0.06` or `0.0695` today — requires a
  live/paper boot or provider read, out of scope for a read-only review.
- `nautilus_pyo3.process_mass_status_for_reconciliation` behaviour (Rust,
  unreadable) — the 09-12 plan already marks this UNVERIFIED; ruling does
  not depend on it.

## Everything else in the ruling

No other defect found. Consequences section (§6) is directionally correct;
once the HIGH item above is folded in, the `:118-123` fallback-value text
needs one more clause (theta-at-fill, not theta-at-reconciliation).

## Delta review (Revision 2)

Verified against `docs/evidence/RULING_venue_reconciliation_R1_R2_2026-09-21.md`,
sha256 `5ce58699133f0973c9cd263e6408bda83792cc6824c164ed98f81a9444fd3146` (hash
confirmed this session). The prior [HIGH] is substantively fixed: theta now
resolves at `record.ts_event` via a new `fee_coefficient_at_fill` field for
new writes, falls back to the dated `FEE_SCHEDULE_PIN` schedule for legacy
rows, refuses on an unresolvable date rather than guessing, `feeSource` is
renamed `RECORDED`/`MODELLED_AT_FILL_TIME`, a RED test for pre-drift-fill/
post-drift-boot is required, and the "byte-identical 0.01" claim is withdrawn
(§4:73-77). R-2 and findings 1-9 are confirmed textually unchanged — no
regression. `feeSource` still never read by trial scoring (finding 3
unchanged) — no new PREREG contamination path introduced.

### [MEDIUM] Remaining gap: the dated schedule is two points, not a resolved step function across the transition day itself

`FEE_SCHEDULE_PIN_2026-09-18.md` evidences `("2026-08-25", 0.06)` (a captured
corpus date) and confirms `0.0695` observed via three alerts timestamped
17:00, 18:00, 20:00 UTC on **2026-09-17** — it does NOT establish the
intraday cutover instant, and states outright "open, out of scope: why
2026-09-17 holds 6 rows against 2026-09-16's 53624" (i.e. whether 09-17
pre-17:00 UTC activity was still billed at 0.06 is not evidenced either way).
The ruling's fallback (§4:80) refuses when `ts_event` "predates the earliest
pinned date, or falls in a gap the schedule does not cover" — but does not
say whether a `ts_event` on 2026-09-17 itself (a record's fill time on the
transition day, before the first observed 17:00 UTC alert) is treated as
"gap" (refuse) or silently mapped to one side of the two-point schedule.
Without an explicit rule, an implementer will pick a boundary (midnight
UTC, most likely) that is not actually in evidence for the first ~17 hours
of that day.

**Required change:** add one sentence to §4's binding text: "`ts_event`
values on 2026-09-17 itself, prior to the earliest confirmed-drift evidence
(17:00 UTC), are an unresolved gap and MUST refuse, not default to either
coefficient; only `ts_event < 2026-09-17T00:00:00Z` resolves to 0.06 and
only `ts_event >= 2026-09-17T17:00:00Z` resolves to 0.0695 without
refusal." This does not block the one existing record (2026-09-11, well
clear of the window) and costs one boundary clause.

**Verdict: ENDORSE-WITH-REQUIRED-CHANGES** (downgraded from the prior
ENDORSE-WITH-REQUIRED-CHANGES's HIGH to one remaining MEDIUM — the load-
bearing defect is fixed; the transition-day boundary is a smaller, bounded
gap that does not block the one record currently in scope but should be
closed before B1 generalizes to future fills near any future drift date).

## Delta review (Revision 3)

Verified against sha256 `e211bae3a0351c6e332c94f8b578b1f8f55d021c043d98377b858ed840714272`.
Boundary clause checked against `FEE_SCHEDULE_PIN_2026-09-18.md`: the
`< 2026-09-17T00:00:00Z → 0.06` bound matches the 09-16 baseline (53,624/53,624
rows at `0.06`), the `>= 2026-09-17T17:00:00Z → 0.0695` bound matches the
first confirmed drift alert (`17:00:00.610319588Z`) and its co-timestamped
offer-tape row, and `[00:00Z,17:00Z)` is correctly named AMBIGUOUS — the pin
doc itself calls that exact gap "open, out of scope." Refusal-not-default
inside the window, a dedicated RED test, and an acceptance-criteria item are
all present. R-2 and findings 1-9 confirmed unchanged — no regression. The
one existing SFO 09-11 record is unaffected either way.

**Verdict: ENDORSE — no required change.**
