"""MAKER-S2 WP1: ``load_model`` -- the density artefact, asserted against its NBP evidence doc.

Plan r3 WP1 + r4 delta (g). ``load_model`` takes the artefact path and sha from the deploy
manifest, then asserts against the NBP validate evidence doc: its ``artefact_sha256`` (the bullet
and the JSON block's ``artefact.sha256``) equals the loaded artefact's sha256, the v5.0 era's
``v5_fit_slice`` ``last_climate_day`` equals ``DEFAULT_SPLITS.v5_fit_slice.end`` (2026-06-30), and
no era's ``last_climate_day`` is later than that. Any failure, or an unparseable doc, refuses.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from breezy.analysis.nbp_calibration import DEFAULT_SPLITS
from scripts.analysis.maker_stage0_inputs import sha256_bytes, sha256_file

__all__ = [
    "DEPLOY_MANIFEST_REL",
    "EVIDENCE_DOC_REL",
    "FIT_WINDOW_END",
    "ModelPin",
    "ModelRefused",
    "load_model",
]

FIT_WINDOW_END: Final[dt.date] = dt.date(2026, 6, 30)
DEPLOY_MANIFEST_REL: Final[str] = "deploy/families/pm_us_crh_fq_v1.json"
EVIDENCE_DOC_REL: Final[str] = "docs/evidence/NBP_S2_VALIDATE_RESULT_2026-09-30.md"
_V5_ERA: Final[str] = "v5.0"
_V5_SPLIT: Final[str] = "v5_fit_slice"
_BULLET_RE: Final[re.Pattern[str]] = re.compile(
    r"^- artefact_sha256: `([0-9a-f]{64})`", re.MULTILINE
)
_JSON_BLOCK_RE: Final[re.Pattern[str]] = re.compile(r"```json\n(.*?)\n```", re.DOTALL)


class ModelRefused(ValueError):
    """The model artefact or its evidence doc failed an assertion."""


@dataclass(frozen=True, slots=True)
class ModelPin:
    family_id: str
    artefact_path: Path
    artefact_sha256: str
    manifest_path: Path
    manifest_sha256: str
    evidence_doc_path: Path
    evidence_doc_sha256: str
    fit_window_end: dt.date


def _parse_doc(text: str) -> tuple[str, str, Mapping[str, Any]]:
    try:
        bullet = _BULLET_RE.search(text)
        block = _JSON_BLOCK_RE.search(text)
        if bullet is None or block is None:
            raise ValueError("no artefact_sha256 bullet or JSON block")
        body = json.loads(block.group(1))
        return bullet.group(1), str(body["artefact"]["sha256"]), dict(body["fit_provenance"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ModelRefused(f"evidence doc unparseable: {type(exc).__name__}: {exc}") from exc


def _last_day(era: str, split: str, entry: Mapping[str, Any]) -> dt.date:
    try:
        return dt.date.fromisoformat(str(entry["last_climate_day"]))
    except (ValueError, KeyError, TypeError) as exc:
        raise ModelRefused(f"evidence doc unparseable: {era} {split} last_climate_day") from exc


def _assert_fit_window(provenance: Mapping[str, Any]) -> None:
    era = provenance.get(_V5_ERA)
    v5 = era.get(_V5_SPLIT) if isinstance(era, dict) else None
    if v5 is None:
        raise ModelRefused(f"evidence doc has no {_V5_ERA} {_V5_SPLIT} entry")
    last = _last_day(_V5_ERA, _V5_SPLIT, v5)
    if last != DEFAULT_SPLITS.v5_fit_slice.end or last != FIT_WINDOW_END:
        raise ModelRefused(
            f"fit window mismatch: doc {last}, DEFAULT_SPLITS {DEFAULT_SPLITS.v5_fit_slice.end}, "
            f"pinned {FIT_WINDOW_END}"
        )
    for era_name, splits in provenance.items():
        for split, entry in dict(splits).items():
            day = _last_day(str(era_name), str(split), entry)
            if day > FIT_WINDOW_END:
                raise ModelRefused(
                    f"{era_name} {split} last_climate_day {day} is after {FIT_WINDOW_END}"
                )


def load_model(
    repo_root: Path,
    *,
    manifest_rel: str = DEPLOY_MANIFEST_REL,
    evidence_doc_rel: str = EVIDENCE_DOC_REL,
) -> ModelPin:
    """Artefact path and sha from the deploy manifest, asserted against the evidence doc."""
    manifest_path = repo_root / manifest_rel
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artefact_path = repo_root / str(manifest["density_artefact_path"])
        pinned = str(manifest["density_artefact_sha256"])
        family_id = str(manifest["family_id"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ModelRefused(f"deploy manifest unusable: {type(exc).__name__}") from exc
    try:
        loaded = sha256_file(artefact_path)
    except OSError as exc:
        raise ModelRefused(
            f"artefact {artefact_path.name} unreadable ({type(exc).__name__})"
        ) from exc
    if loaded != pinned:
        raise ModelRefused(f"manifest density_artefact_sha256 {pinned} != artefact bytes {loaded}")
    doc_path = repo_root / evidence_doc_rel
    try:
        doc_bytes = doc_path.read_bytes()
        doc_text = doc_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ModelRefused(f"evidence doc unreadable ({type(exc).__name__})") from exc
    bullet, block_sha, provenance = _parse_doc(doc_text)
    if not bullet == block_sha == loaded:
        raise ModelRefused(
            f"evidence doc artefact_sha256 bullet {bullet} / block {block_sha} != loaded {loaded}"
        )
    _assert_fit_window(provenance)
    return ModelPin(
        family_id=family_id,
        artefact_path=artefact_path,
        artefact_sha256=loaded,
        manifest_path=manifest_path,
        manifest_sha256=sha256_file(manifest_path),
        evidence_doc_path=doc_path,
        evidence_doc_sha256=sha256_bytes(doc_bytes),
        fit_window_end=FIT_WINDOW_END,
    )
