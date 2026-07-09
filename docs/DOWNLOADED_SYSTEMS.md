# Downloaded Optional Systems

Last updated: 2026-07-08

This records optional systems downloaded for the agentic/Mindpage roadmap. The
actual binaries and virtual environments live under ignored `data/` paths and
are not committed to GitHub.

## Installed Locally

### llama.cpp b9933

CPU build:

- `data/tools/llama.cpp/b9933/cpu-x64/llama-server.exe`
- `data/tools/llama.cpp/b9933/cpu-x64/llama-cli.exe`

CUDA 12.4 build:

- `data/tools/llama.cpp/b9933/cuda-12.4-x64/llama-server.exe`
- `data/tools/llama.cpp/b9933/cuda-12.4-x64/llama-cli.exe`
- `data/tools/llama.cpp/b9933/cuda-12.4-x64/cudart64_12.dll`
- `data/tools/llama.cpp/b9933/cuda-12.4-x64/ggml-cuda.dll`

Source archives retained locally:

- `data/tools/llama.cpp/b9933/llama-b9933-bin-win-cpu-x64.zip`
- `data/tools/llama.cpp/b9933/llama-b9933-bin-win-cuda-12.4-x64.zip`
- `data/tools/llama.cpp/b9933/cudart-llama-bin-win-cuda-12.4-x64.zip`

Verification:

```powershell
data\tools\llama.cpp\b9933\cpu-x64\llama-server.exe --version
data\tools\llama.cpp\b9933\cuda-12.4-x64\llama-server.exe --version
```

Both report version `9933`.

### sqlite-vec

Installed in the main Python environment:

- `sqlite-vec==0.1.9`

Verification:

```powershell
python -c "import sqlite_vec; print(sqlite_vec.__version__)"
```

### MCP SDK

Installed in an isolated venv so it does not change Alpecca's main runtime
dependency pins:

- `data/tools/mcp-venv`
- `mcp==1.28.1`

Verification:

```powershell
data\tools\mcp-venv\Scripts\python.exe -c "import mcp, pydantic; print('mcp installed'); print(pydantic.__version__)"
```

## Notes

- The retired legacy Ollama model remains removed and should not be
  reintroduced.
- Existing approved Ollama models already present locally include `qwen3.5:9b`,
  `qwen3.5:4b`, `gemma4-e4b`, `qwen2.5vl:7b`, and `nomic-embed-text`.
- `pip check` still reports pre-existing voice/ML package conflicts unrelated
  to these downloads. Main `pydantic` was restored to `2.9.2`; MCP keeps its
  newer `pydantic` inside `data/tools/mcp-venv`.
