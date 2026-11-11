#!/usr/bin/env bash
# One weekly DAG run with `airflow dags test`, in throwaway dirs. Usage, from the repo root:
#   labs/airflow/run_week.sh [RUN_AFTER]     (default 2026-11-09T06:00:00+00:00 → 2026-W45)
set -euo pipefail
LAB="$(cd "$(dirname "$0")" && pwd)"
RUN_AFTER="${1:-2026-11-09T06:00:00+00:00}"
WORK="$(mktemp -d -t pulse-airflow)"
export AIRFLOW_HOME="$WORK/airflow" PULSE_DATA_DIR="$WORK/data"
export AIRFLOW__CORE__DAGS_FOLDER="$LAB/dags" AIRFLOW__CORE__LOAD_EXAMPLES=False
AF=(uv run --project "$LAB" --frozen --quiet airflow)

"${AF[@]}" db migrate > "$WORK/migrate.log" 2>&1
start=$(python3 -c 'import time; print(time.time())')
"${AF[@]}" dags test pulse_weekly "$RUN_AFTER" > "$WORK/dags-test.log" 2>&1 || status=$?
end=$(python3 -c 'import time; print(time.time())')

grep -o '{"stage": [^}]*}' "$WORK/dags-test.log" || true
grep -o 'DagRun Finished: .*state=[a-z_]*' "$WORK/dags-test.log" | sed 's/, run_start.*state=/ … state=/' || true
python3 -c "print(f'wall time: {$end - $start:.1f} s (airflow dags test, incl. CLI start-up)')"
echo "logs and data: $WORK"
exit "${status:-0}"
