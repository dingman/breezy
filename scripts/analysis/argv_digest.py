"""AUD-19b/19c (plan §6 C6 step 2): the ONE shared implementation of the
replay driver's run identifier, verified by both the writer (the driver,
AUD-19b) and the reader (AUD-09's scheduled runner, AUD-19c).

Stdlib-only, no `breezy` import: both callers reach this module through the
same sibling-import convention `current_rung_hold_paper_replay.py:44-47`
already uses for `archive_correction_probe.wilson_interval` --
``sys.path.insert(0, str(Path(__file__).resolve().parent))`` followed by a
bare import -- never a `src/breezy` utility (this is scripts-layer analysis
plumbing with no runtime consumer) and never re-implemented inline by either
caller (a second implementation would defeat the round-trip verification
AUD-19c's runner performs).

No `main`, no `argparse`, no `__main__` block: this is a helper module, not
a script, so it never joins `deploy/systemd/replay-daily-run.sh`'s invoked-
script set (AUD-09 §8 B18).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence


def argv_sha256(argv: Sequence[str]) -> str:
    """SHA-256 hex digest of ``"\\n".join(argv)``.

    ``argv`` is the resolved argument vector actually parsed -- the
    arguments after the script path, in the order passed. Chosen over a pid
    or a timestamp precisely because a caller that independently knows the
    vector it passed (AUD-19c's runner) can recompute this value and verify
    it; a pid/timestamp would only ever be readable, never verifiable.
    Order-sensitive and change-sensitive: reordering the same arguments, or
    editing any one of them, changes the digest.
    """
    return hashlib.sha256("\n".join(argv).encode("utf-8")).hexdigest()
