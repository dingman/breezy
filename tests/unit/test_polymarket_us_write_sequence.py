"""Offline suite for R-OP-SEQ -- the bot-driven positive-control sequence.

Authority: ``docs/plans/OP_SEQ_BOT_POSITIVE_CONTROL_2026-09-04.md``,
"Converged peer review" section (BINDING).

Every test here is offline: every transport is a double, every credential is
an ephemeral Ed25519 key generated in-process, and nothing can reach a venue
host. Barrier proofs (B4 non-vacuity, D4 zero-importers) live in
``tests/unit/test_polymarket_us_readonly_guard.py`` and
``tests/unit/test_cage_rule_constants_are_pinned.py``; this module pins the
sequence's own behaviour, plus the pure helper's selection/body/schema/verdict
logic.
"""

from __future__ import annotations

import ast
import base64
import importlib.util
import json
import stat
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from nacl.signing import SigningKey

from breezy.adapters.polymarket_us.credentials import PolymarketUSCredentials
from breezy.adapters.polymarket_us.exec.submit_chain import ORDER_BODY_KEYS
from breezy.adapters.polymarket_us.secure import RedactedSecureString
from breezy.adapters.polymarket_us.transport import VenueResponse

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "venue" / "polymarket_us_write_signing_probe.py"
HELPER_PATH = REPO_ROOT / "scripts" / "venue" / "_write_sequence.py"
RAW = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"

_API_BASE = "https://api.example.invalid"
_GATEWAY_BASE = "https://gateway.example.invalid"
_KEY_ID = "11111111-2222-3333-4444-555555555555"
_CITY_CODES = ("nyc",)


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def helper() -> ModuleType:
    return _load(HELPER_PATH, "breezy_write_sequence_helper")


@pytest.fixture(scope="module")
def probe(helper: ModuleType) -> ModuleType:
    return _load(SCRIPT_PATH, "breezy_polymarket_us_write_sequence_probe")


# --------------------------------------------------------------------------
# Market payload fixtures
# --------------------------------------------------------------------------


def _raw_market(name: str = "market_open_510636_by_slug.json") -> dict[str, Any]:
    payload = json.loads((RAW / name).read_text(encoding="utf-8"))
    market = payload["market"]
    assert isinstance(market, dict)
    return market


def eligible_market(slug: str = "tc-temp-nychigh-2026-08-25-lt79f") -> dict[str, Any]:
    market = _raw_market()
    market["slug"] = slug
    for side in market["marketSides"]:
        side["identifier"] = slug
    market["bestAskQuote"] = {"value": "0.5400", "currency": "USD"}
    market["orderPriceMinTickSize"] = 0.01
    market["minimumTradeQty"] = 0.01
    market["archived"] = False
    market["closed"] = False
    market["status"] = "MARKET_STATUS_OPEN"
    return market


def market_page(*markets: dict[str, Any]) -> dict[str, Any]:
    return {"markets": list(markets)}


# --------------------------------------------------------------------------
# Doubles
# --------------------------------------------------------------------------


