# Breezy — Progress and Backlog

State of the work. Backlog items are tracked here, not in the design docs.

---

## Phase 1 — NWS ingestion substrate: BUILT AND LIVE-VALIDATED (2026-08-23)

> **[CORRECTION 2026-08-24] The catalog described in this section no longer
> exists.** The 14 persisted climate days, the `14/14` digest re-verification
> and the restart-dedupe run below were all real when written, but the catalog
> they were written to is gone — most likely a `BREEZY_CATALOG_BASE` pointed at
> a tmpfs path that did not survive a reboot. Nothing was collecting between
> that loss and 2026-08-24T19:45:54Z. **Treat every record count in this
> section as historical, not as data on disk.** Current on-disk state is in
> "Collection re-established" below. The code claims in this section still
> stand; only the data does not.


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

## Collection re-established after total catalog loss (2026-08-24)

**Status: LIVE.** All five venue sites collecting on durable storage.

### What was lost

The catalog backing every record count in the Phase 1 sections above was gone,
and nothing had been collecting for an unknown interval ending
2026-08-24T19:45:54Z. No parquet, no `breezy-state*`, no bootstrap witness
existed anywhere under `/home/jon`, and `BREEZY_CATALOG_BASE` was unset. The
evidence documents were accurate at the time of writing; the storage they
described did not survive.

### Deployment now in place

| | |
|---|---|
| `BREEZY_CATALOG_BASE` | `/home/jon/.local/share/breezy/catalog` (0700) |
| Filesystem | **ext4, 543G free — verified not tmpfs** |
| State DB | derived: `<base>/state/breezy-state.sqlite3` |
| Env file | `/home/jon/.config/breezy/breezy.env` (0600) |
| Unit | `~/.config/systemd/user/breezy-nws-ingest.service`, enabled, lingering on |
| `BREEZY_SITES` | all five: `polymarket_us:{NYC,SFO,MIA,MDW,LAX}` |
| `BREEZY_USER_AGENT` | set to a real role mailbox in the env file |

Chosen over the runbook's `/var/lib/breezy` + `_breezy` service user because
that path needs root; the runbook production posture remains the documented
target and is unchanged.

### First-poll evidence (2026-08-24)

Cold start 19:45:54Z. First poll per site, on the designed 0/60/120/180/240s
anti-UA-trap stagger:

| Site | Predicted | Actual | Records | Gate |
|---|---|---|---|---|
| NYC | 19:50:55 | 19:51:04 | 28 | OPEN |
| SFO | 19:51:55 | 19:52:03 | 28 | OPEN |
| MIA | 19:52:55 | 19:53:04 | 28 | OPEN |
| MDW | 19:53:55 | 19:54:04 | 30 | OPEN |
| LAX | 19:54:55 | 19:55:08 | 38 | OPEN |

152 records, 10 parquet files, both `custom_nws_climate_day` and
`custom_nws_raw_product` datasets per site.

**Seven climate days recovered (2026-08-17 .. 2026-08-23) on all five sites**,
each with both a PRELIMINARY and a FINAL product. 2026-08-17 was recovered with
**zero days of margin** against assumed NWS retention — the restart won that
race by less than a day.

### What this validated, unprompted, on live data

- **The fail-closed gate works as designed.** Every site defaulted to
  `BLOCKED / final_cli_overdue` with no history, then transitioned to
  `OPEN / final_received` only on a real FINAL product for 2026-08-23. This is
  the SettlementGate's core claim, observed in production rather than in a test.
- **The stagger works as designed.** Actual first-fire times matched the
  `site_stagger_offset_seconds(index, 5, 300)` prediction to within 9s, giving
  one request per 60s to `api.weather.gov` under a single User-Agent instead of
  a five-way simultaneous burst.
- **The durability probe is now armed** (`durability:probe` row in the state
  DB) — the guard that would have caught the original loss.

### [OPEN] Non-uniform record counts across sites — unverified inference

Same seven days and the same product pair per day yielded 28/28/28/**30**/**38**.
The extra records on MDW (+2) and LAX (+10) are *most likely* correction or
revision products, which would make LAX the highest-revision site and give the
preliminary->final revision-rate study its first live sample. **This is an
inference from record counts and has not been verified** — extra METAR
observations for those stations are equally consistent with the numbers.
Confirm before relying on it.

### [LOW] Misleading gate log line: `state=BLOCKED reason=successful_poll`

