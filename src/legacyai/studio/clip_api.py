"""Clip revision lifecycle: draft -> rendering -> ready -> approved -> delivered."""
import hashlib
import hmac
import io
import json
import os
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from legacyai.clips.render import probe, safe_path
from legacyai.search.retrieve import decorate
from legacyai.search.index import youtube_id
from .auth import user
from .db import connect, get_record, now, storage_root, uid
from .jobs import enqueue, export_token
from .models import ClipEdit, NewClip
from .workflow_api import can_publish

router = APIRouter()


def require_clip(con, clip_id, actor):
    row = get_record(con,"clips",clip_id,actor["workspace_id"])
    if not row:
        raise HTTPException(404,"Clip not found")
    return dict(row)


def editable(con, clip):
    pending = con.execute("""SELECT id FROM jobs WHERE workspace_id=? AND state IN ('queued','running')
        AND kind IN ('render','publish') AND json_extract(payload,'$.clip_id')=?""",
        (clip["workspace_id"],clip["id"])).fetchone()
    if pending:
        raise HTTPException(409,"This clip has a job in progress. Wait for it to finish before editing")


def serialize(con, clip):
    ep = get_record(con,"episodes",clip["episode_id"],clip["workspace_id"])
    item = {**dict(ep),**dict(clip),"episode_title":ep["title"]}
    item.pop("result_path",None)
    item["has_render"] = bool(clip["result_path"] and clip["render_revision"]==clip["revision"])
    item["approved"] = clip["approved_revision"]==clip["revision"]
    item["assets"] = [dict(row) for row in con.execute(
        "SELECT id,name,duration FROM assets WHERE workspace_id=? AND episode_id=? ORDER BY created DESC",
        (clip["workspace_id"],clip["episode_id"]))]
    delivery = con.execute("SELECT status,receipt FROM deliveries WHERE clip_id=? AND revision=?",
                           (clip["id"],clip["revision"])).fetchone()
    item["delivery"] = dict(delivery) if delivery else None
    pending = con.execute("""SELECT id FROM jobs WHERE workspace_id=? AND state IN ('queued','running')
        AND json_extract(payload,'$.clip_id')=? ORDER BY created DESC LIMIT 1""",
        (clip["workspace_id"],clip["id"])).fetchone()
    item["active_job"] = pending["id"] if pending else None
    return decorate(item)


@router.get("/api/clips")
def clips(actor=Depends(user)):
    with connect() as con:
        return [serialize(con,row) for row in con.execute(
            "SELECT * FROM clips WHERE workspace_id=? ORDER BY updated DESC,id DESC LIMIT 200",(actor["workspace_id"],))]


