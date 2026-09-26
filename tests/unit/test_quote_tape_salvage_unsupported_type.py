"""FU-7 Unit A: a terminal marker for salvage types Nautilus cannot deserialise.

``ArrowSerializer._deserialize_rust`` (Nautilus 1.231.0,
``serialization/arrow/serializer.py:328-347``) maps ``MarkPriceUpdate``,
``IndexPriceUpdate`` and ``InstrumentClose`` to ``None`` and raises
``NotImplementedError`` -- deterministic and permanent for this Nautilus
version. Before this change, ``salvage_truncated_instance`` caught that error
via the generic ``_ISOLATED_ERRORS`` tuple and left the file unmarked, so
every ``*/15`` ingest run re-attempted (and re-failed) the same salvage,
burning the run's deadline gate for nothing (measured: ~one failure per run,
44 in 12h). This module pins the terminal ``.salvage-unsupported-<name>``
marker that stops the retry, while ``ValueError``/``ArrowInvalid``/``OSError``
keep retrying exactly as before (AC5).

Fixtures reuse the real IPC-writer helpers from
``test_quote_tape_ingest_cli.py:1080-1148`` (L-42: salvage fixtures go
through the real writer, never a hand-built feather file).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import nautilus_trader
import pyarrow as pa
import pytest
from nautilus_trader.model.data import MarkPriceUpdate, QuoteTick
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.serialization.arrow.serializer import ArrowSerializer
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from breezy.persistence.feather_preflight import inspect_feather_file, scan_instance
from breezy.runtime.ingest_deadline import RunDeadline
from breezy.runtime.quote_tape_ingest_cli import default_convert
from breezy.runtime.quote_tape_salvage import (
    SALVAGE_MARKER_PREFIX,
    _is_salvage_marked,
    salvage_truncated_instance,
)

INSTANCE = "instance-1"
SUBDIRECTORY = "live"

#: Mirrors quote_tape_salvage.SALVAGE_UNSUPPORTED_PREFIX -- imported directly
#: below once it exists; kept here only as a RED-phase sentinel comment.


def _quote_tick(index: int) -> QuoteTick:
    instrument = TestInstrumentProvider.default_fx_ccy("EUR/USD")
    return QuoteTick(
        instrument_id=instrument.id,
        bid_price=Price.from_str("1.00000"),
        ask_price=Price.from_str("1.00010"),
        bid_size=Quantity.from_int(1),
        ask_size=Quantity.from_int(1),
        ts_event=1_000_000_000 + index,
        ts_init=1_000_000_000 + index,
    )


def _mark_price(index: int) -> MarkPriceUpdate:
    instrument = TestInstrumentProvider.default_fx_ccy("EUR/USD")
    return MarkPriceUpdate(
        instrument_id=instrument.id,
        value=Price.from_str("1.00000"),
        ts_event=1_000_000_000 + index,
        ts_init=1_000_000_000 + index,
    )


def _write_typed_ipc_stream(
    path: Path, objects: list[Any], data_cls: type, *, close: bool
) -> None:
    """Write ``objects`` as one Arrow IPC stream the salvage path can read.

    Verbatim copy of ``test_quote_tape_ingest_cli.py:1080-1095`` (L-42).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    first = ArrowSerializer.serialize_batch([objects[0]], data_cls=data_cls)
    with path.open("wb") as handle:
        writer = pa.ipc.new_stream(handle, first.schema)
        for obj in objects:
            piece = ArrowSerializer.serialize_batch([obj], data_cls=data_cls)
            if isinstance(piece, pa.RecordBatch):
                writer.write_batch(piece)
            else:
                writer.write_table(piece)
        if close:
            writer.close()


def _truncate_tail(path: Path, *, drop_bytes: int = 64) -> None:
    with path.open("r+b") as handle:
        handle.truncate(path.stat().st_size - drop_bytes)


def _make_truncated_mark_price_file(tmp_path: Path) -> tuple[Path, Path]:
    """A truncated ``MarkPriceUpdate`` feather file under a fresh instance dir."""
    instance_dir = tmp_path / SUBDIRECTORY / INSTANCE
    mark_path = instance_dir / "mark_price_update_0.feather"
    _write_typed_ipc_stream(
        mark_path, [_mark_price(i) for i in range(20)], MarkPriceUpdate, close=False
    )
    _truncate_tail(mark_path)
    return instance_dir, mark_path


