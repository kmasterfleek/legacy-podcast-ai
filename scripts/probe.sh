#!/bin/bash
# Probe recent ALL THE SMOKE uploads for upload_date + duration.
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
YTDLP="$BASE/.venv/bin/yt-dlp"
CH="https://www.youtube.com/channel/UC2ozVs4pg2K3uFLw6-0ayCQ/videos"
# Usage: probe.sh [ids_file] [out_tsv] [playlist_end]
IDS="${1:-scripts/data/scratch_ids.txt}"
OUT="${2:-scripts/data/scratch_meta.tsv}"

cd "$BASE"
[ -s "$IDS" ] || $YTDLP --no-warnings --flat-playlist --playlist-end "${3:-120}" \
  --print "%(id)s" "$CH" 2>/dev/null > "$IDS"

probe_one() {
  id="$1"
  Y="$YTDLP"
  for client in android tv web_safari; do
    out=$("$Y" --no-warnings --skip-download --socket-timeout 20 --retries 3 \
      --extractor-args "youtube:player_client=$client" \
      --print "%(id)s|||%(upload_date)s|||%(duration)s|||%(title)s" \
      "https://www.youtube.com/watch?v=$id" 2>/dev/null | tail -1)
    if [ -n "$out" ]; then echo "$out"; return 0; fi
  done
  echo "$id|||FAIL|||0|||FAIL"
}
export -f probe_one
export YTDLP
xargs -P 6 -I{} bash -c 'probe_one "$@"' _ {} < "$IDS" > "$OUT"
echo "probed OK: $(grep -vc 'FAIL' "$OUT") / $(wc -l < "$OUT")"
