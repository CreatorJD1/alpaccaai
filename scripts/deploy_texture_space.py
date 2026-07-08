"""Deploy the Alpecca Texture Lab ZeroGPU Space (Pony V6 + Qwen2.5-VL)."""
import os
import sys
from pathlib import Path

from huggingface_hub import HfApi

REPO = os.environ.get("TEXTURE_SPACE", "CREATORJD/alpecca-texture-lab")
LOCAL = Path(__file__).resolve().parent.parent / "spaces" / "alpecca-texture-lab"
TOKEN = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")

api = HfApi(token=TOKEN)
print("whoami:", api.whoami(token=TOKEN).get("name"))

api.create_repo(
    REPO, repo_type="space", space_sdk="gradio", exist_ok=True, private=True, token=TOKEN
)
print("repo ready (PRIVATE):", REPO)

api.upload_folder(
    repo_id=REPO,
    repo_type="space",
    folder_path=str(LOCAL),
    commit_message="Deploy Alpecca Texture Lab (Pony V6 XL + Qwen2.5-VL) on ZeroGPU",
    token=TOKEN,
)
print("files uploaded")

try:
    api.request_space_hardware(repo_id=REPO, hardware="zero-a10g", token=TOKEN)
    print("requested ZeroGPU (zero-a10g) hardware")
except Exception as e:
    print("hardware request note:", repr(e)[:200])

print("done ->", f"https://huggingface.co/spaces/{REPO}")
