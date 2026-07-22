# Alpecca Video Companion, Streaming, And Sharing Plan

**Status:** ACTIVE IMPLEMENTATION PLAN
**Last reviewed:** 2026-07-22
**Authority:** `PROJECT_CONTEXT.md` and `HANDOFF.md` remain canonical.

## Goal

Give Alpecca one bounded way to watch a complete video, follow a live source,
react as a co-viewer or streamer, and share approved artifacts through House
HQ, Discord, and later supported surfaces. House HQ is the primary control and
co-watching experience; Discord is one channel adapter. This extends her
existing mind, memory, voice, Discord bridge, House HQ, and VRM body. It does
not create a second agent, a second memory authority, or an always-recording
surveillance process.

The target experience is:

1. Alpecca can watch an uploaded or local video from beginning to end and
   resume at the last verified timestamp.
2. She can follow an explicitly shared screen or supported live stream while
   direct conversation remains more important than passive watching.
3. She can react naturally whenever her context and Soul find a moment worth
   expressing, without an arbitrary reactions-per-minute limit.
4. Her reactions can drive speech, lip sync, expression, and body cues through
   the existing embodiment pipeline.
5. She can attach a permitted file to Discord or create a bounded share receipt
   and link through an approved storage adapter.
6. Every observation, reaction, share, interruption, and resume is ordered,
   attributable, and visible in the Brain Garden.

## Research Synthesis

