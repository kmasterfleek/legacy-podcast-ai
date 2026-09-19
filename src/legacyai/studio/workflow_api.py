"""Saved opportunities and configured headline sources."""
import shutil

from fastapi import APIRouter, Depends, HTTPException
from legacyai.trends.feeds import public_url, save_opportunity
from .auth import user
from .db import connect, get_record, now, uid
from .jobs import enqueue, publisher_ready
from .models import Opportunity, Source

router = APIRouter(prefix="/api")


@router.get("/opportunities")
def opportunities(actor=Depends(user)):
    with connect() as con:
        return [dict(x) for x in con.execute("""SELECT o.*,s.name AS source_name FROM opportunities o
            LEFT JOIN sources s ON s.id=o.source_id WHERE o.workspace_id=?
            ORDER BY o.created DESC,o.id DESC LIMIT 100""",(actor["workspace_id"],))]


@router.post("/opportunities")
def save(data: Opportunity, actor=Depends(user)):
    with connect() as con:
        return save_opportunity(con,actor["workspace_id"],data.title,data.source_url)


@router.get("/connections")
def connections(actor=Depends(user)):
    with connect() as con:
        sources = [dict(x) for x in con.execute("SELECT * FROM sources WHERE workspace_id=? ORDER BY name",
                                               (actor["workspace_id"],))]
        jobs = [dict(x) for x in con.execute("""SELECT id,kind,state,error,created,updated FROM jobs
            WHERE workspace_id=? ORDER BY created DESC LIMIT 20""",(actor["workspace_id"],))]
    # Publisher is restricted to a single configured workspace, never shared across tenants.
    return {"sources":sources,"jobs":jobs,"renderer":bool(shutil.which("ffmpeg") and shutil.which("ffprobe")),
            "publisher":can_publish(actor["workspace_id"]),"search":"Keyword + aliases"}


def can_publish(workspace_id):
    import os
    return publisher_ready() and os.environ.get("LEGACY_PUBLISH_WORKSPACE")==workspace_id


@router.post("/sources")
def add_source(data: Source, actor=Depends(user)):
    try:
        public_url(data.url)
    except ValueError as exc:
        raise HTTPException(422,str(exc))
    with connect() as con:
        if con.execute("SELECT COUNT(*) FROM sources WHERE workspace_id=?",(actor["workspace_id"],)).fetchone()[0]>=10:
            raise HTTPException(422,"This workspace supports up to ten feeds")
        existing = con.execute("SELECT id FROM sources WHERE workspace_id=? AND url=?",
                               (actor["workspace_id"],data.url)).fetchone()
        if existing:
            raise HTTPException(409,"This feed is already connected")
        record_id = uid()
        con.execute("INSERT INTO sources(id,workspace_id,name,url) VALUES(?,?,?,?)",
                    (record_id,actor["workspace_id"],data.name,data.url))
        job_id = enqueue(con,actor["workspace_id"],"feed",{"source_id":record_id})
    return {"id":record_id,"job_id":job_id}


@router.post("/sources/{source_id}/sync")
def sync_source(source_id: str, actor=Depends(user)):
    with connect() as con:
        if not get_record(con,"sources",source_id,actor["workspace_id"]):
            raise HTTPException(404,"Feed not found")
        pending = con.execute("""SELECT id FROM jobs WHERE workspace_id=? AND kind='feed'
            AND state IN ('queued','running') AND json_extract(payload,'$.source_id')=?""",
            (actor["workspace_id"],source_id)).fetchone()
        return {"job_id":pending["id"] if pending else enqueue(con,actor["workspace_id"],"feed",{"source_id":source_id})}


@router.delete("/sources/{source_id}")
def remove_source(source_id: str, actor=Depends(user)):
    with connect() as con:
        con.execute("DELETE FROM sources WHERE id=? AND workspace_id=?", (source_id,actor["workspace_id"]))
    return {"ok":True}


@router.get("/jobs/{job_id}")
def job(job_id: str, actor=Depends(user)):
    with connect() as con:
        row = get_record(con,"jobs",job_id,actor["workspace_id"])
        if not row:
            raise HTTPException(404,"Job not found")
        return {key:row[key] for key in ("id","kind","state","error","created","updated")}
