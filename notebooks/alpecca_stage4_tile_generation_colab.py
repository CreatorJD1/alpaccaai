# %% [markdown]
# # Alpecca Stage 4 Tile Generation Worker
#
# Run this in Google Colab or another GPU runtime. It pulls Stage 4 tile jobs
# from the Hugging Face art dataset, generates exact 4096x4096 RGBA PNG frame
# tiles, and uploads outputs/reports back to Hugging Face for local import.
#
# This notebook does not approve art. Back in the repo, run the returned-slice
# QA gate first:
#
# ```powershell
# python scripts\run_alpecca_stage4_returned_slice_qa.py
# ```
#
# Only after `readyForHumanVisualReview` is true and the turnaround preview
# visually passes should you import and stitch.

# %%
from pathlib import Path
import os
import subprocess

REPO_URL = "https://github.com/CreatorJD1/alpaccaai.git"
WORKDIR = Path("/content/alpaccaai")
HF_REPO = "CREATORJD/alpecca-art-library"
HF_JOB_CHUNK = "stage4-tile-jobs/first_slices/idle_eye_16sector_frame000_turnaround/tile_jobs_idle_eye_16sector_frame000_turnaround.jsonl"
OUTPUT_ROOT = WORKDIR / "output" / "alpecca_stage4_tile_jobs" / "worker_outputs_colab"
HF_OUTPUT_PREFIX = "stage4-worker-outputs/colab/idle_eye_16sector_frame000_turnaround"

# Start with the 16-tile native 4K still turnaround proof. After it passes
# visual QA, switch HF_JOB_CHUNK to:
# stage4-tile-jobs/first_slices/idle_eye_16sector_full_loop/tile_jobs_idle_eye_16sector_full_loop.jsonl
JOB_OFFSET = 0
JOB_LIMIT = 16

# %%
if not WORKDIR.exists():
    subprocess.run(["git", "clone", REPO_URL, str(WORKDIR)], check=True)
os.chdir(WORKDIR)
print(Path.cwd())

# %%
subprocess.run(["python", "-m", "pip", "install", "-q", "-r", "requirements-stage4-art.txt"], check=True)

# %%
# Optional model controls. Keep SDXL as the default first-pass open-source model.
os.environ.setdefault("ALPECCA_TILE_MODEL", "stabilityai/stable-diffusion-xl-base-1.0")
# Production mode must be native 4096. The generator refuses fake 4K upscales
# unless --allow-draft-upscale is explicitly passed.
os.environ.setdefault("ALPECCA_TILE_RENDER_SIZE", "4096")
os.environ.setdefault("ALPECCA_TILE_STEPS", "28")
os.environ.setdefault("ALPECCA_TILE_GUIDANCE", "7.0")
os.environ.setdefault("ALPECCA_TILE_STRENGTH", "0.62")
os.environ.setdefault("ALPECCA_TILE_MEMORY_MODE", "low_vram")
os.environ.setdefault("ALPECCA_TILE_ENABLE_ATTENTION_SLICING", "1")
os.environ.setdefault("ALPECCA_TILE_ENABLE_VAE_SLICING", "1")
os.environ.setdefault("ALPECCA_TILE_ENABLE_VAE_TILING", "1")
os.environ.setdefault("ALPECCA_TILE_ENABLE_XFORMERS", "1")

os.environ["ALPECCA_TILE_COMMAND"] = (
    'python scripts/generate_alpecca_stage4_tile_diffusers.py '
    '--prompt "{prompt_file}" '
    '--job-json "{job_json}" '
    '--seed "{seed_canvas}" '
    '--pose "{pose_guides}" '
    '--out "{output}"'
)

# %%
# Fast preflight before spending GPU time. This checks HF access, CUDA,
# dependencies, selected jobs, native 4096 contract, and low-VRAM settings.
subprocess.run(
    [
        "python",
        "scripts/preflight_alpecca_stage4_tile_worker.py",
        "--hf-path",
        HF_JOB_CHUNK,
        "--hf-repo",
        HF_REPO,
        "--offset",
        str(JOB_OFFSET),
        "--limit",
        str(JOB_LIMIT),
    ],
    check=True,
)

# %%
subprocess.run(
    [
        "python",
        "scripts/run_alpecca_stage4_resumable_colab_worker.py",
        "--hf-path",
        HF_JOB_CHUNK,
        "--hf-repo",
        HF_REPO,
        "--output-root",
        str(OUTPUT_ROOT),
        "--output-prefix",
        HF_OUTPUT_PREFIX,
        "--offset",
        str(JOB_OFFSET),
        "--limit",
        str(JOB_LIMIT),
        "--upload-every",
        "1",
        "--skip-existing",
        "--timeout",
        "7200",
        "--fail-fast",
    ],
    check=True,
)

# %%
# Inspect the generated worker report.
import json
report_path = OUTPUT_ROOT / "resumable_worker_report.json"
print(report_path)
print(json.dumps(json.loads(report_path.read_text()), indent=2)[:4000])

# %%
# Mechanical QA over the returned tile folder. This does not approve art.
subprocess.run(
    [
        "python",
        "scripts/qa_alpecca_stage4_tile_outputs.py",
        "--manifest",
        "output/alpecca_stage4_tile_jobs/first_slices/idle_eye_16sector_frame000_turnaround/tile_job_manifest.json",
        "--outputs-root",
        str(OUTPUT_ROOT),
    ],
    check=False,
)

# %%
# The resumable worker uploads after each tile. This line is just the returned
# prefix to inspect in Hugging Face.
print(f"Resumable uploads target https://huggingface.co/datasets/{HF_REPO}/tree/main/{HF_OUTPUT_PREFIX}")

# %% [markdown]
# ## Return Outputs
#
# Back on the local repo:
# 1. Run `python scripts\run_alpecca_stage4_returned_slice_qa.py`.
# 2. Inspect `turnaround_16_sector_qa.jpg` for 360 body volume and design lock.
# 3. Import and stitch only if the returned-slice QA is ready for visual review.
# 4. Promote to Stage 5 only after human visual QA approves the art.
