# G-14 — reboot-durable supervision for the quote tape and the K1 study

**Status: PREPARED, NOT ACTIVATED.** Nothing in this directory is installed,
enabled, or running. The cutover in §3 is run by the coordinator, with eyes on
it, because it briefly stops the one data stream Breezy cannot re-acquire.

## 1. What this replaces, and why it is urgent

Capture is currently supervised by three PPID-1 orphaned `bash` loops living in
a **session scratchpad under `/tmp`**:

| Process | Script | Cadence | Self-exit |
|---|---|---|---|
| capture supervisor (H3) | `tape_supervisor.sh` | 30 s | 2026-09-02T14:00Z |
| capture supervisor (K1) | `tape_supervisor_k1.sh` | 60 s | 2026-10-01T00:00Z |
| K1 daily driver | `k1_daily.sh` | `sleep 86400` | 2026-10-01T12:00Z |

All three are `/tmp/claude-1000/-home-jon-breezy/cf107d94-6203-4ff5-a844-294812f915b0/scratchpad/*.sh`.

Three failure modes follow, none of them hypothetical:

1. **No unit ⇒ no reboot survival.** Nothing restarts any of these after a
   reboot. The recorder itself is likewise unsupervised by systemd.
2. **`/tmp` reaping deletes the supervisors themselves.** The restart mechanism
   is stored in a directory the system is entitled to clear.
3. **The recorder lives in a tmux cgroup, not its own.** Measured:
   `/proc/<pid>/cgroup` = `…/user@1000.service/tmux-spawn-d3dce6d4-….scope`.
   Tearing down that tmux scope kills the recorder as collateral. Under
   `breezy-quote-tape.service` it gets its own cgroup and that coupling is gone.

Polymarket.us price history is **forward-only**. An hour not recorded is an
hour that is gone. That is the entire justification for the care in §3.

## 2. Install (safe — changes no running process)

```bash
# Symlink, so edits in the repo are the deployed truth and `git` is the audit log.
ln -s /home/jon/breezy/deploy/systemd/breezy-quote-tape.service ~/.config/systemd/user/
ln -s /home/jon/breezy/deploy/systemd/breezy-k1-daily.service   ~/.config/systemd/user/
ln -s /home/jon/breezy/deploy/systemd/breezy-k1-daily.timer     ~/.config/systemd/user/

systemctl --user daemon-reload
systemd-analyze --user verify ~/.config/systemd/user/breezy-quote-tape.service \
                              ~/.config/systemd/user/breezy-k1-daily.service \
                              ~/.config/systemd/user/breezy-k1-daily.timer
```

`daemon-reload` starts nothing. `verify` prints **nothing** when the units are
clean — treat any output as a failure, because `systemd-analyze verify` returns
exit 0 even for a directive it could not parse (measured; see §7).

Lingering is already enabled — `loginctl show-user jon -p Linger` → `Linger=yes`
— so user units survive logout and start at boot without further action. This
mirrors `breezy-nws-ingest.service`, which is the only other Breezy unit and the
convention source for `EnvironmentFile`, `WorkingDirectory`, `UMask=0077`,
`Restart=always`, and journald logging.

## 3. Cutover — ORDERED. Do not reorder steps 1–4.

The supervisors are the *restarters*. Signalling the recorder before they are
gone just makes them start a second one 30 s later. Their PIDs have changed
since this was written; re-find them.

```bash
# 0. Snapshot the "before" so the rollback in §5 has a target.
pgrep -af "[t]ape_supervisor.sh"; pgrep -af "[t]ape_supervisor_k1.sh"; pgrep -af "[k]1_daily.sh"
REC=$(pgrep -x -f "/home/jon/breezy/.venv/bin/python3 /home/jon/breezy/.venv/bin/breezy-quote-tape")
INST=$(basename "$(ls -1dt /home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us/live/*/ | head -1)")
echo "recorder=$REC instance=$INST"
```

1. **Stop BOTH supervisor loops first** (and the K1 driver). Plain SIGTERM;
   these are `bash` loops with no cleanup to do. Zero capture is lost here —
   the recorder is a separate session (PPID 1, its own PGID/SID) and was
   `nohup`'d, so nothing here can reach it.
   ```bash
   kill $(pgrep -f "[t]ape_supervisor.sh") $(pgrep -f "[t]ape_supervisor_k1.sh") $(pgrep -f "[k]1_daily.sh")
   sleep 2
   pgrep -af "[t]ape_supervisor"; pgrep -af "[k]1_daily.sh"   # must print NOTHING
   ```

2. **Send the recorder its clean-shutdown signal and WAIT for it to exit.**
   `SIGTERM` — never `SIGKILL`. `NautilusKernel._setup_loop` registers
   SIGTERM/SIGINT/SIGABRT (`nautilus_trader/system/kernel.py:558-572`), and only
   a clean stop runs `StreamingFeatherWriter.close()`, which writes the Arrow
   end-of-stream marker. A SIGKILL leaves a mid-message tail and the native read
   path then returns **zero rows in silence** — pinned by
   `tests/contract/test_quote_tape_unclean_shutdown.py:166-187`.
   ```bash
   kill -TERM "$REC"
   while kill -0 "$REC" 2>/dev/null; do sleep 2; done; echo "recorder exited"
   ```
   Typically seconds. If it is still alive after ~120 s, do **not** escalate to
   `-9`; investigate — SIGKILL is the failure mode, not the remedy.

3. **Verify the last feather closed cleanly.** This is the exact check:
   ```bash
   # NOTE: `breezy-quote-tape-preflight` IS declared in pyproject.toml
   # [project.scripts] but is NOT installed in .venv/bin (the venv predates
   # that entry). Invoke it as a MODULE -- verified working 2026-09-02:
   /home/jon/breezy/.venv/bin/python -m breezy.runtime.quote_tape_preflight_cli \
     --instance-id "$INST" -q \
     --catalog /home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us
   # Use --instance-id, NOT --latest: after the unit is started `--latest`
   # resolves to the NEW live session, whose open files always look truncated
   # (the tool says so itself). You want the OLD instance you just closed.
   echo "preflight exit=$?"
   ```
   Exit contract (`src/breezy/runtime/quote_tape_preflight_cli.py:16-30`):
   **0 = intact, safe to interpret** (proceed) · 1 = zero rows captured ·
   2 = usage error · **3 = TRUNCATION DETECTED — stop and escalate.**
   Spot check if you want the raw evidence: a cleanly closed tape ends with the
   8 bytes `ff ff ff ff 00 00 00 00`
   (`tests/contract/test_quote_tape_unclean_shutdown.py:232-235`):
   ```bash
   tail -c8 "$(find /home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us/live/$INST/quote_tick \
     -name '*.feather' -printf '%T@ %p\n' | sort -n | tail -1 | cut -d' ' -f2)" | xxd
   ```

