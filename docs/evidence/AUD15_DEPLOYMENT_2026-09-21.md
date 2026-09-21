# AUD-15 deployment record — 2026-09-21

Commits: `225e2fe` (emit_alert URL-leak fix), `4258261` (AUD-15 as amended).
Deployed 2026-09-21 ~17:57–18:05Z by the coordinator session. Nothing was started, stopped or
restarted on the live path: `breezy-trade-supervisor.service` (active since 2026-09-20 15:26:18Z)
and `breezy-quote-tape.service` (active since 2026-09-21 09:00:38Z) kept the same
`ActiveEnterTimestamp` and `MainPID` before and after (diff = identical).

Deployed inside the protected window `[16:35Z, 01:15Z)` deliberately: that rule governs HEAVY
studies starting beside the node; this deploy starts nothing heavy (`daemon-reload` starts nothing,
the refresh unit is in the light band with the documented light-job exemption), and waiting risked
the 13:30Z deadline — the retired wrapper was the only thing running the `--since` ASOS refresh.

## Was the ASOS refresh failing before the fix? No.
Journal, both wrappers, every day 2026-09-14 → 09-21 including the timeout nights:
`asos refresh ok` (13:30Z in `breezy-mb-daily`, 02:06Z in `breezy-offer-gate-daily`). The refresh
ran first and succeeded; the studies after it hit `TimeoutStartSec`. The exposure was forward-looking:
retiring `breezy-mb-daily` without the same-commit re-home would have starved the 15:00Z consumer.

## Steps and results
1. `migrate-alerts-env.sh` (base mode): `~/.config/breezy/alerts.env` created, mode 600, exactly one
   key line; `breezy-trade.env` unchanged. No value printed at any step.
2. Delivery check under the unit's own environment —
   `systemd-run --user --wait --pipe -p EnvironmentFile=-$HOME/.config/breezy/alerts.env
   .venv/bin/breezy-check-alerts --severity INFO` → `delivered`, exit 0.
3. Installed supervisor unit is a COPY on this host (not a symlink): backed up to
   `breezy-trade-supervisor.service.bak-<ts>`, replaced with the repo text (13 added lines, the
   `EnvironmentFile=-%h/.config/breezy/alerts.env` stanza). Effective at the supervisor's next
   unforced restart; `systemctl --user cat` shows the line.
4. New units symlinked (`breezy-asos-refresh.service/.timer`, `breezy-study-failed@.service`);
   retired timers disabled, four dangling symlinks removed, `daemon-reload`, `reset-failed` on the
   retired services AND timers → no `mb-daily` / `offer-gate` row remains in `list-units --all` or
   `list-timers --all`. `systemd-analyze --user verify` silent.
5. `breezy-asos-refresh.timer` enabled: next fire `2026-09-22 13:30:00 UTC`; no catch-up fire on enable.
6. End-to-end `OnFailure=` proof: a transient unit running `/bin/false`, wired to the real template,
   started `breezy-study-failed@…`, which logged `event=study_unit_failed severity=WARN
   detail=study_unit_reached_failed_state`, exited 0, and logged no "NO alert egress" warning.
7. `migrate-alerts-env.sh --finalize --delivery-confirmed`: key removed from `breezy-trade.env`
   (backup kept, mode 600); `alerts.env` is now the single source. Delivery re-checked → exit 0.

## Still to observe (first scheduled fire, 2026-09-22)
- 13:30Z journal for `breezy-asos-refresh`: `asos refresh ok` + `asos cache freshness check ok`.
- 15:00Z `breezy-position-monitor-report` and 15:20Z `breezy-exit-window-study`: no cache miss.
- At the supervisor's next unforced restart: `log_alert_egress_status` shows egress configured.

## Not part of this item
`breezy-family-tally@pm_us_crh_cont.service` (failed) and the orphaned
`breezy-pm-crh-{cont,v2}-tally.{service,timer}` rows pre-date this work (G-04 / AUD-05). They are
now covered by the `OnFailure=` notifier but were not otherwise touched.
