"""TE-2 S0-D: rebuild each fill's p-hat from the pinned commit, a derived NBP store and the node
log's cycle visibility (I/O). Plan: TE-2_plan_r3_2.md section 4, S0-D.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from breezy.persistence.nbp_derived_store import DerivedNbpRow
from scripts.analysis.fq_loss_taxonomy_classify import S0D_TOLERANCE, GateResult, S0DMiss
from scripts.analysis.fq_loss_taxonomy_pins import Boot, BootPin, GitPort

CYCLE_AMBIGUITY_NS: Final = 5 * 10**9
TOLERANCE: Final = S0D_TOLERANCE


class S0DStop(Exception):
    """Fewer than 23 of 25 reconstructed p-hat values match the logged value."""


@dataclass(frozen=True)
class FillSpec:
    fill_id: str
    instrument_id: str
    p_hat_logged: float
    decision_now_ns: int
    ask_proxy: float


@dataclass(frozen=True)
class ReconstructedFill:
    fill_id: str
    instrument_id: str
    boot_number: int | None
    commit: str | None
    p_hat_logged: float
    p_hat_reconstructed: float | None
    delta: float | None
    match: bool
    s0d_class: S0DMiss | None
    reason: str | None
    material: bool | None
    cycle_ns: int | None
    raw_sha256: str | None
    cycle_age_s: float | None
    newest_visible: bool | None
    vector: Mapping[str, float] | None
    pmf: Mapping[int, float] | None


@dataclass(frozen=True)
class PinnedModel:
    commit: str
    calibration: Any
    bounds: Any
    fee_coefficient: float


def iter_published_cycles(path: Path) -> Iterator[tuple[int, int]]:
    """``(cycle_ns, visible_ns)`` for every NBM_NBP_PUBLISHED line of one node log."""
    raise NotImplementedError


def published_cycles(paths: Sequence[Path]) -> dict[int, int]:
    raise NotImplementedError


def load_derived_cycles(root: Path) -> dict[int, tuple[DerivedNbpRow, ...]]:
    raise NotImplementedError


def partition_complete(rung_ids: Sequence[str]) -> bool:
    raise NotImplementedError


def load_pinned_model(
    git: GitPort, commit: str, manifest_path: str, workdir: Path
) -> PinnedModel:
    raise NotImplementedError


class Reconstructor:
    def __init__(
        self,
        git: GitPort,
        *,
        manifest_path: str,
        workdir: Path,
        cycles: Mapping[int, Sequence[DerivedNbpRow]],
        published: Mapping[int, int],
    ) -> None:
        raise NotImplementedError

    def reconstruct(self, spec: FillSpec, commit: str) -> ReconstructedFill:
        raise NotImplementedError

    def reproduces_under(
        self, specs_by_boot: Mapping[int, Sequence[FillSpec]]
    ) -> Callable[[int, str], bool]:
        raise NotImplementedError


def reconstruct_all(
    reconstructor: Reconstructor,
    specs: Sequence[FillSpec],
    boots: Sequence[Boot],
    pins: Sequence[BootPin],
) -> tuple[ReconstructedFill, ...]:
    raise NotImplementedError


def boot_for(boots: Sequence[Boot], now_ns: int) -> int | None:
    raise NotImplementedError


def s0d_gate(results: Sequence[ReconstructedFill]) -> GateResult:
    """STOP (``S0DStop``) below 23 matches; UNTESTABLE counts as a non-match."""
    raise NotImplementedError


def vector_table(results: Sequence[ReconstructedFill]) -> list[dict[str, Any]]:
    raise NotImplementedError

