"""TE-2 WP0 (RED): the AST guards (plan tests 36 and the core I/O-free check).

The allowlists are per file family: the core family is stdlib-pure plus ``breezy.*``; the I/O
family adds subprocess, pathlib and friends. Module matching is exact-or-dotted-child, so a
string-prefix lookalike such as ``mathx`` is not ``math``.
"""

from __future__ import annotations

from pathlib import Path

from scripts.analysis.fq_loss_taxonomy_core import holdout_violations, io_violations

_ANALYSIS = Path(__file__).resolve().parents[2] / "scripts/analysis"
_CORE_FAMILY = ("core", "stats", "classify", "verdict", "guard")
_IO_FAMILY = ("inputs", "pins", "logs", "truth")
_CORE_FILES = [_ANALYSIS / f"fq_loss_taxonomy_{n}.py" for n in _CORE_FAMILY]
_IO_FILES = [_ANALYSIS / f"fq_loss_taxonomy_{n}.py" for n in _IO_FAMILY]
_CLI = _ANALYSIS / "fq_v1_loss_taxonomy.py"
_FAMILY_MODULES = tuple(
    f"scripts.analysis.fq_loss_taxonomy_{n}" for n in (*_CORE_FAMILY, *_IO_FAMILY)
)
_PURE = (
    "__future__", "ast", "collections", "dataclasses", "datetime", "decimal", "enum",
    "itertools", "math", "re", "typing",
)  # fmt: skip
_CORE_ALLOWED = (*_PURE, "breezy", *_FAMILY_MODULES[:5])
_IO_ALLOWED = (
    *_PURE, "breezy", "argparse", "hashlib", "json", "pathlib", "subprocess", "sys",
    *_FAMILY_MODULES,
)  # fmt: skip
_NAMES = {"breezy.analysis.nbp_calibration": frozenset({"holm_correction"})}
_NBP = "breezy.analysis.nbp_calibration"


def _bad(source: str, allowed: tuple[str, ...] = _CORE_ALLOWED) -> tuple[str, ...]:
    return holdout_violations(source, allowed, _NAMES)


def test_ast_pin_allowlist_forbids_open_holdout_attribute_and_string_access() -> None:
    clean = f"import math\nfrom math import sqrt\nfrom {_NBP} import holm_correction\n"
    bypasses = {
        "name": f"from {_NBP} import open_holdout\n",
        "name not on the allowlist": f"from {_NBP} import DEFAULT_SPLITS\n",
        "alias": f"from {_NBP} import open_holdout as f\n",
        "star import": f"from {_NBP} import *\n",
        "attribute": f"import {_NBP} as nc\nnc.open_holdout()\n",
        "string": f"import {_NBP} as nc\ngetattr(nc, 'open_holdout')\n",
        "concatenated": f"import {_NBP} as nc\ngetattr(nc, 'open_' + 'holdout')\n",
        "f-string": f'import {_NBP} as nc\ngetattr(nc, f"open_{"holdout"}")\n',
        "importlib": "import importlib\n",
        "importlib from": "from importlib import import_module\n",
        "__import__": "m = __import__('os')\n",
        "eval": "eval('1')\n",
        "exec call": "exec('x = 1')\n",
        "relative from": "from . import sibling\n",
        "relative module": "from .sibling import thing\n",
        "prefix lookalike": "import mathx\n",
        "off-list": "import requests\n",
        "direct exec import": "from breezy.adapters.polymarket_us.exec.client import X\n",
        "m1v3 path": "p = 'docs/evidence/m1v3/result.json'\n",
        "M1-v3 spelling": "p = 'data/M1-v3/holdout'\n",
        "m1_v3 spelling": "p = 'data/m1_v3/rows'\n",
    }

    assert _bad(clean) == ()
    for label, source in bypasses.items():
        assert _bad(source), label
    for module in ("os", "pathlib", "subprocess", "sqlite3", "socket", "io", "logging"):
        assert _bad(f"import {module}\n"), f"core must not import {module}"
    assert _bad("import subprocess\nimport pathlib\n", _IO_ALLOWED) == ()  # the I/O family may
    for path in _CORE_FILES:
        assert holdout_violations(path.read_text("utf-8"), _CORE_ALLOWED, _NAMES) == (), path.name
    for path in [*_IO_FILES, _CLI]:
        assert holdout_violations(path.read_text("utf-8"), _IO_ALLOWED, _NAMES) == (), path.name


def test_core_modules_are_io_free_by_ast_and_the_detector_fires_on_io() -> None:
    dirty = {
        "open call": "open('f')\n",
        "print call": "print('x')\n",
        "os": "import os\n",
        "pathlib": "from pathlib import Path\n",
        "sqlite3": "import sqlite3\n",
        "subprocess": "import subprocess\n",
        "socket": "import socket\n",
        "io": "import io\n",
        "logging": "import logging\n",
    }

    for path in _CORE_FILES:
        assert io_violations(path.read_text("utf-8")) == (), path.name
    for label, source in dirty.items():
        assert io_violations(source), label
