"""Signed, bounded delivery of research requests to a subscribed ChatGPT Work chat."""

import base64
import ctypes
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
import secrets
import socket
import ssl
import time
from ctypes import wintypes
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from .db import instant, now, uid, write

EVENT = "research.requested"


def _after(seconds):
    return instant((datetime.fromisoformat(now()) + timedelta(seconds=seconds)).isoformat())


def _protect(data, *, decrypt=False):
    """Protect the callback capability and signing keys for this Windows user."""
    if os.name != "nt":
        raise ValueError("Subscription secret storage requires Windows user protection.")

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.c_void_p)]

    memory = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(memory, ctypes.c_void_p))
    output = Blob()
    api = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not api(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ValueError("Cannot use the subscription secret under this Windows account.")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.c_void_p(output.data))


def _key(raw):
    if not isinstance(raw, str) or not raw.startswith("whsec_") or len(raw) > 100:
        raise ValueError("Invalid subscription signing key.")
    key = base64.b64decode(raw[6:], validate=True)
    if not 24 <= len(key) <= 64:
        raise ValueError("Invalid subscription signing key.")
    return key


def _destination(url):
    target = urlsplit(url)
    host = target.hostname or ""
    if (
        len(url) > 1800
        or target.scheme != "https"
        or target.port not in (443, None)
        or target.username is not None
        or target.password is not None
        or target.fragment
        or not (host in ("chatgpt.com", "openai.com") or host.endswith((".chatgpt.com", ".openai.com")))
        or not target.path.startswith("/")
        or any(ord(c) <= 32 for c in url)
    ):
        raise ValueError("A private subscription requires an official HTTPS callback.")
    return target


def _post(url, keys, sub, ident, body):
    target = _destination(url)
    host = target.hostname
    ips = [a[4][0] for a in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)]
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise ValueError("Callback did not resolve to a public service.")
    stamp = str(int(time.time()))
    raw = json.dumps(body, separators=(",", ":")).encode()
    signed = ident.encode() + b"." + stamp.encode() + b"." + raw
    signatures = ["v1," + base64.b64encode(hmac.digest(_key(k), signed, "sha256")).decode() for k in keys]
    conn = http.client.HTTPSConnection(host, timeout=8)
    try:
        with socket.create_connection((ips[0], 443), timeout=8) as network:
            conn.sock = ssl.create_default_context().wrap_socket(network, server_hostname=host)
            conn.request(
                "POST",
                target.path + ("?" + target.query if target.query else ""),
                raw,
                {
                    "Content-Type": "application/json",
                    "webhook-id": ident,
                    "webhook-timestamp": stamp,
                    "webhook-signature": " ".join(signatures),
                    "X-MCP-Subscription-Id": sub,
                },
            )
            response = conn.getresponse()
            if not 200 <= response.status < 300:
                raise ValueError("Callback declined the signed request.")
            reply = response.read(4097)
            if len(reply) > 4096:
                raise ValueError("Callback response too large.")
            return reply
    finally:
        conn.close()


