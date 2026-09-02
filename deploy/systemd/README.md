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
   systemctl --user list-timers breezy-k1-daily.timer --no-pager   # next run 22:30Z
   ```
   `--now` starts the *timer*, not the service. To prove the study runs without
   waiting for 22:30Z: `systemctl --user start breezy-k1-daily.service` and read
   `~/.local/share/breezy/k1/k1_daily.log`.

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

If `breezy-quote-tape.service` has entered `failed` after exhausting its start
limit, clear it with `systemctl --user reset-failed breezy-quote-tape.service`
before trying again.

## 6. Design notes (why these values)

- **`KillSignal=SIGTERM`, `TimeoutStopSec=120`.** SIGTERM is what the clean path
  handles (`kernel.py:558-572`, reached from `:284-287`) and a clean stop is the
  only thing that writes the end-of-stream marker. The writer flushes every 10 s
  (`node_config.py:292`), so the stop must be allowed to flush and close; 120 s
  is deliberate headroom over systemd's 90 s default, because the timeout
  expiring means SIGKILL and SIGKILL means the silent-zero-rows failure.
- **`RestartSec=30`** matches the supervisors' 30 s poll — the cutover changes
  the supervisor, not the recovery latency.
- **`StartLimitBurst=20` / `StartLimitIntervalSec=3600`** *diverges* from the NWS
  unit's 3/300 s. At `RestartSec=30`, 3-in-300 s is exhausted by a ~2-minute
  network outage and would abandon capture permanently. 20/hour still fails
  closed on a persistent exit-2 misconfiguration (~10 min) and still bounds a hot
  loop. This is the one place data-irreplaceability outranks convention-mirroring.
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

## G-14 status — DONE 2026-09-02T04:38Z

- **ACTIVATED AND VERIFIED.** Units symlinked into `~/.config/systemd/user/`,
  `daemon-reload`ed, `systemd-analyze --user verify` silent (= clean).
  `breezy-quote-tape.service` active, `NRestarts=0`; `breezy-k1-daily.timer`
  enabled, next fire 22:30Z. `Linger=yes`, so both survive reboot and logout.
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
- **Deliberate divergence from `breezy-nws-ingest.service`:**
  `StartLimitBurst=20`/`StartLimitIntervalSec=3600` instead of 3/300 s, so a
  short network outage cannot permanently abandon capture (§6).
- **Carried forward as a real defect (not a cutover concern):** the retired
  supervisors polled `pgrep -f "bin/breezy-quote-tape"`, which also matches
  `breezy-quote-tape-preflight` — a preflight running during an outage read as
  "recorder is up" and would have SUPPRESSED the restart. Any future
  process-liveness check must use `pgrep -x -f "<full ExecStart>"`.