At 19:51:04Z NYC logged a BLOCKED transition whose stated reason was a
*successful* poll, superseded ~200ms later by the OPEN transition. The gate
re-derives per call so this is cosmetic rather than functional, but the reason
string is contradictory and should be corrected.

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

### [RESOLVED 2026-08-24] MDW now has a live proof

Closed by the 19:45:54Z collection restart: MDW polled at 19:54:04Z and
persisted 30 records with its gate transitioning to OPEN on `final_received`
for climate day 2026-08-23, alongside the other four sites. All five venue
sites now have a live proof. Evidence:
`docs/evidence/ingestion/COLLECTION_RESTART_2026-08-24.md`.

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

---

## Venue quote-tape recorder: BUILT, REVIEWED, NOT YET RUNNING (2026-08-26)

Work item 1.1 of `docs/plans/TRADING_ENABLEMENT_PLAN.md`. **Uncommitted.**
**Not started collecting** — gated on a live run (see "Gating item" below).

### Why this and not a strategy or a backtest

Backtesting was impossible and remains so for any period before the tape
starts: a backtest needs the weather series AND the market price series
aligned in time, and no Polymarket.us price history exists or can be
obtained. Polymarket.us weather markets did not exist before 2026, so no
vendor can backfill them. Weather history IS retroactively available (the
alignment study drew ~1,800 city-days per site from the IEM archive), which
makes the price tape the only irreversible item on the critical path: every
uncaptured day is permanently lost. Strategy, sizing, execution client and
settlement package can all be built later from a standing start.

### What was built

Native Nautilus persistence, verified NATIVE SUFFICIENT by execution rather
than by reading: `StreamingConfig` / `StreamingFeatherWriter` wired at
`runtime/node_config.py::build_quote_tape_node_config`, plus a
`breezy-quote-tape` entrypoint. **No bespoke persistence layer was written.**

Captured: `QuoteTick`, `OrderBookDepth10`, `TradeTick`, `MarkPriceUpdate`,
`InstrumentClose`, `InstrumentStatus`, and four custom records —
`QuoteTapeGap`, `VenueClockOffset`, `VenueSettlementSnapshot`,
`DepthTruncation`.

Gates at the close of pass 4 (final): `pytest` 2412 passed / exit 0; `mypy`
clean over 88 source files; `ruff` 9 findings, all pre-existing in the vendored
`docs/evidence/**/sdk_snapshot/`. All three independently re-run by the
coordinator, not accepted from agent reports.

### A regression this introduced and closed

A first attempt made seven `POLYMARKET_US_*` variables unconditionally
required in `load_settings()`, which broke the startup path of the LIVE NWS
collector — it would have failed on restart. 90 test errors. Fixed by role
separation (`PolymarketUSQuoteTapeSettings` / `load_quote_tape_settings`),
not by defaults, which would have started the recorder half-configured and
silently recording nothing. Pinned by
`tests/unit/test_nws_ingest_settings_role_isolation.py`.

### Three silent-data-loss traps found in Nautilus and in our own code

1. `StreamingFeatherWriter` **discards a quote with no exception and no log**
   when the instrument is absent from the `Cache` (`writer.py:228-238`).
2. `OrderBookDepth10.__init__` pads a short side with `NULL_ORDER` at
   precision 0; the Arrow encoder then rejects the record, and
   `writer.write` swallows that into a log line (`writer.py:284-288`). A
   thin book — i.e. a quiet weather market — would have vanished silently.
   We now pad at the instrument's own precision.
3. Ours: `resolved_gaps_by_seq` keyed on `gap_seq` alone, but `gap_seq` is
   per-instrument, so two cities collided and one city's outage was silently
   discarded while the other's boundaries were stamped onto it. A
   contamination filter that is confidently wrong is worse than none.

All three are contract-tested so an upstream change fails RED.

### Two venue facts corrected against the committed captures

- **The venue does not emit ten levels.** `book_open_510636.json` carries 12
  bids and 14 offers. `OrderBookDepth10` truncates; `DepthTruncation`
  records how many levels were dropped per frame, not what they were.
  Slippage measured from this tape is valid only to level ten.
