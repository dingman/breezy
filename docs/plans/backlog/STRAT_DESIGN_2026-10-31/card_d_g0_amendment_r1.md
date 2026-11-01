# Card D — G0 folded into the bid pre-registration, amendment r1 (2026-11-01)

Status: r1 PEER-REVIEWED 2026-11-01 (architect + prediction-market-reviewer: APPROVE CLOSE-WITHOUT-RUN; text fixes applied below). Card status: **CLOSED-UNRUN (expected KILL, prize ≈ 0, BLOCKER-H)**. Not frozen. **Zero looks used** (`prereg_r2_1.md:3`: "Run 2 is not registered").
Revises `card_d_g0_amendment_r0.md` (c30e57f5) against `review_card_d_g0_amendment_r0.md` (verdict REVISE, blockers 1–5).
Invariants: Nautilus is immutable; `allow_short` stays False; no operator cap is read or set; `iem_cli_fetch.fetch` is never
called; zero network; no order ids or fingerprints in any artefact; nothing in the holdout is fitted, folded or scored.
**Recommendation (§7): CLOSE-WITHOUT-RUN.** The frozen text below is kept so a later revival starts from a design that has already been reviewed.

Authorship: planner agent text, landed verbatim by the coordinator (planner has no Write tool). Unverified citations are listed in §9.

## 1. Blocker resolutions

- **Blocker 1 → resolution.** §2 rebuilds the scope on `docs/evidence/RULING_holdout_freeze_and_forward_window_2026-10-03.md`.
  The window splits in two. 09-21..10-01 sits inside the frozen holdout [07-01, 10-02), so it is descriptive under cl.3.
  10-02..10-30 is forward data under cl.2. The verdict uses the forward block only. The disclosure line goes in the artefact header (§5).
- **Blocker 2 → resolution.** There is no standalone G0 prereg and no `FREEZE_card_d_g0.txt`. G0 becomes precondition P0 inside the
  one bid prereg `prereg_card_d_bid.md`: one freeze, one look (§4).
- **Blocker 3 → resolution.** §3 corrects the cache facts. The "UNVERIFIED" T-group row is replaced by the measured shares.
  The KNYC cite now points to `scripts/analysis/cli_basis_offer_gate_scan.py:237-240`, and the store span to `scripts/archive/metar_routine_store.py:10`.
- **Blocker 4 → resolution.** §5 adds a header assertion that applies to both the dry run and the look. Any failure exits with code 2. The dry run prints counts only.
- **Blocker 5 → resolution.** The Q2 characterisation comes before the freeze, as precondition F1 in §4. The freeze cannot be minted until F1 is recorded.

## 2. Holdout scope and window split (10-03 RULING)

- Seal scope, per the architect's ruling (review :6-12): the seal limits what is FITTED, FOLDED or SCORED, not what may be read.
  Enforcing code: `multisource_blend_features.py:41-42`. The `metar_routine_minute_probe`/`metar_routine_store` guards only
  restrict the FB-R13 feature fetch (2021-01-01..2026-06-30, `metar_routine_store.py:10`). They are not used and stay byte-unchanged.
- **Block H (sealed holdout, cl.1 + cl.3): climate days 2026-09-21..2026-10-01, 11 dates.** These are reported in a separate
  descriptive table only. They are never in the verdict denominator and never a confirmatory input.
- **Block F (forward data, cl.2): 2026-10-02..2026-10-30, 29 dates.** **The ONE look's verdict is computed on Block F only.**
  The test fits no model, so using forward data here spends no AUT-4 α. Card D outputs never become a feature, threshold or
  selection input to any model scored on dates ≥ 07-01.
- Both blocks are read in the same invocation, so there is one look (L-34), provided Block H is rendered after the frozen verdict and can never feed it. Block H rows are labelled `descriptive_cl3` and are excluded from P0, the median and the floors.
- **Block F bids were already read by Card A leg 2** (every rung, 09-21..10-30, 18:00Z ± 30 min, `wp7b_census.py:45-49`), so Block F is forward data (cl.2) but not unseen. On revival the verdict block is the fresh post-freeze block of §7, never 10-02..10-30; the §4 denominator follows from that block.
- Card E's disclosure: the hand-appended lines (df6a92b0) violated L-75 (architect ruling: L-75 covers any writer-produced `docs/evidence/*`, `.md` included); reverted and moved to the sidecar `card_e_cli_vs_twc.disclosure.md`. The Card E writer was not re-run.

## 3. Corrected data facts

