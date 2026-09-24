# Peer review — RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21.md

Status: PROPOSED (independent adversarial review)
Reviewer: evaluation-methodology peer (blind)
Date: 2026-09-21

## Q1 (trial_id provenance) — REJECT (as written; fixable)

**Defect [CRITICAL], evidence omitted.** `deploy/families/pm_us_crh_cont.json:3` and
`deploy/families/pm_us_crh_v4.json:3` carry the **identical**
`"trial_id_prefix": "continuous_rung_hold/trial/"`. `pm_us_crh_cont.json:15` `status:
REGISTERED`, `terminal_climate_day: 2026-09-19` (already past — AUD-05 BLOCKER-1/2,
`AUD-05-live-family-tally-unit.md:712-720,748-752`, both open/undecided). The ruling's Q1
evidence (lines 30-61) compares only v2 vs v4 prefixes and concludes (line 94-95) the fix
"never colliding across families for the same (station, climate_day)." That is **false**:
applying the ruling's own formula `paper_replay/{manifest.trial_id_prefix}{station}/{climate_day}`
to v4 and to `pm_us_crh_cont` yields **byte-identical** replay `trial_id`s, because the two
manifests' `trial_id_prefix` values are identical. The ruling never cites `pm_us_crh_cont.json`
or AUD-05's BLOCKER-1 (which names this exact identical-prefix hazard on the **live** side and
is still open) anywhere in 517 lines, despite Q1 being specifically about trial_id collision.
**Required change:** Q1 §RULING item 2 must state the fix is necessary-but-insufficient while
`pm_us_crh_cont` and `pm_us_crh_v4` share a `trial_id_prefix`, and must either (a) name AUD-05
BLOCKER-1's disposition as a co-precondition of the Q4(a) ordering gate, or (b) explicitly scope
Q1's disjointness claim to "distinct `trial_id_prefix` values only" and flag the v4/cont case as
a second, open collision this ruling does not resolve.

**Defect [LOW], quoted API signature wrong.** Q3's adapted R5-7 text (line 281, intended to be
"pinned verbatim" into AUD-10 §6b.3) quotes `scipy.stats.bootstrap(..., seed=SEED)`. The actual
call at `src/breezy/settlement/roi_bound.py:220` passes `random_state=np.random.default_rng(SEED)`;
installed scipy's `bootstrap()` signature (`_resampling.py:300-303`) has no `seed=` kwarg at all
(only `rng=`/`random_state`-style params). Cosmetic for a prose citation, but this text is
directed to be pinned verbatim as the criterion — pin the real call, not `seed=SEED`.

Everything else in Q1 checks out: `paper_replay.py:92,347` (v2-hardcoded, no family branch),
`live_family_tally.py:83,91,148-180` (`assert_live_only`/`assert_paper_only`, `startswith`
prefix checks — confirmed verbatim this session) are accurately cited, and the barrier described
(literal `"paper_replay/"` outer prefix) is real and unforgeable as claimed.

## Q2 (MECHANISM_ONLY / §9 citability) — ENDORSE

Citations verified: `PREREG_v3_continuous_rung_hold_DRAFT_2026-09-10.md:197-199`,
`structural_dead_stop.py` threshold reuse, `resolver-fills-are-residual-by-prereg` memory. The
fail-closed "no, categorically, forever" answer for §9 is the conservative default and its
rationale (structural resemblance between census and KILL counter) is sound. No gap found.

## Q3 (R5-7/R5-8 transfer) — ENDORSE-WITH-REQUIRED-CHANGES

`combine_station_day` (`current_rung_hold_v2.py:298-345`, verified) is genuinely
family-agnostic; `fit_date` genuinely has zero hits outside the forecast plan (verified,
`/usr/bin/grep -rn fit_date src/ scripts/` → 0). The `d0_climate_day` substitution and the
`sending_family_id`-as-champion definition are faithful, non-silent adaptations — correctly
labelled as adaptations, not a verbatim transcription, matching AUD-10's own concern.
**Required change:** the ruling should carry an explicit provisional tag on the transfer itself
(not just the sub-clauses) — R5-7/R5-8 are being reused from a **terminally CLOSED** programme;
the ruling argues persuasively that only `fit_date` was forecast-specific, but states this as
settled fact rather than as "provisional pending no further forecast-specific coupling being
found." Given the repo's own two recorded incidents of statistics silently attached to the wrong
family (`bss-headline-is-the-wrong-family`, `archive-table-train-serve-skew`, both cited
elsewhere in this ruling for Q2), the same caution should explicitly attach to Q3's transfer,
not just be implied by the "what would overturn this" section. Fix the `seed=SEED` citation
noted under Q1 in the same pinned text.

