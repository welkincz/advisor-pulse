"""Point Airflow at a throwaway home before it is imported, and migrate its SQLite DB once."""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

LAB = Path(__file__).resolve().parents[1]
_HOME = Path(tempfile.mkdtemp(prefix="pulse-airflow-home-"))
atexit.register(shutil.rmtree, _HOME, ignore_errors=True)
os.environ.update(
    {
        "AIRFLOW_HOME": str(_HOME),
        "AIRFLOW__CORE__DAGS_FOLDER": str(LAB / "dags"),
        "AIRFLOW__CORE__LOAD_EXAMPLES": "False",
        "AIRFLOW__CORE__UNIT_TEST_MODE": "False",
        # Retries wait 1 s in tests instead of 5 min; read when the DAG file is parsed.
        "PULSE_AIRFLOW_RETRY_DELAY_S": "1",
    }
)
os.environ.setdefault("PULSE_DATA_DIR", str(_HOME / "data"))


@pytest.fixture(scope="session")
def airflow_db() -> Path:
    airflow = Path(sys.executable).with_name("airflow")
    subprocess.run([str(airflow), "db", "migrate"], check=True, capture_output=True)
    return _HOME