| Fact | r0 said | r1 (verified or measured) |
|---|---|---|
| Cache dir | — | `~/.local/share/breezy/archive/settlement-alignment-cache` (`scripts/analysis/settlement_alignment_cache.py:8-10`) |
| Cache span | "08-27 → today" | 2020-12-31 → 10-31, about 590k rows per non-NYC station (review :16-17, measured as counts; the fetch-start cites in r0 were per-study fetches, not coverage) |
| T-group on 5-min rows | UNVERIFIED | Present. 08-27..09-20: KSFO 98.6%, KLAX 99.6%, KMDW 99.8%, KMIA 97.9%, KNYC 98.1%. About 91% fall on 5-min marks; KNYC is hourly at :51 (review :15-17) |
| Row drop | — | Rows without a T-group are dropped (`settlement_alignment_study.py:251-253`). Resolution is tenths °C → `round_half_up_f` (`:261,:269`) |
| Loader | — | Globs `*.txt` (`cli_basis_offer_gate_scan.py:523`), filters on `station` (`:529`), silently skips unreadable files (`:526-527`) |
| Header | — | `parse_asos_rows` is a bare `csv.DictReader` with no header check (`settlement_alignment_study.py:664-665`). Hence §5 |
| CLI in dir | Q3 | CLI products are cached as `.zip`, so the `*.txt` glob does not pick them up (review :18) |
| KNYC | in grid | Excluded from P0 and the verdict and reported separately (`cli_basis_offer_gate_scan.py:237-240`; review Q4) |
| Sides | HIGH/LOW? | HIGH only (review Q4) |

## 4. Pre-registration `prereg_card_d_bid.md` (folded G0; frozen once, after peer review)

**F1 (before freeze; Q2).** Record the T-group share and minute-of-hour histogram per station, for 08-27..09-20 only.
These are counts with no temperature values. Values come from review :15-17. If the reviewers require a re-measure, the writer
produces it before the freeze (L-75: never a hand edit). The read is inside the sealed block, so it carries the cl.3 line.

**Estimand (`design_r2.md:202-207`, unchanged).** The YES bid on bands lying strictly below the running max. Not the ask.

**Definitions (Block F; stations LAX, SFO, MDW, MIA; HIGH).**
- Running max RM_f: the maximum `rounded_f` over T-group rows with `valid_utc` in [00:00, 10:30] LST of the climate day.
  LST is the standard offset (PT 10:30 LST = 18:30Z, CT = 16:30Z, ET = 15:30Z). The PDT shift is deleted.
- Dead band: its highest admissible integer °F `u` satisfies `u ≤ RM_f − 2`. PM.us edges are inclusive (`gte{A}lt{B}` = [A, B]).
  The 1 °F guard absorbs the tenths-to-whole °F conversion. It is frozen and open to reviewer challenge.
- Frame: the nearest Depth10 frame to 10:30 LST with `|offset| ≤ 15 min` and age ≤ 60 s (`design_r2.md:222-223`).
  If there is no such frame, the station-day is missing, not a zero bid. An empty bid on a present frame counts as 0.00, which leans toward KILL.
- Exclusion: §4.0 own-order instruments are trimmed from the denominator only. No id appears in the artefact.
- Station-day statistic: the YES bid of the dead band nearest below RM_f.

**P0 (folded G0 precondition).** A station-day is obs-valid if `hour_coverage` contains every LST hour 0..9 and at least one
row falls in [10:00, 10:30] LST. P0 passes if, for each of the 4 stations, obs-valid station-days / station-days with a frame ≥ 70%.
If P0 fails, the result is INCONCLUSIVE. The look is spent and there is no re-run.

**Denominator N.** Block F station-days that are obs-valid, have a frame, and have at least one untrimmed dead band. The grid is 4 × 29 = 116.

**Frozen criterion (`design_r2.md:233-237`).**
- PASS: P0 met, N ≥ 30, at least 7 distinct dates, and the median YES bid is ≥ 0.10. A size gate applies only after the Depth10 unit line.
- KILL: the median is ≤ 0.03, or N < 30.
- Otherwise, a median in (0.03, 0.10) is INCONCLUSIVE.
- P(PASS | H0) ≈ 0.

**Decides.** A KILL ends late-day rounding designs on PM.us (this card only). A PASS writes a later note. It places nothing and does not reach the size question.

**One look.** The freeze sha is checked by a ≤ 30-line local guard (review Q5). `wp7b_census.py` stays byte-unchanged.

## 5. Header check, dry run, artefact

- For every `*.txt` that contributes a row, in both the dry run and the look:
  - the first line must start with `station,valid`;
  - the DictReader fieldnames must include `station`, `valid` and `metar`.
- Any failure, or an unreadable file, exits with code 2. The loader's silent `continue` at `:526-527` cannot hide a file.
- Dry run (not a look; L-59 counts and timestamps only), zero writes, store opened `mode=ro`. It prints:
  - file count and header-pass count;
  - own-order trim count;
  - per-station min/max `valid`;
  - station-days with a frame per block.
- The dry run prints no per-day coverage, no RM_f and no bid.
- Artefact header line: "Holdout disclosure (RULING 2026-10-03 cl.3): 09-21..10-01 read as DESCRIPTIVE evidence only, never a
  confirmatory input; verdict on forward data 10-02..10-30 (cl.2)."

## 6. Harness route — BLOCKER-H

