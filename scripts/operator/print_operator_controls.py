#!/usr/bin/env python3
"""Print presence of the two operator-reserved caps. Never prints a value.

Two modes, both value-free:

* no args: report presence in the current process environment
* ``--check-file PATH``: validate the operator's file without loading it
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import sys
from collections.abc import Mapping
from pathlib import Path

from breezy.adapters.polymarket_us.operator_controls import OPERATOR_RESERVED_CONTROL_ENV_VARS

UNSET_SENTINEL = "<unset>"
SET_TOKEN = "<set>"
UNSET_TOKEN = "<unset>"
LINE_RE = re.compile(r"^[A-Z][A-Z0-9_]*=\S+$", re.ASCII)
_GROUP_OTHER = stat.S_IRWXG | stat.S_IRWXO


def _refuse(reason: str) -> int:
    print(reason, file=sys.stderr)
    return 2


def _presence_token(mapping: Mapping[str, str], name: str) -> str:
    if name not in mapping:
        return UNSET_TOKEN
    raw = mapping[name]
    if raw.strip() == "":
        return UNSET_TOKEN
    if raw == UNSET_SENTINEL:
        return UNSET_TOKEN
    return SET_TOKEN


def _report(mapping: Mapping[str, str]) -> int:
    all_set = True
    for name in OPERATOR_RESERVED_CONTROL_ENV_VARS:
        token = _presence_token(mapping, name)
        print(f"{name}={token}")
        if token != SET_TOKEN:
            all_set = False
    if all_set:
        return 0
    return 1


def _check_file(raw_path: str) -> int:
    path = Path(raw_path)
    if path.is_symlink():
        return _refuse("path is a symlink")
    try:
        mode = path.stat().st_mode
    except OSError:
        return _refuse("cannot stat path")
    if mode & _GROUP_OTHER:
        return _refuse("mode has group or other bits")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return _refuse("cannot read file")

    inventory = frozenset(OPERATOR_RESERVED_CONTROL_ENV_VARS)
    parsed: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line == "" or line.startswith("#"):
            continue
        if LINE_RE.fullmatch(line) is None:
            return _refuse("malformed line")
        key, _, value = line.partition("=")
        if key not in inventory:
            return _refuse(f"unexpected key: {key}")
        if key in parsed:
            return _refuse("repeated key")
        parsed[key] = value
    for name in OPERATOR_RESERVED_CONTROL_ENV_VARS:
        if name not in parsed:
            return _refuse("missing key")
    return _report(parsed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Report presence of the two operator-reserved caps. Never prints a value."
        )
    )
    parser.add_argument(
        "--check-file",
        metavar="PATH",
        default=None,
        help="validate an operator file without loading it into the environment",
    )
    args = parser.parse_args(argv)
    if args.check_file is not None:
        return _check_file(args.check_file)
    return _report(os.environ)


if __name__ == "__main__":
    raise SystemExit(main())
