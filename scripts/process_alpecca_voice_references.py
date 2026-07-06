from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf


DEFAULT_VIDEOS = [
    r"C:\Users\Jason\Downloads\20260630_194053739.mp4",
    r"C:\Users\Jason\Downloads\20260630_195021419.mp4",
    r"C:\Users\Jason\Downloads\20260630_195047221.mp4",
    r"C:\Users\Jason\Downloads\20260630_195324819.mp4",
    r"C:\Users\Jason\Downloads\20260630_195236417.mp4",
    r"C:\Users\Jason\Downloads\20260630_195142228.mp4",
]


def ffmpeg_path() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise RuntimeError(
            "imageio-ffmpeg is required. Install with: python -m pip install imageio-ffmpeg"
        ) from exc


def run_ffmpeg(args: list[str]) -> None:
    subprocess.run([ffmpeg_path(), "-y", *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def extract_audio(video: Path, wav: Path) -> bool:
    try:
        run_ffmpeg([
            "-i",
            str(video),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "24000",
            "-af",
            "highpass=f=80,lowpass=f=9000,dynaudnorm=f=150:g=7",
            str(wav),
        ])
        return wav.exists() and wav.stat().st_size > 1024
    except Exception:
        return False


def extract_frame(video: Path, image: Path, at_seconds: float = 1.5) -> bool:
    try:
        run_ffmpeg([
            "-ss",
            str(max(0.0, at_seconds)),
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(image),
        ])
        return image.exists() and image.stat().st_size > 1024
    except Exception:
        return False


def safe_mean(values: list[float]) -> float:
    clean = [float(v) for v in values if math.isfinite(float(v))]
    return round(float(statistics.mean(clean)), 4) if clean else 0.0


def safe_median(values: list[float]) -> float:
    clean = [float(v) for v in values if math.isfinite(float(v))]
    return round(float(statistics.median(clean)), 4) if clean else 0.0


def analyze_wav(wav: Path) -> dict:
    y, sr = librosa.load(wav, sr=24000, mono=True)
    duration = float(librosa.get_duration(y=y, sr=sr))
    if len(y) == 0:
        return {"duration": 0.0}
    rms = librosa.feature.rms(y=y, frame_length=1024, hop_length=256)[0]
    zcr = librosa.feature.zero_crossing_rate(y, frame_length=1024, hop_length=256)[0]
    centroid = librosa.feature.spectral_centroid(y=y, sr=sr, n_fft=1024, hop_length=256)[0]
    bandwidth = librosa.feature.spectral_bandwidth(y=y, sr=sr, n_fft=1024, hop_length=256)[0]
    try:
        f0, _, _ = librosa.pyin(y, fmin=librosa.note_to_hz("C2"), fmax=librosa.note_to_hz("C7"), sr=sr)
        f0_clean = [float(v) for v in f0 if v and math.isfinite(float(v))]
    except Exception:
        f0_clean = []
    voiced_ratio = len(f0_clean) / max(1, len(rms))
    return {
        "duration_seconds": round(duration, 3),
        "sample_rate": sr,
        "rms_mean": safe_mean(rms),
        "rms_median": safe_median(rms),
        "zero_crossing_mean": safe_mean(zcr),
        "spectral_centroid_mean": safe_mean(centroid),
        "spectral_bandwidth_mean": safe_mean(bandwidth),
        "f0_median_hz": safe_median(f0_clean),
        "f0_mean_hz": safe_mean(f0_clean),
        "f0_min_hz": round(float(min(f0_clean)), 3) if f0_clean else 0.0,
        "f0_max_hz": round(float(max(f0_clean)), 3) if f0_clean else 0.0,
        "voiced_ratio": round(float(voiced_ratio), 4),
        "peak": round(float(np.max(np.abs(y))), 4),
    }


def transcribe_wavs(
    wavs: list[Path],
    enabled: bool,
    model_name: str = "base.en",
    vad_filter: bool = False,
) -> dict[str, str]:
    if not enabled:
        return {}
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(model_name, device="cpu", compute_type="int8")
    except Exception as exc:
        return {"_error": f"transcription unavailable: {type(exc).__name__}: {exc}"}
    out: dict[str, str] = {}
    for wav in wavs:
        try:
            segments, _info = model.transcribe(
                str(wav),
                beam_size=5,
                vad_filter=vad_filter,
                language="en",
                condition_on_previous_text=False,
                temperature=0.0,
            )
            text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
            out[wav.stem] = text
        except Exception as exc:
            out[wav.stem] = f"[transcription failed: {type(exc).__name__}: {exc}]"
    return out


def derive_profile(clips: list[dict], transcripts: dict[str, str]) -> dict:
    metrics = [c["analysis"] for c in clips if c.get("analysis")]
    f0 = [m.get("f0_median_hz", 0) for m in metrics if m.get("f0_median_hz", 0) > 0]
    rms = [m.get("rms_median", 0) for m in metrics if m.get("rms_median", 0) > 0]
    centroid = [m.get("spectral_centroid_mean", 0) for m in metrics if m.get("spectral_centroid_mean", 0) > 0]
    all_text = " ".join(v for k, v in transcripts.items() if not k.startswith("_")).strip()
    return {
        "identity": "Alpecca voice/personality reference set from Jason-provided videos",
        "speaker_lock": "Kokoro af_heart remains the base voice; these clips guide modulation, pacing, text shaping, and visual personality.",
        "target_quality": {
            "voice": "soft, close, emotionally present, feminine/anime-adjacent, less robotic",
            "interaction": "directly responsive to Jason, grounded in current input, curious without inventing events",
            "visualization": "large readable profile presence, expressive face/mouth timing, and clear embodied focus on Jason",
        },
        "acoustic_summary": {
            "median_f0_hz": safe_median(f0),
            "mean_f0_hz": safe_mean(f0),
            "median_rms": safe_median(rms),
            "mean_spectral_centroid": safe_mean(centroid),
            "clip_count": len(clips),
            "total_seconds": round(sum(c.get("analysis", {}).get("duration_seconds", 0.0) for c in clips), 3),
        },
        "tts_guidance": {
            "kokoro_voice": "af_heart",
            "identity_lock": True,
            "prefer_server_voice": True,
            "browser_fallback_allowed": False,
            "naturalization": {
                "speed_bias": "slightly slower than default when tender or thoughtful",
                "breath": "subtle, only to soften hard robotic gating",
                "pitch": "do not over-pitch; preserve af_heart timbre",
                "volume": "gentle limiter, no harsh peaks",
            },
        },
        "personality_notes": {
            "must_not": [
                "echo Jason's message as the reply",
                "claim events that did not happen",
                "sound like a generic assistant",
                "expose voice settings as if viewers can change who she is",
            ],
            "should": [
                "answer Jason normally first",
                "speak with warm self-presence",
                "ask grounded questions from what she actually sees/remembers",
                "show her profile clearly while speaking",
            ],
            "transcript_excerpt": all_text[:1200],
        },
    }


def write_markdown(path: Path, profile: dict, clips: list[dict], transcripts: dict[str, str]) -> None:
    lines = [
        "# Alpecca Voice And Personality Reference",
        "",
        "This file was generated from Jason-provided video references.",
        "",
        "## Target",
        f"- Voice: {profile['target_quality']['voice']}",
        f"- Interaction: {profile['target_quality']['interaction']}",
        f"- Visualization: {profile['target_quality']['visualization']}",
        "",
        "## Acoustic Summary",
    ]
    for key, value in profile["acoustic_summary"].items():
        lines.append(f"- {key}: {value}")
    lines += ["", "## TTS Guidance"]
    for key, value in profile["tts_guidance"].items():
        lines.append(f"- {key}: {json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value}")
    lines += ["", "## Clip Inventory"]
    for clip in clips:
        a = clip.get("analysis", {})
        lines.append(
            f"- {clip['source_name']}: {a.get('duration_seconds', 0)}s, "
            f"f0 median {a.get('f0_median_hz', 0)} Hz, rms {a.get('rms_median', 0)}"
        )
    if transcripts:
        lines += ["", "## Transcripts"]
        for key, text in transcripts.items():
            lines.append(f"### {key}")
            lines.append(text or "[no speech detected]")
            lines.append("")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/voice_references")
    parser.add_argument("--transcribe", action="store_true")
    parser.add_argument("--whisper-model", default="base.en")
    parser.add_argument("--vad", action="store_true")
    parser.add_argument("videos", nargs="*")
    args = parser.parse_args()

    out = Path(args.out)
    audio_dir = out / "audio"
    frame_dir = out / "frames"
    audio_dir.mkdir(parents=True, exist_ok=True)
    frame_dir.mkdir(parents=True, exist_ok=True)

    videos = [Path(v) for v in (args.videos or DEFAULT_VIDEOS)]
    clips = []
    wavs = []
    for video in videos:
        if not video.exists():
            clips.append({"source": str(video), "source_name": video.name, "missing": True})
            continue
        stem = video.stem
        wav = audio_dir / f"{stem}.wav"
        frame = frame_dir / f"{stem}.jpg"
        ok_audio = extract_audio(video, wav)
        ok_frame = extract_frame(video, frame)
        analysis = analyze_wav(wav) if ok_audio else {}
        if ok_audio:
            wavs.append(wav)
        clips.append({
            "source": str(video),
            "source_name": video.name,
            "audio": str(wav) if ok_audio else "",
            "frame": str(frame) if ok_frame else "",
            "analysis": analysis,
        })

    transcripts = transcribe_wavs(
        wavs,
        args.transcribe,
        model_name=args.whisper_model,
        vad_filter=args.vad,
    )
    profile = derive_profile(clips, transcripts)
    payload = {"profile": profile, "clips": clips, "transcripts": transcripts}
    (out / "alpecca_voice_personality_profile.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    write_markdown(out / "Alpecca_Voice_Personality_Profile.md", profile, clips, transcripts)
    print(json.dumps({
        "out": str(out),
        "clips": len(clips),
        "audio": len(wavs),
        "transcribed": bool(transcripts) and "_error" not in transcripts,
        "profile": str(out / "Alpecca_Voice_Personality_Profile.md"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
