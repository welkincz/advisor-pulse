#!/usr/bin/env bash
# Check that a Pages deployment serves the recap video it was built with.
# Usage: check_recap.sh <built site dir> <deployment URL>
# Writes the response headers to the log and a line to the step summary. It warns rather than
# fails: the video is optional, and the page hides the section when the mp4 is not video.
set -uo pipefail
dist=$1
url=${2%/}
summary=${GITHUB_STEP_SUMMARY:-/dev/null}

if [[ ! -f "$dist/recap/recap.mp4" ]]; then
  echo "Recap video: not in this deploy (the page shows no recap section)." | tee -a "$summary"
  exit 0
fi
if [[ -z "$url" ]]; then
  echo "::warning::The deployment URL is unknown; the recap video was not checked."
  echo "Recap video: not checked (no deployment URL in the wrangler output)." >> "$summary"
  exit 0
fi

type=''
for attempt in 1 2 3 4 5; do
  headers=$(curl -sSI --max-time 20 "$url/recap/recap.mp4" || true)
  echo "curl -sI $url/recap/recap.mp4 (attempt $attempt)"
  echo "$headers" | grep -iE '^(HTTP|content-type|content-length|cache-control|etag)'
  type=$(echo "$headers" | tr -d '\r' | awk -F': *' 'tolower($1) == "content-type" {print tolower($2)}' | tail -n 1)
  [[ "$type" == video/mp4* ]] && break
  sleep "${RECAP_CHECK_DELAY:-5}"
done

if [[ "$type" == video/mp4* ]]; then
  echo "Recap video: $url/recap/recap.mp4 serves video/mp4." >> "$summary"
else
  echo "::warning::$url/recap/recap.mp4 answers ${type:-no content type}, not video/mp4; the recap section stays hidden."
  echo "Recap video: $url/recap/recap.mp4 answers ${type:-no content type}, not video/mp4." >> "$summary"
fi
