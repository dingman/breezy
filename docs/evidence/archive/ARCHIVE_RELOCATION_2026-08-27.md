# Settlement-alignment archive — relocated off `/tmp`

Date: 2026-08-27. Action taken by the coordinator, not a study step.

## The risk

The 299 MB IEM/CLI archive that three published evidence documents rest on was
living in `/tmp/breezy-settlement-alignment-cache`. This host runs
`systemd-tmpfiles` with `q /tmp 1777 root root 10d` — a **10-day** sweep. The
archive's mtimes are 2026-08-25, so it was due for deletion around
**2026-09-04**, roughly eight days after this was noticed.

It cannot be honestly re-fetched. IEM is a curated post-hoc product: a re-fetch
returns a *later revision*, not the same bytes, so the published documents would
become unreproducible rather than merely re-runnable.

Documents that depend on it:
- `docs/evidence/settlement_alignment_diagnosis_2026-08-25.md`
- `docs/evidence/settlement_bucket_gate_2026-08-25.md`
- `docs/evidence/settlement_bucket_guard_band_2026-08-26.md`

Found by the agent pre-registering the decision-time clearance study, while
verifying data availability rather than assuming it. It is recorded there as
prerequisite P0.

## What was done

Copied to `~/.local/share/breezy/archive/settlement-alignment-cache/`, alongside
the existing catalog, with a SHA-256 manifest at
`~/.local/share/breezy/archive/settlement-alignment-cache.sha256` (also copied
into this directory as the in-repo record).

Verified: 40/40 files `OK` at the destination, and **0 mismatches** when the
destination manifest is checked against the `/tmp` original — byte-identical.

The `/tmp` copy was NOT deleted. It expires on its own; deleting it would be an
irreversible act with no upside.

Contents: five IEM ASOS CSVs (`station,valid,metar`, `tz=Etc/UTC`) with row
counts matching `settlement_alignment_diagnosis_2026-08-25.md:50-56` exactly,
plus 35 CLI AFOS retrievals.

## Still open

### CLOSED 2026-08-31 — the `/tmp` defaults. This section was stale.

This note originally claimed four scripts still defaulted to the `/tmp` path
(`settlement_alignment_diagnosis.py:39`, `settlement_bucket_gate.py:42`,
`settlement_bucket_guard_band.py:45`, `settlement_alignment_study.py:45`) and
that a future run would silently re-fetch into `/tmp`. **That is no longer
true, and the claim is corrected here rather than left to mislead.**

All four now route through a single shared module,
`scripts/analysis/settlement_alignment_cache.py`, which at `:8-10` defaults to
this directory:

```python
DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR: Final[Path] = (
    Path.home() / ".local/share/breezy/archive/settlement-alignment-cache"
)
```

and which **fails closed** at `:24-31` — `require_settlement_alignment_cache_dir`
raises `SettlementAlignmentCacheError` naming the expected directory rather than
re-fetching anything:

| Script | imports (line) | `DEFAULT_CACHE_DIR` | fail-closed call |
|---|---|---|---|
| `settlement_alignment_diagnosis.py` | `:22-25` | `:45` | `:489` |
| `settlement_bucket_gate.py` | `:24-27` | `:57` | `:819` |
| `settlement_bucket_guard_band.py` | `:22-25` | `:50` | `:663` |
| `settlement_alignment_study.py` | `:33-36` | `:50` | `:1170` |

The only surviving `/tmp` reference is prose in a docstring
(`settlement_alignment_study.py:1089`) describing the historical location.
`DATA_CAPTURE_AND_RISK_PLAN.md` §0.2 finding H records the same correction.
**The follow-up this note tracked is closed.**

### Superseded — this archive now has a verified off-device backup

`docs/evidence/archive/ARCHIVE_BACKUP_2026-08-31T002635Z.md` (increment P0)
records a `.tar.zst` copy on `/dev/sdb1` (`st_dev` 2065, against the primary's
64512), verified **40/40 from a restored extraction** against the manifest at
`:28-31` above. The quote tape under `<catalog_root>/live/` is covered by the
same run (37/37). The `/tmp` copy is still not deleted and is no longer the
only redundancy.

### Genuinely still open

`settlement_bucket_guard_band_2026-08-26.md:4` records a `--catalog-base`
inside a *session scratchpad* under `/tmp/claude-1000/...`, which is more
ephemeral still. That snapshot is not recovered here and may already be gone.

The P0 backup is a second **device**, not a second **host**: a host-loss event
still takes every copy. Off-host storage needs an operator spend ceiling.
