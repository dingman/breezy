# AUD-15 — Round 3 review (silent-failure-hunter)

**Plan file:** AUD-15-failing-study-units-fix-or-retire-and-alert.md
**SHA256:** 0eac74f82db8c6d16bea6a76398f268c64298cd708d958b08d544968845161c1
**Round:** 3
**Reviewer:** silent-failure-hunter (independent, blind)

## Claims verified against source (this session)

| Claim | Status |
|---|---|
| `breezy-offer-gate-daily.service:34-35` cites 14.7G/17.3G/15.3G; `:41-42` MemoryHigh=12G/MemoryMax=16G | CONFIRMED verbatim, exact lines |
| `breezy-mb-daily.service:36-37` cites **14.3G**, 10.1G, 11.6G (all three peaks, not a subset); `:43-44` MemoryHigh=12G/MemoryMax=16G | CONFIRMED verbatim — the corrected "quote whole, all three peaks" instruction is genuinely followed in §2 |
| `TimeoutStartSec=1800` at offer-gate `:81`, `TimeoutStartSec=3600` at mb-daily `:62` | CONFIRMED exact lines |
| `grep -rl OnFailure deploy/systemd/` matches only `.sh` comments and `README.md`, no `.service` file | CONFIRMED — reran the grep this session; matches are `position-monitor-report-run.sh:67`, `k1-daily-run.sh:33`, `exit-window-study-run.sh:33,57`, `offer-gate-daily-run.sh:40`, `mb-daily-run.sh:51`, `README.md:966` — zero `.service` files, confirming the structural gap |
| Units with a sibling `.timer` in `deploy/systemd/` | CONFIRMED — 11 timers found (`breezy-exit-window-study`, `breezy-family-tally@`, `breezy-k1-daily`, `breezy-live-tally`, `breezy-mb-daily`, `breezy-offer-gate-daily`, `breezy-position-monitor-report`, `breezy-quote-tape-ingest[-frequent]`, `breezy-quote-tape-rotate`, `breezy-score-live-trials`), so the pin test (§7 15a step 2) is not vacuous — it has real, non-trivial scope |

## New defect found this round

### MATERIAL — the `memory.events`/`high` falsifier for mb-daily has no stated positive control or cgroup-path specification, so a zero reading is not distinguishable from a broken measurement

§6's mb-daily paragraph and §7 step 1(e) make the diagnosis conditional on a direct cgroup read: `memory.events` `high` ≈ 0 confirms "input growth, not throttle" and leaves the remediation unchanged; a materially non-zero `high` amends the diagnosis to include a throttle component and pulls in decision-table row (i). This is explicitly framed as the mechanism that turns "a strong inference into a measurement" (§7 step 1, echoing both round-1 reviewers' request).

Two gaps undermine that framing, both attacking the brief's specific question — "is it read from the right cgroup, and can it be zero merely because the counter reset with the unit":

