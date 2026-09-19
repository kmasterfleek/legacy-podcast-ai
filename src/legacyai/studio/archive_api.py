"""Read/query the archive and import additional transcripts through the browser."""
from pathlib import Path
import hashlib
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from legacyai.search.index import index_archive, parse_transcript
from legacyai.search.retrieve import decorate, search
from .auth import user
from .db import connect, get_record, storage_root, uid

router = APIRouter(prefix="/api")


@router.get("/stats")
def stats(actor=Depends(user)):
    wid = actor["workspace_id"]
    with connect() as con:
        row = dict(con.execute("""SELECT COUNT(*) AS episodes,COALESCE(SUM(word_count),0) AS words,
            COALESCE(SUM(duration),0) AS seconds,MIN(published) AS first_date,MAX(published) AS last_date,
            COALESCE(SUM(source_kind='youtube'),0) AS video_linked,
            COALESCE(SUM(speaker_labels),0) AS speaker_labeled FROM episodes WHERE workspace_id=?""", (wid,)).fetchone())
        row["passages"] = con.execute("SELECT COUNT(*) FROM passages WHERE workspace_id=?", (wid,)).fetchone()[0]
        row["clips"] = con.execute("SELECT COUNT(*) FROM clips WHERE workspace_id=?", (wid,)).fetchone()[0]
        row["opportunities"] = con.execute("SELECT COUNT(*) FROM opportunities WHERE workspace_id=?", (wid,)).fetchone()[0]
    return row


@router.get("/search")
def find(q: str=Query(min_length=2,max_length=500), source: str="", actor=Depends(user)):
    if source not in {"","youtube","podcast","archive"}:
        raise HTTPException(422,"Unknown source filter")
    with connect() as con:
        return search(con,actor["workspace_id"],q,source_kind=source)


@router.get("/episodes")
def episodes(q: str=Query(default="",max_length=200), page: int=Query(default=1,ge=1), actor=Depends(user)):
    pattern = "%"+q.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%"
    with connect() as con:
        total = con.execute("SELECT COUNT(*) FROM episodes WHERE workspace_id=? AND title LIKE ? ESCAPE '\\'",
                            (actor["workspace_id"],pattern)).fetchone()[0]
        rows = con.execute("""SELECT * FROM episodes WHERE workspace_id=? AND title LIKE ? ESCAPE '\\'
            ORDER BY published DESC,id LIMIT 24 OFFSET ?""",(actor["workspace_id"],pattern,(page-1)*24)).fetchall()
    return {"items":[decorate(row) for row in rows],"total":total,"page":page}


@router.get("/episodes/{episode_id}")
def episode(episode_id: str, actor=Depends(user)):
    with connect() as con:
        ep = get_record(con,"episodes",episode_id,actor["workspace_id"])
        if not ep:
            raise HTTPException(404,"Episode not found")
        rows = con.execute("""SELECT * FROM passages WHERE workspace_id=? AND episode_id=?
            ORDER BY ordinal""", (actor["workspace_id"],episode_id)).fetchall()
        assets = con.execute("SELECT id,name,duration FROM assets WHERE workspace_id=? AND episode_id=?",
                             (actor["workspace_id"],episode_id)).fetchall()
        result = decorate(ep)
        result["passages"] = [dict(row) for row in rows]
        result["assets"] = [dict(row) for row in assets]
    return result


@router.get("/passages/{passage_id}")
def passage(passage_id: str, actor=Depends(user)):
    with connect() as con:
        row = get_record(con,"passages",passage_id,actor["workspace_id"])
        if not row:
            raise HTTPException(404,"Passage not found")
        ep = get_record(con,"episodes",row["episode_id"],actor["workspace_id"])
        around = con.execute("""SELECT * FROM passages WHERE workspace_id=? AND episode_id=?
            AND ordinal BETWEEN ? AND ? ORDER BY ordinal""",
            (actor["workspace_id"],row["episode_id"],max(0,row["ordinal"]-2),row["ordinal"]+2)).fetchall()
    return {"passage":decorate({**dict(ep),**dict(row)}),"context":[dict(x) for x in around]}


@router.post("/archive/import")
async def import_files(files: List[UploadFile]=File(...), actor=Depends(user)):
    if len(files)>50:
        raise HTTPException(422,"Import up to 50 transcripts at a time")
    folder = storage_root()/"transcripts"/actor["workspace_id"]
    folder.mkdir(parents=True,exist_ok=True)
    accepted, errors = 0, []
    for upload in files:
        name = Path(upload.filename or "transcript.md").name
        if not name.endswith(".md"):
            errors.append({"file":name,"error":"Upload Markdown transcripts (.md)"})
            await upload.close()
            continue
        data = await upload.read(2*1024*1024+1)
        await upload.close()
        if len(data)>2*1024*1024:
            errors.append({"file":name,"error":"Transcript exceeds 2 MB"})
            continue
        path = folder/(uid()+".md")
        try:
            path.write_text(data.decode("utf-8"),encoding="utf-8")
            fm, _, _, _ = parse_transcript(path)
            # An episode gets one immutable-source file per import replacement.
            target = folder/(hashlib.sha256(fm["video_id"].encode()).hexdigest()+".md")
            path.replace(target)
            accepted += 1
        except (ValueError,UnicodeError,OSError) as exc:
            errors.append({"file":name,"error":str(exc)[:200]})
            if path.exists():
                path.unlink()
    result = index_archive(actor["workspace_id"],folder,log=lambda _:None)
    return {**result,"accepted":accepted,"errors":errors+result["errors"]}
