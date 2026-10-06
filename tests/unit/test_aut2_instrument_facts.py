"""AUT-2 r7 WP2: ``analysis/labeling/instrument_facts.py`` is a pure move out of the scorer script.

``scripts/analysis/score_live_trials.py`` re-imports the two functions under their old private
names, so the move changes no behaviour (L-46).
"""

from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import sys
from pathlib import Path

from breezy.analysis.labeling import instrument_facts
from breezy.domain.weather_bucket_facts import Measure

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "analysis" / "score_live_trials.py"


def _load_script() -> object:
    sys.path.insert(0, str(_SCRIPT.parent))
    try:
        spec = importlib.util.spec_from_file_location("score_live_trials_aut2_probe", _SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(_SCRIPT.parent))
        sys.modules.pop("score_live_trials_aut2_probe", None)


def test_script_reimports_the_moved_functions_and_defines_none_itself() -> None:
    script = _load_script()
    assert (
        script._bucket_facts_from_instrument_id  # type: ignore[attr-defined]
        is instrument_facts.bucket_facts_from_instrument_id
    )
    assert (
        script._read_bucket_facts_by_instrument_id  # type: ignore[attr-defined]
        is instrument_facts.read_bucket_facts_by_instrument_id
    )
    defined = {
        node.name
        for node in ast.walk(ast.parse(_SCRIPT.read_text(encoding="utf-8")))
        if isinstance(node, ast.FunctionDef)
    }
    assert not defined & {"_bucket_facts_from_instrument_id", "_read_bucket_facts_by_instrument_id"}


def test_slug_grammar_gives_the_rung_facts() -> None:
    facts = instrument_facts.bucket_facts_from_instrument_id(
        "tc-temp-laxhigh-2026-10-02-gte89lt90f.POLYMARKET_US"
    )
    assert facts is not None
    assert (facts.lower_f, facts.upper_f, facts.measure) == (89, 90, Measure.HIGH)
    assert facts.climate_day == dt.date(2026, 10, 2)
    # the NO leg shares its base slug's facts
    assert (
        instrument_facts.bucket_facts_from_instrument_id(
            "tc-temp-laxhigh-2026-10-02-gte89lt90f^no.POLYMARKET_US"
        )
        == facts
    )
    assert (
        instrument_facts.bucket_facts_from_instrument_id("not-a-weather-slug.POLYMARKET_US") is None
    )
