# AUD-12 review (round 2, mle-reviewer)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-12-cost-model-slippage-and-fee-drift.md
sha256: 54953aa7636d9679d8cb77081c5b355b22689fc6d877ee53b90f0fe651510f86
Round: 2
Reviewer: mle-reviewer (backtesting / statistical-validation lens)

## Round-1 defect disposition (verified, not just read from §13)

- MATERIAL (s8.5 mischaracterised as "done") — FIX VERIFIED: §1/§3(a) now
  state explicitly "this item satisfies ONLY the 'slippage derived from
  realised fills' sub-question" and name the broader fill-or-refuse record as
  unbuilt residual scope. I independently re-read
  `docs/evidence/bl19_edge_and_cost_decision_2026-09-01.md` s8.5 (lines
  660-742) and CONFIRM the plan's quotes are exact: the required record is
  specified "regardless of whether an order forms" (matches the doc's own
  "Required instrumentation, per station-day, written regardless of whether
  an order forms" at line ~695) and the N0/N1/N2/N3 table (lines 670-677)
  matches verbatim, including "nothing about profitability from N2 alone,
  since N2 ... is a config outcome driven by an unmeasured slippage
  placeholder ..., not a market verdict." The scope-narrowing statement is
  accurate and the distinction is real — the fix is correct as far as it
  goes, but see the fresh defect below: the §7 step 0 pre-check meant to
  settle this empirically queries the wrong data source.
- MINOR (flagged-fill disposition) — FIX VERIFIED: §6 item 1/§7 step 1/§8/§9
  now require exclusion-with-count, not silent n-reduction.
- MINOR (probe interval) — FIX VERIFIED: §5/§7 step 3a/§8 now specify "no
  coarser than every 2 hours."
- prediction-market-reviewer's two MATERIALs (stale WP-B0 framing; no
  live-configuration acceptance criterion) — FIX VERIFIED: §2/§4/§6 item
  3/§10/§12 now correctly state WP-B0 landed at `f97c26f` (2026-09-20), and
  §7 step 5/§8 add a live-configuration closing criterion via the
  `breezy-check-alerts` CLI. I independently ran `git show --stat f97c26f`
  this round and CONFIRM: commit dated 2026-09-20T14:08:33Z, message states
  "BREEZY_ALERT_WEBHOOK_URL was unset in ~/.config/breezy and absent from the
  live node's /proc/94168/environ... The 2026-09-17 fee halt ran THREE DAYS
  unnoticed and the permit lapse ELEVEN HOURS -- both correctly emitted,
  neither delivered," and lists a real loopback-TLS delivery test. The plan's
  round-2 framing (mechanism landed; live-configuration is the remaining,
  narrower, verification-shaped question) is accurate and appropriately
  cautious — it does not over-claim the coordinator's env-file grep as
  sufficient proof, correctly keeping §12's conditional blocker open for
  what only a live-process check can establish.

## Fresh round-2 defect (new, this session, independent source check)

**MATERIAL** — §7 step 0 (new this round) instructs: "query whether any
refused-but-priced station-day records exist in the current
`TrialDayLatch`/`StateStore` data (i.e., a triggered evaluation that has a
decision-time `ask` but no resulting fill)." I traced this against source
(`src/breezy/strategy/current_rung_hold/continuous_strategy.py`,
`trial_day_latch.py`) and confirmed: **a `Refuse` decision is never written
to `TrialDayLatch`/`StateStore`.** The only calls into the latch's durable
write path (`_latch.record_attempt` at line 1623/1952,
`_latch.record_with_legacy_fallback` at line 2416,
`_latch.record_duplicate_fill` at line 2435, `_latch.consume_if_absent` at
line 984 for fill-walk adoption) all fire exclusively on a `Take` that is
actually submitted or already filled. Every `Refuse` branch (lines
1554-1592) only calls `self.refusals.record(decision.reason)` — an
in-memory-only `RefusalCounter`, never persisted to `TrialDayLatch` or
`StateStore`. **`TrialDayLatch`/`StateStore` therefore cannot contain a
refused-but-priced record by construction — the count §7 step 0 asks the
implementer to query is guaranteed to be zero regardless of what actually
happened on the live node.** A pre-check that is structurally guaranteed to
return zero, then reported as an empirical finding in
`MEASURED_SLIPPAGE_2026-09-21.md` (per §6 item 2/§8), is a measurement-
instrument defect: it would state "0 refused-but-priced station-days" as if
it were a fact about the world, when it is actually a fact about which table
was queried. This is exactly the sample-size-honesty failure this plan's own
(a) work is otherwise careful to avoid (n=6, no invented CI).