- **`settlementPx` on an OPEN market is a daily mark, not a settlement.**
  Open: `settlementPx == closePx == 0.4900`, method `..._EVENT_TIER_2`.
  Expired: `settlementPx = 1.0000`, no `closePx`, method `..._EVENT_TIER_1`.
  The venue distinguishes the regimes by its own enum. Recording the open-
  market value as a settlement would have fabricated a settled price into an
  archive that can never be re-recorded. `InstrumentClose` now requires a
  terminal state AND `TIER_1`.

### Review outcome

Three independent axes over two rounds. Domain: original CRITICAL closed
(levels beyond 10 are far-OTM dust, not liquidity near the best). Security:
read-only cage INTACT and measurably hardened — `transport.py` B3 replaced a
bound method whose `__self__` reached the pyo3 client with a `_GetOnlyCallable`
closure, plus a runtime receiver-graph scanner. Code: approve, with the
mutation check independently reproduced (parse-depth-and-discard fails
exactly 3 tests).

One documented claim was found FALSE and removed rather than left standing:
`max_file_size` is never consulted under `rotation_mode=SCHEDULED_DATES`
(`writer.py:305-318` is an `if/elif` chain), so the "512 MB backstop" was
dead code asserting a bound the code did not provide. **One day's tape file
is unbounded. Accepted and unmitigated — needs external disk alerting.**

### Gating item — do NOT start continuous capture until this passes

**No live run has happened.** Zero authenticated calls, zero live-network
verification; every venue host in every test is `.invalid`. 2401 green tests
do not establish that a real frame reaches parquet. This is exactly the
standing lesson of this repo.

`MARKET_SLUG_KEY = "marketSlug"` remains an **unresolved venue guess** and
every routing decision rests on it. If it is wrong the recorder captures
nothing and looks exactly like a quiet market.

Live venue tests are behind the deliberate three-lock gate of
`docs/plans/POLYMARKET_US_READONLY_AUTH_PLAN.md` D2 (`BREEZY_VENUE_LIVE=1`
AND `BREEZY_ALLOW_CREDENTIALED_PYTEST=1` AND the `--venue-live` flag). That
gate exists so no automation trips it incidentally; unlocking it is an
operator decision.

### Other open, disclosed limitations

- Trade frame schema UNRESOLVED — `TRADE_CONTAINER_KEY` and the taker-side
  mapping are inferred. Fail-closed: an unrecognised side maps to
  `NO_AGGRESSOR`, never a guessed direction.
- `EXPIRED_MARKET_STATES` partly speculative; only observed states confirmed.
- `tape_gaps` is a LOWER BOUND. `QuoteTapeGap` now carries a
  `recorder_instance_id` sourced from the native `NautilusKernelConfig.instance_id`
  (the same value that names the streaming directory), and
  `resolved_gaps_by_seq` keys on `(recorder_instance_id, instrument_id, gap_seq)`.
  The FIELD makes correct partitioning possible; nothing FORCES a consumer to
  use it, so a consumer iterating raw catalog rows still inherits the
  under-exclusion hazard. Loader-side enforcement is outstanding.
- **Void/cancel settlements are unhandled and deliberately unguessed.**
  `parse_instrument_close` emits `CONTRACT_EXPIRED` unconditionally on a TIER_1
  terminal frame, so a voided market arriving under TIER_1 would be recorded as
  a genuine settlement. No evidence either way exists in the captures. This is a
  `polymarket-us-discovery` live-probe question, not a coding one.
- Strike-ladder coverage of configured slugs is unverified.
- `VenueSettlementSnapshot.settlement_px` is a verbatim string; no rounding
  decision has been made.

### Settlement premise: still unvalidated, and the gate may be the wrong shape

The pre-registered 2 F bucket-alignment gate FAILED all five cities. A
post-hoc boundary guard-band sweep (`docs/evidence/settlement_bucket_guard_band_2026-08-26.md`)
did NOT rescue it — agreement DEGRADES as the guard tightens (0.764 -> 0.688)
while retention collapses to 12.97%.

The residual is not boundary noise. It is a one-directional bias: misses go
from 68.5% to 99.3% "METAR below CLI" as the guard tightens, and NYC is
~99.6% one-directional at every band. KNYC (Central Park) reports ~29
observations/day against ~306 at the airport ASOS sites — sparse sampling
systematically misses the true daily maximum. **Systematic bias is
correctable; boundary noise is not.**

Open question, NOT yet tested: the bucket gate is SYMMETRIC, but the Tier-1
rule is ASYMMETRIC — it only buys once the observed running max has already
cleared the strike, and refuses the P~0 side. A negative bias is the
conservative direction for that rule. Testing the asymmetric form needs its
own pre-registration and an adversarial domain review; it must not be
adopted as a rescue without one.

