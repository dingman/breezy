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

### Retiring a unit (general pattern, folded in by the AUD-15 amendment)

Any unit's retirement (a timer + service + wrapper triple, same shape as
`breezy-mb-daily`/`breezy-offer-gate-daily` below) follows this order,
never fewer steps:

```bash
systemctl --user disable --now <unit>.timer
# If the service ever reached `failed` (it will have, on its last run before
# retirement, if that run was a timeout/OOM/non-zero exit):
systemctl --user reset-failed <unit>.service
rm ~/.config/systemd/user/<unit>.timer ~/.config/systemd/user/<unit>.service
systemctl --user daemon-reload
```

**Never leave a disabled timer with an orphan unit.** The
`breezy-pm-crh-{cont,v2}-tally` orphans are the named anti-pattern (G-04):
both symlinks were left in place after their timers were disabled, so they
sit in `not-found`/`failed` forever, indistinguishable at a glance from a
unit that is merely quiet. `systemctl --user list-units --all 'breezy-*'`
after any retirement must show **neither** `not-found` **nor** `failed` for
the retired name -- confirming the symlinks and the failed-state latch are
BOTH gone, not just the timer disabled.

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

## `breezy-mb-daily` / `breezy-offer-gate-daily` — RETIRED 2026-09-22

**Both units are RETIRED**, per
`docs/evidence/RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md`
RULING 1 (ENDORSED, review trail
`docs/evidence/reviews/RULING_study_ceiling_exit_review_2026-09-21.md`):
`breezy-offer-gate-daily` on decision-table rows 1+2 (no consumer of
`offer_gate_latest.md`; the lock-family programme it measures is dead by
standing verdict); `breezy-mb-daily`'s M_A on rows 1+2 (same lock programme)
and M_B on row 2 (it measures the archive-vs-tape edge closed TERMINAL
2026-09-20). Their timers, units and wrapper scripts (`mb-daily-run.sh`,
`offer-gate-daily-run.sh`) are deleted. `ma_prelock_winner_ask_study.py`,
`mb_current_rung_edge_study.py` and `cli_basis_offer_gate_scan.py` are **NOT**
deleted or edited (ruling §1.4 item 3): the offer-gate module is imported as
a library elsewhere (AUD-09), and M_B's module is a registered PREREG v1/v2
analysis definition, pinned byte-unmodified while those specs are live.
`ma_prelock_winner_ask_study.py:169-177`'s docstring, which names
`breezy-mb-daily.timer` as the window advancer, is now stale by this
retirement and is left that way by the same zero-diff rule (a documented,
accepted doc-drift, not an oversight).

**Historical, retained so this file's own A-20 pin still holds:**
- `breezy-k1-daily` moved `22:30 UTC` to `01:35 UTC` (MOVED 2026-09-12).
- `breezy-offer-gate-daily` (now retired) moved `22:45 UTC` to `02:05 UTC` (MOVED 2026-09-12).
- `breezy-mb-daily` (now retired) stayed at `13:30 UTC`.

**What replaced them.** Retiring both wrappers would have deleted the ONLY
nightly invocation of `asos_recent_refresh.py --since <ASOS_FETCH_START
anchor>` (`mb-daily-run.sh:86-87`'s form) -- the fixed-window fetch a
**live-path** consumer reads without fetching itself
(`current_rung_hold_monitor_hypothetical_hold.py:158-168`,
`current_rung_hold_exit_window_study.py:16-24`). Ruling §1.4 item 4 / the
Revision 2 addendum §A1 makes re-homing that ONE invocation (never the
offer-gate rolling 3-day form, §A1(ii)) a BINDING same-commit condition. See
the `breezy-asos-refresh` section immediately below.

---

## `breezy-asos-refresh` — re-homed ASOS fixed-window refresh (2026-09-22)

`breezy-asos-refresh.service` + `.timer` + `deploy/systemd/asos-refresh-
run.sh` are the re-home target: exactly the invocation `asos_recent_
refresh.py --since "$ASOS_FETCH_START_ANCHOR"` moved verbatim from the
retired `mb-daily-run.sh`, at the **same 13:30 UTC** slot that unit
vacated. The anchor is not forked (ruling §A1(iii)): it exists in exactly
two places after this commit, the module constant `ma_prelock_winner_ask_
study.ASOS_FETCH_START` and the wrapper's own `ASOS_FETCH_START_ANCHOR`,
both carrying the "update both together" comment, and a RED-first pin
(`tests/unit/test_asos_refresh_re_home.py::
test_an_enabled_timer_invokes_the_since_anchored_asos_refresh_and_the_consumer_cache_key_is_fresh`)
imports the module constant so a fork fails the suite.

**Light unit, not a heavy study.** `MemoryHigh=512M`/`MemoryMax=1G` (the
`breezy-position-monitor-report.service` band) -- this is one HTTP GET per
site plus a cache-mtime read, never a tape scan. It still cites the
2026-09-11 K1 incident, joins `breezy-studies.slice`, and takes the shared
studies flock, so it never contends with a heavy study or the live node.

**`$OUT/asos_refresh.log` is append-only, with no rotation** -- an
accepted residual, same pre-existing pattern as every other study
wrapper's own log file (`k1_daily.log`, the retired `mb_daily.log`/
`offer_gate_daily.log`): one light run per day keeps this small enough
that rotation has never been worth building.

**Control flow differs from the retired heavy wrappers on purpose** (a
round-6 review defect, fixed before this shipped): the retired wrappers
`exit 0` IMMEDIATELY on lock contention, so nothing after the lock line ever
ran on a contention night. `asos-refresh-run.sh` CAPTURES the lock result
instead (`if flock -n 9; then <refresh>; else <SKIPPED-LOCK>; fi`) so the
freshness check below always runs. `SKIPPED-INFRA`/`exit 75` on a genuine
lock-infrastructure failure is unchanged.

