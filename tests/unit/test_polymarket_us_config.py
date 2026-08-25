"""Config contract for the Polymarket.us data client (plan revision 2, Step 8).

Authority: ``docs/plans/POLYMARKET_US_READONLY_AUTH_PLAN.md`` section 6
(``config.py`` blueprint, ``:602-630``) and section 9 Step 8 (``:1207-1214``).

Two properties are load-bearing and both are pinned here:

* **No secret ever enters the config.** A ``NautilusConfig`` is *serialised*
  -- ``config.json()`` may be written to disk by the kernel and
  ``tokenize_config`` hashes it -- so a config field carrying credential
  material is a disclosure, not a style problem. The config carries env var
  *names* only.
* **Every venue parameter is a required input with no default**
  (``TRADING_ENABLEMENT_FINDINGS.md:254-256``). A frozen kw-only msgspec
  struct expresses "required" with a ``None`` sentinel plus a
  ``__post_init__`` that refuses it, because msgspec does NOT validate field
  types on construction -- an unchecked struct would silently accept both a
  missing endpoint and a misspelled signing variant.
"""

from __future__ import annotations

import msgspec
import pytest
from nautilus_trader.common.config import tokenize_config

from breezy.adapters.polymarket_us.config import PolymarketUSDataClientConfig
from breezy.adapters.polymarket_us.credentials import (
    PolymarketUSSecretsRefConfig,
    assert_config_type_excludes_secrets,
)
from breezy.adapters.polymarket_us.signing import SigningVariant
from breezy.runtime.settings import SettingsError

VALID_KWARGS: dict[str, object] = {
    "api_base_url": "https://api.example.invalid",
    "gateway_base_url": "https://gateway.example.invalid",
    "ws_url": "wss://api.example.invalid",
    "market_slugs": ("tc-temp-nychigh-2026-08-25-lt79f",),
    "user_agent": "breezy-test/1.0 (+mailto:ops@example.invalid)",
}


def make_config(**overrides: object) -> PolymarketUSDataClientConfig:
    kwargs = dict(VALID_KWARGS)
    kwargs.update(overrides)
    return PolymarketUSDataClientConfig(**kwargs)  # type: ignore[arg-type]


def test_config_raises_settings_error_naming_each_unset_field() -> None:
    """Every unset venue parameter is named, not just the first one found."""
    with pytest.raises(SettingsError) as excinfo:
        PolymarketUSDataClientConfig()

    message = str(excinfo.value)
    for field in ("api_base_url", "gateway_base_url", "ws_url", "market_slugs", "user_agent"):
        assert field in message


def test_config_raises_settings_error_for_an_empty_market_slug_tuple() -> None:
    with pytest.raises(SettingsError, match="market_slugs"):
        make_config(market_slugs=())


def test_config_raises_settings_error_for_a_blank_market_slug() -> None:
    with pytest.raises(SettingsError, match="market_slugs"):
        make_config(market_slugs=("ok-slug", "   "))


def test_signing_variant_defaults_to_path_only() -> None:
    assert make_config().signing_variant is SigningVariant.PATH_ONLY


def test_signing_variant_rejects_an_unknown_string() -> None:
    """msgspec does not type-check on construction; ``__post_init__`` must."""
    with pytest.raises(SettingsError, match="signing_variant"):
        make_config(signing_variant="path-only")


def test_signing_variant_accepts_its_own_string_value() -> None:
    config = make_config(signing_variant="path_with_query")
    assert SigningVariant(config.signing_variant) is SigningVariant.PATH_WITH_QUERY


@pytest.mark.parametrize(
    "field",
    [
        "http_timeout_secs",
        "global_requests_per_second",
        "instrument_requests_per_minute",
        "book_requests_per_minute",
        "ws_heartbeat_secs",
        "ws_idle_timeout_secs",
    ],
)
def test_non_positive_policy_numbers_are_rejected(field: str) -> None:
    with pytest.raises(SettingsError, match=field):
        make_config(**{field: 0})


def test_config_carries_no_secret_bearing_field() -> None:
    """The shipped ban must hold for this type; it also runs at import time."""
    assert_config_type_excludes_secrets(PolymarketUSDataClientConfig)


def test_config_json_round_trip_contains_only_env_var_names() -> None:
    config = make_config()
    encoded = config.json()

    assert b"POLYMARKET_US_KEY_ID" in encoded
    assert b"POLYMARKET_US_SECRET_KEY_FILE" in encoded
    # A serialised config must never carry a value that could BE a secret.
    for banned in (b'secret_key":', b"BEGIN PRIVATE KEY", b'key_id":'):
        assert banned not in encoded

    decoded = msgspec.json.decode(encoded, type=PolymarketUSDataClientConfig)
    assert decoded == config


def test_tokenize_config_succeeds_and_contains_no_secret() -> None:
    digest = tokenize_config(make_config())
    assert isinstance(digest, str)
    assert digest


def test_secrets_field_defaults_to_the_shipped_reference_config() -> None:
    assert make_config().secrets == PolymarketUSSecretsRefConfig()


def test_config_is_frozen() -> None:
    config = make_config()
    with pytest.raises(AttributeError):
        config.api_base_url = "https://elsewhere.invalid"  # type: ignore[misc]


def test_config_module_never_imports_os() -> None:
    """Endpoints are populated by the factory; the config reads no environment."""
    import ast
    from pathlib import Path

    import breezy.adapters.polymarket_us.config as config_module

    source = Path(config_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    assert "os" not in imported
