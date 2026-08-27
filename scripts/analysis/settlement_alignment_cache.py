"""Shared settlement-alignment archive cache paths for analysis scripts."""

from __future__ import annotations

from pathlib import Path
from typing import Final

DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR: Final[Path] = (
    Path.home() / ".local/share/breezy/archive/settlement-alignment-cache"
)


class SettlementAlignmentCacheError(FileNotFoundError):
    """Raised when the settlement-alignment archive cache is unavailable."""


def resolve_settlement_alignment_cache_dir(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = path.resolve(strict=False)
    return path


def require_settlement_alignment_cache_dir(raw: str | Path) -> Path:
    cache_dir = resolve_settlement_alignment_cache_dir(raw)
    if not cache_dir.is_dir():
        raise SettlementAlignmentCacheError(
            "settlement-alignment archive cache directory does not exist; "
            f"expected cache directory: {cache_dir}"
        )
    return cache_dir
