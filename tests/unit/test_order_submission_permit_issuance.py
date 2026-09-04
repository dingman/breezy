"""T4 -- ``OrderSubmissionPermit.issue``'s five-precondition refusal matrix.

Companion to ``test_order_submission_permit.py`` (T2, the accidental-
construction guard on ``__init__``): THIS module exercises the real
construction path, ``issue`` itself, now that CRH step 8 wiring gives it its
one legitimate caller (``app/trade.py::main``, B11).

Every refusal is a subclass of ``OrderSubmissionRefused`` and every message
names the failed precondition only, never a value (L-22 shape,
``test_polymarket_us_secret_exposure.py:141`` precedent for the caplog
pattern). Reuses the shipped fixtures rather than inventing parallel ones:
``enable_operator_gate``/``credentials`` (live-trading permit issuance),
``operator_control_env`` (the ONE whitelisted seam for the two operator-
reserved caps -- never named here), and ``write_canonical_verified`` /
``write_canonical_unverified`` (the two monkeypatch fixtures for
``WRITE_CANONICAL_STRING_VERIFIED``, imported rather than re-defined so the
repo-wide "only this module may patch it" scan in
``test_polymarket_us_submit_order_chain.py`` stays green -- the module
default is True since C5's OP-4 positive-control flip, so refusal tests now
use ``write_canonical_unverified`` explicitly).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import pytest
from nautilus_trader.common.component import TestClock

from breezy.adapters.polymarket_us.operator_controls import (
    MAX_DAILY_BUDGET_USD_ENV_VAR,
    MAX_POSITION_COST_USD_ENV_VAR,
)
from breezy.adapters.polymarket_us.safety import issue_live_trading_permit
from breezy.runtime.order_enablement import (
    LiveTradingPermitNotValidError,
    OperatorCapsNotConfiguredError,
    OrdersNotRequestedError,
    OrderSubmissionPermit,
    RungHoldNotReadyError,
    SettingsNotSettingsLikeError,
    WriteCanonicalStringUnverifiedError,
)
from tests.unit.operator_control_env import operator_control_env
from tests.unit.test_polymarket_us_permit_issuance import (
    clock_at,
    credentials,
    enable_operator_gate,
)
from tests.unit.test_polymarket_us_submit_order_chain import (
    write_canonical_unverified,  # noqa: F401 -- reused as a fixture, see module docstring
    write_canonical_verified,  # noqa: F401 -- reused as a fixture, see module docstring
)

_ = credentials  # imported for parity with the shipped rig; not used directly here

#: B11 pins ``named_call_sites("issue")`` to exactly one PRODUCTION caller,
#: ``("src/breezy/app/trade.py", "main")``, repo-wide, INCLUDING ``tests/``
#: (``REPO_WIDE_SCAN_ROOTS``) -- deliberately stricter than B6/B7, which
#: scope to ``src``/``scripts`` only, because the whole security claim here
#: is an exact-set AST pin (converged review item 1). Every call below binds
#: through this local alias rather than writing ``OrderSubmissionPermit.issue(``
#: literally; the scanner is alias-aware (review finding 2,
#: ``_resolve_local_aliases`` in ``test_polymarket_us_readonly_guard.py``), so
#: each test function below IS still counted as a call site of ``issue`` --
#: enumerated explicitly, alongside the production caller, in
#: ``_B11_ISSUE_SITES``.
_ISSUE = OrderSubmissionPermit.issue


@dataclass(frozen=True, slots=True)
class _FakeSettings:
    """The narrow ``SettingsLike`` surface ``issue`` needs -- nothing else."""

    orders_enabled_requested: bool = True
    current_rung_hold: bool = True
    live_observations: bool = True


@contextmanager
def _caps(daily: str = "1000.00", position: str = "10.00") -> Iterator[None]:
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, daily),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, position),
    ):
        yield


def test_all_preconditions_satisfied_issues_a_permit(
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Positive control: every precondition met mints a real permit."""
    enable_operator_gate(monkeypatch)
    clock = clock_at()
    live_permit = issue_live_trading_permit(clock=clock)
    with _caps():
        permit = _ISSUE(
            settings=_FakeSettings(),
            live_trading_permit=live_permit,
            clock=clock,
        )
    assert isinstance(permit, OrderSubmissionPermit)
    assert permit.operator_id == live_permit.operator_id
    assert permit.expires_at_ns == live_permit.expires_at_ns


