# RULING — Replay evidence citability, trial_id provenance, R5-7/R5-8 transfer, and the two INERT dependency owners

Status: ENDORSED 2026-09-21 — independent peer review ENDORSE on all four rulings, no required change, on Revision 2 (`docs/evidence/reviews/RULING_citability_review_2026-09-21.md`). Rulings delegated to engineering peers by the operator.

Slug: `replay_evidence_citability_and_promotion_criteria`
Author: independent evaluation-methodology peer (blind; no other peer's output consulted)
Date: 2026-09-21

**Revision 2 (2026-09-21).** Independent review (`docs/evidence/reviews/RULING_citability_review_2026-09-21.md`):
Q1 REJECT-as-written, Q2 ENDORSE, Q3/Q4 ENDORSE-WITH-REQUIRED-CHANGES. All four points independently
re-verified against source this revision; Q1's discriminator is replaced (`trial_id_prefix` → proven
non-unique on this tree; `family_id` is now the mandated discriminator), Q3 gains a PROVISIONAL tag and
a corrected bootstrap-call citation, Q4 reconciles ownership to a single owner (AUD-05, implementing
SP-1 I5) and names the sibling driver item AUD-19. Q2 is unchanged. See each section's "REVISION-2"
markers for the exact deltas. Status remains PROPOSED.

## Rulings at a glance

| Q | Verdict | One-line ruling |
|---|---|---|
| Q1 | `trial_id_prefix` REJECTED as discriminator (proven collision: `pm_us_crh_cont` and `pm_us_crh_v4` share it byte-for-byte); mandated fix is `family_id` | `trial_id = f"paper_replay/{family_id}/{trial_id_prefix}{station}/{climate_day}"`; live/paper barrier unaffected; gates AUD-19 |
| Q2 | Confirmed, unchanged | `MECHANISM_ONLY` (any validity tag) never feeds PREREG v3 §9 (permanently, live-venue-only) or a promotion criterion while `MECHANISM_ONLY`/`params_match=false` |
| Q3 | Transfer WITH adaptations, tagged PROVISIONAL | `fit_date`→`d0_climate_day`; estimator/bootstrap already shared code (citation corrected: `random_state=np.random.default_rng(SEED)`, not `seed=`); PROVISIONAL lifts on first no-`INERT` run |
| Q4a | New item **AUD-19** | `--family-manifest` on the replay driver; gated on Q1's fix landing first |
| Q4b | **AUD-05 exclusively** | champion-scoped KILL clock; implements SP-1 I5 (spec of record unchanged); supersedes R-4's stale `pm_us_crh_cont.json` literal — clock must follow `sending_family_id` dynamically |

## 0. Scope note

This ruling addresses four strategy-lead questions blocking `docs/plans/backlog/AUDIT_2026-09-21/AUD-09-scheduled-per-station-replay.md`
(AUD-09) and `docs/plans/backlog/AUDIT_2026-09-21/AUD-10-evidence-gated-promotion-proposal.md` (AUD-10).
Both plans are **planning-only artefacts — nothing below has been implemented.** This ruling does not
authorize, request, or imply a value for either operator-reserved cap, and does not touch live-trading
enablement or the NO-SEND firewall. It changes PREREG semantics only insofar as §9's citability rule
(Q2) and R5-7/R5-8's transfer (Q3) are ruling questions the plans themselves deferred to this artefact.

---

## Q1 — `trial_id` provenance for replay-generated rows

**Verbatim question**, AUD-09 §12: *"BLOCKER — strategy lead (does NOT block the build, blocks any
statistical reading): paper/replay `trial_id` provenance. `PAPER_TRIAL_ID_PREFIX =
"paper_replay/current_rung_hold/trial"` (`runtime/paper_replay.py:92,347`) is v2-named and v3 rows
would share it — ruling **R1** in `V3_BACKTEST_REPLAY_SUBCLASS_2026-09-12.md` §8, still open."* Also
carried, unresolved, into AUD-09's "Coordinator final status" (line 1169): *"Strategy lead: R1
`trial_id` provenance; whether a `MECHANISM_ONLY` result may be cited under PREREG v3 §9 (default
taken: no)."*

### Evidence (verified against source, 2026-09-21; RE-VERIFIED in revision 2 per independent review)

- `src/breezy/runtime/paper_replay.py:92`: `PAPER_TRIAL_ID_PREFIX: Final[str] = "paper_replay/current_rung_hold/trial"`.
- `src/breezy/runtime/paper_replay.py:347`: `trial_id = f"{PAPER_TRIAL_ID_PREFIX}/{ctx.station}/{ctx.climate_day}"`
  — **no family, no strategy, no composition-kind component anywhere in the id.**
