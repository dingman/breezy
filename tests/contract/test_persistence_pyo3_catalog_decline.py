"""Contract test settling the **pyo3 catalog** decline.

`docs/plans/WEATHER_INGESTION_PROPOSAL.md` §4.1/§10 declines the pyo3
`ParquetDataCatalog` -- despite its immunity to the pyarrow schema-inference drift
documented in §4.1 -- on the grounds that "its on-disk layout is incompatible with
the Python catalog's, which reads **0 records** from a pyo3-written catalog".

Two thirds of that decline were already re-verifiable by reading source:

* `backtest/node.py:708-713` -- `BacktestNode.load_catalog` unconditionally
  constructs the **Python** `ParquetDataCatalog`, so anything the Python catalog
  cannot read is unreachable from `BacktestDataConfig` replay;
* `core/nautilus_pyo3.pyi:5225-5231` -- `write_custom_data(data: list[object], ...)`
  is typed against pyo3 objects, not Cython `Data` subclasses.

The remaining third -- the layout claim itself -- rested on a single measurement in
a shell that no longer exists. This module pins it by execution against the
installed **nautilus-trader 1.231.0**, and pins a *stronger* prior gate the
proposal did not record.

What is actually true on 1.231.0
--------------------------------
**Gate 1 (prior, and decisive on its own): Breezy's record types cannot enter the
pyo3 catalog at all.** `NwsClimateDay` is a hand-written Cython `Data` subclass
carrying a **Python** `register_arrow` codec. The pyo3 catalog requires the Rust
record-batch codec protocol instead -- `decode_record_batch_py(metadata, batch)`
as a classmethod and `encode_record_batch_py(items)` on instances
(`nautilus_pyo3.register_custom_data_class.__doc__`; `CustomData.__doc__` states
outright that "Custom data is always Rust-defined"). Our class implements neither,
so it is refused at three separate points before any byte is written:

===============================================  ===========  ==============================================
call                                             raises       message (substring pinned below)
===============================================  ===========  ==============================================
`register_custom_data_class(NwsClimateDay)`      `TypeError`  "must have decode_record_batch_py"
`write_custom_data([record])`                    `TypeError`  "requires CustomData wrappers"
`write_custom_data([pyo3.CustomData(..)])`       `OSError`    "is not registered for Arrow encoding"
===============================================  ===========  ==============================================

The Cython `nautilus_trader.model.data.CustomData` wrapper is rejected by the same
`TypeError` as a bare record -- only the pyo3 `CustomData` is accepted as a
container, and it then fails on the missing Rust codec.

**Gate 2: the layout claim is confirmed, but its stated mechanism is imprecise.**
Measured with a `@customdataclass_pyo3` probe type that *both* catalogs can write
(so the only variable is the catalog), the Python catalog reads **0** records from
a pyo3-written root while reading 3 from its own -- silently, with no exception.
The cause is **purely the directory-naming convention**, not the schema:

* pyo3 writes  ``data/custom/<PascalCaseClassName>/<start>_<end>.parquet``
* Python writes ``data/custom_<snake_case_class_name>/<start>_<end>.parquet``
  (`persistence/funcs.py::class_to_filename` + `parquet.py:2465-2479::_make_path`)

`_make_path` looks only under the snake_case path, finds no directory, and returns
`[]`. Relocating the *unmodified* pyo3 parquet file into the Python catalog's
directory name makes all three records decode correctly -- so the pyo3 payload
(which carries an extra ``data_type`` column and ``type_name`` schema metadata) is
readable by the Python decoder. "On-disk layout incompatible" is right in outcome;
"schema incompatible" would have been wrong.

Why this matters to Breezy if it ever changes
---------------------------------------------
Both gates are load-bearing for a decline recorded in §10, so a RED here is a
signal to **re-open that decision**, not to patch the test:

* If gate 1 relaxes (the pyo3 catalog accepts a Python-registered `register_arrow`
  class), Breezy could gain the pyo3 catalog's **schema-drift immunity**, which
  §4.1 documents we currently forgo -- our residual hole is a nullable ``*_flag``
  column dropped alongside a present value, undetected and coerced to `None`.
* If gate 2 relaxes (the two catalogs converge on one directory convention), the
  second half of the decline -- "adopting pyo3 forfeits `BacktestDataConfig`
  replay" -- stops being true, because `BacktestNode.load_catalog` would then find
  the rows.
* Conversely, if gate 2 *changes shape* -- e.g. the Python catalog starts reading
  the pyo3 layout **partially** -- that is worse than either state, because today's
  failure is a clean, total 0. A partial read would put a subset of settlement
  records into a backtest with no error, which is the silent-wrong-answer class
  this suite exists to prevent.

Import-time note
----------------
This module MUST NOT carry ``from __future__ import annotations``. PEP 563
stringifies annotations, and `customdataclass` inspects them at class-definition
time: adding it makes the probe class below fail to define with
``TypeError: Unsupported custom data annotation: 'str'``.

Defining the probe class registers it in three process-global registries
(`register_arrow`, `register_serializable_type`, and the pyo3 custom-data
registry). The name is deliberately unique to this module; re-registering the same
class name elsewhere raises.

Two symbols used below are **absent from `core/nautilus_pyo3.pyi` yet present at
runtime**: `register_custom_data_class` and `ParquetDataCatalog.query_custom_data`.
Grepping the stub to prove either does not exist yields a false negative -- use
`dir(nautilus_pyo3)`. The project's configured `mypy` gate covers `src/` only, so
this does not affect it; an ad-hoc `mypy --strict` on this file reports both as
`attr-defined`, which is a stub gap upstream, not a defect here.
"""

