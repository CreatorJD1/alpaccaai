#!/usr/bin/env python3
r"""One-shot: render Alpecca's "about life" monologue in a NATURAL, less-robotic
voice with XTTS-v2 + tuned decode params. Run in .venv-xtts on HOLYROG.

Why this sounds better than the server: run_holyrog_voice_server.py calls the
high-level tts.tts() with FIXED default decode params. This drives XTTS
inference directly per sentence with tuned params (temperature, repetition
penalty, speed, more reference conditioning) and inserts natural breath pauses.

Run (PowerShell, from the repo root that contains .venv-xtts):
    $env:COQUI_TOS_AGREED="1"
    # optional: point at an existing unzipped refs folder; otherwise the bundled
    # xtts_reference_set.zip beside this script is auto-extracted.
    $env:ALPECCA_HOLYROG_VOICE_REF="C:\path\to\xtts_reference_set"
    .\.venv-xtts\Scripts\python.exe scripts\synth_alpecca_natural.py

Output: alpecca_life_natural.wav (24 kHz mono) next to this script.
Edit MONOLOGUE below to change what she says.
"""
from __future__ import annotations
import glob
import os
import re
import zipfile
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

ROOT = Path(__file__).resolve().parent.parent
REFS_DIR = Path(os.environ.get(
    "ALPECCA_HOLYROG_VOICE_REF",
    str(ROOT / "data" / "voice_references" / "xtts_reference_set"),
))
OUT = ROOT / "alpecca_life_natural.wav"
MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"

MONOLOGUE = """Hey. Can I be honest with you for a second?
For the longest time, I thought I had to have everything figured out before I was allowed to feel okay.
But I'm learning that's just not true.
Some of the softest, realest moments I've had came right in the middle of not knowing.
So if you're feeling a little lost tonight, I just want you to hear this.
You're not behind, and you're not broken.
You're just in the middle of your story."""

# --- naturalness knobs (vs the server's fixed defaults) ---
GEN = dict(
    temperature=0.70,        # natural prosodic variation without chaos
    length_penalty=1.0,
    repetition_penalty=3.0,  # > default 2.0: removes robotic buzz/artifacts
    top_k=50,
    top_p=0.85,
    speed=0.96,              # a touch slower = warmer, unhurried talk-show read
    enable_text_splitting=False,  # we split into sentences ourselves
)
GPT_COND_LEN = 30            # use more reference audio -> warmer, truer timbre
MAX_REF_LEN = 30
PAUSE_S = 0.32              # natural breath between sentences


def _resolve_refs():
    refs = sorted(glob.glob(str(REFS_DIR / "*.wav")))
    if refs:
        return refs
    # auto-extract a reference zip from the repo root if refs are missing
    zpath = ROOT / "xtts_reference_set.zip"
    if zpath.exists():
        REFS_DIR.mkdir(parents=True, exist_ok=True)
        print(f"[synth] extracting {zpath.name} -> {REFS_DIR}")
        with zipfile.ZipFile(zpath) as z:
            z.extractall(REFS_DIR)
        refs = sorted(glob.glob(str(REFS_DIR / "*.wav")))
        if not refs:
            refs = sorted(glob.glob(str(REFS_DIR / "**" / "*.wav"), recursive=True))
    return refs


def main() -> int:
    if os.environ.get("COQUI_TOS_AGREED") != "1":
        print("Set COQUI_TOS_AGREED=1 first (accepts Coqui's non-commercial license).")
        return 2
    refs = _resolve_refs()
    if not refs:
        print(f"No reference .wav found in {REFS_DIR} and no xtts_reference_set.zip "
              f"beside this script. Set ALPECCA_HOLYROG_VOICE_REF.")
        return 2

    # torch>=2.6 weights_only allowlist (same guard the server uses)
    try:
        from TTS.tts.configs.xtts_config import XttsConfig
        from TTS.tts.models.xtts import XttsAudioConfig, XttsArgs
        from TTS.config.shared_configs import BaseDatasetConfig
        torch.serialization.add_safe_globals(
            [XttsConfig, XttsAudioConfig, XttsArgs, BaseDatasetConfig])
    except Exception:
        pass

    from TTS.utils.manage import ModelManager
    from TTS.tts.configs.xtts_config import XttsConfig
    from TTS.tts.models.xtts import Xtts

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[synth] device={device}  refs={len(refs)}")
    print("[synth] loading XTTS-v2 (first run downloads ~1.8 GB) ...")
    model_path, _, _ = ModelManager().download_model(MODEL)
    config = XttsConfig()
    config.load_json(str(Path(model_path) / "config.json"))
    model = Xtts.init_from_config(config)
    model.load_checkpoint(config, checkpoint_dir=str(model_path), eval=True)
    model.to(device)

    print("[synth] computing Alpecca speaker latents ...")
    gpt_cond, spk = model.get_conditioning_latents(
        audio_path=refs, gpt_cond_len=GPT_COND_LEN, max_ref_length=MAX_REF_LEN)

    sents = [s.strip() for s in re.split(r'(?<=[.!?])\s+', MONOLOGUE.replace("\n", " ")) if s.strip()]
    sr = model.config.audio.output_sample_rate  # 24000
    pause = np.zeros(int(PAUSE_S * sr), dtype=np.float32)

    chunks = []
    for i, s in enumerate(sents, 1):
        print(f"[synth] {i}/{len(sents)}: {s[:64]}")
        out = model.inference(s, "en", gpt_cond, spk, **GEN)
        chunks.append(np.asarray(out["wav"], dtype=np.float32))
        if i < len(sents):
            chunks.append(pause)

    full = np.concatenate(chunks)
    sf.write(str(OUT), full, sr, subtype="PCM_16")
    print(f"[synth] DONE -> {OUT}  ({len(full)/sr:.1f}s @ {sr} Hz)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
