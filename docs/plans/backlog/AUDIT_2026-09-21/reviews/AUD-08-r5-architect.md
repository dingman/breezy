# AUD-08 — Review record (Round 5, FINAL)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-08-unattended-station-candidate-register.md
- Plan file sha256: 0b52192f890dcb53cae2b769b5746a8e93ee8c75ed6e1a96ac47f01147dc2090 (coordinator recorded 0b52192f…)
- Round: 5 (delta) · Reviewer: architect (module boundaries, versioned inter-stage contracts,
  idempotency, import layering, exchange portability, YAGNI)
- Total: 100/100 · Readiness: READY

## Round-4 dispositions, verified against the plan body AND against source

| R4 defect | Claimed | Verified? |
|---|---|---|
| **A8-6 (MATERIAL)** — `catalog_root` unbound; a wrong/absent root reads as `count=0` ⇒ a legitimate-looking `REGISTRY_ONLY_NO_CAPTURE`; `QuoteTapeGapDataUnavailable` unhandled | ACCEPTED IN FULL | **FIXED, and fixed at the right layer.** §6b.3 now carries three sub-bullets. **Binding:** `--catalog-root` with `default=str(DEFAULT_QUOTE_TAPE_CATALOG)` — I re-read the model it copies (`structural_dead_stop.py:275-279`) and the constant (`ma_prelock_winner_ask_study.py:187`); the wrapper passes `BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG` resolved byte-identically to `score-live-trials-run.sh:57-60`, whose own comment does say that env var names the root `breezy-quote-tape(-ingest).service` writes. Tying it to AUD-09's `$QUOTE_CATALOG` resolution so the two items cannot read different catalogs is a genuine cross-plan improvement I did not ask for. **Refusal semantics:** all three guards are asserted *by the emitter* — `catalog_root.is_dir()`, `(catalog_root/"data"/"order_book_depths").is_dir()`, and `except QuoteTapeGapDataUnavailable` — and the plan's proof that the *library* call guards none of them is correct at source: `count_covered_listed_station_days_from_catalog` (`:219-251`) performs no root check, while `main()` does them at `:355-361`, `:363-365` and `:373-375`. On any of the three the emitter exits non-zero **having written nothing** — register unchanged, watermark unadvanced, no pruning — so `REGISTRY_ONLY_NO_CAPTURE` now means only what it says. The rejection of "keep the previous value" (no answer for the *first* fold) is sound. **Coherence:** the unadvanced-watermark/alert argument is right — `first_seen_day` is the fold day, so a catalog outage *delays* the one-shot alert rather than skipping it, and §9's three-failure escalation bounds it. **Criteria:** A9 gains a fourth arm asserting exit code, byte-unchanged register, unchanged watermark and *in particular* no `REGISTRY_ONLY_NO_CAPTURE`; §9 gains the case; §7 steps 10/12/13 updated, including a wrapper assertion that `--catalog-root` comes from the env exactly as `score-live-trials-run.sh:57-60` does. Nothing left open. |
| **a1 (MINOR)** — sidecar day-resolution/rotation unstated; sink write call-site unnamed | ACCEPTED | **FIXED, and more completely than asked.** The rotation row now states the day is resolved **per append**, never at attach, from the **sighting's own `observed_ts_ns`** (not the wall clock) — which is the stronger choice, because it makes the filename and the record's own claimed day agree, keeping the filename-keyed fold and the `last_folded_day` watermark consistent. The failure it prevents (a handle resolved at attach writing D+1…D+n into D's file, then made unreachable by the watermark) is stated as the reason. The call-site is named: `load_all_async`, immediately after the `_unregistered_city_sightings` assignment and the single per-cycle WARN, `sink.append(sighting)` per sighting under a `None` check — explicitly **not** from `_weather_market_payloads` (which must stay I/O-free, and is also what `discovery_candidate_slugs` calls at `:187`) nor `_discover_markets` (per payload page). That placement is correct and preserves "flushed and closed per cycle". **A12** gains the rotation arm (two appends straddling a synthetic UTC midnight land in two day-named files from one sink, no filename resolved at attach), and §7 step 7 carries it. The one residual — a sighting produced after that day was folded and pruned — is stated and bounded. |

Everything verified in round 4 is unchanged and re-checked consistent: the `subscribe_trades`
discriminator and the untouched `lru_cache` key (A14 iii), the `venue_city_token` seed domain and A6's
collapse clause, the `MIN_STRUCTURAL_DEAD_STATION_DAYS` mapping and A9's equality, the watermark (A17),
H1's seven rows, H2 declined without residue, and the §6c eight-step table — the last still identical
in AUD-09 §6c and AUD-10 §6c.

## Defects found in revision 5

**None.** I looked specifically for regressions introduced by the two fixes and found none: the
refusal path cannot half-write (the emitter exits before any fold output), A7's byte-identical re-run
still holds, and per-append rotation does not contradict "flushed and closed per cycle".

Two **non-scoring observations**, neither a defect and neither requiring a change:
- §6b.3 says the emitter "carries the same three guards" as `main()`, while deliberately **diverging**
  on one: `main()` treats an absent depth root as `count = 0, exit 0` (its own comment at `:377-380`
  says an absent depth root only *delays* a KILL and never manufactures one), whereas the emitter
  refuses. The divergence is the correct one for this artefact's semantics and its reason is stated in
  substance one bullet earlier ("a legitimate-looking `REGISTRY_ONLY_NO_CAPTURE`"); only the word
  "same" is loose.
- Refusing the whole fold on a catalog outage couples the **sighting** path (which needs no catalog)
  to the **seed** path's catalog dependency, so a venue-expansion sighting's alert is delayed by a
  quote-tape outage. The plan states this, argues the alternative (a partial fold) is the
  silently-permissive shape, and bounds it with the three-failure escalation. That is a reasoned,
  stated, escalated trade-off, not a defect.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | 08a closes the livelock; 08b's one PM.us row is now producible end to end **and** its value cannot be silently fabricated. §6c states honestly that AUD-08 owns steps 1–2 of eight. The residual "stations are still static" gap against G-05's headline is **not** deducted: steps 3–5 and 8 are operator/strategy-lead acts no plan change reaches — recorded as a blocker. |
| Technical correctness and evidence grounding | 20 | 20 | Every citation re-opened this round is exact: `structural_dead_stop.py:219-251,253-266,275-279,355-361,363-365,373-375`; `ma_prelock_winner_ask_study.py:187`; `score-live-trials-run.sh:57-60`; plus the round-4 set (`factories.py`, `config.py:322-333`, `node_config.py:527`, `quote_tape_cli.py:188`, `trade_cli.py:402,405`, `sites.py:348-350,384-401`). No claim I checked is unsupported. |
| Implementation specificity and feasibility | 15 | 15 | Both remaining open decisions are now made in the plan: the catalog root (flag, default constant, env passthrough) and the sink's day resolution + call-site + method (`sink.append`). An implementer can execute this without inventing anything. |
| Acceptance criteria and validation quality | 20 | 20 | A1–A17 objective and property-shaped; A9 now has a value arm **and** an absent-input arm asserting exit code, byte-unchanged register and unchanged watermark; A12 has the rotation arm; A14(iii), A6's collapse arm and A17's recovery arm all pin the properties that matter. |
| Autonomous operation, failure handling, recovery | 15 | 15 | Livelock closed; interleaving unreachable by construction; two sidecar crash cases; multi-day recovery with a counted residual; the new catalog-refusal path writes nothing and loses nothing; corruption and unknown-version refusals; three-failure escalation through the shipped sink; one-shot candidate alert with a durable dedupe. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | ROI honesty, abandonment criterion scoped to sighting-origin rows only, H2 declined without residue across three files, out-of-scope steps named with owners, no operator-cap / enablement / NO-SEND / PREREG contact. |
| **Total** | **100** | **100** | |

## Required changes
None. I find no substantive defect in revision 5.

## Blockers and notes (recorded separately; not scored)
- **Operator + strategy lead, OUTSIDE this item:** the `src/breezy/registry/sites.toml`
  re-verification gate and the archive-table extension for a fifth station (§6c steps 3–4). This is
  why G-05's headline cannot be closed here.
- **Evidence unavailable:** the trigger (a venue listing a 6th city) has never been observed; 08a's
  value is argued, not demonstrated — correctly used as the P1-not-P0 argument.
- **Cross-item constraint:** a sixth registered site breaks `load_sites()`'s hardcoded
  `IEM_ASOS_IDS`, which the counter this plan calls depends on. Recorded in AUD-09 §6c step 6 and §12
  with an owner; no effect today.

_Saved verbatim by the coordinator: the `architect` reviewer has no file-write tool._
