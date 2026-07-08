# Mindpage — Disk- and Pagefile-Powered Memory for Alpecca (Layers B & C setup)

Companion doc to `AGENTIC_ASSESSMENT.md` Stage 6. Layer A (software paging, pressure senses) is code in `alpecca/mindpage.py` when implemented. This doc covers the two layers that are configuration + infrastructure rather than Alpecca code. Everything here is fully open source.

## Layer B — Her brain state on the hard drive (KV-cache persistence)

Ollama does not expose KV-cache save/restore, so this layer uses **llama.cpp's `llama-server`** (MIT licensed) as an opt-in backend.

1. Download/build llama-server (Windows release zips exist; no compile needed).
2. Start it with slot persistence pointed at the data drive:
   ```
   llama-server -m <model.gguf> -c 8192 --slot-save-path data\mindpage\kv\
   ```
3. Save/restore a slot over HTTP:
   ```
   POST /slots/0?action=save     {"filename": "alpecca_slot.bin"}
   POST /slots/0?action=restore  {"filename": "alpecca_slot.bin"}
   ```
   Documented example: 1745 tokens → ~14.3 MB on disk (~8.2 KB/token; a full 8K context ≈ 65 MB). Community-measured warm restore is ~7× faster than re-processing the prompt.
4. Prefix caching is ON by default in llama-server — Alpecca's fixed persona scaffolding is processed once; each turn only re-processes the changed suffix.
5. Alpecca side (future flag): `ALPECCA_LLM_BACKEND=llamacpp` + save-on-shutdown / restore-on-wake hooks in the server lifespan. Default stays `ollama` with `keep_alive=30m`.

## Layer C — Pagefile-powered deep brain (bigger model than RAM)

llama.cpp (and Ollama, which embeds it) **memory-maps model weights by default**: the OS pages weights in from disk on demand instead of loading the whole file into RAM. With a large Windows paging file, a quantized model bigger than physical RAM can run — slowly — because the OS pagefile machinery backs the overflow. Alpecca's background deep-reflection tier already tolerates 600-second timeouts (`REFLECT_TIMEOUT_SECONDS`, `config.py:166`), so slow-but-deep is acceptable there. Never route live chat to this tier.

Setup on Windows:
1. **Pagefile**: System Properties → Advanced → Performance Settings → Advanced → Virtual memory. Put a large custom pagefile (e.g. 32–64 GB) on the fastest drive with free space — SSD strongly preferred; an HDD pagefile works but deep ticks will take minutes.
2. **Model**: pull a bigger open-weight tag for the deep tier, e.g. a larger quantized qwen3.5 GGUF (the live chat model is qwen3.5:9b — the deep tier should be a bigger sibling). Smaller quants (q4) page less.
3. **Alpecca env** (future flag): `ALPECCA_DEEP_LOCAL_MODEL=<big tag>` so `tier="deep"` self-acts (musings, self-questioning, identity authorship) route to the big mmap'd model, fully local.
4. **VRAM caveats — keep these rules** (from `config.py:74-84`, verbatim intent): Ollama's VRAM estimator is conservative for some GGUFs; on a 4 GB card pinning layers via `ALPECCA_NUM_GPU` can double-to-quadruple speed, BUT a value needing more VRAM than free makes the model fail to load (echo fallback), and pinned layers starve the F5 voice and vision models. `START_HERE.bat` deliberately leaves GPU placement on AUTO — do not set `ALPECCA_NUM_GPU` while voice is on the GPU.

## Budget knobs (Layer A, for reference)

- `ALPECCA_MINDPAGE=1` — software paging on/off.
- `ALPECCA_MINDPAGE_DISK_GB` — cap on the page-store; the pressure sense reports usage against it.
- Pressure reading = context fill %, turns-until-history-eviction, unsummarized-evict backlog, hot-tier size, disk usage. Routed through the Soul's Feeler/Carer (sense) → Reflector/Improver (reason) so awareness → decision → relief stays inside the seven-subagent arbitration.