def subscription(db, params, *, remove=False):
    route = params.get("delivery", {})
    if (
        params.get("name") != EVENT
        or params.get("arguments") != {}
        or not isinstance(route, dict)
        or route.get("mode") != "webhook"
    ):
        raise ValueError("Unsupported event subscription.")
    url = route.get("url", "")
    _destination(url)
    sub = "sub_" + hashlib.sha256((EVENT + url).encode()).hexdigest()[:32]
    if remove:
        with write(db):
            db.execute("DELETE FROM assistant_events WHERE sub_id=? AND state<>'accepted'", (sub,))
            db.execute(
                "UPDATE assistant_subscriptions SET expires=?,destination=x'' WHERE id=?", (now(), sub)
            )
        return {}
    secret = route.get("secret")
    _key(secret)
    ttl = params.get("ttlMs")
    if ttl is not None and (type(ttl) is not int or ttl < 1000):
        raise ValueError("Invalid subscription lifetime.")
    expires = _after(min(86400, ttl / 1000 if ttl else 86400))
    saved = db.execute(
        "SELECT * FROM assistant_subscriptions WHERE id=? AND expires>?", (sub, now())
    ).fetchone()
    previous = json.loads(_protect(saved["destination"], decrypt=True)) if saved else {}
    verified = saved["verified_at"] if saved else None
    if previous.get("key") != secret or verified < _after(-3600):
        challenge = secrets.token_urlsafe(30)
        reply = _post(url, [secret], sub, uid("verify"), {"type": "verification", "challenge": challenge})
        if not hmac.compare_digest(json.loads(reply).get("challenge", ""), challenge):
            raise ValueError("Callback challenge failed.")
        verified = now()
    stored = {"url": url, "key": secret}
    if previous and previous["key"] != secret:
        stored.update(old=previous["key"], until=_after(300))
    elif previous.get("until", "") > now():
        stored.update(old=previous["old"], until=previous["until"])
    sealed = _protect(json.dumps(stored).encode())
    with write(db):
        db.execute(
            """INSERT INTO assistant_subscriptions VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                   destination=excluded.destination,expires=excluded.expires,verified_at=excluded.verified_at""",
            (sub, sealed, expires, verified),
        )
    return {"id": sub, "refreshBefore": expires, "cursor": None, "truncated": False}


def tick(db):
    if not db.execute("SELECT 1 FROM assistant_subscriptions WHERE expires>?", (now(),)).fetchone():
        return
    stamp = now()
    from . import assistant

    with write(db):
        db.execute(
            """INSERT OR IGNORE INTO assistant_events(job_id,sub_id,state,next_at)
                   SELECT j.id,s.id,'pending',? FROM assistant_jobs j CROSS JOIN assistant_subscriptions s
                   WHERE j.state='pending' AND s.expires>?""",
            (stamp, stamp),
        )
        row = db.execute(
            """SELECT e.*,s.destination,j.case_id,j.created_at,p.label FROM assistant_events e
                   JOIN assistant_subscriptions s ON s.id=e.sub_id JOIN assistant_jobs j ON j.id=e.job_id
                   CROSS JOIN assistant_profile p WHERE p.enabled AND s.expires>? AND e.state IN ('pending','sending')
                   AND e.next_at<=? AND j.state='pending' ORDER BY e.next_at LIMIT 1""",
            (stamp, stamp),
        ).fetchone()
        if not row:
            return
        try:
            job = assistant._item(db, row["job_id"])
            assistant._current_event(db, job)
        except ValueError:
            db.execute(
                "UPDATE assistant_events SET state='retired' WHERE job_id=? AND sub_id=?",
                (row["job_id"], row["sub_id"]),
            )
            return
        db.execute(
            "UPDATE assistant_events SET state='sending',attempts=attempts+1,next_at=? WHERE job_id=? AND sub_id=?",
            (_after(60), row["job_id"], row["sub_id"]),
        )
    ident = row["job_id"]
    try:
        stored = json.loads(_protect(row["destination"], decrypt=True))
        keys = [stored["key"]]
        if stored.get("until", "") > now():
            keys.append(stored["old"])
        _post(
            stored["url"],
            keys,
            row["sub_id"],
            ident,
            {
                "eventId": ident,
                "name": EVENT,
                "timestamp": row["created_at"],
                "cursor": None,
                "data": {"job_id": ident, "case_id": row["case_id"], "label": row["label"]},
            },
        )
        state = "accepted"
    except (ValueError, OSError, http.client.HTTPException):
        state = "pending" if row["attempts"] < 7 else "failed"
    with write(db):
        db.execute(
            """UPDATE assistant_events SET state=?,accepted_at=?,next_at=?
                   WHERE job_id=? AND sub_id=? AND state='sending' AND attempts=?""",
            (
                state,
                now() if state == "accepted" else None,
                _after(min(3600, 30 * 2 ** row["attempts"])),
                ident,
                row["sub_id"],
                row["attempts"] + 1,
            ),
        )
    return ident