**The freshness alert this re-home ships (`scripts/analysis/asos_cache_
freshness_check.py`).** 15a's `OnFailure=` only fires on `failed`, and the
refresh's own shortfall path exits 0 by design -- so a refresh that fetches
nothing would otherwise leave the unit looking healthy while the consumer's
cache key goes unwritten. The wrapper therefore runs an UNCONDITIONAL
check, on every invocation regardless of the lock outcome: it resolves the
SAME cache path the live consumer resolves (`asos_url` + `cache_path_
for_url`, never re-derived by hand) and compares its **epoch mtime** against
00:00:00Z of the current UTC day -- missing, or older than that boundary,
fires exactly one `asos_cache_stale` WARN through the existing alert sink
(`breezy.runtime.health`) and the unit still exits 0. There is no hour
threshold: the cache key hashes a URL carrying both window dates, so it
rotates every UTC day and a present file under today's key can only ever
have been written today -- "missing" is therefore the dominant signal, and
the mtime leg is what keeps the rule correct if the key ever stops rotating.
Fires 90 minutes ahead of the first consumer (15:00 UTC).

Validation performed:

```
$ systemd-analyze --user verify deploy/systemd/breezy-asos-refresh.service \
    deploy/systemd/breezy-asos-refresh.timer
(no output)
EXIT=0

$ bash -n deploy/systemd/asos-refresh-run.sh
OK
```

To activate: symlink both unit files into `~/.config/systemd/user/` (§2's
pattern), `daemon-reload`, then
`systemctl --user enable --now breezy-asos-refresh.timer` — deliberately not
run here; see the TRAP section above for the post-edit `daemon-reload`
discipline that applies to any future edit of this unit too.

---

## AUD-18 addendum — nightly IEM MOS closed-day refresh (2026-09-25)

Two extra steps were added to the SAME `asos-refresh-run.sh` at the SAME
13:30 UTC slot, rather than a new unit/timer (coordinator decision): the
lock, the freshness-alert pattern, and the "run regardless of the others'
outcome" contract were already correct here and did not need forking.

**The steps, in order.** (1) ASOS refresh, (2) ASOS freshness check
(unchanged from the section above), (3) IEM MOS closed-day refresh
(`scripts/archive/iem_mos_backfill.py --closed-days-lookback 7 --model NBS
--apply`, one 1-day entry per (station, settled UTC day) for
KLAX/KMDW/KMIA/KSFO, self-healing over the 7-night lookback), (4) IEM MOS
freshness check (`scripts/archive/iem_mos_freshness_check.py`). Steps (1)
and (3) share ONE captured lock result (`LOCKED`, from a single `flock -n 9`
call) — a lock-contention night skips BOTH fetch steps, never just one.
Steps (2) and (4) are unconditional, exactly like (2) already was.

**New exit contract.** The wrapper used to exit ALWAYS 0. It now exits 1 if
ANY of the four steps exits non-zero, 75 on the pre-existing
lock-infrastructure failure paths (unchanged), 0 otherwise. `asos_recent_
refresh.main` and both freshness checks are still fail-soft by design (they
return 0 on a data-freshness signal, never a crash) — the new non-zero paths
come only from the MOS refresh step failing (upstream refused, a retry
budget exhausted, the completeness guard tripping) or an unexpected
internal exception in any step, which is intended: those are exactly the
conditions `OnFailure=` should page on.

**`TimeoutStartSec=1800`** (up from 600): budgeted as ASOS (600, unchanged)
+ the MOS step's own `900`-second timeout (`timeout --kill-after=30`) + its
30s kill grace + both freshness checks (~60s combined, generous), with
margin. Pinned by `tests/unit/test_asos_refresh_alert_env.py::
test_unit_timeout_exceeds_step_bounds`.

**`breezy.env` joins the EnvironmentFile allowlist**, dash-prefixed
(`EnvironmentFile=-%h/.config/breezy/breezy.env`) for the SAME independence
reason as the rest of this unit: the MOS step needs `BREEZY_USER_AGENT`
(`iem_mos_backfill.py` refuses without one), but a missing `breezy.env` must
never stop the independent ASOS steps from starting. Per this file's own
"AUD-15 alert env file" section below, `breezy.env` is non-credential. The
forbidden-substring list (`breezy-trade.env`, `polymarket.env`,
`operator.env`) is unchanged.

**Freshness alert.** `iem_mos_archive_stale` (WARN) fires per station,
`site=<station>`, `detail=latest_closed_day_missing`, when that station's
EXACT 1-day manifest key for the latest SETTLED closed UTC day (`L = (now -
12h).date() - 1`) is missing — one missed night is enough. A wider entry
that merely spans `L` (see the AUD-18 note below) does NOT satisfy this
check: `resolve_mos_coverage`'s narrowest-wins rule means the 1-day entry,
once it exists, is what a read actually resolves to, so its continued
absence is the real gap. A missing or unreadable manifest emits one
`site=global` alert instead (`detail=manifest_missing` /
`manifest_unreadable`).

**AUD-18 note — the acknowledged wide 2026-09-25 entry, and FU-1 (KNYC).**
A one-off `--start 2026-09-20 --end 2026-09-27 --apply` run on 2026-09-25
(before this refresh existed) left one wide 6-day manifest entry per
station. It is NOT rewritten or deleted (the cache is write-once); the
nightly closed-day refresh's 1-day entries for 2026-09-25/26 onward take it
over through the narrowest-wins rule as they land. **Such a one-off would
now be REFUSED**: the window-mode CLI gained a settled-bound guard
(`--end` may not claim a day after `(now - 12h).date()`), so `--end
2026-09-27` at the time that run happened would be refused with exit 2.
KNYC stays out of MOS scope, pinned by `tests/unit/test_iem_mos_probe_
transport.py::test_mos_url_rejects_knyc`, tracked as follow-up FU-1 under
AUD-18.

---

## `breezy-study-failed@` — OnFailure= notifier for every study unit (AUD-15a, 2026-09-22)

