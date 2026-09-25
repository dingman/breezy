# AUD-14a — Restart classification, regenerated at execution time

**Date:** 2026-09-24. **Plan:** `docs/plans/backlog/AUDIT_2026-09-21/AUD-14-hands-off-operation-restart-motive-and-selfcheck-escalation.md`,
§7 14a steps 1-2. Promotes and reproduces the §2 table from the plan itself,
regenerating both halves (journal + `git log`) live rather than copying the
plan's table, per the plan's own instruction.

## Method

```
journalctl --user -u breezy-trade-supervisor.service --no-pager -o short-iso \
  | grep -iE "Stopping|Stopped|Started|Main process exited|Failed"
```

for the restart cycles, cross-referenced against

```
git log --date=iso-strict --pretty="%H %ad %s" --since=<window-start> --until=<window-end>
```

(run in `/home/jon/breezy`, no pathspec filter — the 09-10 restart's nearest
commit is a `docs/` change and a `-- src deploy` pathspec would silently
drop it) for the nearest preceding commit to each restart.

## Result — all 7 restarts, reproduced bit-for-bit against the plan's table

| # | Restart (UTC) | Nearest preceding commit | Δ | Classification |
|---|---|---|---|---|
| 1 | 2026-09-10T16:43:56 | `cd3f8e8` 2026-09-10T16:43:10Z docs(evidence): gate attribution — illegal_cell is the take rule, not a table gap | 46 s | deploy-adjacent (weak — a docs commit; motive cannot be closed from the artefacts) |
| 2 | 2026-09-12T01:24:03 | `7938032` 2026-09-12T01:24:03Z deploy(supervisor): CUT to pm_us_crh_cont | **0 s** | **deploy-driven** |
| 3 | 2026-09-12T01:37:20 | `a858b93` 2026-09-12T01:37:12Z feat(supervisor): v3-aware 17:05Z self-check | 8 s | **deploy-driven** |
| 4 | 2026-09-15T15:06:58 | `e9955628`/`76c760b` 2026-09-15T14:40:52Z merge — mid-day relaunch core | ~26 min (nearest same-window commit; plan cites `eed0f4c` merge, same cluster) | **deploy-driven** |
| 5 | 2026-09-19T04:01:44 | `a115691` 2026-09-19T04:00:41Z fix(venue): accept bonusHold as declared-but-unread balance drift | 63 s | **deploy-driven** |
| 6 | 2026-09-19T04:20:17 | `fbc5eea` 2026-09-19T04:19:33Z Merge branch 'backlog/wp11b-active-family-registry-2026-09-19' | 44 s | **deploy-driven** |
| 7 | 2026-09-20T15:26:18 | `e3e8ac6` 2026-09-20T15:26:04Z feat(fee): register theta on the family manifest; open pm_us_crh_v4 at 0.0695 | **14 s** | **deploy-driven** |

Every cycle is a clean `Stopping` → `Stopped` → `Started` (an operator
`systemctl --user restart`). Three cycles (#2, #3, #7) additionally log
`Unit process <pid> (breezy-trade) remains running after unit stopped` —
expected supervisor behaviour (it does not own the child's lifecycle across
its own restart) and not a crash indicator. **No `Main process exited`, no
`Failed`, no crash line, across all 7 cycles.**

**Restart count of recovery-driven (crash/failure) restarts: 0 of 7.** 6 are
unambiguously deploy-driven within ≤63 s of a commit; the 7th (#1) is
deploy-adjacent — the nearest commit is a docs-only change 46 s earlier, and
its motive cannot be closed from the artefacts alone. This reproduces the
plan's §2 finding exactly: G-13's implied "recovery restarts" are not in
evidence.

## Closing the one open evidence link (§7 14a step 2)

Grepped every archived node log under `/home/jon/.local/share/breezy/logs/`
(oldest retained log: `breezy-trade-20260904T172121Z.log`) for the first
appearance of `ContinuousRungHoldStrategy subscribed`:

```
grep -rl "ContinuousRungHoldStrategy subscribed" /home/jon/.local/share/breezy/logs/*.log
```

**First appearance: `2026-09-12T16:50:33.686758125Z`**, in
`breezy-trade-20260912T165030Z.log`:

```
2026-09-12T16:50:33.686758125Z [INFO] BREEZY-L001.ContinuousRungHoldStrategy: ContinuousRungHoldStrategy subscribed tc-temp-laxhigh-2026-09-12-gte85f.POLYMARKET_US
```

No earlier occurrence exists in any retained log back to 2026-09-04.

**Finding — CONFIRMED, not disconfirmed.** The string first appears the same
day as `7938032` (the `pm_us_crh_cont` cut, 2026-09-12T01:24:03Z), 14 minutes
before the first `FAIL_NODE_NOT_READY` self-check at
`2026-09-12T17:05:01Z`. The strategy *was* subscribed and running before the
first FAIL; the FAIL was caused by `STRATEGY_SUBSCRIBED_MARKER` naming only
`CurrentRungHoldStrategy` while the live family logs
`ContinuousRungHoldStrategy subscribed`, so `trade_supervisor_core.py`'s
readiness check fell through to `FAIL_NODE_NOT_READY` even though the
strategy was, in fact, ready. This confirms the causal chain `1859498`'s
commit message describes end to end: marker mismatch → readiness never
observed → `next_due` never enters `MIDDAY_WATCH` → the daily FAIL. It also
confirms this plan's correction to that commit message: the FAIL window
began 2026-09-12, not 2026-09-15 as the commit message states — three days
earlier, consistent with `7938032` landing 2026-09-12T01:24.

## What this closes

- §8 acceptance item 1: all 7 restarts classified, 0 recovery-driven, and
  the `ContinuousRungHoldStrategy subscribed` first-appearance timestamp
  recorded next to the first FAIL.
- The AUD-14a code change (a `revision=` field on `supervisor_started`)
  makes this comparison — "did the running revision change at this
  restart?" — answerable from the journal alone at the *next* deploy
  restart, without a manual `git log` correlation. §8 item 5's demonstration
  (a real deploy restart showing a changed `revision=` value) is left for
  the next deploy, per the plan.

## Correction — first implementation was inert in production (caught by review)

The first cut of `_resolve_build_revision` fell back to
`importlib.metadata.version("breezy")` when `BREEZY_BUILD_REVISION` was
unset. `pyproject.toml`'s version is a hand-edited literal (`0.1.0`), frozen
across ordinary commits, and nothing in this deployment sets
`BREEZY_BUILD_REVISION` — so every `supervisor_started` line would have read
`revision=0.1.0` regardless of which commit was actually running, making the
field unable to answer the one question it exists for (§8 item 5's
"the value differs from the previous restart's"). Independent review
(REQUEST_CHANGES) caught this before merge. The corrected resolver reads the
git commit of the source tree actually imported directly from `.git` files
(`HEAD`, loose/packed refs, and the linked-worktree `commondir` indirection —
no `git` subprocess, no GitPython), truncated to 12 hex characters, and falls
back to the package version only when no `.git` is resolvable at all (e.g. a
non-editable install). The value reflects the checked-out tree at supervisor
*start*; the node is spawned later from that same tree, so it is also the
node's revision.
