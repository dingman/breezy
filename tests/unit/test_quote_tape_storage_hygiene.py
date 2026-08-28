"""The tape's directory on disk, and how big it is allowed to get.

Two properties that only matter once the recorder actually runs, and both of
which are invisible from the parquet itself.

**Permissions.** Nautilus hands the streaming path to ``fsspec``, which calls
``makedirs`` under the process umask -- typically ``0755``, world-readable. The
tape is not a secret, but it is strategy-inferable: which markets Breezy
watches, and from what moment. This repo already has a hardened convention for
its own data roots (``breezy.persistence.catalog.open_station_catalog``: 0700,
symlink-checked before and after the ``mkdir``), and the venue tape was
bypassing it purely because the directory was created by library code.

**Growth.** ``StreamingConfig.rotation_mode`` defaults to
``RotationMode.NO_ROTATION``, which means one ever-growing feather file per
type for the whole process lifetime. A recorder is meant to run for months.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from nautilus_trader.persistence.writer import RotationMode

from breezy.persistence.catalog import CatalogPathError
from breezy.runtime.node_config import (
    QUOTE_TAPE_ROOT_MODE,
    build_quote_tape_node_config,
    prepare_quote_tape_root,
)
from tests.unit.test_quote_tape_recorder import (
    make_data_client_config,
    make_tape_settings,
)


class TestRootPermissions:
    def test_the_root_is_created_private_to_the_owner(self, tmp_path: Path) -> None:
        root = tmp_path / "venue" / "polymarket_us"

        prepare_quote_tape_root(root)

        assert root.is_dir()
        assert stat.S_IMODE(os.lstat(root).st_mode) == QUOTE_TAPE_ROOT_MODE
        assert QUOTE_TAPE_ROOT_MODE == 0o700

    def test_parents_are_created_too_so_a_fresh_host_just_works(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "a" / "b" / "c"

        prepare_quote_tape_root(root)

        assert root.is_dir()

    def test_an_existing_world_readable_root_is_tightened_rather_than_accepted(
        self, tmp_path: Path
    ) -> None:
        """A root created by an earlier, laxer version must not stay lax."""
        root = tmp_path / "venue"
        root.mkdir(parents=True)
        os.chmod(root, 0o755)

        prepare_quote_tape_root(root)

        assert stat.S_IMODE(os.lstat(root).st_mode) == QUOTE_TAPE_ROOT_MODE

    def test_a_symlinked_root_is_refused_rather_than_written_through(
        self, tmp_path: Path
    ) -> None:
        """`mkdir(exist_ok=True)` reports success for a symlink to a directory.

        Every subsequent write would land in the link's target. The repo's
        station-catalog code already refuses this; the venue tape must too.
        """
        real = tmp_path / "elsewhere"
        real.mkdir()
        root = tmp_path / "venue"
        root.symlink_to(real, target_is_directory=True)

        with pytest.raises(CatalogPathError, match="symlink"):
            prepare_quote_tape_root(root)

    def test_a_root_that_is_a_regular_file_is_refused(self, tmp_path: Path) -> None:
        root = tmp_path / "venue"
        root.write_text("not a directory", encoding="utf-8")

        with pytest.raises(CatalogPathError):
            prepare_quote_tape_root(root)

    def test_preparing_twice_is_idempotent(self, tmp_path: Path) -> None:
        root = tmp_path / "venue"

        prepare_quote_tape_root(root)
        prepare_quote_tape_root(root)

        assert stat.S_IMODE(os.lstat(root).st_mode) == QUOTE_TAPE_ROOT_MODE


class TestFileRotation:
    def test_the_stream_rotates_rather_than_growing_without_bound(
        self, tmp_path: Path
    ) -> None:
        """`NO_ROTATION` is an unbounded disk-exhaustion path for a months-long run."""
        config = build_quote_tape_node_config(
            make_tape_settings(tmp_path), make_data_client_config()
        )

        assert config.streaming is not None
        assert config.streaming.rotation_mode != RotationMode.NO_ROTATION

    def test_rotation_is_scheduled_daily_so_a_days_tape_is_one_readable_unit(
        self, tmp_path: Path
    ) -> None:
        """Daily, in UTC, because the study's unit of analysis is a market-day.

        Size-based rotation would cut files at arbitrary instants and make
        "which files cover 2026-08-25" a scan rather than a lookup.
        """
        config = build_quote_tape_node_config(
            make_tape_settings(tmp_path), make_data_client_config()
        )
        streaming = config.streaming

        assert streaming is not None
        assert streaming.rotation_mode == RotationMode.SCHEDULED_DATES
        assert streaming.rotation_timezone == "UTC"

    def test_a_maximum_file_size_is_still_configured_as_a_backstop(
        self, tmp_path: Path
    ) -> None:
        """Scheduled rotation does not bound a single pathological day."""
        config = build_quote_tape_node_config(
            make_tape_settings(tmp_path), make_data_client_config()
        )

        assert config.streaming is not None
        assert config.streaming.max_file_size > 0
