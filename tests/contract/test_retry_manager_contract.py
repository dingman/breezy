"""Contract tests pinning `nautilus_trader.live.retry.RetryManager` semantics.

Every assertion here was observed by execution against the pinned install
(nautilus-trader 1.231.0), not inferred from documentation. Run these FIRST on
any version bump: a failure means the platform moved, not that Breezy is
wrong.

This is the file a settlement-critical hole was found against. Breezy's
`src/breezy/ingest/http.py` builds a `TransportError` hierarchy where the bare
base class is a routine network hiccup (retry, degrade after three) and its
subclasses (`DisallowedHostError`, `RedirectError`, `ContentEncodingError`,
...) are integrity alarms that must hard-block the site rather than be
retried. Whether that separation holds depends entirely on THIS module's
dispatch semantics, not on Breezy's own code -- so it is pinned here, framework
side, independent of `breezy.ingest.http`.

The taxonomy below is deliberately local to this test file (`_Base`, `_Leaf`,
`_Sibling`) and NOT imported from `breezy.ingest.http`: this is a framework
contract test and must keep passing even if Breezy's error hierarchy is
renamed or restructured.

Scope: `live/retry.py` `RetryManager.run` (`:145-201`, exception dispatch at
`:172`, veto-without-reraise at `:174-183`), `RetryManager.clear` (`:206`),
`RetryManagerPool.acquire`/`release` (`:321`, `:344`), and
`get_exponential_backoff` (`:24`). No network access.
"""

from __future__ import annotations

import inspect

import pytest
from nautilus_trader.common.component import Logger
from nautilus_trader.live.retry import RetryManager, RetryManagerPool, get_exponential_backoff

pytestmark = pytest.mark.contract


class _Transient(Exception):
    """Stands in for a network hiccup -- listed in `exc_types`."""


class _Base(Exception):
    """Stands in for a listed `exc_types` entry that has subclasses."""


class _Leaf(_Base):
    """A SUBCLASS of a listed type. `except self.exc_types` is ordinary Python
    `except`, hence `isinstance`-based -- this must be caught too."""


class _Sibling(Exception):
    """NOT related to `_Transient`/`_Base` by inheritance and NOT listed in
    `exc_types` for the tests that use it -- must propagate uncaught."""


def _logger() -> Logger:
    return Logger("CONTRACT-PROBE")


