<!-- Generated: 2026-08-23 | Commit: 07c2344 | Files scanned: 12 | Token estimate: ~2800 -->

# NWS Collection Runtime Runbook

**For:** Breezy weather-ingest operator, on-call 3am troubleshooting  
**Time-critical facts:** UA-trap halt requires manual acknowledgement; delaying blocks all automatic collection  
**Failing closed:** All safety halts are permanent until operator intervention

---

## 1. Environment Variables

**Required:**

| Variable | Purpose | Format/Example | Failure if wrong |
|---|---|---|---|
| `BREEZY_CATALOG_BASE` | Root of NWS data directory (state DB, catalogs, witness marker live here) | `/var/lib/breezy/catalog` | Missing: SettingsError exit 2. Not writable: OSError exit 2. Symlinked: writer lock fails (see §9). |
| `BREEZY_USER_AGENT` | HTTP User-Agent string with a monitored operator contact | `breezy-weather-ingest/0.1 (+mailto:ops@example.com)` | Missing or blank: UserAgentConfigurationError, startup fails exit 2. Read by `ingest/http.py`, not `settings.py`. NWS uses this to contact the operator on abuse. |

**When `BREEZY_SITES` IS set**, its values are matched CASE-SENSITIVELY and EXACTLY against the
table keys in `src/breezy/registry/sites.toml`.** `SiteRegistry.settlement_site`
(`registry/sites.py:313-324`) does a plain dict lookup on the `(venue, city)`
tuple: it never lower-cases, never aliases a venue name, and never substitutes
a neighbour. The registry's keys are `[sites.<venue>.<CITY>]`, so today the
only legal values are:

```
polymarket_us:NYC   polymarket_us:SFO   polymarket_us:MIA
polymarket_us:MDW   polymarket_us:LAX
```

Verified live on 2026-08-24: `BREEZY_SITES=polymarket:nyc` — a plausible-looking
lowercase/short-venue spelling — exits **2** with
`breezy: configuration error: configured site polymarket/nyc is not in the registry`.
There is no Kalshi entry in the registry yet, so `kalshi:…` is not a valid
value either.

**Optional:**

| Variable | Default | Type/Range | Notes |
|---|---|---|---|
| `BREEZY_TRADER_ID` | `BREEZY-001` | Two non-empty hyphen-separated segments, e.g. `WEATHER-PROD` | Malformed → NodeConfigError exit 2. Unvalidated value panics Nautilus in Rust (SIGABRT 134, uncatchable); pre-validation at `runtime/node_config.py:82-100` prevents this. |
| `BREEZY_SITES` | **all sites in the registry in force** (today the five `polymarket_us` cities) | comma-separated `venue:city` pairs, e.g. `"polymarket_us:NYC,polymarket_us:SFO"` | Which cities exist is a VENUE FACT, so unset means "derive" (G-19 B4), not "fail". Set it only to NARROW a run deliberately. Blank/malformed: startup fails exit 2. Not in the registry: exit 2 with `configured site <venue>/<city> is not in the registry`. |
| `BREEZY_STATE_DB` | `{BREEZY_CATALOG_BASE}/state/breezy-state.sqlite3` | Path | SQLite file; must not be on a network filesystem. Created if missing. |
| `BREEZY_POLL_INTERVAL_SECONDS` | `300` (5 min) | Positive integer | Polling frequency per site. Governs how fast missed products can be caught; lower = faster catch-up, higher = lower request rate. NOT derived from the CLI issuance cadence — see the reasoning at `runtime/settings.py:_DEFAULT_POLL_INTERVAL_SECONDS`. |
| `BREEZY_PARSE_TIMEOUT_MS` | `250` | Positive integer | Timeout for CLI product text parsing. Exceeds → product marked OVERSIZE_OR_PARSE_TIMEOUT, site degraded. |
| `BREEZY_LOG_LEVEL` | `INFO` | `OFF`, `TRACE`, `DEBUG`, `INFO`, `WARNING`, `ERROR` | Nautilus kernel log level. `CRITICAL` is rejected and startup fails exit 2. stdlib `logging` records are bridged to Nautilus by the console entrypoint. |
| `BREEZY_ALLOW_PROXY_ENV` | (check proxy env) | (any value) | Set to `"1"` to allow HTTP_PROXY/HTTPS_PROXY env vars. Unset or `"0"` → block proxy env (secure default). |
| `BREEZY_REGISTRY_PATH` | (none) | Path to `registry/sites.toml` | Optional override; if unset, embedded registry used. |
| `BREEZY_HEALTH_SNAPSHOT_DIR` | (none — feature off) | **Absolute** directory path | Directory the per-site health snapshots are written into, one file per site: `health-<venue>.<city>.json`, mode 0600. Unset = no file is written at all. Blank, relative, or containing a NUL byte → SettingsError exit 2. |
| `BREEZY_ALERT_WEBHOOK_URL` | (none) | `https://…` URL, no userinfo | Read by `runtime/health.py`, not `settings.py`. Unset → the process uses `LoggingAlertSink` and builds **no** HTTP client and **no** TLS context. Exactly ONE sink is built per process and shared by all five actors. |


