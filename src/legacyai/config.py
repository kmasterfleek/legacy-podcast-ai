"""Series configuration and on-disk layout.

Layout (relative to LEGACY_HOME, default: current directory):

    series/<slug>/series.json     what to harvest and how
    series/<slug>/catalog.json    every episode discovered (id -> metadata)
    series/<slug>/manifest.json   per-episode build status
    series/<slug>/cache/          raw extractor JSON and caption files
    series/<slug>/transcripts/    rendered markdown (overridable)
"""
import json
import os
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional


def home() -> Path:
    return Path(os.environ.get("LEGACY_HOME", os.getcwd())).resolve()


def slugify(text: str, limit: int = 70) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:limit].rstrip("-") or "untitled"


@dataclass
class Series:
    name: str
    slug: str
    sources: List[str] = field(default_factory=list)
    language: str = "en"
    min_minutes: float = 0
    max_minutes: Optional[float] = None
    include: Optional[str] = None      # regex on title; keep only matches
    exclude: Optional[str] = None      # regex on title; drop matches
    providers: List[str] = field(default_factory=lambda: ["captions", "whisper"])
    transcripts_dir: Optional[str] = None  # relative to series dir; default "transcripts"
    player_clients: List[str] = field(default_factory=lambda: ["android", "tv", "web"])
    max_entries: int = 0               # per source; 0 = everything
    request_sleep: float = 1.0         # seconds between yt-dlp requests (rate-limit courtesy)
    cookies_from_browser: Optional[str] = None  # e.g. "chrome", "firefox", "safari"
    cookies_file: Optional[str] = None          # Netscape cookies.txt
    created: str = field(default_factory=lambda: time.strftime("%Y-%m-%d"))

    # ---- paths -------------------------------------------------------
    @property
    def dir(self) -> Path:
        return home() / "series" / self.slug

    @property
    def config_path(self) -> Path:
        return self.dir / "series.json"

    @property
    def catalog_path(self) -> Path:
        return self.dir / "catalog.json"

    @property
    def manifest_path(self) -> Path:
        return self.dir / "manifest.json"

    @property
    def cache_dir(self) -> Path:
        return self.dir / "cache"

    @property
    def out_dir(self) -> Path:
        return (self.dir / (self.transcripts_dir or "transcripts")).resolve()

    # ---- persistence -------------------------------------------------
    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(exist_ok=True)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False))

    @classmethod
    def load(cls, slug: str) -> "Series":
        path = home() / "series" / slug / "series.json"
        if not path.exists():
            raise SystemExit(f"no series '{slug}' (expected {path}); run: legacy init")
        data = json.loads(path.read_text())
        known = {k for k in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def list_all(cls) -> List["Series"]:
        base = home() / "series"
        if not base.exists():
            return []
        out = []
        for p in sorted(base.iterdir()):
            if (p / "series.json").exists():
                out.append(cls.load(p.name))
        return out

    # ---- filtering ---------------------------------------------------
    def wants(self, episode: dict) -> Optional[str]:
        """Return None if the episode is in scope, else the reason it is not."""
        dur = episode.get("duration") or 0
        if self.min_minutes and dur < self.min_minutes * 60:
            return "too short"
        if self.max_minutes and dur > self.max_minutes * 60:
            return "too long"
        title = episode.get("title") or ""
        if self.include and not re.search(self.include, title, re.I):
            return "title not in include pattern"
        if self.exclude and re.search(self.exclude, title, re.I):
            return "title matches exclude pattern"
        return None


def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            pass
    return default


def save_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True))
    os.replace(tmp, path)
