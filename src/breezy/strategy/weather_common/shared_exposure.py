"""Shared max-payout exposure participation, factored out of every weather strategy.

Why this exists
----------------
``new_shared_exposure_view``/``use_shared_exposure_view`` used to be
hand-duplicated, byte-for-byte identical, in every weather strategy
(``forecast_mispricing``, ``calibration_mean_reversion``, ``forecast_revision``).
``breezy.runtime.backtest_harness._install_shared_exposure_view`` discovers
them via ``getattr(strategy, name, None)`` -- ``runtime`` may not import
``breezy.strategy`` at all (see the layers contract in ``pyproject.toml``:
``strategy`` is the TOP layer and nothing may reach back up into it), so the
harness has no nominal type to check against and must ask each strategy
structurally.

Structural discovery means a strategy that forgot to copy the pair was
INDISTINGUISHABLE, from the harness's seat, from a strategy that deliberately
does not participate: both simply lack the two methods. The forgetful
strategy was silently handed its own PRIVATE ``SharedExposureView`` instead
of the composition root's shared one (``RiskManager.__init__`` falls back to
``SharedExposureView() if exposure_view is None else exposure_view``), and
two strategies each holding a tail on the same ``event_key`` would each
believe they hold the only position -- doubling real exposure past the
configured max-payout budget, with no exception raised and no refusal
counted anywhere.

The fix here has two layers, deliberately:

1. This mixin makes the omission structurally impossible for any strategy
   that inherits it: the pair is provided CONCRETELY, so there is nothing
   left to hand-write, and therefore nothing left to forget. Put it FIRST in
   the base list, ahead of ``Strategy`` (see the three existing weather
   strategies) -- Nautilus's ``Strategy`` is a compiled Cython extension
   type, and mixing a plain Python class in ahead of it is the ordering
   Python's MRO expects for a cooperative mixin.
2. ``breezy.runtime.backtest_harness.SharedExposureContractError`` is a
   second, independent line of defence for the one failure mode this mixin
   cannot see: a FUTURE strategy that skips it entirely. See that error's
   docstring for what it can and cannot prove from the outside.
"""

from __future__ import annotations

from breezy.strategy.weather_common.risk import RiskManager, SharedExposureView

__all__ = ["SharedExposureMixin"]


class SharedExposureMixin:
    """Give a weather strategy shared max-payout exposure tracking by construction.

    Inherit this FIRST in the base list, e.g.::

        class MyWeatherStrategy(SharedExposureMixin, Strategy):
            ...

    so the concrete methods below are found before ``Strategy``'s own
    attribute lookup in the MRO. Nothing else about a strategy's
    ``__init__``/``on_start`` needs to change: it still reads
    ``self._shared_exposure_view`` when building its ``RiskManager``, exactly
    as before.
    """

    #: Set by `use_shared_exposure_view` before `on_start` runs (the
    #: composition root installs it right after construction); read by the
    #: strategy's own `on_start` when it builds its `RiskManager`.
    _shared_exposure_view: SharedExposureView | None = None
    #: Narrowed to a real `RiskManager` by the concrete strategy's `on_start`.
    #: Declared here only so `use_shared_exposure_view` can refuse a late
    #: install without every strategy re-declaring the same guard.
    _risk: RiskManager | None = None

    @staticmethod
    def new_shared_exposure_view() -> SharedExposureView:
        return SharedExposureView()

    def use_shared_exposure_view(self, exposure_view: SharedExposureView) -> None:
        if self._risk is not None:
            raise RuntimeError("shared exposure must be installed before strategy start")
        self._shared_exposure_view = exposure_view
