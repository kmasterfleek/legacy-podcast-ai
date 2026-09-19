"""Claude search step: selection, ordering, and keyword fallback. No network."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from legacyai.search import rerank
from legacyai.search.index import index_archive
from legacyai.search.retrieve import search
from legacyai.studio.auth import provision
from legacyai.studio.db import connect, initialize
from test_studio import FIXTURE


@pytest.fixture
def workspace(tmp_path,monkeypatch):
    monkeypatch.setenv("LEGACY_STUDIO_DATA",str(tmp_path/"data"))
    monkeypatch.setenv("ANTHROPIC_API_KEY","test-key-never-sent")
    archive=tmp_path/"archive";archive.mkdir();(archive/"one.md").write_text(FIXTURE)
    initialize()
    workspace_id=provision("a@example.com","test-password-123","Alice","Studio")
    index_archive(workspace_id,archive,log=lambda *_:None)
    return workspace_id


def test_model_is_pinned_to_haiku():
    assert rerank.MODEL=="claude-haiku-4-5"


def test_claude_picks_reorder_results_and_supply_reasons(workspace,monkeypatch):
    calls=[]
    def fake(system,content,schema,max_tokens):
        calls.append(content)
        if schema is rerank.PLAN_SCHEMA:
            return {"keywords":["Garnett","leadership","injury"],"related":["KG","leader"],"angle":"Garnett leading a team"}
        assert "Test podcast" in system and "[1]" in content
        last=content.count("\n[")+content.startswith("[") or 1
        return {"picks":[{"n":last,"reason":"A teammate credits the leader for their confidence."},{"n":99,"reason":"out of range"}]}
    monkeypatch.setattr(rerank,"ask",fake)
    with connect() as con:
        keyword=search.__globals__["keyword_search"](con,workspace,["garnett","leadership","injury"],["kg","leader"],40,"",False)["results"]
        data=search(con,workspace,"Kevin Garnett leadership after an injury comeback")
    assert len(calls)==2
    assert data["engine"]=="Keyword search, read by Claude"
    assert [r["id"] for r in data["results"]]==[keyword[-1]["id"]]
    assert data["results"][0]["reason"].startswith("A teammate credits")


def test_short_queries_skip_planning_and_failures_keep_keyword_results(workspace,monkeypatch):
    calls=[]
    monkeypatch.setattr(rerank,"ask",lambda *a:calls.append(a) or None)
    with connect() as con:
        data=search(con,workspace,"Garnett")
    assert len(calls)==1
    assert data["engine"]=="Keyword + aliases" and data["results"]
    assert data["results"][0]["reason"].startswith("Mentions")