No existing Breezy script produces the estimand.
- `wp7b_market_as_forecaster.py` has only `--census-only`, `--prereg-sha` and `--dry-run` (`:1312-1322`).
- `--census-only` dispatches into `wp7b_census.run_census`, which is pinned to 18:00Z (`wp7b_census.py:47`) and to leg sums (`:282-333`).
- `cli_basis_offer_gate_scan.py` joins the ASOS running max to upper-tail **asks** with a ≤ 0.05 ceiling (`:230-235`), not to dead-band **bids**.
- `cli_basis_boundary_study.py` scores against CLI truth.
- `design_r2.md:209` itself says "NEW EVALUATOR — exception requested".

Adding the estimand would mean joining RM_f to Depth10 bids at 10:30 LST, selecting bands and taking a median. That is
evaluator logic, which the operator ruled out on 10-21. The r0/review assumption of "one flag, cheap" does not hold.
The Card A `--census-only` precedent was one flag in front of a new module of more than 800 lines.
**This is a BLOCKER.** r1 proposes no flag and no evaluator. Only an operator exception or an architect ruling can lift it.

## 7. Prize and decision — CLOSE-WITHOUT-RUN

- Expected outcome: KILL (`design_r2.md:235-236`).
- Prize: **≈ $0 at qty 1.** `design_r2.md:49` gives "D dead band: $0".
  - At a YES bid of 0.03 the NO costs 0.97. Fee θ·p·(1−p) = 0.0695 × 0.97 × 0.03 = 0.0020, which banker's rounding (`fees.py:218`, `:353`) takes to $0.00 at qty 1; gross 0.03 − 0.02 slippage ≈ +0.01/contract, and that case is a KILL anyway.
  - At the 0.10 PASS edge the NO costs 0.90, fee 0.0063 (≈ 0.01 after rounding), so the net is < 0.09/contract before slippage, on a few station-days a month (review :33-37). The NO price = 1 − YES bid identity is the Card A assumption (`card_a_census.md:130`) and is unverified under SELL/BUY_SHORT.
  - A PASS places nothing anyway (`design_r2.md:239-242`).
- Execution caveat: a NO buy goes to the venue as SELL/BUY_SHORT and `allow_short` is False; whether the merged NO-side path (S5) covers this bid is NOT verified here. A PASS writes a later note anyway.
- Consistent with (not corroborating; different estimand, whole-ladder Σ YES bid at 18:00Z): Card A's NO-basket leg was KILLED on 149 station-days (`card_a_census.md:119-122`). Card E was KILLED. The KILL expectation rests on the dead-band bid being near 0 and on the `design_r2.md:49` prize of $0.
- Value of a run: it would only confirm an expected KILL on a cell already priced at $0. It cannot reach the size question even on a PASS.
  It would also cost an evaluator exception (§6) plus a review loop.
- **Decision:** CLOSE Card D without running it. The status is `CLOSED-UNRUN (expected KILL, prize ≈ 0, BLOCKER-H)`. No look is consumed.
- Revival condition (all three must hold):
  - (a) the operator answers the size question with q materially above 1 for PM.us;
  - (b) BLOCKER-H is lifted by operator exception or by an existing harness path;
  - (c) the venue fee or tick changes so that a NO at ≥ 0.97 nets > 0.
- On revival, this §4 text is frozen as written, plus two additions the PM review requires: a frozen bid-SIZE floor (a 1-lot 0.10 bid must not PASS) and a date-clustering note (4 stations share dates, so "≥ 7 dates" is a weak independence floor). F1 is re-recorded if more than 30 days old. The look runs on a fresh forward block that starts after the freeze.

## 8. Notes for reviewers

- Contradiction: review :38 ("cheap, one flag") versus §6 — RULED 11-01: §6 holds (`design_r2.md:209, :413` already named D a NEW EVALUATOR); review :38 is void.
- L-75 — RULED 11-01: extends to any writer-produced `docs/evidence/*` including `.md`; Card E lines reverted to a sidecar (see §2).
- Open follow-up: `DEFAULT_SPLITS` still lacks cl.1's `holdout_end_exclusive` (`nbp_calibration.py:273-278`). This is an architect change under cl.4.

## 9. Cited but not verified by the author

- The cache span (2020-12-31 → 10-31, ~590k rows), the T-group shares, the minute-of-hour shares and ".zip CLI caching" come from the review's measurement (`review_card_d_g0_amendment_r0.md:15-18`); not re-measured.
- `prereg_r2_1.md:3`, `wp7b_census.py` being over 800 lines, and `nbp_calibration.py:273-278` were taken from r0, the review and grep context; not opened line by line.
- The fee arithmetic in §7 follows the review and Card A conventions; not recomputed through `fees.py`.

**Peer review: DONE 2026-11-01 — architect APPROVE CLOSE-WITHOUT-RUN (BLOCKER-H verified at file:line; no RUN route), prediction-market-reviewer APPROVE CLOSE-WITHOUT-RUN (close is consistent with the 10-21 directive: no look spent, no winner foregone).**
