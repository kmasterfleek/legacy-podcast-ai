"""Discover episodes from sources and probe their metadata.

A source is anything yt-dlp can enumerate: a YouTube channel (or its
/videos, /podcasts tab), a playlist, another site's series page, or a single
video URL. Local media files are added with `import_local`.
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional

from .config import Series, load_json, save_json
from .sources import LISTERS, kind_of

CACHE_TTL = 4 * 3600  # signed caption URLs expire; refresh extractor JSON after this
BLOCK_MARKERS = ("429", "Too Many Requests", "not a bot", "Sign in to confirm")


class RateLimited(Exception):
    """YouTube is refusing anonymous requests from this IP for now."""


def _ydl(series: Series, client: Optional[str] = None, flat: bool = False, max_entries: int = 0):
    import yt_dlp  # imported lazily so `legacy --help` works without it
    opts = {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "socket_timeout": 30, "retries": 3, "ignoreerrors": True,
        "logger": _SilentLogger(),
        "sleep_interval_requests": series.request_sleep or 0,
    }
    if series.cookies_from_browser:
        opts["cookiesfrombrowser"] = (series.cookies_from_browser,)
    if series.cookies_file:
        opts["cookiefile"] = str(Path(series.cookies_file).expanduser())
    if flat:
        opts["extract_flat"] = "in_playlist"
    if max_entries:
        opts["playlistend"] = max_entries
    if client:
        opts["extractor_args"] = {"youtube": {"player_client": [client]}}
    return yt_dlp.YoutubeDL(opts)


class _SilentLogger:
    """Swallow yt-dlp chatter but remember anything that looks like a block."""
    def __init__(self):
        self.blocked = False

    def _note(self, msg):
        if any(m in str(msg) for m in BLOCK_MARKERS):
            self.blocked = True

    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): self._note(msg)
    def error(self, msg): self._note(msg)


def list_source(series: Series, url: str, max_entries: int = 0) -> List[dict]:
    """Return flat entries [{id, url, title}] for a source URL."""
    with _ydl(series, flat=True, max_entries=max_entries or series.max_entries) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        return []
    entries = []
    stack = [info]
    while stack:
        node = stack.pop()
        if not node:
            continue
        if node.get("_type") in ("playlist", "multi_video") or "entries" in node:
            stack.extend(e for e in (node.get("entries") or []) if e)
            continue
        vid = node.get("id")
        if not vid or node.get("ie_key") in ("YoutubeTab", "YoutubePlaylist"):
            continue  # a playlist/tab shelf, not an episode
        entries.append({
            "id": vid,
            "url": node.get("webpage_url") or node.get("url") or f"https://www.youtube.com/watch?v={vid}",
            "title": node.get("title") or "",
        })
    return entries


def fetch_info(series: Series, url: str, episode_id: str, force: bool = False) -> Optional[dict]:
    """Full extractor JSON for one episode, cached on disk (TTL-aware)."""
    path = series.cache_dir / "json" / f"{episode_id}.json"
    if not force and path.exists() and time.time() - path.stat().st_mtime < CACHE_TTL:
        return load_json(path, None)
    info = fallback = None
    blocked = False
    for client in series.player_clients or [None]:
        try:
            with _ydl(series, client=client) as ydl:
                info = ydl.extract_info(url, download=False)
                blocked = blocked or ydl.params["logger"].blocked
        except Exception as exc:
            info = None
            blocked = blocked or any(m in str(exc) for m in BLOCK_MARKERS)
        if not info or info.get("duration") is None:
            continue
        if info.get("subtitles") or info.get("automatic_captions"):
            break  # this client exposes caption tracks; good enough
        fallback = fallback or info
    info = info if (info and info.get("duration") is not None) else fallback
    if not info:
        if blocked:
            raise RateLimited(url)
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    keep = {k: info.get(k) for k in (
        "id", "title", "webpage_url", "upload_date", "duration", "uploader",
        "channel", "description", "subtitles", "automatic_captions", "extractor_key",
        "language", "playlist_title", "series", "season_number", "episode_number",
    )}
    save_json(path, keep)
    return keep


def episode_from_info(info: dict, source: str) -> dict:
    return {
        "id": info.get("id"),
        "title": info.get("title") or "",
        "url": info.get("webpage_url") or "",
        "upload_date": info.get("upload_date") or "",
        "duration": int(info.get("duration") or 0),
        "channel": info.get("channel") or info.get("uploader") or "",
        "source": source,
        "kind": "url",
        "season": info.get("season_number"),
        "episode": info.get("episode_number"),
    }


def discover(series: Series, workers: int = 6, max_entries: int = 0, log=print) -> Dict[str, dict]:
    """Enumerate all sources, probe new episodes, merge into catalog.json."""
    catalog: Dict[str, dict] = load_json(series.catalog_path, {})
    seen: Dict[str, dict] = {}
    for src in series.sources:
        kind = kind_of(src)
        log(f"listing [{kind}] {src}")
        try:
            if kind in LISTERS:  # archive.org / RSS: entries arrive with full metadata
                eps = LISTERS[kind](src, max_entries or series.max_entries, log)
                for ep in eps:
                    catalog[ep["id"]] = {**ep, "source": src}
                    seen.setdefault(ep["id"], {**ep, "source": src})
                log(f"  {len(eps)} entries")
                continue
            entries = list_source(series, src, max_entries)
        except Exception as exc:  # network / extractor failure on one source
            log(f"  !! could not list source: {exc}")
            continue
        log(f"  {len(entries)} entries")
        for e in entries:
            seen.setdefault(e["id"], {**e, "source": src})
    todo = [e for vid, e in seen.items()
            if e.get("kind", "url") == "url" and (vid not in catalog or not catalog[vid].get("duration"))]
    log(f"{len(seen)} unique entries across sources, {len(todo)} need metadata")

    def probe(e):
        info = fetch_info(series, e["url"], e["id"])
        if not info:
            return e["id"], None
        return e["id"], episode_from_info(info, e["source"])

    done = 0
    stop = False
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(probe, e) for e in todo]
        for fut in as_completed(futures):
            if stop:
                continue
            try:
                vid, ep = fut.result()
            except RateLimited:
                stop = True
                for f in futures:
                    f.cancel()
                log("  !! YouTube is rate-limiting this IP (HTTP 429 / bot check). Stopping early;\n"
                    "     re-run `legacy discover` later, lower --workers, or set cookies via\n"
                    "     `legacy config <series> --cookies-from-browser chrome`.")
                continue
            done += 1
            if ep:
                catalog[vid] = ep
            else:
                catalog.setdefault(vid, {**seen[vid], "duration": 0, "upload_date": "",
                                         "kind": "url", "probe_failed": True})
            if done % 10 == 0 or done == len(todo):
                log(f"  probed {done}/{len(todo)}")
            if done % 25 == 0:
                save_json(series.catalog_path, catalog)
    save_json(series.catalog_path, catalog)
    return catalog


def _ffprobe_duration(path: Path) -> int:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=60).stdout.strip()
        return int(float(out))
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def import_local(series: Series, paths: List[str], log=print) -> Dict[str, dict]:
    """Add local audio/video files (e.g. a TV series on disk) to the catalog."""
    catalog: Dict[str, dict] = load_json(series.catalog_path, {})
    for p in paths:
        path = Path(p).expanduser().resolve()
        if not path.is_file():
            log(f"  !! not a file: {path}")
            continue
        vid = "local-" + hashlib.sha1(str(path).encode()).hexdigest()[:12]
        mtime = time.strftime("%Y%m%d", time.localtime(path.stat().st_mtime))
        catalog[vid] = {
            "id": vid, "title": path.stem, "url": "", "upload_date": mtime,
            "duration": _ffprobe_duration(path), "channel": "", "source": "local",
            "kind": "local", "path": str(path),
        }
        log(f"  + {vid}  {path.name}")
    save_json(series.catalog_path, catalog)
    return catalog


def in_scope(series: Series, catalog: Dict[str, dict]) -> List[dict]:
    eps = [e for e in catalog.values() if series.wants(e) is None]
    return sorted(eps, key=lambda e: e.get("upload_date") or "", reverse=True)
