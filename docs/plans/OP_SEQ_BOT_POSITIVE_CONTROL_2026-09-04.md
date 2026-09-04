# OP-SEQ bot-driven positive control — plan (2026-09-04)

Repo `/home/jon/breezy` @ `798db7d`, branch `feat/data-capture-and-risk`. Read-only planning; no files written.

## Goal

Replace the hand-driven OP-1→OP-4 runbook sequence with ONE bot-driven, stop-ruled run that (a) rests its own positive control, (b) proves the venue enumerates it (OQ-B), (c) cancels it via the pinned cancel-all (OQ-D), (d) proves the account flat again, and (e) writes one value-free `PRIVATE_` artefact whose verdict is the evidence the flip of `WRITE_CANONICAL_STRING_VERIFIED` (`src/breezy/adapters/polymarket_us/write_transport.py:48`) cites. Operator residue: launching the command.

Decisive reframing the plan is built on: **the canonical string never signs the body** — `timestamp + method + path` (`api-reference_authentication_2026-08-25.md`, restated in the create-order snapshot at `api-reference_orders_create-order_2026-08-25.md:554`), and the repo's builder is `build_canonical_path_without_query` (`write_transport.py:123-130`, probe `:367-369`). Therefore a 401/403 on `POST /v1/orders` is a pure signing answer, and a 200-with-id already verifies write signing on the create-order verb — strictly earlier and stronger than the cancel-all verb it precedes. That is why resting the control is not a risk added to the sequence; it is the first and cheapest branch of the answer (401/403 → CLOSED-NO with nothing resting and $0 at risk).

## Null-hypothesis (Nautilus first)

- Nautilus ships **no Polymarket.us adapter**: `.venv/lib/python3.13/site-packages/nautilus_trader/adapters/` contains only `__init__.py` and `env.py`. There is no native signed-REST venue probe, no native canonical-string verifier, and nothing that could sign an Ed25519 `X-PM-*` header triple.
- The only native primitive that applies is `nautilus_pyo3.HttpClient`, and it is **already** what both the shipped write transport (`write_transport.py:57-73`) and the probe's write client use. Reuse continues; nothing new is built at the transport layer.
- Could the *bot* do this natively via `TradingNode` → `_submit_order`? No, and the refusal is structural, not stylistic: `exec/submit_chain.py:40-42` (`CANONICAL_UNVERIFIED_REASON`) makes the exec client refuse to submit while the flag is False, and the flag can only be flipped by this evidence — a closed circle. Independently, `unmappable_order_reason` (`submit_chain.py:225-226`) refuses anything that is not `TimeInForce.IOC`, so a **resting GTC control order is unreachable through the bot's exec path by construction**. The sequence therefore belongs in the probe, and the probe reuses the canonical-string builder rather than duplicating it.
- Verdict: extension, not reimplementation. Nothing in Nautilus is modified, patched, or bypassed.

## Design

**Location: extend `scripts/venue/polymarket_us_write_signing_probe.py`.** It is already the one B4-exempt script (`tests/unit/test_polymarket_us_readonly_guard.py:242-247`), already carries the credential guard, the read client, `_sign_write_headers`, `_signed_get_open_orders`, `_signed_post_cancel_all`, the intent marker, and the artefact discipline. A new `scripts/venue/polymarket_us_positive_control.py` would require **widening `B4_EXEMPT_PATHS` to a third exact path** plus a matching `CAGE_EXEMPTIONS` row (`tests/unit/test_cage_rule_constants_are_pinned.py`) and a second non-vacuity proof (`readonly_guard.py:931-942`) — a real barrier cost bought for zero benefit, since the two files would be near-duplicates. **Rejected.** New CLI mode: `--sequence`.

**B9 is untouched:** the probe never calls `post_order` or `clear_submit_intent`; it calls `write_client.post(...)` directly, exactly as `_signed_post_cancel_all` does (`:398-403`). The pinned sets at `readonly_guard.py:1700-1707` stay byte-identical, and a test asserts that.

