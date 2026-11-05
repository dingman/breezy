# AUD-09 — Scheduled per-station replay producing a machine-readable result

## 1. ID and actionable title

**AUD-09** — Replace the manual, stale, human-read backtest/replay with a **scheduled per-station
replay** that (a) first decides, cheaply and on disk, *which station-days can be replayed at all*,
and (b) replays exactly one eligible station-day per run inside the existing memory-capped studies
slice, emitting a machine-readable result record for AUD-10 to consume.

Split:

- **AUD-09a** — **replay-sufficiency census**: disk-only, per `(station, climate_day)`, dated,
  machine-readable, **versioned** (§6a, hand-off H0). Cheap. Independently useful (it answers "why
  did nothing replay?"), and the named reader of AUD-08b's candidate register (§6a, hand-off H1).
- **AUD-09b** — **scheduled replay runner**: one station-day per invocation, driven by the census,
  emitting `replay_results.jsonl`. **Includes the `--asos-cache-csv` producer** the driver requires
  (§6b.1) — *round-2 change*: without it the runner cannot execute a single replay.

## 2. Source finding and class

- **Gap:** G-06 "Backtesting is manual, stale and feeds nothing." Verdict **FALSE (autonomy)**;
  evidence agent-reported (A) for the mtimes, not re-checked by the coordinator.
- **Evidence cited by the audit:** harness exists —
  `src/breezy/runtime/backtest_harness.py:663-736`,
  `scripts/analysis/run_weather_strategy_backtests.py`,
  `scripts/analysis/current_rung_hold_paper_replay.py`,
  `scripts/analysis/whole_tape_paper_replay.py`. **No timer runs any of them** — confirmed in
  round 1 by an independent reviewer enumerating `deploy/systemd/*.timer`: the installed set is
  `breezy-exit-window-study`, `family-tally@`, `k1-daily`, `live-tally`, `mb-daily`,
  `offer-gate-daily`, `position-monitor-report`, `quote-tape-ingest{,-frequent}`,
  `quote-tape-rotate`, `score-live-trials`. No replay/backtest unit exists.
  Last artefacts 09-03 / 09-05. Output is human-read only.
- **Class:** **autonomous-operation failure** (the capability exists and is not operated), with a
  **verification gap** underneath it (nobody can state which days are replayable).

**Existing PROGRESS item — UPDATE, do not duplicate.** `SP-4` (PROGRESS.md:55): *"subclass DONE
09-13; replay NOT RUN"*, plan `docs/plans/V3_BACKTEST_REPLAY_SUBCLASS_2026-09-12.md`, whose
Increment F is exactly one capped SFO 2026-09-01 run with the command at plan :80-91. **AUD-09b
subsumes SP-4's Increment F**: SP-4's single hand-run becomes this item's first scheduled run, and
SP-4's PROGRESS row is re-pointed at this plan rather than a second row being opened.
***AUD-09b also inherits SP-4's own open blocker and does not drop it*** (round-2 MATERIAL):
`V3_BACKTEST_REPLAY_SUBCLASS_2026-09-12.md:90` writes the command's `--asos-cache-csv` argument as
`<see §9 UNVERIFIED>`, and that plan's `:137` states verbatim: *"no producer script exists under
`scripts/` and no matching CSV was found under `~/.local/share/breezy` (searched to depth 4).
`read_asos_rows` needs `station,valid,metar` columns. Locate or regenerate it; a missing file makes
F unrunnable."* Revision 2 claimed the subsumption while presenting an invocation the driver's own
argparse rejects. §6b.1 discharges it; §12 keeps the honest residual.

## 3. Current behaviour, required behaviour, concrete gap

**Current.**

1. Replay is invoked by hand. `current_rung_hold_paper_replay.py::main` (`:1074`) takes
   `--climate-day`, `--station`, `--tape-instance-id`, `--tape-subdirectory`, `--quote-catalog`,
   `--work-catalog`, **`--asos-cache-csv` (required)**, `--weather-catalog-root`, `--lag-minutes`,
   `--output-dir`, `--strategy`, `--monitor-out-dir` — the complete parser, re-read at
   `:1075-1113` in round 3. **There is no `--family`, no manifest path and no fee-coefficient
   argument.**
2. Its output is scored-trial parquet plus a markdown report — read by a human, consumed by no
   scheduled job (`FORECAST_LEVERAGE_AUDIT_2026-09-18.md:7`).
3. **Most station-days cannot be replayed.** Measured 2026-09-10 (memory
   `quote-tape-is-not-replay-sufficient`): across 09-01..09-10 **only SFO 09-01 is clean**. Causes
   are structural and named: an empty top-of-book bid emits no QuoteTick at all (L-35), so an
   ask-only hunter subscribed to quotes is blind for hours; `breezy-quote-tape-ingest` refuses an
   entire instance forever if one file is truncated; and three outright outages (09-02 venue
   listing gap, 09-06 afternoon, 09-09 17:17Z–00:09Z).
4. Nothing computes or records that sufficiency. It exists only as a scratchpad audit and a memory
   note. A scheduler built without it would spend a 10–24 GB job slot to discover a day is dead.
5. **Price history is forward-only** (PROGRESS.md:31): an insufficient day is insufficient
   permanently.
6. **The observation input the driver requires has no producer.** `read_asos_rows`
   (`current_rung_hold_paper_replay.py:471-474`) is a bare `csv.DictReader` over a
   `station,valid,metar` file, consumed at `:1176`; `--asos-cache-csv` is `required=True` at
   `:1082`. A round-3 repo search found no script writing that file. `scripts/analysis/
   asos_recent_refresh.py` refreshes a *different* artefact — URL-keyed `.txt` cache files in the
   settlement-alignment cache directory — and is already scheduled nightly from two wrappers
   (`deploy/systemd/offer-gate-daily-run.sh:80`, `deploy/systemd/mb-daily-run.sh:86`).

**Required.**

- A dated, machine-readable, **versioned** census of `(station, climate_day) →
  SUFFICIENT | INSUFFICIENT(reason)` with the winner tape instance named, recomputed daily as the
  tape grows forward, and covering the AUD-08b candidate cities so "why is there no replay for city
  X" is answerable in one artefact.
- A scheduled runner that picks the highest-priority **unreplayed SUFFICIENT** station-day, replays
  exactly that one, and writes a result record carrying: station, climate day, family id, strategy,
  lag, tape instance id, trials taken, fills, per-fill price vs decision ask, refusal-reason counts,
  wall-clock, peak RSS, a **validity tag**, and — new in round 3 — **the parameters the engine
  actually ran with, next to the parameters the named family registers**.
- **The runner's command must be runnable exactly as written.** That means the ASOS CSV exists,
  by a named producer, before the timer is enabled.
- The runner must obey the host's real constraints: nightly studies run 10–24 GB, one heavy job at
  a time inside `breezy-studies.slice`; `mb-daily-run.sh`'s host-wide `flock` on
  `$XDG_RUNTIME_DIR/breezy-studies.lock`, skip-not-kill.
- The result must be **honestly tagged**: a MECHANISM result, not an edge result, until the
  look-ahead and cost items land.

**Concrete gap.** Three absent things: the census, the schedule + machine-readable result, and the
observation CSV the existing driver already demands.

## 4. Priority, rationale, dependencies, execution order

**Priority: P1** for AUD-09a, **P1** for AUD-09b.

Rationale: the audit's overall verdict is that the discovery → backtest → promotion → execution loop
is not autonomous. Of the four stages, **backtest is the only one where the capability is already
built and merely unoperated** — so it is the cheapest stage to move from FALSE to TRUE, and it is
the input AUD-10 needs to exist at all. It is P1 rather than P0 because nothing here restores
trading; G-01's two structural gates (memory `two-structural-gates-block-every-take`) do.

**Dependencies.**

- AUD-09b **depends on AUD-09a** (the census is its work queue).
- AUD-09a **reads AUD-08b's `station_candidates.jsonl`** (hand-off H1, §6a). The read is
  non-blocking: a missing register is a WARN and an empty candidate set, never a census failure, so
  AUD-09 can ship before AUD-08b.
- AUD-09b **depends on SP-4's merged subclass** (`ContinuousRungHoldBacktestStrategy`, done 09-13)
  — already in the tree.
- AUD-09b **contains** the `--asos-cache-csv` producer (§6b.1). It is not a dependency on another
  item; it is scoped in. It **does** depend on the already-scheduled `asos_recent_refresh.py` having
  populated the settlement-alignment cache — which is a data availability condition, not a code
  dependency, and is handled as a named failure case (§9, `ASOS_CACHE_EMPTY`).
- **Validity depends on AUD-11 (look-ahead) and AUD-12 (costs)** — by id only. Until both land,
  every result row is written with `validity: "MECHANISM_ONLY"`. AUD-09 does **not** wait on them.
- **AUD-19 is a downstream sibling, not a dependency** (RULING Q4 item 1): it owns the
  `--family-manifest` driver flag AUD-09 excludes (§5, §6b.2 item 5). AUD-09b runs the armed family
  only and never waits on it; AUD-19 itself is gated on the ruling's Q1 `trial_id` fix.
- **AUD-10 consumes** `replay_results.jsonl` (hand-off H3, §6b.4).

**Execution order:** AUD-09a → AUD-09b (producer first, then runner) → (AUD-11, AUD-12 flip the
validity tag) → AUD-10.

## 5. Scope and explicit exclusions

**In scope.** A census core module + script; **the `--asos-cache-csv` producer script** (round-2
change); a runner script; one new systemd service + timer; the result-record schema; the
`[tool.importlinter]` amendment and the `[tool.mypy] files` entry the new package requires; tests;
one real capped run as the acceptance artefact.

**Explicitly excluded.**

- Any change to `ContinuousRungHoldStrategy`, `ContinuousRungHoldBacktestStrategy`,
  `backtest_harness.py`, or the fill model. The replay *engine* is done; this item operates it.
- **Any change to `current_rung_hold_paper_replay.py` itself, including the `--family-manifest`
  flag** a challenger replay would need. *Round-2 decision (09-2), stated once and carried into
  AUD-10:* the runner replays the **armed family only**; see §6b.2 for why, what it costs, and what
  is recorded as a consequence. Adding the flag later is **owned by AUD-19** — a new sibling backlog
  item created by RULING
  `docs/evidence/RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21.md` (Q4 RULING
  item 1), cited here **by id only** — and AUD-19 may not land before that ruling's Q1 `trial_id`
  provenance fix lands.
- Any change to PREREG v3 §3/§5/§9 semantics. Paper/replay rows never enter the live tally —
  `assert_paper_only` / `assert_live_only` (`scripts/analysis/live_family_tally.py:148,168-180`) and
  `test_paper_rows_never_pool_into_the_live_tally` stay untouched and green.
- Fixing look-ahead (AUD-11) or the slippage placeholder (AUD-12).
- Back-filling missing tape, and **fetching** ASOS observations. The producer of §6b.1 is
  **cache-only and zero-network**, exactly like `cli_basis_offer_gate_scan.py`, so it runs inside
  the no-egress test sandbox. The network fetch stays where it already is
  (`asos_recent_refresh.py`, already scheduled).
- Running the whole-tape driver on a schedule. `whole_tape_paper_replay.py` fans over every
  station-day in one process and has a measured unbounded-memory history (L-31; memory
  `replay-driver-memory-grows-unbounded`). The scheduled unit runs the **single-day** driver.
- **Replaying any station outside `SUPPORTED_STATIONS`.** See H1: an AUD-08b candidate is recorded
  by the census and never queued. §6c states the full path by which that could ever change.
- **Emitting a promotion proposal.** That is AUD-10b. *Round-4 note (09-5 = AUD-10 10-6), recorded
  here so the two plans cannot drift:* AUD-10 §6b.4 **appends one further `"$PY"` invocation** of
  `scripts/analysis/promotion_proposal.py` to this item's `deploy/systemd/replay-daily-run.sh`,
  inside the same host-wide `breezy-studies.lock`, after the replay. That addition is **expected and
  sanctioned**, is owned by AUD-10, and is why **B18** asserts a property over a named script set
  rather than an invocation count (§6b.3). Nothing else may be appended to this wrapper without
  amending B18's named set.

## 6. Proposed changes (grounded)

**Nautilus null hypothesis (L-1).** Multi-run sequencing: `BacktestNode(configs)`
(`.venv/lib/python3.13/site-packages/nautilus_trader/backtest/node.py:79-107,459-490`) sequences
`BacktestRunConfig`s **in one process**. Breezy's own prior verdict on exactly this question is
recorded: *"NATIVE — insufficient … Do not invent a Node fan-out"*
(`WHOLE_TAPE_PAPER_REPLAY_2026-09-05.md`, L-1 block), because the Breezy paper path is one
`BacktestEngine` via `backtest_harness.build_backtest_engine:663` + `backtest:1027`. A
multi-day-in-one-process fan-out is also precisely the shape that produced the unbounded-memory
incident (L-31). **Verdict: the scheduling unit is GENUINELY ABSENT from Nautilus** — `systemd`
timers are the native scheduler here, and the engine stays the native one, run once per invocation.
Nothing about Nautilus is modified, forked or wrapped.

### The layer decision (coordinator requirement 1 — identical in AUD-09 and AUD-10)

Verified in round 1: `src/breezy/analysis/` **does not exist**, the `[tool.importlinter]` layers
contract (pyproject.toml:71-101) is `exhaustive = true` (:92), and the current top-level packages are
exactly `adapters, app, domain, features, ingest, normalize, persistence, registry, runtime,
settlement, strategy`. A new `breezy.analysis` package therefore fails `lint-imports` on the first
run — the plan's own gate.

**Decision: create `analysis` as a real layer, positioned immediately BELOW `app` and ABOVE
`strategy`.** Rationale: the offline analysis cores must reach *down* into `persistence`
(`feather_preflight`, `family_manifest`, `station_candidates`), `settlement` (`roi_bound`,
`current_rung_hold_v2`) and `strategy` (`SUPPORTED_STATIONS`), and **nothing in the trading path may
reach up into them**. A layer above `strategy` grants exactly that downward reach; the layers
contract then forbids every package below from importing `analysis`. The one hole layers alone leave
is `app` (which sits above and would be permitted to import `analysis`) — closed explicitly by a
`forbidden` contract, because the property that matters is *the live node process never loads
offline analysis code*.

**The literal `pyproject.toml` change.** In the existing contract
*"Breezy top-level source packages follow the documented layer direction"*, insert one entry:

```toml
layers = [
    "app",
    # Offline analysis cores (census, promotion criteria). Reach DOWN into
    # strategy/persistence/settlement for constants and loaders; nothing below
    # may reach up into them, and `app` is barred by the forbidden contract
    # below so the live node process never loads offline analysis code.
    "analysis",
    "strategy",
    "runtime",
    "adapters",
    "ingest",
    "persistence | registry | normalize",
    "features | settlement",
    "domain",
]
```

and add two new contracts:

```toml
[[tool.importlinter.contracts]]
name = "The live trading path never imports the offline analysis layer"
type = "forbidden"
source_modules = [
    "breezy.app", "breezy.strategy", "breezy.runtime", "breezy.adapters",
    "breezy.ingest", "breezy.persistence", "breezy.registry", "breezy.normalize",
    "breezy.features", "breezy.settlement", "breezy.domain",
]
forbidden_modules = ["breezy.analysis"]

[[tool.importlinter.contracts]]
name = "The offline analysis layer never DIRECTLY imports Nautilus"
type = "forbidden"
source_modules = ["breezy.analysis"]
forbidden_modules = ["nautilus_trader"]
# The property wanted is NO DIRECT ADOPTION: an analysis module must never
# write `import nautilus_trader`. Indirect chains are unavoidable and are NOT
# adoption -- `analysis` is permitted to import `breezy.strategy`, and
# `breezy.strategy.current_rung_hold.config` imports
# `nautilus_trader.model.identifiers` / `nautilus_trader.trading.config` at
# config.py:59-60, which is also where SUPPORTED_STATIONS (:76) lives. Same
# reasoning, and the same flag, as the `.com` adapter contract above.
allow_indirect_imports = true
```

***Round-2 change (09-1, identical to AUD-10's 10-1) — the `allow_indirect_imports = true` line and
its comment are new; revision 2's contract could not pass.*** Verified at source:
`ForbiddenContract.allow_indirect_imports = fields.BooleanField(required=False, default=False)`
(`.venv/lib/python3.13/site-packages/importlinter/contracts/forbidden.py:72`), and at `:131-143` a
false value takes the `graph.find_shortest_chains(...)` branch — so **indirect chains are violations
unless the flag is explicitly true**. With `nautilus_trader` in `root_packages` (pyproject.toml:68),
the chain `breezy.analysis.replay_sufficiency → breezy.strategy…config → nautilus_trader` would be
found on the first run.

**Why this option and not the other.** The reviewers offered two remedies: set the flag, or
re-source `SUPPORTED_STATIONS` from a Nautilus-free module. **The flag is taken, as the smaller
change**, on three grounds: (i) re-sourcing means editing
`src/breezy/strategy/current_rung_hold/config.py` — a live strategy module with **8 in-repo callers
of `SUPPORTED_STATIONS`** across `config.py`, `composition.py`, `app/trade.py`,
`scripts/analysis/whole_tape_paper_replay.py` and four test modules — to satisfy a lint property,
which is exactly the "edit the trading path to please a contract" inversion the repo's own `.com`
contract comment warns against; (ii) the property actually wanted *is* no direct adoption, and the
repo already has a written precedent for saying so — `allow_indirect_imports = true` with a rationale
at `pyproject.toml:116-121`; (iii) AUD-10a independently **removes** the `SUPPORTED_STATIONS` import
from `composition.py`, so re-sourcing would collide with an item in the same backlog. The residual
risk is named honestly: with the flag set, an analysis module could reach Nautilus **indirectly**
and still pass. That is accepted, because the failure it guards against — an analysis core taking a
direct dependency on the framework — is the one that would make offline code un-runnable outside a
Nautilus process, and it is still caught.

`analysis` may import: `strategy`, `runtime`, `adapters`, `ingest`, `persistence | registry |
normalize`, `features | settlement`, `domain` — and **not** `app`, **not** `nautilus_trader`
directly. No entry is added to `ignore_imports`. **`"src/breezy/analysis"` is also added to
`[tool.mypy] files` (pyproject.toml:159-189), where `strict = true` (`:158`) applies.**
*Round-3 b2 accepted — the change stands, the reason given for it did not:* revision 3 claimed the
new package "would be the only unchecked source package in the repo", which is **false**. Re-read
this round, `[tool.mypy] files` (`:159-189`) lists `adapters, normalize, registry, settlement,
domain, ingest, persistence, runtime, strategy` and **omits `src/breezy/app` and
`src/breezy/features`**, both of which exist on disk. The correct reason is narrower and sufficient:
the analysis cores are the *only* consumer of the census/results contracts (H0/H3) and their
signatures are the seam AUD-10b reads, so they are typechecked at the same strictness as the
`persistence` loaders they sit beside — not because of a repo-wide property that does not hold. The
two unchecked packages are pre-existing and are **not** in this item's scope. AUD-10 states this decision
verbatim; the two plans must not diverge, and B10/C10 in the two acceptance tables are the same
criterion.

### AUD-09a — census

- New `src/breezy/analysis/replay_sufficiency.py` (pure; no direct `nautilus_trader` import, pinned
  by the second contract above):
  - `ReplaySufficiency` frozen dataclass: `schema_version, station, climate_day, verdict, reason,
    winner_instance_id, depth_window_minutes, quote_window_minutes, distinct_instruments,
    computed_day`.
  - **`classify_station_day`'s signature, given rather than described** (round-2 b2 accepted; the
    reviewer was right that this is the seam between the script-side scanners and the pure core):

    ```python
    def classify_station_day(
        *,
        station: str,
        climate_day: str,
        instances: Sequence[InstanceSpan],
        computed_day: str,
    ) -> ReplaySufficiency: ...

    @dataclass(frozen=True, slots=True, kw_only=True)
    class InstanceSpan:
        instance_id: str
        verdict: Literal["CLEAN", "EMPTY", "LIVE", "CORRUPT"]
        depth_window_minutes: float
        quote_window_minutes: float
        distinct_instruments: int
    ```

    `InstanceSpan` is a **pure value the script builds**; the core never touches disk. Its
    `verdict` field is deliberately the same four-value alphabet as
    `cli_basis_offer_gate_scan.InstanceVerdict = Literal["CLEAN","EMPTY","LIVE","CORRUPT"]`
    (`cli_basis_offer_gate_scan.py:247`), produced by `classify_instance(report, *, now_ns,
    grace_ns=WRITER_ACTIVITY_GRACE_NS) -> InstanceVerdict` (`:391-410`) from a
    `PreflightReport` (`persistence/feather_preflight.py:168-205`) returned by
    `scan_instance(catalog_root, instance_id, subdirectory) -> PreflightReport` (`:501-531`). The
    script converts; the core classifies. Declaring the alphabet locally rather than importing it
    is deliberate: `cli_basis_offer_gate_scan` lives in `scripts/` and is unimportable from
    `src/breezy/**`, and **B15** pins the two literals equal so they cannot drift.
- New `scripts/analysis/replay_sufficiency_census.py` — the I/O wrapper. It reuses, without
  modification:
  - `persistence/feather_preflight.py:488 list_instance_ids` and `:501 scan_instance`;
  - `scripts/analysis/cli_basis_offer_gate_scan.py:391 classify_instance` and
    `:441 station_days_only_on_corrupt_tape` (cross-script `sys.path.insert` is the established
    repo pattern, used by 37 scripts — feasible for the **script**, which is why the impure I/O
    lives here and not in `src/`);
  - the **de-dup / winner rule already ruled on**: key `(station, climate_day)` only, winner = the
    CLEAN instance with the longest in-window Depth10 span, and **two CLEAN instances each ≥30 min
    ⇒ REFUSE the pair** — no first-list, no stitch, no union
    (`WHOLE_TAPE_PAPER_REPLAY_2026-09-05.md`, "De-dup BEFORE replay"; memory
    `paper-replay-instance-selection` records the zero-fill trap the first-listed instance caused);
  - the coverage basis is **DEPTH**, not quotes: v3 hunts Depth10 (L-35), and at `L2_MBP` the
    QuoteTick tape is inert for execution (`BACKTEST_VENUE_CONFIG.md:144-150`). The census reports
    both spans but decides on depth — matching `assert_decision_window_has_coverage(...,
    source="depth")` (`current_rung_hold_paper_replay.py:257`);
  - the ≥30 min afternoon-coverage threshold from `structural_dead_stop.py:163-216` (rule at :214),
    so the census and the KILL clock cannot disagree about "covered".
- **Refusal reasons are a closed alphabet**, each traceable to a measured cause:
  `NO_CLEAN_INSTANCE`, `AMBIGUOUS_WINNER_TWO_CLEAN_GE_30MIN`, `DEPTH_WINDOW_UNDER_30MIN`,
  `NO_IN_WINDOW_DEPTH`, `VENUE_NEVER_LISTED_UNCONFIRMED`, `INGEST_INSTANCE_REFUSED`, `CORRUPT_ONLY`,
  `CANDIDATE_UNSUPPORTED_STATION`. *Round-1 change (n4 accepted):* there is now exactly **one**
  never-listed token — `VENUE_NEVER_LISTED_UNCONFIRMED` — because the census never probes the venue
  and a by-slug probe is what promotes a guess to a fact (memory `venue-skips-station-days`).

**Hand-off H0 — AUD-09a → AUD-09b (REAL; round-2 change 09-3).** Round 2 established that
`replay_sufficiency.jsonl` crosses a process boundary *and* a merge boundary while carrying only a
`schema_version` field and none of the seven-row discipline H1/H3 carry — so a stale file from a
previous schema would be silently consumed by target selection, the exact failure H1/H3 refuse. The
finding is accepted; the artefact is brought up to the same standard:

| Field | Value |
|---|---|
| Artefact | `~/.local/share/breezy/derived/replay/replay_sufficiency.jsonl` |
| `schema_version` | `1` (`REPLAY_SUFFICIENCY_SCHEMA_VERSION`, `src/breezy/analysis/replay_sufficiency.py`) |
| Writer | `breezy.analysis.replay_sufficiency.write_replay_sufficiency`, called by `scripts/analysis/replay_sufficiency_census.py` — atomic temp + `os.replace`, **whole-file rewrite** (a derived view of the tape, not an append-only ledger) |
| Reader | `breezy.analysis.replay_sufficiency.read_replay_sufficiency`, called by **`scripts/analysis/replay_daily_runner.py`**'s target-selection step (*round-3 09-4*: revision 3 named the shell wrapper, which cannot call a Python function; the wrapper only invokes the module) |
| Record key | `(station, climate_day)` — one line per key; a duplicate key in the file is a hard error, never last-wins |
| Unknown version | `UnknownReplaySufficiencySchemaError` — the runner **refuses and exits non-zero**, naming path, line number and version seen. It never falls back to an empty queue, because "no work" and "unreadable work list" must not look alike |
| Idempotency key | `(station, climate_day)`; two consecutive census runs over an unchanged tape are byte-identical (B3) |

**Hand-off H1 — AUD-08b → AUD-09a (REAL; stated identically in AUD-08 §6c).**

| Field | Value |
|---|---|
| Artefact | `~/.local/share/breezy/derived/station_candidates/station_candidates.jsonl` |
| `schema_version` | `1` (`STATION_CANDIDATES_SCHEMA_VERSION`) |
| Writer | `breezy.persistence.station_candidates.write_station_candidates` (AUD-08b) |
| Reader | `breezy.persistence.station_candidates.read_station_candidates`, called by `scripts/analysis/replay_sufficiency_census.py` |
| Join key | `(venue, city_token)`, mapped to a station code by the registry's `venue_city_token` → site mapping |
| Unknown version | `UnknownStationCandidateSchemaError` — the census **fails loudly**, never degrades |
| Idempotency key | `(venue, city_token, last_seen_day)` |

Behaviour: for every candidate, the census emits one row with `verdict="INSUFFICIENT"` and
`reason="CANDIDATE_UNSUPPORTED_STATION"`, carrying the candidate's sufficiency. It is **never**
added to the replay queue — no station outside `SUPPORTED_STATIONS` can be replayed (the frozen
archive table and the strategy allow-list both cover four stations only, `config.py:74-76,245-252`).
A missing register file is a WARN and an empty candidate set, so AUD-09 does not block on AUD-08b.

**Hand-off H2 — AUD-08b → AUD-10: DECLINED, without residue.** Recorded here and in AUD-08 §6c and
AUD-10 §6b: a candidate cannot enter a promotion proposal because promotion cannot widen the station
allow-list. Expansion is a ruling, not a promotion. *Round-2 change (10-2/a2 accepted, decided once
for all three plans):* AUD-10's `C-STATIONS` is a **pure subset predicate with no register read**,
and the "register candidate count recorded in `criteria.json`" clause is **deleted** — recording a
count required reading the artefact, which made "declined" false and left that read with no reader,
no version rule and no missing-file rule. The visibility it aimed at is delivered instead by
AUD-08b's one-shot `BREEZY_STATION_CANDIDATE_NEW` alert. Against G-05/G-06 this is the honest chain:
discovery *records and announces*, the census *explains*, and only supported stations reach the
queue.

### AUD-09b — runner

#### 6b.1 The `--asos-cache-csv` producer (round-2 MATERIAL accepted, scoped in)

`--asos-cache-csv` is `required=True` (`current_rung_hold_paper_replay.py:1082`); `read_asos_rows`
(`:471-474`) is `list(csv.DictReader(handle))` over a file its own docstring describes as
*"`station,valid,metar` rows verbatim -- no price ever derived here"*, consumed at `:1176`. A
round-3 search confirms the reviewer and SP-4 §9: **no producer exists**. Rather than leave it as a
blocker, AUD-09b builds one, because every piece already exists:

- New `scripts/analysis/asos_cache_csv.py`, **cache-only and zero-network by construction** — the
  same guarantee, and the same reason for it, as `cli_basis_offer_gate_scan.py` (that script's own
  docstring: it must run inside the no-egress sandbox). It:
  - resolves the station's IEM id through the existing `load_sites()`
    (`scripts/analysis/settlement_alignment_study.py:638-658`), which maps each registry
    `(venue, city)` pair to a `SiteSpec` carrying `iem_asos_id`. **Bound, stated (round-3 b3):**
    that resolution goes through the hardcoded five-entry `IEM_ASOS_IDS`
    (`settlement_alignment_study.py:65-71` — `KNYC/KSFO/KMIA/KMDW/KLAX`) and raises
    `RuntimeError(f"no explicit IEM ASOS mapping for {site.icao}")` at `:646-649` for anything
    else. See §12 and §6c step 6;
  - calls the existing `load_recent_asos_rows(cache_dir, iem_asos_id)`
    (`scripts/analysis/cli_basis_offer_gate_scan.py:495-536`), which parses **every** `.txt` file in
    `DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR` with the reused
    `settlement_alignment_study.parse_asos_rows` (`:634-635`), keeps rows whose `station` column
    matches, de-duplicates on `(station, valid)` and returns them sorted by `valid`. Its own
    docstring states it returns `()` for a missing directory or an unfetched station — never
    fabricated, never fetched;
  - **windows those rows to the target climate day before writing them** — `--out` and the
    emptiness predicate are therefore **the same set** (*round-3 b1 accepted*: revision 3 wrote
    "those rows" (every cached row for the station, as `load_recent_asos_rows` returns them,
    `cli_basis_offer_gate_scan.py:495-536`) while gating on "rows inside the target climate day's
    window", two different sets, and named no helper for the boundary);
  - the boundary is computed by **one named helper**,
    `climate_day_utc_bounds(*, station: str, climate_day: dt.date) -> tuple[int, int]` in
    `scripts/analysis/asos_cache_csv.py`, returning the half-open `[start_ns, end_ns)` of the
    climate day in **local standard time**. It composes the two existing pieces and adds no new
    time rule: `default_registry().climate_day_window(WEATHER_VENUE, station).std_utc_offset_hours`
    (`WEATHER_VENUE: Final[str] = "polymarket_us"`,
    `scripts/analysis/run_weather_strategy_backtests.py:352` — *round-4 b2 accepted*: it was used
    uncited; it is already reached by cross-script import from both replay drivers, so the helper
    adds no new coupling)
    (`src/breezy/registry/sites.py:403-414`; `ClimateDayWindow` at `:135-148`, whose docstring pins
    *"NEVER DST-aware: the climate day runs local-standard midnight to midnight all year"*) and
    `breezy.normalize.climate_day.standard_time_zone` — the identical pair
    `structural_dead_stop._afternoon_window_ns` composes at `:148-155`. The bound is **midnight to
    midnight**, deliberately **not** `AFTERNOON_WINDOW_START/END`
    (`ma_prelock_winner_ask_study.py:149-150`): those bound the *decision* window, whereas
    `load_replay_observations` (`src/breezy/runtime/paper_replay.py:181-206`) consumes observations
    across the whole replayed day and stamps each `received_at_ns = observed_at_ns + lag_minutes`.
    Rows outside the day are dropped rather than written: the engine's clock would never reach them,
    and carrying them would be exactly the output-set/predicate mismatch this defect named;
  - writes the windowed rows to `--out` as `station,valid,metar` with `csv.DictWriter`, restricted
    to exactly those three columns (the `metar` column exists because `asos_url`
    (`settlement_alignment_study.py:408-425`) requests `data=metar`);
  - **exits non-zero with `ASOS_CACHE_EMPTY` and writes no file** when zero rows fall inside
    `climate_day_utc_bounds(...)`. A zero-row CSV would make the replay run and report a clean
    zero-trial day, which is the "0 rows is not a quiet market" failure L-8 names. Should the driver
    ever be shown to need pre-midnight rows, widening is a one-line change **to that one helper**,
    with its own test — which is the point of naming it.
- **The upstream fetch is already scheduled and is not re-planned:** `asos_recent_refresh.py` runs
  nightly from `offer-gate-daily-run.sh:80` and `mb-daily-run.sh:86` and writes into that same cache
  directory. AUD-09 adds no network call and no new unit for it.
- **Honest residual:** the cache is refreshed with `DEFAULT_LOOKBACK_DAYS = 3`
  (`asos_recent_refresh.py:91`), so coverage of an *old* climate day — such as the expected first
  target, SFO 2026-09-01 — depends on what earlier incidental fetches happen to have left on disk.
  `load_recent_asos_rows` reads whatever is there and is explicit that this is a hard dependency
  (BL-24). This is **measured, not assumed**, at §7 step 3, and it is the one condition that can
  still block step 12. §12 keeps it as a named, testable blocker with an owner.

#### 6b.2 The family dimension — DECIDED: armed family only (round-2 09-2 / 10-3 accepted)

Round 2 established, against the driver's own parser, that revision 2's five-tuple queue key was
textual rather than operative: the driver takes no family, manifest or fee-coefficient argument
(`:1075-1113`), so the engine is built from config defaults while the row is stamped with a
`family_id` the engine never saw. Re-verified in round 3 at the construction site: the driver builds
`cfg = CurrentRungHoldConfig(instrument_ids=..., stations=(station,))`
(`current_rung_hold_paper_replay.py:932`) — **every other field defaults**, including
`required_fee_coefficient: Decimal = Decimal("0.06")` (`config.py:226`) — while the armed manifest
`deploy/families/pm_us_crh_v4.json` registers `"taker_fee_coefficient": "0.0695"`. Those two numbers
are not equal, and memory `venue-fee-theta-drift-2026-09-17` records that this drift is what refuses
every live order. Stamping such a row with `family_id: "pm_us_crh_v4"` and nothing else would be a
fresh instance of the exact error memory `bss-headline-is-the-wrong-family` and
`archive-table-train-serve-skew` record. The finding is accepted in full. The decision:

1. **The runner replays the ARMED family only.** It reads exactly one manifest —
   `deploy/families/{settings.sending_family_id}.json` via `load_family_manifest`
   (`persistence/family_manifest.py:211`) — the same single-manifest rule `app/trade.py:192-212`
   uses. `<id>` is therefore **bound**, which round 2 correctly flagged as an unresolved design
   decision in revision 2. No challenger list, no enumeration of `deploy/families/`.
2. **`family_id` is PROVENANCE, not a queue-key dimension.** The queue key drops to
   **`(station, climate_day, strategy, lag_minutes)`**. Re-replay policy is unchanged in shape: a
   station-day is re-replayed whenever any component of that key changes, never for an unchanged key.
   *This partially withdraws round 1's N2 fix, and says so:* N2's remedy was sound reasoning about a
   queue that could serve multiple families, but such a queue cannot exist until the driver can be
   told which family to run. Keeping the dimension would have left B11 passable only by a synthetic
   fixture — a criterion that can be unit-tested and never satisfied. B11 is restated accordingly.
3. **The engine's actual parameters are recorded next to the family's registered ones**, so the
   divergence is visible in the artefact rather than inferred. Every result row carries:
   `family_id` (from the manifest), `manifest_sha256` (from the manifest — **RULED**, Q1 RULING
   item 4: a *secondary, non-discriminating* integrity check a reader cross-checks against
   `load_family_manifest(...).manifest_sha256` (`persistence/family_manifest.py:185`, computed at
   `:220`) to catch a hand-edited or stale manifest; the discriminator itself is `family_id`),
   `manifest_taker_fee_coefficient` (from the manifest),
   `engine_required_fee_coefficient` (the value the driver's `CurrentRungHoldConfig` actually
   carried), `engine_params_source: "DRIVER_DEFAULTS"`, and
   `params_match: bool` = the two coefficients are equal. On today's tree `params_match` is
   **false** (`0.06` ≠ `0.0695`), and the plan expects it to be false — that is the point of
   recording it.
4. **A diverged row may never feed a promotion criterion.** AUD-10's `C-VALIDITY` is extended to
   refuse any row with `params_match == false`, exactly as it already refuses
   `validity == "MECHANISM_ONLY"`. A mechanism count (trials, fills, refusal histogram) is still
   legible; an edge statistic is not.
5. **AUD-10's `C-PAIRED` is recorded as INERT**, with a named dependency: it cannot evaluate true
   until a challenger-replay path exists, and that path is a `--family-manifest` flag on
   `current_rung_hold_paper_replay.py` threading at minimum `required_fee_coefficient` into the
   `CurrentRungHoldConfig` built at `:932`. That change is **excluded from AUD-09's scope** (§5), is
   named here as the single blocking change, and is **owned by AUD-19** (RULING Q4 item 1), itself
   gated on the ruling's Q1 `trial_id` fix landing first. AUD-10 §6b and §12 record the same
   dependency in the same words.

#### 6b.3 Wrapper, command, selection, schedule

**The runner has a module, and the wrapper/module split is stated (round-3 09-4 accepted in
full).** Revision 3 named every other component to a file — the census
(`scripts/analysis/replay_sufficiency_census.py`), the producer
(`scripts/analysis/asos_cache_csv.py`), the cores (`src/breezy/analysis/replay_sufficiency.py`,
`…/replay_results.py`) — but left the runner unnamed, had `record_blocked` as an undefined shell
helper, and wrote H0's Reader and H3's Writer as "called by
`deploy/systemd/replay-daily-run.sh`", i.e. a **shell script calling a Python function**, which is
not a binding that can exist. The reviewer is right that this is not cosmetic: the unnamed
components are exactly the ones carrying the strongest repairs (target selection under the full
key, the `RECOVERED`/`FAILED` branch, the duplicate-key hard error, the row append). All of them
move into Python:

**New `scripts/analysis/replay_daily_runner.py`** — the runner proper, strict-typed like its
siblings (`scripts/analysis` is inside `[tool.mypy] files`, pyproject.toml:177, under
`strict = true` at `:158`). It owns, end to end:

| Responsibility | Home | Why |
|---|---|---|
| Read `replay_sufficiency.jsonl` via `read_replay_sufficiency` (H0), including the unknown-version and duplicate-key refusals | **module** | it is a Python call; B14's refusals are unreachable from shell |
| **Target selection** under the full key `(station, climate_day, strategy, lag_minutes)`, oldest-first, tie-broken by `SUPPORTED_STATIONS` order | **module** | it joins two JSONL artefacts and must apply the same key the writer uses |
| Invoke the ASOS producer and the driver as **subprocesses** (`subprocess.run`, no `shell=True`), with the literal argument vectors below | **module** | keeps the `required=True` argument set in one place with the `argparse` introspection test (B17) |
| The `RECOVERED` / `FAILED` crash branch: read the orphan parquet, sha256 it, append the row, choose the exit code | **module** | it parses a parquet and an exception type |
| `record_blocked(reason)` — append one `outcome="BLOCKED"` row with `blocked_reason` from the closed set, exit 0, day stays queued | **module**, a function (revision 3's undefined shell helper) | one writer, one closed reason set |
| Row append via `append_replay_result`, including the duplicate-key hard error | **module** | H3's Writer |
| Daily summary line | **module**, to stdout; the wrapper's `say()` tees it to the log | one format, testable |
| **Stall escalation:** after appending a `BLOCKED` row, emit ONE alert when the run of consecutive `BLOCKED` rows sharing the same `blocked_reason` reaches **N = 3** (round-4 b1) | **module** | it reads `replay_results.jsonl`, which only the module does |

**`deploy/systemd/replay-daily-run.sh` keeps only what a wrapper is for** — and is modelled
line-for-line on `mb-daily-run.sh`: `unset POSIXLY_CORRECT`; `exec 9>>"$LOCK"`;
`flock -n 9 || exit 0` on the **same** host-wide `breezy-studies.lock`; `set -uo pipefail`; `say()`
logging to `$OUT/replay_daily.log`; environment/path resolution (`$PY`, `$REPO`, `$OUT`,
`$QUOTE_CATALOG`, `$WEATHER_CATALOG_ROOT`, `$OUT_ROOT`); its `"$PY"` invocations —
`scripts/analysis/replay_sufficiency_census.py`, then `scripts/analysis/replay_daily_runner.py` —
and propagation of the runner's exit code. It makes **no** selection decision, parses **no**
artefact, and contains **no** `record_blocked`.

**The wrapper's invocation contract is a PROPERTY over a named script set, never a count
(round-4 09-5 = AUD-10 10-6; round-5 b1: the bolded property sentence below is
identical word for word in AUD-10 §6b.4 (compare after whitespace normalisation: the two copies differ only in indentation and line-wrap, normalised sha256 ce5b6d1d…a26263) — the lead-in and closing around it are not, and are not
claimed to be).** Revision 4
asserted "exactly two `"$PY"` invocations", and **AUD-10 §6b.4 appends a third to this same
wrapper** — `scripts/analysis/promotion_proposal.py`, inside the same host-wide
`breezy-studies.lock`, after the replay. A count is therefore the wrong invariant: it would fail CI
the moment AUD-10b lands, and whichever way an implementer resolved that, it would be a cross-item
design decision neither plan had taken. The invariant that carries the property actually wanted is:
**every `"$PY"` invocation in `deploy/systemd/replay-daily-run.sh` is one of the named scripts —
`scripts/analysis/replay_sufficiency_census.py`, `scripts/analysis/replay_daily_runner.py`, and,
once AUD-10b lands, `scripts/analysis/promotion_proposal.py` — and the wrapper contains no JSONL
parsing and no `record_blocked`.** `promotion_proposal.py` is the **sanctioned third invocation**
and its later addition is expected, not a regression. **B18** asserts exactly that property, and
AUD-10 carries a criterion testing the same coupling from its side.

- Step 1 (wrapper): run the census. Steps 2–4 (module): read `replay_sufficiency.jsonl` (H0) and
  pick the target; produce the observation CSV; run exactly one replay. Steps 3–4 are the literal
  argument vectors the module builds, **complete — every `required=True` argument of the driver's
  parser is present** (round-2 b1 / MATERIAL accepted; revision 2's block omitted
  `--asos-cache-csv` entirely). Shown in shell form for readability; the module builds the same
  vectors as lists, and B17 asserts the set against the driver's own parser:

  ```sh
  # Both invocations are issued by scripts/analysis/replay_daily_runner.py via
  # subprocess.run(argv, shell=False); `record_blocked` is a function in that
  # module, never a shell helper.
  ASOS_CSV="$WORK/asos_${ST}_${DAY}.csv"
  "$PY" scripts/analysis/asos_cache_csv.py \
    --station "$ST" --climate-day "$DAY" --out "$ASOS_CSV"
  # non-zero exit here -> the module calls record_blocked("ASOS_CACHE_EMPTY"),
  # which appends one BLOCKED row, exits 0, and leaves the day queued.

  "$PY" scripts/analysis/current_rung_hold_paper_replay.py \
    --strategy continuous_rung_hold \
    --station "$ST" \
    --climate-day "$DAY" \
    --tape-instance-id "$WINNER" \
    --lag-minutes 30 \
    --quote-catalog "$QUOTE_CATALOG" \
    --work-catalog "$(mktemp -d)" \
    --asos-cache-csv "$ASOS_CSV" \
    --weather-catalog-root "$WEATHER_CATALOG_ROOT" \
    --output-dir "$OUT_ROOT/paper_replay/scored_trials/v3/$ST/$DAY/lag_30"
  ```

  `$QUOTE_CATALOG` and `$WEATHER_CATALOG_ROOT` are resolved from the same environment the other
  study wrappers use and are passed through to the module; they are elided as variables, never as
  `…`. Fresh empty `--work-catalog` per invocation (WHOLE_TAPE plan, "Wrap `main()`").
- **A persistently `BLOCKED` schedule escalates through the shipped alert sink (round-4 b1
  accepted).** Revision 4 conceded in its own self-score that a *persistently* empty ASOS cache
  "yields a quiet nightly `BLOCKED` row with no escalation of its own": the unit never fails, so
  G-14's alerting over unit state never fires, and the item's whole purpose — a schedule that
  actually replays — silently stops being met. That is the "detector without delivery is not a
  control" shape memory `readiness-audit-2026-09-12` prices at three days plus eleven hours of
  silent halt, and the remedy is one call, already shipped and already used by a sibling script.
  - **Rule.** After `record_blocked` appends a row, the module reads back the tail of
    `replay_results.jsonl` and computes the length of the **current run of consecutive `BLOCKED`
    rows carrying the identical `blocked_reason`**. When that run length **equals `N = 3`**, it
    emits exactly one alert. Any `COMPLETED`/`RECOVERED`/`FAILED` row, or a row with a different
    `blocked_reason`, resets the run. `N = 3` is not a new number: it is the same
    three-consecutive-failure tolerance AUD-08 §9 already uses for its emitter, so the two
    scheduled jobs escalate on the same rule.
  - **Path — the shipped one, not a new one.**
    `resolve_alert_sink(os.environ)` (`src/breezy/runtime/health.py:579`) then
    `emit_alert(sink, AlertPayload(...))` (`:668`), with
    `event="BREEZY_REPLAY_STALLED"`, `site=<station>`, `severity="warning"`, and a `detail` naming
    the `blocked_reason` and the act it implies (for `ASOS_CACHE_EMPTY`: widen
    `asos_recent_refresh.py --since`, or target a recent climate day — the two options §12 already
    enumerates with an owner). `AlertPayload` truncates `detail` to `MAX_ALERT_DETAIL_CHARS = 200`
    (`health.py:112,373-374`) and its own contract forbids an absolute path or a state dump; the
    detail above carries neither.
  - **Import-layer legality, checked rather than assumed.** The runner lives in
    `scripts/analysis/`, and `[tool.importlinter] root_packages = ["breezy", "nautilus_trader"]`
    (pyproject.toml:68), so `scripts/` sits outside **every** import-linter contract — including the
    two new `forbidden` contracts this item adds. The import is also precedented in this exact
    directory: `scripts/analysis/current_rung_hold_paper_replay.py:68` already does
    `from breezy.runtime.health import AlertPayload, emit_alert, resolve_alert_sink`. Note this is
    a *script* import, not a `src/breezy/analysis/` one — the cores stay free of `runtime`.
  - **Once per stall episode, deliberately.** Firing on run length *equal to* 3 gives one alert per
    episode rather than a nightly repeat. `runtime/health.AlertState` cannot be used for the dedupe
    for the same reason AUD-08 §6b.4 records: its own docstring states it is in-memory, per-process
    and never seeded from a persisted source, so in a nightly one-shot every condition cold-starts
    `False` and would re-fire every night. The durable property is the row run in
    `replay_results.jsonl`. **Residual, stated:** a stall lasting 30 days produces one alert, not
    thirty; the standing visibility for that is §11's abandonment criterion.
  - **A sink failure can never fail the run.** `emit_alert` contains sink failures (`:668`) and
    `resolve_alert_sink` degrades to a bare `LoggingAlertSink` when `BREEZY_ALERT_WEBHOOK_URL` is
    unset (`:579`), so escalation never converts a `BLOCKED` day (exit 0, day stays queued) into a
    unit failure. Pinned as **B19**.
- **Completion marker and crash recovery (N3 accepted).** The **`replay_results.jsonl` row is the
  single completion marker.** The runner never skips on the presence of `scored_trials_*.parquet`.
  On selecting a day whose output directory already holds a parquet but has **no** matching row
  (the crash window), the runner **recovers**: it reads the existing parquet, appends a row with
  `outcome="RECOVERED"` and the parquet's own sha256, and exits 0 without re-running the engine.
  If the parquet is unreadable it appends `outcome="FAILED"` with the exception type, exits
  non-zero, and the day leaves the queue — it never re-selects the same dead day nightly. The
  baseline's parquet-keyed skip is deleted; it created a permanently queued, permanently skipped day
  that burned the single daily slot forever.
- **Target selection is deterministic and auditable**, and lives in
  `scripts/analysis/replay_daily_runner.py` (not the wrapper): among SUFFICIENT days with no row
  under the full key `(station, climate_day, strategy, lag_minutes)`, choose the **oldest** climate
  day, tie-broken by station in `SUPPORTED_STATIONS` order. Oldest-first so the backlog drains
  monotonically and no station starves.
- **Timer slot — DECIDED (N4 accepted).** A **separate unit at `OnCalendar=*-*-* 15:50:00 UTC`**,
  not a sequenced step inside the exit-window study's wrapper. **Tick list re-derived from
  `deploy/systemd/*.timer` this round (round-4 b2 accepted: revision 4 carried it from an earlier
  round), enumerated per unit so it is re-checkable:** `breezy-k1-daily` 01:35,
  `breezy-offer-gate-daily` 02:05, `breezy-quote-tape-rotate` 09:00, `breezy-mb-daily` 13:30,
  `breezy-score-live-trials` 14:15, `breezy-live-tally` 14:30, `breezy-position-monitor-report`
  15:00, `breezy-exit-window-study` 15:20, `breezy-family-tally@` 17:20,
  `breezy-quote-tape-ingest` 00,06,12,18:15, plus `breezy-quote-tape-ingest-frequent`'s `*:0/15`
  stepper. The list is unchanged from the carried one; `tests/unit/test_deploy_timer_hours.py`
  forbids two timers on the same `HH:MM` tick, and **15:50 is free**. It is also outside the protected LST-union no-start window
  [16:35Z, 01:15Z) (`deploy/systemd/README.md`). **Consequences, stated as the review required:**
  (i) *memory* — a separate unit keeps its own `MemoryHigh=3G`/`MemoryMax=4G`; sequencing inside the
  exit-window wrapper would have put a replay inside a unit sized for a 10–24 GB-class study, so an
  OOM would be attributed to the wrong job and the replay's own cap would be unenforceable;
  (ii) *failure attribution* — `breezy-replay-daily.service` fails on its own, so `OnFailure=`/
  alerting names the replay rather than the exit study, and a replay failure can never mark the
  exit study failed or vice versa; (iii) *contention* — the two units share the host-wide
  `breezy-studies.lock`, so a 15:20 study still running at 15:50 makes the replay **skip** (exit 0,
  `SKIPPED -- another study holds the studies lock`) and the day stays queued and drains tomorrow.
  That is the accepted cost of separation and is recorded as such, not hidden.
- New `deploy/systemd/breezy-replay-daily.service` + `.timer`:
  - `Type=oneshot`, `WorkingDirectory=/home/jon/breezy`, `Slice=breezy-studies.slice`, `UMask=0077`,
    no `[Install]` on the service, `Persistent=true` on the timer,
    `SyslogIdentifier=breezy-replay-daily`.
  - **`MemoryHigh=3G` / `MemoryMax=4G`** — deliberately an order of magnitude below the 12G/16G the
    tape studies carry, because the measured single-day envelope is **n=1 ≈ 80 s / ~674 MB**
    (V3 plan §4 increment F, itself flagged UNVERIFIED-against-a-fresh-run). A single-day replay
    reaching 4 GB is a regression of L-31, and being OOM-killed in its own cgroup is the intended,
    loud outcome.
  - `TimeoutStartSec=1800`. No `Restart=` — a missed day is not an incident.
  - **The timer is installed and enabled only after §7 step 12 produces a non-`BLOCKED` result row**
    (round-2 change). A unit that fails identically on every tick is the "healthy unit, silently
    non-functional" shape this audit exists to close.
- Result record `~/.local/share/breezy/derived/replay/replay_results.jsonl`, append-only, one line
  per completed replay, fields: `schema_version, run_ts, station, climate_day, family_id,
  manifest_sha256, manifest_taker_fee_coefficient, engine_required_fee_coefficient, engine_params_source,
  params_match, composition_kind, strategy, lag_minutes, tape_instance_id, sufficiency_reason,
  trials, fills, fill_price_vs_decision_ask[], refusal_counts{}, wall_s, peak_rss_bytes, outcome,
  validity`. `outcome ∈ {COMPLETED, RECOVERED, BLOCKED, FAILED}`; a `BLOCKED` row carries a
  `blocked_reason` from a closed set that includes `ASOS_CACHE_EMPTY`.
- **The validity constant (round-1 minor accepted).** `validity` is written from a single named
  constant, `REPLAY_VALIDITY: Final[str] = "MECHANISM_ONLY"` in
  `src/breezy/analysis/replay_results.py`, and nowhere else. AUD-11 and AUD-12 flip **that one
  symbol** and must, in the same change, update every reader of `C-VALIDITY` (AUD-10b). Naming it
  here gives the future implementer a grep target instead of a literal scattered across a script —
  the drift shape memory `archive-table-train-serve-skew` records.

#### 6b.4 Hand-off H3 — AUD-09b → AUD-10b (REAL; stated identically in AUD-10 §6b)

| Field | Value |
|---|---|
| Artefact | `~/.local/share/breezy/derived/replay/replay_results.jsonl` |
| `schema_version` | `1` (`REPLAY_RESULTS_SCHEMA_VERSION`, `src/breezy/analysis/replay_results.py`) |
| Writer | `breezy.analysis.replay_results.append_replay_result`, called by **`scripts/analysis/replay_daily_runner.py`** — from its `COMPLETED`, `RECOVERED`, `FAILED` and `record_blocked` paths alike, so every outcome has exactly one writer (*round-3 09-4*: revision 3 named the shell wrapper) |
| Reader | `breezy.analysis.replay_results.read_replay_results`, called by `scripts/analysis/promotion_proposal.py` (AUD-10b) |
| Join key | `(station, climate_day, strategy, lag_minutes)` — the same key as the queue. `family_id` is **provenance on the row, not part of the key** (§6b.2) |
| Unknown version | `UnknownReplayResultSchemaError` — the generator **refuses**, naming path and version seen |
| Idempotency key | the join key; a duplicate key in the file is a hard error, not a last-wins |

### 6c. The eligibility sequence for a new station (identical in AUD-08 §6c and AUD-10 §6c)

Stated here so this plan's "a candidate is recorded, never queued" limit is legible as a step in a
path rather than a dead end. Steps marked **OUTSIDE** are not in this backlog:

| # | Step | Owner | In this backlog? |
|---|---|---|---|
| 1 | Venue lists an unregistered city → sighting → candidate record | automated (AUD-08) | **AUD-08** |
| 2 | One alert on first appearance, naming the ruling to open and its owner | automated (AUD-08b) | **AUD-08** |
| 3 | Ruling artefact under `docs/evidence/` + the `src/breezy/registry/sites.toml` re-verification gate | strategy lead + operator | **OUTSIDE** |
| 4 | Archive-table extension/calibration and widening `SUPPORTED_STATIONS` (the frozen corpus pin, `config.py:261-265`, means a fifth station has no measured table) | strategy lead + implementer | **OUTSIDE** |
| 5 | Capture: a WS subscription within the shared MARKET_DATA+TRADE cap | implementer, with cap evidence | **OUTSIDE** |
| 6 | The station's days become SUFFICIENT in the census and are replayed. **Additional constraint, named in round 3:** a sixth station must also be added to the hardcoded five-entry `IEM_ASOS_IDS` map (`settlement_alignment_study.py:65-71`), or `load_sites()` raises at `:646-649` — which fails **both** this item's ASOS producer **and** `count_covered_listed_station_days_from_catalog` (same `load_sites()` call, `structural_dead_stop.py:237`), i.e. AUD-08's sufficiency computation and the KILL clock | automated (**this item**), + the map edit with step 4 | **AUD-09**, only after 4 and 5 |
| 7 | A promotion proposal may name the station | automated (AUD-10b) | **AUD-10**, only after 4 |
| 8 | Arming: four separate human acts | operator + strategy lead | **OUTSIDE** |

AUD-09 owns step 6 and nothing else. Until step 4 lands, a candidate station's every census row is
`CANDIDATE_UNSUPPORTED_STATION` by design.

## 7. Ordered implementation steps (RED first)

1. **RED** `tests/unit/test_asos_cache_csv.py`: rows for the target station are written as exactly
   `station,valid,metar`; rows for other stations are excluded; a cache directory with no matching
   row exits non-zero with `ASOS_CACHE_EMPTY` **and writes no file**; zero network calls (a fake
   client asserted never constructed).
2. **GREEN** `scripts/analysis/asos_cache_csv.py`.
3. **Measure the real cache, before anything depends on it.** Run the producer by hand for
   `SFO 2026-09-01` and record the row count in the evidence doc. This is the one condition §6b.1
   names as still able to block step 12; measuring it here means the answer is known before the
   runner is built, not after. **Record either outcome** — a non-empty CSV, or `ASOS_CACHE_EMPTY`
   plus the blocker in §12.
   **MEASURED 2026-09-21 (read-only pre-check, ahead of the build): the non-empty branch holds for
   the target day.** The settlement-alignment cache
   (`~/.local/share/breezy/archive/settlement-alignment-cache`) holds ASOS rows inside the
   **2026-09-01** climate-day window for all four `SUPPORTED_STATIONS` — distinct `(station, valid)`
   rows: **SFO 313, LAX 314, MDW 312, MIA 317**. Caveats, stated rather than absorbed:
   (i) *method* — `scripts/analysis/asos_cache_csv.py` does not exist yet, so the §6b.1 predicate
   (`load_recent_asos_rows` + `climate_day_utc_bounds`) was **reproduced by anchored grep over the
   cached `.txt` files**, not executed; a boundary row at either end of the local-standard window
   may differ, so the counts are indicative of *non-emptiness*, not exact;
   (ii) *this step still runs at build time with the real producer* — the measurement de-risks it,
   it does not discharge it, and the recorded count is the producer's own;
   (iii) *census-breadth limit* — the cache is **not contiguous**: a negative control, SFO
   2026-08-20, returned **0 rows**, so an arbitrary older SUFFICIENT day may still yield
   `ASOS_CACHE_EMPTY`. That is the §9 failure case working as designed (day stays queued, B19
   escalates a persistent stall), not a new defect.
4. **RED** `tests/unit/test_replay_sufficiency.py`: two CLEAN instances each ≥30 min is
   `AMBIGUOUS_WINNER_TWO_CLEAN_GE_30MIN`, **not** first-listed; a depth-only day is SUFFICIENT; a
   quote-only day is `NO_IN_WINDOW_DEPTH`; a 29-minute depth span is `DEPTH_WINDOW_UNDER_30MIN`;
   the reason alphabet contains no bare `VENUE_NEVER_LISTED`; `InstanceSpan.verdict`'s literal
   values equal `cli_basis_offer_gate_scan.InstanceVerdict`'s (B15);
   `read_replay_sufficiency` raises `UnknownReplaySufficiencySchemaError` on `schema_version: 2`
   naming path/line/version, and a duplicate `(station, climate_day)` is a hard error (B14).
5. **GREEN** `src/breezy/analysis/replay_sufficiency.py` **plus the `pyproject.toml` layers
   amendment, both forbidden contracts (including `allow_indirect_imports = true`), and the
   `[tool.mypy] files` entry** (§6). `lint-imports` **and** `mypy src/breezy` must be green at this
   step, not at the end.
6. **RED** `tests/unit/test_replay_sufficiency_census.py`: one line per `(station, climate_day)`;
   re-running the same day is byte-idempotent; a CORRUPT-only day is `CORRUPT_ONLY` and never
   selected; zero network calls; **H1** — a register with one candidate yields one
   `CANDIDATE_UNSUPPORTED_STATION` row and zero queue entries; a register at `schema_version: 2`
   fails the census with `UnknownStationCandidateSchemaError`; a **missing** register WARNs and
   yields an empty candidate set.
7. **GREEN** the census script.
8. **RED** `tests/unit/test_replay_daily_runner.py`, driving
   **`scripts/analysis/replay_daily_runner.py`** directly (not the wrapper), with the producer and
   the driver stubbed as fake subprocesses:
   - target selection is oldest-first and skips only rows matching the **full** key
     `(station, climate_day, strategy, lag_minutes)`;
   - the same key twice is never re-replayed; **changing `lag_minutes` re-selects the day, and
     changing only `family_id` does NOT** (the restated B11 — the queue has no family dimension);
   - **crash recovery**: a parquet present with no row yields `outcome="RECOVERED"`, exit 0, no
     engine run; an unreadable parquet yields `outcome="FAILED"`, exit non-zero, and the day is out
     of the queue;
   - an empty queue exits 0 and says so; an **unreadable** `replay_sufficiency.jsonl` exits
     non-zero and does **not** report an empty queue (H0);
   - the row carries `validity=REPLAY_VALIDITY`, the manifest-read `family_id`, both fee
     coefficients, `engine_params_source="DRIVER_DEFAULTS"`, and `params_match=False` for today's
     manifest (B16);
   - a `ASOS_CACHE_EMPTY` producer failure yields `outcome="BLOCKED"`, `blocked_reason=
     "ASOS_CACHE_EMPTY"`, exit 0, the engine never started, and the day **stays queued**;
   - a driver refusal produces `outcome="BLOCKED"` with the refusal reason, never a silent
     zero-trial row;
   - **stall escalation (B19, round-4 b1)**: three consecutive `BLOCKED` rows with the identical
     `blocked_reason` emit exactly one `BREEZY_REPLAY_STALLED` payload to a recording fake
     `AlertSink`; a fourth emits none; an intervening `COMPLETED` row or a different
     `blocked_reason` resets the run; and a sink that raises leaves the exit code 0.
9. **GREEN** `scripts/analysis/replay_daily_runner.py` (selection, subprocess invocation,
   `RECOVERED`/`FAILED` branch, `record_blocked`, row append, summary line) +
   `src/breezy/analysis/replay_results.py`. The wrapper `deploy/systemd/replay-daily-run.sh` is a
   separate, later artefact (step 11) and contains no selection or parsing logic.
10. **RED** a units test in the `tests/unit/test_analysis_units_memory_capped.py` shape:
    `breezy-replay-daily.service` declares `MemoryHigh`/`MemoryMax` and `Slice=breezy-studies.slice`;
    the wrapper takes the host-wide studies lock; the wrapper does not enable POSIX mode; **every
    `"$PY"` invocation in the wrapper is one of the named scripts — the census,
    `replay_daily_runner.py`, and (once AUD-10b lands) `promotion_proposal.py` — and the wrapper
    contains no `record_blocked` and no JSONL parsing** (B18, round-4 09-5); and
    `tests/unit/test_deploy_timer_hours.py` stays green with the new 15:50 tick.
11. **GREEN** the unit files + wrapper.
12. Gate: `scripts/ci/run_tests_no_egress.sh`, `lint-imports`, `mypy src/breezy`.
13. **The one real run (L-24).** Execute the runner by hand once, in a quiet window (not
    13:30/15:00/15:20/22:30/22:45Z, not 16:35–01:15Z), against the census's own pick — expected to
    be **SFO 2026-09-01**. Record the selected instance id and **why the depth-span rule picked it**
    — the two known candidates are `3dd59abf-…` (whole-tape v2 winner) and `5a111bca-…` (09-04
    all-station instance); the census must name one by rule, never by hand. If step 3 returned
    `ASOS_CACHE_EMPTY`, this step's honest outcome is a `BLOCKED` row, and the timer stays disabled.
14. **Ratchet B5 (n2 accepted):** record this run's peak RSS and wall clock as the baseline, then
    set B5's thresholds at 2× that measurement for subsequent runs. **Only after step 13 produces a
    non-`BLOCKED` row**, install and enable the timer.

## 8. Measurable acceptance criteria and required evidence

| # | Criterion | Evidence |
|---|---|---|
| B1 | `replay_sufficiency.jsonl` classifies every `(station, climate_day)` in the tape with a reason from the closed alphabet | the file + a count by reason |
| B2 | The census reproduces the 2026-09-10 finding — for 09-01..09-10 the SUFFICIENT set is **SFO 09-01 only** — or names precisely which day now differs and why | census output diffed against memory `quote-tape-is-not-replay-sufficient` |
| B3 | The census is idempotent and network-free | two consecutive runs byte-identical; request-count assertion |
| B4 | One scheduled invocation replays exactly **one** station-day and appends exactly one result row | journal + `replay_results.jsonl` |
| B5 | Peak RSS and wall clock are **recorded on the first real run and thereafter bounded at 2× that baseline** (initial expectation < 2 GB / < 10 min, n=1) | `journalctl … -o cat \| grep -aoE '[0-9.]+[MG] memory peak'` + the row's `peak_rss_bytes` |
| B6 | The unit never runs concurrently with `k1`/`mb`/`offer-gate`/`exit-window` | a contention run showing `SKIPPED -- another study holds the studies lock`, exit 0 |
| B7 | Every result row carries `validity=REPLAY_VALIDITY` (`"MECHANISM_ONLY"`) while AUD-11/AUD-12 are open, and the literal appears in exactly one source file | schema assertion + `grep -rn 'MECHANISM_ONLY' src/ scripts/ deploy/` showing one definition site |
| B8 | Zero paper rows reach the live tally | `test_paper_rows_never_pool_into_the_live_tally` unmodified and green; `assert_paper_only` untouched |
| B9 | SP-4's Increment F obligation is discharged **in one of two explicitly-defined ways**: the SFO 2026-09-01 v3 replay has a `COMPLETED` result row, **or** it has a `BLOCKED` row whose `blocked_reason` is recorded in §12 as an open blocker with an owner. Any third shape fails acceptance. *Round-2: revision 2 asserted only the first, while presenting an invocation that could not run.* | the result row from step 13 |
| B10 | **`lint-imports` is green with `breezy.analysis` present**, under the amended layers list and both new forbidden contracts | command output; identical criterion to AUD-10 C10 |
| B11 | The queue key has **no family dimension**: changing `lag_minutes` or `strategy` re-selects a day; changing only the manifest's `family_id` does not, and the plan records why (§6b.2) | step 8 RED→GREEN |
| B12 | Crash recovery: parquet-without-row yields `RECOVERED`, and no day can be permanently queued-and-skipped | step 8 RED→GREEN |
| B13 | H1 is exercised: a candidate register produces `CANDIDATE_UNSUPPORTED_STATION` rows, zero queue entries, and an unknown `schema_version` fails the census | step 6 RED→GREEN |
| B14 | **H0 is a real contract:** `read_replay_sufficiency` refuses an unknown `schema_version` with path/line/version and refuses a duplicate `(station, climate_day)`; an unreadable census file makes the runner exit non-zero rather than report an empty queue | step 4 + step 8 RED→GREEN |
| B15 | `InstanceSpan.verdict`'s literal set equals `cli_basis_offer_gate_scan.InstanceVerdict`'s, asserted in a test so the two cannot drift | step 4 assertion |
| B16 | **Every result row records the engine's real parameters beside the family's registered ones** — `engine_required_fee_coefficient`, `manifest_taker_fee_coefficient`, `engine_params_source`, `params_match` — and on today's tree `params_match` is `False` (`0.06` vs `0.0695`) | step 8 RED→GREEN + the row from step 13 |
| B17 | **The runner's literal argument vector executes.** Every `required=True` argument of `current_rung_hold_paper_replay.py`'s parser appears in the vector **`scripts/analysis/replay_daily_runner.py` builds**, asserted by a test that introspects the driver's own `required=True` set and compares it against the module's vector-builder (*round-3 09-4*: revision 3 parsed the shell wrapper, which no longer builds the vector) | a test over `replay_daily_runner.py` + `argparse` introspection |
| B18 | **The wrapper/module split holds, asserted as a PROPERTY over a named script set rather than as a count (round-4 09-5).** Every decision the plan specifies — H0 read, target selection under the full key, `RECOVERED`/`FAILED`, `record_blocked`, row append — is exercised by `tests/unit/test_replay_daily_runner.py` against `scripts/analysis/replay_daily_runner.py`; and **every `"$PY"` invocation in `deploy/systemd/replay-daily-run.sh` is one of the named scripts — `scripts/analysis/replay_sufficiency_census.py`, `scripts/analysis/replay_daily_runner.py`, and, once AUD-10b lands, `scripts/analysis/promotion_proposal.py` — and the wrapper contains no JSONL parsing and no `record_blocked`.** The assertion is over the *set* of invoked script paths, so AUD-10b's sanctioned third invocation is expected rather than a failure, while an unnamed fourth still fails. Identical property asserted from AUD-10's side by **C19** | step 8 + step 10 RED→GREEN; a grep-shaped assertion collecting the wrapper's invoked script paths and comparing the set against the named three |

| B19 | **A persistent stall escalates exactly once (round-4 b1).** Three consecutive `BLOCKED` rows carrying the identical `blocked_reason` emit **exactly ONE** `BREEZY_REPLAY_STALLED` alert through `resolve_alert_sink`/`emit_alert`, whose `detail` names the `blocked_reason` and the act it implies and contains no absolute path; a fourth consecutive identical row emits none; a `COMPLETED`/`RECOVERED`/`FAILED` row or a different `blocked_reason` resets the run so the next three re-arm it; and a raising sink leaves the run's exit code at 0 with the day still queued | step 8 RED→GREEN against a recording fake `AlertSink` |
| B20 | **Every result row is family-scoped by the RULED discriminator (Q1 RULING items 3-4).** The row carries `family_id` from the loaded manifest **and** `manifest_sha256`, and a test asserts `manifest_sha256` equals `load_family_manifest(<armed manifest>).manifest_sha256` (`persistence/family_manifest.py:185`, computed `:220`); no selector in this item's code discriminates on `trial_id_prefix`, which is proven non-unique (`pm_us_crh_cont` and `pm_us_crh_v4` share it) | step 8 RED→GREEN + the row from step 13 |

**Evidence artefact:** `docs/evidence/SCHEDULED_REPLAY_<date>.md` carrying B1–B20, headed with the
verbatim look-ahead caveat already mandated for every replay report
(`WHOLE_TAPE_PAPER_REPLAY_2026-09-05.md`, "Look-ahead caveat"): settlement joins the highest
`revision_seq` FINAL CLI record, unpublished at decision time — **MECHANISM TEST — NO VERDICT**.
**Second mandatory caveat line (RULING
`docs/evidence/RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21.md` Q1 RULING
item 8):** *the underlying parquet `trial_id` is NOT family-scoped yet* — it is still
`paper_replay/current_rung_hold/trial/<station>/<climate_day>`
(`src/breezy/runtime/paper_replay.py:92,347`), a shape two REGISTERED families would share. The
`replay_results.jsonl` row is family-scoped (`family_id` + `manifest_sha256`), the parquet rows are
not; no reader may cross families on the parquet's `trial_id`. The fix lives in
`runtime/paper_replay.py` and `live_family_tally.py`, **outside this item** (§12).

## 9. Validation: failure cases, integration, autonomous operation

- **`ASOS_CACHE_EMPTY` (round-2 change — the most likely first outcome).** The producer finds no
  cached observation row inside the target climate day's window. The runner records a `BLOCKED` row
  with `blocked_reason="ASOS_CACHE_EMPTY"`, exits 0, **never starts the engine**, and the day stays
  queued so it drains once the cache covers it. This is enumerated here precisely because round 2
  found it was the most likely real outcome and was absent from revision 2's failure list.
- **A *persistently* `BLOCKED` schedule (round-4 b1).** One `BLOCKED` row is a data verdict; three
  consecutive rows under the same `blocked_reason` mean the schedule has stopped meeting its
  purpose while the unit still reads green. The runner emits exactly one `BREEZY_REPLAY_STALLED`
  alert through the shipped `resolve_alert_sink`/`emit_alert` path at that point (§6b.3), which is
  the *only* escalation this item does not inherit from unit state. Exit code, queue state and the
  day's position are unchanged by the alert; a raising sink cannot fail the run. **B19.**
- **Unreadable or unknown-version `replay_sufficiency.jsonl`.** Exit non-zero naming path, line and
  version. Never an empty-queue report: "no work" and "unreadable work list" must not look alike.
- **Empty queue**: exit 0 with an explicit `QUEUE EMPTY -- n SUFFICIENT days, all replayed under
  key (station, climate_day, strategy, lag)` line. Never a silent no-op.
- **Every day INSUFFICIENT**: exit 0 with the reason histogram. The expected state for most of the
  tape; it must read as a data verdict, not a job failure.
- **Crash between the parquet write and the row append**: the next run recovers (`RECOVERED`) or
  fails loudly; the day never stays permanently queued-and-skipped.
- **Driver raises** `NoDecisionWindowCoverageError` / `EntryAskFromLatchMissingError` /
  `ImpossibleFillPriceError` (L-25): row written with `outcome="FAILED"` + exception type; the unit
  exits non-zero. `ImpossibleFillPriceError` must never be swallowed — a fill better than the
  displayed ask is a defect signature, not price improvement.
- **Duplicate key in `replay_results.jsonl`**: a hard error on read, never last-wins. A duplicate
  means two writers raced and the counts are untrustworthy.
- **Parameter divergence** (`params_match=False`): **not** a failure — it is the expected state and
  is recorded, not refused. The containment is downstream: AUD-10's `C-VALIDITY` refuses such a row
  as an edge input (§6b.2 item 4). Refusing to *run* on divergence would leave the mechanism
  unmeasured for no gain.
- **OOM**: killed in its own 4 GB cgroup, unit fails, node untouched. Memory
  `nightly-studies-run-at-10-24gb` — stop the study, never the node — is respected by construction:
  this unit never signals the node, the supervisor, or the recorder.
- **Concurrency.** The host-wide flock is skip-not-kill (exit 0) precisely so `Persistent=true` does
  not retrigger and no sibling `OnFailure=` fires on a healthy skip. With the 15:50 slot, the most
  likely skip source is a long-running 15:20 exit-window study; the day stays queued (§6b.3).
- **B2 disagreeing (n1 accepted).** If B2 finds a different SUFFICIENT set, two things move and both
  are recorded rather than silently absorbed: the queue-size estimate in §11, and the 30-day
  abandonment criterion's threshold. A *larger* set comfortably satisfies it; a *smaller* one means
  the binding constraint is capture, and the item is re-opened as a capture problem immediately
  rather than after 30 days.
- **Integration with AUD-10.** H3 is the contract: versioned, named reader, refuse-on-unknown, plus
  the `params_match` field `C-VALIDITY` now reads.
- **Integration with the live path: none.** The runner mints no `OrderSubmissionPermit` (V3 plan's
  L-1 verdict #3: `issue()` requires a genuine `LiveTradingPermit`, both operator caps and
  `live_observations`; `@final` + `_SEAL` refuse forgery; the B11 AST pin scans the single literal
  call site). The replay reaches `SimulatedExchange`, never `PolymarketUSExecutionClient`, and the
  exec client's own independent deny (`adapters/polymarket_us/exec/client.py:2665`,
  `PERMIT_ABSENT_REASON`) is unreachable from a strategy-side override. The producer of §6b.1
  touches no venue and no network at all.
- **Autonomous operation.** Daily timer with `Persistent=true`; queue drains oldest-first; a missed
  day self-heals; failures land in the unit's failed state — **AUD-09b inherits G-14's weakness for
  the *failed-unit* path and does not pretend otherwise**: a failing timer is only as good as the
  alerting over it (shipped `f97c26f`). The one failure mode that unit state can **never** express
  — a healthy unit producing `BLOCKED` rows forever — is no longer silent: it escalates on its own
  through the same shipped sink after three identical consecutive rows (§6b.3, B19, round-4 b1).

## 10. Deployment, observability, rollback

- **Deploy:** scripts merge inert. The timer is installed and enabled **only after** step 13's real
  run produces a non-`BLOCKED` row. `systemctl --user show breezy-studies.slice -p MemoryHigh
  -p MemoryMax` returning non-`infinity` is the real observable that the slice exists
  (`daemon-reload` alone does not create it).
- **Observability:** `$OUT/replay_daily.log` + journal + the three JSONL artefacts. The daily line
  is emitted by `scripts/analysis/replay_daily_runner.py` on stdout and tee'd by the wrapper's
  `say()`, so its format is unit-testable; it always states: days SUFFICIENT, days replayed to date
  under the full key, day picked (or QUEUE EMPTY), ASOS row count, outcome (with `blocked_reason`
  when BLOCKED), `params_match`, wall, peak RSS. **Plus one push observable (round-4 b1):** a
  `BREEZY_REPLAY_STALLED` alert on the third consecutive identical `blocked_reason`, through the
  already-shipped sink — the only observable in this item that does not require someone to read a
  log or a unit state.
- **Rollback:** `systemctl --user disable --now breezy-replay-daily.timer`. All three JSONL
  artefacts are derived and consumed by nothing that trades. Reverting the `pyproject.toml` layers
  amendment is safe only together with removing `src/breezy/analysis/` and its `[tool.mypy] files`
  entry — the three are one change.

## 11. Relationship to portfolio-level ROI

**Demonstrated: none, and this plan must not be read as producing any.** Until AUD-11 (look-ahead)
and AUD-12 (costs) land, a result row is a **mechanism** claim — take-rate, fill-vs-book, refusal
distribution — never an edge claim. Round 3 adds a second, independent reason the rows are not edge
evidence: on today's tree the engine runs with a fee coefficient the armed family does not register
(`params_match=False`, §6b.2), so even a look-ahead-free row would describe a family nobody is
trading. The programme's standing record is that **no family has a proven edge** and admissible
n = 0 (PROGRESS.md:32), and the forecast-taker edge is CLOSED as terminal
(`RULING_forecast_edge_programme_closes_2026-09-20.md`).

**Plausible ROI benefit, stated as plausible:** a nightly machine-readable replay is the only way a
promotion proposal (AUD-10) can ever be evidenced without a human running a study by hand, and the
only mechanism by which the *cost of being wrong* about a station is paid in compute rather than in
live fills.

**How it will be evaluated.** Two mechanical numbers: (1) SUFFICIENT station-days the census finds
per week — if ~0 on an ongoing basis, the binding constraint is capture, not replay, and the idle
schedule is itself the finding; (2) result rows AUD-10 consumes. **Abandonment criterion:** if after
30 days the census reports fewer than 3 SUFFICIENT days total, disable the timer and re-open the
item as a capture problem — subject to the B2 adjustment in §9.

## 12. Assumptions, unresolved questions, blockers

- **Assumption (explicit, the single biggest risk):** the 2026-09-10 sufficiency picture still holds.
  Measured over 09-01..09-10, before the per-file ingest fix and before ING-1. B2 tests it; §9
  states what moves if it disagrees.
- **Assumption:** the V3 envelope (n=1 ≈ 80 s / ~674 MB) is representative. Explicitly
  UNVERIFIED-against-a-fresh-run in its own plan. B5 measures it and **ratchets** off the first real
  run; the 4 GB cap contains it.
- **No decision is left to the implementer.** Round 1 flagged two (layer position, timer slot);
  round 2 flagged three more (the forbidden contract, the family dimension, the census artefact's
  version discipline) plus the missing driver argument. All are now decided in-plan: §6 (contract,
  with the option not taken and the reason), §6a (H0), §6b.1 (producer), §6b.2 (armed family only).
- **BLOCKER — build, newly carried forward from SP-4 (round-2 MATERIAL):** whether the
  settlement-alignment cache actually holds ASOS rows for the target climate day. The producer
  exists (§6b.1) and is cache-only by design; `asos_recent_refresh.py`'s
  `DEFAULT_LOOKBACK_DAYS = 3` (`:91`) means an old day is covered only by what earlier incidental
  fetches left on disk (`load_recent_asos_rows`'s own docstring calls this a hard dependency,
  BL-24). **Measured at §7 step 3, before the runner is built — and pre-measured read-only on
  2026-09-21: the 2026-09-01 window is NON-EMPTY for all four stations (SFO 313 / LAX 314 / MDW 312
  / MIA 317 distinct `(station, valid)` rows), by an anchored-grep reproduction of the §6b.1
  predicate, the real producer not existing yet. The blocker is therefore *de-risked for the
  expected first target, not discharged*: step 3 still re-runs it with the producer, the counts may
  differ by a boundary row, and the cache is NOT contiguous (negative control SFO 2026-08-20 =
  0 rows), so an older queued day can still block.** If it returns `ASOS_CACHE_EMPTY`,
  the honest outcomes are: B9 discharges as a `BLOCKED` row, the timer stays disabled (§6b.3), and
  the remaining options — widening `asos_recent_refresh.py --since` (a network fetch, owned by
  whoever owns that script) or replaying a *recent* day instead of 09-01 — are named here rather
  than assumed away. **Owner:** the AUD-09b implementer; escalates to whoever owns
  `asos_recent_refresh.py` only if a wider fetch is needed.
- **OWNED ELSEWHERE — no longer an unowned blocker (RULED, Q4 item 1):** a challenger family cannot
  be replayed until `current_rung_hold_paper_replay.py` grows a `--family-manifest` flag threading at
  least `required_fee_coefficient` into the config built at `:932`. Excluded from this item's scope
  (§5); AUD-10's `C-PAIRED` is recorded INERT against it. **Owner: AUD-19** — a new sibling backlog
  item created by RULING
  `docs/evidence/RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21.md` (Q4 RULING
  item 1; peer-ENDORSED, `docs/evidence/reviews/RULING_citability_review_2026-09-21.md`), cited here
  **by id only**. AUD-19 is itself gated on the Q1 `trial_id` fix below landing first.
- **RULED (was the R1 strategy-lead blocker) — paper/replay `trial_id` provenance.** RULING
  `docs/evidence/RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21.md` Q1
  (Revision 2, peer-ENDORSED). The discriminator is the manifest's **`family_id`**, never
  `trial_id_prefix` — the latter is *proven* non-unique: `pm_us_crh_cont` and `pm_us_crh_v4` are both
  `REGISTERED` and share `"continuous_rung_hold/trial/"` byte-for-byte. Required id shape:
  `f"paper_replay/{manifest.family_id}/{manifest.trial_id_prefix}{station}/{climate_day}"`, with
  `manifest_sha256` recorded alongside as a **secondary** integrity check (Q1 items 3-4 — this half
  IS in AUD-09b's scope and is carried on the result row, §6b.2 item 3, §6b.3, **B20**). A replay row
  never shares id space with a live trial; that barrier is untouched (Q1 item 1).
  **Residual, honestly stated:** today `trial_id` is built at `src/breezy/runtime/paper_replay.py:347`
  from `PAPER_TRIAL_ID_PREFIX` (`:92`) with **no family component**, and the paired paper-namespace
  check is `live_family_tally.py`'s restated `_PAPER_TRIAL_ID_PREFIX` (`:91`); both call sites must
  move together with a test pinning them equal (Q1 item 6). Q1 item 7 places that fix **outside
  AUD-09 as drafted** (§5 excludes the driver; the fix lives one layer down in
  `runtime/paper_replay.py` + `live_family_tally.py`, which this item also does not touch) and the
  ruling assigns it to **no existing item**. **Coordinator decision 2026-09-21: owned by AUD-19 as its
  first increment (AUD-19a), which gates AUD-19's flag increment (AUD-19b)** — the flag is the change
  that would make the collision live, so the fix ships in the same item, first. AUD-09b may build and run meanwhile (Q1 item 8: containment via `C-VALIDITY`/
  `C-PAIRED` holds), provided §8's second caveat line ships with every evidence artefact.
  **Resolved: AUD-19a owns the Q1 `trial_id` fix (cited by ID only).**
  The same excluded path carries Q1 item 4's SECOND half: the parquet's own metadata gains
  `family_id` + `manifest_sha256` — also AUD-19a's, not this item's (this item takes the JSONL-row half, B20).
- **RULED (was a strategy-lead blocker) — MECHANISM_ONLY citability.** RULING
  `docs/evidence/RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21.md` Q2
  (ENDORSE, unchanged from revision 1) **confirms this plan's default and extends it**: *no* — and
  **never**, permanently — for PREREG v3 §9, whose `covered_listed_station_days` stays defined over
  live venue coverage only, so no replay-derived artefact of **any** validity tag may feed,
  substitute into, or corroborate it (overturned only by a separate PREREG ruling); and *no, pending
  AUD-11/AUD-12*, for any promotion criterion requiring an edge statistic — `C-VALIDITY` stands
  unmodified, and once `validity` flips off `MECHANISM_ONLY` a `params_match == true` row **may**
  feed `C-ESTIMATOR`/`C-N`/`C-PAIRED`. No text change is required to PREREG v3 itself.
- **CONSTRAINT on a sixth station (round-3 b3, no effect today):** the ASOS producer resolves
  `iem_asos_id` through `settlement_alignment_study.load_sites()` (`:638-658`), which reads the
  hardcoded five-entry `IEM_ASOS_IDS` (`:65-71`: `KNYC/KSFO/KMIA/KMDW/KLAX`) and raises
  `RuntimeError(f"no explicit IEM ASOS mapping for {site.icao}")` at `:646-649` otherwise. The
  moment §6c step 3 adds a sixth site to `src/breezy/registry/sites.toml`, **both** this producer
  **and** `count_covered_listed_station_days_from_catalog` (which calls the same `load_sites()` at
  `structural_dead_stop.py:237`, and which AUD-08's sufficiency mapping depends on) fail hard. No
  effect today — every AUD-08b *candidate* is unregistered and the one *seed* is one of the five —
  but the census's "covers the AUD-08b candidate cities" framing must not be read as implying
  otherwise. **Owner:** whoever executes §6c step 4; the map edit belongs with the registry edit,
  not here. Named in §6c step 6.
- **Not assumed:** that a SUFFICIENT day produces a fill. Zero trials is a valid, recorded mechanism
  result.

## 13. Review history

**Baseline self-score (2026-09-21, author):** 83/100.

### Round 1

- **trading-bot-architect (scheduling/pipeline/host-resource lens): 85/100 · NOT READY**
- **code-architect (module boundaries, data contracts, layering): 75/100 · NOT READY**

| Defect | Reviewer | Disposition |
|---|---|---|
| **MATERIAL N1** — `breezy.analysis` breaks the `exhaustive = true` layers contract | ca | **ACCEPTED.** New `analysis` layer between `app` and `strategy`, literal `layers` list and two `forbidden` contracts quoted, **B10** added. (Round 2 found the second contract still unable to pass — see 09-1.) |
| **MATERIAL N2** — dedup key `(station, climate_day)` blocks re-replay for a new family/lag | ca | **ACCEPTED in round 1; PARTIALLY WITHDRAWN in round 3** — see 09-2 below. The lag/strategy dimensions are kept; the family dimension is removed because nothing can vary it. |
| **MATERIAL N3** — parquet-keyed crash-safe skip creates a permanent silent stall | ca | **ACCEPTED.** JSONL row is the single completion marker; `RECOVERED`/`FAILED`; **B12**. Round 2 called this "the strongest repair in the revision" and it is unchanged here. |
| **MATERIAL N4** — timer slot left to the implementer | ca | **ACCEPTED.** 15:50:00 UTC, separate unit, with memory/attribution/contention consequences stated. Independently re-verified by both round-2 reviewers. |
| **MINOR n1–n4** | ca | **ACCEPTED**, all four; re-verified present by both round-2 reviewers. |
| **MINOR** — no durable name for the constant AUD-11/AUD-12 must flip | tba | **ACCEPTED.** `REPLAY_VALIDITY`, single definition site, pinned by **B7**. |

### Round 2

- **trading-bot-architect (scheduling/pipeline/host-resource lens): 73/100 · NOT READY**
- **architect (code-architect lens): 81/100 · NOT READY**

Both reviewers verified every round-1 disposition against the body and found each fix real (the
layers text, the 5-tuple key as text, the completion-marker repair, the timer tick list, all four
minors). Round 3 leaves that text alone except where a round-2 defect requires otherwise.

| Defect | Reviewer | Disposition |
|---|---|---|
| **MATERIAL 09-1 / 10-1** — the "analysis never imports Nautilus" forbidden contract cannot pass: `allow_indirect_imports` defaults to `False`, and `analysis` may import `strategy`, whose `config.py:59-60` imports Nautilus and holds `SUPPORTED_STATIONS` at `:76` | architect (both plans) | **ACCEPTED.** Verified independently at `.venv/.../importlinter/contracts/forbidden.py:72` (`fields.BooleanField(required=False, default=False)`) and `:131-143` (the false branch takes `find_shortest_chains`), and at `config.py:59-60,76`. **Decided once, identically in AUD-09 §6 and AUD-10 §6: add `allow_indirect_imports = true` with the rationale the `.com` contract already records (pyproject.toml:116-121).** The alternative — re-sourcing `SUPPORTED_STATIONS` — is **rejected with evidence**: it means editing a live strategy module with 8 in-repo callers of that symbol to satisfy a lint property, it inverts the principle the repo's own `.com` comment states, and it collides with AUD-10a, which *removes* that import from `composition.py` in this same backlog. The residual (an indirect reach still passes) is named in §6 rather than glossed. The `[tool.mypy] files` entry for the new package is added in the same breath, since `strict = true` (`:158`) would otherwise not cover it. |
| **MATERIAL (tba) / b1 (architect)** — the runner's literal command omits `--asos-cache-csv` (`required=True`, `:1082`), and the plan silently drops SP-4's own still-open "no producer exists … a missing file makes F unrunnable" blocker | both | **ACCEPTED IN FULL, and carried forward by building the producer rather than only naming it.** Verified in round 3: `required=True` at `:1082`, `read_asos_rows` at `:471-474`, consumed at `:1176`; no producer anywhere in the repo; `asos_recent_refresh.py` writes a *different*, URL-keyed `.txt` cache. **§6b.1 scopes a producer into AUD-09b** — `scripts/analysis/asos_cache_csv.py`, cache-only and zero-network, composed entirely from existing pieces (`load_sites`, `settlement_alignment_study.py:638-659`; `load_recent_asos_rows`, `cli_basis_offer_gate_scan.py:495-536`; `parse_asos_rows`, `:634-635`) — with its own RED tests (§7 step 1) and criterion **B17**. The **command block is now complete and runnable as written** (§6b.3). The residual the producer cannot remove — whether the cache actually covers an old climate day, given `DEFAULT_LOOKBACK_DAYS = 3` — is **measured at §7 step 3 before the runner is built**, kept as a named blocker with an owner in §12, gated: the timer is enabled only after a non-`BLOCKED` row, `ASOS_CACHE_EMPTY` is an enumerated §9 failure case, and **B9 is restated with a two-way pass condition** as the reviewer's second point required. |
| **MATERIAL 09-2 / 10-3** — `family_id` is in the queue key and on every row, but the driver takes no family/manifest/fee argument, `<id>` is unbound, the key degenerates, and B11 can only pass synthetically | architect | **ACCEPTED IN FULL.** Re-verified at the construction site: `cfg = CurrentRungHoldConfig(instrument_ids=..., stations=(station,))` (`:932`) with `required_fee_coefficient` defaulting to `Decimal("0.06")` (`config.py:226`), against `pm_us_crh_v4.json`'s registered `"0.0695"`. **Decision: armed family only** (§6b.2) — the reviewer's own second option, taken because the first requires a driver change this item excludes. `<id>` is bound to `settings.sending_family_id`; `family_id` becomes **provenance, not a queue-key dimension**; the key drops to `(station, climate_day, strategy, lag_minutes)`; **round 1's N2 fix is explicitly partially withdrawn and B11 restated** rather than left as a criterion nothing could satisfy. The divergence is not merely conceded — it is **recorded in the artefact** (`engine_required_fee_coefficient`, `manifest_taker_fee_coefficient`, `engine_params_source`, `params_match`, criterion **B16**) and **contained downstream**: AUD-10's `C-VALIDITY` refuses any `params_match=False` row as an edge input. AUD-10's `C-PAIRED` is recorded **INERT** with the `--family-manifest` flag named as its single blocking change, with an owner, in both plans' §12. |
| **MATERIAL 09-3** — `replay_sufficiency.jsonl` crosses a process and merge boundary with none of the seven-row discipline H1/H3 carry | architect | **ACCEPTED.** Hand-off **H0** added to §6a with all seven rows — module, `REPLAY_SUFFICIENCY_SCHEMA_VERSION`, `write_/read_replay_sufficiency`, record key `(station, climate_day)`, duplicate-key hard error, `UnknownReplaySufficiencySchemaError` with path/line/version, atomic whole-file rewrite — plus the rule the reviewer's concern actually turns on: an unreadable work list **must not** look like an empty queue. Criterion **B14**; tests at §7 steps 4 and 8. |
| **MINOR b2** — `classify_station_day`'s span input is prose, not a signature | architect | **ACCEPTED.** §6a now gives the literal signature and the `InstanceSpan` dataclass, with its `verdict` field's alphabet traced to `cli_basis_offer_gate_scan.InstanceVerdict` (`:247`), produced by `classify_instance` (`:391-410`) from a `PreflightReport` (`feather_preflight.py:168-205`) returned by `scan_instance` (`:501-531`) — all read this round. The alphabet is declared locally (the script is unimportable from `src/`) and **B15** pins the two equal so they cannot drift. |
| **MINOR (tba)** — B9's discharge condition is optimistic given the above | tba | **ACCEPTED.** B9 now defines a pass condition for both outcomes and fails any third shape. |

**Rejections:** one, evidenced — the 09-1 remedy "re-source `SUPPORTED_STATIONS` from a
Nautilus-free module" is rejected in favour of the flag, for the three reasons recorded in §6. The
reviewers offered both and asked for a justified choice; this is it. Everything else in round 2 is
accepted. One round-1 acceptance (N2's family dimension) is **partially withdrawn**, in the open,
because round 2 proved it inoperative.

**Revision 3 self-score (2026-09-21, author, conservative):**

| Criterion | Max | Score | Remaining weakness |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 17 | "Scheduled" and "machine-readable" are both covered, SP-4 is folded **with its blocker** rather than around it, and §6c states what this item does not own. Residual: `run_weather_strategy_backtests.py` is still untouched (deferred to AUD-11), and the family dimension the promotion loop eventually needs is named and deferred, not delivered. |
| Technical correctness and evidence grounding | 20 | 16 | Both round-2 verified errors are fixed against re-read source (import-linter's default and branch; the driver's parser, `read_asos_rows`, and the `:932` config construction; the 0.06 vs 0.0695 divergence). Residual: the cache-coverage question is measured at step 3 rather than known now, and the timer-tick list and `structural_dead_stop` citations are carried from earlier rounds rather than re-read this round. |
| Implementation specificity and feasibility | 15 | 12 | The command block is complete and testable (B17), `<id>` is bound, the producer is composed from named existing functions, and `classify_station_day` has a signature. Residual: `record_blocked` in the wrapper sketch is named by behaviour rather than given as shell, and the producer's climate-day window boundary is specified by intent ("inside the target climate day's window") rather than by reusing a named helper. |
| Acceptance criteria and validation quality | 20 | 16 | B1–B17 objective; B9 is two-way; B14/B16/B17 cover the three round-2 material gaps; B11 is restated to something achievable. Residual: B2 remains the only falsification test of the sufficiency picture, and B16's expected `False` makes the first real row informative about mechanism only. |
| Autonomous operation, failure handling, recovery | 15 | 12 | `ASOS_CACHE_EMPTY` is a first-class enumerated outcome that keeps the day queued; unreadable-work-list is distinguished from empty-queue; crash recovery, duplicate-key, skip-not-kill, OOM all stand. Residual: still inherits G-14's alerting dependency, and a persistently empty ASOS cache yields a quiet nightly `BLOCKED` row with no escalation of its own. |
| Portfolio objective alignment, scope and dependencies | 10 | 9 | Mechanism-vs-edge separation now has two independent grounds; the deferred driver change is named with an owner rather than assumed; abandonment criterion and the PREREG barrier unchanged. |
| **Total** | **100** | **82** | |

### Round 3

- **trading-bot-architect (scheduling/pipeline/host-resource lens): 100/100 · READY**
- **architect (code-architect lens): 85/100 · NOT READY**

**Readiness is the LOWER of the two: 85.** The 100 is recorded but not relied on: it found none of
the four defects below, including a structural one — two inter-stage contracts naming a shell script
as the caller of a Python function — that the architect verified and I re-verified.

Both reviewers confirmed every round-2 fix is real and sound (the `allow_indirect_imports = true`
contract and its literal semantics, the armed-family decision with `<id>` bound at `:932`, H0's
seven rows, the complete `required=True` command block plus the ASOS producer, and
`classify_station_day`'s signature). The round-3 reviewer additionally checked the new producer's
placement (`root_packages = ["breezy", "nautilus_trader"]`, pyproject.toml:68, so `scripts/` is
outside every import-linter contract) and found no layer violation. Revision 4 therefore changes
only the passages below.

| Defect | Reviewer | Disposition |
|---|---|---|
| **MATERIAL 09-4** — the runner has no named module; H0's Reader and H3's Writer name `deploy/systemd/replay-daily-run.sh` as the caller of Python functions; `record_blocked` is an undefined shell helper; and B17 parses the wrapper, so nothing covers target selection, the `RECOVERED`/`FAILED` branch, the duplicate-key error or the row append | architect | **ACCEPTED IN FULL — the reviewer is right that this is structural, not cosmetic.** §6b.3 now opens with the module and an explicit **responsibility table**: **`scripts/analysis/replay_daily_runner.py`** owns the H0 read (with B14's refusals, which are unreachable from shell), target selection under the full key `(station, climate_day, strategy, lag_minutes)`, both subprocess invocations (`subprocess.run`, no `shell=True`), the `RECOVERED`/`FAILED` crash branch, **`record_blocked(reason)` as a function**, the `append_replay_result` row append with its duplicate-key hard error, and the daily summary line; **`deploy/systemd/replay-daily-run.sh`** keeps only `flock`/`say()`/environment resolution and **two** `"$PY"` invocations (census, then runner module), makes no selection decision and parses no artefact. **H0's Reader row and H3's Writer row are corrected** to name the module — H3's additionally states that all four outcome paths (`COMPLETED`/`RECOVERED`/`FAILED`/`record_blocked`) share the one writer. **B17 is restated** against the module's argument-vector builder rather than the wrapper's shell text, and a **new B18** asserts the split from both sides: the module's decisions are exercised by `tests/unit/test_replay_daily_runner.py`, and the wrapper contains no JSONL parsing, no `record_blocked`, and exactly two `"$PY"` invocations. §7 steps 8–10 restated to target the module. The shell block in §6b.3 is retained for readability with a comment stating the module issues both invocations. |
| **MINOR b1** — the producer's output set (every cached row for the station) and its emptiness predicate (rows inside the climate-day window) are two different sets, and no window helper is named | architect | **ACCEPTED, and closed by making them the same set.** §6b.1 now states `--out` **is** windowed and names one helper, `climate_day_utc_bounds(*, station, climate_day) -> tuple[int, int]`, composed from `default_registry().climate_day_window(...).std_utc_offset_hours` (`src/breezy/registry/sites.py:403-414`; `ClimateDayWindow:135-148`, whose docstring pins the never-DST-aware local-standard midnight-to-midnight rule) and `breezy.normalize.climate_day.standard_time_zone` — the identical pair `structural_dead_stop._afternoon_window_ns` composes at `:148-155`. The bound is **midnight-to-midnight, not** `AFTERNOON_WINDOW_START/END` (`ma_prelock_winner_ask_study.py:149-150`), with the reason read at source: those bound the *decision* window, whereas `load_replay_observations` (`src/breezy/runtime/paper_replay.py:181-206`) consumes observations across the whole replayed day at `received_at_ns = observed_at_ns + lag_minutes`. If the driver is ever shown to need pre-midnight rows, widening is a one-line change to that one helper — which is the point of naming it. |
| **MINOR b2** — the mypy-entry justification is false: `[tool.mypy] files` also omits `src/breezy/app` and `src/breezy/features` | architect | **ACCEPTED.** Verified this round by re-reading `pyproject.toml:159-189`: the list is `adapters, normalize, registry, settlement, domain, ingest, persistence, runtime, strategy` plus `scripts/venue`, `scripts/analysis`, `scripts/archive`, `tests` — and both `src/breezy/app` and `src/breezy/features` exist on disk and are absent. The **change stands**; the **claim is replaced** with the narrower true reason (the analysis cores hold the H0/H3 contract signatures AUD-10b reads, so they are checked at the same strictness as the `persistence` loaders beside them). The two unchecked packages are pre-existing and explicitly not in this item's scope. |
| **MINOR b3** — the producer inherits the hardcoded five-entry `IEM_ASOS_IDS`, which bounds the portability claim | architect | **ACCEPTED, and recorded in three places rather than one.** Verified: `IEM_ASOS_IDS` at `settlement_alignment_study.py:65-71` holds exactly `KNYC/KSFO/KMIA/KMDW/KLAX`, and `load_sites` raises `RuntimeError(f"no explicit IEM ASOS mapping for {site.icao}")` at `:646-649`. §6b.1 names the bound at the resolution site, §12 carries it as a named constraint with an owner (whoever executes §6c step 4, since the map edit belongs with the registry edit), and **§6c step 6** states the consequence the reviewer identified plus one he did not: the same `load_sites()` is called by `count_covered_listed_station_days_from_catalog` (`structural_dead_stop.py:237`), so a sixth site breaks **AUD-08's sufficiency computation and the KILL clock**, not only this producer. No effect today — every AUD-08b candidate is unregistered and the one seed is one of the five. |
| **TRIVIAL (carried)** — `load_sites` is `:638-658`, not `:638-659` | architect | **ACCEPTED.** Re-read: `def` at `:638`, `return tuple(sites)` at `:658`. Corrected in §6b.1. (The round-2 disposition text in this section is left verbatim as the historical record it is.) |

Also corrected for cross-plan consistency with AUD-08 revision 4: §6c step 3 now cites
`src/breezy/registry/sites.toml` rather than `registry/sites.toml`.

**Rejections:** none in round 3.

**Revision 4 self-score (2026-09-21, author, conservative):**

| Criterion | Max | Score | Remaining weakness |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 17 | Unchanged and not claimed higher. "Scheduled" and "machine-readable" are both covered and SP-4 is folded with its blocker, but `run_weather_strategy_backtests.py` is still untouched (deferred to AUD-11) and the family dimension the promotion loop eventually needs is deferred with a named owner, not delivered — a real completeness gap against G-06's downstream half. |
| Technical correctness and evidence grounding | 20 | 18 | The false mypy claim is replaced with a verified one, the IEM-map bound is named with its raise site, and `load_sites`'s range is corrected — all re-read this round (`pyproject.toml:68,159-189`; `settlement_alignment_study.py:65-71,638-658,646-649`; `sites.py:135-148,403-414`; `paper_replay.py:181-206`; `ma_prelock_winner_ask_study.py:149-150`; `structural_dead_stop.py:148-155,237`). Not 20: the timer-tick list is still carried from an earlier round rather than re-read. |
| Implementation specificity and feasibility | 15 | 13 | The runner is now a named module with a responsibility table, `record_blocked` is a function with a home, and the producer's window has a named helper. Not 15: the module's internal function names beyond `record_blocked` and `climate_day_utc_bounds` are left to the implementer, and `$QUOTE_CATALOG`/`$WEATHER_CATALOG_ROOT` are still described as "resolved from the same environment the other study wrappers use" rather than quoted. |
| Acceptance criteria and validation quality | 20 | 17 | B17 now targets the component that actually builds the vector, and B18 pins the wrapper/module split from both sides, closing the "nothing covers the module" gap. Not higher: B2 remains the sole falsification of the sufficiency picture, and B16's expected `params_match=False` keeps the first real row informative about mechanism only. |
| Autonomous operation, failure handling, recovery | 15 | 13 | Every failure branch now has an owner in Python, so `RECOVERED`/`FAILED`/`BLOCKED` are unit-testable rather than shell-resident. Not 15: a persistently empty ASOS cache still yields a quiet nightly `BLOCKED` row with no escalation of its own, and the item still inherits G-14's alerting dependency. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | The round-3 reviewer found no defect here. Mechanism-vs-edge separation on two independent grounds; the deferred driver change named with an owner; PREREG barrier and permit path untouched; abandonment criterion with a stated adjustment; the new IEM-map constraint recorded as a dependency rather than absorbed. |
| **Total** | **100** | **88** | |

### Round 4

- **trading-bot-architect (scheduling/pipeline/host-resource lens): 100/100 · READY**
- **architect (code-architect lens): 95/100 · NOT READY**

**Readiness is the LOWER of the two: 95.** For the **second consecutive round** the
trading-bot-architect returned a perfect score while finding none of the architect's defects — and
in a scheduling/pipeline lens, missing a cross-plan wrapper contradiction (09-5) and a permanently
quiet stall (b1) is the lens's own subject matter. The 100 is recorded, not relied on.

Both reviewers confirmed every round-3 fix is real and structural rather than editorial: the
`replay_daily_runner.py` module with its seven-row responsibility table, `record_blocked` as a
function, H0's Reader and H3's Writer corrected to name the module, B17 retargeted at the vector
builder, the windowed `--out` with one named `climate_day_utc_bounds` helper, the corrected mypy
justification, and the `IEM_ASOS_IDS` bound recorded in three places. Revision 5 therefore changes
**only** the passages named below.

| Defect | Reviewer | Disposition |
|---|---|---|
| **MATERIAL 09-5 (= AUD-10 10-6)** — the 09-4 fix introduced a cross-plan contradiction: B18 asserts the wrapper carries "exactly two `"$PY"` invocations", while AUD-10 §6b.4 appends a third (`promotion_proposal.py`) to that same wrapper. Either B18 fails CI once AUD-10 lands, or AUD-10's emission has no home — and either way the second implementer must resolve a design decision neither plan takes | architect (both plans) | **ACCEPTED IN FULL — the reviewer's framing is the right one: the count is the wrong invariant.** Verified against both plan bodies: AUD-10 §6b.4 ("appended to the AUD-09b wrapper (`replay-daily-run.sh`), inside the same host-wide `breezy-studies.lock`, after the replay"), §10 ("one extra line in the AUD-09b wrapper"), §7 step 13 ("GREEN the script + wrapper line"). **Decided once, in character-identical wording in both files:** §6b.3 now states the wrapper's invocation contract as a **property over a named script set** — *every `"$PY"` invocation in `deploy/systemd/replay-daily-run.sh` is one of the named scripts (`replay_sufficiency_census.py`, `replay_daily_runner.py`, and, once AUD-10b lands, `promotion_proposal.py`), and the wrapper contains no JSONL parsing and no `record_blocked`* — with `promotion_proposal.py` named as the **sanctioned third invocation**. **B18 is restated** over the set (so an unnamed fourth invocation still fails, while AUD-10b's addition is expected), **§5 names AUD-10's appended line** as an owned, expected later addition and forbids anything further without amending B18's set, **§7 step 10's RED wording follows**, and **AUD-10 adds C19** testing the same coupling from its side. |
| **MINOR b1** — a *persistently* empty ASOS cache is a permanently quiet failure: the unit never fails, so G-14's alerting over unit state never fires, and the schedule silently stops meeting its purpose; the remedy is one call to the already-shipped sink | architect | **ACCEPTED, and closed rather than accepted as a residual.** The reviewer is right that this is the "detector without delivery" shape memory `readiness-audit-2026-09-12` prices, and right that the sibling plan proves the remedy is one call. §6b.3 adds a rule with everything decided: after `record_blocked` appends, the module computes the run of consecutive `BLOCKED` rows sharing the identical `blocked_reason` and emits **exactly one** alert when that run **equals `N = 3`** — the same three-consecutive-failure tolerance AUD-08 §9 already uses, so the two scheduled jobs escalate on one rule. Path is the shipped `resolve_alert_sink` (`health.py:579`) / `emit_alert` (`:668`), `event="BREEZY_REPLAY_STALLED"`, `severity="warning"`, `detail` naming the `blocked_reason` and the act it implies, inside `MAX_ALERT_DETAIL_CHARS = 200` (`:112,373-374`) and carrying no absolute path. **Import-layer legality was checked, not assumed:** the runner is in `scripts/`, which sits outside every import-linter contract (`root_packages = ["breezy", "nautilus_trader"]`, pyproject.toml:68), and the identical import is already made in this same directory at `scripts/analysis/current_rung_hold_paper_replay.py:68` — a *script* import, so the `src/breezy/analysis/` cores stay free of `runtime`. Dedupe is the durable row run, **not** `AlertState` (per-process, never seeded from disk, so a nightly one-shot would re-fire every night — the same reasoning AUD-08 §6b.4 records). A raising sink cannot fail the run (`emit_alert` contains sink failures; `resolve_alert_sink` degrades to `LoggingAlertSink`). New criterion **B19**; §7 step 8, §9 and §10 updated. Residual stated: a 30-day stall produces one alert, not thirty. |
| **MINOR b2** — `WEATHER_VENUE` is used uncited by the new helper, and the timer-tick list is carried from an earlier round rather than re-read | architect | **ACCEPTED, both halves.** `WEATHER_VENUE: Final[str] = "polymarket_us"` is cited at its definition site, `scripts/analysis/run_weather_strategy_backtests.py:352`, in §6b.1, with the note that it already reaches both replay drivers by cross-script import so the helper adds no new coupling. The **tick list was re-derived from `deploy/systemd/*.timer` this round** and is now enumerated **per unit** so it is re-checkable rather than recited: `breezy-k1-daily` 01:35, `breezy-offer-gate-daily` 02:05, `breezy-quote-tape-rotate` 09:00, `breezy-mb-daily` 13:30, `breezy-score-live-trials` 14:15, `breezy-live-tally` 14:30, `breezy-position-monitor-report` 15:00, `breezy-exit-window-study` 15:20, `breezy-family-tally@` 17:20, `breezy-quote-tape-ingest` 00,06,12,18:15, plus `breezy-quote-tape-ingest-frequent`'s `*:0/15` stepper. The carried list was **correct** — 15:50 is free and `test_deploy_timer_hours.py` stays green — but it is now sourced. |

**Rejections:** none. All three round-4 findings are accepted; b1 is closed rather than taken as
the "bounded, owned residual" the reviewer offered as the alternative.

**Revision 5 self-score (2026-09-21, author, conservative):**

| Criterion | Max | Score | Remaining weakness |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | "Scheduled" and "machine-readable" are both covered, SP-4 is folded with its blocker, and the schedule can no longer stop meeting its purpose silently (B19). Not 20, and not claimed higher: `run_weather_strategy_backtests.py` is still untouched (AUD-11's scope) and the family dimension the promotion loop eventually needs is deferred with a named owner — a real completeness gap against G-06's downstream half, but one the reviewer correctly scores as blocker/other-item scope. |
| Technical correctness and evidence grounding | 20 | 19 | `WEATHER_VENUE` is cited at its definition site, the tick list is re-derived per unit from `deploy/systemd/*.timer` this round, and the alert path's legality is grounded in `pyproject.toml:68` plus the `current_rung_hold_paper_replay.py:68` precedent — on top of round-4's verified set. Not 20: the ASOS cache-coverage question is still measured at §7 step 3 rather than known now. |
| Implementation specificity and feasibility | 15 | 14 | The wrapper's invocation contract is now a stated property with a named set, so the AUD-10 implementer has no decision to resolve; the stall rule names `N`, the event, the severity, the dedupe and the reset condition. Not 15: the module's internal function names beyond `record_blocked` and `climate_day_utc_bounds` are still left to the implementer, and `$QUOTE_CATALOG`/`$WEATHER_CATALOG_ROOT` are described by their resolution rather than quoted. |
| Acceptance criteria and validation quality | 20 | 19 | B18 is now an invariant that survives AUD-10 landing and still fails an unnamed fourth invocation, and B19 pins the escalation from four sides (fires once, does not repeat, resets, cannot fail the run). Not 20: B2 remains the sole falsification of the sufficiency picture, and B16's expected `params_match=False` keeps the first real row informative about mechanism only. |
| Autonomous operation, failure handling, recovery | 15 | 14 | The one failure mode unit state can never express — a healthy unit producing `BLOCKED` rows forever — now escalates on its own through the shipped sink. Not 15: the *failed-unit* path still inherits G-14's dependency, and a 30-day stall produces one alert rather than a standing signal. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | No reviewer has found a defect here since round 2. Mechanism-vs-edge separation on two independent grounds; the deferred driver change named with an owner and mirrored in AUD-10; PREREG barrier, permit path and NO-SEND untouched; abandonment criterion with a stated adjustment; the IEM-map constraint recorded as a dependency; and AUD-10's wrapper line named as scope owned elsewhere rather than absorbed. |
| **Total** | **100** | **95** | |

### Round 5

- **trading-bot-architect (scheduling/pipeline/host-resource lens): 100/100 · READY**
- **architect (code-architect lens): 99/100 · READY (one one-line MINOR outstanding)**

**Readiness is the LOWER of the two: 99.** Both reviewers verified every round-4 disposition against
the body and against source: B18 restated as a property over the named script set (diffed
character-for-character against AUD-10 §6b.4's normative sentence), B19's stall escalation with its
reset and its no-fail-on-raise property, `WEATHER_VENUE` at its definition site
(`run_weather_strategy_backtests.py:352`), and the timer tick list re-derived independently per unit
(15:50 free, not a multiple of 15). One new MINOR was found. Revision 6 changes **only** that line.

| Defect | Reviewer | Disposition |
|---|---|---|
| **MINOR b1 (= AUD-10 c1)** — §6b.3 claims the wrapper-contract *paragraph* is character-identical in AUD-10 §6b.4; it is not (different lead-ins and closings). Only the bolded normative property sentence is identical — which the reviewer verified word for word, so **no contract drifts** — but a self-identity claim that fails a literal diff devalues the drift-detection mechanism these plans rely on (`C10 == B10`, the §6c tables, H1/H3) | architect (both plans) | **ACCEPTED, taking the reviewer's first option.** The claim is **scoped to what is actually identical**: the heading now says *the bolded property sentence below is character-identical in AUD-10 §6b.4 — the lead-in and closing around it are not, and are not claimed to be*. **The property sentence itself is unchanged in both files** and was re-compared literally before and after this edit; the mirrored edit is made in AUD-10 §6b.4. Making the whole paragraphs identical was rejected as the more invasive of the two options for zero added guarantee: the sentence is the binding, and each plan's lead-in correctly addresses its own side of the coupling. |

**Rejections:** none in round 5 (one reviewer-offered *alternative* — make the paragraphs identical —
declined in favour of the reviewer's own first option). No design change was required or made.

**Revision 6 self-score (2026-09-21, author, conservative):** **95/100**, deliberately unchanged from
revision 5 (19 / 19 / 14 / 19 / 14 / 10). Round 5's only defect was a one-line documentation-accuracy
fix, so it closes the reviewer's −1 on technical correctness but touches none of the residuals behind
my own deductions: the ASOS cache-coverage question is still measured at §7 step 3 rather than known;
`run_weather_strategy_backtests.py` and the family dimension remain out of scope with named owners;
the module's internal function names beyond `record_blocked` and `climate_day_utc_bounds` are still
the implementer's; B2 remains the sole falsification of the sufficiency picture; and a 30-day stall
still produces one alert rather than a standing signal. Scoring the revision higher for a scoped
claim would be inflation.

### Round 6

- **architect: 100/100** (`reviews/AUD-09-r6-architect.md`) · **trading-bot-architect: 100/100**
  (`reviews/AUD-09-r6-trading-bot-architect.md`). No defect found; no design change made. Readiness
  stayed **NOT READY** on the open strategy-lead blockers alone, not on plan quality.

### Round 7 — ruling-driven revision (no peer review; two blockers RULED, one measurement landed)

| Change | Source | Disposition |
|---|---|---|
| **R1 `trial_id` provenance — RULED** | RULING `docs/evidence/RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21.md` Q1 (Revision 2, peer-ENDORSED, `docs/evidence/reviews/RULING_citability_review_2026-09-21.md`) | §12's R1 blocker bullet is **replaced by the ruling**: discriminator is `family_id`, **never** `trial_id_prefix` (proven collision: `pm_us_crh_cont` / `pm_us_crh_v4` share `"continuous_rung_hold/trial/"`); replay ids never share live id space. **The half the ruling assigns here is taken in scope:** `manifest_sha256` is added to the result row (§6b.2 item 3, §6b.3) as a secondary integrity check against `load_family_manifest(...).manifest_sha256` (`persistence/family_manifest.py:185`, computed `:220`), pinned by new **B20**. **The id-construction fix stays out of scope**, exactly as Q1 item 7 directs (`src/breezy/runtime/paper_replay.py:92,347` + `live_family_tally.py:91`, neither touched by this item) — and the ruling assigns it to no existing item, so §12 records it as an **unowned build item that gates AUD-19**, not as work this plan silently absorbs. §8 gains the mandated second caveat line (Q1 item 8). |
| **MECHANISM_ONLY citability — RULED** | same ruling, Q2 (ENDORSE) | §12's second strategy-lead blocker becomes a **RULED** record: the plan's default was confirmed *and extended* — permanently never for PREREG v3 §9 at any validity tag, and not for an edge-statistic promotion criterion until AUD-11/AUD-12 flip `REPLAY_VALIDITY`. `C-VALIDITY`, `REPLAY_VALIDITY` and B7 are unchanged; no PREREG text changes. |
| **`--family-manifest` ownership** | same ruling, Q4 item 1 | "deferred, externally owned … whoever takes the promotion loop past its first proposal" is replaced by **owner: AUD-19**, cited **by id only**, in §4, §5, §6b.2 item 5 and §12 — with AUD-19's own binding gate (the Q1 fix lands first) recorded in each place. Nothing about the armed-family-only decision (round-2 09-2) is reopened; the ruling explicitly declined to fold the flag into AUD-09. |
| **ASOS cache coverage — MEASURED, not discharged** | read-only measurement 2026-09-21 (positive + negative control) | §7 step 3 and §12 now carry the number instead of the open question: the settlement-alignment cache (`~/.local/share/breezy/archive/settlement-alignment-cache`, relocation cited at `settlement_alignment_study.py:1091`) holds **SFO 313 / LAX 314 / MDW 312 / MIA 317** distinct `(station, valid)` rows inside the **2026-09-01** window, so §7 step 3's non-empty branch holds for the expected first target. Three caveats are recorded rather than absorbed: the §6b.1 predicate was reproduced **by anchored grep** (`asos_cache_csv.py` does not exist yet), so a boundary row may differ; step 3 still re-runs with the real producer at build time; and the cache is **not contiguous** (negative control SFO 2026-08-20 = **0 rows**), so an older queued day can still yield `ASOS_CACHE_EMPTY` — the §9 path, with B19's escalation. |

**Rejections:** none. **No design, scope, acceptance criterion or numbered item was removed**; the
only additions are those the ruling's own "Consequences — AUD-09" section requires, plus the
measurement and B20.

**Revision 7 self-score (2026-09-21, author, conservative):** **96/100** (19 / 20 / 14 / 19 / 14 /
10). The single point moves on *technical correctness and evidence grounding*, 19 → 20: the one
residual behind that deduction since round 3 was "the ASOS cache-coverage question is measured at
§7 step 3 rather than known now", and it is now measured with a positive and a negative control.
Nothing else moves, and nothing is claimed for the rulings themselves — resolving a blocker by
citing an external artefact does not improve this plan's specificity, validation or recovery
behaviour: the module's internal function names beyond `record_blocked` and `climate_day_utc_bounds`
are still the implementer's, B2 is still the sole falsification of the sufficiency picture, B16's
expected `params_match=False` still keeps the first real row mechanism-only, and a 30-day stall
still produces one alert rather than a standing signal.

**Latest score:** 96 (revision 7 self-score; round-6 peer scores 100 / 100; round-5 100 / 99;
round-4 100 / 95; round-3 100 / 85; round-2 73 / 81; round-1 85 / 75).

**Readiness:** **NOT READY.** What genuinely remains, and nothing more:

1. **Build item owned by AUD-19a (gates AUD-19b, does NOT gate this item's build):** the Q1 `trial_id`
   family-scoping fix in `src/breezy/runtime/paper_replay.py:92,347` + `live_family_tally.py:91`.
   Owner decided 2026-09-21: AUD-19a (see §12).
2. **Build-time, de-risked but not discharged:** §7 step 3 re-runs the ASOS producer for real; the
   timer stays disabled until step 13 produces a non-`BLOCKED` row (§6b.3, B9).
3. **Owned elsewhere, by id:** AUD-19 (`--family-manifest`), AUD-11/AUD-12 (validity flip),
   AUD-08b (H1 register, non-blocking), AUD-10 (H3 consumer, plus its sanctioned third wrapper
   invocation under B18).
4. **Round 7 is unreviewed:** the changes above are ruling-driven and have had no peer pass.

<!-- COORDINATOR FINAL STATUS — appended after review; everything above this line is the reviewed revision -->

## Coordinator final status (2026-09-22) — authoritative

This block supersedes any score or readiness wording in §13 above, which plan revisers wrote
before review closed.

- **Reviewed revision sha256** (file content above the marker line): `32a2d7591730b6227a96f1f1c2547830ab65b8ab3a7239c69ba5e7f4e6b7e95b`
- **Baseline self-score:** 83/100
- **Final score (lowest reviewer, never averaged):** 100/100
  - `architect` round 8: 100/100 — `reviews/AUD-09-r8-architect.md`
  - `trading-bot-architect` round 8: 100/100 — `reviews/AUD-09-r8-trading-bot-architect.md`
- **Readiness:** **READY**
- **Unresolved blockers / notes:**
  - None. Strategy-lead questions are RULED and peer-ENDORSED (`docs/evidence/RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21.md`).
  - Build-time gate, de-risked not discharged: §7 step 3 re-runs the ASOS producer (read-only measurement 2026-09-21 found 312–317 rows per station for 2026-09-01; cache not contiguous). Sibling items by id: AUD-19, AUD-11/12, AUD-08b, AUD-10.
- **Full review history:** 16 records, `reviews/AUD-09-r*-*.md`
- Planning only. Nothing in this plan has been implemented.