def _manager(exc_types: tuple[type[BaseException], ...], **kwargs: object) -> RetryManager:
    return RetryManager(
        max_retries=3,
        delay_initial_ms=1,
        delay_max_ms=1,
        backoff_factor=2,
        logger=_logger(),
        exc_types=exc_types,
        **kwargs,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Exhaustion semantics: `run()` over an always-failing coroutine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_over_an_always_failing_coroutine_exhausts_retries_and_returns_none() -> None:
    """`live/retry.py:145-183` -- with `max_retries=3` and a coroutine that
    always raises a listed exception: `run()` returns `None`, `result` is
    `False`, `retries` is exactly `3` (not 4, not unlimited), and
    `last_exception` holds the LAST raised instance. The function is invoked
    4 times total (1 initial attempt + 3 retries) -- `retries` counts RETRIES,
    not attempts.
    """
    call_count = 0

    async def always_fails() -> str:
        nonlocal call_count
        call_count += 1
        raise _Transient(f"attempt {call_count}")

    manager = _manager(exc_types=(_Transient,))

    result = await manager.run("op", None, always_fails)

    assert result is None
    assert manager.result is False
    assert manager.retries == 3
    assert isinstance(manager.last_exception, _Transient)
    assert str(manager.last_exception) == "attempt 4"
    assert call_count == 4


# ---------------------------------------------------------------------------
# (a) A type NOT in `exc_types` propagates out uncaught
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_exception_type_not_in_exc_types_propagates_uncaught() -> None:
    """`live/retry.py:172` -- `except self.exc_types as e:` only catches what
    is listed. `_Sibling` is unrelated to `_Transient` and is not listed, so
    it must escape `run()` rather than being swallowed into a `None` return.

    This is the property Breezy's fail-closed integrity errors depend on: an
    error the retry manager does not recognise must surface, not vanish.
    """
    call_count = 0

    async def raises_sibling() -> str:
        nonlocal call_count
        call_count += 1
        raise _Sibling("not a transient failure")

    manager = _manager(exc_types=(_Transient,))

    with pytest.raises(_Sibling, match="not a transient failure"):
        await manager.run("op", None, raises_sibling)

    # Escaped on the FIRST attempt -- no retry loop was entered for it.
    assert call_count == 1
    assert manager.retries == 0


# ---------------------------------------------------------------------------
# (b) THE TRAP: a SUBCLASS of a listed exc_type is caught and retried
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_subclass_of_a_listed_exc_type_is_caught_and_retried() -> None:
    """`live/retry.py:172` -- `except self.exc_types as e:` is ORDINARY Python
    `except`, which is `isinstance`-based, not exact-type. `_Leaf` is a
    SUBCLASS of `_Base`, and `exc_types=(_Base,)` therefore catches and
    retries `_Leaf` too -- it is NOT required to appear in `exc_types`
    itself.

    This is the exact trap a settlement-critical Breezy defect hit: listing a
    base class (e.g. a bare `TransportError`) in `exc_types` silently retries
    every subclass raised through it, including ones meant to hard-block as
    integrity alarms. The fix is to list only the leaf types meant to be
    retried -- but that fix is only correct if this isinstance-based dispatch
    is what the framework actually does, which is what this test proves by
    execution rather than by reading the `except` clause and assuming.
    """
    call_count = 0

    async def fails_once_with_a_subclass() -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise _Leaf("leaf failure, subclass of the listed base")
        return "recovered"

    manager = _manager(exc_types=(_Base,))

    result = await manager.run("op", None, fails_once_with_a_subclass)

    assert result == "recovered"
    assert manager.result is True
    assert manager.retries == 1  # one retry consumed catching the _Leaf
    assert call_count == 2


# ---------------------------------------------------------------------------
# (c) `retry_check` returning False vetoes the retry WITHOUT re-raising
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_check_veto_does_not_reraise_it_returns_none_instead() -> None:
    """`live/retry.py:174-183` -- when `retry_check(e)` returns `False`, the
    manager runs `_log_error()`, sets `result = False`, and `return None`.
    It does **not** re-raise the exception. `retry_check` can veto a retry;
    it cannot make the failure propagate to the caller.

    Asserted explicitly with `pytest.raises` wrapped around a `pytest.fail`
    fallback, not merely "the awaited call didn't raise" -- a bare successful
    `await` is not strong evidence on its own that NOTHING could have
    propagated, since a bug that raised a DIFFERENT exception would also make
    a bare "no exception" read wrong if that were the only check.
    """
    call_count = 0

    async def always_fails() -> str:
        nonlocal call_count
        call_count += 1
        raise _Base("vetoed failure")

    def veto(exc: BaseException) -> bool:
        return False

    manager = _manager(exc_types=(_Base,), retry_check=veto)

    try:
        result = await manager.run("op", None, always_fails)
    except BaseException as exc:  # noqa: BLE001 -- deliberately broad: proving NOTHING escapes
        pytest.fail(f"retry_check veto must not re-raise, but {exc!r} escaped run()")

    assert result is None
    assert manager.result is False
    assert isinstance(manager.last_exception, _Base)
    assert str(manager.last_exception) == "vetoed failure"
    # Vetoed on the FIRST attempt -- retry_check runs before retries increments.
    assert manager.retries == 0
    assert call_count == 1


# ---------------------------------------------------------------------------
# Pool acquire/release: no cross-operation state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pool_release_then_acquire_resets_retries_to_zero() -> None:
    """`live/retry.py:206` `clear()`, invoked from `acquire()` (`:321`) on a
    manager popped from the pool -- after a manager accumulates retries,
    `pool.release(m)` followed by `pool.acquire()` returns the SAME manager
    instance with `retries` back to `0`. State is cleared on acquisition, not
    on release, but the caller-visible effect is the same: no leftover retry
    count crosses into the next operation that reuses this manager.
    """
    pool = RetryManagerPool(
        pool_size=1,
        max_retries=3,
        delay_initial_ms=1,
        delay_max_ms=1,
        backoff_factor=2,
        logger=_logger(),
        exc_types=(_Transient,),
    )

    manager = await pool.acquire()

    async def always_fails() -> str:
        raise _Transient("fails")

    await manager.run("op", None, always_fails)
    assert manager.retries == 3  # dirtied

    await pool.release(manager)
    reacquired = await pool.acquire()

    assert reacquired is manager
    assert reacquired.retries == 0


# ---------------------------------------------------------------------------
# Item 5: no server-supplied delay hook exists anywhere in this surface
# ---------------------------------------------------------------------------


def test_get_exponential_backoff_delay_derives_solely_from_attempt_count() -> None:
    """`live/retry.py:24-38` -- `get_exponential_backoff`'s ONLY variable
    input governing the computed delay is `num_attempts` (the others are
    fixed configuration: `delay_initial_ms`, `delay_max_ms`,
    `backoff_factor`, `jitter`). There is no `retry_after`-shaped parameter.
    Asserted via signature introspection, not timing -- a timing assertion
    would be flaky, and the signature is what actually gates whether a
    server-supplied `Retry-After` could ever reach this function.
    """
    params = list(inspect.signature(get_exponential_backoff).parameters)

    assert params == ["num_attempts", "delay_initial_ms", "delay_max_ms", "backoff_factor", "jitter"]
    assert not any("retry_after" in p.lower() or "server" in p.lower() for p in params)


def test_retry_manager_surface_has_no_delay_override_parameter_anywhere() -> None:
    """`live/retry.py:96-113` (`RetryManager.__init__`), `:145-152` (`run`),
    and `:264-289` (`RetryManagerPool.__init__`) -- none of the three
    constructor/call surfaces that could plausibly accept a per-request delay
    override do so. `retry_check` (the one exception-inspection hook that
    exists) is typed `Callable[[BaseException], bool]` -- it can only veto,
    it cannot supply a delay -- pinned by execution below, not just by the
    type hint, since a `bool`-returning callback could still be silently
    reinterpreted at runtime.
    """
    init_params = set(inspect.signature(RetryManager.__init__).parameters)
    run_params = set(inspect.signature(RetryManager.run).parameters)
    pool_init_params = set(inspect.signature(RetryManagerPool.__init__).parameters)

    delay_shaped_names = {"retry_after", "server_delay", "delay_override", "delay_hint"}
    assert not (init_params & delay_shaped_names)
    assert not (run_params & delay_shaped_names)
    assert not (pool_init_params & delay_shaped_names)


@pytest.mark.asyncio
async def test_retry_check_return_value_is_used_only_as_a_bool_never_as_a_delay() -> None:
    """Execution-level companion to the signature checks above: a
    `retry_check` that returns a large truthy integer (60, shaped like a
    "wait 60 seconds" hint) is treated purely as "retry allowed" -- the retry
    proceeds on the configured `delay_initial_ms`/`delay_max_ms` schedule
    (1ms here), not on any value `retry_check` returned. If the return value
    were ever repurposed as a delay, this test would need far longer than a
    few milliseconds to complete; it is bounded well under one second instead.
    """
    import asyncio

    call_count = 0

    async def fails_once() -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise _Transient("transient")
        return "ok"

    def retry_check_returns_a_delay_shaped_int(exc: BaseException) -> bool:
        return 60  # type: ignore[return-value]  # truthy, NOT a real bool -- proves only truthiness matters

    manager = _manager(exc_types=(_Transient,), retry_check=retry_check_returns_a_delay_shaped_int)

    result = await asyncio.wait_for(manager.run("op", None, fails_once), timeout=2.0)

    assert result == "ok"
    assert call_count == 2
