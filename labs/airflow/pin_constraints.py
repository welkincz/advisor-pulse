"""Copy Airflow's official constraint pins into ``[tool.uv] constraint-dependencies``.

``uv lock`` has no ``--constraint`` flag, so the pins live in pyproject.toml. Only packages
in this lab's lock are pinned. Re-run, then ``uv lock``, until nothing changes:

    curl -sO https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-3.12.txt
    python3 labs/airflow/pin_constraints.py constraints-3.12.txt && uv lock --project labs/airflow
"""

import re
import sys
import tomllib
from pathlib import Path

LAB = Path(__file__).resolve().parent


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def main(constraints: Path) -> None:
    pins = {}
    for line in constraints.read_text().splitlines():
        if m := re.match(r"([A-Za-z0-9_.\-]+)==(\S+)", line.strip()):
            pins[norm(m.group(1))] = m.group(2)
    locked = {p["name"] for p in tomllib.loads((LAB / "uv.lock").read_text())["package"]}
    pyproject = (LAB / "pyproject.toml").read_text()
    pinned = set(re.findall(r'^    "([a-z0-9\-]+)==', pyproject, re.M))
    names = sorted((locked | pinned) & pins.keys())
    block = "".join(f'    "{n}=={pins[n]}",\n' for n in names)
    pyproject = re.sub(
        r"constraint-dependencies = \[\n.*?\]\n",
        f"constraint-dependencies = [\n{block}]\n",
        pyproject,
        flags=re.S,
    )
    (LAB / "pyproject.toml").write_text(pyproject)
    print(f"Pinned {len(names)} packages from {constraints.name}.")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
