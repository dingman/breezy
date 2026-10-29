# EXEC-FOREIGN-POS: implementation plan r3 (code-architect, 2026-10-29)

**Item** (docs/core/PROGRESS.md:66; operator ruling 2026-10-29; LESSONS L-69):
- The operator trades by hand in the bot's Polymarket.us account. The bot ignores everything the operator does there.
- A position or open order whose slug is outside Breezy's weather grammar is **FOREIGN**. It is logged once at INFO (slug, qty). It is never netted, sold, hidden or allowlisted, and never a reason to refuse.
- A `tc-temp-*` position with no loaded instrument stays a refusal.
- The `startup_open_orders_present` never-arm gate ignores foreign orders.
- Reconciliation `instrument_absent` counts weather positions only.
- Acceptance: a boot with the 10-28 parlay `crossd-ba05d7244fbd670a` listed binds rests and logs `foreign=1`.

**Base:** `feat/data-capture-and-risk` @ `97dd428a` (HEAD, tree clean). Every line number below was re-read at that commit for r3. Re-read each function with codegraph (projectPath=/home/jon/breezy) before editing it.

**What r3 changes, in brief.**
- **Placement.** The namespace predicate and a new self-identification helper now live in `exec/reports.py`, the read-side mapper the client already imports. `exec/submit_chain.py` is byte-untouched, so C7 row 78 and the NO-SEND-adjacent diff are gone.
- **A row must name itself.** FOREIGN now also requires `marketMetadata.slug` to equal the row's own market: the dict key for positions, `marketSlug` for orders.
  - A sparse or contradictory row keeps today's refusal (fail-closed; R18).
  - Every observed row self-identifies: 1/1 positions, 98/98 activities-embedded orders.
- **DAY only where the ruling needs it.**
  - `TIME_IN_FORCE_DAY` is enumerable only on a self-identifying non-weather row.
  - A weather, unusable or non-self-identifying DAY row still refuses the whole read, exactly as today.
  - r2's R16 behaviour change is withdrawn.
- **Diagnosable refusals (L-37).**
  - A refused open-orders read now logs the bounded mapper message.
  - The boot-sweep and no-id read sites stay byte-identical (firewall-pinned). The evidence refresh that runs after them names the cause.
- **Tests.**
  - IDs are prefixed (T-, S, K, RP, TL, CE-).
  - [CHAR] tests assert observables that exist at base.
  - New tests cover self-identification, the manual tri-state, exception containment, the mapper detail, a hypothesis property, a discovery-discriminator corpus binding, and never-hidden positions.
- **Fewer edits.**
  - 3 changed existing tests (r2: 4). The resolver refresh row never self-identifies, so it needs no change.
  - 3 C7 rows (r2: 4).
- **Acceptance.**
  - The pre-boot probe gains stop rules: a live parse failure, and a non-self-identifying foreign row.
  - An offline sandboxed replay of the saved 10-28 positions body closes the F=0 gap.
  - The PROGRESS close-out consolidates: the file is at 12,093 bytes of its 12 KB budget.

### Hard invariants (restate verbatim in every implementer brief, Grok included)
- **Write mode** must be explicit in every brief. Every review or investigation brief is read-only.
- **Nautilus Trader is immutable.** The change lives only in:
  - Breezy's `LiveExecutionClient` subclass (its native report hooks);
  - Breezy's venue mapper `exec/reports.py`;
  - Breezy strategy code (`trial_day_latch.py`).
- **`allow_short` stays False.**
- **Never weaken or delete a safety, settlement, contract or NO-SEND test** to go green. The ONLY permitted edits to existing tests are CE-1..CE-3 (see "Changed existing tests"):
  - one input re-point;
  - one exact-literal widening;
  - the line-citation numbers in the pins commit, each of which must still resolve to its cited text.
- **Never assign a value to an operator-reserved control.**
  - Tests reuse only the existing `gate_env` / `caps` fixtures.
  - In prose, call the controls only "the daily budget" and "the per-position cap" (L-39).
- **Never touch live-trading enablement or the NO-SEND execution-egress firewall.** That covers:
  - `write_transport.py` and `exec/submit_chain.py` (both byte-untouched in r3);
  - the `SLUG_SCOPED_CANCEL_ALL_VERIFIED` and GTD flags;
  - the `_submit_order` body and `_sweep_resting_orders_at_boot`;
  - every resolver coroutine, `_resolve_no_id_intent` included;
  - every set and allowlist in `tests/unit/test_execution_egress_firewall_guard.py`, `test_resting_path_firewall_delta.py` and `test_ambig_no_id_firewall_delta.py`.
