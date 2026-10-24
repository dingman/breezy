"""Every ``OnFailure=`` template named under ``deploy/systemd`` has its unit file.

systemd drops an ``OnFailure=`` job when the target unit is not installed
(``Unit ... not found``). A template instance ``name@%n.service`` is installed
from ``name@.service`` in this directory. Autonomy units name
``breezy-autonomy-failed@%n.service``; that template was the X-3 gap.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

_DEPLOY: Final[Path] = Path(__file__).resolve().parents[2] / "deploy" / "systemd"
_UNIT_SUFFIXES: Final[frozenset[str]] = frozenset({".service", ".timer", ".conf"})


def _directive_lines(text: str) -> list[str]:
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            lines.append(stripped)
    return lines


def _missing_onfailure_templates() -> list[str]:
    missing: list[str] = []
    for path in sorted(_DEPLOY.rglob("*")):
        if not path.is_file() or path.suffix not in _UNIT_SUFFIXES:
            continue
        for line in _directive_lines(path.read_text(encoding="utf-8")):
            if not line.startswith("OnFailure="):
                continue
            for target in line.removeprefix("OnFailure=").split():
                if "@" not in target or not target.endswith(".service"):
                    continue
                template = f"{target.split('@', 1)[0]}@.service"
                if not (_DEPLOY / template).is_file():
                    missing.append(f"{path.relative_to(_DEPLOY)} -> {target} (missing {template})")
    return missing


def test_every_onfailure_template_target_exists_in_deploy_systemd() -> None:
    """RED while ``breezy-autonomy-failed@.service`` is absent; GREEN once it is shipped."""
    assert _missing_onfailure_templates() == []
    # The autonomy template must page through the proven study notifier and must not chain.
    text = (_DEPLOY / "breezy-autonomy-failed@.service").read_text(encoding="utf-8")
    lines = _directive_lines(text)
    assert not any(line.startswith("OnFailure=") for line in lines)
    assert not any(line.startswith("Restart=") for line in lines)
    execs = [line for line in lines if line.startswith("ExecStart=")]
    assert execs == ["ExecStart=%h/breezy/.venv/bin/breezy-study-failed --unit %i"]
    assert "EnvironmentFile=-%h/.config/breezy/alerts.env" in lines
