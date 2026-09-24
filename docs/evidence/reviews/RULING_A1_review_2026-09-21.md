# Review — RULING A1 (`pm_us_crh_v4` disposition, 2026-09-21)

Status: PROPOSED — independent peer review of
`docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`

**Verdict: ENDORSE-WITH-REQUIRED-CHANGES**

## Defects

**D1 [MEDIUM] — §3 item 5's factual claim is false; the A0-unmet conclusion
survives but the text must be corrected.**
`ls docs/evidence/venue/polymarket_us/` succeeds (not exit 1); the directory
exists and contains `FEE_SCHEDULE_PIN_2026-09-18.md` plus dated
capture/probe artefacts. I read that file in full: it documents the pin
(`0.06`), the single-snapshot 2026-08-25 exact-set, and the 09-17 drift
discovery — it does NOT satisfy A0's actual acceptance criterion
(`POST_FORECAST_PHASE_2026-09-20.md:44`: re-pull `feeCoefficient` across
**all listed weather slugs**, **≥5 consecutive days**, separate wire drift
from tape-writer artefact, maker field recorded independently, RED-first
test extension pinning the OBSERVED SET). No such per-slug/per-day table or
extended pin test exists anywhere under `docs/evidence/`. **Net effect: the
ruling's bottom line on A0 (unmet) is still correct, but §3.5 must be
rewritten** — replace "does not exist" with "exists but does not satisfy
A0's acceptance criterion (no per-slug/per-day re-pull, no ≥5-day window, no
extended RED-first pin test)" and cite `FEE_SCHEDULE_PIN_2026-09-18.md` by
name. As written, the artefact fails its own brief's "verify every
file:line you cite" instruction on the one claim it flagged as
independently `ls`-checked.

