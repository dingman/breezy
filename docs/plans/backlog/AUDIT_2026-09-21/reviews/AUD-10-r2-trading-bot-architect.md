# AUD-10 — Review record (Round 2)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-10-evidence-gated-promotion-proposal.md
- Plan file sha256: fc8ab3a49c765a4cc724cc3983a5ab107311422e0a9eb9b58b9e9445de027e52
- Round: 2 · Reviewer: trading-bot-architect (promotion-gate/risk-architecture lens)
- Total: 91/100 · Readiness: NOT READY (score-capped by named, correctly-surfaced strategy-lead blockers, not by a fixable defect)

## Round-1 defect verification (both round-1 reviewers' records read)

| Defect | Verified fixed in body? |
|---|---|
| P1 / two-loop change list unattainable, C4 unattainable | YES — re-derived `grep -n "SUPPORTED_STATIONS" composition.py` this round and got the identical six hits the plan cites (`:45,319,328,381,448,565`); each has a stated disposition in §6's table; C4's literal `grep -c ... == 0` is now attainable exactly as described. |
| P2 / zero-instrument guard unsound under narrowing | YES, and independently re-verified against source this round: `resolved` is keyed by `buckets = {station: {} for station in SUPPORTED_STATIONS}` today (composition.py:318-320) and the guard `if all(len(ids) == 0 for ids in resolved.values())` sits at exactly `:444` and `:544` as the plan states. Narrowing `:319`'s bucket keys to `today_by_station` (derived from `manifest.stations`) is what makes the guard range over the composable set only — the fix is real and the hazard was real. |
| P3 layering | YES — identical text to AUD-09 §6, and the literal pyproject.toml layers list matches the current file before insertion. |
| p1 `roi_bound` path | YES — confirmed `src/breezy/settlement/roi_bound.py:100` (`MIN_NON_EXCLUDED_N: Final[int] = 30`) this round, exact line and value. |
| p2 no manifest writer | YES — `dump_family_manifest`/`write_family_manifest` colocated with `_REQUIRED_KEYS`/`_OPTIONAL_KEYS`, verified those key sets exist at `family_manifest.py:96-111,125`; round-trip test specified (C11). |
| p3 directory-collision idempotency false | YES — content-hash directory naming replaces the UTC-stamp scheme; C12 tests it. |
| p4 C8 not a test | YES — C8 now defines a pass condition for both outcomes, fails any third shape. |
| p5 line drift | YES — `:565`/`:488` used consistently and match source exactly. |
| tba — H2/H3 chain not a real data flow | YES — H3 real and identical to AUD-09's own table; H2 explicitly declined with the same justification in all three plans; `C-STATIONS` records `EXPANSION_REQUIRES_RULING`. |

The one round-1 *option* rejection — leaving `resolve_station_instrument_ids` wide (`:319`/`:328`)
and narrowing only the two builder loops — is examined fresh below per the brief's specific check.

## Fresh check: was rejecting "leave resolve_station_instrument_ids wide" correct?