### 1a. Health snapshots — "stale file means the process is dead"

`BREEZY_HEALTH_SNAPSHOT_DIR` holds **one file per site**, not one file for
the process:

```
/var/lib/breezy/health/health-polymarket_us.NYC.json
/var/lib/breezy/health/health-polymarket_us.SFO.json
…
```

Per-site because an actor knows only its own site — five actors sharing one
path would overwrite each other every poll cycle and the file would report
whichever site wrote last. Each file is rewritten once per poll cycle via
`write_snapshot_atomic` (mkstemp → fsync → `os.replace`), so a reader never
observes a partial document.

**Liveness checks (both, they answer different questions):**

| Question | Check | Meaning |
|---|---|---|
| Is the PROCESS alive? | `max(mtime)` over `BREEZY_HEALTH_SNAPSHOT_DIR/health-*.json` older than `2 × BREEZY_POLL_INTERVAL_SECONDS` | Dead or wedged process. Nothing else makes every file go stale at once. |
| Is a SITE alive? | any individual `health-<venue>.<city>.json` older than `2 × BREEZY_POLL_INTERVAL_SECONDS` while others are fresh | That one site's poll cycle is wedged; the rest of the process is fine. |
| Is the GAP LEDGER readable? | `ledger_unavailable` is non-`null` in any site's snapshot | **`open_gaps` in that snapshot is NOT authoritative.** Reconciliation is failing, so the list is unknown, NOT empty. Revision detection is dead for that site until this clears. |

**`ledger_unavailable` is the one field that must never be read as "absent means
fine".** The key is ALWAYS emitted: `null` means the ledger was read
successfully; a non-`null` string names the failure class. A site whose ledger
is unreadable will otherwise present as perfectly healthy -- `open_gaps: []`,
fresh mtime, gate OPEN -- while a superseded NWS final goes undetected. A
CRITICAL `LEDGER_UNAVAILABLE` alert is also emitted on the alert sink, but the
webhook sink is UNSET by default, so on a default deployment this file is the
only place the condition is visible.

The detail string is deliberately scrubbed at capture (class name, then a
<=120-char de-identified tail): paths, URLs and the `mailto:` contact are
dropped whole, so it names the failure without carrying PII or filesystem
layout into this artifact or off-host.

`schema_version` is **2** as of the `ledger_unavailable` addition. A consumer
pinned to schema 1 will not see this field.

Example:

```bash
DIR=/var/lib/breezy/health
NOW=$(date +%s)
# process-level: newest file
NEWEST=$(stat -c %Y "$DIR"/health-*.json | sort -n | tail -1)
echo "process silent for $(( NOW - NEWEST ))s"
```

### 1b. Poll stagger

