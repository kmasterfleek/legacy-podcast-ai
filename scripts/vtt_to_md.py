#!/usr/bin/env python3
"""Convert a YouTube ASR .vtt caption file into a clean markdown transcript.

YouTube auto-captions use a rolling two-cue format: a short carry-over cue
holding the previous line, then a cue whose <NN:NN:NN.NNN><c>word</c> tags
carry the newly spoken words. We keep the tagged line and de-duplicate any
residual overlap against what we've already emitted.
"""
import re
import sys
import html
import json
import argparse

TAG_RE = re.compile(r"<[^>]+>")
CUE_RE = re.compile(
    r"(\d{2}:\d{2}:\d{2}\.\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2}\.\d{3})"
)

# Paragraph breaks: start a new stamped block past this many seconds or words.
PARA_SECONDS = 45
PARA_WORDS = 110


def ts_to_sec(ts):
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def sec_to_stamp(sec):
    sec = int(sec)
    return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"


def parse_cues(text):
    """Yield (start_seconds, new_text) for each caption cue."""
    blocks = re.split(r"\n\s*\n", text)
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        m = None
        payload = []
        for ln in lines:
            hit = CUE_RE.search(ln)
            if hit and m is None:
                m = hit
            elif m is not None:
                payload.append(ln)
        if m is None or not payload:
            continue
        # Prefer the line carrying inline word timings: that's the new speech.
        tagged = [ln for ln in payload if "<" in ln and ">" in ln]
        chosen = tagged[-1] if tagged else payload[-1]
        clean = html.unescape(TAG_RE.sub("", chosen)).strip()
        clean = re.sub(r"\s+", " ", clean)
        if clean:
            yield ts_to_sec(m.group(1)), clean


def dedupe_append(emitted, words):
    """Append only the part of `words` that isn't already the tail of `emitted`."""
    max_ov = min(len(emitted), len(words), 40)
    for n in range(max_ov, 0, -1):
        if emitted[-n:] == words[:n]:
            return words[n:]
    return words


def build_paragraphs(cues):
    words, paras = [], []
    cur, cur_start = [], None
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
        ends_sentence = cur and cur[-1][-1:] in ".?!"
        if (long_enough and ends_sentence) or start - cur_start >= PARA_SECONDS * 2 or (timed_out and ends_sentence):
            paras.append((cur_start, " ".join(cur)))
            cur, cur_start = [], None
    if cur:
        paras.append((cur_start or 0, " ".join(cur)))
    return paras, len(words)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vtt")
    ap.add_argument("--meta", required=True, help="JSON file with episode metadata")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.vtt, encoding="utf-8") as fh:
        raw = fh.read()
    meta = json.load(open(args.meta, encoding="utf-8"))

    paras, total_words = build_paragraphs(parse_cues(raw))
    if not paras:
        sys.exit(f"no cues parsed from {args.vtt}")

    d = meta.get("duration") or 0
    dur = f"{int(d)//3600:02d}:{(int(d)%3600)//60:02d}:{int(d)%60:02d}"
    ud = str(meta.get("upload_date") or "")
    date = f"{ud[:4]}-{ud[4:6]}-{ud[6:8]}" if len(ud) == 8 else ud

    def esc(s):
        return str(s or "").replace('"', "'")

    lines = [
        "---",
        f'title: "{esc(meta.get("title"))}"',
        'show: "All The Smoke"',
        f'video_id: "{esc(meta.get("id"))}"',
        f'url: "https://www.youtube.com/watch?v={esc(meta.get("id"))}"',
        f'upload_date: "{date}"',
        f'duration: "{dur}"',
        f"word_count: {total_words}",
        'transcript_source: "YouTube auto-generated captions (ASR), English"',
        "---",
        "",
        f"# {meta.get('title')}",
        "",
        f"**Show:** All The Smoke · **Aired:** {date} · **Runtime:** {dur}",
        f"**Source:** <https://www.youtube.com/watch?v={meta.get('id')}>",
        "",
        "> Machine transcript from YouTube's automatic (ASR) captions. The source",
        "> track carries no speaker labels or punctuation guarantees, so wording,",
        "> names and attribution may be imperfect. Timestamps mark paragraph starts",
        "> and link back to the video.",
        "",
        "---",
        "",
    ]
    vid = meta.get("id")
    for start, text in paras:
        stamp = sec_to_stamp(start)
        link = f"https://www.youtube.com/watch?v={vid}&t={int(start)}s"
        lines.append(f"##### [`{stamp}`]({link})")
        lines.append("")
        lines.append(text)
        lines.append("")

    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"  -> {args.out}  ({total_words:,} words, {len(paras)} paragraphs)")


if __name__ == "__main__":
    main()