---

## GO LIVE backlog (opened 2026-08-26)

Roadmap: `docs/plans/GO_LIVE_PLAN.md`. Per-item execution plans:
`docs/plans/backlog/G-*.md`.

**Scope boundary:** this backlog covers work up to — and deliberately NOT
including — the forecast model. Populating `src/breezy/features/` and
`src/breezy/settlement/` (both currently 0 bytes), the probability estimator,
calibration, sizing and the execution client are Phase E/F and are not opened
here. They are entered only on a Phase D GO.

Status vocabulary: `TODO` / `IN PROGRESS` / `GREEN` / `BLOCKED (<unlock>)`.

### Phase B — free falsification (no venue, no credentials, no wait)

- **G-01 — Preliminary→final revision-rate study (DOM-11).** `GREEN (result: UNDERPOWERED)`
  Pre-registered, run, reported. N=44 against a pre-registered floor of N>=90
  per site. LAX 0/8, MDW 0/9, MIA 0/9, NYC **2/9 (0.222, Wilson [0.063, 0.547])**,
  SFO 0/9. No PASS claim is valid. Evidence:
  `docs/evidence/preliminary_final_revision_2026-08-26.md`. NYC's revision rate,
  though underpowered, is a warning for the post-preliminary window DOM-11
  proposed as possibly dominating Tier 1. The item is green because the study
  was executed and honestly reported; the *finding* is that more data is needed.
  Measure the preliminary-CLI → final-CLI revision rate per site from the
  catalog already on disk. Prices the post-preliminary-CLI window, which the
  domain review judges may dominate Tier 1. Pre-register before running.
- **G-02 — ROI feasibility arithmetic (DOM-13).** `GREEN (verdict: NO-GO)`
  Per 100 contracts per city-day cluster: pessimistic ~$3/day net, central
  ~$9/day net, optimistic ~$15/day net. **NO-GO for committing to the downstream
  adapter / settlement / execution build** on current worked-example economics;
  free falsification and irreversible tape capture stay in scope. Evidence:
  `docs/evidence/roi_feasibility_2026-08-26.md`. Theta sensitivity moves the
  five-city p=0.97 result by only ~$1/day per 500 contracts, so G-15 fee
  discovery will not rescue it. Breadth moves the central case from ~$6/day
  (three cities) to ~$9/day (five).
  Programme-level gross/net ROI estimate before committing to 63 blocking
  requirements. Central estimate from the worked example is tens of dollars
  per day gross. Written GO/NO-GO.
- **G-03 — Asymmetric-gate pre-registration + adversarial review.** `GREEN`
  `docs/evidence/asymmetric_gate_prereg_2026-08-26.md` at **revision 14**,
  **APPROVED-WITH-AMENDMENTS** on round 13; both advisories applied. Twelve
  consecutive BLOCK verdicts preceded it, each on a real defect. **G-17 is now
  authorised on methodological grounds** and remains unconditionally blocked on
  G-16 (tape capture), which is operational, not methodological.

  What the loop actually found, in order:
  1. The document's own central premise was **falsified**: MDW runs the
     dangerous direction (56.37% METAR>CLI, mean +0.0527), so "METAR reads below
     CLI" may not be asserted programme-wide anywhere.
  2. `H(c,k)` was structurally blind to adverse selection (DOM-10).
  3. The `p̂ = 0.985` power anchor was taken from market price — presupposing
     the calibration DOM-10 disputes.
  4. That anchor survived in the **binding formula** after the prose claimed to
     replace it.
  5. The replacement `min(c, 2c)` was dead algebra reducing to `c`.
  6. The Wilson lower bound converges to `p̂` from below, so the floor could be
     **mathematically undefined**, not merely large — which would have produced
     programme-wide NO-GO by arithmetic rather than evidence.
  7. "Computable today" was false: the cited script strata by the *final* daily
     max, not the running max at receipt, and cannot emit two of the five bins.
  8. A claimed conservatism margin was a **no-op** — a constant lag cannot
     change observation ordering.
  9. A declared DOM-9 prerequisite gated nothing the construction implemented.
  10. The anchor measured a different **population** than the statistic it sized.
  11. The representativeness fix named the **wrong partition**.
  12. "Do not fall back to the pooled anchor" routed to a branch defined on the
      pooled anchor.
  13. A new exempt state had no resolution path, reopening DOM-1.

  Findings 4, 5, 11 and 12 are the paper-close pattern — see the standing lesson
  below. Several were introduced *by* a fix for the previous round.
  The failed 2 °F gate is SYMMETRIC; the Tier-1 rule is ASYMMETRIC. Write the
  pre-registration and obtain an adversarial domain review **before** testing.
  Must not be adopted as a post-hoc rescue.