4. **Start the unit.**
   ```bash
   systemctl --user enable --now breezy-quote-tape.service
   systemctl --user status breezy-quote-tape.service --no-pager
   ```

5. **Verify a NEW `live/<instance_id>` directory appears and grows.** Each run
   gets its own directory, so a new one appearing IS the proof the new process
   is writing. Measured across five prior sessions, the first `quote_tick`
   feather appears **0–1 s** after process start.
   ```bash
   NEW=$(basename "$(ls -1dt /home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us/live/*/ | head -1)")
   test "$NEW" != "$INST" && echo "NEW SESSION: $NEW" || echo "!! still the old instance — investigate"
   du -sh /home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us/live/$NEW; sleep 60
   du -sh /home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us/live/$NEW   # must be larger
   journalctl --user -u breezy-quote-tape -n 40 --no-pager
   ```

6. **Confirm the environment survived `EnvironmentFile` parsing.** Two values in
   `polymarket.env` are shell-quoted (`POLYMARKET_US_MARKET_SLUGS=""`,
   `POLYMARKET_US_USER_AGENT='breezy/1.0 (+mailto:…)'`). systemd strips such
   quotes, but that was **not** provable without starting the unit, so check it
   here — a literal `'` in the user agent would be sent to the venue:
   ```bash
   MP=$(systemctl --user show -p MainPID --value breezy-quote-tape.service)
   tr '\0' '\n' < /proc/$MP/environ | grep -E 'POLYMARKET_US_(USER_AGENT|MARKET_SLUGS)|QUOTE_TAPE_CATALOG'
   ```
   Expect `POLYMARKET_US_USER_AGENT=breezy/1.0 (+mailto:weather-breezy@jonathan.vc)`
   with **no** surrounding quotes.

7. **Only then, enable the timer.**
   ```bash
   systemctl --user enable --now breezy-k1-daily.timer
   systemctl --user list-timers breezy-k1-daily.timer --no-pager   # next run 01:35Z (MOVED 2026-09-12, was 22:30Z)
   ```
   `--now` starts the *timer*, not the service. To prove the study runs without
   waiting for 01:35Z (MOVED 2026-09-12, was 22:30Z): `systemctl --user start
   breezy-k1-daily.service` and read `~/.local/share/breezy/k1/k1_daily.log`.

### Expected capture gap

| Phase | Seconds |
|---|---|
| Stop supervisors (step 1) — recorder untouched | 0 |
| SIGTERM → graceful exit (step 2) | 5–30 typical |
| Preflight verification (step 3) | 30–60 |
| `enable --now` → process up (step 4) | 1–2 |
| Process up → first quote written (measured, n=5) | 0–1 |
| **Total, canonical order** | **≈ 40–90 s** |

Hard ceiling **≈ 180 s** if the graceful stop runs the full `TimeoutStopSec=120`
— at which point systemd escalates to SIGKILL and the *current day's* feather is
endangered, so a stop that slow is an abort condition, not a wait.

*Optional gap-minimising variant:* steps 3 and 4 may be swapped. Preflight is
read-only and inspects the **old** `instance_id`, which the new process never
touches (separate `live/<uuid>/` directory), so verifying after the unit is up is
safe and cuts the gap to **≈ 10–35 s**. Take this variant if the market is
active; take the canonical order if you want the old tape blessed before
anything else moves.

## 4. Two things that will bite you

- **`pgrep -f "bin/breezy-quote-tape"` also matches `breezy-quote-tape-preflight`.**
  It is a substring. Both supervisors use exactly this pattern
  (`tape_supervisor.sh:12` and `:25`, `tape_supervisor_k1.sh:22` and `:35`), so a preflight running
  during a recorder outage reads to them as "the recorder is up" and the restart
  is skipped. Use `pgrep -x -f '<full ExecStart line>'` as in §3 step 0.
- **The two supervisors race until 2026-09-02T14:00Z.** They share no lock. If
  the recorder dies in that window, both can fire a restart within their 30 s and
  60 s ticks and produce **two** recorders writing two `live/<instance_id>`
  directories at once. Neither corrupts the other's files, but the tape becomes
  double-booked and per-instance analysis silently double-counts. This alone
  justifies doing the cutover before 14:00Z; after 14:00Z only the K1 supervisor
  remains and the race is gone.

## 5. Rollback

```bash
systemctl --user disable --now breezy-quote-tape.service
systemctl --user disable --now breezy-k1-daily.timer
```

Then relaunch the recorder with the supervisors' verbatim command line
(`tape_supervisor_k1.sh:25-33`):

```bash
(
  set -a
  . /home/jon/.config/breezy/polymarket.env
  export BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG=/home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us
  set +a
  cd /home/jon/breezy
  nohup /home/jon/breezy/.venv/bin/python3 /home/jon/breezy/.venv/bin/breezy-quote-tape \
    >> /tmp/claude-1000/-home-jon-breezy/cf107d94-6203-4ff5-a844-294812f915b0/scratchpad/capture_supervised.log 2>&1 &
)
```

and restart the loops (**copy the scripts out of `/tmp` first** if they have
been reaped — that is the defect being fixed):

```bash
S=/tmp/claude-1000/-home-jon-breezy/cf107d94-6203-4ff5-a844-294812f915b0/scratchpad
nohup "$S/tape_supervisor_k1.sh" >/dev/null 2>&1 &
nohup "$S/k1_daily.sh"           >/dev/null 2>&1 &
```

If `breezy-quote-tape.service` has entered `failed` because of an exit-2
configuration error (`RestartPreventExitStatus=2` refuses to hot-loop that
class), clear it with `systemctl --user reset-failed breezy-quote-tape.service`
after fixing the env, then `start` again. A runtime / market-data fault
(exit 1) must **not** land here any more: that class retries indefinitely
with backoff, and `StartLimitIntervalSec=0` is what makes 09-09's
"Start request repeated too quickly" abandon-permanently outcome impossible.

## 6. Design notes (why these values)

- **`KillSignal=SIGTERM`, `TimeoutStopSec=120`.** SIGTERM is what the clean path
  handles (`kernel.py:558-572`, reached from `:284-287`) and a clean stop is the
  only thing that writes the end-of-stream marker. The writer flushes every 10 s
  (`node_config.py:292`), so the stop must be allowed to flush and close; 120 s
  is deliberate headroom over systemd's 90 s default, because the timeout
  expiring means SIGKILL and SIGKILL means the silent-zero-rows failure.
