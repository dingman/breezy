"""T2 -- ``OrderSubmissionPermit`` construction is unforgeable (L-22).

Deliberately narrow, per the converged peer review of
``CRH_ENABLEMENT_STEP8_BRIEF_2026-09-04.md`` item 1: the preconditions run
inside ``issue`` (the real construction path), so what THIS module pins is
only the accidental-construction guard on ``__init__`` -- the seal check, the
no-arg refusal, that the type is not a msgspec ``Struct``, and that no field
value ever appears in ``repr()``. It never calls ``OrderSubmissionPermit.issue``
by that name: ``issue`` has exactly one PRODUCTION caller repo-wide,
``app/trade.py::main`` (B11, ``test_polymarket_us_readonly_guard.py``), and a
test calling it here would add a second call site to that pin. The test
modules that DO exercise ``issue``'s refusal matrix
(``test_order_submission_permit_issuance.py``,
``test_current_rung_hold_order_submission_wiring.py``) call through a local
alias for the same reason -- and B11's exact-set pin is alias-resolved, so
those call sites are still counted, just not added to this module.
"""

from __future__ import annotations

import msgspec
import pytest

from breezy.runtime.order_enablement import (
    OrderSubmissionPermit,
    OrderSubmissionPermitForgeryError,
)


def test_direct_construction_with_a_foreign_seal_raises() -> None:
    with pytest.raises(OrderSubmissionPermitForgeryError):
        OrderSubmissionPermit(object(), expires_at_ns=1, operator_id="op")


def test_no_arg_construction_raises() -> None:
    with pytest.raises(TypeError):
        OrderSubmissionPermit()  # type: ignore[call-arg]


def test_it_is_not_a_msgspec_struct() -> None:
    """A capability object cannot be a ``NautilusConfig`` field (L-22): every
    field there must be msgspec-encodable, so this type is deliberately not a
    ``Struct`` and can never be decoded out of persisted or replayed config
    bytes.
    """
    assert not issubclass(OrderSubmissionPermit, msgspec.Struct)


def test_repr_reveals_nothing() -> None:
    """Every field is declared ``repr=False``: none of their values may ever
    appear rendered. Built by bypassing ``__init__`` entirely
    (``object.__new__`` + ``object.__setattr__``, since the type is frozen)
    so this exercises the dataclass-generated ``__repr__`` directly, without
    a second ``OrderSubmissionPermit(`` construction call.
    """
    permit = object.__new__(OrderSubmissionPermit)
    object.__setattr__(permit, "seal", object())
    object.__setattr__(permit, "expires_at_ns", 123456789)
    object.__setattr__(permit, "operator_id", "the-operator")
    rendered = repr(permit)
    assert "123456789" not in rendered
    assert "the-operator" not in rendered
