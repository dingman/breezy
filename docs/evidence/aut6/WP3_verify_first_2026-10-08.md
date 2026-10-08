# AUT-6 WP3 verify-first, S1 slice (2026-10-08)

Read-only `systemctl --user` / `journalctl --user` only. Nothing was reset, started or stopped.

## Failed-unit census (`systemctl --user list-units --failed --all --plain --no-legend`, ~20:50Z)

One unit: `breezy-autonomy-alert-redeliver.service` (failed, exit-code). The transients named in plan
§3.8 (`fq-halt-20261005`, `breezy-parity-mem-1d/7d`, `run-p814078-i21773018`,
`breezy-replay-backfill-0929`) are `LoadState=not-found` now: they were reset before this slice
started, so their `InvocationID` can no longer be read. `breezy-portfolio-roi` and
`breezy-fee-evidence-pull` are `inactive/Result=success` with `ExecMainStatus=1` retained (reset
after their failure). `breezy-discovery-pull` last run 20:09:50Z finished (WP3b).

## F2: is `InvocationID` non-empty on a failed unit?

`systemctl --user show -p InvocationID,Result,InactiveEnterTimestamp breezy-autonomy-alert-redeliver.service`:

```
InactiveEnterTimestamp=Thu 2026-10-08 20:10:58 UTC
InvocationID=8aa93b559c3846f087ca594a7b0985b3
Result=exit-code
```

Result: **PASS** (non-empty). Cross-check: the journal entries of that run carry
`USER_INVOCATION_ID=8aa93b559c3846f087ca594a7b0985b3` and `USER_UNIT=breezy-autonomy-alert-redeliver.service`
(`journalctl --user -o json`), so the property joins to the journal on `USER_INVOCATION_ID`
(the journal field is `USER_INVOCATION_ID`, not `_SYSTEMD_INVOCATION_ID`/`INVOCATION_ID`, for user
units logged by the manager).

Deviation from the brief: only ONE failed unit remained, so the planned second sample (a failed transient) is
unobtainable. The transients were gone before this verify-first ran. The plan fallback
(unit, InactiveEnterTimestamp) is therefore not exercised; it stays in the design for the
case of an empty id.
Not a STOP.
