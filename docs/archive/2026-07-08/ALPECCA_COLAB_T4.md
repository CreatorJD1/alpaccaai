# Alpecca Colab T4 Fast-Brain Accelerator

This is an optional speed tier for House HQ chat. It does not replace Alpecca's
configured local reasoning model. When the Colab runtime is awake, normal fast
House HQ replies can go to the T4; if Colab sleeps or disconnects, Alpecca falls
back to local Ollama.

## 1. Start The Colab Runtime

1. Open Google Colab and select a T4 GPU runtime.
2. Copy the cells from `notebooks/alpecca_colab_t4_server.ipynb`.
3. Run all cells.
4. Wait for a printed URL like:

```text
ALPECCA_COLAB_URL=https://example.trycloudflare.com
```

If you set `ALPECCA_COLAB_TOKEN` in the notebook, also keep that value as
`ALPECCA_COLAB_API_KEY` locally.

## 2. Point Alpecca At The Colab URL

In PowerShell before starting Alpecca:

```powershell
$env:ALPECCA_COLAB_URL="https://example.trycloudflare.com"
$env:ALPECCA_COLAB_MODEL="Qwen/Qwen2.5-7B-Instruct"
# Optional, only if the notebook token is non-empty:
$env:ALPECCA_COLAB_API_KEY="your-token"
python server.py
```

Keep `ALPECCA_COLAB_FAST_CHAT=1` to let House HQ fast replies use the T4. Set it
to `0` to disable the Colab tier without removing the URL.

## 3. Verify

Open:

```text
http://127.0.0.1:8765/system/status
```

Look for:

```json
"colab_fast_ready": true
```

In House HQ, short messages should report `backend: colab-t4` in
`window.__HOUSE_DEBUG__.alpecca` after a reply. Longer reviews, code/action
requests, and deep self-work still use the local/deep configured tiers.

## Notes

Colab free GPUs are opportunistic. The notebook can sleep, disconnect, or change
GPU availability. Alpecca treats Colab as a bonus accelerator, not a dependency.