- `scripts/analysis/live_family_tally.py:83`: `_LIVE_TRIAL_ID_PREFIX = "current_rung_hold/trial/"`.
- `scripts/analysis/live_family_tally.py:91`: `_PAPER_TRIAL_ID_PREFIX = "paper_replay/current_rung_hold/trial/"`
  — a **second, independently hardcoded copy** of the same v2-shaped literal (comment: "restated
  verbatim here, not imported").
- `scripts/analysis/live_family_tally.py:148-180`: `assert_live_only`/`assert_paper_only` refuse any
  row whose `trial_id` does not start with the respective prefix (`str.startswith`, confirmed by
  reading the function bodies) — this is the live/paper barrier, and it is unforgeable and correct as
  far as it goes, and holds regardless of everything below.
- `src/breezy/persistence/family_manifest.py:179`: `FamilyManifest.trial_id_prefix: str` — already a
  validated, loaded field.
- **REVISION-2 CORRECTION — the original Q1 fix is REJECTED as written.** Verified this round,
  `deploy/families/pm_us_crh_cont.json:3-4` and `deploy/families/pm_us_crh_v4.json:3-4` (both files
  read in full):

  | manifest | `family_id` | `trial_id_prefix` | `status` | `terminal_climate_day` |
  |---|---|---|---|---|
  | `pm_us_crh_cont.json` | `pm_us_crh_cont` | `continuous_rung_hold/trial/` | `REGISTERED` | `2026-09-19` |
  | `pm_us_crh_v4.json` | `pm_us_crh_v4` | `continuous_rung_hold/trial/` | `REGISTERED` | (none — active) |

  **The two manifests share an IDENTICAL `trial_id_prefix`.** The revision-1 ruling's mandated shape
  — `f"paper_replay/{manifest.trial_id_prefix}{station}/{climate_day}"` — therefore produces
  **byte-identical replay ids for two separately-REGISTERED families**, which is exactly the collision
  Q1 exists to prevent. That fix is withdrawn below.
- **Coordinator hand-down (relied on, not re-derived here):** `pm_us_crh_cont` is RETIRED as of
  `bcb82d6` (verified: `git log -1 bcb82d6` = *"fix(alerts): tee to log AND webhook; promote the unit
  to pm_us_crh_v4"*, 2026-09-20; `pm_us_crh_cont.json`'s own `terminal_climate_day: "2026-09-19"` is
  consistent with this). Its manifest stays on disk `REGISTERED` as history — it is not deleted or
  reclassified — and `pm_us_crh_v4` is ruled "may not SEND orders" but stays the deployed
  `sending_family_id`. A future re-arm mints a **new** family id, new `trial_id_prefix`, n=0 (L-34
  class C). This retroactively explains *why* the collision above exists (two `continuous_rung_hold`
  compositions issued nine days apart share the literal, unversioned prefix `composition_kind` maps
  to) and confirms it is not a one-off authoring slip — nothing in the manifest schema enforces
  `trial_id_prefix` uniqueness across registrations, only `family_id` (the file/registry key) is a
  primary key.
- **Selector audit (round-2, the review's explicit instruction) — every row selector reachable from
  `trial_id`/`trial_id_prefix`, re-read this round:**
  - `scripts/analysis/family_tally_v2.py:548`: `filter_rows_to_manifest_prefix` —
    `if row.trial_id.startswith(manifest.trial_id_prefix): ...` — **prefix match, on the LIVE id
    space** (`current_rung_hold/trial/...` / `continuous_rung_hold/trial/...`, no `paper_replay/`
    segment). Would match rows from **both** `pm_us_crh_cont` and `pm_us_crh_v4` identically if ever
    read outside its own per-`family_id` store subdirectory — this is the **live-side** twin of the Q1
    defect, already named in AUD-05's own title (*"resolve the `pm_us_crh_v4` / `pm_us_crh_cont`
    `trial_id_prefix` collision"*) and out of this ruling's scope to fix (AUD-05 owns it).
  - `scripts/analysis/score_live_trials.py:611,675,689,707,861,1079,1788`: `count_filled_takes` and
    siblings key on `family_prefix` via **plain `str.startswith`** (docstring at `:611`, verified) —
    same prefix-collision exposure, same AUD-05 ownership.
  - **No selector anywhere in `family_tally_v2.py` or `score_live_trials.py` uses substring matching**
    (`in`, `re.search`, etc.) — every match found this round is `startswith`, confirmed by grep and
    read. The review's "prefix OR substring" concern is therefore fully answered: substring matching
    does not exist as a risk; prefix-collision (not substring) is the real and confirmed one.
  - **The live/paper barrier is unaffected by any of the above**, because it keys on the outer literal
    (`"paper_replay/"` present or absent), never on `trial_id_prefix`'s content — a replay row can
    still never be selected as live, under any discriminator choice made below.
  - **`family_id` is not subject to the same collision**: it is the manifest's own file/registry key
    (`deploy/families/<family_id>.json`), and by the coordinator's hand-down a re-arm always mints a
    **new** `family_id` (L-34 class C) — two simultaneously-`REGISTERED` manifests sharing one
    `family_id` would be a distinct, more severe defect (a genuine primary-key violation) that no
    evidence found and this ruling does not need to guard against for `trial_id` purposes.
- AUD-09 §6b.2 (accepted, round-2 09-2): the runner replays the **armed family only**, using the
  **same** `current_rung_hold_paper_replay.py` script / `runtime/paper_replay.py` library regardless
  of which family is armed. `paper_replay.py`'s trial-id construction has no branch on
  `composition_kind` or `family_id`.
- Consequence, verified by construction: **AUD-09b's very first real run** (§7 step 13, expected
  target SFO 2026-09-01, armed family `pm_us_crh_v4`) will emit paper trial rows whose `trial_id` is
  literally `paper_replay/current_rung_hold/trial/SFO/2026-09-01` — the **v2-family-shaped** id —
  even though the replayed strategy is `continuous_rung_hold`, and (per the collision above) would be
  **indistinguishable from a `pm_us_crh_cont` replay of the same day** if `trial_id_prefix` alone were
  ever used as the discriminator.
- Containment that already exists and is not in question: AUD-10's `C-VALIDITY` (§6b.3) refuses any
  row with `validity == "MECHANISM_ONLY"` or `params_match == false` as an edge input, and `C-PAIRED`
  is `INERT` (no challenger-replay path exists at all, per AUD-09 §6b.2 item 5 / AUD-10 §6b.3). No
  code path in either plan reads the replay **parquet** by `trial_id` across families today. So the
  collision is **latent, not live-wired**, today — this is unchanged by the revision-2 correction.

### Options considered

1. **Leave open / decide nothing** — rejected. The plan itself names this as blocking "any statistical
   reading," and the repo's own costliest recurring defect class (`bss-headline-is-the-wrong-family`,
   `archive-table-train-serve-skew`) is exactly a statistic silently attached to the wrong family.
   Leaving a known, reproducible id collision undecided while build work proceeds is not conservative.
2. **Declare the collision immaterial because C-VALIDITY/C-PAIRED already block every consumer** —
   rejected as the ruling, though it is true today, for the same reason as revision 1: it relies on two
   unrelated barriers staying closed forever.
3. **(REVISION 1, WITHDRAWN) Discriminate on the manifest's `trial_id_prefix`** — rejected this round
   on direct evidence: `pm_us_crh_cont` and `pm_us_crh_v4` already share an identical
   `trial_id_prefix` on disk today. A discriminator that is already non-unique on the current tree
   cannot be the ruling.
