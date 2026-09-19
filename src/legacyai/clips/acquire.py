"""Fetch a video's exact YouTube source on explicit producer request."""
import os
from pathlib import Path

from legacyai.search.index import youtube_id
from legacyai.studio.db import storage_root, uid
from .render import probe


def fetch_video(episode):
    if not youtube_id(episode["source_url"]):
        raise ValueError("This episode has no linked YouTube video. Upload the source video instead")
    try:
        import yt_dlp
    except ImportError:
        raise ValueError("Install the project's yt-dlp dependency to fetch source videos")
    asset_id = uid()
    folder = storage_root()/"media"/episode["workspace_id"]/asset_id
    folder.mkdir(parents=True,exist_ok=True)
    limit = int(os.environ.get("LEGACY_UPLOAD_MB","1000"))*1024*1024

    def progress(info):
        if info.get("downloaded_bytes",0)>limit:
            raise ValueError("Source video exceeds the configured media size limit")

    options = {"quiet":True,"no_warnings":True,"noplaylist":True,
               "format":"bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
               "merge_output_format":"mp4","outtmpl":str(folder/"source.%(ext)s"),
               "max_filesize":limit,"socket_timeout":30,"retries":2,
               "progress_hooks":[progress]}
    if os.environ.get("LEGACY_YOUTUBE_COOKIE_FILE"):
        options["cookiefile"] = os.environ["LEGACY_YOUTUBE_COOKIE_FILE"]
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            downloader.download([episode["source_url"]])
        files = [p for p in folder.iterdir() if p.is_file() and p.suffix in {".mp4",".mkv",".webm"}]
        if len(files)!=1:
            raise ValueError("A complete source video could not be fetched. Upload the original file instead")
        path = files[0]
        if path.stat().st_size>limit:
            path.unlink()
            raise ValueError("Source video exceeds the configured media size limit")
        return {"id":asset_id,"path":str(path),"duration":probe(path),"name":episode["title"]+path.suffix}
    except yt_dlp.utils.DownloadError:
        raise ValueError("YouTube could not provide this video. Upload your source file or configure owner authentication")
