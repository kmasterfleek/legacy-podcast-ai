"""Transcript providers, tried in order until one yields cues.

captions  - manual subtitles, then platform ASR captions. On YouTube the
            English ASR track is hidden from anonymous clients, but machine
            translations are not; their URLs are the English track plus
            "&tlang=xx", so stripping tlang recovers the original.
whisper   - download audio (needs ffmpeg) and transcribe with faster-whisper
            or the openai-whisper CLI, whichever is installed.
"""
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

from .config import Series
from .render import Cue, parse_vtt
from .sources import UA, parse_podcast_json_transcript


class ProviderError(Exception):
    """Raised with a short, stable reason string."""


# ---------------------------------------------------------------- captions
def _vtt_tracks(tracks: dict, lang_pred) -> List[str]:
    urls = []
    for lang, items in (tracks or {}).items():
        if not lang_pred(lang):
            continue
        for t in items or []:
            if t.get("ext") in ("vtt", "srt") and t.get("url"):
                urls.append(t["url"])
    return urls


def pick_caption_urls(info: dict, language: str) -> List[Tuple[str, str]]:
    """Ordered (url, label) candidates for the wanted language."""
    base = language.split("-")[0].lower()
    same = lambda lang: lang.split("-")[0].lower() == base  # noqa: E731
    out: List[Tuple[str, str]] = []
    for u in _vtt_tracks(info.get("subtitles"), same):
        out.append((u, "manual subtitles"))
    for u in _vtt_tracks(info.get("automatic_captions"), same):
        if "tlang=" not in u:
            out.append((u, "automatic captions (ASR)"))
    # A translated track whose *source* is the wanted language -> strip tlang.
    src_is_base = re.compile(r"[?&]lang=" + re.escape(base) + r"(?:-[^&]*)?(?:&|$)")
    for u in _vtt_tracks(info.get("automatic_captions"), lambda _: True):
        if "tlang=" in u and src_is_base.search(u):
            out.append((_strip_tlang(u), "automatic captions (ASR)"))
            break
    # Last resort: a translation *into* the wanted language.
    for u in _vtt_tracks(info.get("automatic_captions"), same):
        if "tlang=" in u:
            out.append((u, f"automatic captions, machine-translated to {language}"))
            break
    return out


def _strip_tlang(url: str) -> str:
    return re.sub(r"([&?])tlang=[^&]*&?", r"\1", url).rstrip("?&")


def _download(url: str, dest: Path, attempts: int = 3) -> bool:
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=180) as r, open(dest, "wb") as fh:
                shutil.copyfileobj(r, fh)
            if dest.stat().st_size > 0 and "-->" in dest.read_text(errors="ignore")[:5000]:
                return True
        except (OSError, ValueError):
            pass
        time.sleep(2 * (i + 1))
    return False


