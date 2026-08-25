"""Pin the optional `polymarket-us` SDK version used by the adapter."""

from __future__ import annotations

import tomllib
from importlib import metadata
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MANDATED_POLYMARKET_US_VERSION = "0.1.2"


def test_pyproject_declares_polymarket_us_as_optional_exact_pin() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["optional-dependencies"]["polymarket-us"] == [
        f"polymarket-us=={MANDATED_POLYMARKET_US_VERSION}"
    ]


def test_installed_polymarket_us_matches_the_mandated_pin() -> None:
    polymarket_us = pytest.importorskip("polymarket_us")

    assert metadata.version("polymarket-us") == MANDATED_POLYMARKET_US_VERSION
    assert polymarket_us.__name__ == "polymarket_us"