- **Add nothing new:** no module (src or test), service, ledger, unit, config knob, slug allowlist or ruling.
  - The new files are a value-free evidence note (L-37's standing response to venue drift) and the dated P4 read (docs).
- **Text traps in new src text:**
  - In `exec/reports.py` and `exec/client.py` (X3 reads raw text, comments included):
    - never write `_SHORT`, `BUY_SHORT` or `SELL_`;
    - never write `1 - x` arithmetic;
    - never call `float(` or `dataclasses.asdict`.
  - In `reports.py` and `trial_day_latch.py`, never write the tokens `write_transport`, `operator_controls` or `maker_poll_trade_id` anywhere:
    - the D4 importer scan reads every string constant;
    - the operator-controls mention pin and the poll-trade-id writer pin read raw text.
  - In `client.py`, never add a `self._order_sender` reference or a `_refuse(` call.
- **Formatting:**
  - Run `ruff format` in write mode only on files that are format-clean at base (listed under "Pins and gate").
  - Never run it on `exec/client.py`, on any non-clean test module, or on a directory.
- **mypy ratchet is exact both ways.** New test code adds zero mypy errors and removes none. Use typed rig helpers (`wire_payloads`) or `typing.cast`, never a bare attribute access mypy flags.
- **Shared tree and worktree discipline:**
  - Never `git stash`.
  - Commit by explicit path; add a new file with `git add <path>` (never `-A`, never `-N`).
  - In a worktree, set `PYTHONPATH=<tree>/src` for every python, pytest and lint-imports run.
  - Never combine `PYTHONPATH` with `python -I`.
  - Never run an installer.

## Premises

| # | Premise | Holds | Evidence (97dd428a) |
|---|---|---|---|
| P1 | The boot guard refuses every submit while a position has no loaded instrument | YES | See the chain below this table. |
| P2 | The position guard reads only the dict key; the strict pin is never reached for an unloaded slug | YES | `_map_position` 6167-6174 refuses before `parse_position_status_report` (reports.py:1578-1640).<br>The strict mapper refuses a PRESENT `marketMetadata` whose `slug` differs from the key or is None (code 1620-1633; `_assert_market_matches` 860-875). An absent block leaves the key authoritative (docstring 1589-1603).<br>The saved 10-28 row has 22 keys; `marketMetadata` has 6 keys with `slug == key`; `netPosition` is a str; `expired` is False. The body has `eof: true` and `nextCursor` "" (scratch `plan_efp_r3/scripts/shape_positions.py`). |
| P3 | `instrument_absent` is the latch | PARTLY | It is a counter (5796, 5859; line 601-608), never latched (5790-5795). The latch is `_map_position#1` (6170-6173): DURABLE, unscoped, cleared only by a restart with the position gone. |
| P4 | The never-arm gate refuses any open order | YES | Producer: boot 6904-6935 and the resolver refresh 3232-3259 (every 60 s, 643) → `_read_open_orders` 6937-6957 → `_note_open_orders_outcome` 6959-6994 → writer 6711-6757.<br>Consumer: trial_day_latch 1513-1560, with the exemption at 1549-1550. Read by CRH only (continuous_strategy.py:795, 2366). |
| P4b | Real operator orders are refused by the strict enumeration before any classification | YES | `_TIME_IN_FORCE` = FOK/GTC/GTD/IOC (reports.py:483-488). The check at 1861-1863 refuses the whole read (1905-1943).<br>The BASE parser over the 98 activities-embedded orders (scratch `r3_rule_sim.py`) refuses 21, all on DAY:<br>- 9 are non-weather MANUAL: the account's UI orders.<br>- 12 are weather. Each is the PASSIVE side of a Breezy AUTOMATIC IOC, i.e. another account's rest (`day_pairs.py`).<br>Under the r3 rule all 9 parse; the 12 still refuse, and they are never in our book. |
| P4c | P4b reaches the live maker | YES | The boot sweep parses the UNFILTERED book strictly (8497-8501, 8517-8525). The except latches `boot-sweep`, cleared only by the next boot (1442-1446). That refusal is unscoped, so `_submit_order` denies every order (7430-7433). The sweep runs when the ledger or a no-id context is non-empty (8477-8479). The no-id read (4668-4676) goes INCOMPLETE. |
| P5 | The gate and the permit are in safety.py | NO | The permit reads only operator controls. The gate is in trial_day_latch.py. safety.py is untouched. |
| P6 | Where the predicate lives | reports.py | symbology.py is TE-2-pinned (`TE2_PINS.json` sha 40e46379 = current digest).<br>submit_chain imports reports (`_key_tree`, `parse_fill_report`, submit_chain.py:41), so the open-order parser can use a predicate only if reports.py hosts it.<br>client.py already imports from reports (301-315).<br>reports.py is format-clean, not TE-2-pinned, and is C7 row 77.<br>`import re` is E0-INERT-clean (the rule bans network prefixes only, firewall 2652-2723). |
| P7 | Nautilus can filter this natively | NO (gap) | `filter_position_reports`, `reconciliation_instrument_ids` and `filter_unclaimed_external_orders` act after `generate_mass_status` returns ($NT/live/execution_engine.py:1710, 1734-1738).<br>Breezy sets only `LiveExecEngineConfig(inflight_check_interval_ms=0)` (node_config.py:1155) and claims weather ids only (composition.py:436-450).<br>Natively, an uncached instrument's position report is skipped (`return True  # Filtered instrument not loaded`, execution_engine.py:2475-2477, 2398-2399, 2437-2439; orders 3056-3062). The refusal is Breezy's own `_refuse`.<br>The docstring's "Excluding one was tried and is WRONG" (client.py:107-122) is about caps reading zero for a LOADED instrument. |
| P8 | Foreign slugs on this account are well formed | YES | 44 observed slugs: 37 `tc-temp-*` and 7 in aec, asc, astatc and crossd; all classify as expected. All three grammars start with `tc-temp-` (symbology.py:173; submit_chain.py:346-350; write_transport.py:68-71). |
| P9 | `manualOrderIndicator` can classify operator activity | Veto only | It is MANUAL on single-leg UI orders, UNDEFINED on the parlay order, and absent on positions. Breezy stamps AUTOMATIC (submit_chain.py:630). `manual` is False only for AUTOMATIC (reports.py:1819-1832). |
| P10 | Sweep and cancel paths never cancel foreign orders | YES | The slug cancel-all runs on ledger slugs only (8510-8511). `_require_daily_slug` refuses non-weather cancels. Only the sweep's strict parse can reach a foreign row (P4c). |
| P11 | Existing tests encode the old behaviour on non-weather inputs | YES (2) | exec_client 1336-1356: its `build_position` carries `marketMetadata.slug == key` (polymarket_us_exec_shapes.py:147-161), so the row becomes FOREIGN → CE-1. Contract 696-721 → CE-2.<br>The resolver refresh test (test_current_rung_hold_ambiguous_resolver.py:2460-2519) needs NO change: its row carries no `marketMetadata` (2489-2501). Every other non-weather literal also carries no metadata and asserts only enumeration, evidence rows or `_declared_positions`:<br>- `_open_orders_payload` (`slug-a`/`slug-b`, 4943-5036);<br>- `some-slug` (925, 986);<br>- the resolver's `a-different-market` (1216, 2447). |
| P12 | Which pins trip | 4 classes | (1) `_EXEC_CLIENT_SHA256` (test_forecast_quantile_ladder_manifest_and_markers.py:47).<br>(2) C7 rows 73 (client), 77 (reports) and 236 (trial_day_latch); rows 78 (submit_chain) and 94 (symbology) unchanged.<br>(3) aut2.label (pins.py:36; the label_run closure lists the touched modules at closure_manifest.py:22-27, 222).<br>(4) Line citations: test_entry_guard.py:191 (430) and test_us_source_ingest_egress_guard.py:62 (1965) and :77 (7752).<br>Not tripped: TE2, aut6.health (closure 255-318 has no touched module), X1, E0-INERT, X3, D4, the mention pin, REFUSAL_PRODUCERS, the resolver and order allowlists, the sweep callee set, FROZEN_SOURCE, and `test_submit_chain_is_not_byte_pinned_in_tests`. |
| P13 | AUT-2 `labeling/reconcile.py` is latent | YES | A venue-only slug becomes MISMATCH + CRITICAL (208-221). src/scripts has no caller. |
| P14 | New boot-path code can kill the node if it raises | YES | `_connect` turns any exception into fatal-fault + shutdown (2691-2699).<br>At boot, `_note_open_orders_outcome` runs in an `else:` (6919-6920) and the writer runs outside any try (6929, 6933).<br>In the refresh, it sits inside the outer try (3239-3250) and the writer in the outer `else:`.<br>`generate_position_status_reports` calls `_map_positions` outside its try when no pass is memoised (5712-5713). |
| P15 | No NO-SEND allowlist delta | YES | The resolver scan covers named coroutine bodies only (2159-2186). Its callee allowlist starts at 2188; `isinstance` and `type` are permitted, `str` is not.<br>`_note_open_orders_outcome` (2238) and the writer are allowlisted callees with unscanned bodies. No coroutine is added, and nothing references `self._order_sender`.<br>CHECKPOINT: the row comment (2233-2236) calls the body "attribute-and-log". r3 adds pure, sync, I/O-free classification (provider/cache lookups via `_find_instrument`). The guard stays unmodified. |
| P16 | Whole-tree text and type guards bind new code | YES | X3 (257, 1317-1353). D4 importer scan (test_polymarket_us_write_transport.py:49-131). The mention pin (test_operator_reserved_controls.py:758-775). The `float(` ban (test_polymarket_us_exec_endpoints.py:84-95). The `maker_poll_trade_id` writer pin (test_maker_fill_record_selector_freeze.py:176-190). The exact mypy ratchet (test_mypy_ratchet.py:364-410). |
| P17 | The test plan adds no exec importer (X1 equality) | YES | New tests go only into X1 members: exec_reports, resting_order_shape, exec_client, startup_evidence, the durable-reports contract and parsers_agree.<br>Or into the two exec-free modules, resting_sweep and the CRH gate module (zero exec import statements; they reach the client via `ambig_latch_rig.client_module`). |
| P18 | DAY is venue-documented | YES | Open-orders doc snapshot 2026-10-13 :181 and :187. The SDK row is pinned without it (snapshot drift test 167-168). test_no_id_attribution.py:205-220 already enumerates DAY open orders: an echo match is a CONTRADICTION, anything else is ignored. |
| P19 | The live maker reads the never-arm gate | NO | strategy/no_ladder_maker reads no evidence. The maker's exposure is P1 and P4c. |
| P20 | A latched refusal reaches the operator | NO (out of scope) | `breezy-trade-20261028T165019Z.log` has 547 `AlertNotDeliveredError` lines, the first at 21:30:00Z (MAKER_ORDER_DENIED).<br>`breezy-trade-20261028T234548Z.log` has 546, starting at line 416: that process's first alert, the crossd `component_degraded`. |
| P21 | The sweep and no-id read sites cannot carry the mapper message without a firewall delta | YES | The sweep's callee set is pinned EXACTLY (test_resting_path_firewall_delta.py:770-788, 812-815).<br>`_resolve_no_id_intent` is a scanned resolver coroutine (2159-2186) whose allowlist lacks `str`. |
| P22 | The evidence refresh names a sweep/no-id refusal | YES | `_connect` awaits the sweep (2683) and then the refresh (2690); the order is pinned by test_resting_path_firewall_delta.py:842-851.<br>The refresh reads the same unfiltered endpoint, and the resolver refresh repeats it every 60 s. |
| P23 | `tc-temp-` is Breezy's only weather family | YES | Discovery loads only slugs that parse as weather. It RAISES on a weather-by-question market whose slug misses the grammar (provider.py:250-262; discriminator 312-319; regex 96-98).<br>The raw corpus has 729 weather-by-question market objects, all `tc-temp-`. The 114 `temp-*` slugs are EVENT objects (`raw_weather_scan.py`). |
| P24 | `OpenOrderRecord` can take a trailing defaulted field | YES | It is a NamedTuple (reports.py:1791-1823), constructed only at 1890. No test constructs it. Tests read `._fields` only to exclude "intent"/"outcome" (exec_reports 1974-1979). |
| P25 | Observed rows self-identify | YES | Positions 1/1. Activities orders 98/98 (196 with the nested execution copies) have `marketMetadata.slug == marketSlug`.<br>The venue doc lists `marketMetadata` on Order (open-orders doc:112). Real positions carry it: the leg is read from `marketMetadata.outcome` (RULING_no_side_position_shape_2026-09-16.md:27, 41). |
| P26 | Breezy never sends DAY | YES | The only TimeInForce literals in src are IOC and GTD (submit_chain.py:334, 378; no_id_attribution.py:35-36). |
| P27 | hypothesis is available | YES | 6.165.10 in the venv; a dev dependency (pyproject.toml:35); used by 16 test modules. |
| P28 | component_health_watch.py is pinned | YES | C7 row 180; in the label_run closure (closure_manifest.py:180). |
| P29 | PROGRESS budget | YES | 76 lines / 12,093 bytes against the hook-enforced 250 lines / 12 KB (PROGRESS.md:9). The item line alone is 1,180 bytes. |
| P30 | Log assertions need TimedClient | YES | The client logger is Rust-backed and cannot be captured by caplog (test_polymarket_us_exec_client.py:3027). `TimedClient._log` wraps it in `_RecordingLog` (ambig_latch_rig.py:139-202). |

**P1 chain (client.py unless noted):**
1. Nautilus `reconcile_execution_state` calls the client ($NT/live/execution_engine.py:1710).
2. `generate_mass_status` (5458-5535) → `generate_order_status_reports` (5602-5640) → `_durable_reconciliation_pass` (5746-5840).
3. `_map_positions` (5720-5738) → `_map_position` (6160-6264).
4. `_find_instrument` (6266-6285) returns None → `_refuse` (6170-6173), which records a DURABLE refusal with `instrument=""`.
5. `_submit_order` (7430-7433) denies every order while such a refusal exists.

## Design

### S0. Glossary
Paste this into: the predicate docstring, the client helper docstring, the gate docstring, the evidence-key comment, and L-69.

> FOREIGN MARKET (operator ruling 2026-10-29) = a usable venue slug outside Breezy's weather namespace (`tc-temp-`, compared separator-blind), on a row whose `marketMetadata.slug` names that same market, for which this client loaded no instrument (for an order: not marked AUTOMATIC); it is ignored. This is NOT the older "foreign" used in this code and its tests (an unbound order or an unattributed position on a WEATHER market), which still refuses.

- The acceptance tokens keep the ruling's word: `foreign=` and `EXEC_FOREIGN_MARKET`.
- The evidence key and the pure predicate are named `non_weather_*`.

### S1. Pure helpers in exec/reports.py (RP1, RP3)
`import re` goes after `import logging` (127). The block below goes after `_MANUAL_ORDER_INDICATOR_AUTOMATIC` (1788), before `class OpenOrderRecord`.

```python
#: Breezy's ONLY market namespace on this venue (operator ruling 2026-10-29): every grammar it
#: discovers, rests, takes or cancels under begins with it (bound by T-A4 and T-A5).
WEATHER_SLUG_NAMESPACE: Final[str] = "tc-temp-"
_WEATHER_NAMESPACE_COMPACT: Final[str] = WEATHER_SLUG_NAMESPACE.replace("-", "")
#: A usable venue market slug, restated independently of the frozen symbology validator (its
#: ``$``/``match`` admits a trailing newline): ASCII, ``fullmatch``, 1-128 characters of
#: ``[a-z0-9_-]`` with a leading ``[a-z0-9]`` -- never ``.`` or ``^``. T-A6/T-A7 bind it inside
#: that validator.
_VENUE_MARKET_SLUG_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9][a-z0-9_-]{0,127}", re.ASCII)


def is_non_weather_market_slug(slug: object) -> bool:
    """<S0 glossary>. This is its NAMESPACE half; the self-identification,
    loaded-instrument and AUTOMATIC-veto halves are applied by the exec client. Total and
    fail-closed: a non-string, non-ASCII or unusable slug, and every separator-blind spelling
    of the namespace, is False. Adding a non-tc-temp market family to Breezy invalidates this
    predicate; extend the namespace first."""
    if not isinstance(slug, str) or not slug.isascii():
        return False
    if _VENUE_MARKET_SLUG_RE.fullmatch(slug) is None:
        return False
    return not slug.replace("-", "").replace("_", "").startswith(_WEATHER_NAMESPACE_COMPACT)


def metadata_slug_matches(payload: object, slug: str) -> bool:
    """True only when ``payload`` is an object whose ``marketMetadata`` is an object whose
    ``slug`` is exactly ``slug`` -- the row names its own market. Total, never raises. This
    module's rule that two venue identifiers which disagree are a contradiction
    (:func:`parse_position_status_report`), read as a FACT, never a refusal: an absent, null,
    empty or non-string ``slug`` is no match, so a row that does not name itself is never a
    FOREIGN MARKET (EXEC-FOREIGN-POS)."""
    if not isinstance(payload, Mapping):
        return False
    metadata = payload.get("marketMetadata")
    if not isinstance(metadata, Mapping):
        return False
    named = metadata.get("slug")
    return isinstance(named, str) and named == slug
```

**Each of these is NOT non-weather, so it keeps today's refusal:**
- a non-string or non-ASCII value;
- an unusable slug: empty, containing `.` or `^`, uppercase, longer than 128 characters, a trailing newline, or a leading `-` or `_`;
- any separator-blind spelling of the namespace: `tc_temp_…`, `tc-temps-…`, `tc-temperature-…`, `tctemp…`.

**Why the predicate is stricter than the strict mapper.** The foreign path requires a self-naming block, while the mapper accepts an absent block. A lenient rule would let a venue keying drift plus a dropped block turn Breezy's own weather position into an ignored row (D-10).

**Why nothing existing serves:**
- `parse_weather_slug(s) is None` would make an unparseable `tc-temp-*` slug foreign, which breaks the carve-out.
- `slug_to_instrument_id` accepts every usable slug.
- `is_daily_high_slug` is HIGH-only.
- `_require_daily_slug` sits inside the NO-SEND firewall.
- symbology.py is TE-2-pinned, and submit_chain cannot be imported by the parser (P6).
- An allowlist or config knob is forbidden by the ruling.
- The manual indicator cannot classify (P9).

### S2. DAY for enumeration, self-identifying non-weather rows only (RP2, RP4, RP5, RP6)

**RP2, after `_TIME_IN_FORCE` (488):**
```python
#: EXEC-FOREIGN-POS (``docs/evidence/venue/polymarket_us/OPEN_ORDER_TIF_DRIFT_2026-10-29.md``):
#: the venue's open-orders doc declares ``TIME_IN_FORCE_DAY``; the pinned SDK snapshot does not.
#: The first VALUE-level sibling of the key-level DECLARED-BUT-UNREAD sets above: accepted by
#: membership ONLY in :func:`parse_open_orders`, ONLY on a row that names its own non-weather
#: market, never mapped to a native enum. ``_TIME_IN_FORCE`` stays the SDK row, so
#: :func:`parse_order_status_report` still refuses DAY, and a DAY row on a weather, unusable or
#: non-self-identifying market still refuses the whole enumeration.
_OPEN_ORDER_TIF_DRIFT_ALLOWED: Final[frozenset[str]] = frozenset({"TIME_IN_FORCE_DAY"})
```

**RP4, a trailing `OpenOrderRecord` field after `manual` (1823):**
```python
    #: True only when ``marketMetadata.slug`` is exactly ``market_slug``
    #: (:func:`metadata_slug_matches`). Never a refusal by itself; the exec client's
    #: FOREIGN-MARKET flag and the DAY admission both require it. Default ``False``: a
    #: record not built by :func:`parse_open_orders` never names itself.
    names_own_market: bool = False
```

**RP5, in `_open_order_record`.** Replace 1861-1863 and add the field at 1890-1902. The first message text is unchanged.
```python
    tif = _require_text(payload, "tif", context=context)
    names_itself = metadata_slug_matches(payload, market_slug)
    if tif not in _TIME_IN_FORCE:
        if tif not in _OPEN_ORDER_TIF_DRIFT_ALLOWED:
            raise ExecutionReportMappingError(f"{context}.tif {tif!r} is not a declared TimeInForce")
        if not (names_itself and is_non_weather_market_slug(market_slug)):
            raise ExecutionReportMappingError(
                f"{context}.tif {tif!r} is enumerated only on a non-weather market whose "
                "marketMetadata.slug names it (EXEC-FOREIGN-POS)"
            )
    ...
    return OpenOrderRecord(..., manual=_manual_indicator_flag(payload), names_own_market=names_itself)
```

**RP6.** `parse_open_orders`' docstring gains one sentence naming the DAY scope.

**Consumers.** Every enumeration consumer now sees a FOREIGN-MARKET DAY order exactly as it already sees a GTC one:
- **CRH gate:** exempt only if the order is flagged.
- **Resolver refresh:** records it.
- **No-id resolver:** an in-window open order matching the echo slug and price is a CONTRADICTION (test_no_id_attribution.py:205-220). A non-weather order never matches a weather echo slug, so it is ignored unless its tif is IOC (no_id_attribution.py:303-345).
- **Boot sweep:** it is never on a ledger slug, so it is listed and left alone.

Every weather, unusable or non-self-identifying DAY row is unchanged: it refuses the whole read.

### S3. Exec-client classification rule (K15, after `_find_instrument`, 6285)
```python
    def _is_foreign_market(self, kind: str, slug: object) -> bool:
        """<S0 glossary> -- the namespace and loaded-instrument halves; the caller has
        already required the row to name itself (and, for an order, not AUTOMATIC).
        Never raises: any error is "not foreign", so the pre-ruling refusal applies."""
        try:
            # ORDER IS LOAD-BEARING: the namespace predicate runs first. It admits only slugs
            # the symbology validator accepts (T-A6, T-A7), so `_find_instrument` -- which
            # latches the global `_find_instrument#1` refusal on an unusable slug -- is never
            # reached with one, and classification can never latch (T-D5).
            return (
                isinstance(slug, str)
                and is_non_weather_market_slug(slug)
                and self._find_instrument(slug) is None
            )
        except Exception as exc:  # noqa: BLE001 - never foreign-by-exception
            self._warn_foreign_once(kind, "classification", exc)
            return False

    def _warn_foreign_once(self, kind: str, stage: str, exc: Exception) -> None:
        """One WARNING per (stage, kind, exception class) per process; class name only."""
        key = (stage, kind, type(exc).__name__)
        if key in self._foreign_log_keys:
            return
        self._foreign_log_keys = self._foreign_log_keys | {key}
        consequence = (
            "treated as not foreign, so the refusal that applies without the ruling stands"
            if stage == "classification"
            else "the market is still ignored; only its INFO line was lost"
        )
        self._log.warning(
            f"EXEC_FOREIGN_MARKET {stage} failed kind={kind} ({key[2]}); {consequence}"
        )
```
- An instrument this client loaded is never foreign.
- The lookup is the YES-leg lookup, the same first lookup `_map_position` makes. Discovery builds both legs together.
- The client imports `is_non_weather_market_slug` and `metadata_slug_matches` from `exec.reports` (K2).

### S4. Positions: classify at the `_map_positions` loop head (K13; `_map_position` stays byte-identical)
```python
        for slug in sorted(positions):
            payload = positions[slug]
            if metadata_slug_matches(payload, slug) and self._is_foreign_market(
                _FOREIGN_KIND_POSITION, slug
            ):
                self._note_foreign_market(_FOREIGN_KIND_POSITION, slug, payload.get("netPosition"))
                outcomes.append(_MAP_FOREIGN)
                continue
            self._position_map_outcome = _MAP_UNPARSEABLE
            report = self._map_position(slug, payload)
            ...unchanged...
```
- A row that does not name itself never reaches `_is_foreign_market`, so it takes exactly today's path: `_find_instrument` → `_map_position#1`.
- A FOREIGN row gets no mapping, no strict parse and no `PositionStatusReport`:
  - nothing reaches Nautilus, so it is never netted;
  - the exit seam never sees it, so it is never sold;
  - no `_refuse` call is added, so REFUSAL_PRODUCERS is unchanged.
- `_MAP_FOREIGN` is not `_MAP_UNPARSEABLE`, so `positions_read_failed` is not latched.
- Classification precedes the expired branch, so sign, size and settlement are irrelevant, and `settled_positions` never gains the row.
- The row stays in every evidence row (6729-6737) and in `held_position_slugs`, so it is never hidden (T-B1).

### S5. Open orders

**S5a. Classify once, in `_note_open_orders_outcome` (K18, 6959-6994).**
```python
        if error is not None or records is None:
            self._open_orders_read_refused = True
            self._open_orders = ()
            self._non_weather_open_orders = frozenset()
            self._log.warning(
                "startup evidence: open-orders read failed "
                f"({_open_orders_failure_detail(error)}); "
                "recording open_orders_read_refused=True"
            )
            return
        self._open_orders_read_refused = False
        self._open_orders = records
        self._non_weather_open_orders = frozenset(
            (r.venue_order_id, r.market_slug)
            for r in records
            if r.manual is not False  # AUTOMATIC veto: an API-placed order is never the operator's
            and r.names_own_market
            and self._is_foreign_market(_FOREIGN_KIND_OPEN_ORDER, r.market_slug)
        )
        counted = [
            r for r in records if (r.venue_order_id, r.market_slug) not in self._non_weather_open_orders
        ]
        for r in records:
            if (r.venue_order_id, r.market_slug) in self._non_weather_open_orders:
                self._note_foreign_market(_FOREIGN_KIND_OPEN_ORDER, r.market_slug, r.quantity)
        ...the drift WARNING is unchanged (all rows)...
        if counted:  # the startup_open_orders_present ERROR counts and redacts only these
            ...
```
- `self._open_orders` still holds every record, so the evidence never hides a FOREIGN order.
- The set is replaced together with the book, never one without the other.

**S5b. Evidence flag (producer; K4, K8-K11, K17).**
- Constant: `STARTUP_OPEN_ORDER_NON_WEATHER_KEY: Final[str] = "non_weather_market"`, after 497, with the S0 comment; added to `__all__`.
- `StartupOpenOrderSnapshot` gains `non_weather_market: bool = False`.
- The writer (6746-6754) sets `non_weather_market=(o.venue_order_id, o.market_slug) in self._non_weather_open_orders`.
- `to_bytes` writes the key ONLY when it is True, so existing goldens and rows stay byte-identical.
- `from_bytes` decodes it with `is True`.
- Tests that set `client._open_orders` directly leave the set empty, so no flag is written (fail-closed).

**S5c. Gate (consumer; trial_day_latch 1545-1550; TL1-TL4).**
```python
    if any(
        not (isinstance(o, dict) and (o.get("own_resting") is True
             or o.get(STARTUP_OPEN_ORDER_NON_WEATHER_KEY) is True))
        for o in open_orders
    ):
        return STARTUP_OPEN_ORDERS_PRESENT_REASON
```
- The latch rule after it (1551-1559) is unchanged:
  - with a FOREIGN-only book, a present non-False `resting_cancel_unconfirmed` still refuses;
  - an absent key still refuses (T-E4);
  - the producer writes `False` whenever any order is open (6699-6709).
- The key is imported in the existing exec.client import (68-75), so no new edge.
- **Portability:** this is as portable as the existing evidence keys (`own_resting`, `resting_cancel_unconfirmed`), which are also defined in the PM.us client module. A second venue needs its own evidence namespace, predicate and gate wiring, as today.

### S6. Reconciliation counts (K6, K7, K14)
- `_MAP_FOREIGN: Final[str] = "foreign"` sits beside `_MAP_INSTRUMENT_ABSENT` (554-560; "first three" becomes "first four").
- `_RECONCILIATION_COUNT_FIELDS` (587-598) gains `"foreign"` right after `"instrument_absent"`.
- After 5796: `counts["foreign"] = outcomes.count(_MAP_FOREIGN)`, with the comment "never latched, never a refusal".
- The `_durable_reconciliation_pass` docstring (5768-5770) says a FOREIGN-MARKET position is counted as `foreign`, never `instrument_absent`.
- `instrument_absent` (5796 and 5859) now counts:
  - a weather-namespace, unusable or non-self-identifying position with no loaded instrument;
  - a NO-leg holding without a NO-leg instrument (6198-6206);
  - a provider-held instrument missing from the Nautilus cache (5856-5864).
- Expected line: `durable reconciliation: order_reports=0 fill_reports=0 records_considered=0 gated_out=0 instrument_absent=0 foreign=1 refusals=0 refusals_positions_read_failed=0 refusals_record_venue_disagreement=0 refusals_fee_coefficient_ambiguous=0 refusals_durable_reports_build_failed=0`

### S7. Log lines (K5, K15)
Module-level helpers go after `_loggable_slug` (520-525). A comment goes ABOVE `_loggable_slug`:

```python
#: `_note_foreign_market` logs a FOREIGN-MARKET slug VERBATIM (``!r``) on purpose: only a slug
#: `is_non_weather_market_slug` admits reaches it (ASCII ``[a-z0-9_-]``, at most 128 chars), so
#: it cannot inject; routing it through `_loggable_slug` would blank the acceptance line.
...
_FOREIGN_KIND_POSITION: Final[str] = "position"
_FOREIGN_KIND_OPEN_ORDER: Final[str] = "open_order"
_QUANTITY_LOG_MAX_CHARS: Final[int] = 32
#: L-37: the open-orders mapper names the refused field in its message; bounded because it
#: may quote an unbounded venue string.
_MAPPER_DETAIL_MAX_CHARS: Final[int] = 200


def _loggable_quantity(value: object) -> str:   # total, never raises
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        return "<invalid-qty>"
    try:
        text = str(value)
    except ValueError:  # an int past the interpreter's str-conversion digit limit
        return "<invalid-qty>"
    if len(text) > _QUANTITY_LOG_MAX_CHARS or not (text.isascii() and text.isprintable()):
        return "<invalid-qty>"
    return text


def _open_orders_failure_detail(error: BaseException | None) -> str:
    """The class name, plus -- for an ``ExecutionReportMappingError`` only -- the mapper's own
    message, bounded (the 97d3fd9e resting-poll rule, client.py:9195-9203: the mapper names
    keys and fields; any other exception may carry a raw wire value, so it is never echoed)."""
    if error is None:
        return "no result"
    name = type(error).__name__
    if not isinstance(error, ExecutionReportMappingError):
        return name
    text = str(error)
    if len(text) > _MAPPER_DETAIL_MAX_CHARS:
        text = f"{text[:_MAPPER_DETAIL_MAX_CHARS]}… (truncated)"
    return f"{name}: {text}"
```

```python
    def _note_foreign_market(self, kind: str, slug: str, quantity: object) -> None:
        """ONE INFO line per (kind, slug) per process (operator ruling 2026-10-29)."""
        try:
            key = ("info", kind, slug)
            if key in self._foreign_log_keys:
                return
            self._foreign_log_keys = self._foreign_log_keys | {key}
            self._log.info(
                f"EXEC_FOREIGN_MARKET kind={kind} slug={slug!r} qty={_loggable_quantity(quantity)!r}: "
                "outside the weather slug namespace and not loaded, so not Breezy's; ignored -- never "
                "netted, sold, cancelled or allowlisted (operator ruling 2026-10-29)"
            )
        except Exception as exc:  # noqa: BLE001 - a log line must never fail a boot
            self._warn_foreign_once(kind, "note", exc)
```

**New state, initialised after 2302 (K12).** Both fields are reassigned, never mutated, and touched only on the event loop:
- `self._non_weather_open_orders: frozenset[tuple[str, str]] = frozenset()`;
- `self._foreign_log_keys: frozenset[tuple[str, str, str]] = frozenset()`.

**Scope:**
- Positions are classified and logged at the boot reconciliation only (`generate_mass_status` is boot-only, 2314-2321).
- Open orders are classified at every enumeration (boot and the 60 s refresh), but logged once per slug.
- Two orders on one slug produce one line, carrying the first order's quantity.

### S8. Fail-closed rules
1. A weather-namespace slug with no loaded instrument, parseable or not and in any separator spelling, still refuses via the unchanged `_map_position#1` (T-B3, T-B4).
2. An unusable slug in any namespace:
   - positions: the unchanged `_find_instrument#1` + `_map_position#1`;
   - orders: never flagged, so the gate refuses; a DAY one refuses the read (T-A3, T-D5, T-R4, R13).
3. A slug with a loaded instrument is mapped as today (T-B5).
4. A row that does not name itself is not FOREIGN. That covers: a non-object row, non-object metadata, and a slug that is absent, null, empty, non-string or different.
   - Positions refuse (T-B6).
   - Orders are never flagged (T-D7).
   - A DAY order refuses the read (T-R4, T-D7, R18).
5. A classification exception means "not foreign" (T-B7, T-D4, T-G4).
6. An order the venue marks AUTOMATIC is never flagged (T-D6).
7. The flag is honoured only when it is exactly `True` (T-E2).
8. Manual WEATHER activity still stops the bot:
   - positions via the exec client;
   - open orders via the CRH gate, and a ledger-slug one is cancelled at boot (spec 9.18);
   - a DAY weather order still refuses the whole enumeration (R2).
9. Breezy never sends DAY (P26), so admitting DAY on a FOREIGN row can never hide a Breezy order.

### S9. Non-raising boot path
- Total by construction, and each pinned by tests:
  - `is_non_weather_market_slug` (T-A3);
  - `metadata_slug_matches` (T-R5);
  - `_loggable_quantity` (T-B9);
  - `_open_orders_failure_detail` (T-G6).
- `_is_foreign_market` and `_note_foreign_market` catch `Exception` and log one deduplicated, class-only WARNING (T-B7, T-G4, T-G5).
- The writer only tests frozenset membership.
- No new code runs inside a scanned coroutine.
- Residual: the logger itself is unguarded here, exactly as on every existing boot-path log call.

### S10. Deliberately unchanged
- `_submit_order`, `_refuse`, `_map_position`, `_find_instrument`, `_declared_positions` and `generate_mass_status`.
- The resolver coroutines, including the class-only WARN at 4674.
- `_sweep_resting_orders_at_boot`, including its class-only latch cause at 8523.
- `parse_order_status_report`, `parse_position_status_report`, every key pin, `_TIME_IN_FORCE`.
- `symbology.py`, `submit_chain.py`, `write_transport.py`, `safety.py`.
- `held_position_slugs`, the breaker watcher, and the positions evidence rows.
- `no_id_attribution.py`, `labeling/reconcile.py`, `set_family_halt_cli`, `component_health_watch.py`.

## Files

| File | Change | Commit |
|---|---|---|
| src/breezy/adapters/polymarket_us/exec/reports.py | RP1-RP6 (S1, S2) | A |
| src/breezy/adapters/polymarket_us/exec/client.py | K1-K18 (GREEN) | A |
| src/breezy/strategy/current_rung_hold/trial_day_latch.py | TL1-TL4 (S5c) | A |
| docs/evidence/venue/polymarket_us/OPEN_ORDER_TIF_DRIFT_2026-10-29.md (new) | Value-free note: names, counts and doc citations only, no values | A |
| tests/unit/polymarket_us_exec_shapes.py | Test constants and 3 builders (no new import) | A |
| 8 test modules (RED tests) | T-A, T-R, T-B, T-C, T-D, T-E, T-G, T-H; CE-1, CE-2 | A |
| tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py; tests/unit/data/maker_stage0_c7_closure_pins.json; src/breezy/persistence/autonomy/pins.py; tests/unit/test_entry_guard.py; tests/contract/test_us_source_ingest_egress_guard.py | Pin classes 1-4 (CE-3) | B |
| docs/evidence/P4_LIVE_READ_2026-10-29.md (new); docs/core/PROGRESS.md; docs/core/LESSONS.md (L-69 via the lessons skill) | Acceptance read, residual table, follow-ups | C |

**Not touched:**
- `exec/submit_chain.py`;
- `test_current_rung_hold_ambiguous_resolver.py` (r2's E-2 is dropped);
- `component_health_watch.py` (D-7).

## RED tests

**Tags:**
- [CHANGE] fails before the delta.
- [CHAR] passes before the delta and needs MUTATION_RED_EVIDENCE (L-33): apply the named mutation to the GREEN tree, show red, restore.

[CHAR] tests assert only observables that exist at base:
- `trading_refusals` and `counts["instrument_absent"]`;
- `counts.get("foreign", 0)`;
- decoded evidence rows' `.get("non_weather_market") is not True`;
- the gate reason.

**Constants** (module-level in polymarket_us_exec_shapes.py, so DRY across modules):
- `CROSSD="crossd-ba05d7244fbd670a"`
- `ASTATC="astatc-nba-gs-min-2026-10-28-ast-ayodos-gte10"`
- `AEC="aec-nfl-lar-den-2026-09-27"`
- `UNLOADED="tc-temp-laxhigh-2026-08-24-gte80lt81f"`
- `UNPARSEABLE_W="tc-temp-lax-2026-08-25-gte70lt71f"`
- `FRGN="FRGN00000001"`

**Fixtures (shapes helper, test-only):**
- `build_combo_position(slug)`:
  - the 10-28 parlay row's full key tree: 22 top-level keys; `marketMetadata` with 6 keys and `slug` = key; two `comboLegDetails` legs of 17 keys each, including the `team` object;
  - JSON types verbatim, every value a same-typed synthetic value, `positionId` a dummy UUID;
  - `netPosition` "963", `expired` False.
- `build_manual_day_open_order(slug, order_id, **overrides)`:
  - the 27-key `WIRE_ORDER_KEYS` set;
  - `marketMetadata` in the observed 7-key single-leg shape (`eventId`, `eventSlug`, `icon`, `outcome`, `slug`=marketSlug, `subject`, `title`);
  - tif DAY, MANUAL indicator, state NEW, `quantity` 3.69 (a float, as observed), `cumQuantity` 0, `price` {USD, "0.625"};
  - overrides for tif, indicator and metadata;
  - synthetic values.
- `build_non_weather_instrument(slug)`: the 510636 capture with `slug` and `category="sports"` replaced. Its facts are UNKNOWN (parsing.py:1316-1325).

**Minimum set, mapped:**
- Foreign position does not latch: T-B1, T-B2, T-C1, T-G2, T-G5.
- Weather position without an instrument still refuses: T-B3, T-B4, T-C2, CE-1, plus the unchanged unusable-slug test (1359-1380).
- Foreign open order does not trip never-arm: T-D1, T-D8, T-E1, T-G1, T-G3, T-H1. The operator's real DAY shape is covered by T-R1, T-D1, T-G1 and T-G3.
- Weather open order still trips it: T-D2, T-E3, T-R4, plus the unchanged CRH `test_a_foreign_slug_open_order_also_refuses` (86-94) and the unchanged resolver refresh test (2460-2519).
- `instrument_absent` counts weather only and `foreign=N` is reported: T-B1, T-B3, T-C1, T-C2, T-G2, CE-2.
- Locks on Breezy's own exposure: T-A4, T-A5, T-A7, T-B5, T-B6, T-D5, T-D6, T-D7, T-R2, T-R4.
- Never hidden: T-B1 (evidence row and held slugs), T-D1 (flag in bytes), T-G3 (row still listed).
- Diagnosable refusal (L-37): T-G6.
- Clearing path (L-48): T-B8.
- Containment: T-B7, T-B9, T-D4, T-D9, T-G4, T-G5.

**T-A. tests/unit/test_polymarket_us_resting_order_shape.py** (X1 member, format-clean; after the `is_daily_high_slug` tests at 160-189; predicate imported from reports)
- **T-A1** [CHANGE] `test_is_non_weather_market_slug_is_true_for_the_accounts_observed_non_weather_slugs`: CROSSD, ASTATC, AEC, `asc-cfb-minnst-wash-2026-09-26-neg-1pt5`, `"a"*128` → True.
- **T-A2** [CHANGE] `test_is_non_weather_market_slug_is_false_for_every_weather_namespace_spelling` → False for:
  - a parseable HIGH slug and a parseable LOW slug;
  - an invalid date, and `…-banana`;
  - UNPARSEABLE_W;
  - `tc-temp`, `tc_temp_nychigh-2026-08-25-lt79f`, `tc-temps-x`, `tc-temperature-nyc`, `tctemp-x`, `tc--temp-x`;
  - a weather slug with a trailing newline.
- **T-A3** [CHANGE] `test_is_non_weather_market_slug_is_false_for_an_unusable_or_non_string_slug` → False, never raising, for:
  - `""`, `bad.slug`, `crossd-x^no`, `CROSSD-AB`;
  - `TC-TEMP-NYCHIGH-2026-08-25-LT79F`, `"a"*129`, `"crossd-x\n"`;
  - a fullwidth digit, `-crossd`, `_x`;
  - None, 7, `b"crossd-x"`, `["x"]`.
- **T-A4** [CHANGE] `test_every_send_and_parse_grammar_begins_with_the_weather_namespace`: `submit_chain._DAILY_HIGH_SLUG_RE.pattern`, `write_transport._DAILY_SLUG_RE.pattern` (function-level import) and `symbology._WEATHER_SLUG_RE.pattern` (with `^` removed) all start with `WEATHER_SLUG_NAMESPACE`.
- **T-A5** [CHANGE] `test_no_market_the_discovery_weather_discriminator_selects_is_non_weather`:
  - Walk `docs/evidence/venue/polymarket_us/raw/*.json` (27 files) and select every object whose `provider._weather_city_name_from_payload(obj)` is not None.
  - Assert more than 100 are selected (precedent symbology test 214-217; 729 today), and none is non-weather.
  - Docstring: the namespace claim rests on this test, on T-A4, and on discovery raising for an off-grammar weather market (provider.py:250-262).
- **T-A6** [CHANGE] `test_every_observed_non_weather_slug_passes_the_symbology_validator`: `symbology.slug_to_instrument_id(s)` succeeds for every T-A1 vector.
- **T-A7** [CHANGE] `test_a_non_weather_slug_always_passes_the_symbology_validator`:
  - hypothesis, `@settings(max_examples=500, deadline=None)`;
  - strategies: `st.text` over lowercase, digits, `-_.^`, space, newline, uppercase, a fullwidth digit and NUL (max 140), plus `st.from_regex(r"[a-z0-9][a-z0-9_-]{0,135}", fullmatch=True)`;
  - property: predicate True ⇒ `symbology.assert_valid_slug(s)` does not raise.

**T-R. tests/unit/test_polymarket_us_exec_reports.py** (X1 member)
- **T-R1** [CHANGE] `test_parse_open_orders_enumerates_a_manual_day_order_on_a_self_identifying_non_weather_market`: `build_manual_day_open_order(AEC, FRGN)` → one record with tif DAY, `manual is True`, `names_own_market is True`, `unknown_keys == ()`.
- **T-R2** [CHAR] `test_parse_order_status_report_still_refuses_a_day_tif`. Mutation: add DAY to `_TIME_IN_FORCE`.
- **T-R3** [CHANGE] `test_the_open_order_tif_drift_set_is_exactly_day_outside_the_sdk_row_and_venue_documented`: the set equals {DAY}, is disjoint from `set(_TIME_IN_FORCE)`, and `- TIME_IN_FORCE_DAY` appears in the open-orders doc snapshot.
- **T-R4** [CHAR] `test_a_day_order_still_refuses_the_whole_read_unless_it_names_its_own_non_weather_market`:
  - Parametrize: a self-identifying HIGH weather slug; UNPARSEABLE_W; `bad.slug`; AEC with metadata slug = UNLOADED; AEC with no metadata; AEC with `{"slug": None}`.
  - Each raises `ExecutionReportMappingError` matching `.tif`.
  - Mutations: (a) drop the namespace clause (weather and `bad.slug` cases go red); (b) drop the identity clause (the three AEC cases go red).
- **T-R5** [CHANGE] `test_metadata_slug_matches_is_total_and_exact_and_the_record_defaults_to_false`:
  - True for a self-naming row.
  - False, never raising, for non-Mapping payloads (`"x"`, None, `["x"]`); for metadata absent, None, a list, a str or `{}`; for slug None, `""`, 7 or another slug.
  - `OpenOrderRecord._field_defaults["names_own_market"] is False`, and a parsed GTC row without metadata carries False.

**T-B. tests/unit/test_polymarket_us_exec_client.py** (X1 member; call `client.start()` before asserting degradation)
- **T-B1** [CHANGE] `test_a_foreign_market_position_does_not_refuse_latch_or_degrade_and_stays_recorded`.
  - Arrange: positions {CROSSD: combo}; `start()`; `_connect()`.
  - Act: `generate_mass_status()`.
  - Assert:
    - `trading_refusals == ()`; not degraded;
    - `position_reports == {}`; `settled_positions == ()`;
    - counts foreign 1, instrument_absent 0, refusals 0;
    - `read_startup_position_evidence().positions` contains CROSSD with net "963";
    - `held_position_slugs` contains CROSSD.
  - Mutation for the last two (sub-[CHAR]): the writer skips non-weather slugs.
- **T-B2** [CHANGE] `test_a_foreign_position_is_ignored_whatever_its_sign_size_or_settlement`: parametrize netPosition "963"/"-5"/"0" × expired False/True; asserts as T-B1.
- **T-B3** [CHANGE] `test_a_weather_position_without_a_loaded_instrument_still_refuses_beside_a_foreign_one`.
  - Arrange: positions {UNLOADED, CROSSD}.
  - Assert: exactly one refusal; it names UNLOADED with "for which no instrument is loaded"; instrument_absent 1, foreign 1.
- **T-B4** [CHAR] `test_an_unparseable_or_near_miss_weather_position_still_refuses`.
  - Parametrize UNPARSEABLE_W and `tc_temp_nychigh-2026-08-25-lt79f`; each refuses, with `counts.get("foreign", 0) == 0`.
  - Mutations: replace the namespace test with `parse_weather_slug(s) is None` (case 1 goes red); drop the separator-blind compaction (case 2 goes red).
- **T-B5** [CHAR] `test_a_non_weather_market_with_a_loaded_instrument_is_mapped_never_ignored`.
  - Arrange: `build_non_weather_instrument(AEC)` in the provider and the cache; positions {AEC: `_position(AEC)`}.
  - Assert: the report is forwarded and a "no durable fill record" refusal names it, as in 1116-1146; foreign 0 via `.get`.
  - Mutation: delete `and self._find_instrument(slug) is None`.
- **T-B6** [CHAR] `test_a_non_weather_row_that_does_not_name_itself_still_refuses`.
  - CROSSD with: (a) metadata slug = UNLOADED; (b) metadata `["x"]`; (c) row `"x"`; (d) no metadata; (e) `{}`; (f) `{"slug": None}`; (g) `{"slug": ""}`; (h) `{"slug": 7}`.
  - Each: a refusal names CROSSD with "for which no instrument is loaded"; `counts.get("foreign", 0) == 0`; instrument_absent 1.
  - Mutations: `metadata_slug_matches` returns True (all go red); a lenient rule accepting absent/None/"" (cases d-g go red); drop the metadata isinstance check (case b goes red).
- **T-B7** [CHANGE] `test_a_classification_error_refuses_never_ignores`: monkeypatch `client_module.is_non_weather_market_slug` to raise. Assert: CROSSD refuses; foreign 0; instrument_absent 1.
- **T-B8** [CHAR] `test_the_retained_weather_refusal_clears_on_the_next_boot_once_the_position_is_gone`.
  - Two boots over one store, following the 4469-4478 pattern.
  - Boot 1, with the UNLOADED position listed: refuses.
  - Boot 2, with positions empty: `trading_refusals == ()`.
  - Perturbation: keep the position listed in boot 2 (goes red).
- **T-B9** [CHANGE] `test_the_foreign_note_is_value_safe_and_bounded`.
  - First asserts that `_note_foreign_market`, `_loggable_quantity` and `_open_orders_failure_detail` exist.
  - AST over `_note_foreign_market`:
    - exactly one `self._log.info`;
    - `slug` and the `_loggable_quantity(...)` value both use `!r`;
    - no `$`;
    - no operator-control env-var name constant (the 3025-3049 technique).
  - `_loggable_quantity` vectors:
    - "963" → "963"; `Decimal("963.04")` → "963.04";
    - each of these → `<invalid-qty>`: "9"*33, a 1 MB string, `{"a": 1}`, True, None, "96\n3", 10**5000.
  - `_FOREIGN_KIND_POSITION == "position"` and `_FOREIGN_KIND_OPEN_ORDER == "open_order"`.

**T-C. tests/contract/test_reconciliation_durable_reports_contract.py** (real LiveExecutionEngine)
- **T-C1** [CHANGE] `test_a_foreign_market_position_is_counted_foreign_never_instrument_absent_and_never_refused`.
  - Arrange: `_Rig(cached=(yes,))`; a weather record and hold; positions[CROSSD] = combo.
  - Act: `await rig.reconcile()`, which returns True.
  - Assert: foreign 1, instrument_absent 0, refusals 0; no reconciliation or trading refusals; no position for CROSSD's id; the weather order report is still built.
- **T-C2** [CHANGE] `test_a_weather_instrument_absent_from_the_cache_still_counts_beside_a_foreign_position`: the F8 shape (397-416) plus CROSSD. Assert: instrument_absent 1, foreign 1, gated_out 0.

**T-D. tests/unit/test_polymarket_us_startup_evidence.py** (X1 member; `_build_rig`; no log capture, P30)
- **T-D1** [CHANGE] `test_a_manual_day_order_on_a_non_weather_market_is_flagged_and_does_not_refuse_the_gate`.
  - Arrange: `build_manual_day_open_order(AEC, FRGN)`. Act: `_connect()`.
  - Assert: the read is not refused; the row is flagged in both the dataclass and the bytes; the decoded gate reason is None; `trading_refusals == ()`.
- **T-D2** [CHAR] `test_a_weather_namespace_open_order_is_never_flagged_even_when_it_does_not_parse`: a self-identifying MANUAL GTC UNPARSEABLE_W order is unflagged (decoded `.get`) and the reason is `STARTUP_OPEN_ORDERS_PRESENT_REASON`. Mutation: as T-B4 (a).
- **T-D3** [CHANGE] `test_startup_evidence_round_trips_the_non_weather_flag_and_omits_it_when_false`: a True row and a False row round-trip; only the True row carries the key; also pins `STARTUP_OPEN_ORDER_NON_WEATHER_KEY == "non_weather_market"`.
- **T-D4** [CHANGE] `test_an_open_order_classification_error_keeps_the_gate_refusing`: with `client_module.is_non_weather_market_slug` raising, the read succeeds (the parser's own binding is untouched), the AEC DAY order is unflagged, the reason is `STARTUP_OPEN_ORDERS_PRESENT_REASON`, and `trading_refusals == ()`.
- **T-D5** [CHAR] `test_an_unusable_open_order_slug_never_latches_trading_and_is_never_flagged`.
  - Parametrize `bad.slug`, `CROSSD-AB`, `crossd-x^no`: self-identifying MANUAL GTC rows.
  - Assert: `trading_refusals == ()`; unflagged; the gate refuses.
  - Mutation: move `self._find_instrument(slug) is None` ahead of the grammar test, so `_find_instrument#1` latches.
- **T-D6** [CHAR] `test_an_automatic_order_on_a_non_weather_market_is_never_flagged`: a self-identifying AUTOMATIC GTC order on AEC is unflagged and the gate refuses. Mutation: drop `manual is not False`.
- **T-D7** [CHAR] `test_an_open_order_that_does_not_name_its_own_market_is_never_flagged_and_a_day_one_still_refuses_the_read`.
  - (i) MANUAL GTC on AEC with metadata slug = UNLOADED; (ii) the same with no metadata: both parse, are unflagged, and the gate refuses; `trading_refusals == ()`.
  - (iii) MANUAL DAY with the (i) metadata; (iv) MANUAL DAY with no metadata: both refuse the read (`open_orders_read_refused`).
  - Mutations: drop the identity clause from the flag ((i)/(ii) go red); drop it from the DAY admission ((iii)/(iv) go red).
- **T-D8** [CHANGE] `test_a_non_weather_order_with_an_undefined_or_absent_indicator_is_flagged`: parametrize (DAY, UNDEFINED), (GTC, UNDEFINED) and (DAY, key absent). Each is flagged and the reason is None. This kills the mutant `manual is True`.
- **T-D9** [CHANGE] `test_a_read_failure_after_a_flagged_read_drops_the_flag_with_the_book`.
  - `_connect()` with the AEC DAY order (flagged).
  - Then `rig.read.raises[OPEN_ORDERS_PATH] = RuntimeError("x")`, and `await client._refresh_startup_position_evidence()`.
  - Assert: evidence `open_orders_read_refused is True`; `open_orders == ()`; no decoded row carries the flag; `client._non_weather_open_orders == frozenset()`.

**T-E. tests/unit/test_continuous_rung_hold_open_orders_gate_2026_09_16.py** (strategy; NO exec import; the wire key is written as the literal `"non_weather_market"`, pinned by T-D3)
- **T-E1** [CHANGE] `test_a_non_weather_market_open_order_does_not_refuse_to_arm`: a flagged dict with `resting_cancel_unconfirmed=False`. Assert: reason None; `startup_evidence_missing == 0`; `_latch is not None`; `_run_never_arm_walk() is True`.
- **T-E2** [CHAR] `test_a_non_weather_flag_that_is_not_exactly_true_still_refuses`: parametrize "true", 1, "yes", None and absent; each refuses. Mutation: replace `is True` with a truthiness check.
- **T-E3** [CHAR] `test_a_non_weather_order_does_not_mask_a_weather_order`: a flagged CROSSD row plus an unflagged weather row refuses. Mutation: check only the first row.
- **T-E4** [CHANGE] `test_a_non_weather_only_book_still_honours_the_resting_cancel_latch`: a flagged-only book returns `resting_cancel_unconfirmed` both when the latch is True and when the key is absent.

**T-G. tests/unit/test_polymarket_us_resting_sweep.py** (TimedClient via ambig_latch_rig; existing `gate_env`; NO exec import; `client_module`, `OPEN_ORDERS_PATH` and `PORTFOLIO_POSITIONS_PATH` come from ambig_latch_rig)
- **T-G1** [CHANGE] `test_a_manual_day_order_logs_info_once_and_leaves_only_own_orders_in_the_error`.
  - Arrange: `_submit_rest(rig, 0)`; book = [`_open_row(command, 0)`, `build_manual_day_open_order(AEC, FRGN)`].
  - Act: `_refresh_startup_position_evidence()` twice.
  - Assert:
    - exactly one `log_lines("info", "EXEC_FOREIGN_MARKET kind=open_order")`, containing `slug='aec-nfl-lar-den-2026-09-27'`;
    - every `startup_open_orders_present` ERROR line says `1 open order(s)` and never contains `FRGN`;
    - the own row has `own_resting` True and the AEC row is flagged;
    - `startup_evidence_permits_arm(evidence) is True`.
- **T-G2** [CHANGE] `test_each_foreign_position_is_noted_once_per_process_and_counted`.
  - Arrange: positions {CROSSD, ASTATC} (self-identifying combo rows).
  - Act: `generate_mass_status()` twice.
  - Assert: exactly one `kind=position` INFO per slug; the last `durable reconciliation:` line contains `instrument_absent=0 foreign=2`; `_trading_refusals == []`.
- **T-G3** [CHANGE] `test_the_boot_sweep_leaves_a_manual_day_order_alone_and_latches_nothing`.
  - Arrange: `_rig(pin=True)` with an own rest; `_second_process` with book = [the AEC DAY order]; a cancel-all double that removes only rows on the posted slugs.
  - Act: `_connect()`.
  - Assert:
    - `_trading_refusals == []`;
    - `cancel_alls == [[<weather ledger slug>]]`;
    - own id cancelled;
    - the FRGN row is still listed;
    - no `boot-sweep` latch;
    - exactly one `kind=open_order` INFO;
    - the evidence permits arm.
- **T-G4** [CHANGE] `test_a_classification_error_warns_by_class_name_only_once_and_refuses`.
  - The predicate raises `RuntimeError("SECRET-x")`. Run `generate_mass_status()` twice.
  - Assert: exactly one WARNING `EXEC_FOREIGN_MARKET classification failed kind=position (RuntimeError)`, not containing `SECRET-x`; a refusal names CROSSD.
- **T-G5** [CHANGE] `test_a_failing_foreign_note_is_contained_and_never_refuses`.
  - After `_connect()`, replace `client.__dict__["_recording_log"]` with a `_RecordingLog` subclass whose `info` raises `RuntimeError` for messages containing `EXEC_FOREIGN_MARKET`. Positions {CROSSD}.
  - Assert:
    - `generate_mass_status()` completes; `_trading_refusals == []`; counts foreign 1;
    - exactly one WARNING `EXEC_FOREIGN_MARKET note failed kind=position (RuntimeError)`;
    - `generate_position_status_reports(None)` with no memoised pass returns `[]` without raising.
  - Recorded mutation: delete `_note_foreign_market`'s `except` (goes red).
- **T-G6** [CHANGE] `test_a_refused_open_orders_read_names_the_mapper_field_bounded_and_nothing_else`.
  - (a) A row with tif `TIME_IN_FORCE_FOREVER`: the WARN contains `open-orders read failed (ExecutionReportMappingError: open order [0].tif 'TIME_IN_FORCE_FOREVER' is not a declared TimeInForce)`.
  - (b) A 10,000-character tif: the detail is at most 200 characters plus `… (truncated)`.
  - (c) The read raising `RuntimeError("SECRET-x")` via the stub's `raises` map: `(RuntimeError)` only.
  - (d) End to end: `_rig(pin=True)` with an own rest, and a second process whose book carries the FOREVER row. After `_connect()`:
    - the existing `boot-sweep` latch is present (`boot_sweep_reread_failed:ExecutionReportMappingError`);
    - exactly one WARN names `.tif`. One boot names both.

**T-H. tests/unit/test_startup_evidence_parsers_agree_2026_09_16.py** (X1 member)
- **T-H1** [CHANGE] `test_both_parsers_agree_on_a_non_weather_only_book`: the dataclass keeps the flag through bytes; the strategy reason is None; with the flag False it is `STARTUP_OPEN_ORDERS_PRESENT_REASON`.

**Changed existing tests (review checkpoint; nothing weakened):**
- **CE-1.** `test_polymarket_us_exec_client.py::test_a_position_in_an_unknown_market_is_refused_not_mapped` (1336-1356):
  - `"a-market-we-never-loaded"` becomes UNLOADED at all three occurrences (1344 twice, 1353);
  - one docstring line cites the ruling;
  - the assertion logic is unchanged; only the slug under test is re-pointed.
- **CE-2.** `test_reconciliation_durable_reports_contract.py::test_the_reconciliation_counts_line_distinguishes_zero_records_from_zero_reports` (696-721):
  - `"foreign": 0` is added to `base` after `instrument_absent`;
  - the literal gains `foreign=0 ` after `instrument_absent=0 `;
  - `==` is kept: a widening (L-12);
  - the file is not format-clean, so split the literal by hand to stay within 100 columns.
- **CE-3** (pins commit). Line citations: test_entry_guard.py:191, and test_us_source_ingest_egress_guard.py:62 and :77 (numbers only).

**Must stay byte-unchanged and green:**
- exec_client:
  - the unusable-slug test (1359-1380);
  - `test_a_no_holding_with_no_no_leg_instrument_loaded_is_refused`;
  - `test_a_foreign_long_position_is_forwarded_priced_from_the_venue_cost_basis` (1116-1146);
  - the `slug-a`/`slug-b` tests (4943-5036);
  - the `_declared_positions` tests (905-995).
- contract 397-416.
- All five CRH open-orders gate tests.
- startup_evidence 323-431.
- The resolver refresh test (2460-2519).
- resting_slug_escalation (its `_FOREIGN_SLUG` is a weather slug).
- resting_sweep and resting_sweep_review.
- trial_day_latch 2318-2370.
- The parsers-agree combinatorial and reason-order tests (their only order is weather, 53-57).
- test_no_id_attribution.py 205-220; test_ambig_no_id_resolver.py.
- exec_reports `test_parse_open_orders_refuses_a_malformed_order`, including `TIME_IN_FORCE_FOREVER` (1928-1953), and the `_fields` test (1974-1979).
- The whole snapshot drift module.
- test_exec_refusal_health_surface.py.
- tests/integration/test_resting_order_lifecycle.py.

## GREEN change

**reports.py:**
- **RP1** `import re`.
- **RP2** the DAY set.
- **RP3** the namespace constants and the two functions.
- **RP4** the `names_own_market` field.
- **RP5** the `_open_order_record` tif block and field.
- **RP6** the `parse_open_orders` docstring.

**client.py** (18 hunks; base lines; no other function changes):
- **K1** Module docstring, after 122: a FOREIGN MARKETS carve-out paragraph. It says:
  - These are the one exception to "refuse to trade" (glossary).
  - They are logged once: positions at the boot reconciliation, orders at each enumeration.
  - They are never mapped, netted, sold, cancelled, hidden or allowlisted.
  - "Excluding one was tried and is WRONG" does not apply: no instrument is loaded, so no cap, exit or order can address the position.
  - Nautilus itself skips such a report (`execution_engine.py:2475-2477`), and such a position never reached Nautilus before the ruling either.
  - A weather-namespace slug is never foreign.
- **K2** The `exec.reports` import list (301-315) gains `is_non_weather_market_slug` and `metadata_slug_matches`, placed where ruff sorts them.
- **K3** `__all__` (395-413) gains `STARTUP_OPEN_ORDER_NON_WEATHER_KEY`, placed where ruff sorts it.
- **K4** After 497: the key constant, with the S0 comment.
- **K5** The `_loggable_slug` comment (above 520), and after 525: the kind constants, both bounds, `_loggable_quantity` and `_open_orders_failure_detail`.
- **K6** 554-560: `_MAP_FOREIGN`, and the comment fix.
- **K7** 587-598: the `"foreign"` field.
- **K8** 1493-1506: the snapshot field.
- **K9** 1529-1533: the open-orders contract now reads "every open order exempt: `own_resting` or `non_weather_market` exactly True".
- **K10** 1560-1568: the conditional key in `to_bytes`.
- **K11** 1617-1625: decode in `from_bytes`.
- **K12** After 2302: the two state fields.
- **K13** 5720-5738: the S4 loop head, plus the docstring (outcome list gains `foreign`).
- **K14** 5768-5770 docstring and after 5796: the count.
- **K15** After 6285: `_is_foreign_market`, `_warn_foreign_once`, `_note_foreign_market`. All sync and private; no `self._order_sender` reference.
- **K16** 6699-6706: the `_resting_cancel_evidence` docstring says "an own or FOREIGN-MARKET order".
- **K17** 6746-6754: the flag.
- **K18** 6959-6994: S5a, plus its docstring.

**trial_day_latch.py:**
- **TL1** Import the key in the existing exec.client import (68-75).
- **TL2** Gate docstring (1514-1530): S0 glossary plus the exemption.
- **TL3** S5c at 1545-1550.
- **TL4** `startup_evidence_permits_arm` docstring (1563-1570): "no unexempt open order".

**Evidence note** (value-free). It records:
- the venue doc lists DAY (snapshot :181, :187) and the SDK row omits it (drift test 167-168);
- on 10-28 activities page 0, 21 of 98 trade-side Order objects carry DAY:
  - 9 on non-weather markets, marked MANUAL, across 3 namespaces;
  - 12 on weather markets, each the passive side of a Breezy IOC;
- all 98 self-identify;
- the disposition, per S2;
- "inferred from activities-embedded orders and the venue doc; live `GET /v1/orders/open` capture pending (pre-boot probe)".

No ids, prices or quantities.

**Build order:**
1. **RED.** Write the shapes constants and builders, all new tests, and CE-1/CE-2.
   - Run them focused via `scripts/ci/run_tests_no_egress.sh --basetemp=<tree>/.pytest-tmp <modules>`, and keep the RED output.
   - An AttributeError, ImportError or TypeError on a new name is the expected RED only for T-A1–T-A7, T-R3, T-R5, T-B7, T-D3, T-D4, T-G4 and T-H1.
   - T-R1 fails on the base parser's own `ExecutionReportMappingError`, which is the behaviour under change.
   - Every other [CHANGE] test must fail on an assertion. Every [CHAR] test passes.
2. **GREEN.** Apply reports → client → trial_day_latch → evidence note. Re-run focused and keep the GREEN output.
3. **Mutation evidence.** Produce MUTATION_RED_EVIDENCE for every [CHAR] test, for T-B1's never-hidden sub-assertions and for T-G5's except (L-33).
4. **Lint:**
   - `ruff check` on the touched files;
   - the format rule (below);
   - mypy via `tests/unit/test_mypy_ratchet.py` (one full-config run; zero new errors, and none removed);
   - `cd <tree> && PYTHONPATH=<tree>/src lint-imports` (the console script; `python -m importlinter` is a no-op);
   - `scripts/ci/regen_closure_manifest.py --check`.
5. **Reviews** in parallel, read-only, each with the diff plus these invariants:
   - python-reviewer;
   - prediction-market-reviewer: sign-off on the R2 and R18 narrowings;
   - security-reviewer: the P15 checkpoint and the identity rule;
   - silent-failure-hunter.
6. **Commit A** after review fixes: code, tests and evidence note. Then compute every pin from A's final bytes, and make **Commit B** with all four pin classes.
7. **Merge and gate.** ff-merge into `feat/data-capture-and-risk` on the PRIMARY tree. Run the full gate there and read EXIT (addopts already has `-q`, so never add another). `rm -rf` the basetemp after reading it. Push only on EXIT=0.
8. **Relaunch.** Run the Acceptance pre-boot probe first. Then relaunch per the standard recipe:
   - the 16:50Z scheduled boot, if merged by 16:40Z;
   - otherwise a hand relaunch per the recipe.
   Enablement and caps are untouched.
9. **Close-out.** Acceptance read, then the docs commit C.

## Pins and gate

**Pin classes (Commit B, from the final bytes):**
1. **Exec client sha.**
   - Command: `sha256sum src/breezy/adapters/polymarket_us/exec/client.py`.
   - Write it to `_EXEC_CLIENT_SHA256` (test_forecast_quantile_ladder_manifest_and_markers.py:47), with a dated line in the 37-46 style: `# re-pinned 2026-10-29: EXEC-FOREIGN-POS (...); prior 417b4613d5b7db40034922d0c8f1e97e2d1ce974be4fc26fe3313200caf01032; <verdicts>  # noqa: E501`.
   - Tests:
     - `test_exec_client_is_byte_identical_to_its_pre_sl13_sha256`;
     - `test_b7_repin_is_sensitive_to_the_old_digest_and_to_a_single_flipped_byte`;
     - `test_autonomy_envelope.py::test_exec_client_never_edited`;
     - `test_aut1_wp0_closure_premises.py::test_submit_chain_is_not_byte_pinned_in_tests`.
2. **C7 closure JSON.**
   - Command: `sha256sum` of client.py, reports.py and trial_day_latch.py.
   - Replace rows 73, 77 and 236 of tests/unit/data/maker_stage0_c7_closure_pins.json. Rows 78 (submit_chain), 94 (symbology), 180 (component_health_watch) and EXEMPT are unchanged.
   - Test: `test_maker_stage0_c7_scope.py::test_verdict_closure_bytes_match_the_commit1_pin`. Its `set(loaded) == set(pins)` also proves no module was added.
3. **aut2.label.**
   - Command: `PYTHONPATH=<tree>/src /home/jon/breezy/.venv/bin/python -c "from breezy.persistence.autonomy.closure import closure_sha256; print(closure_sha256('breezy.analysis.labeling.label_run'))"`.
   - Write it to pins.py:36 with the comment `# re-pin: EXEC-FOREIGN-POS (exec/client.py, exec/reports.py, current_rung_hold/trial_day_latch.py; label_run closure only); was 6fd44dbc...5f88`. aut6.health is unchanged.
   - Tests: `test_autonomy_pins.py::test_code_identity_pins_cover_import_closure`, `test_te1_label_pin.py::test_aut2_label_is_pinned_to_its_own_closure`.
4. **Line citations (CE-3).**
   - Command: `grep -n` the final client for `^FILL_INDEX_KEY_PREFIX`, `^class PolymarketUSExecutionClient` and `self._order_sender.post_order(`.
   - Write the results to test_entry_guard.py:191 (keep `==`, refresh its dated comment) and test_us_source_ingest_egress_guard.py:62 and :77.
   - Tests: `test_fill_index_key_matches_exec_client_writer`, `test_every_banned_module_citation_resolves`.
   - The commit message states that each citation still resolves to its cited text (precedent 3e1569b7).

**Must pass with zero set or allowlist delta (run unmodified):**
- test_exec_refusal_health_surface.py;
- test_execution_egress_firewall_guard.py: X1 equality, the resolver and order allowlists, the order-sender ban, E0-INERT, X3;
- test_resting_path_firewall_delta.py: the sweep callee set, the connect order, the poll closure;
- test_ambig_no_id_firewall_delta.py: FROZEN_SOURCE and the prefix sha;
- test_cage_rule_constants_are_pinned.py;
- test_no_id_attribution_purity.py;
- test_polymarket_us_exec_snapshot_drift.py;
- test_polymarket_us_exec_endpoints.py;
- test_polymarket_us_write_transport.py;
- test_operator_reserved_controls.py;
- test_maker_fill_record_selector_freeze.py;
- `regen_closure_manifest.py --check`; `lint-imports`.

**Focused run** (advisory in a worktree). Known worktree-only failures are not regressions: phase-2 interpreter_link, and the bwrap script mode 0775 (`chmod 0755`, never committed).
- **Feature modules:** the 8 RED modules.
- **Neighbours:**
  - test_current_rung_hold_ambiguous_resolver.py, test_polymarket_us_discovery.py, test_polymarket_us_symbology.py;
  - test_polymarket_us_resting_slug_escalation.py, test_polymarket_us_resting_sweep_review.py, test_current_rung_hold_trial_day_latch.py;
  - test_no_id_attribution.py, test_ambig_no_id_resolver.py;
  - test_polymarket_us_exec_snapshot_drift.py, test_polymarket_us_exec_endpoints.py;
  - tests/integration/test_resting_order_lifecycle.py.
- **Pin modules:** test_forecast_quantile_ladder_manifest_and_markers.py, test_maker_stage0_c7_scope.py, test_autonomy_pins.py, test_te1_label_pin.py, test_aut1_wp0_closure_premises.py, test_entry_guard.py.
- **Whole-tree guards, listed literally:**
  - all `tests/unit/test_autonomy_*.py`;
  - test_strategy_module_gate.py, test_nautilus_native_import_gate.py, test_r2_2_citation_map.py, test_runtime_import_isolation.py;
  - test_execution_egress_firewall_guard.py, test_polymarket_us_readonly_guard.py, test_polymarket_us_write_transport.py;
  - test_operator_reserved_controls.py, test_operator_control_assignment_scan.py;
  - test_polymarket_us_credential_serialization.py, test_polymarket_us_fee_schedule_pin.py;
  - test_mypy_ratchet.py, test_autonomy_bwrap_argv.py;
  - test_exec_refusal_health_surface.py, test_cage_rule_constants_are_pinned.py, test_no_id_attribution_purity.py, test_ambig_no_id_firewall_delta.py, test_resting_path_firewall_delta.py;
  - test_maker_fill_record_selector_freeze.py, test_set_family_halt_cli.py;
  - test_settlement_conservatism_prose_guard.py (after commit C);
  - all of `tests/contract/`.
- **Sweep:** `tests/unit -k "ambiguous or latch or intent or ledger or exec or resolver or entry_guard"`.

**Format rule** (ruff 0.16.4, line-length 100; counts re-measured for r3):
- Clean at base. `ruff format --check` must stay clean, and write mode is allowed:
  - reports.py, trial_day_latch.py;
  - test_polymarket_us_resting_order_shape.py, test_continuous_rung_hold_open_orders_gate_2026_09_16.py, test_polymarket_us_resting_sweep.py;
  - test_entry_guard.py, test_us_source_ingest_egress_guard.py, test_forecast_quantile_ladder_manifest_and_markers.py, pins.py.
- NOT clean at base (format hunks at base) — never write-format; hand-format new code instead:

  | File | Hunks |
  |---|---|
  | client.py | 44 |
  | test_polymarket_us_exec_client.py | 55 |
  | durable-reports contract | 16 |
  | test_polymarket_us_exec_reports.py | 19 |
  | polymarket_us_exec_shapes.py | 2 |
  | test_polymarket_us_startup_evidence.py | 2 |
  | parsers_agree | 1 |

- Check for each of those 7 files: the following must print nothing.
  ```
  diff <(git show 97dd428a:F | ruff format --no-cache --diff --stdin-filename F - | grep -E '^[-+]' | grep -vE '^(---|\+\+\+) ') \
       <(ruff format --no-cache --diff F | grep -E '^[-+]' | grep -vE '^(---|\+\+\+) ')
  ```
  That proves no new format debt and no reformat of old lines.

**Full gate** (binding; PRIMARY tree after merge): `scripts/ci/run_tests_no_egress.sh`.
- Basetemp inside the tree; `rm -rf` it after reading EXIT.
- Under systemd-run, pass `-p LimitNOFILE=524288`.
- A failure of the persistence import budget under host load is flaky: compare per-entry deltas before calling it a regression.

## Acceptance

**Step 0 — offline replay (after merge, before the boot; read-only, delegated).**
- Feed the saved 10-28 body `~/.local/share/breezy/scratch/session-2026-10-27/G_crossd_position/out/positions.json` into the merged client, through `_build_rig(positions=...)`, in a scratch pytest module.
  - The module lives OUTSIDE the repo and is never committed.
  - Run it with `scripts/ci/run_tests_no_egress.sh <module> --basetemp=<scratch>/.pytest-tmp`.
- Record value-free: foreign=1, instrument_absent=0, refusals=0, `trading_refusals` empty, one `kind=position` line.
- This closes the F=0 gap with the venue body verbatim (L-48).

**Pre-boot (16:00-16:45Z, read-only, delegated).** Outputs go to a fresh session-scratch dir and never the repo, because they carry the account's positionId and order ids.
- Run a positions + open-orders variant of `G_crossd_position/probe_crossd.py`: two GETs through the shipped read client.
- It classifies with the merged `reports.is_non_weather_market_slug` and `reports.metadata_slug_matches`, checks the envelope with `submit_chain.open_orders_envelope_is_known`, and parses with `reports.parse_open_orders`.
- Record, value-free:
  - positions: row count, `eof`, whether `nextCursor` is present;
  - each slug's class: NON-WEATHER self-identifying, NON-WEATHER not self-identifying, WEATHER, or UNUSABLE; this gives the predicted `foreign=F`;
  - open orders: envelope known, and parse OK or the refused field. This is the first live capture of a manual open order's tif, indicator and self-identification.
- **Stop and surface to the operator before 16:50Z** (launch blockers, never worked around):
  - `eof` not true (R14);
  - a WEATHER position Breezy did not open (R2);
  - a non-weather position that does not self-identify (R18) or an unusable slug (R13);
  - `parse_open_orders` raising (R7): name the refused field from the mapper message.
- While alerts are undelivered (R15), this probe is part of every relaunch.

**16:50Z boot; the node log must show:**
1. `durable reconciliation: … instrument_absent=W foreign=F refusals=0 …`, matching the prediction. W is expected to be 0.
2. Exactly one `EXEC_FOREIGN_MARKET kind=position slug=…` line per foreign slug for the whole process, and one `kind=open_order` line per FOREIGN-MARKET slug with an open order.
3. None of the following:
   - a `Trading refused: the venue reports a position in market '<foreign slug>'` line;
   - a `latched a trading refusal` denial;
   - a `component_degraded` alert whose detail names a foreign slug or "for which no instrument is loaded" (this filter excludes the AMBIGUOUS→GET noise of 4+1 per day);
   - a `boot_sweep_reread_failed` latch;
   - an `EXEC_FOREIGN_MARKET … failed` WARNING;
   - an `open-orders read failed` WARN. If one appears, its detail now names the refused field; read it and act per R7.
4. Rests bound:
   - at least one rest bound in the boot window (10-28 had 5, 16:50-17:03Z);
   - fallback if the strategy posts nothing (regime): zero denials and an empty `trading_refusals` at boot+15 min;
   - if any rest binds: zero `resting poll: the read did not map` lines, which is the pending live confirmation of 97d3fd9e.
5. A FOREIGN-MARKET open order listed pre-boot is still listed after the sweep.
6. Unchanged precondition: the boot-time permit line and `maker_live_orders enabled=True reason=ok`.

**If F=0** (the parlay has settled out of the page; its legs tipped 2026-10-29T00:00Z):
- Acceptance is boot items 1, 3 and 4 with `foreign=0`, plus Step 0.
- The PROGRESS item STAYS OPEN until the first boot with `foreign>=1` is captured. The account traded non-weather on 09-27, 10-20 and 10-28.

**Close-out:**
- The acceptance read and the residual table (R2, R5-R7, R11-R15, R17-R19, each with its trigger) go in docs/evidence/P4_LIVE_READ_2026-10-29.md.
- PROGRESS sits at 12,093 bytes of its 12 KB budget (P29):
  - replace the 1,180-byte item line with a short DONE/OPEN line;
  - add ONE follow-ups line pointing at the residual table (R5, R6, R7 incl. the boot-sweep latch scope, R11, R12, R13, R14, R15, R18);
  - consolidate, never raise the budget.
- L-69, via the lessons skill:
  - the glossary;
  - the narrowings R2, R13, R18 and the boot-only scope R19;
  - the clearing paths;
  - the manual-weather rate;
  - the alert gap;
  - two operator notes:
    - manual non-DAY orders on Breezy's ledger weather slugs are cancelled at boot (spec 9.18), and a manual weather DAY order still blocks the enumeration;
    - avoid UI trades while a no-id AMBIGUOUS intent is open (R12).

## Rollback
- One line: `git revert --no-edit <pins-sha> <code-sha>`, then gate and relaunch by the standard recipe.
- This restores the pre-change fail-closed behaviour: foreign positions latch again and DAY open orders are refused again.
- Evidence rows are compatible both ways:
  - the old `from_bytes` reads only named keys (1617-1625);
  - the old gate refuses flagged rows.
- `names_own_market` is in-memory only. The counts line is log-only.

## Risks
- **R1. False FOREIGN on Breezy's own exposure.** Locks:
  - the namespace (T-A4; T-A5 against the discovery discriminator; discovery loads only `tc-temp-` and raises otherwise, P23);
  - self-identification (T-B6, T-D7);
  - the loaded-instrument rule (T-B5);
  - the AUTOMATIC veto (T-D6);
  - Breezy never sends DAY (P26).
  - A fill-index check is rejected: it would add boot-path store reads and refusal side effects.
- **R2. Manual WEATHER activity still stops the bot** (the carve-out).
  - A manual weather position refuses (`_map_position#1`, or `_entry_price_from_records#1` if loaded). Clearing path: the position leaves the page, then a restart (T-B8).
  - A manual weather open order refuses the CRH gate. On a ledger slug the boot sweep cancels it (spec 9.18).
  - A manual weather DAY order still refuses the WHOLE enumeration, exactly as at base (T-R4):
    - the CRH gate refuses;
    - the boot sweep, when it runs, latches `boot-sweep` until the next boot;
    - the no-id resolver goes INCOMPLETE.
  - Observed rate: 1 own manual weather order on activities page 0 (2026-08-05). The observed operator weather orders were GTC/IOC, not DAY.
- **R3. Test edits CE-1..CE-3** are the review checkpoint.
- **R4. Log fields.**
  - The slug passes the strict ASCII charset and is logged with `!r`.
  - qty goes through `_loggable_quantity` and `!r`.
  - The mapper detail is bounded at 200 and echoed for `ExecutionReportMappingError` only.
  - Once per (kind, slug).
- **R5. AUT-2 reconcile legs.** The positions leg raises a CRITICAL `venue_only_slug`; the cash leg fails on unexplained cash. Both must adopt the predicate before any caller wires them. Today there is no caller; add this as a precondition at OPS-4 planning.
- **R6. `set_family_halt_cli`.**
  - A foreign position refuses only exit-path families (477-499).
  - A malformed foreign row is UNKNOWN and refuses every family.
  - Follow-up.
- **R7. Strict mapper residual.**
  - Any OTHER strictness failure on any open-order row still refuses the whole read:
    - an undeclared enum member;
    - a non-positive quantity, or a cumQuantity outside [0, quantity];
    - a non-USD or out-of-range price;
    - a missing field or a non-object row;
    - a DAY row not naming its own non-weather market.
  - Consequences: the CRH gate refuses; no-id goes INCOMPLETE; with a non-empty ledger the boot sweep latches `boot-sweep`, which denies every submit, maker included, until the next boot.
  - Trigger: the first message-bearing `open-orders read failed` WARN.
  - Follow-ups, each needing its own peer-reviewed plan:
    - (a) scope or auto-clear the boot-sweep re-read latch on a later readable enumeration;
    - (b) a per-row tolerant mapping for self-identifying non-weather rows inside `parse_open_orders`. This is possible now that the predicate is in reports.py, but it loosens the enumeration mapper for those rows.
- **R8. Byte-pinned shared tree:** the format rule, no stash, pins committed after the final code bytes.
- **R9. F=0 acceptance:** the item stays open; Step 0 is the interim evidence.
- **R10. Threads:** new state is touched on the event loop only; no clock callback is added.
- **R11. Balance-delta integrity checks.**
  - `portfolio_roi_report.DailyUnexplained` (1377) will flag the parlay's cash as UNEXPLAINED_CAPITAL_FLOW, because `account_activity` drops TRADE and RESOLUTION rows (14-16, 100-104).
  - `roi_status` is ledger-derived and unaffected.
  - Follow-up: net out non-weather cash, classified by the predicate.
- **R12. No-id resolver.**
  - A UI parlay leg is a CONTRADICTION while a no-id AMBIGUOUS intent is open, because:
    - `_leg_from_trade` sets manual = (indicator == MANUAL) (no_id_attribution.py:200);
    - the 10-28 parlay aggressor and passive both carry UNDEFINED (activities_p0);
    - `no_id_aggressor_legs` collects every aggressor leg with no slug filter (208-258);
    - `classify_no_id_evidence` marks a non-manual unmatched in-window leg `unattributed` (369-394).
  - Trigger: a CONTRADICTION token `unattributed` whose leg slug is outside `tc-temp-`.
  - The fix touches a purity-pinned module, so it is its own item. Interim operator note in L-69.
- **R13. Unusable non-weather slugs** (uppercase, `.`, `^`, longer than 128, non-ASCII, trailing newline) still refuse. Observed: 0 of 44.
  - Trigger: the first such slug at a boot or in the probe.
  - If ever widened: no instrument can exist for one, so a case-insensitive namespace test with the existing log bounds would suffice, without `_find_instrument`.
- **R14. Pagination.**
  - Positions: `eof != true` latches `positions_read_failed` and `generate_position_status_reports#1`, DURABLE (6130-6145). The client sends a bare path, and the page size is undocumented.
  - Open orders:
    - `parse_open_orders` refuses a present `eof` that is not true (1935-1938);
    - it records an unknown `nextCursor` envelope key (bounded, not fatal);
    - the boot-sweep re-read refuses ANY key beyond `orders`/`eof` (`open_orders_envelope_is_known`, submit_chain.py:929-933).
  - The probe records both. R-4P-2 cursor-following is the trigger.
- **R15. Alert delivery (P20).**
  - On 10-28: 547 delivery failures in the 16:50Z log, first at 21:30:00Z on a MAKER_ORDER_DENIED, under the denial flood.
  - 546 in the 23:45Z log, starting with that process's FIRST alert (the crossd `component_degraded`).
  - The follow-up targets the sink's behaviour under an alert flood or quota, not just "delivery broken".
  - Every retained refusal stays log-loud only until delivery works.
- **R16. Withdrawn in r3.** DAY is no longer admitted on weather rows, so the boot sweep's handling of a weather DAY order is unchanged.
- **R17. AUTOMATIC veto.** If the venue ever stamps UI orders AUTOMATIC, the CRH gate refuses on them, visibly, in the ERROR count. The maker is unaffected.
- **R18. Non-self-identifying foreign rows still refuse.**
  - A position without `marketMetadata.slug == key` latches `_map_position#1`: the 10-28 outcome.
  - An order without `marketMetadata.slug == marketSlug` is never flagged, and a DAY one refuses the read.
  - Observed: 1/1 positions and 98/98 orders self-identify (P25). Deliberate (D-10).
  - Trigger: a `_map_position#1` refusal naming a non-`tc-temp` slug, or the WARN detail "enumerated only on a non-weather market whose marketMetadata.slug names it".
- **R19. Mid-session scope.**
  - A foreign position opened mid-session is not mapped or logged until the next boot (mass status is boot-only, 2314-2321).
  - It is recorded in every evidence row and listed by `held_position_slugs` meanwhile.
  - Open orders are classified at every enumeration.
- **Portability (Kalshi):**
  - The predicate lives in the PM.us mapper and the loaded-instrument rule in the PM.us client.
  - The strategy reads one evidence flag defined in the PM.us client module, exactly like `own_resting` and `resting_cancel_unconfirmed`.
  - It is as portable as those keys: a second venue needs its own evidence namespace, predicate and gate wiring, as today.
  - The only new code literal is `WEATHER_SLUG_NAMESPACE` in reports.py.

## Changes since r1

| # | Finding (reviewer, severity) | r2 change (r3 note) |
|---|---|---|
| F1 | design MED: P12 false; focused list misses guards | P12 rewritten; CE-3 + pin class 4; guards listed literally |
| F2 | design LOW: format rule unsatisfiable | Write-format clean files only; changed-line equality check |
| F3 | design LOW: TE-2 pins symbology | Predicate left symbology (r3: hosted in reports.py, V2) |
| F4 | design LOW: three classification sites; one grammar bound | Classify once; T-A4 binds all three grammars (r3: + T-A5) |
| F5 | design LOW: R7 understated | R7 rewritten (r3: trigger + remedies, V3) |
| F6 | design LOW: residuals not stated | R2, R13, R14 (r3: + R18, R19) |
| F7, F15, F26, F32 | design/market/python/security LOW: qty unbounded | `_loggable_quantity`; T-B9 |
| F8, F42 | design/silent LOW: "foreign" vocabulary | S0; `non_weather_*` names |
| F9, F35 | market/silent HIGH: DAY refused | DAY declared (r3: self-identifying non-weather rows only, V2) |
| F10 | market MED: tests undefined; trimmed fixture | All defined; T-B2; T-B4; full key-tree fixture (D-1); CE-1 reworded |
| F11 | market MED: balance-delta consumers | R11 |
| F12 | market LOW: docstring; triage text | K1; triage edit declined (D-2) |
| F13 | market LOW: acceptance fragile; N=0 | Scoped items + F=0 branch (r3: + Step 0, V31) |
| F14, F39 | market/silent LOW: no-id parlay leg | R12 (r3: evidence + trigger, V8) |
| F16 | market LOW: manual-weather rate; pagination | R2; R14 |
| F17 | python HIGH: line pins 430, 1965, 7752 | CE-3; pin class 4 |
| F18 | python MED: TE-2, decide the host | r2 chose submit_chain (r3: reports.py, V2) |
| F19 | python MED: mypy ratchet + guards | Ratchet run as a test; guards pasted literally |
| F20 | python MED: no-side-effect claim unpinned | Load-bearing order comment + T-D5 |
| F21, F30 | python/security LOW: trailing newline | fullmatch + isascii; T-A2/T-A3 |
| F22 | python LOW: G1 redaction vacuous | FRGN id; assert absence |
| F23 | python LOW: acceptance noise | Text-scoped filter |
| F24 | python LOW: R7 maker claim wrong | R7 rewritten |
| F25 | python LOW: imprecise refs; private state | Lines fixed; emission via TimedClient (T-G) |
| F27 | security MED: lock mutations survive | T-B4, T-B5, T-D2 with mutation evidence |
| F28, F36 | security/silent MED: key-only classification | Contradiction rule (r3: the row must name itself, V13/V20/V21) |
| F29 | security LOW: near-miss prefixes | Separator-blind; T-A2; T-A4; tuple declined (D-3) |
| F31 | security LOW: AUTOMATIC veto | T-D6, R17 |
| F33 | security LOW: vocabulary; EMPTY texts | S0; K9, K16, TL2/TL4; oracle declined (D-6) |
| F34 | security LOW: residual table | In the 10-29 P4 read |
| F37 | silent MED: emission; loaded rule; WARNING; mid-session | T-G2, T-B5, T-G4; mid-session declined (D-4; r3 states the scope, V30) |
| F38 | silent MED: clearing path; alerts; probe | T-B8; R2, R15; probe uses the shipped predicate |
| F40 | silent LOW: R5/R6 follow-ups | Follow-ups; R6 corrected |
| F41 | silent LOW: boot-path raise | S9; T-G4 (r3: + T-G5, T-D9) |

## Changes since r2

| # | Finding (reviewer, severity) | r3 change |
|---|---|---|
| V1 | design MED: the open-orders refusal logs the class only (L-37) | K18's error branch logs `_open_orders_failure_detail`: the mapper message bounded at 200, for `ExecutionReportMappingError` only. T-G6 sits in resting_sweep, because the Rust logger is invisible to the startup_evidence module (P30). Acceptance item 3 reads the detail. The sweep is not edited (P21). |
| V2 | design LOW: host the predicate in reports.py; DAY for non-weather rows only | Adopted (S1, S2). DAY also requires self-identification. submit_chain is byte-untouched, so C7 row 78 is dropped. R16 is withdrawn. T-R4 [CHAR] locks the weather side. The DAY set is worded as the first value-level sibling of the key-level path. |
| V3 | design LOW: R7 follow-up; L-69; probe in the recipe | R7 gains a trigger and two follow-up remedies. L-69 gets R2, R7 and R18 (R16 is withdrawn). The pre-boot probe runs at every relaunch while alerts are undelivered. |
| V4 | design LOW: P7 under-evidenced | P7 and K1 add the native filter, Breezy's config and the docstring objection by name. |
| V5 | design LOW: Kalshi claim overstated | Reworded: as portable as the existing evidence keys. |
| V6 | design LOW: stale "foreign" wording; `_loggable_slug` | Comment beside `_loggable_slug` (K5). The component_health_watch edit is declined (D-7). |
| V7 | market LOW: probe records the live parse only | Stop-and-surface launch-blocker rule on a parse failure. |
| V8 | market LOW: R12 evidence and hook | R12 rewritten with the UNDEFINED-indicator evidence and a trigger; L-69 interim note. |
| V9 | market LOW: R16 untested | Superseded by V2: DAY is not admitted on weather rows. T-R4 pins the unchanged behaviour. The L-69 sentence covers spec 9.18 for non-DAY orders. |
| V10 | market LOW: R13 follow-up | R13 gets a trigger and a widening note, and goes in the residual table. |
| V11 | market LOW: instrument_absent wording; DAY evidence caveat | S6 reworded (NO-leg and cache-miss cases). The evidence note says "inferred; live capture pending". The probe records the first live manual open order. |
| V12 | python LOW: "never hidden" untested for positions | T-B1 asserts the evidence row (CROSSD, "963") and `held_position_slugs`. Mutation: the writer skips non-weather slugs. |
| V13 | python LOW: sparse-metadata leniency untested | Leniency dropped: the row must name itself (S4). T-B6 (d)-(h) [CHAR] pins it. R18 added. |
| V14 | python LOW: [CHAR] tests cannot pass at base | [CHAR] tests use base observables (`counts.get`, decoded-bytes `.get`). The step-1 rule is rewritten. |
| V15 | python LOW: identifier collisions | S0-S10, K1-K18, RP1-RP6, TL1-TL4, T-xx, CE-1..3, R1-R19, V1-V31. |
| V16 | python LOW: property test | T-A7 (hypothesis). |
| V17 | python LOW: A5 cannot see a non-tc-temp family | T-A5 re-pointed at the discovery discriminator (P23). |
| V18 | python LOW: dead outer try; magic kind strings | `_is_foreign_position` is removed (the total `metadata_slug_matches` replaces it). `_FOREIGN_KIND_*` constants are pinned by T-B9. Tests assert the literal acceptance tokens. |
| V19 | python LOW: optional reports.py host | As V2. |
| V20 | security MED: no order-side identity rule | `OpenOrderRecord.names_own_market` (default False). The flag and the DAY admission require it. T-D7, T-R4, T-R5. Never a raise, so R7 does not widen. |
| V21 | security LOW: positions sparse metadata | Adopted (as V13). |
| V22 | security LOW: A5 | As V17. |
| V23 | security LOW: D7.8/R2 wording; no-id sentence | Under V2, S8 rule 8 and R2 are accurate again and reworded precisely. The S2 no-id sentence is corrected (echo match = CONTRADICTION). |
| V24 | security LOW: [CHAR] at base | As V14. |
| V25 | silent MED: mapper message at three sites; latch follow-up; pagination | The K18 site and T-G6 are adopted. The sweep and no-id sites are disputed (D-8); T-G6(d) proves one boot names both. The latch follow-up is in R7; open-orders pagination is in R14. |
| V26 | silent MED: untested guarantees | (a) T-B6, strict direction (D-10). (b) T-D8 kills `manual is True`. (c) T-G5 (note failure contained) and T-D9 (read failure after success). T-B9 first asserts that its helpers exist. |
| V27 | silent LOW: WARNING lacks kind and slug; no dedupe | Kind added, deduplicated per (stage, kind, class) via `_warn_foreign_once`. The slug is omitted (D-9). |
| V28 | silent LOW: wrong citations | submit_chain import is client.py:284. reports.py 1589-1603 is the docstring and 1620-1633 the code. S1 states the foreign path is stricter than the mapper. |
| V29 | silent LOW: R15 facts | R15 rewritten with the verified counts and onsets. |
| V30 | silent LOW: mid-session positions never logged | R19; K1 and L-69 state the boot-only scope. |
| V31 | silent LOW: F=0 leaves the live path unproven | Acceptance Step 0: an offline sandboxed replay of the saved 10-28 body. |

### Disputed findings (checkable evidence)
- **D-1. Verbatim parlay row "only positionId zeroed"** (silent MED, market MED, r1): disputed in part.
  - The repo's venue evidence is value-free (ORDER_SHAPE_DRIFT_2026-10-28.md:13), and the row carries the operator's cost, avgPx, fees, cashValue and positionId.
  - The fixture keeps the full key tree, the JSON types and the slug, with synthetic values.
  - Step 0 replays the real body outside the repo.
- **D-2. Edit the refusal-triage text** (market LOW, r1): declined.
  - test_exec_refusal_health_surface.py:58 and :64 stay true in the S0 old sense.
  - The module is a run-unmodified guard.
- **D-3. Make the namespace a tuple** (security LOW, r1): declined (YAGNI). One namespace exists, and T-A4/T-A5 bind it.
- **D-4. Log mid-session foreign positions from the evidence writer** (silent MED, r1): declined.
  - `generate_mass_status` is boot-only (2314-2321), and `position_check_interval_secs=None` is required (module docstring 153-157).
  - The scope is now stated (R19).
- **D-5. Skip foreign legs in `classify_no_id_evidence`** (r1): deferred to its own item. `ATTRIBUTION_IMPORTS` is purity-pinned (R12).
- **D-6. Reword `_dataclass_permits_arm`** (security LOW, r1): declined.
  - It is the parity oracle over an all-weather corpus (parsers_agree 53-57, 114-123).
  - T-H1 adds the flagged case.
- **D-7. Fix the `component_health_watch.py:103-107` comment in commit C** (design LOW): declined.
  - The file is byte-pinned (C7 row 180) and sits in the label_run closure (closure_manifest.py:180), so a comment edit adds a pinned file to this change.
  - The comment ("a foreign position to resolve") stays true in the S0 old sense: a degraded client is still possible on an unattributed weather position.
- **D-8. Log the mapper message at the boot sweep (8521) and the no-id read (4674)** (silent MED): declined.
  - The sweep's callee set is pinned EXACTLY (test_resting_path_firewall_delta.py:770-788, 812-815). A `str(...)` or helper call is a new callee, so it is a firewall-set delta.
  - `_resolve_no_id_intent` is a scanned resolver coroutine (firewall 2159-2186) whose allowlist lacks `str`, and S9 keeps new code out of scanned coroutines.
  - The diagnosis still lands:
    - `_connect` awaits the sweep (2683), then `_refresh_startup_position_evidence` (2690), whose WARN carries the bounded detail for the same unfiltered endpoint;
    - the order is pinned by test_resting_path_firewall_delta.py:842-851;
    - the resolver refresh repeats it every 60 s;
    - T-G6(d) proves a single boot logs both.
- **D-9. Put a charset-validated slug in the classification WARNING** (silent LOW): declined.
  - The slug's charset is unproven exactly when classification failed, and validating it re-runs the faulting path.
  - The position refusal that follows names the slug through the existing `_map_position#1` text, and the order stays in the evidence row.
  - Kind and dedupe are adopted.
- **D-10. Keep the sparse-metadata leniency and test it (B10 asserting foreign=1)** (silent MED (a)): disputed in direction; resolved strict instead.
  - The strict mapper itself refuses a present block with no slug (reports.py:1622-1633).
  - Every observed row self-identifies (P25).
  - Leniency has a silent failure mode. A venue keying drift (e.g. keys becoming the `positionId` UUID, which the predicate admits) plus a dropped metadata block would make Breezy's own weather position an ignored FOREIGN row, with caps reading zero: the hazard client.py:113-122 names.
  - The strict rule's failure mode is the visible 10-28 latch, recorded as R18 with a trigger.
  - T-B6 pins the strict direction with mutation evidence.

