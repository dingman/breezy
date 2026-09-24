# AUD-03 — Daily decision-funnel digest, delivered through the existing alert path

## 1. ID and actionable title

**AUD-03.** Ship a small, unattended daily job that computes the decision
funnel (decisions emitted → rung resolved → cell legal → priced → margin>0 →
orders, by station) from the already-written offer-tape decision log and
delivers a one-line-per-stage summary through the existing alert egress, so
"why no trades today" is answerable in seconds without an ad hoc offline
study — closing the gap `DECISION_FUNNEL_2026-09-20.md` itself diagnoses and
`docs/core/LESSONS.md`'s `no-trade-day-diagnosis-gaps-2026-09-14` names.

## 2. Source finding, verdict, class

Gap **G-17** — "'Why no trades' is not answerable from the node log"
(`AUTONOMY_ROI_AUDIT_2026-09-21.md` lines 104-106, verdict FALSE/observability,
verified via G-01). Directly stated consequence in
`docs/evidence/DECISION_FUNNEL_2026-09-20.md`, "Monitoring implication":
*"Every existing signal is a fault signal or a wait signal. None is an edge
signal... The funnel above is the minimum daily digest, and it must be
DELIVERED... rather than written to a file nobody opens."*

Class: **autonomous-operation failure (observability)** — not a pricing or
safety defect. The underlying refusal reasons (`observation_ambiguous`,
`illegal_cell`) are, per AUD-01, CORRECT and by design homogeneous most days
— they must NOT become halt pages (that would defeat the existing, deliberate
"a homogeneous judgement reason is not a halt" design in `halt_detector.py`).
This item is about making the COMPOSITION of an ordinary day's refusals
readable on demand, not about alerting on them as faults.

## 3. Current behaviour, required behaviour, gap

**Current, verified against source (not assumed):**
- `HaltDetector` (`src/breezy/strategy/weather_common/halt_detector.py:264-421`)
  already distinguishes a genuine discovery/subscription collapse
  (`zero_evaluation_halt`, gated on `wait_ticks==0`, fixed `e83fc5c`
  09-20 — **this specific WP-R1 false-page defect is ALREADY CLOSED**,
  contradicting `docs/core/PROGRESS.md:103-128`'s still-open framing; see
  §12) from an "all refused for one STRUCTURAL reason"
  (`all_refused_halt_reason`, `:227-242`, closed set
  `STRUCTURAL_HALT_REASONS` = `fee_schedule_mismatch`, `shorts_disabled`,
  `instrument_unresolved`, `settlement_halt`, `no_side_first_order_pending`).
  **`observation_ambiguous` and `illegal_cell` are deliberately NOT members
  of that set** — a day that refuses 100% of decisions on
  `observation_ambiguous` (exactly what happened 09-16 through 09-20 per the
  funnel) produces **zero alerts**, by design, because the detector correctly
  treats it as an ordinary "judgement" outcome, not a halt
  (`test_one_homogeneous_judgement_reason_is_not_a_halt`).
- No script or unit converts the raw
  `~/.local/share/breezy/catalog/quote_tape/decisions/offer_tape_<date>.jsonl`
  rows (schema confirmed by direct read of `OfferTapeRecord`,
  `current_rung_hold/offer_tape.py:82-155`: `station`, `hour_lst`, `reason`,
  `illegal_cell`, `ask`, `break_even`, `p_bound`, `side`, `decision`,
  `source`, `exit_rule`, `exit_decision`, per-row) into the aggregate funnel
  table `DECISION_FUNNEL_2026-09-20.md` computed by hand.
- The `docs/evidence/DECISION_FUNNEL_2026-09-20.md` analysis itself was a
  one-off, read-only, human-triggered study — not a repeatable job.
- **The offer-tape is a shared sidecar for THREE distinct row families, not
  two — corrected after round-2 review, re-verified directly against
  `continuous_strategy.py` and `position_monitor.py` this revision, not
  trusted from the module's own prose docstring (which the round-2
  prediction-market-reviewer found imprecise — see §6.2):**
  - **Entry-hunt rows** — the strategy's own real per-tick pricing decisions,
    written at two call sites: `_snapshot_from_quote`
    (`continuous_strategy.py:289-298`) writes `source="quote"` (line 295,
    **not** `"quote_tick"` — `"quote_tick"` is a value of the DIFFERENT
    `Trigger` field, `Trigger = Literal["quote_tick", "on_data", "depth"]`,
    `:263`, used at `trigger="quote_tick"`, line 1146; the `Source` field is
    separately typed `Source = Literal["quote", "depth"]`, `:264`), and a
    second call site writes `source="depth"` (`continuous_strategy.py:1164`).
    Both re-verified this revision by direct `grep` against current source:
    `continuous_strategy.py:295: source="quote"`,
    `continuous_strategy.py:1164: source="depth"`.
  - **NO-side shadow rows** — `continuous_strategy.py:1776: source=
    "no_side_shadow"`, written from `_evaluate_shadow_rest` (around
    `:1748-1786`, re-read this revision): a **shadow-mode, resting-bid
    evaluation** (per the operator's 09-16 resting-bid ruling,
    `docs/core/LESSONS.md` `operator-ruling-resting-bids-2026-09-16`), never
    a real order attempt — these rows can never carry `decision == "take"`
    for a submitted order and are not entry-hunt decisions in the sense §6.3
    means it.
  - **Exit-decision rows** — `position_monitor.py:174-198`
    (`_exit_offer_tape_record`), unconditionally `source="position_monitor"`
    (`:190`), for the intra-day position monitor's own exit decisions
    (INC-E3, EXIT-1, gap G-12, currently BUILT/UNARMED). `exit_rule`
    (`:193`) is set from `rule_value = outcome.rule.value if outcome.rule is
    not None else None` (`:170`, re-read this revision) — **`exit_rule` CAN
    be `None` on an exit row** (an early-refused exit that never reached
    rule selection), so `exit_rule is None` is **not** a safe stand-in for
    "is an entry-hunt row"; only `source` distinguishes the three families
    unambiguously.

