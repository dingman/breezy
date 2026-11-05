# AUT-1 r10 — merged blind review (2026-10-03)

| Reviewer | Score | Verdict |
|---|---|---|
| trading-bot-architect | 93 | NOT READY (2 MED) |
| silent-failure-hunter | 88 | NOT READY (1 HIGH) |

The architect confirms that all three r9 HIGHs are closed:

- the pinger runs first in `_connect`;
- option B has no `"*"` subscription;
- `ForecastPoint` writes a regular `custom_` table;
- the subscribe-before-poll ordering holds.

Rulings held by both reviewers:

- The stop hook stays, as evidence only.
- `EXTEND_TIMEOUT_USEC` is native and correct.
- Rotate `TimeoutStartSec=4500` is sane. The only dependent is `OnSuccess=station-candidate-register`.
- Leg W is sound.
- EM2 (the per-tick try/except and done-callback) is sound.

## Owed in r11

- **GH1 [HIGH, SFH]: inconsistent rotate bound.** The file table at about line 248 says 4200, while §3.10.2, R5 and §3.13 say 4500. The rule is 120+12+4200+30 = 4362, so 4500 is correct. Fix line 248, and derive every number from one constant. `test_rotate_bound_covers_recorder_stop_and_max_start` asserts against that constant.
- **GM1 [SFH]: hung discovery attempt.** Add `discovery_attempt_inflight_since_ns` to `RecorderSample`. An attempt in flight longer than a request budget (about 180 s; derive and state it) classifies non-OK and stops the extension. The retry sleep itself stays OK.
- **GM2 [SFH]: per-write loss detection.**
  - The wrapper compares `get_current_file_info()[table]["size"]` before and after each `write`. The writer updates sizes only on success (`writer.py:276`).
  - An unchanged size means a silent drop. Count it, and set `health.ok=False`.
  - A changed size, including a rotation reset, counts as success.
  - On the Take path, a drop means `flush_for_submit` returns False and the Take is refused. This is fail-closed capture; check it against the plan's live-proof rules.
  - `table_bytes()` sums all of a table's files, so the 00:00Z rotation does not register as flat.
  - Amend ER-7 to add "and per-write size delta".
- **GM3 [SFH]: stop-hook blind window.** State explicitly that a failed hook, or one killed by `timeout -k`, leaves no stall record until the next day's leg W. Where feasible, the node's `recorder_stale` check also counts recorder invocation changes it can observe locally, for example a recorder-written boot marker. Never use systemctl from the node.
- **GM4 [TBA]: activating tolerance.** Add the WP3 contract test `test_aut6_unit_health_tolerates_activating_within_start_budget`, citing AUT-6 r15-final build item 7. That item was added today and requires AUT-6 to treat `activating/start` as healthy until `TimeoutStartSec`.
- **GM5 [TBA]: rotate's `OnSuccess` timing.** Add a WP0 check that `breezy-station-candidate-register` has no deadline inside 09:00–10:15Z. Read its unit and timer now, and cite them.
- **GL1:**
  - `test_classifier_timing_constants_equal_unit_file` also runs in step 1, against the pending unit text.
  - Define whether `written_by_type` includes the heartbeat being written.
  - Hold a strong reference to the pinger task, and make `_connect` idempotent against a second pinger.
- **ER-9 AMEND.** Replace the stale final clause with: "…recorder and feed stall observations (the recorder's process-level heal is systemd's own watchdog, per §4.6 as amended by E-11; AUT-6 pages and does not restart)".

## Errata

| Item | Verdict |
|---|---|
| ER-1–ER-6 | ADOPT / AMEND-applied |
| ER-7 | AMEND: per-write size delta |
| ER-8 | REDUCED; adopt |
| ER-9 | AMEND: text above |
| ER-10 | ADOPT |

## Approval bar

Both reviewers ≥95 and zero CRIT/HIGH.