## Q4 (ownership) — ENDORSE-WITH-REQUIRED-CHANGES

**PROGRESS.md R-4 (`docs/core/PROGRESS.md:73`) is a live, scheduled item, not an orphan** — it
sits in the Execution-order chain at `PROGRESS.md:63` ("→ SP-1 I5 after R-4 → SP-5") and is
cross-referenced from `PROGRESS.md:60`'s parenthetical ("I5 needs a v3 SCORER pass and a
v3-scoped count, not only a tally unit"). SP-1 I5 is a real increment
(`LIVE_FILL_SCORING_CHAIN_2026-09-05.md:236`, "I5 — end-to-end contract test (REQUIRED; was
O6)"), not a dead citation. The ruling's Q4 ownership analysis (AUD-05 vs a new item) is sound on
its own terms, but **never touches PROGRESS.md's R-4 row or its Execution-order line at all** —
the Consequences section (lines 442-483) lists exact text changes for AUD-09/AUD-10/AUD-05 but
omits `docs/core/PROGRESS.md`, which is where R-4 and "SP-1 I5" actually live and will keep
reading their stale, pre-v4 text (see next point) indefinitely if not updated alongside AUD-05.
**Required change:** add a Consequences entry for `docs/core/PROGRESS.md`: update R-4's row (`:73`)
to point at this ruling and AUD-05's new increment, and update the Execution-order line (`:63`)
so "SP-1 I5 after R-4" either retires (superseded by AUD-05) or is re-scoped to whatever of I5
survives once AUD-05 discharges the counter-rebinding piece.

**Second defect: R-4's own literal text is stale and the ruling silently overrides it without
saying so.** `PROGRESS.md:73` R-4 names the required manifest as
`--family-manifest pm_us_crh_cont.json` (d0 09-12) — **not** `pm_us_crh_v4.json`. The ruling's
Q4b (lines 413-422) resolves this as "resolve `sending_family_id`" (today `pm_us_crh_v4`) with no
mention that this reinterprets R-4's own literal, still-live text, or of why `pm_us_crh_cont` is
being superseded rather than targeted. Given `pm_us_crh_cont` is `REGISTERED`, past its
`terminal_climate_day`, and (per AUD-05 BLOCKER-2, still open) not yet formally retired, a
"champion-scoped" KILL clock resolved dynamically off `sending_family_id` is almost certainly the
right call — but the ruling needed to say so explicitly and reconcile it against R-4's literal
text, rather than leave a reader who greps R-4 believing `pm_us_crh_cont.json` is still the
target. **Required change:** Q4 §RULING item 2 should add one sentence: R-4's literal
`pm_us_crh_cont.json` target is superseded by resolving `sending_family_id` dynamically, because
the champion has since rolled from `pm_us_crh_cont` to `pm_us_crh_v4` and AUD-05 BLOCKER-2 (cont's
retirement status) is a separate, still-open question this ruling does not resolve.

## Multiple-comparison exposure

Not addressed anywhere in the ruling. Q3's transfer reuses R5-7/R5-8 machinery originally
calibrated/reviewed once for the forecast family; reusing it for `continuous_rung_hold` without
re-deriving α or acknowledging that this is now a second family drawing on the same
`roi_bound.py` sequential-look machinery is a gap, though likely immaterial today since AUD-10's
own `C-N`/`C14` (cited, not re-verified this session) already bars `PROPOSAL` at n=0 and no
promotion has occurred. Flag as a note, not a blocking defect: worth one sentence in "what would
overturn this ruling" for Q3.

## Robustness to the two named alternative outcomes

- **Re-issuing v4 with a new `trial_id_prefix`:** does NOT break any of the four rulings — Q1's
  fix mechanism (embed `manifest.trial_id_prefix`) actually **requires** this to achieve the
  disjointness it claims, since it is currently false in the presence of `pm_us_crh_cont`
  sharing v4's prefix (see Q1 defect above). This is a point in favor of prioritizing that
  re-issue, which the ruling should have surfaced but did not.
- **Stopping v4 from sending orders entirely:** does not break Q1-Q4's structure (champion
  identity via `sending_family_id`, §9 scoping, R5-7/R5-8 adaptation all remain valid regardless
  of whether the champion is currently ordering). No issue found.

## Verdict summary

| Q | Verdict |
|---|---|
| Q1 | REJECT as written — material evidence gap (pm_us_crh_cont collision); fixable with the required change above |
| Q2 | ENDORSE |
| Q3 | ENDORSE-WITH-REQUIRED-CHANGES — add provisional tag + fix `seed=SEED` citation |
| Q4 | ENDORSE-WITH-REQUIRED-CHANGES — add PROGRESS.md consequences entry; reconcile R-4's literal `pm_us_crh_cont.json` text |

