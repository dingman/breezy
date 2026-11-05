# AUD-08 — Review record (Round 3)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-08-unattended-station-candidate-register.md
- Plan file sha256: 5b2b5569831a48a76bfb7599a1d2aa477ef1c9d777d431ac3db51ab9f9604fad (filled by coordinator at save time)
- Round: 3 · Reviewer: architect (code-architect lens: module boundaries, versioned inter-stage
  data contracts, idempotency, import layering, exchange portability, YAGNI)
- Total: 81/100 · Readiness: NOT READY

## Round-2 dispositions, verified against the plan body and against source

| R2 defect | Claimed | Verified? |
|---|---|---|
| **A8-1 / M5** — sidecar unspecified; contradicts §1 | ACCEPTED IN FULL | **FIXED as a document.** §1 now scopes the sidecar into 08b and says so explicitly (lines 16–18); §6b.1 is a full artefact table — module, path, `SIGHTING_SCHEMA_VERSION`, `append_sighting`/`read_sightings`, `UnknownSightingSchemaError`, `O_APPEND` one-line-per-`write()` framing, daily rotation, 35-day pruning, and the two crash cases split correctly (trailing partial line = WARN; malformed non-final line = hard refusal, because it can only mean interleaving). A12 added. The §1↔§6b contradiction is genuinely gone. **But the enforcement mechanism it now rests on does not hold — see A8-3.** |
| **A8-2** — NYC has no producer; three `Sufficiency` values dead | ACCEPTED IN FULL | **FIXED in shape, broken in key domain and undefined in value.** The second named input (`seed_cities`), the `origin: Literal["SIGHTING","REGISTRY_SEED"]` field with its own key rule (seeds never count slugs, origin never changes, a seed never alerts), and the restatement of A9 against the seed path are all present and are the right design. I confirm `SiteRegistry.pairs()` exists (`src/breezy/registry/sites.py:348`) and that `settlement_alignment_study.load_sites` uses exactly that enumeration (`:638-641`). **But the pair it yields is not the key the record uses — A8-4 — and the `Sufficiency` value it must carry has no stated computation — A8-5.** |
| **a1** — signature not expressible under `mypy --strict` | ACCEPTED | **FIXED.** Two `@overload`s on `Literal[False]`/`Literal[True]` over one implementation, plus A13 (`mypy src/breezy` clean) as the binding constraint and a two-function shape named as a substitute. Re-verified the premise myself: `strict = true` (pyproject.toml:158), `files` includes `src/breezy/adapters` (`:160`) with no override, and `discovery_candidate_slugs` (`provider.py:181-187`) calls `_weather_market_payloads(payload, city_codes)` positionally with no flag, so it binds the first overload and keeps its type. Sound. |
| **a2 (= AUD-10 10-2)** — H2 "declined" while `C-STATIONS` records the register's count | ACCEPTED | **FIXED, and consistently across all three files.** §6c H2 now states the decline *without residue* and names the deletion; AUD-09 §6a states the same; AUD-10 §6b.2 deletes the clause and §6b.3's `C-STATIONS` row is a pure subset predicate whose input column reads "the proposal's own draft manifest only". I diffed the three statements: no drift. The reasoning for choosing deletion over a bounded read (AUD-10b's refuse-on-missing-input rule would let a missing register refuse a proposal) is the correct one. |
| **a3** — no compaction/retention rule | ACCEPTED | **FIXED.** §6b.2: no expiry (with a stated rationale — the artefact's value is the standing "has this venue ever listed X" fact), a per-day growth bound via the registry-derived flood cap, compaction-not-deletion at 180 days, key-preserving and idempotent, pinned as A15. |
| **tba minor** — candidate sits unread; no trigger/owner | ACCEPTED | **FIXED and well-grounded.** §6b.4's one-shot alert rides the shipped path: `resolve_alert_sink` (`runtime/health.py:579`, returning a bare `LoggingAlertSink` when unconfigured at `:609`), `emit_alert` (`:668`), `AlertSink` Protocol (`:385`), `MAX_ALERT_DETAIL_CHARS` (`:112`) — all re-opened and exact. The refusal to dedupe via `AlertState` (per-process, never persisted) and to use the register's own `first_seen_day == today` instead is the right call and is argued from that class's docstring, not asserted. A16. |

Priority (P1/P3), the §6c eight-step eligibility table, the L-1 grep verdict and the registry-derived
flood cap are unchanged from revision 2 and remain correct.

## Defects found in revision 3

**A8-3 (MATERIAL, NEW — the single-writer invariant the whole sidecar design rests on is not
implementable as written, and the fix as sketched breaks a documented invariant).**
§6b.1 makes "exactly one writer by construction" the substitute for a lock: an injected
`sighting_sink: SightingSink | None = None`, supplied at `factories.py:517` by "the recorder
composition" and `None` by the trade node, with **A14** as the test. Two problems, both verified at
source:

1. **There is no recorder-vs-trade-node discriminator at that site.** `_shared_polymarket_us_
   instrument_provider` (`factories.py:516-537`) receives only `(client, provider_config, discovery,
   clock)`; neither process identity nor the recorder's knob is among them. The plan's phrase "only
   when the recorder's discovery config is in play" names no field, and §13's self-score concedes the
   implementer must "read it at `factories.py:517`". The only discriminator that exists is in the
   *caller's* config — `config.subscribe_trades` (`adapters/polymarket_us/config.py:333`), which
   `factories.py:619-622` documents verbatim as "The recorder's knob … the trade node's config leaves
   it False". Deciding this is a material design decision, and it governs a safety invariant, not a
   detail.
2. **Passing the sink through that function collides with `@lru_cache(maxsize=1)`.** The same
   function is called from **both** `create()`s — the data factory at `:589-594` and the exec factory
   at `:722` — and the module comment at `:432-446` states the point explicitly: both call the same
   `@lru_cache(1)` getters "with an equal-valued `config`, so … ONE instrument provider exist[s] for
   the process, never two independently-quota'd clients", and `lru_cache` "raises `TypeError` if a
   config is ever unhashable". A sink is an object: if the data side passes a file-backed sink and the
   exec side passes `None` (or a separately-constructed instance), the two calls have different cache
   keys, `maxsize=1` evicts, and **two providers are constructed** — reinstating precisely the R-4
   divergence the docstring at `:523-529` says this function dissolves, and creating **two appenders
   to one sidecar inside one process**, i.e. the interleaving case §9 declares impossible by
   construction and treats as a hard refusal.
REQUIRED: (a) name the discriminator literally (e.g. `config.subscribe_trades`, or a new explicit
field on `PolymarketUSMarketDiscoveryConfig`) and say which `create()` resolves it; (b) state that the
sink is resolved through its own `@lru_cache`/module-level singleton so **both** call sites pass an
equal-valued, hashable argument, or that the sink is attached after construction rather than as a
cache-key parameter; (c) extend **A14** to assert that exactly one `PolymarketUSInstrumentProvider` is
constructed per process across both factories — otherwise A14 can pass while the invariant is broken.

**A8-4 (MATERIAL, NEW — the seed input's key is in the wrong domain, so the merge rule cannot fire
and H1's join breaks).**
§6b.3 computes `seed_cities` from `default_registry().pairs()`, which yields `(venue, city)` where
`city` is the registry's site key — `[sites.polymarket_us.NYC]` (`src/breezy/registry/sites.toml:117`,
and `.SFO/.MIA/.MDW/.LAX` at `:154,193,239,279`), i.e. **"NYC"**. But the record's key field is
`city_token`, and a *sighting*'s token is `parsed.city` tested against `city_set = city_codes`
(`provider.py:221`), which `discovery_city_codes_from_registry` derives as `venue_city_token`
(`adapters/polymarket_us/config.py:155-183`) and which that module requires be **lowercase slug
codes** (`config.py:214`); `sites.toml:121` gives `venue_city_token = "nyc"`. Consequences, all
mechanical: (i) a seeded row keys on `("polymarket_us","NYC")` and a later sighting on
`("polymarket_us","nyc")`, so §6b.3's rule "a city that is both seeded and later sighted keeps
`origin="REGISTRY_SEED"`" can **never** fire and the register holds two rows for one city, violating
A6's own uniqueness premise; (ii) **H1 breaks across the plan boundary** — its join row says
`(venue, city_token)` is "mapped to a station code by the registry's `venue_city_token` → site
mapping", i.e. `SiteRegistry.site_for_venue_city_token` (`sites.py:393-401`), which raises
`SiteNotFoundError` for `"NYC"`; so AUD-09a's census fails on the only row this register is expected
to hold on PM.us.
REQUIRED: derive the seed token through the same derivation the discovery config already uses
(`discovery_city_codes_from_registry`, `config.py:155-183`, or the registry's venue-symbology
accessor), state once that `city_token` is **always** the venue's lowercase token, and add a clause to
A6 asserting that a seeded row and a later sighting of the same city collapse into one record with
`origin="REGISTRY_SEED"`.

**A8-5 (MATERIAL, NEW — the seed path's `Sufficiency` value has no stated computation, so A9 has no
pass condition).** §6b.3 gives three seed-path values (`REGISTRY_ONLY_NO_CAPTURE`,
`CAPTURED_INSUFFICIENT`, `CAPTURE_SUFFICIENT`) and says the script computes sufficiency by calling
`count_covered_listed_station_days_from_catalog(..., cities=(city,))`. That function returns an
**`int`** (`scripts/analysis/structural_dead_stop.py:219-250`). Nothing states the mapping from that
integer to the three-valued alphabet — no threshold, no "0 ⇒ REGISTRY_ONLY_NO_CAPTURE", no reuse of a
named constant (`MIN_AFTERNOON_STATION_DAYS` is imported in that module at `:58` but never referenced
by the plan). **A9** therefore asserts the register's sufficiency "agrees with" an integer, which is
not a testable predicate, and the implementer must invent the threshold — the one number that decides
whether a candidate reads as testable. This is the same class of gap A8-2 closed on the input side,
left open on the value side.
REQUIRED: state the integer→`Sufficiency` mapping explicitly (threshold, its source constant, and the
zero case), and restate A9 as an equality against that mapping applied to the fixture's count.

**a1 (MINOR) — the literal sufficiency call does not typecheck.**
`count_covered_listed_station_days_from_catalog` is **keyword-only**: `def …(*, catalog_root: Path,
cities: Sequence[str] = DENSE_STATIONS, fetch_start…, fetch_end…)` (`structural_dead_stop.py:219-225`).
§6b.3 writes `count_covered_listed_station_days_from_catalog(catalog_root, cities=(city,))` — a
positional first argument, i.e. a `TypeError` at runtime and a strict-mypy error in a directory the
plan itself notes is `strict`-covered (`scripts/analysis`, pyproject.toml:177). REQUIRED:
`catalog_root=catalog_root`.

**a2 (MINOR) — registry path drift.** §3, §5 and §6c cite `registry/sites.toml`; the file is
`src/breezy/registry/sites.toml` (the line numbers 117/154/193/239/279 are correct). §13 concedes
these were carried rather than re-read. REQUIRED: correct the path in all three places.

**a3 (MINOR) — the fold window is shorter than the failure tolerance.** §6b.4's emitter "reads
yesterday's and today's sidecar files", while §9 escalates only after **three** consecutive failed
emissions. A recovered emitter therefore never folds the sidecar day(s) it missed — those sightings
are permanently unread, even though the file survives the 35-day pruning. Self-healing is argued from
the venue re-listing the city, which is an assumption about the venue, not a property of the design.
REQUIRED: fold every unpruned sidecar day since a recorded `last_folded_day` watermark (the register's
`last_seen_day` already provides one), or state the two-day window as an accepted, bounded loss.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 17 | 08a closes the load-bearing livelock completely; §6c honestly bounds AUD-08 to steps 1–2 of eight. 08b's headline deliverable on PM.us — the one NYC row — is not yet producible end to end (A8-4, A8-5). |
| Technical correctness and evidence grounding | 20 | 16 | Every external citation I re-opened is exact: `provider.py:181-187/190-229/221-227`, `factories.py:516-537`, `health.py:112/385/579/609/668`, `pyproject.toml:158,160,177`, `sites.py:348,393`, `sites.toml:117,121,154,193,239,279`, `config.py:76`. Deducted for the verified key-domain error (A8-4), the keyword-only call (a1) and the path drift (a2). |
| Implementation specificity and feasibility | 15 | 10 | Sidecar, overloads, seed input, retention and alert are all decided to the symbol. Two material decisions remain with the implementer: the recorder discriminator + lru_cache interaction (A8-3) and the sufficiency threshold (A8-5). |
| Acceptance criteria and validation quality | 20 | 16 | A1–A8, A10–A13, A15, A16 objective and property-shaped. **A9** has no defined pass condition (A8-5) and **A14** cannot be written as specified and would not catch the failure it exists to prevent (A8-3). |
| Autonomous operation, failure handling, recovery | 15 | 12 | Livelock closed with a two-cycle test; two distinct sidecar crash cases; registry-derived flood cap; corruption refusal; three-failure escalation; push notification with a durable dedupe. Deducted for A8-3 (the "impossible by construction" interleaving case is reachable through the `lru_cache` path) and a3 (recovery loses unfolded sidecar days). |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | ROI honesty, abandonment criterion scoped to 08b's sighting count only, H2 declined without residue and consistent across three files, out-of-scope steps named with owners, no operator-cap or enablement contact. No defect found. |
| **Total** | **100** | **81** | |

## Required changes to reach 100
1. Make the single-writer invariant implementable: name the recorder discriminator, keep both
   factory call sites' `lru_cache` key equal-valued, and strengthen A14 to assert one provider per
   process (A8-3).
2. Derive `seed_cities` in the `venue_city_token` domain and assert seed/sighting collapse in A6
   (A8-4).
3. State the integer→`Sufficiency` mapping and restate A9 against it (A8-5).
4. Fix the keyword-only call (a1), the `sites.toml` path (a2), and the fold window/watermark (a3).

## Blockers (recorded separately; not scored)
- **Operator + strategy lead, OUTSIDE this item:** the `registry/sites.toml` pre-production
  re-verification gate and the archive-table extension for a fifth station (§6c steps 3–4). Correctly
  named, correctly not planned here.
- **Evidence unavailable:** the trigger scenario (a venue listing a 6th city) has never been
  observed, so 08a's value cannot be demonstrated, only argued. Correctly recorded in §12 and used as
  the P1-not-P0 argument.
None of these caps the score; all four material defects are author-resolvable.

_Saved verbatim by the coordinator: the `architect` reviewer has no file-write tool._
