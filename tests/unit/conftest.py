"""Shared helpers for the unit suite.

Currently one thing lives here: the walker over the captured Polymarket.us
payload corpus. It was previously duplicated byte-for-byte in
``test_polymarket_us_fee_model.py`` and ``test_polymarket_us_parsing.py``,
which meant a change to what counts as a "market object" had to be made twice
and could silently diverge. One definition, imported by both.
"""

from __future__ import annotations

import gc
import json
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

import pytest

from breezy.strategy.current_rung_hold.continuous_strategy import ContinuousRungHoldStrategy
from breezy.strategy.current_rung_hold.strategy import CurrentRungHoldStrategy

REPO_ROOT = Path(__file__).resolve().parents[2]

#: FU-16. Both classes' `on_start` enters the trial-day latch (a
#: `SqliteStateStore` db fd plus `-wal`/`-shm`, and an `os.open` flock fd
#: from `submit_intent.py` with no `__del__`) into `self._exit_stack`,
#: released only by `on_stop`. Subclasses (`ContinuousRungHoldBacktestStrategy`,
#: `CurrentRungHoldBacktestStrategy`) override `on_start` but call
#: `super().on_start()`, so patching these two base classes covers them too.
#: ~228 unit-test instances start via `.start()` and never call `.stop()`,
#: leaking ~1000 fds across the suite.
_LATCH_OWNING_STRATEGY_CLASSES: tuple[type, ...] = (
    ContinuousRungHoldStrategy,
    CurrentRungHoldStrategy,
)


def stop_if_still_open(instances: Iterable[object]) -> None:
    """Release every resource a tracked strategy instance still holds.

    Two independent things must happen, measured empirically (calling only
    one leaves fds open):

    1. If ``_exit_stack`` is still set, the latch (db fd + ``-wal``/``-shm``,
       plus the ``submit_intent`` flock) was never released. Prefer the real
       Nautilus lifecycle trigger, ``.stop()``, so the component's own FSM
       state advances correctly -- ``dispose()`` below is a silent no-op
       unless a component has actually reached STOPPED. Fall back to calling
       ``on_stop`` directly for an instance whose ``on_start`` was invoked
       outside ``.start()`` (FSM stuck at INITIALIZED, where ``.stop()``
       itself silently no-ops).
    2. Nautilus's own message-bus subscriber bookkeeping keeps a bound
       method (e.g. ``self.on_data``) alive after ``on_stop``, which forms a
       reference cycle back to this strategy and everything it holds --
       including the just-closed latch's ``SqliteStateStore``, still
       reachable via ``self._position_evidence_reader``. Ordinary
       refcounting cannot free a cycle; only ``.dispose()`` tears down that
       bookkeeping. Without it, the sqlite db/``-wal``/``-shm`` fds survive
       even a clean ``.stop()``.

    Idempotent: a test that already called ``.stop()`` itself has cleared
    ``_exit_stack`` to ``None``, so step 1 is a no-op for it; ``is_disposed``
    guards step 2 against a double ``dispose()``. Never swallows a cleanup
    failure -- a raise here is left to propagate so the caller can fail
    loudly instead of masking a broken teardown.
    """
    disposed_any = False
    for instance in instances:
        if getattr(instance, "_exit_stack", None) is not None:
            instance.stop()  # type: ignore[attr-defined]
            if getattr(instance, "_exit_stack", None) is not None:
                instance.on_stop()  # type: ignore[attr-defined]
        if not instance.is_disposed:  # type: ignore[attr-defined]
            instance.dispose()  # type: ignore[attr-defined]
            disposed_any = True
    if disposed_any:
        # Breaks the msgbus<->strategy reference cycle `.dispose()` untangles
        # into actually-freed objects (sqlite fds included) instead of merely
        # eligible-but-uncollected garbage sitting until the next automatic
        # run. Gated on `disposed_any`: `gc.collect()` is not free, and most
        # of this suite's tests never touch these two classes at all -- an
        # unconditional collection here would tax every other test's
        # teardown too.
        gc.collect()


@pytest.fixture(autouse=True)
def _stop_leaked_strategies(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Pair every ``on_start`` a test causes on a latch-owning strategy class
    with a full stop+dispose at teardown, even when the test itself never
    calls ``.stop()``. See :data:`_LATCH_OWNING_STRATEGY_CLASSES` and
    :func:`stop_if_still_open` for the leak this closes (FU-16).

    Instances are recorded unconditionally before the real ``on_start`` runs
    (not only on success), so an instance whose ``on_start`` raises after
    entering the latch (partial acquisition) is still tracked and cleaned up.
    """
    started: list[object] = []

    def _make_wrapper(original: Callable[..., None]) -> Callable[..., None]:
        def _wrapped_on_start(self: object, *args: object, **kwargs: object) -> None:
            started.append(self)
            original(self, *args, **kwargs)

        return _wrapped_on_start

    for cls in _LATCH_OWNING_STRATEGY_CLASSES:
        monkeypatch.setattr(cls, "on_start", _make_wrapper(cls.on_start))

    yield

    try:
        stop_if_still_open(started)
    except Exception as exc:  # noqa: BLE001 -- surfaced loudly, never swallowed
        pytest.fail(f"leaked strategy failed to clean up in teardown: {exc!r}")


#: The append-only capture of real venue payloads. Read-only in tests.
RAW_CAPTURE_DIR = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"

#: Non-vacuity floor for corpus properties. The capture held 729 market
#: observations on 2026-08-26; a property asserted over an empty or gutted
#: corpus is worthless, so every corpus test asserts this floor first.
MIN_CAPTURED_MARKETS = 700


def iter_captured_market_payloads(
    directory: Path = RAW_CAPTURE_DIR,
) -> list[dict[str, Any]]:
    """Every market object in every captured file, as a parseable payload.

    A market object is any JSON object carrying BOTH ``slug`` and
    ``orderPriceMinTickSize`` -- the shape ``parse_binary_option`` consumes.
    The walk is recursive, so markets nested under ``events[].markets[]``
    count too; a top-level-only scan misses most of the corpus.

    Returned as ``{"market": <object>}`` because that is the envelope
    ``parse_binary_option`` expects.
    """
    found: list[dict[str, Any]] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if "slug" in node and "orderPriceMinTickSize" in node:
                found.append({"market": node})
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for path in sorted(directory.glob("*.json")):
        walk(json.loads(path.read_text(encoding="utf-8")))
    return found
