"""Minimal TikTok-helper server: a checklist of clips, mobile-friendly video previews, one guarded write.

Run it behind `tailscale serve` (tailnet-only) so only your own devices can reach it.

    HELPER_CHECKLIST=ready/upload_checklist.csv \
    HELPER_ALLOWED_ORIGINS="http://127.0.0.1:8790,https://<host>.<tailnet>.ts.net:8443" \
    python helper_server.py

Checklist CSV columns: queue,video_file,caption_file,uploaded
  - `uploaded` is empty (waiting), 'inbox <time>' (delivered as a TikTok draft) or 'posted <time>'.

Security model:
  * GET endpoints are read-only.
  * The single write (POST /api/mark) requires an allowed Origin AND the custom 'X-Dashboard' header. Browsers
    won't send a custom header cross-origin without a CORS preflight this server never approves, so another
    site can't trigger it (CSRF).
  * Videos are served only by queue number from the checklist - never by a client-supplied path.
"""
from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CHECKLIST = Path(os.environ.get("HELPER_CHECKLIST", "upload_checklist.csv"))
ALLOWED_ORIGINS = {o.strip() for o in os.environ.get("HELPER_ALLOWED_ORIGINS", "http://127.0.0.1:8790").split(",") if o.strip()}
PORT = int(os.environ.get("HELPER_PORT", "8790"))


def read_rows(path: Path = None) -> list[dict]:
    path = path or CHECKLIST
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_rows(rows: list[dict], path: Path = None) -> None:
    path = path or CHECKLIST
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    os.replace(tmp, path)


def listing(rows: list[dict]) -> dict:
    def item(r):
        try:
            caption = Path(r["caption_file"]).read_text(encoding="utf-8").strip()
        except OSError:
            caption = ""
        return {"queue": r["queue"], "caption": caption, "uploaded": (r.get("uploaded") or "").strip()}
    items = [item(r) for r in rows]
    return {"inbox": [i for i in items if i["uploaded"].startswith("inbox")],
            "waiting": [i for i in items if not i["uploaded"]],
            "posted": [i for i in items if i["uploaded"].startswith("posted")]}


def mark(rows: list[dict], queues: set[str], undo: bool = False) -> int:
    n = 0
    for r in rows:
        if r["queue"] in queues:
            r["uploaded"] = "" if undo else "posted " + datetime.now().strftime("%Y-%m-%d %H:%M")
            n += 1
    return n


def write_allowed(origin: str, custom_header: str | None) -> bool:
    return origin in ALLOWED_ORIGINS and custom_header == "1"


def parse_range(header: str, size: int) -> tuple[int, int, bool]:
    """'bytes=100-' -> (100, size-1, True). Mobile video players scrub with Range requests."""
    m = re.match(r"bytes=(\d*)-(\d*)", header or "")
    if not m or not (m.group(1) or m.group(2)):
        return 0, size - 1, False
    if not m.group(1):                                    # suffix range: last N bytes
        return max(0, size - int(m.group(2))), size - 1, True
    start = int(m.group(1))
    end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
    return start, end, True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype); self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path == "/api/list":
            return self._send(200, json.dumps(listing(read_rows())))
        m = re.fullmatch(r"/video/(\d+)", self.path)
        if m:
            row = next((r for r in read_rows() if r["queue"] == m.group(1)), None)
            p = Path(row["video_file"]) if row else None
            if not p or not p.is_file():
                return self._send(404, "not found", "text/plain")
            size = p.stat().st_size
            start, end, partial = parse_range(self.headers.get("Range", ""), size)
            self.send_response(206 if partial else 200)
            if partial:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Type", "video/mp4"); self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1)); self.end_headers()
            with p.open("rb") as f:
                f.seek(start); left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except OSError:
                        break
                    left -= len(chunk)
            return
        self._send(404, "not found", "text/plain")

    def do_POST(self):
        if not write_allowed(self.headers.get("Origin", ""), self.headers.get("X-Dashboard")):
            return self._send(403, json.dumps({"error": "forbidden"}))
        if self.path != "/api/mark":
            return self._send(404, json.dumps({"error": "not found"}))
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 65536)) or b"{}")
            queues = {str(q) for q in body.get("queues", []) if re.fullmatch(r"\d{1,6}", str(q))}
        except (ValueError, AttributeError):
            return self._send(400, json.dumps({"error": "bad request"}))
        rows = read_rows()
        n = mark(rows, queues, bool(body.get("undo")))
        if n:
            write_rows(rows)
        self._send(200, json.dumps({"marked": n}))


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()   # localhost only; Tailscale fronts it
