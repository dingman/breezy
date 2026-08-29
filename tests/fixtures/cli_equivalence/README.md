# CLI Equivalence Fixtures

Golden pair for `docs/plans/CLI_BACKFILL_PLAN.md` increment I-1.

- Station: MIA
- Climate day: 2026-08-24
- Issuance instant: 2026-08-25T08:27:00Z
- Live fixture: `MIA_20260824_live.txt`
- Archive fixture: `MIA_20260824_archive.txt`
- Live transmission-sequence line: `000`
- Archive transmission-sequence line: `100 ` (stripped value `100`)
- Live SHA-256: `5107e7fb9cd56d2ee49b3cad302dee76f72a0e9f42c7f1b4ebec988ea5dac87f`
- Archive SHA-256: `fd57ce50dea7295624651e7034f9a4de84843b0974439f43cc391fa9ce9627a7`
- IEM source URL: `https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py?pil=CLIMIA&fmt=zip&order=asc&sdate=2026-08-24T00%3A00Z&edate=2026-08-26T00%3A00Z&limit=3000`
- IEM zip member: `CLIMIA_202608250827.txt`
- Date acquired: 2026-08-29

The two files are the same CLI transmission as observed through the live NWS API and the IEM AFOS archive. Their parser-relevant fields agree after widening the structural allowlist to carry the archive transmission sequence, while their byte-level SHA-256 digests intentionally differ.
