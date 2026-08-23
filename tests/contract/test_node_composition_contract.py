"""Contract: the four composition facts that fail SILENTLY at deploy time.

Every assertion in this file was executed against the **installed
`nautilus-trader 1.231.0`** (`nautilus_trader.__version__`, asserted below)
before it was written. Nothing here is copied from a plan or from docs: the
plan's line citations for `trader.py` were checked and one was stale (see
"Verified file:line" below).

Why this file exists
--------------------
`tests/unit/test_runtime_actor_wiring.py` already proves the *happy* path:
ids are unique, `Trader.add_actor` is the registration route, and a real
`TradingNode` accepts the actors. None of that fails loudly if a guard is
removed. These four pins do — and each one guards a failure whose production
symptom is "Breezy quietly collects fewer cities" rather than a traceback.

Verified file:line in the installed 1.231.0 (re-check these on a version bump)
-----------------------------------------------------------------------------
* `common/config.py:589-614` -- `ActorFactory.create`, ending in
  `return actor_cls(config)`. **One positional argument. No injection seam.**
* `common/actor.pyx:148-157` -- `Actor.__init__` coerces a `str`
  `config.component_id` into a real `ComponentId`.
* `trading/trader.py:332-334` -- running-trader branch: **logs and returns**.
  (Plan citation `332-334` is correct.)
* `trading/trader.py:336-340` -- duplicate-id branch: raises `RuntimeError`.
  (Plan cited `335-339`; the real range is `336-340`. Off by one -- the plan's
  line numbers are stale, the behaviour is not.)
* `trading/trader.py:342` -- `clock = self._clock.__class__()`, one Clock per
  component.

Version sensitivity
-------------------
Pin 1 asserts that Nautilus offers **no** dependency-injection seam for
Actors. **It SHOULD start failing the day Nautilus grows one.** That is a
signal to revisit `build_ingest_actors` and possibly move to the declarative
`ImportableActorConfig` route -- it is NOT a bug in this test. Read the
failure, do not delete the test.

No test here runs `TradingNode.run()`, calls `build()`, or opens a socket;
one test asserts that last point rather than assuming it.
"""

from __future__ import annotations

import asyncio
import inspect
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import nautilus_trader
import pytest
from nautilus_trader.common.actor import Actor
from nautilus_trader.common.config import ActorConfig, ActorFactory, ImportableActorConfig
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.identifiers import ComponentId
from nautilus_trader.trading.trader import Trader

from breezy.ingest.config import NwsIngestActorConfig
from breezy.ingest.nws_actor import NwsIngestActor
from breezy.persistence.catalog import FilesystemLocality, FilesystemProbe
from breezy.runtime.composition import (
    BreezyIngestRuntime,
    build_ingest_node,
    ingest_runtime,
)
from breezy.runtime.node_config import NWS_INGEST_ACTOR_PATH, actor_component_id
from breezy.runtime.settings import BreezyRuntimeSettings

pytestmark = pytest.mark.contract

PINNED_NAUTILUS_VERSION = "1.231.0"

#: The five Polymarket.us weather sites, per ``src/breezy/registry/sites.toml``.
SITES: tuple[tuple[str, str], ...] = (
    ("polymarket_us", "NYC"),
    ("polymarket_us", "SFO"),
    ("polymarket_us", "MIA"),
    ("polymarket_us", "MDW"),
    ("polymarket_us", "LAX"),
)

#: The id every Actor adopts when ``component_id`` is left unset -- the class
#: name. Verified: ``NwsIngestActorConfig(venue=..., city=...).component_id``
#: is ``None``, and the resulting ``actor.id`` is ``ComponentId("NwsIngestActor")``.
DEFAULT_COLLIDING_ID = ComponentId("NwsIngestActor")

NWS_INGEST_CONFIG_PATH = "breezy.ingest.config:NwsIngestActorConfig"


def _local_probe(path: Path) -> FilesystemProbe:
    """A filesystem probe that never touches a real mount."""
    return FilesystemProbe(
        path=str(path),
        mount_point="/",
        fs_type="ext4",
        locality=FilesystemLocality.LOCAL,
        detail="contract-test probe",
    )


