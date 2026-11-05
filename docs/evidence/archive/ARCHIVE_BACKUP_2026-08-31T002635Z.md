# P0 — verified off-device backup of both irreplaceable datasets

Date: **2026-08-31T00:26:35Z**. Increment **P0** of
`docs/plans/DATA_CAPTURE_AND_RISK_PLAN.md` §4.P0 (revision 2), the plan's only
T0 item.

**Outcome: COMPLETE.** Both datasets now hold one copy on a second physical
device, and each was proven by a **restored extraction** verified against a
per-file SHA-256 manifest — not by re-reading the source.

| Dataset | Files | Bytes | Restore verify |
|---|---|---|---|
| (a) settlement-alignment archive | 40 | 312,459,225 | **40/40 OK**, 0 mismatched, 0 missing, 0 unexpected |
| (b) quote tape `<catalog_root>/live/` | 37 | 4,925,597 | **37/37 OK**, 0 mismatched, 0 missing, 0 unexpected |

---

## 1. Re-measurement (plan step 1)

`[REPORTED]` figures in the plan re-measured on this host, not carried forward.

```
$ find ~/.local/share/breezy/archive/settlement-alignment-cache -type f | wc -l
40
$ du -sb ~/.local/share/breezy/archive/settlement-alignment-cache
312459225   /home/jon/.local/share/breezy/archive/settlement-alignment-cache   # 299 MiB

$ find ~/.local/share/breezy/catalog/quote_tape/polymarket_us/live -type f | wc -l
37
$ du -sb ~/.local/share/breezy/catalog/quote_tape/polymarket_us/live
4925597     /home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us/live   # 5.1 MiB
```

The archive's 299 MB is 227,617,946 bytes across 10 uncompressed IEM ASOS CSVs
(the four largest are 54–57 MB each) plus 84,841,279 bytes across 30 already-
compressed CLI AFOS `.zip` retrievals. That split explains the 10.4× tar.zst
ratio below: the bulk of the dataset is repetitive METAR text, not the zips.

### The `/tmp` copy — present, and NOT deleted

```
$ ls -d /tmp/breezy-settlement-alignment-cache
/tmp/breezy-settlement-alignment-cache
$ find /tmp/breezy-settlement-alignment-cache -type f | wc -l
40
$ du -sb /tmp/breezy-settlement-alignment-cache
312459225   /tmp/breezy-settlement-alignment-cache
$ stat -c '%n mtime=%y' /tmp/breezy-settlement-alignment-cache
/tmp/breezy-settlement-alignment-cache mtime=2026-08-25 00:40:01 +0000
```

Still intact after the run. `ARCHIVE_RELOCATION_2026-08-27.md:9-11` puts the
`systemd-tmpfiles` sweep at roughly **2026-09-04**; until this backup existed
that copy was the only redundancy. It is left to expire on its own — deleting
it would be irreversible with no upside, and this increment deletes nothing.

### The quote-tape catalog root was resolved, not guessed

The recorder requires `BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG` with no default
(`src/breezy/runtime/settings.py:63`, consumed at `:539-543`) and the streaming
writer lands under `<catalog_path>/<environment>/<instance_id>` with
`environment=Environment.LIVE` pinned in
`src/breezy/runtime/node_config.py:452, :465-473`. The variable was unset in
this shell, so it was supplied explicitly and pointed at the tree the recorder
had actually written:

```
export BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG=/home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us
```

The script refuses to guess: with the variable unset and no `--tape-live-dir`,
it exits non-zero naming the variable. A unit test pins the literal against
`settings.py` by AST, so the two cannot drift.

---

## 2. The device — asserted, not assumed

```
$ findmnt -o TARGET,SOURCE,FSTYPE,SIZE,AVAIL
/              /dev/mapper/ubuntu--vg-ubuntu--lv  ext4  913.3G  528.7G
└─/mnt/storage /dev/sdb1                          ext4    3.6T    3.4T
```

`/` is an LVM volume on `nvme0n1`; `/mnt/storage` is `sdb1` on a **separate
physical disk** (`lsblk`: `sdb` vs `nvme0n1`).

| Path | `os.stat().st_dev` |
|---|---|
| `~/.local/share/breezy/archive/settlement-alignment-cache` (source a) | **64512** |
| `~/.local/share/breezy/catalog/quote_tape/polymarket_us/live` (source b) | **64512** |
| `/mnt/storage` (destination) | **2065** |
| `/tmp` (the expiring copy) | 43 |

