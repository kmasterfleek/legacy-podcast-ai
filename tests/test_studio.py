"""Offline integration checks for real data boundaries and clip lifecycle behavior."""
import io
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from legacyai.search.index import index_archive
from legacyai.studio.app import create_app
from legacyai.studio.auth import provision
from legacyai.studio.db import connect, initialize, now
from legacyai.studio.jobs import claim, run_job, enqueue

FIXTURE = '''---
title: "Kevin Garnett on leadership"
show: "Test podcast"
video_id: "abcdefghijk"
url: "https://www.youtube.com/watch?v=abcdefghijk"
upload_date: "2020-01-02"
duration: "00:01:30"
word_count: 100
transcript_source: "Test fixture"
---
# Fixture
##### `00:00:00`
Promo code SPORTSBOOK. New customers get free bets.
##### `00:00:30`
**Speaker 1:** Leadership means showing up for your teammates. Kevin Garnett helped our team.
##### `00:01:00`
**Speaker 2:** That leader gave us confidence. We came back from injury and learned to trust one another.
'''


@pytest.fixture
def studio(tmp_path,monkeypatch):
    monkeypatch.setenv("LEGACY_STUDIO_DATA",str(tmp_path/"data"))
    monkeypatch.delenv("LEGACY_ENV",raising=False)
    monkeypatch.delenv("LEGACY_DEMO",raising=False)
    monkeypatch.delenv("LEGACY_EMBEDDED_WORKER",raising=False)
    monkeypatch.delenv("LEGACY_PUBLISH_WEBHOOK",raising=False)
    initialize()
    first=provision("a@example.com","test-password-123","Alice","First studio")
    second=provision("b@example.com","test-password-456","Bob","Second studio")
    folder=tmp_path/"archive";folder.mkdir()
    (folder/"episode.md").write_text(FIXTURE)
    assert index_archive(first,folder,log=lambda _:None)["indexed"]==1
    with TestClient(create_app()) as client:
        assert client.post("/api/login",json={"email":"a@example.com","password":"test-password-123"}).status_code==200
        client.headers["x-csrf-token"]=client.get("/api/me").json()["csrf"]
        yield client,first,second,folder


def make_clip(client):
    results=client.get("/api/search",params={"q":"leadership"}).json()["results"]
    assert results and not any("Promo code" in p["text"] for p in results)
    response=client.post("/api/clips",json={"passage_id":results[0]["id"]})
    assert response.status_code==200,response.text
    return response.json()


def test_auth_csrf_and_origin(studio):
    client,*_=studio
    token=client.headers.pop("x-csrf-token")
    assert client.post("/api/opportunities",json={"title":"Retirement"}).status_code==403
    client.headers["x-csrf-token"]=token
    assert client.post("/api/opportunities",json={"title":"Retirement"},headers={"Origin":"https://evil.example"}).status_code==403
    assert client.post("/api/opportunities",json={"title":"Retirement"}).status_code==200
    assert client.post("/api/logout").status_code==200
    assert client.get("/api/clips").status_code==401
    assert client.get("/api/media/missing").status_code==401
    assert client.post("/api/demo").status_code==404


def test_workspace_isolation(studio):
    client,first,second,_=studio
    clip=make_clip(client)
    assert client.get("/api/stats").json()["episodes"]==1
    client.post("/api/logout")
    client.post("/api/login",json={"email":"b@example.com","password":"test-password-456"})
    client.headers["x-csrf-token"]=client.get("/api/me").json()["csrf"]
    assert client.get("/api/stats").json()["episodes"]==0
    assert client.get("/api/search?q=leadership").json()["results"]==[]
    assert client.get("/api/clips").json()==[]
    for suffix in ("","/export","/video"):
        assert client.get(f"/api/clips/{clip['id']}"+suffix).status_code==404
    for action in ("approve","render"):
        assert client.post(f"/api/clips/{clip['id']}/{action}").status_code==404
    assert client.get("/api/episodes/abcdefghijk").status_code==404
    assert client.post("/api/clips",json={"passage_id":clip["passage_id"]}).status_code==404
    assert client.post("/api/episodes/abcdefghijk/fetch-video").status_code==404


