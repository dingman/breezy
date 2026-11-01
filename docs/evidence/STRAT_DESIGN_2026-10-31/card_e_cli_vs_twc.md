# Card E: CLI versus Kalshi expiration value

## Frozen inputs

- prereg: `docs/plans/backlog/STRAT_DESIGN_2026-10-31/prereg_r2_1.md`
- prereg sha256: `4f490f4b255ab34b214251f19500f66ed487bb68a4e780a7e8c3108c09d34070`
- stations file: `docs/evidence/STRAT_DESIGN_2026-10-31/stations_card_e.json`
- stations sha256: `89c6ed6a867078ff2fc5cc1eef58fc20e91c1c1ffff9f1445833b4bb1718ccba`
- iem_pull_ts: `2026-10-31T05:58:05+00:00`
- kalshi_pull_ts: `2026-10-31T05:57:25+00:00`
- verdict: KILL
- climate dates: 2026-07-05 .. 2026-10-30
- sides: high, low
- p0: 0.01
- alpha_t1: 0.025
- alpha_t2: 0.025
- same_sign_share: 0.8
- kill_ucb: 0.02
- ucb_level: 0.95 (fixed, not a flag)
- force-new-look: none
- planning N=4080 pooled threshold k=55 at p0=0.01, alpha=0.025
- Bonferroni first step over 48 sides at alpha 0.025: n=90 k=6, n=71 k=6, n=65 k=5, n=63 k=5

## Stations

| city | icao | timezone | cli_id | high_series | low_series |
| --- | --- | --- | --- | --- | --- |
| ATL | KATL | America/New_York | ATL | KXHIGHTATL | KXLOWTATL |
| AUS | KAUS | America/Chicago | AUS | KXHIGHAUS | KXLOWTAUS |
| BOS | KBOS | America/New_York | BOS | KXHIGHTBOS | KXLOWTBOS |
| DCA | KDCA | America/New_York | DCA | KXHIGHTDC | KXLOWTDC |
| DEN | KDEN | America/Denver | DEN | KXHIGHDEN | KXLOWTDEN |
| DFW | KDFW | America/Chicago | DFW | KXHIGHTDAL | KXLOWTDAL |
| EWR | KEWR | America/New_York | EWR | KXHIGHTEWR | KXLOWTEWR |
| HOU | KHOU | America/Chicago | HOU | KXHIGHTHOU | KXLOWTHOU |
| LAS | KLAS | America/Los_Angeles | LAS | KXHIGHTLV | KXLOWTLV |
| LAX | KLAX | America/Los_Angeles | LAX | KXHIGHLAX | KXLOWTLAX |
| MDW | KMDW | America/Chicago | MDW | KXHIGHCHI | KXLOWTCHI |
| MIA | KMIA | America/New_York | MIA | KXHIGHMIA | KXLOWTMIA |
| MSP | KMSP | America/Chicago | MSP | KXHIGHTMIN | KXLOWTMIN |
| MSY | KMSY | America/Chicago | MSY | KXHIGHTNOLA | KXLOWTNOLA |
| NYC | KNYC | America/New_York | NYC | KXHIGHNY | KXLOWTNYC |
| OKC | KOKC | America/Chicago | OKC | KXHIGHTOKC | KXLOWTOKC |
| PHL | KPHL | America/New_York | PHL | KXHIGHPHIL | KXLOWTPHIL |
| PHX | KPHX | America/Phoenix | PHX | KXHIGHTPHX | KXLOWTPHX |
| SAN | KSAN | America/Los_Angeles | SAN | KXHIGHTSAN | KXLOWTSAN |
| SAT | KSAT | America/Chicago | SAT | KXHIGHTSATX | KXLOWTSATX |
| SDF | KSDF | America/Kentucky/Louisville | SDF | KXHIGHTSDF | KXLOWTSDF |
| SEA | KSEA | America/Los_Angeles | SEA | KXHIGHTSEA | KXLOWTSEA |
| SFO | KSFO | America/Los_Angeles | SFO | KXHIGHTSFO | KXLOWTSFO |
| TTN | KTTN | America/New_York | TTN | KXHIGHTTTN | KXLOWTTTN |

