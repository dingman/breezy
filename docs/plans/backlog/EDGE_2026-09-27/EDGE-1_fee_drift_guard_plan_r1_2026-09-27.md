# EDGE-1 — Fee-drift guard is blind (UNKNOWN never halts, and the wire read is 100% broken)

**Status:** DRAFT r1 · **Date:** 2026-09-27 · **Severity:** HIGH (safety) · **Author:** trading-bot-architect (plan only — no source/test edits, no git, no service changes)

## Goal & acceptance criteria

1. `fetch_wire_fee_coefficient` correctly parses the venue's real
   `GET /v1/market/slug/{slug}` envelope (`{"market": {...}}`), so a live
   probe fire against a real, open, correctly-fee-tagged market returns
   `AGREE` or `DISAGREE` — never `UNKNOWN` — under normal venue conditions.
   Testable: a unit test constructs the fixture from the ACTUAL captured
   envelope shape (`docs/evidence/venue/polymarket_us/raw/market_open_510636_by_slug.json`),
   not a flattened stand-in, and asserts a parsed `Decimal`.
2. Sustained inability to verify the wire fee (N consecutive `UNKNOWN`s)
   flips a new, distinct, self-clearing "fee unverified" submit-veto that
   blocks new order submission for the affected family until the NEXT
   successful probe fire (`AGREE` or `DISAGREE`) — without invoking the
   durable, operator/peer-ruling-gated `TrialDayLatch.record_policy_halt`
   path that `DISAGREE` uses. Testable: `N` consecutive `UNKNOWN`s sets the
   veto; a subsequent `AGREE` clears it; a subsequent `DISAGREE` clears it
   (and separately halts, as today).
3. Crossing the veto threshold, and the veto persisting past an escalation
   window, each emit their own distinct, named alert — never silently folded
   into the existing per-fire `fee_drift_probe_unknown` CRITICAL. Testable:
   alert-sink assertions on event names.
4. No change weakens `DISAGREE`'s existing behavior (unconditional halt,
   per-value dedupe, halt-set-failure alerting) — all three pre-existing
   `DISAGREE` tests keep passing unmodified in substance.
5. Zero new network calls, zero new endpoints, zero new credentials; the
   fix stays inside the already-injected `wire_fee_fetcher` /
   `_PublicReadClient` seam.
6. Plan explicitly states what does and does not feed Ruling A1 condition 3
   (the A0 evidence pack) and reports A0's *actual current* consecutive-day
   count, not an assumed one.

## Evidence / root cause (file:line)

