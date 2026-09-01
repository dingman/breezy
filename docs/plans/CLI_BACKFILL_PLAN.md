# Historical NWS CLI backfill — implementation plan

**Status:** REVISION 2. **EXECUTED THROUGH I-2 — do not re-implement.** `src/breezy/domain/archived_climate_day.py`, `archived_raw_product.py`, `src/breezy/ingest/archive_records.py` and `src/breezy/persistence/archive_catalog.py` are on disk (commits `cf33468`, `7a61015`, `0ab94f2`), and the resulting AFOS dataset (N~1820/site) is the basis of `docs/evidence/observation_lock_falsification_2026-08-31.md`. Re-verify every file:line before extending; note §494 calls the schema freeze irreversible on first write. Revised after adversarial peer review by four independent reviewers (architecture, job/refusal machinery, analytical value, citation audit) — 4× APPROVE-WITH-CHANGES, 0 BLOCK. Decisions D1–D12 in §12 record what changed and why.
**Scope:** ingest historical, verbatim NWS CLI text products from the Iowa Environmental Mesonet (IEM) AFOS archive into a **structurally separate** research store, for calibration and out-of-sample validation. Not settlement. Not live.

**Read §0 first.** Every claim about *this repository* carries a `file:line` citation. Claims about the IEM service and about NautilusTrader internals are marked `[UNVERIFIED]` or `[REPO-ASSERTED]` and are not load-bearing without the increment that measures them.

---

## 0. Evidence status, stated up front

| Class | Method | Status |
|---|---|---|
| Breezy source behaviour | Direct read of source | VERIFIED, cited `file:line` |
| Breezy committed evidence docs | Direct read | VERIFIED **as what the repo asserts**, cited |
| Installed `nautilus_trader` 1.231.0 internals | Taken from `persistence/catalog.py:77-86`, `domain/selection.py:3-9`, `FORECAST_INGESTION_PLAN.md:100-115` | `[REPO-ASSERTED]` — re-verify before relying on it for a new decision |
| IEM AFOS coverage 2008→present, throttle policy, service terms, `limit` truncation, corrections retention | Live probe + repo evidence docs | `[UNVERIFIED]` except where a committed evidence doc measures it |
| The `000` failure (`CliStructuralError: unexpected transmission indicator line: '507 '`) | Live probe | **Structurally confirmed**: `normalize/cli_parse.py:442-445` requires `lines[1].strip() == "000"`, verbatim |

### 0.1 The finding that reshapes this plan

IEM CLI retrieval is **not** new work. `scripts/analysis/settlement_alignment_study.py` already:

- builds the AFOS URL, `fmt=zip`, `order=asc`, explicit `limit`, `+2 day` `edate` pad — `:394-405`;
- fetches through a content-addressed on-disk cache keyed on `sha256(url)` with a sleep throttle — `:343-345`, `:359-391`;
- chunks **by station-year** — `year_chunks` `:596-601`, driven at `:617-619` with `limit=3_000`;
- splits multi-product AFOS responses on `\x03` (ETX) and strips the leading numeric transmission line — `split_iem_afos_products` `:436-450`;
- recovers the issuance instant from the zip member filename (`_YYYYMMDDHHMM.txt`) — `:453-457` — falling back to the product's `ISSUED` line `:460-481`;
- parses with **Breezy's own hardened parser** — `:498-503`, `:558-563`;
- runs an **archive-vs-live-catalog validation bridge** — `validate_archive_against_catalog` `:741-825`, comparing `tmax_f` per `(city, climate_day)` at `:798-802`.

It has been **run over 2021-01-01 → 2025-12-31 for all five cities** (`:60-61`), results committed:

- `docs/evidence/settlement_alignment_2026-08-25.md:24-26` — validation bridge **passed**, 36 overlapping final records, **0 mismatches**.
- `:58-73` — over five station-years per city, `archive_parse_error` is **1–2 per city**, `missing_cli_final` **4–17 per city**.
- `docs/plans/archive/GO_LIVE_PLAN.md:108-109` — *"the alignment study drew ~1,800 city-days per site from the IEM archive."*

**Consequences.** (1) The archive's 2021–2025 coverage and parser compatibility are *measured*, not assumed. (2) The `000` problem is already worked around — by **rewriting the product text** (`:449` synthesises `"\n000\n" + body`), which is disqualifying for an ingest path (§4.1). (3) The real novelty is **provenance, storage separation, resumability and refusal**.

### 0.2 The honesty statement this plan must make first

**Backfilling CLI observations does NOT clear REQ-DATA-09, and no document produced by this work may say it does.**

- REQ-DATA-09 is *"Historical backfill of **forecasts + observations + settled outcomes**, sufficient for the model-grade bar (>=2,000 settled pairs...)"* — `docs/plans/TRADING_ENABLEMENT_PLAN.md:117`.
- The Tier-2 bar is *">=400 settled pairs **per traded stratum** and >=2,000 overall"*, calibration *"fitted walk-forward only"* — `:578-581`.
- Historical **forecasts** are unavailable: `docs/evidence/decision_time_clearance_prereg_2026-08-27.md:189-194` pre-registers bindingly that a forecast-based estimator *"cannot be backtested at all in this repository ... it must first accumulate a forecast archive of its own"*.
- Historical **prices** are unavailable and unbackfillable: `docs/plans/archive/GO_LIVE_PLAN.md:109-111` — *"those markets did not exist before 2026, so no vendor can backfill them. Every uncaptured day is permanently lost."* Echoed at `adapters/polymarket_us/data.py:684-688` and `runtime/node_config.py:225-226`.

