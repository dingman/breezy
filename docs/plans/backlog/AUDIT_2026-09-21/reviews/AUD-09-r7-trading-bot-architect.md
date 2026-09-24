# AUD-09 — Review record (Round 7, ruling-driven revision, delta)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-09-scheduled-per-station-replay.md
- Plan file sha256: 31828b196390bbb65824dcc80cbc62437505029322e6eab367fcf61630df10f9
- Round: 7 · Reviewer: trading-bot-architect (scheduling/pipeline/host-resource lens)
- Total: 100/100 (readiness/self-score text ignored per instruction)

## Scope of this round

Round 6 closed at 100/100 (both reviewers, no defect, no design change). This round applies the
strategy-lead RULING (`docs/evidence/RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21.md`,
Revision 2, peer-ENDORSED) plus one coordinator ownership decision not in the supplied diff. I read
the ruling in full (Rulings-at-a-glance, Q1 items 1–8, Q2, Q4) and verified every plan claim against
it and against source.

## Q1 (`trial_id` provenance) — faithfully applied

- Discriminator is `family_id`, never `trial_id_prefix` — matches RULING item 3, and the plan states
  the withdrawal of revision-1's `trial_id_prefix` shape (item 2) correctly.
- Required id shape quoted verbatim matches the ruling's `f"paper_replay/{manifest.family_id}/
  {manifest.trial_id_prefix}{station}/{climate_day}"` (item 3).
- `manifest_sha256` added to the result row as a **secondary, non-discriminating** check, matching
  item 4 exactly, cited to `family_manifest.py:185` (field) / `:220` (computed) — I re-confirmed
  `manifest_sha256: str` is a `FamilyManifest` field and is `hashlib.sha256(raw).hexdigest()` in
  `load_family_manifest`, both previously verified in round 5 and unchanged.
- New **B20** pins the row's `family_id` + `manifest_sha256` and asserts no selector in this item's
  code discriminates on `trial_id_prefix` — correctly scoped to *this item's* code (item 5 explicitly
  leaves `family_tally_v2.py`/`score_live_trials.py`'s live-side selectors to AUD-05).
- The id-construction fix itself (`runtime/paper_replay.py:92,347` + `live_family_tally.py:91`)
  stays **out of AUD-09's scope**, matching item 7 ("this is a build item... out of scope for AUD-09
  as currently drafted"). The plan does not silently absorb it — confirmed.
