"""Ingest Jason-provided Alpecca clips for BOTH voice cloning and character animation.

Each uploaded clip is a short Kling AI Alpecca video (her look + her voice). This
one-shot importer turns a folder of those clips into two reference sets:

  1. Voice (F5-TTS reference material):
       - extracts mono 24 kHz audio  -> data/voice_references/audio/<name>.wav
       - transcribes it (faster-whisper) so F5 gets matched ref_text
       - prints ready-to-paste REFERENCE_SPECS entries for prepare_open_tts_refs.py

  2. Animation (character motion/expression reference):
       - copies the master clip       -> data/character/reference/animation_clips/<name>.mp4
       - lays down a frame sheet       -> data/character/reference/animation_clips/frames/<name>/
       - records an index.json describing every clip

Everything lands under data/ (git-ignored), so the personal media never enters git.

Usage:
    python scripts/ingest_alpecca_reference_uploads.py <folder-of-mp4s> [more files/dirs...]
    python scripts/ingest_alpecca_reference_uploads.py clip1.mp4 clip2.mp4

Uploaded names look like "<hash>-20260630_195021419.mp4"; the hash prefix is
stripped so the clean timestamp name matches the existing voice pipeline.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIO_DIR = ROOT / "data" / "voice_references" / "audio"
ANIM_DIR = ROOT / "data" / "character" / "reference" / "animation_clips"
FRAME_DIR = ANIM_DIR / "frames"
INDEX = ANIM_DIR / "index.json"

FRAME_EVERY_SECONDS = 1.2
MAX_FRAMES = 14
WHISPER_MODEL = "base.en"          # override via ALPECCA_WHISPER_MODEL


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise RuntimeError(
            "imageio-ffmpeg is required: python -m pip install imageio-ffmpeg"
        ) from exc


def run_ffmpeg(args: list[str]) -> None:
    subprocess.run([ffmpeg_exe(), "-y", *args], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def clean_name(path: Path) -> str:
    """"<hash>-20260630_195021419.mp4" -> "20260630_195021419"."""
    stem = path.stem
    m = re.match(r"^[0-9a-f]{6,}-(.+)$", stem)
    return m.group(1) if m else stem


def gather_inputs(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            out.extend(sorted(p.glob("*.mp4")) + sorted(p.glob("*.mov"))
                       + sorted(p.glob("*.webm")))
        elif p.exists():
            out.append(p)
        else:
            print(f"  ! not found: {p}", file=sys.stderr)
    return out


def extract_audio(video: Path, wav: Path) -> bool:
    if wav.exists() and wav.stat().st_size > 1024:
        return True
    wav.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "-i", str(video), "-vn", "-ac", "1", "-ar", "24000",
        "-af", "highpass=f=80,lowpass=f=9000,dynaudnorm=f=150:g=7",
        str(wav),
    ])
    return wav.exists() and wav.stat().st_size > 1024


def extract_frames(video: Path, out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("f*.jpg"):
        old.unlink()
    run_ffmpeg([
        "-i", str(video),
        "-vf", f"fps=1/{FRAME_EVERY_SECONDS}",
        "-frames:v", str(MAX_FRAMES), "-q:v", "3",
        str(out_dir / "f%02d.jpg"),
    ])
    return len(list(out_dir.glob("f*.jpg")))


_MODEL = None


def transcribe(wav: Path) -> tuple[str, float]:
    global _MODEL
    if _MODEL is None:
        import os
        from faster_whisper import WhisperModel
        name = os.environ.get("ALPECCA_WHISPER_MODEL", WHISPER_MODEL)
        print(f"  loading faster-whisper model {name!r} (cpu/int8)...")
        _MODEL = WhisperModel(name, device="cpu", compute_type="int8")
    segments, info = _MODEL.transcribe(str(wav), language="en", beam_size=5)
    text = " ".join(seg.text.strip() for seg in segments).strip()
    text = re.sub(r"\s+", " ", text)
    return text, float(getattr(info, "duration", 0.0) or 0.0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+", help="mp4 files or folders of clips")
    ap.add_argument("--no-transcribe", action="store_true",
                    help="skip speech-to-text (voice ref_text left blank)")
    args = ap.parse_args()

    videos = gather_inputs(args.inputs)
    if not videos:
        print("No input clips found.", file=sys.stderr)
        return 1

    ANIM_DIR.mkdir(parents=True, exist_ok=True)
    index: list[dict] = []
    specs: list[dict] = []

    for video in videos:
        name = clean_name(video)
        print(f"\n== {video.name}  ->  {name} ==")

        master = ANIM_DIR / f"{name}.mp4"
        if master.resolve() != video.resolve():
            master.write_bytes(video.read_bytes())
        print(f"  animation master: {master.relative_to(ROOT)}")

        frames = extract_frames(video, FRAME_DIR / name)
        print(f"  animation frames: {frames} -> {(FRAME_DIR / name).relative_to(ROOT)}")

        wav = AUDIO_DIR / f"{name}.wav"
        had_audio = wav.exists()
        audio_ok = extract_audio(video, wav)
        print(f"  voice audio:      {'existing' if had_audio else 'extracted'} "
              f"{'ok' if audio_ok else 'FAILED'} -> {wav.relative_to(ROOT)}")

        text, duration = ("", 0.0)
        if audio_ok and not args.no_transcribe:
            text, duration = transcribe(wav)
            print(f"  transcript ({duration:.1f}s): {text!r}")

        index.append({
            "name": name,
            "source_upload": video.name,
            "animation_master": str(master.relative_to(ROOT)),
            "frames_dir": str((FRAME_DIR / name).relative_to(ROOT)),
            "frame_count": frames,
            "voice_audio": str(wav.relative_to(ROOT)) if audio_ok else "",
            "duration_seconds": round(duration, 2),
            "transcript": text,
        })
        if audio_ok:
            specs.append({
                "id": f"clip_{name.split('_')[-1]}",
                "roles": ["REVIEW"],   # assign real emotion roles before use
                "source": wav.name,
                "text": text,
                "max_seconds": round(min(12.0, duration or 12.0), 1),
            })

    INDEX.write_text(json.dumps({"clips": index}, indent=2), encoding="utf-8")
    print(f"\nWrote animation index: {INDEX.relative_to(ROOT)} ({len(index)} clips)")

    print("\n--- Proposed REFERENCE_SPECS entries (add real 'roles', then run "
          "prepare_open_tts_refs.py) ---")
    print(json.dumps(specs, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
