# G-21 — Pre-existing test-suite order dependence

Recorded 2026-08-27. **Not caused by any change in this session** — proven below.

## Symptom
Intermittent first-run failures that clear on re-run. Observed across at least
four different test names in three modules:

- `tests/unit/test_polymarket_us_auth_smoke.py::test_evidence_file_and_sidecar_are_owner_read_write_only`
- `tests/unit/test_polymarket_us_auth_smoke.py::test_a_permissive_preexisting_directory_is_tightened`
- `tests/unit/test_polymarket_us_fee_model.py` (`get_commission`)
- `tests/unit/test_polymarket_us_discovery.py::test_discovery_refuses_weather_city_without_registry_truth`

Three independent agents hit it on different modules, which is why it is
recorded as one item rather than four.

## Proof it is pre-existing
An agent holding six dirty files copied them aside, `git checkout`-ed the
tracked ones, moved its new test module out, and confirmed `git status` was
empty. On that pristine tree, with its work entirely absent, the flake still
reproduced **1/20**. It then restored all six files and re-verified the gates.

## Lead worth investigating first
`tests/unit/test_polymarket_us_auth_smoke.py:949`:

    monkeypatch.setattr(os, "umask", lambda _mask: 0)

That replaces process-global `os.umask` with a stub that *reports* 0 without
*setting* anything. `os.umask` is process-wide state shared by every test in the
session, so any test asserting created-file permissions is order-dependent on
whoever ran before it. `pytest-randomly` is active, which is why it surfaces
intermittently rather than never or always.

This is a hypothesis with a mechanism, not a diagnosis — it has not been
confirmed to cause the fee-model or discovery occurrences.

## Why it matters beyond the noise
A suite that fails ~1/20 for reasons unrelated to the change under test trains
readers to re-run rather than investigate. That is exactly the habit that lets a
real intermittent failure through. The repo's whole gate discipline rests on a
green run meaning something.

## Explicitly NOT the cause
One agent hypothesised `__warningregistry__` order dependence for the fee-model
occurrence and then disproved its own theory: `catch_warnings` bumps the filter
version and invalidates the registry. Recorded so the next investigator does not
re-derive a dead end.
