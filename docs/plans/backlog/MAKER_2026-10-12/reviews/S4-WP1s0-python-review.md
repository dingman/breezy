# S4 WP1 step 0 python review (ee266fde, tests/unit/test_polymarket_us_discovery.py)
Verdict: APPROVE (no CRITICAL/HIGH; 2 LOW)

(1) Characterisation: PASS. Test 1 asserts exact ordered equality with the 60 daily slugs, len(listing)==71,
    skipped set == listing minus discovered, len 11, SJC slug included, sightings == (). Not vacuous.
    Tests 2/3 use pytest.raises on real code paths; 4/5 assert exact lists and non-None positive control.
(2) Mutation evidence: credible. Each of the 5 tests has a named mutation + target; RED outcome stated per mutation.
    LOW: commit body says "-> RED" but quotes no RED line (L-33 asks for it quoted); not re-run here.
(3) sys.modules file-path load: same pattern as tests/unit/test_fee_drift_evidence_pull.py:34-39
    (spec_from_file_location + sys.modules[spec.name] + exec_module). Script has only an `if __name__ == "__main__"`
    entry (:860) and no module-level calls; transport is a stub _Client; gate ran under bwrap no-egress. Safe.
    LOW: unique name "wp1s0_fee_drift_pull" is never removed from sys.modules (parity with existing test; harmless).
(4) _station_day private import: acceptable for a tolerance-audit characterisation; it is the exact seam where
    non-daily slugs are filtered, and it is a pure function. Public entry would need a data_root fixture. No change.
(5) Additions only: 112 insertions, 0 deletions, 1 file; no existing test edited. Tripwire at :653-664
    ("climate-policy-index-2026" raises "does not match the observed weather grammar") intact.
(6) mypy: Success, 0 errors in 1 file. ruff check: clean. ruff format --check: clean.
    `# noqa: E501` on the long test name (line ~960) is justified (name carries the 60/11 contract); the
    parenthesised `-> (  None )` shape is ruff-format output, ok.
Minor: test 3 (daily-shaped unparseable slug) has no `match=`, so any VenuePayloadError satisfies it.
    Fix (optional): add match="does not match the observed weather grammar" if that is the real message.
Gate: `[breezy] gate: phase1 rc=0 phase2 rc=0` (37 passed + 41 passed; basetemp removed).