**What this delivers:** the **observation/label side only** — a ~69,000-product, ~18-year verbatim CLI archive (~34,700 station-days; see OQ-6, which corrects Revision 1's unreconciled "~32,000") and a derived per-station-day truth series. Sufficient to establish climatology, fit and validate an *observation-side* model out-of-sample, and give any future forecast-error model a labelled target. It supplies **one half of a settled pair, never the pair.** REQ-DATA-09 remains open on the forecast and outcome halves.

---

## 1. Null hypothesis: what already exists

### 1.1 REUSED VERBATIM

| Component | Evidence | Why it fits |
|---|---|---|
| The CLI parser | `normalize/cli_parse.py:1-61` | PURE (no I/O, no clock, no `nautilus_trader`), four rejection categories with four consequences (`:20-42`), structural pre-parse gate (`:54-61`), observed-subsection anchoring so a NORMAL/RECORD row can never be read as the observed extreme (`:95-105`), record-qualifier `100R` handling (`:111-123`). Already proven against 2021–2025 archive text. |
| Issuance classification | `normalize/classify.py:77-88` | Discriminator is the `VALID TODAY AS OF ... LOCAL TIME.` line, never `issuanceTime` (`:7-17`). Clock-free, identical live and archived. |
| Correction detection, both signals | `classify.py:32-70`; `cli_parse.py:170-193` (`_CORRECTION_BBB_RE`) | Alphabets pinned identical by `tests/unit/test_normalize_correction_signal_agreement.py`. Positional verdict is the supersession input; free-text is the audit trail. |
| Physical sanity bounds | `normalize/sanity.py` via `cli_parse.py:69` | Runs last, after every field is extracted (`:504`). |
| Station registry | `registry/sites.py:95-115`, `:133-146`, `:341` | Poll by `CLI{cli_location}`; body header validated against the registry pattern, the same guard `build_climate_day` applies (`ingest/records.py:292-297`). |
| Climate-day arithmetic | `normalize/climate_day.py` via `ingest/gaps.py:118`, `ingest/records.py:310-314` | Fixed local-standard offset, never DST. `gaps.py:42-52` names conflating the two clocks as the top risk. |
| Per-station catalog roots, writer lock, read-back verification | `persistence/catalog.py:341-388`, `:391-419`, `:422-508` | Allowlisted components, containment re-check (`:383-386`), symlink refusal (`:380`), `flock` with `O_NOFOLLOW` (`:115-120`), read-back fingerprint verification (`:480-502`). |
| `WriteOutcome` skip semantics | `catalog.py:307-338`, skip branch `:494-496` | *"A successful return from `write_data` does not mean data was written"* (`:310-313`). |
| The disjoint-base convention | `catalog.py:347-348` | *"Enrichment data lives under a disjoint base and never shares a root with settlement data."* |
| Hand-written `Data` subclass pattern | `domain/nws_climate_day.py:1-80` | Explicit `ts_event`/`ts_init`, `to_dict`/`from_dict` by direct subscript (`:288-293`), explicit `schema()`, exactly one module-scope `register_arrow` (`:383-389`), `@customdataclass` refused (`:10-19`). |
| Supersession rule | `domain/selection.py:78-138` (code; `:11-50` is the docstring) | max `(is_final, ts_init, revision_seq)` per `(station, climate_day)`, `is_final` leading. |
| Durable manifest + entry ledger pattern | `ingest/product_index.py:83-113`, `:371-403`, `:501-509` | Manifest FIRST, entry SECOND, so a crash between reads as tampered, not first-seen. |
| IEM URL builder, zip chunking, throttled cache | `scripts/analysis/settlement_alignment_study.py:343-345`, `:359-405`, `:596-631` | §0.1. Proven over 25 station-years. |
| Archive-vs-catalog validation bridge | `settlement_alignment_study.py:741-825` | §4.9's gate is this function, extended. |
| Cache location convention | `scripts/analysis/settlement_alignment_cache.py:8-12` | `~/.local/share/breezy/archive/settlement-alignment-cache`. |
| The `live` pytest marker | `pyproject.toml:46` | Real network I/O deselected by default, needs `BREEZY_LIVE=1`. |

### 1.2 Existing scaffolding that ANTICIPATES this work

- `domain/selection.py:20-22` names this plan's dominating hazard verbatim, before the plan existed: *"`ts_init` is `retrieved_at_ns`, so **a backfill that re-fetches a week of products stamps every one of them `now`** and a re-fetched preliminary would then outrank the final already on disk."* That is why `is_final` leads.
- `catalog.py:682-683` — restated: *"`is_final` leading so that a backfilled preliminary can never shadow a final."*
- `ingest/nws_actor.py:440-444` — a `refetch_known_products` flag exists, documented as *"Backfill / replay-repair mode"*, normally `False`.
- `ingest/gaps.py:949-952` — pass 1 deliberately unbounded by the high-water mark *"or a late backfill would never clear it."*

The repo was designed *around* an eventual backfill. This plan must not undo any of it.

### 1.3 GENUINELY ABSENT

1. **A structural allowlist accepting the real WMO transmission-sequence line.** `cli_parse.py:442-445` hard-requires `"000"`.
2. **A record type whose `ts_init` is not a claim about when Breezy received the bytes.** `NwsClimateDay.ts_init` *is* `retrieved_at_ns`, non-parameterised (`:231-233`), re-checked on decode (`:294-298`).
3. **An identifier for a product with no `product_uuid`.** IEM assigns none; `ProductIntegrityIndex` requires a canonical UUID and refuses otherwise (`product_index.py:117-129`, `:256-274`).
4. **A third catalog root and its non-nesting assertion.**
5. **A resumable, quarantining, yield-gated batch job.**
6. **A blocking verification gate.** `validate_archive_against_catalog` exists but is a study step, not a precondition.

---

## 2. Problem statement

Breezy holds 68 settled weather observations collected since 2026-08-24. The model-grade bar is `>=2,000` settled pairs, `>=400` per stratum (`TRADING_ENABLEMENT_PLAN.md:117`, `:578`). The IEM AFOS archive holds verbatim issued CLI products for the same five stations back to at least 2008 `[UNVERIFIED for 2008–2020; VERIFIED for 2021–2025]`.

Three obstacles:

1. **The parser refuses archived products** (`cli_parse.py:442-445`).
2. **A backfilled row has no honest `retrieved_at_ns`**, and every point-in-time guarantee keys on it (§3).
3. **The grammar changed** over 18 years, risking silent mis-parse rather than loud refusal.

---

## 3. The dominating constraint, worked through

`ts_init` is the axis the design turns on:

- `nws_climate_day.py:20-26` — *"`ts_init` is `retrieved_at_ns` — the instant **Breezy** received the product — and is not a constructor parameter, so it cannot be re-stamped from a clock. Replay order then equals real arrival order."*
- `:231-233`, `:294-298` — stamped once; `from_dict` raises on disagreement.
- `catalog.py:552-617` — `read_climate_day_as_of_settlement` bounds by it, required keyword, runtime `TypeError` on non-`int` (`:603-610`), because *"an optional bound makes correctness depend on every future caller remembering to pass one, and the failure is silent"* (`:566-573`).
- `domain/selection.py:31-43` — bound applied first; ordering chooses only among what had arrived.

### 3.1 What SHOULD `ts_init` be for a backfilled 2015 product?

**Option A — the actual retrieval instant (today).**
*For:* honest; `issuance <= retrieval` holds trivially; no invariant bent.
*Against:* the record is useless for its purpose. A backtest bounded at a 2015 decision instant sees nothing. If it mixes with live data, `selection.py:20-22`'s exact scenario fires. The failure is **not loud** — an as-of query returning `None` looks like a data gap.

**Option B — the original WMO issuance instant.**
*For:* it is the instant the information became public, the operative instant for "could a decision at time T have known this". Breezy's live receipt lag is minutes; over 18 years that is noise.
*Against:* it makes a *false claim in the field whose documented meaning is "when Breezy received it"*. A backfilled row becomes indistinguishable from a live one on the single field the design keys on — silently and permanently. This is what `FORECAST_INGESTION_PLAN.md:1248-1257` (D12) refuses.

**Neither is safe *on `NwsClimateDay`*.** The asymmetry is decisive: A fails loudly and locally; B fails silently and globally — but only *because the record type asserts a meaning the value does not have*. Remove that assertion and B's **provenance** objection evaporates.

### 3.1.1 What does NOT evaporate: the receipt lag (residual, stated)

Option B's "For" clause above says Breezy's receipt lag is "minutes, noise over 18 years." That compares the lag to the **archive span**, which is the wrong scale. The lag matters at the scale of a **decision instant**.

The CLI final issues around 02:27 local. An archived row bounded as-of 03:00 answers *"was this public?"*. The live pipeline's row answers *"did Breezy have it?"*. Those are different questions wearing the same field name. A model fitted on archive-derived as-of answers and then deployed live carries a **systematic look-ahead equal to the receipt lag, in the same direction every time** — the classic backtest-flatters-live failure, and it does not average out.

### MEASURED (I-0, 2026-08-29) — `RECEIPT_LAG_2026-08-29.md`

The catalog's 132 records split cleanly into two populations, separated by a **39,248-second empty interval** (so the cut is observed, not chosen): 76 rows of post-restart `recovery_ingestion` (products fetched days after issuance during the 2026-08-24 cold start) and **56 rows of `steady_state` routine polling**.

| Population | n | min | p50 | p95 | max |
|---|---:|---:|---:|---:|---:|
| **steady_state — the plan-relevant figure** | 56 | 115.7 s | 355.8 s | **895.7 s (14.9 min)** | 1195.6 s (19.9 min) |
| recovery_ingestion — not a latency measure | 76 | 40,443.9 s | 328,559.6 s | 598,676.4 s | 603,775.8 s |

**Revision 1's "minutes" characterisation was right, and this section's earlier challenge to it was wrong on magnitude.** Steady-state receipt lag is **~6 minutes median, ~15 minutes at p95, ~20 minutes worst observed**. Issuance was derivable for all 132 rows from the WMO heading; zero negative lags.

**What that does and does not change.** The structural point stands unaltered: archived `ts_init` and live `ts_init` are different clocks, and a merged replay is mis-ordered by the difference. But the *magnitude* is ~15 minutes, and the settlement decision window is hours wide (CLI final issues ~02:27 local; settlement is 08:00 ET next-day). So:

- For **settlement-window** decisions, a 15-minute lag is immaterial — it cannot move an as-of answer across that boundary.
- For any strategy acting **within minutes of issuance**, it is decisive, and the offset must be applied.
- A pooled figure would have been badly misleading. An earlier draft of this measurement reported p95 = 567,236 s (6.6 days) by mixing recovery rows into the estimate; that number is superseded and must not be cited.

**Caveat, stated:** n=56 over five days is a provisional measurement, not a long-run service level. It is above the n<20 threshold at which it would not have been worth writing down at all, and it should be re-measured once the collector has a longer uninterrupted run.

Three consequences, all binding:

1. **The lag is measured, not assumed.** Done: see the table above. Any future re-measurement supersedes it in place.
2. **Any decision-time study on archived data applies an explicit, documented lag offset.** §4.4 requires it; a study that bounds on raw issuance instants is wrong by construction.
3. **The two streams are NOT orderable in one replay without that adjustment.** This promotes OQ-7 / I-7 from "not casual" to **semantically invalid as-is**: the two `ts_init` columns are on different clocks, so a merged replay is mis-ordered by the lag regardless of how carefully the merge is written. Barrier 1's runtime refusal of a merged list (§4.4) is therefore not merely defensive — it is enforcing a real semantic incompatibility.

This is a residual the design does not remove. It is made **visible and quantified** rather than assumed away.

### 3.2 Decision

> **A NEW record type, `ArchivedClimateDay`, whose `ts_init` is the WMO issuance instant, carrying the real retrieval instant as a separate audit field, written to a THIRD disjoint catalog root, produced by a process that never touches settlement state.**

Four barriers, ranked by what each survives that the others do not. **This list and §4.8's are the same four** — an earlier draft disagreed with itself, listing provenance fields as a barrier. They are not one; they are an audit trail, and counting them inflated the total.

1. **Type — strongest by a distance, and RUNTIME-enforced.** `ArchivedClimateDay` is a distinct `Data` subclass and explicitly **not** a subclass of `NwsClimateDay`. Beyond the static typing of `read_climate_day_as_of_settlement` / `read_climate_days` (`catalog.py:511-534`, `:552-617`), the enforcement is live: `catalog.py:936`'s `_read` isinstance check and `selection.py:83-92`'s `_require_unwrapped` both raise on a foreign type. This survives an operator pointing the wrong path at the wrong base, a hand-copied parquet file, **and a merged in-memory list** — none of which a root-only separation survives. See §4.4 for why it must be duplicated rather than generalised.
2. **Import-linter `forbidden` contract.** The only barrier that fires on *new code at CI time* rather than at runtime on a path someone had to execute first. §4.8.3.
3. **Root.** `BREEZY_ARCHIVE_CATALOG_BASE`, disjoint from `BREEZY_CATALOG_BASE` (`runtime/settings.py:52`), with a startup assertion that neither nests inside the other in **either** direction. Survives deployment and operator error; adds little the type barrier does not once the code is correct.
4. **Process.** An operator-run batch job outside the collector. Never opens the settlement `StateStore`, never constructs a `SettlementGate`, never takes a settlement writer lock. Survives concurrent-writer and gate-state corruption — but R-1 is a *code* hazard, not a process one, so this is weakest against the stated threat.

**Not a barrier, deliberately listed apart:** the provenance fields `archive_retrieved_at_ns`, `archive_source_url` (redacted), `archive_job_version`, `issuance_time_source`. They make a violation *diagnosable after the fact*. They prevent nothing.

**On barrier 4 and the `breezy-quote-tape` precedent.** `FORECAST_INGESTION_PLAN.md:681-687` *dropped* that precedent because the forecast poller's mitigation was reading and writing gate-owned state. **It transfers here for the opposite reason:** this job shares nothing a second writer could corrupt — no gate, no `SqliteStateStore`, no station root. A reviewer should check this reasoning specifically; it is the plan's most load-bearing borrowed conclusion.

### 3.3 The cost of a distinct type, stated

A second ~22-field Arrow schema, a second `register_arrow`, a second strict decoder, and an obligation on calibration scripts to read two types. Accepted, because the alternative is a shared type discriminated by a free-text field — a convention, not a structure, and `write_records` would accept it into the settlement root.

The schema is **irreversible on first write**: `make_strict_decoder` rejects any fragment whose column set differs in either direction, and a second `register_arrow` is forbidden (`nws_climate_day.py:16-19`). The field set freezes on evidence, not inspection — see I-2's review bar.

---

## 4. Design

### 4.1 The `000` accommodation

#### Options

**O-1. Normalize archived text to `000` before parsing — REJECTED.** This is `settlement_alignment_study.py:449`. Fine for a study, disqualifying for ingestion: the digest is then over **Breezy-manufactured text**. `NwsRawProduct`'s contract is *"the verbatim, immutable archive of one fetched NWS product"* with `raw_sha256` *"over the product text itself"* (`nws_raw_product.py:1`, `:10-16`, `:183-188`).

Corroborating: the same file already computes **two different digests for "the same" product** — `:523` hashes rewritten text, `:583` hashes verbatim text. Two digest bases, one file. That is the defect class not to inherit.

**O-2. A `transmission_indicator=` parameter on `parse_cli_product` — REJECTED.** A per-call lever on the settlement parser, reachable from the live path. Same objection as `FORECAST_INGESTION_PLAN.md:407-412`.

**O-3. Delete the line-1 check — REJECTED.** A real cheap shape gate.

**O-4. Widen from the literal `"000"` to a digits-only transmission sequence, and CARRY the value — RECOMMENDED.**

#### The change

In `check_structural_allowlist` (`cli_parse.py:392-473`), replace the equality at `:442` with an anchored digits-only match, and add the value to the returned `CliStructuralHeader` (`:473`) so it becomes provenance.

- Anchored `\A...\Z`, **never `$`** — `$` also matches before a trailing newline; the sibling case uses `.match` (`:447`). The `.strip()` masks this today; the comment must say why `\Z` is still required.
- Bounded length (1–6 digits).
- **Nothing else moves.** The WMO abbreviated-heading check (`:447-451`) and AWIPS PIL equality check (`:461-471`) are the actual addressing guards and are untouched. `"000"` is not a security property; it is an artefact of the live API normalising the sequence. The PIL check proves the product is ours.

#### The equivalence test — the backfill's whole premise

The provable claim is **not** identical records — bytes differ, so `raw_sha256` differs. It is:

> For the same transmission, the **live** form (`000`) and the **archived** form (`507`) parse to a `ParsedCliProduct` **equal field-for-field**, with the same `classify_issuance` verdict and the same `is_correction_bbb` verdict.

A committed golden fixture **pair** under `tests/fixtures/` — one real live-API product body and its IEM counterpart for the *same* product. Assertions:

1. `parse_cli_product(live, ...) == parse_cli_product(archived, ...)` field by field.
2. `classify_issuance(live) == classify_issuance(archived)`.
3. `sha256(live) != sha256(archived)`, **asserted explicitly**, with a comment that the digest is byte-level and this inequality is correct.
4. The new transmission-sequence field is `"000"` for one and `"507"` for the other.

Assertion 3 kills the O-1 mutant: any implementation normalising archived text before hashing makes the digests equal and fails.

### 4.2 The record types

`breezy/domain/archived_climate_day.py`, `breezy/domain/archived_raw_product.py`. Both follow `nws_climate_day.py:1-80` exactly, with its reasons *restated*, not cross-referenced.

#### `ArchivedClimateDay` — fields

| Field | Type | Note |
|---|---|---|
| `station` | `str` | Registry `cli_location` (`sites.py:111`, inside the `SettlementSite` dataclass). Never parsed from text. |
| `climate_day` | `date` | `ParsedCliProduct.summary_date`. Same name as live deliberately — same concept, the join key. |
| `tmax_f`, `tmin_f`, `tavg_f` | `int \| None` | Whole °F as published. `tavg_f` **never computed** — `nws_climate_day.py:126-131`. |
| `tmax_flag`, `tmin_flag`, `tavg_flag` | `str \| None` | Same `MISSING_VALUE_FLAGS` exclusivity as `:355-380`. |
| `is_final` | `bool` | From `classify_issuance` on verbatim text — derived, never passed (`ingest/records.py:305-308`). |
| `correction_flag` | `bool` | Free-text superset, `classify.has_correction_evidence`. |
| `is_correction_bbb` | `bool` | Positional verdict. Stored **separately** because `classify.py:59-66` documents them as deliberately different in coverage. Live collapses them; the archive should not, since §4.5 makes the BBB signal load-bearing. |
| `revision_seq` | `int` | Monotonic per `(station, climate_day, is_final)`, from 1, by issuance order within the batch — §4.5. |
| `issuing_office` | `str` | From the WMO heading. |
| `wmo_transmission_sequence` | `str` | The value §4.1 carries instead of discarding. Audit trail for the whole accommodation. |
| `wmo_bbb_token` | `str \| None` | As parsed. |
| `issuance_time_ns` | `int` | **Becomes `ts_init` and `ts_event`.** Source: zip-member filename (`settlement_alignment_study.py:453-457`), falling back to the `ISSUED` line (`:460-481`). If **neither** resolves, the product is **quarantined, never written** — an unstamped archived record has no defensible position in a replay stream. |
| `issuance_time_source` | `str` | `"wmo_filename"` or `"issued_line"`. Two derivations exist; which was used must be in the data. |
| `archive_retrieved_at_ns` | `int` | The **real** fetch instant. Never `ts_init`. |
| `archive_source_url` | `str` | Redacted via `ingest/http.redact_url` (`ingest/records.py:220`). |
| `archive_job_version` | `str` | Batch-job provenance. |
| `parser_version`, `registry_version` | `str` | `PARSER_VERSION` is `"breezy.normalize.cli_parse@0.1.0"` (`test_backfill_dependency_pin.py:66`); `registry_version` from `sites.py:341`. **The same parser version as live** — the point of §4.1. |
| `raw_sha256` | `str` | Digest of the **verbatim** archived text. Joins to `ArchivedRawProduct`. |
| `station_year_yield` | `float` | The per-station-year admission yield (§4.7) this row was admitted under. **Added in Revision 2 and load-bearing.** §4.7 and OQ-3 make admission yield and era the *sample-selection covariates* for anything fitted on this data — exactly the values a later bias analysis needs per row. Because the schema is irreversible on first write (§3.3), a field omitted now can never be added; without it the bias correction is forever a join against a Markdown evidence doc. |
| `admission_era` | `str` | `"modern"` (2008+) or `"transitional"` (2003–2007, admitted only per OQ-3). Derivable from `climate_day.year`, stored explicitly so an era-labelled stratum cannot be assembled by accident. |
| `schema_version` | `int` | Forensics only; **not** a compatibility mechanism (§3.3). The docstring must say so in those words. |
| `ts_event` | `int` | `= issuance_time_ns`. |

**Constructor invariants** (constructor is also the decode path — `nws_climate_day.py:51-56` — so *field* invariants only):

- `ts_init == ts_event == issuance_time_ns`, neither a constructor parameter; `from_dict` raises on disagreement (`:294-298`).
- `issuance_time_ns <= archive_retrieved_at_ns` — the archived analogue of `nws_raw_product.py:193-199`.
- `revision_seq >= 1`; `tmin_f <= tmax_f` when both present; value/flag exclusivity both directions.
- **No** `is_final` classification guard, **no** `ts_event <= ts_init` check — vacuous when both are the issuance instant.

**Explicitly NOT a subclass of `NwsClimateDay`.** A pinned test asserts `not issubclass(...)` both directions. A subclass would satisfy any downstream `isinstance` check and silently re-open barrier 1.

#### `ArchivedRawProduct`

Same shape, holding `raw_text` verbatim with `raw_sha256` recomputed at construction (`nws_raw_product.py:183-188`) and `verify_digest()`. **No `product_uuid`** — IEM assigns none, inventing one is false provenance and is refused by `product_index.py:256-274`. Identity is `(station, issuance_time_ns, raw_sha256)`, the archive's own dedupe shape (`nws_raw_product.py:15-17`).

Storing raw text is not optional: it is the only way to re-derive a record after a parser change without re-fetching, and it is the quarantine/audit substrate for §4.7. ~32,000 × ~4 KB ≈ 130 MB before parquet.

#### Topic-prefix hazard

`runtime/backtest_feed.py:116-120` records that `is_matching_py("data.NwsClimateDayExtra*", "data.NwsClimateDay*")` is `True`. The archived types share no prefix with the live ones — asserted by a named test, not a note.

#### Builder parity

`breezy/ingest/archive_records.py::build_archived_climate_day` mirrors `ingest/records.py:225-330`, reusing `classify_issuance`, the `body_header_regex` re-check (`:292-297`) and `_value_and_flag`. A test feeds one `ParsedCliProduct` to **both** builders and asserts the settlement fields are equal. That stops the schemas drifting semantically.

### 4.3 Storage — the third root

`archive_catalog_path(base, venue, city)` reuses `station_catalog_path` (`catalog.py:341-388`) unchanged; only `base` differs. All path-safety machinery applies verbatim — allowlisted components, containment re-check (`:383-386`), symlink refusal (`:380`), post-`mkdir` `lstat` (`:416-417`).

**Startup assertion, both directions:** the archive base must not be, be inside, or contain the settlement base — resolved paths, `is_relative_to` both ways. Fatal at job start, before any fetch.

The job runs its own writer-lock filesystem support check against the archive base; the collector's precondition check covered only the settlement base.

### 4.4 Reading

One accessor, `read_archived_climate_days(catalog, *, station, start=None, end=None)`, and one selection helper mirroring `select_climate_day`'s ordering — max `(is_final, ts_init, revision_seq)` per `(station, climate_day)` — with `ts_init` now meaning publication. **`is_final` still leads**, for the reason `selection.py:20-22` gives.

**DUPLICATE THE ORDERING; NEVER GENERALISE IT.** `selection.py:11-50` is *docstring*. The code is `_ordering` (`:78-81`), `_require_unwrapped` (`:83-92`) and `latest_by_climate_day` (`:94-138`) — and `_require_unwrapped` is a **runtime** `isinstance(record, NwsClimateDay)` gate that raises `TypeError` on anything else.

That makes barrier 1 stronger than §3.2 first claimed: it is runtime-enforced, not merely a type annotation, and it already refuses a **merged** list — `latest_by_climate_day(live + archived)` raises. It also makes this the single most dangerous seam in the plan. The cheapest way to satisfy a naive "reuse the ordering" instruction is to widen `_require_unwrapped` to `(NwsClimateDay, ArchivedClimateDay)` or to generalise it over a Protocol. **That one edit deletes the runtime half of barrier 1 and legalises the merged stream the whole design exists to prevent.**

Therefore `breezy.domain.archived_selection` carries its **own** `_ordering` and `_require_unwrapped`, isinstance-gated on `ArchivedClimateDay`. `selection.py` is not touched, not parameterised, and not imported by the archived path. §7 pins both directions.

**No unbounded settlement-shaped accessor is built.** There is deliberately no `read_archived_climate_day_as_of_settlement`; the name would invite the misuse §4.8 forbids. Research callers pass explicit bounds and own their walk-forward discipline, which `TRADING_ENABLEMENT_PLAN.md:579-580` requires anyway.

### 4.5 Corrections

Whether IEM preserves corrections is *inferred* from its transmission-level design, not proven — no CCA product appeared in any probe.

**This is answerable today at zero network cost**, because the study already cached 25 station-years of AFOS zips (`settlement_alignment_cache.py:8-12`). `[UNVERIFIED: whether that cache is still populated on this host.]`

**Increment I-0 — the correction probe.** Read-only, no `src/` change. For each cached station-year, report:

1. Products per `(station, climate_day, issuance_class)`. Any FINAL count > 1 is a candidate correction.
2. Of those, how many carry a `CCx` BBB token, how many carry free-text evidence only, how many neither.
3. Whether the later product's values differ from the earlier.
4. Distribution of `(later.issuance_time_ns - earlier.issuance_time_ns)`.
5. Products whose issuance instant resolves from neither source.
6. Per-year: total, parseable, distinct climate days with a parseable FINAL, and each rejection category separately.

### 4.5.1 MEASURED (I-0, 2026-08-29) — the answer, and it is not the one the plan expected

`ARCHIVE_CORRECTION_PROBE_2026-08-29.md`, over 25 station-years of cached AFOS zips:

| Quantity | Measured |
|---|---|
| Duplicate-FINAL candidate groups | **469** (5.16% of 9,096 parseable final station-days; Wilson 95% CI 4.72–5.63%) |
| Later-product pairs within those groups | **496** |
| Pairs carrying a `CCx` BBB token | **14** |
| Pairs carrying free-text correction evidence only | **1** |
| Pairs carrying **neither** signal | **481** |
| Pairs whose parsed `tmax_f`/`tmin_f`/`tavg_f` **differ** | **12** |
| Pairs byte-different but **value-identical** | **472** |
| Products with no resolvable issuance instant | **0** |

**Three conclusions, in order of consequence.**

1. **The archive is NOT lossy for corrections. OQ-1 resolves in the favourable direction.** 14 `CCx`-tokened pairs and 12 value-changing pairs are present in the archive. Revision 1's working assumption ("assume NO until I-0 proves otherwise") is refuted by measurement, and the §4.5 language inviting a "the archive is lossy" finding is withdrawn. D9's requirement stands and is satisfied: the comparison against the live 1-of-8 rate is reported with its interval and **not** asserted as lossiness.
2. **A finding the plan did not anticipate: 472 of 496 duplicate finals are byte-different but semantically identical retransmissions.** Roughly 95% of duplicate-FINAL groups are *not* corrections at all. This is a real design input, not trivia — the archive identity `(station, issuance_time_ns, raw_sha256)` treats each retransmission as a distinct row, so ~5% of final station-days will carry multiple stored records that mean the same thing. `revision_seq` and the `max(is_final, ts_init, revision_seq)` ordering handle it correctly (the latest wins, and it is value-identical anyway), so **no design change is required** — but the storage estimate and any per-row count must expect it, and §4.9's V-1 must not treat a value-identical duplicate as an anomaly.
3. **Issuance-instant recovery is 100% effective** on this cache. §4.2's quarantine path for unresolvable issuance instants is therefore correct to keep but is expected to be empty in the modern era.

**The pre-measurement reasoning is retained below for audit.**

**A negative answer is a finding, and a consequential one.** The live catalog shows MDW with `corrected_finals=1` across ~9 site-days (`settlement_alignment_2026-08-25.md:32`). If the archive shows ~0 across ~1,800 station-days, both cannot be representative, and the strong reading is that **the archive is lossy for corrections**. The plan must then state, in the record docstring and every derived evidence doc, that an archived "final" is *final-as-first-transmitted*, and any calibration on it inherits that bias.

**`revision_seq` works either way.** Within one `(station, climate_day, is_final)` group, sort by `issuance_time_ns` ascending, assign 1, 2, 3…, ties broken by `raw_sha256`. No corrections means every group has one member and every `revision_seq` is 1 — correct, not degraded.

### 4.6 Batching, throttling, resumability, idempotency

**Batch unit: one `(station, calendar year)`.** 5 × 19 years (2008–2026) = **95 requests**, not 32,000. Reuses `afos_url` (`:394-405`) and `year_chunks` (`:596-601`).

**Truncation guard — a real hazard the existing code does not check.** `afos_url` takes a `limit` (`:394`, driven at `:618` with `3_000`). A station-year holds ~732 products, so it is not binding — but a response returning *exactly* `limit` was silently truncated, and the missing products are indistinguishable from missing days. **Assert `count < limit`; equality aborts the year.**

**Throttle.** ≥1.0 s between requests, a descriptive `User-Agent` with operator contact (`settlement_alignment_study.py:55-58`), and a hard per-run request cap. 95 requests ≈ 2 minutes. NWS products are public domain; **IEM's own terms are `[UNVERIFIED]` and must be read and recorded in I-3's evidence doc**.

**Fetch idempotency by construction.** Content-addressed cache keyed on `sha256(url)` (`:343-345`, `:374-391`). A re-run never re-fetches a cached year.

**Durable ledger.** A per-`(station, year)` state machine — `PENDING → FETCHED → PARSED → WRITTEN` — with the zip's `sha256` and parsed/written row counts at each transition. Stored in **SQLite under the archive base**, never the settlement state DB. Manifest-first-entry-second ordering copied from `product_index.py:501-509`.

Interruption: `PENDING` → refetch; `FETCHED` → reparse from cache, no network; `PARSED` → re-attempt write and reconcile; `WRITTEN` → skip.

**Write idempotency — a deliberate policy inversion.**

`write_records` silently skips an exact `ts_init`-range collision and reports it in `WriteOutcome.skipped` (`catalog.py:307-338`, `:494-496`). `nws_actor.py:892-898` records this costing a real record in production and mandates *"One batch, one write, one parquet file per type covering that range"*, routing any skip to `record_write_integrity_violation`, CRIT, hard-block.

The backfill **must invert that, narrowly and loudly**:

- One `write_records` call per `(station, year, record type)`, rows sorted ascending by `issuance_time_ns` so `_require_non_decreasing` (`catalog.py:474-475`) is satisfied. Consecutive years' ranges do not overlap.
- On non-empty `skipped`: **always attempt read-back reconciliation first. Never gate the reconciliation on ledger state.**
  - Read back the range, recompute row count and per-row fingerprints, and compare against what *this* job instance would have written.
  - **Match** → benign. Mark the ledger `WRITTEN` (idempotently) and continue, whatever the ledger said before.
  - **Mismatch** → **integrity event**. Abort non-zero. Something else wrote that range.

**Why the ledger must NOT gate the reconciliation.** An earlier draft said "ledger says `WRITTEN` → benign, otherwise → abort." That is backwards, and it inverts the very precedent it cites. `write_records` writes the parquet and verifies it **first** (`catalog.py:422-508`); the ledger transition to `WRITTEN` is a **later**, separate durable write. So the crash window sits between a completed payload and an unwritten claim:

> Job writes the parquet successfully → crashes → ledger still says `PARSED` → restart re-attempts the write → range already on disk → `skipped` non-empty → the old rule **hard-aborts a completely benign single-writer resume.**

`product_index.py:501-509`'s manifest-FIRST/entry-SECOND ordering works because the *claim* is durable before the *payload*, so a crash in between reads as tampered. Here the ordering is reversed — payload first, claim second — so every crash in the window produces a **false-positive abort**, not a false-negative accept. Fingerprint comparison is the only signal that distinguishes "my own interrupted run" from "a foreign writer", and it is available unconditionally.

**Ledger loss or corruption.** If the ledger is deleted, corrupted, or absent on a fresh checkout while parquet already exists, every completed station-year defaults to `PENDING`, re-fetches from the content-addressed cache (wasted, harmless, no network), re-parses, and lands in exactly the reconciliation path above — which now resolves it correctly instead of aborting. The ledger is therefore a **performance and audit** structure, not the root of trust; the catalog plus fingerprints is. I-3 additionally builds `--rebuild-ledger`, which re-derives `WRITTEN` markers from existing parquet ranges and fingerprints without fetching. §7 pins "ledger absent, parquet present".

**Ledger durability.** SQLite in WAL mode with `synchronous=FULL`, and the `WRITTEN` transition in a single transaction. I-3 also extends `assert_writer_lock_filesystem_supported` to the archive base before creating the ledger, since the plan's existing precondition check covered only parquet roots.
- Records sharing one `issuance_time_ns` (NWS publishes at minute granularity — `nws_raw_product.py:117-118`) are ordinary, handled by the single-call rule.

This is the one place the plan diverges from a settlement rule, and it must be stated that loudly in the job docstring and in review.

### 4.7 Format drift, refusal, quarantine

A 1998 probe returned a pre-modernization free-text format (`HIGH YESTERDAY......... 90`) the parser cannot read; a 2003 probe returned the modern tabular format. Between them lies an unmapped boundary.

**The parser already fails closed** — four rejection categories with four consequences (`cli_parse.py:20-42`), a structural gate ahead of every regex (`:54-61`), observed-subsection anchoring (`:95-105`). The backfill preserves that.

**Quarantine, not drop.** Every product raising `CliStructuralError`, `CliContentError`, `CliSanityError` or `ClassificationError` is written to `<archive_base>/quarantine/<station>/<year>/` as **verbatim bytes plus a JSON sidecar** naming exception type, message, station, year, source URL, zip member. Nothing is silently discarded. `CliNotOurProductError` is **not** quarantine — it is the routine sibling-PIL case (`:464-471`) — but it is counted separately, and a non-zero count under a PIL-scoped query is itself a finding.

**A per-year YIELD FLOOR — the control that actually matters.** A parse-error alarm is insufficient: the dangerous year is one where 60% of days parse and 40% do not, producing a **non-random subsample** that biases everything fitted on it.

- Compute per `(station, year)`: `days_with_parseable_final / calendar_days_in_year`.
- Below the floor, the year is `DEGRADED` and **nothing from it is written**. All-or-nothing per station-year.
- **MEASURED (I-0, 2026-08-29, `ARCHIVE_CORRECTION_PROBE_2026-08-29.md`).** Across **25 station-years** (5 stations × 2021–2025) the single-year yield distribution is **min 0.9836 / median 1.0000 / max 1.0000**. Every station-year clears 0.95, and the worst is SFO 2021 at 0.9836. So **0.95 is supported as a floor but is loose** — it sits ~3 points below the observed worst case and would admit a year materially worse than anything yet seen. D5 is resolved: the floor is now evidence-backed rather than a placeholder, and §12/D5's open item is closed for 2021–2025. **The floor stays at 0.95 for the 2008–2020 era, which remains unmeasured**; tightening toward ~0.98 should be decided at I-5 once those years are measured, not now on five years of the easiest era.
- Historical note, superseded: the value below was Revision 1's reasoning before I-0 ran.

- Proposed floor: **0.95 — a PLACEHOLDER, not yet supported by the cited evidence.** The counts at `settlement_alignment_2026-08-25.md:58-73` (`missing_cli_final` 4–17 per city, `archive_parse_error` 1–2) are aggregated over **five** station-years, not one. Worst city is SFO at (1825−18)/1825 ≈ **0.9901 as a five-year average**. Concentrate those same 18 bad days into a single calendar year and that year's yield is (365−18)/365 ≈ **0.9507** — barely clearing the proposed floor. The evidence supports ~0.99 as an *average*; it does not establish 0.95 as a *single-year* floor, which is the statistic the gate actually applies.
- **I-0 sets the number.** The floor is locked only after I-0 publishes the per-station-year yield distribution (§6). Until then no increment may cite 0.95 as measured.

**Intra-year completeness — the floor alone is not sufficient.** A station-year can clear any annual threshold while one whole month is systematically absent, which biases every seasonal or threshold-conditioned calibration built on it. The annual ratio cannot see this. I-0 therefore also reports per-station-**month** parseable-final counts, and the admission gate applies a per-quarter completeness sub-check in addition to the annual floor. This closes the gap that V-3 alone would have to catch — and V-3 is not blocking (§4.9).

**MEASURED (I-0, 2026-08-29): the hazard does not materialise in 2021–2025.** 21 station-months were flagged as low-count; the **largest gap in any month is 3 days** (MIA 2025-04, NYC 2025-06, SFO 2025-04), and **no month is missing or near-missing**. So the per-quarter sub-check finds nothing to refuse in the modern era.

That is a reason to keep the control, not to drop it. It is now known-cheap (it fires on nothing in five clean years), and the era it was designed to protect against — 2008–2020, and especially the 2003–2007 transitional band — is exactly the era still unmeasured. A completeness control validated only where it never fires has not been tested; I-5 is where it earns its place. D6 stands.

**Between-year selection is a residual, and it is NOT closed by this control.** All-or-nothing admission removes within-year bias by relocating it to which *years* are admitted. If transmission garbling, special bulletins, or station outages correlate with severe weather — plausible, and precisely the tail the bot prices — then the dropped years are systematically the extreme ones, and the admitted sample is unrepresentative in the direction that matters most. Nothing in this plan measures that. I-5 must report the `DEGRADED`-year rate against an independent severe-weather indicator for the same station-years before any calibration treats the admitted sample as representative. Stated as an open residual, not a solved problem — see R-3.

**Era guard, in code.** Any year `<= 2002` refused before any network call. 2008–present admitted by default. **2003–2007 refused by default, admitted only per-year, per-station, on a measured yield clearing the floor** — and any stratum from those years must be era-labelled, because "opportunistic" data mixed unlabelled into a calibration sample is indistinguishable from good data afterwards.

**Reporting.** Every run emits an evidence doc with per-station-year: products seen, parsed, quarantined by exception type, `CliNotOurProductError` count, distinct climate days with a FINAL, realised yield, admit/`DEGRADED` verdict.

### 4.8 May backfilled data ever settle a live position?

**No. Never. Research and calibration only.** Four structural levels:

1. **Type.** The settlement readers are typed on `NwsClimateDay` and cannot return an `ArchivedClimateDay`, which is not a subclass (pinned test).
2. **Root.** Disjoint base + bidirectional non-nesting assertion. The collector never opens the archive base.
3. **Import-linter `forbidden` contract.** The layers contract does **not** cover this: `breezy.settlement` sits above `domain` (`pyproject.toml:59-71`), so `breezy.settlement -> breezy.domain.archived_climate_day` is *legal* under `layers`. A dedicated `forbidden` contract is therefore genuinely required, with `source_modules = ["breezy.settlement", "breezy.strategy", "breezy.ingest.nws_actor", "breezy.runtime.backtest_feed"]`.

**The contract must run indirect-STRICT, and that forces a module split.** `forbidden` defaults to `allow_indirect_imports = False` (the existing nautilus contract sets it explicitly at `pyproject.toml:88`). An earlier draft put the archived readers in `breezy.persistence.catalog` — but `ingest/nws_actor.py:188` imports that module, so `nws_actor -> persistence.catalog -> domain.archived_*` is an indirect chain and the contract would fail on day one. Setting `allow_indirect_imports = true` clears the failure while silently degrading the contract to direct-imports-only — much weaker than this section advertises.

Therefore the archived readers live in a **new `breezy.persistence.archive_catalog` module**, which nothing on the settlement path imports. The contract then runs in its strong, indirect-strict form with no collateral. `allow_indirect_imports` is stated explicitly (omitted, i.e. `False`) rather than left to a default a future reader must look up. §7 pins the **indirect** chain, not just a synthesised direct import.
4. **Process.** Not in the live process; no entry point the collector can reach.

**The one legitimate adjacent use.** `validate_archive_against_catalog` (`:741-825`) compares archive against live catalog and reports `blocked: validation_mismatch` on disagreement (`:804-813`). Legitimate because it **flags**; it never substitutes. Using archived data to *dispute or restate* a venue settlement is a non-goal (§8).

### 4.9 Verification

**V-1 — Re-parse determinism (free).** Re-parse every admitted product from its stored `raw_text`, assert field equality against the written record. Catches a parser change between fetch and write, and builder transcription errors. `verify_digest()` on read catches storage corruption.

**V-2 — Live-overlap cross-check (cheap, strongest). BLOCKING.** For every `(station, climate_day)` in **both** the live catalog and the archive, assert equality of `tmax_f`, `tmin_f`, `tavg_f` **and** their sentinel flags. This is `validate_archive_against_catalog` (`:790-802`) extended from `tmax_f` alone to the full tuple, and promoted from study step to **precondition for writing anything**. Any mismatch aborts.

Its power is demonstrated: the bridge ran and **passed with 36 overlapping records and 0 mismatches** (`settlement_alignment_2026-08-25.md:24-26`). The overlap window grows every day the collector runs, so this check strengthens monotonically for free.

**V-3 — Distributional sanity (cheap, catches systematic mis-parse).** Per station-year: admitted-day count, counts by sentinel flag, monthly mean `tmax_f` against neighbouring years. A systematic climate-day off-by-one, or a NORMAL row read as the observed extreme, shows as a shifted seasonal curve — a mis-parse V-1 cannot see because it is *deterministically* wrong.

**V-4 — NCEI / GHCN-Daily tripwire (optional, FLAG-ONLY, LAST).** Three mandatory constraints:
- **Flag-only, never a settlement or correction input.** A GHCN value is a *derived* product; the bot refuses derived values in the same terms `nws_climate_day.py:126-131` refuses computing `tavg`.
- **Tuned for systematic breaks, not per-day disagreement.** US GHCN TMAX round-trips through tenths of °C, so small per-day disagreement is *expected*. Fire on an anomalous station-year rate, or a lag-1 correlation spike (the signature of a whole-year off-by-one).
- Adds a second third-party host and dependency. Ranked last, genuinely optional.

### 4.10 pyiem: retrieval, parsing, both, or neither?

**Recommendation: NEITHER.**

**Not for parsing — decisive.** The premise is §4.1's equivalence claim, which is only meaningful if **the same parser** produces both forms. Parsing archived text with pyIEM and live text with `cli_parse` makes the equivalence untestable in principle. `test_backfill_dependency_pin.py:53-58` already states where protection comes from: *"the golden-parse fixtures in `test_normalize_cli_parse.py`, which pin `cli_parse.py`'s own behaviour directly."*

**Not for retrieval.** One URL and one zip walk, already written and proven across 25 station-years. pyIEM is a large dependency for that.

**Consequences:**

- `pyproject.toml:36`'s `backfill = ["pyiem==1.27.0"]` becomes **dead** and should be removed.
- `tests/unit/test_backfill_dependency_pin.py` should be **updated, not deleted** — its docstring (`:60-63`) invites exactly this. Convert to a **negative pin**: assert (by the AST technique at `:69-89`) that **no** module under `src/breezy/` or `scripts/backfill/` imports `pyiem`.
- Removing a published extra is operator-visible. Flagged as OQ-4.

---

## 5. Layering

`pyproject.toml:51-81`, `exhaustive = true` (`:72`). **No new top-level package** — `FORECAST_INGESTION_PLAN.md:252-255` established that it fails `lint-imports` immediately.

| Module | New imports | Direction | Legal? |
|---|---|---|---|
| `breezy.normalize.cli_parse` (edit) | none | — | Yes |
| `breezy.domain.archived_climate_day` (new) | `pyarrow`, `nautilus_trader.core.data`, serializer, `domain.validation`, `domain.strict_arrow` | within `domain` | Yes, **one** forbidden-nautilus `ignore_imports` entry, identical in kind to `:104-105`. `disallow_subclassing_any` at `:201` already wildcards `breezy.domain.*`: **no mypy edit** |
| `breezy.domain.archived_raw_product` (new) | same | within `domain` | Yes; **one** more entry |
| `breezy.ingest.archive_records` (new) | `domain.archived_*`, `normalize.{cli_parse,classify}`, `registry.sites` | downward | Yes, no change |
| `breezy.persistence.catalog` (edit) | `domain.archived_*` | downward | Yes (already holds `:108`) |
| `breezy.domain.archived_selection` (new) | `domain.archived_climate_day` | within `domain` | Yes |
| `scripts/backfill/` (new, **outside `breezy`**) | `httpx`, `breezy.*` | not import-linted (`root_packages = ["breezy"]`, `:52`) | Yes; add `"scripts/backfill"` to mypy `files`, alongside `"scripts/analysis"` (`:176`) |

### 5.1 Why retrieval lives in `scripts/backfill/`

`HttpTransport` cannot express this request and must not be made to. `DEFAULT_ALLOWED_HOSTS` is *"The only host this process may fetch settlement data from"*, and the AFOS endpoint is query-string driven, which the transport's two typed fetch methods cannot express. The two ways to force it in are a query-string lever on the shared hardened `_fetch` (refused, `FORECAST_INGESTION_PLAN.md:407-412`) or a second transport module (refused, `:257-260`).

Keeping retrieval in `scripts/` yields a **stronger** property: **the live process contains no code path that can reach `mesonet.agron.iastate.edu` at all.** That is what `settlement_alignment_study.py:1-7` already relies on. This job *does* write — to a **disjoint** catalog.

**The honest cost:** `scripts/` is not import-linted, so nothing structurally stops a script importing upward. Mitigation is partial: `breezy` cannot import `scripts.backfill` (asserted by test), and `scripts/backfill` is typechecked. A weakened guarantee, stated rather than hidden.

### 5.2 Net `pyproject.toml` changes

2 forbidden-nautilus `ignore_imports`; 1 mypy `files` entry; 1 new `forbidden` contract; 1 removed optional dependency (OQ-4). **Zero** `layers` changes, **zero** new layers-debt entries (`:73-81`), no new top-level package.

---

## 6. Build order

### I-0. The correction + drift probe — LOAD-BEARING #1, zero `src/` change, zero network
Read-only walk of the **already-cached** 2021–2025 AFOS zips, answering every item in §4.5. Output: an evidence doc. The cached zips parse under today's parser because `split_iem_afos_products` already synthesises `000`.
**Why first:** the correction answer determines what the dataset may be *claimed* to be. It also re-measures per-year yield, calibrating §4.7's floor with data rather than taste.
**Blocks:** the `[UNVERIFIED]` cache-populated claim. If gone, I-0 becomes a ~25-request network probe under the `live` marker.

### I-1. The `000` accommodation + the equivalence golden test — LOAD-BEARING #2
§4.1. Nothing else proceeds. One function in `cli_parse.py`, one field on `CliStructuralHeader`. Requires one live fetch (under the `live` marker) of a product also in the archive. The live settlement path is unchanged in behaviour.

### I-2. Record types + builder + writer + reader + the forbidden contract — SCHEMA FREEZE
§4.2–§4.4, §4.8. **The field set is irreversible on first write** (§3.3), so this carries a raised review bar and includes a **throwaway end-to-end spike, run before the freeze and deleted as part of the increment**: real I-0 payloads → builder → `write_records` → reader → selection helper. Copied from `FORECAST_INGESTION_PLAN.md:1259-1284` (D10). Depends on I-0 and I-1.

### I-3. The job — fetch, throttle, ledger, resume, quarantine, yield gate
§4.6–§4.7, in `scripts/backfill/`. Includes era guard, truncation guard, IEM terms record. Writes nothing until I-4's gate passes.

### I-4. The verification gate — V-1, V-2, V-3, wired as BLOCKING
§4.9. The increment that makes the backfill trustworthy; the run does not happen without it.

### I-5. Run it — 2008 → present, five stations
Publish per-station-year yields, quarantine counts, correction counts, V-1/V-2/V-3 results as a committed evidence doc. 2003–2007 evaluated separately per §4.7.

### I-6. (Optional, LAST) The NCEI/GHCN flag-only tripwire
§4.9 V-4. Second host, second dependency, weakest signal. Gates nothing.

### I-7. (Optional, deferred) Replay wiring
A `_DATA_TYPE_FACTORIES` entry (`backtest_feed.py:105-124`) plus its topic-prefix-leak test. Not assumed by anything above; it puts archived rows on a message bus and must not be done casually.

**Ordering:** `I-0 → I-1 → I-2 → I-3 → I-4 → I-5` is a genuine dependency chain.

---

## 7. Test strategy — every critical row names the mutant it must kill

| Layer | Test | Mutation it must catch |
|---|---|---|
| Parser | Allowlist **accepts** `"000"`, `"507"`, `"487"`; **refuses** `""`, `"   "`, `"5O7"`, `"O00"`, a 9-digit line, and (via `\Z`) an embedded newline | "Skip line 1 entirely"; `\Z` → `$` |
| Parser | WMO-heading (`:447-451`) and PIL-equality (`:461-471`) checks still refuse a sibling station's product with the sequence set to `"507"` | Widening line 1 while loosening the addressing guards |
| Parser | `CliStructuralHeader` carries the sequence verbatim | Discarding it |
| **Equivalence (THE PREMISE)** | Golden pair → identical `ParsedCliProduct`, `classify_issuance`, `is_correction_bbb`; **and `sha256(live) != sha256(archived)` asserted** | **Normalising archived text before hashing** — the `:449` shape — killed only by the digest-inequality assertion |
| Record | `ts_init == ts_event == issuance_time_ns`, none a constructor parameter; `from_dict` raises on disagreement | Adding `ts_init` as a parameter; deleting the check |
| Record | `archive_retrieved_at_ns >= issuance_time_ns` raises when violated | Flipping or removing the comparison |
| Record | `not issubclass(ArchivedClimateDay, NwsClimateDay)` **and** the reverse | **Making it a subclass** — satisfying every downstream `isinstance` and re-opening barrier 1 |
| Record | Missing column in `from_dict` raises `KeyError` | Replacing a subscript with `.get(...)` (`nws_climate_day.py:10-14`) |
| Record | `register_arrow` called exactly once per module (AST) | A second call (`:16-19`) |
| Record | Arrow round-trip preserves every field; a fragment missing a column raises `SchemaDriftError` | Loosening the strict decoder |
| Record | Archived types prefix-collide with neither live type | Adding a prefix-sharing class (`backtest_feed.py:116-120`) |
| Builder parity | One `ParsedCliProduct` → both builders agree on every settlement field | The builders drifting (e.g. one computing `tavg`) |
| Separation | Settlement readers cannot return an `ArchivedClimateDay`, by type and by runtime attempt | Any union of the streams |
| **Separation (NEW, R2)** | `latest_by_climate_day([archived_row])` raises `TypeError`; a **mixed** live+archived list raises; and the archived helper symmetrically refuses an `NwsClimateDay` | **Widening `selection.py:83-92`'s `_require_unwrapped` to a union or a Protocol** — the single edit that deletes the runtime half of barrier 1 and legalises the merged stream. No Revision 1 row caught it |
| **Separation (NEW, R2)** | `lint-imports` catches the **INDIRECT** chain `nws_actor -> persistence.* -> domain.archived_*`, not merely a synthesised direct import | Putting the archived readers back in `persistence.catalog`, or silently setting `allow_indirect_imports = true` to make the contract pass |
| **Write (NEW, R2)** | Crash-after-write-before-ledger: parquet present, ledger `PARSED`, re-run reconciles fingerprints, marks `WRITTEN`, **exits 0** | **Gating reconciliation on `ledger == WRITTEN`** — false-aborts every benign interrupted resume |
| **Write (NEW, R2)** | Ledger absent entirely, parquet present → `--rebuild-ledger` re-derives `WRITTEN` from ranges+fingerprints without fetching; normal run reconciles rather than aborting | Treating a missing ledger as a first-seen write, or as an integrity violation |
| **Refusal (NEW, R2)** | A station-year clearing the annual floor while ONE MONTH is empty is refused by the per-quarter sub-check | Applying only the annual ratio — the intra-year gap the annual number cannot see |
| **Record (NEW, R2)** | `station_year_yield` and `admission_era` are present, non-null, and round-trip through Arrow | Omitting them — unaddable later, since the schema is irreversible on first write |
| Separation | Archive base nested inside settlement base — **and the reverse** — fails at startup before any fetch | Removing the assertion; checking one direction |
| Separation | `lint-imports` green with the new contract; a **synthesised** module importing the archived type from `breezy.settlement` FAILS | Relying on `layers`, which **permits** `settlement → domain` |
| Separation | No `src/breezy/` module imports `scripts.backfill`; none names the IEM host | Adding IEM to `DEFAULT_ALLOWED_HOSTS`; moving retrieval into `breezy.ingest` |
| Write | N rows sharing one `issuance_time_ns` → exactly **ONE** `write_records` call, all N present on read-back | **Reverting to a per-row loop** — the mutant `nws_actor.py:892-898` says lost a record in production |
| Write | Re-run over a `WRITTEN` year: `skipped` non-empty, fingerprints match, exit 0, nothing re-written. Re-run over a NOT-`WRITTEN` year with `skipped` non-empty: **abort non-zero** | Treating all skips as benign (silent loss); treating all as fatal (no resume). Both mutants must die |
| Write | Rows out of `issuance_time_ns` order raise before any filesystem access | Dropping the sort |
| Refusal | A `CliContentError` product is quarantined **verbatim** with sidecar, absent from the catalog, and increments the year's failure count | Swallowing the exception; dropping the bytes |
| Refusal | `CliNotOurProductError` counted separately, does **not** quarantine | Collapsing the four rejection categories |
| Refusal | A station-year below the floor writes **NOTHING**, not "the good rows" | **Admitting the parseable subset** — the biased-subsample defect, the highest-consequence silent failure here |
| Refusal | A year `<= 2002` refused before any network call; a 1998-shaped product raises rather than mis-parses | Removing the era guard; loosening `_OBSERVED_SUBSECTION_RE` |
| Refusal | A product whose issuance instant resolves from neither source is quarantined, never written with a substituted timestamp | Falling back to "now" or midnight — a fabricated `ts_init` |
| Retrieval | A response whose count equals `limit` aborts the year | Removing the truncation guard |
| Retrieval | Requests ≥1.0 s apart; run-level cap enforced | Removing the throttle |
| Verification | A synthetic 1 °F disagreement between archive and live for the same `(station, climate_day)` **fails** the gate and aborts | Comparing only `tmax_f`; comparing with a tolerance; making the gate non-blocking |
| Verification | V-1 re-parse of stored `raw_text` reproduces the written row exactly | Skipping the re-parse |
| pyiem | No module under `src/breezy/` or `scripts/backfill/` imports `pyiem` (AST, extending `:69-89`) | Introducing a second parser for archived text |

Coverage: meet whatever the project gate is; **no threshold invented here.**

---

## 8. Non-goals

1. Any change to settlement BEHAVIOUR. The only settlement-adjacent edit is §4.1's widening, behaviour-preserving for `000` and pinned both directions.
2. **Clearing REQ-DATA-09.** §0.2. Observation half only.
3. Backfilling forecasts (`decision_time_clearance_prereg_2026-08-27.md:189-194`).
4. Backfilling prices (`GO_LIVE_PLAN.md:109-111`).
5. Backfilling METAR / intraday observations.
6. Using archived data for settlement, reconciliation, or dispute of a live position. §4.8.
7. Replay wiring. Deferred to I-7.
8. Re-running or amending already-published evidence docs. OQ-5.
9. Widening `DEFAULT_ALLOWED_HOSTS`. §5.1.
10. Pre-2003 data. Refused in code.
11. Any live-trading enablement. Operator-only gate.

---

## 9. Risks

| ID | Risk | Sev | Mitigation |
|---|---|---|---|
| R-1 | **Backfilled rows reach the settlement path**; every as-of query silently breaks — `selection.py:20-22` names this scenario in the codebase already | **HIGH** | Four independent barriers (§3.2, §4.8), tested at each level |
| R-2 | **The `000` relaxation weakens the structural gate** — first check ahead of every regex on a path that parses inline on the event loop | **HIGH** | Digits-only, anchored `\A...\Z`, length-bounded; WMO-heading and PIL checks untouched and re-tested; value carried into provenance; negative tests |
| R-3 | **A partially-parseable station-year is admitted**, producing a non-random subsample | **HIGH** | §4.7's all-or-nothing yield floor (0.95, calibrated on measured yields), published per-year. A *completeness* control, not a parse-error alarm |
| R-4 | **The archive omits corrections**, so every archived "final" is systematically pre-correction | **MED–HIGH** | I-0 measures it at zero network cost. A negative answer changes what the dataset may claim, stated in the record docstring and every derived doc |
| R-5 | **A subtle 2008-era grammar difference produces a MIS-parse rather than a refusal** | **MED** | Layered: observed-subsection anchoring; V-2 overlap; V-3 distributional sanity; optional V-4. **Residual risk, stated: no single sufficient control** |
| R-6 | **Silent truncation at the AFOS `limit`** | **MED** | `count < limit` asserted; equality aborts the year; reconciled by the yield gate |
| R-7 | **Re-run idempotency inverts the "a skip is an integrity alarm" rule** established after a real production data loss | **MED** | Ledger-gated, read-back-verified, stated loudly, both mutants tested |
| R-8 | **`raw_sha256` has two meanings in the repo** — `:523` digests rewritten text, `:583` verbatim | **MED** | Named here so it is not inherited. The archive digest is over verbatim bytes, full stop. OQ-5 covers retiring the rewrite |
| R-9 | **The schema is irreversible on first write** and `schema_version` creates false confidence | **MED** | §3.3 says the opposite in the docstring; I-2's spike exists for this alone; raised review bar |
| R-10 | **IEM terms / politeness** unread | **MED** | 95 requests, ≥1 s throttle, descriptive UA, per-run cap; terms read and recorded in I-3 |
| R-11 | **2008–2020 is entirely `[UNVERIFIED]`** | **MED** | I-5 measures per-year; the yield gate refuses what does not clear. A poor result shrinks the dataset, it cannot corrupt it |
| R-12 | **`scripts/` is not import-linted** | **LOW–MED** | Accepted with reason (§5.1): the compensating property is stronger than the one given up. Partly closed by mypy and the no-upward-import test |
| R-13 | **Storage growth** ~130 MB verbatim plus parquet plus quarantine | **LOW** | Measured at I-5 |

---

## 10. Open questions

**OQ-1 (blocking I-2). Does IEM preserve `CCx` corrections?** *Recommendation:* assume **NO** until I-0 proves otherwise; `revision_seq` is designed correct either way. If I-0 shows ~0 across ~1,800 station-days while live shows 1 in ~9 MDW site-days, treat the archive as lossy and label the dataset.

**OQ-2 (RESOLVED, and the plan's most attackable decision). `ts_init` = issuance or retrieval?** *Recommendation:* **issuance, on a distinct record type**, retrieval kept as `archive_retrieved_at_ns`. §3.1 works through both failure modes. The asymmetry is that back-stamping is dangerous only *because a record type asserts a meaning the value does not have*. **A reviewer who disagrees should attack §3.1 directly** — everything in §4 follows from it.

**OQ-3 (blocking I-5). Admit 2003–2007?** *Recommendation:* refused by default; per-station-year on measured yield; **never mixed into a stratum without an era label**.

**OQ-4 (non-blocking). Remove the `pyiem` extra?** *Recommendation:* **yes**, converting `test_backfill_dependency_pin.py` to a **negative** pin (§4.10). Its docstring at `:60-63` sanctions the update. Operator-visible, so flagged.

**OQ-5 (non-blocking, after I-5). Retire the analysis scripts' text rewrite?** *Recommendation:* eventually yes (R-8) — but **not** casually: it changes `raw_sha256` values inside a **published** evidence doc, requiring a re-run of a study with its own pre-registration. Flagged, not decided.

**OQ-6 (non-blocking). Actual usable sample size? — earlier figure was wrong; corrected here.** Revision 1 headlined "~32,000 products / ~16,000 station-days / ~3,200 per station" in both §0.2 and this entry. That contradicted this plan's own §4.6 arithmetic by a factor of ~2.2 and never reconciled.

Derived from §4.6's own stated rate: 5 stations × 19 years (2008–2026) × 365 days ≈ **34,700 station-days**, at ~2 issuances/day ≈ **~69,000 products**, ≈ **~6,900 station-days per station**. At the measured 2021–2025 yield (>0.99) essentially all of it is admissible, so quarantine loss cannot explain the old figure — it was simply unreconciled.

The qualitative conclusion is unchanged under either number: comfortably above `>=400 per stratum` and `>=2,000 overall` *if those could be met with observations alone* — and per §0.2 they cannot, so neither figure moves REQ-DATA-09. Storage in §4.2 (~130 MB at ~32,000 × ~4 KB) must be re-derived at ~69,000 products ≈ **~280 MB** verbatim before parquet. Both remain `[UNVERIFIED]` until I-5 measures the admitted-day count directly.

**And the honest framing of the count itself:** "6,900 station-days per station" is a *label* count, not a settled-pair count. It is the right number for climatology and for fitting an observation-side model; it is the wrong number to quote as progress toward the trading gate. §0.2 governs.

**OQ-7 (non-blocking). Should the archived stream ever replay through `BacktestNode`?** Deferred to I-7. Standing constraint: streaming catalog replay **raises** for Breezy's record types because the Rust `DataBackendSession` cannot see a Python `register_arrow` schema — `TRADING_ENABLEMENT_PLAN.md:118` (REQ-DATA-10), contract-tested.

---

## 11. Success criteria

- [ ] I-0's evidence doc committed, answering corrections **either way**, with per-station-year counts, yields, rejection breakdowns.
- [ ] `check_structural_allowlist` accepts a real transmission sequence, refuses non-digit and blank forms, carries the value into provenance — WMO and PIL checks proven unchanged.
- [ ] The golden **pair** test passes, asserting field equality **and** digest inequality.
- [ ] Both archived types `register_arrow` exactly once; `ts_init == ts_event == issuance_time_ns` enforced on construct **and** decode; neither is a subclass of a live type, asserted both directions.
- [ ] The I-2 spike ran end-to-end against real payloads and was **deleted** before the schema froze.
- [ ] `lint-imports` green including the new `forbidden` contract, **zero** new layers-debt entries — verified by running it.
- [ ] `DEFAULT_ALLOWED_HOSTS` still exactly `{"api.weather.gov"}`; no `src/breezy/` module names the IEM host.
- [ ] Archive and settlement roots provably disjoint at startup, both directions.
- [ ] One `write_records` call per `(station, year, type)`; a re-run is a clean no-op; an unledgered skip aborts.
- [ ] A station-year below the yield floor writes **nothing**, proven by test.
- [ ] The live-overlap gate is **blocking**, covers `tmax`/`tmin`/`tavg` **and** flags, and passed before any bulk write.
- [ ] Every quarantined product on disk verbatim with sidecar; the evidence doc publishes yields, quarantine counts, admit/`DEGRADED` verdicts.
- [ ] **No document produced by this work claims the CLI backfill clears REQ-DATA-09 or produces settled pairs.**

---

## 12. Revision 2 — decisions from adversarial peer review

Four independent reviewers, disjoint seams, each running blind: architecture (§3/§4.2–4.4/§4.8/§5), job and refusal machinery (§4.5–4.7/§4.9/§6), analytical value (§0.2/§8/OQ-3/OQ-6), and a citation audit of ~93 `file:line` claims. Verdicts: **4× APPROVE-WITH-CHANGES, 0 BLOCK.**

| # | Decision | Origin | Where |
|---|---|---|---|
| **D1** | **Duplicate the selection ordering; never generalise it.** `selection.py`'s `_require_unwrapped` is a *runtime* isinstance gate, so barrier 1 is stronger than Revision 1 claimed — it already refuses a merged live+archived list. Revision 1's "reuse `:11-50` verbatim" pointed at docstring and invited the one edit that deletes that protection. | Architecture, HIGH | §4.4, §7 |
| **D2** | **Always reconcile read-back fingerprints on a write skip; never gate reconciliation on ledger state.** Revision 1's rule false-aborted every benign crash-interrupted resume, because the payload is durable *before* the claim — the reverse of the `product_index` precedent it cited. | Job, HIGH | §4.6, §7 |
| **D3** | **Archived readers move to a new `breezy.persistence.archive_catalog` module.** Keeping them in `persistence.catalog` made the `forbidden` contract fail on an indirect chain through `nws_actor`, and the one-line fix (`allow_indirect_imports = true`) would have silently degraded the contract to direct-only. | Architecture, HIGH | §4.8, §5, §7 |
| **D4** | **The receipt lag is a stated, quantified residual, not noise.** Archived `ts_init` answers "was this public"; live `ts_init` answers "did Breezy have it". Fitting on the former and deploying on the latter is a systematic, same-direction look-ahead. Measured in I-0; makes a merged replay (OQ-7/I-7) semantically invalid, not merely unwise. | Architecture, MED-HIGH | §3.1.1, §4.4 |
| **D5** | **0.95 is a placeholder, not a measurement.** The cited yields aggregate over five station-years (~0.9901); the same defects concentrated in one year give ~0.9507. I-0 publishes the single-year distribution and sets the floor. | Job, MED | §4.7, §6 |
| **D6** | **Add a per-quarter intra-year completeness sub-check.** An annual ratio cannot see a year that clears the floor while missing a whole month, and V-3 — the only other control — is non-blocking. | Job + domain, MED | §4.7, §7 |
| **D7** | **Between-year selection bias is an OPEN residual.** All-or-nothing admission relocates bias from days to years, and dropped years may correlate with severe weather — the tail the bot prices. I-5 must report `DEGRADED`-year rate against an independent severe-weather indicator. Not solved here. | Domain, HIGH | §4.7, R-3 |
| **D8** | **Add `station_year_yield` and `admission_era` to the schema.** They are the sample-selection covariates for any later bias analysis, and the schema is irreversible on first write — omitted now means never. | Architecture, MED | §4.2 |
| **D9** | **Correction loss is a hypothesis with a stated interval, never a finding.** The live base rate is 1 of 8 — a 95% CI spanning roughly 2–53%. I-0 reports a Wilson interval and may not assert lossiness from a comparison this thin. | Domain, MED-HIGH | §4.5, §6 |
| **D10** | **Barrier lists reconciled to the same four**, ranked by what each uniquely survives: Type (runtime-enforced) > import-linter (fires at CI on new code) > Root > Process. Provenance fields demoted — they diagnose, they do not prevent. | Architecture, MED | §3.2, §4.8 |
| **D11** | **Product-count arithmetic corrected.** Revision 1's "~32,000 products / ~16,000 station-days" contradicted §4.6's own rate by ~2.2×. Corrected to ~69,000 products / ~34,700 station-days / ~6,900 per station; storage re-derived to ~280 MB. No conclusion changes — and the count is a *label* count, never progress toward the trading gate. | Domain, HIGH | §0.2, OQ-6 |
| **D12** | **Citations corrected:** `sites.py:349`→`:111` (the one outright fabrication — `:349` is `settlement_site()`), `selection.py:11-50`→`:78-138` for code, `:20-24`→`:20-22`, `product_index.py:504-509`→`:501-509`, `FORECAST_INGESTION_PLAN.md:258-260`→`:257-260`. Audit found **1 fabrication, 3 slips in ~93 checked**. | Citation audit | throughout |

### Sequencing, revised

The analytical-value reviewer's bottom line was **"build later, not now, and not never"**: the IEM archive is not decaying, while the quote tape and forecast archive lose data permanently every day. That argument is accepted.

It resolves in a specific way: **the higher-value work is blocked on operator enablement** (venue endpoint config and `BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG`), not on engineering. So:

- **I-0 proceeds now** — zero-network, zero-cost, cache verified present on this host (40 files, ~300 MB). It resolves D5, D6, D9 and D4's measurement, none of which can be settled by argument.
- **I-1 through I-5 are HELD** pending that evidence and an explicit operator decision on sequencing against the clock-bound streams.
- Nothing in I-0 commits the schema, creates the third catalog root, or touches the network.

### Reviewer items deliberately NOT adopted

- **`scripts/` as a second import-linter `root_packages` entry** (architecture reviewer, §5.1). It would recover structural upward-import protection, but pulls `scripts/analysis` and `scripts/venue` under the linter and may surface unrelated existing debt. Recorded in R-12 as an evaluated option with its cost, rather than silently omitted.
- **NCEI/GHCN tripwire promotion.** Stays optional and last (V-4); a second third-party host for the weakest signal.

---

## 13. I-0 executed — 2026-08-29

I-0 ran read-only against the already-cached AFOS zips and the live catalog. No network fetch, no write to `~/.local/share/breezy/`, no `src/` change. Gates re-run independently: `ruff` clean, `mypy` clean on 266 files. Evidence:

- `docs/evidence/ingestion/ARCHIVE_CORRECTION_PROBE_2026-08-29.md` (script: `scripts/analysis/archive_correction_probe.py`)
- `docs/evidence/ingestion/RECEIPT_LAG_2026-08-29.md` (script: `scripts/analysis/receipt_lag_probe.py`)

### What I-0 settled

| Review item | Status | Result |
|---|---|---|
| **OQ-1 / D9** — does IEM retain corrections? | **RESOLVED, favourably** | Yes. 14 `CCx`-tokened pairs, 12 with genuinely different parsed values, across 25 station-years. Revision 1's "assume NO" working assumption is refuted by measurement. No lossiness claim is made or needed. |
| **D5** — is 0.95 a real floor? | **RESOLVED for 2021–2025** | Single-year yield min 0.9836 / median 1.0000 / max 1.0000 over 25 station-years. 0.95 holds but is loose. Deliberately **not** tightened to ~0.98: five years of the easiest era is a poor basis for tightening a gate that must survive 2008–2020. Revisit at I-5. |
| **D6** — intra-year completeness | **CONTROL RETAINED, fires on nothing** | 21 low-count station-months; largest gap 3 days; no missing month. The hazard does not materialise in the modern era — which is exactly why the control cannot be considered validated yet. |
| **D4** — receipt lag | **RESOLVED, and it corrected this plan twice** | Steady-state p95 **895.7 s (14.9 min)**, max 19.9 min, n=56. Revision 1's "minutes" was right; §3.1.1's initial challenge to it was wrong on magnitude, though right on structure. |

### What I-0 found that no reviewer predicted

**~95% of duplicate FINAL products are retransmissions, not corrections.** Of 496 duplicate-FINAL pairs, **472 are byte-different but value-identical**. The archive identity `(station, issuance_time_ns, raw_sha256)` stores each as a distinct row, so ~5% of final station-days will carry multiple semantically identical records. The existing `max(is_final, ts_init, revision_seq)` ordering handles this correctly with **no design change** — but §4.9's V-1 must not treat a value-identical duplicate as an anomaly, and per-row storage estimates must expect it.

**Issuance-instant recovery was 100% effective** — 0 unresolvable products across both probes. §4.2's quarantine path for unresolvable issuance stays, but is expected to be empty in the modern era.

### A methodological note worth keeping

The receipt-lag probe's first result pooled two populations and reported p95 = 6.6 days. Separating them — justified by an observed 39,248-second empty interval, not a chosen threshold — gave 14.9 minutes. **The pooled figure was off by a factor of ~630 and looked entirely plausible.** Any future measurement over this catalog must check for the collection-restart boundary before quoting a percentile.

### Still open after I-0

- **D7** — between-year selection bias vs severe-weather regime. Unmeasured; requires I-5 and an independent severe-weather indicator.
- **2008–2020 coverage, yield, and format stability.** Entirely unmeasured; R-11 stands.
- **2003–2007 admission** (OQ-3). Unchanged: refused by default.
- **Sequencing.** I-1 through I-5 remain HELD pending an operator decision against the clock-bound live streams (§12). Nothing in I-0 committed the schema, created a catalog root, or touched the network.

---

## 14. I-1 executed — 2026-08-29

The `000` accommodation (§4.1 option O-4) is implemented, with the equivalence golden pair that is the premise of the whole backfill.

### The observed sequence value was `100`, not `507`

§4.1 and §7 cite `507`/`487` as example archived sequences. The real value on the acquired pair is **`100`** (line 1 is `100 `, with a trailing space). This vindicates widening to a *class* — anchored 1–6 ASCII digits — rather than enumerating observed values. Had the plan allowlisted `507`/`487` specifically, I-1 would have failed on the first real product.

### Change

`check_structural_allowlist` now matches `\A\d{1,6}\Z` against the stripped line-1 token instead of requiring literal `"000"`, and `CliStructuralHeader` gained `wmo_transmission_sequence` carrying the observed value as provenance. `\Z` rather than `$` is used deliberately and carries a comment saying why, since `$` also matches before a trailing newline.

**The addressing guards are byte-identical**, verified by diff: `_WMO_HEADING_RE` and the `actual_pil != expected_pil` equality check are untouched. `000` was never a security property — it is an artefact of the live API normalising the sequence. The PIL check is what proves a product is ours, and a sibling station's product with a widened sequence is still refused (pinned by test).

### Evidence

RED: 8 failing parser tests, including the archive fixture rejected with `unexpected transmission indicator line: '100 '; expected '000'`.
GREEN: **3417 passed, 1 skipped, exit 0**; `ruff`, `mypy` (266 files), `lint-imports` (2 contracts kept, 0 broken) all clean. Gates re-run independently of the implementing agent.

Fixtures: `tests/fixtures/cli_equivalence/` — MIA, climate day 2026-08-24, issuance 2026-08-25T08:27:00Z. Live half read from the local catalog; archive half took **1** IEM request. `api.weather.gov` was never contacted, so the production collector's latching UA trap was never at risk.

### The assertion that matters most

The equivalence test asserts field-for-field parse equality **and** `sha256(live) != sha256(archive)`, with both digests pinned. That inequality is what kills the O-1 mutant: any implementation that normalises archived text to `000` before hashing — the shape `settlement_alignment_study.py:449` uses — makes the digests equal and fails. A test that only checked parse equality would have passed for a design that destroys the verbatim-bytes contract.

### One existing test was changed, and it was a strengthening

`test_normalize_cli_parse_errors.py` used `001` as an invalid-sequence example in two places. Under the widened rule `001` is *valid*, which would have made both assertions **vacuous** — asserting a refusal that no longer occurs. They now use `NOT000`, still under `pytest.raises(CliStructuralError)`. No test was weakened, skipped, or deleted.

### Next

I-2 (record types, SCHEMA FREEZE) remains gated on the operator sequencing decision in §12. I-1 changed only the parser and is independently useful: the settlement path now tolerates a real transmission sequence without any behaviour change for live `000` products.