**The wire read is not "sometimes unknown" — it has NEVER once succeeded.**
`/usr/bin/grep -oh "event=fee_drift_probe_[a-z_]*" ~/.local/share/breezy/logs/breezy-trade-2026*.log`
across every retained trade-node log returns **only** `fee_drift_probe_unknown`
(5 occurrences, all in the current boot `breezy-trade-20260926T165018Z.log`,
one per 2h fire: 16:50, 18:50, 20:50, 22:50, 00:50Z) — never one
`fee_drift_probe_mismatch` or a silent `AGREE`, across the probe's entire
deployed life (`e1eb9ed` "run the fee-drift probe on the live continuous
node" through `ea0095e`, 09-25). A 100% failure rate with an identical
exception type on every fire is the signature of a deterministic code
defect, not venue flakiness, an auth/scope problem, or a genuine venue-side
schedule change.

**The HTTP call itself succeeds.** Log line immediately preceding every
alert (`breezy-trade-20260926T165018Z.log:562-563`):

```
16:50:23.673Z [INFO] ...POLYMARKET_US-http: GET https://gateway.polymarket.us/v1/market/slug/tc-temp-laxhigh-2026-09-26-lt77f status=200 ...
16:50:23.673Z [ERROR] ...breezy alert event=fee_drift_probe_unknown ... detail=wire fee read failed: WireFeeCoefficientError
```

`status=200` — the unauthenticated `get_public` path is reachable, correctly
routed, and the venue answers. This rules out: wrong endpoint (it is the
same `MARKET_BY_SLUG_PATH = "/v1/market/slug/{slug}"` `provider.py:84` and
`parsing.py` use successfully elsewhere), auth/scope (no credential is even
attached — `get_public` is unauthenticated by construction, confirmed
`http.py:137-152`), and rate-limiting/quota exhaustion (a 429 would raise
`VenueRateLimitError`, not `WireFeeCoefficientError`). The failure happens
strictly AFTER a successful 200 response, inside payload parsing.

**Root cause: an envelope-unwrap bug — `fetch_wire_fee_coefficient` reads
the field one level too shallow.**
`src/breezy/strategy/current_rung_hold/fee_drift_probe.py:184-186`:

```python
path = MARKET_BY_SLUG_PATH.format(slug=slug)
payload = await client.get_public(path, quota_key=quota_key)
raw = payload.get(FEE_COEFFICIENT_WIRE_KEY)   # payload.get("feeCoefficient")
```

But `GET /v1/market/slug/{slug}` returns the market object WRAPPED under a
`"market"` key, never flat. Proof, three independent sources:

- **The venue SDK's own response type**,
  `docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/types/markets.py:125-128`:
  `class GetMarketResponse(TypedDict): market: MarketDetail`.
- **Two real captured payloads**,
  `docs/evidence/venue/polymarket_us/raw/market_open_510636_by_slug.json` and
  `market_closed_15806_by_slug.json`: both are
  `{"market": {..., "feeCoefficient": 0.06, ...}}` — `feeCoefficient` is a
  child of `"market"`, never a top-level key of the response body.
- **Breezy's own parser already knows this and unwraps it correctly.**
  `src/breezy/adapters/polymarket_us/parsing.py:1386`
  (`parse_binary_option`) and `:1496` (`parse_binary_option_pair`) both open
  with `market = _require_mapping(payload, "market", context="market payload")`
  before reading anything, and `_parse_fee_coefficient` (`parsing.py:618-643`)
  is called on that unwrapped `market`, reading `market.get("feeCoefficient")`
  (`parsing.py:639`) — exactly the field name the probe uses, at exactly one
  more level of nesting than the probe reads it at.

**A0's own fallback path (built one AUD item later, same endpoint) already
has the correct unwrap** — the fix pattern to mirror is already in-tree:
`scripts/venue/fee_drift_evidence_pull.py:458`
(`pull_slug`, the bounded per-slug fallback):

```python
market = payload.get("market") if isinstance(payload.get("market"), Mapping) else payload
```

This is strong corroboration, not a new invention: a later, independent
implementation against the identical endpoint (`MARKET_BY_SLUG_PATH`,
imported from `fee_drift_probe.py` itself) hit the same shape and handled
it; `fetch_wire_fee_coefficient` alone never did.

**Why the unit suite never caught it.**
`tests/unit/test_fee_drift_probe.py:328-337` (`_RecordingHttpClient`) and
its three callers (`:347-372`,
`test_fetch_wire_fee_coefficient_uses_the_unauthenticated_gateway_path`,
`_raises_on_a_missing_field`, `_raises_on_a_malformed_field`) all construct
the fixture FLAT — `_RecordingHttpClient({FEE_COEFFICIENT_WIRE_KEY: "0.06"})`
— never the real `{"market": {...}}` envelope. The mock shape and the real
wire shape diverged, and the test that should have caught the divergence
(the "happy path" `AGREE`-producing test) instead exercises a payload shape
the real venue never sends. This is the second, independent defect: a
test-fixture/reality gap, not just a production bug. Any fix must correct
both.

**Confirmed non-causes, explicitly ruled out (per this item's own brief):**
venue response shape has NOT drifted (both a 2026-04-23 and a 2026-08-25
capture show the identical `{"market": {...}}` wrapper — this has been the
shape all along); it is not the wrong endpoint; it is not an auth/scope
problem.

## Options & trade-offs

### (a) Fix the parse

Only one reasonable option: unwrap `payload["market"]` before reading
`feeCoefficient`, mirroring `pull_slug`'s existing
`payload.get("market") if isinstance(..., Mapping) else payload` idiom (a
defensive fallback to the raw payload if some future response is ever flat,
rather than a hard `_require_mapping` — deliberately looser than
`parsing.py`'s `_require_mapping`, because this probe's job is DETECTION,
not instrument construction: an even-more-malformed envelope should still
fail closed to `WireFeeCoefficientError`/`UNKNOWN`, never raise an unhandled
exception out of `probe_once`, which is already guarded by `probe_once`'s
own bare `except Exception`). No alternative design considered — this is a
one-line correction of a proven defect, not a judgment call.

### (b) Fail-closed policy for sustained UNKNOWN — two candidates

**Option B1 — escalate UNKNOWN into the SAME durable halt `DISAGREE` uses**
(`set_family_halted` → `TrialDayLatch.record_policy_halt`) after N
consecutive UNKNOWNs.
*Cost:* `record_policy_halt` is described, in this probe's own wiring
(`app/trade.py:296-301`), as a write nothing in this module can clear —
clearing a `policy_halt` is the kind of durable state Ruling A1's own
apparatus treats as needing an operator/peer act to reverse. Routing a
transient read failure (a network blip, a slow venue maintenance window —
exactly the kind of flakiness this repo has already measured: quote-ingest
timed out 22 times over 2026-09-24..26 per the 2026-09-27 audit) into that
same expensive, human-gated halt would convert ordinary flakiness into a
halt an operator must explicitly, ceremonially clear — precisely the
"operational cost of false halts" this item asks to weigh, and precisely
why AUD-12b's original author deliberately chose NOT to halt on UNKNOWN in
the first place (module docstring, "a probe interval's worth of ordinary
read flakiness" should not "convert into a family-wide trading stop").

**Option B2 — a separate, non-durable, self-clearing "fee unverified"
submit-veto** (chosen). While N consecutive fires return UNKNOWN, a plain
boolean/timestamp state — NOT `TrialDayLatch.record_policy_halt` — is set,
consulted at the same submit-veto site `family_halt_submit_veto` already
reads (so refusing to submit is structurally identical to the existing
halt-veto check, just backed by different state). The MOMENT a later probe
fire returns `AGREE` or `DISAGREE` (both are "we got a real, current answer
this cycle" — `DISAGREE` additionally halts through the existing path), the
veto clears automatically — no operator action, no peer ruling, no re-arm
ceremony. Cost of a false positive is bounded to at most one probe interval
(2h) of no NEW submissions for the affected family; already-open positions,
exits, and everything else this repo's exit-guard/reconciliation paths do
are untouched (this veto is scoped to NEW order submission only, exactly
like the existing halt-veto's own scope).

**Chosen: B2.** It fails closed on the thing that actually matters — never
submitting an order whose fee-schedule assumption is currently unverified —
without inheriting B1's expensive, durable-halt blast radius for what is
usually a transient read problem. B1's mechanism stays available: an
operator (or a future ruling) can always still choose to escalate a
persistent unverified state into a real `policy_halt` by hand; B2 does not
foreclose that, it just declines to do it AUTOMATICALLY for something that
might resolve on its own within one interval.

**Threshold N.** N=2 consecutive UNKNOWNs (≤4h exposure) before the veto
engages — long enough to absorb one isolated transient read failure without
blocking trading, short enough that the family is never left both "actively
submitting orders" and "unable to verify its own fee schedule" for more
than one missed interval beyond the first. `interval_seconds` stays the
existing `DEFAULT_FEE_DRIFT_PROBE_INTERVAL_SECONDS` (2h) — this item does
not touch cadence.

**Alerts (new, both distinct from the existing per-fire
`fee_drift_probe_unknown`):**
- `fee_drift_probe_unverified_submit_veto_engaged` (CRITICAL) — fired once,
  the fire that crosses N, naming N and the elapsed span. This is the
  actionable, escalated signal an operator should page on, as opposed to
  the routine per-fire `fee_drift_probe_unknown` (which, per the live
  evidence, has already fired 5 times unread — a detector alone is not a
  control; this alert is the escalation the existing one lacks).
- `fee_drift_probe_unverified_submit_veto_persisting` (CRITICAL) — mirrors
  the existing `_alert_mismatch_persisting` idiom exactly (same
  `_MISMATCH_SUPPRESSION_WINDOW_NS`-style 24h reminder, timed on
  `self.clock.timestamp_ns()`, never wall time), fired if the veto is still
  engaged 24h after it engaged, and re-arms its own window.
- Veto clearing (`AGREE` or `DISAGREE` after the veto was engaged) is logged
  INFO, not alerted — resolution is good news, not a paging event, matching
  this file's existing asymmetry (AGREE is always silent).

### (c) Do NOT conflate this with A0

A0 (`docs/evidence/venue/polymarket_us/FEE_DRIFT_EVIDENCE_2026-09-25.md`)
explicitly excludes `FeeDriftProbeActor` samples from its own evidence set
("AUD-12b's `FeeDriftProbeActor` samples are excluded from this evidence
set regardless of date" — closing rule item 1). Fixing the probe does not
add a row to A0's table and must not be presented as though it does.

## Architecture & data flow

No new component. This is a bug fix plus one additive state machine inside
the existing `FeeDriftProbeActor`:

```
FeeDriftProbeActor.probe_once()
  -> _wire_fee_fetcher() -> fetch_wire_fee_coefficient()   [FIXED: unwrap "market"]
       -> AGREE      -> counters["agree"]++; reset consecutive_unknown; clear veto if engaged (INFO log)
       -> DISAGREE    -> existing dedupe/alert/halt path, UNCHANGED; reset consecutive_unknown; clear veto if engaged (INFO log)
       -> UNKNOWN     -> existing _alert_unknown, UNCHANGED; consecutive_unknown++
                         if consecutive_unknown == N: engage veto, call `set_fee_unverified()`,
                                                       alert veto_engaged (CRITICAL)
                         elif veto already engaged and >=24h since engaged/last reminder:
                                                       alert veto_persisting (CRITICAL)
```

`set_fee_unverified` / `clear_fee_unverified`: two new injected callables,
same PULL-seam idiom as `set_family_halted` (constructor parameters, wired
once in `app/trade.py::_build_fee_drift_probe`). The wiring site backs them
with a plain state row read by the SAME submit-veto check site that already
reads `family_halt_submit_veto` (`current_rung_hold/composition.py`) — this
item does not need to invent a new store; it needs to invent a new KEY,
distinct from `continuous_rung_hold/halt`, e.g.
`continuous_rung_hold/fee_unverified` (exact key name is an implementation
decision for the build agent, not fixed here) — read the same way, ORed
into the same submit-refusal decision, but writable AND clearable by this
module, unlike the halt key.

## File-by-file plan

- **`src/breezy/strategy/current_rung_hold/fee_drift_probe.py`**
  - Fix `fetch_wire_fee_coefficient` (lines 184-186): unwrap
    `payload.get("market")` (falling back to `payload` itself if `"market"`
    is absent/not a mapping — mirrors `fee_drift_evidence_pull.py:458`)
    before reading `FEE_COEFFICIENT_WIRE_KEY`. Update the module docstring's
    field-provenance comment (currently cites `parsing.py:639` correctly but
    the function below it did not follow that citation).
  - Add `_consecutive_unknown: int` state, `unknown_veto_threshold: int = 2`
    constructor param, `set_fee_unverified: Callable[[], None]` and
    `clear_fee_unverified: Callable[[], None]` constructor params (both
    required keywords, same style as `set_family_halted`), the two new
    `_alert_*` methods, and the branch in `probe_once` per the data-flow
    above. Reset `_consecutive_unknown` and call `clear_fee_unverified` (if
    previously engaged) on both `AGREE` and `DISAGREE`.
  - Both halt-set-failure-style safety nets apply here too: a
    `set_fee_unverified`/`clear_fee_unverified` raising must not crash
    `probe_once` — wrap each the same way `_set_family_halted` is already
    wrapped, with its own distinct alert on failure
    (`fee_drift_probe_unverified_veto_set_failed` /
    `..._clear_failed`) so "veto engaged" vs. "veto SHOULD be engaged but
    the write failed" never look identical in the alert stream — same
    reasoning `_alert_halt_set_failed`'s own docstring already states for
    `DISAGREE`.

- **`src/breezy/app/trade.py`** (`_build_fee_drift_probe`, ~246-390)
  - Wire `set_fee_unverified`/`clear_fee_unverified` against the new state
    key, using the SAME already-open `TrialDayLatch`/store handle this
    function already threads through for `set_family_halted` — no second
    store open. Read, do not reinvent, whatever accessor
    `current_rung_hold/composition.py`'s `family_halt_submit_veto` already
    uses for its OWN read-side, and add the fee-unverified key to that same
    OR'd refusal check (this second file is in this item's blast radius —
    confirm via `codegraph_explore "family_halt_submit_veto"` before
    editing, not assumed here).

- **`tests/unit/test_fee_drift_probe.py`**
  - Fix `_RecordingHttpClient` fixture shape: every existing
    `fetch_wire_fee_coefficient` test must construct
    `{"market": {FEE_COEFFICIENT_WIRE_KEY: "0.06"}}` (or the missing/malformed
    variants nested the same way), not a flat mapping. This is the
    regression guard for the actual production defect — a fixture fix that
    stays flat would re-hide the same bug.
  - New RED tests (see Test strategy).

- **`tests/unit/test_app_trade_fee_drift_probe_wiring.py`** (existing file
  per `RULING_fee_drift_probe_target_2026-09-25.md`'s own citation) — extend
  with a wiring-level test that the fee-unverified veto reaches the same
  submit-refusal site the halt-veto reaches, mirroring
  `test_disagree_reaches_the_same_latch_the_submit_veto_reads_and_alerts_once`.

## Test strategy (RED list)

Envelope-fix regression (the core defect):
- `test_fetch_wire_fee_coefficient_unwraps_the_market_envelope` — payload
  shaped exactly like the real captured
  `market_open_510636_by_slug.json`/`market_closed_15806_by_slug.json`
  (top-level `{"market": {...}}`, `feeCoefficient` nested) → returns the
  parsed `Decimal`, not `WireFeeCoefficientError`.
- `test_fetch_wire_fee_coefficient_raises_on_a_missing_field` — updated to
  nest under `"market"` with `feeCoefficient` absent → still raises (field
  genuinely missing, now correctly detected AT the right level instead of
  by accident at the wrong level).
- `test_fetch_wire_fee_coefficient_raises_on_a_malformed_field` — same,
  nested, malformed value → still raises.
- `test_fetch_wire_fee_coefficient_raises_when_market_key_itself_is_missing`
  (new) — a flat/malformed envelope with no `"market"` key at all → the
  fallback-to-`payload` path still raises cleanly (never an unhandled
  `AttributeError`/`TypeError` escaping `fetch_wire_fee_coefficient`).

Fail-closed UNKNOWN-veto (new behavior):
- `test_n_consecutive_unknowns_engages_the_fee_unverified_veto_and_alerts`
- `test_fewer_than_n_consecutive_unknowns_does_not_engage_the_veto`
- `test_an_agree_after_the_veto_clears_it_and_logs_not_alerts`
- `test_a_disagree_after_the_veto_clears_it_in_addition_to_halting`
- `test_the_veto_persisting_past_the_escalation_window_fires_exactly_one_reminder`
- `test_veto_set_failure_alerts_distinctly_and_never_crashes_probe_once`
- `test_veto_clear_failure_alerts_distinctly_and_never_crashes_probe_once`
- (wiring) `test_the_fee_unverified_veto_reaches_the_same_submit_refusal_site_the_halt_veto_reaches`

Unchanged-behavior guards (must still pass, asserting no regression):
- `test_probe_once_disagrees_alerts_critical_and_halts`
- `test_probe_once_never_raises_when_the_halt_set_write_itself_fails`
- `test_disagree_persists_the_halt_through_a_real_trial_day_latch_and_the_veto_then_refuses`
- `test_an_unknown_never_resets_the_mismatch_dedupe` (UNKNOWN must still
  leave `DISAGREE` dedupe state untouched — orthogonal to the new veto
  counter)
- `test_documented_fee_coefficient_default_is_byte_identical_to_the_pin`

Run via `scripts/ci/run_tests_no_egress.sh`; `lint-imports` after the slice
(this module must still never import `breezy.runtime` beyond what it
already does, and the execution-egress firewall guard test must keep
reporting this module silent, exactly as `fee_drift_evidence_pull.py`'s own
docstring already asserts for itself).

## Execution order & parallelism

Single seam, single file pair — no parallel fan-out needed for the build
itself:
1. RED: fixture-shape fix + envelope-unwrap tests (above) — prove the
   defect with a failing test against the corrected fixture shape.
2. GREEN: the one-line `fetch_wire_fee_coefficient` fix.
3. RED: veto state-machine tests.
4. GREEN: `FeeDriftProbeActor` veto additions.
5. RED→GREEN: `app/trade.py` wiring + composition read-side.
6. Full gate (`run_tests_no_egress.sh` + `lint-imports`) after every slice,
   per the binding invariant.

## Deploy & verification (what proves it live)

- Node-side change (`fee_drift_probe.py`, `app/trade.py`): live only on the
  next node respawn (binding invariant — never kill the live node to
  deploy). Since the family is currently HALTED (policy_halt, 09-24
  16:42:30Z) and 0 orders are flowing, this fix can safely wait for the next
  scheduled/hand-triggered respawn without any trading-window cost.
- **Proof of fix, once live:** the NEXT probe fire (within 2h of boot,
  `on_start` also fires one immediately) must log `fee_drift_probe`'s
  outcome as `AGREE` or `DISAGREE` — grep
  `~/.local/share/breezy/logs/breezy-trade-<latest>.log` for
  `event=fee_drift_probe_mismatch` or the ABSENCE of a new
  `fee_drift_probe_unknown` at the next 2h boundary. A single further
  `fee_drift_probe_unknown` post-deploy is not proof of failure by itself
  (could be one genuine transient read) — proof of failure is a SECOND
  consecutive one, or the new `..._veto_engaged` alert firing.
- Given `pm_us_crh_v4` is registered at `taker_fee_coefficient = 0.0695`
  (per `RULING_fee_drift_probe_target_2026-09-25.md`) and the venue has
  served `0.0695` since 2026-09-17 (per `FEE_SCHEDULE_PIN_2026-09-18.md`),
  the expected steady-state outcome post-fix is `AGREE` — a `DISAGREE`
  post-fix would itself be a genuine, newsworthy finding (a second real
  drift), not a sign the fix is broken.

## Risk register

| Risk | Mitigation |
|---|---|
| Fix introduces a NEW shape assumption (`payload["market"]`) that also drifts later | The fallback-to-flat-`payload` branch (mirroring `pull_slug`) keeps the probe from crashing if the envelope ever changes again; it still correctly reports `UNKNOWN` rather than silently mis-parsing, and the new veto now gives that state teeth. |
| N=2 threshold too aggressive/lax | Both directions are bounded and self-healing (worst case: 2 missed intervals before veto, or up to one extra interval of silent unverified trading if too lax) — not a durable commitment; a future item can retune N from lived data once the fix has run for a while. |
| Veto and halt states diverge/race (e.g., a DISAGREE fires while a veto-clear from a prior AGREE is in flight) | Both writes go through the probe's own single-threaded `probe_once` coroutine per fire; no two outcomes are ever "in flight" concurrently for the same Actor instance — no new concurrency hazard beyond what `DISAGREE`'s existing halt-set already has. |
| Test-fixture fix (making `_RecordingHttpClient` nest under `"market"`) accidentally narrows what the fetcher accepts, weakening a currently-passing case | Every existing assertion (return value, exception type) is preserved; only the INPUT shape changes to match reality — this is a fixture correction, not a loosened assertion, and is exactly the "never weaken a safety/contract test to go green" floor applied in the correct direction (tightening the fixture to match the real wire, not loosening the code under test). |
| Someone reads "A0 has 1/5 days" as this item's problem to fix | Explicitly scoped out below — A0's timer is healthy and running on its own schedule; this item does not touch it. |

## LESSONS / invariant compliance

- Nautilus Trader untouched; extension stays inside the existing native
  `Actor`/`Clock.set_timer` shape already in place — no new mechanism.
- `allow_short` untouched; no execution-path code touched at all (this
  module is confirmed, by its own docstring and an existing firewall test,
  never to import anything under `.exec`).
- No safety/settlement/contract test weakened — the three cited `DISAGREE`
  tests are asserted UNCHANGED in substance; the fixture-shape fix
  tightens realism, it does not loosen an assertion.
- No operator-reserved cap assigned; no live-trading enablement touched;
  the A1 halt is untouched and this item neither sets nor clears it.
- "Verify agent claims against the artifact" / "a detector without delivery
  is not a control" (readiness audit 2026-09-12 lesson): this plan is
  built entirely from live log grep, real captured venue payloads, and
  the actual A0 timer/journal state — not from the module's own docstring
  claims (which, notably, never mention the envelope bug at all — the
  docstring's confidence in the design does not match the code's actual,
  0-for-5-forever behavior).

## Dependencies on other EDGE items

None known. This item is self-contained (one module pair plus its tests
and the one wiring call site).

## Ruling A1 condition-3 / A0 tie-in

**A0 and this item are formally independent** — A0's own closing rule
excludes `FeeDriftProbeActor` samples "regardless of date"
(`FEE_DRIFT_EVIDENCE_2026-09-25.md`, closing rule 1). Fixing this probe
does not add a day, a slug, or a value to A0's evidence table, and must
not be cited as progress toward condition 3.

**A0's actual current state (verified live, not assumed):**
`systemctl --user status breezy-fee-evidence-pull.service` and its journal
show the timer IS installed, enabled, and firing daily at 11:10 UTC:
- 2026-09-25 11:10Z: `complete=False markets_listed=0 ok=0` (empty listing —
  predates the same-day ordering-filter fix documented in the script's own
  "Fail loudly" section; recorded, does not count toward the streak).
- 2026-09-26 11:10Z: `complete=True markets_listed=60 ok=60` — one COMPLETE
  day, verified from `data/evidence/fee_drift/2026-09-26/` and the unit
  journal.
- **A0 therefore currently has 1 of the required ≥5 CONSECUTIVE complete
  days.** Barring another incomplete day, the earliest A0 could close is
  2026-09-30 (five straight completes 09-26..09-30). This plan does not
  change that timeline; it is reported here only so this item is not
  mistaken for A0 progress by a later reader.
- **Per-slug re-pull:** already covered by A0's own bounded fallback
  (`pull_slug`, `fee_drift_evidence_pull.py:437-469`), which ALREADY
  performs the correct `{"market": {...}}` unwrap this item is adding to
  the probe — no gap here, and the two code paths should be recognizably
  the same idiom after this fix (a follow-up could extract a shared
  one-line helper, not required by this item).
- **Maker field recorded independently:** already covered — A0 records
  `makerCommissionsBasisPoints` verbatim, separately from the taker B-6
  verdict, never backfilled from the documented constant
  (`fee_drift_evidence_pull.py:210-219`, `FEE_DRIFT_EVIDENCE_2026-09-25.md`
  item 4). No gap.
- **Wire-vs-tape-writer drift, separated: a real, currently OPEN gap, out
  of this item's scope.** A0 compares the wire to itself day-over-day
  (STEP CHANGE vs. NON-STATIONARY of raw wire values); neither A0 nor the
  probe currently cross-checks the live wire fee against what is actually
  baked into an ALREADY-CACHED, currently-open instrument in the running
  node's own catalog (parsed once at load time by
  `parsing.py:_parse_fee_coefficient` into `BinaryOption.taker_fee`/
  `info[FEE_COEFFICIENT_KEY]`, and never re-parsed while that instrument
  stays cached). That second comparison — "does our own already-loaded
  instrument still match what the venue serves RIGHT NOW" — is exactly the
  gap `current_rung_hold/decision.py:342`'s per-order check would need a
  fresh wire read to close and currently cannot; this probe closes the
  "wire vs. our DOCUMENTED constant / registered manifest theta" gap, not
  the "wire vs. our own already-cached instrument" gap. Flagging this as a
  candidate for a future EDGE/AUD item, not building it here — it needs its
  own design (which cached instrument, refreshed how often, whose
  responsibility to re-parse) and is out of scope for "the fee-drift guard
  is blind."

**Why this item still matters for re-arm even though it isn't A0.** Ruling
A1's re-arm conditions are a checklist, not a single gate; a re-armed
family with a silently-broken independent fee-drift detector (0-for-5
forever, currently) is exactly the "detector without delivery is not a
control" failure mode this repo already paid for once (readiness audit,
alerts-reach-nobody, fixed 09-20 after 3 days + 11h of silent halt). This
item should land before or alongside any future A1-class re-arm, as a
readiness precondition for TRADING SAFELY once re-armed — not as a
component of condition 3 itself.

## Confidence self-assessment

**High confidence (root cause):** the envelope-unwrap defect is confirmed
by three independent sources (SDK type, two real captures, this repo's own
correct parser) plus a live-log signature (100% failure, always the same
exception, always immediately after an HTTP 200) that is inconsistent with
every alternative explanation (auth, endpoint, venue drift) and consistent
with exactly one (a shallow field read). The masking test-fixture gap is
directly read from the test file, not inferred.

**Medium confidence (veto design specifics):** the choice of B2 over B1 and
N=2 is a judgment call, argued from this repo's own stated design
philosophy (AUD-12b's original UNKNOWN-never-halts rationale, this item's
own "consider the operational cost" instruction) rather than from a
measured false-positive rate — there is no historical data yet on how often
this specific probe's reads would transiently fail once the underlying bug
is fixed (it has never once succeeded, so its OWN flakiness rate, as
opposed to the rest of the node's measured network flakiness, is unknown
until it runs correctly for a while).

**Open questions:**
- Exact new store-key name and whether `current_rung_hold/composition.py`'s
  `family_halt_submit_veto` read-side is a single OR'd boolean or needs a
  second named check — left to the implementing agent after a fresh
  `codegraph_explore` on that function (not fully expanded in this pass).
- Whether N=2 should instead be a time-based staleness bound (e.g. "no
  successful read in the last 4h") rather than a fire-count, which would
  be robust to a future cadence change; fire-count is simpler and matches
  this file's existing `_consecutive`-style idioms, but a build-time
  reviewer may prefer the time-based framing.