## Per-side sample

| side | n | k | day_exclusions | p | holm | pos | neg | sign_share | sign_ok | side_ucb | outcome |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ATL:high | 117 | 0 | missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0252795 | KILL |
| ATL:low | 117 | 0 | missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0252795 | KILL |
| AUS:high | 117 | 0 | missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0252795 | KILL |
| AUS:low | 117 | 0 | missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0252795 | KILL |
| BOS:high | 116 | 0 | missing_kalshi=1, non_numeric_expiration_value=1 | 1 | no | 0 | 0 | n/a | no | 0.0254947 | KILL |
| BOS:low | 116 | 0 | missing_kalshi=1, non_numeric_expiration_value=1 | 1 | no | 0 | 0 | n/a | no | 0.0254947 | KILL |
| DCA:high | 117 | 0 | missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0252795 | KILL |
| DCA:low | 117 | 0 | missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0252795 | KILL |
| DEN:high | 117 | 0 | missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0252795 | KILL |
| DEN:low | 117 | 0 | missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0252795 | KILL |
| DFW:high | 117 | 0 | missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0252795 | KILL |
| DFW:low | 117 | 0 | missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0252795 | KILL |
| EWR:high | 65 | 0 | missing_kalshi=53 | 1 | no | 0 | 0 | n/a | no | 0.0450423 | KILL |
| EWR:low | 65 | 0 | missing_kalshi=53 | 1 | no | 0 | 0 | n/a | no | 0.0450423 | KILL |
| HOU:high | 117 | 0 | missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0252795 | KILL |
| HOU:low | 117 | 0 | missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0252795 | KILL |
| LAS:high | 116 | 0 | missing_kalshi=1, non_numeric_expiration_value=1 | 1 | no | 0 | 0 | n/a | no | 0.0254947 | KILL |
| LAS:low | 117 | 0 | missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0252795 | KILL |
| LAX:high | 116 | 0 | missing_kalshi=1, non_numeric_expiration_value=1 | 1 | no | 0 | 0 | n/a | no | 0.0254947 | KILL |
| LAX:low | 117 | 0 | missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0252795 | KILL |
| MDW:high | 116 | 0 | amendment=1, missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0254947 | KILL |
| MDW:low | 116 | 0 | amendment=1, missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0254947 | KILL |
| MIA:high | 117 | 1 | missing_kalshi=1 | 0.691456 | no | 1 | 0 | 1.000 | yes | 0.0399029 | KILL |
| MIA:low | 116 | 0 | missing_kalshi=1, null_expiration_value=1 | 1 | no | 0 | 0 | n/a | no | 0.0254947 | KILL |
| MSP:high | 116 | 0 | missing_kalshi=2 | 1 | no | 0 | 0 | n/a | no | 0.0254947 | KILL |
| MSP:low | 116 | 0 | missing_kalshi=2 | 1 | no | 0 | 0 | n/a | no | 0.0254947 | KILL |
| MSY:high | 117 | 0 | missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0252795 | KILL |
| MSY:low | 117 | 0 | missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0252795 | KILL |
| NYC:high | 117 | 0 | missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0252795 | KILL |
| NYC:low | 117 | 0 | missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0252795 | KILL |
| OKC:high | 117 | 0 | missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0252795 | KILL |
| OKC:low | 117 | 0 | missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0252795 | KILL |
| PHL:high | 116 | 0 | amendment=1, missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0254947 | KILL |
| PHL:low | 116 | 0 | amendment=1, missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0254947 | KILL |
| PHX:high | 116 | 0 | missing_both=1, missing_temperature=1 | 1 | no | 0 | 0 | n/a | no | 0.0254947 | KILL |
| PHX:low | 116 | 0 | missing_both=1, missing_temperature=1 | 1 | no | 0 | 0 | n/a | no | 0.0254947 | KILL |
| SAN:high | 71 | 0 | missing_both=1, missing_kalshi=46 | 1 | no | 0 | 0 | n/a | no | 0.0413157 | KILL |
| SAN:low | 71 | 0 | missing_both=1, missing_kalshi=46 | 1 | no | 0 | 0 | n/a | no | 0.0413157 | KILL |
| SAT:high | 117 | 0 | missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0252795 | KILL |
| SAT:low | 117 | 0 | missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0252795 | KILL |
| SDF:high | 63 | 0 | missing_kalshi=55 | 1 | no | 0 | 0 | n/a | no | 0.0464385 | KILL |
| SDF:low | 63 | 0 | missing_kalshi=55 | 1 | no | 0 | 0 | n/a | no | 0.0464385 | KILL |
| SEA:high | 113 | 0 | amendment=3, missing_kalshi=1, not_final=1 | 1 | no | 0 | 0 | n/a | no | 0.0261626 | KILL |
| SEA:low | 113 | 0 | amendment=3, missing_kalshi=1, not_final=1 | 1 | no | 0 | 0 | n/a | no | 0.0261626 | KILL |
| SFO:high | 117 | 0 | missing_kalshi=1 | 1 | no | 0 | 0 | n/a | no | 0.0252795 | KILL |
| SFO:low | 116 | 0 | missing_kalshi=1, non_numeric_expiration_value=1 | 1 | no | 0 | 0 | n/a | no | 0.0254947 | KILL |
| TTN:high | 65 | 0 | missing_kalshi=53 | 1 | no | 0 | 0 | n/a | no | 0.0450423 | KILL |
| TTN:low | 65 | 0 | missing_kalshi=53 | 1 | no | 0 | 0 | n/a | no | 0.0450423 | KILL |