**The correct durable source exists and was not checked by the plan.**
`src/breezy/strategy/current_rung_hold/offer_tape.py`'s `OfferTape` /
`OfferTapeRecord` records **every eligible snapshot — Take AND Refuse** —
including `ask`, `reason` (the first blocking gate, e.g.
`edge_below_break_even`, `not_executable`, `observation_unavailable`),
`p_bound`, `break_even`, `fee_coefficient`, `staleness_ns`, and the
running-max interval, to a durable per-day JSONL sidecar
(`catalog_root.parent / "decisions" / f"offer_tape_{day.isoformat()}.jsonl"`,
confirmed at `composition.py:473-485,554-559`). The module's own docstring
records real production volume: "the first live day wrote 7.9 MB / 9612 rows
in ONE hour for ONE station." This is populated on every live day and is
very likely to already contain a large, real population of refused-but-priced
station-days — the opposite of what §7 step 0's specified query would report.
Beyond settling the count, the `OfferTapeRecord` schema itself substantially
overlaps with bl19 s8.5's specified per-station-day record (ask, the first
blocking gate/reason, fee_coefficient, p_bound/break_even as an edge proxy) —
this plan's own framing that the "broader s8.5 record... remains unbuilt"
(§3(a), §12) was never checked against this existing artefact, and may be
substantially wrong. This is the same class of reuse-diligence the plan itself
performs well elsewhere (WP-B0 landed-commit check, `_load_climate_day_records`
equivalent in the sibling AUD-11 plan) but missed here.

Required change: point §7 step 0 (and §6 item 2's residual-scope framing) at
`offer_tape_<date>.jsonl`/`OfferTapeRecord` instead of (or in addition to)
`TrialDayLatch`/`StateStore`; re-run the empirical count against the correct
source; and explicitly assess, field-by-field, how much of bl19 s8.5's
specified record the existing `OfferTapeRecord` schema already satisfies
before claiming the broader record "remains unbuilt."

## Per-criterion points (out of 20/20/15/20/15/10)

- Fidelity to audit gap and completeness: 15/20 — the fills-only scope
  narrowing is accurate and well-cited, but the residual-scope claim ("the
  broader s8.5 record remains unbuilt") was never checked against the
  existing `OfferTapeRecord` artefact, which likely already satisfies much of
  it — a live, unexamined near-duplicate of scope this plan claims to be
  missing.
- Technical correctness and evidence grounding: 14/20 — WP-B0/`f97c26f`
  framing is now exact (independently re-verified this round); the new §7
  step 0 mechanism is incorrect against source — it queries a table that
  cannot, by construction, hold the data it claims to check.
- Implementation specificity and feasibility: 12/15 — join keys, file
  locations, and the Actor/timer extension point remain concrete and correct;
  deducted because the one NEW mechanism this round (§7 step 0) is not
  actually executable as specified against the right data source.
- Acceptance criteria and validation quality: 15/20 — n=6 honesty and the
  three-valued probe design remain strong and structurally enforced; the new
  §8 criterion requiring §7 step 0's count in the doc would currently
  populate that doc with a structurally-guaranteed-zero, misleading number.
- Autonomous operation, failure handling, recovery: 15/15 — unchanged;
  three-valued AGREE/DISAGREE/UNKNOWN design and unauthenticated-endpoint
  requirement are both sound and unaffected by the defect above.
- Portfolio alignment, scope, dependencies: 10/10 — unchanged; WP-B0
  dependency framing is now accurate, A0 non-duplication is explicit, no
  invented ROI number.

**Total: 81/100.**

## Required changes to reach 100

1. Re-point §7 step 0's pre-check at `offer_tape_<date>.jsonl`
   (`OfferTapeRecord`) rather than `TrialDayLatch`/`StateStore` — the latter
   never persists a `Refuse` decision, so the specified query is guaranteed
   to return zero independent of reality.
2. Before claiming (§3(a)/§12) that bl19 s8.5's broader per-station-day
   record "remains unbuilt," compare `OfferTapeRecord`'s existing fields
   (ask, first-blocking-gate reason, fee_coefficient, p_bound, break_even,
   staleness) against s8.5's specified column list and state explicitly which
   columns (if any) are still missing (e.g. `cli_received_ts`,
   `correction_flag`, `revision_seq`, `vwap_ask_at_intended_size` at
   multiple sizes, dual-slippage edge) rather than treating the whole record
   as unbuilt.
3. Re-run the count in `MEASURED_SLIPPAGE_2026-09-21.md`'s scope-statement
   line against the corrected source once (1) is fixed.

## Blockers

None requiring an operator/strategy-lead ruling. This is a read-only source
correction within existing build authority — the same authority §7 step 0
already claims for itself.

## Score

81/100 — APPROVE WITH WARNINGS. (a)'s fills-only slippage measurement design,
(b)'s fee-drift probe design, and the WP-B0 landed-vs-configured correction
are all sound and independently verified this round. The new §7 step 0
pre-check — the plan's own mechanism for empirically settling its residual-
scope claim — targets a data source that cannot answer the question it asks,
which is a material, source-verified defect a round-2 revision introduced.
