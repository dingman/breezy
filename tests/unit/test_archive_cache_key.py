"""Cache-key identity: one canonical function, hashed once."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from breezy.persistence.archive_cache import ArchiveRequest

REPO_ROOT = Path(__file__).resolve().parents[2]
REQUEST_MODULE = REPO_ROOT / "src" / "breezy" / "persistence" / "archive_request.py"
_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")


def _request(**overrides: Any) -> ArchiveRequest:
    payload: dict[str, Any] = {
        "source": "iem-asos-1min",
        "station": "KNYC",
        "product": "asos-1min",
        "window_start": 1_704_067_200_000_000_000,
        "window_end": 1_735_689_600_000_000_000,
        "model": None,
    }
    payload.update(overrides)
    return ArchiveRequest(**payload)


def test_cache_key_is_stable_across_equal_requests() -> None:
    from breezy.persistence.archive_cache import cache_key, canonical_request_bytes

    first = _request()
    second = _request()

    assert cache_key(first) == cache_key(second)
    assert first.cache_key() == second.cache_key()
    assert canonical_request_bytes(first) == canonical_request_bytes(second)


def test_every_field_change_changes_the_key() -> None:
    from breezy.persistence.archive_cache import cache_key

    baseline = cache_key(_request())
    variants = (
        {"source": "iem-asos-5min"},
        {"station": "KORD"},
        {"product": "tmpf"},
        {"window_start": 1_704_067_200_000_000_001},
        {"window_end": 1_735_689_600_000_000_001},
        {"model": "hrrr"},
    )
    keys = {cache_key(_request(**variant)) for variant in variants}

    assert baseline not in keys
    assert len(keys) == len(variants)


def test_cache_key_is_64_lowercase_hex() -> None:
    from breezy.persistence.archive_cache import cache_key

    key = cache_key(_request())

    assert _HEX64.fullmatch(key) is not None
    assert key == key.lower()


def test_the_request_factory_imports_the_one_key_function_and_never_rehashes() -> None:
    from breezy.persistence.archive_cache import cache_key as cache_key_impl
    from breezy.persistence.archive_request import cache_key as factory_cache_key
    from breezy.persistence.archive_request import iem_asos_1min_request

    tree = ast.parse(REQUEST_MODULE.read_text(encoding="utf-8"), filename=str(REQUEST_MODULE))
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "breezy.persistence.archive_cache":
            imported_names.update(alias.name for alias in node.names)

    hashed_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "hashlib"
                and node.func.attr in {"sha256", "new"}
            )
            or (isinstance(node.func, ast.Name) and node.func.id == "sha256")
        )
    ]

    assert "cache_key" in imported_names
    assert hashed_calls == []
    assert factory_cache_key is cache_key_impl
    assert iem_asos_1min_request("KNYC", 2024).cache_key() == cache_key_impl(
        iem_asos_1min_request("KNYC", 2024)
    )