## T1 pooled exact one-sided binomial

| k | n | p0 | alpha | threshold | p_value | reject |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 5186 | 0.01 | 0.025 | 67 | 1 | False |

## T2 Holm

Family m = 48 (requested station-sides, including n = 0). Flagged: none.

| side | k | n | p | flagged |
| --- | --- | --- | --- | --- |
| ATL:high | 0 | 117 | 1 | no |
| ATL:low | 0 | 117 | 1 | no |
| AUS:high | 0 | 117 | 1 | no |
| AUS:low | 0 | 117 | 1 | no |
| BOS:high | 0 | 116 | 1 | no |
| BOS:low | 0 | 116 | 1 | no |
| DCA:high | 0 | 117 | 1 | no |
| DCA:low | 0 | 117 | 1 | no |
| DEN:high | 0 | 117 | 1 | no |
| DEN:low | 0 | 117 | 1 | no |
| DFW:high | 0 | 117 | 1 | no |
| DFW:low | 0 | 117 | 1 | no |
| EWR:high | 0 | 65 | 1 | no |
| EWR:low | 0 | 65 | 1 | no |
| HOU:high | 0 | 117 | 1 | no |
| HOU:low | 0 | 117 | 1 | no |
| LAS:high | 0 | 116 | 1 | no |
| LAS:low | 0 | 117 | 1 | no |
| LAX:high | 0 | 116 | 1 | no |
| LAX:low | 0 | 117 | 1 | no |
| MDW:high | 0 | 116 | 1 | no |
| MDW:low | 0 | 116 | 1 | no |
| MIA:high | 1 | 117 | 0.691456 | no |
| MIA:low | 0 | 116 | 1 | no |
| MSP:high | 0 | 116 | 1 | no |
| MSP:low | 0 | 116 | 1 | no |
| MSY:high | 0 | 117 | 1 | no |
| MSY:low | 0 | 117 | 1 | no |
| NYC:high | 0 | 117 | 1 | no |
| NYC:low | 0 | 117 | 1 | no |
| OKC:high | 0 | 117 | 1 | no |
| OKC:low | 0 | 117 | 1 | no |
| PHL:high | 0 | 116 | 1 | no |
| PHL:low | 0 | 116 | 1 | no |
| PHX:high | 0 | 116 | 1 | no |
| PHX:low | 0 | 116 | 1 | no |
| SAN:high | 0 | 71 | 1 | no |
| SAN:low | 0 | 71 | 1 | no |
| SAT:high | 0 | 117 | 1 | no |
| SAT:low | 0 | 117 | 1 | no |
| SDF:high | 0 | 63 | 1 | no |
| SDF:low | 0 | 63 | 1 | no |
| SEA:high | 0 | 113 | 1 | no |
| SEA:low | 0 | 113 | 1 | no |
| SFO:high | 0 | 117 | 1 | no |
| SFO:low | 0 | 116 | 1 | no |
| TTN:high | 0 | 65 | 1 | no |
| TTN:low | 0 | 65 | 1 | no |

