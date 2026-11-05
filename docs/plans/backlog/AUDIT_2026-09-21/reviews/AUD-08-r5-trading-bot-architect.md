# AUD-08 — Review record (Round 5, delta on the in-place-edited final revision)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-08-unattended-station-candidate-register.md
- Plan file sha256: 0b52192f890dcb53cae2b769b5746a8e93ee8c75ed6e1a96ac47f01147dc2090
- Round: 5 · Reviewer: trading-bot-architect (autonomous-loop/pipeline lens)
- Total: 100/100 · Readiness: READY

## Correction to my round-4 verdict

My round-4 review scored this plan 100/100 and missed **A8-6**: the sufficiency counter's
`catalog_root` was unbound (no default on `count_covered_listed_station_days_from_catalog`), and a
wrong/unreadable root read as `count=0`, i.e. a silently-permissive, legitimate-looking
`REGISTRY_ONLY_NO_CAPTURE`. The architect found this and the coordinator verified it in source. I
re-derived it myself this round rather than trusting the plan's fix.

## A8-6 fix verified against source (independent re-derivation)

The plan (§6b.3) now binds `--catalog-root` to `default=str(DEFAULT_QUOTE_TAPE_CATALOG)` and adds
three pre-count guards before ever calling the counter: root-is-dir, `depth_root_present`, and a
catch on `QuoteTapeGapDataUnavailable`. I re-read the relevant source directly rather than trusting
either the plan's or the architect's citations:

- `count_covered_listed_station_days_from_catalog` (`scripts/analysis/structural_dead_stop.py:219-251`)
  performs no root check at all — confirmed by reading the full body; `discover_station_days` over a
  non-existent `depth_root` returns nothing and the function returns `0`.
- The shipped CLI's `main()` carries exactly the three guards the plan says it does: root-is-dir
  check with `return 1` (`:355-361`, confirmed by reading `:272-300`), `depth_root_present =
  depth_root.is_dir()` (`:363-365`), and `except QuoteTapeGapDataUnavailable` (`:373-376`).
- `DEFAULT_QUOTE_TAPE_CATALOG` is defined at `ma_prelock_winner_ask_study.py:187` — confirmed —
  and `structural_dead_stop.py:275-279` already uses it as `--catalog-root`'s default, confirmed by
  reading `_parse_args`.
- The wrapper resolution the plan claims is byte-identical to `score-live-trials-run.sh:57-60` —
  confirmed: `CATALOG_ROOT=${BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG:-$HOME/.local/share/breezy/
  catalog/quote_tape/polymarket_us}` is exactly at line 60, preceded by the comment at `:57-59`
  naming it the same root `breezy-quote-tape(-ingest).service` writes.
- The refusal semantics — exit non-zero, register byte-unchanged, `last_folded_day` unadvanced, no
  sidecar pruned, never a `REGISTRY_ONLY_NO_CAPTURE` row — is a coherent, argued choice (a
  partially-computed fold is the silently-permissive shape itself; "keep the previous value" has no
  answer for the first fold). It joins §9 as its own case and A9 gains a fourth arm asserting exit
  code, byte-unchanged register, and unadvanced watermark for three sub-cases (absent root,
  `depth_root_present == false`, `QuoteTapeGapDataUnavailable`).

This closes the exact "healthy-looking artefact, wrong underlying answer" shape this whole audit
exists to find. The fix is not merely a default value — it is the fail-closed refusal rule and its
test, which is the part that actually matters.

## a1 fix (sidecar rotation) verified against source

The plan now states `append_sighting` resolves `sightings-<UTC day>.jsonl` per append (not once at
attach) keyed on the sighting's own `observed_ts_ns` converted to UTC, never the wall clock, and
names the call site as `PolymarketUSInstrumentProvider.load_all_async` (not `_weather_market_payloads`,
which must stay I/O-free because `discovery_candidate_slugs` calls it positionally at
`provider.py:187` — confirmed). A12 gains a rotation arm (two appends straddling a UTC midnight land
in two files). This is sound design reasoning; the call-site attribute this plan references
(`self._unregistered_city_sightings`) does not yet exist in `provider.py` because 08a's changes are
unbuilt — expected for a design plan, not a citation defect.

## Full re-scan for anything else of the kind

I re-read §6b.3 in full (catalog binding through the sufficiency mapping), §9's failure-case list,
and A9/A12/A17's final text, specifically looking for: (a) any other unbound parameter reaching a
shipped function with no default, (b) any other place a wrong/absent input could read as a valid
value, (c) any other citation drift. Found none. The `MIN_STRUCTURAL_DEAD_STATION_DAYS` chain
(`structural_dead_stop.py:58,85`, `ma_prelock_winner_ask_study.py:163`, test pin at
`test_structural_dead_stop.py:99`) re-verified unchanged and correct. The registry-path citations
(`src/breezy/registry/sites.toml`) remain corrected throughout.

## Defects

None found in this revision.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | 08a closes the livelock; the one PM.us seed row is now producible end to end with its value honestly bounded (no silently-permissive read). |
| Technical correctness and evidence grounding | 20 | 20 | Every citation I independently re-derived this round is exact, including the previously-missed catalog-root/guard chain. |
| Implementation specificity and feasibility | 15 | 15 | The last unmade input decision (`catalog_root`) is now bound by name with its refusal semantics fully decided; the sink's day resolution and call site are specified rather than inferred. |
| Acceptance criteria and validation quality | 20 | 20 | A9's fourth arm and A12's rotation arm close the two remaining testing gaps from round 4; every failure path now has a named, tested behaviour. |
| Autonomous operation, failure handling, recovery | 15 | 15 | The silently-permissive catalog-root read is closed; the "impossible by construction" interleaving case remains genuinely unreachable; watermark recovery, flood cap, three-failure escalation, one-shot alert all stand. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Unchanged; no defect found here across any round. |
| **Total** | **100** | **100** | |

## Required changes to reach 100

None.

## Blockers (recorded, not scored)

- **Operator + strategy lead, OUTSIDE this item:** the `src/breezy/registry/sites.toml`
  re-verification gate and the archive-table extension for a fifth station.
- **Evidence unavailable:** the trigger (a venue listing a 6th city) has never been observed.
- **Cross-item constraint (AUD-09 §6c step 6, mirrored):** a sixth registered site breaks
  `load_sites()`'s hardcoded `IEM_ASOS_IDS`, which the same counter this plan calls depends on.
