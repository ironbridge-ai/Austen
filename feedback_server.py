#!/usr/bin/env python3
"""
Combined server for Austen — AI News Digest by RAMSAC.

Deployed in the ai-guild-infra fleet at https://ramsac-austen.ironbridge.tech.

- Serves static files (the published digest pages + a landing page) from
  AUSTEN_WEB_ROOT.
- POST /api/feedback  ->  appends to <AUSTEN_DATA_DIR>/feedback_log.json
- POST /api/search    ->  appends to <AUSTEN_DATA_DIR>/search_log.json
- GET  /api/trending  ->  top search terms over the last 7 days
- GET  /health        ->  200 readiness probe (the deploy health gate hits this)
- Sends one daily summary email at DIGEST_SEND_TIME covering all feedback
  received since the previous send.

Configuration — env vars, or podman secrets mounted at /run/secrets/<name>:

  REQUIRED (the server EXITS at startup if either is missing — we fail fast
  rather than run half-configured):
    smtp_user      / SMTP_USER       M365 sender, e.g. someone@ironbridgesg.com
    smtp_password  / SMTP_PASSWORD   M365 password or app password

  Optional (sane defaults):
    PORT                       listen port (default 4097; argv[1] also accepted)
    HOST                       bind address (default 0.0.0.0 — container needs this)
    AUSTEN_WEB_ROOT            static-file root (default: this script's dir)
    AUSTEN_DATA_DIR            feedback/search log dir (default: this script's dir)
    SMTP_SERVER                SMTP host (default smtp.office365.com)
    DIGEST_SEND_TIME           HH:MM 24h, default 17:00
    AUSTEN_FEEDBACK_RECIPIENT  daily-digest recipient

Local dev:
    SMTP_USER=you@ironbridgesg.com SMTP_PASSWORD=xxx python3 feedback_server.py
"""

import functools
import json
import os
import smtplib
import sys
import threading
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from http.server import SimpleHTTPRequestHandler, HTTPServer

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
WEB_ROOT     = os.environ.get("AUSTEN_WEB_ROOT", SCRIPT_DIR)
DATA_DIR     = os.environ.get("AUSTEN_DATA_DIR", SCRIPT_DIR)
FEEDBACK_LOG = os.path.join(DATA_DIR, "feedback_log.json")
SEARCH_LOG   = os.path.join(DATA_DIR, "search_log.json")
SMTP_SERVER  = os.environ.get("SMTP_SERVER", "smtp.office365.com")
SMTP_PORT    = 587
RECIPIENT    = os.environ.get("AUSTEN_FEEDBACK_RECIPIENT", "renato.velasquez@ironbridgesg.com")
STORY_LABELS = {1: "Story 1", 2: "Story 2", 3: "Story 3", 4: "Story 4", 5: "Story 5"}
SEND_TIME    = os.environ.get("DIGEST_SEND_TIME", "17:00")  # HH:MM, 24h

# Resolved once at startup in __main__ (fail-fast). Read by send_daily_digest().
SMTP_USER     = None
SMTP_PASSWORD = None


def read_secret(name, env_name=None):
    """Read a podman file-secret at /run/secrets/<name>; fall back to an env var.

    Same code path locally (env var) and in the container (mounted file)."""
    path = os.path.join("/run/secrets", name)
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    return os.environ.get(env_name or name.upper())


def require_secret(name, env_name):
    """Resolve a required secret or exit non-zero with a clear message.

    Fail-fast: a missing required secret aborts startup so the deploy's
    post-restart health gate fails (and alerts) rather than the service
    silently running without email."""
    val = read_secret(name, env_name)
    if not val:
        sys.exit(
            f"FATAL: required secret '{name}' is not set — mount it at "
            f"/run/secrets/{name} or set ${env_name}. Add austen_{name} to "
            f"ai-guild-infra deployment/secrets.enc.yaml (production tier)."
        )
    return val


def load_log():
    if os.path.exists(FEEDBACK_LOG):
        with open(FEEDBACK_LOG) as f:
            return json.load(f)
    return {"entries": []}


def load_search_log():
    if os.path.exists(SEARCH_LOG):
        with open(SEARCH_LOG) as f:
            return json.load(f)
    return {"events": []}


def save_search_log(log):
    with open(SEARCH_LOG, "w") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def get_trending(days=7, limit=12):
    log = load_search_log()
    cutoff = datetime.now().timestamp() - days * 86400
    counts = {}
    for ev in log["events"]:
        if ev.get("ts", 0) >= cutoff:
            term = ev.get("term", "").strip().lower()
            if term:
                counts[term] = counts.get(term, 0) + 1
    ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    return [{"term": t, "count": c} for t, c in ranked[:limit]]


