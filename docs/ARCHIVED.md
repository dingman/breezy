# Breezy — ARCHIVED 2026-11-05

**Status:** project shut down by operator decision on 2026-11-05. No strategy family ever recorded
positive expectancy after venue fees — see `docs/evidence/EDGE_SCREEN_GAP1_VS_ASK_2026-11-06.md` and
the Standing verdicts in `docs/core/PROGRESS.md`.

## Backup
- 156 local branches + 19 tags pushed to origin `https://github.com/dingman/breezy.git`; all hashes verified.
- Worktree WIP committed as `chore(shutdown): preserve uncommitted work before archival`.

## Runtime shutdown (2026-11-05 03:09–03:15Z)
- Trade node DISPOSED gracefully (11 s).
- 0 open orders account-wide (offline exec-state + venue `GET /v1/orders/open`).
- Quote tape preflight rc=0 (instance `6609bc2a-…`, 1,365,330 rows, 0 truncated).
- 32 timers + all services stopped; 35 units disabled (`systemctl --user disable`, see
  `~/breezy-archive-2026-11-05/disable-list.txt`). The units were *linked* units, so disabling removed
  their symlinks from `~/.config/systemd/user`; the unit files in `deploy/systemd/` are untouched.
- Venue positions untouched (account shared with manual trading).
- Three units were already `failed` before shutdown: asos-refresh, label-outcomes, portfolio-roi.

## Data outside this repo (NOT on GitHub)
| Path | Size | Notes |
|---|---|---|
| `/mnt/storage/breezy/catalog/quote_tape/polymarket_us` | 497G | quote tape — irreplaceable |
| `/mnt/storage/breezy/us_source_archive` | 8.9G | live LAMP/PFM/METAR captures — partly irreplaceable |
| `/mnt/storage/breezy/logs-archive` | 11G | archived logs |
| `/mnt/storage/breezy/kalshi_depth` | 552M | Kalshi depth captures — irreplaceable |
| `~/.local/share/breezy` | 8.1G | state sqlite, settlement truth, derived ROI/PRIVATE_*, logs (4.4G) |
| `~/.config/breezy` | 40K | **CREDENTIALS** (`polymarket_us_secret.key`, `*.env`) — never commit |
| `~/breezy-archive-2026-11-05/private` | <1M | arm-b2 live-run evidence, shutdown probe (mode 700) |
| `~/.claude/projects/-home-jon-breezy` | 1.6G | Claude memory + transcripts |
| `~/.cache/breezy*` | ~750M | disposable |

## Deletion checklist (operator runs; each step irreversible)
1. Decide keep/delete for the 497G tape and the other irreplaceable data above. If keeping, leave
   `/mnt/storage/breezy` alone.
2. Revoke/rotate the Polymarket.us API key, then `rm -rf ~/.config/breezy`.
3. `cd ~ && git -C /home/jon/breezy worktree list`, then `rm -rf /home/jon/breezy-arm-b2` (its `.git`
   metadata lives in `breezy/.git`) and `rm -rf /home/jon/breezy`.
4. Remove the unit symlinks that point into the repo (42 remained after disable; dangling once the repo
   is gone): `find ~/.config/systemd/user -maxdepth 2 -xtype l -lname '/home/jon/breezy/*' -print -delete`
   then `systemctl --user daemon-reload`. Also remove the drop-in dirs `breezy-quote-tape.service.d`,
   `breezy-quote-tape-ingest.service.d`, `breezy-trade-supervisor.service.d`, `breezy.slice.d`
   (and any remaining `breezy-*.d` / `us-source-collector@*.d`).
5. Optionally delete `~/.local/share/breezy`, `~/.cache/breezy*`, `~/.claude/plugins/data/*/state/breezy*`,
   `/tmp/claude-1000/-home-jon-breezy`.
6. On GitHub: Settings → Archive this repository (read-only) rather than delete, so the evidence survives.

## Dormant (2026-11-10, operator: "Pause all activity. Disable Breezy entirely. No auto-restart.")
- Verified before acting: no breezy timers, units or processes running; no Claude session crons or wakeups.
- Removed the 30 remaining *linked* unit symlinks from `~/.config/systemd/user` (list:
  `~/breezy-archive-2026-11-05/dormant-2026-11-10-removed-links.txt`) and ran `daemon-reload`; `list-unit-files`
  now shows no breezy entry, so nothing can start at login/boot or by name. Unit files in `deploy/systemd/` untouched.
- Drop-in dirs (`breezy-quote-tape*.service.d`, `breezy-replay-daily.service.d`, `breezy-trade-supervisor.service.d`,
  `breezy.slice.d`) left in place; inert without their units (deletion step 4 still covers them).
- User `Linger=yes` left as is (serves the operator's other user services).
- Nothing in this project may be started, enabled, scheduled or resumed without a new operator instruction.

## To resurrect
1. Clone the repo and `uv sync` per `README.md`.
2. Restore `~/.config/breezy` from a secure copy.
3. Re-enable the units from `deploy/systemd/` (linked units take the absolute path):
   `systemctl --user enable /home/jon/breezy/deploy/systemd/<unit>` for each entry in
   `~/breezy-archive-2026-11-05/disable-list.txt` and `dormant-2026-11-10-removed-links.txt`, then `systemctl --user daemon-reload`.

## Tests and CI removed 2026-11-05 (operator order)
The full suite and GitHub workflows exist in history up to commit 0142adec1b8ea1ab3fd550d13e49e3b1c0ca22dd; `.github/workflows/` was dropped earlier on this branch (b8fba517) and remained only on `main`; `scripts/ci/` (local gate runners) is removed here too. Restore with `git checkout 0142adec1b8ea1ab3fd550d13e49e3b1c0ca22dd -- tests scripts/ci` and `git checkout 0ab94f234e574a2b0b39c05bc79107773c86d0cb -- .github`.
