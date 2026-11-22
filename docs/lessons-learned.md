# Lessons learned (real incidents)

Each entry: what broke, why, and the fix that stops it recurring.

### Disk filled to 1 GB free
- **Cause:** 4–6 GB livestream VODs, plus a second full copy of every source made by the clipper.
- **Fix:**
  - Source caps in the downloader: no livestreams, at most 4 h and 6 GB.
  - A storage guardian with ordered rules that deletes only files every platform has confirmed.
  - Abandoned `.part` downloads are removed.
  - Duplicate sources become **NTFS hard links**: both paths work, the bytes are stored once.
  - Downloads pause below a 20 GB floor.

### Silent rejection by yt-dlp
- **Cause:** `--print` implies `--quiet`, so the "does not pass filter" line never reached the logs, and
  over-long videos looked like failed downloads that were retried forever.
- **Fix:** `--no-quiet`, plus a dedicated `skipped_too_long` status.

### Hashtags that nobody searches
- **Cause:** `#GTA4Retrospective` (a franchise glued to a series name), `#Per` (an accented "Perú" lost its last
  letter), `#NPCsCrashInto` (a phrase cut mid-sentence).
- **Fix:**
  - Accent folding.
  - Franchise and acronym tags are never glued to other words.
  - A phrase may not end on a stop word.
  - Niche-guaranteed tags (#BreakingNews for news, #GTA alongside #GTA4).

### Clipping the creator's own commercial
- **Cause:** The LLM rates moments for hook and energy, and a well-produced sponsor read or merch plug scores
  well. Clips of sponsored segments, a podcast's partner ad and a creator showing off their own plushies went out.
- **Fix (`NO_ADS_V1`), before rendering:**
  - **SponsorBlock:** a free, community-maintained database of sponsor and self-promo segments, keyed by the
    public YouTube video ID. A moment overlapping a segment by 25 % or more is dropped. It sits behind a config
    flag, so the clipper can stay fully offline.
  - **The clip's own words:** one unmistakable ad phrase ("sponsored by", "use code", "in partnership with") or
    two softer ones ("plushies", "link in the description", "download").
  - The first version flagged GTA robbery gameplay ("jewelry store", "$400") and "get yourself"; the softer
    word list was narrowed after checking every hit by hand.
  - Clips already in the queue get the same check and are held everywhere.

### Hooks that stacked
Generating a hook for every caption exposed a re-entrancy bug: each re-tag prepended a new hook above the
previous ones. The caption builder now strips everything above the `Creator - title` line before adding the
current hook.

### Trend clips nobody watched
- **Cause:** The trend pipeline only takes Creative Commons videos, and those come almost entirely from small
  channels. Of 209 trend videos it had picked, 126 had under 10k views or came from tiny channels: betting
  picks, game previews, coach pressers, live streams, and one music video picked because the band's *name*
  contained the trending word. The AI then rated the best moment *within* each video highly (89/100), which
  says nothing about whether anyone wants the video.
- **Fix (`TREND_QUALITY_V1`):**
  - A trend must appear in what the video is about, not only in the channel name.
  - At least 10k views and a channel with 100k+ subscribers.
  - Commentary formats are rejected (picks, predictions, previews, breakdowns, reactions, pressers, podcasts,
    live streams).
  - Sports trends need actual highlights.
  - Already-queued clips that fail are held from every platform, not deleted.

### Tags about the channel, not the clip
- **Cause:** A gaming streamer's documentary about a country went out as `#Streamer #Gamer #Gameplay #Gaming
  #VideoGames`. The creator's usual niche was hard-coded, and the clip's real topics were filtered out because
  short transcripts couldn't confirm them. Facebook also re-used captions Instagram had posted days earlier,
  so old mistakes were repeated there.
- **Fix:**
  - **Topic tags:** title words the clip actually talks about ('African Freedom Speech' -> `#Africa #Freedom`),
    confirmed by the transcript (same 5-letter stem), the uploader's description, or (weakest) the real title.
    Hook words like "Epic" or "Power" never count.
  - **A creator's usual niche must show up in the clip.** If it doesn't, its community tags are dropped.
  - **The creator tag must earn its slot:** only very large channels (by subscriber count, cached for 14 days)
    or news outlets keep it. Everyone else's slot goes to the topic.
  - Split names are merged (`#Jane #Smith` -> `#JaneSmith`), and `#NameLive` next to `#Name` is dropped.
  - Facebook rebuilds hashtags with the current engine at post time.

### AI hooks that add facts
- **Cause:** for a news clip, a local model added a claim about who was "in charge" that wasn't in the source,
  and was factually wrong.
- **Fix:** a prompt that only restates the source, plus a grounding check. Every longer word of the Spanish hook
  must stem-match the source, otherwise the hook is regenerated or dropped.

### One login change took down another platform
- **Cause:** while setting up Facebook Login, removing the app's business integration also invalidated the
  Instagram session token, so posting stopped.
- **Fix:** documented re-auth, a token check before publishing, and failed-before-publish items re-queued only
  when the ledger proves nothing reached the platform.

### A deals video got almost no views
- **Fix:** a shopping and ads filter at topic discovery and at video ranking, which also blocks drafts already
  queued downstream.
