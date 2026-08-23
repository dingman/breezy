"""Fixtures shared with `tests/unit/test_ingest_nws_actor.py`.

Contract tests that need a fully-wired `NwsIngestActor` (the WI-11 backlog-
drain tests) reuse the SAME `actor`/`shared`/`clock`/`store`/`store_pair`/
`registry` fixtures the unit suite already proves out, rather than inventing
a parallel harness. Importing them here (a `conftest.py`, autodiscovered by
pytest for every test module under this directory) makes them available to
every test in `tests/contract/` without each test module having to import
and then shadow the same names as function parameters -- the latter is
exactly what pytest fixture injection requires, but it reads to a linter as
an unused-import-redefinition.
"""

from __future__ import annotations

from tests.unit.test_ingest_nws_actor import (
    actor,
    clock,
    registry,
    shared,
    store,
    store_pair,
)

__all__ = ["actor", "clock", "registry", "shared", "store", "store_pair"]
