# AUD-09 — Review record (Round 2)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-09-scheduled-per-station-replay.md
- Plan file sha256: 03295e8e29f2131d2fc6b083db42040f95c965ed24d6987f2084e62967fafdb5
- Round: 2 · Reviewer: trading-bot-architect (scheduling/pipeline/host-resource lens)
- Total: 73/100 · Readiness: NOT READY

## Round-1 defect verification (both round-1 reviewers' records read)

| Defect | Verified fixed in body? |
|---|---|
| N1 `breezy.analysis` breaks `exhaustive=true` | YES — pyproject.toml:71-101 re-read; current `layers` list matches the plan's pre-insertion text exactly; the inserted `analysis` layer + two `forbidden` contracts are literal and self-consistent (app barred from importing analysis by the explicit forbidden contract, closing the one hole a plain layers insertion leaves). |
| N2 dedup key too narrow | YES — full 5-tuple `(station, climate_day, family_id, strategy, lag_minutes)`, RED test at step 5, B11. |
| N3 parquet-keyed skip creates permanent stall | YES — JSONL row is the sole completion marker; `RECOVERED`/`FAILED` outcomes specified; B12. |
| N4 timer slot undecided | YES — 15:50 UTC verified genuinely free against every installed `.timer` file (`01:35, 02:05, 09:00, 13:30, 14:15, 14:30, 15:00, 15:20, 17:20, 00/06/12/18:15, */0:15`); outside the stated no-start window. |
| n1-n4 minors | YES, each independently confirmed (B2 failure-mode statement, B5 ratchet, H1 real, alphabet single-token). |

## Claims verified (this round, fresh read)

| Ref | Claim | Result |
|---|---|---|
| §6b timer slot list and `test_deploy_timer_hours.py` | CONFIRMED — every listed tick present in `deploy/systemd/*.timer`; the collision test exists at `tests/unit/test_deploy_timer_hours.py` and enforces the one-tick-per-day model. |
| §6b `MemoryHigh=3G`/`MemoryMax=4G` against the 12G/16G slice ceiling | CONFIRMED consistent with the existing precedent (`breezy-studies.slice` 12G/16G aggregate; `breezy-exit-window-study.service` already uses a smaller 1G/2G sub-cap), and the host-wide `flock` pattern in `replay-daily-run.sh` is described "line-for-line" on `mb-daily-run.sh`, whose actual flock/skip-not-kill/`POSIXLY_CORRECT` shape matches exactly. |
| §6b command line for `current_rung_hold_paper_replay.py` | **REFUTED** — see MATERIAL below. The literal invocation omits a required CLI argument. |
| §2 "AUD-09b subsumes SP-4's Increment F" | Partially refuted by the same defect: Increment F's own command (`V3_BACKTEST_REPLAY_SUBCLASS_2026-09-12.md:80-91`) carries `--asos-cache-csv <see §9 UNVERIFIED>`, and that plan's §9 explicitly records "no producer script exists... a missing file makes F unrunnable." AUD-09 does not carry this blocker forward. |

## Defects

