"""Source adapters beyond yt-dlp: the Internet Archive and RSS podcast feeds.

Every adapter yields episode dicts with at least:
    id, title, url, upload_date (YYYYMMDD, or YYYY for year-only dates),
    duration (seconds), kind ("media"), media_url, transcript_urls (list)
"""
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Dict, Iterator, List, Optional

UA = "LegacyPodcastAI/0.2 (+https://github.com/kmasterfleek/legacy-podcast-ai)"
IA_SEARCH = "https://archive.org/advancedsearch.php"
IA_META = "https://archive.org/metadata/"
IA_DL = "https://archive.org/download/"

SUB_FORMATS = ("SubRip", "WebVTT")
AUDIO_FORMATS = ("VBR MP3", "MP3", "Ogg Vorbis", "Flac", "24bit Flac", "128Kbps MP3", "64Kbps MP3",
                 "WAVE", "AIFF", "Advanced Audio Coding")
VIDEO_FORMATS = ("h.264", "MPEG4", "512Kb MPEG4", "h.264 IA", "h.264 HD", "Ogg Video", "Matroska", "MPEG2",
                 "MPEG1", "QuickTime", "WebM", "Flash Video", "Windows Media")
AUDIO_EXT = (".mp3", ".ogg", ".oga", ".m4a", ".aac", ".wav", ".flac", ".aiff", ".opus")
VIDEO_EXT = (".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm", ".mpg", ".mpeg", ".m4v", ".ogv")


def _first(v):
    """archive.org returns a list whenever a metadata field is repeated."""
    return v[0] if isinstance(v, list) and v else v


