"""AUT-1 WP5-A (V-15): the adapter-free ``domain.exec_intent`` module.

``intent_fingerprint`` moved byte-identically out of the venue adapter's
``submit_chain`` (which keeps a re-export shim), and the exec-store key
prefixes the audit reads are restated adapter-free. The prefixes are pinned
equal to the byte-pinned exec client's constants here (a test-only import).
"""

from __future__ import annotations

import ast
import hashlib
import random
from pathlib import Path
from types import SimpleNamespace

import pytest

from breezy.adapters.polymarket_us import operator_controls
from breezy.adapters.polymarket_us.exec import client, submit_chain
from breezy.domain import exec_intent

_PREFIX_NAMES = (
    "STATE_KEY_NAMESPACE",
    "VENUE_ORDER_ID_KEY_PREFIX",
    "FILL_KEY_PREFIX",
    "FILL_INDEX_KEY_PREFIX",
    "FILL_BY_DAY_KEY_PREFIX",
    "FILL_BY_FINGERPRINT_KEY_PREFIX",
    "RESOLVER_CONTEXT_KEY_PREFIX",
)


def _original_intent_fingerprint(order: object) -> str:
    """Verbatim copy of the adapter's pre-move function (the oracle)."""
    payload = "\n".join(
        (
            str(getattr(order, "instrument_id", "")),
            str(getattr(order, "side", "")),
            str(getattr(order, "quantity", "")),
            str(getattr(order, "price", "")),
            str(getattr(order, "time_in_force", "")),
            str(getattr(order, "client_order_id", "")),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_exec_key_prefixes_equal_client_constants() -> None:
    for name in _PREFIX_NAMES:
        assert getattr(exec_intent, name) == getattr(client, name), name
    assert exec_intent.STATE_KEY_NAMESPACE == "exec/polymarket_us/"


def test_intent_fingerprint_shim_is_the_domain_function() -> None:
    assert submit_chain.intent_fingerprint is exec_intent.intent_fingerprint


def test_exec_intent_imports_no_adapter_module() -> None:
    tree = ast.parse(Path(exec_intent.__file__).read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert not [m for m in imported if m.startswith(("breezy.adapters", "nautilus_trader"))]


def test_intent_fingerprint_equals_original_over_1000_random_orders() -> None:
    rng = random.Random(20261004)
    for _ in range(1000):
        fields = {
            name: rng.choice(
                ["", "A.B", "BUY", "SELL", "0.55", "10", "GTC", "IOC", "O-é-1", "x\ny"]
            )
            + str(rng.randint(0, 10**6))
            for name in (
                "instrument_id",
                "side",
                "quantity",
                "price",
                "time_in_force",
                "client_order_id",
            )
        }
        for dropped in rng.sample(sorted(fields), rng.randint(0, 2)):
            del fields[dropped]
        order = SimpleNamespace(**fields)
        expected = _original_intent_fingerprint(order)
        assert exec_intent.intent_fingerprint(order) == expected
        assert submit_chain.intent_fingerprint(order) == expected


def test_intent_fingerprint_of_bare_object_matches_original() -> None:
    assert exec_intent.intent_fingerprint(object()) == _original_intent_fingerprint(object())


# -- utc_day_for_ns (AUT-1 WP5 stage 2a, S2-R14): a duplicate of the adapter's day derivation --

_CLIENT_SOURCE = Path(client.__file__).read_text(encoding="utf-8")
_DAY_BOUNDARIES_NS = (
    1,
    999_999_999,
    1_000_000_000,
    86_399_999_999_999,
    86_400_000_000_000,
    86_400_000_000_001,
    1_790_972_432_790_092_624,  # 2026-10-02T20:20:32Z
    1_791_071_999_999_999_999,  # 2026-10-03T23:59:59.999999999Z
    1_791_072_000_000_000_000,  # 2026-10-04T00:00:00Z
    4_102_444_800_000_000_000,  # 2100-01-01
)


@pytest.mark.parametrize("now_ns", _DAY_BOUNDARIES_NS)
def test_utc_day_for_ns_equals_the_adapter_derivation(now_ns: int) -> None:
    assert exec_intent.utc_day_for_ns(now_ns) == operator_controls.utc_day_for_ns(now_ns)


def test_utc_day_for_ns_equals_the_adapter_over_random_instants() -> None:
    rng = random.Random(20261004)
    for _ in range(2000):
        now_ns = rng.randint(1, 4_102_444_800_000_000_000)
        assert exec_intent.utc_day_for_ns(now_ns) == operator_controls.utc_day_for_ns(now_ns)


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, "1", None])
def test_utc_day_for_ns_refuses_what_the_adapter_refuses(bad: object) -> None:
    with pytest.raises(Exception):  # noqa: B017 - the oracle's error type is adapter-only
        operator_controls.utc_day_for_ns(bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="now_ns"):
        exec_intent.utc_day_for_ns(bad)  # type: ignore[arg-type]


def _utc_day_call_arguments(source: str) -> list[str]:
    """The unparsed first argument of every ``utc_day_for_ns(...)`` call, in source order."""
    return [
        ast.unparse(node.args[0])
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "utc_day_for_ns"
        and node.args
    ]


def test_the_exec_client_derives_the_fingerprint_day_from_intent_created_ns() -> None:
    """The audit's leg I recomputes ``fill_by_fingerprint/<day>:<fp>`` with ``intent_created_ns``
    as the day input (``client.py``), and the day index with the fill's own ``ts_event``. Pin both
    inputs: a client edit that swaps them would silently skew the audit's keys."""
    arguments = _utc_day_call_arguments(_CLIENT_SOURCE)
    assert "intent_created_ns" in arguments
    assert "record.ts_event" in arguments
    lines = _CLIENT_SOURCE.splitlines()
    key_line = next(
        i for i, ln in enumerate(lines) if "day = utc_day_for_ns(intent_created_ns)" in ln
    )
    assert "FILL_BY_FINGERPRINT_KEY_PREFIX" in "\n".join(lines[key_line : key_line + 4])


def test_utc_day_for_ns_imports_no_adapter_module() -> None:
    tree = ast.parse(Path(exec_intent.__file__).read_text(encoding="utf-8"))
    imported = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not [m for m in imported if m.startswith("breezy.adapters")]
