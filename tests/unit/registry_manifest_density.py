"""E-24 fixtures: a BOOTSTRAP or MINT row binds an artefact, and its manifest pins that artefact.

Production reads the manifest file and compares its ``density_artefact_sha256`` with the row's
``artefact_sha256`` (``Rule.MANIFEST_DENSITY_NOT_BOUND``). A fixture chain has no manifest file, so
the builders register each introducing row's pair here and the fixture readers answer from it: the
manifest of an introducing row pins exactly that row's artefact, and a manifest nobody registered
is unreadable. The registry maps a manifest sha to one artefact for the whole run; the default
manifest sha is derived from (family, artefact), so two different artefacts never share a sha.
"""

from __future__ import annotations

import hashlib
from typing import Any, Final

from breezy.persistence.autonomy.schemas import ManifestFacts

_ARTEFACT_OF: Final[dict[str, str]] = {}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def default_artefact(family: str) -> str:
    """The artefact a fixture family binds when a test names none (distinct per family)."""
    return _sha(f"fixture-artefact:{family}")


def default_manifest(family: str, artefact: str) -> str:
    """The manifest sha a fixture introducing row carries when a test names none."""
    return _sha(f"fixture-manifest:{family}:{artefact}")


def bind(manifest_sha256: str, artefact_sha256: str) -> None:
    """Record that the manifest at ``manifest_sha256`` pins ``artefact_sha256`` as its density."""
    _ARTEFACT_OF[manifest_sha256] = artefact_sha256


def density_of(manifest_sha256: str) -> str:
    """The registered density pin of ``manifest_sha256``; a filler for a manifest no row introduced
    (the density rule reads introducing manifests only, which are always registered)."""
    return _ARTEFACT_OF.get(manifest_sha256, "f" * 64)


def introducer_columns(
    family: str, given: dict[str, Any], manifest_default: str | None = None
) -> dict[str, Any]:
    """``manifest_sha256`` and ``artefact_sha256`` for a BOOTSTRAP or MINT row, registered.

    A column a test names is kept; a missing one is defaulted so the manifest pins the artefact.
    """
    artefact = given.get("artefact_sha256") or default_artefact(family)
    manifest = (
        given.get("manifest_sha256") or manifest_default or default_manifest(family, artefact)
    )
    bind(manifest, artefact)
    return {"manifest_sha256": manifest, "artefact_sha256": artefact}


def density_facts(
    family_id: str, manifest_sha256: str, *, d0: str, composition: str
) -> ManifestFacts | None:
    """Facts for a registered introducing manifest (its density pin is the row's artefact)."""
    artefact = _ARTEFACT_OF.get(manifest_sha256)
    if artefact is None:
        return None
    return ManifestFacts(
        family_id=family_id,
        manifest_sha256=manifest_sha256,
        d0_climate_day=d0,
        trial_id_prefix=f"{composition}/trial/{family_id}/",
        composition_kind=composition,
        density_artefact_sha256=artefact,
    )