def _settings(tmp_path: Path) -> BreezyRuntimeSettings:
    return BreezyRuntimeSettings(
        trader_id="BREEZY-001",
        sites=SITES,
        catalog_base=tmp_path / "catalog",
        state_db_path=tmp_path / "state" / "breezy.sqlite3",
        poll_interval_seconds=300,
        parse_timeout_ms=250,
        log_level="INFO",
        check_proxy_env=False,
        registry_path=None,
    )


@pytest.fixture
def settings(tmp_path: Path) -> BreezyRuntimeSettings:
    return _settings(tmp_path)


@pytest.fixture
def runtime(settings: BreezyRuntimeSettings) -> Iterator[BreezyIngestRuntime]:
    """One live runtime.

    ``SharedIngestState`` claims a process-wide slot, so exactly one of these
    may exist at a time; the fixture is function-scoped for that reason.
    """
    with ingest_runtime(settings, probe=_local_probe) as rt:
        yield rt


@contextmanager
def _real_trading_node(config: Any) -> Iterator[TradingNode]:
    """A genuine `TradingNode`, constructed only -- never built, never run.

    The loop is supplied explicitly because
    ``common/functions.py:get_event_loop`` refuses to create one under pytest.
    ``node.dispose()`` closes the loop itself, hence the ``is_closed`` guard.
    """
    loop = asyncio.new_event_loop()
    node = TradingNode(config, loop=loop)
    try:
        yield node
    finally:
        for actor in node.trader.actors():
            if isinstance(actor, NwsIngestActor):
                actor.shutdown_executor()
        node.dispose()
        if not loop.is_closed():
            loop.close()


def _make_default_id_actors(runtime: BreezyIngestRuntime) -> list[NwsIngestActor]:
    """Five Actors built the way a careless refactor would: no `component_id`.

    ``build_ingest_actors`` is deliberately NOT called in the same test --
    ``SharedIngestState.register_site_actor`` keys on ``(venue, city)`` and
    would raise ``DuplicateSiteRegistrationError`` on the second claim.
    """
    return [
        NwsIngestActor(NwsIngestActorConfig(venue=venue, city=city), shared=runtime.shared)
        for venue, city in SITES
    ]


# ---------------------------------------------------------------------------
# Version guard -- every pin below is version-scoped
# ---------------------------------------------------------------------------


def test_pins_target_the_installed_nautilus_version() -> None:
    """A version bump must announce itself here, not three pins later."""
    assert nautilus_trader.__version__ == PINNED_NAUTILUS_VERSION


# ---------------------------------------------------------------------------
# PIN 1 -- the declarative route is STRUCTURALLY unusable for this Actor
# ---------------------------------------------------------------------------
#
# `NwsIngestActor.__init__(config, *, shared: SharedIngestState, ...)` needs a
# live container. `ActorFactory.create` ends in `actor_cls(config)` -- exactly
# one positional argument and nowhere to pass `shared`. If someone "tidies"
# `build_ingest_actors` away in favour of `TradingNodeConfig(actors=[...])`,
# the process dies at startup rather than running with private state -- and
# these tests document that it can never work in the first place.


def test_actor_factory_create_has_no_injection_seam() -> None:
    """`ActorFactory.create` ends in `actor_cls(config)` -- one argument.

    SHOULD FAIL when Nautilus grows an injection seam. That is the signal to
    revisit the composition root, not to delete this assertion.
    """
    source = inspect.getsource(ActorFactory.create)

    assert "return actor_cls(config)" in source
    # No kwargs, no container, no context argument anywhere in the factory.
    assert "actor_cls(config, " not in source
    assert "**" not in source


def test_declarative_construction_of_the_ingest_actor_raises_type_error(
    runtime: BreezyIngestRuntime,
) -> None:
    """The full `ImportableActorConfig` -> `ActorFactory.create` route fails.

    `runtime` is requested so the registry-backed config path is exercised
    exactly as production would resolve it. Observed verbatim against 1.231.0:

        TypeError: NwsIngestActor.__init__() missing 1 required keyword-only
        argument: 'shared'
    """
    importable = ImportableActorConfig(
        actor_path=NWS_INGEST_ACTOR_PATH,
        config_path=NWS_INGEST_CONFIG_PATH,
        config={
            "component_id": actor_component_id("polymarket_us", "NYC"),
            "venue": "polymarket_us",
            "city": "NYC",
        },
    )

    with pytest.raises(TypeError) as excinfo:
        ActorFactory.create(importable)

    assert "missing 1 required keyword-only argument" in str(excinfo.value)
    assert "'shared'" in str(excinfo.value)