The five sites do **not** poll simultaneously. The composition root assigns
each site a deterministic phase offset — `index × poll_interval ÷ site_count`,
so 0/60/120/180/240s on the 300s default — and feeds it to Nautilus's own
`Clock.set_timer(start_time=…)`. The steady-state cadence is unchanged: every
site still polls once per `BREEZY_POLL_INTERVAL_SECONDS`.

Offsets are derived from the site's **position in `BREEZY_SITES`**, so they
are stable across restarts and an incident is reproducible. Reordering or
adding entries to `BREEZY_SITES` reassigns offsets; that is expected and
harmless, but note it when correlating logs across a config change.

This exists to keep five concurrent requests per interval — under a single
`BREEZY_USER_AGENT` — from tripping the NWS UA trap (§ below), which latches
**all** sites and clears only by manual operator action.

---

## 2. Supervision: systemd Unit

Place as `/etc/systemd/system/breezy-nws-ingest.service`:

```ini
[Unit]
Description=Breezy NWS Weather Data Ingest
Documentation=docs/core/RUNBOOK_NWS_COLLECTION.md
After=network-online.target
Wants=network-online.target
StartLimitBurst=3
StartLimitIntervalSec=300

[Service]
Type=simple
User=_breezy
Group=_breezy
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
UMask=0077

WorkingDirectory=/var/lib/breezy
StateDirectory=breezy
CacheDirectory=breezy

Environment="BREEZY_CATALOG_BASE=/var/lib/breezy/catalog"
Environment="BREEZY_SITES=polymarket_us:NYC"
Environment="BREEZY_USER_AGENT=breezy-ingest/1.0 (+mailto:ops@example.com)"

# Use the full path to breezy entrypoint
ExecStart=/opt/breezy/bin/breezy

# Restart policy
Restart=always
RestartSec=5
StartLimitBurst=3
StartLimitIntervalSec=300

StandardOutput=journal
StandardError=journal
SyslogIdentifier=breezy-nws

[Install]
WantedBy=multi-user.target
```

