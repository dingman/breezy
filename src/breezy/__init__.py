"""Breezy -- a weather-prediction trading bot built natively on NautilusTrader."""


__all__ = ["main"]


def main() -> int:
    """The `breezy` console-script entrypoint (see `pyproject.toml`).

    Delegates to `breezy.runtime.cli`, which owns the process exit contract.
    The import is deliberately function-local: importing `breezy` must not
    pull in NautilusTrader, and the CLI module does.
    """
    from breezy.runtime import cli

    return cli.run()
