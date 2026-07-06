"""Preflight a Stage 4 tile worker before spending GPU time.

This does not generate art. It checks the selected job slice, Hugging Face
access, PyTorch/CUDA visibility, expected 4K contract, and current low-VRAM
settings so a Colab or remote GPU run can fail fast before a multi-hour attempt.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from run_alpecca_stage4_tile_worker import download_hf_file, load_jsonl


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HF_REPO = "CREATORJD/alpecca-art-library"
DEFAULT_HF_PATH = "stage4-tile-jobs/first_slices/idle_eye_16sector_frame000_turnaround/tile_jobs_idle_eye_16sector_frame000_turnaround.jsonl"
DEFAULT_REPORT = REPO_ROOT / "output" / "alpecca_stage4_tile_jobs" / "worker_preflight_report.json"
LOW_VRAM_ENV = (
    "ALPECCA_TILE_MEMORY_MODE",
    "ALPECCA_TILE_ENABLE_ATTENTION_SLICING",
    "ALPECCA_TILE_ENABLE_VAE_SLICING",
    "ALPECCA_TILE_ENABLE_VAE_TILING",
    "ALPECCA_TILE_ENABLE_XFORMERS",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def inspect_hf_auth(repo_id: str, repo_type: str) -> dict[str, Any]:
    try:
        from huggingface_hub import HfApi
    except ImportError as error:
        return {"ok": False, "error": f"huggingface_hub missing: {error}"}
    token_present = bool(os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACEHUB_API_TOKEN"))
    info: dict[str, Any] = {"ok": False, "tokenPresent": token_present, "repoId": repo_id, "repoType": repo_type}
    try:
        api = HfApi()
        repo = api.repo_info(repo_id=repo_id, repo_type=repo_type)
        info.update({"ok": True, "private": bool(getattr(repo, "private", False)), "sha": getattr(repo, "sha", "")})
    except Exception as error:
        info["error"] = f"{type(error).__name__}: {error}"
    return info


def inspect_torch() -> dict[str, Any]:
    try:
        import torch
    except ImportError as error:
        return {"installed": False, "cuda": False, "error": str(error)}
    info: dict[str, Any] = {
        "installed": True,
        "version": getattr(torch, "__version__", ""),
        "cuda": bool(torch.cuda.is_available()),
        "deviceCount": int(torch.cuda.device_count()) if torch.cuda.is_available() else 0,
        "devices": [],
    }
    if torch.cuda.is_available():
        for index in range(torch.cuda.device_count()):
            try:
                props = torch.cuda.get_device_properties(index)
                info["devices"].append({
                    "index": index,
                    "name": props.name,
                    "totalGpuMemoryGb": round(props.total_memory / (1024 ** 3), 2),
                    "major": props.major,
                    "minor": props.minor,
                })
            except Exception as error:
                info["devices"].append({"index": index, "error": f"{type(error).__name__}: {error}"})
    return info


def inspect_diffusers() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for module in ("diffusers", "transformers", "accelerate", "safetensors"):
        try:
            imported = __import__(module)
            out[module] = {"installed": True, "version": getattr(imported, "__version__", "")}
        except ImportError as error:
            out[module] = {"installed": False, "error": str(error)}
    return out


def inspect_jobs(jobs_path: Path, offset: int, limit: int | None) -> dict[str, Any]:
    jobs = load_jsonl(jobs_path)
    selected = jobs[offset : offset + limit if limit is not None else None]
    sizes = sorted({tuple(job.get("expectedSize", [])) for job in selected})
    sectors = sorted(
        {str(job.get("viewSector16") or "") for job in selected if str(job.get("viewSector16") or "")},
        key=lambda value: int(value[1:]) if value.startswith("s") and value[1:].isdigit() else 999,
    )
    return {
        "path": str(jobs_path),
        "totalJobs": len(jobs),
        "selectedJobs": len(selected),
        "offset": offset,
        "limit": limit,
        "expectedSizes": [list(size) for size in sizes],
        "allSelectedNative4096": bool(selected) and all(tuple(job.get("expectedSize", [])) == (4096, 4096) for job in selected),
        "sectors": sectors,
        "sectorCount": len(sectors),
        "firstJob": {
            "jobId": selected[0].get("jobId"),
            "matrixKey": selected[0].get("matrixKey"),
            "targetId": selected[0].get("targetId"),
        } if selected else None,
    }


def readiness_checks(hf: dict[str, Any], torch: dict[str, Any], diffusers: dict[str, Any], jobs: dict[str, Any], strict_native_4k: bool) -> list[dict[str, Any]]:
    gpu_memory = 0.0
    for device in torch.get("devices") or []:
        gpu_memory = max(gpu_memory, float(device.get("totalGpuMemoryGb") or 0.0))
    checks = [
        {"id": "hf_access", "ok": bool(hf.get("ok")), "detail": hf.get("error", "HF repo is reachable.")},
        {"id": "torch_installed", "ok": bool(torch.get("installed")), "detail": torch.get("version", torch.get("error", ""))},
        {"id": "cuda_visible", "ok": bool(torch.get("cuda")), "detail": f"{len(torch.get('devices') or [])} CUDA device(s)"},
        {"id": "diffusers_installed", "ok": bool(diffusers.get("diffusers", {}).get("installed")), "detail": diffusers.get("diffusers", {}).get("version", "")},
        {"id": "job_slice_present", "ok": int(jobs.get("selectedJobs") or 0) > 0, "detail": f"{jobs.get('selectedJobs')} selected job(s)"},
        {"id": "native_4096_contract", "ok": bool(jobs.get("allSelectedNative4096")) if strict_native_4k else True, "detail": str(jobs.get("expectedSizes"))},
        {
            "id": "low_vram_mode",
            "ok": os.environ.get("ALPECCA_TILE_MEMORY_MODE", "low_vram").strip().lower() in {"low_vram", "sequential"},
            "detail": os.environ.get("ALPECCA_TILE_MEMORY_MODE", "low_vram"),
        },
        {
            "id": "gpu_memory_warning",
            "ok": gpu_memory >= 14.0,
            "warning": gpu_memory > 0 and gpu_memory < 14.0,
            "detail": f"largest GPU memory {gpu_memory:.2f} GB; native 4096 SDXL may still fail on small GPUs.",
        },
    ]
    return checks


def run_preflight(
    *,
    jobs: Path | None,
    hf_path: str | None,
    hf_repo: str,
    hf_repo_type: str,
    hf_revision: str | None,
    offset: int,
    limit: int | None,
    report_path: Path,
    strict_native_4k: bool,
) -> dict[str, Any]:
    jobs_path = jobs
    if hf_path:
        jobs_path = download_hf_file(hf_repo, hf_path, hf_repo_type, hf_revision)
    if jobs_path is None:
        raise ValueError("jobs or hf_path is required")
    hf = inspect_hf_auth(hf_repo, hf_repo_type)
    torch_info = inspect_torch()
    diffusers = inspect_diffusers()
    jobs_info = inspect_jobs(jobs_path, offset, limit)
    memory_env = {name: os.environ.get(name, "") for name in LOW_VRAM_ENV}
    checks = readiness_checks(hf, torch_info, diffusers, jobs_info, strict_native_4k)
    blocking = [check for check in checks if not check.get("ok") and not check.get("warning")]
    warnings = [check for check in checks if check.get("warning")]
    report = {
        "schemaVersion": 1,
        "stage": "stage-4-tile-worker-preflight",
        "generatedAt": utc_now(),
        "status": "ready" if not blocking else "blocked",
        "ready": not blocking,
        "blockingCount": len(blocking),
        "warningCount": len(warnings),
        "strictNative4k": strict_native_4k,
        "hf": hf,
        "torch": torch_info,
        "diffusers": diffusers,
        "jobs": jobs_info,
        "memoryEnv": memory_env,
        "checks": checks,
        "nextStep": (
            "Run the Stage 4 tile worker for the selected slice, then upload outputs to Hugging Face."
            if not blocking else
            "Fix blocking checks before starting a long GPU generation run."
        ),
    }
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--jobs", type=Path)
    source.add_argument("--hf-path", default=DEFAULT_HF_PATH)
    parser.add_argument("--hf-repo", default=DEFAULT_HF_REPO)
    parser.add_argument("--hf-repo-type", default="dataset")
    parser.add_argument("--hf-revision")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=16)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--allow-non-4096", action="store_true")
    args = parser.parse_args()
    report = run_preflight(
        jobs=args.jobs,
        hf_path=args.hf_path,
        hf_repo=args.hf_repo,
        hf_repo_type=args.hf_repo_type,
        hf_revision=args.hf_revision,
        offset=args.offset,
        limit=args.limit,
        report_path=args.report,
        strict_native_4k=not args.allow_non_4096,
    )
    print(json.dumps({
        "status": report["status"],
        "ready": report["ready"],
        "blockingCount": report["blockingCount"],
        "warningCount": report["warningCount"],
        "selectedJobs": report["jobs"]["selectedJobs"],
        "sectorCount": report["jobs"]["sectorCount"],
        "largestGpuMemoryGb": max([float(d.get("totalGpuMemoryGb") or 0) for d in report["torch"].get("devices", [])] or [0]),
        "report": str(args.report),
        "nextStep": report["nextStep"],
    }, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