## Sign

Card sign rule applies only to Holm-flagged sides. Not a pooled-T1 input.

| side | positive | negative | share | sign_ok | flagged |
| --- | --- | --- | --- | --- | --- |
| ATL:high | 0 | 0 | n/a | no | no |
| ATL:low | 0 | 0 | n/a | no | no |
| AUS:high | 0 | 0 | n/a | no | no |
| AUS:low | 0 | 0 | n/a | no | no |
| BOS:high | 0 | 0 | n/a | no | no |
| BOS:low | 0 | 0 | n/a | no | no |
| DCA:high | 0 | 0 | n/a | no | no |
| DCA:low | 0 | 0 | n/a | no | no |
| DEN:high | 0 | 0 | n/a | no | no |
| DEN:low | 0 | 0 | n/a | no | no |
| DFW:high | 0 | 0 | n/a | no | no |
| DFW:low | 0 | 0 | n/a | no | no |
| EWR:high | 0 | 0 | n/a | no | no |
| EWR:low | 0 | 0 | n/a | no | no |
| HOU:high | 0 | 0 | n/a | no | no |
| HOU:low | 0 | 0 | n/a | no | no |
| LAS:high | 0 | 0 | n/a | no | no |
| LAS:low | 0 | 0 | n/a | no | no |
| LAX:high | 0 | 0 | n/a | no | no |
| LAX:low | 0 | 0 | n/a | no | no |
| MDW:high | 0 | 0 | n/a | no | no |
| MDW:low | 0 | 0 | n/a | no | no |
| MIA:high | 1 | 0 | 1.000 | yes | no |
| MIA:low | 0 | 0 | n/a | no | no |
| MSP:high | 0 | 0 | n/a | no | no |
| MSP:low | 0 | 0 | n/a | no | no |
| MSY:high | 0 | 0 | n/a | no | no |
| MSY:low | 0 | 0 | n/a | no | no |
| NYC:high | 0 | 0 | n/a | no | no |
| NYC:low | 0 | 0 | n/a | no | no |
| OKC:high | 0 | 0 | n/a | no | no |
| OKC:low | 0 | 0 | n/a | no | no |
| PHL:high | 0 | 0 | n/a | no | no |
| PHL:low | 0 | 0 | n/a | no | no |
| PHX:high | 0 | 0 | n/a | no | no |
| PHX:low | 0 | 0 | n/a | no | no |
| SAN:high | 0 | 0 | n/a | no | no |
| SAN:low | 0 | 0 | n/a | no | no |
| SAT:high | 0 | 0 | n/a | no | no |
| SAT:low | 0 | 0 | n/a | no | no |
| SDF:high | 0 | 0 | n/a | no | no |
| SDF:low | 0 | 0 | n/a | no | no |
| SEA:high | 0 | 0 | n/a | no | no |
| SEA:low | 0 | 0 | n/a | no | no |
| SFO:high | 0 | 0 | n/a | no | no |
| SFO:low | 0 | 0 | n/a | no | no |
| TTN:high | 0 | 0 | n/a | no | no |
| TTN:low | 0 | 0 | n/a | no | no |

## Half-split stability

