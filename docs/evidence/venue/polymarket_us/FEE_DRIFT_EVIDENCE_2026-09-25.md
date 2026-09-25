# Fee-drift evidence pack — pre-registered header (AUD-02 A0)

**Status: PENDING.** This header is committed BEFORE any real pull runs (the
timer is not yet installed/enabled — the coordinator does that separately).
Every rule below is fixed as of this commit and is never loosened after data
starts arriving; only the observed-set tables beneath "Observations" may grow.

Authority: `docs/plans/backlog/AUDIT_2026-09-21/AUD-02-COMPLETION-PLAN-2026-09-25.md`
Section 2 "A0" and its Rev 2.1 addendum. Producer:
`scripts/venue/fee_drift_evidence_pull.py`, driven by
`deploy/systemd/breezy-fee-evidence-pull.{service,timer}` (11:10 UTC daily).

**Runtime-fix amendment (2026-09-25, before any observation was recorded).**
The first live run (05:43Z) timed out at `TimeoutStartSec=900` with zero
artifacts written: the original design GETed every listed weather slug
individually, and the real universe under `categories=climate` is 4353
markets since inception (paged to eof, `limit=500`) -- an unauthenticated,
public per-slug GET for each, paced at 6/min, would take roughly 12 hours.
Measured the same day: **every** listed market object already carries its
own `feeCoefficient` (0 missing across all 4353), so the fixed design reads
the fee straight off the list response and narrows the denominator to the
**currently tradable universe** (`active=true, closed=false, archived=false`
-- 58 markets that day, 48 of which parse as a weather slug), matching
`PolymarketUSMarketDiscoveryConfig`'s own defaults and keeping this
denominator consistent with WP-D1's. This amendment happens BEFORE the
"Observations" table below has a single row, so it changes the
pre-registered rule rather than loosening it after data arrived. See
`scripts/venue/fee_drift_evidence_pull.py`'s module docstring for the full
measurement and the fix.

## Pre-registered closing rule

1. **Evidence set.** Only observations produced by this script's own daily
   pulls, dated strictly after **2026-09-17**. AUD-12b's `FeeDriftProbeActor`
   (`30dd034`) is a single-slug, in-node DETECTOR sampled at its own
   2-hour cadence; its samples are **excluded** from this evidence set
   regardless of date. The two are compared against each other only via
   `docs/evidence/RULING_fee_drift_probe_target_2026-09-25.md` (a separate,
   parallel ruling; not a dependency of this doc's own closing rule).

2. **Complete day.** A UTC day counts as COMPLETE only if at least **95%**
   of that day's venue-listed weather slugs (the day's denominator: the
   `GET /v1/markets?categories=climate&active=true&closed=false&archived=false`
   response, paged to eof and stored verbatim by the pull script -- the
   CURRENTLY tradable universe, per the runtime-fix amendment above, not the
   full historical archive) returned a parseable `feeCoefficient`. A day
   below that threshold is recorded in the raw directory and in the table
   below, but does **not** count toward the required length.

3. **Required length.** At least **5 consecutive** complete days are
   required before a verdict may be rendered. Fewer than 5 consecutive
   complete days closes as PENDING, not as a negative finding.

4. **B-6 verdict — rendered exactly as follows, no other wording:**
   - **STEP CHANGE** if every post-2026-09-17 observation across all
     complete days is a single value.
   - **NON-STATIONARY** if there are two or more distinct post-2026-09-17
     values across complete days.

   The maker-side wire field (`makerCommissionsBasisPoints`, read verbatim
   off the raw payload — see the pull script's module docstring for why this
   is never backfilled from `MAKER_FEE_COEFFICIENT` or a parsed
   `Instrument`) is reported as its own per-day observed-value set,
   separately from the B-6 verdict, which is taker-only.

5. **Day-list completeness.** Before this evidence set is closed, WP-D1's
   result (`docs/plans/backlog/AUDIT_2026-09-21/AUD-02-COMPLETION-PLAN-2026-09-25.md`
   Section 2 "WP-D1") is cited here to confirm the venue's own market list is
   a complete source for each counted day — i.e. that the denominator this
   script pages to eof is not itself an undercount. Citation:
   **PENDING** (WP-D1 has not yet closed as of this commit).

6. **Raw-data retention.** `data/evidence/fee_drift/<UTC date>/` is outside
   git (`.gitignore`). Each day's raw directory is fingerprinted by the
   `manifest.sha256.json` the pull script writes alongside it; that
   per-file sha256 mapping is copied into the day's row below once
   observations begin. **No retention or cleanup job may prune this
   directory** — none currently reads or writes under `data/evidence/`, and
   this doc is the record excluding it from that surface by name.

## Observations

No pull has run yet. This table is populated one row per UTC day, in the
same commit that adds the corresponding `manifest.sha256.json` reference,
never edited retroactively.

| UTC date | Complete? | Slugs listed | Slugs OK | Taker values observed | Maker values observed | Manifest sha256 ref |
|---|---|---|---|---|---|---|
| _(none yet)_ | | | | | | |

## Verdict

**PENDING** — fewer than 5 consecutive complete days recorded.

## Cross-references

- Producer script: `scripts/venue/fee_drift_evidence_pull.py`.
- Unattended runner: `deploy/systemd/breezy-fee-evidence-pull.service` /
  `.timer` (see `deploy/systemd/README.md`'s own section for install steps —
  NOT activated by this commit).
- Evidence-record test:
  `tests/unit/test_polymarket_us_fee_schedule_pin.py` (asserts
  `DOCUMENTED_TAKER_FEE_COEFFICIENT == Decimal("0.06")` stays pinned, and
  that this doc's recorded observed set — empty/PENDING as of this commit —
  is consistent with the pin).
- Probe comparison target (separate, parallel ruling; not a dependency of
  this doc's closing rule):
  `docs/evidence/RULING_fee_drift_probe_target_2026-09-25.md`.
- Day-list source: `docs/plans/backlog/AUDIT_2026-09-21/AUD-02-COMPLETION-PLAN-2026-09-25.md`
  Section 2 "WP-D1".
