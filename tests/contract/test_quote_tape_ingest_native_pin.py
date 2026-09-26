"""Contract pins for the native machinery ING-2 S3a's mirror and A8 detector
depend on. These fail FIRST on a NautilusTrader version bump (``contract``
marker), before anything else in the S3a suite goes red for a confusing
reason.

T-PIN-1 pins native ``convert_stream_to_data``'s own list -> read -> convert
call sequence and kwargs -- the exact shape :func:`_convert_stream_natively`
mirrors. T-PIN-2 pins the signatures of the six native methods this module
calls, plus ``_write_chunk``'s skip-on-exists behaviour and its directory
grouping, which :mod:`breezy.runtime.quote_tape_salvage`'s A8 detector
mirrors independently (Arch S7).

Every spy here WRAPS the native method (calls through to it, never replaces
it) -- verified oracle usage, not a test double standing in for Nautilus.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.model.data import InstrumentStatus, QuoteTick
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.runtime.quote_tape_salvage import _write_data_group
from tests.unit.test_quote_tape_ingest_bounded_read import _status, _write_flat_stream

pytestmark = pytest.mark.contract

IID = InstrumentId.from_str("EUR/USD.SIM")


class TestNativeConvertStreamToDataCallSequence:
    """T-PIN-1."""

    def _make_two_files(self, tmp_path: Path) -> Path:
        instance_dir = tmp_path / "live" / "instance-1"
        _write_flat_stream(
            instance_dir / "instrument_status_0.feather",
            [_status(i) for i in range(3)],
            InstrumentStatus,
        )
        _write_flat_stream(
            instance_dir / "instrument_status_1.feather",
            [_status(i) for i in range(100, 103)],
            InstrumentStatus,
        )
        return tmp_path

    def test_the_call_sequence_and_kwargs_without_other_catalog(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = self._make_two_files(tmp_path)
        catalog = ParquetDataCatalog(str(root))
        calls: list[tuple[str, dict[str, Any]]] = []

        real_list = ParquetDataCatalog._list_feather_data_files
        real_read = ParquetDataCatalog._read_feather_file
        real_convert = ParquetDataCatalog._convert_feather_table_to_parquet

        def list_spy(self: ParquetDataCatalog, **kwargs: Any) -> Any:
            calls.append(("list", kwargs))
            yield from real_list(self, **kwargs)

        def read_spy(self: ParquetDataCatalog, path: str) -> Any:
            result = real_read(self, path)
            calls.append(("read", {"path": path}))
            return result

        def convert_spy(self: ParquetDataCatalog, **kwargs: Any) -> Any:
            calls.append(("convert", kwargs))
            return real_convert(self, **kwargs)

        monkeypatch.setattr(ParquetDataCatalog, "_list_feather_data_files", list_spy)
        monkeypatch.setattr(ParquetDataCatalog, "_read_feather_file", read_spy)
        monkeypatch.setattr(ParquetDataCatalog, "_convert_feather_table_to_parquet", convert_spy)

        catalog.convert_stream_to_data("instance-1", InstrumentStatus, subdirectory="live")

        kinds = [kind for kind, _ in calls]
        assert kinds.count("list") == 1
        assert kinds.count("read") == 2
        assert kinds.count("convert") == 2
        assert kinds == ["list", "read", "convert", "read", "convert"]

        for kind, kwargs in calls:
            if kind != "convert":
                continue
            assert kwargs["used_catalog"] is catalog
            assert kwargs["data_cls"] is InstrumentStatus
            assert kwargs.get("use_ts_event_for_ts_init", False) is False
            assert "feather_table" in kwargs
            assert "feather_path" in kwargs

    def test_the_call_sequence_routes_used_catalog_to_other_catalog(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = self._make_two_files(tmp_path)
        catalog = ParquetDataCatalog(str(root))
        other = ParquetDataCatalog(str(tmp_path / "other"))
        calls: list[tuple[str, dict[str, Any]]] = []

        real_convert = ParquetDataCatalog._convert_feather_table_to_parquet

        def convert_spy(self: ParquetDataCatalog, **kwargs: Any) -> Any:
            calls.append(("convert", kwargs))
            return real_convert(self, **kwargs)

        monkeypatch.setattr(ParquetDataCatalog, "_convert_feather_table_to_parquet", convert_spy)

        catalog.convert_stream_to_data(
            "instance-1", InstrumentStatus, other_catalog=other, subdirectory="live"
        )

        assert len(calls) == 2
        for _kind, kwargs in calls:
            assert kwargs["used_catalog"] is other
        assert len(other.query(data_cls=InstrumentStatus)) == 6
        assert len(catalog.query(data_cls=InstrumentStatus)) == 0


class TestNativeSignaturesArePinned:
    """T-PIN-2."""

    def test_convert_stream_to_data_signature(self) -> None:
        sig = inspect.signature(ParquetDataCatalog.convert_stream_to_data)
        assert list(sig.parameters) == [
            "self",
            "instance_id",
            "data_cls",
            "other_catalog",
            "subdirectory",
            "identifiers",
            "use_ts_event_for_ts_init",
        ]
        assert sig.parameters["other_catalog"].default is None
        assert sig.parameters["subdirectory"].default == "backtest"
        assert sig.parameters["use_ts_event_for_ts_init"].default is False

    def test_read_feather_file_signature(self) -> None:
        sig = inspect.signature(ParquetDataCatalog._read_feather_file)
        assert list(sig.parameters) == ["self", "path"]

    def test_convert_feather_table_to_parquet_signature(self) -> None:
        sig = inspect.signature(ParquetDataCatalog._convert_feather_table_to_parquet)
        assert list(sig.parameters) == [
            "self",
            "feather_table",
            "feather_path",
            "data_cls",
            "used_catalog",
            "use_ts_event_for_ts_init",
        ]
        assert sig.parameters["use_ts_event_for_ts_init"].default is False

    def test_list_feather_data_files_signature(self) -> None:
        sig = inspect.signature(ParquetDataCatalog._list_feather_data_files)
        assert list(sig.parameters) == ["self", "kind", "instance_id", "data_cls", "identifiers"]
        assert sig.parameters["identifiers"].default is None

    def test_apply_stream_conversion_transforms_signature(self) -> None:
        sig = inspect.signature(ParquetDataCatalog._apply_stream_conversion_transforms)
        assert list(sig.parameters) == [
            "table",
            "use_ts_event_for_ts_init",
            "convert_bar_type_to_external",
        ]
        assert sig.parameters["use_ts_event_for_ts_init"].default is False
        assert sig.parameters["convert_bar_type_to_external"].default is False

    def test_handle_table_nautilus_signature(self) -> None:
        sig = inspect.signature(ParquetDataCatalog._handle_table_nautilus)
        assert list(sig.parameters) == [
            "table",
            "data_cls",
            "convert_bar_type_to_external",
            "use_ts_event_for_ts_init",
        ]

    def test_write_chunk_skips_silently_on_an_existing_filename(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Behavioural pin (Arch §7 A8): the exact silent skip A8 detects."""
        catalog = ParquetDataCatalog(str(tmp_path))
        objects = [_status(0), _status(1)]
        catalog.write_data(objects, skip_disjoint_check=True)
        before = list(tmp_path.rglob("*.parquet"))
        assert len(before) == 1

        catalog.write_data(objects, skip_disjoint_check=True)  # same identifier, same interval
        after = list(tmp_path.rglob("*.parquet"))
        assert after == before, "a same-filename write must be silently skipped, never rewritten"
        assert "already exists, skipping write" in capsys.readouterr().out

    def test_write_chunk_directory_grouping_matches_the_a8_detector(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The r3 addition: ``_write_chunk``'s own directory choice, observed
        via a wrapping spy on a two-instrument fixture, equals what the A8
        detector (:func:`_write_data_group` + ``_make_path``) computes for
        the same objects.
        """
        instrument_a = InstrumentId.from_str("EUR/USD.SIM")
        instrument_b = InstrumentId.from_str("GBP/USD.SIM")
        objects = [
            _make_quote(instrument_a, 1),
            _make_quote(instrument_a, 2),
            _make_quote(instrument_b, 1),
        ]
        catalog = ParquetDataCatalog(str(tmp_path))

        real_write_chunk = ParquetDataCatalog._write_chunk
        seen_dirs: set[str] = set()

        def write_chunk_spy(self: ParquetDataCatalog, **kwargs: Any) -> Any:
            seen_dirs.add(
                self._make_path(data_cls=kwargs["data_cls"], identifier=kwargs.get("identifier"))
            )
            return real_write_chunk(self, **kwargs)

        monkeypatch.setattr(ParquetDataCatalog, "_write_chunk", write_chunk_spy)

        catalog.write_data(objects, skip_disjoint_check=True)

        expected_dirs = {
            catalog._make_path(data_cls=cls, identifier=ident)
            for cls, ident in {_write_data_group(obj) for obj in objects}
        }
        assert seen_dirs == expected_dirs


def _make_quote(instrument_id: InstrumentId, ts: int) -> QuoteTick:
    from nautilus_trader.model.objects import Price, Quantity

    return QuoteTick(
        instrument_id=instrument_id,
        bid_price=Price.from_str("1.00000"),
        ask_price=Price.from_str("1.00010"),
        bid_size=Quantity.from_int(1),
        ask_size=Quantity.from_int(1),
        ts_event=ts,
        ts_init=ts,
    )
