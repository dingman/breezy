"""RED-PENDING-AUT6 (AUT-1 WP5 stage 3, design r3 D11, S3-R9, S3-R39): not collected by the gate.

AUT-1's live proof and heal re-send read AUT-6's delivery evidence through
``breezy.analysis.capture_aut6_contract`` (the per-attempt delivery records under
``evidence/alerts/<date>/`` and the notifier markers under ``evidence/alerts/notify/<date>/``).
This file pins what AUT-1 needs from AUT-6's WRITER, which is not merged yet
(``src/breezy/runtime/alert_delivery.py``, AUT-6 r15 section 3.6.2/3.6.3).

The file name does not match pytest's ``test_*.py`` pattern, so the merge gate does not collect
it and it cannot redden the gate. Running it by path (``pytest
tests/unit/autonomy/pending_aut6_notifier_proof_contract.py``) FAILS today, at the module import
below. Stage 4 (design r3 section 9, items 9 and 10) renames it to
``test_aut6_notifier_proof_contract.py`` once AUT-6 has merged and adds the write-then-read round
trip through AUT-6's real record writer, and it then goes GREEN.
"""

import importlib
import re
from typing import Any, Final

from breezy.analysis.capture_aut6_contract import (
    DELIVERY_RECORD_NAME_RE,
    DELIVERY_SCHEMA,
    NBP_MISSED_MARKER_RE,
    NOTIFIER_MARKER_RE,
)
from breezy.persistence.autonomy.capture_alerts import CAPTURE_ALERT_SEVERITIES

_HEX32: Final = re.compile(r"[0-9a-f]{32}")
#: AUT-6's runtime module; absent until AUT-6 merges, so importing it is where this file fails.
alert_delivery: Any = importlib.import_module("breezy.runtime.alert_delivery")


def test_aut6_exposes_the_record_writer_and_the_proof_bearing_set() -> None:
    assert hasattr(alert_delivery, "DeliveryRecordWriter")
    assert hasattr(alert_delivery, "PROOF_BEARING_EVENTS")


def test_every_critical_capture_event_is_proof_bearing() -> None:
    """Section 3.6.3 scope: every CRITICAL from any site carries a delivery proof, which is what
    makes ``delivered_events`` able to see it."""
    critical = {e for e, severity in CAPTURE_ALERT_SEVERITIES.items() if severity == "CRITICAL"}
    assert critical
    missing = sorted(critical - set(alert_delivery.PROOF_BEARING_EVENTS))
    assert not missing, missing


def test_the_documented_name_shapes_are_the_ones_aut1_reads() -> None:
    """AUT-6 r15 section 3.6.2 and 3.1.1, restated: the shapes AUT-1's readers accept."""
    invocation = "0123456789abcdef0123456789abcdef"
    assert _HEX32.fullmatch(invocation)
    assert NOTIFIER_MARKER_RE.fullmatch(f"breezy-quote-tape.service__{invocation}.delivered.json")
    assert NBP_MISSED_MARKER_RE.fullmatch("NBP_CYCLE_MISSED__1791032400000000000.delivered.json")
    assert DELIVERY_RECORD_NAME_RE.fullmatch("1791032400000000000_daily_d.json")
    assert DELIVERY_SCHEMA == "alert_delivery/v1"