def test_index_idempotence_aliases_and_provenance(studio):
    client,first,_,folder=studio
    assert index_archive(first,folder,log=lambda _:None)["unchanged"]==1
    assert client.get("/api/search?q=KG").json()["results"]
    assert client.get('/api/search',params={"q":'" OR * DROP TABLE clips; --'}).status_code==200
    assert client.get('/api/search',params={"q":"a "*501}).status_code==422
    clip=make_clip(client)
    (folder/"episode.md").write_text(FIXTURE.replace("showing up","working hard"))
    index_archive(first,folder,log=lambda _:None)
    after=client.get(f"/api/clips/{clip['id']}").json()
    assert "showing up" in after["transcript_text"]
    assert after["transcript_hash"]==clip["transcript_hash"]


def test_editorial_export_and_approval_gates(studio):
    client,*_=studio
    clip=make_clip(client)
    assert client.post(f"/api/clips/{clip['id']}/render").status_code==422
    assert client.post(f"/api/clips/{clip['id']}/approve").status_code==422
    assert client.post(f"/api/clips/{clip['id']}/publish").status_code==422
    package=zipfile.ZipFile(io.BytesIO(client.get(f"/api/clips/{clip['id']}/export").content))
    assert "clip.mp4" not in package.namelist()
    assert "Editorial package only" in package.read("README.txt").decode()
    decision=json.loads(package.read("edit-decision.json"))
    assert decision["timing"]=="Approximate paragraph boundaries"
    assert not decision["approved"]
    assert "result_path" not in clip


def test_optimistic_edit_rejects_stale_tabs(studio):
    client,*_=studio
    clip=make_clip(client)
    data={"title":"New title","caption":"Post caption","start":30,"end":60,"format":"1:1","revision":1}
    result=client.patch(f"/api/clips/{clip['id']}",json=data)
    assert result.status_code==200
    assert result.json()["revision"]==2
    assert client.patch(f"/api/clips/{clip['id']}",json=data).status_code==409
    data.update(revision=2,end=200)
    assert client.patch(f"/api/clips/{clip['id']}",json=data).status_code==422


def test_import_validates_and_replaces_same_episode(studio):
    client,*_=studio
    bad=client.post("/api/archive/import",files=[("files",("bad.md",b"bad content","text/markdown"))]).json()
    assert bad["accepted"]==0 and bad["errors"]
    for word in ("first replacement","second replacement"):
        updated=FIXTURE.replace("showing up",word)
        response=client.post("/api/archive/import",files=[("files",("episode.md",updated.encode(),"text/markdown"))])
        assert response.status_code==200,response.text
        assert response.json()["accepted"]==1
    assert client.get("/api/stats").json()["episodes"]==1
    assert "second replacement" in client.get("/api/search?q=leadership").json()["results"][0]["text"]


def test_feed_worker_deduplicates_and_isolates(studio,monkeypatch):
    client,first,second,_=studio
    monkeypatch.setattr("legacyai.studio.workflow_api.public_url",lambda u:u)
    monkeypatch.setattr("legacyai.studio.jobs.fetch_feed",lambda u:[{"title":"Kevin Garnett leadership","url":"https://example.com/story"}]*2)
    source=client.post("/api/sources",json={"name":"Test feed","url":"https://example.com/rss"}).json()
    job=claim();assert job["kind"]=="feed";run_job(job)
    rows=client.get("/api/opportunities").json()
    assert len(rows)==1 and rows[0]["source_id"]==source["id"]
    client.post(f"/api/sources/{source['id']}/sync")
    run_job(claim())
    assert len(client.get("/api/opportunities").json())==1
    with connect() as con:
        assert not con.execute("SELECT id FROM opportunities WHERE workspace_id=?",(second,)).fetchall()


