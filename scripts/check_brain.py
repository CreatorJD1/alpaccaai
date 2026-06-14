r"""One-shot brain check: does her LLM actually answer, or will she echo?

Run this in the project folder:

    python scripts\check_brain.py

It uses the SAME model + context settings her app uses, makes one real call to
Ollama, and prints either her reply (brain healthy) or the exact error (the very
thing that makes her fall back to "You said: ..."). No server needed -- this
talks to Ollama directly, so it isolates the brain from everything else.
"""
import os
import sys

# Default to the small 4B brain (what fits a 4 GB card) unless you've set one.
# config reads ALPECCA_MODEL, so set it BEFORE importing config.
os.environ.setdefault("ALPECCA_MODEL", "qwen3:4b")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import OLLAMA_MODEL, OLLAMA_HOST, OLLAMA_NUM_CTX

print("=" * 56)
print(" Alpecca brain check")
print("=" * 56)
print(f" model   : {OLLAMA_MODEL}")
print(f" host    : {OLLAMA_HOST}")
print(f" num_ctx : {OLLAMA_NUM_CTX}   (low = small KV cache = fits small RAM)")
print("-" * 56)

try:
    import ollama
except Exception as exc:
    print("FAIL: the 'ollama' python package isn't installed in THIS python.")
    print(f"      {type(exc).__name__}: {exc}")
    print("      fix:  python -m pip install ollama")
    sys.exit(1)

client = ollama.Client(host=OLLAMA_HOST)

print(" Asking her to say hello (first call may pause to load the model)...")
try:
    resp = client.chat(
        model=OLLAMA_MODEL,
        messages=[{"role": "user", "content": "Say hello in five words."}],
        options={"num_ctx": OLLAMA_NUM_CTX},
    )
    text = resp["message"]["content"].strip()
    print("-" * 56)
    print(" SUCCESS - her brain replied:")
    print(f"    {text}")
    print("-" * 56)
    print(" Her brain works. If she still echoes in the app, the running")
    print(" server is on OLD code -- close it and restart with start_full.bat.")
except Exception as exc:
    print("-" * 56)
    print(" FAIL - the model call errored. THIS is why she echoes:")
    print(f"    {type(exc).__name__}: {exc}")
    print("-" * 56)
    msg = str(exc).lower()
    if "not found" in msg or "no such" in msg or "pull" in msg:
        print(" Looks like the model isn't pulled.  Fix:  ollama pull qwen3:4b")
    elif "out of memory" in msg or "oom" in msg or "allocate" in msg:
        print(" Still an out-of-memory.  Lower the context further, e.g.:")
        print("   set ALPECCA_NUM_CTX=4096   (then re-run this check)")
    elif "connection" in msg or "refused" in msg or "max retries" in msg:
        print(" Ollama isn't running.  Open the Ollama app, then re-run this.")
    print(" Copy this whole output to share it.")
    sys.exit(2)
