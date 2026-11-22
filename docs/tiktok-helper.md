# TikTok: inbox uploads + a phone helper for captions

TikTok's Content Posting API has two modes. **Direct Post** publishes immediately, but requires an
app audit before posts can be public. **Inbox upload** needs no audit: the video lands as a draft in the
creator's TikTok app. The catch is that inbox uploads **carry no caption**, so a human has to finish each post.
The TikTok helper makes that a 15-second job from your phone.

```mermaid
sequenceDiagram
    participant IG as Instagram publisher
    participant S as Stager (every 30 min)
    participant U as Inbox uploader (every 5 min)
    participant TT as TikTok API
    participant Ph as Your phone
    participant H as Helper page (tailnet)
    IG->>S: Reel confirmed on Instagram
    S->>S: caption + up to 8 TikTok hashtags, best clips first
    U->>TT: /post/publish/inbox/video/init + upload
    TT-->>Ph: "Video uploaded" in Inbox → System notifications
    Ph->>H: open helper, Copy caption
    Ph->>TT: paste caption, add sound, Post
    U->>TT: status/fetch (read-only)
    TT-->>U: PUBLISH_COMPLETE
    U->>H: clip moves from "In your inbox" to "Posted"
```

## What the helper page does
Served by the dashboard (`/tiktok`) and opened on your phone over the private tailnet URL
(see [remote-access-tailscale.md](remote-access-tailscale.md)):

- **In your TikTok inbox:** every clip that's been delivered as a draft, newest first, with an inline video
  preview (HTTP range streaming, so it scrubs on mobile), the ready caption, **Copy caption** and **Posted**.
- **Waiting to send:** staged clips by day, best first, with size, caption and a link to the Instagram original.
- Posting is **detected automatically**: the uploader polls TikTok's status endpoint and marks a clip posted
  once TikTok reports `PUBLISH_COMPLETE`, so the **Posted** button is only a manual override.

## Pacing and TikTok's pending-draft limit
TikTok refuses new inbox uploads (`spam_risk_too_many_pending_share`) once a handful of drafts are waiting
unposted. The uploader:

- sends at most one clip per gap, best clips first;
- **stops sending at the pending limit** and emails one reminder ("N drafts waiting, post them to
  resume");
- resumes on its own as soon as you post a draft;
- treats an explicit TikTok rejection *before* a `publish_id` exists as safe to retry later (nothing was
  created).

## Lesson learned: reconcile "unknown" uploads, never re-send them
An upload's final `PUT` can return an error (we saw HTTP 403) even though TikTok accepted the file. Those
items were marked `outcome_unknown` and, by design, never re-sent, but they were also **never re-checked**.
The uploader counted 0 waiting drafts while TikTok counted 3, so every new upload was refused for 7 hours.

Fix: `outcome_unknown` items that have a `publish_id` are included in the read-only status reconciliation.
`SEND_TO_USER_INBOX` moves them to "In your inbox" and `PUBLISH_COMPLETE` to "Posted". Nothing is ever
uploaded twice; the state just stops lying.

## Minimal implementation
[`src/dashboard/helper_server.py`](../src/dashboard/helper_server.py) is a self-contained version of the
helper's server side: a CSV checklist, range-streamed previews, and an origin- and header-guarded "mark
posted" endpoint, with tests.
