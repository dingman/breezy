# AUD-09 — Review record (Round 3)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-09-scheduled-per-station-replay.md
- Plan file sha256: fc00ec7e39f819b7b8e7eb705ceb129bf27b128e6dec2b73757af87bcb9f2ec5
- Round: 3 · Reviewer: trading-bot-architect (scheduling/pipeline/host-resource lens)
- Total: 100/100 · Readiness: READY

## Round-2 defect verification (both round-2 reviewers' records read, against the plan BODY not §13)

| Defect | Verified fixed in body? |
|---|---|
| MATERIAL 09-1/10-1 — the Nautilus forbidden contract omits `allow_indirect_imports = true` and cannot pass | YES. §6 now quotes the contract WITH the flag and the rationale (mirrors the `.com` contract at `pyproject.toml:116-121`). I re-derived the underlying defect against `.venv/lib/python3.13/site-packages/importlinter/contracts/forbidden.py` this round: `:72` declares `allow_indirect_imports = fields.BooleanField(required=False, default=False)` and the false branch at `:131-143` takes `find_shortest_chains` — confirming a false default is a real hazard here, and that the plan's chosen fix genuinely neutralises it. |
| MATERIAL (both)/b1 — the runner's literal CLI invocation omits required `--asos-cache-csv`, and SP-4's own open blocker is silently dropped | YES, resolved by BUILDING the producer, not just naming the gap. I independently re-read `current_rung_hold_paper_replay.py:1074-1113`: every `required=True` argument (`--climate-day`, `--station`, `--tape-instance-id`, `--quote-catalog`, `--work-catalog`, `--asos-cache-csv`, `--weather-catalog-root`, `--lag-minutes`) now appears in §6b.3's literal command block, including `--asos-cache-csv "$ASOS_CSV"` at plan line ~490. §6b.1's producer (`scripts/analysis/asos_cache_csv.py`) is composed from real, existing functions I re-read this round: `load_sites()` (`settlement_alignment_study.py:638-658`, exact signature and body, off by one line from the plan's cited `:638-659` — trivial), `load_recent_asos_rows(cache_dir, iem_asos_id)` (`cli_basis_offer_gate_scan.py:495-536`, confirmed **zero network**: returns `()` for a missing/empty directory, reads only local `.txt` files via `Path.read_text`), and `parse_asos_rows` (`settlement_alignment_study.py:634-635`, a bare `csv.DictReader`). The producer is genuinely cache-only and zero-network on the scheduled path, as claimed. B17 tests the command block is complete by introspecting the driver's own `argparse` `required=True` set — a real, non-circular test. |
| MATERIAL 09-2/10-3 — `family_id` in the queue key with no producer; driver takes no family/manifest/fee argument | YES. I independently re-verified the construction site: `cfg = CurrentRungHoldConfig(instrument_ids=tuple(i.id for i in instruments), stations=(station,))` at `current_rung_hold_paper_replay.py:932-934` — every other field defaults, including `required_fee_coefficient: Decimal = Decimal("0.06")` (`config.py:226`), against `deploy/families/pm_us_crh_v4.json`'s `"taker_fee_coefficient": "0.0695"` (both grepped directly this round, exact match). §6b.2's decision — armed family only, `family_id` demoted to provenance, queue key `(station, climate_day, strategy, lag_minutes)` — is consistent with what the driver can actually do, and the divergence is recorded on every row (`engine_required_fee_coefficient`, `manifest_taker_fee_coefficient`, `params_match`, B16) rather than hidden. |
| MATERIAL 09-3 — `replay_sufficiency.jsonl` lacked the H1/H3 artefact standard | YES. H0 (§6a) now carries all seven rows: `REPLAY_SUFFICIENCY_SCHEMA_VERSION`, `write_/read_replay_sufficiency`, `UnknownReplaySufficiencySchemaError`, record key, duplicate-key hard error, atomic whole-file rewrite, and the "unreadable work list must not look like an empty queue" rule; B14 tests it. |
| MINOR b2 — `classify_station_day` signature was prose | YES. Literal signature + `InstanceSpan` dataclass given, B15 pins its `verdict` alphabet equal to `cli_basis_offer_gate_scan.InstanceVerdict`. |
| MINOR (tba) — B9's discharge condition optimistic | YES. B9 now states a genuine two-way pass condition (`COMPLETED` or a `BLOCKED` row with a named §12 blocker), failing any third shape. |

No round-2 acceptance is falsely claimed.

## Claims verified this round (fresh read against current source)

| Ref | Claim | Result |
|---|---|---|
| §6b.2 `:932-934` construction and `config.py:226` default | CONFIRMED exactly. |
| `deploy/families/pm_us_crh_v4.json` `taker_fee_coefficient` | CONFIRMED `"0.0695"`. |
| §6b.1 producer composition (`load_sites`, `load_recent_asos_rows`, `parse_asos_rows`) | CONFIRMED to exist, at the cited lines, with the claimed cache-only/zero-network behaviour. |
| §7 step 3 — cache coverage measured before the runner is built, gating timer enablement | Correctly sequenced in §7 (step 3, before the census/runner RED tests) and in §6b.3's timer-enablement rule ("only after step 13 produces a non-`BLOCKED` row"). This is the right place to gate: the plan does not claim the cache is populated, it makes the claim testable and blocks autonomous enablement on the test. |
| §6b.3 command block completeness | CONFIRMED runnable as written — every `required=True` driver argument is present; B17 makes this a standing regression test rather than a one-time claim. |

## Defects

None found. All four round-2 MATERIAL defects are genuinely closed, independently re-verified against source rather than accepted on the plan's word, including the two items the coordinator specifically asked me to check: the `--asos-cache-csv` producer is real, composed from functions that actually exist and are actually cache-only/zero-network, and the command block is runnable as written; the armed-family-only decision is consistent with the driver's actual construction site and records the fee-coefficient divergence on every row rather than asserting a false equivalence.

## Strengths (credited)

The honest handling of "armed family only" is the standout: rather than pretending the driver can do something it cannot, the plan narrows the queue key, demotes `family_id` to provenance, and *records* the parameter divergence so a downstream reader (AUD-10's `C-VALIDITY`) can refuse it as an edge input. The crash-recovery design (JSONL row as the sole completion marker, `RECOVERED`/`FAILED` split) remains the strongest single piece of engineering in this plan and is unchanged from round 2's assessment. The timer-slot decision prices its own contention cost rather than hiding it. `ASOS_CACHE_EMPTY` is now a first-class, enumerated, non-fatal outcome that keeps the day queued rather than silently degrading to a fabricated zero-trial result.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | Census + schedule + machine-readable result are complete and, for the first time, genuinely executable; SP-4's own open blocker is closed rather than dropped. |
| Technical correctness and evidence grounding | 20 | 20 | Every citation I independently re-opened this round (driver parser, construction site, fee coefficients, producer functions, import-linter's own default) is exact. |
| Implementation specificity and feasibility | 15 | 15 | The command block, the producer, the layer contract, the family decision, and the census artefact's version discipline are all decided to a buildable level; nothing is left to the implementer as a material design choice. |
| Acceptance criteria and validation quality | 20 | 20 | B1–B17 are objective and property-shaped; B9 and B17 in particular turn what were previously optimistic claims into real, falsifiable tests. |
| Autonomous operation, failure handling and recovery | 15 | 15 | `ASOS_CACHE_EMPTY`, unreadable-work-list-vs-empty-queue, crash recovery, duplicate-key hard error, skip-not-kill, OOM cgroup containment are all enumerated and consistent with each other. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | Mechanism-vs-edge separation now rests on two independent grounds (look-ahead AND params_match); the deferred `--family-manifest` change is named with an owner; abandonment criterion is real. |
| **Total** | **100** | **100** | |

## Required changes to reach 100

None.

## Blockers

- **BLOCKER (strategy lead, correctly named, does not cap this plan's score):** R1, `PAPER_TRIAL_ID_PREFIX` provenance for v3 rows — kept exactly as before, not softened.
- **BLOCKER (build, measured not assumed):** whether the settlement-alignment cache actually covers SFO 2026-09-01 given `DEFAULT_LOOKBACK_DAYS = 3` — genuinely unknown until §7 step 3 runs, and the plan correctly gates timer enablement on that measurement rather than assuming it.
- **BLOCKER (deferred, named owner, mirrored in AUD-10):** `C-PAIRED` cannot evaluate until a `--family-manifest` flag exists on the driver — excluded from this item's scope by design, not an oversight.
