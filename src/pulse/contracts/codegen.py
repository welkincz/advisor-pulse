"""Write JSON Schema files for every contract to ``contracts/schemas/``.

python -m pulse.contracts.codegen          # write
python -m pulse.contracts.codegen --check  # exit 1 if committed files are stale
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pulse.contracts import REGISTRY, SCHEMA_VERSION, Contract

DEFAULT_OUT = Path(__file__).resolve().parents[3] / "contracts" / "schemas"


def schema_for(model: type[Contract]) -> dict[str, Any]:
    schema = model.model_json_schema(by_alias=True, mode="validation")
    schema["$id"] = f"https://pulse.charliebuild.com/contracts/{model.contract_name}.schema.json"
    schema["title"] = model.contract_name
    if model.contract_description:
        schema["description"] = model.contract_description
    schema["x-contract-kind"] = model.contract_kind
    schema["x-schema-version"] = SCHEMA_VERSION
    return schema


def render() -> dict[str, str]:
    """File name → file content for every registered contract."""
    return {
        f"{name}.schema.json": json.dumps(schema_for(model), indent=2, sort_keys=True) + "\n"
        for name, model in sorted(REGISTRY.items())
    }


def write(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    expected = render()
    for stale in out_dir.glob("*.schema.json"):
        if stale.name not in expected:
            stale.unlink()
    written = []
    for name, content in expected.items():
        path = out_dir / name
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


def stale_files(out_dir: Path) -> list[str]:
    """Names that are missing, different, or no longer registered."""
    expected = render()
    problems = []
    for name, content in expected.items():
        path = out_dir / name
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            problems.append(name)
    problems += [p.name for p in out_dir.glob("*.schema.json") if p.name not in expected]
    return sorted(problems)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--check", action="store_true", help="Fail if files are stale.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    if args.check:
        problems = stale_files(args.out)
        if problems:
            print("Stale contract schemas (run `make contracts`):", file=sys.stderr)
            for name in problems:
                print(f"  {name}", file=sys.stderr)
            return 1
        print(f"contracts/schemas is up to date ({len(REGISTRY)} contracts).")
        return 0

    written = write(args.out)
    print(f"Wrote {len(written)} schemas to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