def http_json(url: str, timeout: int = 60):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def http_bytes(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


VIDEO_HOSTS = ("youtube.com", "youtu.be", "vimeo.com", "twitch.tv", "dailymotion.com", "soundcloud.com",
               "rumble.com", "bitchute.com", "tiktok.com", "facebook.com", "instagram.com", "x.com", "twitter.com")


def kind_of(url: str, sniff: bool = True) -> str:
    """Classify a source URL: 'archive', 'rss', or 'ytdlp'.

    Explicit prefixes (ia:, rss:) win. archive.org is 'archive'. Known video
    platforms are 'ytdlp'. Anything else is sniffed: if the body starts with an
    RSS/Atom document it is a feed, otherwise it is handed to yt-dlp.
    """
    u = url.strip()
    if u.startswith("ia:") or re.match(r"https?://(www\.)?archive\.org/", u):
        return "archive"
    if u.startswith("rss:"):
        return "rss"
    host = (urllib.parse.urlparse(u).hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in VIDEO_HOSTS):
        return "ytdlp"
    if re.search(r"\.(rss|xml)(\?.*)?$", u, re.I):
        return "rss"
    if sniff and u.startswith(("http://", "https://")):
        try:
            req = urllib.request.Request(u, headers={"User-Agent": UA, "Range": "bytes=0-4095"})
            with urllib.request.urlopen(req, timeout=20) as r:
                head = r.read(4096).decode("utf-8", "replace").lower()
            if "<rss" in head or "<feed" in head or "<channel" in head:
                return "rss"
        except (OSError, ValueError):
            pass
    return "ytdlp"


def normalize_date(value) -> str:
    """'1945-07-20' -> '19450720'; '1945' -> '1945'; RFC 2822 -> YYYYMMDD; else ''."""
    if not value:
        return ""
    s = str(value).strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return "".join(m.groups())
    if re.match(r"^\d{8}$", s):
        return s
    if re.match(r"^\d{4}$", s):
        return s
    try:
        return parsedate_to_datetime(s).strftime("%Y%m%d")
    except (TypeError, ValueError, IndexError):
        pass
    m = re.match(r"^(\d{4})-(\d{2})$", s)  # "1945-07"
    if m:
        return m.group(1) + m.group(2) + "01"
    m = re.search(r"\b(1[89]\d{2}|20\d{2})\b", s)  # "c. 1945", "[1945]", "Mon, 01 Jan 2024"
    return m.group(1) if m else ""


def _to_seconds(value) -> int:
    if value is None or value == "":
        return 0
    s = str(value).strip()
    if re.match(r"^\d+(\.\d+)?$", s):
        return int(float(s))
    parts = s.split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return 0
    total = 0.0
    for n in nums:
        total = total * 60 + n
    return int(total)


# ------------------------------------------------------------ Internet Archive
def archive_query(url: str) -> Optional[str]:
    """Turn a source URL into an advancedsearch query, or None for a single item."""
    u = url.strip()
    if u.startswith("ia:"):
        return u[3:].strip()
    parsed = urllib.parse.urlparse(u)
    qs = urllib.parse.parse_qs(parsed.query)
    if "query" in qs:
        return qs["query"][0]
    m = re.match(r"^/details/([^/?#]+)", parsed.path)
    if m:
        ident = m.group(1)
        meta = http_json(IA_META + ident)
        if (meta.get("metadata") or {}).get("mediatype") == "collection":
            return f"collection:{ident}"
        return None  # single item; caller uses archive_item
    return None


def archive_search(query: str, max_entries: int = 0, log=print) -> Iterator[dict]:
    """Yield {identifier, title, date, mediatype} for a query, oldest first."""
    q = query
    if "mediatype" not in q:
        q = f"({q}) AND (mediatype:movies OR mediatype:audio)"
    page, seen = 1, 0
    while True:
        params = {"q": q, "fl[]": ["identifier", "title", "date", "year", "mediatype"],
                  "rows": 200, "page": page, "output": "json", "sort[]": "date asc"}
        url = IA_SEARCH + "?" + urllib.parse.urlencode(params, doseq=True)
        docs = (http_json(url).get("response") or {}).get("docs") or []
        if not docs:
            return
        for d in docs:
            yield d
            seen += 1
            if max_entries and seen >= max_entries:
                return
        page += 1
        time.sleep(0.5)


def _ia_file_url(ident: str, name: str) -> str:
    return IA_DL + ident + "/" + urllib.parse.quote(name)


def archive_item(ident: str, log=print) -> Optional[dict]:
    """Episode dict for one archive.org item, choosing the best media + subtitle files."""
    meta = http_json(IA_META + ident)
    md = meta.get("metadata") or {}
    files = meta.get("files") or []
    if _first(md.get("mediatype")) not in ("movies", "audio"):
        return None
    name = lambda f: str(f.get("name", "")).lower()  # noqa: E731
    subs = [f for f in files if f.get("format") in SUB_FORMATS or name(f).endswith((".srt", ".vtt"))]
    audio = [f for f in files if f.get("format") in AUDIO_FORMATS or name(f).endswith(AUDIO_EXT)]
    video = [f for f in files if f.get("format") in VIDEO_FORMATS or name(f).endswith(VIDEO_EXT)]
    # Whisper only needs audio: prefer an audio derivative, else the smallest video.
    pool = audio or video
    if not pool:
        log(f"  !! {ident}: no audio/video file found; skipped")
        return None
    media = min(pool, key=lambda f: int(f.get("size") or 10 ** 12))
    duration = 0
    for f in video + audio:
        duration = max(duration, _to_seconds(f.get("length")))
    date = normalize_date(_first(md.get("date"))) or normalize_date(_first(md.get("year")))
    title = _first(md.get("title")) or ident
    return {
        "id": "ia-" + ident, "title": str(title), "url": f"https://archive.org/details/{ident}",
        "upload_date": date, "duration": duration, "kind": "media",
        "media_url": _ia_file_url(ident, media["name"]),
        "transcript_urls": [_ia_file_url(ident, f["name"]) for f in subs],
        "channel": str(_first(md.get("creator")) or ""), "license": str(_first(md.get("licenseurl")) or ""),
        "source_kind": "archive",
    }


def list_archive(url: str, max_entries: int = 0, log=print) -> List[dict]:
    query = archive_query(url)
    if query is None:
        ident = re.match(r".*/details/([^/?#]+)", url).group(1)
        ep = archive_item(ident, log)
        return [ep] if ep else []
    out = []
    for d in archive_search(query, max_entries, log):
        try:
            ep = archive_item(d["identifier"], log)
        except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
            log(f"  !! {d.get('identifier')}: metadata fetch failed ({exc}); skipped")
            continue
        if ep:
            out.append(ep)
        time.sleep(0.3)
        if len(out) % 20 == 0 and out:
            log(f"  archive.org: {len(out)} items so far")
    return out


# ---------------------------------------------------------------- RSS feeds
NS = {
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    "podcast": "https://podcastindex.org/namespace/1.0",
    "media": "http://search.yahoo.com/mrss/",
}


def parse_rss(xml_text, feed_url: str = "") -> List[dict]:
    """Episodes from an RSS 2.0 podcast feed (Podcasting 2.0 transcripts honoured).

    Accepts bytes (preferred: expat honours the declared encoding) or str.
    """
    root = ET.fromstring(xml_text)
    if root.tag.endswith("feed"):
        raise ValueError("Atom feed not supported yet (RSS 2.0 only); use the show's RSS URL")
    channel = root.find("channel")
    if channel is None:
        raise ValueError("not an RSS 2.0 feed (no <channel>)")
    show = (channel.findtext("title") or "").strip()
    out = []
    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        guid = (item.findtext("guid") or "").strip()
        link = (item.findtext("link") or "").strip()
        enc = item.find("enclosure")
        media_url = enc.get("url") if enc is not None else ""
        if not media_url:
            mc = item.find("media:content", NS)
            media_url = mc.get("url") if mc is not None else ""
        if not media_url:
            continue
        transcripts = []
        for t in item.findall("podcast:transcript", NS):
            u, typ = t.get("url"), (t.get("type") or "").lower()
            if u and ("vtt" in typ or "srt" in typ or "subrip" in typ or "json" in typ
                      or u.lower().endswith((".vtt", ".srt", ".json"))):
                transcripts.append(u)
        key = guid or media_url
        ep_num = item.findtext("itunes:episode", default="", namespaces=NS)
        se_num = item.findtext("itunes:season", default="", namespaces=NS)
        out.append({
            "id": "rss-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12],
            "title": title, "url": link or media_url,
            "upload_date": normalize_date(item.findtext("pubDate")),
            "duration": _to_seconds(item.findtext("itunes:duration", default="", namespaces=NS)),
            "kind": "media", "media_url": media_url, "transcript_urls": transcripts,
            "channel": show, "source_kind": "rss", "feed": feed_url,
            "season": int(se_num) if se_num.isdigit() else None,
            "episode": int(ep_num) if ep_num.isdigit() else None,
        })
    return out


def list_rss(url: str, max_entries: int = 0, log=print) -> List[dict]:
    u = url[4:] if url.startswith("rss:") else url
    eps = parse_rss(http_bytes(u), u)
    return eps[:max_entries] if max_entries else eps


def parse_podcast_json_transcript(text: str, min_words: int = 8):
    """Podcasting 2.0 JSON transcript -> cues [(start_seconds, text)].

    Word-level segments are merged into cues of at least `min_words` so the
    renderer's overlap de-duplication never sees single repeated words.
    """
    data = json.loads(text)
    segs = data.get("segments") if isinstance(data, dict) else data
    cues, buf, buf_start = [], [], None
    for s in segs or []:
        body = (s.get("body") or s.get("text") or "").strip()
        if not body:
            continue
        start = float(s.get("startTime") or s.get("start") or 0)
        if buf_start is None:
            buf_start = start
        buf.append(body)
        if sum(len(b.split()) for b in buf) >= min_words:
            cues.append((buf_start, " ".join(buf)))
            buf, buf_start = [], None
    if buf:
        cues.append((buf_start or 0, " ".join(buf)))
    return cues


LISTERS = {"archive": list_archive, "rss": list_rss}
