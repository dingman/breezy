"""Offline defeat-resistance suite for the value-free venue shape capturer.

Authority: EXEC SPINE R-1 security preconditions. R-1 captures the *shapes* of
``/v1/portfolio/positions``, ``/v1/account/balances`` and ``/v1/orders/open``
— i.e. the operator's real financial position — into a repository-adjacent
artefact. Two independently verified facts make that dangerous:

1. ``docs/evidence/venue/polymarket_us/`` is GIT-TRACKED. File mode ``0600``
   is no defence against ``git add``; only an ignore rule is.
2. The existing leak check cannot see money. ``write_evidence``
   (``scripts/venue/polymarket_us_auth_smoke.py:714-722``) calls
   ``find_secret_leak_offsets(text, secret_values)``, which scans ONLY for the
   supplied credential strings. A balance passes it unimpeded.

So every assertion in this file is deliberately independent of
``find_secret_leak_offsets``. The suite is written to be *defeat-resistant*:
a naive "no sentinel value in the output" test is defeated by a payload that
carries the secret in its KEYS (a slug-keyed positions map publishes the
operator's portfolio as field names), and by any encoding that discloses
magnitude without reproducing the value (digit counts, exponents, string
lengths). Both cases are tested here in their own right.

The strongest statement available is value-INVARIANCE: two payloads that
differ only in their scalar values must render byte-identical artefacts. That
is asserted concretely (a $1.00 balance vs a $987,654,321.05 balance) and
generatively (Hypothesis mutates every scalar in a random payload).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "venue" / "polymarket_us_shape_capture.py"
SDK_SNAPSHOT = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "sdk_snapshot"


def _load_shape_capture_module() -> ModuleType:
    """Load the capturer the way the repo loads its other venue scripts.

    It is a ``scripts/venue/`` module rather than a ``breezy`` package module
    on purpose: it writes into ``docs/evidence/``, and
    ``test_probe_containment.py::test_no_module_under_src_reads_docs_evidence``
    bans that path as a runtime constant under ``src/``.
    """
    spec = importlib.util.spec_from_file_location("breezy_polymarket_us_shape_capture", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


shape_capture = _load_shape_capture_module()

MAX_SHAPE_DEPTH: int = shape_capture.MAX_SHAPE_DEPTH
PRIVATE_ARTIFACT_PREFIX: str = shape_capture.PRIVATE_ARTIFACT_PREFIX
PRIVATE_SHAPE_DIRECTORY: Path = shape_capture.PRIVATE_SHAPE_DIRECTORY
SHAPE_ALLOWED_KEYS: frozenset[str] = shape_capture.SHAPE_ALLOWED_KEYS
SHAPE_DIR_MODE: int = shape_capture.SHAPE_DIR_MODE
SHAPE_FILE_MODE: int = shape_capture.SHAPE_FILE_MODE
ShapeLeakError: type[Exception] = shape_capture.ShapeLeakError


def describe_shape(payload: object) -> dict[str, Any]:
    return cast(dict[str, Any], shape_capture.describe_shape(payload))


def render_shape_report(*, endpoint: str, shape: dict[str, Any]) -> str:
    return cast(str, shape_capture.render_shape_report(endpoint=endpoint, shape=shape))


def verify_value_free(shape: dict[str, Any]) -> None:
    shape_capture.verify_value_free(shape)


def shape_artifact_filename(endpoint: str) -> str:
    return cast(str, shape_capture.shape_artifact_filename(endpoint))


def write_shape_artifact(*, endpoint: str, payload: object, directory: Path) -> Path:
    return cast(
        Path,
        shape_capture.write_shape_artifact(endpoint=endpoint, payload=payload, directory=directory),
    )


BALANCES_PATH = "/v1/account/balances"
POSITIONS_PATH = "/v1/portfolio/positions"
OPEN_ORDERS_PATH = "/v1/orders/open"

#: Distinctive scalars planted in fixture VALUES. Chosen so that any leak --
#: verbatim, truncated, digit-counted or magnitude-encoded -- shows up as a
#: literal substring search failure.
SENTINEL_VALUES = (
    "ZQXJV-SENTINEL-VALUE",
    "wxq-operator-secret-position",
    "8675309.42",
)

#: Distinctive KEY names. This is the case the naive sentinel test misses.
SENTINEL_KEYS = (
    "ZQXJK-SENTINEL-KEY",
    "tc-temp-nychigh-2026-08-25-lt79f",
)


# ---------------------------------------------------------------------------
# Fixtures (payloads only -- this suite never touches the network)
# ---------------------------------------------------------------------------


def balances_payload(current_balance: float) -> dict[str, Any]:
    """A ``GetAccountBalancesResponse``-shaped payload, magnitude injectable."""
    return {
        "balances": [
            {
                "currentBalance": current_balance,
                "currency": "USD",
                "lastUpdated": "2026-08-31T12:00:00Z",
                "buyingPower": current_balance,
                "pendingWithdrawals": [
                    {"id": "w-1", "balance": current_balance, "acknowledged": False}
                ],
                "unsettledFunds": current_balance,
            }
        ]
    }


def slug_keyed_positions_payload() -> dict[str, Any]:
    """``GetUserPositionsResponse.positions`` is ``dict[str, UserPosition]``.

    The keys ARE market slugs, i.e. the operator's portfolio expressed as
    field names. Verified against the committed SDK TypedDict at
    ``docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/
    types/portfolio.py`` (``GetUserPositionsResponse``).
    """
    position = {
        "netPosition": "1200",
        "cost": {"value": "8675309.42", "currency": "USD"},
        "expired": False,
    }
    return {
        "positions": {
            "tc-temp-nychigh-2026-08-25-lt79f": position,
            "wxq-operator-secret-position": position,
            "ZQXJK-SENTINEL-KEY": position,
        },
        "eof": True,
    }


def sentinel_payload() -> dict[str, Any]:
    """Sentinels in both values and keys, nested, with lists and ``None``."""
    return {
        "orders": [
            {
                "id": "ZQXJV-SENTINEL-VALUE",
                "marketSlug": "wxq-operator-secret-position",
                "price": {"value": "8675309.42", "currency": "USD"},
                "quantity": 8675309,
                "goodTillTime": None,
                "marketMetadata": {
                    "slug": "wxq-operator-secret-position",
                    "ZQXJK-SENTINEL-KEY": "ZQXJV-SENTINEL-VALUE",
                },
            },
            {"tc-temp-nychigh-2026-08-25-lt79f": ["ZQXJV-SENTINEL-VALUE", 8675309.42]},
        ],
        "ZQXJK-SENTINEL-KEY": {"nested": "ZQXJV-SENTINEL-VALUE"},
    }


def artifact_text(payload: object, *, endpoint: str = OPEN_ORDERS_PATH) -> str:
    return render_shape_report(endpoint=endpoint, shape=describe_shape(payload))


# ---------------------------------------------------------------------------
# Sentinels in VALUES
# ---------------------------------------------------------------------------


def test_no_sentinel_value_reaches_the_artifact() -> None:
    text = artifact_text(sentinel_payload())
    for sentinel in SENTINEL_VALUES:
        assert sentinel not in text
    # Also every fragment of a sentinel long enough to identify it.
    assert "ZQXJV" not in text
    assert "8675309" not in text


def test_scalar_payloads_render_as_type_only() -> None:
    assert describe_shape("ZQXJV-SENTINEL-VALUE") == {"type": "string"}
    assert describe_shape(8675309.42) == {"type": "number"}
    assert describe_shape(8675309) == {"type": "number"}
    assert describe_shape(True) == {"type": "bool"}
    assert describe_shape(None) == {"type": "null"}


def test_int_and_float_are_indistinguishable() -> None:
    """``int`` vs ``float`` is a one-bit disclosure about the value itself.

    A balance that happens to be integral would render a different token from
    one that is not. Both collapse to ``number``.
    """
    assert describe_shape({"cashValue": 1}) == describe_shape({"cashValue": 1.5})


# ---------------------------------------------------------------------------
# Sentinels in KEYS -- the case the naive test misses
# ---------------------------------------------------------------------------


def test_no_sentinel_key_reaches_the_artifact() -> None:
    text = artifact_text(sentinel_payload())
    for sentinel in SENTINEL_KEYS:
        assert sentinel not in text
    assert "ZQXJK" not in text


def test_unrecognized_keys_become_a_count_not_a_name() -> None:
    shape = describe_shape({"id": "x", "ZQXJK-A": 1, "ZQXJK-B": 2, "ZQXJK-C": 3})
    assert shape["type"] == "object"
    assert set(shape["keys"]) == {"id"}
    assert shape["unrecognized_key_count"] == 3


def test_non_string_keys_count_as_unrecognized() -> None:
    shape = describe_shape({1: "a", ("t",): "b"})
    assert shape["keys"] == {}
    assert shape["unrecognized_key_count"] == 2


# ---------------------------------------------------------------------------
# Slug-keyed map -- the portfolio-as-field-names attack
# ---------------------------------------------------------------------------


def test_slug_keyed_position_map_publishes_a_count_not_the_slugs() -> None:
    payload = slug_keyed_positions_payload()
    text = artifact_text(payload, endpoint=POSITIONS_PATH)
    for slug in payload["positions"]:
        assert slug not in text

    shape = describe_shape(payload)
    positions = shape["keys"]["positions"]
    assert positions["keys"] == {}
    assert positions["unrecognized_key_count"] == 3
    # The VALUE shape is still described -- that is the point of the capture.
    assert set(positions["unrecognized_value"]["keys"]) == {
        "netPosition",
        "cost",
        "expired",
    }


# ---------------------------------------------------------------------------
# No magnitude leakage -- the strongest available statement
# ---------------------------------------------------------------------------


def test_balance_magnitude_produces_byte_identical_artifacts() -> None:
    small = artifact_text(balances_payload(1.0), endpoint=BALANCES_PATH)
    huge = artifact_text(balances_payload(987654321.05), endpoint=BALANCES_PATH)
    assert small.encode("utf-8") == huge.encode("utf-8")


def test_written_artifact_files_are_byte_identical_across_magnitudes(
    tmp_path: Path,
) -> None:
    small = write_shape_artifact(
        endpoint=BALANCES_PATH,
        payload=balances_payload(1.0),
        directory=tmp_path / "small",
    )
    huge = write_shape_artifact(
        endpoint=BALANCES_PATH,
        payload=balances_payload(987654321.05),
        directory=tmp_path / "huge",
    )
    assert small.name == huge.name
    assert small.read_bytes() == huge.read_bytes()


def test_string_length_is_not_disclosed() -> None:
    short = artifact_text({"marketSlug": "a"})
    long = artifact_text({"marketSlug": "a" * 4096})
    assert short == long


def test_list_length_is_not_disclosed() -> None:
    one = artifact_text({"orders": [{"id": "a"}]})
    many = artifact_text({"orders": [{"id": "a"}] * 97})
    assert one == many


# ---------------------------------------------------------------------------
# Independent no-money assertion (does NOT use find_secret_leak_offsets)
# ---------------------------------------------------------------------------


def test_allowlisted_key_names_contain_no_digits() -> None:
    """Precondition that makes the digit test below meaningful."""
    assert not [key for key in SHAPE_ALLOWED_KEYS if any(c.isdigit() for c in key)]


def test_artifact_carries_no_digit_outside_the_unrecognized_key_count() -> None:
    """A money value cannot be rendered without a digit.

    Every line of the payload-derived subtree is checked for digits; the only
    line permitted to carry one is the structural ``unrecognized_key_count``.
    This assertion consults no credential list, so it holds against payloads
    that contain no credential at all -- which is exactly the R-1 case.

    The ``endpoint`` header is excluded because it is not payload-derived: it
    is a caller-supplied constant, asserted verbatim below and constrained by
    the module's endpoint pattern, so it cannot carry a captured value.
    """
    for payload in (sentinel_payload(), slug_keyed_positions_payload(), balances_payload(42.5)):
        document = json.loads(artifact_text(payload))
        assert document["endpoint"] == OPEN_ORDERS_PATH
        rendered = json.dumps(document["shape"], indent=2, sort_keys=True)
        for line in rendered.splitlines():
            if "unrecognized_key_count" in line:
                continue
            assert not any(char.isdigit() for char in line), line


def test_every_string_in_the_artifact_is_allowlisted_or_a_type_token() -> None:
    document = json.loads(artifact_text(sentinel_payload()))
    strings: list[str] = []

    def collect(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                strings.append(key)
                collect(value)
        elif isinstance(node, list):
            for item in node:
                collect(item)
        elif isinstance(node, str):
            strings.append(node)

    collect(document["shape"])
    structural = {
        "type",
        "keys",
        "items",
        "variants",
        "unrecognized_key_count",
        "unrecognized_value",
    }
    tokens = {
        "object",
        "array",
        "mixed",
        "string",
        "number",
        "bool",
        "null",
        "unsupported",
        "truncated",
    }
    for value in strings:
        parts = set(value.split("|"))
        assert value in SHAPE_ALLOWED_KEYS or value in structural or parts <= tokens, value


# ---------------------------------------------------------------------------
# The value-free verifier, and proof it actually fires
# ---------------------------------------------------------------------------


def test_verifier_accepts_a_real_shape() -> None:
    verify_value_free(describe_shape(sentinel_payload()))


def test_verifier_detects_a_smuggled_key_name() -> None:
    shape = describe_shape({"id": "x"})
    shape["keys"]["ZQXJK-SENTINEL-KEY"] = {"type": "string"}
    with pytest.raises(ShapeLeakError):
        verify_value_free(shape)


def test_verifier_detects_a_smuggled_value() -> None:
    shape = describe_shape({"id": "x"})
    shape["keys"]["id"] = {"type": "string", "value": "ZQXJV-SENTINEL-VALUE"}
    with pytest.raises(ShapeLeakError):
        verify_value_free(shape)


def test_verifier_detects_an_unknown_type_token() -> None:
    with pytest.raises(ShapeLeakError):
        verify_value_free({"type": "8675309.42"})


def test_writer_refuses_and_writes_nothing_when_the_verifier_fires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def leaky(payload: object, *, depth: int = 0) -> dict[str, Any]:
        return {"type": "string", "value": "ZQXJV-SENTINEL-VALUE"}

    monkeypatch.setattr(shape_capture, "describe_shape", leaky)
    directory = tmp_path / "evidence"
    with pytest.raises(ShapeLeakError):
        write_shape_artifact(endpoint=BALANCES_PATH, payload={"id": "x"}, directory=directory)
    assert not directory.exists() or list(directory.iterdir()) == []


# ---------------------------------------------------------------------------
# Artefact naming, permissions and the git ignore rule
# ---------------------------------------------------------------------------


def test_filename_carries_the_private_prefix() -> None:
    name = shape_artifact_filename(POSITIONS_PATH)
    assert name.startswith(PRIVATE_ARTIFACT_PREFIX)
    assert "/" not in name


def test_endpoint_that_is_not_a_plain_path_is_refused() -> None:
    with pytest.raises(ValueError):
        shape_artifact_filename("/v1/market/slug/tc-temp-nychigh-2026-08-25-lt79f?x=1")


def test_artifact_is_written_0600_in_a_0700_directory(tmp_path: Path) -> None:
    directory = tmp_path / "evidence" / "venue"
    path = write_shape_artifact(
        endpoint=POSITIONS_PATH,
        payload=slug_keyed_positions_payload(),
        directory=directory,
    )
    assert stat.S_IMODE(os.stat(path).st_mode) == SHAPE_FILE_MODE
    assert stat.S_IMODE(os.stat(directory).st_mode) == SHAPE_DIR_MODE


def test_default_artifact_path_is_git_ignored() -> None:
    """Fails if the ``PRIVATE_`` ignore rule is ever removed or narrowed.

    ``git check-ignore`` does not require the path to exist, so this asks git
    the real question without creating a real artefact in the work tree.
    """
    probe = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        pytest.skip("not a git work tree")

    relative = PRIVATE_SHAPE_DIRECTORY / shape_artifact_filename(POSITIONS_PATH)
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--", str(relative)],
        cwd=REPO_ROOT,
        check=False,
    )
    assert ignored.returncode == 0, f"{relative} is NOT git-ignored"

    # Proof the check is meaningful: a non-PRIVATE sibling is NOT ignored.
    sibling = PRIVATE_SHAPE_DIRECTORY / "READONLY_AUTH_SMOKE_probe.md"
    not_ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--", str(sibling)],
        cwd=REPO_ROOT,
        check=False,
    )
    assert not_ignored.returncode == 1, f"{sibling} unexpectedly ignored"


def test_writer_refuses_to_overwrite_an_existing_artifact(tmp_path: Path) -> None:
    write_shape_artifact(endpoint=BALANCES_PATH, payload=balances_payload(1.0), directory=tmp_path)
    with pytest.raises(FileExistsError):
        write_shape_artifact(
            endpoint=BALANCES_PATH, payload=balances_payload(1.0), directory=tmp_path
        )


# ---------------------------------------------------------------------------
# Structural edge cases
# ---------------------------------------------------------------------------


def test_empty_payloads() -> None:
    assert describe_shape({}) == {"type": "object", "keys": {}, "unrecognized_key_count": 0}
    assert describe_shape([]) == {"type": "array"}


def test_heterogeneous_list_of_dicts_is_unioned() -> None:
    shape = describe_shape([{"id": "a"}, {"price": {"value": "1", "currency": "USD"}}])
    assert set(shape["items"]["keys"]) == {"id", "price"}


def test_list_mixing_scalars_and_objects_becomes_mixed() -> None:
    shape = describe_shape(["a", 1, None, {"id": "x"}])
    items = shape["items"]
    assert items["type"] == "mixed"
    assert {variant["type"] for variant in items["variants"]} == {
        "null|number|string",
        "object",
    }


def test_none_values_are_typed_not_omitted() -> None:
    shape = describe_shape({"goodTillTime": None})
    assert shape["keys"]["goodTillTime"] == {"type": "null"}


def test_non_json_scalars_are_unsupported_never_stringified() -> None:
    shape = describe_shape({"cost": b"ZQXJV-SENTINEL-VALUE"})
    assert shape["keys"]["cost"] == {"type": "unsupported"}


def test_deep_nesting_is_truncated_without_recursion_error() -> None:
    payload: Any = "ZQXJV-SENTINEL-VALUE"
    for _ in range(MAX_SHAPE_DEPTH + 40):
        payload = {"order": payload}
    text = render_shape_report(endpoint=OPEN_ORDERS_PATH, shape=describe_shape(payload))
    assert "truncated" in text
    assert "ZQXJV" not in text


def test_report_is_deterministic_and_carries_no_timestamp() -> None:
    first = artifact_text(sentinel_payload())
    second = artifact_text(sentinel_payload())
    assert first == second
    assert "20" + "26-" not in first  # no capture date smuggled into the body


# ---------------------------------------------------------------------------
# Allowlist provenance -- derived from the committed SDK TypedDicts
# ---------------------------------------------------------------------------


def sdk_typed_dict_keys() -> set[str]:
    keys: set[str] = set()
    for path in sorted(SDK_SNAPSHOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not any("TypedDict" in ast.unparse(base) for base in node.bases):
                continue
            for statement in node.body:
                if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                    keys.add(statement.target.id)
    return keys


def test_allowlist_equals_the_committed_sdk_typed_dict_fields() -> None:
    """Pins provenance: the allowlist is the SDK schema, not a hand list.

    If the snapshot is refreshed and a field is added or removed, this fails
    -- which is the point. An unrecognized key is only *safe* because it
    degrades to a count; an over-broad allowlist would let a venue-chosen name
    through verbatim.
    """
    if not SDK_SNAPSHOT.exists():
        pytest.skip("SDK snapshot not present")
    assert set(SHAPE_ALLOWED_KEYS) == sdk_typed_dict_keys()


# ---------------------------------------------------------------------------
# Generative value-invariance: the general form of the magnitude test
# ---------------------------------------------------------------------------

json_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**12), max_value=10**12),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
    st.text(max_size=12),
)

key_names = st.one_of(
    st.sampled_from(sorted(SHAPE_ALLOWED_KEYS)[:40]),
    st.text(min_size=1, max_size=8),
)

json_payloads = st.recursive(
    json_scalars,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(key_names, children, max_size=4),
    ),
    max_leaves=12,
)


def mutate_values(node: object) -> object:
    """Same structure and keys, every scalar replaced by a different one."""
    if isinstance(node, dict):
        return {key: mutate_values(value) for key, value in node.items()}
    if isinstance(node, list):
        return [mutate_values(item) for item in node]
    if node is None:
        return None
    if isinstance(node, bool):
        return not node
    if isinstance(node, int | float):
        return 987654321.05
    if isinstance(node, str):
        return "ZQXJV-SENTINEL-VALUE"
    return node


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(json_payloads)
def test_report_depends_only_on_structure_and_key_names(payload: object) -> None:
    original = artifact_text(payload)
    mutated = artifact_text(mutate_values(payload))
    assert original == mutated
    assert "ZQXJV" not in mutated
    assert "987654321" not in mutated