### Phase C — amendment set (`TRADING_ENABLEMENT_PLAN.md` is BLOCK)

- **G-04 — STK-1: pyo3 socket escape in the test suite.** `GREEN (with stated residual)`
  RED test reproduced the escape against a closed loopback port
  (`HttpError ... Connection refused (os error 111)` while the Python socket
  block read green), then closed it. `tests/unit/test_pyo3_network_block.py`.
  **Residual, not overclaimed:** this is an in-process constructor block for
  known Nautilus pyo3 HTTP/WebSocket clients, NOT a kernel-level egress block.
  A complete OS/process-level block still needs an external network namespace
  or CI firewall.
  **Safety-critical, ahead of the document work.** The autouse socket blocker
  patches Python's `socket` only; a `nautilus_pyo3` client reached the OS while
  the gate read green. An ordinary `uv run pytest -q` could transmit a signed
  order. Needs a RED test proving the escape, then a real block.
- **G-05 — STK-10: pin `nautilus-trader==1.231.0`.** `GREEN`
  Pinned in `pyproject.toml` and `uv.lock`; `uv lock --check` exit 0; contract
  suite passes against the pin.
  Currently `~=1.231` while the whole `contract/` suite pins measured 1.231.0
  behaviour.
- **G-06 — STK-6: register the `venue_live` pytest marker.** `GREEN`
  Registered with marker text naming the exact three-lock gate. Wired to the
  existing gate rather than a second mechanism; gate not weakened.
  No `venue_live` marker exists and `--strict-markers` requires registering it
  in the same change as its first use.
- **G-07 — STK-9 / ARC-4: import-linter layering contract.** `GREEN`
  `uv run lint-imports --no-cache` exit 0, **2 contracts kept, 0 broken**:
  "Breezy top-level source packages follow the documented layer direction" and
  "Breezy never imports the Nautilus Polymarket .com adapter".
  Promote `lint-imports` from cosmetic (it has no configuration today) to
  required. It is the enforcement mechanism for the missing dependency-direction
  rule and for the "never import the .com adapter" ban.
- **G-08 — Amend TRADING_ENABLEMENT_PLAN with the full finding set.** `GREEN`
  All 38 findings resolved, 0 argued-rejected. Traceability table at
  `docs/plans/TRADING_ENABLEMENT_PLAN_AMENDMENTS.md`. Eight new requirements
  added (REQ-VENUE-18, REQ-OPS-13..17, REQ-ALPHA-09..10); Phase 3 split into
  3a/3b per ARC-7; Phase 0 items labelled non-TDD per STK-11. Spot-verified by
  the coordinator by grepping six cited requirement IDs in the amended plan —
  all present. **The BLOCK header was NOT lifted**: it was re-labelled to the
  accurate current reason (ROI NO-GO + asymmetric gate not authorised).
  Committed as `d4bde7b`.
  SEC-1..8, ARC-1..8, DOM-1..13, STK-1..12. Document work. Lifts the BLOCK
  ruling. Depends on G-01, G-02, G-03 landing their determinations.

### Phase A support — recorder hardening (no venue access needed)

- **G-09 — Loader-side gap-partitioning enforcement.** `GREEN (with stated residual)`
  `src/breezy/persistence/quote_tape_gaps.py` —
  `load_partitioned_quote_tape_gaps`, `GapPartitionKey`,
  `PartitionedQuoteTapeGaps`, `UnpartitionedQuoteTapeGapReadError`. RED test
  writes colliding `gap_seq=1` rows through a real Nautilus
  `ParquetDataCatalog`, proves the naive flat collapse drops a still-open
  outage, and proves the sanctioned loader refuses flat reads.
  **Residual:** fully preventing a direct raw `ParquetDataCatalog.query(...)`
  would require wrapping Nautilus globally, which the immutability constraint
  forbids. Enforcement is the sanctioned loader API, not a hard seal.
  `QuoteTapeGap` carries `recorder_instance_id` and `resolved_gaps_by_seq` keys
  on `(recorder_instance_id, instrument_id, gap_seq)`, but nothing FORCES a
  consumer to partition correctly — a consumer iterating raw catalog rows still
  inherits the under-exclusion hazard. `tape_gaps` remains a LOWER BOUND until
  this lands.
