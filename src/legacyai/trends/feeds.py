"""Bounded public RSS/Atom fetching, including redirect validation."""
import hashlib
import ipaddress
import socket
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

from legacyai.studio.db import now, uid


def public_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use a public HTTP or HTTPS URL")
    if parsed.port not in {None,80,443}:
        raise ValueError("Only standard web ports are supported")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except OSError:
        raise ValueError("This source hostname could not be resolved")
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("Private network sources are not supported")
    return url


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_feed(url):
    req = urllib.request.Request(public_url(url), headers={"User-Agent": "LegacyStudio/0.3"})
    opener = urllib.request.build_opener(PublicRedirect())
    with opener.open(req, timeout=20) as response:
        data = response.read(2*1024*1024+1)
    if len(data)>2*1024*1024:
        raise ValueError("Feed exceeds the 2 MB limit")
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("Feed contains unsupported XML declarations")
    root = ET.fromstring(data)
    entries = root.findall("./channel/item") or root.findall("{http://www.w3.org/2005/Atom}entry")
    if root.tag not in {"rss", "{http://www.w3.org/2005/Atom}feed"}:
        raise ValueError("This URL does not contain an RSS or Atom feed")
    out = []
    for entry in entries[:50]:
        title = entry.findtext("title") or entry.findtext("{http://www.w3.org/2005/Atom}title") or ""
        link = entry.findtext("link") or ""
        if not link:
            node = entry.find("{http://www.w3.org/2005/Atom}link")
            link = node.get("href", "") if node is not None else ""
        if title.strip() and urlparse(link).scheme in {"http", "https"}:
            out.append({"title": title.strip()[:500], "url": link[:2000]})
    return out


def save_opportunity(con, workspace_id, title, url="", source_id=None):
    fingerprint = hashlib.sha256((url or title.strip().lower()).encode()).hexdigest()
    record_id = uid()
    con.execute("""INSERT OR IGNORE INTO opportunities
        (id,workspace_id,title,source_url,source_id,fingerprint,created) VALUES(?,?,?,?,?,?,?)""",
        (record_id, workspace_id, title, url, source_id, fingerprint, now()))
    return dict(con.execute("SELECT * FROM opportunities WHERE workspace_id=? AND fingerprint=?",
                            (workspace_id,fingerprint)).fetchone())