4. **Discriminate on `family_id` (the manifest's own registry primary key), recording
   `manifest_sha256` alongside as a secondary integrity check** — **taken.** `family_id` is unique by
   construction (one file per family under `deploy/families/`, and per the coordinator's hand-down a
   re-arm always mints a *new* `family_id`, never reuses a retired one's), so this discriminator holds
   whether or not any family's `trial_id_prefix` is ever re-issued or shared — which it already has
   been, twice, on this tree.

### RULING

1. **A replay row may never share an id space with a live trial.** The existing barrier —
   `trial_id` must start with the literal `"paper_replay/"` segment for any paper/replay consumer, and
   never for a live consumer — is correct, already unforgeable (`assert_paper_only`/`assert_live_only`,
   both confirmed `startswith`-only, no substring matching anywhere in the selector set), and **is not
   overturned.** Nothing in this ruling touches that boundary, and nothing below changes it, because
   every discriminator considered is inserted *inside* the `"paper_replay/"`-prefixed namespace, never
   removes or reorders that leading literal.
2. **REVISION 1's mandated shape is WITHDRAWN.** `trial_id_prefix` is proven non-unique
   (`pm_us_crh_cont` and `pm_us_crh_v4` share `"continuous_rung_hold/trial/"` verbatim) and may never
   be the sole discriminator for a replay id.
3. **The mandatory provenance tag is `family_id`**, the manifest's own registry primary key, embedded
   as its own path segment, positioned immediately after the `"paper_replay/"` literal and before the
   (now merely descriptive, non-discriminating) `trial_id_prefix`/station/day tail. The required shape:

   ```
   trial_id = f"paper_replay/{manifest.family_id}/{manifest.trial_id_prefix}{station}/{climate_day}"
   ```

   which for `pm_us_crh_v4` yields
   `paper_replay/pm_us_crh_v4/continuous_rung_hold/trial/SFO/2026-09-01`, and for a hypothetical
   `pm_us_crh_cont` replay of the same day yields
   `paper_replay/pm_us_crh_cont/continuous_rung_hold/trial/SFO/2026-09-01` — **never** colliding, and
   remaining non-colliding under any future `trial_id_prefix` re-issuance, because `family_id` is the
   axis that is actually guaranteed unique.
4. **`manifest_sha256` is recorded alongside `family_id` in every replay result row** (both the
   `replay_results.jsonl` row AUD-09 §6b.2 already extends with `manifest_taker_fee_coefficient` etc.,
   and the underlying parquet's own metadata) as a **secondary, non-discriminating** integrity check —
   the same "record both, don't just trust one" posture AUD-09 §6b.2 already applies to
   `engine_required_fee_coefficient` vs `manifest_taker_fee_coefficient`. It is not part of the
   `trial_id` string itself (that would make an already-long id unreadable); it is a companion field a
   reader can cross-check against `load_family_manifest(...).manifest_sha256` for the named
   `family_id` to catch a hand-edited or stale manifest.
5. **Selectors that key on `trial_id_prefix` alone (`filter_rows_to_manifest_prefix`,
   `count_filled_takes`'s `family_prefix` checks) are a SEPARATE, live-side instance of the identical
   defect, already named in AUD-05's own title, and are explicitly OUT OF SCOPE for this ruling to
   fix.** This ruling only mandates the discriminator for the *replay/paper* `trial_id` construction in
   `runtime/paper_replay.py`; it does not touch `family_tally_v2.py`/`score_live_trials.py`'s live-side
   selectors, which are AUD-05's to resolve on its own already-declared collision.
6. **Both paper-side call sites that encode the paper-namespace assumption must move together, and a
   test must pin them equal** — the same discipline AUD-09's own `B15` already applies to
   `InstanceSpan.verdict`: `runtime/paper_replay.py`'s trial-id builder, and `live_family_tally.py`'s
   restated `_PAPER_TRIAL_ID_PREFIX` check (which must become: literal `"paper_replay/"` outer prefix,
   then an exact-equality check against the manifest's `family_id` segment — never a single hardcoded
   full string, and never a `trial_id_prefix` comparison for discrimination purposes).
7. **This is a build item, not something this ruling authors.** It is out of scope for AUD-09 as
   currently drafted (§5 excludes changes to `current_rung_hold_paper_replay.py`; the fix lives one
   layer down, in `runtime/paper_replay.py` and `live_family_tally.py`, which AUD-09 also does not
   touch). **Gate:** AUD-19 (the `--family-manifest` flag item, see Q4) **must not land before this fix
   lands** — landing challenger-replay first would manufacture the exact collision on its first
   execution, with no barrier catching it. This ordering constraint is binding and is recorded in
   AUD-19's own dependency list (§6 below).
8. **Until the fix lands, AUD-09b may still build and run** (containment via `C-VALIDITY`/`C-PAIRED`
   holds today), but every result-record consumer must be told, in the evidence artefact, that the
   underlying parquet `trial_id` is **not** family-scoped yet — a one-line caveat alongside the
   existing look-ahead caveat AUD-09 §8 already mandates.

### Rationale, and the strongest argument against

The strongest argument against `family_id` as the discriminator, raised by construction rather than by
a reviewer, is that it makes the `trial_id_prefix` segment redundant inside the paper namespace (it no
longer discriminates anything, only describes the composition kind for a human reader) — a cleaner
design might drop `trial_id_prefix` from the paper id entirely and keep only `family_id`. This is
rejected in favor of keeping both: `trial_id_prefix` still carries the strategy/composition-kind
information a reader wants without a manifest lookup, and removing it would be a bigger, unforced
change to an id shape already read by nothing today (§Q1 evidence) — the minimal fix inserts the
missing discriminator, it does not redesign the id. The strongest argument against ruling now at all is
unchanged from revision 1: AUD-09's own "does NOT block the build." That remains true and this ruling
still does not reopen AUD-09's build scope — it rules the provenance tag and the ordering constraint,
and leaves the fix itself to AUD-19.

---

## Q2 — May a `MECHANISM_ONLY` replay result be cited in a PREREG v3 §9 context, or feed any promotion criterion?

**Verbatim question**, AUD-09 §12 (also mirrored in AUD-10 §5/§6b.3's `C-VALIDITY`): *"BLOCKER —
strategy lead: whether a scheduled MECHANISM_ONLY replay result may ever be cited in a PREREG v3 §9
context. Default taken here: no — resolver/paper rows are residual and n grows only via the live
create path (memory `resolver-fills-are-residual-by-prereg`). Changing that needs a ruling artefact
under `docs/evidence/`, which this plan does not author."*

### Evidence

- `docs/specs/PREREG_v3_continuous_rung_hold_DRAFT_2026-09-10.md:197-199`, §9 "Structural-Dead Test
  (unchanged from v2)": *"Window [12:00, 17:00) LST, 30 min afternoon-covered threshold, ≥15 covered
  listed station-days denominator."* This count (`covered_listed_station_days`) is computed **only**
  from live venue quote/depth-listing coverage, via `count_covered_listed_station_days_from_catalog`
  (`structural_dead_stop.py:237`) — a LIVE-tape measurement, not a replay-sufficiency measurement.
- AUD-09a's census (`replay_sufficiency.py`/`replay_sufficiency_census.py`) computes a **structurally
  similar but semantically different** quantity over the **same** tape catalog: whether a station-day
  has enough CLEAN Depth10 coverage to be **replayed offline** — reusing the same ≥30 min threshold
  (`structural_dead_stop.py:163-216`) "so the census and the KILL clock cannot disagree about
  'covered'" (AUD-09 §6a). The shared threshold is a deliberate consistency choice; it does **not**
  make the two artefacts interchangeable inputs.
- AUD-10 §6b.3, `C-VALIDITY` row: *"every replay-derived input row carries `validity !=
  REPLAY_VALIDITY` ("MECHANISM_ONLY") and `params_match == true`, else no edge statistic may be
  cited"* — the default AUD-09/AUD-10 already took.
- AUD-10 §6b.3, `C-KILL` binding table: the **only** two inputs `C-KILL` may read are the
  `covered_listed_station_days_<UTC-day>.json` counter (`structural_dead_stop.py --output`, live-venue
  scoped) and `count_filled_takes` over the exec-state DB (live fills). Neither is, nor is permitted to
  become, a replay artefact.
- Memory `resolver-fills-are-residual-by-prereg`: n grows only via the live create path — cited
  correctly by both plans.

### Options considered

1. **Yes, a MECHANISM_ONLY row may feed §9 or a promotion criterion** — rejected. §9 is a live-venue
   safety/KILL measurement; MECHANISM_ONLY is explicitly a validity tag meaning "no look-ahead
   correction, no cost model, not yet an edge or coverage fact a safety clock may rely on." Admitting
   it would let an offline mechanism artefact gate a live safety stop — the fail-open direction.
2. **No for promotion criteria, but census/replay coverage MAY substitute for or corroborate §9's
   `covered_listed_station_days` when the live counter is stale/absent** — rejected. This is the
   specific new risk this question is actually probing (the two artefacts look interchangeable because
   they scan the same catalog with the same threshold). Substituting one for the other would silently
   change what "covered" means for a KILL clock without a PREREG amendment.
3. **No, categorically, on both counts — confirm the default AUD-09/AUD-10 already took, and extend
   the clause explicitly to §9** — **taken.**

### RULING

1. **Confirmed: a `MECHANISM_ONLY` replay result may never feed any promotion criterion requiring an
   edge statistic.** `C-VALIDITY` as written stands, unmodified.
2. **Confirmed and extended: no replay-derived artefact — of any validity tag, `MECHANISM_ONLY` or
   otherwise — may ever be read by, substituted into, or used to corroborate PREREG v3 §9's structural-
   dead test.** §9's `covered_listed_station_days` is defined over **live venue coverage only**
   (`structural_dead_stop.py`'s `--catalog-root` scan against the live tape), and must stay so
   permanently — this is not a temporary restriction that lifts once AUD-11/AUD-12 land, unlike
   `C-VALIDITY`'s edge-statistic restriction (see below). AUD-09a's census answers "can this day be
   replayed offline," which is a different question from "did the venue list this station-day live,"
   even though both are computed from the same catalog with the same 30-minute threshold.
3. **Once AUD-11 (look-ahead) and AUD-12 (costs) land and `validity` flips off `MECHANISM_ONLY`**,
   replay rows with `params_match == true` **may** feed `C-ESTIMATOR`/`C-N`/`C-PAIRED` — that is the
   intended design and this ruling does not change it. **They may never feed §9**, at any validity
   tag, under any future change to AUD-11/AUD-12 — a second, independent ruling would be required to
   change that, because §9 is a safety clock, not an evidence gate.

### Rationale, and the strongest argument against

The strongest argument against extending the ruling to §9 explicitly is that neither plan actually
proposes reading replay data into §9 today — AUD-10's `C-KILL` binding is already scoped to the two
live artefacts. But the structural similarity between the census and the KILL counter (same catalog,
same threshold, same "covered" vocabulary) is exactly the kind of resemblance that produces the
"statistic attached to the wrong family/wrong purpose" error class this repo has paid for twice
already (`bss-headline-is-the-wrong-family`, `archive-table-train-serve-skew`). Ruling it out now, in
writing, costs nothing today and forecloses a plausible future shortcut (e.g., "the census already
computed coverage, let's just read that instead of running the counter script again").

---

## Q3 — Do R5-7/R5-8 transfer to `continuous_rung_hold`, and what does champion/challenger mean at admissible n = 0?

**Verbatim question**, AUD-10 §12: *"BLOCKER — strategy lead (real, score-capping for 10b, retained
from rounds 1 and 2): the promotion criteria in `FORECAST_EDGE_PEER_REVIEW_2026-09-18.md:121-152` were
written for the forecast family (`pm_us_crh_fc_v1`, PREREG v6), and that programme is CLOSED as
terminal (`RULING_forecast_edge_programme_closes_2026-09-20.md`). Whether R5-7/R5-8 transfer unchanged
to a `continuous_rung_hold` family, and what the champion/challenger pair even is when the champion has
admissible n = 0, is a ruling, not a design decision this plan may take. 10b encodes the criteria as
written and tags them `SOURCE=FORECAST_FAMILY_R5` so the transfer is explicit and auditable; it does
not adapt them. 10b is faithfully transcribed but cannot be judged correct until the ruling exists."*

### Evidence

- `docs/evidence/FORECAST_EDGE_PEER_REVIEW_2026-09-18.md:148-152`, verbatim R5-7/R5-8 (quoted in full
  in AUD-10 §3 and reproduced above in the AUD-10 excerpt read this session).
- `docs/evidence/RULING_forecast_edge_programme_closes_2026-09-20.md`: the forecast-taker programme on
  PM.us daily-high rungs is **TERMINAL** — the market's resolution exceeds the forecast's by 1.98×, "no
  surplus resolution to unlock," "recalibration cannot rescue this." This closes the *forecast family*
  (`pm_us_crh_fc_v1`, density-table/forecast-bucket machinery, R5-5), **not** the statistical machinery
  R5-7/R5-8 describe.
- `src/breezy/settlement/current_rung_hold_v2.py:298`: `combine_station_day` — the function R5-7's
  estimator is built from — lives in a module named for, and already shared by, **both**
  `current_rung_hold` (v2) and `continuous_rung_hold` (v4) families. AUD-10's own `C-ESTIMATOR` (§6b.3)
  already calls this exact function for the `continuous_rung_hold` family, independent of this ruling.
  Nothing in `combine_station_day`, `CombinedDraw`, or `score_combined` (`:195-345`) references a
  forecast, a density table, or a forecast bucket.
- `src/breezy/settlement/roi_bound.py:92-100,214-219`, verified verbatim this session:
  `B_RESAMPLES: Final[int] = 10_000` (`:93`), `SEED: Final[int] = 20260904` (`:97`),
  `MIN_NON_EXCLUDED_N: Final[int] = 30` (`:100`, matching AUD-10 §6b.3's own citation), and the
  bootstrap call `scipy.stats.bootstrap(method="BCa", paired=True, n_resamples=B_RESAMPLES, ...)`
  (`:214-219`). All four are unconditional module-level constants/calls with no family or forecast
  branch — already family-agnostic, shared code.
- `docs/plans/FORECAST_EDGE_FAMILY_Rev5_2026-09-18.md:981,1001,1011`: `fit_date` is a field of the
  **forecast** family's manifest schema (paired with `holdout_start`/`holdout_end`, a train/calibration
  boundary for the density-table forecaster). `/usr/bin/grep -rn "fit_date" src/ scripts/` returns
  **zero** hits outside that one forecast-plan document — `fit_date` does not exist anywhere in
  `current_rung_hold`/`continuous_rung_hold` code.
- `deploy/families/pm_us_crh_v4.json:9`: `"density_artefact_path": "deploy/families/artefacts/not_applicable_density.json"` — `continuous_rung_hold` explicitly carries **no** density/forecast calibration artefact, confirming it has no `fit_date`-equivalent boundary.
- `deploy/families/pm_us_crh_v4.json:5`: `"d0_climate_day": "2026-09-20"` — the field
  `continuous_rung_hold` (and `current_rung_hold`) families DO carry, already read throughout AUD-10
  (`C-REVISION`, `C-KILL`'s provenance rule) as the family's own admission/reset boundary.

### Options considered

1. **Bind R5-7/R5-8 as-is, `SOURCE=FORECAST_FAMILY_R5` tag only, no adaptation** — rejected. R5-7's
   pairing clause names `fit_date`, a field that provably does not exist for `continuous_rung_hold`.
   Transcribing it verbatim leaves an unevaluable predicate (no `fit_date` to pair on) rather than a
   working one — AUD-10's own words, "cannot be judged correct," are literally true of the unadapted
   text.
2. **Replace R5-7/R5-8 entirely with new, freshly-authored criteria for `continuous_rung_hold`** —
   rejected. The estimator (`combine_station_day`/`CombinedDraw`/`score_combined`), the bootstrap
   (`roi_bound.B_RESAMPLES`/`SEED`), and the KILL-precedence rule (R5-8) are **already** the shared,
   family-agnostic machinery AUD-10's `C-ESTIMATOR`/`C-KILL` use for `continuous_rung_hold` today,
   independent of the forecast program's closure. Discarding R5-7/R5-8 and re-deriving equivalent
   rules from scratch would be pure duplication with real risk of silent drift from the code that
   already implements them.
3. **Bind with named, minimal adaptations — replace only the forecast-specific vocabulary (`fit_date`)
   with the field that actually exists (`d0_climate_day`), state the estimator/bootstrap are
   unmodified shared code (cite the concrete constants), and define champion/challenger operationally
   for n = 0** — **taken.**

### RULING

**R5-7 and R5-8 transfer to `continuous_rung_hold`-composition families WITH NAMED ADAPTATIONS — not
as-is, and not replaced.** The exact adapted text, for AUD-10 to pin verbatim in place of the
`SOURCE=FORECAST_FAMILY_R5` transcription:

> **R5-7 (adapted for `continuous_rung_hold`) — PROVISIONAL, see lifting condition below.**
> Realized-edge comparison: PAIRED on the same post-`d0_climate_day` station-days for champion and
> challenger (`d0_climate_day` replaces R5-7's original `fit_date`, which is a forecast-family-only
> field — `continuous_rung_hold` manifests carry no `fit_date`/density-calibration boundary,
> `deploy/families/pm_us_crh_v4.json`'s `density_artefact_path` is explicitly
> `not_applicable_density.json` — and `d0_climate_day` is the field `continuous_rung_hold` families
> actually register as their admission/reset boundary), CI-lower vs CI-lower (never challenger CI vs
> champion point). Estimator: UNCHANGED, family-agnostic, already shared code — `edge_hat = Σx/Σqty`,
> `SE = √I/Σqty` over `CombinedDraw`s (`src/breezy/settlement/current_rung_hold_v2.py::combine_station_day`,
> `:298`), `CI = edge_hat ± z·SE`, plus the station-day block bootstrap ALREADY PINNED IN CODE —
> `scipy.stats.bootstrap((pnl_arr, cost_arr), _ratio_of_sums, paired=True, vectorized=True,
> n_resamples=B_RESAMPLES, random_state=np.random.default_rng(SEED), confidence_level=_CONFIDENCE_LEVEL,
> alternative="greater", method="BCa")` (`src/breezy/settlement/roi_bound.py:213-222`, verified
> verbatim this round — **correction from revision 1, which cited a non-existent `seed=SEED` kwarg;
> the actual call passes `random_state=np.random.default_rng(SEED)`**, `B_RESAMPLES = 10_000`,
> `SEED = 20260904`). No forecast-specific parameter (density table, forecast bucket, R5-5) is part of
> this rule and none transfers.

> **R5-8 (adapted for `continuous_rung_hold`) — PROVISIONAL, see lifting condition below.** UNCHANGED
> IN SUBSTANCE. Any artefact change — including drift rollback to last-good — MINTS A NEW REVISION; an
> in-place action under a running `S_k` is `permit=None` halt only (L-34 class C). Promotion is
> REFUSED while any PREREG v3 §9 KILL/LOSS_STOP **of the champion** is tripped or pending at the next
> scheduled look; a promotion never resets a tripped clock (see Q2 — §9's own count stays
> live-venue-scoped only, permanently). Promotion requires a real `boundary_inputs_sha256`
> (`load_family_manifest` raises `UnpinnedBoundaryArtefactError` otherwise) — a blocking step, not a
> by-product. "The champion" means the manifest at `sending_family_id` (today `pm_us_crh_v4`, ruled
> "may not SEND orders" while remaining the deployed `sending_family_id` — a coordinator-level
> constraint this ruling does not revisit). **The one operative gap R5-8 inherits for
> `continuous_rung_hold`, not fixed by this adaptation**: R5-8 presupposes a KILL clock actually
> scoped to the champion; none is deployed today (Q4, below). AUD-10's `C14` rule — an `INERT`
> predicate bars `PROPOSAL` — is the correct, conservative operationalization of that gap and requires
> no further change.

**PROVISIONAL tag and lifting condition (required by independent review, and correct on its own
merits).** R5-7/R5-8-adapted are transferred from a CLOSED, terminally-wrong-on-its-central-claim
programme (`RULING_forecast_edge_programme_closes_2026-09-20.md`). Even though the specific machinery
reused (`combine_station_day`, `roi_bound`'s bootstrap) is family-agnostic and demonstrably unaffected
by *why* the forecast programme closed (Q3 Rationale), the criteria as a **whole package** have never
been exercised end-to-end for `continuous_rung_hold` and carry the closed programme's tag until they
have. Both adapted rules are therefore marked **`STATUS=PROVISIONAL, SOURCE=FORECAST_FAMILY_R5,
ADAPTED_BY=RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21`** in AUD-10's
`criteria.json` schema and §6b.3 table. **Lifting condition, named and checkable:** PROVISIONAL lifts
automatically the first time a promotion-proposal run completes with **every** predicate evaluable —
no `INERT` anywhere in the run (the identical gate AUD-10 §11's own abandonment criterion already uses
to decide which decisions "count") — regardless of that run's verdict (`PROPOSAL` or `NO_PROPOSAL`).
A run blocked by `C-PAIRED`/`C-KILL` `INERT` does not lift it, because the adapted rules have not
actually been exercised end-to-end in that run — only cited. Until lifted, `PROPOSAL` and
`NO_PROPOSAL` verdicts alike must carry the `PROVISIONAL` tag in the human-readable `RATIONALE.md`, so
a human reading a proposal knows the criteria that produced it have not yet been end-to-end exercised.

**Champion/challenger at admissible n = 0:** "Champion" means the currently-armed, `REGISTERED`
manifest at `sending_family_id` (today `pm_us_crh_v4`). "Challenger" means a not-yet-armed candidate
manifest a promotion proposal names. At champion admissible n = 0, R5-7's pairing rule has no realized
champion sample to pair against and **cannot execute** — this is not a defect in R5-7, it is `C-N`'s
job to say so first, and `C-N`/`C-PAIRED` already do (both plans' `C14`: any `INERT`/failing predicate
bars `PROPOSAL`, never silently passes as `true`). No further change to that mechanism is ruled here.

### Rationale, and the strongest argument against

The strongest argument against transfer at all is the one AUD-10's own blocker states: R5-7/R5-8 were
written for a family whose entire programme was later found terminally wrong on its central empirical
claim (the market beats the forecast). If the *statistical machinery itself* were forecast-specific,
that finding would taint it by association. It is not: `combine_station_day` and `roi_bound`'s
bootstrap are family-agnostic modules that predate and outlive the forecast programme, already reused
by `continuous_rung_hold` in AUD-10's own `C-ESTIMATOR` table independent of this ruling. The only
genuinely forecast-specific element in R5-7's text is `fit_date`, which this ruling replaces with the
field that actually exists. Binding as-is would have left an unevaluable predicate; replacing wholesale
would have thrown away correct, already-implemented machinery to solve a vocabulary problem.

---

## Q4 — Ownership of the two externally-owned dependencies keeping `C-PAIRED` and `C-KILL` INERT

**Verbatim framing**, AUD-10 §4/§11 (COMPOUND limit, round-5 10-7): *"no run can emit `PROPOSAL` until
BOTH externally-owned dependencies land: (1) a champion-scoped KILL clock — a deployed wrapper invoking
`structural_dead_stop.py --family-manifest <champion manifest> --output <its own path>`; owner:
whoever owns the live-tally / `score-live-trials` units; the repo tracks the question as PROGRESS R-4
..., and AUD-05 is cited by id only ...; and (2) `--family-manifest` on the replay driver
(`current_rung_hold_paper_replay.py`, threading `required_fee_coefficient` into the
`CurrentRungHoldConfig` built at `:932`), owner as already named in §12 — whoever takes the promotion
loop past its first proposal."*

### Evidence, verified against source this session

- **(a) `--family-manifest` on the replay driver.** `scripts/analysis/current_rung_hold_paper_replay.py:1076-1113`,
  the complete `add_argument` set, re-read verbatim this session: `--climate-day`, `--station`,
  `--tape-instance-id`, `--tape-subdirectory`, `--quote-catalog`, `--work-catalog`, `--asos-cache-csv`,
  `--weather-catalog-root`, plus output/strategy/monitor args. **Confirmed: no `--family-manifest`, no
  `--family`, no fee-coefficient argument of any kind exists.** `:932`: `cfg = CurrentRungHoldConfig(instrument_ids=..., stations=(station,))`
  — every other field, including `required_fee_coefficient: Decimal = Decimal("0.06")`
  (`src/breezy/strategy/current_rung_hold/config.py:226`), takes its class default. The armed
  manifest, `deploy/families/pm_us_crh_v4.json:13`, registers `"taker_fee_coefficient": "0.0695"`.
  Both plans' §5 explicitly exclude any change to `current_rung_hold_paper_replay.py`, "excluded from
  both AUD-09's and AUD-10's scope."
- **(b) A champion-scoped KILL clock.** `deploy/systemd/score-live-trials-run.sh:47`:
  `FAMILY_MANIFEST="$REPO/deploy/families/pm_us_crh_v2.json"` — hardcoded, verified verbatim this
  session. `:123-127`: `"$PY" scripts/analysis/structural_dead_stop.py --catalog-root "$CATALOG_ROOT"
  --family-manifest "$FAMILY_MANIFEST" --output "$CJSON"` — the counter JSON `C-KILL` reads is produced
  under this hardcoded v2 pin, not the champion's manifest. `pm_us_crh_v2.json:5`: `"d0_climate_day":
  "2026-09-05"`; `pm_us_crh_v4.json:5`: `"d0_climate_day": "2026-09-20"` — the mismatch AUD-10's
  champion-scope rule (§6b.3) is built to catch. **Separately and correctly**, the same wrapper's
  *scorer* loop (`:77-94`, `FAMILY_MANIFESTS` array, the L-38 fix) already **does** iterate every
  `REGISTERED`, `venue=polymarket_us` manifest under `deploy/families/*.json`, including
  `pm_us_crh_v4.json` — so `score_live_trials.py` output (which feeds `C-ESTIMATOR`/`C-N` via
  `load_realized_draws`) is **already** champion-scoped. **Only the `structural_dead_stop.py` counter
  invocation at `:47,125` remains pinned to v2** — a narrower, single-line gap than the wrapper's other
  loop suggests at first read.
- `scripts/analysis/structural_dead_stop.py:275-290`: the script **already accepts** `--family-manifest`
  as a parameter — the flag exists on the *consumer* script; only the *caller* (the wrapper) hardcodes
  which manifest it passes. This is a wrapper-level fix, not a `structural_dead_stop.py` change.
- `docs/core/PROGRESS.md:73`: R-4 (row), verbatim: *"v3 §9 is 'unchanged from v2' with no carve-out,
  so the v3 tally MUST receive a v3-scoped count (own `--family-manifest pm_us_crh_cont.json`, d0
  09-12, never v2's JSON); today no unit runs the v3 tally at all."* — **the literal text names
  `pm_us_crh_cont.json`**, re-verified this round at `:73`.
- `docs/core/PROGRESS.md:60,63`: the execution-order note, re-read this round: *"I5 needs a v3 SCORER
  pass and a v3-scoped count, not only a tally unit"* (`:60`) and *"SP-1 I5 after R-4"* (`:63`) — **SP-1
  I5 is the spec of record this dependency implements**; R-4 is the ruling question blocking it, not a
  separate spec.
- **Reconciliation, required by the coordinator hand-down and confirmed against source.** R-4's literal
  text (`pm_us_crh_cont.json`, d0 `2026-09-12`) is **SUPERSEDED, not authoritative as written**:
  `pm_us_crh_cont` is retired (`bcb82d6`, `terminal_climate_day: "2026-09-19"`, Q1 evidence above), and
  the coordinator's hand-down states the KILL clock must follow `sending_family_id`, not a fixed,
  named manifest — `pm_us_crh_v4` today, and whatever a future re-arm's **new** family id is after
  that (L-34 class C; a re-arm never reuses a retired family's id, per the same hand-down). **R-4 as
  written would, if implemented literally, re-create the identical wrong-family error this whole
  backlog exists to close** (`bss-headline-is-the-wrong-family`): it would scope the counter to a
  RETIRED family instead of the champion. The correct implementation reads the champion **dynamically**
  (`sending_family_id`/the armed manifest), never a manifest filename baked into the spec text.
- `docs/plans/backlog/AUDIT_2026-09-21/AUD-05-live-family-tally-unit.md:1-23`: AUD-05's own title and
  scope is *"Give the live family `pm_us_crh_v4` a tally that runs"* — it already cites R-4 directly
  (*"Related ruling question: R-4 ... R-4 also blocks SP-1 I5 and renders SP-5's coverage diagnostic
  inert"*) and already claims to "unblock SP-1 I5 and SP-5 (per R-4)" (`:99`). **Verified this
  session**: `/usr/bin/grep -n "score-live-trials\|covered_listed_station_days" AUD-05...md` returns
  only incidental hits — AUD-05's **in-scope** change list (D-A, D-B, D-D, D-E, D-F, BLOCKER-1/2/3)
  does **not** include rebinding `score-live-trials-run.sh:47`'s `FAMILY_MANIFEST`. AUD-05's
  `BLOCKER-2` (`:738-739`) is a **different** question (retiring `pm_us_crh_cont`), not this pin.
  **R-4 is cited by AUD-05 as relevant context but is not currently discharged by any in-scope item in
  AUD-05's own change list.**
- No other backlog item under `docs/plans/backlog/AUDIT_2026-09-21/` references `score-live-trials-run.sh`'s
  `FAMILY_MANIFEST` pin or `current_rung_hold_paper_replay.py`'s missing flag as in-scope work
  (`/usr/bin/grep -rln "score-live-trials-run.sh\|--family-manifest.*paper_replay" docs/plans/backlog/AUDIT_2026-09-21/*.md`
  matches only AUD-09/AUD-10's own dependency citations of each other and of AUD-05/R-4).

### Options considered (per dependency)

**(a) `--family-manifest` on the replay driver:**
1. Fold into AUD-09 — rejected. AUD-09's exclusion of this exact change was a **deliberate, converged,
   peer-reviewed round-2 decision** ("armed family only... Adding the flag later is a named, deferred
   change with an owner, not an implicit assumption"). Reopening AUD-09's scope now would relitigate a
   decision that already survived independent review, for no new evidence.
2. Fold into AUD-10 — rejected. AUD-10 consumes replay results; it does not own the replay driver, and
   folding a driver change into the promotion-criteria plan would blur exactly the module boundary
   AUD-09/AUD-10's own layer split (§6, both plans) is built to keep clean.
3. Fold into AUD-05 — rejected. AUD-05's territory is the live-tally/`score-live-trials` unit family;
   the replay driver is a different subsystem (`scripts/analysis/current_rung_hold_paper_replay.py`,
   owned conceptually by AUD-09) with no overlap in files, wrappers, or units.
4. **A new, small, sibling backlog item, scoped to exactly this one flag** — **taken.**

**(b) Champion-scoped KILL clock:**
1. A new backlog item, separate from AUD-05 — rejected. This is a one-line-cause fix
   (`score-live-trials-run.sh:47`'s hardcoded `FAMILY_MANIFEST` used only for the
   `structural_dead_stop.py --output` counter call) inside a wrapper AUD-05 already edits for D-A/D-B/
   D-D/D-E/D-F. A separate item would fork edits to the same wrapper across two backlog items, risking
   a merge collision on the exact `flock`/pre-flight/manifest-resolution block AUD-05 is already
   touching, and would duplicate the R-4 citation trail AUD-05 already carries.
2. **AUD-05, as an explicitly-named added increment (distinct from its existing BLOCKER-1/2/3, which
   are unrelated NO-side statistical rulings)** — **taken.**

### RULING

1. **The `--family-manifest` replay-driver flag is owned by a NEW, small backlog item, named
   AUD-19**, sibling to AUD-09, not folded into any existing plan. Minimum scope: add
   `--family-manifest <path>` to `current_rung_hold_paper_replay.py`'s parser, load it via the existing
   `load_family_manifest`, thread at minimum `required_fee_coefficient` into the
   `CurrentRungHoldConfig` built at `:932` (replacing the class default), and keep the
   single-manifest-per-invocation shape AUD-09 §6b.2 already established (no enumeration of
   `deploy/families/`). **AUD-19's gate: it may not land before Q1's `trial_id` provenance fix lands**
   (Q1 RULING items 2-4) — it is the change that would make the Q1 collision (which is proven, not
   hypothetical, given the `pm_us_crh_cont`/`pm_us_crh_v4` `trial_id_prefix` collision) live on its
   first execution. AUD-10's `C-PAIRED` becomes evaluable "with no change to AUD-10's plan" the moment
   AUD-19 and the Q1 fix have both landed, exactly as AUD-10 §12 already states for AUD-19 alone; this
   ruling adds the Q1 ordering as AUD-19's binding precondition.
2. **The champion-scoped KILL clock has EXACTLY ONE owner: AUD-05** (coordinator decision, relied on
   here) — no split ownership, no second item. AUD-05 gains a named, explicitly-scoped increment
   (distinct from its existing BLOCKER-1/2/3, which concern the unrelated NO-side statistical formula)
   that **IMPLEMENTS SP-1 I5** — SP-1 I5 (`docs/core/PROGRESS.md:60,63,73`) stays the spec of record;
   this ruling and AUD-05 only implement it, never redefine it. Minimum scope: `score-live-trials-run.sh`'s
   `structural_dead_stop.py --family-manifest` invocation (`:47,123-127`) must resolve the manifest
   **dynamically from `sending_family_id`** (never a manifest filename hardcoded in the wrapper or in
   R-4's own literal text — see the reconciliation below) and write its own `--output` counter JSON,
   distinct from the legacy v2-scoped file (so nothing that still reads the v2 file for a different
   purpose is disturbed). AUD-10's `C-KILL` becomes evaluable "with no change to AUD-10's plan" the
   moment this lands, exactly as AUD-10 §12 already states.
3. **Reconciliation with R-4's literal text.** R-4 (`PROGRESS.md:73`) names `pm_us_crh_cont.json`
   verbatim; that text is **SUPERSEDED**, not binding as written, because `pm_us_crh_cont` is retired
   and the counter must follow `sending_family_id`. AUD-05's increment implements SP-1 I5's *intent*
   (a v3-scoped, never-v2's-JSON count) using the *current* champion, not R-4's now-stale literal
   filename. A PROGRESS.md consequence line is required (§Consequences below; this ruling does not
   edit PROGRESS.md itself).
4. Neither dependency is owned by AUD-10 itself, confirming both plans' own §5 exclusions.

### Rationale, and the strongest argument against

The strongest argument against creating AUD-19 rather than just reopening AUD-09 is cost: a new item
means a new plan, a new peer-review cycle, more process for a small, well-specified change. That cost
is accepted deliberately — AUD-09's round-2 exclusion of this exact flag was itself the product of
independent peer review finding the alternative (adding the flag inside AUD-09) unsound at the time (no
manifest-driven config path existed yet to hang it on); overriding a converged review with a unilateral
ruling, rather than a fresh small plan, would set a worse precedent than the extra process cost. For
the KILL clock, the strongest argument against folding into AUD-05 is that AUD-05 is already `NOT
READY` with three open strategy-lead blockers (BLOCKER-1/2/3) — adding scope to a stuck plan doesn't
unstick it. That is accepted as a real but separable risk: the KILL-clock fix touches a **different**
region of the same wrapper file (the counter invocation, not the per-city scorer loop D-A/D-B modify)
and can be built, reviewed, and merged independently of BLOCKER-1/2/3's resolution; it is recorded as
an explicit sub-item precisely so it is not blocked by them. The strongest argument against **dynamic**
`sending_family_id` resolution (rather than R-4's literal `pm_us_crh_cont.json`) is that it makes the
counter's scope change silently whenever the champion changes, with no re-registration of the counter
itself — accepted, because that is exactly the property wanted: the whole point of a champion-scoped
clock is that it always describes the family actually sending orders, and a clock that required a
manual edit on every re-arm would reintroduce the identical staleness risk AUD-10's `C-KILL` binding
was built to refuse (a stale/wrong-family file must never read as permissive).

---

## Consequences — exact text changes required in each affected plan

**AUD-09** (`docs/plans/backlog/AUDIT_2026-09-21/AUD-09-scheduled-per-station-replay.md`):
- §12, R1 bullet: replace "still open" / "ruling **R1** ... still open" with a pointer to this ruling
  artefact and the adapted `trial_id` shape (Q1 RULING items 3-4: `family_id`-discriminated, NOT
  `trial_id_prefix`-discriminated — revision 1's shape is withdrawn), and add the explicit ordering
  constraint: *"AUD-19 (the `--family-manifest` flag item) may not land before this fix lands (RULING
  `replay_evidence_citability_and_promotion_criteria_2026-09-21.md` Q1)."*
- §8, evidence artefact paragraph (B-series caveat): add one line alongside the existing look-ahead
  caveat stating the parquet `trial_id` is not yet family-scoped (Q1 RULING item 8).
- §12, "BLOCKER — strategy lead ... MECHANISM_ONLY ... PREREG v3 §9" bullet: replace "Default taken
  here: no ... Changing that needs a ruling artefact" with "RULED (this artefact, Q2): no, and never,
  for §9 specifically; no, pending AUD-11/AUD-12, for promotion criteria."
- §12, "BLOCKER — deferred change with a named owner (round-2 09-2)" bullet (the `--family-manifest`
  flag): replace "Owner: whoever takes the promotion loop past its first proposal" with "Owner: AUD-19
  (new backlog item, RULING Q4), gated on the Q1 `trial_id` fix landing first."
- "Coordinator final status" block, "Unresolved blockers" list: update the R1/MECHANISM_ONLY line to
  point at this ruling as resolving both; name AUD-19 as the owner of the driver flag.

**AUD-10** (`docs/plans/backlog/AUDIT_2026-09-21/AUD-10-evidence-gated-promotion-proposal.md`):
- §6b.3, R5-7/R5-8 citation and the `SOURCE=FORECAST_FAMILY_R5` tagging: replace with the adapted R5-7/
  R5-8 text given in Q3 RULING verbatim, tagged `STATUS=PROVISIONAL,
  SOURCE=FORECAST_FAMILY_R5, ADAPTED_BY=RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21`,
  and add the PROVISIONAL lifting condition (Q3 RULING) to the `criteria.json` schema description.
- §12, "BLOCKER — strategy lead (real, score-capping for 10b...)" bullet: replace with "RULED (this
  artefact, Q3): R5-7/R5-8 transfer with the named adaptations quoted in §6b.3, tagged PROVISIONAL
  until the first no-`INERT` promotion run. Champion/challenger defined for n=0 (Q3 RULING); no further
  change to `C14`'s INERT-bars-PROPOSAL mechanism."
- §12, `C-PAIRED`/`--family-manifest` blocker bullet: replace "Owner: whoever takes the promotion loop
  past its first proposal" with "Owner: AUD-19 (new backlog item, RULING Q4), gated on AUD-09's Q1
  `trial_id` fix."
- §12, champion-scoped KILL clock blocker bullet: replace "Owner: whoever owns the live-tally /
  score-live-trials units ... AUD-05 ... cited by id only" with "Owner: AUD-05 exclusively (RULING
  Q4) — a named increment implementing SP-1 I5 (`PROGRESS.md:60,63,73`), reconciling R-4's stale
  literal `pm_us_crh_cont.json` text with the retired-family hand-down by resolving the champion
  dynamically from `sending_family_id`."
- §11, COMPOUND-limit paragraph: update the two "owner" clauses identically to the §12 changes above.

**AUD-05** (`docs/plans/backlog/AUDIT_2026-09-21/AUD-05-live-family-tally-unit.md`):
- Add a new explicitly-scoped increment (sibling to D-A/D-B, distinct from BLOCKER-1/2/3), stated as
  **implementing SP-1 I5** (`PROGRESS.md:60,63,73` remains the spec of record): rebind
  `score-live-trials-run.sh`'s `structural_dead_stop.py --family-manifest` invocation from the
  hardcoded `pm_us_crh_v2.json` literal to the champion, resolved **dynamically** from
  `sending_family_id` (never a manifest filename hardcoded in the wrapper or copied from R-4's own
  literal text), writing its own `--output` counter JSON distinct from the legacy v2 file. Cite this
  ruling as the authority for taking the scope and for superseding R-4's literal `pm_us_crh_cont.json`
  naming (AUD-05 previously deferred R-4 rather than resolving it; `pm_us_crh_cont` is retired).

**`docs/core/PROGRESS.md`** (text-only consequence — **not edited by this ruling or by the coordinator
instruction**; the line below is what a future editor should add against R-4's row, `:73`):
- Append to R-4's row: *"SUPERSEDED in part by RULING
  `replay_evidence_citability_and_promotion_criteria_2026-09-21.md` Q4 — `pm_us_crh_cont.json` is
  retired; the v3-scoped count must follow `sending_family_id` dynamically, not a fixed manifest
  filename. Implemented by AUD-05's new increment (SP-1 I5 stays the spec of record)."*

No text change is proposed to `docs/specs/PREREG_v3_continuous_rung_hold_DRAFT_2026-09-10.md` itself —
§9 is confirmed unchanged (Q2), and this ruling's Q2 clause is a citability rule about *inputs*, not a
change to the registered test.

---

## What would overturn this ruling, and what remains operator-only

**Q1** is overturned by: evidence that a downstream consumer already depends on the current, unscoped
`trial_id` shape in a way a `family_id`-discriminated adaptation would break (none found this
session — no consumer reads the replay parquet across families today) — or evidence that `family_id`
is not, in fact, guaranteed unique (none found; it is the registry's own primary key and the
coordinator's hand-down states a re-arm always mints a new one) — in which case a still-stronger
discriminator (e.g. `manifest_sha256` promoted from secondary check to the primary discriminator) would
be required instead.

**Q2** is overturned only by a **new, separate ruling** explicitly amending PREREG v3 §9's input
definition — a PREREG semantics change, which this artefact treats as requiring its own dedicated
ruling given L-34's re-registration/no-peeking discipline, not a side effect of this one.

**Q3** is overturned by: evidence that `combine_station_day`/`roi_bound`'s bootstrap are **not** in
fact shared between `current_rung_hold` and `continuous_rung_hold` (this session's source read found
them shared, unconditionally) — or a future finding that `d0_climate_day` is not, in fact, a safe
substitute for `fit_date`'s leakage-prevention role (this ruling asserts substitution because
`continuous_rung_hold` has no calibration step to leak from — `density_artefact_path` is
`not_applicable`; a future family with a real calibration boundary would need its own ruling, not this
one, reused).

**Q4** is overturned by: a strategy-lead decision to prioritize differently (e.g., landing AUD-19
before Q1's `trial_id` fix, accepting the collision risk with an explicit operator-level risk
acceptance) — that specific override, and only that one, would need to come from the operator, because
it trades a known statistical-integrity hazard for schedule speed, which is the kind of
irreversible-if-wrong tradeoff this ruling's conservative default (§0, "fail-closed on money and on
statistical validity") is built to avoid without an explicit sign-off. The AUD-05-sole-ownership
decision itself is a coordinator decision this ruling relies on, not re-derives, and is overturned only
by a new coordinator/operator instruction, not by this ruling's own reasoning.

**Nothing in this ruling sets, proposes, or implies a value for the two operator-reserved caps (max
daily budget, max per position), and nothing here touches live-trading enablement or the NO-SEND
firewall.** The only genuinely operator-only residue is the possible override named in Q4's overturn
condition above; everything else in this ruling is decided.
