"""Build transcripts for every in-scope episode that isn't done yet.

manifest.json maps episode id -> {status, file, provider, reason, attempts, updated}.
Existing markdown files in the output dir are adopted by their frontmatter
video_id so a series can start from transcripts made elsewhere.
"""
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional

from .catalog import fetch_info, in_scope
from .config import Series, load_json, save_json, slugify
from .dedupe import mark_duplicates
from .providers import PROVIDERS, ProviderError
from .render import build_paragraphs, read_frontmatter, render_markdown


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def adopt_existing(series: Series, manifest: Dict[str, dict], log=print) -> int:
    """Mark transcripts already on disk as done (by frontmatter video_id)."""
    added = 0
    for path in sorted(series.out_dir.glob("*.md")):
        fm = read_frontmatter(path)
        vid = fm.get("video_id")
        if not vid or manifest.get(vid, {}).get("status") == "done":
            continue
        manifest[vid] = {
            "status": "done", "file": path.name, "provider": "adopted",
            "reason": "", "attempts": 0, "updated": _now(),
            "word_count": int(fm.get("word_count") or 0),
        }
        added += 1
    if added:
        log(f"adopted {added} existing transcript(s) from {series.out_dir}")
    return added


def out_name(episode: dict, out_dir: Optional[Path] = None) -> str:
    """date-[sNNeNN-]slug.md; falls back to the id for empty slugs and on collisions."""
    date = (episode.get("upload_date") or "00000000")[:8]
    prefix = ""
    if episode.get("season") and episode.get("episode"):
        prefix = f"s{int(episode['season']):02d}e{int(episode['episode']):02d}-"
    slug = slugify(episode.get("title") or "")
    if slug == "untitled":
        slug = slugify(episode["id"]) or "untitled"
    name = f"{date}-{prefix}{slug}.md"
    if out_dir is not None:
        existing = out_dir / name
        if existing.exists() and read_frontmatter(existing).get("video_id") not in ("", None, episode["id"]):
            name = f"{date}-{prefix}{slug}-{slugify(episode['id'])[:11]}.md"
    return name


def build_one(series: Series, episode: dict) -> dict:
    """Try providers in order; return a manifest record."""
    info: Optional[dict] = None
    if episode.get("kind", "url") == "url":
        info = fetch_info(series, episode["url"], episode["id"])
        if info:  # refresh catalog-level fields that may have been missing
            for k in ("title", "upload_date", "duration"):
                if info.get(k):
                    episode[k] = info[k]
    reasons: List[str] = []
    for name in series.providers:
        fn = PROVIDERS.get(name)
        if not fn:
            reasons.append(f"{name}: unknown provider")
            continue
        try:
            cues, label = fn(series, episode, info)
        except ProviderError as exc:
            reasons.append(f"{name}: {exc}")
            continue
        except Exception as exc:  # keep the batch alive on unexpected errors
            reasons.append(f"{name}: {type(exc).__name__}: {exc}")
            continue
        paras, words = build_paragraphs(cues)
        if not paras:
            reasons.append(f"{name}: no cues parsed")
            continue
        md = render_markdown(episode, series.name, paras, words, label)
        fname = out_name(episode, series.out_dir)
        (series.out_dir / fname).write_text(md, encoding="utf-8")
        return {"status": "done", "file": fname, "provider": name, "reason": "",
                "word_count": words, "paragraphs": len(paras), "updated": _now()}
    return {"status": "failed", "file": "", "provider": "", "reason": "; ".join(reasons),
            "updated": _now()}


def build(series: Series, limit: int = 0, workers: int = 3, retry_failed: bool = False,
          since: str = "", only: Optional[List[str]] = None, force: bool = False,
          dedupe: bool = True, log=print) -> Dict[str, dict]:
    series.out_dir.mkdir(parents=True, exist_ok=True)
    catalog = load_json(series.catalog_path, {})
    manifest: Dict[str, dict] = load_json(series.manifest_path, {})
    if adopt_existing(series, manifest, log):
        save_json(series.manifest_path, manifest)
    if dedupe and mark_duplicates(series, log=log):  # same episode from another source
        manifest = load_json(series.manifest_path, {})

    todo = []
    for ep in in_scope(series, catalog):
        rec = manifest.get(ep["id"], {})
        if rec.get("status") == "duplicate":
            continue
        if rec.get("status") == "done" and not force:
            continue
        if rec.get("status") == "failed" and not (retry_failed or force):
            continue
        if since and (ep.get("upload_date") or "") < since.replace("-", ""):
            continue
        if only and ep["id"] not in only:
            continue
        todo.append(ep)
    if limit:
        todo = todo[:limit]
    log(f"{len(todo)} episode(s) to build, {workers} worker(s)")
    if not todo:
        save_json(series.manifest_path, manifest)
        return manifest

    def work(ep):
        mins = (ep.get("duration") or 0) // 60
        log(f"[{ep['id']}] {ep.get('upload_date','')} {mins:>4}m  {ep.get('title','')[:60]}")
        try:
            rec = build_one(series, ep)
        except Exception as exc:  # never let one episode sink the batch
            rec = {"status": "failed", "file": "", "provider": "",
                   "reason": f"internal: {type(exc).__name__}: {exc}", "updated": _now()}
        rec["attempts"] = manifest.get(ep["id"], {}).get("attempts", 0) + 1
        return ep["id"], rec

    ok = fail = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(work, ep) for ep in todo]
        for fut in as_completed(futures):
            vid, rec = fut.result()
            manifest[vid] = rec
            if rec["status"] == "done":
                ok += 1
                log(f"  -> {rec['file']}  ({rec['word_count']:,} words)")
            else:
                fail += 1
                log(f"  !! {vid}: {rec['reason']}")
            save_json(series.manifest_path, manifest)
    log(f"=== done: {ok} ok, {fail} failed ===")
    return manifest


def write_index(series: Series, log=print) -> Path:
    """index.md in the output dir: one row per transcript, newest first."""
    catalog = load_json(series.catalog_path, {})
    manifest = load_json(series.manifest_path, {})
    rows = []
    for vid, rec in manifest.items():
        if rec.get("status") != "done":
            continue
        ep = catalog.get(vid) or read_frontmatter(series.out_dir / rec["file"])
        date = str(ep.get("upload_date") or "")
        date = f"{date[:4]}-{date[4:6]}-{date[6:8]}" if re.fullmatch(r"\d{8}", date) else date
        rows.append((date, ep.get("title") or vid, rec["file"], rec.get("word_count", 0)))
    rows.sort(reverse=True)
    lines = [f"# {series.name} transcripts", "", f"{len(rows)} episodes.", "",
             "| Date | Episode | Words |", "|---|---|---|"]
    for date, title, fname, words in rows:
        safe = title.replace("|", "\\|")
        lines.append(f"| {date} | [{safe}]({fname}) | {words:,} |")
    path = series.out_dir / "index.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"wrote {path} ({len(rows)} rows)")
    return path
