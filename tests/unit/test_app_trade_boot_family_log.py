"""AUD-16b: a boot-time ``boot_family`` log line naming the sending family
and the sha256 of the manifest bytes actually loaded.

Reuses the ``run()`` harness from ``test_trade_cli_current_rung_hold.py``
(``RecordingNode``, ``_trade_env``, ``_operator_order_ceiling``,
``_write_today_catalog``, ``_install_family``) rather than redefining it.

Not implemented here: ``test_the_family_line_precedes_the_permit_lines``.
``app/trade.py::main`` (the sole production caller of ``run()``, per
``pyproject.toml``'s ``breezy-trade`` entry point) mints both permits and
logs every permit-related line BEFORE it calls ``run()`` -- the function
this manifest load and its new log line live in. A boot that exits during
permit minting never reaches ``run()`` at all, so no placement inside
``run()`` can precede those lines; writing this test would either fabricate
a false-green assertion or pin a RED that can never go GREEN without moving
manifest resolution into ``main()`` ahead of permit issuance, which is out
of this item's scope. See the AUD-16 return report for the coordinator
decision.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
from pathlib import Path

import pytest

from breezy.app import trade as trade_module
from breezy.app.trade import run
from breezy.runtime.settings import (
    LIVE_OBSERVATIONS_VAR,
    SENDING_FAMILY_ID_VAR,
    TRADE_CATALOG_ROOT_VAR,
)
from breezy.runtime.trade_cli import EXIT_OK
from breezy.runtime.trade_supervisor_core import COMPOSITION_KIND_SUBSCRIBED_MARKERS
from tests.unit.test_trade_cli_current_rung_hold import (  # noqa: F401 -- reused harness
    RecordingNode,
    _clean_nodes,
    _install_family,
    _operator_order_ceiling,
    _trade_env,
    _write_today_catalog,
)

_BOOT_FAMILY_RE = re.compile(
    r"boot_family id=(?P<id>\S+) composition_kind=(?P<composition_kind>\S+) "
    r"status=(?P<status>\S+) manifest_sha256=(?P<manifest_sha256>[0-9a-f]{64})"
)


def _boot_family_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.name == trade_module._BOOT_LOGGER_NAME and r.getMessage().startswith("boot_family ")
    ]


def _boot_one_family(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    family_id: str,
    caplog: pytest.LogCaptureFixture,
) -> tuple[int, Path]:
    _install_family(monkeypatch, tmp_path, family_id=family_id, stations=["LAX"])
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    _write_today_catalog(catalog_root)
    env = _trade_env(
        tmp_path,
        **{
            SENDING_FAMILY_ID_VAR: family_id,
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )
    manifest_path = tmp_path / "families" / f"{family_id}.json"
    with caplog.at_level(logging.INFO):
        code = run(env=env, node_factory=RecordingNode, stderr=io.StringIO())
    return code, manifest_path


def test_a_boot_logs_the_sending_family_id_and_manifest_sha(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    family_id = "pm_us_crh_boot16a"
    code, manifest_path = _boot_one_family(
        monkeypatch, tmp_path, family_id=family_id, caplog=caplog
    )

    assert code == EXIT_OK
    records = _boot_family_records(caplog)
    assert len(records) == 1
    match = _BOOT_FAMILY_RE.fullmatch(records[0].getMessage())
    assert match is not None, records[0].getMessage()
    assert match["id"] == family_id
    assert match["composition_kind"] == "current_rung_hold"
    assert match["status"] == "REGISTERED"
    assert match["manifest_sha256"] == hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def test_a_boot_with_no_sending_family_logs_the_none_line_explicitly(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        code = run(env=_trade_env(tmp_path), node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_OK
    records = _boot_family_records(caplog)
    assert len(records) == 1
    assert records[0].getMessage() == (
        "boot_family id=none composition_kind=none status=none manifest_sha256=none"
    )


def test_the_family_line_format_is_exactly_the_four_pinned_fields_in_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A fifth field or a renamed/reordered key is a test failure here, not a
    silent schema drift discovered later in the log archive."""
    family_id = "pm_us_crh_boot16b"
    _boot_one_family(monkeypatch, tmp_path, family_id=family_id, caplog=caplog)

    records = _boot_family_records(caplog)
    assert len(records) == 1
    message = records[0].getMessage()
    # fullmatch above already pins field order/keys/single-space separators;
    # this additionally pins there is nothing before/after the four fields.
    assert message.startswith("boot_family id=")
    assert message.count(" ") == 4


def test_the_logged_sha_is_the_sha_of_the_bytes_actually_loaded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    family_id = "pm_us_crh_boot16c"
    code, manifest_path = _boot_one_family(
        monkeypatch, tmp_path, family_id=family_id, caplog=caplog
    )
    assert code == EXIT_OK
    first_sha = _BOOT_FAMILY_RE.fullmatch(_boot_family_records(caplog)[0].getMessage())[
        "manifest_sha256"
    ]

    # Mutate the deployed manifest by one whitespace byte -- still valid
    # JSON, so it still loads, but the raw on-disk bytes differ.
    manifest_path.write_text(manifest_path.read_text() + " ")
    caplog.clear()
    catalog_root = tmp_path / "catalog"
    env = _trade_env(
        tmp_path,
        **{
            SENDING_FAMILY_ID_VAR: family_id,
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )
    with caplog.at_level(logging.INFO):
        second_code = run(env=env, node_factory=RecordingNode, stderr=io.StringIO())

    assert second_code == EXIT_OK
    second_sha = _BOOT_FAMILY_RE.fullmatch(_boot_family_records(caplog)[0].getMessage())[
        "manifest_sha256"
    ]
    assert second_sha != first_sha
    assert second_sha == hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def test_the_family_line_never_carries_an_environ_value_or_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The rendered line's four values come only from the loaded manifest and
    ``settings.sending_family_id`` -- never an arbitrary environ value and
    never exception text, even when unrelated environ noise is present."""
    monkeypatch.setenv("BREEZY_TEST_UNRELATED_SENTINEL", "SENTINEL_9f3a7c21")
    family_id = "pm_us_crh_boot16d"
    code, _ = _boot_one_family(monkeypatch, tmp_path, family_id=family_id, caplog=caplog)

    assert code == EXIT_OK
    message = _boot_family_records(caplog)[0].getMessage()
    assert "SENTINEL_9f3a7c21" not in message
    for leak_marker in ("Error", "Traceback", "Exception"):
        assert leak_marker not in message


def test_the_family_line_is_not_a_supervisor_readiness_marker() -> None:
    """Pins ``COMPOSITION_KIND_SUBSCRIBED_MARKERS`` byte-unchanged and free of
    the new ``boot_family`` prefix, so nothing in the supervisor's readiness
    detection can ever key on this observability-only line."""
    assert COMPOSITION_KIND_SUBSCRIBED_MARKERS == {
        "current_rung_hold": "CurrentRungHoldStrategy subscribed",
        "continuous_rung_hold": "ContinuousRungHoldStrategy subscribed",
        "forecast_ladder": "ForecastLadderStrategy subscribed",
    }
    for marker in COMPOSITION_KIND_SUBSCRIBED_MARKERS.values():
        assert "boot_family" not in marker