**64512 ≠ 2065.** The script computes both numbers itself and raises
`SameDeviceError` when they are equal, so this is enforced rather than
observed. Both sources sit on the same device, which is precisely the risk P0
exists to remove.

**Honest scope.** This is a second **device**, not a second **host**. A truly
off-host target needs a credential the repo does not have and provisioning
money — an operator ceiling, per §4.P0's "Destination" paragraph. This is the
largest correct thing available without one. A host-loss event (fire, theft,
motherboard) still takes both copies. That remains an open, tracked risk.

---

## 3. What was written

Destination: `/mnt/storage/breezy-p0-backup/` (347,685,992 bytes total).

| Artifact | Bytes |
|---|---|
| `settlement-alignment-cache-20260831T002635Z.tar.zst` | 30,181,142 |
| `settlement-alignment-cache-20260831T002635Z.tar.zst.sha256` | 118 |
| `settlement-alignment-cache-20260831T002635Z.files.sha256` | 5,400 |
| `settlement-alignment-cache-20260831T002635Z.restore/` | extracted tree, retained |
| `quote-tape-live-20260831T002635Z.tar.zst` | 105,552 |
| `quote-tape-live-20260831T002635Z.tar.zst.sha256` | 107 |
| `quote-tape-live-20260831T002635Z.files.sha256` | 8,851 |
| `quote-tape-live-20260831T002635Z.restore/` | extracted tree, retained |

Detached tarball digests:

```
00bc0ed422bbe0d6ee9c632f9cccba7b1f7158dc44cfd31cda9e33f13859d214  settlement-alignment-cache-20260831T002635Z.tar.zst
2e8d0f88f18d86600c2f76f11229f4299513345f7e675279bb3116ad7468b37b  quote-tape-live-20260831T002635Z.tar.zst
```

**The archive's per-file manifest travelled UNCHANGED.**
`settlement-alignment-cache-20260831T002635Z.files.sha256` is byte-identical to
the git-tracked `docs/evidence/archive/settlement-alignment-cache.sha256`
(5,400 bytes, 40 lines) — the record established at
`ARCHIVE_RELOCATION_2026-08-27.md:28-31`. It is the record, not a re-derivation
of it.

**The tape's manifest was GENERATED**, because the quote tape has none. 37
entries, one SHA-256 per file, written alongside the tarball and used to verify
the restored extraction. Sample (first and last lines):

```
$ head -1 quote-tape-live-20260831T002635Z.files.sha256
13629a3db43f2ca4bf40636dcd7920366da332f5db5371b07ef20bf54b61afd3  43749af1-0f3e-4de1-8d5e-746c7db072f5/binary_option_1788105944517435203.feather
$ tail -1 quote-tape-live-20260831T002635Z.files.sha256
1ce7d8d138edb0e3dc045567b4c537584d091655e868ef9c914c0a42eed850fa  43749af1-0f3e-4de1-8d5e-746c7db072f5/quote_tick/tc-temp-nychigh-2026-08-30-lt82f.POLYMARKET_US/tc-temp-nychigh-2026-08-30-lt82f.POLYMARKET_US_1788105944974870933.feather
$ wc -l quote-tape-live-20260831T002635Z.files.sha256
37 quote-tape-live-20260831T002635Z.files.sha256
```

The full generated manifest is the file itself, on the destination device.

### The extracted trees are retained

`*.restore/` is not scratch that was swept. It is a **third, plain, directly
readable copy** on the second device, and it is what was verified. Retaining it
costs 317 MB on a 3.4 TB volume and removes the recovery step most likely to
fail under pressure. Consistent with this increment deleting nothing.

---

## 4. Verification — from the RESTORED extraction

### 4a. The primary, checked BEFORE any copy

Ordering is enforced in code: the primary is verified against the git-tracked
manifest *before* the device check and *before* the destination directory is
created. A digest mismatch raises and writes nothing, so backing up an
already-corrupt primary is impossible — corruption cannot be laundered into the
only surviving copy.

Dry run (writes zero bytes), verbatim:

```
$ export BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG=/home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us
$ .venv/bin/python scripts/archive/backup_irreplaceable_data.py \
    --destination /mnt/storage/breezy-p0-backup
[settlement-alignment-cache]
  source            : /home/jon/.local/share/breezy/archive/settlement-alignment-cache
  files             : 40
  bytes             : 312459225
  source st_dev     : 64512
  destination st_dev: 2065
  manifest          : git-tracked
  primary verify    : 40/40 OK, 0 mismatched, 0 missing, 0 unexpected
  mode              : DRY RUN (no bytes written; pass --apply)
[quote-tape-live]
  source            : /home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us/live
  files             : 37
  bytes             : 4925597
  source st_dev     : 64512
  destination st_dev: 2065
  manifest          : GENERATED
  primary verify    : 37/37 OK, 0 mismatched, 0 missing, 0 unexpected
  mode              : DRY RUN (no bytes written; pass --apply)

DRY RUN complete. Zero bytes written. Re-run with --apply.

$ ls -d /mnt/storage/breezy-p0-backup
ls: cannot access '/mnt/storage/breezy-p0-backup': No such file or directory
```