Sequence (single `run_sequence` coroutine; every step's stop is terminal — no step is ever retried):

| # | Step | Requests | Pass condition | Stop code / action |
|---|---|---|---|---|
| S0 | Artefact pre-check (`O_EXCL` filename exists?) | 0 | absent | `FileExistsError`, exit 2, refused before spending a venue request (mirrors `:484-489`) |
| S1 | Pre-flight signed `GET /v1/orders/open`, unfiltered | 1 (signed) | 200 **and** `{"orders":[]}` | `PREFLIGHT_NOT_200` (transport fault → re-run once) / `PREFLIGHT_NOT_EMPTY` (account not flat → STOP, no write ever) |
| S2 | Instrument selection: public `GET /v1/markets` via `get_public` | 1 (unsigned, gateway) | ≥1 eligible weather bucket (below) | `NO_ELIGIBLE_INSTRUMENT` → STOP, exit 2, **no artefact** (nothing was written) |
| S3 | `_signed_post_order`: `POST /v1/orders`, limit BUY YES, qty 1, price $0.01, GTC | 1 (signed, write) | 200 with an order id | `REST_UNAUTHORIZED` (401/403) → **CLOSED-NO**, STOP, artefact, nothing resting, $0 at risk · `REST_AMBIGUOUS` (any other status, or 200 without id) → skip S4, go to S5 as one-shot cleanup, verdict `INCONCLUSIVE` |
| S4 | Enumeration + fill read: signed `GET /v1/orders/open`, unfiltered | 1 (signed) | payload enumerates **our** id, `cumQuantity==0`, state `ORDER_STATE_NEW` | `OQB_NO` (id absent) → cleanup via S5, then STOP + escalate · `CONTROL_FILLED` (cumQuantity>0 / state FILLED) → cleanup via S5, then STOP + escalate (≤$0.01 + fee spent) |
| S5 | `_signed_post_cancel_all` — unchanged (`:379-412`) | 1 (signed, write) | 200, or non-401/403 carrying `CancelAllOrdersResponse` | `CANCEL_NOT_OK` → **STOP, un-flat, never retried**; artefact written; exit 2 |
| S6 | Post-flight signed `GET /v1/orders/open` | 1 (signed) | 200 + empty | `POSTFLIGHT_NOT_200` / `POSTFLIGHT_NOT_EMPTY` — describe the read, do not by themselves answer OQ-D |

Verdict field (computed, never a free-text word): `CLOSED_YES_BOTH_VERBS` iff S3 200-with-id **and** S4 enumerated-and-unfilled **and** S5 ok **and** S6 200-empty; `CLOSED_NO` iff S3 401/403; `INCONCLUSIVE` otherwise. Full budget: **4 signed + 1 unsigned** requests; every refusal path issues strictly fewer.

Interruption: `_write_intent_marker` moves to **immediately before S3** (the first write) and is widened to record both write paths as constants. The existing `except BaseException` → partial artefact + re-raise (`:561-577`) wraps S3–S6, with `INTERRUPTED` as the value of the postflight reason (schema unchanged in shape, per `:178-182`).

**`--positive-control` (existing, `:663-671`, `:528-536`): KEPT, unchanged.** Its tests (`test_positive_control_success_...`, `test_positive_control_failure_...`) stay green untouched. It is no longer referenced by the runbook. **OP-2 is subsumed by S4** and is strictly stronger: OP-2 inferred OQ-B from an *unattributable* refusal (`PREFLIGHT_NOT_EMPTY` carries no id — `:169-171`), whereas S4 looks for an id **we minted the intent for**, so "the venue enumerates the whole account" is answered with attribution instead of by elimination.

## Instrument selection

Source: one unauthenticated `get_public(MARKET_LIST_PATH)` (`src/breezy/adapters/polymarket_us/provider.py:75`) using the provider's own query shape; candidates via `provider.discovery_candidate_slugs(payload, city_codes)` (`provider.py:180-186`) so the probe and the bot agree on what "a listed weather bucket" is and no second grammar is invented. The `GET /v1/markets` payload carries `bestAskQuote` per market (`docs_snapshots/api-reference_markets_get-markets_2026-08-25.md:381-384`), so listing **and** price come from the same read — no book/BBO call is needed (and the BBO snapshot at `api-reference_order-book_get-best-bidoffer_2026-08-25.md:13-19` is the *institutional* host `api.prod.polymarketexchange.com`, not our gateway; do not call it).

Eligibility, all required, evaluated in memory and never written down:
1. not resolved/closed — reuse `provider._resolved_reason` semantics (`provider.py:250-257`);
2. `bestAskQuote.value ≥ 0.20`;
3. `orderPriceMinTickSize == 0.01` and `minimumTradeQty ≤ 1`;
4. slug parses under `parse_weather_slug`.

Tie-break: **lexicographically smallest eligible slug** — deterministic, reproducible, and expresses no market judgement. Zero eligible → `NO_ELIGIBLE_INSTRUMENT`, no write.

**Why the $0.20 floor.** It is 19 ticks above the $0.01 control, so a fill requires the ask to collapse 19 ticks between the read and the POST milliseconds later, on the thin side of a book whose *bid* side is already known empty (median top-of-book bid 0.3 contracts). It also sits inside the strategy's own `(0.05, 0.95)` ask band, so the control rests on a market of exactly the class we will trade — the probe proves signing on the real surface, not on an oddity. It is a safety floor, not a strategy parameter: raising it only shrinks the candidate set. Constant `_CONTROL_ASK_FLOOR: Final[Decimal] = Decimal("0.20")`.

## Wire shapes

Order body, built **in-function from the chosen slug only** (never a caller-supplied body — the `_signed_post_cancel_all` doctrine at `:386-392` is preserved):

```
{"marketSlug": <slug>, "type": "ORDER_TYPE_LIMIT",
 "price": {"value": "0.01", "currency": "USD"}, "quantity": 1,
 "tif": "TIME_IN_FORCE_GOOD_TILL_CANCEL", "outcomeSide": "OUTCOME_SIDE_YES",
 "action": "ORDER_ACTION_BUY", "manualOrderIndicator": "MANUAL_ORDER_INDICATOR_AUTOMATIC",
 "participateDontInitiate": true}
```

Citations, all from `docs_snapshots/api-reference_orders_create-order_2026-08-25.md`: `CreateOrderRequest` required `marketSlug` (:61-66); `price` is `Amount` = `{value: decimal STRING, currency}` (:144-159, example `'0.55'`); `quantity` is a number in contracts (:73-78); `tif` enum includes `TIME_IN_FORCE_GOOD_TILL_CANCEL` — "remains active until filled or canceled" (:160-174) — this is the resting TIF; `outcomeSide` + `action` are the documented alternative to `intent` (:92-102) and are what the shipped `build_order_body` already uses (`submit_chain.py:266-277`); `manualOrderIndicator` AUTOMATIC per VENUE_FACTS Q6; `participateDontInitiate: true` = "order must rest on the book prior to matching (maker only); order will be rejected if it would immediately match" (:82-86) — a **second, venue-enforced** guarantee that the control cannot execute. `synchronousExecution`/`maxBlockTime` are deliberately omitted (they exist for the IOC block-until-done path). Response: `CreateOrderResponse{id, executions}` (:124-135) — the `id` is what S4 looks for.

Tick/min-size compliance: `$0.01` is exactly one `orderPriceMinTickSize` (`0.01`) and strictly inside `(0.00, 1.00)`; qty `1` ≥ `minimumTradeQty` (`0.01`). Direct evidence: VENUE_FACTS_2026-08-25.md:18 (Q7), :629-637 (`orderPriceMinTickSize: 0.01`, `minimumTradeQty: 0.01` on a live weather bucket), :651. Eligibility check 3 re-asserts both **on the chosen market** rather than trusting the archived capture; a mismatch refuses instead of guessing, and a `400 ORD_REJECT_REASON_INVALID_PRICE_INCREMENT` (:375-386) would classify as `REST_AMBIGUOUS`, not as a signing answer.

Signing: `_sign_write_headers` gains a `path: str` parameter constrained to a module-level `_SIGNABLE_WRITE_PATHS = frozenset({_CANCEL_ALL_PATH, _ORDERS_PATH})` and refuses anything else — the "no arbitrary caller-supplied path, no query" property at `:386-392` survives the widening. Everything else is untouched: same `build_canonical_path_without_query`, same `_load_signing_key`, same three headers (`:365-376`). `PERMITTED_METHODS` and `signing.py` are still read, never copied, never widened.

**Reuse rejected, with reasons:** `write_transport.post_order` — calling it would break B9's exact one-caller pin (`readonly_guard.py:1700-1707`) and put a live write behind the shipped transport while its own verified-flag is still False. `submit_chain.build_order_body` — refuses non-IOC outright (`:225-226`), and `encode_order_body` refuses any key set ≠ `ORDER_BODY_KEYS` (`:65-78`, `:281-282`), which excludes both GTC and `participateDontInitiate`. Reused instead: the canonical-string builder, the key loader, the header names, the read client, the artefact discipline.

## Artefact (schema v2, closed)

New file `PRIVATE_write_sequence_probe[_<stamp>].json`, new title, new closed field set `SEQUENCE_DOCUMENT_FIELDS` (13): `artifact, preflight_status, preflight_reason, selection_reason, rest_status, rest_reason, enumeration_status, enumeration_reason, cancel_status, cancel_response_type, postflight_status, postflight_reason, verdict`. Same `0600`-under-`0700`, `O_EXCL`, deterministic render, round-trip re-verify (`:628-660`). **No slug, no order id, no counts, no lengths, no bodies** — every field is a status, a reason code, a response *type name*, or the computed verdict. `PROBE_DOCUMENT_FIELDS` and its 7-field pins are **untouched**: v2 is an added closed schema, never a loosened one.

## Tests (RED first, `tests/unit/test_polymarket_us_write_sequence.py` + edits)

Driven by a fake read transport + fake write client (the existing `RecordingTransport` / injected `write_client_factory` seams at `:472-473`); zero network.

1. Branch matrix, one test each, asserting artefact fields **and** the exact request count/order: S1 non-200; S1 non-empty; S2 no eligible instrument (no write, no artefact); S3 401 and 403 → `CLOSED_NO`, no S4/S5 issued; S3 200 without id → cleanup path; S3 500 → cleanup path; S4 id absent → `OQB_NO` + cleanup; S4 filled → `CONTROL_FILLED` + cleanup; S5 non-200 → `CANCEL_NOT_OK`, un-flat, exit 2; S6 non-200 and non-empty; happy path → `CLOSED_YES_BOTH_VERBS`, exit 0.
2. Selection: floor boundary (ask exactly 0.20 eligible, 0.19 not); resolved/closed excluded; wrong tick excluded; lexicographic tie-break deterministic across payload orderings.
3. Body shape: exact key set, `price.value == "0.01"` as a **string**, `tif == TIME_IN_FORCE_GOOD_TILL_CANCEL`, `action == ORDER_ACTION_BUY`, `outcomeSide == OUTCOME_SIDE_YES`, `participateDontInitiate is True`; **no `ORDER_ACTION_SELL`/`SELL_SHORT`/`OUTCOME_SIDE_NO` literal anywhere in the file** (AST/source scan).
4. Signing: `_sign_write_headers` refuses a path outside `_SIGNABLE_WRITE_PATHS`; still signs `timestamp+POST+path` with the shipped builder; still never calls `sign_headers`; `PERMITTED_METHODS` unchanged and read-not-copied (extend the existing `:388-451` family).
5. `_signed_post_order` has **no `query` parameter** and takes a slug, never caller bytes (sibling of `:377`, whose existing assertion is re-scoped to `_signed_post_cancel_all` by name rather than weakened).
6. Ordering non-vacuity: AST check that in `run_sequence` the first write is bracketed by a signed GET before and after, and that S5 follows S4 — plus the two planted-defect twins (reordered write; missing post-flight), mirroring `:341-375`.
7. Schema: v2 document closed to exactly 13 fields; missing field refused; artefact is `0600`, carries no verdict *prose*, no slug, no id, no digits beyond statuses; **`PROBE_DOCUMENT_FIELDS` still exactly 7** (pinned in the same file so a v2 edit cannot silently mutate v1).
8. Barriers: `B4_EXEMPT_PATHS == {probe, write_transport}` exactly (unchanged, two members); `named_call_sites("post_order") == {(exec/client.py, _submit_order)}` and `named_call_sites("clear_submit_intent") == {(clear_submit_intent_cli.py, main)}` unchanged; the probe still trips B4 raw (`:931-942`) with the new code present.
9. Isolation: the probe imports **nothing** from `breezy.adapters.polymarket_us.exec.*` (AST import scan) and remains non-importable by the trading process (existing zero-importers pin).
10. stdout/stderr: no body, no id, no slug, no credential fragment on any branch, including the exception hook.
11. Widening (never loosening): `test_full_run_issues_exactly_three_signed_requests` (`:250`) is kept **as-is for the legacy mode** and joined by `test_sequence_issues_exactly_four_signed_and_one_public_request`.

## Build order

1. **C1 (RED)** — the full test module above against the unimplemented `--sequence`; commit the failing output as the artefact.
2. **C2** — `_sign_write_headers(path)` + `_SIGNABLE_WRITE_PATHS`; widened intent marker; **no behaviour change to the legacy path** (its tests stay green untouched).
3. **C3** — selection (`select_control_instrument`), `_signed_post_order`, `run_sequence`, schema v2, `--sequence` CLI, stdout summary. GREEN.
4. **C4** — runbook rewrite: §1–§4 collapse into one bot-driven section, one command, every stop rule from the table above preserved verbatim in operator language; `--positive-control` documented as legacy.
5. **C5 (after the live run, separate commit)** — flip `write_transport.py:48` to `True`, citing in the commit message: `docs/evidence/venue/polymarket_us/PRIVATE_write_sequence_probe_<stamp>.json`, `verdict=CLOSED_YES_BOTH_VERBS`, `rest_status=200`, `cancel_status=<n>`, `postflight_status=200`. C5 lands only on that artefact — never on a green test suite.

Gate at every commit: `scripts/ci/run_tests_no_egress.sh`, passed count never drops.

## Risks

- **Ask collapses between S2 and S3 and the control fills.** Mitigated three ways: the 19-tick floor, `participateDontInitiate: true` (venue rejects rather than matches), and an empty bid side. Residual loss bound unchanged: **$0.01 + fee**. Detected at S4 (`CONTROL_FILLED`) and escalated.
- **`participateDontInitiate` unsupported → 400.** Classified `REST_AMBIGUOUS`, cleanup runs, no signing conclusion drawn, $0 spent. Operator re-runs with `--allow-taker-rest` (flag drops the field) as an explicit, logged decision.
- **S3 ambiguous leaves an order resting.** Cleanup is the same cancel-all the sequence was always going to issue, executed **once**; its failure is `CANCEL_NOT_OK` — a stop, never a retry (runbook §3 rule preserved).
- **Cancel-all cancels an unrelated order.** Impossible by S1: the sequence refuses to start unless the account is provably flat.
- **B4/B9 drift.** Pinned by exact-set assertions plus the existing non-vacuity proofs; no exempt path is added.
- **Schema-pin erosion.** v1's 7-field pin is asserted inside the new module, so a v2 edit that touched it fails immediately.
- **`bestAskQuote` absent on a payload.** Absence is ineligibility, never a default — `NO_ELIGIBLE_INSTRUMENT`, no write.

## Residue

After C4, operator residue is **one command** — `.venv/bin/python scripts/venue/polymarket_us_write_signing_probe.py --sequence [--stamp <token>]` — plus reading its printed verdict. No UI clicks, no hand-placed order, no hand cancel, no manual flatness check, no code edits. Unchanged and out of scope: the operator-only enablement variable, maximum daily budget, and maximum per position (runbook §6) — this sequence assigns none of them and requires none of them, since it never touches the bot's exec path.
