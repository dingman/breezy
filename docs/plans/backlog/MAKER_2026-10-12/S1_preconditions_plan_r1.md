# S1 — Stage 0 preconditions (maker-window tape census + TRADE_QUANTITY_UNIT)

| Field | Value |
|---|---|
| ID | S1 |
| Title | Stage 0 preconditions: tape census 2026-08-30..2026-10-13 (LAX/MDW/MIA/SFO) with trade prints; resolve `TRADE_QUANTITY_UNIT` |
| Revision | r1 |
| Date | 2026-10-12 |
| Status | DRAFT (planning only; nothing built, nothing run) |
| Spec | `docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md` v0.2, §6.0, §6.1, §7.6, §9.3, §9.4 |

## 1. Goal state (acceptance test)

S1 is done when all four of these exist on the branch:

1. **A committed censused-day list** that Stage 0 reads and nothing else may override. It is written to
   `~/.local/share/breezy/derived/maker/s1/censused_days.jsonl`, and its sha256 is quoted in the evidence doc.
   There is one row per (station, climate_day) for LAX/MDW/MIA/SFO, 2026-08-30..2026-10-13, using a closed
   eligibility alphabet. Each row carries `maker_window_coverage`, `prints_total`, `prints_buyer`, `prints_seller`,
   `prints_no_aggressor` and `firewall_class` ∈ {`PRE_FREEZE`, `SEARCH_DECLARED`}. The doc states one number:
   **E = eligible station-days with ≥ 1 known-aggressor print in the maker window.**
2. **A documented unit verdict.** `TRADE_QUANTITY_UNIT` ∈ {`CONTRACTS`, `USD_NOTIONAL_YES`, `USD_NOTIONAL_TAKER`}
   comes from matching our own durable fills to recorded prints. If the evidence cannot separate the hypotheses,
   the verdict is the explicit token `UNRESOLVED`.
3. **The code change that records the unit.** `parsing.TRADE_QUANTITY_UNIT` is changed from `"UNRESOLVED"` to the
   verdict, and its RED→GREEN pin test is rewritten to match. The constant changes only if item 2 resolved the unit.
4. **One evidence doc**, `docs/evidence/MAKER-S1_preconditions_<run-date>.md`. It contains E, the unit verdict, the
   empirically confirmed YES→NO inversion (§5.3), the SEARCH-forfeiture tally, and the `census_provenance:` line.

## 2. Entry criteria and STOP conditions

**Entry (all required):**
- A worktree off `feat/data-capture-and-risk`; every command carries `PYTHONPATH=<wt>/src`; no uv/pip from the
  worktree; never `git stash`.
- **≥ 10 GB free disk.** At plan time `/` had **5.0 GB free (100 %)**, below the collector floor and the ~1 GB gate
  basetemp. **No WP gate or run starts until a coordinator frees space** (S1 never deletes tape).
- `breezy-quote-tape.service` active; no other heavy job (`systemctl --user list-units 'breezy-*'`, `breezy-studies.lock`).
- **Before any post-2026-09-25 climate day is read: WP0's SEARCH declaration is committed** (§3.2).

**STOP conditions:**
- **S-1 (tape):** if E < 25 over the PRE_FREEZE plus SEARCH_DECLARED days, Stage 0 waits for tape. The evidence doc
  then states the projected date when E reaches 25, using the measured per-day eligible rate. It never relaxes the
  eligibility rule to get there.
- **S-2 (unit):** if the unit verdict is `UNRESOLVED` after the primary check and both fallbacks (§6, WP2), §6.1 fill
  simulation cannot run. Stage 0 waits, the constant stays `"UNRESOLVED"`, and the doc records why.
- **S-3 (premise break):** the own-fill match may show a print that is not on the YES instrument, a NO-taker fill
  that does not print as SELLER at `1 − cost`, or a YES-taker fill that does not print as BUYER at `cost`. Any of
  these means the inversion in §5.3 is false. STOP, and send it back to the spec for a revision before S2.
- **S-4 (firewall):** if the peer loop does not endorse WP0, run the census on PRE_FREEZE days only. If that gives
  E < 25, apply S-1.

## 3. Simplest direct path

### 3.1 Path

