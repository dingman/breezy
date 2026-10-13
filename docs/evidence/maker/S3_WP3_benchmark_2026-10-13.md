# MAKER S3 WP3 subset benchmark and run sizing (2026-10-13, revised after review)

Not evidence: `official_evidence_written=0`. Order-of-magnitude sizing only. Every figure below is
**+/- 2x**: the per-replicate slope and the outer-SE unit are extrapolated 50x to 200x from 100/200
replicate points, and moved by up to 1.5x between runs on the same host (0.0066 to 0.0153 s per
replicate across four runs). A 1,000-replicate calibration run is REQUIRED before WP4 sets any
`RuntimeMaxSec`, `MemoryMax` or `--max-memory-gib` (see the last section).

Command (one cell, f 0.5, b 0.80, k 2, N_TEMPLATE_DATES 1000), run twice in separate units:

    systemd-run --user --wait --pipe -p MemoryMax=5G -p RuntimeMaxSec=1800 -p LimitNOFILE=524288 \
      -p WorkingDirectory=<wt> -E PYTHONPATH=<wt>/src:<wt> <venv>/bin/python \
      <wt>/scripts/analysis/fq_loss_floor_mc_maker.py --subset-benchmark

## Measured inputs

| Item | Run A | Run B |
|---|---|---|
| 100 / 200 replicates, no outer SE | 3.10 s / 4.63 s | 2.85 s / 3.83 s |
| 100 replicates + outer 2x100 | 5.41 s | 5.30 s |
| seconds per replicate | 0.0153 | 0.0099 |
| outer SE, per (resample x outer replicate) | 0.0115 s | 0.0123 s |
| one `recheck_cell` call at 100 replicates (7 sims) | 0.79 s | 0.79 s |
| peak RSS at 100 / 200 replicates | 396 / 407 MiB | 397 / 409 MiB |

Separate calibration points, no outer SE (`run_cell` only): 1,000 replicates 12.7 s, 498 MiB;
4,000 replicates 46.6 s, 829 MiB. Slope about 0.0116 s and 0.11 MiB per replicate. The planning
unit below uses 0.0115 s per replicate, 0.012 s per outer unit, and 79 s per recheck cell.

## Per-cell costs

| Cell kind | Seconds | Basis |
|---|---|---|
| sweep cell, 2,000 replicates, NO outer SE | about 25 | 0.0115 x 2000 + base |
| binding / confirm / report cell, 10,000 replicates + outer 20x2000 | about 590 | 115 + 0.012 x 40,000 = 480 (outer SE is about 80 percent) |
| borderline 50,000-replicate re-run (repeats the outer SE) | about 1,050 | 575 + 480 |
| `recheck_cell`, one binding cell | about 79 | 0.79 s at 100 replicates x 100; an upper bound, the template build is a fixed cost |
| horizon cell (4 sims, L_cap 220 dates, 10,000 replicates) | about 90 | 4/7 of a recheck cell x 2 for the longer horizon |

## Itemised stages (central estimate; range is x0.5 to x2)

| Stage | Count and arithmetic | Hours | Range |
|---|---|---|---|
| sweep | 30 cells x 25 s | 0.21 | 0.1 to 0.4 |
| early-stop confirm (only if all 30 veto) | 6 cells x 590 s | 0.98 | 0.5 to 2.0 |
| binding cells | 12 (6 plan cells x {f_kill, f_pass}) x 590 s | 1.97 | 1.0 to 3.9 |
| report cells (theta 0.08 at f_pass) | 6 x 590 s | 0.98 | 0.5 to 2.0 |
| frozen-c re-check | 12 cells x 7 sims = **84 sims**, 12 x 79 s | 0.26 | 0.1 to 0.5 |
| horizon cell | 1 x 90 s | 0.03 | 0.02 to 0.06 |
| borderline 50k re-runs, binding and confirm cells only | expected 0 to 3 x 1,050 s; worst case 18 (12 binding + 6 confirm) | 0 to 0.9; worst 5.2 | |

The re-check is 7 simulations per cell: 4 binding rows (H0, S4, S5-bind, S8-persist3) plus 3 G3
deltas (-0.16, -0.08, -0.04). Report cells are not re-checked and never trigger a re-run.

Units and totals:

| Unit | Stages | Central | With expected re-runs | +/- 2x plus worst-case re-runs |
|---|---|---|---|---|
| `--sweep` | sweep + confirm | 1.2 h | 1.2 to 2.1 h | up to 2.4 + 1.7 = 4.1 h |
| `--binding` | 12 binding + 6 report + re-check + horizon | 3.2 h | 3.2 to 4.1 h | up to 6.5 + 3.5 = 10 h |
| both | | 4.4 h | 5 to 6.5 h | 2.5 to 11 h |

`--binding` runs only when the sweep does not end in an early stop, so the two units are usually
not both needed; when both run, plan on 5 to 6.5 h and do not assume less. The earlier note's
"2.4 h" counted the 18 cells alone and left out the confirm step, the 84 re-check sims, the
re-runs and the horizon cell.

## Memory

Peak RSS is about 0.11 MiB per replicate plus about 380 MiB: 10,000 replicates about 1.5 GiB;
a **50,000-replicate re-run about 5.9 GiB**, which exceeds `MemoryMax=5G` and is close to the
default `--max-memory-gib 8` address-space cap (virtual size runs above RSS). Both units can reach
a re-run, so both need `MemoryMax=9G` and `--max-memory-gib 12`.

## Recommended WP4 limits (provisional until the calibration run)

| Unit | `RuntimeMaxSec` | `MemoryMax` | `--max-memory-gib` |
|---|---|---|---|
| `--sweep` (sweep + confirm + re-runs) | 14,400 (4 h) | 9G | 12 |
| `--binding` (cells + re-check + horizon + re-runs) | 28,800 (8 h) | 9G | 12 |

Never run one unit for the whole job at the old 5 h: central 4.4 h plus re-runs is already past it.
Watch (every-background-job-needs-a-watch): arm a Monitor in the launch turn on the unit state AND
on stdout. The CLI prints one flushed `cell k= b= f= theta= floor_mode= c=` line per finished cell;
alert if no new line appears for 2,400 s (the longest legitimate step is a re-run, about 1,050 s;
a 2x slow host gives about 2,100 s), and re-arm on expiry. On early stop the CLI also prints
`early_stop=`; on a `freeze_blocked` cell it prints `BUILDER-DEFECT freeze_blocked ...`.

## WP4 step 0: REQUIRED calibration before caps are set

Run `run_cell` once at **1,000 replicates with the outer 20x2000** and once `recheck_cell` on that
cell, on the WP4 host and under the same unit properties, and record seconds and peak RSS. Set
`RuntimeMaxSec` to 2x the central total recomputed from that point, never from this note. This
note's per-replicate slope was extrapolated from 100/200-replicate points; the extra 1,000 and
4,000 replicate points above (no outer SE) are consistent with it but do not measure the outer SE.

Superseded run (before the sweep was moved off the outer SE): sweep cell 486 s, 30 cells 14,569 s.
That is why the sweep runs WITHOUT the outer SE (context only, plan r3 WP4 step 2); the confirm
step and the binding run use the pinned 20x2000.
