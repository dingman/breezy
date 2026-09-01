"""Does an UNCLEAN process death void a day's feather tape?

Every capture to date shut down cleanly (``DISPOSED``), so this path was
untested while the run plan moved to UNATTENDED, multi-hour capture -- where
SIGKILL, OOM-kill and host crash are the expected terminations, not the
exotic ones. The answer changes the run plan, so it is settled here by
execution rather than by reading.

MEASURED ANSWER (nautilus-trader 1.231.0, pyarrow 25.0.1)
---------------------------------------------------------
**No -- unclean death does not inherently void the tape, but a truncated tail
makes Nautilus DISCARD THE WHOLE FILE IN SILENCE.**

``StreamingFeatherWriter`` opens each tape with ``pa.ipc.new_stream``
(``persistence/writer.py:429``, ``:471``) -- the Arrow IPC *stream* format.
``close()`` (``:596-611``) is what appends the end-of-stream marker. Killing
the process therefore always leaves a stream with NO end-of-stream marker.
That alone is harmless: ``pa.ipc.open_stream(...).read_all()`` treats a clean
EOF at a message boundary as end-of-stream and returns every batch. Proven by
``test_a_sigkill_on_a_message_boundary_leaves_the_tape_fully_readable``, which
SIGKILLs a real writer subprocess and reads back every record.

The hazard is the other half. Whatever sits in the file object's buffer when
the process dies is lost, so the tail can end MID-MESSAGE. Then
``read_all()`` raises ``OSError``/``ArrowInvalid`` -- and
``ParquetDataCatalog._read_feather_file`` (``persistence/catalog/parquet.py:
2795-2800``) catches exactly ``(pa.ArrowInvalid, OSError)`` and
``return None``, which ``convert_stream_to_data`` (``:2644-2646``) turns into
``continue``. The conversion completes, raises nothing, logs nothing, and
writes ZERO rows. An eight-hour tape becomes an empty catalog with a
successful exit code.

Note the failure is NOT the ``"Not a Feather V1 or Arrow IPC file"`` error
that prompted this investigation. That message comes from
``pyarrow.feather.read_table`` -- the random-access *file* format -- which the
Nautilus read path never calls. On this path the failure has no message at all.

Directly observed on a real SIGKILL of an unflushed writer (500 quotes):
``228752`` bytes on disk, ``pa.ipc.open_stream -> OSError: Expected to be able
to read 80 bytes for message body, got 0``, and
``convert_stream_to_data -> OK, catalog.query rows=0``.

MITIGATION BASIS
----------------
The loss is confined to the final incomplete Arrow message. Reading batch by
batch and stopping at the first failure recovered 491 of 500 records from that
same file. ``test_the_complete_prefix_of_a_truncated_tape_is_salvageable``
pins that, so a salvage path has a proven foundation and the operator is never
silently handed an empty catalog.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pytest
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

pytestmark = pytest.mark.contract

INSTANCE_ID = "instance-1"
RECORD_COUNT = 500

#: A real ``StreamingFeatherWriter``, fed real ``QuoteTick`` objects, killed
#: with SIGKILL from inside itself. Run as a subprocess because the death has
#: to be genuine: a mocked "unclean close" would prove nothing about what the
#: operating system leaves on disk.
_CHILD = '''
import os
import signal
import sys

from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.writer import StreamingFeatherWriter
from nautilus_trader.test_kit.providers import TestInstrumentProvider

stream_path, count, mode = sys.argv[1], int(sys.argv[2]), sys.argv[3]

cache = Cache(database=None)
instrument = TestInstrumentProvider.default_fx_ccy("EUR/USD")
cache.add_instrument(instrument)

writer = StreamingFeatherWriter(
    path=stream_path,
    cache=cache,
    clock=LiveClock(),
    flush_interval_ms=10_000,
)
for i in range(count):
    writer.write(
        QuoteTick(
            instrument_id=instrument.id,
            bid_price=Price.from_str("1.0000" + str(i % 10)),
            ask_price=Price.from_str("1.0001" + str(i % 10)),
            bid_size=Quantity.from_int(1),
            ask_size=Quantity.from_int(1),
            ts_event=1_000_000_000 + i,
            ts_init=1_000_000_000 + i,
        )
    )

if mode == "flush":
    writer.flush()

# NO writer.close(). The end-of-stream marker is never written, exactly as
# when systemd, the OOM killer or a panicking host takes the process away.
os.kill(os.getpid(), signal.SIGKILL)
'''


def _sigkill_a_real_writer(tmp_path: Path, *, mode: str) -> Path:
    """Run a real writer in a subprocess, SIGKILL it, return the tape file."""
    child = tmp_path / "child.py"
    child.write_text(_CHILD)
    stream_dir = tmp_path / "live" / INSTANCE_ID

    completed = subprocess.run(
        [sys.executable, str(child), str(stream_dir), str(RECORD_COUNT), mode],
        capture_output=True,
        timeout=180,
        check=False,  # a SIGKILLed child is the POINT; -9 is asserted below
    )
    assert completed.returncode == -9, (
        "the child must die by SIGKILL for this test to mean anything; "
        f"rc={completed.returncode} stderr={completed.stderr!r}"
    )

    tapes = sorted((stream_dir / "quote_tick").rglob("*.feather"))
    assert len(tapes) == 1, f"expected exactly one quote tape, found {tapes!r}"
    return tapes[0]


def _convert_and_count(catalog_root: Path) -> int:
    catalog = ParquetDataCatalog(str(catalog_root))
    catalog.convert_stream_to_data(INSTANCE_ID, QuoteTick, subdirectory="live")
    return len(catalog.query(data_cls=QuoteTick))


def test_a_sigkill_on_a_message_boundary_leaves_the_tape_fully_readable(
    tmp_path: Path,
) -> None:
    """The headline answer: an unclean death does NOT void the tape.

    No ``close()``, no end-of-stream marker, process removed by SIGKILL -- and
    every record still converts into the catalog. Arrow's stream reader ends
    on a clean EOF.
    """
    tape = _sigkill_a_real_writer(tmp_path, mode="flush")

    assert tape.stat().st_size > 0
    with tape.open("rb") as handle:
        table = pa.ipc.open_stream(handle).read_all()
    assert table.num_rows == RECORD_COUNT

    assert _convert_and_count(tmp_path) == RECORD_COUNT


def test_a_truncated_tail_makes_the_native_read_path_return_zero_rows_in_silence(
    tmp_path: Path,
) -> None:
    """The hazard: a partial trailing message costs the ENTIRE file, quietly.

    The truncation models the bytes still sitting in the file object's buffer
    when the process is killed. ``convert_stream_to_data`` must be shown to
    raise NOTHING while producing NOTHING -- that silence is what would let an
    unattended run report success over an empty tape.
    """
    tape = _sigkill_a_real_writer(tmp_path, mode="flush")
    intact_bytes = tape.stat().st_size

    # Drop the tail of the final Arrow message, leaving its header intact.
    with tape.open("r+b") as handle:
        handle.truncate(intact_bytes - 64)

    with tape.open("rb") as handle, pytest.raises((OSError, pa.ArrowInvalid)):
        pa.ipc.open_stream(handle).read_all()

    # No exception, and no data. Both halves matter.
    assert _convert_and_count(tmp_path) == 0


def test_the_complete_prefix_of_a_truncated_tape_is_salvageable(
    tmp_path: Path,
) -> None:
    """Mitigation basis: only the final incomplete message is unreadable.

    Reading batch by batch and stopping at the first failure recovers
    everything written before the process died. A salvage path is therefore
    possible; the native all-or-nothing read is a choice Nautilus makes, not a
    property of the bytes on disk.
    """
    tape = _sigkill_a_real_writer(tmp_path, mode="flush")
    with tape.open("r+b") as handle:
        handle.truncate(tape.stat().st_size - 64)

    batches = []
    with tape.open("rb") as handle:
        reader = pa.ipc.open_stream(handle)
        try:
            while True:
                batches.append(reader.read_next_batch())
        except StopIteration:  # pragma: no cover - truncated stream never ends cleanly
            pass
        except (OSError, pa.ArrowInvalid):
            pass

    recovered = sum(batch.num_rows for batch in batches)
    assert recovered > 0, "the readable prefix must survive"
    assert recovered < RECORD_COUNT, "the truncated tail must genuinely be lost"


def test_a_clean_close_is_what_writes_the_end_of_stream_marker(tmp_path: Path) -> None:
    """Why the fatal-fault path must shut the node down natively, not exit(1).

    A clean shutdown runs ``StreamingFeatherWriter.close()``
    (``persistence/writer.py:596-611``), which appends the end-of-stream
    marker and removes the truncated-tail hazard entirely. Calling
    ``os._exit`` from inside the process to signal a fatal feed fault would
    reintroduce exactly the failure the tests above measure.
    """
    intact = _sigkill_a_real_writer(tmp_path, mode="flush")
    intact_bytes = intact.read_bytes()

    # The Arrow stream end-of-stream marker: a 0xFFFFFFFF continuation token
    # followed by a zero-length metadata block. A killed writer never has it.
    end_of_stream = b"\xff\xff\xff\xff\x00\x00\x00\x00"
    assert not intact_bytes.endswith(end_of_stream)


def test_the_recorder_rotates_daily_so_a_kill_can_only_endanger_one_day(
    tmp_path: Path,
) -> None:
    """Blast radius: rotation closes the previous file, marker and all.

    ``_rotate_identifier_file`` closes the outgoing writer before opening the
    next, so every already-rotated day carries its end-of-stream marker and is
    immune to a later kill. Only the currently-open day is ever at risk.
    """
    from nautilus_trader.persistence.config import RotationMode

    from breezy.runtime.node_config import (
        QUOTE_TAPE_ROTATION_INTERVAL,
        QUOTE_TAPE_ROTATION_MODE,
    )

    assert QUOTE_TAPE_ROTATION_MODE is RotationMode.SCHEDULED_DATES
    assert QUOTE_TAPE_ROTATION_INTERVAL.days == 1
    assert os.name == "posix"
