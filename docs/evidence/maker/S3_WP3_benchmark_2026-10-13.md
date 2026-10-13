# MAKER S3 WP3 subset benchmark (2026-10-13)

Command (HEAD a119fd97 + WP3 working tree), one cell (f 0.5, b 0.80, k 2), N_TEMPLATE_DATES 1000:

    systemd-run --user --wait --pipe -p MemoryMax=5G -p RuntimeMaxSec=3600 -p LimitNOFILE=524288 \
      -E PYTHONPATH=<wt>/src:<wt> <venv>/bin/python scripts/analysis/fq_loss_floor_mc_maker.py --subset-benchmark

Not evidence: `official_evidence_written=0`. Two runs, 13.8 s each; the replicate slope moved 2x between runs
(0.0132 then 0.0066 s/replicate), so treat the projections as order-of-magnitude.

| Item | Run 2 (final code) |
|---|---|
| 100 / 200 replicates, no outer SE | 3.34 s / 4.00 s |
| 100 replicates + outer 2x100 | 5.40 s |
| outer SE cost | 0.0103 s per (resample x outer replicate) |
| projected sweep cell (2000 replicates, no outer SE) | 16 s; 30 cells about 475 s |
| projected binding cell (10,000 replicates + outer 20x2000) | about 481 s (outer SE is about 85 percent) |
| projected binding run, 18 cells (12 binding + 6 theta 0.08 report) | about 8,660 s (2.4 h), plus the frozen-c re-check (7 sims per cell, 12 cells) and the horizon cell |
| peak RSS at 200 replicates | 409 MiB; about 11 MiB per 100 replicates, so about 1.5 GiB at 10k |

Run 1 (before the sweep was moved off the outer SE): sweep cell 486 s, 30 cells 14,569 s. That would exceed the
3600 s `RuntimeMaxSec` default, so the sweep runs WITHOUT the outer SE (context only, plan r3 WP4 step 2);
the early-stop confirm and the binding run use the pinned 20x2000.

WP4 sizing: set `RuntimeMaxSec` to 2x the projection per cell group; the binding run needs about 5 h of cap, not 1 h.
