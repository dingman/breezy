# BL-6 — No-Side Instrument Probe (2026-08-31)

Read-only, offline. Question: do the 5 tradable YES buckets have a
complementary NO-side *instrument* on Polymarket.us? Gates whether
`SHORT_YES` is legally representable at the venue at all.

## 1. Corpus definition (load-bearing)

Two distinct, non-overlapping corpora exist on disk; answered over both.

**Corpus A — raw venue captures**, `docs/evidence/venue/polymarket_us/raw/*.json`
(2026-08-25 vintage). Walked every JSON for `market`-shaped objects
(`slug`+`id`+`marketSides`):

```
events_seriesId_35.json 600, search_weather.json 60,
markets_categories_climate.json 20, markets_tagIds_weather.json 20,
search_weather_seriesIds_35.json 12, events_seriesId_35_active.json 12,
4 single-market files 4, markets_slug_open.json 1
TOTAL market objects (w/ dup across files): 729   unique (id,slug) pairs: 680
```
729 matches `EGRESS_PREREQUISITES_2026-08-31.md:189` exactly — this raw tree
**is** the "729 market objects" corpus. Dated 2026-08-25; contains **no**
2026-08-30 slug (checked explicitly for `*nychigh-2026-08-30*` /
`*miahigh-2026-08-30*` — zero hits).

**Corpus B — the 2026-08-30/08-31 catalog backing the backtest**,
`ParquetDataCatalog('/home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us')`.
`catalog.instruments()` → **60** `BinaryOption`s (5 cities × 6 buckets × 2
days) — this is the "60 instruments" figure. The 5 target buckets are in it.

Grammar/schema conclusions are drawn from Corpus A (widest offline sample);
the 5 specific target instruments are cross-checked directly against Corpus B.

## 2. VERDICT: **NO**

No complementary NO-side *instrument* exists for any of the 5 buckets — not
in Corpus A, not in Corpus B — and the id grammar makes one structurally
impossible under the current parser. NO is a side of the *same* instrument's
order, never a second instrument.

## 3. Evidence

**a) Every raw market carries exactly 2 `marketSides`, always `("No","Yes")`,
always sharing one `identifier` equal to the market's own `slug`.** Verified
729/729 in Corpus A: `side count distribution: {2: 729}`; description-tuples
seen: `{('No','Yes')}`; markets with differing side identifiers: **0**.
Example (`market_open_510636_by_slug.json`, slug
`tc-temp-nychigh-2026-08-25-lt79f`): `Yes` side `long:true`, `No` side
`long:false`, **same `identifier`** — one market, one slug, two sides of one
book, not two markets.

**b) The parser enforces this as a hard invariant.**
`src/breezy/adapters/polymarket_us/parsing.py:1058` (`_market_sides`):
identifier of every side must equal `slug` or `InstrumentDefinitionError`
aborts ingestion; exactly one `long:true` side is required and its
`description` becomes `outcome`. A payload where the second side carried a
*different* identifier (a real separate NO instrument) would fail to load,
not silently produce a second `BinaryOption`. All 60 Corpus-B instruments
exist today only because their payload cleared this check — so the invariant
held for the 5 targets' ingestion too, even though their raw JSON predates
Corpus A by 5 days and wasn't independently found on disk.

**c) The id grammar has no side token.**
`src/breezy/adapters/polymarket_us/symbology.py`: `_WEATHER_SLUG_RE` (~124)
captures only `city`, `measure`, `YYYY-MM-DD`, `bounds` — no outcome/side
group. `slug_to_instrument_id` (206) is a pure 1:1 `slug -> InstrumentId`
map. `INSTRUMENT_SEPARATOR = "~"` (107) is explicitly "reserved for a future
composite symbol" and refused today — a documented, unimplemented extension
point, not an active NO-side encoding. Grepped all 680 unique Corpus-A slugs
for `-no`/`-no-`/`noside` — zero matches.

**d) Direct check on the 5 targets** (Corpus B): each has `outcome=="Yes"`
and `info["market_side_ids"]` holding exactly 2 ids (e.g.
`['1115548','1115549']` for `tc-temp-nychigh-2026-08-30-lt82f`) — the YES/NO
`marketSide` row ids from the *same* market, same shape as Corpus A. No
second `InstrumentId` was, or could have been, derived.

```
tc-temp-miahigh-2026-08-30-gte89lt90f.POLYMARKET_US   outcome=Yes
tc-temp-miahigh-2026-08-30-gte91lt92f.POLYMARKET_US   outcome=Yes
tc-temp-nychigh-2026-08-30-gte82lt83f.POLYMARKET_US   outcome=Yes
tc-temp-nychigh-2026-08-30-gte84lt85f.POLYMARKET_US   outcome=Yes
tc-temp-nychigh-2026-08-30-lt82f.POLYMARKET_US        outcome=Yes
```

**e) Consistent with the repo's prior direction-encoding finding**
(`EGRESS_PREREQUISITES_2026-08-31.md:166-169`): `outcomeSide`+`action` decide
direction; `price.value` always means YES — trading NO at X sends `1.00-X` on
the *same* instrument. Corroborated structurally here (there is nothing else
to address), but I did not re-verify the order-schema precedence citation
itself in this pass.

## 4. What a P5 live probe would need to ask

NO is a side of the same instrument, not a second instrument, so BL-6 cannot
be closed further offline. Remaining unknowns are execution-time:
1. Does live order entry accept `outcomeSide=NO` on these 5 `InstrumentId`s
   and invert price as documented, vs. reject/misbehave? `GET
   /v1/order/preview`, if non-mutating (egress doc B-2 item 2), is the
   zero-capital probe.
2. Given the empty-YES-bid finding, is the NO side actually fillable — a NO
   buy still needs NO-side depth, never captured here.
3. Does the single per-market `feeCoefficient` (`theta=0.06`/`-0.0125`) apply
   identically to a NO fill, or does the venue split it — payload carries one
   value, not one per side.

## 5. Unverified / could not check offline

- Live order-entry acceptance of `outcomeSide=NO` — no order has ever been
  submitted (egress doc: "no fill payload has ever been observed").
- NO-side order-book depth for the 5 targets — not inspected in this pass.
- Whether the 2026-08-30 raw payloads reproduce Corpus A's pattern
  byte-for-byte — inferred from (b), not directly observed (raw JSON for
  that date is not on disk). Flagged rather than overstated.

No file outside this document was modified.