- **`RestartSec=30` + `RestartSteps=4` + `RestartMaxDelaySec=480`.** The first
  retry stays 30 s (the supervisors' poll this unit replaced), so a blip is
  still recovered at the old latency. Then exponential backoff with ratio 2
  (`(480/30)^(1/4) = 2`): 30s, 60s, 120s, 240s, 480s, 480s, … A multi-hour
  venue outage therefore retries forever at 8 min, not 120 times an hour.
  `RestartSteps` / `RestartMaxDelaySec` landed in systemd 254; this host is
  259 (259.5-0ubuntu3.4), so the directives load.
- **`RestartPreventExitStatus=2` / `StartLimitIntervalSec=0`.** Discriminate
  failure class by exit code, not by attempt count. The recorder's contract
  (`quote_tape_cli.py:52-61, :107-109, :145-174, :270-272`) matches the
  sibling `breezy-trade-supervisor.service`: 0 clean, 1 runtime / FATAL
  market-data fault, 2 configuration/environment. Exit 2 fails closed
  immediately — restarting cannot change the env. Exit 1 retries indefinitely.
  The previous `StartLimitBurst=20` / `StartLimitIntervalSec=3600` *looked*
  like an hour of resilience; at `RestartSec=30` it was 20 × 30s = **600 s of
  wall clock**, and on 2026-09-09 that is exactly what parked capture for
  6.7 hours after a venue websocket drop (status=1/FAILURE at 16:00:17Z,
  "Start request repeated too quickly" at 17:28:05Z, manual `reset-failed` +
  `start` at 00:09Z on 09-10). The NWS unit's 3/300 s is even tighter
  (~15 s at `RestartSec=5`); that is defensible there because NWS climate
  records are re-fetchable. Polymarket.us price history is not. This is the
  one place data-irreplaceability outranks convention-mirroring.
- **`MemoryHigh=2G` / `MemoryMax=3G`** (added 2026-09-04, after the recorder
  was OOM-killed at ~1.1 GB RSS with no per-cgroup ceiling set at all). Sized
  from the measured post-incident steady state, MemoryCurrent ~= 1.10 GB /
  MemoryPeak ~= 1.14 GB after 28 min uptime: `MemoryHigh` clears that with
  ~1.8x headroom so ordinary operation is never throttled, and `MemoryMax`
  stays under a tenth of the 31 GB host so this cgroup's own OOM kill — not
  the host-wide OOM killer choosing among unrelated processes — is what fires
  on a leak. `Restart=always` recovers from that kill like any other exit.
  Pinned by `tests/unit/test_quote_tape_service_memory_ceiling.py`.
- **No `SuccessExitStatus`.** The exit contract must reach `systemctl status`:
  0 clean, **1 fatal market-data fault**, 2 configuration error
  (`quote_tape_cli.py:52-61`, `:145-174`). Commit `79b9b44` exists precisely so a
  dead feed is not reported as success; suppressing exit 1 would undo it.
- **journald, not the `/tmp` log file.** `StandardOutput/Error=journal` +
  `SyslogIdentifier=`, mirroring the NWS unit. Reboot-durable, rotated, queryable
  per-unit. The `/tmp` append-log is part of what G-14 removes.
- **The K1 service holds no credential.** No `EnvironmentFile`. It reads the tape
  and the settlement catalog from absolute defaults
  (`k1_cheap_open_settlement.py:143-146`) and opens no socket — the same role
  separation that keeps the recorder and the NWS collector apart.

## 7. Validation performed (2026-09-02, no unit activated)

```
$ systemd-analyze --user verify deploy/systemd/breezy-quote-tape.service \
    deploy/systemd/breezy-k1-daily.service deploy/systemd/breezy-k1-daily.timer
(no output)
EXIT=0

$ bash -n deploy/systemd/k1-daily-run.sh
OK

$ loginctl show-user jon -p Linger
Linger=yes
```

Positive control — `verify` does emit a diagnostic for a bad directive but still
exits 0, so **empty output**, not the exit status, is the pass signal:

```
$ systemd-analyze --user verify /tmp/…/broken.service      # Restart=alwayz
broken.service:52: Failed to parse Restart=alwayz, ignoring: Invalid argument
EXIT=0
```

systemd 259 (259.5-0ubuntu3.4). Host clock is UTC (`timedatectl`: `Etc/UTC`).

---

## TRAP: editing a symlinked unit does NOT reload it

The units here are symlinked into `~/.config/systemd/user/` so the repo is the
deployed truth. That is the point — and it is also the trap, because systemd
caches the unit it PARSED at load time. Editing the file in the repo changes
what a human reads and NOT what systemd runs, silently, with no warning at the
edit site.

Caught live on 2026-09-02: `breezy-offer-gate-daily.service` gained an
`ExecStartPre=` that refreshes recent ASOS before the scan. On disk it was
there; `systemctl --user show ... -p ExecStartPre` returned EMPTY, and
`NeedDaemonReload` was `yes`. That night's timer would have run the OLD unit,
skipped the refresh, and reported "no observation data" for every station-day —
losing a day of accumulation on a programme whose binding constraint IS
elapsed calendar time, and reporting it as a normal empty result.

**After ANY edit to a file in this directory:**

```bash
systemctl --user daemon-reload
systemctl --user show <unit> -p NeedDaemonReload --value   # must print: no
systemctl --user show <unit> -p ExecStart -p ExecStartPre  # must match the file
```

`daemon-reload` re-reads configuration and starts/stops nothing: a running
service keeps its old config until it is restarted, so this is safe to run while
`breezy-quote-tape.service` is recording. Verified — the recorder's MainPID was
identical either side of the reload.

Do not trust the timer's `NEXT` column as evidence the unit is current. It shows
when the timer will fire, never which version of the service it will fire.

## G-14 status — DONE 2026-09-02T04:38Z

- **ACTIVATED AND VERIFIED.** Units symlinked into `~/.config/systemd/user/`,
  `daemon-reload`ed, `systemd-analyze --user verify` silent (= clean).
  `breezy-quote-tape.service` active, `NRestarts=0`; `breezy-k1-daily.timer`
  enabled, next fire 22:30Z (ANNOTATED, MOVED 2026-09-12: true as of this
  2026-09-02 record; `breezy-k1-daily.timer` now fires 01:35Z instead -- see
  "Protected window and serialization" below; this dated observation is
  annotated in place, never rewritten). `Linger=yes`, so both survive reboot
  and logout.
- **Nothing was lost.** The recorder took **28 s** to shut down cleanly on
  SIGTERM (inside the 120 s `TimeoutStopSec`, which is why that value is not
  the default 90). Preflight on the closed pre-cutover instance
  `5a111bca-c349-49d7-94bc-948649485ac8`: **rows=952453 files=297 intact=296
  empty=1 truncated=0 unreadable=0, exit 0.** The three newest feathers each
  end with the Arrow end-of-stream marker `ffffffff00000000`.
- **Measured capture gap ≈ 2 s**, not the 40–90 s this document predicted: the
  old recorder keeps writing throughout its graceful shutdown, so the gap is
  last-write → new-writer-created (04:38:48 → 04:38:50), not TERM → start.
- **The three `/tmp` supervisor loops are stopped and gone.** They belonged to
  a Claude session that had already exited, which is precisely the risk this
  closes: no live owner, and a `/tmp` reap would have deleted the only restart
  mechanism for the one irreplaceable data stream.
- **Resolved, previously undetermined:** systemd DOES strip the shell quotes in
  `EnvironmentFile`. Measured with a transient unit before cutover, then
  confirmed in the running unit: `POLYMARKET_US_USER_AGENT` arrives as
  `breezy/1.0 (+mailto:...)` with no literal quotes, `MARKET_SLUGS` empty.
- **Deliberate divergence from `breezy-nws-ingest.service`:** originally
  `StartLimitBurst=20`/`StartLimitIntervalSec=3600` instead of 3/300 s.
  **Superseded 2026-09-10 after the 09-09 capture loss:** that 20/hour
  window was only ~10 minutes of wall clock at `RestartSec=30` and
  permanently abandoned the tape. Current policy is
  `RestartPreventExitStatus=2` + `StartLimitIntervalSec=0` + backoff
  (`RestartSteps=4`/`RestartMaxDelaySec=480`); see §6.
- **Carried forward as a real defect (not a cutover concern):** the retired
  supervisors polled `pgrep -f "bin/breezy-quote-tape"`, which also matches
  `breezy-quote-tape-preflight` — a preflight running during an outage read as
  "recorder is up" and would have SUPPRESSED the restart. Any future
  process-liveness check must use `pgrep -x -f "<full ExecStart>"`.

---

## `breezy-mb-daily` — M_A + M_B tape-side studies (2026-09-02, PREPARED, NOT ACTIVATED)

`breezy-mb-daily.service` + `.timer` run `ma_prelock_winner_ask_study.py`
(M_A) and `mb_current_rung_edge_study.py` (M_B) daily at **13:30 UTC** via a
wrapper script, `deploy/systemd/mb-daily-run.sh`, in the same style as
`k1-daily-run.sh`: the timer owns cadence, the script owns the work. M_A runs
first; M_B runs **unconditionally** afterward — a failed or cache-starved M_A
never skips M_B's own daily sample. The schedule sits after the 12:15 UTC
quote-tape-catalog ingest tick, after every dense station's previous climate
day has closed (latest, SFO/LAX at UTC-8, closes at 08:00 UTC) and its CLI
final has normally posted. It was originally staggered a full hour off
`breezy-k1-daily`/`breezy-offer-gate-daily`.

MOVED 2026-09-12: those two moved from (22:30 UTC) / (22:45 UTC) to `01:35
UTC` / `02:05 UTC` (see "Protected window and serialization" below);
`breezy-mb-daily` stayed at `13:30 UTC` -- see the timer file's own comment
for the full reasoning.

Both studies previously hard-coded `ASOS_FETCH_END` to a literal date with a
comment instructing a human to hand-edit it forward each day
(`ma_prelock_winner_ask_study.py`, imported by `mb_current_rung_edge_study.py`)
— exactly what an unattended daily timer cannot do. `default_asos_fetch_end()`
replaces it with a through-**today** default (not yesterday: a station-day
without a posted CLI final already scores PENDING rather than a false
"zero-qualifying" result, so including today's still-open climate day is
safe). `ASOS_FETCH_START` stays a fixed anchor, so the window only ever
widens — this is the mechanism by which "the tape-side sample accrues" across
runs, not merely "the same report gets rewritten daily."

Both studies are **cache-only** for ASOS: `load_asos_series_for_day` raises
`SystemExit` on a cache miss rather than fetching, keyed on the exact IEM
ASOS URL for `(ASOS_FETCH_START, ASOS_FETCH_END)`
(`settlement_alignment_study.py:cache_path_for_url` hashes the whole URL, so
no partial or nearby-range cache file satisfies it). `asos_recent_refresh.py`
(Item 4's fetcher) previously only supported a `--lookback-days` window
relative to *today*, which can **never** produce that exact URL against a
*fixed* `ASOS_FETCH_START` — its window's start drifts a day further from the
anchor every day the timer fires. `mb-daily-run.sh` therefore calls it with
the new `--since <ASOS_FETCH_START literal>` flag instead
(`lookback_days_since`), which pins the fetch's start to the exact same
anchor and its end to `today` — matching `default_asos_fetch_end()` exactly,
so the refreshed cache entry is the one the studies actually read. The
`--since` literal in `mb-daily-run.sh` duplicates
`ma_prelock_winner_ask_study.ASOS_FETCH_START`; there is no shared import
across the shell/Python boundary, so both must be updated together if that
anchor ever moves — the wrapper script's header says so at the point of use.

Artefacts land under `~/.local/share/breezy/derived/`, dated
(`ma_prelock_winner_ask_<date>.md`, `mb_current_rung_edge_<date>.md`), one
snapshot per day — the unit never writes into `docs/evidence/`; promoting a
snapshot there is a deliberate, reviewed step, same convention as
`breezy-k1-daily` and `breezy-offer-gate-daily`.

Validation performed (no unit activated):

```
$ systemd-analyze --user verify deploy/systemd/breezy-mb-daily.service \
    deploy/systemd/breezy-mb-daily.timer
(no output)
EXIT=0

$ bash -n deploy/systemd/mb-daily-run.sh
OK
```

To activate: symlink both unit files into `~/.config/systemd/user/` (§2's
pattern), `daemon-reload`, then
`systemctl --user enable --now breezy-mb-daily.timer` — deliberately not run
here; see the TRAP section above for the post-edit `daemon-reload` discipline
that applies to any future edit of this unit too.

---

## `breezy-quote-tape-rotate` — daily recorder instance rotation (2026-09-03, PREPARED, NOT ACTIVATED)

Closes a gap `breezy-quote-tape-ingest.timer` cannot close by itself. The
recorder's writer already rotates every calendar day internally
(`node_config.QUOTE_TAPE_ROTATION_MODE = RotationMode.SCHEDULED_DATES`,
1-day interval, pinned by
`tests/contract/test_quote_tape_unclean_shutdown.py::
test_the_recorder_rotates_daily_so_a_kill_can_only_endanger_one_day`), which
closes each day's *file* with its Arrow end-of-stream marker. But the ingest
CLI's live-write-avoidance rule (`quote_tape_ingest_cli.py`'s module
docstring, rule (b)) skips the whole *instance directory* — every
already-marker-closed day inside it included — for as long as it is both the
most-recently-started instance and `breezy-quote-tape.service` reports
active. A new instance directory is opened only on process start, so a
recorder left running for days leaves days of marker-closed, ingest-eligible
data sitting behind that one still-open instance, invisible to the parquet
catalog `breezy-mb-daily` reads. Measured 2026-09-02: instance `dbb0354a…`
had been live since 10:56Z with no calendar-driven path to close it.

`breezy-quote-tape-rotate.service` + `.timer` run
`systemctl --user try-restart breezy-quote-tape.service` daily at
**09:00 UTC**: after every station's 08:00 UTC settlement and before
Polymarket.us's ~09:45 UTC listing of the next cohort — the one window where
the recorder has nothing time-sensitive to capture, so the ~2 s rotation gap
measured at the original G-14 cutover (see that section above) costs
nothing. `try-restart`, not `restart`: if an operator has deliberately
stopped the recorder, this timer must never be what silently brings it back
up — `try-restart` is a no-op against an inactive unit, `restart` would start
it unconditionally. Full daily sequence and why each stagger exists:
**rotate 09:00 UTC → ingest 12:15 UTC → mb-daily 13:30 UTC**. The
09:00→12:15 gap is deliberate, not incidental: it clears the ingest CLI's
30-minute live-write grace window (`DEFAULT_LIVE_GRACE_MINUTES`) by over two
hours, so 12:15's pass is guaranteed to see the rotated-off instance as
genuinely quiet and convert it, landing it in the catalog before
`breezy-mb-daily` reads at 13:30.

A daily `try-restart` does not interact badly with the recorder's own
`Restart=always` / `RestartPreventExitStatus=2` / `StartLimitIntervalSec=0`:
systemd counts both automatic and manual restarts against the same start-limit
budget, but that budget is disabled (interval 0), so one scheduled rotate
per day cannot park capture the way the old 20-per-hour ceiling did on
09-09. No further adjustment to `breezy-quote-tape.service` is needed for
the rotate unit.

Validation performed (no unit activated):

```
$ systemd-analyze --user verify deploy/systemd/breezy-quote-tape-rotate.service \
    deploy/systemd/breezy-quote-tape-rotate.timer
(no output)
EXIT=0
```

To activate: symlink both unit files into `~/.config/systemd/user/` (§2's
pattern), `daemon-reload`, then
`systemctl --user enable --now breezy-quote-tape-rotate.timer` — deliberately
not run here; see the TRAP section above for the post-edit `daemon-reload`
discipline that applies to any future edit of this unit too.

---

## `breezy-live-tally` — 6d nightly live-family tally (2026-09-04, PREPARED, NOT ACTIVATED)

`breezy-live-tally.service` + `.timer` run `scripts/analysis/
live_family_tally.py` daily at **14:30 UTC** via a wrapper script,
`deploy/systemd/live-tally-run.sh`, in the same style as `mb-daily-run.sh`:
the timer owns cadence, the script owns the work. The script reads the 6c
scored-trial parquet store (`~/.local/share/breezy/derived/scored_trials`,
written by `scripts/analysis/score_live_trials.py`), builds realized-hold-rate
strata (pooled / per-station / per-ask-band) over LIVE trials ONLY —
`live_family_tally.assert_live_only` refuses the whole run if any row's
`trial_id` is not a `current_rung_hold/trial/{station}/{climate_day}` key,
so an archive trial can never be pooled into this tally (a plan decision of
`docs/plans/SCORER_TALLY_BCA_BRIEF_2026-09-04.md` §6d, analogous to L-13 and
L-21 but stated verbatim by neither) — then renders a Markdown report whose
stratum table header is byte-identical to the M_B live section
(`mb_current_rung_edge_study.py`) and appends the 6e BCa bootstrap line via
`breezy.settlement.roi_bound.format_roi_bound`. This unit never prints the
naive normal-approximation interval EXEC_SPINE R-9 refuses by name.

Scheduled a full hour AFTER `breezy-mb-daily` (13:30 UTC) so the tally's read
of the (unrelated) parquet store never races that unit's work, and a
distinct hour from every other Breezy timer (`breezy-quote-tape-rotate`
09:00, `breezy-quote-tape-ingest` 00,06,12,18:15, `breezy-k1-daily` 01:35,
`breezy-offer-gate-daily` 02:05 (MOVED 2026-09-12, was 22:30/22:45)) —
pinned by
`tests/unit/test_deploy_timer_hours.py`, which parses every
`deploy/systemd/*.timer`'s `OnCalendar=` line as text (no `systemd-analyze`
shelling in the test suite; that check stays a manual step, below). No
network: the store is local, and the unit carries no `EnvironmentFile`.

