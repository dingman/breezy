# AUD-09 — Review record (Round 8, micro-delta, FINAL)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-09-scheduled-per-station-replay.md
- Plan file sha256: 32a2d7591730b6227a96f1f1c2547830ab65b8ab3a7239c69ba5e7f4e6b7e95b (coordinator recorded 32a2d759…)
- Round: 8 (micro-delta) · Reviewer: architect (code-architect lens)
- Total: 100/100 · Readiness: READY

## Round-7 dispositions, verified in place

| R7 defect | Claimed | Verified? |
|---|---|---|
| **09-6 (MINOR)** — Q1 RULING item 4 mandates `manifest_sha256` in **both** the `replay_results.jsonl` row **and** the underlying parquet's metadata; the plan took the JSONL half and left the parquet half named nowhere and owned by nobody | FIXED | **CONFIRMED at §12**, directly after the ownership resolution: *"The same excluded path carries Q1 item 4's SECOND half: the parquet's own metadata gains `family_id` + `manifest_sha256` — also AUD-19a's, not this item's (this item takes the JSONL-row half, B20)."* This is the right assignment and the right reasoning: the parquet is written on the path §5 excludes and Q1 item 7 places outside this item, which is the same path AUD-19a already owns for the id construction — so the obligation now has a home rather than falling between two plans. It also draws the in/out boundary explicitly (JSONL row = this item, pinned by B20; parquet metadata = AUD-19a), so neither half can later be assumed done because the other was. |
| **09-7 (MINOR)** — §8's evidence artefact still enumerated "B1–B19" after B20 was added | FIXED | **CONFIRMED at §8:** *"`docs/evidence/SCHEDULED_REPLAY_<date>.md` carrying **B1–B20**"*, with the look-ahead caveat and the mandated second (`trial_id` not-family-scoped) caveat both still following it intact. B20 exists in the criteria table, so the enumeration and the table now agree. |
| **Unscored closing-pass flag** — §13's readiness item 1 still said the Q1 fix owner was undecided, contradicting §12's "Resolved: AUD-19a" | FIXED | **CONFIRMED at §13:** *"Build item owned by AUD-19a (gates AUD-19b, does NOT gate this item's build) … Owner decided 2026-09-21: AUD-19a (see §12)."* The file no longer contradicts itself, and the cross-reference points at the section that carries the decision. |

## Regression check

The three edits are textually local and I re-read their neighbourhoods: §8's two caveat paragraphs are
unchanged and still follow the evidence-artefact line; §12's surrounding bullets (the AUD-19-owned
`--family-manifest` dependency, the RULED `trial_id` provenance bullet with the ruling's exact id shape,
the RULED MECHANISM_ONLY bullet, the sixth-station `IEM_ASOS_IDS` constraint) are untouched; §13's
remaining readiness items 2–4 are unchanged. **B18's three-script set and §6b.3's property sentence were
not in scope of this delta and remain byte-unchanged**, so the normalised-hash anchor (`ce5b6d1d…a26263`)
and AUD-10 C19's mirror still hold. No criterion, step, hand-off or decision was added, renumbered or
removed; B1–B20 are intact.

Everything I verified in round 7 stands: the ruling is applied faithfully clause by clause (the exact
`f"paper_replay/{manifest.family_id}/{manifest.trial_id_prefix}{station}/{climate_day}"` shape, the
`family_id`-not-`trial_id_prefix` discriminator with its proven collision, Q1 items 6/7/8, Q2's two
halves plus its forward clause, Q4's AUD-19 ownership with its gate), and the ASOS measurement
reproduces independently against the real cache with the boundary caveat it states.

## Defects found in revision 8

**None.** Both round-7 MINORs are closed at the text I asked for, and neither fix introduced a new claim
or a new cross-reference that does not hold.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | Every mandated consequence of the ruling is applied in the ruling's own terms, and **both** halves of Q1 item 4 are now recorded with the in/out boundary and an owner — the round-7 deduction is discharged. The census, the scheduled runner, the machine-readable result and the ASOS producer remain fully in scope; the armed-family-only design is not reopened. |
| Technical correctness and evidence grounding | 20 | 20 | The id shape matches the ruling verbatim; `family_manifest.py:185,220`, `paper_replay.py:92,347`, `live_family_tally.py:91` all check out; the ASOS measurement reproduces independently (314 raw UTC-dated SFO rows vs the plan's 313 windowed — exactly the boundary difference its own caveat predicts), with a negative control and an explicit "de-risked, not discharged". |
| Implementation specificity and feasibility | 15 | 15 | The runner module and its responsibility table, `record_blocked`, `climate_day_utc_bounds`, the complete argument vector, the stall rule, and the `manifest_sha256` field with its check are all decided to the symbol. |
| Acceptance criteria and validation quality | 20 | 20 | B1–B20 objective and now fully enumerated in the evidence artefact — the round-7 deduction is discharged. B20 pins both the positive (equality against the loaded manifest) and the negative (`trial_id_prefix` is never a selector) properties; B18 survives AUD-10 landing; B19 pins the stall escalation from four sides. |
| Autonomous operation, failure handling, recovery | 15 | 15 | `ASOS_CACHE_EMPTY` keeps the day queued; unreadable-work-list ≠ empty queue; crash recovery, duplicate-key hard error, skip-not-kill flock, own-cgroup OOM, timer gated on a non-`BLOCKED` row, and the one mode unit state cannot express escalates once on its own. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | Mechanism-vs-edge separation intact and now ruled; AUD-19a/AUD-19b, AUD-05, AUD-11/AUD-12, AUD-08b and AUD-10 all cited **by id only**, with no assertion about content or schedule; PREREG barrier confirmed rather than touched; no operator-cap, enablement or NO-SEND contact. |
| **Total** | **100** | **100** | |

## Required changes
None. This closes every defect I have raised against AUD-09 across rounds 3–7 (09-1 … 09-7, b1–b3).

## Blockers and dependencies (recorded separately; not scored)
- **Owned elsewhere, by id:** AUD-19a (Q1 `trial_id` family-scoping **and** the parquet-metadata half)
  → gates AUD-19b (`--family-manifest`); AUD-11/AUD-12 (validity flip); AUD-08b (H1 register,
  non-blocking); AUD-10 (H3 consumer plus its sanctioned third wrapper invocation under B18).
- **Build-time, de-risked but not discharged:** §7 step 3 re-runs the ASOS producer for real; the timer
  stays disabled until step 13 yields a non-`BLOCKED` row.
- **Evidence limit, correctly stated:** the cache is not contiguous (negative control SFO 2026-08-20 =
  0 rows), so an older queued day can still yield `ASOS_CACHE_EMPTY` — the §9 path with B19's
  escalation, not a defect.
- **Knowingly bounded residual (agreed):** a 30-day stall produces one alert rather than a standing
  signal; a standing-signal design belongs to the alerting item, not here.

_Saved verbatim by the coordinator: the `architect` reviewer has no file-write tool._
