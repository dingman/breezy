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

## Phase 1 NWS ingestion hardening: LANDED AND RE-VERIFIED (2026-08-24)

Six NWS ingestion defects were fixed with RED -> GREEN tests. Final gates:
`uv run pytest -q` exit 0 (1683 tests), `uv run ruff check .` clean,
`uv run mypy` clean.

### [CRITICAL] Conditional-GET validators could launder a blocked site open

`nws_actor.py` stored the discovery ETag before the discovery body was parsed.
If parser failure, sanity violation, integrity violation or write-integrity
violation blocked the site after that point, the next poll could send
`If-None-Match`, receive 304, and let `gate.record_successful_poll`
(`gate.py:911-951`) clear exactly those block reasons without ever persisting
the settlement product.

Validators now store only on genuinely clean paths: the 304 branch, no-new
products, sibling-only products, and after the durable-mark loop following
persist. An independent settlement review audited all 12 `_poll_cycle` exits
and found no remaining path that stores a validator for a list containing an
unpersisted product of ours.

### [HIGH] `asyncio.CancelledError` was swallowed on shutdown

`except BaseException` caught SIGTERM cancellation, routed it as an unrouted
catalog error and durably wrote a write-integrity violation to SQLite. A
restart after a mid-write shutdown could come back BLOCKED. Narrowed to
`except Exception` so cancellation propagates.

### [HIGH] Product body fetches had no intra-site pacing

A fresh site fetched every pending product body back-to-back; the existing
stagger spreads sites, not requests within one site. That made the global NWS
UA trap too easy to latch across all cities. Added
`product_fetch_delay_seconds`, default `0.5`, bounded `[0, 5.0]`, applied
before the 2nd and later fetches through an injectable sleep seam so tests do
not sleep for real.

### [HIGH] `BREEZY_USER_AGENT` defaulted to an unprovisioned placeholder

The shipped default sent `breezy-data@gmail.com`, while
`docs/plans/WEATHER_INGESTION_PROPOSAL.md` already records that this blocks
live NWS fetching until created. `BREEZY_USER_AGENT` is now required and
validated at startup: printable US-ASCII, bounded length, no leading or
trailing whitespace. Misconfiguration raises `UserAgentConfigurationError`
and exits 2.

This also closed a silent-death path: a pasted non-ASCII character previously
raised raw `UnicodeEncodeError`, not `TransportError`, so `poll_once` produced
no `PollOutcome`, gate state or health signal.

### [MEDIUM] Discovery fetches did not state the content contract

NWS requests now send an undisplaceable `Accept: application/ld+json` header
instead of relying on server defaults.

### [HIGH] Sibling-only polls froze freshness

The first validator fix missed the `if not prepared: return` branch, reached
when every pending discovery entry is for a sibling station. Sibling products
are never marked in the product-integrity index, so `_undeduped` re-yields
them every cycle. With no validator stored, 304s never arrived,
`last_successful_poll_ns` froze, and the site would latch `stale_blocked`
after 12 poll intervals despite correct local data.

Validators now store on that branch without recording a false successful poll.
This was a regression introduced by the validator fix and caught in review
before shipping.

### Runbook correction

The copy-paste systemd unit documented `BREEZY_SITES="polymarket:nyc"`, which
the registry rejects (`configuration error: configured site polymarket/nyc is
not in the registry`, exit 2). Corrected alongside the `BREEZY_LOG_LEVEL`
value list: `CRITICAL` was documented but rejected; `OFF` and `TRACE` were
valid but undocumented. Also removed a stale claim that the stdlib ->
Nautilus logging bridge was still outstanding.

### Live validation evidence

Real end-to-end ingestion was re-proven against live `api.weather.gov` on four
sites: NYC, SFO, MIA and LAX. Persisted values were cross-checked against raw
upstream product text while bypassing Breezy's parser. Evidence:
`docs/evidence/ingestion/LIVE_RUN_2026-08-24.md`.

