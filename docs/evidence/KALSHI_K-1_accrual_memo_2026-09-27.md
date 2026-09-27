# Kalshi K-1: desk-only accrual memo (RA-13 §4, as amended by §7 B-2 and B-8)

Authority: RULING_RA-13 §4 [VERIFIED RULING_RA-13:56-65] as amended by B-2 [VERIFIED :86-88] and B-8 [VERIFIED :103]. This memo uses committed docs only. No API calls, no network, no tape, and no PM.us comparator numbers. Nothing here is computed on tape, so no firewall cost [INFERRED].

## 1. Stations
- Kalshi has 24 US cities with an open daily event. Each city has both a HIGH and a LOW series, and every station is quoted from `rules_primary` [VERIFIED KALSHI_DAILY_TEMP_SERIES_ENUMERATION:12].
- **Shared with PM.us (5): pseudo-replication.** NYC/CLINYC, MIA/CLIMIA, Chicago/**CLIMDW** (Midway, not O'Hare), LAX/CLILAX, SFO/CLISFO [VERIFIED ENUM:13; KALSHI_CRH_EXPANSION_PLAN:79].
  - The same station-day on two venues is one weather event, so it adds zero independent n [VERIFIED PLAN:9,11].
  - NYC (KNYC) is also hourly-only and fails cadence [VERIFIED kalshi_station_cadence:37,100].
- **New (19):** ATL (KATL), AUS (KAUS), BOS (KBOS), DFW (KDFW), DEN (KDEN), HOU (**KHOU**, Hobby), LAS (KLAS), SDF (KSDF), MSP (KMSP), MSY (KMSY), EWR (KEWR), OKC (KOKC), PHL (KPHL), PHX (KPHX), SAT (KSAT), SAN (KSAN), SEA (KSEA), TTN (KTTN), DCA (KDCA) [VERIFIED ENUM:17-40; cadence:17-35].
- Admission status of the 19:
  - **KDEN: EXCLUDED.** Its live feed was hourly-only on 2 consecutive days [VERIFIED kalshi_station_temp_cadence:17,84-87].
  - **KHOU: HELD.** The 5-min archive feed stops mid-2025-07 [VERIFIED temp_cadence:18,43-44; PLAN:88].
  - **17 are clean on the temperature-bearing gate on both feeds** [VERIFIED temp_cadence:13-31; PLAN:86].
- Registry hazards:
  - Three pairs of stations share an issuing NWS office (KOKX: EWR+NYC; KPHI: PHL+TTN; KEWX: AUS+SAT), so each needs a narrow header regex [VERIFIED cadence:40-42].
  - Three series titles disagree with their rules text; the rules are authoritative [VERIFIED ENUM:46].
- Correction to AUD-18. Its "~288x-finer settlement cadence" (AUD-18:990-991) is wrong. Every one of these series settles daily; the 5 minutes is the observation cadence [INFERRED from ENUM:11-12; cadence:114-123]. The memory label "all 5-min" is also false for KNYC and for KDEN's live feed [VERIFIED cadence:37; temp_cadence:87].

## 2. Accrual estimate for the new stations (station-days per day)

| Basis | HIGH/day | LOW/day |
|---|---|---|
| Listed (ceiling) | 19 | 19 |
| Temperature-cadence clean (excluding KDEN and KHOU) | 17 | 17 |
| Plus KHOU if it is admitted | 18 | 18 |
| **Admissible today** (settlement reconciliation unmeasured, and no Kalshi capture exists) | **0** | **0** |

- 17 or 18 per day is roughly 3.4-3.6x PM.us's nominal 5 per day [VERIFIED RULING_RA-13:45; INFERRED arithmetic]. It is about 510 HIGH station-days per 30 days [INFERRED].
- HIGH and LOW on the same station-day share one weather day. Do not count 34 per day as independent; the effective n is unmeasured [INFERRED].
- Caveats:
  - The listing is a one-day snapshot (2026-09-04). Whether stations stay listed day to day is unmeasured [VERIFIED ENUM:3,12; INFERRED].
  - Cadence was measured in the 12:00-17:00 local window only, which fits HIGH. Cadence in LOW's overnight window is unmeasured [VERIFIED cadence:7; INFERRED].
  - The cadence files show observation-record cadence, not temperature cadence. The temperature-cadence file supersedes them, but it covers 1 live day and 7 archive days only [VERIFIED cadence:114-123,137-139; temp_cadence:3,8].
  - KHOU's July 83.3% (and KATL's 96.7%) were MADIS archive outages; both were 100% in January [VERIFIED cadence:45-47,85,108-110].
  - Live 5-min rows are integer °C, bounding the temperature to about 1.8 °F. The archive carries tenths [VERIFIED temp_cadence:52-54].
  - The corpus parser drops the 4-digit T-group, e.g. KBOS goes from 59.4 to 7.1 rows/day [VERIFIED temp_cadence:35-41; PLAN:101].
  - Accrual cannot start until a Kalshi data client exists (plan step S7). There is no adapter today [VERIFIED PLAN:23,154].

## 3. Settlement source
- Kalshi settles on **The Weather Company, not NWS**. The CLI code in the rules only identifies the station [VERIFIED ENUM:15-42; PLAN:67].
- Each station needs its own reconciliation of CLI-final against the venue result. The PM divergence rate is **not inherited** [VERIFIED ENUM:45; PLAN:91; AUD-18:996-999].
  - Gate: at least 90 settled events per station, Wilson lower bound above 0.99, voids raise [VERIFIED PLAN:91].
  - The plan scopes this gate to HIGH only. LOW needs its own [INFERRED].

## 4. Power statement (per B-2)
**No MDE, bound, or n-target can be quoted until Kalshi has its own §6.3-equivalent triage and comparator evidence** [VERIFIED RULING_RA-13:88].

This also voids the plan's 0.25 take rate, its n=60/n_max=160 table and its θ placeholder of 0.07 for power use. All three are PM-derived or unverified [VERIFIED PLAN:15,108,204-210].

Prerequisite evidence for that triage:
1. Kalshi's own hypothesis-class table (Kalshi's own §6.3), separate from the PM.us one. Today Kalshi is "out of programme scope" [VERIFIED AUD-18:758,994-995].
2. Kalshi's own α budget and MAX_HYPOTHESES, derived from that class count [VERIFIED AUD-18:994-995; RULING_RA-13:87].
3. Per-station settlement reconciliation for HIGH, and a separate one for LOW [VERIFIED PLAN:91; INFERRED for LOW].
4. A verified Kalshi fee θ (browser-fetched PDF or first-fill derivation) [VERIFIED PLAN:108].
5. Kalshi venue ladder/quote history, the comparator corpus. There are no historical ladders; the PM analogue is at AUD-18:752 [INFERRED].
6. A Kalshi analogue of the market-vs-forecast resolution comparison. The PM.us TERMINAL ruling does not transfer by assertion [VERIFIED AUD-18:751; INFERRED].
7. Take rate / liftable-quote rate per station-day, measured in Kalshi shadow [VERIFIED PLAN:157,177].
8. Per-station archive cells with n_min=90, after the parser fix [VERIFIED PLAN:99,156].
9. The KDEN live recheck (2 or more days) and KHOU archive-density sizing [VERIFIED temp_cadence:87; PLAN:87-88].
10. Listing persistence and the fraction of station-days actually listed [INFERRED].
11. LOW-window cadence and HIGH/LOW dependence, i.e. effective n [INFERRED].

## 5. Branch `wip/kalshi-s4-registry`
- It was created from `d2faeab` and holds one commit, `58280b6`: "S4 registry entries + Kalshi tally unit — PARKED per operator priority 2026-09-04". Epoch 1788557565 is 2026-09-04 21:32:45Z [VERIFIED .git/logs/refs/heads/wip/kalshi-s4-registry:1-2; epoch arithmetic INFERRED].
- **Coordinator-verified (`git show --stat 58280b6`):** 8 files, +618/−17 — `deploy/systemd/breezy-kalshi-crh-tally.{service,timer}`, `src/breezy/registry/sites.toml` (+233), `runtime/observation_composition.py`, `runtime/settings.py`, 3 test files. `sites.toml` adds exactly KLAX, KMDW, KMIA, KSFO — shared cities only; **zero new-station entries** (confirms the INFERRED line below).
- Plan step S4 covers only the **shared** cities (LAX, MDW, MIA, SFO). So the branch most likely carries no new-station entries [VERIFIED PLAN:151; INFERRED for the branch contents].
- It is 23 days stale, so a rebase is non-trivial [INFERRED].

## 6. Recommended K-2 preconditions
K-2 starts **only on a programme KILL** [VERIFIED RULING_RA-13:48,65].
1. A `RULING_RA-13_programme_kill_<date>` has been issued: the first nightly triage on or after 2027-01-25 with none of R2-R4 [VERIFIED :48; B-5 :95-97]. A failed archive-recal re-plan alone does not fire the KILL [VERIFIED B-1 :83-85].
2. Starting K-2 is a peer-loop decision, not an operator one. K-1 never displaces PM.us work [VERIFIED B-8 :103].
3. Rebase the branch and re-plan through the planning gate against the expansion plan [VERIFIED :65]. The re-plan should:
   - lead with the new stations, not the shared ones [INFERRED];
   - strip the PM-derived numbers (§4) [VERIFIED B-2].
4. Widen the firewall/cage (S1') before any `src/breezy/adapters/kalshi/` file exists [VERIFIED PLAN:123-127].
5. Standing invariants: Nautilus unchanged, `allow_short=False`, both caps unassigned, one process with one ledger, and live enablement operator-only [VERIFIED PLAN:19,131,218; RULING_RA-13:65,69].
6. Operator-only items: account/KYC/API key and the θ PDF [VERIFIED PLAN:216-217].
7. Build the §4 evidence items before any Kalshi registration [INFERRED].
