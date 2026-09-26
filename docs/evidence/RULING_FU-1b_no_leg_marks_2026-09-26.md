# RULING — FU-1b: NO-leg position marks (2026-09-26)

**Authority:** `docs/plans/backlog/FU-1_plan_r2_2026-09-25.md:42` names this as a decision to take together with exit-family arming.

**How it was ruled:** Two agents were briefed blind and ruled independently: `trading-bot-architect` (AUTHOR) and `prediction-market-reviewer` (ADVERSARIAL). The coordinator merged their positions below, under the operator's standing grant. No operator-reserved value is involved.

## Agreed by both (evidence)
- **(A) "subscribe `^no` depth" is a category error.**
  - `^no` is a Breezy-internal composite id (`symbology.py:277-286`). `instrument_id_to_slug` refuses it (`:237-241`).
  - The venue has one book per market slug, and the YES leg already subscribes to it (`data.py:1465-1489`, `websocket.py:609`).
  - There is nothing new to subscribe to, so the 10-subs/connection cap is moot.
- **The correct NO mark already exists.**
  - A NO holding is short YES. Closing it means buying YES at the ask, walked to the held quantity, so the mark is `1 − ask_vwap`.
  - This is implemented in `walk_exit_vwap` (`monitor_evidence.py:162-201`) and uses the same fee model as `exit_decider`.
  - It is consistent with the execution path's `1 − YES` wire pricing (`exec/submit_chain.py:342-347`).
- **The gap is routing only.** `PositionMonitor._on_depth` (`position_monitor.py:323-328`) is keyed by `depth.instrument_id`, so a NO-registered position never receives its YES sibling's frames and stays `mark_source="missing"`.
- **Nothing live reads a NO mark today.**
  - `decide_exit` refuses at `family_not_exit_registered` (`exit_decider.py:218-224`) before `_book_is_executable` (`:235`). Every exit family is UNARMED (`exit_gate.py:33-44,55`).
  - The permit's budget gates never read a mark (`order_enablement.py:215-221`).
- **Leaving it unmarked costs this:** the SHADOW evidence base (`PositionMarkRecord`, the nightly `_one_sided_book` rate, the digest counters) is blind for every NO position. Future exit-arming decisions will be made from that evidence.

## Contradiction and resolution
- **AUTHOR: defer to arming.** A derived NO book would silently retire the second independent block on a live NO exit (`book_not_executable` caused by missing depth).
- **ADVERSARY: wire now.** Evidence correctness needs it regardless of arming.

**Resolution: BUILD NOW as FU-1d, with the author's safety concern satisfied explicitly rather than accidentally.**
1. Route each YES `OrderBookDepth10` frame also to any registered sibling NO position (`sibling_instrument_id`, `symbology.py:318-325`), evaluated with `leg="NO"` through the existing `walk_exit_vwap`. Add no new subscription, no new price formula and no adapter change. Nautilus is untouched.
2. **Replace the accidental safety layer with an explicit one.** Add a named, reason-coded refusal: a live NO-leg exit is refused unless the arming family's manifest explicitly declares NO-leg exit support. Pin it with a RED-first test. After FU-1d, a NO exit is blocked by TWO deliberate gates (the family gate and the NO-leg declaration), never by missing data.
3. Tests must prove all of the following:
   - (a) a NO position receives a mark from its YES sibling's frame;
   - (b) the mark equals `1 − walked YES ask VWAP` on a fixture;
   - (c) `decide_exit` for a NO leg still refuses today, at the family gate;
   - (d) with a registered test family lacking the NO-leg declaration, it refuses at the new gate even though a mark is present;
   - (e) YES-leg behaviour is byte-unchanged.

## Re-open triggers
- Any exit family is armed. The NO-leg declaration is then reviewed in that same arming change.
- Evidence that the walked-ask VWAP diverges from realized NO exit fills.

FU-1c (short-YES netting) stays parked.
