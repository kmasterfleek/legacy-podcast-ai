"""A durable worker: render jobs, feed synchronization, and optional webhook delivery."""
import hashlib
import hmac
import json
import os
import time
import urllib.request
from urllib.parse import urlparse

from legacyai.clips.render import render_clip
from legacyai.clips.acquire import fetch_video
from legacyai.trends.feeds import fetch_feed, save_opportunity
from .db import connect, get_record, now, uid


def enqueue(con, workspace_id, kind, payload):
    record_id = uid()
    con.execute("INSERT INTO jobs(id,workspace_id,kind,payload,created,updated) VALUES(?,?,?,?,?,?)",
                (record_id,workspace_id,kind,json.dumps(payload),now(),now()))
    return record_id


def claim():
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        # A worker interrupted during a render can safely render that revision again.
        con.execute("""UPDATE jobs SET state='queued' WHERE state='running'
            AND lease_until<? AND kind!='publish' AND attempts<3""", (now(),))
        expired = con.execute("SELECT * FROM jobs WHERE state='running' AND lease_until<?", (now(),)).fetchall()
        for job in expired:
            con.execute("UPDATE jobs SET state='failed',error=?,updated=? WHERE id=?",
                        ("Worker stopped; check the result before retrying",now(),job["id"]))
            payload = json.loads(job["payload"])
            if job["kind"]=="render":
                con.execute("UPDATE clips SET status='draft',error=? WHERE id=? AND revision=?",
                            ("Render interrupted. Retry rendering",payload["clip_id"],payload["revision"]))
            if job["kind"]=="publish":
                con.execute("UPDATE deliveries SET status='uncertain' WHERE clip_id=? AND revision=?",
                            (payload["clip_id"],payload["revision"]))
        job = con.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created,id LIMIT 1").fetchone()
        if job:
            con.execute("UPDATE jobs SET state='running',attempts=attempts+1,lease_until=?,updated=? WHERE id=?",
                        (now()+2100,now(),job["id"]))
            return dict(job)


def export_token(clip_id, revision, expires):
    secret = os.environ.get("LEGACY_SIGNING_KEY", "")
    if not secret:
        raise ValueError("Set LEGACY_SIGNING_KEY before enabling publisher delivery")
    return hmac.new(secret.encode(), f"{clip_id}:{revision}:{expires}".encode(), hashlib.sha256).hexdigest()


def publisher_ready():
    return bool(os.environ.get("LEGACY_PUBLISH_WEBHOOK") and os.environ.get("LEGACY_PUBLIC_URL")
                and os.environ.get("LEGACY_SIGNING_KEY"))


def publish(clip):
    if not publisher_ready():
        raise ValueError("Connect a publisher webhook before sending clips")
    if os.environ.get("LEGACY_PUBLISH_WORKSPACE") != clip["workspace_id"]:
        raise ValueError("Publisher is not configured for this workspace")
    url = os.environ["LEGACY_PUBLISH_WEBHOOK"]
    if urlparse(url).scheme != "https":
        raise ValueError("Publisher webhooks require HTTPS")
    expires = now()+3600
    token = export_token(clip["id"],clip["revision"],expires)
    asset_url = (os.environ["LEGACY_PUBLIC_URL"].rstrip("/")+f"/delivery/{clip['id']}"
                 f"?revision={clip['revision']}&expires={expires}&token={token}")
    key = f"{clip['id']}:{clip['revision']}"
    payload = {"event": "clip.approved", "idempotency_key": key, "clip_id": clip["id"],
               "revision": clip["revision"], "title": clip["title"], "caption": clip["caption"],
               "format": clip["format"], "video_url": asset_url, "expires": expires}
    body = json.dumps(payload).encode()
    signature = hmac.new(os.environ["LEGACY_SIGNING_KEY"].encode(), body, hashlib.sha256).hexdigest()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type":"application/json", "Idempotency-Key":key, "X-Legacy-Signature":signature})
    # No automatic retry: a timeout may follow a successful external publication.
    with urllib.request.urlopen(req, timeout=30) as response:
        response.read(4096)
        return f"HTTP {response.status}: accepted by connected publisher"


