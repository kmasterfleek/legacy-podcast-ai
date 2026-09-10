"""Turn timed caption cues into a clean, timestamped markdown transcript.

Works for any cue source: YouTube ASR VTT (rolling two-cue format with
inline word timings), manual subtitle VTT, or Whisper segments.
"""
import html
import re
from typing import Iterable, List, Tuple

Cue = Tuple[float, str]  # (start_seconds, text)

TAG_RE = re.compile(r"<[^>]+>")
CUE_RE = re.compile(r"(\d{1,2}:)?(\d{2}):(\d{2})[.,](\d{3})\s+-->\s+(\d{1,2}:)?(\d{2}):(\d{2})[.,](\d{3})")
BRACKET_RE = re.compile(r"\[(?:music|applause|laughter|singing)[^\]]*\]", re.I)

PARA_SECONDS = 45
PARA_WORDS = 110


def _ts(h, m, s, ms) -> float:
    return int((h or "").rstrip(":") or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def sec_to_stamp(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"


def parse_vtt(text: str) -> Iterable[Cue]:
    """Yield (start, text) per cue. Handles both VTT and SRT timing lines."""
    text = re.sub(r"(?m)^[ \t]+$", "", text.replace("\r", ""))  # keep " " lines from splitting blocks
    for block in re.split(r"\n{2,}", text):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        timing = None
        payload: List[str] = []
        for ln in lines:
            hit = CUE_RE.search(ln)
            if hit and timing is None:
                timing = hit
            elif timing is not None:
                payload.append(ln)
        if timing is None or not payload:
            continue
        # YouTube ASR: the line carrying <NN:NN:NN.NNN><c>word</c> tags is the new speech.
        tagged = [ln for ln in payload if "<c>" in ln or re.search(r"<\d{2}:\d{2}", ln)]
        chosen = tagged[-1] if tagged else " ".join(payload)
        clean = BRACKET_RE.sub("", html.unescape(TAG_RE.sub("", chosen)))
        clean = re.sub(r"\s+", " ", clean).strip()
        if clean:
            yield _ts(*timing.groups()[:4]), clean


def dedupe_append(emitted: List[str], words: List[str]) -> List[str]:
    """Return the part of `words` that isn't already the tail of `emitted`."""
    max_ov = min(len(emitted), len(words), 40)
    for n in range(max_ov, 0, -1):
        if emitted[-n:] == words[:n]:
            return words[n:]
    return words


def build_paragraphs(cues: Iterable[Cue]) -> Tuple[List[Tuple[float, str]], int]:
    words: List[str] = []
    paras: List[Tuple[float, str]] = []
    cur: List[str] = []
    cur_start = None
    for start, text in cues:
        new = dedupe_append(words, text.split())
        if not new:
            continue
        words.extend(new)
        if cur_start is None:
            cur_start = start
        cur.extend(new)
        long_enough = len(cur) >= PARA_WORDS
        timed_out = start - cur_start >= PARA_SECONDS
        ends_sentence = cur[-1][-1:] in ".?!"
        if (long_enough and ends_sentence) or start - cur_start >= PARA_SECONDS * 2 \
                or (timed_out and ends_sentence):
            paras.append((cur_start, " ".join(cur)))
            cur, cur_start = [], None
    if cur:
        paras.append((cur_start or 0, " ".join(cur)))
    return paras, len(words)


def _yaml_str(s) -> str:
    return '"' + str(s or "").replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_markdown(episode: dict, series_name: str, paras, total_words: int,
                    source_label: str) -> str:
    """episode: id, title, url, upload_date (YYYYMMDD or YYYY-MM-DD), duration (sec)."""
    d = int(episode.get("duration") or 0)
    dur = sec_to_stamp(d)
    ud = str(episode.get("upload_date") or "").replace("-", "")
    date = f"{ud[:4]}-{ud[4:6]}-{ud[6:8]}" if len(ud) == 8 else (ud or "unknown")
    url = episode.get("url") or ""
    title = episode.get("title") or episode.get("id")
    lines = [
        "---",
        f"title: {_yaml_str(title)}",
        f"show: {_yaml_str(series_name)}",
        f"video_id: {_yaml_str(episode.get('id'))}",
        f"url: {_yaml_str(url)}",
        f'upload_date: "{date}"',
        f'duration: "{dur}"',
        f"word_count: {total_words}",
        f"transcript_source: {_yaml_str(source_label)}",
        "---",
        "",
        f"# {title}",
        "",
        f"**Show:** {series_name} · **Aired:** {date} · **Runtime:** {dur}",
    ]
    if url:
        lines.append(f"**Source:** <{url}>")
    lines += [
        "",
        f"> Transcript source: {source_label}. Speaker labels are not available in the",
        "> source, so wording, names and attribution may be imperfect. Timestamps mark",
        "> paragraph starts" + (" and link back to the source." if url else "."),
        "",
        "---",
        "",
    ]
    for start, text in paras:
        stamp = sec_to_stamp(start)
        if url and "youtube.com/watch" in url:
            lines.append(f"##### [`{stamp}`]({url}&t={int(start)}s)")
        else:
            lines.append(f"##### `{stamp}`")
        lines.append("")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def read_frontmatter(path) -> dict:
    """Minimal frontmatter reader for adopting existing transcripts."""
    out = {}
    try:
        with open(path, encoding="utf-8") as fh:
            first = fh.readline()
            if first.strip() != "---":
                return out
            for ln in fh:
                if ln.strip() == "---":
                    break
                if ":" in ln:
                    k, v = ln.split(":", 1)
                    v = v.strip()
                    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
                        v = v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
                    out[k.strip()] = v
    except OSError:
        pass
    return out