1. **No literal cgroup path or command is named.** Every other observable in this plan (the store key in the sibling AUD-14 item, the alert event/severity/site/detail, `systemctl --user show ... -p MemoryHigh`) is specified down to the literal string; the `memory.events` read is not. For a `--user` oneshot unit nested under `Slice=breezy-studies.slice`, correctly locating the per-unit cgroup (as opposed to the slice aggregate, or a stale/removed cgroup) depends on user-mode cgroup delegation for the memory controller being active, and on reading it while the unit's cgroup still exists — a `Type=oneshot` unit without `RemainAfterExit=` can have its transient cgroup removed once the unit goes `inactive`/`failed`, and "reads a materially non-zero counter" is not achievable at all if the read races that removal or targets the wrong path. Neither is checked or named.
2. **No positive control is stated as a requirement.** §7 step 1(e) says the read happens "for both units," and offer-gate's swap/CPU evidence (3.8-5.2 G swap, ~14 min CPU over 30 min wall, every day) already strongly predicts a materially non-zero `high` there — but the plan never states the cross-check explicitly: *if offer-gate's own `memory.events high` reads ≈0 despite that swap evidence, the read methodology itself (path, delegation, timing) is broken, and mb-daily's ≈0 reading must not be trusted as confirmation of anything.* Without that stated tripwire, an executor could take mb-daily's zero reading at face value even if the measurement apparatus cannot observe a non-zero value at all — silently mis-attributing the diagnosis and mis-directing the §6 decision-table branch (skipping row (i)'s `MemoryHigh` reconciliation when it was actually still needed). This is precisely the "positive control is the bot's job" pattern already recorded in this repo's own memory index, applied to a human/build-time measurement rather than a runtime one, but the principle — do not trust a zero reading from an unvalidated instrument — is identical.

This is MATERIAL because it sits at the one place in the plan where a wrong reading changes a fix-or-retire ruling input silently (the ruling itself is a blocker and not made by this plan, but the evidence pack feeding it is this plan's deliverable, and §6 explicitly treats the cgroup read as authoritative over the corroborating unit comments).

**Required change:**
1. Name the literal cgroup path/command for the read (e.g., `systemctl --user show <unit> -p ControlGroup` to resolve the path, plus verifying `/sys/fs/cgroup/.../cgroup.controllers` lists `memory` for the relevant slice before trusting any reading), and require the read to happen while the unit is still running (during the run, as already stated) rather than after it exits.
2. Add an explicit cross-validation requirement to §6/§7 step 1(e): offer-gate's `memory.events high` must itself read materially non-zero in the same session (consistent with its independently-established swap evidence) as a precondition for trusting mb-daily's ≈0 reading; if offer-gate's own reading is unexpectedly ≈0, the measurement methodology — not the diagnosis — is what must be treated as suspect, and the finding recorded as a measurement defect rather than a diagnosis.

## Other checks — no additional defects found

- The `OnFailure=` template-unit design is cause-agnostic (timeout, OOM-kill, non-zero exit) and correctly reuses the existing sink; the notifier's own-failure residual is named honestly (§9) rather than hidden, with a stated reason for not closing it (avoiding an alert loop).
- The wrapper-exit-contract test (§7 step 4) correctly targets the inverse risk round 1 raised (a wrapper masking a genuine failure as exit 0) rather than the vacuous `OnFailure`-never-fires-on-a-healthy-skip case.
- `TimeoutStartSec` is explicitly forbidden as "the fix" with a negative `git diff` guard (§8 item 9) — correctly prevents converting a 30-minute silent failure into a 60-minute one.
- The citation-integrity failure from round 2 (the truncated mb-daily quote that reversed its own evidence's sign) is genuinely fixed: this session's direct read confirms all three peaks are now quoted, matching the file exactly.

## Per-criterion points

| Criterion | Cap | Points | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | Both units get distinct, measured diagnoses; the un-named structural `OnFailure=` gap is added and independently reconfirmed by a fresh grep this session. |
| Technical correctness and evidence grounding | 20 | 15 | All quoted figures and line citations verified exact. Deducted for the cgroup-read gap above: the plan's own stated falsifier is not yet a measurement in the rigorous sense it claims to be — it lacks a stated positive control and a literal read path, at the exact point the plan says separates inference from measurement. |
| Implementation specificity and feasibility | 15 | 13 | 15a is fully literal end to end. 15c's if/then on the `high` counter is a real improvement over an unconditional diagnosis, but the read mechanism itself (path, delegation check, timing relative to unit-exit) is unspecified. |
| Acceptance criteria and validation quality | 20 | 18 | Nine items including negative `git diff` guards and the falsifiable amendment condition; the amendment condition's trustworthiness depends on the unaddressed cgroup-read gap above. |
| Autonomous operation, failure handling, recovery | 15 | 14 | Cause-agnostic coverage, no alert loop, no auto-retry (reasoned), wrapper-masking inversion pinned, notifier residual named honestly. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Cost-avoidance framed on measured numbers only; G-04 correctly routed to its own item. |
| **Total** | **100** | **89** | |

## Required changes

1. Name the literal cgroup path/read command for `memory.events`/`memory.stat`, and require the read to occur while the unit is live (before cgroup teardown).
2. State the offer-gate cross-validation tripwire explicitly: a ≈0 reading on offer-gate (which independent swap/CPU evidence predicts will be non-zero) invalidates trust in mb-daily's ≈0 reading and must be recorded as a measurement defect, not folded into the diagnosis.

## Blockers

The per-unit fix-or-retire rulings remain strategy-lead BLOCKERs, as the plan states. Neither required change above needs a ruling — both are build-side measurement-methodology gaps fixable within this plan.
