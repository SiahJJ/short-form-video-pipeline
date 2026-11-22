# Publishing safety

Posting to a real account is the one irreversible action in the pipeline, so every publisher follows the same
rules.

## 1. Reserve in the ledger before calling the API
Each platform has a ledger keyed by queue ID. The publisher writes `reserved`/`uploading` *before* the first
network call, then updates the status at each stage (container created, upload accepted, publish requested,
confirmed). A crash leaves an exact record of how far it got.

## 2. Never auto-retry an uncertain outcome
If the answer to the *publish* call is lost (timeout, network drop), the post may or may not be live. Such items
are marked `uncertain` / `outcome_unknown` and are **never retried automatically**; a human checks the account.
Only failures that are *proven* to be before publication are retried automatically (no container, or a
container that ended in `ERROR`/`EXPIRED` with `publishRequestStarted=false`).

## 3. Pace below the platform's limits
| Platform | Limit | Pipeline behaviour |
|---|---|---|
| Instagram | 50 API posts / 24 h | Even pace (about 29 min); 5–10 min gaps while a backlog exists; end-of-day burst in the last hour if the allowance is unused |
| Facebook Reels | 30 / 24 h | 28 / 24 h cap, ≥30 min gap, ≥30 min after the Instagram post |
| YouTube | Daily upload quota | Highest-scoring clips first; cooldown when the quota is hit |

### Facebook: fewer, better, visibly edited
A brand-new Page that reposts other creators' clips gets almost no distribution, and volume makes it worse.
The Facebook roll-over therefore:
- posts only the **best-scored** Instagram Reels (about 10 a day, at most 2 per work window) and skips any
  older than 4 days instead of queueing them forever;
- burns the clip's hook into the first 4 seconds as a title card (ffmpeg `drawtext`, falling back to the
  original file on any error), so the Reel adds something rather than being a bare re-upload;
- rebuilds the hashtags with the current engine at post time;
- reads real Reel plays from `video_insights` when the `read_insights` permission is granted, and otherwise
  falls back to the `views` field.

## 4. Gate content before it can be queued
- **Rights:** YouTube Data API `status.license == creativeCommon`, or a creator on the attested list.
- **Publication cutoff date,** with per-video exceptions in a reviewed config file.
- **Language:** English/Spanish only.
- **Content:** no shopping, deals or ads videos; sensitive-content hold for review.
- **Duration:** 3–90 s for Reels.

## 5. Credentials
- OAuth with local callback servers and a random `state` check.
- Long-lived tokens are encrypted with Windows DPAPI, readable only by the same Windows user.
- Secrets are entered through masked prompts and never printed or logged; error messages strip URLs that could
  carry tokens.
