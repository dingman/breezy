"""AUD-05 D-F: a failing family tally pages once per family per UTC day."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "scripts" / "analysis"

_LOG = """\
Traceback (most recent call last):
  File "family_tally_v2.py", line 666, in build_family_tally_v2
    raise ValueError("filled_takes pnl $12.50")
ValueError: filled_takes pnl $12.50
"""


def _load() -> ModuleType:
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    path = _SCRIPTS / "family_tally_v2.py"
    spec = importlib.util.spec_from_file_location("family_tally_v2_alert", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Sink:
    def __init__(self) -> None:
        self.payloads: list[object] = []

    def emit(self, payload: object) -> None:
        self.payloads.append(payload)


def test_a_failing_tally_emits_a_critical_alert_through_the_sink(tmp_path: Path) -> None:
    mod = _load()
    sink = _Sink()
    emitted = mod.emit_family_tally_failure_alert(
        family_id="pm_us_crh_v4",
        log_text=_LOG,
        latch_path=tmp_path / ".alert_latch.json",
        today_utc="2026-09-24",
        sink=sink,
    )
    assert emitted is True
    assert len(sink.payloads) == 1
    payload = sink.payloads[0]
    assert payload.severity == "CRITICAL"
    assert payload.event == "FAMILY_TALLY_FAILED"
    assert payload.site == "breezy-family-tally@pm_us_crh_v4"


def test_the_failure_alert_fires_once_per_family_per_day(tmp_path: Path) -> None:
    mod = _load()
    sink = _Sink()
    latch = tmp_path / ".alert_latch.json"
    kwargs = {
        "log_text": _LOG,
        "latch_path": latch,
        "today_utc": "2026-09-24",
        "sink": sink,
    }
    assert mod.emit_family_tally_failure_alert(family_id="pm_us_crh_v4", **kwargs) is True
    assert mod.emit_family_tally_failure_alert(family_id="pm_us_crh_v4", **kwargs) is False
    assert len(sink.payloads) == 1
    assert mod.emit_family_tally_failure_alert(family_id="pm_us_crh_cont", **kwargs) is True
    assert len(sink.payloads) == 2


def test_the_failure_alert_carries_no_currency_denominated_field(tmp_path: Path) -> None:
    mod = _load()
    sink = _Sink()
    mod.emit_family_tally_failure_alert(
        family_id="pm_us_crh_v4",
        log_text=_LOG,
        latch_path=tmp_path / ".alert_latch.json",
        today_utc="2026-09-24",
        sink=sink,
    )
    payload = sink.payloads[0]
    body = payload.to_dict()
    assert set(body) == {"severity", "event", "site", "detail"}
    assert "$" not in payload.detail
    assert "12.50" not in payload.detail
    assert payload.detail == "ValueError at family_tally_v2.py:666"
