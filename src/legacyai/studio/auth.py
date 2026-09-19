"""Password authentication with expiring sessions and same-origin CSRF checks."""
import hashlib
import hmac
import os
import secrets
from urllib.parse import urlparse

from fastapi import HTTPException, Request

from .db import connect, now, uid

COOKIE = "legacy_session"


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384,
                            r=8, p=1, dklen=32).hex()
    return f"scrypt${salt}${digest}"


def check_password(password, encoded):
    try:
        _, salt, _ = encoded.split("$")
        return hmac.compare_digest(hash_password(password, salt), encoded)
    except (ValueError, TypeError):
        return False


MIN_PASSWORD = 8


def check_length(password):
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"Use a password with at least {MIN_PASSWORD} characters")


def set_password(email, password):
    """Replace an account's password and sign out its existing sessions."""
    check_length(password)
    with connect() as con:
        row = con.execute("SELECT id FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
        if not row:
            raise ValueError("This account does not exist")
        con.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(password), row[0]))
        con.execute("DELETE FROM sessions WHERE user_id=?", (row[0],))


def provision(email, password, name, workspace_name):
    check_length(password)
    email = email.strip().lower()
    if "@" not in email:
        raise ValueError("A valid email is required")
    with connect() as con:
        if con.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            raise ValueError("This account already exists")
        workspace_id, user_id = uid(), uid()
        con.execute("INSERT INTO workspaces VALUES(?,?,?)", (workspace_id, workspace_name, now()))
        con.execute("INSERT INTO users VALUES(?,?,?,?,?,?)",
                    (user_id, workspace_id, email, hash_password(password), name, now()))
    return workspace_id


def ensure_origin(request):
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.url.netloc:
        raise HTTPException(403, "This request must come from your Studio workspace")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-site requests are not allowed")


def user(request: Request):
    token = request.cookies.get(COOKIE, "")
    digest = hashlib.sha256(token.encode()).hexdigest()
    with connect() as con:
        row = con.execute("""SELECT u.id,u.email,u.name,u.workspace_id,w.name AS workspace_name,
            s.csrf FROM sessions s JOIN users u ON s.user_id=u.id
            JOIN workspaces w ON w.id=u.workspace_id
            WHERE s.token_hash=? AND s.expires>?""", (digest, now())).fetchone()
    if not row:
        raise HTTPException(401, "Sign in to your workspace")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        ensure_origin(request)
        if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), row["csrf"]):
            raise HTTPException(403, "Your session changed. Refresh and try again")
    return dict(row)


def login(request, response, email, password):
    ensure_origin(request)
    email = email.strip().lower()
    client = request.client.host if request.client else "unknown"
    key = hashlib.sha256(f"{client}:{email}".encode()).hexdigest()
    with connect() as con:
        attempt = con.execute("SELECT * FROM login_attempts WHERE key=?", (key,)).fetchone()
        if attempt and attempt["reset_at"] > now() and attempt["attempts"] >= 10:
            raise HTTPException(429, "Too many attempts. Try again in 15 minutes")
        row = con.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        # A dummy hash keeps unknown-account verification on the same expensive path.
        valid = check_password(password, row["password_hash"] if row else DUMMY_HASH)
        if not row or not valid:
            count = attempt["attempts"] + 1 if attempt and attempt["reset_at"] > now() else 1
            con.execute("INSERT OR REPLACE INTO login_attempts VALUES(?,?,?)", (key, count, now()+900))
            con.commit()
            raise HTTPException(401, "Email or password is incorrect")
        con.execute("DELETE FROM login_attempts WHERE key=?", (key,))
        con.execute("DELETE FROM sessions WHERE expires<?", (now(),))
        old = request.cookies.get(COOKIE, "")
        con.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(old.encode()).hexdigest(),))
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        con.execute("INSERT INTO sessions VALUES(?,?,?,?)",
                    (hashlib.sha256(token.encode()).hexdigest(), row["id"], csrf, now()+43200))
    response.set_cookie(COOKIE, token, max_age=43200, httponly=True, samesite="strict",
                        secure=os.environ.get("LEGACY_ENV") == "production")
    return {"ok": True}


DUMMY_HASH = hash_password("not-a-real-account-password")
