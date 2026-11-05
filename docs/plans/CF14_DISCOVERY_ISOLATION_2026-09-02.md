# CF-14 — Discovery: complete the diagnosis before isolating anything

**DESIGN ONLY. No source edited.** Revision 2, 2026-09-02.
**Origin:** `docs/evidence/venue/polymarket_us/LISTING_GAP_INCIDENT_2026-09-02T0845Z.md`;
`docs/core/PROGRESS.md:156`. **Governs:** L-8, L-12, L-13 corollary, L-17, L-14.

## Changelog — Revision 1 → 2

| R1 | R2 | Why |
|---|---|---|
| §3b cohort gate: "0 loaded ⇒ abort, ≥1 loaded ⇒ skip" | **WITHDRAWN** | Defeated by one stray success: 29/30 failing with 1 parsing yields `≥1 loaded`, so 29 markets are skipped on the strength of a log line §9 itself calls unvalidated. A hidden constant of 1, where R1 claimed none. Incremental cohort reveal (measured 5 → ~30 over ~50 min) makes it trigger-happy at n=1 too. |
| §3a isolatable-error set, per-market skip | **DEFERRED → CF-14b** | Unevidenced, not wrong. The base rate of a genuine 1-of-N failure vs a schema rollout is unknown *because we have never been able to see it*. The tally is the instrument that measures it. |
| §4 `DiscoveryRejection` + include-list edit | **DEFERRED → CF-14c** | Cannot fire in its own headline case: on abort, `load_all_async` raises and `_run_one_reload_cycle` (`data.py:1055-1063`) never reaches the publish point. A one-way door on an EXCLUSIVE include-list, taken before a consumer exists. |
| §1 / §10 "one listing run per day" | **FALSIFIED** | Two cohorts entered discovery within 25 min on 09-02 (re-opened 09-01 flip 09:14–09:19Z, discovered 09:20:13Z; new 09-03 `createdAt` 09:45:30Z). R1 §10 said the recommendation flips if this broke. It broke. |
| §3b "re-opened cohorts are narrow — resolved markets `continue` before stage 3" | **WRONG** | Verified: `_resolved_reason` (`provider.py:185-193`) returns `None` for `archived!=True ∧ closed!=True ∧ status=OPEN` — exactly a re-open. Incident log: "loaded 5 active market(s), observed **0 resolved**". |
| §6.3 "Stage 2, all of it" hard-fails | **CORRECTED** | `provider.py:142-144` silently `continue`s when the slug is unparseable AND the question regex misses. Stage 2 is not all-loud. Tracked, not fixed. |
| §1 "capture went to zero" | **CORRECTED (coordinator measurement)** | 132 catalog files written 09:45:30–10:09:41Z for already-subscribed 09-01 instruments. R1's *code reading* was right — abort raises at `data.py:1058` before `_reconcile_discovered_subscriptions`, so it costs only NEW subscriptions. The narrative was wrong. R2 is built on the narrow cost. |
| Survives verbatim | `writer.py` record-drop analysis; the `SiteNotFoundError` alias; the narrow-cost-of-abort reading; evaluate-all-then-decide | Confirmed by review. |

---

# CF-14a — DO THIS. Abort semantics UNCHANGED.

Zero semantic change; a complete diagnosis next time. Four items.

**A1. Evaluate-all-then-decide** in the `load_all_async` loop
(`provider.py:275-294`). Collect every stage-3 failure — regardless of type —
instead of raising on the first.

**A2. A complete per-cohort failure TALLY.** One ERROR naming, for every failure:
slug, city, cohort (`parse_weather_slug(...).climate_date`, `symbology.py:474-506`),
failing field and exception type, plus per-cohort `loaded / failed` counts. Today's
log named one field of one market and nothing about the other 19, which is why
diagnosis required a live payload probe. Highest value per line in this plan, and
it stands alone.

**A3. Narrow the `SiteNotFoundError` alias.** `parsing.py:1225-1231` re-raises it
*as* `InstrumentDefinitionError` (raise at `:1228-1231`), so a
`discovery.city_codes` ↔ `SiteRegistry` mismatch — a Breezy config bug — is
indistinguishable from a venue payload error. Give it a distinct type now, before
CF-14b can ever key on payload-error identity.

