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
