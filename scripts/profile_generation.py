"""Time fresh default-scale workers against main; require byte identity and <5s per trial.

The previous week's initial 52-week history load is setup, excluded from weekly timings.
Run with ``uv run python scripts/profile_generation.py --out generator-profile.json``.
"""

from __future__ import annotations

import argparse
import cProfile
import hashlib
import json
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def worker(args: argparse.Namespace) -> None:
    sys.path.insert(0, str(args.source / "src"))
    from pulse.generate import cli as gen

    assert Path(gen.__file__).resolve().is_relative_to(args.source.resolve())
    profiler = cProfile.Profile()
    if args.profile:
        profiler.enable()
    started = time.perf_counter()
    written = gen.generate_weeks(args.data, [args.week], seed=gen.DEFAULT_SEED, echo=lambda _: None)
    elapsed = time.perf_counter() - started
    profiler.disable()
    assert written == 1, "The requested week exists; this would time a no-op."
    if args.profile:
        profiler.dump_stats(args.profile)
    files = {
        p.relative_to(args.data).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(args.data.rglob("*"))
        if p.is_file()
    }
    print(
        json.dumps(
            {
                "seconds": elapsed,
                "files": files,
                "defaults": [gen.DEFAULT_SEED, gen.DEFAULT_ADVISORS, gen.DEFAULT_CLIENTS],
            }
        )
    )


def run_worker(source: Path, data: Path, week: str, profile: Path | None = None) -> dict[str, Any]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--source",
        str(source),
        "--data",
        str(data),
        "--week",
        week,
    ]
    if profile:
        command.extend(["--profile", str(profile)])
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr[-4000:])
    return json.loads(result.stdout)


def compare(args: argparse.Namespace) -> None:
    base = subprocess.check_output(["git", "merge-base", args.base, "HEAD"], text=True).strip()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    args.out = args.out.resolve()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "base": base,
        "head": head,
        "week": args.week,
        "trials": {},
    }
    with tempfile.TemporaryDirectory(prefix="pulse-generation-") as temp:
        root = Path(temp)
        source = root / "base"
        source.mkdir()
        archive = root / "base.tar"
        with archive.open("wb") as output:
            subprocess.run(["git", "archive", base, "src", "reference"], stdout=output, check=True)
        with tarfile.open(archive) as bundle:
            bundle.extractall(source, filter="data")
        monday = date.fromisoformat(f"{args.week}-1") - timedelta(weeks=1)
        year, week, _ = monday.isocalendar()
        prefix = root / "prefix"
        run_worker(source, prefix, f"{year}-W{week:02d}")
        expected = None
        for trial in range(args.trials):
            # Balance trial order; never share Python process caches across workers.
            for label in ("base", "head") if trial % 2 == 0 else ("head", "base"):
                data = root / f"{label}-{trial}"
                shutil.copytree(prefix, data)
                result = run_worker(source if label == "base" else ROOT, data, args.week)
                if expected is None:
                    expected = result
                assert result["defaults"] == expected["defaults"], "Seed/scale changed"
                assert result["files"] == expected["files"], f"{label} trial {trial}: bytes differ"
                report["trials"].setdefault(label, []).append(result["seconds"])
        report.update(files=expected["files"], defaults=expected["defaults"])
        for label, version in (("base", source), ("head", ROOT)):
            data = root / f"profile-{label}"
            shutil.copytree(prefix, data)
            result = run_worker(
                version, data, args.week, profile=args.out.with_suffix(f".{label}.pstats")
            )
            assert result["files"] == expected["files"]
    lines = [
        f"Week {args.week}; fresh workers; defaults; {len(report['files'])} files identical.",
        f"Base `{base[:7]}`; head `{head[:7]}`. Initial history setup excluded.",
        "",
        "| Unprofiled seconds | Base | Head |",
        "|---|---:|---:|",
    ]
    for name, fn in (("Median", statistics.median), ("Maximum", max)):
        lines.append(
            f"| {name} | {fn(report['trials']['base']):.3f} | {fn(report['trials']['head']):.3f} |"
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    args.out.with_suffix(".md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    if max(report["trials"]["head"]) >= args.max_seconds:
        raise SystemExit(
            f"Weekly generation exceeded {args.max_seconds:g}s; see every trial in JSON."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--week", default="2026-W42")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--max-seconds", type=float, default=5)
    parser.add_argument("--out", type=Path, default=Path("generator-profile.json"))
    for name in ("source", "data"):
        parser.add_argument(f"--{name}", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--profile", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.source:
        worker(args)
    else:
        if args.trials < 1 or args.max_seconds <= 0:
            parser.error("trials and max-seconds must be positive")
        compare(args)


if __name__ == "__main__":
    main()