**A4. Defer `self.add()` until after the cohort verdict.** A1 otherwise makes the
known `_instruments` leak WORSE: Nautilus `initialize(reload=True)` never clears
`_instruments` (`.venv/.../nautilus_trader/common/providers.py:152-192`), and
today the first raise caps the partial adds — evaluate-all would add every
parseable market before aborting, and `_load_slugs`' `find()` short-circuit
(`provider.py:335`) can then reuse them. Build the instrument list locally; call
`self.add()` only on the success path. Makes the leak strictly smaller, not larger.

### Two constraints on A1/A2 — both are places CF-14a could accidentally change behaviour

**C1 (the one that killed CF-14c — do not repeat it). The tally must be emitted by
the PROVIDER, before it raises** — never by the data client after the cycle
returns. `_run_one_reload_cycle` never reaches its own downstream code on abort
(`data.py:1058`). A tally placed downstream of the raise is a tally that cannot
fire in the exact case it exists for.

**C2. Re-raise the FIRST collected failure**, preserving today's exception type,
message and ordering identity. Log the tally at ERROR immediately before. This
keeps semantic change at exactly zero: `test_bounds_disagreement_fails_closed`
(`tests/unit/test_polymarket_us_discovery.py:238`) and every other existing
abort assertion keep holding unchanged, and no test is weakened.

### What must still hard-fail — unchanged from today, restated for the record

Everything that aborts today still aborts, including all of stage 1
(`provider.py:176-182`, `:359-367`, `:270-271`), the loud parts of stage 2
(`:132-136`, `:138`, `:145-148`, `:149-154`, `:155-161`), `BoundsSemanticsError`
(`:279`; also `parsing.py:1218`), venue self-contradiction (`:288-292`), the L-8
zero-discovery refusal (`:261-267`), and every `InstrumentDefinitionError`. CF-14a
adds no isolation and removes no refusal.

### RED tests — CF-14a only

