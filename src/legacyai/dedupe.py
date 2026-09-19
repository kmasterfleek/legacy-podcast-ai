"""Link the same episode arriving from two sources (e.g. YouTube and the RSS feed).

A catalog entry is a duplicate of an existing transcript when the two were
published within a few days of each other and their titles share distinctive
words. Matching is one-to-one: each transcript absorbs at most one entry, the
closest by date and title overlap. Duplicates are recorded in the manifest
with status "duplicate" so build never re-transcribes them.
"""
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from .config import Series, load_json, save_json
from .render import read_frontmatter

STOP = {
    "about", "after", "again", "all", "and", "are", "back", "being", "but", "can", "did", "does",
    "for", "from", "full", "gets", "got", "has", "have", "his", "how", "into", "its", "just",
    "more", "most", "new", "not", "off", "on", "one", "out", "over", "that", "the", "their",
    "them", "they", "this", "was", "what", "when", "who", "why", "will", "with", "you", "your",
    # show-generic words that appear in most titles and say nothing about the guest
    "smoke", "episode", "ep", "podcast", "showtime", "basketball", "sho", "nba", "stories",
    "story", "talks", "real", "unfiltered", "untold", "reveals", "keeps", "breaks", "down",
    "live", "part", "presented",
}


def _initials(t: str) -> str:
    """'T.I.' -> 'ti', 'J.R. Smith' -> 'jr Smith', so short names survive tokenising."""
    return re.sub(r"\b((?:[A-Za-z]\.){2,})", lambda m: m.group(1).replace(".", "") + " ", t)


def title_words(title: str) -> Set[str]:
    t = _initials(title or "").lower().replace("’", "'")
    return {w for w in re.findall(r"[a-z0-9']{2,}", t) if w not in STOP and not w.isdigit()}


def episode_number(title: str) -> Optional[str]:
    m = re.search(r"\bep(?:isode)?\.?\s*#?\s*(\d{1,4})\b", title or "", re.I)
    return m.group(1) if m else None


def _date(s: str) -> Optional[datetime]:
    s = (s or "").replace("-", "")
    try:
        return datetime.strptime(s[:8], "%Y%m%d") if len(s) >= 8 else None
    except ValueError:
        return None


def match_score(a_title: str, a_date: str, b_title: str, b_date: str, days: int = 3) -> int:
    """Shared distinctive title words if dates are within `days`, else 0.

    One shared word is enough only when a title is short (a bare guest name);
    otherwise two are required, which keeps generic overlaps from matching.
    """
    da, db = _date(a_date), _date(b_date)
    if not da or not db or abs((da - db).days) > days:
        return 0
    na, nb = episode_number(a_title), episode_number(b_title)
    if na and nb:
        return 10 if na == nb else 0  # both numbered: the number decides
    wa, wb = title_words(a_title), title_words(b_title)
    shared = len(wa & wb)
    need = 1 if min(len(wa), len(wb)) <= 3 else 2
    return shared if shared >= need else 0


def find_duplicates(series: Series, days: int = 3) -> List[Tuple[str, str, str, int]]:
    """[(catalog_id, done_video_id, done_file, score)] for pending entries that match a done transcript."""
    catalog = load_json(series.catalog_path, {})
    manifest = load_json(series.manifest_path, {})
    done: Dict[str, Tuple[str, str, str]] = {}  # vid -> (title, date, file)
    for vid, rec in manifest.items():
        if rec.get("status") != "done" or not rec.get("file"):
            continue
        fm = read_frontmatter(series.out_dir / rec["file"])
        done[vid] = (fm.get("title", ""), fm.get("upload_date", ""), rec["file"])
    taken = {rec.get("duplicate_of") for rec in manifest.values() if rec.get("status") == "duplicate"}
    candidates = []
    for ep in catalog.values():
        vid = ep["id"]
        if manifest.get(vid, {}).get("status") in ("done", "duplicate") or series.wants(ep) is not None:
            continue
        for dvid, (dtitle, ddate, dfile) in done.items():
            if dvid == vid or dvid in taken:
                continue
            score = match_score(ep.get("title", ""), ep.get("upload_date", ""), dtitle, ddate, days)
            if score:
                gap = abs((_date(ep.get("upload_date", "")) - _date(ddate)).days)
                candidates.append((score, -gap, vid, dvid, dfile))
    out, used_new, used_done = [], set(), set(taken)
    for score, _neg_gap, vid, dvid, dfile in sorted(candidates, reverse=True):
        if vid in used_new or dvid in used_done:
            continue
        used_new.add(vid)
        used_done.add(dvid)
        out.append((vid, dvid, dfile, score))
    return out


def mark_duplicates(series: Series, days: int = 3, dry_run: bool = False, log=print) -> int:
    pairs = find_duplicates(series, days)
    if dry_run:
        catalog = load_json(series.catalog_path, {})
        for vid, dvid, dfile, score in pairs:
            log(f"  {catalog[vid].get('upload_date','')}  {catalog[vid].get('title','')[:55]:<55} == {dfile[:60]}  ({score})")
        log(f"{len(pairs)} duplicate(s) would be linked")
        return len(pairs)
    if pairs:
        manifest = load_json(series.manifest_path, {})
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        for vid, dvid, dfile, score in pairs:
            manifest[vid] = {"status": "duplicate", "duplicate_of": dvid, "file": dfile,
                             "reason": f"same episode as {dvid} (title score {score})", "updated": now}
        save_json(series.manifest_path, manifest)
        log(f"linked {len(pairs)} duplicate(s) to existing transcripts")
    return len(pairs)
