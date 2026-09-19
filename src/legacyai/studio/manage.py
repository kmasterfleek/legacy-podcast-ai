"""One entry point for local demos, provisioning, indexing, serving, and workers."""
import argparse
import getpass
import os
from pathlib import Path

from legacyai.search.index import index_archive
from .auth import provision
from .db import connect, initialize


def main():
    parser = argparse.ArgumentParser(prog="legacy-studio")
    sub = parser.add_subparsers(dest="command",required=True)
    for command in ("serve","demo"):
        p = sub.add_parser(command)
        p.add_argument("--host",default="127.0.0.1")
        p.add_argument("--port",type=int,default=int(os.environ.get("PORT","8000")))
        if command=="demo":
            p.add_argument("--archive",default="transcripts")
    p = sub.add_parser("provision")
    p.add_argument("--email",required=True)
    p.add_argument("--name",required=True)
    p.add_argument("--workspace",required=True)
    p = sub.add_parser("index")
    p.add_argument("--workspace",required=True,help="Workspace ID printed by provision")
    p.add_argument("--archive",default="transcripts")
    p = sub.add_parser("worker")
    p.add_argument("--once",action="store_true")
    sub.add_parser("accounts")
    args = parser.parse_args()
    initialize()
    if args.command=="provision":
        password = os.environ.get("LEGACY_ADMIN_PASSWORD") or getpass.getpass("Password (12+ characters): ")
        workspace_id = provision(args.email,password,args.name,args.workspace)
        print(f"Created workspace {workspace_id}; account {args.email}")
    elif args.command=="accounts":
        with connect() as con:
            for row in con.execute("SELECT u.email,w.id,w.name FROM users u JOIN workspaces w ON w.id=u.workspace_id"):
                print(f"{row['email']}  {row['id']}  {row['name']}")
    elif args.command=="index":
        with connect() as con:
            if not con.execute("SELECT id FROM workspaces WHERE id=?",(args.workspace,)).fetchone():
                parser.error("Workspace does not exist; provision an account first")
        index_archive(args.workspace,args.archive)
    elif args.command=="worker":
        from .jobs import run_worker
        run_worker(once=args.once)
    else:
        if args.command=="demo":
            if os.environ.get("LEGACY_ENV")=="production":
                parser.error("Demo mode cannot run in production")
            os.environ["LEGACY_DEMO"] = "1"
            os.environ["LEGACY_EMBEDDED_WORKER"] = "1"
            with connect() as con:
                existing = con.execute("SELECT workspace_id FROM users WHERE email='demo@legacy.local'").fetchone()
            workspace_id = existing[0] if existing else provision(
                "demo@legacy.local","legacy-local-demo","Studio demo","All The Smoke")
            index_archive(workspace_id,args.archive)
        import uvicorn
        uvicorn.run("legacyai.studio.app:create_app",factory=True,host=args.host,port=args.port,
                    proxy_headers=False)


if __name__=="__main__":
    main()