Artefacts land under `~/.local/share/breezy/derived/`, dated
(`live_family_tally_<date>.md`), one snapshot per day — same convention as
`breezy-mb-daily`; the unit never writes into `docs/evidence/`.

Validation performed (no unit activated):

```
$ bash -n deploy/systemd/live-tally-run.sh
OK
```

**Manual step, not a pytest gate (per the brief's review item 9):**
`systemd-analyze --user verify deploy/systemd/breezy-live-tally.service
deploy/systemd/breezy-live-tally.timer` must be re-run once these unit files
are present at their deployed absolute path (`/home/jon/breezy/deploy/
systemd/...`, matching every `ExecStart=`/`Documentation=` line) — verify run
from an agent worktree fails with "not executable: No such file or
directory" purely because the wrapper script does not yet exist at that
absolute host path, the same caveat that applies to any unit authored in a
worktree before it lands on the main checkout.

To activate: symlink both unit files into `~/.config/systemd/user/` (§2's
pattern), `daemon-reload`, then
`systemctl --user enable --now breezy-live-tally.timer` — deliberately not
run here; see the TRAP section above for the post-edit `daemon-reload`
discipline that applies to any future edit of this unit too.

---

## `breezy-score-live-trials` — I3 live-fill scoring run (2026-09-05, ACTIVATED 04:19 UTC)

**Activation record (coordinator, 2026-09-05 04:19 UTC).** Symlinked both units into
`~/.config/systemd/user/`, `daemon-reload` (also picks up `breezy-live-tally.service`'s new
`Environment=` path line), `enable --now breezy-score-live-trials.timer` (next fire 14:15 UTC).
Pre-deploy checks: live store 0 fill rows (read-only), node-env pre-flight `MATCH` against the
running node, full unit suite green through the no-egress gate. Smoke run
(`systemctl --user start breezy-score-live-trials.service`): `Result=success`, exit 0,
`covered_listed_station_days_2026-09-05.json` + `score_live_trials_ok_2026-09-05` written,
`scored 0 trial(s), refused 0 trial(s), excluded 0 fill(s)` for LAX/MDW/MIA/SFO (no fills yet).
Chain evidence: `tests/contract/test_live_fill_scoring_chain_contract.py`; reviews:
`docs/evidence/codex_fill_chain_review_2026-09-05.md`.

`breezy-score-live-trials.service` + `.timer` run the 14:15 UTC increment of
`docs/plans/LIVE_FILL_SCORING_CHAIN_2026-09-05.md` (I3) via
`deploy/systemd/score-live-trials-run.sh`, in the same wrapper-owns-the-work
style as `live-tally-run.sh`. Each run: (1) a node-env pre-flight (`"$PY" -m
breezy.runtime.exec_state_db_path --check`) binding the run to the actual
running `breezy-trade` node's exec state DB, value-free; (2) the
covered-listed-station-days counter (`scripts/analysis/
structural_dead_stop.py`), run exactly ONCE here — `live-tally-run.sh` no
longer runs it, it only reads this run's dated `--output` JSON
(`covered_listed_station_days_<date>.json`); (3) one `scripts/analysis/
score_live_trials.py` invocation per station named in that JSON (today
LAX/MDW/MIA/SFO, the `pm_us_crh_v2` family manifest's census), each
resolving its fill source in-process from `POLYMARKET_US_EXEC_STATE_DB`
(`--fill-source` is never passed). Only after the counter AND every city's
invocation exit 0 does the wrapper write the ONE dated success marker,
`score_live_trials_ok_<date>`, under `~/.local/share/breezy/derived/` — the
SOLE writer of that marker anywhere in this repo. Both `breezy-live-tally`
(14:30 UTC) and `breezy-pm-crh-v2-tally` (17:15 UTC) assert it before
tallying, so neither can run against a partial or unscored store (BLOCK-2).

Scheduled at **14:15 UTC**, free on the existing schedule and strictly
before both tallies it gates — pinned by
`tests/unit/test_deploy_timer_hours.py`. The unit carries one non-secret
`Environment=POLYMARKET_US_EXEC_STATE_DB=...` path literal, byte-identical
to the same line in `breezy-live-tally.service`
(`tests/unit/test_score_live_trials_deploy.py`); no `EnvironmentFile=`, no
venue credential, no enablement value.

Validation performed (no unit activated):

```
$ bash -n deploy/systemd/score-live-trials-run.sh
OK
```

To activate: symlink both unit files into `~/.config/systemd/user/` (§2's
pattern), `daemon-reload`, then
`systemctl --user enable --now breezy-score-live-trials.timer` —
deliberately not run here; see the TRAP section above for the post-edit
`daemon-reload` discipline that applies to any future edit of this unit
too.

---

## `breezy-position-monitor-report` — INC-6 nightly report (2026-09-15)

`breezy-position-monitor-report.service` + `.timer` run the nightly report
increment of `docs/plans/INTRADAY_POSITION_MONITOR_2026-09-15.md` (Sec 4
"Nightly report" / Sec 6 INC-6) via
`deploy/systemd/position-monitor-report-run.sh`, in the same
wrapper-owns-the-work style as `score-live-trials-run.sh` /
`family-tally-v2-run.sh`. Each run invokes
`scripts/analysis/position_monitor_nightly_report.py`, which joins the
intra-day position monitor's own summary store (SHADOW-ONLY -- never
submits, modifies, or cancels an order) against the 14:15 UTC live-fill
scorer's store on `trial_id`, and writes one dated JSON + Markdown report
under `~/.local/share/breezy/derived/`
(`position_monitor_report_<date>.{json,md}`). When an INC-8 corpus summary
(`~/.local/share/breezy/derived/hypothetical_hold_corpus/
hypothetical_hold_corpus_report_*.json`) exists, the wrapper passes the
NEWEST one as `--corpus-summary` so the report's calibration flag reflects
the corpus accumulation rather than the live monitor's own count alone; no
unit writes into that directory yet, so its absence is normal.

The monitor's own summaries directory is never a second, hand-maintained
path: the wrapper derives it the SAME way
`composition.py::build_continuous_rung_hold_strategies` derives it for the
live node -- `monitor_root = catalog_root.parent / "monitor"`,
`summaries_dir = monitor_root / "summaries"` -- from the same quote-tape
catalog root literal (`BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG`) as
`score-live-trials-run.sh`. It reads the same scored-trials store
(`BREEZY_SCORED_TRIALS_DIR`) and writes into the same reports directory
convention (`BREEZY_LIVE_TALLY_OUTPUT_DIR`) as both siblings.

Scheduled at **15:00 UTC** -- free on the existing schedule, strictly after
`breezy-score-live-trials` (14:15 UTC, the run that populates the
scored-trials store this report joins against), and outside the protected
LST-union window -- pinned by `tests/unit/test_deploy_timer_hours.py`. The
unit carries no `Environment=`/`EnvironmentFile=`: it holds no venue
credential and opens no socket, mirroring `breezy-k1-daily.service`'s own
stance.

**Deliberate deviation from the "light-job exemption."** Unlike
`breezy-score-live-trials`/`breezy-live-tally`/`breezy-pm-crh-v2-tally`
(all <=1GB/<=60s, exempted from the studies flock/slice above), this unit
opts INTO `breezy-studies.slice` and the shared host-wide
`breezy-studies.lock` (same skip-not-kill convention as
`k1-daily-run.sh`/`mb-daily-run.sh`/`offer-gate-daily-run.sh`: contention
exits 0, lock-infrastructure failure exits 75) even though it is itself
light (`MemoryHigh=512M`/`MemoryMax=1G`, well under the 12G/16G heavy-study
floor) -- it reads from the same quote-tape-catalog-derived directory tree
the heavy studies write near, so it stays under the shared discipline
rather than being asserted independently exempt.

Validation performed (no unit activated):

```
$ bash -n deploy/systemd/position-monitor-report-run.sh
OK
```

To activate: symlink both unit files into `~/.config/systemd/user/` (§2's
pattern), `daemon-reload`, then
`systemctl --user enable --now breezy-position-monitor-report.timer` --
never `start` the service directly; see the TRAP section above for the
post-edit `daemon-reload` discipline that applies to any future edit of
this unit too.

---

## `breezy-exit-window-study` — nightly exit-window study (2026-09-16, PREPARED, NOT ACTIVATED)

`breezy-exit-window-study.service` + `.timer` run the nightly offline "exit
window" study (`docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md`) via
`deploy/systemd/exit-window-study-run.sh`, in the same wrapper-owns-the-work
style as `position-monitor-report-run.sh`. Each run invokes
`scripts/analysis/current_rung_hold_exit_window_study.py` for the
`pm_us_crh_v2` family's four stations (`LAX`, `MDW`, `MIA`, `SFO`) since that
family's own `d0_climate_day` (both hardcoded in the wrapper with a citation
comment, the same convention `family-tally-v2-run.sh` uses for its own
`V2_D0_LITERAL` — never a second, independently-derived parse of
`deploy/families/pm_us_crh_v2.json` at run time), with `--obs-source fetch`
(network fetch allowed only on a cache miss) and the CLI's own default
depth-source (auto-select per position), writing one dated JSON + Markdown
report under `~/.local/share/breezy/derived/exit_window_study/<run-stamp>/`
(`<run-stamp>` is `<date>_nightly`).

