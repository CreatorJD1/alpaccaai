"""Warm Alpecca's high-quality open TTS path.

This is deliberately separate from server startup. F5-TTS is much heavier than
Kokoro and must download/checkpoint-load successfully once before House HQ uses
it for live speech. On success it writes:

  data/voice_references/generated_samples/alpecca_f5_open_tts_sample.wav

After that, /voice reports open_tts.ready=true and auto TTS may prefer F5.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (
    OPEN_TTS_DEVICE,
    OPEN_TTS_LOCAL_MODEL_DIR,
    OPEN_TTS_NFE_STEP,
    OPEN_TTS_PYTHON,
    OPEN_TTS_TIMEOUT,
)
from alpecca import open_tts

MODEL_FILES = {
    "model_1250000.safetensors": "https://huggingface.co/SWivid/F5-TTS/resolve/main/F5TTS_v1_Base/model_1250000.safetensors",
    "vocab.txt": "https://huggingface.co/SWivid/F5-TTS/resolve/main/F5TTS_v1_Base/vocab.txt",
}


def _cli() -> list[str]:
    direct = shutil.which("f5-tts_infer-cli")
    if direct:
        return [direct]
    py = Path(OPEN_TTS_PYTHON) if OPEN_TTS_PYTHON else sys.executable
    return [str(py), "-m", "f5_tts.infer.infer_cli"]


def _download_file(url: str, dest: Path, *, timeout: float = 30.0) -> None:
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if curl:
        dest.parent.mkdir(parents=True, exist_ok=True)
        config_path = dest.with_suffix(dest.suffix + ".curl.cfg")
        cmd = [
            curl,
            "--config",
            str(config_path),
            "-L",
            "-C",
            "-",
            "--retry",
            "30",
            "--retry-delay",
            "5",
            "--connect-timeout",
            "30",
            "--speed-time",
            "120",
            "--speed-limit",
            "1024",
            "-o",
            str(dest),
        ]
        hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACEHUB_API_TOKEN")
        config_lines = [f'url = "{url}"']
        if hf_token:
            config_lines.append(f'header = "Authorization: Bearer {hf_token}"')
        config_path.write_text("\n".join(config_lines) + "\n", encoding="utf-8")
        print("  curl:", " ".join(cmd), flush=True)
        try:
            proc = subprocess.run(cmd, cwd=str(ROOT))
            if proc.returncode != 0:
                raise RuntimeError(f"curl failed with exit code {proc.returncode}")
        finally:
            config_path.unlink(missing_ok=True)
        return

    import requests

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    downloaded = tmp.stat().st_size if tmp.exists() else 0
    headers = {}
    if downloaded:
        headers["Range"] = f"bytes={downloaded}-"
    with requests.get(url, stream=True, headers=headers, timeout=timeout, allow_redirects=True) as resp:
        if resp.status_code == 416:
            tmp.replace(dest)
            return
        resp.raise_for_status()
        if downloaded and resp.status_code != 206:
            downloaded = 0
            tmp.unlink(missing_ok=True)
        total_header = resp.headers.get("Content-Length")
        total = int(total_header) + downloaded if total_header and resp.status_code == 206 else int(total_header or 0)
        mode = "ab" if downloaded else "wb"
        last = time.monotonic()
        start = last
        with tmp.open(mode + "") as fh:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                fh.write(chunk)
                downloaded += len(chunk)
                now = time.monotonic()
                if now - last >= 5:
                    mb = downloaded / 1048576
                    if total:
                        print(f"  {dest.name}: {mb:.1f}/{total / 1048576:.1f} MB")
                    else:
                        print(f"  {dest.name}: {mb:.1f} MB")
                    last = now
        elapsed = max(0.001, time.monotonic() - start)
        print(f"  {dest.name}: downloaded {downloaded / 1048576:.1f} MB at {(downloaded / 1048576) / elapsed:.2f} MB/s", flush=True)
    tmp.replace(dest)


def direct_download_model(*, clean: bool = False) -> None:
    model_dir = Path(OPEN_TTS_LOCAL_MODEL_DIR)
    if clean and model_dir.exists():
        for path in model_dir.glob("*.part"):
            print(f"Removing partial local download: {path}")
            path.unlink()
    print(f"Downloading F5 model files into {model_dir}")
    for name, url in MODEL_FILES.items():
        dest = model_dir / name
        if dest.exists() and (name == "vocab.txt" or dest.stat().st_size > 1000 * 1024 * 1024):
            print(f"  {name}: already present ({dest.stat().st_size / 1048576:.1f} MB)")
            continue
        _download_file(url, dest)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", default="Jason, I'm here. I sound like myself, a little softer now.")
    parser.add_argument("--preview", default="tender")
    parser.add_argument("--timeout", type=float, default=max(180.0, OPEN_TTS_TIMEOUT))
    parser.add_argument("--nfe-step", type=int, default=OPEN_TTS_NFE_STEP)
    parser.add_argument("--device", default=OPEN_TTS_DEVICE)
    parser.add_argument(
        "--clean-incomplete",
        action="store_true",
        help="Delete partial F5 Hugging Face blobs before retrying the warmup.",
    )
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="Download the F5 model files, then exit before synthesis.",
    )
    parser.add_argument(
        "--hf-snapshot",
        action="store_true",
        help="Use huggingface_hub snapshot_download instead of Alpecca's direct resumable downloader.",
    )
    args = parser.parse_args()

    if args.clean_incomplete:
        cache = open_tts._f5_model_cache_status()
        for item in cache.get("incomplete", []):
            path = Path(item.get("path", ""))
            if path.exists() and path.name.endswith(".incomplete"):
                print(f"Removing partial F5 blob: {path}")
                path.unlink()

    if args.download_only:
        if not args.hf_snapshot:
            direct_download_model(clean=args.clean_incomplete)
            print("Download attempt complete. F5 status:")
            print(json.dumps(open_tts.status(), indent=2)[:4000])
            return 0
        try:
            from huggingface_hub import snapshot_download
        except Exception as exc:
            print(f"huggingface_hub is required for --download-only: {exc}", file=sys.stderr)
            return 2
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        print("Downloading F5-TTS snapshot from SWivid/F5-TTS...")
        snapshot_download(
            "SWivid/F5-TTS",
            allow_patterns=[
                "F5TTS_v1_Base/model_1250000.safetensors",
                "F5TTS_v1_Base/vocab.txt",
                "F5TTS_v1_Base/*.yaml",
                "*.yaml",
                "*.txt",
            ],
            resume_download=True,
        )
        print("Download attempt complete. Cache status:")
        print(json.dumps(open_tts.status().get("cache", {}), indent=2))
        return 0

    ref = open_tts.select_reference(preview=args.preview)
    if not ref:
        print("No F5 reference found. Run scripts\\prepare_open_tts_refs.py first.", file=sys.stderr)
        return 2

    ref_audio = Path(str(ref["audio"]))
    if not ref_audio.is_absolute():
        ref_audio = ROOT / ref_audio
    out = open_tts.READY_SAMPLE
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        *_cli(),
        "--model",
        "F5TTS_v1_Base",
        "--ref_audio",
        str(ref_audio),
        "--ref_text",
        str(ref.get("text", "")),
        "--gen_text",
        args.text,
        "--output_file",
        str(out),
        "--device",
        args.device,
        "--nfe_step",
        str(max(4, args.nfe_step)),
    ]
    if open_tts.LOCAL_CKPT.exists() and open_tts.LOCAL_CKPT.stat().st_size > 1000 * 1024 * 1024:
        cmd.extend(["--ckpt_file", str(open_tts.LOCAL_CKPT)])
        if open_tts.LOCAL_VOCAB.exists():
            cmd.extend(["--vocab_file", str(open_tts.LOCAL_VOCAB)])
    print("F5 warmup reference:", json.dumps({"id": ref.get("id"), "roles": ref.get("roles")}))
    print("F5 warmup command:", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            env=open_tts._subprocess_env(),
            text=True,
            timeout=args.timeout,
        )
    except subprocess.TimeoutExpired:
        print(
            f"F5 warmup timed out after {args.timeout:.0f}s. "
            "The model cache may still be downloading or the GPU may be out of memory.",
            file=sys.stderr,
        )
        return 124
    if proc.returncode != 0:
        return proc.returncode
    if not out.exists() or out.stat().st_size < 1024:
        print(f"F5 warmup did not create usable audio at {out}", file=sys.stderr)
        return 3
    print(f"F5 ready sample created: {out} ({out.stat().st_size} bytes)")
    print("Restart server.py, then /voice should report open_tts.ready=true.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