`tests/unit/test_polymarket_us_discovery.py`
1. every failing market is evaluated before the cycle raises — 3 failures produce 3 tally entries, not 1.
2. the tally is order-independent: failing-first and failing-last give identical tally content.
3. the tally is emitted BEFORE the raise and survives the abort path — pins C1.
4. the raised exception is the FIRST collected failure, unchanged in type and message — pins C2.
5. a cohort-total failure still aborts with `InstrumentDefinitionError` (regression-pins today's incident).
6. mixed cohorts: 3 good + 3 bad still aborts, and the tally names all 3 bad ones.
7. **on abort, `provider.count` and `_market_slugs` / `_active_market_slugs` / `_resolved_market_reasons` are all unchanged from pre-cycle** — pins A4.
8. on success, `self.add()` is still called for every loaded market and the state fields are assigned exactly as today.
9. a `SiteNotFoundError`-derived failure is distinguishable by type from a venue payload error — pins A3.
10. `test_bounds_disagreement_fails_closed` and `test_zero_discovery_cycle_raises_and_alerts_loudly` (`:225`) pass **unmodified**.

**Barrier audit (L-14 — derived from "what would refuse this?", never recalled).**
CF-14a adds no data type and no adapter constant, so the R1 suspicion list is
mostly moot; `tests/unit/test_polymarket_us_provider.py`'s contract test that no
native `InstrumentProvider` method names appear in this subclass's `__dict__` is
the one to watch, plus `test_polymarket_us_reload_resilience.py`. **Run the full
gate and derive the real list from what turns RED. Widen, never relax (L-12).**

---

# CF-14b — DEFERRED: per-market isolation. Unevidenced, not rejected.

R1's boundary reasoning survives and should be reused when this reopens: isolate
**per market at stage 3 only** (stage-2 failures are unnameable — a renamed or
re-dated slug is the incident's own "dangerous hypothesis"), gated by an exact
reviewer-visible tuple `(InstrumentDefinitionError,)` in the L-12 shape.
`BoundsSemanticsError` is a **sibling, not a subclass**, of
`InstrumentDefinitionError` (`errors.py:178`, `:219`), so bounds failures stay
non-isolatable for free.

What is missing is not a mechanism but a measurement: **no gate can be justified
until we know whether a genuine 1-of-N failure ever occurs.** Every stage-3
failure ever observed has been cohort-total.

**REOPEN when** the CF-14a tally records a single cycle in which, **within one
cohort**, at least one market loaded and at least one failed **with a failure
signature not shared by the whole failing set**. That is the first direct
evidence a per-record anomaly exists; design the gate against that observed
distribution, not against speculation. Zero constants, directly falsifiable.

**CLOSE WONTFIX if** a full quarter of daily listings passes with every observed
stage-3 failure event being cohort-total on a single shared signature. Isolation
would never have fired, and the loud abort is simply correct.

---

# CF-14c — DEFERRED: `DiscoveryRejection` on-tape record.

Deferred because it cannot fire in its own headline case (C1), and because adding
an unretractable, unjoinable row type to an EXCLUSIVE include-list
(`node_config.py:275-287`) on a forward-only tape is a one-way door taken before
its consumer exists. Preserved for whenever it lands:

**The `custom_quote_tape_gap` reuse is a trap, and the mechanism is verified.**
`QuoteTapeGap` carries an `InstrumentId` (`tape_records.py:112-122`).
`StreamingFeatherWriter.write` routes any `custom_*` table whose payload has an
`instrument_id` to a per-instrument writer and **returns without writing when
`cache.instrument(id)` is None**
(`.venv/.../nautilus_trader/persistence/writer.py:208-238`) — the silent drop
documented at `data.py:1145-1148`. A skipped market has no cached instrument **by
construction**, so the record documenting the skip would itself be silently
dropped.

**Landing precondition (L-12 — never to be weakened).** `DiscoveryRejection` must
key on a **slug string and expose no `instrument_id` attribute**, with the RED
test `assert not hasattr(rejection, "instrument_id")` carrying a docstring citing
`writer.py:208-238`. **Every sibling in `tape_records.py` carries a required
`instrument_id`**, so a future "for consistency" edit would silently reintroduce
the drop. Also required at landing: a join contract, since `QuoteTapeGap`'s
(`tape_records.py:73-94`) does not transfer to an instrument-less row.

Also not recommended then or now: the `AlertSink` webhook
(`runtime/health.py:385-514`) — an egress path, forbidden on this read-only path.

---

## Tracked hazards — recorded, deliberately NOT fixed here

1. **Stage 2 is not all-loud.** `provider.py:142-144` silently `continue`s when
   the slug is unparseable AND the question regex misses. Already filed as open
   item 1 of the incident write-up; restated because R1 §6 wrongly claimed
   otherwise.
2. **Stage-2 resolved-misclassification.** A market wrongly marked resolved by
   `_resolved_reason` (`provider.py:185-193`) `continue`s at `:276-278` before
   stage 3, counting toward neither loaded nor failed — so no future gate can see
   it, and the cycle-level `after == 0` alert (`data.py:1121-1125`) is masked
   whenever another cohort is healthy. Pre-existing; outside CF-14a's scope.
3. **Half-mutated `_instruments` on abort** — reduced by A4, not closed.
4. `_last_successful_non_empty_discovery` (`provider.py:236,299`) is written and
   read nowhere in `src/` or `tests/`. Dead field. Confirmed by two reviewers.

## Could not verify

- Whether an ERROR-level tally is read in time by anyone. CF-14a does not depend
  on this (it changes no semantics), but **CF-14b will**, and reopening it must
  settle the question first rather than inherit R1's assumption.
- Whether the venue can list two *new* cohorts in one cycle, as distinct from one
  new plus one re-opened (the measured 09-02 case).
- Whether the incremental cohort reveal (5 → ~30 over ~50 min) is the venue
  publishing progressively or Breezy's `active`/`closed` filter admitting
  progressively. It matters for any future cohort-scoped rule.

## Least-confident decision — aim here first

**A4, deferring `self.add()` until after the cohort verdict.** It is the only item
in CF-14a that changes provider state timing rather than only logging, so it is
the only one that could alter behaviour in a way tests 7 and 8 might not span.
The specific unknown: whether any caller depends on instruments being present in
`_instruments` *during* a cycle rather than after it. `_load_slugs`
(`provider.py:333-353`) is the one path that reads `find()` mid-flight, and it is
driven by `load_ids_async`, not by `load_all_async` — so on the current call graph
they cannot interleave. If that is ever false, A4 is wrong and should be dropped;
CF-14a's value is in A1–A3 regardless.

## Pushback registered

None on the decision. Shrinking to tally-only is right: the gate two reviewers
independently broke had no defensible constant-free form, and the tally is the
instrument that would let us build one from data. Two additions the brief did not
state, both above and both load-bearing: **C1** (the tally must precede the raise,
or CF-14a reproduces the exact flaw that killed CF-14c) and **C2** (re-raise the
first collected failure, so "abort semantics unchanged" is literally true at the
exception level and no existing assertion needs touching).
