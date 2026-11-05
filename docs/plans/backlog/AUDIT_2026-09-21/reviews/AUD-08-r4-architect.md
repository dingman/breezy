# AUD-08 — Review record (Round 4, FINAL)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-08-unattended-station-candidate-register.md
- Plan file sha256: 8a0514478b757b2d91dd2bd9f65d621e759947664570417d5c4e78336546ff46 (filled by coordinator at save time)
- Round: 4 · Reviewer: architect (module boundaries, versioned inter-stage contracts, idempotency,
  import layering, exchange portability, YAGNI)
- Total: 91/100 · Readiness: NOT READY (one material defect, author-resolvable)

## Round-3 dispositions, verified against the plan body AND against source

| R3 defect | Claimed | Verified? |
|---|---|---|
| **A8-3** — single-writer design unimplementable; sink as an `lru_cache` key builds two providers | ACCEPTED IN FULL | **FIXED, and correct at source.** I re-opened `factories.py`: `@lru_cache(maxsize=1)` at `:516` over `(client, provider_config, discovery, clock)` `:517-521`; both `create()`s call it — data `:589-594`, exec `:722`; the equal-valued-key invariant is stated verbatim in-code at `:578-586` and `:710-718`; the R-4 docstring is `:523-529`. Every one of the four decision rows holds: **(a)** `subscribe_trades: bool = False` is at `config.py:333` and its comment `:322-332` reads exactly as quoted ("the quote-tape RECORDER's knob … The live trade node keeps the default"); `factories.py:619-622` repeats it; `node_config.py:527` sets `subscribe_trades=True` — the only site that does. The rejection of a new `sighting_sink_enabled` field is argued, not asserted, and I agree. **(b)** `quote_tape_cli.py:188` is the only `add_data_client_factory` in the recorder and there is no `add_exec_client_factory` in that module; `trade_cli.py:402,405` registers both. So the data factory is provably the only site that must discriminate. **(c)** the cache key is untouched — the sink is post-construction. **Can the shared cached provider be attached twice with different sinks?** No, and I checked the two routes: within one process `_shared_sighting_sink` is `@lru_cache(1)` over one `str`, so a second call with the same directory returns the *same object* (no-op by identity); a call with a *different* directory evicts and returns a different object, which `attach_sighting_sink` refuses loudly with `SightingSinkAlreadyAttachedError`. Both outcomes are safe, and A14 clause (iii) (`data_provider is exec_provider` **and** `cache_info().misses == 1`) closes the gap I named: A14 can no longer pass while the invariant is broken. |
| **A8-4** — seed key in the wrong domain | ACCEPTED IN FULL | **FIXED.** `pairs()` returns site keys (`sites.py:348-350`); the corrected derivation is the same comprehension body as `discovery_city_codes_from_registry` (`config.py:155-183`; the comprehension is `:168-172`, the plan says `:166-173` — trivial), which resolves `venue_symbology(...).venue_city_token` (`sites.py:384-391`) and is refused non-lowercase at `config.py:213-214`. `site_for_venue_city_token` (`sites.py:393-401`) keys on `(venue, token)` built at load from `symbology.venue_city_token` (`:478,486`) — so **H1's join is valid on the corrected token**, and it would have raised on `"NYC"`. §6b.2 states the domain rule once and bindingly; A6 carries the collapse clause with a concrete arm. Sound. |
| **A8-5** — no integer→`Sufficiency` mapping | ACCEPTED IN FULL | **FIXED and correctly sourced.** `MIN_STRUCTURAL_DEAD_STATION_DAYS = MIN_AFTERNOON_STATION_DAYS` at `structural_dead_stop.py:85`, imported `:58`, with the "never a second, potentially-drifting literal" comment at `:82-84` exactly as quoted. A9 is now an **equality** with three arms taken from the imported constant, never the literal `15`. `NO_SETTLEMENT_TRUTH`'s exclusion is reasoned. |
| **a1** — keyword-only call | ACCEPTED | **FIXED.** `def count_covered_listed_station_days_from_catalog(*, catalog_root, cities=DENSE_STATIONS, …) -> int` at `:219-225`; the plan now passes `catalog_root=`, quotes the signature, and additionally names the uppercase-vs-lowercase domain trap on `cities=`. Correct. |
| **a2** — `sites.toml` path drift | ACCEPTED | **FIXED** at §3, §5, §6c step 3, §12. |
| **a3** — fold window shorter than the failure tolerance | ACCEPTED | **FIXED by design, not by an accepted loss.** `last_folded_day` watermark (versioned, atomic, advanced only after a successful fold *and* register write), ascending fold of every unpruned day, absent/unknown watermark folds everything (safe under A7), residual counted as `sidecar_days_lost`. A17 tests a three-day outage and the byte-identical re-run. This is stronger than what I asked for. |

