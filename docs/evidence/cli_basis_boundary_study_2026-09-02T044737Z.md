# CLI-basis boundary upper-tail — measured (2026-09-02T04:47:37Z)

Generated 2026-09-02T04:59:10+00:00 from `scripts/analysis/cli_basis_boundary_study.py`, pre-registered in `scripts/analysis/pre_registration_2026-09-02T044737Z.md`.
Archive cache: `/home/jon/.local/share/breezy/archive/settlement-alignment-cache` (zero network; cache misses are refused).
Corpus window: 2021-01-01 .. 2025-12-31.

## Pre-registered bar

PASS bar: Wilson 95% lower bound >= **0.06285** (ask 0.05 + theta*p*(1-p) at p=0.05, theta=0.06 -> 0.00285, + one 0.01 tick buffer).
Admissibility: n >= 100 station-days, else UNDERPOWERED.
Bonferroni corroboration z = 3.1888 (two-sided 95%/35 cells).

## Per-cell results

| station | hour | n | rate | Wilson lower | Wilson lower (Bonferroni) | verdict |
|---|---:|---:|---:|---:|---:|---|
| LAX | 17 | 1819 | 25.8384% | 23.8791% | 22.7061% | PASS |
| LAX | 18 | 1819 | 25.7284% | 23.7722% | 22.6013% | PASS |
| LAX | 19 | 1818 | 25.5776% | 23.6250% | 22.4567% | PASS |
| LAX | 20 | 1820 | 25.4945% | 23.5453% | 22.3792% | PASS |
| LAX | 21 | 1820 | 25.3846% | 23.4384% | 22.2745% | PASS |
| LAX | 22 | 1820 | 25.3297% | 23.3850% | 22.2221% | PASS |
| LAX | 23 | 1820 | 25.2747% | 23.3316% | 22.1698% | PASS |
| MDW | 17 | 1826 | 18.9485% | 17.2169% | 16.1991% | PASS |
| MDW | 18 | 1826 | 18.5652% | 16.8484% | 15.8405% | PASS |
| MDW | 19 | 1826 | 18.2366% | 16.5327% | 15.5335% | PASS |
| MDW | 20 | 1826 | 17.6889% | 16.0071% | 15.0227% | PASS |
| MDW | 21 | 1826 | 17.2508% | 15.5871% | 14.6147% | PASS |
| MDW | 22 | 1826 | 16.5389% | 14.9054% | 13.9532% | PASS |
| MDW | 23 | 1826 | 15.5531% | 13.9634% | 13.0402% | PASS |
| MIA | 17 | 1813 | 25.6481% | 23.6909% | 22.5198% | PASS |
| MIA | 18 | 1812 | 25.6071% | 23.6505% | 22.4799% | PASS |
| MIA | 19 | 1813 | 25.6481% | 23.6909% | 22.5198% | PASS |
| MIA | 20 | 1812 | 25.6623% | 23.7042% | 22.5325% | PASS |
| MIA | 21 | 1812 | 25.6071% | 23.6505% | 22.4799% | PASS |
| MIA | 22 | 1811 | 25.5108% | 23.5564% | 22.3873% | PASS |
| MIA | 23 | 1812 | 25.4967% | 23.5432% | 22.3747% | PASS |
| NYC | 17 | 1808 | 59.9004% | 57.6227% | 56.1795% | PASS |
| NYC | 18 | 1807 | 59.3248% | 57.0425% | 55.5977% | PASS |
| NYC | 19 | 1806 | 58.9147% | 56.6291% | 55.1831% | PASS |
| NYC | 20 | 1809 | 58.4301% | 56.1434% | 54.6980% | PASS |
| NYC | 21 | 1807 | 57.9967% | 55.7064% | 54.2595% | PASS |
| NYC | 22 | 1804 | 57.4834% | 55.1885% | 53.7400% | PASS |
| NYC | 23 | 1804 | 56.3193% | 54.0195% | 52.5704% | PASS |
| SFO | 17 | 1799 | 22.8460% | 20.9650% | 19.8474% | PASS |
| SFO | 18 | 1799 | 22.8460% | 20.9650% | 19.8474% | PASS |
| SFO | 19 | 1799 | 22.7349% | 20.8574% | 19.7422% | PASS |
| SFO | 20 | 1799 | 22.6793% | 20.8036% | 19.6896% | PASS |
| SFO | 21 | 1799 | 22.6237% | 20.7498% | 19.6371% | PASS |
| SFO | 22 | 1798 | 22.4694% | 20.6000% | 19.4904% | PASS |
| SFO | 23 | 1799 | 22.2902% | 20.4271% | 19.3218% | PASS |

## Verdict

**GO**

Admissible-and-PASS cells: 35. Of those, Bonferroni-corroborated: 35.
