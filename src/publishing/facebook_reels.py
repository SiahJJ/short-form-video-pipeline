"""Facebook Reels publishing (Graph API) for a Page - the 'roll-over' from Instagram.

Three-step upload: start (get a video id) -> binary upload to rupload.facebook.com -> finish with
video_state=PUBLISHED, then poll until processing completes. Wrapped by `Ledger.publish`, so a lost answer to
the finish call becomes 'uncertain' and is never re-posted.

Limits: Pages only (not personal profiles), Reels 3-90 s, 30 API posts per Page per 24 h.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .ledger import PlatformError

GRAPH = "https://graph.facebook.com/v27.0"
RUPLOAD = "https://rupload.facebook.com/video-upload/v27.0"


def _http(method: str, url: str, params=None, data: bytes | None = None, headers=None, timeout=60) -> dict:
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as ex:          # an answer: the platform said no
        try:
            err = json.loads(ex.read()).get("error", {})
            msg = f"{err.get('type')} {err.get('code')}: {err.get('message')}"
        except ValueError:
            msg = f"HTTP {ex.code}"
        raise PlatformError(msg) from None        # never include the URL: it can carry the token


class ReelsClient:
    def __init__(self, page_id: str, token: str):
        self.page_id, self.token = page_id, token

    def upload(self, path: Path) -> str:
        start = _http("POST", f"{GRAPH}/{self.page_id}/video_reels",
                      data=json.dumps({"upload_phase": "start", "access_token": self.token}).encode(),
                      headers={"Content-Type": "application/json"})
        vid = start["video_id"]
        data = Path(path).read_bytes()
        up = _http("POST", f"{RUPLOAD}/{vid}", data=data, timeout=600,
                   headers={"Authorization": f"OAuth {self.token}", "offset": "0", "file_size": str(len(data)),
                            "Content-Type": "application/octet-stream"})
        if not up.get("success"):
            raise PlatformError("upload not accepted")
        return vid

    def finish(self, video_id: str, description: str, poll_s: int = 15, polls: int = 20) -> dict:
        fin = _http("POST", f"{GRAPH}/{self.page_id}/video_reels", timeout=120,
                    data=json.dumps({"access_token": self.token, "video_id": video_id, "upload_phase": "finish",
                                     "video_state": "PUBLISHED", "description": description[:2200]}).encode(),
                    headers={"Content-Type": "application/json"})
        if not fin.get("success", True):
            raise PlatformError("finish not accepted")
        st = {}
        for _ in range(polls):                    # Facebook processes the Reel after 'finish'
            time.sleep(poll_s)
            try:
                st = _http("GET", f"{GRAPH}/{video_id}", {"fields": "status,permalink_url", "access_token": self.token})
            except PlatformError:
                continue
            s = st.get("status", {})
            if s.get("video_status") in ("ready", "published"):
                break
            if s.get("video_status") == "error":
                raise PlatformError("processing error")
        link = st.get("permalink_url")
        return {"video_id": video_id,
                "permalink": ("https://www.facebook.com" + link) if link and link.startswith("/") else link}
