#!/usr/bin/env python3
"""
Combined server for Austen — AI News Digest by RAMSAC.
- Serves static files from this directory (replaces python3 -m http.server)
- Accepts POST /api/feedback  →  appends to feedback_log.json + emails a summary

Required env vars for email:
  SMTP_USER      your M365 address  e.g. renato.velasquez@ironbridgesg.com
  SMTP_PASSWORD  your M365 password or app password

Usage:
  SMTP_USER=you@ironbridgesg.com SMTP_PASSWORD=xxx python3 feedback_server.py
"""

import json
import os
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from http.server import SimpleHTTPRequestHandler, HTTPServer

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
FEEDBACK_LOG = os.path.join(SCRIPT_DIR, "feedback_log.json")
SMTP_SERVER  = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT    = 587
RECIPIENT    = "renato.velasquez@ironbridgesg.com"
STORY_LABELS = {1: "Story 1", 2: "Story 2", 3: "Story 3", 4: "Story 4", 5: "Story 5"}


def load_log():
    if os.path.exists(FEEDBACK_LOG):
        with open(FEEDBACK_LOG) as f:
            return json.load(f)
    return {"entries": []}


def save_log(log):
    with open(FEEDBACK_LOG, "w") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def send_email(entry):
    user     = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    if not user or not password:
        print("  Email skipped — set SMTP_USER and SMTP_PASSWORD to enable.")
        return

    digest_date   = entry.get("digest_date", "unknown")
    text_feedback = entry.get("text", "").strip()
    votes         = entry.get("votes", {})

    vote_lines = []
    for k in sorted(votes, key=lambda x: int(x)):
        label  = STORY_LABELS.get(int(k), f"Story {k}")
        symbol = "Thumbs up" if votes[k] == "up" else "Thumbs down"
        vote_lines.append(f"  {label}: {symbol}")
    vote_block = "\n".join(vote_lines) if vote_lines else "  (no ratings submitted)"

    subject = f"Austen Digest Feedback — {digest_date}"
    body = (
        f"Austen News Digest — Reader Feedback\n"
        f"{'=' * 40}\n"
        f"Submitted:  {entry['submitted_at']}\n"
        f"Digest:     {digest_date}\n\n"
        f"Story Ratings:\n{vote_block}\n\n"
        f"Written Feedback:\n"
        f"  {text_feedback or '(none)'}\n"
    )

    msg = MIMEMultipart()
    msg["From"]    = user
    msg["To"]      = RECIPIENT
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as srv:
            srv.ehlo()
            srv.starttls()
            srv.ehlo()
            srv.login(user, password)
            srv.send_message(msg)
        print(f"  Email sent to {RECIPIENT}")
    except Exception as e:
        print(f"  Email failed: {e}")


class DigestHandler(SimpleHTTPRequestHandler):
    """Extends SimpleHTTPRequestHandler to intercept POST /api/feedback."""

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        if not self.path.startswith("/api/feedback"):
            self.send_response(404)
            self.end_headers()
            return

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
        }

        log = load_log()
        log["entries"].append(entry)
        save_log(log)

        n_votes = len(entry["votes"])
        snippet = repr(entry["text"][:60]) if entry["text"] else "no text"
        print(f"[{entry['submitted_at']}] Feedback — {n_votes} vote(s), {snippet}")

        send_email(entry)

        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, fmt, *args):
        # Only log feedback POSTs, not every static file request
        if "POST" in (args[0] if args else ""):
            print(f"  {self.address_string()} {args[0] if args else ''}")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4097
    os.chdir(SCRIPT_DIR)  # serve files from the digest directory
    smtp_ready = bool(os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASSWORD"))
    print(f"Digest server on 127.0.0.1:{port}  →  https://dev-rvelasquez.tailc35de4.ts.net/")
    print(f"Email: {'will send to ' + RECIPIENT if smtp_ready else 'NOT configured (set SMTP_USER + SMTP_PASSWORD)'}")
    HTTPServer(("127.0.0.1", port), DigestHandler).serve_forever()