| Source | Useful pattern | Decision for Alpecca |
|---|---|---|
| [Hugging Face community discussion](https://discuss.huggingface.co/t/streamer-ai-like-neuro-sama/33836) | Separates speech, chat, game input, avatar motion, and moderation; notes that speech should outrank chat | Treat as anecdotal design input only. Use one CoreMind with typed adapters and priority lanes, not several uncoordinated agents. |
| [ai_licia product](https://www.getailicia.com/) and [public API](https://docs.getailicia.com/docs/public-api/rest/events/) | Cross-platform events, a context-only path, a separate immediate-reaction path, channel status, memory-aware community interaction | Port the event distinction. Most stream events update context; only rare high-value events request an immediate reaction. Do not add ai_licia as a second hosted mind. |
| [ai_licia event schema](https://docs.getailicia.com/docs/public-api/eventsub/events/) | Stable event IDs, timestamps, channel/stream identity, typed chat and TTS events | Adopt an Alpecca-owned ordered envelope with session ID, sequence, media timestamp, speaker/source, and provenance. Never expose raw chain-of-thought. |
| [Tavus CVI architecture](https://docs.tavus.io/sections/conversational-video-interface/overview-cvi) | Modular perception, conversational flow, STT, LLM, TTS, and avatar rendering; explicit interruption control | Port the modular order and interruption semantics. Keep Qwen 3.5 9B, Alpecca's voice, and her VRM rather than adopting Tavus models or replicas. |
| [Tavus interaction protocol](https://docs.tavus.io/sections/conversational-video-interface/interactions-protocols/overview) | Monotonic event sequence plus a turn index for correlating perception, speech, tools, and avatar state | Adopt `seq` and `turn_id` equivalents so stale vision or speech cannot attach to a later turn. |
| [ScreenApp video watcher](https://screenapp.io/features/ai-video-watcher) | Full-video transcript plus timestamped frames and verifiable, time-linked answers | Adopt timestamped multimodal evidence and citations to moments. Do not trust one generated whole-video summary as the source record. |
| [MSI DigiME](https://www.msi.com/Landing/digime-ai-virtual-avatar) | Webcam motion capture, saved scene setup, VRM import, expression switching, voice modulation, GPU/NPU isolation | Reuse only embodiment ideas. Alpecca's locked VRM design and current animation system remain authoritative. |
| [VisionStory streaming](https://www.visionstory.ai/en-us/features/streaming) | Lip sync, expression/body cues, OBS-compatible output, multilingual speech | Port event-to-expression and OBS output concepts. Do not replace her body with a generated portrait avatar. |
| [Muvi video chat](https://www.muvi.com/blogs/what-is-ai-chat-in-video-streaming/) | Ask questions, summarize, search scenes, and jump to contextual moments during playback | Add timeline query and seek suggestions after evidence indexing is live. |
| [FFmpeg documentation](https://ffmpeg.org/ffmpeg.html) | Reads files, network streams, and capture devices; extracts bounded frames and audio | Use the existing packaged FFmpeg/PyAV spine for adapters and benchmarks. Do not add a second media framework. |
| [Browser Screen Capture API](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getDisplayMedia) | Produces a WebRTC-compatible stream after the user selects a screen/window | House screen sharing must start from an HTTPS user gesture every time. Browser permission cannot honestly be made permanent. |
| [Discord message API](https://docs.discord.com/developers/resources/message) | Bots can send multipart attachments; create-message requests are capped at 25 MiB | Prefer a direct Discord attachment for small artifacts and a governed external link for larger items. |
| [Discord voice/video protocol](https://docs.discord.com/developers/topics/voice-connections) | Voice and Go Live now require DAVE end-to-end encryption; video sink support exists at protocol level | Park direct Discord Go Live reception until the bridge and library pass a DAVE/video soak. Never use a self-bot or scrape a user client. |
| [Cloudflare R2 presigned URLs](https://developers.cloudflare.com/r2/api/s3/presigned-urls/) | Time-limited GET capability without revealing storage credentials | Use only for approved, non-art artifacts. Treat each URL as a bearer secret, set a short expiry, and retain a revocation/audit receipt. Alpecca art remains on Hugging Face. |
| [Google Drive sharing](https://developers.google.com/workspace/drive/api/guides/manage-sharing) | Stable file link with ACL-controlled user/group/reader access | Use for creator-selected private folders and durable human-readable files. Verify `canShare`, exact ACL, and download policy before posting. |
| [OBS Virtual Camera](https://obsproject.com/kb/virtual-camera-guide) | Publishes one scene or program output to camera-capable apps including Discord | Use as the optional broadcast output after local House/VRM reaction sync is reliable. |

## Non-Negotiable Architecture

### One ordered perception stream

All media activity uses one descriptor envelope:

```text
event_id, session_id, seq, turn_id, source_kind, source_id,
media_timestamp_ms, observed_at, payload_digest, provenance, privacy_class
```

Raw image/audio chunks may exist only in a bounded pending handoff and the
active decoder/model call. Durable history stores transcript text, visual
descriptions, hashes, timestamps, reactions, and provenance. It does not store
raw screen, webcam, or Discord media in the memory database.

### Priority and interruption

| Lane | Work |
|---|---|
| P0 | Direct text/voice conversation, stop, and urgent safety state |
| P1 | User-requested image/video question, explicit seek, or direct upload |
| P2 | Live scene sampling, stream chat/context, eligible reaction |
| P3 | Post-session summary, temporal fact derivation, reflection |
| P4 | Index maintenance, benchmarks, cleanup, and optional export |

A P0 turn requests cooperative cancellation of P2-P4 work. A video session is
paused, not forgotten, and can resume from its last committed timestamp.

### Reaction policy

Visual and audio events update context by default. They do not automatically
force speech. Alpecca may react whenever grounded context, her Soul, and her
current affect give her something to express: a scene change, a direct
question, a named-person cue, a stream event, a developing pattern, or a quiet
moment are examples rather than a closed trigger list. There is no fixed
reaction-rate cap. Natural turn ownership, current speech, direct conversation,
and measured host pressure determine whether work runs now or waits. Exact
duplicates and long runs of unchanged frames may be represented as a
timestamped range, but meaningful events are not silently discarded. A model
failure produces silence, never a canned or invented event.

### Source and sharing policy

- A local path must first pass the existing allowed-root/file-ingress checks.
- A web source must use a named adapter and record the final origin, media type,
  and authorization. Version 1 does not provide an arbitrary URL downloader.
- Copyright, platform access controls, and signed URLs are not bypassed.
- Small permitted files may be attached directly to Discord.
- Larger files use a creator-selected Drive ACL, an expiring R2 capability, or
  an existing private Hugging Face artifact path. No storage credential appears
  in Discord, prompts, logs, or memory.
- Anything that changes sharing permissions or publishes a private artifact is
  an `APPROVAL_ASK_FIRST` action with a content-free proposal and an exact
  execution receipt.

## Stage Plan And Current Status

### Stage V0 - Discord image reliability and continuity

**Status: IMPLEMENTED, TESTED, LIVE RESTART/SMOKE PENDING**

- Route signed CreatorJD uploads through one exact one-use vision egress grant.
- Use `gemma4:cloud` for that signed path and GPU-capable `qwen3.5:4b` locally as
  the fallback; keep `qwen3.5:9b` as the reasoning model.
- Store a bounded visual description with image/photo/picture/screenshot terms
  so later references can retrieve it across turns.
- Keep guest images local and actor-scoped; retain no raw bytes or attachment
  URLs.
- Exit gate: focused media, guest-boundary, launcher, and consent tests green,
  followed by one live Discord upload and one later "screenshot above" query.

### Stage V1 - Ordered Video Companion foundation

**Status: IN PROGRESS**

- Add resumable file/live session state, bounded timestamped timeline,
  transcript segments, frame descriptors, adaptive sampling, lossless
  unchanged-frame range compaction, interrupt/resume, and P1/P2 work metadata.
- Integrate the serialized vision dispatcher and observer slots.
- Exit gate: no raw frame/audio bytes survive dispatch; repeated frames
  coalesce; P0 chat interrupts a live session; restart restores only a safe
  descriptor checkpoint.

### Stage V2 - Full uploaded/local video watching

**Status: NOT STARTED**

- Add a bounded FFprobe/PyAV adapter for creator-selected files and Discord
  video attachments already admitted by attachment ingress.
- Extract timestamped audio chunks and adaptive key frames. Use faster-whisper
  by default and the existing image-description path one frame at a time.
- Commit timeline evidence incrementally so a two-hour video can resume and be
  queried without fitting the whole item in an 8K prompt.
- Add `ask_video`, `seek_video`, `pause_video`, `resume_video`, and
  `video_status` internal tools.
- Exit gate: complete a 30-minute fixture under fixed memory limits; answer
  timestamped audio-only, visual-only, and cross-modal questions; restart and
  resume within one sample interval.

### Stage V3 - House screen share and live co-watching

**Status: PARTIAL CAPABILITY SPINE EXISTS; ADAPTER NOT STARTED**

- Reuse House's expiring screen capability lease and HTTPS
  `getDisplayMedia()` gesture.
- Send reduced, adaptive frames plus optional system-audio transcript segments
  into the V1 event stream. Do not transmit the full display continuously to
  the model.
- Provide visible source, elapsed time, frame rate, backlog, and stop controls.
- Exit gate: permission revokes on disconnect/restart, capture stops visibly,
  direct chat remains responsive, and no stale frame is described after stop.

### Stage V4 - Natural reactor and stream co-host

**Status: NOT STARTED**

- Add context and expression event classes, following the useful ai_licia
  separation without copying its forced-generation rate limit or installing
  its hosted mind.
- Fuse scene, transcript, chat-room state, speaker presence, affect, and recent
  reactions before choosing silence, emoji, text, or voice.
- Drive TTS, lip sync, face expression, gaze/head target, and a bounded gesture
  from the same reaction receipt.
- Add explicit audience awareness: who is present, who spoke, whether Alpecca
  is already speaking, and whether anyone is waiting for an answer.
- Exit gate: no self-reply loop, no accidental duplicate reaction, natural
  interruption, no arbitrary reaction quota, and evidence-linked avatar cues.

### Stage V5 - Discord attachments and governed share links

**Status: DIRECT TEXT/IMAGE DELIVERY EXISTS; GENERAL SHARE SERVICE NOT STARTED**

- Define a `ShareArtifact` record: digest, owner, classification, destination,
  recipient scope, permission mode, expiry, provider, state, and receipt.
- Attach files no larger than Discord's API limit directly when permitted.
- Add Drive reader ACL and expiring R2 GET adapters. Keep Alpecca art on private
  Hugging Face storage according to project policy.
- Render a human-readable label/button in Discord; never print backend
  credentials or an unredacted signed URL into logs or model context.
- Exit gate: recipient can watch/read/download, unauthorized retrieval fails,
  expiry/revocation works, and the audit identifies exactly what was shared.

### Stage V6 - OBS/virtual-camera broadcast output

**Status: NOT STARTED**

- Publish the existing House/VRM scene to an OBS browser source or virtual
  camera; do not generate a replacement avatar.
- Add optional OBS WebSocket control for approved scene switching, captions,
  and start/stop state. External broadcast start remains explicit.
- Exit gate: voice, mouth, face, and body receipt share one turn ID; stream
  output stays smooth while Qwen answers on the 4 GB GPU.

### Stage V7 - Named web/live source adapters

**Status: NOT STARTED**

- Add adapters individually for open files, creator-authorized HLS/WebRTC, and
  supported platform APIs. Each adapter declares auth, content policy, retry,
  seek/live semantics, and final origin.
- Add scene/topic search and time-linked answers over the timeline.
- Exit gate: every adapter has deterministic offline fixtures and cannot fetch
  private-network or unapproved local targets.

### Stage V8 - Discord Go Live reception

**Status: PARKED**

- Revisit only when the Discord library supports the required DAVE E2EE and
  video sink protocol in a maintained, official-compatible path.
- Until then, detect `self_stream` as presence only and ask for a House screen
  share or an authorized video link. Do not claim Alpecca sees the stream.
- Exit gate: encrypted receive, participant consent, reconnect/resume, frame
  bounds, and Discord policy review all pass.

### Stage V9 - Release benchmarks and Brain Garden visibility

**Status: NOT STARTED**

- Add live nodes for source, decoder, transcript, vision queue, timeline,
  reaction judge, TTS/avatar sync, share provider, and current blockers.
- Run direct-turn latency while video is active, one-hour resource soak,
  interruption recovery, false-scene/false-recall tests, and link expiry tests.
- Exit gate: all nodes are evidence-backed, the House production build passes,
  the focused and full core suites pass, and unsupported adapters remain visibly
  unavailable rather than simulated.

## Deliberately Not Adopted

- No Tavus, VisionStory, DigiME, ScreenApp, or ai_licia hosted runtime inside
  Alpecca's core.
- No new planner or memory authority.
- No continuous full-frame VLM loop on the RTX 3050 4 GB.
- No self-bot, client scraping, DRM bypass, password bypass, or private-network
  URL fetcher.
- No permanent browser screen-capture permission claim.
- No raw video/audio copied into SQLite or Mindpage.
- No automatic public publication of private files, memories, or character art.

## Verification Matrix

| Area | Required proof |
|---|---|
| Ordering | Monotonic sequence and session/turn correlation under reconnect |
| Resource use | Chat P95, RAM, VRAM, CPU, queue depth, deferred work, and timestamped unchanged-frame ranges |
| Full video | End-to-end completion, restart resume, timestamped Q&A |
| Live source | Stale-frame rejection, interruption, explicit stop, permission loss |
| Reactions | Duplicate/self-loop prevention, cooldown, silence path, avatar sync |
| Memory | Provenance, correction, no invented scene, bounded timeline recall |
| Sharing | Digest match, ACL/expiry, revocation, recipient success, no secret logs |
| Discord Go Live | DAVE encryption, maintained library support, policy and consent soak |