(1) Write a ~300-line sidecar census over the maker's own window and run it once under systemd-run. (2) Match our
three pre-freeze own fills (09-21 MIA NO 0.12, 09-21 SFO YES 0.35, 09-22 MDW NO 0.12) to recorded prints; trade
capture has run since 2026-09-16 (`4d6bb059`), with journal quantity-unit evidence lines from 09-17. (3) Flip one
constant.

Why nothing heavier is justified:
- The existing AUD-09a census **cannot answer the maker question**. Its window is `[12:00, 17:00)` LST on D
  (`replay_sufficiency.py:207-222`). The maker rests bids from D−1 12:00Z to **D 09:00 LST** (spec §3), which is
  disjoint from that window.
- Its `ReplaySufficiency` schema has 20 callers, including `promotion_criteria`, `replay_daily_runner` and
  `r3_viability`. Changing that schema to add a second window or print counts would ripple into the promotion path.
  A sidecar that **reuses the census's instance classifier and feather readers** is the smallest correct extension.
- Re-running the unchanged AUD-09a census adds nothing Stage 0 consumes, so it is **not** part of S1.

### 3.2 What RA-13 B-3 actually forbids, and why a census does not lift it

- **B-3 does not ban reading.** It rules that "the firewall binds the corpus, not the statistic". **Any** count on
  post-2026-09-25 tape, outcome-blind or not, permanently spends those station-days' H-ARCHIVE-RECAL CONFIRM status
  (`RULING_RA-13_programme_kill_2026-09-27.md:89-92`).
- The carry-forward rule is in `EDGE-4_DISPOSITION_2026-09-27.md` ("What carries forward"). An exploratory statistic
  may read post-freeze station-days only if that corpus is **explicitly declared SEARCH** for
  H-ARCHIVE-RECAL-2026-09, **with the cost recorded in both plans**.
- **Carve-outs are named, not generic.** Only the AUD-09a sufficiency census and replay-daily are carved out
  (`RA-13:26`; `RA-13-FW_firewall_audit_2026-09-27.md`). The exit-window precedent shows the conservative handling of
  a new tape reader: the read is declared SEARCH, the declaration is dated, and the tally is kept.
- **TE-3 complied by reading nothing after 09-25** (`RULING_TE-3…:4,48`).
- **Therefore a census does not lift B-3.** A census does two things:
  - it satisfies spec §7.6 ("no un-censused tape in the sample");
  - it tells Stage 0 which days are usable.
- **The SEARCH declaration (WP0) is what licenses the post-freeze read.** S1's new maker-window census is itself a
  new statistic, so it needs that declaration too. It is not covered by the AUD-09a carve-out.
- **Cost:** at most 4 stations × 18 days = 72 station-days leave the EDGE-4 revival count. That count needs ≥ 300
  post-freeze CONFIRM station-days and was projected for about 2026-11-24 at 5 per day. NYC is untouched. The
  forfeiture delays revival by about 14 days, to roughly 2026-12-08, which is still inside the 2027-01-25 backstop.
