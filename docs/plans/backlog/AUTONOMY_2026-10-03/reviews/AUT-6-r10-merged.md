# AUT-6 r10, merged review (coordinator)

Scores: TBA 93 (one HIGH), SFH 94. The final score is 93, so the plan goes to r11.

## AE1 [both reviewers, HIGH and MEDIUM]: AST allowlist completeness
Superseded by ARCH errata **E-7a**: every AUT-6 unit runs under the shared bwrap wrapper and table, and the AST test becomes a lint.
- Consume E-7a in full:
  - the table rows for every AUT-6 unit;
  - `aut6.health` and the evaluate stage drop `--unshare-pid`, and the table names that exception;
  - every `OnFailure` target is wrapped, with the notifier fallback.
- The AST lint keeps its non-vacuity floor (M2) and its positive controls. The full-resolution allowlist is no longer a READY criterion. Record this in §R11.

## AE2 [TBA, MEDIUM]: drop the O_TMPFILE fallback
Primary data root: ext4 is verified. With the fallback gone:
- `EOPNOTSUPP`, `EINVAL` or `EISDIR` result in INTEGRITY plus a CRITICAL;
- remove `DEMAND_TMP_PATTERN` and the sweep;
- WP verify-first repeats the ext4 O_TMPFILE check on the production tree.

This removes the change to C5 behaviour.

## AE3 [SFH M3]: self-probe write paths
The self-probe's negative and positive paths come from the E-7a table, so the probe has its own table row with constant paths.

## AE4 [SFH M4]: evaluate rule judges only ended invocations
An invocation counts as ended when one of these holds:
- an exit entry exists;
- the last entry is older than the summed stage bounds;
- the unit is not `activating`.

Add a test that the overlapping health pass does not page.

## AE5 [SFH, WAL]: WAL reads under bwrap
Every WAL-db read in a wrapped AUT-6 unit uses the E-7a Rule 3 snapshot helper.

## Low-severity items
- **SFH L1:** select the exit entry by the `COMMAND=` stage argument.
- **SFH L2:** set `last_paged_ns` only when `delivered=true`.
- **SFH L3:** define recovery from `state_lost` for a pre-AUT-5b host. A corrupt mode file means UNKNOWN plus a finding.
- **SFH L4:** dedupe `demand_stage_deadline_hit` with a 24 h re-page.
- **SFH L6:** allow `O_RDONLY|O_CLOEXEC` and bare `open(path)`, which is read mode.
- **TBA:**
  - AB6 test becomes defensive wording.
  - Add one real-journal test.
  - Add a retention or prune rule for `stage_status/`.
  - `breezy-discovery-pull` gets a `TimeoutStopSec` row in the E-9 test.
