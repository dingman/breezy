"""TE-2 WP1c STUB (RED): the predeclaration reader and the pin-coverage check."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class PredeclarationError(Exception):
    """Phase B refuses: the predeclaration is unreadable, drifted or not for this Phase A table."""


@dataclass(frozen=True)
class Predeclaration:
    phase_a_table_sha256: str
    thresholds: Mapping[str, Any]
    consumer_map: Mapping[str, str]
    s0i_statuses: Mapping[str, str]
    terminal_climate_day: str
    raw_sha256: str


def thresholds_block() -> dict[str, Any]:
    raise NotImplementedError


def default_consumer_map() -> dict[str, str]:
    raise NotImplementedError


def load_predeclaration(path: Path, phase_a_table: Path) -> Predeclaration:
    raise NotImplementedError


def unpinned_family_modules(repo_root: Path, pinned_paths: Iterable[str]) -> tuple[str, ...]:
    raise NotImplementedError
