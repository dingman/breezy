"""TE-2 loss taxonomy: AST guards over script source text (pure). WP0 stub.

``holdout_violations`` is an allowlist pin: an import must name an allowed module (exact or a
dotted child, never a string-prefix lookalike), an allowed name where a name allowlist exists,
and must not reach the holdout opener, an M1-v3 path (any spelling), a dynamic import, or the
execution package. ``io_violations`` finds I/O imports and ``open``/``print`` calls.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def holdout_violations(
    source: str,
    allowed_modules: Sequence[str],
    allowed_names: Mapping[str, frozenset[str]] | None = None,
) -> tuple[str, ...]:
    raise NotImplementedError


def io_violations(source: str) -> tuple[str, ...]:
    raise NotImplementedError