Observed real-data confirmations: record-qualifier suffixes (`96R`, `100R`)
parse to bare integers; the `VALID TODAY AS OF` FINAL/PRELIMINARY
discriminator is correct in both directions; Miami 2026-08-19 captured a real
5 F settlement-relevant revision, preliminary `tmin=81` to final `tmin=76`.

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

### [RESOLVED] Record-qualifier tokens (`100R`) hard-blocked a whole site

A real 5-site live run on 2026-08-24 BLOCKED `polymarket_us/MIA` with
`CliContentError: unrecognized temperature token: '100R'`. The trailing `R` is
NWS's own qualifier meaning the value tied or broke the daily
period-of-record (product footer: `R  INDICATES RECORD WAS SET OR TIED.`).
Miami had hit **100 F on 2026-08-18, a record** — so the bot went blind on
precisely the kind of day a temperature market is most likely to sit near a
strike and be most valuable.

Fixed in `normalize/cli_parse.py` (`_RECORD_TOKEN_RE`, anchored
`^-?\d+R$`) with the qualifier preserved as `TemperatureReadingF.is_record`
(`normalize/units.py`) rather than discarded. Deliberately narrow: `R`,
`10RR`, `10R5`, `R100`, `100r`, `--5R` all still raise `CliContentError`, so
this is a widened allowlist for one attested shape, not a loosening of
fail-closed parsing. Pinned by two REAL captured Miami fixtures
(`tests/fixtures/nws/mia_record_final_2026-08-{18,19}/`, `synthetic: false`).

### [MEDIUM] `is_record` is parsed but not persisted

`TemperatureReadingF.is_record` stops at `ingest/records.py:_value_and_flag`,
which reads only `.sentinel`/`.value_f`; `NwsClimateDay` has no column for it,
so `tmax_flag` is `None` even on a record day. **Not a settlement defect** —
settlement reads the numeric value, and 100 F persists as 100 F; both reviewers
independently confirmed no resolution, correction-detection or
revision/supersession path consults it. It is audit metadata: an operator
reconstructing a disputed settlement must currently re-parse the archived
`NwsRawProduct.raw_text` by hand to recover it. No test exercises a
record-flagged reading through `build_climate_day`.

**Action:** wire `is_record` through `ingest/records.py` to a persisted column
when the domain schema is next revised. Low-risk — the flag can only ever be
`True` when `sentinel == "NONE"` (enforced in `__post_init__`).

### [MEDIUM] Fail-closed parsing turns one bad token into a full site outage

One unrecognized token in any of MAXIMUM/MINIMUM/AVERAGE raises and blocks the
entire site for that poll, even when the other two fields parsed cleanly — this
is what took Miami offline. The `100R` fix closed the one attested instance,
not the class: the parser has no generic "unknown-but-plausible qualifier"
path, so a novel spelling from any office reproduces the same outage with the
same signature. Pre-existing architecture, not introduced by the fix.

**Action:** alert on `CliContentError` rate per site rather than change the
fail-closed design. Also unverified: whether an office could emit `100 R`
(whitespace-separated) — `_MAXIMUM_RE`'s `\S+` capture would take only `100`
and silently drop the marker, the opposite failure mode. Not observed live.

### [MEDIUM] Live tests hardcode a personal contact address

`tests/live/test_nws_live_ingest.py:86` hardcodes a personal address in
`LIVE_USER_AGENT`. That contradicts the control in
`docs/plans/WEATHER_INGESTION_PROPOSAL.md`: the NWS contact must be a role
mailbox, not a personal address, because it lands in every fixture and log
line. Pre-existing at HEAD, not introduced by today's fixes.

**Action:** read the UA from `BREEZY_USER_AGENT` and skip the live tests when
unset. Do not substitute a role mailbox that does not exist yet.

### [MEDIUM] `BREEZY_USER_AGENT` is required for some offline construction paths

`SharedIngestState.__init__` builds `HttpTransport` unconditionally, so a
future offline replay, backtest or tooling path that constructs it will fail
before reaching any no-network actor path. This was a deliberate trade for
fail-fast live behaviour.

**Action:** revisit only if an offline replay or backtest path lands.

### [MEDIUM] Sibling-station products are never marked in the integrity index

