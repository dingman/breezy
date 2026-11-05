> **CORRECTED 2026-09-01 — conclusion stands, premise does not.**
> This appendum argues from a "130906 ms host clock offset". That figure is a
> measurement artifact, not skew: `_clock_offset_ms`
> (`scripts/venue/polymarket_us_auth_smoke.py:890-907`) compares `time.time()` at
> call time against the FIRST response's `Date` header and is called at checkpoint
> time, so it measures elapsed run duration (08-25 ran 22:11:31 -> ~22:13:41 = 130 s).
> Real signing-time offset was **779 ms** against a 15 000 ms guard that never fired.
> The conclusion — **the venue does not enforce a signing window** — still holds, but
> on step D alone (a deliberately stale -120s request returned 200).

# Polymarket.us Venue Facts Signing Window Addendum - 2026-08-26

This is a dated sibling to `VENUE_FACTS_2026-08-25.md`, not an edit to that
file, because `SHA256SUMS_2026-08-25.txt` attests the original facts document.

## 2026-08-25 authenticated smoke observation

The read-only authenticated smoke run recorded a host clock offset of
`130906` ms versus the venue `Date` response header, while authenticated GETs
still returned 200. The same run's Step D deliberately signed an authenticated
GET with a timestamp offset by `-120s`; the venue returned status 200 with the
note `ACCEPTED -- window not enforced`.

Evidence:

- `READONLY_AUTH_SMOKE_2026-08-25T221131+0000.md:16` records the `130906` ms
  host clock offset versus the venue `Date` header.
- `READONLY_AUTH_SMOKE_2026-08-25T221131+0000.md:29-33` records authenticated
  GET status 200 for Step B and the stale `-120s` Step D timestamp accepted
  with status 200.

Operational consequence: future work must not assume the documented `+/-30s`
signing window is either enforced or unenforced. Breezy should guard its own
host clock before signing so clock drift is diagnosed locally as clock skew,
not later as an opaque venue authentication failure.