def test_feed_rejects_private_urls(studio):
    client,*_=studio
    for url in ("http://127.0.0.1/rss","file:///etc/passwd","http://[::1]/feed"):
        assert client.post("/api/sources",json={"name":"Private","url":url}).status_code==422


@pytest.mark.skipif(not shutil.which("ffmpeg"),reason="FFmpeg is required for render integration")
def test_real_video_render_revision_and_export(studio,tmp_path):
    client,*_=studio
    video=tmp_path/"sample.mp4"
    subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i","color=c=blue:s=320x180:r=24:d=4",
                    "-f","lavfi","-i","sine=frequency=440:duration=4","-c:v","libx264","-c:a","aac",
                    "-shortest",str(video)],check=True,capture_output=True)
    clip=make_clip(client)
    upload=client.post("/api/episodes/abcdefghijk/media",files={"file":("sample.mp4",video.read_bytes(),"video/mp4")})
    assert upload.status_code==200,upload.text
    asset=upload.json()
    data={"title":"Leadership cut","caption":"A lesson in leadership","start":.5,"end":2.5,
          "format":"9:16","asset_id":asset["id"],"alignment_confirmed":True,"revision":1}
    edited=client.patch(f"/api/clips/{clip['id']}",json=data)
    assert edited.status_code==200,edited.text
    job_response=client.post(f"/api/clips/{clip['id']}/render")
    assert job_response.status_code==200
    assert client.patch(f"/api/clips/{clip['id']}",json={**data,"revision":2}).status_code==409
    run_job(claim())
    rendered=client.get(f"/api/clips/{clip['id']}").json()
    assert rendered["status"]=="ready",rendered
    assert rendered["has_render"]
    assert client.get(f"/api/clips/{clip['id']}/video").headers["content-type"]=="video/mp4"
    assert client.post(f"/api/clips/{clip['id']}/approve").status_code==200
    assert client.get(f"/api/clips/{clip['id']}").json()["approved"]
    package=zipfile.ZipFile(io.BytesIO(client.get(f"/api/clips/{clip['id']}/export").content))
    assert "clip.mp4" in package.namelist()
    # A caption edit invalidates the old approval and render, preventing stale delivery.
    data.update(revision=2,caption="Changed caption")
    edited=client.patch(f"/api/clips/{clip['id']}",json=data).json()
    assert not edited["approved"] and not edited["has_render"]
    assert client.get(f"/api/clips/{clip['id']}/video").status_code==404


def test_production_cannot_enable_demo(monkeypatch):
    monkeypatch.setenv("LEGACY_ENV","production")
    monkeypatch.setenv("LEGACY_DEMO","1")
    with pytest.raises(RuntimeError,match="Demo sign-in"):
        create_app()


def test_youtube_preview_headers_and_updated_watch_link(studio):
    client,*_=studio
    response=client.get("/")
    assert response.headers["Referrer-Policy"]=="strict-origin-when-cross-origin"
    policy=response.headers["Content-Security-Policy"]
    assert "script-src 'self' https://www.youtube.com https://s.ytimg.com;" in policy
    assert "frame-src https://www.youtube-nocookie.com;" in policy
    assert "https://i.ytimg.com" in policy
    assert "frame-ancestors 'none'" in policy
    assert client.get("/static/youtube.js").status_code==200
    clip=make_clip(client)
    response=client.patch(f"/api/clips/{clip['id']}",json={
        "title":"Updated selection","caption":"", "start":35,"end":75,"revision":1})
    assert response.status_code==200
    assert response.json()["source_link"]=="https://www.youtube.com/watch?v=abcdefghijk&t=35s"
    assert client.get(f"/api/clips/{clip['id']}").json()["source_link"].endswith("t=35s")
