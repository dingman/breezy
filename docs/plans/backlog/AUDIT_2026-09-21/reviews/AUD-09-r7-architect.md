# AUD-09 — Review record (Round 7, ruling-intake delta)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-09-scheduled-per-station-replay.md
- Plan file sha256: 31828b196390bbb65824dcc80cbc62437505029322e6eab367fcf61630df10f9 (coordinator recorded 31828b19…)
- Round: 7 · Reviewer: architect (code-architect lens)
- Total: 98/100 · Readiness: READY on plan quality (two one-line MINORs)

## Ruling application, checked clause by clause against the ruling's own "Consequences — AUD-09"

| Ruling obligation | Applied? |
|---|---|
| §12 R1 bullet → pointer + adapted shape (Q1 items 3-4) + AUD-19 ordering | **YES, faithfully.** The shape is quoted **exactly** as the ruling mandates: `f"paper_replay/{manifest.family_id}/{manifest.trial_id_prefix}{station}/{climate_day}"`. The discriminator is stated as `family_id` **never** `trial_id_prefix`, with the collision evidence carried (`pm_us_crh_cont` / `pm_us_crh_v4` both REGISTERED sharing `"continuous_rung_hold/trial/"` — which I independently confirmed from `deploy/families/*.json` in round 4). Q1 item 6's two-call-site discipline (`paper_replay.py` + `live_family_tally.py:91`, "must move together with a test pinning them equal") and item 7's out-of-scope placement are both recorded. Item 1's live/paper barrier is explicitly noted as untouched. |
| §8 → second caveat line (Q1 item 8) | **YES.** The added line states the parquet `trial_id` is not family-scoped, cites `paper_replay.py:92,347`, distinguishes the family-scoped JSONL row from the non-scoped parquet, forbids cross-family reads on the parquet id, and places the fix outside the item. This is the mandated caveat, and it is stronger than the ruling's minimum. |
| §12 MECHANISM_ONLY bullet → RULED (Q2) | **YES, and complete on both halves.** "never, permanently, for §9 at any validity tag" and "no, pending AUD-11/AUD-12, for edge criteria", plus Q2 item 3's forward clause (a `params_match == true` row **may** feed `C-ESTIMATOR`/`C-N`/`C-PAIRED` once `validity` flips). `C-VALIDITY`, `REPLAY_VALIDITY` and B7 correctly unchanged; no PREREG text touched. |
| §12 `--family-manifest` bullet → Owner AUD-19, gated on Q1 (Q4 item 1) | **YES, and mirrored in four places** — §4 (as a *downstream sibling, not a dependency*), §5, §6b.2 item 5, §12 — each carrying AUD-19's own gate, each citing AUD-19 **by id only**. The armed-family-only decision is not reopened, which is what the ruling's Q4(a) option 1 explicitly required. |
| Q1 item 4's result-row half in scope | **YES.** `manifest_sha256` added to the §6b.2 item 3 field list and the §6b.3 row schema, described correctly as a **secondary, non-discriminating** integrity check against `load_family_manifest(...).manifest_sha256` (`family_manifest.py:185`, computed `:220`), with the discriminator named as `family_id`. New **B20** pins the equality *and* asserts no selector in this item discriminates on `trial_id_prefix`. |
| Coordinator's out-of-diff edit (AUD-19a owns the Q1 fix) | **Applied coherently in §12.** The bullet now reads "…the ruling assigns it to **no existing item**. **Coordinator decision 2026-09-21: owned by AUD-19 as its first increment (AUD-19a), which gates AUD-19's flag increment (AUD-19b)** … **Resolved: AUD-19a owns the Q1 `trial_id` fix (cited by ID only)**." No "still unnamed" residue remains in §12, and the increment split is consistent with the ruling's gate (19a before 19b). |

**Nothing regressed.** §6b.3's property sentence and **B18**'s three-script set are **not in the diff at
all** — byte-unchanged, so the normalised-hash anchor (`ce5b6d1d…a26263`) and AUD-10's C19 mirror still
hold. No criterion, step, hand-off or decision was removed; B1–B19 are intact and B20 is additive. §12's
remaining list is accurate: the ASOS build-time re-run, AUD-19/AUD-11/AUD-12/AUD-08b/AUD-10 by id, and
the sixth-station `IEM_ASOS_IDS` constraint.

**The measurement, re-run independently.** I did not take the numbers on trust. `~/.local/share/breezy/
archive/settlement-alignment-cache` exists and holds URL-hash-named `.txt` files, of which the ASOS ones
carry a literal `station,valid,metar` header with rows shaped `SFO,2026-09-01 HH:MM,KSFO …`. My own
anchored count over `^SFO,2026-09-01 ` returns **314 rows per cached copy** (24 files carry the day; the
copies are duplicates that `load_recent_asos_rows` de-duplicates on `(station, valid)`). The plan claims
**313 distinct rows inside the local-standard climate-day window** — one fewer than the raw UTC-date
count, which is exactly the boundary difference the plan's own caveat (i) predicts. **The load-bearing
claim (non-empty for the expected first target) is confirmed**, the caveats are the right three, and the
negative control (a non-contiguous cache) is the honest framing. This is measurement done properly:
positive control, negative control, stated method, stated limits, and it does **not** discharge §7 step 3.