**D2 [HIGH] — §4's central enforcement claim mischaracterizes existing code;
the ruling currently authorizes nothing operative.**
The ruling states the halt mechanism is "Required follow-up (code, not
performed in this artefact)... land the base plan's own `family_halted`
state... matching the EXIT-1 precedent (BUILT, UNARMED)" — implying
greenfield work comparable to EXIT-1. That is imprecise. The mechanism
**already exists and is already mechanically wired at the chokepoint**:
`FAMILY_HALT_KEY` / `TrialDayLatch.is_family_halted`
(`src/breezy/strategy/current_rung_hold/trial_day_latch.py:1002-1015`),
consulted by `family_halt_submit_veto`
(`src/breezy/strategy/current_rung_hold/composition.py:195`, called from
`src/breezy/app/trade.py:260`) — this veto runs for whichever family
currently occupies the node's one sender, confirmed by
`trade_supervisor_core.py:158-168` ("halted is GLOBAL-equivalent to this
node's only sender is halted... no matter which literal family id currently
occupies" the slot). So the STATE and the VETO are not what's missing.

What is actually missing: **an operator-invocable primitive to SET the halt
on demand for a policy reason.** Today the only writers of `FAMILY_HALT_KEY`
are `record_duplicate_fill` and `record_ambiguous_exit`
(`trial_day_latch.py:861-915`, `:968-1000`) — both automatic consequences
of specific fill/exit events, never a build-side "halt this family now"
action. The only operator CLI that touches this key is
`breezy-clear-family-halt` (`clear_family_halt_cli.py`), which only clears.
**There is no `breezy-set-family-halt` mirror.** Consequence: as of this
ruling, nothing in the repo actually stops `pm_us_crh_v4` from placing an
order if pricing ever legalizes — the ruling's "NOT permitted: to remain
armed" is aspirational, not enforced, and the ruling's own §5 rationale
("the zero-trade state is an accident... an explicit halt removes that
risk") is **not yet true of the artefact as written**, only of its
unbuilt follow-up.

Required change to §4/§6: (a) name the missing piece precisely — a
`breezy-set-family-halt` CLI mirroring `clear_family_halt_cli.py`'s shape
(reason + evidence-path, flock-respecting), not a new `family_halted`
state, since the state/veto already exist; (b) state explicitly, in the
present tense, that until that CLI lands **and is run**, `pm_us_crh_v4` is
NOT halted by any mechanism this ruling controls — the only thing
currently blocking it is the same accidental zero-pricing funnel the
ruling itself calls unsafe to rely on; (c) because the missing piece is
materially smaller than EXIT-1 (a CLI mirroring one that already exists,
not a new gate), the consequences section should treat it as urgent/small,
not open-ended backlog engineering — this changes its priority framing,
not the ruling's disposition.

**D3 [LOW] — HUNT-1 (operator-mandated continuous hunting, commit
`9ddcb8b`, `docs/core/PROGRESS.md`) is not mentioned.** No contradiction
found — (ii) does not claim to satisfy HUNT-1 and does not block AUD-01 or
future hunting work — but the ruling's "what remains" framing in §7 should
note HUNT-1 as a second, independent precondition any future (iii) will
also have to clear (the `P_HOLD` table itself only covers hour_lst
{12..16}), since AUD-18's re-arm evidence bar (§7) currently lists only
the edge-CI and A0 conditions.

## Checks that passed

- No contradiction with any operator ruling found (`build the spine
  anyway` 09-04, `NO-side hunting is a requirement`, `L-34` n-reset) —
  (ii) preserves history, preserves AUD-01, does not retire the manifest.
- A1↔AUD-18 linkage is non-circular: entry (CI-excludes-zero, non-`P_HOLD`,
  real-ladder estimate), exit (a future A1-class ruling, not
  self-executing), explicit exclusion of the closed forecast-taker hunt and
  gate-pass recalibration — verified against
  `RULING_forecast_edge_programme_closes_2026-09-20.md` and
  `DECISION_FUNNEL_2026-09-20.md:625-628`.
- Spot-checked citations hold: `fees.py:86`
  (`DOCUMENTED_TAKER_FEE_COEFFICIENT = Decimal("0.06")`),
  `test_polymarket_us_fee_schedule_pin.py:226` (asserts `== Decimal("0.06")`),
  `family_manifest.py:13-21` (non-retroactivity docstring),
  `DECISION_FUNNEL_2026-09-20.md:8-19` (funnel table, `illegal_cell`=0
  legal both days) all verbatim-match.
- Operator-only scope (§7) is correctly narrow: only the two budget/cap
  values and live-enablement are left to the operator; everything else is
  evidence-resolvable, consistent with the brief.

## What would change this verdict to REJECT

If, on inspection, `family_halt_submit_veto` did NOT actually run for
`pm_us_crh_v4` specifically (e.g. a family-id-scoped bypass I did not find)
— I did not locate one; `trade_supervisor_core.py`'s own docstring states
the halt is sender-global, not family-id-scoped, which is why D2 is a
characterization defect, not a substantive safety hole.

## Delta review (Revision 2)

Revision 2 sha256 `d91f619b6ed7f414337c1d3744d5a50a2cd50ddd49633a400d9e716fe6a20f00`
matches the coordinator's cited hash.

**Verdict: ENDORSE-WITH-REQUIRED-CHANGES (one remaining defect)**

- D1: genuinely fixed, re-verified — `docs/evidence/venue/polymarket_us/`
  exists; §3.5 now correctly says the file present doesn't meet A0's
  per-slug/≥5-day/extended-pin-test bar. Not reworded-around.
- D2: genuinely fixed, re-verified against source — `FAMILY_HALT_KEY` /
  `is_family_halted` (`trial_day_latch.py:1002-1015`) and
  `family_halt_submit_veto` (`composition.py:195`, wired `trade.py:260`)
  correctly described as already-existing and sender-global; only writers
  are `record_duplicate_fill`/`record_ambiguous_exit` (confirmed, no `set`
  CLI exists). §4 states plainly, present tense, the ruling is UNENFORCED
  until that CLI lands and runs — matches source, not just claimed.
  "May not SEND orders" (§4) is stated precisely and correctly distinguishes
  node/capture/shadow/KILL clock (unaffected) from order submission (halted
  once enforced).
- D3: fixed — HUNT-1 (`9ddcb8b`, `PROGRESS.md:51`) added to §7 as a fifth,
  independent re-arm precondition.
- **Remaining defect [LOW-MEDIUM]:** AUD-01 ownership for the
  `breezy-set-family-halt` CLI is a defensible module-adjacency call but
  conflicts with AUD-01's own hardened §5 scope, which after multiple
  review rounds explicitly limits it to AUD-01a (NO-side decision-path
  refusal) and AUD-01b (station-stall diagnosis), and explicitly excludes
  family-disposition matters ("owned by AUD-02"). A submit-time
  operator-halt CLI is neither AUD-01a nor AUD-01b. §6's instruction ("add
  a small, urgent scoped sub-item... alongside its existing NO-side gate
  work") is reasonable but should name it explicitly as a new §5 sub-scope
  (e.g. "AUD-01c") when AUD-01 is amended, not silently folded into
  AUD-01a/b's already-converged text — otherwise it reopens scope debate
  the prior review rounds closed. Not blocking: does not affect
  disposition (ii) or the halt's technical description.
- No regression found elsewhere in the revision.

## Delta review (Revision 3)

Revision 3 sha256 `9c53de23d2a32f4931cd931476f1c74f507e3de2c747b328abd83f53cb01d9ed`
matches. **Verdict: ENDORSE — no required change.**

Verified directly: `AUD-02-...md:149` ("Deciding A1 itself... a
family-disposition... owned by AUD-02") confirms AUD-02 already owns A1 as
a topic, so a new sub-item AUD-02b (set-halt CLI + RED tests + logged/
alerted halt event + the one-time set act) fits cleanly; AUD-01's §5 is
confirmed unchanged and still correctly excludes family-disposition/
enforcement work. The stale "operator, budget-ceiling only" §12 bullet is
correctly deleted — it was conditioned on a future (iii) arming, moot now
that (ii) is ruled; §7 still correctly reserves only the two budget/cap
values and live enablement as operator-only. No regression found.
