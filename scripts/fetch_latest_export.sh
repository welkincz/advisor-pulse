#!/usr/bin/env bash
# Download the newest successful weekly run's published export (all regions, every week)
# into data/web-latest, for `make web-dev-latest`. The fixtures cover only an Ontario and
# Quebec slice, so this is the way to see the full synthetic network locally. Needs `gh`.
set -euo pipefail
dest="${1:-data/web-latest}"
repo="${PULSE_REPO:-welkincz/advisor-pulse}"
# Only runs on main publish the site; a weekly run dispatched from a branch does not.
run_id="$(gh run list -R "$repo" --workflow weekly.yml --branch main --status success -L 1 --json databaseId -q '.[0].databaseId // empty')"
if [[ -z "$run_id" ]]; then
  echo "No successful weekly run found in $repo." >&2
  exit 1
fi
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
gh run download "$run_id" -R "$repo" -n "pages-deploy-$run_id" -D "$tmp"
rm -rf "$dest"
mkdir -p "$(dirname "$dest")"
cp -R "$tmp/data" "$dest"
echo "Weekly run $run_id export in $dest ($(du -sh "$dest" | cut -f1))."