**Required behaviour:** an operator (or the next audit) can answer "why did
today produce N trades" without re-deriving the funnel from raw tape rows,
and a genuinely NEW failure mode (e.g., a station's `illegal_cell` share
jumping from its usual ~0% to 100%, or a station producing zero rows at all
inside its window — the LAX/MDW 09-20 shape from AUD-01b) is visible in a
daily digest even though it correctly does not page as a `HaltDetector`
CRITICAL. The funnel must also be computed from the LIVE pricing rule, not a
plausible-looking restatement of it, so the digest's "margin > 0" stage
means what the strategy itself means by margin > 0. The row filter that
decides which rows are even eligible for the funnel must be correct against
the REAL, closed set of `source` values the strategy writes today, not a
plausible-looking restatement of them (round-2 correction, below).

**Concrete gap:** the funnel computation exists only as a scratchpad/manual
analysis; nothing runs it daily, persists it, or delivers it through
`resolve_alert_sink` (`runtime/health.py:579-610`, already proven working
09-20 per `f97c26f`).

## 4. Priority, rationale, dependencies, execution order

- **P1.** Not P0: no live-money or safety impact (AUD-01a covers the safety
  gap; the existing `HaltDetector` already covers genuine structural halts
  and the false-page defect is already fixed). But it is the concrete,
  smallest fix for a named, repeatedly-costly gap — PROGRESS.md's own
  Readiness Audit already names "alerts reach nobody" as a defect that cost
  three days once; an unreadable funnel is the same class of cost recurring
  on every no-trade day.
- **No dependency on AUD-01 for this item's own acceptance.** AUD-02
  dependency, corrected after round-2 review: this plan's core funnel
  digest still has no dependency on AUD-02 either. It does, however, now
  OWN one REQUIRED, conditional acceptance criterion — the A1-open-age
  escalation line — whose content is specified by AUD-02 §6.4 and which
  applies only once AUD-02 has also landed; see §8's new required bullet
  and §12 for the ownership/fallback resolution (closing the round-2
  prediction-market-reviewer's unowned-escalation finding on AUD-02, which
  named AUD-03 §8 as the natural owner).
- **Execution order:** independent of AUD-01; can land any time relative to
  it. Recommended to land before AUD-02's A0 (fee-drift evidence pack),
  since A0 will want exactly this funnel shape rather than re-deriving it by
  hand a second time (a reuse opportunity, not a hard dependency — A0 can
  proceed without it). If AUD-02 lands BEFORE this item is implemented, the
  A1-open-age line (§8) is a required part of this item's own acceptance;
  if AUD-02 has not landed by then, §8's fallback applies (a named,
  owned follow-up item, not a silent gap).

## 5. Scope and explicit exclusions

**In scope:** one new oneshot script + systemd unit pair (mirroring the
`breezy-position-monitor-report` pattern already in the repo), reading only
the local decision-tape parquet/jsonl files already written by the live
strategy, computing the funnel per station per day **restricted to
entry-hunt rows** (source `"quote"`/`"depth"` only, corrected filter below),
reporting NO-side shadow rows as a separate, clearly-labelled count (never
merged into the entry funnel), and delivering a summary through
`resolve_alert_sink`.

**Excluded:**
- **No change to `HaltDetector`, `STRUCTURAL_HALT_REASONS`, or
  `zero_evaluation_halt`** — those are correct as shipped (§3); this item
  does not touch that module's alerting semantics, only adds a SEPARATE,
  lower-severity daily digest.
- **No new refusal-reason taxonomy decisions** — the digest reports whatever
  reasons appear in the tape verbatim; it does not classify them as
  fault/wait/edge (that classification work, per the evidence doc's own
  "Open questions", is a bigger research item, out of scope here).
  ~~"Monitoring implication" calls for an edge signal~~ — that is a modelling
  question (does a refused decision represent forgone edge), not an
  observability one; not attempted here.
- **No credential, no venue socket, no order-affecting code** — read-only
  over an already-written local file, same trust boundary as
  `position_monitor_nightly_report.py`.
- **No backfill of days before the observation store begins (09-17)** — the
  digest runs forward from deployment; historical funnel reconstruction (as
  performed by hand for 09-16/09-20) is not re-automated.
- **No change to `offer_tape.py`'s schema or writer** — this item is a
  read-only consumer of the existing, already-shipped fields (`p_bound`,
  `source`, `exit_rule` included); it adds no new tape field.

## 6. Proposed changes grounded in inspected code/data flows

