# Legacy Podcast AI

**From Mighty Mouse to this morning's episode: every era of a catalog, transcribed.**

Legacy Podcast AI turns a creator's complete archive into clean, timestamped,
searchable transcripts. It doesn't matter whether the archive is a 1942
black-and-white Terrytoons short sitting on the Internet Archive, a 1990s
television series on DVD, a decade of audio-only podcast episodes behind an
RSS feed, or a YouTube channel that posted a new interview an hour ago. One
tool, one output format, one index.

It was built on the [All The Smoke](https://www.youtube.com/channel/UC2ozVs4pg2K3uFLw6-0ayCQ)
podcast, where it produced 471 full-episode transcripts (about 6.3 million
words) covering the show from its first episode in 2019 to this week, drawing
on YouTube captions and the show's own published podcast transcripts. Then it was pointed at the other end of the
century: Mighty Mouse cartoons from 1945, with no captions anywhere, came out
as lyric-accurate transcripts from the original soundtrack.

## Who this is for

This tool is offered to **the creators and rights-holders of a catalog**: the
host, the studio, the estate, the network that owns the series. An archive is
an asset. Transcripts make it searchable, quotable, repurposable for clips and
newsletters, and usable as grounding data for AI assistants trained on your
own material. The older the catalog, the more of it has never been written
down anywhere.

It is not intended for transcribing and redistributing other people's content.
Run it against material you own or have permission to process.

## Every era, one pipeline

| Era | Typical home | How Legacy gets the words |
|---|---|---|
| 1930s to 1960s film and cartoons | Internet Archive, personal film scans | Whisper on the original soundtrack; music-safe settings |
| 1950s to 1990s television | DVD or tape rips on disk | Local file import, Whisper, season/episode naming |
| 1990s to 2010s radio and early podcasts | RSS feeds, MP3 archives | Feed enclosures, published transcripts when present, else Whisper |
| 2010s to today video podcasts | YouTube channels and playlists | Manual subtitles, then platform captions, then Whisper |
| Today | Any of the above, re-run on a schedule | Only new episodes are touched |

Sources can be mixed within one series. A show that started on radio, moved to
YouTube, and has a public-domain prequel on the Internet Archive is one
`series.json` with three source URLs.

### Sources

- **YouTube and 1,800 other sites** via yt-dlp: channels, playlists, tabs,
  single videos.
- **Internet Archive**: a single item, a whole collection, or a search query
  (`ia:title:(mighty mouse) AND date:[1942 TO 1961]`). Public-domain marks and
  licence URLs are carried into the transcript.
- **RSS podcast feeds**: any RSS 2.0 feed with enclosures. Podcasting 2.0
  `<podcast:transcript>` tags are honoured, so shows that already publish
  transcripts skip transcription entirely.
- **Local files**: audio or video on disk, for anything not online.

### Transcript providers, in order

1. **Manual subtitles** uploaded by the creator. The cleanest text available.
2. **Published transcripts** shipped alongside the media: RSS transcript tags,
   `.srt` and `.vtt` files on Internet Archive items.
3. **Platform captions.** YouTube hides its English auto-captions from
   anonymous clients but exposes machine translations of them; a translated
   track's URL is the original plus a `tlang` parameter, so the tool strips
   it to recover the source-language track.
4. **Whisper**, run locally with `faster-whisper`. No ffmpeg required. Model
   size and voice-activity filtering are configurable per series, which
   matters for archival material: the filter that helps a modern podcast
   throws away narration sung over a 1945 orchestra.

Each transcript records which provider produced it, so you always know how
much to trust the words. When a published transcript carries WebVTT voice
tags, speaker turns are kept: each change of speaker starts a new, labeled
paragraph, and the frontmatter records `speaker_labels: true`.

### One episode, many sources

A show often lives in several places at once: a YouTube upload and a podcast
feed entry for the same interview, sometimes under different titles. Build
links these automatically before transcribing anything. Entries published
within three days of an existing transcript whose titles share the episode
number or distinctive words are recorded as duplicates and never rebuilt.
`legacy dedupe SERIES --dry-run` shows the matches first. The matcher is
deliberately conservative, because skipping a real episode is worse than an
extra file.

## How it works

```
sources (YouTube / Internet Archive / RSS / local files)
        │
        ▼
   discover ──► catalog.json      every episode: id, title, date, duration
        │
        ▼
     build  ──► providers         subtitles → published → captions → Whisper
        │
        ▼
    render  ──► transcripts/*.md  frontmatter + timestamped paragraphs
        │
        ▼
   validate ──► flags             word rate, structure, duplicates
        │
        ▼
    manifest.json                 per-episode status; drives resumption
```

**Discover** enumerates every source and records each episode's date and
duration so filters (minimum length, title patterns) can be applied. The
catalog accumulates and is never thrown away.

**Build** walks in-scope, not-yet-done episodes and tries providers in order
until one yields timed cues. Media is fetched once and cached.

**Render** collapses YouTube's rolling caption format, de-duplicates
overlapping words, breaks text into paragraphs of roughly 45 seconds or 110
words on sentence boundaries, and writes markdown with a timestamp heading per
paragraph. YouTube timestamps deep-link to that moment in the video.

**Validate** checks frontmatter, words-per-minute against configurable bounds,
paragraph count, and duplicate ids.

## Installation

Python 3.9 or newer (3.10+ recommended; yt-dlp has deprecated 3.9).

```bash
git clone https://github.com/kmasterfleek/legacy-podcast-ai.git
cd legacy-podcast-ai
python3 -m venv .venv
.venv/bin/pip install -e ".[whisper]"
.venv/bin/legacy doctor
```

The `[whisper]` extra installs `faster-whisper`, which decodes audio and video
itself, so ffmpeg is optional. Models download on first use (the default
`small` is about 460 MB; `medium` is about 1.5 GB and noticeably better on old
or noisy audio).

## Quick start

**A modern video podcast on YouTube**

```bash
legacy init "All The Smoke" \
  --url "https://www.youtube.com/channel/UC2ozVs4pg2K3uFLw6-0ayCQ/videos" \
  --min-minutes 25 --exclude "unplugged|watch party"
legacy run all-the-smoke --limit 20
```

**A 1940s cartoon series on the Internet Archive**

```bash
legacy init "Mighty Mouse (Terrytoons)" \
  --url "ia:title:(mighty mouse) AND mediatype:movies AND date:[1942-01-01 TO 1961-12-31]" \
  --min-minutes 3 --max-minutes 15 --exclude "trailer|fanmade|dub"
legacy config mighty-mouse --whisper-vad false --min-wpm 0 --whisper-model medium
legacy run mighty-mouse
```

**An audio podcast behind an RSS feed**

```bash
legacy init "Podnews Daily" --url "https://podnews.net/rss"
legacy run podnews-daily --limit 10
```

**A television series on disk**

```bash
legacy init "My Show" --providers whisper
legacy import my-show ~/Videos/my-show/*.mkv
legacy build my-show
```

Then, for any of them:

```bash
legacy status
legacy build <series>        # keeps going; only pending episodes are touched
```

Transcripts land in `series/<slug>/transcripts/` with an `index.md`.

## Commands

| Command | What it does |
|---|---|
| `legacy init NAME --url URL [...]` | Create a series folder and config |
| `legacy add-source SERIES URL [...]` | Add more sources to an existing series |
| `legacy config SERIES [options]` | Change filters, language, Whisper settings, throttling, cookies |
| `legacy discover SERIES [--source TEXT]` | Enumerate sources (or only matching ones) and probe episode metadata |
| `legacy build SERIES [--limit N] [--workers N] [--since DATE] [--id ID] [--retry-failed] [--force]` | Fetch transcripts for pending episodes |
| `legacy dedupe SERIES [--dry-run]` | Link the same episode arriving from two sources (runs automatically in build) |
| `legacy validate SERIES [--strict]` | Sanity-check built transcripts |
| `legacy run SERIES` | discover + build + index + validate |
| `legacy import SERIES FILE [...]` | Add local audio or video files |
| `legacy status [SERIES] [--json]` | Progress per series, with failure reasons |
| `legacy doctor` | Check yt-dlp, ffmpeg, Whisper |

Every command accepts `--help`.

## Series configuration

`legacy init` writes `series/<slug>/series.json`. Everything can be changed
later with `legacy config`.

| Field | Default | Meaning |
|---|---|---|
| `sources` | `[]` | YouTube/yt-dlp URLs, `ia:` queries or archive.org URLs, RSS feeds. |
| `language` | `"en"` | Preferred caption and Whisper language. |
| `min_minutes` / `max_minutes` | `0` / none | Duration window. |
| `include` / `exclude` | none | Case-insensitive regexes on the title. |
| `providers` | `captions, sidecar, whisper` | Order in which transcript sources are tried. |
| `whisper_model` | `small` | `tiny`, `base`, `small`, `medium`, `large-v3`. |
| `whisper_vad` | `false` | Voice-activity filter. Keep off for music-backed or archival audio. |
| `min_wpm` / `max_wpm` | `60` / `250` | Validation bounds. Lower `min_wpm` for sparse-dialogue material. |
| `max_media_mb` | `2000` | Refuse direct media downloads larger than this. |
| `max_entries` | `0` | Only the newest N entries per source. |
| `request_sleep` | `1.0` | Seconds between yt-dlp requests. |
| `cookies_from_browser` / `cookies_file` | none | Authenticate yt-dlp as the channel owner. |
| `transcripts_dir` | `transcripts` | Output folder, relative to the series folder. |

## Output format

One markdown file per episode, `YYYYMMDD-slug.md`, or `YYYY-slug.md` when
only a year is known. Episodes with season and episode numbers get an
`sNNeNN` prefix.

```markdown
---
title: "Mighty Mouse in Krakatoa (1945)"
show: "Mighty Mouse (Terrytoons)"
video_id: "ia-mighty-mouse-in-krakatoa-1945"
url: "https://archive.org/details/mighty-mouse-in-krakatoa-1945"
upload_date: "1945-12-14"
year: "1945"
duration: "00:06:14"
word_count: 297
transcript_source: "Whisper (faster-whisper small)"
---

# Mighty Mouse in Krakatoa (1945)

**Show:** Mighty Mouse (Terrytoons) · **Aired:** 1945-12-14 · **Runtime:** 00:06:14
**Source:** <https://archive.org/details/mighty-mouse-in-krakatoa-1945>
**License:** <https://creativecommons.org/publicdomain/mark/1.0/>

##### `00:00:00`

On a South Sea tropical island ... you'll find a paradise. Hear the sea
caresses the shore, for breezes play as palm trees sway. Oh, lovely island,
island of Krakatoa, where Mother Nature has lavished her splendor.
```

The frontmatter is machine-readable, so a folder of transcripts drops straight
into a static site, a search index, or a retrieval pipeline.

## Rate limits and authentication

YouTube throttles anonymous metadata requests. Crawling a channel of about two
thousand videos in one sitting triggered an HTTP 429 and a "sign in to
confirm you're not a bot" block after roughly 1,200 probes. The harness sleeps
between requests, defaults to 3 workers, detects the block and stops early
with a clear message, and re-probes anything missing on the next run. For
large catalogs, spread discovery across sessions or authenticate as the
channel owner:

```bash
legacy config my-show --cookies-from-browser chrome
```

The Internet Archive and RSS feeds have no such limits at the request rates
the tool uses.

## Adopting existing transcripts

Transcripts already in the output folder with the frontmatter above are marked
done by their `video_id` before anything else runs, so a catalog started with
older tooling carries over without being rebuilt.

## Project layout

```
src/legacyai/
  cli.py        argparse entry point (`legacy`)
  config.py     Series dataclass, on-disk layout, filters
  sources.py    Internet Archive and RSS adapters, URL classification
  catalog.py    yt-dlp listing and probing, discovery, local import, rate-limit abort
  providers.py  captions, sidecar (published transcripts), Whisper
  render.py     VTT/SRT parsing, paragraphing, markdown, frontmatter reader
  build.py      resumable build loop, filename collisions, index page
  validate.py   transcript checks and status summary
tests/
  test_legacyai.py   offline unit tests, no network
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

Design constraints worth keeping:

- Only the main thread writes the catalog and manifest; workers return records.
- Every provider failure is a short, stable reason string that surfaces in
  `legacy status`. A batch never fails silently.
- Files stay under 500 lines. One required dependency (yt-dlp); Whisper is an
  extra.

## Roadmap

- Speaker diarization, so multi-host shows get labeled turns.
- Chapter detection from platform chapter markers and from silence.
- JSON and SRT export alongside markdown.
- Scheduled re-discovery so new episodes are transcribed as they publish.
- A hosted version where a creator connects their channel or feed and receives
  a finished archive plus a private search page.

## Status

Working, tested, and reviewed. Verified end to end on a 2020s YouTube video
podcast, a 1945 Internet Archive cartoon with no captions, a 2026 audio
podcast via RSS through Whisper, and a daily RSS feed with published
transcripts.