First floor(n/2) matched days per side, chronological. Not a gate.

| side | half | start | end | n | k | mean_delta | sign |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ATL:high | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| ATL:high | 2 | 2026-09-01 | 2026-10-29 | 59 | 0 | 0 | zero |
| ATL:low | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| ATL:low | 2 | 2026-09-01 | 2026-10-29 | 59 | 0 | 0 | zero |
| AUS:high | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| AUS:high | 2 | 2026-09-01 | 2026-10-29 | 59 | 0 | 0 | zero |
| AUS:low | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| AUS:low | 2 | 2026-09-01 | 2026-10-29 | 59 | 0 | 0 | zero |
| BOS:high | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| BOS:high | 2 | 2026-09-01 | 2026-10-29 | 58 | 0 | 0 | zero |
| BOS:low | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| BOS:low | 2 | 2026-09-01 | 2026-10-29 | 58 | 0 | 0 | zero |
| DCA:high | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| DCA:high | 2 | 2026-09-01 | 2026-10-29 | 59 | 0 | 0 | zero |
| DCA:low | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| DCA:low | 2 | 2026-09-01 | 2026-10-29 | 59 | 0 | 0 | zero |
| DEN:high | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| DEN:high | 2 | 2026-09-01 | 2026-10-29 | 59 | 0 | 0 | zero |
| DEN:low | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| DEN:low | 2 | 2026-09-01 | 2026-10-29 | 59 | 0 | 0 | zero |
| DFW:high | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| DFW:high | 2 | 2026-09-01 | 2026-10-29 | 59 | 0 | 0 | zero |
| DFW:low | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| DFW:low | 2 | 2026-09-01 | 2026-10-29 | 59 | 0 | 0 | zero |
| EWR:high | 1 | 2026-08-26 | 2026-09-26 | 32 | 0 | 0 | zero |
| EWR:high | 2 | 2026-09-27 | 2026-10-29 | 33 | 0 | 0 | zero |
| EWR:low | 1 | 2026-08-26 | 2026-09-26 | 32 | 0 | 0 | zero |
| EWR:low | 2 | 2026-09-27 | 2026-10-29 | 33 | 0 | 0 | zero |
| HOU:high | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| HOU:high | 2 | 2026-09-01 | 2026-10-29 | 59 | 0 | 0 | zero |
| HOU:low | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| HOU:low | 2 | 2026-09-01 | 2026-10-29 | 59 | 0 | 0 | zero |
| LAS:high | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| LAS:high | 2 | 2026-09-01 | 2026-10-29 | 58 | 0 | 0 | zero |
| LAS:low | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| LAS:low | 2 | 2026-09-01 | 2026-10-29 | 59 | 0 | 0 | zero |
| LAX:high | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| LAX:high | 2 | 2026-09-01 | 2026-10-29 | 58 | 0 | 0 | zero |
| LAX:low | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| LAX:low | 2 | 2026-09-01 | 2026-10-29 | 59 | 0 | 0 | zero |
| MDW:high | 1 | 2026-07-05 | 2026-09-01 | 58 | 0 | 0 | zero |
| MDW:high | 2 | 2026-09-02 | 2026-10-29 | 58 | 0 | 0 | zero |
| MDW:low | 1 | 2026-07-05 | 2026-09-01 | 58 | 0 | 0 | zero |
| MDW:low | 2 | 2026-09-02 | 2026-10-29 | 58 | 0 | 0 | zero |
| MIA:high | 1 | 2026-07-05 | 2026-08-31 | 58 | 1 | 0.0862069 | positive |
| MIA:high | 2 | 2026-09-01 | 2026-10-29 | 59 | 0 | 0 | zero |
| MIA:low | 1 | 2026-07-05 | 2026-09-01 | 58 | 0 | 0 | zero |
| MIA:low | 2 | 2026-09-02 | 2026-10-29 | 58 | 0 | 0 | zero |
| MSP:high | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| MSP:high | 2 | 2026-09-01 | 2026-10-29 | 58 | 0 | 0 | zero |
| MSP:low | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| MSP:low | 2 | 2026-09-01 | 2026-10-29 | 58 | 0 | 0 | zero |
| MSY:high | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| MSY:high | 2 | 2026-09-01 | 2026-10-29 | 59 | 0 | 0 | zero |
| MSY:low | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| MSY:low | 2 | 2026-09-01 | 2026-10-29 | 59 | 0 | 0 | zero |
| NYC:high | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| NYC:high | 2 | 2026-09-01 | 2026-10-29 | 59 | 0 | 0 | zero |
| NYC:low | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| NYC:low | 2 | 2026-09-01 | 2026-10-29 | 59 | 0 | 0 | zero |
| OKC:high | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| OKC:high | 2 | 2026-09-01 | 2026-10-29 | 59 | 0 | 0 | zero |
| OKC:low | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| OKC:low | 2 | 2026-09-01 | 2026-10-29 | 59 | 0 | 0 | zero |
| PHL:high | 1 | 2026-07-05 | 2026-09-01 | 58 | 0 | 0 | zero |
| PHL:high | 2 | 2026-09-02 | 2026-10-29 | 58 | 0 | 0 | zero |
| PHL:low | 1 | 2026-07-05 | 2026-09-01 | 58 | 0 | 0 | zero |
| PHL:low | 2 | 2026-09-02 | 2026-10-29 | 58 | 0 | 0 | zero |
| PHX:high | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| PHX:high | 2 | 2026-09-01 | 2026-10-29 | 58 | 0 | 0 | zero |
| PHX:low | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| PHX:low | 2 | 2026-09-01 | 2026-10-29 | 58 | 0 | 0 | zero |
| SAN:high | 1 | 2026-08-19 | 2026-09-22 | 35 | 0 | 0 | zero |
| SAN:high | 2 | 2026-09-23 | 2026-10-28 | 36 | 0 | 0 | zero |
| SAN:low | 1 | 2026-08-19 | 2026-09-22 | 35 | 0 | 0 | zero |
| SAN:low | 2 | 2026-09-23 | 2026-10-28 | 36 | 0 | 0 | zero |
| SAT:high | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| SAT:high | 2 | 2026-09-01 | 2026-10-29 | 59 | 0 | 0 | zero |
| SAT:low | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| SAT:low | 2 | 2026-09-01 | 2026-10-29 | 59 | 0 | 0 | zero |
| SDF:high | 1 | 2026-08-28 | 2026-09-27 | 31 | 0 | 0 | zero |
| SDF:high | 2 | 2026-09-28 | 2026-10-29 | 32 | 0 | 0 | zero |
| SDF:low | 1 | 2026-08-28 | 2026-09-27 | 31 | 0 | 0 | zero |
| SDF:low | 2 | 2026-09-28 | 2026-10-29 | 32 | 0 | 0 | zero |
| SEA:high | 1 | 2026-07-05 | 2026-09-02 | 56 | 0 | 0 | zero |
| SEA:high | 2 | 2026-09-03 | 2026-10-29 | 57 | 0 | 0 | zero |
| SEA:low | 1 | 2026-07-05 | 2026-09-02 | 56 | 0 | 0 | zero |
| SEA:low | 2 | 2026-09-03 | 2026-10-29 | 57 | 0 | 0 | zero |
| SFO:high | 1 | 2026-07-05 | 2026-08-31 | 58 | 0 | 0 | zero |
| SFO:high | 2 | 2026-09-01 | 2026-10-29 | 59 | 0 | 0 | zero |
| SFO:low | 1 | 2026-07-05 | 2026-09-01 | 58 | 0 | 0 | zero |
| SFO:low | 2 | 2026-09-02 | 2026-10-29 | 58 | 0 | 0 | zero |
| TTN:high | 1 | 2026-08-26 | 2026-09-26 | 32 | 0 | 0 | zero |
| TTN:high | 2 | 2026-09-27 | 2026-10-29 | 33 | 0 | 0 | zero |
| TTN:low | 1 | 2026-08-26 | 2026-09-26 | 32 | 0 | 0 | zero |
| TTN:low | 2 | 2026-09-27 | 2026-10-29 | 33 | 0 | 0 | zero |

