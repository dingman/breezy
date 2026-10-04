"""AUT-1 WP5 stage 3a STUB: the heal duty's I/O (design r3 D6, D7).

Reads the journal, the stall records and the live node directories, writes the write-once heal
records and re-sends the heal and gap alerts. Stage 3 stream S1 fills it in; until then
``run_heal_duty`` raises ``NotImplementedError``. It is wired into the audit CLI in 3c, never
before (S3-R18).
"""

from pathlib import Path

__all__ = ["run_heal_duty"]


def run_heal_duty(data_root: Path, *, now_ns: int, heal_deadline: float) -> int:
    """Run the heal duty once; returns the number of failures (stage 3 S1). ``heal_deadline`` is a
    monotonic instant: running past it, or a ``ScanDeadline``, is a failure."""
    raise NotImplementedError("stage 3 S1: the heal duty")