**Read-only exec-state-store copy, never the live path.** The study script
reads real fills from the live exec `SqliteStateStore`
(`POLYMARKET_US_EXEC_STATE_DB`), but the wrapper never hands the CLI that
live path directly: it first opens the live store `mode=ro` (URI, no flock)
and makes a full snapshot into a private `mktemp` directory via the stdlib
`sqlite3.Connection.backup()` API — safe against a concurrently writing
WAL-mode node, and never a plain `cp` of a possibly-mid-write file — then
passes ONLY that copy's path as `--state-db`. The temp directory is removed
on exit via a `trap`, success or failure. `POLYMARKET_US_EXEC_STATE_DB` is
set with the same byte-identical `Environment=` literal as
`breezy-score-live-trials.service` / `breezy-live-tally.service` /
`breezy-pm-crh-v2-tally.service` (a single non-secret filesystem path, never
a venue credential, so no `EnvironmentFile=` is needed).

Scheduled at **15:20 UTC** — free on the existing schedule, strictly after
`breezy-position-monitor-report` (15:00 UTC), and outside the protected
LST-union window (see "Protected window and serialization" below); pinned
by `tests/unit/test_deploy_timer_hours.py`.

**Deliberate opt-in to the studies discipline.** Like
`breezy-position-monitor-report`, this unit opts INTO `breezy-studies.slice`
and the shared host-wide `breezy-studies.lock` (same skip-not-kill
convention: contention exits 0, lock-infrastructure failure exits 75) even
though its own cap (`MemoryHigh=1G`/`MemoryMax=2G`) is well under the three
heavy studies' `MemoryHigh=12G`/`MemoryMax=16G` floor — it reads from the
same quote-tape-catalog-derived directory tree those studies write near, so
it stays under the shared discipline rather than being asserted
independently exempt.

