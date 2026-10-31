# STRAT-DESIGN r2.1 deltas — what changes in design_r2.md (2026-10-31)

Do not edit `design_r2.md` from this note. Sections not named here stay as written. Card E's frozen rule is `prereg_r2_1.md` (J1), not restated below. J7: that file's sha256 stays PENDING until the coordinator fills it after J1–J3. No run starts while it says PENDING.

## §0 — delta-compliance table

| Row | Was | Change |
|---|---|---|
| G2 | PARTIAL. Instrument set from trial records under `pm_us_*.json` | J5. Authoritative set is the durable store's order/intent records. Manifests and node logs are cross-checks, not the source |
| G3 | DONE. Two flag flips; pins replaced, not deleted | J4. Semantics confirmed; the turn-on list is incomplete. Flags stay false this round |
| G7 | DONE. Run 2 is G0 on `metar-routine` | J2. Run 2 BLOCKED. Not moot, and not started |
| G9 | DONE. Bonferroni k = 3; new evaluator | J6. Entry is the one-off analysis script. k = 3 is not the frozen rule |
| G10 | `prereg_r2.md` carries a sha256 of this design | Run 1 freezes on `prereg_r2_1.md`'s own sha256. Run 2 is not in that file |

G1, G4, G5, G8 are unchanged.

## §3 — engine verdict (J4)

Semantics at `engine.pyx` 4610–4727 and 7010–7096 stay correct. Withdraw "two flag flips and nothing else."

- Flipping harness lines 747 and 752 does nothing for makers until the order guard admits resting orders and `fees.py` is fixed. This round still does not touch the order guard, `allow_short`, or `fee_model`.
- `liquidity_consumption=True` triggers `_seed_trade_consumption`. That is a third behavior, not covered by the two bools.
- Pins to replace when a later note actually flips the flags, and not by deleting them: `tests/unit/test_runtime_backtest_harness.py:583` and `:586`, the docs parity test, `BACKTEST_VENUE_CONFIG.md` rows 59 and 62. §8 line 291 already says the False rationale expires. No safety, settlement, contract, pin, or NO-SEND test is weakened to go green.
- Card B's `queue_sizes` is a parallel re-implementation of Nautilus queue arithmetic: a descriptive prior only. If B survives, the engine path is the mandatory successor. §3 stays unused until that successor exists. No §4 card calls `backtest()`.

## §4.0 — own-order set (J5)

Replace the construction "instrument ids in the trial records under `deploy/families/pm_us_*.json` prefixes."

- Authoritative: durable-store order and intent records.
- Cross-checks only: family manifests and node logs. A disagreement is not resolved by preferring the manifest.
- Cards E and D-G0 only trim denominators by those instrument ids. They do not REFUSE when the set cannot be built. E has no PM.us book, so its trim is empty. An unbuilt set is not treated as empty and is not a date cut.
- Cards A, LOW, C, and B REFUSE if the set cannot be built. Do not shorten the window instead. The artefact still lists instrument ids and a count, never order ids.

## §4.D — Run 2 BLOCKED (J2)

`us_source_archive/metar-routine` covers 5 stations through 2026-06-30. `read_routine_metar` refuses past `HOLDOUT_START`. That source cannot support 2026-09-21..2026-10-30. Run 2 does not start.

Unblock only in a later note, by one of: name `src/breezy/ingest/iem_observations.py` or the observation sidecar, each with its own measured post-July coverage; or mark D G0 moot. This delta does neither. Coverage was not re-measured here.

Binding on any revival, and not in force while blocked:

- Grid denominator: named stations × climate days 2026-09-21..2026-10-30. Not "days that happened to have a frame."
- Per-station timezone table. 10:00 LST Pacific = 18:00Z, not 17:00Z. Delete the PDT shift that moves the hour to 11:00–12:00 LST.
- Report frame-days and METAR-days separately.
- Per-station floor ≥ 70%. The pooled 90% gate is not revived until its rationale is written in that note.
- Contaminated instruments listed by id, using the §4.0 set as a denominator trim (J5), not as a REFUSE.

The bid-test thresholds in §4.D stay frozen and still do not run.

## §4.E — entry label only (J6)

Replace "NEW EVALUATOR — exception requested. Not in the tree." The entry is ordinary analysis tooling: one module, `scripts/analysis/card_e_cli_vs_twc.py`. Not a harness, not an evaluator, not a runner. `k1_kalshi_prior.py` is imported read-only for transport; it stays byte-unchanged. IEM is `afos_cli_text_url` + `IemCliTransport` only.

PASS, KILL, window, mismatch, and m in the §4.E prose are superseded for Run 1 by `prereg_r2_1.md`. Do not keep Bonferroni k = 3 beside that file.

## §5 — order and end states (J2, J4, J5, J6)

- Thresholds for Run 1 live in `prereg_r2_1.md`. Delete "runs 1 and 2 are frozen in `prereg_r2.md`" and the requirement that the prereg carry a sha256 of `design_r2.md`. The coordinator fills the prereg's own sha256. PENDING blocks the run.
- Row 1 entry: the one-off script, not a new evaluator. Decision follows the prereg: PASS opens the Kalshi venue question as a build decision (not the size question); KILL closes the basis cell; INCONCLUSIVE names the extra days. No budget and no per-position size.
- Row 2 does not start. BLOCKED per §4.D. It is not the automatic next job after Row 1. The bid test stays unrun.
- Rows 3, 4, 5, 6 REFUSE if the §4.0 set cannot be built (A, LOW, C, B).
- Row 6, if the prior survives: successor is the engine path (§3), not another `queue_sizes` implementation. PASS still does not price an edge and does not set q.

Next-state bullets that send a Row 1 PASS to the operator size question, or that start Row 2 after Row 1, are withdrawn. Rows 3–6 are otherwise unchanged, and still do not start from this delta.
