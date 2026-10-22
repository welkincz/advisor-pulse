#!/usr/bin/env bash
# Publish dbt docs as a static site at web/public/lineage/ (gitignored), served at /lineage/.
# Called by `make dbt-docs-static` and by the weekly and backfill deploys. Lineage and the
# overview page come from the project manifest; catalog stats reflect the target's warehouse.
#
# Target: DBT_TARGET if set. Otherwise the real warehouse ($PULSE_DATA_DIR/warehouse.duckdb,
# target dev) when one exists, so the catalog describes what the site was built from; else
# the fixture warehouse (target ci), built with `make dbt-build-ci` if it is missing.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

data_dir="${PULSE_DATA_DIR:-data}"
out="${root}/web/public/lineage"
# Cloudflare Pages serves files up to 25 MiB; keep headroom for a growing manifest.
max_bytes=$((20 * 1024 * 1024))

target="${DBT_TARGET:-}"
if [[ -z "$target" ]]; then
  if [[ -s "${data_dir}/warehouse.duckdb" ]]; then target=dev; else target=ci; fi
fi
if [[ "$target" == ci && ! -s data/ci/warehouse.duckdb ]]; then
  make dbt-build-ci
fi
echo "Generating dbt docs against target ${target}"

mkdir -p "$data_dir"
uv run dbt --no-use-colors docs generate \
  --project-dir dbt \
  --profiles-dir dbt \
  --target "$target" \
  --static \
  --no-send-anonymous-usage-stats

test -s dbt/target/static_index.html
test -s dbt/target/manifest.json
test -s dbt/target/catalog.json

size=$(wc -c < dbt/target/static_index.html | tr -d ' ')
if (( size > max_bytes )); then
  echo "dbt docs index is ${size} bytes, above the ${max_bytes} byte budget" >&2
  exit 1
fi

# --static inlines manifest and catalog into one index, so the page works from a static
# host with no extra server. The dbt docs app needs inline and eval'd scripts, which the
# site-wide header policy forbids; public/_headers drops that header under /lineage/* and
# this page carries its own policy instead, still with no third-party origins.
csp="default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'"
rm -rf "$out"
mkdir -p "$out"
uv run python - "$csp" dbt/target/static_index.html "${out}/index.html" <<'PY'
import sys
from pathlib import Path

csp, source, dest = sys.argv[1:]
html = Path(source).read_text(encoding="utf-8")
meta = f'<meta http-equiv="Content-Security-Policy" content="{csp}">'
head = html.find("<head>")
if head < 0:
    sys.exit("dbt docs index has no <head>")
cut = head + len("<head>")
Path(dest).write_text(html[:cut] + meta + html[cut:], encoding="utf-8")
PY
cp dbt/target/manifest.json "${out}/manifest.json"
cp dbt/target/catalog.json "${out}/catalog.json"

echo "Static dbt docs (target ${target}, ${size} bytes) written to ${out}"