import datetime as dt
import hashlib
import shutil
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest
from nautilus_trader.core import nautilus_pyo3
from nautilus_trader.core.data import Data
from nautilus_trader.model.custom import customdataclass_pyo3
from nautilus_trader.model.data import CustomData, DataType
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.persistence.funcs import class_to_filename

from breezy.domain.nws_climate_day import CLIMATE_DAY_SCHEMA_VERSION, NwsClimateDay

pytestmark = pytest.mark.contract

_DAY = dt.date(2026, 8, 22)
_ISSUED_NS = int(dt.datetime(2026, 8, 23, 6, 27, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_RETRIEVED_NS = int(dt.datetime(2026, 8, 23, 6, 31, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_DAY_END_NS = int(dt.datetime(2026, 8, 23, 5, 0, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_SHA = hashlib.sha256(b"CDUS41 KOKX 230627").hexdigest()


def make_climate_day(**overrides: Any) -> NwsClimateDay:
    kwargs: dict[str, Any] = {
        "station": "NYC",
        "climate_day": _DAY,
        "tmax_f": 84,
        "tmin_f": 63,
        "tavg_f": 74,
        "tmax_flag": None,
        "tmin_flag": None,
        "tavg_flag": None,
        "is_final": True,
        "correction_flag": False,
        "revision_seq": 1,
        "is_superseded": False,
        "issuing_office": "KOKX",
        "issuance_time_ns": _ISSUED_NS,
        "retrieved_at_ns": _RETRIEVED_NS,
        "parser_version": "pyiem==1.27.0",
        "registry_version": "1.0.0",
        "raw_sha256": _SHA,
        "source_channel": "api.weather.gov/products/types/CLI/locations/NYC",
        "schema_version": CLIMATE_DAY_SCHEMA_VERSION,
        "ts_event": _DAY_END_NS,
    }
    kwargs.update(overrides)
    return NwsClimateDay(**kwargs)


# ---------------------------------------------------------------------------
# Gate 1 -- our real record type never reaches the pyo3 catalog
# ---------------------------------------------------------------------------


def test_pyo3_catalog_cannot_register_our_record_class() -> None:
    """`register_custom_data_class` refuses a Cython `Data` subclass.

    Registration is the documented precondition for `write_custom_data`. It
    demands the Rust record-batch codec; our class carries the Python
    `register_arrow` codec instead, and the two registries are disjoint.
    """
    assert not hasattr(NwsClimateDay, "decode_record_batch_py")
    assert not hasattr(NwsClimateDay, "encode_record_batch_py")

    with pytest.raises(TypeError) as excinfo:
        nautilus_pyo3.register_custom_data_class(NwsClimateDay)

    assert "decode_record_batch_py" in str(excinfo.value)


def test_pyo3_catalog_refuses_our_record_at_every_wrapping(tmp_path: Path) -> None:
    """Bare, Cython-wrapped, and pyo3-wrapped all fail -- with two different types.

    Pinning all three matters because they fail for *different* reasons and a
    future version could relax any one of them independently. The pyo3 `CustomData`
    wrapper is the only accepted container, and it gets furthest -- far enough to
    name the real blocker (Arrow encoding registration), and still zero bytes on
    disk.
    """
    catalog = nautilus_pyo3.ParquetDataCatalog(str(tmp_path))
    record = make_climate_day()

    with pytest.raises(TypeError) as bare:
        catalog.write_custom_data([record])
    assert "requires CustomData wrappers" in str(bare.value)

    # The *Cython* CustomData wrapper is not the wrapper it means.
    with pytest.raises(TypeError) as cython_wrapped:
        catalog.write_custom_data([CustomData(DataType(NwsClimateDay), record)])
    assert "requires CustomData wrappers" in str(cython_wrapped.value)

    # The pyo3 wrapper is accepted as a container -- it duck-types ts_event/ts_init
    # off our record -- and then fails on the missing Rust codec.
    pyo3_wrapped = nautilus_pyo3.CustomData(
        nautilus_pyo3.DataType(NwsClimateDay.__name__),
        record,
    )
    assert pyo3_wrapped.ts_init == _RETRIEVED_NS

    with pytest.raises(OSError) as encoded:
        catalog.write_custom_data([pyo3_wrapped])
    assert "is not registered for Arrow encoding" in str(encoded.value)

    assert list(tmp_path.rglob("*.parquet")) == []


# ---------------------------------------------------------------------------
# Gate 2 -- the layout divergence, measured with a type both catalogs accept
# ---------------------------------------------------------------------------


@customdataclass_pyo3()
class Pyo3LayoutProbe(Data):
    """Throwaway probe type -- NOT a Breezy record type, and never persisted.

    `customdataclass_pyo3` registers the class with *both* the Python
    `register_arrow` registry and the pyo3 codec protocol, so both catalogs can
    write the same objects. That isolates the variable under test to the catalog
    implementation. Breezy's own types cannot do this -- see gate 1 -- which is
    exactly why the layout question needs a proxy to be measurable at all.
    """

    station: str = ""
    tmax_f: int = 0


nautilus_pyo3.register_custom_data_class(Pyo3LayoutProbe)


def _probe_records() -> list[Pyo3LayoutProbe]:
    return [
        Pyo3LayoutProbe(
            station="NYC",
            tmax_f=80 + index,
            ts_event=1_000_000_000 * (index + 1),
            ts_init=2_000_000_000 * (index + 1),
        )
        for index in range(3)
    ]


def _relative_dirs(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_dir())


def test_python_catalog_reads_zero_records_from_a_pyo3_written_catalog(
    tmp_path: Path,
) -> None:
    """SETTLED: the §10 "reads 0 records" claim reproduces, and it is silent.

    Same class, same three records, two catalogs. Each reads its own root fine;
    the Python catalog reads the pyo3 root as an empty catalog -- no exception, no
    warning, no log. That silence is the reason this is a decline rather than a
    migration: a half-migrated deployment would produce empty backtests, not errors.
    """
    pyo3_root = tmp_path / "pyo3"
    python_root = tmp_path / "python"
    pyo3_root.mkdir()
    python_root.mkdir()

    records = _probe_records()

    pyo3_catalog = nautilus_pyo3.ParquetDataCatalog(str(pyo3_root))
    pyo3_catalog.write_custom_data(
        [
            nautilus_pyo3.CustomData(nautilus_pyo3.DataType(Pyo3LayoutProbe.__name__), record)
            for record in records
        ],
    )

    python_catalog = ParquetDataCatalog(str(python_root))
    python_catalog.write_data(list(records))

    # The divergence, stated as the directory name each side chose.
    assert _relative_dirs(pyo3_root) == ["data", "data/custom", "data/custom/Pyo3LayoutProbe"]
    assert _relative_dirs(python_root) == ["data", "data/custom_pyo3_layout_probe"]
    assert class_to_filename(Pyo3LayoutProbe) == "custom_pyo3_layout_probe"

    # Each catalog reads its own root.
    assert len(pyo3_catalog.query_custom_data(Pyo3LayoutProbe.__name__)) == 3
    assert len(python_catalog.query(data_cls=Pyo3LayoutProbe)) == 3

    # The Python catalog reads the pyo3 root as empty -- silently.
    cross_reader = ParquetDataCatalog(str(pyo3_root))
    assert cross_reader.query(data_cls=Pyo3LayoutProbe) == []
    assert cross_reader.custom_data(cls=Pyo3LayoutProbe) == []


def test_the_incompatibility_is_the_directory_name_not_the_parquet_payload(
    tmp_path: Path,
) -> None:
    """The proposal's *mechanism* is narrower than "layout incompatible" implies.

    Copy the pyo3-written parquet file, byte for byte, into the directory name the
    Python catalog looks under. All three records decode -- extra ``data_type``
    column and ``type_name`` schema metadata and all.

    So the payload is compatible and only the path is not. Recorded here so nobody
    later reads §10 as "the pyo3 parquet format is unreadable" and rules out a
    future convergence on that basis. It also means the failure is a *pure* miss:
    nothing is partially read, which is the only reason the 0 is safe.
    """
    pyo3_root = tmp_path / "pyo3"
    relocated_root = tmp_path / "relocated"
    pyo3_root.mkdir()
    relocated_root.mkdir()

    pyo3_catalog = nautilus_pyo3.ParquetDataCatalog(str(pyo3_root))
    pyo3_catalog.write_custom_data(
        [
            nautilus_pyo3.CustomData(nautilus_pyo3.DataType(Pyo3LayoutProbe.__name__), record)
            for record in _probe_records()
        ],
    )

    (written,) = list(pyo3_root.rglob("*.parquet"))

    # The pyo3 payload carries two things the Python writer does not emit.
    written_schema = pq.read_schema(written)
    assert "data_type" in written_schema.names
    assert written_schema.metadata == {b"type_name": b"Pyo3LayoutProbe"}

    destination = relocated_root / "data" / class_to_filename(Pyo3LayoutProbe)
    destination.mkdir(parents=True)
    shutil.copy(written, destination / written.name)

    relocated = ParquetDataCatalog(str(relocated_root)).query(data_cls=Pyo3LayoutProbe)

    assert len(relocated) == 3
    assert [wrapper.data.tmax_f for wrapper in relocated] == [80, 81, 82]
    assert [wrapper.data.ts_init for wrapper in relocated] == [
        2_000_000_000,
        4_000_000_000,
        6_000_000_000,
    ]
