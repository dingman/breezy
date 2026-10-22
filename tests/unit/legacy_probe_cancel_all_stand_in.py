"""TEST-ONLY stand-in for the retired legacy cancel-all sender (ARM B7, S4 r4 WP6).

``scripts/venue/polymarket_us_write_signing_probe.py::_signed_post_cancel_all`` now refuses
unconditionally (pinned in ``test_polymarket_us_cancel_transport.py``). The two legacy flows
(``run_probe`` and ``run_sequence``) keep their own bookkeeping tests, which need a sender that
completes. This stand-in lives under ``tests/`` (outside the N5 ``src``/``scripts`` scan), is
installed per test with ``monkeypatch`` and never reaches a venue: every caller drives a stub
write client. It reproduces the retired body so those flow tests keep their coverage.
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

import pytest

_PROBE: ModuleType | None = None


async def _signed_post_cancel_all(
    write_client: Any, api_base_url: str, credentials: Any, signer: Any, clock: Any
) -> tuple[int, str | None]:
    """The retired body, module-level so source-inspecting tests can parse it."""
    probe = _PROBE
    assert probe is not None
    status, response_type, _body = await probe._signed_post(
        write_client,
        api_base_url,
        credentials,
        signer,
        clock,
        path=probe._CANCEL_ALL_PATH,
        body={},
    )
    return status, response_type


def install(monkeypatch: pytest.MonkeyPatch, probe: ModuleType) -> None:
    """Replace the probe's refusing sender with the retired body, for this test only."""
    monkeypatch.setattr(sys.modules[__name__], "_PROBE", probe)
    monkeypatch.setattr(probe, "_signed_post_cancel_all", _signed_post_cancel_all)
