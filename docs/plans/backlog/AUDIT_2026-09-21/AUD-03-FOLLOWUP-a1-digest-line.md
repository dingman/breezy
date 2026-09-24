# AUD-03 follow-up — digest line for the AUD-02 governance blocker

**Status:** open. **Owner:** whoever next revises the decision-funnel digest
(`scripts/analysis/decision_funnel_daily_digest.py`). **Filed:** 2026-09-24,
with the AUD-03 implementation, under AUD-03 §8's named fallback.

## Why this is not in the AUD-03 implementation

AUD-03 §8 requires the "A1 open, N days since gap G-02 filed" alert line
only when **both** of these are true at implementation time:

1. Amendment C is present in `docs/evidence/POST_FORECAST_PHASE_2026-09-20.md`.
2. AUD-02 §6.4's requirement is on record.

(1) is false. `POST_FORECAST_PHASE_2026-09-20.md` has no Amendment C.
The core funnel digest therefore ships without that line, and this file is
the standalone ticket §8 requires instead of a note buried in a sibling plan.

## What the next change actually is

AUD-02 §6.4 (round-4 supersession, same plan file) already marks the
A1-open-age line **moot**: the ruling doc exists, so the line would report
nothing. The replacement it specifies is one `halt_enforced: yes|no` field
read from the same halt state the submit veto reads.

That read is **not** done here. AUD-03's binding constraint is read-only
over the offer-tape log: the digest does not touch the node, the order
path, or the tally. A halt-store read is a different trust boundary and
needs its own RED test against a fixture store, not against the live latch.

Do not add the original A1-open-age sentence. It would be permanently
absent and would hide the enforcement question AUD-02 moved to.
