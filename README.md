# Legacy Podcast AI

Turn a creator's entire back catalog into clean, searchable, timestamped transcripts.

Legacy Podcast AI is a command-line harness that takes any podcast, YouTube
channel, playlist, or video series and produces one markdown transcript per
episode, with YAML frontmatter, paragraph-level timestamps that deep-link back
to the source, an index page, and a validation report. It is resumable, so a
catalog of a thousand episodes can be harvested over several sessions without
redoing work.

It was built on the [All The Smoke](https://www.youtube.com/channel/UC2ozVs4pg2K3uFLw6-0ayCQ)
podcast, where it produced 126 full-episode transcripts (about 1.7 million
words) spanning 2021 to 2026, and then generalized so it works for any show.

## Who this is for

This tool is offered to **the creators and rights-holders of a show**: the
podcast host, the production company, or the network that owns the series.
Your archive is your asset. Transcripts make it searchable, quotable,
repurposable for clips and newsletters, and usable as grounding data for AI
assistants trained on your own material.

It is not intended for transcribing and redistributing other people's content.
Run it against shows you own or have permission to process.

## How it works

```
sources (channel / playlist / URLs / local files)
        │
        ▼
   discover ──► catalog.json      every episode: id, title, date, duration
        │
        ▼
     build  ──► providers        1. manual subtitles
        │                        2. platform auto-captions (ASR)
        │                        3. Whisper on downloaded audio (optional)
        ▼
    render  ──► transcripts/*.md  frontmatter + timestamped paragraphs
        │
        ▼
   validate ──► flags            word rate, structure, duplicates
        │
        ▼
    manifest.json                 per-episode status; drives resumption
```

**Discover** enumerates every source with yt-dlp, then probes each new video
for its upload date and duration so the series filters (minimum length, title
patterns) can be applied. Results accumulate in a catalog that is never
thrown away.

**Build** walks the in-scope, not-yet-done episodes and tries providers in
order until one yields timed cues. Manual subtitles are preferred because
creators who upload their own captions get the cleanest text. Otherwise the
platform's automatic captions are used. YouTube hides its English ASR track
from anonymous clients but still exposes machine translations of it, and a
translated track's URL is simply the original plus a `tlang` parameter, so the
tool strips that parameter to recover the source-language track. When neither
exists and ffmpeg plus a Whisper backend are installed, it downloads the audio
and transcribes locally.

**Render** collapses YouTube's rolling two-cue caption format, de-duplicates
overlapping words, breaks the text into paragraphs of roughly 45 seconds or
110 words on sentence boundaries, and writes markdown with a timestamp heading
per paragraph that links straight to that moment in the video.

**Validate** checks every transcript for complete frontmatter, a plausible
words-per-minute rate (60 to 250), enough timestamped paragraphs, and duplicate
episode ids across files.

## Installation

Requires Python 3.9 or newer. Python 3.10+ is recommended because yt-dlp has
deprecated 3.9.

```bash
git clone <this repo>
cd legacy-podcast-ai
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/legacy doctor
```

Optional, for episodes with no captions at all or for local media files:

```bash
brew install ffmpeg            # or your platform's package manager
.venv/bin/pip install -e ".[whisper]"
```

`legacy doctor` reports which of these are available.

## Quick start

```bash
# 1. Describe the show. Sources are repeatable; use a channel, a playlist, or both.
legacy init "All The Smoke" \
  --url "https://www.youtube.com/channel/UC2ozVs4pg2K3uFLw6-0ayCQ/videos" \
  --url "https://www.youtube.com/playlist?list=PL6fkKAMsPY-HOH4B2Gz6vcOavn-JwOqxx" \
  --min-minutes 25 \
  --exclude "unplugged|watch party"

# 2. Discover, build, index and validate in one go. Start small.
legacy run all-the-smoke --limit 20

# 3. Check progress, then keep going. Re-running only touches pending work.
legacy status
legacy build all-the-smoke
```

Transcripts land in `series/all-the-smoke/transcripts/`, alongside an
`index.md` listing every episode newest first.

## Commands

| Command | What it does |
|---|---|
| `legacy init NAME --url URL [...]` | Create a series folder and config |
| `legacy add-source SERIES URL [...]` | Add more sources to an existing series |
| `legacy config SERIES --exclude ... --min-minutes ...` | Change filters, language, throttling, cookies |
| `legacy discover SERIES` | Enumerate sources and probe episode metadata |
| `legacy build SERIES [--limit N] [--workers N] [--since DATE] [--id ID] [--retry-failed]` | Fetch transcripts for pending episodes |
| `legacy validate SERIES [--strict]` | Sanity-check built transcripts (`--strict` exits non-zero on flags) |
| `legacy run SERIES` | discover + build + index + validate |
| `legacy import SERIES FILE [...]` | Add local audio or video files to a series |
| `legacy status [SERIES] [--json]` | Progress per series, with failure reasons |
| `legacy doctor` | Check yt-dlp, ffmpeg, ffprobe, Whisper |

Every command accepts `--help`.

## Series configuration

`legacy init` writes `series/<slug>/series.json`. All fields can be changed
later with `legacy config`.

| Field | Default | Meaning |
|---|---|---|
| `sources` | `[]` | Channel, playlist, or video URLs. Anything yt-dlp can list. |
| `language` | `"en"` | Preferred caption language. |
| `min_minutes` / `max_minutes` | `0` / none | Duration window. Use `min_minutes` to skip clips and shorts. |
| `include` / `exclude` | none | Case-insensitive regexes on the title. |
| `providers` | `["captions", "whisper"]` | Order in which transcript sources are tried. |
| `max_entries` | `0` | Only the newest N entries per source. `0` means everything. |
| `request_sleep` | `1.0` | Seconds between yt-dlp requests. |
| `cookies_from_browser` | none | `chrome`, `firefox`, `safari`, `edge`, or `brave`. |
| `cookies_file` | none | Path to a Netscape-format `cookies.txt`. |
| `transcripts_dir` | `transcripts` | Output folder, relative to the series folder. |
| `player_clients` | `["android", "tv", "web"]` | YouTube player clients to try, in order. |

## Output format

Each transcript is a standalone markdown file named `YYYYMMDD-slug.md`
(episodes with season and episode numbers get an `sNNeNN` prefix).

```markdown
---
title: "Kevin Garnett: The NBA's Greatest Storyteller"
show: "All The Smoke"
video_id: "KSDG65xur20"
url: "https://www.youtube.com/watch?v=KSDG65xur20"
upload_date: "2026-08-22"
duration: "00:46:07"
word_count: 10616
transcript_source: "automatic captions (ASR), en"
---

# Kevin Garnett: The NBA's Greatest Storyteller

**Show:** All The Smoke · **Aired:** 2026-08-22 · **Runtime:** 00:46:07
**Source:** <https://www.youtube.com/watch?v=KSDG65xur20>

> Transcript source: automatic captions (ASR), en. ...

##### [`00:00:04`](https://www.youtube.com/watch?v=KSDG65xur20&t=4s)

Come see me. Think y'all getting this for free. ...
```

The frontmatter is machine-readable, so the folder drops straight into a
static site generator, a search index, or a retrieval pipeline. The
`transcript_source` field tells you how trustworthy the text is: manual
subtitles are best, ASR carries occasional misheard names and no speaker
labels, and machine-translated tracks are a last resort.

## Rate limits and authentication

YouTube throttles anonymous metadata requests. Crawling a channel of roughly
two thousand videos in one sitting triggered an HTTP 429 and a
"sign in to confirm you're not a bot" block after about 1,200 probes. The
harness now:

- sleeps between requests (`request_sleep`, default 1 second) and defaults to 3
  workers;
- detects the block and stops discovery early with a clear message instead of
  recording hundreds of failures;
- re-probes anything that lacks metadata on the next `discover`, so nothing is
  lost.

The block usually lifts within hours. For large catalogs, either spread
discovery across sessions or authenticate with the creator's own account:

```bash
legacy config my-show --cookies-from-browser chrome
```

Logging in as the channel owner is the cleanest path, and it also exposes
caption tracks that YouTube withholds from anonymous clients.

## Local files and video series

For a series that is not online, or for higher-quality transcription than
platform captions, import the media directly:

```bash
legacy init "My Show" --providers whisper
legacy import my-show ~/Videos/my-show/*.mp4
legacy build my-show
```

This path needs ffmpeg and a Whisper backend (`faster-whisper` via
`pip install -e ".[whisper]"`, or the `openai-whisper` CLI). Durations are read
with ffprobe when available.

## Adopting existing transcripts

If a series already has transcripts in the output folder with the frontmatter
shown above, `legacy build` marks them done by their `video_id` before doing
anything else. That is how a catalog started with older tooling carries over
without being rebuilt.

## Project layout

```
src/legacyai/
  cli.py        argparse entry point (`legacy`)
  config.py     Series dataclass, on-disk layout, filters
  catalog.py    source listing, metadata probing, local import, rate-limit abort
  providers.py  captions provider (manual / ASR / tlang trick), whisper provider
  render.py     VTT and SRT parsing, paragraphing, markdown, frontmatter reader
  build.py      resumable build loop, filename collision handling, index page
  validate.py   transcript checks and status summary
tests/
  test_legacyai.py   offline unit tests (no network)
series/<slug>/
  series.json        committed
  catalog.json, manifest.json, cache/, transcripts/   runtime data, ignored
scripts/
  build_transcripts.sh, probe.sh, vtt_to_md.py   the original shell prototype
```

## Development

```bash
.venv/bin/python -m unittest tests/test_legacyai.py -v
```

The tests cover cue parsing for both YouTube's rolling ASR format and plain
SRT, paragraph breaking, frontmatter round-tripping including quotes and
backslashes, caption-track priority and the source-language guard on the
`tlang` trick, filename collision handling for same-day and non-Latin titles,
and the series filters.

Design constraints worth keeping:

- Only the main thread writes the catalog and manifest; workers return records.
- Every provider failure is a short, stable reason string that shows up in
  `legacy status`, so a batch never fails silently.
- Files stay under 500 lines and the package has one runtime dependency,
  yt-dlp. Whisper is optional.

## Roadmap

- Speaker diarization, so multi-host shows get labeled turns.
- A hosted version where a creator connects their channel and receives a
  finished archive plus a private search page.
- Chapter detection from the platform's chapter markers.
- Export to JSON and SRT alongside markdown.
- Automatic re-discovery on a schedule so new episodes are transcribed as they
  are published.

## Status

Working, tested, and reviewed. Built and validated on two shows. Python 3.9 is
supported today but yt-dlp has deprecated it, so plan on 3.10 or newer.