Validation performed (no unit activated):

```
$ bash -n deploy/systemd/exit-window-study-run.sh
OK
```

To activate: symlink both unit files into `~/.config/systemd/user/` (§2's
pattern), `daemon-reload`, then
`systemctl --user enable --now breezy-exit-window-study.timer` — never
`start` the service directly; see the TRAP section above for the post-edit
`daemon-reload` discipline that applies to any future edit of this unit
too.

---

## `breezy-pm-crh-v2-tally` — PREREG v2 family tally, PM-only (2026-09-04, PREPARED, NOT ACTIVATED)

One concrete unit pair runs `scripts/analysis/family_tally_v2.py` (the CLI
sibling of `live_family_tally.py`, built in a parallel commit) via
`deploy/systemd/family-tally-v2-run.sh`: **`breezy-pm-crh-v2-tally`** at
**17:15 UTC** for family `pm_us_crh_v2` — after supervisor launch (16:50)
and the 17:10 window end, so MATCH can bind the live node's sqlite. No
templated `@.service` unit: the repo has no precedent for one, so this is
a concrete pair per the existing convention.

**I3 (2026-09-05):** the wrapper now asserts `breezy-score-live-trials`'s
(14:15 UTC) dated success marker before invoking the CLI, exiting non-zero
with one value-free log line when it is absent for today's date — never
tallying a partial or unscored store (BLOCK-2 above).