The destination directory did not even come into existence. Dry run is the
default; `--apply` is required to write a byte.

### 4b. The restore, which is the actual claim

```
$ .venv/bin/python scripts/archive/backup_irreplaceable_data.py \
    --destination /mnt/storage/breezy-p0-backup --apply
...
  tarball           : /mnt/storage/breezy-p0-backup/settlement-alignment-cache-20260831T002635Z.tar.zst (30181142 bytes)
  tarball sha256    : 00bc0ed422bbe0d6ee9c632f9cccba7b1f7158dc44cfd31cda9e33f13859d214
  restored to       : /mnt/storage/breezy-p0-backup/settlement-alignment-cache-20260831T002635Z.restore/settlement-alignment-cache
  RESTORE VERIFY    : 40/40 OK, 0 mismatched, 0 missing, 0 unexpected
...
  tarball           : /mnt/storage/breezy-p0-backup/quote-tape-live-20260831T002635Z.tar.zst (105552 bytes)
  tarball sha256    : 2e8d0f88f18d86600c2f76f11229f4299513345f7e675279bb3116ad7468b37b
  restored to       : /mnt/storage/breezy-p0-backup/quote-tape-live-20260831T002635Z.restore/quote-tape-live
  RESTORE VERIFY    : 37/37 OK, 0 mismatched, 0 missing, 0 unexpected

Backup complete and RESTORE-VERIFIED on the destination device.
```

**A backup never restored is a hypothesis.** The `RESTORE VERIFY` lines compare
the *extracted* tree — read back off `/dev/sdb1` through the same tar+zstd path
a real recovery would take — against the manifest. They do not re-read the
source. A tarball that restores to the wrong bytes raises and the backup is not
counted.

### 4c. Independently re-checked with coreutils

Not the script's own arithmetic:

```
$ cd /mnt/storage/breezy-p0-backup
$ sha256sum -c settlement-alignment-cache-20260831T002635Z.tar.zst.sha256
settlement-alignment-cache-20260831T002635Z.tar.zst: OK
$ sha256sum -c quote-tape-live-20260831T002635Z.tar.zst.sha256
quote-tape-live-20260831T002635Z.tar.zst: OK

$ cd settlement-alignment-cache-20260831T002635Z.restore/settlement-alignment-cache
$ sha256sum -c ~/breezy/docs/evidence/archive/settlement-alignment-cache.sha256 | grep -c ': OK$'
40

$ cd ../../quote-tape-live-20260831T002635Z.restore/quote-tape-live
$ sha256sum -c ../../quote-tape-live-20260831T002635Z.files.sha256 | grep -c ': OK$'
37
```

**40/40 and 37/37 OK**, from the restored extractions, under a second tool.

### 4d. Sources untouched

```
$ find ~/.local/share/breezy/archive/settlement-alignment-cache -type f | wc -l   # 40
$ du -sb ~/.local/share/breezy/archive/settlement-alignment-cache                 # 312459225
$ find ~/.local/share/breezy/catalog/quote_tape/polymarket_us/live -type f | wc -l # 37
$ du -sb ~/.local/share/breezy/catalog/quote_tape/polymarket_us/live               # 4925597
```

Identical to §1. The pre-existing `/mnt/storage/breezy-backup/` (an unrelated
2026-08-30T23:06Z rsync copy, 310 MB, no proven restore) was left untouched;
this increment wrote to a disjoint directory.

---

## 5. No re-fetch path exists, by construction

The archive is an IEM-curated post-hoc product. A re-fetch returns a **later
revision**, not the same bytes, which would silently invalidate three published
documents (`ARCHIVE_RELOCATION_2026-08-27.md:13-20`):

- `docs/evidence/settlement_alignment_diagnosis_2026-08-25.md`
- `docs/evidence/settlement_bucket_gate_2026-08-25.md`
- `docs/evidence/settlement_bucket_guard_band_2026-08-26.md`

