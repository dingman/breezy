"""Contract tests pinning WHEN `NautilusConfig`/`ActorConfig` actually validate.

Every assertion here was observed by execution against the pinned install
(nautilus-trader 1.231.0), not inferred from documentation. Run these FIRST on
any version bump: a failure means the platform moved, not that Breezy is
wrong.

`NautilusConfig` is a `msgspec.Struct` (`common/config.py:241`,
`kw_only=True, frozen=True, forbid_unknown_fields=True`). Those Struct-level
flags read like a strict, always-validating type, but `msgspec.Struct.__init__`
performs no field-type checking at all -- type enforcement is a property of
the DECODE path (`msgspec.json.decode` / `msgspec.convert`), not of
construction. `NautilusConfig.parse` (`common/config.py:287-303`) IS a decode
path and does validate; direct Python construction (`MyConfig(x=wrong_type)`)
is NOT, and does not. This is a real weakening of a surface Breezy assumed
was strict end-to-end: any code path that builds a config object directly
(rather than through `.parse`/`msgspec.convert`) gets zero type checking, no
matter how strict the class declaration looks.

The one construction-time check that DOES fire is unknown-field rejection --
but that comes from ordinary Python keyword-argument matching (an unrecognised
`__init__` kwarg is a `TypeError` in any Python class, Struct or not), not
from `forbid_unknown_fields`, which is a decode-time msgspec option. All
three arms are pinned here so the boundary between "looks strict" and "is
strict" does not have to be re-derived from first principles the next time
someone reaches for direct construction assuming it validates.

Scope: `common/config.py` `NautilusConfig` (`:241`), `ActorConfig` (`:542`),
`NautilusConfig.parse` (`:287-303`). No network access.
"""

from __future__ import annotations

import msgspec
import pytest
from nautilus_trader.common.config import ActorConfig

pytestmark = pytest.mark.contract


class _ProbeConfig(ActorConfig, kw_only=True, frozen=True):
    """A minimal `ActorConfig` subclass with one non-default field, kept out
    of `breezy.settings` deliberately: this is a framework contract test and
    must keep passing even if every Breezy config class is renamed."""

    count: int = 0


# ---------------------------------------------------------------------------
# Arm 1: direct construction with a wrong-typed field is ACCEPTED
# ---------------------------------------------------------------------------


def test_direct_construction_with_a_wrong_typed_field_is_accepted() -> None:
    """`common/config.py:241` -- `NautilusConfig(msgspec.Struct, ...)`'s
    `__init__` performs no type checking. Constructing `_ProbeConfig` with a
    `str` where `count: int` is declared succeeds silently and the wrong-typed
    value is stored verbatim, retrievable unchanged from the instance.
    """
    cfg = _ProbeConfig(count="not-an-int")  # type: ignore[arg-type]

    assert cfg.count == "not-an-int"
    assert type(cfg.count) is str


# ---------------------------------------------------------------------------
# Arm 2: an unknown field raises TypeError at construction
# ---------------------------------------------------------------------------


def test_an_unknown_field_raises_type_error_at_construction() -> None:
    """`common/config.py:241` `forbid_unknown_fields=True` is a msgspec DECODE
    option and does not itself fire here -- this rejection is ordinary Python
    keyword-argument matching against the Struct's declared fields, the same
    `TypeError` any Python class raises for an unrecognised `__init__` kwarg.
    Pinned as `TypeError` specifically, not `msgspec.ValidationError`, because
    conflating the two would make a caller's `except ValidationError:` miss
    this arm entirely.
    """
    with pytest.raises(TypeError, match="bogus_field"):
        _ProbeConfig(count=1, bogus_field="x")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Arm 3: the decode path DOES validate -- both entry points
# ---------------------------------------------------------------------------


def test_msgspec_convert_strict_true_raises_validation_error_on_wrong_type() -> None:
    """`msgspec.convert(..., type=cls, strict=True)` -- the same underlying
    validation `NautilusConfig.parse` delegates to -- rejects the wrong-typed
    field with `msgspec.ValidationError`, in contrast to direct construction
    (Arm 1) which accepted the identical value silently.
    """
    with pytest.raises(msgspec.ValidationError, match=r"Expected `int`, got `str`"):
        msgspec.convert({"count": "not-an-int"}, type=_ProbeConfig, strict=True)


def test_nautilus_config_parse_decode_path_raises_validation_error_on_wrong_type() -> None:
    """`common/config.py:287-303` -- `NautilusConfig.parse` (the classmethod
    Breezy would actually call to load a config from JSON) runs
    `msgspec.json.decode(raw, type=cls, dec_hook=msgspec_decoding_hook)`,
    which validates and raises `msgspec.ValidationError` for the same
    wrong-typed field that Arm 1 accepted through direct construction. This
    is the arm that proves the "validates on decode" half of the file's
    title claim, not just the strict-convert helper.
    """
    raw = msgspec.json.encode({"count": "not-an-int"})

    with pytest.raises(msgspec.ValidationError, match=r"Expected `int`, got `str`"):
        _ProbeConfig.parse(raw)


def test_the_wrong_typed_value_that_survives_construction_also_survives_re_encoding() -> None:
    """Closing the loop: Arm 1's silently-accepted bad config is not merely
    inert -- round-tripping it through `.json()` (encode) reproduces the same
    wrong-typed value on the wire, because encoding does not validate either.
    Only a subsequent DECODE of that JSON (Arm 3) would catch it. This is why
    "construct, then validate() before trusting it" is a real pattern here
    and not defensive paranoia: nothing else in the object's lifecycle
    catches this class of bug.
    """
    cfg = _ProbeConfig(count="not-an-int")  # type: ignore[arg-type]

    encoded = cfg.json()

    assert b'"not-an-int"' in encoded
    with pytest.raises(msgspec.ValidationError):
        _ProbeConfig.parse(encoded)