class TestUnsupportedTypeGetsATerminalMarker:
    def test_unsupported_type_truncated_file_gets_a_terminal_marker_and_one_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        instance_dir, mark_path = _make_truncated_mark_price_file(tmp_path)
        report = inspect_feather_file(mark_path)
        assert report.is_truncated

        catalog = ParquetDataCatalog(str(tmp_path))
        with caplog.at_level(logging.ERROR, logger="breezy.runtime.quote_tape_salvage"):
            salvage_truncated_instance(
                catalog, instance_dir, INSTANCE, (MarkPriceUpdate,), (report,)
            )

        from breezy.runtime.quote_tape_salvage import SALVAGE_UNSUPPORTED_PREFIX

        marker_path = instance_dir / f"{SALVAGE_UNSUPPORTED_PREFIX}{mark_path.name}"
        assert marker_path.is_file()
        # not the ordinary salvage marker -- this file was never landed
        assert not (instance_dir / f"{SALVAGE_MARKER_PREFIX}{mark_path.name}").is_file()

        error_records = [
            record for record in caplog.records if record.levelno == logging.ERROR
        ]
        assert len(error_records) == 1
        message = error_records[0].getMessage()
        assert "NotImplementedError" in message
        assert "skipped" in message
        assert "reason=unsupported_type" in message
        assert nautilus_trader.__version__ in message

    def test_second_salvage_call_skips_an_unsupported_marked_file_silently(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        instance_dir, mark_path = _make_truncated_mark_price_file(tmp_path)
        report = inspect_feather_file(mark_path)
        catalog = ParquetDataCatalog(str(tmp_path))

        salvage_truncated_instance(catalog, instance_dir, INSTANCE, (MarkPriceUpdate,), (report,))

        with caplog.at_level(logging.ERROR, logger="breezy.runtime.quote_tape_salvage"):
            caplog.clear()
            salvage_truncated_instance(
                catalog, instance_dir, INSTANCE, (MarkPriceUpdate,), (report,)
            )

        assert caplog.records == []

    def test_is_salvage_marked_is_true_for_the_unsupported_marker(self, tmp_path: Path) -> None:
        instance_dir, mark_path = _make_truncated_mark_price_file(tmp_path)
        report = inspect_feather_file(mark_path)
        catalog = ParquetDataCatalog(str(tmp_path))

        assert not _is_salvage_marked(instance_dir, mark_path)
        salvage_truncated_instance(catalog, instance_dir, INSTANCE, (MarkPriceUpdate,), (report,))
        assert _is_salvage_marked(instance_dir, mark_path)

    def test_unsupported_marker_stops_the_deadline_gate_from_admitting_salvage(
        self, tmp_path: Path
    ) -> None:
        instance_dir, mark_path = _make_truncated_mark_price_file(tmp_path)
        report = inspect_feather_file(mark_path)
        catalog = ParquetDataCatalog(str(tmp_path))

        # Mark the file terminal up front, exactly as a prior run would leave it.
        salvage_truncated_instance(catalog, instance_dir, INSTANCE, (MarkPriceUpdate,), (report,))
        assert _is_salvage_marked(instance_dir, mark_path)

        preflight_report = scan_instance(tmp_path, INSTANCE, SUBDIRECTORY)

        deadline = RunDeadline(budget_ns=10**9)
        admit_calls: list[bool] = []
        original_admit = deadline.admit

        def _spy_admit() -> bool:
            admit_calls.append(True)
            return original_admit()

        deadline.admit = _spy_admit  # type: ignore[method-assign]

        from breezy.runtime.quote_tape_ingest_cli import _ingest_instance_per_file

        _ingest_instance_per_file(
            catalog,
            tmp_path,
            INSTANCE,
            SUBDIRECTORY,
            (MarkPriceUpdate,),
            frozenset(),
            preflight_report,
            instance_is_dead=True,
            convert_fn=default_convert,
            dry_run=False,
            deadline=deadline,
        )

        assert admit_calls == []

    def test_value_error_during_salvage_still_leaves_no_marker_and_retries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Characterisation pin (L-33): ``ValueError`` must NOT reach the new
        terminal branch. Mutation evidence -- routing ``ValueError`` into the
        terminal branch (e.g. widening the new ``except NotImplementedError``
        clause to catch ``ValueError`` too) makes this fail: the file would
        gain a ``.salvage-unsupported-`` marker and the second call would
        stay silent instead of logging and retrying again.
        """
        instance_dir, mark_path = _make_truncated_mark_price_file(tmp_path)
        report = inspect_feather_file(mark_path)
        catalog = ParquetDataCatalog(str(tmp_path))

        def _raise_value_error(*args: Any, **kwargs: Any) -> Any:
            raise ValueError("boom")

        monkeypatch.setattr(
            "breezy.runtime.quote_tape_salvage._salvage_one_file", _raise_value_error
        )

        with caplog.at_level(logging.ERROR, logger="breezy.runtime.quote_tape_salvage"):
            salvage_truncated_instance(
                catalog, instance_dir, INSTANCE, (MarkPriceUpdate,), (report,)
            )

        from breezy.runtime.quote_tape_salvage import SALVAGE_UNSUPPORTED_PREFIX

        assert not (instance_dir / f"{SALVAGE_UNSUPPORTED_PREFIX}{mark_path.name}").is_file()
        assert not (instance_dir / f"{SALVAGE_MARKER_PREFIX}{mark_path.name}").is_file()
        assert any("ValueError" in record.getMessage() for record in caplog.records)

        caplog.clear()
        with caplog.at_level(logging.ERROR, logger="breezy.runtime.quote_tape_salvage"):
            salvage_truncated_instance(
                catalog, instance_dir, INSTANCE, (MarkPriceUpdate,), (report,)
            )
        # unmarked -- a second call retries and logs again
        assert len(caplog.records) == 1
