# G-19 — Autonomy sweep: remove operator-supplied venue FACTS

## Governing principle (operator, stated twice, verbatim)

> "The bot itself must be capable of autonomous discovery, the operator will never
> provide that information."

Read as a global rule, not a slug-specific fix:

- **Anything the venue can tell the bot, the bot must find out itself.**
- Operator input is reserved **strictly for enablement ceilings**: real-money
  authorization, spend caps, credentials, contact strings, deploy paths.
- A venue fact behind an operator gate is a **mislabelled blocker**, not a blocker.

This item exists because G-18 fixed slug discovery and then, in the same report,
two fresh violations of the same principle were committed: telling the operator to
add `POLYMARKET_US_DISCOVERY_RELOAD_INTERVAL_MINS` to their env file, and *asking
permission* to chase `feeCoefficient`. The principle is the deliverable; the code
changes are how it is enforced.

## Classification rule

Every human-supplied input is exactly one of:

- **(A) Enablement ceiling** — legitimate. Money, authorization, contact identity,
  filesystem location, resource caps. Keep.
- **(B) Venue fact or derivable quantity** — illegitimate. Must be discovered from
  venue payloads, or derived from data the bot already holds. Remove as a
  requirement; keep at most as an optional override.

An env var that is **required-no-default** and holds a (B) value is the specific
defect shape this item removes: it makes the bot unable to start without a human
reciting a fact the venue already publishes.

## Audit result (2026-08-26)

Full enumeration of every env var read under `src/`, every hardcoded guess, and
every backlog item marked operator-blocked.

### (B) — must be discovered. Ranked by value.

| # | Item | Where | Discovery source |
|---|---|---|---|
| B1 | `POLYMARKET_US_API_BASE` / `_GATEWAY_BASE` / `_WS_URL` | `config.py` `REQUIRED_FIELDS`; `factories.py:105-107,143-157` | Venue constants; already in the captured docs snapshot and `headers/` captures |
| B2 | `POLYMARKET_US_DISCOVERY_RELOAD_INTERVAL_MINS` | `factories.py:109,158-172` | `startDate` / `endDate` / `gameStartTime` give the exact turnover instants |
| ~~B3~~ **DONE** | `DEFAULT_DISCOVERY_CITY_CODES` (hardcoded) | deleted from `config.py` | Now `discovery_city_codes_from_registry()`, derived from `registry/sites.toml` and failing closed on empty/colliding venues. Proof it is derived, not recited: a synthetic BOS/DAL registry yields `("bos","dal")` (`test_polymarket_us_config.py`). |
| ~~B3b~~ **DONE** | `city_codes` silently narrowed discovery | `provider.py:84,119` | `_weather_market_payloads` now RAISES `VenuePayloadError` when a weather market names a city with no `polymarket_us` registry entry, mirroring `derive_site_pairs` refusal #1. A market is identified as weather from the venue's explicit `question` prose, not from inferred slug grammar: `^(?:Highest|Lowest) temperature in <city> on `. Verified against the full captured corpus -- 729/729 questions match, yielding exactly Chicago, Los Angeles, Miami, NYC, San Francisco. Unrelated climate markets are skipped, not refused, so the guard stays precise. |
| B3c | weather market with unrecognised prose is silently skipped | `provider.py:84` | **Open, residual of B3b.** The refusal fires only for markets the regex MATCHES. A genuine weather market phrased differently ("Will the high temperature in Boston...") does not match, is skipped, and the B3b refusal never sees it -- the same shape as the defect B3b closed, one level down. The captured corpus is 100%% one phrasing, so there is no evidence of a second form today, and this cannot be closed from the archive alone. Close it by asserting the observed phrasing set against a live listing during G-12 venue discovery, and refusing an unmatched market in the `climate` category that carries a temperature-shaped slug. || B4 | `BREEZY_SITES` (required-no-default) | `settings.py:34,236` | Same series list, intersected with `registry/sites.toml` |
| ~~B5~~ **CLOSED 2026-09-01** | Fee schedule was `UNKNOWN` | `parsing.py:297` `assert_fee_schedule_known` | All 60 captured instruments carry `fee_schedule_status=KNOWN`, `fee_coefficient=0.06`. Note the venue's absolute fee FLOOR is still unmeasured — EXEC_SPINE OQ-8. |
| B6 | Strike/bounds via inferred slug grammar | `symbology.py:89-101` | `description` / `title` carry the authoritative comparator; `marketSides` carries Yes/No |
| B7 | `MARKET_SLUG_KEY = "marketSlug"` (hardcoded guess, G-12) | `data.py:150` | Self-detect: match frame key VALUES against the known slug set |
| B8 | `TRADE_CONTAINER_KEY`, `_TAKER_SIDES` | `parsing.py:136,175-181` | One live trade frame |
| B9 | `EXPIRED_MARKET_STATES`, settlement methods | `parsing.py:144-172` | Longitudinal `status` polling across the market list through a settlement |
| B10 | Four tape disk thresholds (required-no-default) | `settings.py:47-54,327-341` | `shutil.disk_usage` + observed tape growth rate; only the spend ceiling is (A) |
| B11 | `BREEZY_POLL_INTERVAL_SECONDS` | `settings.py:37` | NWS CLI issuance cadence, already in the catalog |
| B12 | `POLYMARKET_US_SIGNING_VARIANT`, `WS_MARKETS_REQUIRES_AUTH` | `factories.py:114-127` | One signed probe: try `PATH_ONLY`, on 401 retry `PATH_AND_QUERY` |