Stable (every two-signed side agrees, and at least one does): no.

## Bucket check

Reported only. Agree and disagree do not enter the verdict.

| agree | disagree | skipped |
| --- | --- | --- |
| 31144 | 2 | 90 |

## Day-row exclusions

| reason | n |
| --- | --- |
| amendment | 10 |
| missing_both | 4 |
| missing_kalshi | 454 |
| missing_temperature | 2 |
| non_numeric_expiration_value | 5 |
| not_final | 2 |
| null_expiration_value | 1 |

## Day-row kalshi_reason

| reason | n |
| --- | --- |
| missing_kalshi | 458 |
| non_numeric_expiration_value | 5 |
| null_expiration_value | 1 |

## Day-row cli_reason

| reason | n |
| --- | --- |
| amendment | 12 |
| missing_cli | 4 |
| missing_temperature | 3 |
| not_final | 32 |

## Kalshi market-row exclusions

| side | reason | n |
| --- | --- | --- |
| ATL:low | null_expiration_value | 6 |
| AUS:high | null_expiration_value | 3610 |
| AUS:low | null_expiration_value | 132 |
| BOS:high | non_numeric_expiration_value | 6 |
| BOS:low | non_numeric_expiration_value | 6 |
| DCA:high | null_expiration_value | 18 |
| DEN:high | null_expiration_value | 802 |
| DEN:low | null_expiration_value | 108 |
| LAS:high | non_numeric_expiration_value | 6 |
| LAX:high | non_numeric_expiration_value | 6 |
| LAX:high | null_expiration_value | 572 |
| LAX:low | null_expiration_value | 66 |
| MDW:high | null_expiration_value | 5043 |
| MDW:high | unparsed_event_ticker | 6 |
| MDW:low | null_expiration_value | 90 |
| MIA:high | non_numeric_expiration_value | 5 |
| MIA:high | null_expiration_value | 3658 |
| MIA:low | non_numeric_expiration_value | 4 |
| MIA:low | null_expiration_value | 92 |
| NYC:high | null_expiration_value | 5066 |
| NYC:low | null_expiration_value | 90 |
| PHL:high | null_expiration_value | 808 |
| PHL:low | null_expiration_value | 78 |
| SEA:high | null_expiration_value | 5 |
| SEA:low | null_expiration_value | 5 |
| SFO:low | non_numeric_expiration_value | 6 |

