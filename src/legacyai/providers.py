"""Transcript providers, tried in order until one yields cues.

captions  - manual subtitles, then platform ASR captions. On YouTube the
            English ASR track is hidden from anonymous clients, but machine
            translations are not; their URLs are the English track plus
            "&tlang=xx", so stripping tlang recovers the original.
whisper   - download audio (needs ffmpeg) and transcribe with faster-whisper
            or the openai-whisper CLI, whichever is installed.
"""
import re
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

from .config import Series
from .render import Cue, parse_vtt


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


def captions(series: Series, episode: dict, info: Optional[dict]) -> Tuple[List[Cue], str]:
    if episode.get("kind") == "local":
        raise ProviderError("local file")
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
    if not shutil.which("ffmpeg"):
        return None
    try:
        import faster_whisper  # noqa: F401
        return "faster-whisper"
    except ImportError:
        pass
    if shutil.which("whisper"):
        return "whisper-cli"
    return None


def _audio_path(series: Series, episode: dict) -> Path:
    if episode.get("kind") == "local":
        return Path(episode["path"])
    out = series.cache_dir / "audio" / f"{episode['id']}.m4a"
    if out.exists() and out.stat().st_size > 0:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    import yt_dlp
    opts = {
        "quiet": True, "no_warnings": True, "format": "bestaudio/best",
        "outtmpl": str(out.with_suffix("")) + ".%(ext)s",
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}],
        "extractor_args": {"youtube": {"player_client": series.player_clients[:1] or ["android"]}},
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([episode["url"]])
    if not out.exists():
        raise ProviderError("audio download failed")
    return out


def whisper(series: Series, episode: dict, info: Optional[dict]) -> Tuple[List[Cue], str]:
    backend = whisper_available()
    if not backend:
        raise ProviderError("whisper unavailable (needs ffmpeg + faster-whisper or whisper CLI)")
    audio = _audio_path(series, episode)
    lang = series.language.split("-")[0]
    if backend == "faster-whisper":
        from faster_whisper import WhisperModel
        model = WhisperModel("small", compute_type="int8")
        segments, _ = model.transcribe(str(audio), language=lang, vad_filter=True)
        cues = [(float(s.start), s.text.strip()) for s in segments if s.text.strip()]
        return cues, "Whisper (faster-whisper small)"
    out_dir = series.cache_dir / "whisper"
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["whisper", str(audio), "--model", "small", "--language", lang,
                    "--output_format", "vtt", "--output_dir", str(out_dir)],
                   check=True, capture_output=True, timeout=6 * 3600)
    vtt = out_dir / (audio.stem + ".vtt")
    cues = list(parse_vtt(vtt.read_text(encoding="utf-8", errors="ignore")))
    if not cues:
        raise ProviderError("whisper produced no cues")
    return cues, "Whisper (openai-whisper small)"


PROVIDERS = {"captions": captions, "whisper": whisper}