- **G-10 — Tape file disk alerting.** `GREEN`
  `src/breezy/runtime/quote_tape_disk_monitor.py`, wired into
  `quote_tape_cli.py`, thresholds required-no-default in `settings.py`.
  **The Nautilus claim was independently verified before building the
  mitigation:** in installed 1.231.0, `_check_file_rotation` consults
  `max_file_size` only for `RotationMode.SIZE`; `INTERVAL`/`SCHEDULED_DATES`
  take a separate `elif` branch on scheduled time alone. **Decision: alert, do
  not halt** — a false halt creates unrecoverable tape loss, so the monitor
  logs escalating WARNING/ERROR and lets capture continue until the filesystem
  itself rejects writes.
  `max_file_size` is never consulted under `rotation_mode=SCHEDULED_DATES`
  (`writer.py:305-318` is an if/elif chain), so one day's tape file is
  unbounded. Currently accepted and unmitigated. Needs external disk alerting
  before continuous capture starts.
- **G-11 — Commit the quote-tape recorder work.** `GREEN`
  Committed as `b02e7ed` (code) and `58599ec` (docs), staged by explicit path,
  no `git add -A`. Secret scan clean before commit. Gates re-run independently
  by the coordinator at the commit: pytest exit 0 (0 failures), ruff exit 0,
  mypy exit 0 over 90 source files, lint-imports exit 0 (2 contracts kept).
  Work item 1.1 is built and reviewed but **uncommitted**. It is on the
  critical path and must not live only in the working tree.

### Phase A support — autonomous discovery (added 2026-08-26)

- **G-18 — Autonomous market discovery.** `GREEN` — was on the critical path.
  Built and verified **entirely offline against committed captured payloads**;
  zero live venue calls. Six tests: the captured climate payload yields the
  expected weather slug set; the provider discovers open markets from the list
  endpoint; pagination is followed to a short page; a zero-discovery cycle
  raises and alerts loudly; a bounds/`description` disagreement fails closed;
  and subscription never precedes the Cache containing the instrument.
  `POLYMARKET_US_MARKET_SLUGS` is no longer required recorder config —
  `POLYMARKET_US_DISCOVERY_RELOAD_INTERVAL_MINS` is required-no-default in its
  place. `MARKET_SLUG_KEY` deliberately unchanged: it is the WebSocket key and
  G-12 stays open pending a live frame.
  Gates re-run independently by the coordinator: pytest 0 (0 failures), ruff 0,
  mypy 0 over 91 source files, lint-imports 0 (2 contracts kept). The read-only
  barrier suite still passes — discovery is GET-only.
  **Residual:** `POLYMARKET_US_MARKET_SLUGS` survives as optional legacy
  metadata for the auth-smoke probe path only.

  **[SUPERSEDED — original TODO text below]**
  Plan: `docs/plans/backlog/G-18-autonomous-market-discovery.md`.
  Opened on operator direction: the bot must discover markets itself and will
  never be handed a slug list. `POLYMARKET_US_MARKET_SLUGS` is static and
  required while weather slugs are **per-day**, so continuous capture would
  record nothing from day two and look exactly like a quiet market.
  **G-14 must not start until this lands.**
  Verified feasible offline: the venue exposes `GET /v1/markets` with
  `categories` / `active` / `closed` / pagination filters, and list payloads are
  already captured in `docs/evidence/venue/polymarket_us/raw/`. Nautilus
  supplies the reload primitive (`initialize(reload=True)`) and the bundled
  Polymarket adapter supplies the scheduling pattern verbatim — no new
  abstraction is needed.

### Phase A — live venue (OPERATOR-GATED)

- **G-12 — Resolve `MARKET_SLUG_KEY` against the live venue.**
  `BLOCKED (operator: three-lock credential gate + D1 KYC)`
  `"marketSlug"` is an unresolved guess on which every routing decision rests.
  Wrong ⇒ the recorder captures nothing and looks like a quiet market.
- **G-13 — Gating live run of the recorder.**
  `BLOCKED (operator: three-lock credential gate)`
  Zero authenticated calls have ever been made. Prove one real frame reaches
  parquet, read back by a separate process.