def run_job(job):
    payload = json.loads(job["payload"])
    workspace = job["workspace_id"]
    try:
        if job["kind"] in {"render", "publish"}:
            with connect() as con:
                clip = get_record(con,"clips",payload["clip_id"],workspace)
                if not clip or clip["revision"] != payload["revision"]:
                    raise ValueError("The clip changed; this job is obsolete")
                clip = dict(clip)
                asset = get_record(con,"assets",clip["asset_id"],workspace) if clip["asset_id"] else None
                asset = dict(asset) if asset else None
            if job["kind"]=="render":
                if not asset or not clip["alignment_confirmed"]:
                    raise ValueError("Register aligned source media before rendering")
                path = render_clip(clip,asset)
                with connect() as con:
                    con.execute("""UPDATE clips SET result_path=?,render_revision=?,status='ready',
                        error='',updated=? WHERE id=? AND workspace_id=? AND revision=?""",
                        (path,clip["revision"],now(),clip["id"],workspace,clip["revision"]))
            else:
                if clip["approved_revision"] != clip["revision"] or clip["render_revision"] != clip["revision"]:
                    raise ValueError("This revision must be rendered and approved before delivery")
                receipt = publish(clip)
                with connect() as con:
                    con.execute("UPDATE deliveries SET status='delivered',receipt=? WHERE clip_id=? AND revision=?",
                                (receipt,clip["id"],clip["revision"]))
        elif job["kind"]=="fetch_media":
            with connect() as con:
                episode = get_record(con,"episodes",payload["episode_id"],workspace)
                if not episode:
                    raise ValueError("Episode is no longer available")
                episode = dict(episode)
            asset = fetch_video(episode)
            with connect() as con:
                con.execute("INSERT INTO assets VALUES(?,?,?,?,?,?,?)",
                    (asset["id"],workspace,episode["id"],asset["name"],asset["path"],asset["duration"],now()))
        elif job["kind"]=="feed":
            with connect() as con:
                source = get_record(con,"sources",payload["source_id"],workspace)
                if not source or not source["enabled"]:
                    raise ValueError("Source is no longer enabled")
                source = dict(source)
            entries = fetch_feed(source["url"])
            with connect() as con:
                for entry in entries:
                    save_opportunity(con,workspace,entry["title"],entry["url"],source["id"])
                con.execute("UPDATE sources SET last_checked=?,last_error='' WHERE id=?", (now(),source["id"]))
        else:
            raise ValueError("Unknown job type")
        with connect() as con:
            con.execute("UPDATE jobs SET state='done',updated=? WHERE id=?", (now(),job["id"]))
    except Exception as exc:
        # Do not expose remote response bodies, filesystem paths, or secrets to clients.
        message = str(exc)[:300] if isinstance(exc,ValueError) else f"{type(exc).__name__}: operation failed"
        with connect() as con:
            con.execute("UPDATE jobs SET state='failed',error=?,updated=? WHERE id=?", (message,now(),job["id"]))
            if job["kind"]=="render":
                con.execute("UPDATE clips SET status='draft',error=?,updated=? WHERE id=? AND revision=?",
                            (message,now(),payload["clip_id"],payload["revision"]))
            elif job["kind"]=="feed":
                con.execute("UPDATE sources SET last_checked=?,last_error=? WHERE id=?",
                            (now(),message,payload["source_id"]))
            elif job["kind"]=="publish":
                con.execute("UPDATE deliveries SET status='uncertain',receipt=? WHERE clip_id=? AND revision=?",
                            (message,payload["clip_id"],payload["revision"]))


def schedule_feeds():
    with connect() as con:
        for source in con.execute("SELECT * FROM sources WHERE enabled=1 AND last_checked<?", (now()-900,)):
            pending = con.execute("""SELECT id FROM jobs WHERE workspace_id=? AND kind='feed'
                AND state IN ('queued','running') AND json_extract(payload,'$.source_id')=?""",
                (source["workspace_id"],source["id"])).fetchone()
            if not pending:
                enqueue(con,source["workspace_id"],"feed",{"source_id":source["id"]})


def run_worker(stop=None, once=False):
    while not stop or not stop.is_set():
        schedule_feeds()
        job = claim()
        if job:
            run_job(job)
        if once:
            return bool(job)
        if not job:
            if stop:
                stop.wait(2)
            else:
                time.sleep(2)
