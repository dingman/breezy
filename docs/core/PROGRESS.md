# Breezy — Progress and Backlog

State of the work. Backlog items are tracked here, not in the design docs.

---

## Phase 1 — NWS ingestion substrate: BUILT AND LIVE-VALIDATED (2026-08-23)

Design: `docs/plans/WEATHER_INGESTION_PROPOSAL.md` (v6, operator-approved 2026-08-22)
and `docs/plans/PHASE1_ACTOR_BRIEF.md`.

Persistence is native NautilusTrader `ParquetDataCatalog` for weather records
(the data plane), with a SQLite `StateStore` for the settlement gate and the
product-integrity index (the control plane). No PostgreSQL, TimescaleDB, Redis,
DuckDB, vector store or custom persistence abstraction was introduced.

### Live validation evidence

One real process against `api.weather.gov`, one site (`polymarket_us:NYC`):

- Actor registered and RUNNING: `NWS-INGEST-polymarket_us-NYC`;
  `has_cache_backing=False`, `has_msgbus_backing=False`, zero catalogs
  registered with the DataEngine.
- 14 CLI products (2026-08-16 .. 2026-08-22) retrieved, parsed, normalized and
  persisted as both `NwsRawProduct` and `NwsClimateDay`.
- Read back **by a separate process**: `climate_days=14 raw_products=14`,
  `ts_init` non-decreasing, **14/14 settlement digests re-verified**
  (`read_raw_products` deliberately does not re-verify, so an unchecked
  round-trip would prove nothing).
- Preliminary/final pairs correctly distinguished on real data, including a
  real revision: `2026-08-20 tmax=84 tmin=71 final=False` (20:45Z) then
  `tmin=63 final=True` (05:00Z next day).
- Restart dedupe: a second full process over the same catalog and state
  (95s, 30s polls) held at 14/14 with 14 unique UUIDs and all digests valid.

### Independent review outcome

security-reviewer APPROVE (1 MEDIUM), prediction-market-reviewer APPROVE
(1 MEDIUM, 1 LOW), python-reviewer BLOCK (1 HIGH). The HIGH and the security
MEDIUM are fixed; the rest are tracked below.

The two reviewers **contradicted each other** on gate fail-open behaviour.
Resolved empirically, both were half right: per-site state fails CLOSED
(`_derive_state` returns BLOCKED when `last_successful_poll_ns is None`),
while the global `ua_trap_blocked` latch did not. Both halves are now fixed:
an in-store bootstrap sentinel covers row deletion, and an out-of-band
witness at `<catalog_base>/.breezy-bootstrap-witness` covers deletion of the
whole state-DB file. Verified end-to-end through `ingest_runtime`:

    delete state DB only       -> BLOCKED / STATE_STORE_TAMPERED
    delete state DB + witness  -> OPEN / SUCCESSFUL_POLL   (residual limit)
    genuine first boot         -> OPEN / SUCCESSFUL_POLL

**Residual limit, deliberately not overclaimed:** deleting BOTH the state DB
and the witness marker is still undetectable. This raises the bar from
"delete one file" to "delete two files in two different locations" and makes
the realistic case -- a botched restore of just the DB -- loud. It is not a
defence against an adversary with full filesystem write access.

---

## Open follow-ups

### [MEDIUM] `never_substitute` is declared but has no consumers
`src/breezy/registry/sites.toml` defines `never_substitute` /
`never_substitute_cli_locations` per site (e.g. NYC must never settle from
KJFK/KLGA/KEWR), but nothing in the Phase 1 ingest path reads them.

Not settlement-affecting today: the actual protection is the stronger,
independent AWIPS-PIL-equals-`CLI{cli_location}` check plus the per-city
`body_header_regex`, both of which are live code. The risk is forward-looking
— whoever wires the Phase 2 METAR/ACIS cross-check could reasonably assume
`never_substitute` is already enforced and omit the check.

**Action:** before any METAR/ACIS path lands, either consume these lists or
place a `TODO(Phase 2)` at the station-selection call site.

### [RESOLVED] `ABSOLUTE_MAX_F` widened 130 -> 140 F, reconciled
`src/breezy/normalize/sanity.py:65-68`. Kept at 140 F -- above the all-time
world record, so a genuine heat event does not halt trading -- and the
docstring now states the decision and rationale as settled rather than
pending. No numeric or behavioral change.

