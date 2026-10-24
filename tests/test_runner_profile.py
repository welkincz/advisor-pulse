"""The runner profile records the same fields everywhere, from supplied command output (#336)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("runner_profile", ROOT / "scripts/runner_profile.py")
assert spec and spec.loader
profile_mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = profile_mod
spec.loader.exec_module(profile_mod)

LSCPU = """\
Architecture:                         x86_64
CPU(s):                               4
Model name:                           AMD EPYC 7763 64-Core Processor
Thread(s) per core:                   2
Hypervisor vendor:                    Microsoft
NUMA node0 CPU(s):                    0-3
"""


def _profile(**overrides: object) -> dict:
    kwargs: dict = {
        "lscpu": LSCPU,
        "nproc": "4\n",
        "python": "3.12.11",
        "packages": {"dbt-core": "1.12.5", "dbt-duckdb": "1.11.0", "duckdb": "1.5.6"},
        "env": {"ImageOS": "ubuntu26", "ImageVersion": "20261012.163.1", "GITHUB_SHA": "abc"},
        "profiles": (ROOT / "dbt" / "profiles.yml").read_text(),
        "duckdb_threads": 4,
    }
    kwargs.update(overrides)
    return profile_mod.build_profile(**kwargs)


def test_profile_has_the_fields_a_timing_comparison_needs() -> None:
    profile = _profile()
    assert profile["cpu"] == {
        "cpu_count": "4",
        "cpu_model": "AMD EPYC 7763 64-Core Processor",
        "threads_per_core": "2",
        "hypervisor": "Microsoft",
    }
    assert profile["nproc"] == 4
    assert profile["packages"] == {"dbt-core": "1.12.5", "dbt-duckdb": "1.11.0", "duckdb": "1.5.6"}
    assert profile["dbt_threads"] == {"dev": 4, "ci": 4}
    assert profile["runner"]["image_version"] == "20261012.163.1"
    assert profile["runner"]["commit_sha"] == "abc"
    assert set(profile) == {
        "cpu",
        "nproc",
        "python",
        "packages",
        "dbt_threads",
        "duckdb_threads",
        "runner",
    }


def test_missing_tools_leave_fields_empty_not_absent() -> None:
    profile = _profile(lscpu="", nproc="", packages={}, env={}, duckdb_threads=None)
    assert profile["cpu"] == {}
    assert profile["nproc"] is None
    assert profile["packages"] == {"dbt-core": None, "dbt-duckdb": None, "duckdb": None}
    assert set(profile["runner"]) == set(profile_mod.ENV_FIELDS)
    assert all(v is None for v in profile["runner"].values())


def test_only_named_environment_values_are_recorded(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "do-not-record")
    monkeypatch.setenv("GITHUB_SHA", "def")
    out = tmp_path / "artifacts" / "runner_profile.json"
    assert profile_mod.main(["--out", str(out)]) == 0
    text = out.read_text()
    assert "do-not-record" not in text
    assert json.loads(text)["runner"]["commit_sha"] == "def"
