"""CF-6: the live NWS ingest test must never hardcode a personal contact email.

``tests/live/test_nws_live_ingest.py`` used to embed a real, personally
identifiable address directly in its source as the live ``User-Agent``
contact. NWS's own API etiquette wants a monitored contact, but the correct
way to supply one is the existing ``BREEZY_USER_AGENT`` environment variable
every other live probe in this repo already reads
(``breezy.ingest.http.USER_AGENT_ENV_VAR`` -- see e.g.
``tests/live/test_open_meteo_previous_runs_probe_live.py``,
``tests/live/test_iem_afos_forecast_pil_probe_live.py``), never a literal
committed to source control.

This is a pure source-text check -- it does not import the live-marked
module -- so it runs in the default (non-``live``) suite and catches a
regression the moment anyone hardcodes a new email literal back into that
file.
"""

from __future__ import annotations

import re
from pathlib import Path

_EMAIL_LITERAL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

_LIVE_NWS_INGEST_TEST = Path(__file__).resolve().parents[1] / "live" / "test_nws_live_ingest.py"


def test_live_nws_ingest_test_has_no_email_literal() -> None:
    """CF-6: the file must read its contact from BREEZY_USER_AGENT, not embed one."""
    source = _LIVE_NWS_INGEST_TEST.read_text(encoding="utf-8")

    match = _EMAIL_LITERAL.search(source)
    assert match is None, (
        "tests/live/test_nws_live_ingest.py hardcodes an email-address "
        f"literal ({match.group(0)!r}); read the contact from "
        "BREEZY_USER_AGENT instead (see breezy.ingest.http.USER_AGENT_ENV_VAR)"
    )
