"""The ONE designated seam through which a test may drive an operator control.

Not a test module: a helper, in the shape of ``polymarket_us_exec_shapes.py``.

WHY THIS EXISTS, AND WHY IT IS THE ONLY WHITELISTED PATH
--------------------------------------------------------

R-6e's standing invariant is that no file in this repository assigns a value to
an operator-reserved control, and
``tests/unit/test_operator_control_assignment_scan.py`` proves it by scanning
``src/``, ``scripts/``, ``tests/`` and every tracked config file. But the
mechanism has to be EXERCISED, and exercising it means putting a value in the
environment for the duration of one test.

Those two facts are reconciled here rather than by exception. This module is
the scan's single whitelisted path, and it is safe to whitelist because of what
it structurally cannot do:

* **It names no control.** There is no reference here -- not a literal, not an
  imported constant -- to either operator-reserved control or to the constants
  that carry their names. (They are not even spelt out in this docstring: the
  census in layer B is an exact set over every tracked file, and this file is
  not in it.) It takes the variable name as a PARAMETER, so it cannot single
  out a control to favour, and it is audited for exactly that by
  ``test_the_whitelisted_helper_names_no_operator_reserved_control``.
* **It carries no value.** The value is the caller's argument. The audit test
  pins that the module contains no non-empty string constant outside its
  docstrings, so a default can never be smuggled in here.
* **It cannot outlive the ``with`` block.** Both context managers restore the
  previous state in a ``finally``, including removing a variable that was
  absent before. A test therefore cannot leak a value into a later test, into
  a fixture, or into the session.

The whitelist is the seam the scan's non-vacuity has to survive, so the scan's
own proof-by-planting is run with this file in place: a
``monkeypatch.setenv(CONTROL, ...)`` planted in any OTHER test still fires.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def operator_control_env(name: str, value: str) -> Iterator[None]:
    """Bind ``name`` to ``value`` for the body of the ``with`` block only.

    Restores the prior binding on the way out -- and removes the variable
    entirely if there was no prior binding, so absence stays absence.
    """
    previous = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


@contextmanager
def operator_control_unset(name: str) -> Iterator[None]:
    """Remove ``name`` from the environment for the body of the block only.

    Removal is the fail-closed direction and needs no whitelisting on its own;
    this exists so a test can prove absence deterministically even when the
    operator running the suite has the control exported in their own shell.
    """
    previous = os.environ.pop(name, None)
    try:
        yield
    finally:
        if previous is not None:
            os.environ[name] = previous