**517 lines does hide an undecided question**: whether `pm_us_crh_cont` is retired (AUD-05
BLOCKER-2) is load-bearing for Q1's disjointness claim and for Q4b's manifest resolution, and the
ruling under review never surfaces the dependency.

## Delta review (Revision 2)

Verified against `sha256:77c4e53a8f0b6f55265d7c057903729e153cc1cbeabcecf81e171b7bcb31ad` (hash matches).

**Q1 — ENDORSE, no further required change.** Original REJECT is genuinely resolved.
`pm_us_crh_cont.json`/`pm_us_crh_v4.json` confirmed to share `trial_id_prefix` byte-for-byte
(re-verified this round). Constructed both concrete replay ids under the new `family_id`-keyed
scheme and traced them against every selector's actual code:
- `paper_replay/pm_us_crh_v4/continuous_rung_hold/trial/SFO/2026-09-01` vs
  `paper_replay/pm_us_crh_cont/continuous_rung_hold/trial/SFO/2026-09-01` — differ at the
  `family_id` segment, never collide.
- `assert_live_only` (`live_family_tally.py:158-159`, `startswith(_LIVE_TRIAL_ID_PREFIX)` =
  `"current_rung_hold/trial/"`) — neither new-shaped paper id (both start with literal
  `"paper_replay/"`) can ever satisfy it. Confirmed: a `paper_replay/...` id can never satisfy a
  live selector's `startswith`.
- `assert_paper_only` (`live_family_tally.py:174`, currently hardcoded
  `_PAPER_TRIAL_ID_PREFIX = "paper_replay/current_rung_hold/trial/"`) would, AS WRITTEN TODAY,
  reject the new-shaped ids too (they start with `paper_replay/pm_us_crh_v4/...`, not
  `paper_replay/current_rung_hold/trial/`) — but the ruling's own RULING item 6 (lines 187-192)
  already mandates rewriting this exact check to an exact-equality test on the `family_id`
  segment, so this is accounted for as a co-required build change, not a gap.
- `filter_rows_to_manifest_prefix` (`family_tally_v2.py:548`, confirmed `startswith`, no
  substring match anywhere) and `score_live_trials.py`'s `family_prefix` checks operate on the
  **live** state DB / scored-trials store only, never on replay parquet — correctly out of Q1's
  scope, correctly assigned to AUD-05 (its own BLOCKER-1 already names this exact collision).
- No selector anywhere uses substring (`in`/`re.search`) matching — confirmed by direct read,
  matching the ruling's audit claim.
`bcb82d6` (verified via `git log -1`) confirms the `pm_us_crh_v4` promotion and is consistent
with the retirement narrative (commit does not use the word "retired" but the RULING's own
citations — `terminal_climate_day`, `RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md:270` "may
not SEND orders" — are independently verified and consistent).

**Q2 — ENDORSE, unchanged, no further required change.**

**Q3 — ENDORSE, no further required change.** `roi_bound.py:213-222` re-read verbatim: the
corrected citation `random_state=np.random.default_rng(SEED)` matches the actual call exactly
(previous `seed=SEED` error is gone). `STATUS=PROVISIONAL` tag with a concrete, checkable lifting
condition (first no-`INERT` run) is present and satisfies the required-change from round 1.

**Q4 — ENDORSE, no further required change.** `SP-1 I5` is now explicitly named as the spec of
record AUD-05's new increment implements (not redefined), matching `PROGRESS.md:60,63,73`.
R-4's literal `pm_us_crh_cont.json` text is explicitly reconciled as SUPERSEDED, with a stated
reason (retirement) and a stated replacement rule (resolve `sending_family_id` dynamically) — the
round-1 gap is closed. A `docs/core/PROGRESS.md` consequence line is now included (§Consequences,
"not edited by this ruling," correctly deferred). Ownership is now singular (AUD-05 only) with
AUD-19 cleanly split out for the unrelated replay-driver flag; no split-ownership ambiguity
remains.

**Regression check.** All four round-1-verified citations (`paper_replay.py:92,347`,
`live_family_tally.py:83,91,148-180`, `roi_bound.py:92-100`, `current_rung_hold_v2.py:298-345`,
`score-live-trials-run.sh` FAMILY_MANIFEST pin) are re-quoted unchanged and remain accurate. No
new defect introduced by the delta.

### Verdict summary (Revision 2)

| Q | Verdict |
|---|---|
| Q1 | ENDORSE |
| Q2 | ENDORSE |
| Q3 | ENDORSE |
| Q4 | ENDORSE |

All four required changes from the round-1 review are satisfied. No outstanding required changes.