Priority, the flood cap, the 180-day compaction, H2-declined-without-residue and the §6c eight-step
table are unchanged from revision 3 and re-checked consistent with AUD-09 §6c and AUD-10 §6c.

## Defects found in revision 4

**A8-6 (MATERIAL, NEW) — the sufficiency counter's `catalog_root` is unbound, and an unreadable or
wrong root is *silently permissive*: it reads as `count=0`, i.e. a legitimate-looking
`REGISTRY_ONLY_NO_CAPTURE`.**
§6b.3 now calls `count_covered_listed_station_days_from_catalog(catalog_root=catalog_root,
cities=(city,))` — keyword-correct — but **nothing in the plan says what binds `catalog_root`**. That
parameter has *no default* (`structural_dead_stop.py:219-225`), so the script must supply it, and the
repo already has the one right answer: `DEFAULT_QUOTE_TAPE_CATALOG` (`ma_prelock_winner_ask_study.py:187`,
used as this very script's own `--catalog-root` default at `structural_dead_stop.py:277`). Two
consequences, both verified:
1. **Wrong/empty root ⇒ `0` ⇒ `REGISTRY_ONLY_NO_CAPTURE`.** `discover_station_days` over a
   non-existent `depth_root` yields nothing and the counter returns `0` (`:233-250`), which §6b.3's
   own mapping turns into a *valid* value. A misconfiguration and a genuinely-uncaptured city are
   then indistinguishable in the artefact — the same silently-permissive shape I flagged on AUD-10's
   `C-KILL` and that the plan itself calls out elsewhere ("never guesses, never silently skips").
   Note the shipped counter *does* emit `depth_root_present` precisely because this distinction
   matters; the plan reads neither it nor an equivalent.
2. **An unhandled refusal path.** The same call reaches `_resolved_gaps_from_catalog`, which raises
   `QuoteTapeGapDataUnavailable` when the gap partition cannot be read (`:253-266`). §9 enumerates
   flood, sidecar corruption, recorder crash, emitter outage, register corruption, repeated failure
   and an unconfigured alert sink — but **not** "the sufficiency counter refused". The nightly
   emitter would abort with an uncaught exception; the watermark protects the sightings, but the
   alert path and the register update stall behind a failure mode that is not in the plan's own
   failure list.
REQUIRED: (a) bind `catalog_root` to `DEFAULT_QUOTE_TAPE_CATALOG` (or the `BREEZY_POLYMARKET_US_
QUOTE_TAPE_CATALOG` env the deployed wrappers use, `score-live-trials-run.sh:60`) by name; (b) state
that an **absent/unreadable catalog root, `depth_root_present == false`, or a
`QuoteTapeGapDataUnavailable` refusal makes the seed row's sufficiency REFUSE**, never `0` — the seed
keeps its previous value or the run exits non-zero, and the case joins §9; (c) add an A9 arm (or a new
criterion) asserting that an absent catalog root does **not** produce `REGISTRY_ONLY_NO_CAPTURE`.

**a1 (MINOR, NEW) — the sidecar's day-resolution and rotation rule is unstated, and the sink's write
call-site is unnamed.** §6b.1 says "one file per UTC day by filename" and "flushed and closed per
cycle", while the sink row says one process holds "exactly one open append handle"; the getter takes a
*directory* (`_shared_sighting_sink(str(SIGHTINGS_DIR))`), which implies the day is resolved per
append — but that is inference, not specification. The recorder is long-running, so a sink that
resolved its filename once at attach would write days D+1…D+n into D's file; the emitter folds by
filename and advances `last_folded_day` past D, so those sightings become unreachable. **A12 tests
round-trip and the two crash cases, not rotation.** Separately, §6a/§6b.1 never names *where* the
provider calls the sink (presumably at the end of `load_all_async`, beside
`self._unregistered_city_sightings`), so the one write path in the design has no stated home.
REQUIRED: state that the sink resolves `sightings-<UTC day>.jsonl` **per append**, name the day source
(observation ts vs wall clock), name the provider call-site, and add a rotation arm to A12
(two appends across a UTC-midnight boundary land in two files).

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | 08a closes the livelock; the seed row is now producible end to end (A8-4/A8-5 closed at source). −1: the one PM.us deliverable's *value* is not fully specified (A8-6). The residual G-05 "stations are still static" gap is **not** deducted — §6c steps 3–5/8 are operator/strategy-lead acts outside any plan change; recorded as a blocker. |
| Technical correctness and evidence grounding | 20 | 18 | Every citation I re-opened this round is exact: `factories.py:516-521,578-586,589-594,619-622,710-718,722`; `config.py:155-183,213-214,322-333`; `node_config.py:527`; `quote_tape_cli.py:188`; `trade_cli.py:402,405`; `sites.py:348-350,384-401,478,486`; `structural_dead_stop.py:58,82-85,214,219-225,277`. −2 for A8-6's verified `count=0` conflation and the unhandled `QuoteTapeGapDataUnavailable`. |
| Implementation specificity and feasibility | 15 | 13 | The two decisions I said were left to the implementer are now *made*: discriminator (named field, named `create()`, rejected alternative argued) and the threshold (named constant, total mapping). −2: the catalog root is still an unmade input decision (A8-6) and the sink's day-resolution/call-site is inferred (a1). |
| Acceptance criteria and validation quality | 20 | 18 | A9 is a real equality with three constant-derived arms; A14(iii) now catches the failure A14 exists to prevent; A6 has the collapse arm; A17 pins multi-day recovery and the byte-identical re-run. −2: nothing tests the catalog-root/absent-input behaviour (A8-6) and A12 does not test rotation (a1). |
| Autonomous operation, failure handling, recovery | 15 | 13 | Interleaving is now genuinely unreachable via the `lru_cache` path; multi-day recovery is a design property with a counted residual; flood cap, corruption refusal, three-failure escalation, one-shot push alert with a durable dedupe. −2: A8-6 adds a silently-permissive value and a failure mode absent from §9. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | ROI honesty, abandonment criterion scoped to sighting-origin rows only, H2 declined without residue and consistent across three files, out-of-scope steps named with owners, no operator-cap or enablement contact, no `allow_short`/PREREG/NO-SEND surface. No defect found. |
| **Total** | **100** | **91** | |

## Required changes to reach 100
1. Bind `catalog_root` by name, make an absent/unreadable catalog (and a counter refusal) **refuse**
   rather than read as `count=0`, add the case to §9 and an arm to A9 (A8-6).
2. State the sidecar's per-append day resolution and the provider's sink call-site; add a
   UTC-midnight rotation arm to A12 (a1).

## Blockers (recorded separately; not scored)
- **Operator + strategy lead, OUTSIDE this item:** the `src/breezy/registry/sites.toml`
  re-verification gate and the archive-table extension for a fifth station (§6c steps 3–4). Correctly
  named, correctly not planned here. This is why G-05's headline cannot be closed by AUD-08.
- **Evidence unavailable:** the trigger (a venue listing a 6th city) has never been observed, so 08a's
  value is argued, not demonstrated. Correctly recorded in §12 and used as the P1-not-P0 argument.
- **Cross-item constraint (AUD-09 §6c step 6, mirrored):** a sixth registered site breaks
  `load_sites()`'s hardcoded `IEM_ASOS_IDS`, which the same counter this plan calls depends on. No
  effect today; correctly owned by whoever executes §6c step 4.

_Saved verbatim by the coordinator: the `architect` reviewer has no file-write tool._
