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

Four scripts still default to the `/tmp` path:
`settlement_alignment_diagnosis.py:39`, `settlement_bucket_gate.py:42`,
`settlement_bucket_guard_band.py:45`, and `settlement_alignment_study.py:45` —
the last pointing at `scripts/analysis/cache/settlement_alignment`, which does
not exist at all.

Until those defaults move, a future run silently re-fetches into `/tmp` and the
problem returns. Tracked as the follow-up to this note.

`settlement_bucket_guard_band_2026-08-26.md:4` also records a `--catalog-base`
inside a *session scratchpad* under `/tmp/claude-1000/...`, which is more
ephemeral still. That snapshot is not recovered here and may already be gone.
