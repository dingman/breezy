"""Entry-point discovery helpers shared by import-isolation tests."""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SRC_DIR: Final[Path] = REPO_ROOT / "src"
RUNTIME_INIT_PATH: Final[Path] = SRC_DIR / "breezy" / "runtime" / "__init__.py"
PYPROJECT_PATH: Final[Path] = REPO_ROOT / "pyproject.toml"
DEPLOY_SYSTEMD_DIR: Final[Path] = REPO_ROOT / "deploy" / "systemd"
SCRIPTS_DIR: Final[Path] = REPO_ROOT / "scripts"


def _entry_modules_from_pyproject_scripts() -> set[str]:
    """(a) Every `[project.scripts]` target module, `pyproject.toml:306-381`."""
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    scripts = data["project"]["scripts"]
    return {target.split(":", 1)[0] for target in scripts.values()}


def _entry_modules_from_systemd() -> set[str]:
    """(b) Every Python module named in a `deploy/systemd/**` `ExecStart=`
    line (`-m module` and bare `path/to/module.py` forms), plus every `-m
    breezy.<mod>` invocation found inside a `deploy/systemd/*.sh` wrapper
    script (an `ExecStart=` line that only names the wrapper can't show
    this -- the module lives one hop down, inside the script).
    """
    exec_start_re = re.compile(r"^ExecStart=(.*)$", re.MULTILINE)
    module_flag_re = re.compile(r"(?:^|\s)-m\s+([A-Za-z_][\w.]*)")
    py_path_re = re.compile(r"(?:^|/)(scripts/[\w/]+)\.py\b")
    wrapper_module_re = re.compile(r"(?:^|\s)-m\s+(breezy\.[\w.]*)")

    modules: set[str] = set()
    for service_path in sorted(DEPLOY_SYSTEMD_DIR.rglob("*.service")):
        text = service_path.read_text(encoding="utf-8")
        for exec_line in exec_start_re.finditer(text):
            line = exec_line.group(1)
            modules.update(module_flag_re.findall(line))
            modules.update(m.replace("/", ".") for m in py_path_re.findall(line))

    for sh_path in sorted(DEPLOY_SYSTEMD_DIR.rglob("*.sh")):
        text = sh_path.read_text(encoding="utf-8")
        modules.update(wrapper_module_re.findall(text))

    return modules


def _entry_modules_from_scripts_importing(package: str) -> set[str]:
    """Every `scripts/**/*.py` that imports `package` or one of its submodules."""
    modules: set[str] = set()
    for script_path in sorted(SCRIPTS_DIR.rglob("*.py")):
        tree = ast.parse(script_path.read_text(encoding="utf-8"), filename=str(script_path))
        imports_package = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(
                    alias.name == package or alias.name.startswith(f"{package}.")
                    for alias in node.names
                ):
                    imports_package = True
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and (node.module == package or node.module.startswith(f"{package}."))
            ):
                imports_package = True
        if imports_package:
            rel = script_path.relative_to(REPO_ROOT)
            modules.add(".".join(rel.with_suffix("").parts))
    return modules