The Kalshi sibling unit pair (`breezy-kalshi-crh-tally.{service,timer}`,
family `kalshi_crh_v1`, 16:30 UTC) is **parked on branch
`wip/kalshi-s4-registry`**, not on main — per the 2026-09-04 operator
priority: Kalshi is not prioritized until Polymarket.us is working. The
`kalshi_crh_v1` family manifest still exists on disk
(`deploy/families/kalshi_crh_v1.json`), so the wrapper still lists it as a
valid family id even with no unit invoking it.

**The family id is the wrapper's only argument — one invocation per family,
family named by argument, never inferred.** `family-tally-v2-run.sh` takes
the family id as `$1`, validates it against the manifests present in
`deploy/families/*.json` (basename without `.json`), and fails loudly
(exit 2, naming the valid ids in its stderr) on an unknown or missing id,
rather than silently tallying the wrong family. `breezy-pm-crh-v2-tally
.service`'s `ExecStart=` passes its family id explicitly (`...
family-tally-v2-run.sh pm_us_crh_v2`) — the wrapper is shared-ready for a
future Kalshi unit but never infers or defaults the argument. The wrapper
reads the same scored-trials store and writes into the same reports
directory convention as `live-tally-run.sh` (`BREEZY_SCORED_TRIALS_DIR` /
`BREEZY_LIVE_TALLY_OUTPUT_DIR` overrides), naming its output file by family
id so future sibling tallies' artefacts never collide on disk.

Validation performed (no unit activated):

```
$ bash -n deploy/systemd/family-tally-v2-run.sh
OK
```

To activate: symlink the pair into `~/.config/systemd/user/` (§2's
pattern), `daemon-reload`, then
`systemctl --user enable --now breezy-pm-crh-v2-tally.timer` — deliberately
not run here; see the TRAP section above for the post-edit `daemon-reload`
discipline that applies to any future edit of this unit too.

## Orphan node after a supervisor restart is EXPECTED

SP-1/I4 (2026-09-12), doc-only. A `systemctl --user restart
breezy-trade-supervisor.service` — including the one this plan's build-side
steps perform after any unit edit (see the TRAP section above) — does NOT
kill a `breezy-trade` node the supervisor spawned, even one holding a live
position. Verbatim journal quote (09-12 01:24:03, repeated 01:37:20):

```
Found left-over process 3196952 (breezy-trade) in control group … Ignoring
```

This reads like a defect. It is not. `breezy-trade-supervisor.service:131-144`
("THE MOST IMPORTANT LINE IN THIS FILE") sets `KillMode=process`: systemd's
default `KillMode=control-group` would SIGTERM (then SIGKILL) every process
in the unit's cgroup, including a spawned node that may be holding a live
position; `KillMode=process` signals ONLY the supervisor process itself. A
node that outlives its supervisor is an anticipated, tested state, not an
orphan — see L-26 (`docs/core/LESSONS.md`) and the `[B2]` supervisor-death
adoption path (`trade_supervisor.py:700-737`), which re-adopts the
PID-verified flock holder at the next 16:40Z cycle.

**Never `SIGKILL` either process.** The only legitimate ways to stop a
running node are the supervisor's own 16:40Z `STOP_PRIOR` hop, or an
explicit operator SIGTERM. An `ExecStopPost=` "reaper" that cleaned up the
left-over process on unit stop/restart was considered and REJECTED (T5): it
would SIGTERM a node holding a live position, directly contradicting
`KillMode=process` and L-26 — the exact failure this design exists to
prevent.

## Protected window and serialization

SP-1 (2026-09-12): `breezy-k1-daily`, `breezy-mb-daily` and
`breezy-offer-gate-daily` are the three nightly analysis studies. Two
independent `systemd --user` timers had no shared lock, so they could (and,
per the 2026-09-11 incident, did) run concurrently -- each already capped at
its own `MemoryHigh=12G`/`MemoryMax=16G`
(`tests/unit/test_analysis_units_memory_capped.py`), but nothing stopped two
12-16G studies stacking at once, nor stopped either from starting beside the
live trading node (pid 895135) during its LST-derived decision window.

**The protected window, `P`.** Derived from `src/breezy/registry/sites.toml`'s
`std_utc_offset_hours` (`{-5.0, -6.0, -8.0}` across the four supported
stations) union'd with the live decision window
`breezy.strategy.current_rung_hold.strategy._WINDOW_START_HOUR_LST` /
`_WINDOW_END_HOUR_LST` = `[12:00, 17:00)` local standard time (never a UTC
literal, never an IANA zone): `-5 -> 17:00-22:00Z`, `-6 -> 18:00-23:00Z`,
`-8 -> 20:00-01:00Z`, union = `[17:00Z, 01:00Z)`, +/-15 min slack =
**`P = [16:45Z, 01:15Z)`**. Including the 16:40Z `STOP_PRIOR` hop, the
no-start rule is **`[16:35Z, 01:15Z)`**.
`breezy.strategy.current_rung_hold.continuous_strategy` imports these same
two constants rather than re-declaring them
(`tests/unit/test_analysis_units_serialized.py`).

**What moved.**

- `breezy-k1-daily.timer`: `22:30Z -> 01:35Z` (MOVED 2026-09-12).
- `breezy-offer-gate-daily.timer`: `22:45Z -> 02:05Z` (MOVED 2026-09-12).

Both are now outside `P`, with `Persistent=true` kept on both.
`breezy-mb-daily.timer` stays at `13:30Z`, already outside `P`.

**Serialization.** `breezy-studies.slice` (new) gives the three heavy
studies a shared `MemoryHigh=12G`/`MemoryMax=16G` aggregate ceiling --
usually redundant with each unit's own per-service cap once the flock below
holds, and mainly defence-in-depth against a bypassed lock or a future unit
added to the slice before it is wrapped. It only binds once **installed**:
`daemon-reload` alone does not create the `~/.config/systemd/user/`
symlink; without it systemd instantiates an implicit, unbounded slice while
`show <service> -p Slice` still reports the configured name (false green).
The real observable is `systemctl --user show breezy-studies.slice -p
MemoryHigh -p MemoryMax`. Each of the three wrappers (`k1-daily-run.sh`,
`mb-daily-run.sh`, and the new `offer-gate-daily-run.sh`) now takes a
host-wide, non-blocking `flock` on `breezy-studies.lock` (resolved under
`$XDG_RUNTIME_DIR`, falling back to `$HOME/.local/share/breezy`) before
doing any work: contention exits 0 (skip-not-kill -- `Persistent=true`
never retriggers a healthy skip, and no sibling `OnFailure=` fires), while a
lock-INFRASTRUCTURE failure (missing/unwritable lock directory) exits **75**
(`EX_TEMPFAIL`) with its own distinct reason, loud in `journalctl` instead
of silently skipping forever. `Conflicts=` was considered and rejected: it
would SIGTERM the RUNNING job, the exact 2026-09-11 shape this design
avoids.

**Light-job exemption.** `breezy-pm-crh-v2-tally` (17:15Z), `breezy-live-tally`
(14:30Z) and `breezy-score-live-trials` (14:15Z) stay outside this scheme --
each is <=1 GB / <=60 s, well under the exemption threshold, and none is
retimed or wrapped by this item.

**Worst-case-runtime rule.** No heavy study starts within its own worst-case
observed runtime before `16:35Z`: `breezy-offer-gate-daily` 11.5 min,
`breezy-mb-daily` 36 min (13:30Z + 36 min = ~14:06Z, clear).

**Reboot-catch-up residual.** `daemon-reload` can trigger an immediate
`Persistent=true` catch-up run; a reboot can still fire a relocated heavy
timer inside `P`. Accepted: the flock and slice still apply even then.

**G2 is NOT met by this item.** `breezy-quote-tape-ingest.service` (`*:0/15`)
still runs INSIDE `P` every 15 minutes and still peaks approximately 4.0 GB
there -- starving conversion would recreate "the catalog you query is not
the tape you capture", so it is only deprioritised (`Nice=10`,
`IOSchedulingClass=best-effort`, `IOSchedulingPriority=7` -- never `idle`,
which could itself be starved indefinitely by the live node's own I/O), not
serialized behind the studies lock. Anyone reading Rev 2's G2 ("no >1 GB
unit starts inside P") as satisfied by this item is reading it wrong.

**`breezy-nws-ingest.service` residual.** This unit is installed on the host
with no copy in this repo -- a pre-existing, out-of-scope residual, named
here rather than silently inherited.

**Declared stale cross-references (A-20).** MOVED 2026-09-12 retimed
exactly `breezy-k1-daily.timer` (was `22:30`, MOVED 2026-09-12) and
`breezy-offer-gate-daily.timer` (was `22:45`, MOVED 2026-09-12) (plus this
file), correcting the old values above. Five OTHER files still carry a
stale comment cross-reference to that same pre-move schedule, and are
deliberately left unedited because each is protected as an R-5/R-4-gated
zero-diff file:
`breezy-pm-crh-v2-tally.timer:13`, `breezy-live-tally.timer:12`,
`breezy-mb-daily.timer:24-25`, `breezy-score-live-trials.timer:10`, and
`breezy-quote-tape-ingest.timer:11-12`. Follow-up owner: whoever unblocks
R-5 (the `breezy-live-tally` narrowing ruling) should sweep these five
comments in the same pass.

**No v3 tally exists.** `pm_us_crh_cont` (the live v3 strategy) has no
nightly tally unit of its own -- L-38 stands. Building one is I5, blocked on
R-4; this item does not touch it.
