# AUT-4 r8 — merged blind review (2026-10-03)

## Scores

| Reviewer | Score | Verdict |
|---|---|---|
| prediction-market-reviewer | 92 | NOT READY (1 HIGH) |
| mle-reviewer | 88 | NOT READY (2 HIGH) |

## Closed from r7

- AH1–AH5 are closed.
- E-7b and E-7c are consumed.
- The quarantine bind fails closed.
- The `lint-imports` gate and the `sample_size` closure test are present.
- `--tmpfs /tmp` is on every row.

## Owed in r9 (all binding)

### BH1 [HIGH, MLE]: the eval-offline closure cannot reach 0 adapter modules

**Problem**
- `runtime/order_enablement.py:44-53` imports `adapters.polymarket_us.write_transport`, which is a banned HTTP/WS module. It also imports `operator_controls` and `safety`.
- `current_rung_hold/{composition,continuous_strategy,strategy}.py` import it for `OrderSubmissionPermit`.
- §3.9a forbids editing `order_enablement`.
- `fees.py` imports `adapters…errors` and `…parsing`.

**Required in r9**
- State this as a certain finding.
- Choose one of the following and justify it:
  - (a) An owner-reviewed, pure permit-type seam. `OrderSubmissionPermit` moves to a dependency-free module and is re-exported from `order_enablement`. The NO-SEND firewall and the permit-minting path stay byte-identical.
  - (b) Declare N-1 now, as a named non-exec exception with a guard test.
- Re-measure the closure with M1–M3 simulated in a scratch checkout. Do not claim 0 without that measurement.

### BH2 [HIGH, PM + MLE]: M3 live-path gates and behaviour preservation

Add all of the following:
- **Exec-client sha pin.**
  - Pin `exec/client.py`, `submit_chain.py` and `endpoints.py`, plus a no-diff check.
  - Reuse the existing pin pattern in `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py`. Do not invent a new one.
- **Boot smoke.**
  - Run it in a fresh process on each live entrypoint.
  - Compare class identities before and after M3.
  - Resolve eagerly at boot, so that lazy imports cannot defer an ImportError to first use.
- **Permit check.** A scripted permit-line check after the supervisor restart. M3 needs its own supervisor-restart plan, with a window between 01:00Z and 16:40Z.
- **Lazy `__getattr__` tests.**
  - A non-export raises AttributeError, so `PERMANENTLY_UNEXPORTED` / `not hasattr` holds.
  - `dir()` and `import *` behave as today.
  - Submodule attributes are covered, plus a grep for `pkg.sub` attribute usage.
- **Arrow registration.** The set of `register_arrow` registrations loaded is equal before and after. `domain/forecast_point.py:675` is an example of a module-scope registration.
- **Golden replay test.** fs_replay output is byte-identical before and after M1–M3 on a fixed fixture.
- **Module and config diff.** Diff `sys.modules` and the Nautilus config types (from PM MED).

### BM1 [MEDIUM]

- Add one sentence rejecting branch (b) of the earlier fork, or explaining why it is not safer (PM).
- Make the wrapper's `/tmp` ownership (E-7c) a sequenced build gate before AUT-4 rows go live (MLE).

### BL1 [LOW]

- Pin a numeric memory cap for the `/tmp` tmpfs scratch.
- State the N-1 fallback explicitly (PM).

## Approval bar

Both reviewers ≥95 and zero CRIT/HIGH.