`breezy-study-failed@.service` is a templated `Type=oneshot` unit that ONE
line on every other study unit invokes:
`OnFailure=breezy-study-failed@%n.service` -- `%n` carries the failing
unit's own full name as the instance. Cause-agnostic: it fires identically
whether the unit hit `TimeoutStartSec`, was OOM-killed by its own
`MemoryMax`, or exited non-zero for any other reason. `ExecStart` runs a
console entry point, `breezy-study-failed --unit %i`, over a small module
(`src/breezy/runtime/study_failure_notifier.py`) that reuses the existing
alert sink (`breezy.runtime.health.emit_alert`/`resolve_alert_sink`)
unmodified -- no new `src/` alerting mechanism, only the entry point.

The alert is a fixed-shape WARN: `event="study_unit_failed"`,
`site="global"`, and a closed-enum `detail` that never carries the failing
unit's name, exception text, or journal text -- the unit name travels on the
plain log line instead. The template unit itself declares **no**
`OnFailure=` and **no** `Restart=`: if the notifier instance itself fails, it
lands in `failed` (visible in `systemctl --user list-units --all
'breezy-*'`) but nothing pages on it, a named and accepted residual rather
than a second-order watchdog that would reintroduce an alert loop.

Covers, as of this revision: `breezy-k1-daily`, `breezy-exit-window-study`,
`breezy-family-tally@`, `breezy-live-tally`, `breezy-position-monitor-report`,
`breezy-quote-tape-ingest`, `breezy-quote-tape-rotate`,
`breezy-score-live-trials`, and the new `breezy-asos-refresh` -- every unit
with a sibling timer, enumerated by `tests/unit/test_study_failure_alert.py`
by scanning the tree (never a frozen list), so a future study unit added
without `OnFailure=` fails that suite. It incidentally also covers
`breezy-family-tally@pm_us_crh_cont.service` (G-04, a different gap, out of
scope here).

To activate: symlink the template unit into `~/.config/systemd/user/` (§2's
pattern) alongside every unit that references it, `daemon-reload`. There is
no `[Install]` section to enable -- this unit is invoked only via a sibling's
`OnFailure=` line.

---

## AUD-15 alert env file (`~/.config/breezy/alerts.env`) (amendment, 2026-09-22)

**The contradiction this closes.** AUD-15's own plan text said "No
`EnvironmentFile=`, no credential" for `breezy-study-failed@.service` and
`breezy-asos-refresh.service`, and separately assumed
`BREEZY_ALERT_WEBHOOK_URL` "is configured" for them. On this host that
variable lives ONLY in `~/.config/breezy/breezy-trade.env`, loaded only by
`breezy-trade-supervisor.service`. Under an empty declared environment,
both new units' `resolve_alert_sink()` always returned a LOG-ONLY sink --
detection without delivery, the exact defect `f97c26f` was raised to close,
reproduced by AUD-15 itself. Independent review (silent-failure-hunter,
security-reviewer) blocked the build on this before it shipped.

**The fix.** A DEDICATED, single-key file, `~/.config/breezy/alerts.env`,
mode `0600`, holding exactly one line: `BREEZY_ALERT_WEBHOOK_URL=<value>`.
Three units load it via `EnvironmentFile=-%h/.config/breezy/alerts.env`
(the `-` keeps each startable if the file is absent): the two new AUD-15
units, and `breezy-trade-supervisor.service` (added BEFORE its existing
`breezy-trade.env` line, so this is the single source of truth going
forward). Rejected: pointing the new units at `breezy-trade.env` itself
(it also carries `POLYMARKET_US_ACCOUNT_NUMBER` /
`POLYMARKET_US_EXEC_STATE_DB` -- a venue credential a study-adjacent unit
must never hold); `systemctl --user set-environment` (transient, lost on
user-manager restart, invisible to unit-text pinning tests); an inline
`Environment=` literal (a bearer-capability URL mirrored into tracked
`deploy/systemd/`).

**Least privilege inside `asos-refresh-run.sh`.** The ASOS fetch subprocess
never sees the variable (`env -u BREEZY_ALERT_WEBHOOK_URL` wraps only that
call) -- it is an outbound HTTP GET to a public endpoint with no use for a
credential-shaped value. Only the freshness-check step needs it.

**Runtime visibility, not just a hermetic unit test.** Both
`study_failure_notifier.notify_study_failed` and
`asos_cache_freshness_check.main` call
`breezy.runtime.health.log_alert_egress_status(env, component=...)` BEFORE
resolving the sink, on every invocation -- so a missing/empty `alerts.env`
leaves a distinct, loud journal line every run, not a silently-downgraded
`LoggingAlertSink`. The hermetic `resolve_alert_sink` test in each unit's
test module proves the function reads the right key NAME; it does not by
itself prove the deployed file exists, which is what this call and the
deploy-time check below are for.

**Migration (host-only, never committed).** `deploy/systemd/
migrate-alerts-env.sh` -- ONE idempotent script, `set -euo pipefail`,
`umask 077`, never prints/logs/echoes the URL's value (names, counts, and
file modes only):

```bash
# Step 1 (base migration; safe to re-run; leaves breezy-trade.env untouched):
deploy/systemd/migrate-alerts-env.sh
# -> creates ~/.config/breezy/alerts.env (mode 600) from the ONE
#    BREEZY_ALERT_WEBHOOK_URL= line in breezy-trade.env. Aborts loudly if
#    that file has zero or more than one such line.

# Step 2: land the unit-file commit (this repo's changes), symlink, then:
systemctl --user daemon-reload

# Step 3: confirm delivery (see below) -- must exit 0 before step 4.

# Step 4 (only after steps 2-3 both succeed):
deploy/systemd/migrate-alerts-env.sh --finalize --delivery-confirmed
# -> removes BREEZY_ALERT_WEBHOOK_URL= from breezy-trade.env. REFUSES
#    unless `systemctl --user cat breezy-trade-supervisor.service` already
#    shows the alerts.env EnvironmentFile= line (proving step 2 landed) AND
#    --delivery-confirmed is passed (proving step 3 passed). Does NOT
#    restart, stop, start, enable, or disable any unit -- the supervisor's
#    added EnvironmentFile= line and the key's removal from
#    breezy-trade.env both take effect only at ITS NEXT NATURAL RESTART,
#    never forced by this script (the running process keeps its
#    already-loaded URL until then).
```