**MATERIAL — the runner's literal CLI invocation is missing a required argument and the plan
silently drops a known, still-open upstream blocker.** `current_rung_hold_paper_replay.py:main`
declares `parser.add_argument("--asos-cache-csv", required=True, type=Path)` (verified at
`scripts/analysis/current_rung_hold_paper_replay.py:1082`) and `read_asos_rows` needs it
(`:471`, consumed at `:1176`). §6b's runner command (the exact literal quoted in the plan) does not
pass `--asos-cache-csv` at all — not even elided with `…` the way `--quote-catalog` and
`--weather-catalog-root` are. Running it as written fails at argument parsing before the engine ever
starts. This is not a new problem this plan introduces from scratch: it is SP-4's own, still-open
blocker — `V3_BACKTEST_REPLAY_SUBCLASS_2026-09-12.md:90,137` states the exact same flag is
"UNVERIFIED" and names the reason: *"no producer script exists under `scripts/` and no matching CSV
was found under `~/.local/share/breezy` (searched to depth 4)... a missing file makes F unrunnable."*
A repo-wide search this round for any ASOS cache CSV or a script producing the required
`station,valid,metar` schema at a fixed path found none (`scripts/asos_recent_refresh.py` exists and
refreshes a *different*, day/site-keyed ASOS cache used by `ma_prelock_winner_ask_study.py`, not
demonstrated to produce `read_asos_rows`'s consolidated CSV format). AUD-09 claims in §2 that
"AUD-09b subsumes SP-4's Increment F: SP-4's single hand-run becomes this item's first scheduled
run" — but the plan neither resolves this blocker nor even lists it in §12's blockers, and §7 step 10
("the one real run") is presented as though it is executable today. It is not, on the plan's own
cited evidence. This blocks: step 10 of §7, B4, B5's baseline measurement, B9 (SP-4's Increment F
discharge), and by extension every subsequent scheduled invocation of `breezy-replay-daily.service`
— the entire runner would fail on every tick until this is resolved, which is exactly the kind of
"healthy unit, silently non-functional" failure mode this audit exists to close.
REQUIRED CHANGE: either (a) name and build the `--asos-cache-csv` producer (script, output path,
schema) as an explicit in-scope deliverable of AUD-09b with its own RED test, or (b) if genuinely out
of scope, add it to §12 as a named BLOCKER (owner: whoever built `asos_recent_refresh.py`/strategy
lead) and gate §7 step 10 and the timer's `Persistent=true` enablement behind resolving it — do not
present the invocation as runnable when the plan's own cited source says it is not.

**MINOR — B9's discharge condition is optimistic given the above.** B9 says SP-4's obligation is
discharged by "the result row from step 10," but step 10 cannot produce a result row until the
material defect above is fixed. Once fixed, B9 stands as written.

## Strengths (credited)
The census core (`replay_sufficiency.py`) is a genuinely pure, well-specified module with a correctly
derived winner rule (de-dup before replay, ambiguous-pair refusal) traced to a real prior ruling. The
crash-recovery, dedup-key, and timer-slot decisions are all concretely taken with stated,
non-hand-waved consequences (lock contention, memory attribution). The `REPLAY_VALIDITY` single-symbol
seam is a good anti-drift device. H1 is real and correctly non-blocking on a missing register.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 17 | Census + schedule + machine-readable result are all present; SP-4 fold-in claimed but not actually deliverable as specified (see defect). |
| Technical correctness and evidence grounding | 20 | 14 | Layering, timer-tick, and memory-cap claims all verified correct; the CLI invocation is verifiably broken against the cited script's own argparse, and a known open blocker from the cited SP-4 plan is dropped rather than carried or resolved. |
| Implementation specificity and feasibility | 15 | 10 | Everything else is decided in-plan, but the runner as specified cannot execute a single real replay today. |
| Acceptance criteria and validation quality | 20 | 16 | B1-B13 are otherwise objective and well-covered; B4/B5/B9 cannot pass as written until the CLI defect is fixed. |
| Autonomous operation, failure handling and recovery | 15 | 12 | Crash/lock/OOM/concurrency handling is genuinely strong; the runner's very first invocation failure mode (missing required arg) is not itself among the enumerated failure cases in §9, an omission given it is the most likely actual outcome today. |
| Portfolio objective alignment, scope and dependencies | 10 | 9 | Mechanism-vs-edge honesty, dependencies by id, abandonment criterion with stated adjustment all present. |
| **Total** | **100** | **73** | |

## Required changes to reach 100
1. Resolve or explicitly block-and-gate the missing `--asos-cache-csv` producer (MATERIAL).
2. Restate B9's discharge condition once (1) is fixed.
3. Add "missing `--asos-cache-csv`" as an enumerated §9 failure case until resolved.

## Blockers
- **BLOCKER (strategy lead, real, not softened here):** PAPER_TRIAL_ID_PREFIX / ruling R1, correctly
  named in §12 and unaddressed by design — this review does not add to it.
- **BLOCKER (this review, newly surfaced):** the ASOS cache CSV producer does not exist anywhere in
  the repo or under `~/.local/share/breezy` as of this review (verified by search) — this is a build
  blocker for AUD-09b specifically, not an operator ruling; it belongs to whoever owns
  `asos_recent_refresh.py` / the implementer, and should be resolved or explicitly gated, not silently
  dropped.