**Key hardening:**
- `NoNewPrivileges=yes` — process cannot gain capabilities
- `ProtectSystem=strict` — /usr, /etc, /bin read-only (catalog_base must be outside these)
- `UMask=0077` — state/catalog are owner-only (defeats symlink tricks in shared code)
- `StateDirectory=breezy` — ensures parent is owner-only on creation
- **Environment=** values ARE world-readable via `systemctl cat` and `/proc/<pid>/environ` — this is acceptable because `BREEZY_USER_AGENT` is not a secret (it's a contact email for NWS). Do NOT put real secrets in this unit.

**Create the service user:**
```bash
sudo useradd -r -s /usr/sbin/nologin -d /var/lib/breezy _breezy
sudo mkdir -p /var/lib/breezy/{catalog,state}
sudo chown -R _breezy:_breezy /var/lib/breezy
sudo chmod 750 /var/lib/breezy
sudo systemctl daemon-reload
```

---

## 3. Never Start a Second Process

**Two independent failure mechanisms enforce this:**

### 3.1 SharedIngestState process-slot claim (app-level)

`ingest/shared_state.py:278-626` — one global `_LIVE_INSTANCE` per Python process. On construction:
- First process: instance claimed, runs normally
- Second process: `DuplicateSharedIngestStateError` raised, startup fails exit 1

**Symptom:** Second process startup logs `DuplicateSharedIngestStateError`, then exits.

### 3.2 SQLite state-DB concurrency (storage-level)

`runtime/sqlite_store.py` — SQLite with `PRAGMA synchronous=FULL` and WAL mode. Concurrent writes:
- First process: holds database connection, writes durable
- Second process: SQLite enforces single-writer rule; second process blocks on writer availability

**Symptom:** Second process hangs indefinitely on `set()` call with no diagnostic. Appears "stuck". After 5s timeout (line 61), connection attempt fails with `sqlite3.OperationalError`.

**What to do if second process is wedged:**

1. Verify only one systemd service should be running:
   ```bash
   systemctl status breezy-nws-ingest
   ```
2. Find all Python processes running breezy:
   ```bash
   pgrep -a "python.*breezy" | grep -v grep
   ```
3. If two or more: kill the errant one (use SIGKILL only if it won't respond to SIGTERM):
   ```bash
   sudo kill -9 <pid>
   ```
4. Verify first process is still healthy. If it crashed, systemd restarts it (Restart=always).

---

## 4. Never Run Staging Against Live api.weather.gov

**The hazard:** A staging process with `BREEZY_SITES=staging:test` and a different `BREEZY_CATALOG_BASE` (so it has separate state) would start successfully. It would then:

1. Make requests to `api.weather.gov` under the configured `BREEZY_USER_AGENT`
2. Be subject to the **cross-site request-rate policy** — NWS enforces burst limits *per User-Agent*, not per process
3. See only half the rate it would if running alone, because the production process is making the other half
4. Under that reduced apparent rate, trip the UA-trap (403 burst across multiple sites) even sooner than normal

**Result:** Both production and staging get the same global UA-trap halt, and neither recovers until an operator manually clears it.

**Enforcement:**
- Never run two processes with the same `BREEZY_USER_AGENT` pointing to `api.weather.gov`
- If you must test against live api.weather.gov, use a **distinct User-Agent** (e.g., `breezy-staging/...`)
- Better: use **fixture-backed soak** (WI-14) with mocked NWS responses

---

## 5. UA-Trap Manual Clear Procedure

### 5.1 Detect the UA-trap latch

Check the gate status via logs:
```bash
journalctl -u breezy-nws-ingest -n 100 | grep -i "ua_trap\|403"
```

Or query the state database directly (advanced):
```python
import sqlite3
db = sqlite3.connect('/var/lib/breezy/catalog/state/breezy-state.sqlite3')
cursor = db.execute("SELECT key, value FROM state WHERE key = 'gate:__global__'")
import json
row = cursor.fetchone()
if row:
    state = json.loads(row[1])
    print(f"UA-trap blocked: {state.get('ua_trap_blocked')}")
```

### 5.2 Verify before clearing

Before calling `acknowledge_ua_trap_resolved()`, verify:

1. **Is the code/config actually wrong?** The trap triggers on a **genuine 403 burst** (5+ distinct sites reporting 403 within 60 seconds). It is not a transient glitch:
   - Check NWS status page: https://status.weather.gov/
   - Check logs for your User-Agent being blocked (search for "forbidden_403")
   - Verify `BREEZY_USER_AGENT` is valid and properly formatted

2. **Have you fixed the root cause?** If the trap was a malformed User-Agent:
   ```bash
   sudo systemctl stop breezy-nws-ingest
   # Fix BREEZY_USER_AGENT in /etc/systemd/system/breezy-nws-ingest.service
   sudo systemctl daemon-reload
   ```

### 5.3 Clear the latch (programmatic)

Use the Breezy shell or Python REPL:

```python
from breezy.runtime.composition import ingest_runtime
from breezy.runtime.settings import load_settings

settings = load_settings()  # reads env vars
with ingest_runtime(settings) as runtime:
    shared = runtime.shared
    gate = shared.gate
    gate.acknowledge_ua_trap_resolved(detail="User-Agent corrected to breezy-ingest/1.0")
```

Or via a CLI helper (if available in your deployment):
```bash
sudo -u _breezy breezy --acknowledge-ua-trap-resolved "Fixed User-Agent"
```

**Output:** Logs a WARNING: `"UA-trap 403 condition manually cleared: …"`

### 5.4 What happens after clearing

1. Gate latch `ua_trap_blocked` → False
2. All per-site abuse-403 evidence cleared (`abuse_403_degraded`, `abuse_403_last_ns`) across every configured site
3. Sites revert to their prior state (OPEN/DEGRADED/BLOCKED based on other factors)
4. Polling resumes normally

**Critical timing:** While the latch is set, **`network_allowed()` returns False for every site** (`ingest/nws_actor.py:568-639`), which blocks `poll_once()` from running. No automatic catch-up happens. **Every minute the latch is set, the operator loses ~7 days of api.weather.gov retention** (see §7). Delay is expensive.

---

## 6. Availability Posture: Fail-Closed by Design

Breezy treats corrupted or tampered persisted state as a fatal condition, not a recoverable defect.

### 6.1 Bootstrap witness (detects whole-file deletion)

On process start, `runtime/bootstrap_witness.py:100-152` runs `enforce_bootstrap_witness()`:

- **First boot:** Stamps both the state-DB (key `runtime:bootstrap_witness`) and a marker file (`.breezy-bootstrap-witness`) under `BREEZY_CATALOG_BASE`
- **Subsequent boots:** Verifies witness in store and marker file exist together
- **Detection:** If marker file exists but store witness is absent (the state-DB file was deleted and recreated):
  - Replants the gate's bootstrap sentinel (`gate:__bootstrap__`) with no global entry
  - `SettlementGate._load_global()` detects this and reports `STATE_STORE_TAMPERED`
  - Every site BLOCKs under `STATE_STORE_TAMPERED` reason
  - No automatic recovery; requires `acknowledge_ua_trap_resolved()` (same verb as UA-trap)

### 6.2 In-store bootstrap sentinel (detects row deletion)

`ingest/gate.py:62-80` — a separate sentinel `gate:__bootstrap__` stored in the state-DB alongside global entry `gate:__global__`. If global entry is deleted but sentinel survives:
- Detects "whole DB row vanished" vs. "store was never written"
- Treats row deletion as tampering
- Blocks collection, same as above

### 6.3 Residual limit (documented, not overclaimed)

**Undetectable:** Deleting **both** the state-DB file AND the witness marker file (or restoring both from a stale backup taken together). This raises the bar from "delete one file" to "delete two independent files", but it is not absolute defense. If both are deleted, the next boot is indistinguishable from first boot and the system comes up OPEN.

**Stated plainly:** Do not manually delete or restore these files without understanding that you are accepting undetectable tampering risk.

---

## 7. Retention and Permanent Loss

### 7.1 NWS retention window (assumption, not guarantee)

The registry (`registry/sites.toml:136-294`) records `no_data_fallback_days = 7` for every site. This is a **venue settlement rule, not an api.weather.gov API guarantee**.

- **What it means:** If no product publishes for 7 days, the venue may declare default settlement instead of waiting
- **What it does NOT mean:** api.weather.gov keeps any product for 7 days (NWS has never published this SLA)

### 7.2 What "permanently lost" means

Once a product issuance time falls outside NWS retention:
- No polling can retrieve it
- No backfill in this phase recovers it
- Settlement must use a fallback or default

### 7.3 Impact of a UA-trap halt

**While `ua_trap_blocked=True`:**
- `network_allowed()` returns False
- No polling happens (automatic catch-up disabled)
- Products issued during the halt cannot be fetched after the halt ends
- If the halt lasts >7 days, those products are permanently lost

**Example:** Halt set at 2026-08-23 12:00 UTC, cleared at 2026-08-30 18:00 UTC (7 days 6 hours):
- Products issued 2026-08-23 12:00–2026-08-30 12:00 cannot be fetched
- Products issued 2026-08-30 12:00 onward can be fetched
- First 6 hours of 2026-08-30 products are lost forever

**Action:** Clear UA-trap latch within hours, not days.

---

## 8. Shrink-to-NYC Retreat Path

If collection from all configured sites fails and you need to verify the system itself works, shrink to a single reliable site:

```bash
sudo systemctl stop breezy-nws-ingest

# Edit the unit
sudo systemctl edit breezy-nws-ingest
# Change:   Environment="BREEZY_SITES=polymarket_us:NYC,polymarket_us:SFO,…"
# To:       Environment="BREEZY_SITES=polymarket_us:NYC"

sudo systemctl daemon-reload
sudo systemctl start breezy-nws-ingest

# Verify logs
journalctl -u breezy-nws-ingest -f | grep -i "poll\|success\|blocked"
```

This removes all sites except NYC, which:
- Reduces request volume to NWS by 80% (five sites → one)
- Simplifies debugging (single Actor, single gate entry)
- Can be done without code change or redeploy

Restore by reverting the env var and restarting.

---

## 9. Filesystem Posture

### 9.1 Directory permissions

Both `BREEZY_CATALOG_BASE` and `BREEZY_STATE_DB` parent directories **must be owner-only** (`mode 750` or stricter):

```bash
sudo chmod 750 /var/lib/breezy
sudo chmod 750 /var/lib/breezy/state  # if BREEZY_STATE_DB is separate
ls -ld /var/lib/breezy /var/lib/breezy/state
# Expected: drwxr-x--- _breezy _breezy
```

**Why:** The code already uses `O_NOFOLLOW` and `O_CREAT | O_EXCL` to defend against symlink attacks on the writer lock and witness marker. A world-writable parent defeats these: an attacker can create the symlink to any path before the process starts, and the defenses see a pre-existing file and proceed.

### 9.2 Lock file safety

`runtime/bootstrap_witness.py` and `persistence/catalog.py` create `.breezy-bootstrap-witness` and `.breezy-writer.lock` under `catalog_base`. These files are **not secrets** (they contain only a marker byte).

**Never manually delete or `touch` a lock file while the process is running.** Why:
- Deleting it while a live flock is held does not release the lock (the kernel holds it on the file descriptor, not the filename)
- Replacing it with a symlink before the process tries to open it again can confuse `O_NOFOLLOW` on the next boot

**Safe process termination:** Use SIGTERM (graceful) or SIGKILL (wedged). The kernel unconditionally releases the flock on process death (`sqlites/store.py` uses SQLite, not flock, but the principle applies).

---

## 10. Log Rotation and Retention Policy

### 10.1 Disk growth sources

- **Nautilus logging (dominant):** If `LoggingConfig` has `file_config` enabled with no rotation, a months-long LIVE process accumulates gigabytes (measured on real runs)
- **Catalog data:** Single-digit MB/year across all five cities (negligible)
- **State-DB:** Stays under 1 MB

### 10.2 Recommended policy

Enable systemd journal rotation (already active on most systems):

```bash
# Check current journal retention
journalctl --disk-usage
sudo journalctl --vacuum-time=30d  # keep 30 days only
```

**Or** configure Nautilus `LoggingConfig` with file-based rotation in your deployment config. Contact the Nautilus documentation for `LogConfig.file_config` rotation settings.

**Recommended minimum:** Keep 30 days of logs (recovery after a multi-week outage). Monitor disk usage weekly.

---

## 11. Troubleshooting Quick Reference

| Symptom | Check | Action |
|---|---|---|
| Process exits immediately | `journalctl -u breezy-nws-ingest -n 20 \| grep -i error` | If SettingsError/NodeConfigError → fix env vars. If OSError → check paths/permissions. |
| Second process hangs | `pgrep -a "python.*breezy"` | One or more wedged? Kill the extra with `sudo kill -9 <pid>`. |
| All sites BLOCKED for days | `journalctl \| grep -i "ua_trap"` | Check if UA-trap is set. If yes, clear via §5. |
| "NEVER_POLLED" after restart | `journalctl \| grep -i "successful_poll"` | Expected on first boot. After first successful poll, site transitions to OPEN. |
| "STATE_STORE_TAMPERED" | `ls -la /var/lib/breezy/.breezy-bootstrap-witness` | Witness marker missing or stale DB file. Verify backup integrity. Call `acknowledge_ua_trap_resolved()` to retry. |

---

## 12. Escalation and Support

- **NWS service issues:** Check https://status.weather.gov/ and `BREEZY_USER_AGENT` contact email for NWS notices
- **Code defects:** Consult `docs/core/PROGRESS.md` (known outstanding issues) and `docs/plans/archive/NWS_COLLECTION_RUNTIME_PLAN_ADDENDUM.md` (stale plan claims)
- **Operator manual action needed:** `acknowledge_ua_trap_resolved()` is the only persistent halt that requires operator intervention; other blocks clear automatically on one successful poll
