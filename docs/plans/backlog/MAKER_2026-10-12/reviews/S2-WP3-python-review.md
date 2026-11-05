# S2 WP3 Python review (commit 44562c03, worktree maker-s2-wp3)

Date: 2026-10-14. Reviewer: python-reviewer (code quality, typing, idioms, tests).
Verdict: APPROVE (no CRITICAL/HIGH; MED items are test-coverage gaps worth closing before WP4 consumes the module).

Evidence
- mypy (2 files, worktree PYTHONPATH): "Success: no issues found in 2 source files" -> 0 errors, ratchet not affected.
- ruff check: clean. ruff format --check: clean.
- Tests via run_tests_no_egress.sh: 29 passed (brief said 30; 29 collected incl. 3 parametrized). EXIT line printed by the gate:
  `[breezy] gate: phase1 rc=0 phase2 rc=0` (phase2 = 41 passed). Basetemp removed.
- Size: module 181 lines, longest function ~23 lines. Pure: no I/O, no clock, no mutable globals. Absolute import
  `from scripts.analysis import maker_stage0_rule as rule` matches the fq_loss_taxonomy_reconstruct.py convention.

CRITICAL: none. HIGH: none.

MED
1. tests/unit/test_maker_stage0_rule.py:34-39 reads the spec via a cwd-relative Path and imports Path inside the
   test. Fails when pytest runs from another cwd. Fix: Path(__file__).resolve().parents[2] / "docs/...". Move import to top.
   Also the plan (WP3 line 140) names the test `test_constants_match_spec` and mentions a pinned spec sha; the file has
   `test_rule_constants_match_spec_v03` + `test_constants_match_spec_text` and no sha pin. Rename/merge to the plan
   name and add the sha check (or state it is deferred to the plan's pin test).
2. Boundary values missing: no test at exactly p_no == P_MIN (0.94 must pass, 0.9399 refuse); bid exactly B_FLOOR
   (0.70 accepted) vs 0.69 at decide_bid level (select_rungs 0.69 is covered at test:142 only); b_max at the
   B_FLOOR edge (largest b == 0.70 vs none); p_yes == 0.06 in select_rungs (the `P_MIN - _EPS` guard at
   rule:135 is untested at the boundary). STALE_H boundary is covered (test:99-100).
3. select_rungs gaps (rule:117-139): no test for modal at index 0 or last index (abs(idx - modal) edge), modal tie
   (first wins per docstring), equal p_yes ties (sort falls back to ladder index, undocumented), or a bid above
   B_CAP. Add one parametrized test for the first three.
4. K1 determinism: k1_rung is trivially selected[0]; test_max_rungs_1_subset_is_lowest_p_yes (test:164) duplicates
   test_k1_rung_is_first_ranked_at_first_attempt (test:157). Merge, and add a determinism assertion (same inputs
   in a different dict insertion order is NOT equal by design since adjacency is positional; document and test that
   the caller must pass ascending ladder order, or accept a sorted-key input).

LOW
5. rule:39-44 BidDecision docstring says "a price, or a refusal reason (never both)" but nothing enforces it. Add
   __post_init__ (exactly one is not None) or a tagged form.
6. rule:47-48 `_cents` hard-codes 100 while b_max uses `cent / 100`; add `_CENTS_PER_UNIT: Final[int] = 100`.
7. rule:56-67 b_max does not validate theta (negative/NaN theta silently accepted); decide_bid/select_rungs do not
   validate best_no_bid/no_ask/bids range. Acceptable for a pure internal module, but WP4 feeds tape data; either
   validate at the WP4 boundary or add a cheap [0,1] check in _cents.
8. rule:108 forecast_gate returns bare reason strings; promote to module-level Final constants (or an Enum) so WP4/WP6
   reports compare against symbols, not literals (same for decide_bid reasons rule:83,86,94, currently repeated in
   tests as literals). This is the only hidden coupling to WP4/WP6: reason strings are an implicit interface.
9. rule:151-154 hard_cancel_ns takes std_offset_hours as bare int (-8 convention is sign-sensitive); name the
   convention in the docstring (UTC offset, negative west) and test a half-hour/unsupported case or type it.
10. Test duplication: tests/.../test_maker_stage0_rule.py:16-22 re-implements _utc_ns and NS_H; fine for
    independence, but assertion messages are absent on multi-assert tests (test:42-49, 175-183). AAA is loosely followed.
11. rule:167 obs_cancel has a boolean positional-or-keyword flag `integer_c`; make it keyword-only (`*, integer_c`).
12. rule:4 docstring cites spec "lines 69-136" and per-constant "Lines 72-73" comments exist; most Final constants have
    cites, but STALE_H/MAX_RUNGS/CANCEL_LST share one comment line (acceptable).

Verified OK
- Constants match spec lines 72-73; b_max, clamp, empty-NO-bid and empty-YES-bid semantics match spec 83-99 and plan WP3.
- Refusal paths return explicit reason strings; invalid p_no raises ValueError (NaN handled). No silent None except
  bid_price (documented wrapper) and listed_in_time/k1_rung (documented).
- gtd midnight roll-forward at exact midnight is tested; obs_cancel boundary (78.0 / 77.9, 76.1 / 76.3) covered.
