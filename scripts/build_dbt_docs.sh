#!/usr/bin/env bash
# Publish dbt docs as a static site at web/public/lineage/ (gitignored).
# Called by `make dbt-docs-static`. Lineage and the overview page come from
# the project manifest; catalog stats reflect whatever is already in the dev
# warehouse (empty until models have been built there).
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

out="${root}/web/public/lineage"
mkdir -p "$out" "${PULSE_DATA_DIR:-data}"

uv run dbt --no-use-colors docs generate \
  --project-dir dbt \
  --profiles-dir dbt \
  --static \
  --no-send-anonymous-usage-stats

test -s dbt/target/static_index.html
test -s dbt/target/manifest.json
test -s dbt/target/catalog.json

# --static inlines manifest and catalog into one index, so the page works
# from a static host (pulse.charliebuild.com/lineage/) with no extra server.
cp dbt/target/static_index.html "${out}/index.html"
cp dbt/target/manifest.json "${out}/manifest.json"
cp dbt/target/catalog.json "${out}/catalog.json"

echo "Static dbt docs written to ${out}"
