"""Exit-code constants for `breezy-quote-tape-ingest` (alertcause 2026-09-27).

Split out of `breezy.runtime.quote_tape_ingest_cli` into a stdlib-only leaf
module so that `breezy.runtime.study_failure_notifier` -- the LAST line of
alert delivery, which must stay importable and runnable even when the rest
of the runtime is broken -- can name these exit codes without importing
`quote_tape_ingest_cli` itself, which pulls in `nautilus_trader` and
`pyarrow` at import time. A broken Nautilus install, a missing `pyarrow`
wheel, or a syntax error anywhere in the ingest module's import chain is
exactly the kind of fault that can make a study unit fail in the first
place; the notifier must never crash before it can send its alert because
of it (L-52: a detector without delivery is not a control).

`quote_tape_ingest_cli` imports these back under the same names, so nothing
there changes.
"""

from __future__ import annotations

#: The console-script name this module's exits describe.
PROGRAM = "breezy-quote-tape-ingest"

EXIT_USAGE = 2

#: At least one instance's outcome was "failed" (a hard per-file conversion
#: failure -- see `quote_tape_ingest_cli`'s module docstring's "Per-file
#: conversion" section). Distinct from `EXIT_OK`'s "ran, even if every
#: instance was skipped": a skip is an ordinary, expected outcome, never a
#: failure. (`EXIT_OK` itself stays in `quote_tape_ingest_cli` -- it is
#: never needed outside that module.)
EXIT_CONVERSION_FAILED = 3

#: EDGE-6 6f: pending deferred work has crossed the stall threshold in
#: ``breezy.runtime.ingest_deferral_streak`` (>= 4 consecutive runs AND
#: >= 60 minutes). Lower precedence than :data:`EXIT_CONVERSION_FAILED` --
#: see `quote_tape_ingest_cli.run` and its module docstring's
#: exit-precedence note.
EXIT_DEFERRAL_STALLED = 4