- **Programme-level flag (not S1's decision):** an S5 prospective shadow run on these four stations would make most
  future station-days SEARCH as well. Revival accrual would fall to NYC-only (about 1 per day), so R3 could not fire
  before the backstop. Q1 in §10 raises this.

## 4. Invariants (restated; S1 respects every one)

- Nautilus Trader is immutable (native types and readers only); `allow_short` stays `False`; no value is assigned to
  the max daily budget or max per position; live enablement, `BREEZY_ORDERS_ENABLED` and the A1 halt are untouched;
  no frozen PREREG.json is edited and no pre-registered date moves; the FQ-v2 NO-TRADE ruling stays in force.
- No safety, settlement, contract or NO-SEND egress-firewall test is weakened or deleted; exact-set barriers are
  widened only by one reviewed row (L-12). Stage 0 output is EXPLORATORY, never promotion evidence.
- **S1 makes zero network calls**; exec sqlite `mode=ro`; catalog read-only.
- Rewriting `test_the_print_size_unit_is_declared_unresolved` is not weakening a guard (stricter venue-fact pin).

## 5. Nautilus null-hypothesis check

### 5.1 Native capability per need

| Need | Native capability | Evidence | Gap? |
|---|---|---|---|
| Print record with direction | `nautilus_trader.model.data.TradeTick` with `AggressorSide` | built at `parsing.py:995-1000`; `_TAKER_SIDES` `parsing.py:283-289` | none |
| Read recorded feather streams | `ArrowSerializer.deserialize(data_cls, table)` | `cli_basis_offer_gate_scan.py:611-633` (`_load_stream`, already imported by the census at `replay_sufficiency_census.py:84,904`) | none |
| Depth / queue state | `OrderBookDepth10` (10 levels fixed) | `parsing.py:198-200` | none |
| Rung identity per instrument | `BinaryOption.info` → `read_weather_bucket_facts` (Breezy) | `weather_bucket_facts.py:90-124` | none |
| Instance classification (CLEAN/LIVE/EMPTY/CORRUPT) | Breezy census primitives `scan_instance`/`classify_instance` | `replay_sufficiency_census.py:1031-1067` | reuse |
| Capture gaps | recorder's `custom_quote_tape_gap` stream, already read by `replay_sufficiency.py` | on disk under every instance | reuse |
| Maker fill matching (S2's, not S1's) | `BacktestVenueConfig(trade_execution=True, queue_position=True)`. "A SELLER trade can match resting BUY orders" | `docs/reference/nautilus/v1.231.0/concepts/backtesting/trade-execution.md:3,29-34,96` | none, but it caps fills at `trade.size` **in instrument units**, so S1's unit verdict is a precondition for using it |
| Venue quantity unit | none. This is a venue fact Nautilus cannot know | — | **genuinely missing: S1 WP2** |
| Maker-window coverage + per-station-day print counts | none. The census window is afternoon-only | `replay_sufficiency.py:207-222` | **genuinely missing: S1 WP1** |
| Post-freeze firewall enforcement | governance, not Nautilus | §3.2 | **WP0 + a refusal in WP1** |

### 5.2 Bound for S2

Nautilus matches trades and orders on the **same instrument**, but PM.us prints arrive on the YES instrument only
(`parsing.py:936-938`). S2 therefore has to derive NO-frame ticks from YES-frame ticks using §5.3 before feeding the
engine. S1 supplies the verified mapping; it builds nothing.

### 5.3 YES→NO price and side inversion for a NO buy as a maker

**On the venue.** A resting **BUY NO at b** is sent as `ORDER_SIDE_SELL` / `ORDER_INTENT_BUY_SHORT` at wire price
`1 − b` (`leg_prices.py:39-46,56-75`), i.e. a **YES ask at `1 − b`**; "NO bid at ≥ b" ≡ "YES ask at ≤ 1 − b".

**What fills it.** Only a YES print with **aggressor = BUYER** (a YES buyer, or a NO seller closing, lifts YES
asks) **and YES price ≥ 1 − b**. In the NO frame that is a SELLER print at `1 − p_yes ≤ b`, matching Nautilus's
"SELLER trade can fill resting BUY". SELLER-aggressor YES prints are NO-buyers *taking*: they compete, never fill.

**Spec erratum (for the spec owner).** §6.1's "a YES print at price ≤ 1 − b with aggressor SELLER" mixes frames and
selects the wrong flow. Correct: YES print `p_yes ≥ 1 − b`, aggressor **BUYER** ≡ NO-frame print `≤ b`, **SELLER**.

**Empirical check.** WP2 verifies the taker-side half of this mapping from our own fills. Our NO IOC buys were
takers, so they must print as SELLER at `1 − cost`, and our YES buy must print as BUYER at `cost`. If they do not,
STOP S-3 applies.

## 6. Work packages

All new tests run RED first. Every focused gate is:

`PYTHONPATH=<wt>/src /home/jon/breezy/.venv/bin/python -m pytest <tests> tests/unit/test_polymarket_us_fee_guard.py <exec-import-pin + NO-SEND firewall tests> --basetemp ~/.cache/breezy-pytest/s1-<wp>`

The NO-SEND firewall tests run in every focused gate.

Each WP then runs `cd <wt> && lint-imports`, and the output must show "N kept, 0 broken".

### WP0 — SEARCH declaration (docs only, peer-loop ruling; ~1 h)

- **Create:** `docs/evidence/RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md`.
- **Contents:** the basis (§3.2); scope LAX/MDW/MIA/SFO × climate days 2026-09-26..2026-10-13, NYC excluded; the
  cost (≤ 72 station-days forfeited from EDGE-4 revival, and its date effect); coverage of S1 and S2 Stage 0 reads
  only, never S5; and one machine-readable line WP1 parses: `SEARCH_DECLARED: LAX,MDW,MIA,SFO 2026-09-26..2026-10-13`.
- Record the same cost in the H-ARCHIVE-RECAL/AUD-18 record, as the EDGE-4 rule requires "both plans".
- **Review:** prediction-market-reviewer plus architect, blind.
- **Done when:** the ruling is committed and reviews are in `reviews/S1-WP0-*.md`.

### WP1 — maker-window census (sidecar; ~6 h build, ~1–2 h run)

**Create `src/breezy/analysis/maker_tape_census.py`.** It is pure, imports no Nautilus (import-linter contract
"offline analysis layer never DIRECTLY imports Nautilus") and is about 150 lines:
- `FREEZE_LAST_DAY: Final = dt.date(2026, 9, 25)`
- `MAKER_STATIONS: Final = frozenset({"LAX", "MDW", "MIA", "SFO"})`
- `maker_window_ns(*, climate_day: dt.date, std_utc_offset_hours: float) -> tuple[int, int]` returns
  `[D−1 12:00Z, D 09:00 LST)`. It uses integer arithmetic, copying `decision_window_ns`.
- `@dataclass(frozen=True) CensusedDay` has station, climate_day, firewall_class, instances_clean, coverage_fraction,
  max_gap_minutes, prints_total, prints_buyer, prints_seller, prints_no_aggressor, rungs_with_prints, eligible and
  reason. It has explicit `to_dict`/`from_dict` and **no `asdict`** (credential-serialisation guard).
- `classify(...) -> CensusedDay`. The eligibility rule is `coverage_fraction ≥ COVERAGE_MIN (0.90)` **and**
  `max_gap_minutes ≤ GAP_MAX_MIN (30)` **and** `prints_buyer + prints_seller ≥ 1`. The constants are declared before
  any run and never tuned afterwards.
- `parse_search_declaration(text: str) -> tuple[frozenset[str], dt.date, dt.date]`
- `require_firewall_clearance(station, day, declaration | None) -> str` raises `FirewallRefused` on a post-freeze day
  without cover, or on any station not in `MAKER_STATIONS`.
- `write_censused_days(path, rows)` / `read_censused_days(path) -> tuple[CensusedDay, ...]` writes sorted,
  byte-idempotent JSONL. The reader refuses unknown keys or a duplicate (station, day).

**Create `scripts/analysis/maker_tape_census.py`.** This is the I/O layer, about 200 lines.
- **Flags:** `--from`, `--to`, `--stations`, `--search-declaration PATH`, `--output`, `--catalog-root` (default
  `~/.local/share/breezy/catalog/quote_tape/polymarket_us`) and `--subdirectory live`.
- **Per instance:** run `scan_instance` + `classify_instance`. Only CLEAN instances are read; LIVE and CORRUPT are
  counted in `reason`.
- **Per station-day:**
  - Select the instrument dirs whose `binary_option` facts match the station, the climate day and `Measure.HIGH`.
  - Fold Depth10 `ts_event` into a per-station sorted timestamp list. Read only the ts column through
    `breezy.persistence.catalog_column_scan` (UNVERIFIED on raw feather; the fallback is a per-file deserialize
    that is discarded after the fold).
  - Subtract `custom_quote_tape_gap` intervals.
  - Load `trade_tick` with `_load_stream([...], "trade_tick", TradeTick)`. These files are small, 0.3–15 MB per
    instance. Count prints in the window by aggressor.
- It emits a `census_provenance:` stdout line with the git sha, the stations, the range, the declaration sha256 and
  the instance-id count. It also writes one progress line per station-day to stderr; the stall watch keys on these.
- It writes nothing under the catalog.

**RED-first tests** (`tests/unit/test_maker_tape_census.py`): `test_maker_window_spans_d_minus_1_noon_utc_to_d_0900_lst`,
`test_post_freeze_day_refused_without_search_declaration`, `test_post_freeze_day_outside_declared_range_refused`,
`test_nyc_is_refused_even_with_declaration`, `test_eligible_requires_known_aggressor_print_and_coverage`,
`test_no_aggressor_prints_never_make_a_day_eligible`, `test_censused_days_round_trip_is_lossless_and_refuses_extra_keys`,
`test_write_is_byte_idempotent_regardless_of_input_order`, and the script-level
`test_live_instance_is_counted_never_read` (tmp feather fixture built with the census's existing test helpers).

**Run plan** (executes after WP review, not under this plan): (a) **subset benchmark first**, one pre-freeze
station-day (SFO 2026-09-21) under `/usr/bin/time -v`, recording wall time and peak RSS; (b) **Pass A, PRE_FREEZE**,
2026-08-30..2026-09-25, no declaration needed; (c) **Pass B, SEARCH_DECLARED**, 2026-09-26..2026-10-13, only after
WP0 is committed and **at or after 2026-10-14 10:00Z** (the 10-13 window lies partly in the 10-13 boot instance,
LIVE until the 10-14 09:00Z rotation), clear of the 15:20Z/15:50Z studies.
- **Template:**
  ```
  systemd-run --user --unit=breezy-maker-s1-census-<pass> --slice=breezy-studies.slice \
    -p MemoryHigh=3G -p MemoryMax=4G -p RuntimeMaxSec=<3 × benchmark-projected, min 1800> \
    -p LimitNOFILE=524288 -p WorkingDirectory=<wt> -E PYTHONPATH=<wt>/src --collect \
    /usr/bin/flock -w 600 "$XDG_RUNTIME_DIR/breezy-studies.lock" \
    /home/jon/breezy/.venv/bin/python scripts/analysis/maker_tape_census.py --from … --to … \
    --stations LAX,MDW,MIA,SFO [--search-declaration docs/evidence/RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md] \
    --output ~/.local/share/breezy/derived/maker/s1/censused_days.<pass>.jsonl
  ```
- **Stall watch:** arm a Monitor in the launch turn; stop the unit if the progress line stalls 15 min; wait on
  ActiveState ∉ {active, activating}. **Merge** both passes into `censused_days.jsonl` via `read_censused_days` +
  `write_censused_days` (a duplicate key is refused).

**Done when:** tests GREEN; lint-imports passes; python-reviewer clean (blind); both passes exited 0 with their
provenance lines quoted; E computed by the script, never by hand.

### WP2 — `TRADE_QUANTITY_UNIT` evidence (~3 h build, minutes to run)

**Create `src/breezy/analysis/trade_quantity_unit.py`.** It is pure and about 80 lines.
- `UNIT_HYPOTHESES = ("CONTRACTS", "USD_NOTIONAL_YES", "USD_NOTIONAL_TAKER")`
- `@dataclass(frozen=True) OwnFillMatch` has leg, fill_cost: Decimal, fill_qty: Decimal, print_price_yes: Decimal,
  print_size: Decimal, print_aggressor: str and dt_ns: int.
- `predicted_size(h, m)` is defined as:
  - CONTRACTS → `fill_qty`;
  - USD_NOTIONAL_YES → `print_price_yes × fill_qty`;
  - USD_NOTIONAL_TAKER → `fill_cost`.
- `classify_trade_quantity_unit(matches) -> tuple[str, str]` returns a verdict and a reason. It resolves only if
  every match fits exactly one hypothesis (exact Decimal equality at 4 dp) **and** at least one match is a NO-leg
  fill. Only a NO-leg fill separates the YES notional from the taker notional: for a NO fill at 0.12 the three
  predictions are 1, 0.88 and 0.12. It also needs at least 2 matches. Anything else returns `UNRESOLVED`.
- `inversion_holds(m) -> bool` requires:
  - NO-leg: aggressor SELLER and `print_price_yes == 1 − fill_cost`;
  - YES-leg: aggressor BUYER and `print_price_yes == fill_cost`.

**Create `scripts/analysis/trade_quantity_unit_crosscheck.py`.** It is about 120 lines.
- Reads `exec/polymarket_us/fill/*` from `~/.local/share/breezy/state/exec_polymarket_us.sqlite` (`mode=ro`; 34 rows,
  qty 1, `cumulativeCost`, `instrumentId`, `tsEvent`); keeps climate day ≤ 2026-09-25 and `tsEvent` ≥ 2026-09-16
  (the 09-21 MIA NO, 09-21 SFO YES, 09-22 MDW NO fills).
- Per fill, loads `trade_tick` for `yes_instrument(instrumentId)` (`capture_audit_fill_support.py:183`) from the CLEAN
  instances covering `tsEvent`; candidates within ±5 s; reports every candidate and the nearest, never silently picks.
- Writes a JSON result and prints the verdict.

**Fallbacks (only if the primary returns UNRESOLVED):**
- **F1:** the same matcher over the 25 post-freeze fills (10-01..10-05). They fall inside WP0's declared range, so
  they cost no extra forfeiture; requires `--search-declaration`.
- **F2:** Depth10 corroboration on PRE_FREEZE days: at each print instant the YES level at the print price should
  drop by the print size; median `Δlevel / size` vs 1 (contracts) and vs `1/p_yes` (USD). Assumes book `qty` is
  contracts (venue docs, `parsing.py:217-220`). Corroboration only, never alone.
- **Not planned:** the REST activities endpoint (needs egress + credentials; its own brief).
- **Prior only:** journal first-print lines (e.g. `'10.3300'` USD at 0.19, `'3.2500'` at 0.47) are fractional under
  every hypothesis and decide nothing.

**RED-first tests** (`tests/unit/test_trade_quantity_unit.py`): `test_no_leg_fill_separates_all_three_hypotheses`,
`test_yes_leg_only_matches_cannot_resolve`, `test_disagreeing_matches_are_unresolved`,
`test_fewer_than_two_matches_are_unresolved`, `test_inversion_holds_for_no_taker_as_seller_at_complement`,
`test_inversion_fails_on_buyer_aggressor_for_no_taker`, `test_crosscheck_reads_exec_db_read_only` (`mode=ro` in the URI).

**Done when:** tests GREEN; the verdict and the inversion result are emitted by the script; STOP S-3 evaluated.

### WP3 — record the unit (~1 h; only if WP2 resolved)

**Modify `src/breezy/adapters/polymarket_us/parsing.py:225-231`.**
- Set `TRADE_QUANTITY_UNIT: str = "<verdict>"`.
- Rewrite the comment to cite the evidence doc and the matched fills.
- Update the `parse_trade_tick` docstring line "**size is unit-unresolved**".
- Do not convert units in the parser. Recorded tape semantics stay byte-stable, and conversion belongs to S2.

**Modify `src/breezy/adapters/polymarket_us/data.py:1863-1866`.** The log text interpolates the constant instead of
the literal "is UNRESOLVED". There is no other behaviour change.

**Modify `tests/unit/test_polymarket_us_depth_parsing.py:431-438`.**
- Replace `test_the_print_size_unit_is_declared_unresolved` with
  `test_the_print_size_unit_is_resolved_by_own_fill_crosscheck`. It asserts the verdict value, and asserts that
  `docs/evidence/MAKER-S1_preconditions_*.md` exists and names it.
- Order: write the new test first (RED against `"UNRESOLVED"`), then flip the constant (GREEN).

**Gate:** focused gate, then the **full gate** `scripts/ci/run_tests_no_egress.sh --basetemp ~/.cache/breezy-pytest/s1-full`; read EXIT, then `rm` the basetemp.

**Activation:** at the next scheduled 09:00Z recorder rotation and the node's next scheduled spawn. **No manual
recorder restart**, for a concrete reason: it opens a capture hole in the tape S2/S5 need, for a log-string change.

### WP4 — evidence doc + PROGRESS row (~1 h)

- **Create:** `docs/evidence/MAKER-S1_preconditions_<run-date>.md`: E by pass and by station; the eligible list (or
  sha256 plus row count); the `census_provenance:` lines; the unit verdict and match table; the inversion result; the
  forfeiture tally (station-days actually read post-freeze); the spec §6.1 erratum; which STOP fired, if any.
- Add a one-line row to `docs/core/PROGRESS.md`.
- Commit at the milestone, then push after the gate is green and EXIT has been read.

## 7. Data and tooling dependencies

| Item | Path | Status |
|---|---|---|
| Raw tape (81 instances, 293 GB) | `~/.local/share/breezy/catalog/quote_tape/polymarket_us/live/<uuid>/{binary_option*,order_book_depths/,quote_tick/,trade_tick/,custom_quote_tape_gap/}` | present; per-instrument subdirs |
| Converted catalog (4.8 GB) | `…/polymarket_us/data/` | present; **not used**. Its completeness is in doubt because of the open ingest-interval collision fix |
| Trade capture start | commit `4d6bb059` (2026-09-16); first journal evidence line 2026-09-17 09:00Z | VERIFIED (journal) |
| Durable fills (34) | `~/.local/share/breezy/state/exec_polymarket_us.sqlite`, table `state`, keys `exec/polymarket_us/fill/<venueOrderId>` | VERIFIED; 3 pre-freeze fills inside the trade-capture era |
| Existing census output | `~/.local/share/breezy/derived/replay/replay_sufficiency.jsonl` (computed_day 2026-09-30) | not consumed. The census has not run since; replay-daily exits in under 1 s |
| Feather readers | `cli_basis_offer_gate_scan._load_stream`, `catalog_column_scan` | `_load_stream` VERIFIED for `binary_option`; **UNVERIFIED** for `trade_tick` and the column scan on raw feather (first RED fixture proves it) |
| Gap stream semantics | `custom_quote_tape_gap` | **UNVERIFIED** meaning (recorder-side gap vs feed silence); WP1 reads `src/breezy/runtime/quote_tape_gaps.py` before using it |
| Fill `tsEvent` vs venue `tradeTime` clock | exec report field | **UNVERIFIED** alignment; ±5 s tolerance plus nearest-candidate reporting |
| Disk | `/` | **5.0 GB free at plan time: entry blocker** |

## 8. Risks → invariant → guard

| Risk | Invariant at stake | Guard |
|---|---|---|
| A post-freeze read without declaration contaminates the CONFIRM corpus | RA-13 B-3 firewall | `require_firewall_clearance` refusal and its RED test; Pass B gated on the committed WP0 |
| NYC accidentally read | B-3 cost scope; spec excludes NYC | closed `MAKER_STATIONS` set and its test |
| Census OOM or stall on 293 GB tape | one-heavy-job rule; node safety | studies slice, MemoryMax 4G, RuntimeMaxSec, flock, subset benchmark, progress-line Monitor |
| Test basetemp fills `/` (already at 100 %) | host stability, recorder capture | entry criterion of ≥ 10 GB; basetemp under `~/.cache`; rm after EXIT |
| New test imports exec and trips the exec import pin | NO-SEND/egress exact-set pins (L-12) | S1 tests never import `exec/`; pins run in every focused gate |
| Agent runs `ruff format` on whole dirs | byte-pinned exec client | brief says "format only your files"; `git status` checked before commit |
| Unit flipped on a coincidental print | correctness of S2 fills | ≥ 2 matches, one of them NO-leg, exact Decimal equality, every candidate in a ±5 s window reported; otherwise UNRESOLVED |
| Thresholds tuned after seeing E | Stage 0 honesty | `COVERAGE_MIN`/`GAP_MAX_MIN`/eligibility defined in code before the run; changing them requires a new revision of this plan |
| Rewriting the unit pin test read as "weakening a test" | L-12 / guard rule | the new pin is stricter (resolved value plus evidence citation); reviewer sign-off in WP3 |

## 9. Effort and the evidence artifact

~**16 agent-hours** (WP0 1, WP1 6 + ~2 h run wall, WP2 3, WP3 1, WP4 1, blind reviews 2–3), plus the wait to
2026-10-14 10:00Z for Pass B. **Single evidence artifact:** `docs/evidence/MAKER-S1_preconditions_<run-date>.md`
(WP0's ruling is a governance input to it, not evidence).

## 10. Open questions for peer review (≤ 5)

1. **SEARCH scope across the programme.** WP0 declares only 09-26..10-13. An S5 shadow run on LAX/MDW/MIA/SFO would
   make every later station-day SEARCH, leaving EDGE-4 revival to NYC alone, so it is unreachable by 2027-01-25.
   Should that trade be ruled now, before S2 spends effort, rather than at S5?
2. **Eligibility definition.** Should the E ≥ 25 threshold count any known-aggressor print, or only **BUYER**-aggressor
   prints at YES prices ≥ 0.20? Under §5.3 only those could fill a NO bid at b ≤ 0.80. The stricter count is the
   honest denominator for Stage 0's fill-rate test.
3. **Coverage thresholds.** Are 0.90 coverage and a 30-min maximum gap over `[D−1 12:00Z, D 09:00 LST)` right? The
   09:00Z rotation sits inside every maker window, and the 09-02 empty-listing hole is a known pattern.
4. **Pre-freeze sufficiency.** If Pass A alone reaches E ≥ 25 (trade capture covers about 09-16..09-25), should
   Pass B be skipped? It would avoid the 72-station-day forfeiture, at the price of a smaller Stage 0 sample.
5. **Print attribution.** Can a taker's single qty-1 IOC appear as more than one print (one per maker), or as a
   print net of fee? Either would break exact equality, so should the classifier accept a sum of prints within
   ±5 s?