## Defects found in revision 7

**09-6 (MINOR, NEW) — one clause of a RULED obligation is now assigned to nobody and named nowhere.**
Q1 RULING item 4 mandates `manifest_sha256` "in every replay result row — **both** the
`replay_results.jsonl` row … **and the underlying parquet's own metadata**". The plan takes the JSONL
half (correctly, with B20) and describes it as "the only half of Q1 the ruling assigns here" — but the
**parquet-metadata half is never mentioned**, neither as in-scope nor as out-of-scope-with-an-owner.
§12's residual describes the unowned/AUD-19a item as the **id-construction** fix only
(`paper_replay.py:92,347` + `live_family_tally.py:91`). The parquet metadata is written on the same
excluded path, so it plainly belongs with AUD-19a — but as drafted the obligation falls between the two
plans, which is how ruled work silently goes undone.
REQUIRED: add one clause to §12's AUD-19a description (and, if you wish, to §8's caveat) — *"and the
parquet's own metadata gains `family_id` + `manifest_sha256` (Q1 item 4's second half), on the same
excluded path"*.

**09-7 (MINOR, NEW) — the evidence-artefact enumeration is stale against the new criterion.** §8 still
reads *"`docs/evidence/SCHEDULED_REPLAY_<date>.md` carrying **B1–B19**"* while **B20** now exists in the
table (and §13 correctly says "plus the measurement and B20"). A criterion outside the artefact's
enumeration is a criterion that may not be evidenced. This is the identical class I raised against
AUD-10's "C1–C16" in round 5, and AUD-10 fixed it by updating the range.
REQUIRED: "B1–B20".

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | Every mandated consequence is applied, in the ruling's own terms, with the armed-family-only design untouched and no scope quietly absorbed. −1: one clause of Q1 item 4 (parquet metadata) is unrecorded and unowned (09-6). |
| Technical correctness and evidence grounding | 20 | 20 | The `trial_id` shape matches the ruling verbatim; the collision evidence is real; `family_manifest.py:185,220`, `paper_replay.py:92,347`, `live_family_tally.py:91` all check out; and the new ASOS measurement reproduces independently (314 raw vs 313 windowed — consistent with its own stated boundary caveat), with a negative control and an explicit "de-risked, not discharged". |
| Implementation specificity and feasibility | 15 | 15 | The runner module, `record_blocked`, `climate_day_utc_bounds`, the full argument vector, the stall rule and now the `manifest_sha256` field and its check are all decided; the ruling resolved the two questions that were open to an owner, not to the implementer. |
| Acceptance criteria and validation quality | 20 | 19 | B20 is objective and tests the right thing (equality against the loaded manifest **plus** the negative property that no selector uses `trial_id_prefix`); B18/B19 unchanged and sound. −1: the evidence artefact still enumerates B1–B19 (09-7). |
| Autonomous operation, failure handling, recovery | 15 | 15 | Unchanged and still complete: `ASOS_CACHE_EMPTY` keeps the day queued, unreadable-work-list ≠ empty queue, crash recovery, duplicate-key hard error, skip-not-kill, own-cgroup OOM, and B19's one-shot stall escalation. The measurement strengthens the first-run expectation without weakening any refusal. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | Mechanism-vs-edge separation intact and now ruled; AUD-19/AUD-05/AUD-11/AUD-12/AUD-10/AUD-08b all cited **by id only** with no assertion about their content or schedule; PREREG barrier confirmed rather than touched; no operator-cap, enablement or NO-SEND contact. |
| **Total** | **100** | **98** | |

## Required changes to reach 100
1. Record Q1 item 4's **parquet-metadata** half with its owner (AUD-19a) in §12 (09-6).
2. §8: "B1–B19" → "B1–B20" (09-7).

## Notes and blockers (recorded separately; not scored)
- **Instructed-ignore, but flagged for the closing pass:** §13's readiness list item 1 still reads
  *"Unowned build item … Coordinator decision needed on who owns it"*, which the coordinator's §12 edit
  has since resolved ("AUD-19a owns it"). I was told to ignore self-score/readiness text and have not
  scored it; it should be reconciled when the round closes, or the file contradicts itself.
- **Owned elsewhere, by id:** AUD-19a (Q1 fix) → AUD-19b (`--family-manifest`); AUD-11/AUD-12 (validity
  flip); AUD-08b (H1, non-blocking); AUD-10 (H3 + the sanctioned third wrapper invocation).
- **Build-time, de-risked not discharged:** §7 step 3 re-runs the producer for real; the timer stays
  disabled until step 13 yields a non-`BLOCKED` row.
- **Evidence limit, correctly stated:** the cache is not contiguous, so an older queued day can still
  yield `ASOS_CACHE_EMPTY` — the §9 path with B19's escalation, not a defect.

_Saved verbatim by the coordinator: the `architect` reviewer has no file-write tool._