1. **New script** `scripts/analysis/decision_funnel_daily_digest.py`,
   modelled on `scripts/analysis/position_monitor_nightly_report.py`'s
   shape (oneshot, reads a local store, writes a dated artefact, delivers via
   the alert sink). Reads
   `~/.local/share/breezy/catalog/quote_tape/decisions/offer_tape_<climate_day>.jsonl`
   for the just-completed climate day (schema fields confirmed by direct
   read of `OfferTapeRecord`, `offer_tape.py:82-155`).
2. **Row filter — REWRITTEN per round-2 review (MATERIAL defect fixed).**
   The Revision 2 filter, `source in {"quote_tick", "depth",
   "no_side_shadow"}` (with a claimed-equivalent `exit_rule is None`), used
   a wrong literal: the round-2 prediction-market-reviewer found, and this
   revision independently re-confirmed by direct `grep` against
   `continuous_strategy.py` (see §3), that entry-hunt rows are written with
   `source="quote"` — never `"quote_tick"` (that string is a `Trigger`
   value, a different field) — so the Revision 2 filter would have silently
   EXCLUDED every quote-triggered row, the dominant entry-hunt path, from
   every funnel stage. The claimed `exit_rule is None` equivalence was also
   refuted: `position_monitor.py:170` sets `exit_rule=None` on some
   genuinely exit-sourced rows (an early-refused exit that never reached
   rule selection), so that check would silently RE-ADMIT some
   `position_monitor` rows into the entry funnel.

   **Fixed filter, decided and justified here (coordinator requirement):**
   this function classifies every row against the REAL, closed set of
   `source` values the strategy currently writes (re-verified this
   revision, three call sites, `grep`-confirmed): `"quote"`
   (`continuous_strategy.py:295`), `"depth"` (`:1164`), `"no_side_shadow"`
   (`:1776`), `"position_monitor"` (`position_monitor.py:190`). Rather than
   the weaker `source != "position_monitor"` (which would silently ADMIT
   any future fourth row-family into the entry funnel unless someone
   remembers to exclude it too), this function uses an **explicit allow-list
   per bucket that FAILS LOUDLY on any other value**:
   - `_ENTRY_SOURCES = frozenset({"quote", "depth"})` — the six-stage entry
     funnel (§6.3) is computed ONLY over rows with `source in
     _ENTRY_SOURCES`.
   - `_SHADOW_SOURCES = frozenset({"no_side_shadow"})` — reported as a
     separate, clearly-labelled count (§6.4), never merged into the entry
     funnel's six stages. **Decided explicitly (coordinator requirement):**
     shadow rows are NOT entry-hunt decisions — `_evaluate_shadow_rest`
     (`continuous_strategy.py:1748-1786`) is a resting-bid shadow
     evaluation per the operator's 09-16 ruling and can never produce
     `decision == "take"` for a submitted order; folding it into "decisions
     emitted → ... → orders" would corrupt every downstream percentage with
     rows that were never candidates for the "orders" stage by design, the
     same class of contamination the round-1 mle-reviewer flagged for
     `position_monitor` rows.
   - `_EXIT_SOURCES = frozenset({"position_monitor"})` — excluded from the
     digest's funnel entirely (unchanged intent from Revision 1/2), reported
     only as a raw exit-fired/exit-refused count for context.
   - **Any row whose `source` is not in `_ENTRY_SOURCES | _SHADOW_SOURCES |
     _EXIT_SOURCES` raises `UnknownOfferTapeSourceError` (a new, small
     exception local to this script)** rather than being silently counted
     toward, or silently dropped from, any bucket. Justification: a future
     fourth row-family (e.g. a new shadow mode, a new exit rule tag) must
     force a deliberate update to this digest's classification, not
     silently join whichever bucket a loose comparison happens to admit it
     to — the same fail-loud-on-unknown-input discipline this repo already
     applies at other trust boundaries (`UnknownFeeScheduleError`,
     `UnknownSiteError`). This is a stricter, safer choice than
     `source != "position_monitor"` and is the one this plan specifies.
3. **Funnel stages computed exactly as the live decision rule defines them,
   per station, over `_ENTRY_SOURCES` rows only:**
   - decisions emitted: count of `_ENTRY_SOURCES` rows after the §6.2 filter.
   - rung resolved: `reason != "observation_ambiguous"`.
   - cell legal: `illegal_cell is False` and not refused for that reason.
   - reached a price: `ask is not None and break_even is not None`.
   - **margin > 0: `p_bound is not None and p_bound > break_even`** — this
     is the ACTUAL live rule, verified verbatim at
     `current_rung_hold/decision.py:402-404` (`_finalize_take`):
     `break_even = price + _fee(price, inputs.fee_coefficient); if not
     (p_bound > break_even): return Refuse("edge_below_break_even", ...)`.
     `p_bound` is a real, present offer-tape field
     (`offer_tape.py:117-120`, "The side's own edge estimand (`P_HOLD_LOWER`
     for YES, `1 - P_HOLD_UPPER` for NO)"), added specifically so a
     snapshot's WHY could be reconstructed. The round-1-draft definition
     (`ask < break_even`) compared a price to a price-plus-fee and is a
     TAUTOLOGY (true on nearly every priced row, since
     `break_even = ask + fee(ask)` and fee is strictly positive) — it would
     have silently reported "margin > 0" as satisfied for almost every
     priced row regardless of the actual probability/price comparison the
     strategy uses. Fixed here to the probability-vs-price-plus-fee
     comparison the strategy itself makes. (Re-verified this revision,
     round 2: `decision.py:402-404` byte-exact.)
   - orders: `decision == "take"` (post-filter, so an armed EXIT-1's own
     "take" analog on the exit side, if any, is excluded by construction —
     `_EXIT_SOURCES` rows never enter the entry funnel at all under the
     rewritten §6.2 filter).
   Reuses no strategy import — this is a pure aggregation over
   already-materialised tape fields, not a re-evaluation of
   `evaluate_decision`, so it cannot silently diverge from or duplicate the
   live decision logic (DRY: it reports what the strategy already decided,
   using the same field the strategy itself wrote for that purpose, never
   re-deriving a decision from scratch).
