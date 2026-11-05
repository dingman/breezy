# AUD-02 round 6 review — silent-failure-hunter

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-02-edge-discovery-programme-status-and-fold-in.md
sha256: ed594d4e50fae1b131399ee579efdba9cef35dc71823d85b667ad70db76670a7
Round: 6. Reviewer: silent-failure-hunter (independent, blind).

## Round-5 MATERIAL defect (stale `StartupPositionEvidence`): substantially FIXED, verified
- `StartupPositionEvidence` write timing CONFIRMED at `_connect` end (`client.py:3102-3133`) — the
  round-6 correction (also written on resolver terminal-zero, `:908-910`) is accurate.
- Fallback bound: `ts_ns` age check + cross-check against `TrialDayLatch.iter_fill_records`
  (`trial_day_latch.py:1102`, CONFIRMED present, read-only, no prefix scan per its own docstring)
  and `record_exit`/`exit_at_ns` (`:918`) — sound design, UNKNOWN-fails-closed, no silent "flat".
- Override removal (round-6 defect 2): CONFIRMED — a free-text `--reason` escape satisfying only
  `MIN_REASON_LENGTH` was an unenforced bypass; removing it rather than re-specifying is the correct
  call for a safety stop.
- NO-SEND firewall claim: CONFIRMED structurally sound — `PolymarketUSReadTransport._dispatch`
  (`http.py:179-207`) enforces `PERMITTED_METHODS` (GET only, `MethodNotPermittedError` otherwise) and
  `_raise_for_status` (`:224-247`) raises named exceptions on 401/403/429/non-2xx — an order can never
  reach the venue through this path, and auth failure/timeout do not silently pass as "flat" (they
  raise, forcing the fallback branch).

## MATERIAL defect (new, round 6 — the DEFAULT live GET path has no pagination/eof-completeness check)
The plan's cited live-GET implementation source, `scripts/venue/polymarket_us_auth_smoke.py:164,1019`
(`_probe_authenticated`, read this round), is a bare connectivity probe: it calls
`client.get_authenticated(PORTFOLIO_PATH, ...)` and only distinguishes "accepted" vs "REJECTED:
<exception>" — it never parses `payload["positions"]` and never checks `payload["eof"]`. The venue's
own position response is cursor-paginated, and the EXISTING durable-evidence writer enforces this
via `_declared_positions` (`client.py:2592-2622`): it explicitly REFUSES a page where `eof is not
True` ("page 1 is not necessarily the whole book... refuse rather than silently truncate", R-4P-1).
§6.5's new DEFAULT live-GET path has no stated equivalent: it cites an existing function that does
not do this validation, and does not specify that the new CLI code parses the response through
`_declared_positions` (or an equivalent eof-gate) before treating an empty/zero-looking page as
"flat." Without it, a paginated response whose first page happens to show no open position but is
NOT `eof=true` could read as flat and let the halt proceed over an under-reported book — reintroducing,
on the now-default path, the same class of silent-truncation risk R-4P-1 was written to close on the
durable-evidence path. Required change: the live-GET branch must apply the same `eof=True` gate (reuse
`_declared_positions` or equivalent) and treat `eof is not True` as UNKNOWN → refuse, with a RED test
for a non-eof live-GET page.

## MINOR
- "Apply the leg sign before judging flat: the venue nets a NO holding as a short YES" is carried
  forward as a caveat sentence with no cited enforcement mechanism or test in either round 5 or 6 (the
  refuse-on-any-nonzero rule makes sign-blindness safe for the binary flat/non-flat gate itself, so
  this is not blocking, but the sentence is currently unbacked prose, not a checked behaviour).

## Per-criterion (cap/points)
fidelity 20: 18 · technical correctness 20: 15 (cited source for the live-GET path does not support
  the completeness claim made about it) · implementation specificity 15: 11 (no stated eof/pagination
  handling on the new default path) · acceptance criteria/validation 20: 14 (tests 12-14 cover the
  fallback well; none covers a non-eof live-GET page) · autonomous/failure handling 15: 11 (§9 failure
  catalog omits partial-page live GET) · portfolio alignment 10: 10.

**Total: 79/100.**

## Blockers
None operator/strategy-lead-side; buildable within AUD-02b's own scope (reuse `_declared_positions`
or equivalent on the live-GET response).