class _QueuedReadTransport:
    """A ``PolymarketUSReadTransport`` double answering from a fixed queue."""

    def __init__(self, responses: list[VenueResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    async def get(self, url: str, *, headers: Any, quota_key: str) -> VenueResponse:
        self.calls.append(url)
        return self._responses.pop(0)


class _QueuedWriteClient:
    """A raw-pyo3-``HttpClient`` double answering ``post`` from a fixed queue."""

    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def post(self, url: str, *, headers: Any, body: bytes, keys: list[str]) -> Any:
        self.calls.append({"url": url, "headers": dict(headers), "body": body, "keys": list(keys)})
        return self._responses.pop(0)


def _credentials() -> PolymarketUSCredentials:
    secret = base64.b64encode(bytes(SigningKey.generate())).decode("ascii")
    return PolymarketUSCredentials(
        key_id=RedactedSecureString(_KEY_ID),
        secret_key=RedactedSecureString(secret),
    )


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        api_base_url=_API_BASE,
        gateway_base_url=_GATEWAY_BASE,
        signing_variant="path_only",
        http_timeout_secs=10.0,
        global_requests_per_second=15,
        instrument_requests_per_minute=6,
        book_requests_per_minute=12,
        user_agent="breezy-test",
    )


def _prepared(probe: ModuleType) -> Any:
    return probe.Prepared(core_limit=(0, 0), config=_config(), credentials=_credentials())


async def _run(
    probe: ModuleType,
    *,
    read_responses: list[VenueResponse],
    write_responses: list[SimpleNamespace],
    tmp_path: Path,
    stamp: str | None = None,
    sleeps: list[float] | None = None,
) -> tuple[Any, _QueuedReadTransport, _QueuedWriteClient]:
    read_transport = _QueuedReadTransport(read_responses)
    write_client = _QueuedWriteClient(write_responses)
    sleep_log = sleeps if sleeps is not None else []

    async def _sleep(seconds: float) -> None:
        sleep_log.append(seconds)

    observation = await probe.run_sequence(
        directory=tmp_path,
        stamp=stamp,
        prepare_fn=lambda env=None, *, guard=None: _prepared(probe),
        read_transport_factory=lambda config: read_transport,
        write_client_factory=lambda config: write_client,
        sleep=_sleep,
    )
    return observation, read_transport, write_client


def _order_response(status: int, order_id: str | None) -> SimpleNamespace:
    body: dict[str, Any] = {"executions": []}
    if order_id is not None:
        body["id"] = order_id
    return SimpleNamespace(status=status, body=json.dumps(body).encode("utf-8"))


def _cancel_response(status: int = 200) -> SimpleNamespace:
    return SimpleNamespace(status=status, body=b'{"canceledOrderIds": []}')


def _open_orders(status: int, orders: list[dict[str, Any]]) -> VenueResponse:
    return VenueResponse(status=status, headers={}, body=json.dumps({"orders": orders}).encode())


def _market_list_response(*markets: dict[str, Any], status: int = 200) -> VenueResponse:
    return VenueResponse(status=status, headers={}, body=json.dumps(market_page(*markets)).encode())


def _resting_order(order_id: str) -> dict[str, Any]:
    return {"id": order_id, "cumQuantity": 0, "state": "ORDER_STATE_NEW"}


def _filled_order(order_id: str) -> dict[str, Any]:
    return {"id": order_id, "cumQuantity": 1, "state": "ORDER_STATE_FILLED"}


# ==========================================================================
# Branch matrix (Tests list item 1)
# ==========================================================================


@pytest.mark.asyncio
async def test_s1_non_200_preflight_stops_with_no_writes(probe: ModuleType, tmp_path: Path) -> None:
    observation, read, write = await _run(
        probe,
        read_responses=[VenueResponse(status=503, headers={}, body=b"")],
        write_responses=[],
        tmp_path=tmp_path,
    )
    assert observation.preflight_reason == probe.PREFLIGHT_NOT_200
    assert observation.verdict == probe.INCONCLUSIVE
    assert len(read.calls) == 1
    assert write.calls == []


@pytest.mark.asyncio
async def test_s1_non_empty_preflight_stops_with_no_writes(
    probe: ModuleType, tmp_path: Path
) -> None:
    observation, _read, write = await _run(
        probe,
        read_responses=[_open_orders(200, [{"id": "x"}])],
        write_responses=[],
        tmp_path=tmp_path,
    )
    assert observation.preflight_reason == probe.PREFLIGHT_NOT_EMPTY
    assert observation.verdict == probe.INCONCLUSIVE
    assert write.calls == []


@pytest.mark.asyncio
async def test_s2_no_eligible_instrument_refuses_without_an_artefact(
    probe: ModuleType, tmp_path: Path
) -> None:
    read_transport = _QueuedReadTransport(
        [_open_orders(200, []), _market_list_response()]
    )
    write_client = _QueuedWriteClient([])
    with pytest.raises(probe.ProbeRefusal) as excinfo:
        await probe.run_sequence(
            directory=tmp_path,
            prepare_fn=lambda env=None, *, guard=None: _prepared(probe),
            read_transport_factory=lambda config: read_transport,
            write_client_factory=lambda config: write_client,
        )
    assert probe.NO_ELIGIBLE_INSTRUMENT in str(excinfo.value)
    assert write_client.calls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_s3_401_is_closed_no_with_no_s4_s5_and_an_artefact(
    probe: ModuleType, tmp_path: Path
) -> None:
    observation, _read, write = await _run(
        probe,
        read_responses=[
            _open_orders(200, []),
            _market_list_response(eligible_market()),
        ],
        write_responses=[SimpleNamespace(status=401, body=b"{}")],
        tmp_path=tmp_path,
    )
    assert observation.rest_status == 401
    assert observation.rest_reason == probe.REST_UNAUTHORIZED
    assert observation.verdict == probe.CLOSED_NO
    assert len(write.calls) == 1
    path = probe.write_sequence_artifact(observation, directory=tmp_path, stamp="401")
    assert path.exists()


@pytest.mark.asyncio
async def test_s3_403_is_also_closed_no(probe: ModuleType, tmp_path: Path) -> None:
    observation, _read, write = await _run(
        probe,
        read_responses=[
            _open_orders(200, []),
            _market_list_response(eligible_market()),
        ],
        write_responses=[SimpleNamespace(status=403, body=b"{}")],
        tmp_path=tmp_path,
    )
    assert observation.verdict == probe.CLOSED_NO
    assert len(write.calls) == 1


@pytest.mark.asyncio
async def test_s3_200_without_id_is_ambiguous_and_cleans_up(
    probe: ModuleType, tmp_path: Path
) -> None:
    observation, _read, write = await _run(
        probe,
        read_responses=[
            _open_orders(200, []),
            _market_list_response(eligible_market()),
            _open_orders(200, []),
        ],
        write_responses=[_order_response(200, None), _cancel_response(200)],
        tmp_path=tmp_path,
    )
    assert observation.rest_reason == probe.REST_AMBIGUOUS
    assert observation.verdict == probe.INCONCLUSIVE
    assert len(write.calls) == 2  # order POST + cleanup cancel-all, S4 skipped


@pytest.mark.asyncio
async def test_s3_500_is_also_ambiguous_and_cleans_up(probe: ModuleType, tmp_path: Path) -> None:
    observation, _read, write = await _run(
        probe,
        read_responses=[
            _open_orders(200, []),
            _market_list_response(eligible_market()),
            _open_orders(200, []),
        ],
        write_responses=[SimpleNamespace(status=500, body=b"{}"), _cancel_response(200)],
        tmp_path=tmp_path,
    )
    assert observation.rest_reason == probe.REST_AMBIGUOUS
    assert len(write.calls) == 2


@pytest.mark.asyncio
async def test_s4_id_absent_is_oqb_no_after_one_retry_then_cleans_up(
    probe: ModuleType, tmp_path: Path
) -> None:
    sleeps: list[float] = []
    observation, _read, write = await _run(
        probe,
        read_responses=[
            _open_orders(200, []),
            _market_list_response(eligible_market()),
            _open_orders(200, []),  # S4 first read: absent
            _open_orders(200, []),  # S4 retry: still absent
            _open_orders(200, []),  # S6 postflight
        ],
        write_responses=[_order_response(200, "order-1"), _cancel_response(200)],
        tmp_path=tmp_path,
        sleeps=sleeps,
    )
    assert observation.enumeration_reason == probe.OQB_NO
    assert observation.verdict == probe.INCONCLUSIVE
    assert sleeps == [0.25]
    assert len(write.calls) == 2


@pytest.mark.asyncio
async def test_s4_filled_is_control_filled_and_cleans_up(probe: ModuleType, tmp_path: Path) -> None:
    observation, _read, _write = await _run(
        probe,
        read_responses=[
            _open_orders(200, []),
            _market_list_response(eligible_market()),
            _open_orders(200, [_filled_order("order-1")]),
            _open_orders(200, []),  # S6 postflight
        ],
        write_responses=[_order_response(200, "order-1"), _cancel_response(200)],
        tmp_path=tmp_path,
    )
    assert observation.enumeration_reason == probe.CONTROL_FILLED
    assert observation.verdict == probe.INCONCLUSIVE


@pytest.mark.asyncio
async def test_s5_non_200_is_cancel_not_ok_and_leaves_verdict_inconclusive(
    probe: ModuleType, tmp_path: Path
) -> None:
    observation, _read, _write = await _run(
        probe,
        read_responses=[
            _open_orders(200, []),
            _market_list_response(eligible_market()),
            _open_orders(200, [_resting_order("order-1")]),
            _open_orders(200, []),
        ],
        write_responses=[
            _order_response(200, "order-1"),
            SimpleNamespace(status=500, body=b"not json"),
        ],
        tmp_path=tmp_path,
    )
    assert observation.cancel_status == 500
    assert observation.verdict == probe.INCONCLUSIVE


@pytest.mark.asyncio
async def test_s6_non_200_postflight_is_recorded(probe: ModuleType, tmp_path: Path) -> None:
    observation, _read, _write = await _run(
        probe,
        read_responses=[
            _open_orders(200, []),
            _market_list_response(eligible_market()),
            _open_orders(200, [_resting_order("order-1")]),
            VenueResponse(status=500, headers={}, body=b""),
        ],
        write_responses=[_order_response(200, "order-1"), _cancel_response(200)],
        tmp_path=tmp_path,
    )
    assert observation.postflight_reason == probe.POSTFLIGHT_NOT_200
    assert observation.verdict == probe.INCONCLUSIVE


@pytest.mark.asyncio
async def test_s6_non_empty_postflight_is_recorded(probe: ModuleType, tmp_path: Path) -> None:
    observation, _read, _write = await _run(
        probe,
        read_responses=[
            _open_orders(200, []),
            _market_list_response(eligible_market()),
            _open_orders(200, [_resting_order("order-1")]),
            _open_orders(200, [{"id": "leftover"}]),
        ],
        write_responses=[_order_response(200, "order-1"), _cancel_response(200)],
        tmp_path=tmp_path,
    )
    assert observation.postflight_reason == probe.POSTFLIGHT_NOT_EMPTY
    assert observation.verdict == probe.INCONCLUSIVE


@pytest.mark.asyncio
async def test_happy_path_is_closed_yes_both_verbs_exit_0(
    probe: ModuleType, tmp_path: Path
) -> None:
    observation, _read, _write = await _run(
        probe,
        read_responses=[
            _open_orders(200, []),
            _market_list_response(eligible_market()),
            _open_orders(200, [_resting_order("order-1")]),
            _open_orders(200, []),
        ],
        write_responses=[_order_response(200, "order-1"), _cancel_response(200)],
        tmp_path=tmp_path,
    )
    assert observation.verdict == probe.CLOSED_YES_BOTH_VERBS
    path = probe.write_sequence_artifact(observation, directory=tmp_path, stamp="happy")
    assert set(json.loads(path.read_text())) == probe.SEQUENCE_DOCUMENT_FIELDS


# ==========================================================================
# Selection (Tests list item 2)
# ==========================================================================


def test_selection_floor_boundary_020_eligible_019_not(helper: ModuleType) -> None:
    at_floor = eligible_market()
    at_floor["bestAskQuote"] = {"value": "0.20", "currency": "USD"}
    result = helper.select_control_instrument(market_page(at_floor), city_codes=_CITY_CODES)
    assert result == at_floor["slug"]

    below_floor = eligible_market()
    below_floor["bestAskQuote"] = {"value": "0.19", "currency": "USD"}
    result = helper.select_control_instrument(market_page(below_floor), city_codes=_CITY_CODES)
    assert result is None


def test_selection_excludes_resolved_or_closed(helper: ModuleType) -> None:
    closed = eligible_market()
    closed["closed"] = True
    assert helper.select_control_instrument(market_page(closed), city_codes=_CITY_CODES) is None


def test_selection_excludes_wrong_tick(helper: ModuleType) -> None:
    wrong_tick = eligible_market()
    wrong_tick["orderPriceMinTickSize"] = 0.05
    assert helper.select_control_instrument(market_page(wrong_tick), city_codes=_CITY_CODES) is None


def test_selection_lexicographic_tie_break_is_order_independent(helper: ModuleType) -> None:
    first = eligible_market("tc-temp-nychigh-2026-08-25-lt79f")
    second = eligible_market("tc-temp-nychigh-2026-08-25-lt80f")
    assert (
        helper.select_control_instrument(market_page(first, second), city_codes=_CITY_CODES)
        == helper.select_control_instrument(market_page(second, first), city_codes=_CITY_CODES)
        == "tc-temp-nychigh-2026-08-25-lt79f"
    )


def test_selection_venue_payload_error_is_no_eligible_never_a_crash(helper: ModuleType) -> None:
    broken = {"markets": "not-a-list"}
    assert helper.select_control_instrument(broken, city_codes=_CITY_CODES) is None


# ==========================================================================
# Body shape (Tests list item 3)
# ==========================================================================


def test_control_body_exact_key_set_and_shape(helper: ModuleType) -> None:
    body = helper.build_control_order_body("some-slug")
    expected_keys = (ORDER_BODY_KEYS - {"synchronousExecution", "maxBlockTime"}) | {
        "participateDontInitiate"
    }
    assert set(body) == expected_keys
    assert body["price"]["value"] == "0.01"
    assert isinstance(body["price"]["value"], str)
    assert body["tif"] == "TIME_IN_FORCE_GOOD_TILL_CANCEL"
    assert body["action"] == "ORDER_ACTION_BUY"
    assert body["outcomeSide"] == "OUTCOME_SIDE_YES"
    assert body["participateDontInitiate"] is True


def test_no_sell_or_short_or_outcome_side_no_literal_anywhere(
    helper: ModuleType, probe: ModuleType
) -> None:
    for path in (HELPER_PATH, SCRIPT_PATH):
        source = path.read_text(encoding="utf-8")
        for forbidden in ("ORDER_ACTION_SELL", "SELL_SHORT", "OUTCOME_SIDE_NO"):
            assert forbidden not in source, f"{forbidden} found in {path}"


# ==========================================================================
# Signing (Tests list item 4-5)
# ==========================================================================


def test_sign_write_headers_refuses_a_path_outside_signable_set(probe: ModuleType) -> None:
    from nautilus_trader.common.component import TestClock

    credentials = _credentials()
    clock = TestClock()
    clock.set_time(1_700_000_000_000 * 1_000_000)
    signer = probe.Ed25519RequestSigner.for_variant(credentials, clock=clock)
    with pytest.raises(ValueError):
        probe._sign_write_headers(credentials, signer, clock, path="/v1/orders/open")


def test_signed_post_order_has_no_query_parameter(probe: ModuleType) -> None:
    import inspect

    params = set(inspect.signature(probe._signed_post_order).parameters)
    assert "query" not in params
    assert "slug" in params


@pytest.mark.asyncio
async def test_signed_post_url_ends_with_the_signed_path_for_both_writes(probe: ModuleType) -> None:
    credentials = _credentials()
    from nautilus_trader.common.component import TestClock

    clock = TestClock()
    clock.set_time(1_700_000_000_000 * 1_000_000)
    signer = probe.Ed25519RequestSigner.for_variant(credentials, clock=clock)

    order_client = _QueuedWriteClient([_order_response(200, "id-1")])
    await probe._signed_post_order(
        order_client, _API_BASE, credentials, signer, clock, slug="a-slug"
    )
    assert order_client.calls[0]["url"].endswith(probe._ORDERS_PATH)

    cancel_client = _QueuedWriteClient([_cancel_response(200)])
    await probe._signed_post_cancel_all(cancel_client, _API_BASE, credentials, signer, clock)
    assert cancel_client.calls[0]["url"].endswith(probe._CANCEL_ALL_PATH)


# ==========================================================================
# Schema (Tests list item 7)
# ==========================================================================


def test_v2_schema_closed_to_exactly_13_fields(helper: ModuleType) -> None:
    assert len(helper.SEQUENCE_DOCUMENT_FIELDS) == 13


def test_v1_schema_still_exactly_7_fields(helper: ModuleType) -> None:
    assert len(helper.PROBE_DOCUMENT_FIELDS) == 7


def test_missing_field_in_v2_document_is_refused(helper: ModuleType) -> None:
    observation = helper.SequenceObservation(
        preflight_status=200,
        preflight_reason=None,
        selection_reason=None,
        rest_status=200,
        rest_reason=None,
        enumeration_status=200,
        enumeration_reason=None,
        cancel_status=200,
        cancel_response_type="dict",
        postflight_status=200,
        postflight_reason=None,
        verdict=helper.CLOSED_YES_BOTH_VERBS,
    )
    document = helper.sequence_document(observation)
    document.pop("verdict")
    assert set(document) != helper.SEQUENCE_DOCUMENT_FIELDS


@pytest.mark.asyncio
async def test_artifact_is_0600_carries_no_slug_no_id_and_a_sha256_sidecar(
    probe: ModuleType, tmp_path: Path
) -> None:
    observation, _read, _write = await _run(
        probe,
        read_responses=[
            _open_orders(200, []),
            _market_list_response(eligible_market()),
            _open_orders(200, [_resting_order("order-1")]),
            _open_orders(200, []),
        ],
        write_responses=[_order_response(200, "order-1"), _cancel_response(200)],
        tmp_path=tmp_path,
        stamp="sidecar",
    )
    path = probe.write_sequence_artifact(observation, directory=tmp_path, stamp="sidecar")
    text = path.read_text(encoding="utf-8")
    assert "order-1" not in text
    assert eligible_market()["slug"] not in text
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600
    sidecar = path.with_name(path.name + ".sha256")
    assert sidecar.exists()
    assert path.name in sidecar.read_text(encoding="utf-8")


# ==========================================================================
# Isolation (Tests list item 9)
# ==========================================================================


def test_probe_imports_nothing_from_exec_package(probe: ModuleType) -> None:
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"), filename=str(SCRIPT_PATH))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "exec" not in node.module.split("."), node.module
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "exec" not in alias.name.split("."), alias.name


# ==========================================================================
# stdout (Tests list item 10)
# ==========================================================================


def test_stdout_never_leaks_slug_id_or_credential(
    probe: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    argv = ["--sequence", "--evidence-dir", str(tmp_path), "--stamp", "stdout"]

    async def _fake_run_sequence(**kwargs: Any) -> Any:
        return probe.SequenceObservation(
            preflight_status=200,
            preflight_reason=None,
            selection_reason=None,
            rest_status=200,
            rest_reason=None,
            enumeration_status=200,
            enumeration_reason=None,
            cancel_status=200,
            cancel_response_type="dict",
            postflight_status=200,
            postflight_reason=None,
            verdict=probe.CLOSED_YES_BOTH_VERBS,
        )

    monkeypatch.setattr(probe, "run_sequence", _fake_run_sequence)
    code = probe.main(argv)
    assert code == 0
    out = capsys.readouterr().out
    for forbidden in (eligible_market()["slug"], "order-1", _KEY_ID):
        assert forbidden not in out


# ==========================================================================
# Exception path (plan item 10, Converged peer review) -- describe_exception
# must never let a secret-shaped fragment through ``main``'s except clauses.
# ==========================================================================

_LEAK_HEX_KEY = "a1b2c3d4e5f60718293a4b5c6d7e8f90112233445566778899aabbccddeeff"
_LEAK_HEADER_LINE = "X-PM-ACCESS-KEY: 11111111-2222-3333-4444-555555555555"
_LEAK_ORDER_ID = "order-9f3d2b1c"
_LEAK_SLUG = "tc-temp-laxhigh-2026-09-04-gte84f"
_LEAK_BODY_FRAGMENT = '{"price": "0.01", "size": "1", "side": "BUY"}'

_LEAK_FRAGMENTS = (
    _LEAK_HEX_KEY,
    _LEAK_HEADER_LINE,
    _LEAK_ORDER_ID,
    _LEAK_SLUG,
    _LEAK_BODY_FRAGMENT,
)


def _leaky_message() -> str:
    return (
        "synthetic failure carrying "
        f"{_LEAK_HEX_KEY} {_LEAK_HEADER_LINE} {_LEAK_ORDER_ID} "
        f"{_LEAK_SLUG} {_LEAK_BODY_FRAGMENT}"
    )


@pytest.mark.parametrize(
    ("exc_attr", "prefix"),
    [
        ("ProbeRefusal", "REFUSED:"),
        ("ArtifactSchemaError", "REFUSED:"),
        ("PolymarketUSError", "CONFIGURATION ERROR:"),
        ("ValueError", "REFUSED:"),
        ("FileExistsError", "REFUSED:"),
    ],
)
def test_run_sequence_exception_never_leaks_secret_shaped_fragments(
    probe: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    exc_attr: str,
    prefix: str,
) -> None:
    """Every taxonomy branch ``main`` catches (docs/plans/OP_SEQ..., item 10):
    ``run_sequence`` is armed to raise each caught type carrying synthetic
    secret-shaped fragments (a fake 64-hex key, an ``X-PM-`` header line, an
    order-id-looking token, a weather slug, and a JSON body fragment). None of
    that material -- and no traceback -- may reach stdout or stderr, and the
    documented ``REFUSED:``/``CONFIGURATION ERROR:`` prefix and non-zero exit
    code must still be produced.

    ``_fake_run_sequence`` arms ``kwargs["guard"]`` before raising -- the same
    order real ``run_sequence``/``prepare`` use (credential read begins near
    the top of the call, so essentially every downstream raise happens after
    the arm), rather than leaving the double free to raise from a state real
    code never reaches."""
    argv = ["--sequence", "--evidence-dir", str(tmp_path), "--stamp", "exc"]
    exception_types: dict[str, type[BaseException]] = {
        "ProbeRefusal": probe.ProbeRefusal,
        "ArtifactSchemaError": probe.ArtifactSchemaError,
        "PolymarketUSError": probe.PolymarketUSError,
        "ValueError": ValueError,
        "FileExistsError": FileExistsError,
    }
    exc_type = exception_types[exc_attr]
    message = _leaky_message()

    async def _fake_run_sequence(**kwargs: Any) -> Any:
        kwargs["guard"].mark_credential_read_begun()
        raise exc_type(message)

    monkeypatch.setattr(probe, "run_sequence", _fake_run_sequence)
    code = probe.main(argv)
    assert code == 2

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    for fragment in _LEAK_FRAGMENTS:
        assert fragment not in combined
    assert "Traceback" not in combined
    assert prefix in captured.err


def test_run_sequence_base_exception_after_credential_read_propagates(
    probe: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``BaseException`` that is not an ``Exception`` (e.g. a keyboard
    interrupt arriving mid-sequence, after the intent marker and the
    credential read) is not one of ``_run_refusable``'s narrow excepts and
    propagates uncaught -- matching the module's documented "Narrow excepts
    only" stance for ``asyncio.CancelledError``. This is the safe behaviour:
    nothing forces a print of its message."""
    argv = ["--sequence", "--evidence-dir", str(tmp_path), "--stamp", "base-exc"]

    async def _fake_run_sequence(**kwargs: Any) -> Any:
        kwargs["guard"].mark_credential_read_begun()
        raise KeyboardInterrupt("interrupted mid-sequence, after credential read")

    monkeypatch.setattr(probe, "run_sequence", _fake_run_sequence)
    with pytest.raises(KeyboardInterrupt):
        probe.main(argv)


# ==========================================================================
# Widening (Tests list item 11) -- kept: legacy exactly-three-signed pin
# ==========================================================================


@pytest.mark.asyncio
async def test_sequence_happy_path_signed_and_public_request_counts(
    probe: ModuleType, tmp_path: Path
) -> None:
    observation, read, write = await _run(
        probe,
        read_responses=[
            _open_orders(200, []),
            _market_list_response(eligible_market()),
            _open_orders(200, [_resting_order("order-1")]),
            _open_orders(200, []),
        ],
        write_responses=[_order_response(200, "order-1"), _cancel_response(200)],
        tmp_path=tmp_path,
    )
    assert observation.verdict == probe.CLOSED_YES_BOTH_VERBS
    # S1 + S2(public) + S4 + S6 = 4 reads through the read transport; S3 + S5 = 2 writes.
    assert len(read.calls) == 4
    assert len(write.calls) == 2
