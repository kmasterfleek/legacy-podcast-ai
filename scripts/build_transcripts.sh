#!/bin/bash
# Fetch English ASR captions for each target episode and render markdown.
#
# YouTube no longer exposes the source English caption track to the player
# clients yt-dlp can reach unauthenticated, but it DOES expose machine
# translations, whose signed URLs are the English track plus "&tlang=xx".
# Stripping tlang yields the original English ASR VTT.
#
# Usage: scripts/build_transcripts.sh [targets.tsv]   (id, yyyymmdd, seconds, title)
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SC="$BASE/scripts/data/cache"   # gitignored metadata/VTT cache
YTDLP="$BASE/.venv/bin/yt-dlp"
PY="$BASE/.venv/bin/python"
cd "$BASE"
mkdir -p transcripts "$SC/vtt" "$SC/json"

slug() {
  echo "$1" | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//' | cut -c1-70
}

ok=0; fail=0
while IFS=$'\t' read -r id date dur title; do
  [ -z "$id" ] && continue
  echo "[$id] $date  $(($dur/60))m  ${title:0:50}"
  J="$SC/json/$id.json"

  if [ ! -s "$J" ]; then
    "$YTDLP" --no-warnings --skip-download --sleep-requests 2 --retries 5 \
      --extractor-args "youtube:player_client=android" \
      -J "https://www.youtube.com/watch?v=$id" 2>/dev/null > "$J"
  fi
  if [ ! -s "$J" ]; then echo "  !! metadata fetch failed"; fail=$((fail+1)); continue; fi

  # Any translated track's URL -> strip &tlang= to get the English source.
  URL=$(jq -r '[.automatic_captions[]?[]? | select(.ext=="vtt") | .url] | .[0] // empty' "$J")
  if [ -z "$URL" ]; then echo "  !! no caption tracks exposed"; fail=$((fail+1)); continue; fi
  EN=$(echo "$URL" | sed -E 's/&tlang=[^&]*//')

  V="$SC/vtt/$id.vtt"
  curl -s --max-time 180 "$EN" -o "$V"
  if [ ! -s "$V" ] || ! grep -q -- "-->" "$V"; then
    echo "  !! caption download failed"; fail=$((fail+1)); continue
  fi
  echo "  vtt: $(wc -c < "$V" | tr -d ' ') bytes, $(grep -c -- '-->' "$V") cues"

  OUT="transcripts/${date}-$(slug "$title").md"
  if "$PY" scripts/vtt_to_md.py "$V" --meta "$J" --out "$OUT"; then
    ok=$((ok+1))
  else
    fail=$((fail+1))
  fi
done < "${1:-scripts/data/targets.tsv}"

echo "=== done: $ok ok, $fail failed ==="
