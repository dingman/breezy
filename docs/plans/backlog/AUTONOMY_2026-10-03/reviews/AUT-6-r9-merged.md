# AUT-6 r9 merged review (coordinator)

TBA scored 95 (READY); SFH scored 93. The final score is 93, so the plan goes to r10. Neither review has a CRITICAL or HIGH finding.

## MEDIUM
- **AC1 [TBA M]: temp file under `registry/demand/`.** Write demand files with `O_TMPFILE`, then `os.link("/proc/self/fd/N", final)` within the same bind. Do not use `mkstemp`. This leaves no visible temp name, so a SIGKILL cannot leave an orphan that vetoes the venue. If `O_TMPFILE` is unsupported, the C5 listing must ignore a pinned dot-prefixed temp pattern, and a sweep must remove the orphans. Test both paths.
- **AC2 [both reviewers, SFH AB1 / TBA L]: report every evaluate failure.** Emit `evaluate_stage_failed`, `evaluate_stage_timeout` or `evaluate_stage_unrecorded` whenever `evaluate_exit` is non-zero or unrecorded, independent of the demand row. Add a parametrised test.
- **AC3 [SFH AB2]: deadline outcome.** When `DEMAND_STAGE_DEADLINE_S` is hit, the summary line gets `deadline_hit=1` and `unprocessed=<n>`, the stage exits non-zero, and a CRITICAL is raised. Assert `EVALUATE_STAGE_DEADLINE_S < EVALUATE_STAGE_BUDGET_S` and `DEMAND_STAGE_DEADLINE_S < DEMAND_STAGE_BUDGET_S`.
- **AC4 [SFH AB3]: missing venue directory.** If `registry/demand/<venue>/` is missing (ENOENT), the writer creates it inside the bind with `mkdir`. The listing treats a missing directory as "no files" only when the parent `registry/demand/` exists and is readable. Any other error is a CRITICAL. Add a test.
- **AC5 [SFH AB4]: deleted mode file.** A missing `_self_heal_mode.json` counts as UNKNOWN and degraded, raising `self_heal_mode_state_lost`, whenever there is evidence the host was past AUT-5b: any selfheal record, `armed.json`, or an enabled probe timer. Add a test.
- **AC6 [SFH AB5]: AST check uses an allowlist (coordinator ruling).** Replace the forbidden-construct denylist with an **allowlist**:
  - In a non-writer closure, the only permitted I/O calls are named read-only functions: `open` with literal mode `"r"`/`"rb"`, `os.open` with literal `O_RDONLY`, sqlite with `mode=ro`, `os.stat`/`os.scandir`/`os.listdir`, and the shared read helpers.
  - Any other call to a builtin, `os`, `io`, `pathlib` write method, `shutil`, `subprocess`, `multiprocessing` or `asyncio` subprocess/exec function fails the test.
  - Writers are limited to their table rows, with path constants.
  - This stops the growing denylist. Apply the same rule in AUT-6's closures; AUT-1 and AUT-5 adopt it as a build item.

## LOW
- **AB6:** #22 reads the last `98e32220` exit entry by timestamp. Add a test.
- **AB7:** dedupe `bwrap_unavailable` and `demand_stage_timeout`, with a 24 h re-page.
- **AB8:** add a cause hint that tells an import crash apart from a bwrap launch failure.
- **AB9:** add a negative self-probe on `registry/` outside `demand/`, which must return EROFS.
- **AB10:** add a real-bwrap journal test that proves the stage's stdout carries `_SYSTEMD_INVOCATION_ID` under `--unshare-pid`. If it does not, the stage writes its summary to the stage-status file instead.
