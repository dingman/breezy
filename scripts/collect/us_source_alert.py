"""F13-C1 S4: the alert webhook poster -- the single sanctioned POST under ``scripts/collect``.

It is NOT a data transport. It sends one small JSON object to the operator's alert sink URL
(read from ``alerts.env`` by ``us_source_guards``), https only, with a closed key set, and it
never raises and never logs the URL (a webhook URL is a bearer secret).
"""

from __future__ import annotations

import json
import sys
import urllib.request
from collections.abc import Callable
from typing import Any, Final
from urllib.parse import urlsplit

__all__ = ["post_alert"]

_TIMEOUT_S: Final[float] = 10.0
_MAX_DETAIL_CHARS: Final[int] = 500
_OK_STATUSES: Final[range] = range(200, 300)

Opener = Callable[..., Any]


def post_alert(
    url: str,
    event: str,
    source: str,
    detail: str,
    *,
    opener: Opener = urllib.request.urlopen,
    timeout_s: float = _TIMEOUT_S,
) -> bool:
    """POST ``{event, source, detail}``; True only on a 2xx. Every failure is swallowed."""
    if urlsplit(url).scheme != "https":
        print("alert: sink refused (not https)", file=sys.stderr)
        return False
    body = json.dumps(
        {"event": event, "source": source, "detail": detail[:_MAX_DETAIL_CHARS]},
        sort_keys=True,
    ).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with opener(request, timeout=timeout_s) as response:
            return int(response.status) in _OK_STATUSES
    except Exception as exc:  # noqa: BLE001 - an alert failure must never mask the cycle
        print(f"alert: sink unreachable ({type(exc).__name__})", file=sys.stderr)
        return False