- **G-14 — Start continuous capture under systemd.**
  `BLOCKED (depends G-12, G-13, G-10, G-18)`
  **G-18 added as a hard dependency:** starting continuous capture on a static
  slug list would silently record nothing after day one.
- **G-15 — Fee schedule discovery.**
  `GREEN (autonomous; NOT an operator input)`
  The previous `BLOCKED (operator: live probe)` label was **wrong**. The venue
  publishes the fee coefficient in every market payload we had already
  captured, so this was never an operator question and never needed a live
  probe. Per the governing principle, venue facts are discovered by the bot,
  never supplied by the operator.

  **Evidence, re-derived 2026-08-26** by recursive sweep of
  `docs/evidence/venue/polymarket_us/raw/*.json`:
  - **729 market observations / 680 distinct slugs** across **11 files** that
    contain market objects: `events_seriesId_35.json` (600),
    `search_weather.json` (60), `markets_categories_climate.json` (20),
    `markets_tagIds_weather.json` (20), `events_seriesId_35_active.json` (12),
    `search_weather_seriesIds_35.json` (12), `market_closed_15806_by_id.json`,
    `market_closed_15806_by_slug.json`, `market_open_510636_by_id.json`,
    `market_open_510636_by_slug.json`, `markets_slug_open.json` (1 each).
  - `feeCoefficient == 0.06` in **729/729**, with **zero** exceptions, spanning
    both `MARKET_STATUS_OPEN` (60 slugs) and `MARKET_STATUS_RESOLVED` (620
    slugs), so it is not an artefact of one lifecycle stage. No slug ever
    disagrees with itself across duplicate observations.
  - `orderPriceMinTickSize == 0.01` in **729/729**.
  - `minimumTradeQty` **VARIES** — 378 slugs at `0.01`, 302 at `1`. Read per
    market; never assumed. (`_increment` aborts the load if it is absent.)

  Note: an earlier note circulated "7 files / 45 observations / 42 vs 3". That
  came from a top-level-only scan and **undercounts by ~16x**; it misses every
  market nested under `events[].markets[]`. The numbers above supersede it.

  **Implemented.** `theta` is parsed per market, validated (finite, `[0,1]`),
  and written to `info` only when actually parsed — `FEE_SCHEDULE_STATUS_KNOWN`
  is DERIVED, never assumed. Absence leaves `UNKNOWN` and fail-closed; an
  unusable value aborts the instrument via `InstrumentDefinitionError`. The fee
  itself is computed by `PolymarketUSFeeModel`, a subclass of the native
  `backtest.models.FeeModel` extension point. `maker_fee`/`taker_fee` now carry
  `theta` rather than a zero, which can only ever OVERSTATE (the gap is
  `theta*C*p^2 >= 0`). Barrier F1 remains green and remains load-bearing.

  **STILL GENUINELY UNVERIFIED — do not read this item as more certain than it
  is:**
  1. **The maker coefficient.** The payload has ONE coefficient and no
     maker/taker split. Makers are charged at the taker coefficient as a
     deliberate conservative inference. The docs snapshot describes a maker
     REBATE (-0.0125) which we deliberately do NOT apply, because applying an
     unobserved rebate would understate cost. Resolve on the first observed
     maker fill.
  2. **The venue's exact rounding.** No captured payload states it. Banker's
     rounding to $0.01 is implemented on the strength of the
     `polymarket-us-integration` docs snapshot alone. Confirm against the first
     real fill's charged commission.
  3. **That `feeCoefficient` IS the taker coefficient.** Inferred from its
     value (0.06) matching the documented taker theta exactly. Never stated by
     the payload itself.
  4. **Volume-tiered taker discounts** (0.054 / 0.045 / 0.03) are documented
     but not applied; applying them would understate cost.

### Phase D — hard gate

- **G-16 — Accumulate ≥14 days of joined tape.**
  `BLOCKED (calendar: 14 days after G-14)`
- **G-17 — Phase 1.5 premise falsification GO/NO-GO.**
  `BLOCKED (depends G-16)`
  Restructured per DOM-1: (a) settlement-alignment Wilson lower bound per city
  and per degree-of-clearance stratum as the GO/NO-GO, plus (b) a capturability
  study on depth-weighted fill price and printed trades. GO requires both.
  **NO-GO stops the programme.**

