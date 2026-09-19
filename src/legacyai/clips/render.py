"""FFmpeg runs only against workspace-owned, locally registered media."""
import json
import subprocess
from pathlib import Path

from legacyai.studio.db import storage_root

FORMATS = {"9:16": (720,1280), "1:1": (1080,1080), "16:9": (1280,720)}
ALLOWED_FORMATS = "mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,avi,mpegts"


def safe_path(path):
    path = Path(path).resolve()
    if storage_root() not in path.parents:
        raise ValueError("Media path is outside Studio storage")
    return path


def probe(path):
    cmd = ["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
           "-format_whitelist", ALLOWED_FORMATS, "-show_format", "-show_streams",
           "-of", "json", str(safe_path(path))]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=45)
        info = json.loads(result.stdout)
        if not any(s.get("codec_type")=="video" for s in info.get("streams", [])):
            raise ValueError("Please upload a video file, not audio-only media")
        duration = float(info.get("format", {}).get("duration", 0))
        if duration<=0:
            raise ValueError("Could not read the video's duration")
        return duration
    except FileNotFoundError:
        raise ValueError("FFmpeg is not installed on this server")
    except (subprocess.SubprocessError, json.JSONDecodeError):
        raise ValueError("This video could not be read. Try an MP4 or WebM file")


def render_clip(clip, asset):
    start, end = float(clip["start"]), float(clip["end"])
    if start<0 or end<=start or end-start>180 or end>asset["duration"]+.1:
        raise ValueError("Choose a valid range of up to 180 seconds within the source video")
    width, height = FORMATS[clip["format"]]
    folder = storage_root()/"renders"/clip["workspace_id"]
    folder.mkdir(parents=True, exist_ok=True)
    output = folder/f"{clip['id']}-r{clip['revision']}.mp4"
    temporary = folder/f"{clip['id']}-r{clip['revision']}.partial.mp4"
    filters = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
           "-protocol_whitelist", "file,pipe", "-format_whitelist", ALLOWED_FORMATS,
           "-ss", str(start), "-i", str(safe_path(asset["path"])), "-t", str(end-start),
           "-map", "0:v:0", "-map", "0:a:0?", "-vf", filters,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-threads", "2",
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(temporary)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=1800)
        actual = probe(temporary)
        if abs(actual-(end-start))>1.5:
            raise ValueError("The rendered duration did not match the selected range")
        temporary.replace(output)
        return str(output)
    except FileNotFoundError:
        raise ValueError("FFmpeg is not installed on this server")
    except subprocess.SubprocessError:
        raise ValueError("Video rendering failed. Check the source file and try again")
    finally:
        if temporary.exists():
            temporary.unlink()
