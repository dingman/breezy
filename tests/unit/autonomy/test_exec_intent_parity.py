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