## CLI undated products

Counted once per city, not once per side.

| city | reason | n |
| --- | --- | --- |
| none | none | 0 |

## CLI final overwrites

Times a later product replaced the stored product for a date. Per side.

| side | overwrites |
| --- | --- |
| ATL:high | 235 |
| ATL:low | 235 |
| AUS:high | 232 |
| AUS:low | 232 |
| BOS:high | 121 |
| BOS:low | 121 |
| DCA:high | 118 |
| DCA:low | 118 |
| DEN:high | 123 |
| DEN:low | 123 |
| DFW:high | 120 |
| DFW:low | 120 |
| EWR:high | 119 |
| EWR:low | 119 |
| HOU:high | 116 |
| HOU:low | 116 |
| LAS:high | 120 |
| LAS:low | 120 |
| LAX:high | 171 |
| LAX:low | 171 |
| MDW:high | 119 |
| MDW:low | 119 |
| MIA:high | 124 |
| MIA:low | 124 |
| MSP:high | 123 |
| MSP:low | 123 |
| MSY:high | 118 |
| MSY:low | 118 |
| NYC:high | 123 |
| NYC:low | 123 |
| OKC:high | 118 |
| OKC:low | 118 |
| PHL:high | 119 |
| PHL:low | 119 |
| PHX:high | 122 |
| PHX:low | 122 |
| SAN:high | 123 |
| SAN:low | 123 |
| SAT:high | 232 |
| SAT:low | 232 |
| SDF:high | 235 |
| SDF:low | 235 |
| SEA:high | 123 |
| SEA:low | 123 |
| SFO:high | 117 |
| SFO:low | 117 |
| TTN:high | 121 |
| TTN:low | 121 |