def test_single_positional_construction_raises_type_error(
    runtime: BreezyIngestRuntime,
) -> None:
    """The same failure, isolated from config resolution."""
    config = NwsIngestActorConfig(
        component_id=actor_component_id("polymarket_us", "NYC"),
        venue="polymarket_us",
        city="NYC",
    )

    with pytest.raises(TypeError) as excinfo:
        NwsIngestActor(config)  # type: ignore[call-arg]

    assert "'shared'" in str(excinfo.value)


# ---------------------------------------------------------------------------
# PIN 2 -- component_id collision, and the str -> ComponentId coercion it rides
# ---------------------------------------------------------------------------


def test_five_configs_without_component_id_all_collapse_to_the_class_name(
    runtime: BreezyIngestRuntime,
) -> None:
    """`ActorConfig.component_id` defaults to `None` -> id is the class name.

    Five distinct sites, one id. This is the whole reason
    ``actor_component_id`` exists.
    """
    actors = _make_default_id_actors(runtime)
    try:
        assert all(a.config.component_id is None for a in actors)
        assert {a.id for a in actors} == {DEFAULT_COLLIDING_ID}
        assert len({str(a.id) for a in actors}) == 1
    finally:
        for actor in actors:
            actor.shutdown_executor()


def test_trader_rejects_the_second_colliding_actor_with_runtime_error(
    runtime: BreezyIngestRuntime,
) -> None:
    """`trading/trader.py:336-340` -- duplicate id raises `RuntimeError`.

    Observed verbatim: ``Already registered an actor with ID NwsIngestActor,
    try specifying a different actor ID.``
    """
    actors = _make_default_id_actors(runtime)
    try:
        with _real_trading_node(runtime.node_config) as node:
            trader = node.trader
            trader.add_actor(actors[0])

            with pytest.raises(RuntimeError) as excinfo:
                trader.add_actor(actors[1])

            assert "Already registered an actor with ID" in str(excinfo.value)
            assert str(DEFAULT_COLLIDING_ID) in str(excinfo.value)
            # Only the first one ever attached: four cities would be lost.
            assert len(trader.actors()) == 1
    finally:
        for actor in actors:
            actor.shutdown_executor()


def test_the_real_configs_do_not_collide_and_all_five_attach(
    runtime: BreezyIngestRuntime,
) -> None:
    """The production path attaches all five, with the five expected ids."""
    loop = asyncio.new_event_loop()
    node = build_ingest_node(runtime, node_factory=lambda cfg: TradingNode(cfg, loop=loop))
    try:
        registered = node.trader.actors()
        expected = {actor_component_id(venue, city) for venue, city in SITES}

        assert len(registered) == len(SITES) == 5
        assert {str(a.id) for a in registered} == expected
        assert len({str(a.id) for a in registered}) == 5
    finally:
        for actor in node.trader.actors():
            if isinstance(actor, NwsIngestActor):
                actor.shutdown_executor()
        node.dispose()
        if not loop.is_closed():
            loop.close()


def test_actor_component_id_returns_a_plain_str() -> None:
    """Breezy hands Nautilus a `str`; the coercion below is what saves it."""
    value = actor_component_id("polymarket_us", "NYC")

    assert type(value) is str
    assert not isinstance(value, ComponentId)
    assert value == "NWS-INGEST-polymarket_us-NYC"


def test_actor_init_coerces_a_str_component_id_into_a_real_component_id(
    runtime: BreezyIngestRuntime,
) -> None:
    """`common/actor.pyx:148-157` -- the coercion the current code relies on.

    [PR-A1]: `actor_component_id` returns a `str` and `NwsIngestActorConfig`
    stores it unchanged, so `actor.id` is a genuine `ComponentId` ONLY because
    `Actor.__init__` converts it. Pin the coercion so a Nautilus change that
    drops it surfaces here instead of as `str`-vs-`ComponentId` key misses
    inside `Trader._actors`.
    """
    loop = asyncio.new_event_loop()
    node = build_ingest_node(runtime, node_factory=lambda cfg: TradingNode(cfg, loop=loop))
    try:
        for actor in node.trader.actors():
            assert isinstance(actor.config.component_id, str)
            assert not isinstance(actor.config.component_id, ComponentId)
            assert isinstance(actor.id, ComponentId)
            assert type(actor.id) is ComponentId
            assert not isinstance(actor.id, str)
            assert str(actor.id) == actor.config.component_id
    finally:
        for actor in node.trader.actors():
            if isinstance(actor, NwsIngestActor):
                actor.shutdown_executor()
        node.dispose()
        if not loop.is_closed():
            loop.close()


