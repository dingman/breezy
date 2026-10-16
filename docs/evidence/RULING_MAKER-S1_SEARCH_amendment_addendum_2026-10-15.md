# RULING_MAKER-S1_SEARCH_amendment_addendum_2026-10-15

Status: **FINAL**. Dated addendum under `docs/evidence/RULING_MAKER-S1_SEARCH_declaration_amendment_2026-10-13.md` §3 (non-result void re-run rule). Decision owner per Pre-Auth; no operator cap involved.
Amendment sha (unchanged): `cf9a4dad826f61016b2616d32fbc1ca82f73b339b7da8e74fb6a9f25f4c818d0`.

## Voided run

voided_run_id: s2v-20261015T073314Z

- Launched 2026-10-15 07:33:14Z as unit `breezy-maker-s2-verdict` (MemoryMax 4G, RuntimeMaxSec 21600).
- Cause: **OOM, cgroup MemoryMax 4 GiB, during the Stage-0 preamble** (probe frame ledger plus the whole-instance `DepthTruncation` query). No station-day was scored; the run never reached `progress.jsonl`.
- Classification: non-result void (amendment §3: "S-5, S-6, S-7, E4 disk, OOM, crash, host kill").
- Voided by hand 2026-10-15 08:12:18Z via `maker_stage0_ledger.void_run_dir`; ledger void entry `files: []`, `tree_sha256 e3b0c442…b855` (empty tree).

## code_sha

- Old (voided run): `ae7801c1ce6bc0829134ffc9c5a00d953ddd38db`.
- New (re-run): `e6184e5dd5de7f7c76beacc2f81018afdc63cf59` — S-5 preamble memory bound (probe frame spill, chunked depth/truncation queries, heap release; merges 288e0133, e6184e5d), verdict-blind, PMR/python blind-reviewed, full gate green, bench 4 and bench 8 S-5 pass (projected peak 2.50 GB).

## Attestation

No fill, rate or label output of the voided run was read: none was produced. The `.void` directory holds no `scored_episodes.csv`, `s3_inputs.json` or `verdict.*`, and `episodes.jsonl` was never opened.

## Relaunch

`--addendum docs/evidence/RULING_MAKER-S1_SEARCH_amendment_addendum_2026-10-15.md --addendum-sha <sha256 of this file>`, same `AMEND_SHA`, same truth and NBP pins, same frozen date set. This file is committed verbatim with the step-10 evidence; it is never edited afterwards.