## CLI raw body sha256

SHA-256 of the raw IEM body, one per city.

| city | sha256 |
| --- | --- |
| ATL | c119351c20ff668978ff37050adb26e7cba165de5138c7f7d25c4f79ed5d865c |
| AUS | 45940d21da8a0ff705144c839177d49e76846c44ed5965cf000c5706ed6092ec |
| BOS | 9614e0296cfb6310c4af3298e9c229ac1ef4fed0803db5695d402eb67cb17df1 |
| DCA | 9f438e44cf677231b51b9561bb23e84a7a5e6357f5100b27f9d79d9f10e5dec9 |
| DEN | 32e2cf2e14208bbf372b7ddc69e45219f4cee2fc0942bf357bc7f918e910f0d3 |
| DFW | ab5291a637a8af588db28a57b1156283acf8a20460e94d04349d56fb7d7588f4 |
| EWR | c9ecfe0e84c5151d870195540181995fb612339f66d431a4b45e264c8dd3d53e |
| HOU | d71df68864a32492cfaf81b2ca11fc12e1e03e9a7158d7837e5105fc4b0e8c89 |
| LAS | 2c8552b28606b5fd107b577f462ce9ec6e398b9a6e6ca10d06f3f45eb50fc464 |
| LAX | 20bb9821a344c42006a98c1d40574febcf7e9fb78f146456c7aa86e0743932fd |
| MDW | 7f6fe46c895ba8699fec2103e38d9b036a61143f857b1d7c4e94880191597ccb |
| MIA | 5f000dcd6b795231568c1451fd43709724666ca55c9f94d62330b659d99921c2 |
| MSP | 394046b96a9bac146abfeb88f540f2e54d6d730b0fdaf6a8cdc83f2bed1b66d3 |
| MSY | d72c777276afdb6db98b49a620bd6c384d07fffd5603fc6606d49db16b5726b0 |
| NYC | e0c09da9c698782545d05214baf322b175c97e420619f88bdf3fc86c69244dbb |
| OKC | f6aef3eeae73f7a27f6fca8d0a93fa73a19dadf91ee59a5a13c8ddaf6759ac47 |
| PHL | cb68f4316f526cee2ff2b0a07b8d5c481620a2ed9c4d3861b78e8a38f00306f0 |
| PHX | aa8c10ba00296c5213b38dd6bf9e63fd60844c6888da1f965c37fe8aa71c0820 |
| SAN | 663f4f79ab891c3569f2b9752eebe45efa719ec611d954d3375cdcba2228b30e |
| SAT | 8af8e2585a75e7d13bff4ea3abefd38fbf937dee2463c8d5df915268577a90fb |
| SDF | 8a8281b7b037156aed7ca83ba99ec6f81f675f401d00905c1fd68a187529052d |
| SEA | b3261f4f90dc4daba0a5d9e138c862028641ace51e84f28e3ba5398f881c812b |
| SFO | 292fb229c3de51fdbe1f9e29237c120ef84323a8194b55e4313e7b80f76226c2 |
| TTN | e54f5f520c65c0750ebc375133112edd79e5248d0a746b29af505273ef35e17a |

## Kalshi historical and live copies

Client cutoff: 2026-07-04 (days before it are historical).

- overlap tickers: 1884
- expiration conflicts: 0
- historical rows: 84144
- historical rows not status finalized: 0
- status counts: finalized=101688

## Verdict

**KILL** — T1 not rejected and the pooled one-sided Clopper-Pearson upper bound is at or below the kill level

Pooled one-sided upper bound: 0.000914414.

## Request counts

- mode: live
- kalshi_get_json: 157
- iem_fetches: 24
- kalshi_errors: 0
- iem_errors: 0
