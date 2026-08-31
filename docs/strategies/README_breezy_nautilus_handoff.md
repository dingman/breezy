# Breezy × Nautilus strategy handoff pack

Three **design-only** implementation briefs. Each file is a drop-in spec for one new package under `src/breezy/strategy/<name>/` (`config.py`, `decision.py`, `strategy.py`).

Do not modify Nautilus internals. Do not register via `pyproject.toml` or `__init__.py`. Import the strategy class by direct name in the existing backtest harness.

| File | Package | Build order | Executable direction |
|---|---|---|---|
| `breezy_strategy_running_extreme_lock.md` | `running_extreme_lock` | 1 (after NWS same-day prelim check) | LONG_YES only |
| `breezy_strategy_cli_settlement_print_lock.md` | `cli_settlement_print_lock` | 1 as experiment, 2 as wiring | LONG_YES only |
| `breezy_strategy_lagged_anomaly_tail.md` | `lagged_anomaly_tail` | 3 | LONG_YES only |

Hard constraints baked into every brief:

- Long-only. `allow_short = False`. No `SHORT_YES`.
- No forecast feed. Observation + live L2 book only, or an explicit “this requires data Breezy does not have” gate.
- No reconstructed tapes of expired markets.
- Edge vs bid/ask, never midpoint. Every fill treated as a taker against the live ask.
- Risk caps in max-payout dollars, not mark-to-market.
- Two operator caps have no assigned value: maximum daily trading budget; maximum notional per position. Do not invent numbers.
- No look-ahead of the settling observation.

Existing strategies these must not clone: `forecast_mispricing`, `calibration_mean_reversion`, `forecast_revision`.