# ---------------------------------------------------------------------------
# PIN 3 -- `add_actor` on a RUNNING trader is SILENT
# ---------------------------------------------------------------------------
#
# `trading/trader.py:332-334` logs an error and RETURNS. No exception reaches
# the caller. A refactor that moves actor attachment after `node.run()` would
# collect from zero extra cities and raise nothing, anywhere.


def test_trader_add_actor_source_logs_and_returns_when_running() -> None:
    """Structural pin on the branch itself, independent of log capture."""
    source = inspect.getsource(Trader.add_actor)

    assert "if self.is_running and not self._has_controller:" in source
    assert 'self._log.error("Cannot add an actor/component to a running trader")' in source
    # The running branch returns; it does not raise. Only the duplicate-id
    # branch below it raises, and it raises RuntimeError.
    assert "raise RuntimeError(" in source
    assert "raise ValueError(" not in source


def test_add_actor_after_start_neither_raises_nor_registers(
    runtime: BreezyIngestRuntime,
) -> None:
    """The silent-drop pin.

    A plain Nautilus `Actor` is used as the sentinel that gets the trader into
    ``RUNNING`` -- starting a real `NwsIngestActor` would arm its poll timers,
    which is a different seam and not what this pins. The **late** actor IS a
    real `NwsIngestActor`, so the dropped component is the production one.
    """
    sentinel = Actor(ActorConfig(component_id="CONTRACT-SENTINEL"))
    late = NwsIngestActor(
        NwsIngestActorConfig(
            component_id=actor_component_id("polymarket_us", "NYC"),
            venue="polymarket_us",
            city="NYC",
        ),
        shared=runtime.shared,
    )
    try:
        with _real_trading_node(runtime.node_config) as node:
            trader = node.trader
            trader.add_actor(sentinel)
            trader.start()
            try:
                assert trader.is_running
                # The guard is `is_running AND NOT _has_controller`; with a
                # controller the add would proceed, so pin the absence too.
                assert trader._has_controller is False
                count_before = len(trader.actors())
                assert count_before == 1

                # No exception. None returned. Nothing registered.
                assert trader.add_actor(late) is None

                assert len(trader.actors()) == count_before
                assert str(late.id) not in {str(a.id) for a in trader.actors()}
            finally:
                trader.stop()
    finally:
        late.shutdown_executor()


# ---------------------------------------------------------------------------
# PIN 4 -- building the node performs ZERO network I/O
# ---------------------------------------------------------------------------


def test_building_the_runtime_and_node_opens_no_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every outbound seam is recorded AND blocked for the whole build.

    This does not merely lean on the repo-wide `conftest.py` guard: it
    installs its own recorder over `socket.socket.connect`, `connect_ex`,
    `socket.create_connection` and `socket.getaddrinfo`, then asserts the
    recorder is empty after constructing the runtime, all five Actors and a
    genuine `TradingNode`. A build that resolved a hostname would be caught
    even if it never reached `connect`.
    """
    calls: list[str] = []

    def _record(name: str) -> Any:
        def _blocked(*args: Any, **kwargs: Any) -> Any:
            calls.append(name)
            raise RuntimeError(f"contract test: {name} attempted during node build")

        return _blocked

    monkeypatch.setattr(socket.socket, "connect", _record("socket.connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", _record("socket.connect_ex"))
    monkeypatch.setattr(socket, "create_connection", _record("socket.create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", _record("socket.getaddrinfo"))

    loop = asyncio.new_event_loop()
    with ingest_runtime(_settings(tmp_path), probe=_local_probe) as rt:
        node = build_ingest_node(rt, node_factory=lambda cfg: TradingNode(cfg, loop=loop))
        try:
            assert len(node.trader.actors()) == len(SITES)
            assert calls == []
        finally:
            for actor in node.trader.actors():
                if isinstance(actor, NwsIngestActor):
                    actor.shutdown_executor()
            node.dispose()
            if not loop.is_closed():
                loop.close()

    assert calls == []
