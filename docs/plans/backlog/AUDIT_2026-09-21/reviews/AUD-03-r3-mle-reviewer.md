# AUD-03 — Round 3 mle-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-03-daily-decision-funnel-digest.md
sha256: cefdefb6c7288c2fc479f0a9310d7ad2970c6c97bde5599ddc5b24ffe4c8b9c3
Round: 3
Reviewer: mle-reviewer (lens: production ML engineering — calibration tables as models, train/serve skew, data contracts, monitoring, rollback)

## Scope of this round's check (per coordinator instruction)

Round 2 (this lens) awarded 100/100 while the plan's entry filter used
`"quote_tick"` (a `Trigger` literal) instead of the real `Source` literal
`"quote"` — a miss the round-2 prediction-market-reviewer caught and this
lens did not, because the round-2 pass quoted the plan's own filter text
rather than independently re-deriving it from the `source=` assignment call
sites. This round, every literal and field name in the plan's schema/filter
description was checked one-by-one directly against
`continuous_strategy.py`, `position_monitor.py`, and `offer_tape.py` — not
carried over from either the plan's prose or a prior reviewer's report.

## Literal-by-literal verification (this round, direct grep + read)

| Plan claim | Source location | Verified |
|---|---|---|
| `source="quote"` (entry, quote-triggered) | `continuous_strategy.py:295` | CONFIRMED exact — `grep` hit at line 295, inside `_snapshot_from_quote` |
| `source="depth"` (entry, depth-triggered) | `continuous_strategy.py:1164` | CONFIRMED exact — `grep` hit at line 1164, inside `on_order_book_depth` |
| `source="no_side_shadow"` (shadow, excluded from entry funnel) | `continuous_strategy.py:1776` | CONFIRMED exact — `grep` hit at line 1776 |
| `source="position_monitor"` (exit, excluded from entry funnel) | `position_monitor.py:190` | CONFIRMED exact — `grep` hit at line 190, inside `_exit_offer_tape_record` |
| `Trigger = Literal["quote_tick", "on_data", "depth"]` (a DIFFERENT field from `Source`) | `continuous_strategy.py:263` | CONFIRMED — distinct type alias, `trigger="quote_tick"` used separately at line 1146 (`on_quote_tick`), never as a `source` value |
| `Source = Literal["quote", "depth"]` | `continuous_strategy.py:264` | CONFIRMED — note this type alias itself does not include `"no_side_shadow"`/`"position_monitor"`, both of which are written to `OfferTapeRecord.source: str` (a plain `str` field, `offer_tape.py`, not typed against the narrower `Source` alias) — the plan's classification is against the `OfferTapeRecord.source` field's actual runtime values, not the `_AskSnapshot.source: Source` alias, and this distinction is handled correctly: the plan's `_ENTRY_SOURCES`/`_SHADOW_SOURCES`/`_EXIT_SOURCES` buckets are defined over `OfferTapeRecord.source` string values, which is the field the digest actually reads. No defect. |
| `exit_rule` set from `outcome.rule.value if outcome.rule is not None else None` — can be `None` on a genuine exit row | `position_monitor.py:170` | CONFIRMED exact, refuting the Revision-2 `exit_rule is None` equivalence claim correctly |
| Margin stage `p_bound is not None and p_bound > break_even` matches live rule | `decision.py:402-404`: `break_even = price + _fee(...); if not (p_bound > break_even): return Refuse("edge_below_break_even", ...)` | CONFIRMED byte-exact |
| `p_bound`/`break_even` are present `OfferTapeRecord` fields | `offer_tape.py:117-120` | CONFIRMED, both `Decimal | None` fields present as described |
| 09-20 regression numbers (40,796 decisions; 4,816 rung-resolved) | `DECISION_FUNNEL_2026-09-20.md:10-11` | CONFIRMED exact |
| `resolve_alert_sink` / `AlertPayload.severity` | `runtime/health.py:579` (`def resolve_alert_sink`), `:351-378` (`AlertPayload`, `severity: str`) | CONFIRMED |
| `STRUCTURAL_HALT_REASONS` excludes `observation_ambiguous`/`illegal_cell` | `halt_detector.py:138-154` | CONFIRMED, five-member closed set exactly as cited |
| Sibling script pattern `position_monitor_nightly_report.py` | `scripts/analysis/` | CONFIRMED exists |

No wrong literal, wrong field, or mismatched type found anywhere in the
plan's §3/§6.2/§6.3 schema and filter description this round. The
round-2 defect (wrong `Trigger` literal substituted for the real `Source`
literal) is fixed and does not recur elsewhere in the revision.

## Defects

None MATERIAL. None MINOR found this round.

## Per-criterion points

- Fidelity to audit gap and completeness: 20/20 — the three-family
  row-classification (entry/shadow/exit) is now verified fully correct
  against all four real call sites; the digest's scope (funnel + stall flag
  + shadow line + A1-age line) matches G-17's stated gap.
- Technical correctness and evidence grounding: 20/20 — every literal, field
  name, and cited line range independently re-verified this round, all
  exact; the round-2 wrong-literal defect does not recur.
- Implementation specificity and feasibility: 15/15 — the fail-loud
  `UnknownOfferTapeSourceError` design, the three explicit bucket
  frozensets, and the margin-stage formula are all fully specified against
  real, unmodified source.
- Acceptance criteria and validation quality: 20/20 — the RED test suite
  (§7 steps 1,3-7,9,11) now covers exclusion, inclusion, fail-loud-unknown,
  shadow-own-line, and margin-tautology-vs-real-rule distinctly, closing
  every defect class found across three rounds; the byte-for-byte 09-20
  regression guard is independently achievable with the corrected filter
  (verified against the source numbers above), not a coincidence of
  EXIT-1-unarmed data as Revision 2's version was.
- Autonomous operation, failure handling, recovery: 15/15 — fail-closed
  missing-file/partial-day handling, fail-loud unknown-source handling, no
  retry-storm risk (`Persistent=true`, no `Restart=`), read-only trust
  boundary matching the sibling report script.
- Portfolio alignment, scope, dependencies: 10/10 — correctly independent of
  AUD-01; the AUD-02 §6.4 escalation-line ownership is now a required,
  conditional, RED-tested acceptance criterion in this plan's own §8, with a
  named fallback if AUD-02 has not landed — cross-checked non-circular
  against AUD-02's own Revision 3 text this round.

**Total: 100/100.**

## Required changes

None.

## Blockers

None. Confirmed no operator/strategy-lead ruling, PREREG amendment, or
unavailable evidence is required for this item's own acceptance.

## Disposition

APPROVE. The specific defect class this round's brief flagged (wrong
literal in the entry filter) is verified fixed and does not recur in any
other literal or field cited across the plan's schema/filter/margin logic.
