# Architecture

Everything runs on a single Windows PC with a consumer NVIDIA GPU (8 GB VRAM is enough), driven by Windows Task Scheduler. Each stage is
an independent script that reads and writes a small state file or database, so any stage can fail, restart or
be replaced without breaking the others.

## Components

| Component | Language | Role | State |
|---|---|---|---|
| Creator watcher / worker | Python | Polls creator channels (YouTube Data API); when a video passes its view trigger, downloads it with yt-dlp (no livestreams, ≤4 h, ≤6 GB) and submits it to the clipper | `tracker.db` (SQLite): videos, clip_uploads |
| Trend discovery | Python | Google Trends topics → candidate videos → Creative Commons licence check → shopping/ads, language and cutoff filters | `trends.db` |
| AI Clipper | Python (FastAPI) | Transcribe (faster-whisper large-v3-turbo) → pick moments (Qwen3 via Ollama + heatmap, energy and scene-cut signals) → 9:16 reframe (YuNet face tracking) → karaoke captions → NVENC encode | job records |
| Metadata engine | Python | Niche detection, hashtag candidate pool and ranking, bilingual hooks with a grounding check | Instagram drafts manifest |
| Instagram publisher | Node.js + PowerShell | Container → status poll → publish through the Instagram Graph API; cadence gate; recovery manager | publish ledger (JSON) |
| YouTube uploader | Python | Highest-score-first uploads within the daily quota; scheduled publishAt peak slots | `tracker.db` |
| TikTok stager | Python | Packages the best clips for TikTok (Content Posting API inbox) | TikTok ledger |
| Facebook roll-over | Python | Re-posts each Instagram-confirmed Reel to the Facebook Page (Reels Publishing API: start → binary upload → finish) | `fb_ledger.json` |
| Storage guardian | Python | Hourly ordered cleanup rules; hard-link dedupe; emergency mode | deletions CSV |
| Dashboard | Python (stdlib) | Read-only status page: queues, last posts, cadence, storage, task health | none (read-only) |

## Data flow
1. **Discover:** creator triggers and trend topics produce candidate source videos.
2. **Gate:** rights (CC-BY or attested creator), publication cutoff, language (English/Spanish), and content
   (no shopping or ads) are checked before any download.
3. **Clip:** the clipper produces 15–90 s vertical clips with scores.
4. **Describe:** the metadata engine writes caption, hook and hashtags for each platform.
5. **Publish:** each platform has its own paced publisher and its own ledger. Facebook follows Instagram.
6. **Clean up:** the guardian deletes a clip only after every platform that still needs it has confirmed it.

## Design principles
- **Idempotent, ledger-first publishing.** A post is reserved in the ledger *before* any network call.
  An uncertain outcome is never retried automatically.
- **Fail closed.** A missing licence, transcript or language signal holds the clip; it doesn't guess.
- **Local AI.** Transcription, clip selection, hashtag ranking and hooks all run on the local GPU through
  Ollama, with no per-clip API cost.
- **Secrets never touch logs.** Tokens are DPAPI-encrypted at rest; credentials are entered through masked
  prompts.