Sibling products stay pending and are re-fetched whenever the discovery list
changes. Restored 304s bound the damage, but a list change can still waste one
body fetch per sibling product.

### [LOW] `_store_validators` can pair a fresh ETag with stale `Last-Modified`

The headers can come from different responses. RFC 7232 requires servers to
prefer `If-None-Match` when both validators are sent, so this is safe in
practice, but it remains a latent staleness vector if an intermediary
misbehaves.

### [LOW] `respx` intercepts below httpx header validation

No mocked request test can catch a malformed User-Agent. Mitigated by startup
validation that is asserted directly rather than through a mocked request.

### [LOW] `lint-imports` has no configuration

`import-linter` is declared as a dev dependency but has zero contracts defined,
so `lint-imports` reports "Could not read any configuration". Either define
the layer contracts or drop the dependency.

### [LOW] `ruff format --check` reports 31 unformatted files

Pre-existing cosmetic drift. Formatting is not currently part of any gate.

### [UNPROVEN] MDW is the only venue site not in the four-site live proof

NYC, SFO, MIA and LAX now have the 2026-08-24 live proof recorded in
`docs/evidence/ingestion/LIVE_RUN_2026-08-24.md`. MDW does not.

### [UNPROVEN] No CORRECTION product appeared in the live window

No CCA/CCB product appeared in any live window, so the supersession write path
remains fixture-covered only. `revision_seq` was live-proven in its
preliminary -> final form.

---

## Pre-production gate: RUN AND PASSED (2026-08-24)

`sites.toml:94-104` requires **independent live re-verification of every site's
`issuing_office` and `body_header_regex` by a different agent** before trading
real money. The design designates this — not the ingestion validation above —
as the final settlement-truth check. One WFO issues several cities' CLI
products, so office matching alone is worthless and a mis-bound site would
settle from the wrong city's temperatures.

**Executed 2026-08-24 by a separate agent against live `api.weather.gov`**
(51 read-only GETs: 17 location listings, 34 product bodies). Verdict **PASS**.

- `issuingOffice` checked on **every** product in each listing (76 products
  across the 5 settlement sites), not merely on a sample: `NYC->KOKX (14/14)`,
  `SFO->KMTR (14/14)`, `MIA->KMFL (14/14)`, `MDW->KLOT (15/15)`,
  `LAX->KLOX (19/19)`. Zero office drift.
- Each site's `body_header_regex` matched its own real PRELIMINARY and FINAL
  product (10/10).
- **Negative test — the one that actually matters:** all 12 sibling/decoy
  locations in `never_substitute_cli_locations` were fetched live and every
  site regex was run against every other site's text. The full 5x17
  cross-matrix is a clean identity — 2/2 on own location, 0/2 on all 16
  others. Same-office collisions (JFK/LGA/EWR under KOKX, OAK/SJC under KMTR,
  FLL/APF under KMFL, ORD under KLOT, BUR/LGB under KLOX) are all correctly
  rejected, as are the two different-office geographic neighbours
  (MTH->KKEY, SNA->KSGX).

### Two documentation defects found by the gate (code is correct)

1. **The `0400 PM` preliminary-marker literal is WRONG for the Pacific sites.**
   `classify.py:12`, `domain/selection.py:17`, `test_normalize_classify.py:5`
   and the `nws-cli-settlement` skill all quote the discriminator verbatim as
   `VALID TODAY AS OF 0400 PM LOCAL TIME.` Live today, **SFO and LAX (and OAK,
   SJC, BUR, LGB, MTH) carry `0500 PM`**. A literal-string check would classify
   the SFO and LAX PRELIMINARY as FINAL — settling 2 of 5 sites on a
   non-finalized value. **The shipped code is safe**: `classify.py:27` uses a
   time-agnostic regex. The prose/comments are what is wrong. A regression test
   pinning the `0500 PM` variant has been added so the regex cannot be
   "simplified" into a literal.
2. **The LAX double-space claim is misattributed.** Live LAX is single-spaced
   (`LOS ANGELES INTL AIRPORT CA`); the genuine double space is in the Burbank
   decoy (`HOLLYWOOD/BURBANK  AIRPORT`). `sites.toml:267` already records this
   correctly; the skill does not. `\s+` makes the regex correct either way.