- **AUD-19 gate is correctly stated twice, consistently**: §4 ("AUD-19 itself is gated on the
  ruling's Q1 `trial_id` fix"), §5, §6b.2 item 5, and §12 ("AUD-19 is itself gated on the Q1
  `trial_id` fix below landing first") — matching item 7's binding ordering constraint.
- **AUD-09b may build and run before the fix lands** — matches item 8 exactly (containment via
  `C-VALIDITY`/`C-PAIRED`), and the mandated second caveat line is present verbatim in §8, naming
  the parquet `trial_id` as not yet family-scoped and citing `paper_replay.py:92,347` — matches item
  8's exact requirement.

## Coordinator's ownership decision (not in the ruling itself) — internally consistent

The ruling leaves the Q1 fix's owner unnamed ("a build item whose owner is still unnamed... gates
AUD-19", item 7's framing). The plan now records a **separate, explicitly-labelled coordinator
decision**: the fix is owned by AUD-19 as its own first increment (AUD-19a), gating AUD-19's flag
increment (AUD-19b). This does not contradict the ruling — the ruling's binding requirement was
ordering ("must not land before"), not that the fix be a *separate* item, and folding it into AUD-19
as an internally-sequenced first increment satisfies that ordering by construction. The decision is
correctly cited **by id only** (AUD-19 is not itself re-derived or asserted to have any other
content). §12's "Open, for the coordinator" line from the diff is confirmed removed and replaced with
"Resolved: AUD-19a owns the Q1 `trial_id` fix (cited by ID only)."

## Q2 (MECHANISM_ONLY citability) — faithfully applied

§12's bullet replaces the old "default taken: no" language with "RULED... no, and never, for §9
specifically; no, pending AUD-11/AUD-12, for promotion criteria" — matches RULING items 1–3 exactly,
including the permanence of the §9 exclusion (item 2: "not a temporary restriction... unlike
`C-VALIDITY`'s edge-statistic restriction") versus the conditional promotion-criteria restriction
(item 3). No PREREG text change is claimed, matching the ruling.

## Q4 item 1 (`--family-manifest` ownership) — faithfully applied

§4, §5, §6b.2 item 5, and §12 all now read "Owner: AUD-19", cited by id only, with the Q1 gate
recorded in each place — matches RULING item 1 exactly. Round-2's armed-family-only decision is
explicitly stated as not reopened, matching the ruling's own framing ("the ruling explicitly
declined to fold the flag into AUD-09").

## ASOS cache measurement — read-only, correctly scoped, not overclaimed

New §7 step 3 text reports SFO 313 / LAX 314 / MDW 312 / MIA 317 distinct `(station, valid)` rows for
2026-09-01, with three honestly-stated caveats: (i) the method is an anchored-grep reproduction of the
§6b.1 predicate because `asos_cache_csv.py` does not exist yet, so counts are indicative of
non-emptiness only; (ii) the build-time step still re-runs with the real producer — de-risked, not
discharged; (iii) a negative control (SFO 2026-08-20 = 0 rows) proves the cache is not contiguous, so
an older queued day can still yield `ASOS_CACHE_EMPTY` via the existing §9 path. I confirmed
`~/.local/share/breezy/archive/settlement-alignment-cache` exists and contains `KSFO`-tagged `.txt`
files consistent with the claim; I did not re-run the exact anchored-grep count reproduction, which
the plan itself already flags as approximate and non-authoritative pending the real producer. This is
the correct epistemic posture — a pre-check that narrows risk without claiming to discharge B9.

## No regression — B18/C19 and the mirrored property sentence unchanged

B18's text is byte-identical to what was independently verified in rounds 5–7 (property-over-a-
named-script-set, the three named scripts, AUD-10b's sanctioned third invocation, C19 cited as the
mirror). AUD-10 was not touched this round (its own sha256 is unchanged from round 7's close), so the
whitespace-normalized property-sentence identity I confirmed by hash in round 6 still holds by
construction. B19's stall escalation, the runner responsibility table, H0/H3, `climate_day_utc_bounds`,
and the IEM-map bound are all unchanged.

## Defects

None found in this revision, against the rubric (readiness/self-score text excluded from scoring per
instruction). One hygiene observation, explicitly NOT scored per the coordinator's "ignore self-score/
readiness text" instruction: §12's closing "Readiness" numbered list (item 1) still reads "Unowned
build item... Coordinator decision needed on who owns it," which now visibly disagrees with the
"Resolved: AUD-19a owns..." sentence a few dozen lines earlier in the same §12. This is readiness
bookkeeping, not a rubric-scored plan defect, and is reported here only for the coordinator's
awareness, not as a deduction.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | All ruling-mandated text changes applied faithfully and completely; no design/scope change beyond what the ruling requires. |
| Technical correctness and evidence grounding | 20 | 20 | Every claim checked against the ruling's verbatim RULING items and against source (`family_manifest.py:185,220`, the cache directory, `paper_replay.py:92,347`) is exact. |
| Implementation specificity and feasibility | 15 | 15 | B20 is a concrete, testable criterion; the required `trial_id` shape and the `manifest_sha256` cross-check are both decided to the field. |
| Acceptance criteria and validation quality | 20 | 20 | B20 objective and testable; B1–B19 unchanged and unregressed. |
| Autonomous operation, failure handling, recovery | 15 | 15 | Unchanged; the cache-measurement caveats correctly preserve the existing `ASOS_CACHE_EMPTY`/B19 failure path rather than assuming it away. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | Both strategy-lead blockers are now RULED rather than open; ownership is named for both remaining external dependencies; no operator-cap or enablement content introduced. |
| **Total** | **100** | **100** | |

## Required changes to reach 100

None.

## Blockers (recorded, not scored)

- **Build item, owned (AUD-19a):** the Q1 `trial_id` family-scoping fix in `runtime/paper_replay.py`
  + `live_family_tally.py`; gates AUD-19b (`--family-manifest`).
- **Build-time, de-risked not discharged:** §7 step 3 re-runs the ASOS producer for real before the
  timer is enabled.
- **Owned elsewhere, by id:** AUD-19 (both increments), AUD-11/AUD-12 (validity flip), AUD-08b (H1
  register, non-blocking), AUD-10 (H3 consumer).
- **Operator:** none — this ruling proposes no value for either reserved cap and does not touch live
  enablement or the NO-SEND firewall.