So re-fetch is **prohibited, not a fallback**, and the prohibition is
structural rather than conventional: a unit test parses the script's AST and
fails if it imports any of `httpx`, `requests`, `urllib`, `urllib3`, `http`,
`aiohttp`, `socket`, `ssl`, `ftplib`, `smtplib`, `telnetlib`, `xmlrpc`,
`webbrowser`, or `breezy.ingest.http`. Adding `import urllib.request` to the
script turns that test red (demonstrated). A second AST test fails on any
`unlink` / `rmtree` / `remove` / `removedirs` / `rmdir` call, so the script
cannot grow a delete path either.

---

## 6. Correction to `ARCHIVE_RELOCATION_2026-08-27.md`

That note's **"Still open"** section (originally `:43-49`, before the
correction below was applied) claimed four scripts still default to the `/tmp`
path. **That is stale**, as `DATA_CAPTURE_AND_RISK_PLAN.md` §0.2 finding H
already recorded. Verified directly:

`scripts/analysis/settlement_alignment_cache.py:8-10` defines

```python
DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR: Final[Path] = (
    Path.home() / ".local/share/breezy/archive/settlement-alignment-cache"
)
```

and `:24-31` (`require_settlement_alignment_cache_dir`) **fails closed**,
raising `SettlementAlignmentCacheError` naming the expected directory rather
than re-fetching into `/tmp`.

All four scripts import both and bind `DEFAULT_CACHE_DIR` to the shared
constant, then gate on the fail-closed requirement:

| Script | imports (line) | `DEFAULT_CACHE_DIR` | fail-closed call |
|---|---|---|---|
| `settlement_alignment_diagnosis.py` | `:22-25` | `:45` | `:489` |
| `settlement_bucket_gate.py` | `:24-27` | `:57` | `:819` |
| `settlement_bucket_guard_band.py` | `:22-25` | `:50` | `:663` |
| `settlement_alignment_study.py` | `:33-36` | `:50` | `:1170` |

The only surviving `/tmp` reference is prose in a docstring
(`settlement_alignment_study.py:1089`) describing the historical location. The
follow-up that note tracked is **closed**. The relocation note has been
corrected in place and points here.

---

## 7. Still open after P0

1. **Second device, not second host.** A host-loss event still takes every
   copy. Needs an operator spend ceiling for off-host storage. Unmitigated.
2. **The backup is a point-in-time snapshot with no schedule.** The quote tape
   grows; this copy captures instance
   `43749af1-0f3e-4de1-8d5e-746c7db072f5` only. Re-running before §4.P1.4's
   convert-then-prune deletes any feather run is a hard prerequisite of that
   increment.
3. **The `/tmp` copy expires ~2026-09-04** on its own. Deliberately not
   deleted; simply no longer load-bearing.

---

## Commands run, in order

```
findmnt -o TARGET,SOURCE,FSTYPE,SIZE,AVAIL
df -h
lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT
find ~/.local/share/breezy/archive/settlement-alignment-cache -type f | wc -l
du -sb ~/.local/share/breezy/archive/settlement-alignment-cache
find ~/.local/share/breezy/catalog/quote_tape/polymarket_us/live -type f | wc -l
du -sb ~/.local/share/breezy/catalog/quote_tape/polymarket_us/live
ls -d /tmp/breezy-settlement-alignment-cache
stat -c '%n mtime=%y' /tmp/breezy-settlement-alignment-cache
python3 -c "import os; print(os.stat(p).st_dev)"        # per path, table in §2

.venv/bin/python -m pytest tests/unit/test_archive_backup.py
.venv/bin/python -m ruff check scripts/archive tests/unit/test_archive_backup.py
.venv/bin/python -m mypy scripts/archive tests/unit/test_archive_backup.py

export BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG=/home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us
.venv/bin/python scripts/archive/backup_irreplaceable_data.py --destination /mnt/storage/breezy-p0-backup
.venv/bin/python scripts/archive/backup_irreplaceable_data.py --destination /mnt/storage/breezy-p0-backup --apply

cd /mnt/storage/breezy-p0-backup
sha256sum -c settlement-alignment-cache-20260831T002635Z.tar.zst.sha256
sha256sum -c quote-tape-live-20260831T002635Z.tar.zst.sha256
cd settlement-alignment-cache-20260831T002635Z.restore/settlement-alignment-cache
sha256sum -c ~/breezy/docs/evidence/archive/settlement-alignment-cache.sha256
cd ../../quote-tape-live-20260831T002635Z.restore/quote-tape-live
sha256sum -c ../../quote-tape-live-20260831T002635Z.files.sha256
```

Nothing was deleted. Nothing was committed; the coordinator commits by explicit
path.