Not re-verified by this gate: the specific historical product UUIDs quoted
inline in `sites.toml`, and station geometry/elevation (out of scope).

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

**Closed 2026-08-24:** that lesson previously had no executable backing — the
`live` marker was declared in `pyproject.toml` but wired to nothing (zero uses
of `@pytest.mark.live`, nothing read `BREEZY_LIVE`), so "run the real process"
was a manual discipline. `tests/live/test_nws_live_ingest.py` now makes it a
committed, runnable test: real `api.weather.gov` I/O through the real
composition root, deselected by default, skipped with a clear reason unless
`BREEZY_LIVE=1`, and exempted from the autouse socket block only under that
marker. It found nothing on its own — the Miami outage was found by an actual
5-site run — which is itself the point: keep doing both.

---

## Multi-site live validation (2026-08-24)

Phase 1's evidence above covers one site (NYC). All five registry sites have
now been run against live `api.weather.gov` in one process.

**Before the `100R` fix** — 4 of 5 sites ingesting, Miami hard-blocked:

```
polymarket_us/NYC  outcome=persisted     wrote 28 record(s)
polymarket_us/SFO  outcome=persisted     wrote 28 record(s)
polymarket_us/MIA  outcome=parse_failure CliContentError: unrecognized temperature token: '100R'
polymarket_us/MDW  outcome=persisted     wrote 30 record(s)
polymarket_us/LAX  outcome=persisted     wrote 38 record(s)
```

**After the fix** — 5 of 5:

```
polymarket_us/NYC  outcome=persisted  wrote 28 record(s)
polymarket_us/SFO  outcome=persisted  wrote 28 record(s)
polymarket_us/MIA  outcome=persisted  wrote 28 record(s)
polymarket_us/MDW  outcome=persisted  wrote 30 record(s)
polymarket_us/LAX  outcome=persisted  wrote 38 record(s)
```

All five gates reached `state=OPEN reason=successful_poll`, `ua_trap=False`.
Read back by a separate process: `NYC 14/14, SFO 14/14, MIA 14/14, MDW 15/15,
LAX 19/19` climate days / raw products, **0 settlement-digest failures across
all 5 sites**. Miami's record day persists correctly as
`2026-08-18 tmax=100 tmin=82 tavg=91`, in both PRELIMINARY and FINAL revisions.

### Authenticity, proven not assumed

An independent process re-fetched persisted products from live
`api.weather.gov` and compared bytes. Three NYC products matched
**byte-for-byte** (lengths 4391/4714/4462 identical; `raw_sha256` identical).
For one product the SHA-256 of the *entire* fresh HTTP response body also
equalled the stored `response_sha256` — the whole JSON envelope reproduces
exactly. `issuanceTime`, `issuingOffice`, `wmoCollectiveId` and `productCode`
all matched, and PRELIMINARY/FINAL classification was confirmed correct
against the `VALID TODAY AS OF` rule on the real text.

### Whole-corpus parser sweep

Every CLI product currently retrievable for all five sites — **76 products**
across 5 forecast offices — was run through `parse_cli_product` with each
site's own `cli_location` and `body_header_regex`: **76/76 parsed, 0 failures.**
This is the empirical basis for believing no further real-world format hazard
is outstanding today. It is a snapshot, not a guarantee: the sweep can only
see products NWS is currently serving.

### Known gap in the operability artifacts

On a run shorter than one full poll cycle, the on-disk health snapshot and gap
ledger describe a pre-poll state that is already false by process exit
(`gate_state: BLOCKED`, `gate_reason: never_polled`, 7 open gaps with CRITICAL
severities) — the snapshot fired ~0.3s before the first catalog write, and the
state DB shows the correct OPEN state. Whether the ledger converges on cycle 2
is **not demonstrated by that run's evidence** and remains unverified.

**Action:** verify post-persist ledger/snapshot convergence over a multi-cycle
run before relying on either artifact for alerting.