**Duplication during the transition is deliberate and harmless.** Between
step 1 and step 4, the SAME value may exist in both files; whichever
`EnvironmentFile=` line systemd loads last wins, and both hold the
identical value, so this is never a two-sources-of-truth risk -- only
step 4's removal makes `alerts.env` the sole copy.

**Deploy-time delivery check (§4d).** `%h` is a systemd-native specifier,
NOT expanded by `systemd-run -p` on the command line, so the real `$HOME`
must be substituted by the shell instead:

```bash
systemd-run --user --wait --pipe -p EnvironmentFile=-"$HOME"/.config/breezy/alerts.env \
  /home/jon/breezy/.venv/bin/breezy-check-alerts --severity INFO
```

Expected: exit `0` and a `delivered -- event=BREEZY_ALERT_EGRESS_CHECK
severity=INFO detail=operator_channel_test` line (`breezy-check-alerts`'s
own contract, `check_alerts_cli.py`: `0` delivered, `2` NOT CONFIGURED,
`3` configured but NOT DELIVERED). One run covers both new units, since
both declare the identical `EnvironmentFile=`. Exit `2` -> `alerts.env`
missing or empty, stop and fix before continuing. Exit `3` -> endpoint
unreachable, report and stop.

**Rollback.** Re-add the removed line to `breezy-trade.env` from
`alerts.env` (the two are still byte-identical at that key until finalize
ran), `git revert` the unit/test commit, `daemon-reload`. Leave
`alerts.env` in place (harmless) or `rm -f` it. No supervisor restart at
rollback either -- same "next natural restart" rule as the forward path.

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
catalog the (now-retired, AUD-15) `breezy-mb-daily` used to read. Measured
2026-09-02: instance `dbb0354a…`
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
**rotate 09:00 UTC → ingest 12:15 UTC → 13:30 UTC tick**. The
09:00→12:15 gap is deliberate, not incidental: it clears the ingest CLI's
30-minute live-write grace window (`DEFAULT_LIVE_GRACE_MINUTES`) by over two
hours, so 12:15's pass is guaranteed to see the rotated-off instance as
genuinely quiet and convert it, landing it in the catalog before the 13:30
tick. AUD-15 (2026-09-22): the 13:30 tick's occupant is now `breezy-asos-
refresh` (retired `breezy-mb-daily`'s successor at that slot), which does
not read this catalog at all -- it fetches ASOS, not quote-tape data -- so
this stagger has no live reader left downstream of it; retained because it
remains harmless and documents the tick's history.

A daily `try-restart` does not interact badly with the recorder's own
`Restart=always` / `RestartPreventExitStatus=2` / `StartLimitIntervalSec=0`:
systemd counts both automatic and manual restarts against the same start-limit
budget, but that budget is disabled (interval 0), so one scheduled rotate
per day cannot park capture the way the old 20-per-hour ceiling did on
09-09. No further adjustment to `breezy-quote-tape.service` is needed for
the rotate unit.

**AUD-08b (2026-09-24): `OnSuccess=breezy-station-candidate-register.service`.**
The rotate unit is otherwise byte-identical to its pre-08b self (no slice, no
memory cap, no extra env). After a successful rotation it enqueues
`breezy-station-candidate-register.service`, a separate oneshot (no timer, no
`[Install]`) that runs `station-candidate-register-run.sh` under the shared
studies flock and `breezy-studies.slice`, with `MemoryHigh=4G`/`MemoryMax=6G`
(growth measurements in the unit comment), `alerts.env` and `OnFailure=`. It
folds the recorder's unregistered-city sighting sidecar
(`~/.local/share/breezy/derived/station_candidates/sightings/`) into the
ADVISORY register `station_candidates.jsonl` -- never a trading input, never a
subscription -- and raises `BREEZY_STATION_CANDIDATE_NEW` once per new venue
city and `BREEZY_STATION_CANDIDATE_STALE` when the fold has not succeeded for
more than two nights (also checked on the lock-skip path). An unreadable catalog
makes it exit 1 having written nothing; the register's failure can never fail
the rotation. The recorder unit now also reads `alerts.env`, for the
`BREEZY_SIGHTING_SIDECAR_BROKEN` alert (three consecutive failed sidecar
appends). The sidecar only grows once the recorder restarts on this code.

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

## `breezy-live-tally` — 6d nightly live-family tally — RETIRED 2026-09-24

**RETIRED 2026-09-24 per `docs/evidence/RULING_R5_prereg_v1_tally_2026-09-24.md`
(§2-§4, ENDORSED).** Disabled (never deleted), 2026-09-25T02:54:23Z:
`systemctl --user disable --now breezy-live-tally.timer`. Reason: this
unit's tally produced zero evidence for its entire life (`row count: 0`
every dated report); it has been structurally incapable of evidencing
either family actually trading (`pm_us_crh_cont`/`pm_us_crh_v4`, disjoint
`trial_id_prefix`) since `pm_us_crh_cont`'s D0 (2026-09-12); the pooled
60/150 Wilson statistic it exists to serve is superseded, for
`pm_us_crh_v2` itself, by PREREG v2 rev b's LD-OBF sequential design; and
its own structural-dead check is already, and more completely, duplicated
daily by `breezy-family-tally@pm_us_crh_v2` (own alert edge, reading the
champion-scoped counter per the R-4 ruling). Re-enable only via a NEW
ruling, and only if `pm_us_crh_v2` is ever re-armed as a sending family.

The unit files, `live-tally-run.sh`, and `scripts/analysis/
live_family_tally.py` all stay in the repo, unedited in logic
(`tests/unit/test_prereg_v1_is_byte_unmodified.py` byte-pins the analysis
module); every past `live_family_tally_*.md` report and `live_tally.log`
line is retained as citable history. The description below is kept as
historical/architecture record of what the unit did while active.

`breezy-live-tally.service` + `.timer` run `scripts/analysis/
live_family_tally.py` daily at **14:30 UTC** via a wrapper script,
`deploy/systemd/live-tally-run.sh`, in the same style as `k1-daily-run.sh`:
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

Scheduled a full hour AFTER the 13:30 UTC tick (occupied by the now-retired
`breezy-mb-daily`, AUD-15's `breezy-asos-refresh` since 2026-09-22) so the
tally's read of the (unrelated) parquet store never races that unit's work,
and a distinct hour from every other Breezy timer (`breezy-quote-tape-rotate`
09:00, `breezy-quote-tape-ingest` 00,06,12,18:15, `breezy-k1-daily` 01:35,
the now-retired `breezy-offer-gate-daily` 02:05 (MOVED 2026-09-12, was 22:45)) —
pinned by
`tests/unit/test_deploy_timer_hours.py`, which parses every
`deploy/systemd/*.timer`'s `OnCalendar=` line as text (no `systemd-analyze`
shelling in the test suite; that check stays a manual step, below). No
network: the store is local, and the unit carries no `EnvironmentFile`.

Artefacts land under `~/.local/share/breezy/derived/`, dated
(`live_family_tally_<date>.md`), one snapshot per day — same convention as
`breezy-k1-daily`; the unit never writes into `docs/evidence/`.

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

**Retired — not to be activated.** The activation steps this unit
previously documented here (symlink, `daemon-reload`, then the systemd
command that starts and arms this timer) no longer apply: the unit is
disabled per the RETIRED note above, and re-arming it is gated on a NEW
ruling, not a deploy step.

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

## `breezy-portfolio-roi` — AUD-04 unattended portfolio ROI report (2026-09-21/22, PREPARED, NOT ACTIVATED)

`breezy-portfolio-roi.service` + `.timer` + `deploy/systemd/
portfolio-roi-run.sh` ship the daily, unattended, read-only portfolio-level
ROI report of
`docs/plans/backlog/AUDIT_2026-09-21/AUD-04-portfolio-roi-measurement.md`
(section 6 D1, section 7 step 5). Each run invokes
`scripts/analysis/portfolio_roi_report.py`, which joins the durable
exec-state fill ledger and the scored-trial store family-agnostically
across the whole live record and writes a PRIVATE Markdown + versioned JSON
sibling under `~/.local/share/breezy/derived/` — realised P&L after fees,
capital deployed, the account-balance series, an unexplained-capital-flow
line, and ROI against the two registered baselines (B0 cash, B1 fee-drag
null). No dollar figure ever reaches the journal, the wrapper log, or an
alert (section 6 D6).

**Gated on the score-live-trials marker, never on the family tally
(section 6 D2).** The wrapper requires the same
`$OUT/score_live_trials_ok_<stamp>` success marker
`family-tally-v2-run.sh` requires, and deliberately never requires AUD-05's
family tally to have succeeded — AUD-05 is open and this item must still
produce a number while it is failing.

**ASSUMPTION, named because the plan leaves it open.** The plan's section 7
steps 2–3 name `portfolio_roi_report.py`'s loader FUNCTION signatures and
its output artefact paths, but no CLI/argparse contract for the script
itself (unlike `family_tally_v2.py`'s `--family`/`--store-dir`/`--as-of`/
`--output`, which the plan names explicitly). The wrapper therefore invokes
the script with **no arguments** — `"$PY" "$REPO/scripts/analysis/
portfolio_roi_report.py"`. If the script's implementer lands a required
flag, this invocation line and its pin in
`tests/unit/test_portfolio_roi_deploy.py` both need updating together.

**Light unit, not a heavy study.** `MemoryHigh=512M`/`MemoryMax=1G` (the
same band as `breezy-position-monitor-report.service` and the re-homed
`breezy-asos-refresh.service`) — this unit reads two already-persisted
local stores plus a bounded log-line scan for the balance series, never a
raw quote-tape scan. It still cites the 2026-09-11 K1 incident, joins
`breezy-studies.slice`, and takes the shared studies flock
(`portfolio-roi-run.sh` mirrors `position-monitor-report-run.sh`'s own
skip-not-kill convention: lock contention exits 0, lock-infrastructure
failure exits 75), so it never contends with a heavy study or the live
node.

**Alert env file.** The unit's only `EnvironmentFile=` is
`-%h/.config/breezy/alerts.env` (the AUD-15 amendment single-key file,
never `breezy-trade.env`/`polymarket.env`/`operator.env`), needed because
the D8 frozen-input ladder and the D9 unsettled-position check both deliver
through the existing shipped sink (`breezy.runtime.health.resolve_alert_sink`
/ `emit_alert`) — without it, both would always resolve a LOG-ONLY sink on
this host. See "AUD-15 alert env file" above for the full migration story.

**`OnFailure=`.** `OnFailure=breezy-study-failed@%n.service`, the same
notifier every other study-adjacent unit with a sibling timer declares
(`tests/unit/test_study_failure_alert.py` scans the tree, so this unit is
covered by that test's own discovery rather than a name added by hand).

Scheduled at **17:40 UTC** — strictly after `breezy-family-tally@.timer`'s
17:20 UTC tick (section 6 D1), and free against every occupied
`OnCalendar=` on this host, pinned by
`tests/unit/test_deploy_timer_hours.py`. This report never reads either
PREREG tally's output, so the ordering is for a lower-contention slot on
the shared studies lock, not for correctness.

Validation performed (no unit activated):

```
$ bash -n deploy/systemd/portfolio-roi-run.sh
OK
```

To activate: symlink all three files (`breezy-portfolio-roi.service`,
`breezy-portfolio-roi.timer`) into `~/.config/systemd/user/` (§2's
pattern), `daemon-reload`, then
`systemctl --user enable --now breezy-portfolio-roi.timer` — never `start`
the service directly; see the TRAP section above for the post-edit
`daemon-reload` discipline that applies to any future edit of this unit
too.

**Rollback:** `systemctl --user disable --now breezy-portfolio-roi.timer`
and revert the commit. Nothing else consumes the report's output except
through the D7 sanctioned reader (`read_portfolio_roi_report()`), which
refuses an absent or unknown-schema input, so rollback is total and
fail-closed.

---

## `breezy-exit-window-study` — nightly exit-window study (2026-09-16, PREPARED, NOT ACTIVATED)

`breezy-exit-window-study.service` + `.timer` run the nightly offline "exit
window" study (`docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md`) via
`deploy/systemd/exit-window-study-run.sh`, in the same wrapper-owns-the-work
style as `position-monitor-report-run.sh`. Each run invokes
`scripts/analysis/current_rung_hold_exit_window_study.py` for the
`pm_us_crh_v2` family's four stations (`LAX`, `MDW`, `MIA`, `SFO`) since that
family's own `d0_climate_day` (both hardcoded in the wrapper with a citation
comment — this study is v2-scoped offline analysis, not the KILL clock;
`family-tally-v2-run.sh` reads the deployed champion manifest for that
guard and does not share this date literal), with `--obs-source fetch`
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

## `breezy-pm-crh-cont-tally` — PREREG v3 family tally, pm_us_crh_cont (2026-09-16, PREPARED, NOT ACTIVATED)

**L-38 closure.** `pm_us_crh_cont` (`deploy/families/pm_us_crh_cont.json`,
trial prefix `continuous_rung_hold/trial/`, `status: REGISTERED`) has been
the LIVE family since 2026-09-13, but until this item had NO scheduled
tally at all -- "a stop that cannot fire is MISSING". This unit pair,
**`breezy-pm-crh-cont-tally`** at **17:25 UTC**, closes that gap by running
the SAME `family-tally-v2-run.sh` wrapper against family id
`pm_us_crh_cont` instead of `pm_us_crh_v2` -- byte-identical
`Type=oneshot`/`MemoryHigh=1G`/`MemoryMax=2G`/`WorkingDirectory=`/no-`
[Install]` shape to `breezy-pm-crh-v2-tally.service`, scheduled 10 minutes
after the v2 tally's own 17:15Z tick (never the same minute --
`tests/unit/test_deploy_timer_hours.py::test_1725_utc_is_owned_by_exactly_one_timer`)
and still outside the protected window `P` (light-job exemption, same as
its v2 sibling).

**What this item does NOT do.** The wrapper's `PM_FAMILY`-scoped branch
(`family-tally-v2-run.sh:73`, literal `"pm_us_crh_v2"` only) still gates
the structural-dead-stop's `--covered-listed-station-days` /
`--fill-source` / `--fill-since-climate-day` arguments to `pm_us_crh_v2`
alone -- `pm_us_crh_cont` runs the plain, unqualified path (identical to
`kalshi_crh_v1`'s), with `covered_listed_station_days=None` and
`filled_takes=None`, so the structural-dead stop is never evaluated for
it. Wiring a v3-scoped count (its own `--family-manifest
pm_us_crh_cont.json`, d0 `2026-09-12`) is **R-4** (`docs/core/PROGRESS.md`
SP-1 I5) and is explicitly out of scope here. What this item DOES restore
is the LD-OBF sequential Wald boundary look (every 10 filled trials) and
the per-stratum Wilson `cell_dead` diagnostics -- both of which were
simply never running for this family before, since nothing invoked the
CLI against it on any schedule.

**Verified before landing (read-only, against a scratch copy of the real
derived store -- never the live `~/.local/share/breezy/derived/` tree):**
the manifest's `status` is `REGISTERED` (not `DRAFT_NOT_REGISTERED`), so
the CLI's own draft gate (`family_tally_v2.py:1042`, SHADOW/DIAGNOSTIC-only
output for a non-`REGISTERED` manifest) does not apply -- full
`SURVIVE`/`KILL`/`CONTINUE` verdict vocabulary is issued. The tally's
source parquet is the SAME store the v2 tally and the 14:15Z scorer read
(`BREEZY_SCORED_TRIALS_DIR`, default
`~/.local/share/breezy/derived/scored_trials`) -- no separate store exists
for v3. As of 2026-09-16 (before that day's 14:15Z scorer run) the live
store carries **zero** `*.parquet` score-run files at all (any family), so
`pm_us_crh_cont`'s rendered `row count: 0 (excluded: 0)` and verdict
`CONTINUE -- fewer than one completed look so far (n < look_step)` --
consistent with "Resolver fills are residual by PREREG"
(`docs/core/LESSONS.md`): every v3 fill so far (the 2026-09-13 MIA take,
the 2026-09-15 NO-side trial) has landed as fee-unreconciled *residual*
dollars via the resolver path, never as a create-path row this store's
scorer has admitted, so 0 (not 3) is the correct count today regardless of
whether the 14:15Z scorer has already run.

Validation performed (no unit activated, no real state touched):

```
$ bash -n deploy/systemd/family-tally-v2-run.sh
OK
$ BREEZY_SCORED_TRIALS_DIR=<scratch copy> BREEZY_LIVE_TALLY_OUTPUT_DIR=<scratch dir> \
  BREEZY_FAMILY_TALLY_V2_FAMILIES_DIR=deploy/families \
  bash deploy/systemd/family-tally-v2-run.sh pm_us_crh_cont
family tally v2 (pm_us_crh_cont) ok   # exit 0; row count: 0 (excluded: 0); verdict CONTINUE
```

To activate: symlink the pair into `~/.config/systemd/user/` (§2's
pattern), `daemon-reload`, then

```
systemctl --user daemon-reload
systemctl --user enable --now breezy-pm-crh-cont-tally.timer
```

-- deliberately not run here; see the TRAP section above for the post-edit
`daemon-reload` discipline that applies to any future edit of this unit
too.

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

**AUD-15 (2026-09-22): `breezy-mb-daily` and `breezy-offer-gate-daily` are
RETIRED** (see their own section above). This section is retained as the
historical design record for the protected window and the flock, which both
still apply to the surviving `breezy-k1-daily` and to the new light
`breezy-asos-refresh` unit (its own section documents its use of the same
lock).

SP-1 (2026-09-12): `breezy-k1-daily`, `breezy-mb-daily` and
`breezy-offer-gate-daily` were the three nightly analysis studies at the
time this section was written. Two
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
MemoryHigh -p MemoryMax`. `k1-daily-run.sh` (the sole surviving heavy
wrapper after AUD-15's retirement) and the new light `asos-refresh-run.sh`
both take a
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
observed runtime before `16:35Z`: `breezy-k1-daily` at `01:35Z` clears by a
wide margin. (Historical, pre-retirement figures: `breezy-offer-gate-daily`
11.5 min, `breezy-mb-daily` 36 min (13:30Z + 36 min = ~14:06Z, clear) --
both units are now retired.) `breezy-asos-refresh` is a light unit, not
subject to this rule.

**Reboot-catch-up residual.** `daemon-reload` can trigger an immediate
`Persistent=true` catch-up run; a reboot can still fire a relocated heavy
timer inside `P`. Accepted: the flock and slice still apply even then.
AUD-15 amendment (2026-09-22), naming the unit this applies to explicitly:
`breezy-asos-refresh.timer` sets `Persistent=true` (confirmed in the
working tree, `breezy-asos-refresh.timer:25`), so it inherits this same
residual -- a missed 13:30Z tick can fire immediately on the next boot
rather than waiting a full day, which is fine (the flock still serializes
it, and it is a light unit, not subject to the worst-case-runtime rule
above).

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
exactly `breezy-k1-daily.timer` (was `22:30`, MOVED 2026-09-12) and the
now-retired `breezy-offer-gate-daily.timer` (was `22:45`, MOVED 2026-09-12)
(plus this file), correcting the old values above. Four OTHER files still
carry a stale comment cross-reference to that same pre-move schedule, and
are deliberately left unedited because each is protected as an R-5/R-4-gated
zero-diff file (AUD-15, 2026-09-22: `breezy-mb-daily.timer` dropped from
this list -- the file is retired, not merely left stale):
`breezy-pm-crh-v2-tally.timer:13`, `breezy-live-tally.timer:12`,
`breezy-score-live-trials.timer:10`, and
`breezy-quote-tape-ingest.timer:11-12`. Follow-up owner: whoever unblocks
R-5 (the `breezy-live-tally` narrowing ruling) should sweep these four
comments in the same pass.

**v3 tally now scheduled (L-38 closed 2026-09-16).** `pm_us_crh_cont` (the
live v3 strategy) now has its own nightly tally unit,
`breezy-pm-crh-cont-tally.{service,timer}` at 17:25Z (see that section
above) -- a stop that cannot fire is no longer MISSING for this family. The
structural-dead-stop's v3-scoped count wiring (its own
`--covered-listed-station-days`/`--fill-source`/`--fill-since-climate-day`
args, currently `pm_us_crh_v2`-only in the wrapper) remains I5, blocked on
R-4; this item schedules the LD-OBF sequential look and per-stratum
`cell_dead` diagnostics only, not the structural-dead stop itself.

---

## `breezy-fee-evidence-pull` — AUD-02 A0 unattended fee-drift evidence pull (2026-09-25, runtime-fixed after a live TIMEOUT)

`breezy-fee-evidence-pull.service` + `.timer` run the daily, unattended,
unauthenticated public-GET evidence pull of
`docs/plans/backlog/AUDIT_2026-09-21/AUD-02-COMPLETION-PLAN-2026-09-25.md`
Section 2 "A0". Each run invokes `scripts/venue/fee_drift_evidence_pull.py`
directly (no wrapper shell script, no `breezy-studies.lock` -- see below),
which:

1. pages `GET /v1/markets` (category `climate`, `active=true&closed=false&
   archived=false` -- the CURRENTLY tradable universe, not the full
   historical archive) to eof and stores every raw page as the day's
   denominator;
2. reads `feeCoefficient` (and a candidate maker field) straight off each
   listed market's own list entry -- **no per-slug GET in the normal case**.
   A bounded fallback (`MAX_FALLBACK_PER_SLUG_CALLS`, default 20) GETs
   `/v1/market/slug/{slug}` only for a listed entry that itself lacks a
   parseable fee, paced under the SAME native, client-side rate limiter
   every other `get_public` caller already pays into (`QUOTA_KEY_INSTRUMENTS`,
   6 requests/minute). **Runtime-fix note:** the first live run (05:43Z)
   timed out at `TimeoutStartSec=900` because the original design GETed
   every listed slug unconditionally -- measured that day at 4353 total
   climate-category markets, a ~12-hour pull at that pace. Every listed
   market already carries `feeCoefficient` on the list response (0 missing
   observed across all 4353), so the fix removes the per-slug GET from the
   normal path entirely; `worst_case_runtime_secs()` bounds the pathological
   case at 580s, tested against `TimeoutStartSec` with margin;
3. records the taker (`feeCoefficient`) and a candidate maker
   (`makerCommissionsBasisPoints`) field **off the raw wire JSON**, never from
   a parsed `Instrument` (B-7: `parsing.py` writes theta onto both of
   `Instrument`'s flat fee fields, so reading either back would just echo
   theta at itself) -- a missing or unparseable field is recorded with a
   reason, never dropped and never fabricated;
4. writes `data/evidence/fee_drift/<UTC date>/{slugs,summary,manifest.sha256}.json`
   (outside git; see `.gitignore`) or, if the run started inside the
   protected window (below), a bare `incomplete.json` and nothing else.

**Unauthenticated only; no credential of any kind.** The script's
`build_default_client` passes `signer=None` to `PolymarketUSHttpClient`:
`get_public`'s dispatch is unconditionally `authenticated=False`
(`http.py:137-152`), and the `if authenticated:` guard
(`http.py:200-202`) is the only place the signer is ever read -- provably
unreachable here, not merely unused. Verified holding no execution-egress
surface: it imports nothing under `breezy.adapters.polymarket_us.exec`, so
`tests/unit/test_execution_egress_firewall_guard.py`'s X1 scan needs no
widening for this unit.

**Point-in-time guard (AUD-11): not applicable.** The guard polices records
fed into a backtest/replay/study DECISION stream that could look ahead of a
decision instant. This script computes no decision and replays nothing -- it
is a live, wall-clock capture of the venue's current wire state. A future
C2 readout that treats this evidence as a backtest input is the case the
guard actually covers, and must call it there.

**Protected window, enforced by the script itself, not just the timer's
placement.** A run started inside `[16:35Z, 01:15Z)` -- the supervisor's
LAUNCH/mid-day-watch/self-check span -- pulls nothing and marks that day
INCOMPLETE (Rev 2.1 item 2 of the completion plan). This means a
`Persistent=true` catch-up firing late from a reboot degrades to an honestly
INCOMPLETE day instead of an uncontrolled pull, so the timer's own placement
only has to avoid contention, not correctness.

**Light unit; deliberately does NOT take `breezy-studies.lock`.** Unlike
every other study unit in this file, `ExecStart=` invokes the venv Python
directly against the script (`breezy-study-failed@.service`'s own pattern) —
there is no wrapper shell script and no shared-lock acquisition. The plan's
own trade-off: this job is light enough, and bounded independently by its
own native per-key venue rate limits, that serializing it behind the shared
studies lock buys nothing. `MemoryHigh=384M`/`MemoryMax=512M`, between
`breezy-decisions-retention.service` (256M/512M) and
`breezy-position-monitor-report.service` (512M/1G).

**Env files (2026-09-25 follow-up).** Two `EnvironmentFile=` lines, both
non-credential. `%h/.config/breezy/breezy.env` (no `-` prefix — a missing
file fails the unit loudly) supplies `BREEZY_USER_AGENT`, the operator's own
configured contact string, substituted into `ExecStart=` as
`--user-agent "${BREEZY_USER_AGENT}"` rather than hardcoded in the unit; the
script itself refuses an empty/whitespace-only value
(`fee_drift_evidence_pull.py`'s `_parse_args`), so an unset variable fails
the run rather than sending the venue a blank contact header.
`-%h/.config/breezy/alerts.env` (the AUD-15 amendment single-key file) keeps
its `-` prefix, same discipline as `breezy-decision-funnel-digest.service` —
never `breezy-trade.env`/`polymarket.env`/`operator.env`.

**`OnFailure=`.** `OnFailure=breezy-study-failed@%n.service`, same notifier
every other study-adjacent unit declares.

Scheduled at **11:10 UTC** — clear of every occupied `OnCalendar=` on this
host and of the 15-minute quote-tape ingest ticks, and outside the protected
window, pinned by `tests/unit/test_deploy_timer_hours.py`.

**Retention.** `data/evidence/fee_drift/` is outside git
(`.gitignore`); the evidence doc
(`docs/evidence/venue/polymarket_us/FEE_DRIFT_EVIDENCE_2026-09-25.md`)
records each day's raw-directory sha256 manifest instead, and no retention
job may prune this directory.

To activate: symlink both files (`breezy-fee-evidence-pull.service`,
`breezy-fee-evidence-pull.timer`) into `~/.config/systemd/user/` (§2's
pattern), `daemon-reload`, then
`systemctl --user enable --now breezy-fee-evidence-pull.timer` — never
`start` the service directly. **Not activated by this change** — the
coordinator installs and enables it.

**Rollback:** `systemctl --user disable --now breezy-fee-evidence-pull.timer`
and revert the commit. Nothing reads `data/evidence/fee_drift/` except the
evidence doc's own dated notes, so rollback is total.

## `breezy-hypothesis-triage` — AUD-18 nightly hypothesis triage (DEPLOYED 2026-09-25 21:17Z)

The timer fires at 01:20 UTC (`Persistent=true`). The service has no `[Install]` section and is started only by the timer. It is ordered `After=breezy-replay-daily.service`, but does not require it.

```bash
# 1. Confirm alerts.env exists (mode 600). Without it the unit's sink is log-only.
ls -l ~/.config/breezy/alerts.env

# 2. Link both units, following this repo's symlink convention (§2).
ln -s /home/jon/breezy/deploy/systemd/breezy-hypothesis-triage.service ~/.config/systemd/user/
ln -s /home/jon/breezy/deploy/systemd/breezy-hypothesis-triage.timer   ~/.config/systemd/user/
systemctl --user daemon-reload

# Any output from verify is a FAIL (verify exits 0 even on parse errors).
systemd-analyze --user verify ~/.config/systemd/user/breezy-hypothesis-triage.{service,timer}

# 3. Ledger records go through the registrar. Run each writer SEQUENTIALLY (L-50).
.venv/bin/python scripts/analysis/hypothesis_register.py --registered-at 2026-09-20 \
    --freeze-commit <40-hex> --register-forecast-taker-closed
.venv/bin/python scripts/analysis/hypothesis_register.py --registered-at <YYYY-MM-DD> \
    --register-underpowered H-NO-SIDE-2026-09

# 4. Enable the timer. This starts nothing; no stamp file exists yet, so there is no catch-up run.
systemctl --user enable --now breezy-hypothesis-triage.timer
```

Rules and checks:

- **Never start the service by hand inside [16:35Z, 01:15Z).** Linking and enabling start nothing, so both may run at any time.
- **Ledger path:** `~/.local/share/breezy/derived/hypothesis/hypothesis_ledger.jsonl`. The registrar and triage share this default, and neither the unit nor the wrapper sets `BREEZY_DERIVED_ROOT`.
- **"CLEAN no look-taking hypothesis" appears in two cases:** when the ledger is absent, and when every record is zero-look. So check the ledger contents directly with `read_hypothesis_ledger` (L-30).
