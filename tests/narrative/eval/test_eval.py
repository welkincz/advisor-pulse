"""Offline eval in CI: every recorded answer gets the verdict its recording expects."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

HERE = Path(__file__).parent


def _run_eval() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_eval", HERE / "run_eval.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_eval"] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


run_eval = _run_eval()
CASES = run_eval.load_cases()


def test_ten_frozen_cases_with_a_recording_each() -> None:
    assert len(CASES) == 10
    assert {c.case_id for c in CASES} == {p.stem for p in (HERE / "recorded").glob("*.json")}


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.case_id)
def test_recorded_answer_gets_the_expected_verdict(case: object) -> None:
    doc = json.loads((HERE / "recorded" / f"{case.case_id}.json").read_text())  # type: ignore[attr-defined]
    result = run_eval.score(case, doc["answer"])
    expected = doc.get("expected_pass", True)
    assert all(result.values()) is expected, result


def test_offline_eval_prints_a_pass_rate_table(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_eval.main([]) == 0
    out = capsys.readouterr().out
    assert "pass rate" in out and "8/10" in out


def test_live_eval_needs_a_key(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_eval.main(["--live"]) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