### (A) — legitimate operator ceilings. Keep as-is.

`POLYMARKET_US_KEY_ID` / `_SECRET_KEY` / `_SECRET_KEY_FILE` (real-money credential);
`BREEZY_USER_AGENT` and `POLYMARKET_US_USER_AGENT` (contact strings — cannot be
self-derived and must not be); `BREEZY_CATALOG_BASE`, `BREEZY_STATE_DB`,
`BREEZY_REGISTRY_PATH`, `BREEZY_HEALTH_SNAPSHOT_DIR`,
`BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG` (deploy paths); `BREEZY_PARSE_TIMEOUT_MS`
(resource ceiling); `BREEZY_LOG_LEVEL`, `BREEZY_TRADER_ID`,
`BREEZY_ALLOW_PROXY_ENV`, `BREEZY_ALERT_WEBHOOK_URL`; `BREEZY_VENUE_LIVE`,
`BREEZY_ALLOW_CREDENTIALED_PYTEST`, `--venue-live` (the deliberate live-venue gate);
GO-LIVE gates D1 KYC, D2 funding, D3 probe USD ceiling, D4 `BREEZY_TRADING_ENABLED`,
D5 risk caps.

## Mislabelled backlog items

| Item | Old label | Truth |
|---|---|---|
| G-15 | `BLOCKED (operator: live probe)` | **Resolvable offline.** `feeCoefficient` is in every captured payload. |
| G-12 | `BLOCKED (operator: three-lock + D1 KYC)` | A schema fact. Only the *gate* is (A); the fact is (B) and can be self-detected. |
| DOM-9 (trading hours) | unresolved external question | Derivable from `startDate` / `endDate` / `gameStartTime`. |

## Captured payload fields we hold but do not consume

`description`, `title`, `titleShort`, `question` (authoritative strike and
comparator — today only cross-checked, never primary), `startDate`, `endDate`,
`gameStartTime`, `status`, `ep3Status`, `tags`, `outcomes`, `outcomePrices`,
`marketSides` (Yes/No identity, `long`, `tradable`, per-side quotes), `sortOrder`
(the bucket ladder order). `series_limit100.json` and `events_seriesId_*.json` are
consumed by **nothing** in `src/`.

Every one of these is evidence already paid for and never spent.

## Execution waves

- **Wave 1 (offline, evidence in hand):** B5 (fee), B1, B2, B3, B4.
- **Wave 2 (offline, more design):** B6 (strike from prose), B10, B11.
- **Wave 3 (needs one live frame, behind the (A) gate — but the FACT is still (B),
  so the bot self-detects rather than being told):** B7, B8, B12, then B9
  longitudinally.

Wave 3 is gated on live access, **not** on operator knowledge. When the gate opens,
the bot learns these itself; the operator authorizes, and says nothing more.

## Definition of done

- The adapter constructs and runs with **none** of the (B) env vars set. A test
  asserting exactly that is the deliverable which proves the principle.
- No (B) value remains a required-no-default.
- Every remaining hardcoded venue value cites the evidence file that establishes it.
- Every derivation fails **loudly** on bad data — never falls back to a guess.
- `pytest`, `ruff`, `mypy`, `lint-imports` all clean; the 24 read-only cage barriers
  and fee Barrier F1 still green.
