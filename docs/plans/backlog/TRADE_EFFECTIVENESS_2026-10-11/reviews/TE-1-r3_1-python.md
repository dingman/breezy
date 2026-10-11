VERDICT: READY-WITH-CHANGES (no BLOCKER or HIGH remains; one MEDIUM must be fixed first)
SCORE: 92/100

All six r3 findings (H1, H2, M1, M2, L1, L2) and merge items 1–5 and 12 are implemented correctly, except for one S0-9 pattern.

**M-1 (MED). The `not_wired` S0-9 pattern over-matches, so the WP-A acceptance can never pass.**
- A bare `not_wired` over `src/` and `tests/` also hits `src/breezy/analysis/autonomy/evidence_row.py:216-219` (`*_reader_not_wired`) and `tests/unit/autonomy/test_evidence_row.py:289`.
- That is 5 hits beyond the 4 the plan expects. S0-9's table and the WP-A acceptance ("zero hits in src/ and tests/") both break.
- Fix: use `\bnot_wired\b` or `reason=not_wired`. The `\b` form excludes the `_reader_not_wired` hits, because `_` is a word character.

**Checked and correct**
- **S0-9 schema regex.** `(schema_version|SCHEMA_VERSION).*== 4(?![0-9])` over `tests/` returns exactly 10 lines. They are `test_portfolio_roi_report.py` lines 283, 423, 2234, 2295, 4424, 5165, 5187, 5909, 5921 and 5922. `:4708` is excluded.
- **`ProducerUnpinned` and the control flow.**
  - `_RC_REFUSED` is 2, as the existing test's `rc == 2` shows.
  - At `label_run.py:860` and `:895`, `unit_factory(args)` is the only call that can raise. Wrapping the `_resolve_factory` call and the factory call in one `try/except ProducerUnpinned` is compatible.
  - In `_measure_main`, the refusal fires after the `is_measure_unit` and MemAvailable gates, which is acceptable.
  - The `main` and `_measure_main` branches both return `_RC_REFUSED` after printing.
- **Sentinels against the real `UnitWiring` fields.**
  - `deps`, `unit_max_bytes`, `measured_peak_bytes`, `proof_window` (`ProofHook | None`) and `slot_ns` match.
  - `Lock` is a Protocol with `acquire(wait_s)->bool` and `release`, so a sentinel is easy to write.
  - `aut6`: the plan says "absent", but `Aut6Reading.status` is `pass | not_pass | missing | corrupt`. Use `missing_aut6_reading()` (`memory_gate.py`).
- **Rename test.** The monkeypatch of `unit_wiring.producer_pin_state` only works if the factory calls it through the module attribute, not a from-import. Say so in the brief.
- **Remaining items.** The single `_resolve_factory` helper, the dropped contract with the fully-qualified AST guard, the both-producer re-pin rule and rollback, and the subprocess `env` and `sys.executable` are all correctly stated.

Relevant paths:
- /home/jon/breezy/docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/TE-1_plan_r3_1.md (S0-9 table row for `not_wired`, WP-A acceptance, WP-A sentinel list)
- /home/jon/breezy/src/breezy/analysis/labeling/label_run.py
- /home/jon/breezy/src/breezy/analysis/labeling/memory_gate.py
- /home/jon/breezy/src/breezy/analysis/autonomy/evidence_row.py