def sidecar(series: Series, episode: dict, info: Optional[dict]) -> Tuple[List[Cue], str]:
    """Transcript files published next to the media: RSS <podcast:transcript>, archive.org .srt/.vtt."""
    urls = episode.get("transcript_urls") or []
    if not urls:
        raise ProviderError("no sidecar transcript")
    dest_dir = series.cache_dir / "sidecar"
    dest_dir.mkdir(parents=True, exist_ok=True)
    vtt_first = lambda u: 0 if re.search(r"webvtt|\.vtt(\?|$)", u, re.I) else 1  # noqa: E731
    for u in sorted(urls, key=vtt_first):  # WebVTT carries <v Speaker> voice tags; SRT does not
        ext = "json" if u.lower().split("?")[0].endswith(".json") else "vtt"
        dest = dest_dir / f"{episode['id']}.{ext}"
        try:
            req = urllib.request.Request(u, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as fh:
                shutil.copyfileobj(r, fh)
        except (OSError, ValueError):
            continue
        text = dest.read_text(encoding="utf-8", errors="ignore")
        cues = parse_podcast_json_transcript(text) if text.lstrip().startswith(("{", "[")) else list(parse_vtt(text))
        if cues:
            return cues, "published transcript"
    raise ProviderError("sidecar transcript download failed")


def captions(series: Series, episode: dict, info: Optional[dict]) -> Tuple[List[Cue], str]:
    if episode.get("kind") != "url":
        raise ProviderError("not a yt-dlp source")
    if not info:
        raise ProviderError("metadata fetch failed")
    candidates = pick_caption_urls(info, series.language)
    if not candidates:
        raise ProviderError("no caption tracks exposed")
    vtt = series.cache_dir / "vtt" / f"{episode['id']}.vtt"
    vtt.parent.mkdir(parents=True, exist_ok=True)
    for url, label in candidates:
        if _download(url, vtt):
            cues = list(parse_vtt(vtt.read_text(encoding="utf-8", errors="ignore")))
            if cues:
                return cues, f"{label}, {series.language}"
    raise ProviderError("caption download failed")


# ----------------------------------------------------------------- whisper
def whisper_available() -> Optional[str]:
    try:
        import faster_whisper  # noqa: F401
        return "faster-whisper"  # decodes with PyAV; no ffmpeg binary needed
    except ImportError:
        pass
    if shutil.which("whisper") and shutil.which("ffmpeg"):
        return "whisper-cli"
    return None


def _audio_path(series: Series, episode: dict) -> Path:
    """Local path to something PyAV can decode: the file itself, a direct download, or yt-dlp's best audio."""
    kind = episode.get("kind")
    if kind == "local":
        return Path(episode["path"])
    adir = series.cache_dir / "audio"
    adir.mkdir(parents=True, exist_ok=True)
    complete = lambda p: p.stat().st_size > 0 and not p.name.endswith(".part")  # noqa: E731
    existing = [p for p in adir.glob(episode["id"] + ".*") if complete(p)]
    if existing:
        return existing[0]
    if kind == "media":
        url = episode.get("media_url") or ""
        ext = Path(url.split("?")[0]).suffix.lstrip(".") or "bin"
        dest = adir / f"{episode['id']}.{ext}"
        part = dest.with_name(dest.name + ".part")
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                size_mb = int(r.headers.get("Content-Length") or 0) / (1 << 20)
                if series.max_media_mb and size_mb > series.max_media_mb:
                    raise ProviderError(f"media too large: {size_mb:.0f} MB > max_media_mb={series.max_media_mb}")
                with open(part, "wb") as fh:
                    shutil.copyfileobj(r, fh, 1 << 20)
            os.replace(part, dest)  # only a finished download gets the real name
        except (OSError, ValueError) as exc:
            if part.exists():
                part.unlink()
            raise ProviderError(f"media download failed: {exc}")
        return dest
    import yt_dlp
    opts = {
        "quiet": True, "no_warnings": True, "format": "bestaudio/best",
        "outtmpl": str(adir / episode["id"]) + ".%(ext)s",
        "extractor_args": {"youtube": {"player_client": series.player_clients[:1] or ["android"]}},
    }
    if shutil.which("ffmpeg"):  # optional: shrink to m4a when ffmpeg is around
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}]
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([episode["url"]])
    found = [p for p in adir.glob(episode["id"] + ".*") if complete(p)]
    if not found:
        raise ProviderError("audio download failed")
    return found[0]


def whisper(series: Series, episode: dict, info: Optional[dict]) -> Tuple[List[Cue], str]:
    backend = whisper_available()
    if not backend:
        raise ProviderError("whisper unavailable (pip install faster-whisper)")
    audio = _audio_path(series, episode)
    lang = series.language.split("-")[0]
    model_name = series.whisper_model or "small"
    if backend == "faster-whisper":
        model = _whisper_model(model_name)
        segments, _ = model.transcribe(str(audio), language=lang, vad_filter=bool(series.whisper_vad), beam_size=5)
        cues = [(float(s.start), s.text.strip()) for s in segments if s.text.strip()]
        if not cues:
            raise ProviderError("no speech detected")
        return cues, f"Whisper (faster-whisper {model_name})"
    out_dir = series.cache_dir / "whisper"
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["whisper", str(audio), "--model", model_name, "--language", lang,
                    "--output_format", "vtt", "--output_dir", str(out_dir)],
                   check=True, capture_output=True, timeout=6 * 3600)
    vtt = out_dir / (audio.stem + ".vtt")
    cues = list(parse_vtt(vtt.read_text(encoding="utf-8", errors="ignore")))
    if not cues:
        raise ProviderError("whisper produced no cues")
    return cues, f"Whisper (openai-whisper {model_name})"


_MODELS = {}
_MODEL_LOCK = threading.Lock()


def _whisper_model(name: str):
    """Load each model once per process (hundreds of MB); safe with several build workers.

    CTranslate2 allows concurrent transcribe() calls on one model, but decoding is
    CPU-bound, so Whisper-heavy series gain nothing from --workers above 1.
    """
    with _MODEL_LOCK:
        if name not in _MODELS:
            from faster_whisper import WhisperModel
            _MODELS[name] = WhisperModel(name, compute_type="int8")
        return _MODELS[name]


PROVIDERS = {"captions": captions, "sidecar": sidecar, "whisper": whisper}
