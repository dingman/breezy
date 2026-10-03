# AMBIG-LATCH-RESUME r4 — merged blind review (2026-10-03)

| Reviewer | Score | Verdict |
|---|---|---|
| security-reviewer | 88 | NOT READY (1 HIGH) |
| trading-bot-architect | 88 | NOT READY (1 HIGH) |

## Verified OK by both reviewers

- **Superseding L-36's no-id clause is safe** under its fail-closed conditions. The T41(vii) real-capture control stands. Disclose the supersession as a ruled change.
- **No order is sent while the intent is unresolved.** The deny fires at `client.py:5451-5452` before any permit spend, and `arm` refuses on OPEN. There is no double-order path.
- **`launch_to_resolve` is deadlock-free** at 16:40Z and 16:50Z.
- **A multi-match is classified CONTRADICTION.**
- **All 12 allowlist additions are additive and non-egress.** T42 pins them.

## Owed in r5 (binding)

### DH1 [HIGH, both reviewers]: enforce restart ordering in the build, not just the docs

**Problem.** Node respawns use `cwd=repo_root` (`trade_supervisor.py:~869`). An old supervisor that spawns an r4 node can decode `RESOLVER_NO_ID_NO_FILL` as corrupt (`submit_intent.py:207-219`) and then refuse every launch. That is the L-48 deadlock.

**Ruling: two phases**

- **Phase A merge.** Contents: C0 (the `RetirementReason` member), the supervisor changes, and the `submit_intent` changes.
  - Restart the supervisor in the 01:00–16:40Z window.
  - Verify all of the following:
    - the supervisor's start time is later than the Phase A merge;
    - a decode check of the new member;
    - `permit_watch_adopted_live_node` for the same pid.
  - A script performs these checks and is a merge precondition for Phase B.
- **Phase B merge.** Contents: everything node-side.
- **Node-side guard.** The no-id retire path stays disabled until a supervisor-decode marker is present. Fail-closed: if the marker is absent, the intent stays AMBIGUOUS and pages.
- **Test.** The supervisor's `RetirementReason` set is a superset of the node's.
- **Launch alert.** A launch-to-resolve over a no-id or no-context intent sends a CRITICAL, not a WARN. The between-restarts window (MED-2, TBA) is otherwise covered by the split.

### DM1 [MED, security]: bound the attribution window

Cap the window at `created_ns + 65 s + skew`, with the skew derived and stated. Any leg later than that is unattributed and classified CONTRADICTION. Correct the "never a wrong retirement" claim in R-OTHER-AUTOMATION.

### DM2 [MED, security]: firewall scan coverage

- Add `_adopt_no_id_venue_order` to the callee-scanned set.
- Pin `no_id_attribution.py` as pure: no asyncio, network or os imports or callees, enforced by a test.

### DM3 [MED, security]: activity completeness cap

A 20×100-row scan can never complete once there are more than 2000 rows.

**Ruling**

- Use early termination on strictly descending timestamps once a parsed row is older than the window.
- Pin the ordering assumption with a test against a captured response.
- Treat an out-of-order row as INCOMPLETE.
- Add a measured row-count headroom figure.

### DM4 [MED, architect]: R-CONTRA has no automated exit

A manual operator buy on a same-day Breezy instrument makes `v > d` permanently.

**Ruling.** Capture the venue-holding snapshot in the pre-POST context, and compare the **delta** instead of the absolute value. If the delta still contradicts, it stays AMBIGUOUS and pages CRITICAL with a named automated re-check cadence. No operator step may be required. Any residual must be named and bounded with evidence.

### DL1 [LOW]

- Record the measured fill-feed latency (3.2 s observed) next to the 300 s margin.
- T44(iii) also asserts no spawn when the singleton is corrupt on the boot-retry path.

## Approval bar

Both reviewers score at least 95, with zero CRITICAL or HIGH findings.
