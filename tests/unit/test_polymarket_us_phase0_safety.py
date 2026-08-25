"""Phase 0 safety fuses for the Polymarket.us adapter path."""

from __future__ import annotations

import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.common.config import NautilusConfig, tokenize_config
from nautilus_trader.common.secure import SecureString

from breezy.adapters.polymarket_us.credentials import (
    CredentialConfigError,
    assert_config_type_excludes_secrets,
)
from breezy.adapters.polymarket_us.secure import RedactedSecureString

REPO_ROOT = Path(__file__).resolve().parents[2]
SECRET_VALUE = "pm_test_secret_material_never_serialize"
KEY_ID_VALUE = "pm_test_key_id_never_serialize"


def test_gitignore_covers_polymarket_us_secret_files() -> None:
    ignored = {
        line.strip()
        for line in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }

    assert ".env.*" in ignored
    assert "*.pem" in ignored
    assert "*.key" in ignored
    assert "secrets/" in ignored
    assert ".polymarket-us-credentials.json" in ignored


class _UnsafeBaseSecretConfig(NautilusConfig, frozen=True):
    secret: SecureString


class _UnsafeSubclassSecretConfig(NautilusConfig, frozen=True):
    secret: RedactedSecureString


@pytest.mark.parametrize(
    ("config_type", "secret_type"),
    [
        (_UnsafeBaseSecretConfig, SecureString),
        (_UnsafeSubclassSecretConfig, RedactedSecureString),
    ],
    ids=["base", "redacted_subclass"],
)
def test_secure_string_cannot_be_encoded_inside_any_nautilus_config(
    config_type: type[NautilusConfig],
    secret_type: type[SecureString],
) -> None:
    """Both the Nautilus base class and Breezy's subclass are refused.

    The subclass is covered deliberately: ``RedactedSecureString`` renders
    safely, but a config field is *serialised*, not rendered, so a subclass
    must not become a way to smuggle secret material into a NautilusConfig
    that the kernel may write to disk.
    """
    config = config_type(secret=secret_type(SECRET_VALUE, name="pm_secret_key"))

    with pytest.raises(TypeError, match="SecureString"):
        config.json()
    with pytest.raises(TypeError, match="SecureString"):
        tokenize_config(config)
    with pytest.raises(CredentialConfigError):
        assert_config_type_excludes_secrets(config_type)


def test_polymarket_us_config_serializes_only_secret_references() -> None:
    from breezy.adapters.polymarket_us.credentials import (
        PolymarketUSCredentials,
        PolymarketUSSecretsRefConfig,
        assert_config_type_excludes_secrets,
    )

    credentials = PolymarketUSCredentials(
        key_id=RedactedSecureString(KEY_ID_VALUE, name="pm_key_id"),
        secret_key=RedactedSecureString(SECRET_VALUE, name="pm_secret_key"),
    )
    config = PolymarketUSSecretsRefConfig(
        key_id_env_var="POLYMARKET_US_KEY_ID",
        secret_key_env_var="POLYMARKET_US_SECRET_KEY",
    )

    assert_config_type_excludes_secrets(type(config))
    encoded = config.json()
    digest = tokenize_config(config)

    # S16: never call .get_value() INSIDE an assert -- pytest rewrites the
    # assertion and prints every operand, so a failure would dump the
    # cleartext secret into CI output. Compare first, assert on the bool.
    secret_round_trips = credentials.secret_key.get_value() == SECRET_VALUE

    assert credentials.key_id == KEY_ID_VALUE
    assert secret_round_trips, "secret_key does not round-trip (value withheld)"
    assert SECRET_VALUE.encode() not in encoded
    assert KEY_ID_VALUE.encode() not in encoded
    assert SECRET_VALUE not in digest
    assert KEY_ID_VALUE not in digest


def test_credentials_present_do_not_authorize_live_order_submission() -> None:
    from breezy.adapters.polymarket_us.credentials import PolymarketUSCredentials
    from breezy.adapters.polymarket_us.safety import (
        LiveTradingPermissionError,
        assert_live_order_submission_permitted,
    )

    credentials = PolymarketUSCredentials(
        key_id=RedactedSecureString(KEY_ID_VALUE, name="pm_key_id"),
        secret_key=RedactedSecureString(SECRET_VALUE, name="pm_secret_key"),
    )

    with pytest.raises(LiveTradingPermissionError, match="live-trading permit"):
        assert_live_order_submission_permitted(
            credentials=credentials,
            permit=None,
            manual_order_indicator=True,
            order_notional_usd=Decimal("1.00"),
        )


