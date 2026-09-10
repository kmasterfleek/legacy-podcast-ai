"""Sanity checks over built transcripts. Returns a list of flag strings."""
import re
from collections import Counter
from typing import List

from .config import Series, load_json
from .render import read_frontmatter

MIN_WPM, MAX_WPM = 60, 250
HEADING_RE = re.compile(r"^##### ", re.M)


def _dur_seconds(stamp: str) -> int:
    try:
        h, m, s = stamp.split(":")
        return int(h) * 3600 + int(m) * 60 + int(s)
    except ValueError:
        return 0


def validate(series: Series, log=print) -> List[str]:
    flags: List[str] = []
    manifest = load_json(series.manifest_path, {})
    ids = Counter()
    checked = 0
    for path in sorted(series.out_dir.glob("*.md")):
        if path.name == "index.md":
            continue
        fm = read_frontmatter(path)
        rel = path.name
        missing = [k for k in ("title", "video_id", "upload_date", "duration", "word_count") if not fm.get(k)]
        if missing:
            flags.append(f"{rel}: missing frontmatter {missing}")
            continue
        checked += 1
        ids[fm["video_id"]] += 1
        secs = _dur_seconds(fm["duration"])
        words = int(fm["word_count"] or 0)
        if secs >= 60:
            wpm = words / (secs / 60)
            if wpm < MIN_WPM or wpm > MAX_WPM:
                flags.append(f"{rel}: {wpm:.0f} words/min is outside {MIN_WPM}-{MAX_WPM}")
        body = path.read_text(encoding="utf-8", errors="ignore")
        n_head = len(HEADING_RE.findall(body))
        if n_head < 3 and secs > 300:
            flags.append(f"{rel}: only {n_head} timestamped paragraph(s)")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fm["upload_date"]):
            flags.append(f"{rel}: upload_date '{fm['upload_date']}' is not YYYY-MM-DD")
        rec = manifest.get(fm["video_id"])
        if rec and rec.get("status") == "done" and rec.get("file") != rel:
            flags.append(f"{rel}: manifest points at {rec.get('file')} for the same episode")
    for vid, n in ids.items():
        if n > 1:
            flags.append(f"video_id {vid} appears in {n} files")
    log(f"validated {checked} transcript(s): {len(flags)} flag(s)")
    for f in flags:
        log(f"  - {f}")
    return flags


def status(series: Series) -> dict:
    catalog = load_json(series.catalog_path, {})
    manifest = load_json(series.manifest_path, {})
    scoped = [e for e in catalog.values() if series.wants(e) is None]
    done = [v for v in manifest.values() if v.get("status") == "done"]
    failed = {k: v for k, v in manifest.items() if v.get("status") == "failed"}
    reasons = Counter(v.get("reason", "").split(";")[0].strip() for v in failed.values())
    pending = [e for e in scoped if manifest.get(e["id"], {}).get("status") not in ("done", "failed")]
    unprobed = sum(1 for e in catalog.values() if e.get("probe_failed"))
    dates = sorted(e.get("upload_date") or "" for e in scoped if e.get("upload_date"))
    return {
        "series": series.name, "sources": len(series.sources),
        "catalog": len(catalog), "in_scope": len(scoped), "unprobed": unprobed,
        "done": len(done), "failed": len(failed),
        "pending": len(pending),
        "words": sum(int(v.get("word_count") or 0) for v in done),
        "date_range": (dates[0], dates[-1]) if dates else ("", ""),
        "failure_reasons": dict(reasons.most_common()),
        "out_dir": str(series.out_dir),
    }
