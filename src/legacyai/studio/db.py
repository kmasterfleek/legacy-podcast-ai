"""Durable workspace data and a derived, workspace-scoped FTS5 index."""
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


def storage_root():
    return Path(os.environ.get("LEGACY_STUDIO_DATA", ".legacy-studio")).resolve()


def uid():
    return uuid.uuid4().hex


def now():
    return int(time.time())


@contextmanager
def connect():
    root = storage_root()
    root.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(root / "studio.sqlite3", timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
 email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, name TEXT NOT NULL,
 created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
 csrf TEXT NOT NULL, expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts (
 key TEXT PRIMARY KEY, attempts INTEGER NOT NULL, reset_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS episodes (
 id TEXT NOT NULL, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
 title TEXT NOT NULL, show_name TEXT NOT NULL, published TEXT NOT NULL,
 duration REAL NOT NULL, word_count INTEGER NOT NULL, source_url TEXT NOT NULL,
 source_kind TEXT NOT NULL, speaker_labels INTEGER NOT NULL, filename TEXT NOT NULL,
 content_hash TEXT NOT NULL, paragraph_count INTEGER NOT NULL,
 PRIMARY KEY(workspace_id,id));
CREATE TABLE IF NOT EXISTS passages (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, episode_id TEXT NOT NULL,
 ordinal INTEGER NOT NULL, start REAL NOT NULL, end REAL NOT NULL,
 text TEXT NOT NULL, speaker TEXT NOT NULL, title TEXT NOT NULL, is_ad INTEGER NOT NULL,
 FOREIGN KEY(workspace_id,episode_id) REFERENCES episodes(workspace_id,id));
CREATE INDEX IF NOT EXISTS passages_episode ON passages(workspace_id,episode_id,ordinal);
CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(
 text, title, content='passages', content_rowid='rowid', tokenize='porter unicode61');
CREATE TRIGGER IF NOT EXISTS passages_ai AFTER INSERT ON passages BEGIN
 INSERT INTO passages_fts(rowid,text,title) VALUES(new.rowid,new.text,new.title); END;
CREATE TRIGGER IF NOT EXISTS passages_ad AFTER DELETE ON passages BEGIN
 INSERT INTO passages_fts(passages_fts,rowid,text,title)
 VALUES('delete',old.rowid,old.text,old.title); END;
CREATE TABLE IF NOT EXISTS opportunities (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
 title TEXT NOT NULL, source_url TEXT NOT NULL DEFAULT '',
 source_id TEXT, fingerprint TEXT NOT NULL, created INTEGER NOT NULL,
 UNIQUE(workspace_id,fingerprint));
CREATE TABLE IF NOT EXISTS assets (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, episode_id TEXT NOT NULL,
 name TEXT NOT NULL, path TEXT NOT NULL, duration REAL NOT NULL,
 created INTEGER NOT NULL,
 FOREIGN KEY(workspace_id,episode_id) REFERENCES episodes(workspace_id,id));
CREATE TABLE IF NOT EXISTS clips (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, episode_id TEXT NOT NULL,
 passage_id TEXT NOT NULL, title TEXT NOT NULL, caption TEXT NOT NULL,
 transcript_text TEXT NOT NULL, transcript_hash TEXT NOT NULL,
 start REAL NOT NULL, end REAL NOT NULL, format TEXT NOT NULL DEFAULT '9:16',
 status TEXT NOT NULL DEFAULT 'draft', asset_id TEXT REFERENCES assets(id),
 alignment_confirmed INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 1,
 approved_revision INTEGER, render_revision INTEGER, result_path TEXT,
 error TEXT NOT NULL DEFAULT '', created INTEGER NOT NULL, updated INTEGER NOT NULL,
 FOREIGN KEY(workspace_id,episode_id) REFERENCES episodes(workspace_id,id));
CREATE INDEX IF NOT EXISTS clips_workspace ON clips(workspace_id,updated);
CREATE TABLE IF NOT EXISTS sources (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
 name TEXT NOT NULL, url TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
 last_checked INTEGER NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '',
 UNIQUE(workspace_id,url));
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
 kind TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued',
 attempts INTEGER NOT NULL DEFAULT 0, lease_until INTEGER NOT NULL DEFAULT 0,
 error TEXT NOT NULL DEFAULT '', created INTEGER NOT NULL, updated INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS jobs_claim ON jobs(state,created);
CREATE TABLE IF NOT EXISTS deliveries (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, clip_id TEXT NOT NULL,
 revision INTEGER NOT NULL, status TEXT NOT NULL, receipt TEXT NOT NULL DEFAULT '',
 created INTEGER NOT NULL, UNIQUE(clip_id,revision));
PRAGMA user_version=1;
"""


def initialize():
    with connect() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(SCHEMA)


def get_record(con, table, record_id, workspace_id):
    # Only internal callers supply table; identifiers never come from HTTP input.
    if table not in {"episodes", "passages", "clips", "assets", "sources", "jobs"}:
        raise ValueError("Unknown record type")
    return con.execute(f"SELECT * FROM {table} WHERE id=? AND workspace_id=?",
                       (record_id, workspace_id)).fetchone()