def test_live_order_submission_chokepoint_requires_credentials_permit_and_manual_flag() -> None:
    from breezy.adapters.polymarket_us.credentials import PolymarketUSCredentials
    from breezy.adapters.polymarket_us.safety import (
        LiveTradingPermissionError,
        LiveTradingPermit,
        assert_live_order_submission_permitted,
    )

    credentials = PolymarketUSCredentials(
        key_id=RedactedSecureString(KEY_ID_VALUE, name="pm_key_id"),
        secret_key=RedactedSecureString(SECRET_VALUE, name="pm_secret_key"),
    )
    permit = LiveTradingPermit(
        operator_id="operator@example.com",
        max_order_notional_usd=Decimal("5.00"),
        issued_at_ns=1,
    )

    with pytest.raises(LiveTradingPermissionError, match="credentials"):
        assert_live_order_submission_permitted(
            credentials=None,
            permit=permit,
            manual_order_indicator=True,
            order_notional_usd=Decimal("1.00"),
        )
    with pytest.raises(LiveTradingPermissionError, match="manualOrderIndicator"):
        assert_live_order_submission_permitted(
            credentials=credentials,
            permit=permit,
            manual_order_indicator=None,
            order_notional_usd=Decimal("1.00"),
        )
    with pytest.raises(LiveTradingPermissionError, match="exceeds permit"):
        assert_live_order_submission_permitted(
            credentials=credentials,
            permit=permit,
            manual_order_indicator=True,
            order_notional_usd=Decimal("5.01"),
        )

    assert_live_order_submission_permitted(
        credentials=credentials,
        permit=permit,
        manual_order_indicator=False,
        order_notional_usd=Decimal("5.00"),
    )


def test_pytest_fails_fast_when_polymarket_credentials_are_present() -> None:
    env = {
        **os.environ,
        "POLYMARKET_US_SECRET_KEY": SECRET_VALUE,
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "tests/unit/test_domain_strict_arrow.py",
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Polymarket credential environment variable(s) present" in combined
    assert "POLYMARKET_US_SECRET_KEY" in combined
    assert SECRET_VALUE not in combined


def test_pyo3_network_clients_are_blocked_by_default() -> None:
    from nautilus_trader.core import nautilus_pyo3

    assert nautilus_pyo3.HttpClient.__name__ == "_BlockedPyo3NetworkClient"
    assert nautilus_pyo3.WebSocketClient.__name__ == "_BlockedPyo3NetworkClient"


def test_pyo3_egress_gap_has_exact_operator_command_documented() -> None:
    from tests.conftest import OS_EGRESS_BLOCK_COMMAND, PYO3_EGRESS_GAP

    assert "nautilus_pyo3" in PYO3_EGRESS_GAP
    assert "unshare -r -n" in OS_EGRESS_BLOCK_COMMAND
    assert "BREEZY_TEST_OS_EGRESS_BLOCK=1" in OS_EGRESS_BLOCK_COMMAND
    assert ".venv/bin/python -m pytest" in OS_EGRESS_BLOCK_COMMAND


# ``test_adapter_package_never_imports_sync_polymarket_us_client`` was REMOVED
# here. Its predicate (``node.module == "polymarket_us"`` AND an imported name
# of exactly ``PolymarketUS``) is the weak form that "Escape A"
# (``from polymarket_us.auth import create_auth_headers``) walked straight
# through. It is fully subsumed by the prefix-matched B5 barrier
# ``find_sdk_import_violations`` in ``test_polymarket_us_readonly_guard.py``,
# which matches on ``module.split(".")[0]``, also covers plain and dotted
# ``import`` statements, and scans src+scripts+tests rather than the adapter
# package alone. Subsumption was verified before deletion: B5 fires on the
# deleted test's positive case AND on the submodule, plain-import and
# dotted-import escapes it missed, and the deleted test's scope ("src") is
# inside ``REPO_WIDE_SCAN_ROOTS`` without colliding with the B5 oracle
# exemption (``tests/unit/test_polymarket_us_signing.py``).
