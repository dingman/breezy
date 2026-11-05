"""C6 family plug-in contract (ARCH-0 AC 26; ARCH C6, AUTONOMY_ARCHITECTURE.md:742-766).

The Protocols name what each layer needs from a composition kind; the C1/C2/C4/C3 record
types they exchange land with their owning seams, so their payloads are ``Any`` here and
narrowed there. Non-method members are ``@property`` so frozen dataclasses and plain
attributes both satisfy them. A kind with no non-RETIRED family registers
:class:`RefusingPlugin`: every member raises :class:`PluginRefused`, and ``refusing`` is true.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol

from breezy.persistence.autonomy.veto import VetoReason

__all__ = [
    "CaptureAdapter",
    "Detector",
    "DetectorKind",
    "DriftDetectors",
    "Evaluator",
    "PluginRefused",
    "Refitter",
    "RefusingPlugin",
    "Scorer",
    "is_complete",
]


class PluginRefused(Exception):
    """A refusing plug-in was asked to do work (mint, compose, label, evaluate, detect, refit)."""


class DetectorKind(StrEnum):
    NODE_LOCAL = "node_local"
    VERDICT = "verdict"


class CaptureAdapter(Protocol):
    """Strategy layer: C1 decision capture and order tagging."""

    def decision_record(self, decision: Any, ctx: Any) -> Any: ...

    def order_tags(self, decision_id: str) -> Any: ...


class Scorer(Protocol):
    """Analysis layer: C2 outcome labels."""

    def label(self, capture_day: Any, exec_fills: Any, settlements: Any) -> Any: ...


class Evaluator(Protocol):
    """Analysis layer: C4 verdict inputs for each evaluation mode."""

    def offline(self, candidate: Any, champion: Any) -> Any: ...

    def forward_shadow(self, candidate: Any, champion: Any, tape: Any) -> Any: ...

    def live(self, labels: Any) -> Any: ...


class Detector(Protocol):
    """One drift detector: a ``NODE_LOCAL`` one yields a veto, a ``VERDICT`` one a C4 verdict."""

    @property
    def id(self) -> str: ...

    @property
    def kind(self) -> DetectorKind: ...

    def evaluate(self, *args: Any, **kwargs: Any) -> VetoReason | Any | None: ...


class DriftDetectors(Protocol):
    @property
    def detectors(self) -> tuple[Detector, ...]: ...


class Refitter(Protocol):
    """Analysis layer: C3 refit, or refusal (``NOT_FITTABLE``)."""

    def refit(self, windows: Any) -> Any: ...


class RefusingPlugin:
    """The plug-in of a kind with no live family: it satisfies every C6 Protocol by refusing."""

    @property
    def refusing(self) -> bool:
        return True

    @staticmethod
    def _refuse() -> PluginRefused:
        return PluginRefused("this composition kind has no plug-in")

    def decision_record(self, decision: Any, ctx: Any) -> Any:
        raise self._refuse()

    def order_tags(self, decision_id: str) -> Any:
        raise self._refuse()

    def label(self, capture_day: Any, exec_fills: Any, settlements: Any) -> Any:
        raise self._refuse()

    def offline(self, candidate: Any, champion: Any) -> Any:
        raise self._refuse()

    def forward_shadow(self, candidate: Any, champion: Any, tape: Any) -> Any:
        raise self._refuse()

    def live(self, labels: Any) -> Any:
        raise self._refuse()

    @property
    def detectors(self) -> tuple[Detector, ...]:
        raise self._refuse()

    def refit(self, windows: Any) -> Any:
        raise self._refuse()


def is_complete(plugin: object) -> bool:
    """True only for a plug-in that declares ``refusing`` and it is false (fail closed)."""
    return getattr(plugin, "refusing", True) is False