@router.post("/api/clips")
def create(data: NewClip, actor=Depends(user)):
    with connect() as con:
        passage = get_record(con,"passages",data.passage_id,actor["workspace_id"])
        if not passage:
            raise HTTPException(404,"Passage not found")
        ep = get_record(con,"episodes",passage["episode_id"],actor["workspace_id"])
        record_id = uid()
        caption = f"From the archive: {ep['title']}\nOriginally published {ep['published']}."
        con.execute("""INSERT INTO clips(id,workspace_id,episode_id,passage_id,title,caption,
            transcript_text,transcript_hash,start,end,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (record_id,actor["workspace_id"],ep["id"],passage["id"],ep["title"][:250],caption,
             passage["text"],ep["content_hash"],passage["start"],min(passage["end"],passage["start"]+180),now(),now()))
        return serialize(con,get_record(con,"clips",record_id,actor["workspace_id"]))


@router.get("/api/clips/{clip_id}")
def clip(clip_id: str, actor=Depends(user)):
    with connect() as con:
        return serialize(con,require_clip(con,clip_id,actor))


@router.patch("/api/clips/{clip_id}")
def edit(clip_id: str, data: ClipEdit, actor=Depends(user)):
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        clip = require_clip(con,clip_id,actor)
        editable(con,clip)
        if clip["revision"] != data.revision:
            raise HTTPException(409,"This clip changed in another tab. Reload before saving")
        ep = get_record(con,"episodes",clip["episode_id"],actor["workspace_id"])
        duration = ep["duration"]
        if data.asset_id:
            asset = get_record(con,"assets",data.asset_id,actor["workspace_id"])
            if not asset or asset["episode_id"]!=clip["episode_id"]:
                raise HTTPException(422,"Choose a source video for this episode")
            duration = asset["duration"]
        if data.end>duration+.1:
            raise HTTPException(422,"The end time is past the source duration")
        if data.alignment_confirmed and not data.asset_id:
            raise HTTPException(422,"Add the source video before confirming timing")
        con.execute("""UPDATE clips SET title=?,caption=?,start=?,end=?,format=?,asset_id=?,
            alignment_confirmed=?,revision=revision+1,approved_revision=NULL,status='draft',
            error='',updated=? WHERE id=? AND workspace_id=?""",
            (data.title,data.caption,data.start,data.end,data.format,data.asset_id,
             int(data.alignment_confirmed),now(),clip_id,actor["workspace_id"]))
        return serialize(con,get_record(con,"clips",clip_id,actor["workspace_id"]))


@router.post("/api/clips/{clip_id}/render")
def render(clip_id: str, actor=Depends(user)):
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        clip = require_clip(con,clip_id,actor)
        editable(con,clip)
        if not clip["asset_id"] or not clip["alignment_confirmed"]:
            raise HTTPException(422,"Add a source video and confirm the timing before rendering")
        job_id = enqueue(con,actor["workspace_id"],"render",{"clip_id":clip_id,"revision":clip["revision"]})
        con.execute("UPDATE clips SET status='rendering',error='',approved_revision=NULL,updated=? WHERE id=?",
                    (now(),clip_id))
    return {"job_id":job_id}


@router.post("/api/clips/{clip_id}/approve")
def approve(clip_id: str, actor=Depends(user)):
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        clip = require_clip(con,clip_id,actor)
        editable(con,clip)
        if not clip["result_path"] or clip["render_revision"]!=clip["revision"]:
            raise HTTPException(422,"Render and preview this revision before approving")
        con.execute("UPDATE clips SET approved_revision=revision,status='approved',updated=? WHERE id=?",
                    (now(),clip_id))
    return {"ok":True}


@router.post("/api/clips/{clip_id}/publish")
def publish(clip_id: str, actor=Depends(user)):
    if not can_publish(actor["workspace_id"]):
        raise HTTPException(422,"No publisher is connected to this workspace. Export the clip package instead")
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        clip = require_clip(con,clip_id,actor)
        editable(con,clip)
        if clip["approved_revision"]!=clip["revision"] or clip["render_revision"]!=clip["revision"]:
            raise HTTPException(422,"Render and approve the current revision first")
        if con.execute("SELECT id FROM deliveries WHERE clip_id=? AND revision=?",(clip_id,clip["revision"])).fetchone():
            raise HTTPException(409,"This revision has already been sent or attempted. Check its delivery receipt")
        con.execute("INSERT INTO deliveries(id,workspace_id,clip_id,revision,status,created) VALUES(?,?,?,?,?,?)",
                    (uid(),actor["workspace_id"],clip_id,clip["revision"],"queued",now()))
        return {"job_id":enqueue(con,actor["workspace_id"],"publish",{"clip_id":clip_id,"revision":clip["revision"]})}


@router.post("/api/episodes/{episode_id}/media")
async def upload_media(episode_id: str, file: UploadFile=File(...), actor=Depends(user)):
    with connect() as con:
        if not get_record(con,"episodes",episode_id,actor["workspace_id"]):
            raise HTTPException(404,"Episode not found")
    extension = Path(file.filename or "video.mp4").suffix.lower()
    if extension not in {".mp4",".mov",".mkv",".webm",".avi"}:
        raise HTTPException(422,"Upload an MP4, MOV, MKV, WebM, or AVI video")
    limit = int(os.environ.get("LEGACY_UPLOAD_MB","1000"))*1024*1024
    asset_id = uid()
    folder = storage_root()/"media"/actor["workspace_id"]
    folder.mkdir(parents=True,exist_ok=True)
    path = folder/(asset_id+extension)
    total = 0
    try:
        with path.open("wb") as dest:
            while True:
                data = await file.read(1024*1024)
                if not data:
                    break
                total += len(data)
                if total>limit:
                    raise ValueError(f"Video exceeds the {limit//(1024*1024)} MB upload limit")
                dest.write(data)
        # ffprobe is blocking; keep it off the async request event loop.
        from starlette.concurrency import run_in_threadpool
        duration = await run_in_threadpool(probe,path)
        name = Path(file.filename or "Source video").name[:200]
        with connect() as con:
            con.execute("INSERT INTO assets VALUES(?,?,?,?,?,?,?)",
                        (asset_id,actor["workspace_id"],episode_id,name,str(path),duration,now()))
        return {"id":asset_id,"name":name,"duration":duration}
    except ValueError as exc:
        if path.exists():
            path.unlink()
        raise HTTPException(422,str(exc))
    finally:
        await file.close()


@router.post("/api/episodes/{episode_id}/fetch-video")
def fetch_source_video(episode_id: str, actor=Depends(user)):
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        ep = get_record(con,"episodes",episode_id,actor["workspace_id"])
        if not ep:
            raise HTTPException(404,"Episode not found")
        if not youtube_id(ep["source_url"]):
            raise HTTPException(422,"No YouTube video is linked to this episode. Upload the matching video")
        pending = con.execute("""SELECT id FROM jobs WHERE workspace_id=? AND kind='fetch_media'
            AND state IN ('queued','running') AND json_extract(payload,'$.episode_id')=?""",
            (actor["workspace_id"],episode_id)).fetchone()
        return {"job_id":pending["id"] if pending else enqueue(con,actor["workspace_id"],"fetch_media",{"episode_id":episode_id})}


@router.get("/api/media/{asset_id}")
def source_media(asset_id: str, actor=Depends(user)):
    with connect() as con:
        asset = get_record(con,"assets",asset_id,actor["workspace_id"])
        if not asset:
            raise HTTPException(404,"Source video not found")
    return FileResponse(safe_path(asset["path"]))


@router.get("/api/clips/{clip_id}/video")
def video(clip_id: str, actor=Depends(user)):
    with connect() as con:
        clip = require_clip(con,clip_id,actor)
    if not clip["result_path"] or clip["render_revision"]!=clip["revision"]:
        raise HTTPException(404,"Render the current revision first")
    return FileResponse(safe_path(clip["result_path"]),media_type="video/mp4")


@router.get("/api/clips/{clip_id}/export")
def export(clip_id: str, actor=Depends(user)):
    with connect() as con:
        clip = require_clip(con,clip_id,actor)
        ep = get_record(con,"episodes",clip["episode_id"],actor["workspace_id"])
    folder = storage_root()/"exports"/actor["workspace_id"]
    folder.mkdir(parents=True,exist_ok=True)
    package = folder/f"{clip_id}-r{clip['revision']}.zip"
    # Each request uses its own temporary path; concurrent exports cannot corrupt the archive.
    temp = folder/(uid()+".zip")
    manifest = {key:clip[key] for key in ("id","title","caption","start","end","format","revision","episode_id","transcript_hash")}
    manifest.update({"episode_title":ep["title"],"source_url":ep["source_url"],"published":ep["published"],
                     "timing":"Producer-confirmed source timing" if clip["alignment_confirmed"] else "Approximate paragraph boundaries",
                     "transcript_note":"Source passage snapshot; edits to trim points do not retime this text",
                     "approved":clip["approved_revision"]==clip["revision"]})
    with zipfile.ZipFile(temp,"w",compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("edit-decision.json",json.dumps(manifest,indent=2,ensure_ascii=False))
        archive.writestr("caption.txt",clip["caption"])
        archive.writestr("source-passage.txt",clip["transcript_text"])
        if clip["result_path"] and clip["render_revision"]==clip["revision"]:
            archive.write(safe_path(clip["result_path"]),"clip.mp4")
        else:
            archive.writestr("README.txt","Editorial package only. No rendered video yet. Add source media, confirm timing, and render in Legacy Studio.")
    # Response cleanup avoids retaining generated export duplicates on disk.
    from starlette.background import BackgroundTask
    return FileResponse(temp,filename=f"legacy-clip-{clip_id[:8]}.zip",media_type="application/zip",
                        background=BackgroundTask(temp.unlink,missing_ok=True))


@router.get("/delivery/{clip_id}")
def delivery_video(clip_id: str, revision: int, expires: int, token: str=Query(max_length=128)):
    if expires<now() or expires>now()+3600:
        raise HTTPException(403,"Download link has expired")
    try:
        expected = export_token(clip_id,revision,expires)
    except ValueError:
        raise HTTPException(403,"Download is unavailable")
    if not hmac.compare_digest(expected,token):
        raise HTTPException(403,"Invalid download link")
    with connect() as con:
        row = con.execute("SELECT * FROM clips WHERE id=?",(clip_id,)).fetchone()
    if not row or row["revision"]!=revision or row["approved_revision"]!=revision or row["render_revision"]!=revision:
        raise HTTPException(404,"Approved clip revision is no longer available")
    return FileResponse(safe_path(row["result_path"]),media_type="video/mp4")
