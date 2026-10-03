from __future__ import annotations

import os

if os.environ.get("BREEZY_BWRAP_HOST_PHASE") == "1":
    raise RuntimeError("phase-2 ignore-collect imported a non-registry conftest")
