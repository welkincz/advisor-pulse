"""Record the machine and versions a run used, so timings can be compared fairly (#336).

Prints a short profile to the step log and, with --out, writes it as JSON for the run
artifact. Only named fields are read: never the environment as a whole.

    uv run python scripts/runner_profile.py --out data/artifacts/runner_profile.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("dbt-core", "dbt-duckdb", "duckdb")
# Runner metadata Actions sets; values only, never secrets.
ENV_FIELDS = {
    "runner_os": "RUNNER_OS",
    "runner_arch": "RUNNER_ARCH",
    "image_os": "ImageOS",
    "image_version": "ImageVersion",
    "commit_sha": "GITHUB_SHA",
    "workflow": "GITHUB_WORKFLOW",
    "run_id": "GITHUB_RUN_ID",
}
LSCPU_FIELDS = {
    "Model name": "cpu_model",
    "CPU(s)": "cpu_count",
    "Thread(s) per core": "threads_per_core",
    "CPU max MHz": "cpu_max_mhz",
    "Hypervisor vendor": "hypervisor",
}


def parse_lscpu(text: str) -> dict[str, str]:
    """The fields of `lscpu` output that tell two runners apart."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() in LSCPU_FIELDS:
            out.setdefault(LSCPU_FIELDS[key.strip()], value.strip())
    return out


def dbt_threads(profiles: str, target: str) -> int | None:
    """`threads` of one target in dbt/profiles.yml, read without a YAML dependency."""
    in_target = False
    for line in profiles.splitlines():
        stripped = line.strip()
        if stripped == f"{target}:":
            in_target = True
        elif in_target and stripped.endswith(":") and not stripped.startswith("#"):
            if len(line) - len(line.lstrip()) <= 4:  # the next target
                in_target = False
        elif in_target and stripped.startswith("threads:"):
            return int(stripped.split(":", 1)[1])
    return None


def build_profile(
    *,
    lscpu: str,
    nproc: str,
    python: str,
    packages: dict[str, str | None],
    env: dict[str, str],
    profiles: str,
    duckdb_threads: int | None,
) -> dict[str, Any]:
    """The profile from command output and named values: pure, so it is testable."""
    return {
        "cpu": parse_lscpu(lscpu),
        "nproc": int(nproc) if nproc.strip().isdigit() else None,
        "python": python,
        "packages": {name: packages.get(name) for name in PACKAGES},
        "dbt_threads": {t: dbt_threads(profiles, t) for t in ("dev", "ci")},
        "duckdb_threads": duckdb_threads,
        "runner": {field: env.get(name) for field, name in ENV_FIELDS.items()},
    }


def _command(*args: str) -> str:
    if shutil.which(args[0]) is None:
        return ""
    return subprocess.run(args, capture_output=True, text=True, check=False).stdout


def _version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _duckdb_threads() -> int | None:
    try:
        import duckdb
    except ImportError:
        return None
    return int(duckdb.sql("select current_setting('threads')").fetchone()[0])  # type: ignore[index]


def collect() -> dict[str, Any]:
    return build_profile(
        lscpu=_command("lscpu"),
        nproc=_command("nproc") or str(os.cpu_count() or ""),
        python=platform.python_version(),
        packages={name: _version(name) for name in PACKAGES},
        env={name: os.environ[name] for name in ENV_FIELDS.values() if name in os.environ},
        profiles=(ROOT / "dbt" / "profiles.yml").read_text(),
        duckdb_threads=_duckdb_threads(),
    )


def summary(profile: dict[str, Any]) -> str:
    cpu, runner = profile["cpu"], profile["runner"]
    versions = ", ".join(f"{k} {v}" for k, v in profile["packages"].items())
    return (
        f"Runner profile: {cpu.get('cpu_model', 'unknown CPU')}, nproc {profile['nproc']}, "
        f"image {runner.get('image_os')} {runner.get('image_version')}, "
        f"Python {profile['python']}, {versions}, dbt threads {profile['dbt_threads']}, "
        f"DuckDB threads {profile['duckdb_threads']}, commit {runner.get('commit_sha')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, help="also write the profile as JSON here")
    args = parser.parse_args(argv)
    profile = collect()
    print(summary(profile))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
