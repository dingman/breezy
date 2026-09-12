"""Shared hygiene helper for a new ``AlertPayload.detail`` emit site (SP-6).

``AlertPayload.detail`` (``runtime/health.py``) is already forbidden, by
convention, from carrying a full state dump, an absolute filesystem path,
a raw upstream HTTP body/header, or ``user_agent_contact`` -- but that ban
is enforced by CALLER discipline, not by the dataclass itself, which
cannot tell a full state dump from a short sentence.

:func:`assert_payload_detail_is_safe` is a cheap, defence-in-depth check
CALLED at every new emit site this plan adds (A6, A7, A11, A12): the
value in question is always a closed-enum member today, so this never
rejects a real caller -- it exists so a FUTURE enum edit that accidentally
smuggles in a path, a URL, an ``@``, or an oversize string fails loudly at
the emit site instead of shipping silently.
"""

from __future__ import annotations

import re

from breezy.runtime.health import MAX_ALERT_DETAIL_CHARS

__all__ = ["assert_payload_detail_is_safe"]

_ABSOLUTE_PATH_TOKEN_RE = re.compile(r"(?:^|\s)/\S+")
_URL_RE = re.compile(r"https?://", re.IGNORECASE)


def assert_payload_detail_is_safe(detail: str) -> None:
    """Raise ``ValueError`` naming the violated RULE only -- never the
    offending text -- when ``detail`` looks like an absolute filesystem
    path, a URL, carries an ``@`` character, or exceeds
    ``MAX_ALERT_DETAIL_CHARS``. A closed-enum ``detail`` value never
    trips this; nothing here inspects, logs, or echoes ``detail`` itself.
    """
    if _ABSOLUTE_PATH_TOKEN_RE.search(detail):
        raise ValueError("alert detail must not contain an absolute filesystem path")
    if _URL_RE.search(detail):
        raise ValueError("alert detail must not contain a URL")
    if "@" in detail:
        raise ValueError("alert detail must not contain an '@' character")
    if len(detail) > MAX_ALERT_DETAIL_CHARS:
        raise ValueError("alert detail must not exceed MAX_ALERT_DETAIL_CHARS characters")