4. **NO-side shadow line (new, per round-2 correction):** a separate
   per-station count of `_SHADOW_SOURCES` rows for the day (total, and
   split by whatever `reason` they carry), labelled explicitly as "shadow
   evaluations, never counted toward the orders funnel above" — so the
   information is not lost, merely never blended into the six-stage funnel.
5. **Per-station "stalled" check** (feeds AUD-01b, not duplicated logic): for
   any station inside its own `[12:00,17:00)` LST window with zero
   `_ENTRY_SOURCES` rows in the digest window, flag it explicitly — this is
   exactly the LAX/MDW 09-20 shape, surfaced going forward instead of
   requiring another ad hoc study.
6. **A1-open-age escalation line (new, ownership resolved per round-2
   review — see §8/§12):** whenever `pm_us_crh_v4` is the live family and
   no `family_halted`/re-registration ruling doc exists under
   `docs/evidence/` (per AUD-02 §6.4's specification, unchanged by this
   item), the digest's per-day output includes one additional line: "A1
   open, N days since gap G-02 filed" — computed from the earliest dated
   evidence doc naming gap G-02 (`AUTONOMY_ROI_AUDIT_2026-09-21.md`'s own
   filing date is the anchor; N = calendar days since). This reuses the
   digest's own delivery path (`severity="INFO"`, same `AlertPayload`), no
   new transport.