Verified directly against current source, not the plan's characterization: `buckets` is built at
`composition.py:319` over `SUPPORTED_STATIONS`, filtered at `:328`, and the guard at `:444`/`:544`
iterates `resolved.values()` — i.e., exactly the bucket dict built at `:319`. If `:319`/`:328` are
left wide (iterating the full constant) while only the two builder loops (`:448`/`:565`) are narrowed
to the manifest's stations, then `resolved` still contains a key (and a possibly non-empty value) for
every station in `SUPPORTED_STATIONS`, including ones the manifest excludes. Under a narrowed
manifest where every *declared* station resolves zero instruments but an *undeclared* station
resolves several, `all(len(ids) == 0 for ids in resolved.values())` is **False** (the undeclared
station's non-zero entry keeps the `all()` from being true) — the guard does not fire, the two
(correctly-narrowed) builder loops skip every declared station with a WARN, and the builder returns
an empty strategy tuple with no raise. That is precisely the zero-strategy silent-boot hazard P2
names. The rejection is correct on the code: leaving `:319`/`:328` wide is not merely "also possible"
alongside narrowing the guard — it actively defeats the guard, because the guard's domain is defined
by `:319`'s bucket keys, not by the builder loops that consume `resolved`. The plan's chosen remedy
(narrow every site so buckets, filter, message, and both loops all derive from `today_by_station`) is
the only one of the two options that keeps the guard sound, and it is verified as such here
independently of the round-1 reviewers' own conflict resolution. No defect found in this rejection.

## Claims verified (this round, fresh read)

| Ref | Claim | Result |
|---|---|---|
| §6a all six `SUPPORTED_STATIONS` sites and their dispositions | CONFIRMED against a fresh `grep -n` — identical six hits, identical line numbers, each disposition matches current source shape (import removal leaves `CurrentRungHoldConfig.__post_init__` as the remaining lower-layer guard, confirmed present and raising `UnsupportedStationError`). |
| §6b layers amendment identical to AUD-09 | CONFIRMED byte-for-byte between the two plan files' quoted blocks. |
| §12 blocker — FORECAST_EDGE_PEER_REVIEW criteria transcribed from a closed programme | CONFIRMED as stated; correctly tagged `SOURCE=FORECAST_FAMILY_R5` in the criteria table rather than silently adapted. |
| H2 declined, H3 real, identical across AUD-08/09/10 | CONFIRMED — text matches verbatim across all three files where cross-referenced. |

No refuted claim found in this round for AUD-10 specifically.

## Defects

No new MATERIAL defect found in this revision. One MINOR carried over, unresolved by this plan (not
this plan's to resolve):

**MINOR — AUD-10b's real input depends on AUD-09b, which this round's sibling review found cannot
currently execute a real replay** (missing `--asos-cache-csv`, see `AUD-09-r2-trading-bot-architect.md`).
This does not block AUD-10's own acceptance criteria: C8 is designed to pass on an empty
`replay_results.jsonl` (yielding `NO_PROPOSAL` citing `C-N`/`C-VALIDITY`, which is the expected state
regardless). No required change to AUD-10 itself; flagged so the dependency chain is visible to
whoever sequences AUD-09 and AUD-10's builds.

## Strengths (credited)
This is the strongest of the three plans this round. The per-site disposition table is exhaustive and
independently reproducible from a single grep. The zero-instrument-guard fix is not a bolted-on new
guard but a correct narrowing of an existing one, and the RED test at step 3 exercises exactly the
hazard shape. The content-hash idempotency scheme is a real, testable property (unlike the withdrawn
UTC-stamp claim). Both strategy-lead blockers on the promotion criteria are kept explicit and are not
disguised as design decisions — this is exactly the right posture for the rubric's "operator/
strategy-lead decisions surfaced as BLOCKERS" requirement. The arming boundary (four separate human
acts, none automatable) is stated plainly and matches the code (`load_family_manifest`'s
`allow_draft=False` refusal path verified unchanged).

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 18 | REG-1 closed across all six sites; the guard hole it would have opened is closed too. |
| Technical correctness and evidence grounding | 20 | 19 | Every re-checked citation (six grep sites, roi_bound path, guard line numbers, manifest key sets) confirmed exactly; the rejected-option analysis independently verified sound. |
| Implementation specificity and feasibility | 15 | 14 | Per-site dispositions, serialiser, layer position, content-hash scheme all decided; the `C-ESTIMATOR` residual is honestly flagged rather than hidden. |
| Acceptance criteria and validation quality | 20 | 18 | C1-C13 objective; C4 attainable and verified so; C5/C6 cover the new silent-halt class with a real test target; C8 is a genuine two-way test. |
| Autonomous operation, failure handling and recovery | 15 | 13 | Three hard refusals, contradiction ordering (`C-KILL` first), read-only posture, real content-hash idempotency all verified; no alerting independent of the host unit's failed state remains an honest residual. |
| Portfolio objective alignment, scope and dependencies | 10 | 9 | Zero-ROI honesty, blockers kept not softened, H2 declined with a reason, abandonment criterion scoped correctly. |
| **Total** | **100** | **91** | |

## Required changes to reach 100
1. None found that this plan can itself fix — the two strategy-lead blockers (criteria transfer from
   the closed forecast family; whether MECHANISM_ONLY may feed any criterion) are correctly named
   decisions, not design gaps, and the rubric requires reporting them as BLOCKERS rather than scoring
   them down further once faithfully transcribed and flagged. The 2-point residuals above (alerting
   independence, C-ESTIMATOR signature) are genuine minor gaps worth closing for full marks.

## Blockers
- **BLOCKER (strategy lead):** whether R5-7/R5-8 (written for the closed `pm_us_crh_fc_v1` forecast
  family) transfer to a `continuous_rung_hold` family, and what champion/challenger means at admissible
  n = 0. Correctly named, not decided here.
- **BLOCKER (strategy lead):** whether a MECHANISM_ONLY replay row may ever feed a promotion criterion.
  `C-VALIDITY`'s "no" default is conservative and correctly surfaced as a default, not a ruling.
- **BLOCKER (operator):** arming, live-trading enablement, the two reserved caps — untouched by this
  item; no violation found.
