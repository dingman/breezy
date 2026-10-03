# AUT-6 r8: merged review (coordinator)

TBA scored 93 (1 HIGH); SFH scored 92. Final score: 92, so the plan goes to r9.

## HIGH

- **AA1 [TBA H]: stage runtime bound.**
  - **Verify first:** confirm whether `TimeoutStartSec` covers the whole oneshot start phase across multiple `ExecStart=` lines, or re-arms per command. Use a scratch transient unit test via `systemd-run --user` with two sleeps.
  - **Hard kill:** wrap the bwrap stage in an external hard kill, `timeout -k 2 <DEMAND_STAGE_BUDGET_S> bwrap …`.
  - **R-d:** derive R-d from the worst case.

## MEDIUM

- **AA2 [both reviewers]: stage 2 runs even when evaluate fails.**
  - **Change:** make evaluate `ExecStart=-`, or run stage 2 from `ExecStopPost`.
  - **Unit result:** the OR of both stages, with the real exit codes visible to #22.
  - **Test:** add `test_demand_stage_runs_after_late_evaluate_failure`.
- **AA3 [both reviewers]: the demand stage emits its own `PRODUCER_INTRADAY_DEMAND` summary line.** It carries `integrity_demand_write_failures`. #23 keys on that line and on the `integrity_demand_write_failed` record.
- **AA4 [SFH]: demand listing fails closed.** Any read error on the C4 verdict dir or `evidence/demand/` produces three things:
  - a non-zero exit;
  - `INTEGRITY demand_listing_unreadable`;
  - a delivered CRITICAL.
  
  Add a RED test.
- **AA5 [SFH]: self-probe strictness.**
  - **Before the probe:** `stat` `state/` first.
  - **Negative probe:** it must get exactly EROFS. If the open unexpectedly succeeds, unlink the file and treat it as INTEGRITY.
  - **bwrap launch failure:** map a non-zero bwrap exit to a CRITICAL `bwrap_unavailable` delivered by the unwrapped evaluate stage or the notifier. Never let it pass silently.
- **AA6 [SFH]: AST test completeness.**
  - **Forbidden constructs:**

    | Category | Constructs |
    |---|---|
    | File creation and opening | `os.open(O_CREAT/O_WRONLY/O_RDWR)`, `os.fdopen`, `io.open` |
    | File moves and deletion | `os.replace`, `os.rename`, `os.unlink`/`remove`, `mkdir`/`makedirs` |
    | High-level writes | `Path.write_*`/`touch`/`mkdir`/`unlink`, `shutil.*` |
    | Dynamic code and subprocess | `__import__`, `exec`, `eval`, `asyncio.create_subprocess_*` |

    These are in addition to the E-7 list.
  - **Rows:** rows are path-literal or constant.
  - **Scope:** the closure covers the `breezy.*` AUT-6 globs only, consistent with AUT-1's boundary. Each owner's modules are checked under that owner's table.
- **AA7 [SFH]: Y2 schema.** `_self_heal_mode.json` carries `degraded` and `degraded_since_ns`, cleared only on recovery to SELF_HEAL. This keeps degraded state distinct from pre-AUT-5b ALERT_ONLY. Add a test that runs several passes after the drop.

## LOW

- **Y1: one explanation per ended invocation.** Enumerate the intermediate invocations from the start, exit and Stopping journal entries.
- **Y3:** the selfheal record carries the `try-restart` exit status, or the causality claim is softened.
- **Delivery inside bwrap:** add a `loopback_https_receiver` delivery test under real bwrap, covering DNS and CA.
- **Hashing:** pin both stage closure hashes; `producer_code_sha` is pinned per stage.
- **Dedup:** dedupe `integrity_demand_invalid` on `verdict_id`.
