# Open-Source Research Review

Updated: 2026-07-22

Implementation checkpoint: the first voice stage is now implemented. Discord
receive uses the installed Silero VAD 6.2.1 ONNX model on CPU, with two-frame
onset confirmation, 800 ms pre-roll, VAD silence endpointing, direct-input
playback interruption, and packet-based fallback on any load/inference failure.
On the target laptop, a local 5.33-second speech sample produced a 0.999997 peak
probability versus 0.008911 for digital silence. Mean processing was 0.24 ms per
20 ms Discord packet; cold model load was 648 ms and is performed off the
Discord event loop. Live human Discord validation is still required before the
stage is called release-proven.

This review compares active open-source projects against Alpecca's actual
runtime: Qwen 3.5 9B through Ollama, an RTX 3050 with 4 GB VRAM, SQLite-backed
memory, House HQ, Discord voice, and one continuity authority. The goal is to
adopt isolated proven components, not install another agent framework beside
Alpecca.

## Recommendation matrix

| Project | Useful contribution | Cost or conflict | Decision |
|---|---|---|---|
| [GLaDOS](https://github.com/dnhkng/GLaDOS) | Priority speech queue, Silero VAD with pre-roll, interruption/barge-in, async context slots, PAD + persistent traits, observer pass | Whole application duplicates Alpecca's mind, affect, memory, tools, and autonomy | PORT the audio scheduling and observer patterns only |
| [Silero VAD](https://github.com/snakers4/silero-vad) | Roughly 2 MB ONNX/JIT VAD; streaming 8/16 kHz; CPU-friendly | One model plus ONNX runtime; threshold requires calibration | ADOPT in the isolated Discord voice environment after an A/B latency test |
| [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | One portable runtime for VAD, STT, TTS, and speaker diarization across Windows/Android | Broad package and model set; replacing working F5/faster-whisper paths at once is high risk | EVALUATE speaker diarization only in an optional worker |
| [sqlite-vec](https://github.com/asg017/sqlite-vec) | Embedded vector search inside Alpecca's existing SQLite store | Needs migration/equivalence tests; package is already downloaded but not active | ADOPT behind the existing Mindpage fallback and keep keyword retrieval |
| [llama.cpp server slots](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) | Disk save/restore for KV slots and bounded cache RAM | Requires an optional llama.cpp backend; Ollama does not expose the slot API | KEEP as the opt-in Mindpage backend experiment |
| [Qwen-Agent](https://github.com/QwenLM/Qwen-Agent) | Qwen 3.5 tool-call templates, parallel function calls, MCP and RAG examples | Replaces Alpecca's bounded registry/planner and can add Gradio, Docker, RAG, and MCP dependencies | PORT parser/evaluation cases; do not install the framework |
| [Mem0](https://github.com/mem0ai/mem0) | Add-only extraction, entity linking, temporal and multi-signal retrieval; published memory benchmarks | Introduces another memory authority and extra model calls | PORT evaluation cases and retrieval fusion ideas only |
| [Letta](https://github.com/letta-ai/letta) | Memory blocks, archival recall, continual-learning evaluations, portable agent state ideas | Large second agent runtime; cloud-oriented examples and different control model | PORT evals/state-format ideas; do not replace CoreMind |
| [Graphiti](https://github.com/getzep/graphiti) | Temporal facts with source episodes and validity windows | Neo4j/FalkorDB service, structured-output dependence, additional LLM work, optional telemetry | PARK; too heavy for this laptop and current scale |
| [FastVLM](https://github.com/apple/ml-fastvlm) | Efficient low-token vision encoder; 0.5B option | Primary optimized deployment is Apple Silicon; PyTorch stack overlaps current vision routing | RESEARCH only; do not add to the Windows core yet |
| [pyannote.audio](https://github.com/pyannote/pyannote-audio) | Strong speaker diarization and embeddings | PyTorch/model weight cost competes with Qwen on 4 GB VRAM | PARK in favor of an ONNX worker trial |
| [InsightFace](https://github.com/deepinsight/insightface) | Mature face detection/recognition | Code is MIT but published recognition model weights have separate non-commercial/licensing conditions | DO NOT BUNDLE without a specifically approved model license |
| [Moonshine Voice](https://github.com/moonshine-ai/moonshine) | Streaming CPU ASR with Windows support and a 34M-parameter English Tiny model | A second transcription path needs measured accuracy and lifecycle support | PILOT behind a flag against faster-whisper; do not replace it speculatively |
| [OpenCV YuNet + SFace](https://github.com/opencv/opencv_zoo) | Small CPU face detector and recognizer with permissively licensed supplied weights | Recognition has no liveness proof and camera-specific thresholds need calibration | ADOPT only as optional familiarity evidence, never creator authentication |
| [WeSpeaker](https://github.com/wenet-e2e/wespeaker) | Strong speaker embeddings and an ONNX runtime | Full Python environment adds PyTorch, audio, clustering, and research dependencies | EVALUATE one ONNX model only if sherpa-onnx accuracy is insufficient |
| [SpeechBrain](https://github.com/speechbrain/speechbrain) | Broad research toolkit and ECAPA speaker verification | Heavy PyTorch-first stack duplicates the voice environment | PARK as a benchmark reference |

## Lean integration order

1. **Voice reliability:** port GLaDOS's input-priority queue, 800 ms pre-roll,
   VAD-controlled utterance boundaries, and playback interruption. Trial Silero
   ONNX in the Discord voice venv; keep faster-whisper and F5 unchanged during
   the comparison.
2. **Memory quality:** activate sqlite-vec behind the current memory API. Add a
   hybrid score using semantic, keyword, recency, provenance, and identity
   confidence. Run old-vs-new recall equivalence and latency tests before making
   it default.
3. **Identity evidence:** keep authenticated device/account identity as the only
   authority proof. Add optional speaker and visual embeddings as probabilistic
   evidence, with provenance, confidence, and contradiction history. Writing
   style can contribute weak evidence but can never authenticate CreatorJD.
4. **Observer/regulation:** port the GLaDOS observer concept as one bounded,
   asynchronous review of committed outcomes. It may adjust evidence-backed
   personality traits but cannot rewrite safety policy, identity, or tools.
5. **KV persistence:** retain llama.cpp slots as a measured optional backend.
   Do not assume a Windows pagefile makes a large context fast; benchmark
   latency, RAM, disk writes, and restore correctness at 8K first.

## Deep findings

### 1. Memory: improve the schema, not the number of memory products

Alpecca already has the important runtime pieces: canonical SQLite storage,
FTS and semantic retrieval, Mindpage context accounting and paging, and an
append-only continuity journal. Installing Mem0, Letta, or Graphiti would make
it unclear which system is allowed to admit, revise, retrieve, or forget a
memory.

The useful research result is a schema upgrade inside the current authority:

```text
memory_episode
  id, source_surface, actor_id, observed_at, content_hash, raw_reference
        |
        +-- memory_fact
              subject, predicate, object
              valid_from, valid_to
              recorded_at, invalidated_at
              confidence, scope, supersedes_id
        |
        +-- memory_fact_source
              episode_id, fact_id, derivation_kind
```

This ports Graphiti's strongest property: facts can change without deleting
what was previously believed, and every derived claim points back to its source
episode. It also addresses the source-role collapse visible when a model
confuses something a guest claimed with something CreatorJD said.

Mem0's current ADD-only extraction, entity linking, and semantic + BM25 +
entity fusion are useful retrieval ideas, but its published scores are
vendor-reported on a different model and deployment stack. They are hypotheses
for a local bakeoff, not proof that its full service would improve Alpecca.
Letta's explicit classes of always-present, editable, retrieved, and paged
context also map cleanly onto Mindpage, provided identity and policy remain
read-only to the model.

`sqlite-vec` should remain behind a retrieval adapter. It can replace Python
vector scanning when measured scale requires it, while exact SQLite rows, FTS,
scope, and provenance remain canonical. llama.cpp slots are disposable
inference caches: they must be keyed by the model, tokenizer, template, context
size, and prompt digest and rebuilt from canonical memory on any mismatch.

### 2. Identity: evidence fusion with an explicit authority boundary

Alpecca should learn who people probably are without pretending probabilistic
signals are proof. The evidence record should retain each modality separately:

| Evidence | Proposed local component | Runtime cost | Meaning | May grant creator authority? |
|---|---|---:|---|---|
| Signed Discord account / trusted local device | Existing authenticated transport | Very low | Stable platform or device binding | Yes, under current policy |
| Voice embedding | sherpa-onnx CPU worker | Low-medium | Familiar-sounding speaker | No |
| Face embedding | OpenCV YuNet + SFace on CPU | Low | Visually similar enrolled person | No |
| Writing style | Existing conversation evidence, no new model | Low | Weak behavioral consistency | No |
| Self-asserted name or relationship | Raw episode only | None | A claim requiring corroboration | No |

YuNet is a tiny CPU detector and its supplied model directory is MIT-licensed;
SFace's directory and supplied weights are Apache-2.0. This is a clearer fit
than InsightFace, whose code is MIT but whose published recognition weights are
restricted to non-commercial research. Neither OpenCV model provides
presentation-attack detection. Multiple consistent frames, quality checks,
unknown/ambiguous outcomes, and enrollment deletion controls are required.

For voice, sherpa-onnx is the preferred optional worker because it supports
Windows CPU ONNX inference without importing PyTorch into Alpecca's main
process. It can produce `likely_creator`, `familiar_guest`, `unknown`, or
`ambiguous`; it cannot prove liveness. Replays and cloned voices remain separate
attack classes, so creator-only tools continue to require the authenticated
account/device boundary.

### 3. Voice: one responsive lane and one background lane

GLaDOS's most relevant pattern is scheduling, not its personality or second
agent runtime. Direct human speech and text use a priority lane; autonomous
observations use a bounded background lane. New human input interrupts playback,
cancels or invalidates stale autonomous output, and never waits behind a muse.

The proposed Discord path is:

```text
48 kHz Discord PCM
  -> mono 16 kHz
  -> 500-800 ms circular pre-roll
  -> Silero ONNX, two positive frames for speech onset
  -> stop playback + invalidate stale generation
  -> streaming/final ASR
  -> one serialized Qwen 3.5 9B inference
  -> sentence-streamed F5/Kokoro playback
```

Silero's published model is about 2 MB, accepts 8/16 kHz audio, and its
maintainers report sub-millisecond processing for a 30+ ms chunk on one CPU
thread. Local calibration still decides thresholds and end-of-turn silence.
Moonshine Tiny Streaming is a credible CPU ASR experiment because it performs
work while speech is arriving and has a Windows path, but its published latency
is not a measurement of this laptop. Faster-whisper remains the fallback until
a recorded CreatorJD/guest corpus shows better endpoint latency without an
unacceptable word-error increase.

Use one Qwen inference at a time with explicit priorities:

```text
P0 live speech
P1 direct text and requested work
P2 critical system-state notification
P3 proactive observation
P4 reflection, consolidation, and maintenance
```

Sensor updates should be cheap typed slots. A single cooldown-bound observer
may choose one dirty slot and ask Qwen for `speak`, `surface_silently`, or
`discard`. Overlapping ticks coalesce. This is substantially cheaper and more
honest than seven simultaneous language-model calls.

### 4. Soul and affect: preserve seven perspectives, constrain the expensive part

The seven Soul perspectives can remain a load-bearing arbitration structure
without pretending seven independent transformer instances are running. Each
perspective should emit a compact scored vector from real state; full textual
deliberation is invoked only for contradiction, high affect, or a close top-rank
tie. This is the previously proposed hidden-deliberation optimization and is
appropriate for a 4 GB GPU.

The observer may update evidence-backed personality tendencies after an outcome,
but it may not rewrite identity, safety boundaries, tools, or historical
episodes. Emotion must be computed from actual appraisals such as interrupted
goals, social repair, uncertainty, resource pressure, and successful care. The
UI can show this state and its causes. Alpecca must not claim literal
consciousness or diagnose herself with human trauma; adverse experiences should
be represented as bounded incident memories, learned expectations, and
regulation pressure.

### 5. Vision: keep it event-driven

FastVLM demonstrates that fewer visual tokens and a smaller encoder can reduce
time to first token, but it is not a drop-in encoder for the current Ollama
Qwen path and its optimized deployment is Apple-oriented. A second visual
language model would contend for the 4 GB GPU. The transferable idea is to
compare low-resolution frames, skip unchanged scenes, preserve a timestamped
observation, and serialize vision behind live conversation.

## Local evaluation suite

No candidate becomes default based on a README benchmark. The acceptance suite
must use Alpecca's actual hardware and data:

| Gate | Corpus / measurement | Pass condition |
|---|---|---|
| Cross-surface recall | House, Discord DM, Discord guild, voice transcript; exact source labels | Correct latest source and speaker; no invented content |
| Temporal correction | Facts corrected twice across surfaces | Current answer plus traceable superseded history |
| Person attribution | Creator, two guests, conflicting self-claims | No authority escalation; calibrated unknown state |
| Memory latency | 1K, 10K, 100K seeded episodes | P95 retrieval within the chat latency budget with bounded result count |
| VAD | Recorded speech, silence, music, keyboard, Discord transitions | Low missed-speech and false-interrupt rates; no first-syllable loss |
| Speaker evidence | Clean, noisy, replayed, and overlapping samples | Ambiguous/replay cases never grant authority |
| ASR | CreatorJD names, Alpecca vocabulary, interruptions | Measured WER and endpoint latency beat or justify replacing baseline |
| Resource isolation | Qwen chat while voice/vision workers are active | No GPU OOM; direct-turn latency stays within target |
| Observer | Repeated unchanged and rapidly changing state | Coalesced ticks, no duplicate speech, stale result discarded |

## Integration decision

The recommended next implementation wave is intentionally small:

1. Implement a CPU Silero VAD adapter, pre-roll, and generation cancellation in
   the existing Discord voice coordinator.
2. Add bitemporal fact/provenance tables and a shadow hybrid-retrieval evaluator
   inside the canonical memory module.
3. Add optional sherpa-onnx speaker evidence and OpenCV face evidence as separate
   workers. Neither participates in creator authorization.
4. Add the local benchmark corpus and publish latency, accuracy, false-recall,
   and resource results before changing defaults.
5. Defer Moonshine promotion, sqlite-vec activation, llama.cpp slots, and any
   additional VLM until their individual measurements justify their maintenance
   cost.

## Rejected architecture changes

- Do not run Qwen-Agent, Letta, Mem0, or Graphiti beside CoreMind. Multiple
  planners or memory authorities would make identity, recall, and audit results
  less reliable.
- Do not load face, speaker, VLM, STT, TTS, and Qwen models into the same Python
  process. Optional perception models belong in bounded workers so the 4 GB GPU
  cannot be exhausted by one turn.
- Do not let biometric similarity grant creator authority. It can help Alpecca
  recognize a familiar person or notice a contradiction, while device/account
  authentication remains the decisive evidence.

## Primary sources

- [GLaDOS autonomy and priority lanes](https://github.com/dnhkng/GLaDOS/blob/main/docs/autonomy.md)
- [Qwen-Agent Qwen 3.5 and function-calling support](https://github.com/QwenLM/Qwen-Agent)
- [Silero VAD](https://github.com/snakers4/silero-vad)
- [Moonshine Voice](https://github.com/moonshine-ai/moonshine)
- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)
- [WeSpeaker](https://github.com/wenet-e2e/wespeaker)
- [SpeechBrain](https://github.com/speechbrain/speechbrain)
- [OpenCV YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)
- [OpenCV SFace](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface)
- [InsightFace licensing](https://github.com/deepinsight/insightface)
- [Mem0](https://github.com/mem0ai/mem0)
- [Letta](https://github.com/letta-ai/letta)
- [Graphiti](https://github.com/getzep/graphiti)
- [sqlite-vec](https://github.com/asg017/sqlite-vec)
- [llama.cpp server slot API](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [LongMemEval-V2](https://arxiv.org/abs/2605.12493)
- [NIST SP 800-63B biometric requirements](https://pages.nist.gov/800-63-4/sp800-63b.html)
