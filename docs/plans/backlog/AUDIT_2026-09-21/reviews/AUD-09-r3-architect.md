# AUD-09 — Review record (Round 3)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-09-scheduled-per-station-replay.md
- Plan file sha256: fc00ec7e39f819b7b8e7eb705ceb129bf27b128e6dec2b73757af87bcb9f2ec5 (filled by coordinator at save time)
- Round: 3 · Reviewer: architect (code-architect lens)
- Total: 85/100 · Readiness: NOT READY

## Round-2 dispositions, verified against the plan body and against source

| R2 defect | Claimed | Verified? |
|---|---|---|
| **09-1** — the "analysis never imports Nautilus" contract cannot pass | ACCEPTED | **FIXED, and the literal config is correct.** I re-read `importlinter/contracts/forbidden.py`: `allow_indirect_imports = fields.BooleanField(required=False, default=False)` at `:72`, and at `:131-137` `str(self.allow_indirect_imports).lower() == "true"` takes the `_get_direct_chains` branch (the `else` at `:138-143` is `find_shortest_chains`). A TOML `allow_indirect_imports = true` therefore checks **direct** imports only — exactly the stated property, and exactly what the `.com` contract does (`pyproject.toml:116-121`, comment + flag). The `layers` insertion is legal against the real contract (`pyproject.toml:71-101`, `exhaustive = true` at `:92`). The rejection of "re-source `SUPPORTED_STATIONS`" is evidenced and, I agree, the smaller change: it would edit `strategy/current_rung_hold/config.py` where the symbol lives (`:76`) alongside the Nautilus imports, and it collides with AUD-10a, which removes that import from `composition.py:45`. |
| **09-2 / 10-3** — `family_id` in the queue key with no producer; `<id>` unbound | ACCEPTED IN FULL | **FIXED, and verified at the construction site.** `cfg = CurrentRungHoldConfig(instrument_ids=…, stations=(station,))` at `current_rung_hold_paper_replay.py:932` — every other field defaults, including `required_fee_coefficient: Decimal = Decimal("0.06")` (`config.py:226`); `deploy/families/pm_us_crh_v4.json:17` registers `"taker_fee_coefficient": "0.0695"`. The parser (`:1075-1113`) has no family/manifest/fee argument. The decision (armed family only; `<id>` bound to `settings.sending_family_id`; key drops to `(station, climate_day, strategy, lag_minutes)`; the divergence **recorded** as `engine_required_fee_coefficient`/`manifest_taker_fee_coefficient`/`engine_params_source`/`params_match` under **B16** and **contained** downstream by AUD-10's `C-VALIDITY`) is the right resolution, and the partial withdrawal of round 1's N2 is stated in the open rather than quietly dropped. |
| **09-3** — `replay_sufficiency.jsonl` below the H1/H3 standard | ACCEPTED | **FIXED.** H0 carries all seven rows plus the rule the concern actually turned on — "no work" and "unreadable work list" must not look alike — with B14 and tests at §7 steps 4 and 8. |
| **b1 / tba MATERIAL** — command omits `--asos-cache-csv`; SP-4's producer blocker dropped | ACCEPTED | **FIXED, and more than asked.** `required=True` at `:1082` confirmed; `read_asos_rows` at `:471`; the command block now carries every `required=True` flag and **B17** tests it by argparse introspection. The producer is composed of functions I confirmed exist: `load_sites` (`settlement_alignment_study.py:638`), `load_recent_asos_rows` (`cli_basis_offer_gate_scan.py:495`), `parse_asos_rows` (`:634` of settlement_alignment_study), and the residual is measured at §7 step 3 with `DEFAULT_LOOKBACK_DAYS = 3` (`asos_recent_refresh.py:91`) verified. B9's two-way discharge is real. |
| **b2** — `classify_station_day` prose, not a signature | ACCEPTED | **FIXED.** Signature and `InstanceSpan` given; the alphabet is traced to `InstanceVerdict` (`cli_basis_offer_gate_scan.py:247`), `classify_instance` (`:391`), and pinned equal by **B15**. The local declaration with a drift pin is the right call for a `scripts/`-resident symbol. |

**New-producer placement check (coordinator requirement).** `scripts/analysis/asos_cache_csv.py` is
correctly placed: `root_packages = ["breezy", "nautilus_trader"]` (`pyproject.toml:68`), so `scripts/`
is outside every import-linter contract, and the cross-script `sys.path.insert` it relies on is the
established pattern (`structural_dead_stop.py:48-65` does exactly this under the same strict-mypy
coverage). No layer violation, and keeping the impure I/O in `scripts/` while the pure core sits in
`src/breezy/analysis/` is consistent with the census. No defect.

## Defects found in revision 3

**09-4 (MATERIAL, NEW) — the runner itself has no named module, and H0/H3 name a shell script as the
caller of Python functions.**
Every other component in this backlog is named to a file: the census
(`scripts/analysis/replay_sufficiency_census.py`), the producer (`scripts/analysis/asos_cache_csv.py`),
the cores (`src/breezy/analysis/replay_sufficiency.py`, `…/replay_results.py`). The **runner** is not.
H0's Reader row says `read_replay_sufficiency` is "called by `deploy/systemd/replay-daily-run.sh`'s
target-selection step" and H3's Writer row says `append_replay_result` is "called by
`deploy/systemd/replay-daily-run.sh`" — a shell script cannot call a Python function, so both
contracts name an impossible binding. §7 step 9 says "GREEN the runner script" without naming it;
§6b.3's wrapper sketch has `record_blocked` as an undefined shell helper. This is not cosmetic: the
components with no specified home are exactly the ones carrying the plan's strongest repairs — target
selection under the full key, the `RECOVERED`/`FAILED` crash branch (N3), the duplicate-key hard
error, and the row append. Whether they live in shell or in Python decides whether H0/H3 are
enforceable at all, and B17 (which parses the wrapper) does not cover them.
REQUIRED: name the runner module (e.g. `scripts/analysis/replay_daily_runner.py`), state which steps
live in it and which in the wrapper, correct H0's Reader and H3's Writer "called by" rows to that
module, and give `record_blocked` its home.

**b1 (MINOR) — the producer's output set and its emptiness predicate are two different sets, and
neither names a window helper.** §6b.1 says it "writes those rows" (every cached row whose `station`
matches, as `load_recent_asos_rows` returns them, `cli_basis_offer_gate_scan.py:495-536`) but exits
`ASOS_CACHE_EMPTY` "when zero rows fall inside the target climate day's window" — so the CSV may span
the whole cache while the gate is per-day. The repo has named window machinery
(`registry.climate_day_window`, `normalize.climate_day.standard_time_zone`, the `AFTERNOON_WINDOW_*` /
`ASOS_FETCH_*` constants `structural_dead_stop.py:53-56` already imports); none is cited. §13 concedes
the boundary is "specified by intent". REQUIRED: state whether `--out` is windowed, and name the helper
that computes the boundary.

**b2 (MINOR) — a false justification for the mypy entry.** §6 states that without the
`"src/breezy/analysis"` entry "the new package would be the only unchecked source package in the
repo". `[tool.mypy] files` (pyproject.toml:159-189) omits **`src/breezy/app`** and
**`src/breezy/features`**, both of which exist. The change itself is right; the reason given is not.
REQUIRED: drop or correct the clause.

**b3 (MINOR) — the producer inherits a hardcoded five-ICAO map, which bounds the portability claim.**
`settlement_alignment_study.load_sites` resolves `iem_asos_id` through `IEM_ASOS_IDS` (`:65-71`,
five entries) and raises `RuntimeError(f"no explicit IEM ASOS mapping for {site.icao}")` at `:647-649`
for anything else. So the moment §6c step 3 adds a sixth site to the registry, both the ASOS producer
**and** `count_covered_listed_station_days_from_catalog` (which calls the same `load_sites()` at
`structural_dead_stop.py:237`) fail hard. No effect today — a *candidate* is unregistered and a *seed*
is one of the five — but the census's "covers the AUD-08b candidate cities" framing invites the
opposite reading. REQUIRED: one line in §12 naming this as the next constraint on step 6.

Also carried, unchanged and still correct: `load_sites` is `:638-658`, not `:638-659` (trivial).

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 17 | "Scheduled" and "machine-readable" both covered; SP-4 folded **with** its blocker rather than around it; §6c bounds the item to step 6. The family dimension the promotion loop eventually needs is deferred with an owner, not delivered — honestly stated, still a completeness gap against G-06's downstream half. |
| Technical correctness and evidence grounding | 20 | 17 | Both round-2 verified errors are fixed against source I re-read independently (`forbidden.py:72,131-143`; `:932`; `:1082`; `config.py:226`; `pm_us_crh_v4.json:17`; `InstanceVerdict:247`, `classify_instance:391`, `load_recent_asos_rows:495`, `parse_asos_rows:634`, `DEFAULT_LOOKBACK_DAYS:91`). Deducted for the false mypy-coverage claim (b2) and the unstated IEM-map bound (b3). |
| Implementation specificity and feasibility | 15 | 11 | Command block complete and test-pinned, `<id>` bound, producer composed of named functions, `classify_station_day` given a signature. Deducted: the runner has no module and H0/H3 name a shell script as a Python caller (09-4); the producer's window/output set is by intent (b1). |
| Acceptance criteria and validation quality | 20 | 17 | B1–B17 objective; B9 two-way; B14/B16/B17 close the three round-2 gaps; B11 restated to something achievable. Deducted: B17 covers the wrapper's command but nothing covers the unnamed selection/append component (09-4), and B2 remains the sole falsification of the sufficiency picture. |
| Autonomous operation, failure handling, recovery | 15 | 13 | `ASOS_CACHE_EMPTY` is first-class and keeps the day queued; unreadable-work-list distinguished from empty-queue; crash recovery, duplicate-key hard error, skip-not-kill flock, own-cgroup OOM, timer gated on a non-`BLOCKED` row. Deducted: a persistently empty cache yields a quiet nightly `BLOCKED` row with no escalation of its own (conceded in §13), and ownership of the crash-recovery branch is undecided (09-4). |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | Mechanism-vs-edge separation now on two independent grounds; the deferred driver change named with an owner; PREREG barrier and permit path untouched; abandonment criterion with a stated adjustment. No defect found. |
| **Total** | **100** | **85** | |

## Required changes to reach 100
1. Name the runner module, split wrapper vs. module responsibilities, and correct H0's Reader and
   H3's Writer rows (09-4).
2. State the producer's window helper and whether `--out` is windowed (b1).
3. Correct the mypy-coverage justification (b2) and name the IEM-map bound in §12 (b3).

## Blockers (recorded separately; not scored)
- **Evidence/data availability (build):** whether the settlement-alignment cache holds ASOS rows for
  the target climate day. Correctly measured at §7 step 3 *before* the runner is built, with both
  outcomes pre-defined and the timer gated on a non-`BLOCKED` row. No plan change can resolve it.
- **Deferred change with a named owner:** a challenger family cannot be replayed until
  `current_rung_hold_paper_replay.py` grows `--family-manifest`. Correctly excluded from scope and
  mirrored in AUD-10 §12.
- **Strategy lead:** R1 `trial_id` provenance; and whether a `MECHANISM_ONLY` replay result may be
  cited in a PREREG v3 §9 context (default taken: no). Both block a statistical reading, not the
  build, and neither is decided in-plan.

_Saved verbatim by the coordinator: the `architect` reviewer has no file-write tool._
