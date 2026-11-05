"""Path policy for the durable IEM archive cache and the backed-up archive dataset.

This module is stdlib-only on purpose: the backup script duplicates
``BACKED_UP_ARCHIVE_DATASET_DIR`` rather than importing here, and a unit test
AST-pins the two expressions equal. ``src/`` never imports ``scripts/``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

__all__ = [
    "BACKED_UP_ARCHIVE_DATASET_DIR",
    "DEFAULT_IEM_CACHE_DIR",
]

BACKED_UP_ARCHIVE_DATASET_DIR: Final[Path] = (
    Path.home() / ".local/share/breezy/archive/settlement-alignment-cache"
)

DEFAULT_IEM_CACHE_DIR: Final[Path] = Path.home() / ".local/share/breezy/archive/iem-asos-1min"
