#!/usr/bin/env python3
"""
Combined server for Austen — AI News Digest by RAMSAC.
- Serves static files from this directory (replaces python3 -m http.server)
- Accepts POST /api/feedback  →  appends to feedback_log.json
- Sends one daily summary email at DIGEST_SEND_TIME (default 17:00) covering
  all feedback received since the previous send.

Required env vars for email:
  SMTP_USER         your M365 address  e.g. renato.velasquez@ironbridgesg.com
  SMTP_PASSWORD     your M365 password or app password
  DIGEST_SEND_TIME  HH:MM in 24h format to send the daily email (default 17:00)

Optional:
  PORT   port to listen on (default 4097)
  HOST   address to bind (default 0.0.0.0; set 127.0.0.1 for loopback-only)

Usage:
  SMTP_USER=you@ironbridgesg.com SMTP_PASSWORD=xxx python3 feedback_server.py
"""

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
FEEDBACK_LOG = os.path.join(SCRIPT_DIR, "feedback_log.json")
SEARCH_LOG   = os.path.join(SCRIPT_DIR, "search_log.json")
SMTP_SERVER  = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT    = 587
RECIPIENT    = "renato.velasquez@ironbridgesg.com"
STORY_LABELS = {1: "Story 1", 2: "Story 2", 3: "Story 3", 4: "Story 4", 5: "Story 5"}
SEND_TIME    = os.environ.get("DIGEST_SEND_TIME", "17:00")  # HH:MM, 24h


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
    user     = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    if not user or not password:
        print("  Daily email skipped — set SMTP_USER and SMTP_PASSWORD to enable.")
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
    """Extends SimpleHTTPRequestHandler to intercept API endpoints."""

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/healthz"):
            body = b'{"status":"ok"}'
            self.send_response(200)
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
        if "POST" in (args[0] if args else ""):
            print(f"  {self.address_string()} {args[0] if args else ''}")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", 4097))
    host = os.environ.get("HOST", "0.0.0.0")
    os.chdir(SCRIPT_DIR)  # serve files from the digest directory
    smtp_ready = bool(os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASSWORD"))
    print(f"Digest server listening on {host}:{port}")
    print(f"Email: {'daily summary at ' + SEND_TIME + ' → ' + RECIPIENT if smtp_ready else 'NOT configured (set SMTP_USER + SMTP_PASSWORD)'}")

    sender = threading.Thread(target=_daily_sender_loop, daemon=True)
    sender.start()

    HTTPServer((host, port), DigestHandler).serve_forever()
