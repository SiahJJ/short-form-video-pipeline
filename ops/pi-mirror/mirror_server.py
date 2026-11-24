#!/usr/bin/env python3
"""Automation mirror (runs on the always-on Pi). PI_MIRROR_V1, 2026-11-23.

Serves the dashboard (/) and the TikTok helper (/tiktok) 24/7 from the latest snapshot the home PC pushed
(see the PC's sync_to_pi.py, which runs every few minutes while the PC is awake). When the PC is asleep the
pages still open and show the most recent data, plus the time it was taken.

"Posted" taps on the helper are stored in data/marks.jsonl; the PC applies them the next time it wakes.
Standard library only. Listens on 127.0.0.1 - Tailscale Serve publishes it privately on the tailnet.
"""
import json
import os
import re
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEB, DATA = HERE / "web", HERE / "data"
VIDEOS, MARKS = DATA / "videos", DATA / "marks.jsonl"
PORT = int(os.environ.get("MIRROR_PORT", "8788"))


def load(name, default):
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def pending_marks():
    out = []
    try:
        for ln in MARKS.read_text(encoding="utf-8").splitlines():
            try: out.append(json.loads(ln))
            except ValueError: pass
    except OSError:
        pass
    return out


def tiktok_view():
    """The PC's snapshot with not-yet-synced 'Posted' taps applied, so the page reflects them right away."""
    t = load("tiktok.json", {"days": []})
    marks = pending_marks()
    for it in (i for d in t.get("days", []) for i in d.get("items", [])):
        for m in marks:
            if str(it.get("queue")) in {str(q) for q in m.get("queues", [])}:
                if m.get("undo"):
                    it["uploaded"] = ""
                else:
                    it["uploaded"] = "posted (synced when the PC wakes)"
                    it["in_inbox"] = False
        it["exists"] = (VIDEOS / f"{it.get('queue')}.mp4").is_file() or it.get("exists", False)
    return t


def banner():
    meta = load("meta.json", {})
    at = meta.get("pushed_at")
    try:
        age = (time.time() - datetime.fromisoformat(at).timestamp()) / 60
        when = datetime.fromisoformat(at).strftime("%a %I:%M %p").replace(" 0", " ")
    except (TypeError, ValueError):
        age, when = 1e9, "never"
    live = age < 12
    note = ("PC is awake - data is live" if live else
            f"PC is asleep - showing data from {when}. Next update when it wakes ({meta.get('next_wake', 'next window')}).")
    color = "#1f7a3a" if live else "#8a5a00"
    return (f'<div style="background:{color};color:#fff;font:13px system-ui;padding:8px 14px">'
            f'Pi mirror &middot; {note}</div>')


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype):
        b = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def page(self, name):
        try:
            html = (WEB / name).read_text(encoding="utf-8")
        except OSError:
            return self.send(503, "The PC hasn't pushed the pages yet.", "text/plain")
        html = re.sub(r"(<body[^>]*>)", lambda m: m.group(1) + banner(), html, count=1)
        self.send(200, html, "text/html; charset=utf-8")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            return self.page("index.html")
        if path in ("/tiktok", "/tiktok.html"):
            return self.page("tiktok.html")
        if path.startswith("/api/status"):
            return self.send(200, json.dumps(load("status.json", {})), "application/json")
        if path.startswith("/api/tiktok"):
            return self.send(200, json.dumps(tiktok_view()), "application/json")
        m = re.fullmatch(r"/video/(\d+)", path)
        if m:
            p = VIDEOS / f"{m.group(1)}.mp4"
            return self.stream(p) if p.is_file() else self.send(404, "not found", "text/plain")
        self.send(404, "not found", "text/plain")

    def stream(self, p):
        size = p.stat().st_size
        rng = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        start, end = 0, size - 1
        if rng:
            if rng.group(1): start = int(rng.group(1))
            if rng.group(2): end = min(int(rng.group(2)), size - 1)
            self.send_response(206); self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", "video/mp4"); self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1)); self.end_headers()
        with p.open("rb") as f:
            f.seek(start); left = end - start + 1
            while left > 0:
                chunk = f.read(min(262144, left))
                if not chunk: break
                try: self.wfile.write(chunk)
                except (ConnectionError, OSError): break
                left -= len(chunk)

    def do_POST(self):
        origin = self.headers.get("Origin", "")
        ok_origin = origin.endswith(".ts.net:8444") or origin.startswith(("http://127.0.0.1", "http://localhost"))
        if not ok_origin or self.headers.get("X-Dashboard") != "1":
            return self.send(403, "forbidden", "text/plain")
        body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 100_000)) or b"{}")
        if self.path == "/api/tiktok/mark":
            qids = [str(q) for q in body.get("queues", []) if str(q).isdigit()]
            with MARKS.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"queues": qids, "undo": bool(body.get("undo")),
                                    "at": datetime.now().isoformat(timespec="seconds")}) + "\n")
            return self.send(200, json.dumps({"marked": len(qids)}), "application/json")
        if self.path == "/api/tiktok/open":
            return self.send(200, '{"ok":false,"note":"Folders open on the PC only"}', "application/json")
        self.send(404, "not found", "text/plain")


if __name__ == "__main__":
    VIDEOS.mkdir(parents=True, exist_ok=True); WEB.mkdir(parents=True, exist_ok=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