def save_log(log):
    with open(FEEDBACK_LOG, "w") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def send_daily_digest():
    user     = SMTP_USER
    password = SMTP_PASSWORD
    if not user or not password:
        # Should not happen — require_secret() guarantees these at startup.
        print("  Daily email skipped — SMTP credentials not resolved.")
        return

    log      = load_log()
    unsent   = [e for e in log["entries"] if not e.get("emailed")]

    if not unsent:
        print(f"  [{datetime.now().strftime('%H:%M')}] No new feedback to send.")
        return

    today    = datetime.now().strftime("%Y-%m-%d")
    subject  = f"Austen Digest Feedback — {today} ({len(unsent)} response{'s' if len(unsent) != 1 else ''})"

    sections = []
    for i, entry in enumerate(unsent, 1):
        votes      = entry.get("votes", {})
        vote_lines = []
        for k in sorted(votes, key=lambda x: int(x)):
            label  = STORY_LABELS.get(int(k), f"Story {k}")
            symbol = "Thumbs up" if votes[k] == "up" else "Thumbs down"
            vote_lines.append(f"    {label}: {symbol}")
        vote_block    = "\n".join(vote_lines) if vote_lines else "    (no ratings)"
        text_feedback = entry.get("text", "").strip()
        sections.append(
            f"Response {i}  —  submitted {entry['submitted_at']}  |  digest {entry.get('digest_date', '?')}\n"
            f"  Ratings:\n{vote_block}\n"
            f"  Comment: {text_feedback or '(none)'}"
        )

    body = (
        f"Austen News Digest — Daily Feedback Summary\n"
        f"{'=' * 44}\n"
        f"Date:       {today}\n"
        f"Responses:  {len(unsent)}\n\n"
        + "\n\n".join(sections)
    )

    msg = MIMEMultipart()
    msg["From"]    = user
    msg["To"]      = RECIPIENT
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as srv:
            srv.ehlo(); srv.starttls(); srv.ehlo()
            srv.login(user, password)
            srv.send_message(msg)
        print(f"  Daily feedback email sent ({len(unsent)} response(s)) → {RECIPIENT}")
        for entry in unsent:
            entry["emailed"] = True
        save_log(log)
    except Exception as e:
        # A send failure (e.g. SMTP egress blocked) must NOT kill feedback
        # collection — log loudly and keep serving; unsent entries retry tomorrow.
        print(f"  Daily email failed: {e}")


def _daily_sender_loop():
    """Background thread: fires send_daily_digest() once per day at SEND_TIME."""
    send_h, send_m = map(int, SEND_TIME.split(":"))
    last_sent_date = None
    while True:
        now = datetime.now()
        if (now.hour, now.minute) >= (send_h, send_m) and now.date().isoformat() != last_sent_date:
            last_sent_date = now.date().isoformat()
            send_daily_digest()
        time.sleep(30)  # check every 30 seconds


class DigestHandler(SimpleHTTPRequestHandler):
    """Extends SimpleHTTPRequestHandler to intercept API + health endpoints.

    Static files are served from the `directory=` passed at construction
    (AUSTEN_WEB_ROOT) — deliberately NOT the app source dir, so the feedback
    log and the Python source are never exposed over HTTP."""

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path in ("/health", "/healthz"):
            body = b'{"ok":true}'
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/trending"):
            trending = get_trending()
            body = json.dumps({"trending": trending}).encode()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/search"):
            self._handle_search()
        elif self.path.startswith("/api/feedback"):
            self._handle_feedback()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_search(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length))
        except Exception:
            self.send_response(400)
            self.end_headers()
            return

        term = data.get("term", "").strip()
        if term:
            event = {
                "term":  term,
                "page":  data.get("page", ""),
                "ts":    datetime.now().timestamp(),
                "at":    datetime.now().isoformat(timespec="seconds"),
            }
            log = load_search_log()
            log["events"].append(event)
            save_search_log(log)
            print(f"[{event['at']}] Search: {repr(term)} on {event['page']}")

        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def _handle_feedback(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length))
        except Exception:
            self.send_response(400)
            self.end_headers()
            return

        entry = {
            "submitted_at": datetime.now().isoformat(timespec="seconds"),
            "digest_date":  data.get("digest_date", ""),
            "votes":        data.get("votes", {}),
            "text":         data.get("text", "").strip(),
            "emailed":      False,
        }

        log = load_log()
        log["entries"].append(entry)
        save_log(log)

        n_votes = len(entry["votes"])
        snippet = repr(entry["text"][:60]) if entry["text"] else "no text"
        print(f"[{entry['submitted_at']}] Feedback received — {n_votes} vote(s), {snippet}")

        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, fmt, *args):
        # Quiet logging: only echo POST request lines. Guard the type — on
        # error responses (404, etc.) BaseHTTPRequestHandler.log_error() calls
        # this with args[0] being the numeric status code, not the request
        # line, and `"POST" in <HTTPStatus>` would raise TypeError.
        msg = args[0] if args else ""
        if isinstance(msg, str) and "POST" in msg:
            print(f"  {self.address_string()} {msg}")


if __name__ == "__main__":
    # Fail-fast: required secrets must be present or we refuse to start.
    SMTP_USER     = require_secret("smtp_user", "SMTP_USER")
    SMTP_PASSWORD = require_secret("smtp_password", "SMTP_PASSWORD")

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT") or (sys.argv[1] if len(sys.argv) > 1 else 4097))

    os.makedirs(WEB_ROOT, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    print(f"Austen feedback server listening on {host}:{port}")
    print(f"  web root : {WEB_ROOT}")
    print(f"  data dir : {DATA_DIR}")
    print(f"  email    : daily summary at {SEND_TIME} → {RECIPIENT} via {SMTP_SERVER}:{SMTP_PORT}")

    sender = threading.Thread(target=_daily_sender_loop, daemon=True)
    sender.start()

    handler = functools.partial(DigestHandler, directory=WEB_ROOT)
    HTTPServer((host, port), handler).serve_forever()
