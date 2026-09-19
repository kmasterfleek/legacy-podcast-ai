"""Read existing Markdown without inventing speech, speakers, or precise end times."""
import hashlib
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from legacyai.render import read_frontmatter
from legacyai.studio.db import connect

HEADING = re.compile(r"^##### .*?(\d{2}:\d{2}:\d{2}).*$", re.M)
ADS = re.compile(r"promo code|download the .*app|sportsbook|free bets|new customers|"
                 r"terms (?:and|&) conditions|sponsored by|gambling problem|call 1.?800", re.I)


def seconds(stamp):
    try:
        h, m, s = stamp.split(":")
        return int(h)*3600 + int(m)*60 + float(s)
    except (ValueError, AttributeError):
        return 0


def youtube_id(url):
    parts = urlparse(url)
    host = (parts.hostname or "").lower()
    candidate = parts.path.strip("/") if host == "youtu.be" else (
        parse_qs(parts.query).get("v", [""])[0] if host in {"youtube.com", "www.youtube.com"} else "")
    return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate) else None


def parse_transcript(path):
    fm = read_frontmatter(path)
    if not fm.get("video_id"):
        raise ValueError("Transcript needs video_id frontmatter")
    text = Path(path).read_text(encoding="utf-8")
    marks = list(HEADING.finditer(text))
    duration = seconds(fm.get("duration", ""))
    paragraphs = []
    previous = -1
    for i, mark in enumerate(marks):
        start = seconds(mark.group(1))
        if start < previous:
            raise ValueError("Transcript timestamps must be chronological")
        previous = start
        if duration and start > duration:
            raise ValueError("Transcript timestamp is past the episode duration")
        body = text[mark.end():marks[i+1].start() if i+1<len(marks) else len(text)].strip()
        speaker = ""
        match = re.match(r"\*\*(.+?):\*\*\s*", body)
        if match:
            speaker, body = match.group(1), body[match.end():]
        body = re.sub(r"\s+", " ", body).strip()
        if body:
            paragraphs.append({"start": start, "text": body, "speaker": speaker})
    if not paragraphs:
        raise ValueError("Transcript contains no timestamped passages")
    duration = max(duration, paragraphs[-1]["start"]+1)
    for i, para in enumerate(paragraphs):
        para["end"] = paragraphs[i+1]["start"] if i+1<len(paragraphs) else duration
    return fm, paragraphs, duration, hashlib.sha256(text.encode()).hexdigest()


def windows(paragraphs):
    """Overlap speaker turns up to ~60s; long source paragraphs remain intact."""
    for i, para in enumerate(paragraphs):
        group = [para]
        for extra in paragraphs[i+1:i+20]:
            if group[-1]["end"]-para["start"] >= 45 or len(" ".join(p["text"] for p in group).split()) >= 150:
                break
            if extra["end"]-para["start"] > 95:
                break
            group.append(extra)
        body = " ".join((p["speaker"]+": " if p["speaker"] else "")+p["text"] for p in group)
        if group[-1]["end"] <= para["start"]:
            continue
        speakers = list(dict.fromkeys(p["speaker"] for p in group if p["speaker"]))
        yield {"ordinal": i, "start": para["start"], "end": group[-1]["end"],
               "text": body, "speaker": ", ".join(speakers), "is_ad": int(bool(ADS.search(body)))}


def index_archive(workspace_id, folder, log=print):
    result = {"indexed": 0, "unchanged": 0, "errors": []}
    with connect() as con:
        for path in sorted(Path(folder).glob("*.md")):
            if path.name == "index.md":
                continue
            try:
                fm, paras, duration, digest = parse_transcript(path)
            except (ValueError, OSError) as exc:
                result["errors"].append({"file": path.name, "error": str(exc)})
                continue
            ep_id = fm["video_id"]
            old = con.execute("SELECT content_hash FROM episodes WHERE id=? AND workspace_id=?",
                              (ep_id, workspace_id)).fetchone()
            if old and old[0] == digest:
                result["unchanged"] += 1
                continue
            date = fm.get("upload_date", "")
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
                raw = path.name[:8]
                date = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}" if raw.isdigit() else date
            url = fm.get("url", "")
            kind = "youtube" if youtube_id(url) else "podcast" if ep_id.startswith("rss-") else "archive"
            values = (ep_id, workspace_id, fm.get("title", path.stem), fm.get("show", "Archive"),
                      date, duration, int(fm.get("word_count", 0)), url, kind,
                      int(any(p["speaker"] for p in paras)), path.name, digest, len(paras))
            con.execute("""INSERT INTO episodes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(workspace_id,id) DO UPDATE SET title=excluded.title,
                show_name=excluded.show_name,published=excluded.published,duration=excluded.duration,
                word_count=excluded.word_count,source_url=excluded.source_url,source_kind=excluded.source_kind,
                speaker_labels=excluded.speaker_labels,filename=excluded.filename,
                content_hash=excluded.content_hash,paragraph_count=excluded.paragraph_count""", values)
            con.execute("DELETE FROM passages WHERE workspace_id=? AND episode_id=?", (workspace_id, ep_id))
            for p in windows(paras):
                pid = hashlib.sha256(f"{workspace_id}:{ep_id}:{p['ordinal']}".encode()).hexdigest()[:32]
                con.execute("INSERT INTO passages VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (pid, workspace_id, ep_id, p["ordinal"], p["start"], p["end"],
                             p["text"], p["speaker"], fm.get("title", ""), p["is_ad"]))
            result["indexed"] += 1
    log(result)
    return result