def test_orders_not_requested_refuses(
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    enable_operator_gate(monkeypatch)
    clock = clock_at()
    live_permit = issue_live_trading_permit(clock=clock)
    with _caps(), pytest.raises(OrdersNotRequestedError):
        _ISSUE(
            settings=_FakeSettings(orders_enabled_requested=False),
            live_trading_permit=live_permit,
            clock=clock,
        )


def test_live_trading_permit_wrong_type_refuses(
    write_canonical_verified: None,  # noqa: F811
) -> None:
    clock = TestClock()
    with _caps(), pytest.raises(LiveTradingPermitNotValidError):
        _ISSUE(
            settings=_FakeSettings(),
            live_trading_permit=None,
            clock=clock,
        )


def test_live_trading_permit_expired_refuses(
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    enable_operator_gate(monkeypatch)
    clock = clock_at()
    live_permit = issue_live_trading_permit(clock=clock)
    expired_clock = TestClock()
    expired_clock.set_time(live_permit.expires_at_ns + 1)
    with _caps(), pytest.raises(LiveTradingPermitNotValidError):
        _ISSUE(
            settings=_FakeSettings(),
            live_trading_permit=live_permit,
            clock=expired_clock,
        )


def test_write_canonical_string_unverified_refuses(
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_unverified: None,  # noqa: F811
) -> None:
    """The ``write_canonical_unverified`` fixture pins the predicate False --
    since C5's OP-4 positive-control flip the module default is True, so
    this refusal is no longer reachable by default and must be forced,
    exactly the structural unreachability the design section calls out.
    """
    enable_operator_gate(monkeypatch)
    clock = clock_at()
    live_permit = issue_live_trading_permit(clock=clock)
    with _caps(), pytest.raises(WriteCanonicalStringUnverifiedError):
        _ISSUE(
            settings=_FakeSettings(),
            live_trading_permit=live_permit,
            clock=clock,
        )


def test_operator_caps_absent_refuses(
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    enable_operator_gate(monkeypatch)
    clock = clock_at()
    live_permit = issue_live_trading_permit(clock=clock)
    with pytest.raises(OperatorCapsNotConfiguredError):
        _ISSUE(
            settings=_FakeSettings(),
            live_trading_permit=live_permit,
            clock=clock,
        )


def test_current_rung_hold_not_ready_refuses(
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    enable_operator_gate(monkeypatch)
    clock = clock_at()
    live_permit = issue_live_trading_permit(clock=clock)
    with _caps(), pytest.raises(RungHoldNotReadyError):
        _ISSUE(
            settings=_FakeSettings(current_rung_hold=False),
            live_trading_permit=live_permit,
            clock=clock,
        )


def test_live_observations_not_ready_refuses(
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    enable_operator_gate(monkeypatch)
    clock = clock_at()
    live_permit = issue_live_trading_permit(clock=clock)
    with _caps(), pytest.raises(RungHoldNotReadyError):
        _ISSUE(
            settings=_FakeSettings(live_observations=False),
            live_trading_permit=live_permit,
            clock=clock,
        )


_FORBIDDEN_VALUES = ("the-operator-value", "1000.00", "10.00")


def _assert_message_names_no_value(exc: BaseException) -> None:
    message = str(exc)
    for value in _FORBIDDEN_VALUES:
        assert value not in message, f"{value!r} leaked into: {message!r}"


def test_orders_not_requested_message_names_no_value(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """L-22 shape, ``test_polymarket_us_secret_exposure.py:141`` precedent:
    the refusal names the failed precondition only, never the operator id or
    either cap amount used elsewhere in this module's fixtures. Checked
    before ``write_canonical_verified`` in ``issue``'s order, so this branch
    needs no fixture to reach it.
    """
    enable_operator_gate(monkeypatch, operator_id="the-operator-value")
    clock = clock_at()
    live_permit = issue_live_trading_permit(clock=clock)
    with caplog.at_level(logging.INFO), pytest.raises(OrdersNotRequestedError) as exc:
        _ISSUE(
            settings=_FakeSettings(orders_enabled_requested=False),
            live_trading_permit=live_permit,
            clock=clock,
        )
    _assert_message_names_no_value(exc.value)


def test_write_canonical_unverified_message_names_no_value(
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_unverified: None,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    enable_operator_gate(monkeypatch, operator_id="the-operator-value")
    clock = clock_at()
    live_permit = issue_live_trading_permit(clock=clock)
    with (
        _caps(),
        caplog.at_level(logging.INFO),
        pytest.raises(WriteCanonicalStringUnverifiedError) as exc,
    ):
        _ISSUE(
            settings=_FakeSettings(),
            live_trading_permit=live_permit,
            clock=clock,
        )
    _assert_message_names_no_value(exc.value)


def test_operator_caps_and_rung_hold_messages_name_no_value(
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    enable_operator_gate(monkeypatch, operator_id="the-operator-value")
    clock = clock_at()
    live_permit = issue_live_trading_permit(clock=clock)
    with caplog.at_level(logging.INFO):
        with pytest.raises(OperatorCapsNotConfiguredError) as exc_caps:
            _ISSUE(
                settings=_FakeSettings(),
                live_trading_permit=live_permit,
                clock=clock,
            )
        _assert_message_names_no_value(exc_caps.value)

        with _caps(), pytest.raises(RungHoldNotReadyError) as exc_rung:
            _ISSUE(
                settings=_FakeSettings(current_rung_hold=False),
                live_trading_permit=live_permit,
                clock=clock,
            )
        _assert_message_names_no_value(exc_rung.value)


def test_settings_not_satisfying_settingslike_protocol_refuses(
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Finding 4: ``SettingsLike`` is declared ``runtime_checkable`` but was
    never actually checked -- a plain object missing the three required
    attributes must be refused by name at the door, not fall through to an
    ``AttributeError`` deep inside the precondition chain.
    """
    enable_operator_gate(monkeypatch)
    clock = clock_at()
    live_permit = issue_live_trading_permit(clock=clock)

    class _PlainObject:
        pass

    with _caps(), pytest.raises(SettingsNotSettingsLikeError):
        _ISSUE(
            settings=_PlainObject(),
            live_trading_permit=live_permit,
            clock=clock,
        )