### Autonomous-execution note

G-01..G-11 and G-15 are executable without venue access, credentials or a calendar wait.
G-12..G-14, G-16 and G-17 are not, and are tracked as BLOCKED with their unlock condition
rather than as failures. Any "all green" claim refers to the G-01..G-11 + G-15 subset.

---

## Standing lesson — the paper-close pattern (2026-08-26)

Recorded because it was caught **four times in one session**, in a document
whose entire purpose was methodological rigour.

**The pattern.** A finding is raised. The next revision adds prose announcing
the fix — and the prose is accurate about what *should* happen — while the
operative expression an implementer would actually run is left unchanged,
contradicted by a sibling bullet, or replaced with something that does not
compute what the prose says.

**The four instances, all in `docs/evidence/asymmetric_gate_prereg_2026-08-26.md`:**

1. Revision 2 justified a power anchor `p̂ = 0.985` on the ground that it is
   "the entry region where the depth actually is" — i.e. from the market price.
   That presupposes the market is calibrated, which is precisely what DOM-10
   disputes. The circularity was not removed, only relocated.
2. Revision 3 announced a replacement anchor in prose while the **binding
   `N(c,k)` formula still hardcoded `0.985`**. The reviewer's words: "the math a
   G-17 implementer would actually run is unchanged from the version that was
   BLOCKed for circularity."
3. Revision 3 also described its new concordance table as the exceedance
   fraction when the table carried the complement. An implementer following the
   prose would have computed the anchor **backwards**.
4. Revision 4 introduced `p̂_anchor(c,k) = min(c, 1 - 2*(1-c) + 1)`. The second
   term simplifies to `2c`, so the whole expression reduces to `min(c, 2c) = c`
   — a per-city constant with **zero stratum dependence**, which is exactly the
   defect the revision claimed to fix. The bullets below it defined `2c-1`
   instead. Alongside it, a cross-reference reading "defined in the next bullet"
   pointed at a bullet that was not a definition.

**Why prose review does not catch this.** Every one of these reads correctly at
the paragraph level. The defect only appears when you evaluate the expression
or trace the computation end to end. Three of the four were found only because
the reviewer was explicitly instructed to trace what an implementer would run,
rather than to assess whether the document said the right things.

**Binding rules going forward.**

- A review of any document containing a formula MUST simplify the formula, not
  read it. `min(c, 2c)` looks like a stratified anchor and is a constant.
- When a revision claims to replace a value, **grep for the old value** and
  confirm it does not survive in a binding position. Narrative mentions in
  review records are fine; an occurrence inside the operative formula is the
  defect.
- Every formula gets a **worked table of per-input values**. `2c-1` with the
  five city values written out cannot be transcribed wrongly; a bare expression
  can.
- There must be exactly **one** definition of any computed quantity. A formula
  line plus an operational bullet list is two definitions, and they will drift.
- A traceability table is verified by **reading the cited section**, never by
  reading the table. Applied to G-08: six cited requirement IDs were grepped in
  the amended plan and all six were present.

**Cost of not catching it.** Instance 4 would have silently under-powered the
`[0,1)` clearance stratum — the one stratum the document insists must reach a
verdict — raising the odds of a false GO at exactly the boundary where the
DOM-4 divergence modes bite. That is a wrong trade, not a wrong document.

---

## G-20 settlement reporting layer implemented (2026-08-27)

`src/breezy/settlement/reporting.py` now provides the pure reporting layer over
`ProgrammeDetermination`: exact city and stratum joins, MDW headline identity,
MDW boundary-figure requirement for `PRIMARY_GO`, partitioned unevaluated ledger,
unconditional [R7] provenance caveat, and fixed-section Markdown rendering.

The impure writer is isolated in
`scripts/analysis/settlement_programme_report.py`, which reads strict JSON inputs
and writes the report plus `.sha256` and `.meta.json` sidecars. First generated
artifact:
`docs/evidence/settlement_programme_report_2026-08-27.md`.

New guard suites cover settlement purity (D1-D4), report construction/rendering
(R1/R2), and the P1 prose lint. Each live barrier was mutation-tested with a
planted violation, then restored green with the injected file deleted.

Residuals remain: no trading-path consumer forces a report to be produced, D2
constrains only the settlement package, P1 is literal prose linting rather than
semantic enforcement, and the report carries `H(c,k)` only, not DOM-10's
`H2(c,k,q)` statistic.