### [MEDIUM] Unbounded whole-catalog reads per lookup
`src/breezy/persistence/catalog.py:693` and every `read_climate_days` /
`read_raw_products` call site in `nws_actor.py` omit `start`/`end`. Accepted
and self-documented at ~2 records/climate-day/station (~730/year), but this is
a full scan per poll per site and grows linearly with retention.

**Action:** add a catalog row-count metric/alert rather than a code change now.

### [RESOLVED] `BREEZY_LOG_LEVEL` unvalidated at load time
`src/breezy/runtime/settings.py` now fails fast via `SettingsError`, matching
every other setting in that module. Validated against NautilusTrader's actual
`LogLevel` set (verified against the installed `nautilus_pyo3.LogLevel`:
`OFF`/`TRACE`/`DEBUG`/`INFO`/`WARNING`/`ERROR`), not the stdlib `logging`
module's aliases (`WARN`/`CRITICAL` are rejected).

### [RESOLVED] `pyiem` backfill dependency was an open range
`pyproject.toml`'s `backfill` extra declared `pyiem>=1.19`; the
`nws-cli-settlement` skill mandates `pyiem == 1.27.0` exactly. Verified the
installed `.venv` was already resolving `1.27.0` (so no test evidence in this
repo was ever produced against a different release), then pinned the
declaration to `==1.27.0` and resynced `uv.lock` via `uv lock`/`uv sync
--extra backfill` (not hand-edited). Added
`tests/unit/test_backfill_dependency_pin.py` to fail loudly if a future
resync drifts the resolved version.

**Scope note surfaced while verifying:** `pyiem` is not currently imported
anywhere in `src/` or `tests/`. The live settlement parse path
(`breezy.normalize.cli_parse`) is a deliberate hand-rolled, pure-text parser
(see its module docstring) that never calls pyIEM, and
`NwsIngestActor.PARSER_VERSION` is the hardcoded string
`"breezy.normalize.cli_parse@0.1.0"`, not a pyiem version — contrary to the
skill's "Use pyIEM -- Do NOT Hand-Roll Parsing" section and its
`parser_version (pyiem version used)` provenance field. This pin therefore
protects a not-yet-built pyIEM-backed backfill path; today's settlement-parse
protection is the golden-parse fixtures in `test_normalize_cli_parse.py`
(`test_parse_real_final_fixture_matches_expected` et al.), which pin
`cli_parse.py`'s exact tmax/tmin/tavg output directly. Flagging the
skill/implementation gap here rather than resolving it — reconciling it is an
architecture decision (adopt pyIEM per the skill, or update the skill to
match the hand-rolled design) outside this change's scope.

Also checked `metar` and `pynws`, the skill's two other pyIEM-family pins
(`metar == 2.0.1`, `pynws == 2.1.0`): `pynws` is not declared as a dependency
at all (nothing to pin); `metar` is not a direct dependency either — it
arrives only transitively via `pyiem` and happens to lock at `2.0.1`,
matching the skill's mandate today but with no direct top-level pin holding
it there. Not adding either, per this task's scope (do not add currently
undeclared dependencies).

### Import-linter contracts are still absent
`import-linter` is declared as a dependency but **no contracts are configured**,
so the layering it exists to enforce is unenforced.

---

## Pre-production gate (NOT YET RUN)

`sites.toml:94-104` requires **independent live re-verification of every site's
`issuing_office` and `body_header_regex` by a different agent** before trading
real money. The design designates this — not the ingestion validation above —
as the final settlement-truth check. One WFO issues several cities' CLI
products, so office matching alone is worthless and a mis-bound site would
settle from the wrong city's temperatures.

---

## Standing lesson from this phase

The unit suite was **fully green at two separate points while the deployment
was dead**: first the Actor could not be constructed at all
(`ActorFactory.create` ends in `actor_cls(config)`, so `ImportableActorConfig`
cannot carry `SharedIngestState`), then it was built but never registered.
Both were caught by running the real process, never by tests. Both are now
regression-tested by asserting on *behaviour* (`node.trader.added_actors`,
`GateReason.TASK_DEATH` reaching the gate) rather than on structure.

Treat green tests here as necessary and not sufficient; a live run is part of
the definition of done for anything in the ingest path.
