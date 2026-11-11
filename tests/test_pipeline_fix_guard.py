"""The guard that decides whether the pipeline doctor's fix may be pushed (#307)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "pipeline_fix_guard", ROOT / "scripts" / "pipeline_fix_guard.py"
)
assert spec and spec.loader
guard = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = guard
spec.loader.exec_module(guard)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "path",
    [
        "src/pulse/runner/alert.py",
        "src/pulse/quality/checks.py",
        "tests/runner/test_alert.py",
        "tests/conftest.py",
        "dbt/models/marts/mart_kpi.sql",
        "scripts/runner_profile.py",
    ],
)
def test_allows_code_tests_dbt_and_scripts(path: str) -> None:
    assert guard.path_violation(path) is None


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/weekly.yml",
        ".github/workflows/pipeline-doctor.yml",
        ".github/doctor-prompt.md",
        "src/pulse/contracts/activity.py",
        "docs/PLAN.md",
        "AGENTS.md",
        "CLAUDE.md",
        "pyproject.toml",
        "uv.lock",
        "web/pnpm-lock.yaml",
        "dbt/dbt_project.yml",
        "dbt/packages.yml",
        "dbt/package-lock.lock",
        "scripts/pipeline_fix_guard.py",
        "README.md",
        "docs/pipeline-doctor.md",
        "web/src/main.tsx",
        "Makefile",
        ".gitignore",
        "src/.git/hooks/pre-commit",
        "src/../.github/workflows/ci.yml",
        "src/./x.py",
        "src//x.py",
        "/src/x.py",
        "src\\..\\AGENTS.md",
        "",
    ],
)
def test_rejects_protected_and_unlisted_paths(path: str) -> None:
    assert guard.path_violation(path) is not None


def _change(path: str, old: str = "100644", new: str = "100644", status: str = "M") -> Any:
    return guard.Change(old, new, status, path)


def test_violations_need_at_least_one_change_and_list_every_reason() -> None:
    assert guard.violations([]) == ["no changes"]
    assert guard.violations([_change("src/pulse/runner/alert.py")]) == []
    found = guard.violations(
        [
            _change("src/pulse/runner/alert.py"),
            _change(".github/workflows/ci.yml", status="D"),
            _change("src/pulse/contracts/x.py", status="A", old="000000"),
        ]
    )
    assert len(found) == 2
    assert found[0].startswith(".github/workflows/ci.yml")
    assert found[1].startswith("src/pulse/contracts/x.py")


def test_rejects_symlinks_and_submodules_even_in_allowed_paths() -> None:
    assert guard.violations([_change("src/link", old="000000", new="120000", status="A")])
    assert guard.violations([_change("src/sub", old="000000", new="160000", status="A")])
    assert guard.violations([_change("src/was_link", old="120000", new="100644", status="T")])


def test_parse_raw_reads_nul_separated_entries() -> None:
    raw = (
        ":100644 100644 abc1234 def5678 M\0src/a b.py\0:000000 120000 0000000 1111111 A\0src/link\0"
    )
    assert guard.parse_raw(raw) == [
        guard.Change("100644", "100644", "M", "src/a b.py"),
        guard.Change("000000", "120000", "A", "src/link"),
    ]
    assert guard.parse_raw("") == []
    with pytest.raises(ValueError):
        guard.parse_raw(":100644 100644 abc def M\0")


@pytest.mark.parametrize(
    ("run_id", "attempt"),
    [
        ("123:main", "1"),
        ("123", "1:refs/heads/main"),
        ("+123", "1"),
        ("123", "-1"),
        ("123 main", "1"),
        ("../main", "1"),
        ("123/../../main", "1"),
        ("", "1"),
        ("123", ""),
        ("0", "1"),
        ("123\nmain", "1"),
        ("１２３", "1"),
    ],
)
def test_branch_name_rejects_refspec_tricks(run_id: str, attempt: str) -> None:
    with pytest.raises(ValueError):
        guard.branch_name(run_id, attempt)


def test_branch_name_is_namespaced_by_run_and_attempt() -> None:
    assert guard.branch_name("19234567890", "2") == "pipeline-fix/19234567890-2"


def test_find_secrets_names_patterns_without_echoing_them() -> None:
    token = "ghs_" + "a" * 36
    found = guard.find_secrets(f"log line {token} end")
    assert found and token not in " ".join(found)
    assert guard.find_secrets("sk-ant-oat01-" + "x" * 40)
    assert guard.find_secrets("https://x-access-token:abc@github.com/o/r.git")
    assert guard.find_secrets("-----BEGIN OPENSSH PRIVATE KEY-----")
    assert guard.find_secrets("Root cause: check DQ-07 failed at stage checks.") == []


def _git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    return subprocess.run(
        ["git", *args], cwd=repo, env=env, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    for rel in ("src/pulse/runner/alert.py", ".github/workflows/ci.yml", "AGENTS.md"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "switch", "-qc", "fix")
    return tmp_path


def _commit(repo: Path) -> list[str]:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fix")
    return guard.violations(guard.git_changes("main", cwd=repo))


def test_git_diff_accepts_a_fix_in_src(repo: Path) -> None:
    (repo / "src/pulse/runner/alert.py").write_text("x = 2\n")
    assert _commit(repo) == []


def test_git_diff_rejects_a_workflow_change(repo: Path) -> None:
    (repo / "src/pulse/runner/alert.py").write_text("x = 2\n")
    (repo / ".github/workflows/ci.yml").write_text("x = 2\n")
    assert _commit(repo) == [".github/workflows/ci.yml: protected directory"]


def test_git_diff_sees_the_deleted_side_of_a_rename(repo: Path) -> None:
    _git(repo, "mv", ".github/workflows/ci.yml", "src/ci.yml")
    found = _commit(repo)
    assert ".github/workflows/ci.yml: protected directory" in found


def test_git_diff_rejects_a_symlink_into_github(repo: Path) -> None:
    (repo / "src/escape").symlink_to("../.github/workflows/ci.yml")
    assert _commit(repo) == ["src/escape: symlink"]


def test_cli_exit_codes(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "AGENTS.md").write_text("changed\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fix")
    cwd = Path.cwd()
    os.chdir(repo)
    try:
        assert guard.main(["paths", "--base", "main"]) == 1
    finally:
        os.chdir(cwd)
    assert "AGENTS.md: protected file" in capsys.readouterr().err
    assert guard.main(["branch", "123", "1"]) == 0
    assert capsys.readouterr().out.strip() == "pipeline-fix/123-1"
    assert guard.main(["branch", "123:main", "1"]) == 1
    clean = repo / "report.md"
    clean.write_text("Root cause: DQ-07.\n")
    assert guard.main(["secrets", str(clean)]) == 0
    clean.write_text("ghp_" + "b" * 36)
    assert guard.main(["secrets", str(clean)]) == 1