7. **Delivery:** one `AlertPayload` per day (or per station if the payload
   would be too large), `severity="INFO"` (never CRITICAL — this must not
   collide with or duplicate `HaltDetector`'s CRITICAL semantics), through
   `resolve_alert_sink()` — the exact native mechanism already delivering
   `f97c26f`'s alerts, no new transport code.
8. **New systemd unit pair** `breezy-decision-funnel-digest.{service,timer}`,
   copying `breezy-position-monitor-report`'s resource/slice/`Documentation=`
   conventions (`MemoryHigh`/`MemoryMax` sized down further — this reads one
   day's JSONL, not a parquet join), scheduled after
   `breezy-quote-tape-rotate.service` so the prior day's file is finalized
   (check the rotate timer's exact cadence before picking a time slot; must
   not collide with any existing `OnCalendar` per
   `tests/unit/test_deploy_timer_hours.py`'s "no two timers same
   hour:minute" contract).

## 7. Ordered implementation or verification steps

RED-first, per repo convention:
1. RED: a unit test for the pure aggregation function (e.g.
   `funnel_for_day(rows: Iterable[dict]) -> FunnelReport`) asserting the
   EXACT 09-20 numbers from `DECISION_FUNNEL_2026-09-20.md` (40,796
   decisions; 4,816 rung-resolved; 0 legal; 0 priced; 0 margin>0; 0 orders)
   against a fixture built from the real schema fields, **using
   `source="quote"`/`source="depth"` (the real literals, not
   `"quote_tick"`) for the entry-hunt rows in the fixture** — fails before
   the function exists.
2. GREEN: implement `funnel_for_day` as a small, dependency-free pure
   function (no I/O), matching this repo's calibration-architecture style
   (pure functions for anything the RED test can pin exactly), including the
   corrected `_ENTRY_SOURCES`/`_SHADOW_SOURCES`/`_EXIT_SOURCES`
   classification (§6.2) and the corrected `p_bound > break_even` margin
   stage (§6.3) from the start — all are part of the function's first
   correct implementation, not a later patch.
3. RED: a synthetic-fixture test with a MIXED entry+exit-row input — one
   `source="quote"` row and one `source="position_monitor"`,
   `decision="exit_fired"` row — asserting the exit row is excluded from
   every funnel stage (stage-1 count reflects only the entry row).
4. **RED (new, per round-2 review — the direction round 1 missed):** a
   synthetic-fixture test asserting a real `source="quote"` row and a real
   `source="depth"` row are BOTH counted at stage 1 ("decisions emitted") —
   the inclusion direction, not merely the exclusion direction §7 step 3
   already tests. This is the specific gap the round-2
   prediction-market-reviewer named: step 3 alone would still pass under
   the wrong (Revision 2) filter, since `"quote_tick"` never appears in real
   data either way; only an inclusion assertion against the REAL literal
   (`"quote"`) catches the defect.
5. **RED (new, per round-2 review):** a synthetic-fixture test asserting a
   row with an unrecognised `source` value (e.g. `"bogus"`) raises
   `UnknownOfferTapeSourceError` from `funnel_for_day` rather than being
   silently counted or silently dropped — pins the fail-loud behaviour
   decided in §6.2.
6. **RED (new, per round-2 review):** a synthetic-fixture test asserting a
   `source="no_side_shadow"` row is excluded from all six entry-funnel
   stages AND is reflected in the separate shadow count (§6.4) — pins the
   "own line, not the entry funnel" decision.
7. RED: a synthetic-fixture test distinguishing the margin>0 stage from the
   tautological comparison — a row where `ask < break_even` is TRUE but
   `p_bound <= break_even`, asserting that row is NOT counted as margin>0
   (and a second row where `p_bound > break_even`, asserting it IS counted).
8. GREEN: confirm steps 3-7 pass against the step-2 implementation (all
   should already be covered by a correct `funnel_for_day`; if not, fix).
9. RED: a test for the per-station stall flag using a synthetic fixture
   shaped like the LAX/MDW 09-20 case (zero `_ENTRY_SOURCES` rows, station's
   window open) vs a station with rows (must NOT flag).
10. GREEN: implement the flag.
11. **RED (new, per round-2 review, AUD-02 §6.4 ownership):** a test that,
    given a fixture where `pm_us_crh_v4` is the live family and no ruling
    doc exists under a fixture `docs/evidence/` directory, the digest's
    delivered `AlertPayload` includes the "A1 open, N days" line with the
    correct day-count computed from a fixed reference date; and a second
    test that, given an existing ruling doc, the line is ABSENT. Both use a
    fake filesystem/fixture, never the real `docs/evidence/` tree.
12. GREEN: implement the A1-open-age line (§6.6).
13. RED: an integration test that the script reads a real-shaped JSONL
    fixture file, calls `resolve_alert_sink`, and asserts exactly one
    `AlertPayload` with `severity="INFO"` and the computed funnel in
    `detail`/a structured field — using a fake sink, never a real webhook.
14. GREEN: wire the script's `main()`.
15. Deploy config: write the unit/timer pair; RED-first
    `tests/unit/test_deploy_timer_hours.py`-style assertion that the new
    `OnCalendar` slot does not collide with any existing timer, before adding
    it to the real timer file.
16. `ruff`/`mypy` clean; full `tests/unit/test_decision_funnel_daily_digest*`
    suite green.

## 8. Measurable acceptance criteria and required evidence

- RED→GREEN output for all steps in §7, pasted as the change artefact.
- `funnel_for_day` reproduces `DECISION_FUNNEL_2026-09-20.md`'s exact 09-20
  table (six stage counts) from a fixture built from real tape rows for that
  date, **using the real `source="quote"`/`"depth"` literals** — a
  byte-for-byte regression guard against the hand-computed evidence doc that
  is actually achievable with the corrected filter (Revision 2's version of
  this bullet relied on a coincidence — 09-16/09-20 predate EXIT-1 and carry
  no `position_monitor` rows — that happened to mask the wrong-literal
  defect; this revision's filter is correct independent of that
  coincidence).
- The mixed entry/exit-row fixture (§7 step 3), the quote/depth INCLUSION
  fixture (§7 step 4), the unknown-source fail-loud fixture (§7 step 5), the
  shadow-row own-line fixture (§7 step 6), and the tautology-vs-real-rule
  margin fixture (§7 step 7) all pass, proving the digest is not blind to
  any of the defect classes identified across round-1 and round-2 review.
- One end-to-end dry run against the real 09-20 or 09-19
  `offer_tape_<date>.jsonl` (read-only), producing a digest whose numbers
  match the evidence doc, attached as evidence under `docs/evidence/`.
- Unit/timer pass `test_deploy_timer_hours.py` (or its equivalent) with no
  collision.
- No `src/breezy/strategy/**` file touched — confirms the DRY/no-duplication
  claim in §6.3 held in practice, not just in intent.
- **REQUIRED, conditional (new, per round-2 review — closes AUD-02's
  unowned-escalation defect; this plan is the owner):** IF AUD-02 has landed
  (its Amendment C is present in `POST_FORECAST_PHASE_2026-09-20.md` and its
  §6.4 requirement is on record) by the time this item is implemented, THEN
  the A1-open-age line (§6.6, §7 steps 11-12) is a REQUIRED, RED-tested
  acceptance criterion for THIS plan's own DONE status — not optional, not
  merely "on record." **Fallback, if AUD-02 has NOT landed by the time this
  item is implemented:** this bullet is deferred, and the implementer files
  a standalone, owned follow-up backlog item (owner: whoever implements this
  script; a dated ticket under `docs/plans/backlog/`, not a scope note
  buried in a sibling plan) to add the line once AUD-02 does land, and
  records that follow-up explicitly in this item's own closing note. Either
  way, at least one of the two plans (this one) treats the line as an
  enforced obligation rather than a mutual scope note that neither plan's
  acceptance criteria actually requires — closing the exact "correct
  finding, undelivered" failure shape the escalation mechanism exists to
  prevent (§11).

## 9. Validation: failure cases, integration behaviour, autonomous operation

- **Missing/rotated tape file:** the script must fail CLOSED with a named,
  non-CRITICAL diagnostic ("no decision tape found for `<date>`"), never
  crash silently or emit a misleading zero-funnel digest that reads as "zero
  decisions today" when the real cause is a missing file — a test asserts
  this distinction explicitly (mirrors the A-2 three-valued lesson from
  `POST_FORECAST_PHASE` amendment A: absence is not the same fact as zero).
- **Partial-day tape (mid-rotation read):** the digest states the coverage
  window it actually read (min/max `observed_at_ns` seen), so a partial read
  is visibly partial, not silently presented as the whole day.
- **Future EXIT-1 arming:** covered by construction (§6.2's filter), not
  merely by a fixture that happens to be exit-row-free today — the mixed
  fixture (§7 step 3) proves the filter is active code, not implicit in the
  09-20 data's shape.
- **Unrecognised `source` value (new, per round-2 review):** rather than a
  systematically wrong count that passes every existing test silently (the
  exact failure mode the round-2 prediction-market-reviewer identified in
  Revision 2's own filter — a "misleading zero-ish/undercounted digest"
  §9 already warns against for the missing-file case, but did not, before
  this revision, guard against for a wrong-literal filter), any row this
  digest cannot classify raises loudly (`UnknownOfferTapeSourceError`, §6.2)
  rather than silently joining a bucket — pinned by §7 step 5.
- **Integration:** runs entirely after the trading day via a `oneshot`
  systemd unit; holds no credential, opens no socket, cannot affect order
  submission even in principle (same trust class as
  `position-monitor-report`).
- **Autonomous operation:** unattended by design (timer-driven); a missed
  run is not an incident (`Persistent=true` catches a reboot-missed run,
  matching the sibling unit's own stated posture); no `Restart=` — a bad run
  does not retry-storm.

## 10. Deployment, observability, rollback

Deploys as a new, independent unit pair — zero risk to any existing unit or
the live trading node (no shared code path with `current_rung_hold`'s
strategy modules). Observability: this IS the observability deliverable —
delivered through the already-proven alert egress
(`alert_egress_configured`/`f97c26f`), `severity="INFO"` so it never
competes with a `HaltDetector` CRITICAL for operator attention.
**Rollback:** `systemctl --user disable --now
breezy-decision-funnel-digest.timer`; the script and its stored artefacts
are inert without the timer, and nothing else references them.

## 11. Relationship to portfolio-level ROI and evaluation

No direct ROI. This closes a diagnosis-latency cost that has already been
paid concretely at least twice in this repo's own history (the three-day
silent fee halt, the eleven-hour silent permit lapse — both "emitted, never
delivered" per `POST_FORECAST_PHASE` amendment B-0) and is the SAME failure
shape for pricing refusals: the answer existed in a file nobody reads. This
item's evaluation is operational, not financial: the next no-trade day, an
operator (or agent) should be able to state the funnel from the delivered
digest without re-running an ad hoc analysis — measured by whether AUD-02's
future A0 work package (or any future audit) cites this digest instead of
re-deriving the funnel by hand. Because the margin>0 stage is now computed
against the correct live rule (§6.3) and the row filter is now computed
against the correct `source` literals (§6.2), the digest is also safe to
consume the day AUD-01a's or any future gate change lets decisions reach
pricing again — the failure mode the round-1 domain review specifically
flagged as "activates the moment decisions reach pricing again" is closed
before that day arrives, not discovered on it. The A1-open-age line (§6.6)
additionally makes AUD-02's own governance blocker visible on every digest
run, closing the "rots silently" risk both round-2 reviews on AUD-02
independently confirmed was otherwise unenforced by either plan.

## 12. Assumptions, unresolved questions, blockers

- **No blocker.** This item requires no operator ruling, no strategy-lead
  ruling, and no PREREG amendment — it is pure read-only aggregation and
  delivery, using only already-shipped native mechanisms
  (`resolve_alert_sink`, the systemd timer pattern). The A1-open-age line
  (§6.6) reports on AUD-02's blocker; it does not require that blocker to be
  resolved, only visible.
- **Assumption:** the offer-tape JSONL schema (confirmed by direct read of
  `OfferTapeRecord`, `offer_tape.py:82-155`, including `p_bound`, `source`,
  `exit_rule`) is stable enough to build a fixture-pinned test against; if
  the strategy's tape-writer schema changes, the RED test in §7 step 1 will
  fail loudly rather than silently drift, which is the intended contract.
- **Open, stated not resolved:** exact `OnCalendar` slot for the new timer —
  deferred to the implementer, who must check the live timer inventory
  (`deploy/systemd/README.md`'s protected-window table) at build time rather
  than trusting this plan's snapshot, since the inventory changes as other
  backlog items land.
- **Ownership of the AUD-02 §6.4 escalation line — RESOLVED per round-2
  review (was: "New, named per AUD-02 §6.4," an unowned scope note).** This
  plan's own §8 now makes the A1-open-age line a REQUIRED acceptance
  criterion, conditional on AUD-02 having landed first, with a named
  fallback (a standalone, owned follow-up ticket) if AUD-02 has not landed
  by the time this item is implemented. This closes the round-2
  prediction-market-reviewer's MATERIAL finding on AUD-02 (both plans could
  reach 100% of their own acceptance criteria while the escalation line
  never shipped) by making it enforceable in exactly one place, per the
  coordinator's explicit instruction.
- **Correction carried forward, not this plan's to fix:**
  `docs/core/PROGRESS.md:103-128`'s "2026-09-20 — WP-R1 calibration defect
  found in production (open)" entry is STALE — the fix landed same-day
  (`e83fc5c`). Flagged here because it directly bears on this item's scope
  (confirms `HaltDetector` need not be touched); PROGRESS.md itself is not
  edited by this plan per the planning-only constraint.

## 13. Review history

**Round 1** (two independent reviewers; both scored "implementation
specificity" on a /20 scale though the rubric caps that criterion at 15 —
round-1 totals below are as reported by each reviewer and are NOT comparable
to the 20/20/15/20/15/10 rubric; they are superseded by the Revision 2
self-score at the end of this section, which uses the correct caps):

- **mle-reviewer: 90/100 (as reported).** MATERIAL: the offer-tape JSONL is
  a shared sidecar for entry-hunt AND intra-day exit-decision rows
  (distinguished by `source`/`exit_rule`); §6.2's original "count every row"
  definition would silently contaminate stage 1 the day EXIT-1 (BUILT,
  UNARMED, gap G-12) arms, and no test pinned only against 09-16/09-20 data
  (EXIT-1 unarmed then) would catch it.
  **Disposition: ACCEPTED.** §6 (now §6.2) adds an explicit row filter
  (`source in {"quote_tick","depth","no_side_shadow"}`, equivalently
  `exit_rule is None`) applied before any stage is counted; §7 adds a RED
  test (step 3) with a synthetic mixed entry+exit-row fixture proving the
  filter is active code, not an accident of the 09-20 data's shape; §9 adds
  an explicit "future EXIT-1 arming" validation case citing that fixture.

- **prediction-market-reviewer: 78/100 (as reported).** MATERIAL: the
  "margin > 0" stage was defined as `ask < break_even`, which is a
  TAUTOLOGY (`break_even = ask + fee(ask)`, fee strictly positive) — it does
  not reproduce the live rule at `decision.py:402-404`
  (`p_bound > break_even`, a probability-vs-price-plus-fee comparison), and
  the omission traced to the plan's own schema list (§3/§6.1) omitting the
  `p_bound` field despite claiming to have read the schema directly. The
  09-16/09-20 regression fixture is all-zero on this stage and cannot catch
  the bug; it is latent until decisions reach pricing again. MINOR: schema
  list in §3/§6.1 omitted several present fields.
  **Disposition: ACCEPTED, both.** Re-verified directly against
  `decision.py:399-404` and `offer_tape.py:117-120,82-155` this round — the
  reviewer's citation is exact. §6.3 (renumbered) redefines the margin>0
  stage as `p_bound is not None and p_bound > break_even`, citing the exact
  source lines; §3 and §6.1's schema descriptions now include `p_bound`,
  `source`, and `exit_rule` explicitly (the fields actually load-bearing for
  this plan's own logic); §7 adds a RED test (step 4) with a synthetic
  fixture distinguishing `ask < break_even` (always true) from
  `p_bound > break_even` (the real test), matching the reviewer's required
  change exactly.

**Revision 2 self-score** (correct caps: 20/20/15/20/15/10):
- Fidelity to audit gap and completeness: 19/20 — unchanged from round 1;
  correctly reuses the evidence doc's funnel definition (now corrected to
  match the LIVE rule rather than the evidence doc's own prose gloss on it),
  correctly defers the fault/wait/edge classification question.
- Technical correctness and evidence grounding: 20/20 — both material
  defects (schema/source contamination; margin-stage tautology) were
  independently re-verified against current source this round (`offer_tape.py`
  docstring and field list; `decision.py:399-404`) and both corrections are
  now grounded in exact citations rather than the round-1 draft's
  plausible-but-wrong restatement.
- Implementation specificity and feasibility: 15/15 — the aggregation
  function's business logic (`funnel_for_day`) is now fully and correctly
  specified: the row filter and the correct margin comparison are both part
  of the first implementation, not a later patch, closing the exact gap
  both reviewers independently found in the one piece of logic this plan
  owns.
- Acceptance criteria and validation quality: 20/20 — two new synthetic-
  fixture RED tests (mixed entry/exit rows; tautology-vs-real-rule margin
  comparison) directly target both round-1 defects, on top of the existing
  exact-reproduction regression guard; the digest can no longer look correct
  today while being wrong the day either EXIT-1 arms or pricing resumes.
- Autonomous operation, failure handling, recovery: 15/15 — unaffected by
  either correction; fail-closed missing-file/partial-day handling remains
  specific and well-reasoned, now paired with a digest that is also
  correct on the day it starts mattering.
- Portfolio alignment, scope, dependencies: 10/10 — correctly independent of
  AUD-01/AUD-02; the AUD-02 §6.4 digest-field note is recorded without
  creating a hard dependency in either direction.

**Revision 2 total: 99/100. Status: NOT READY — round 2 review pending.**

**Round 2** (two independent reviewers, blind, against Revision 2):

- **mle-reviewer: 100/100.** Both round-1 MATERIAL defects independently
  re-verified fixed against current source (`offer_tape.py:194-248` field
  serialization; `decision.py:402-404` byte-exact). New-defect pass on the
  revision itself found no MATERIAL defect — notably, this reviewer did NOT
  catch the wrong `source` literal the prediction-market-reviewer found (see
  below); its own citations quote the Revision 2 filter's literals without
  independently checking them against the `source=`/`trigger=` assignment
  call sites.
- **prediction-market-reviewer: 70/100.** New MATERIAL finding (not raised
  by either round-1 reviewer or by this round's mle-reviewer): §6.2's entry
  filter used `"quote_tick"` where the real code writes `"quote"` (a
  `Trigger`-field value mistaken for a `Source`-field value, sourced from
  the offer-tape module's own imprecise docstring rather than the actual
  assignment sites), which would have silently EXCLUDED the majority of
  real entry-hunt rows; the claimed `exit_rule is None` equivalence was also
  refuted (`position_monitor.py:170` sets `exit_rule=None` on some genuine
  exit rows too). Required change: fix the filter to the real literals (or
  simplify to `source != "position_monitor"`); add an inclusion-direction
  RED test; re-verify the byte-for-byte 09-20 regression bullet is
  achievable post-fix rather than passing by 09-16/09-20's EXIT-1-unarmed
  coincidence.

**Divergence:** mle-reviewer 100 vs prediction-market-reviewer 70 —
readiness is the LOWER score (70), driven entirely by the
prediction-market-reviewer's MATERIAL literal-value finding, which the
mle-reviewer's own round-2 pass did not catch (a real miss, not a
disagreement in judgement — the mle-reviewer's citations this round quoted
the plan's filter text rather than independently re-deriving it from the
`source=` assignment call sites, exactly the class of error the coordinator
brief's "quote the literal names/lines you saw" instruction exists to
prevent). Both round-1 MATERIAL defects (shared-sidecar contamination;
margin tautology) remain independently confirmed fixed by both reviewers
this round; the round-2 defect is new, in the revision's own corrected
text, at a level (the literal `source` string values) neither round-1
reviewer tested.

**Revision 3 self-score** (correct caps: 20/20/15/20/15/10; conservative,
against the fix actually applied this round, every load-bearing citation
independently re-verified directly against current source via codegraph and
`grep` before writing this revision, per the coordinator's binding
instruction — not carried over from either reviewer's report):
- Fidelity to audit gap and completeness: 18/20 — the funnel shape,
  delivery mechanism, and scope boundaries are correctly reasoned and the
  row-classification defect is now fixed at the literal-value level; docked
  2 (not fully restored to 19-20) because this is the second round a defect
  was found in the one piece of original business logic this plan owns,
  which argues for continued scrutiny at implementation time even though
  this revision's fix is independently re-verified against source.
- Technical correctness and evidence grounding: 20/20 — every `source`
  literal cited in this revision (`"quote"` at `:295`, `"depth"` at
  `:1164`, `"no_side_shadow"` at `:1776`, `"position_monitor"` at
  `position_monitor.py:190`, and the `exit_rule=None` non-equivalence at
  `position_monitor.py:170`) was independently re-verified this round by
  direct `grep` against current source, not merely quoted from a reviewer's
  report.
- Implementation specificity and feasibility: 14/15 — the fail-loud
  `UnknownOfferTapeSourceError` design and the three-bucket classification
  are fully specified and executable; one point held back because the exact
  new exception's exact placement (script-local vs. a shared module) is
  left to implementer judgement.
- Acceptance criteria and validation quality: 19/20 — five distinct RED
  tests (mixed exclusion, quote/depth inclusion, unknown-source fail-loud,
  shadow-row own-line, margin tautology) now target every defect class
  found across both review rounds; one point held back because the exact
  reference-date source for the A1-open-age day-count (§6.6) is specified
  in prose (the audit's own filing date) rather than pinned to a single
  named artefact path an implementer cannot mis-read.
- Autonomous operation, failure handling, recovery: 14/15 — the
  fail-loud-on-unknown-source behaviour directly closes the "systematically
  wrong but silently green" failure mode §9 previously did not guard
  against; one point held back because this is the newest of the fixes in
  this revision and has not yet been exercised against a real future
  fourth-source scenario.
- Portfolio alignment, scope, dependencies: 10/10 — the AUD-02 escalation
  ownership gap is now closed on this plan's side (§8's required,
  conditional criterion with a named fallback), consistent with AUD-02's
  own Revision 3 text (cross-checked when writing AUD-02's revision in the
  same pass).

**Revision 3 total: 95/100. Status: NOT READY — round 3 review pending.**

<!-- COORDINATOR FINAL STATUS — appended after review; everything above this line is the reviewed revision -->

## Coordinator final status (2026-09-21) — authoritative

This block supersedes any score or readiness wording in §13 above, which plan revisers wrote
before review closed.

- **Reviewed revision sha256** (file content above the marker line): `cefdefb6c7288c2fc479f0a9310d7ad2970c6c97bde5599ddc5b24ffe4c8b9c3`
- **Baseline self-score:** 96/100
- **Final score (lowest reviewer, never averaged):** 100/100
  - `mle-reviewer` round 3: 100/100 — `reviews/AUD-03-r3-mle-reviewer.md`
  - `prediction-market-reviewer` round 3: 100/100 — `reviews/AUD-03-r3-prediction-market-reviewer.md`
- **Readiness:** **READY**
- **Unresolved blockers:**
  - None.
- **Full review history:** 6 records, `reviews/AUD-03-r*-*.md`
- Planning only. Nothing in this plan has been implemented.
