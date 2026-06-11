# alpaccaai

A local AI assistant powered by [Claude](https://www.anthropic.com/claude) that can
**see and control your computer**. You describe a task in plain language; alpaccaai
uses Claude's [computer use](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/computer-use-tool)
tool to take screenshots, move the mouse, click, and type until the task is done.

> ⚠️ **alpaccaai controls your real mouse and keyboard.** Run it only on a machine
> and account you're comfortable handing to an autonomous agent — ideally a
> dedicated VM or a throwaway desktop. See [Safety](#safety) below.

## How it works

alpaccaai implements the computer-use **agent loop**:

1. Your task is sent to Claude along with a screenshot of the current screen.
2. Claude replies with an action (click, type, scroll, …).
3. alpaccaai performs the action on the local machine and sends back a fresh
   screenshot.
4. Repeat until Claude reports the task is complete (or a step-count safeguard
   is hit).

Screenshots are automatically downscaled to fit the API's image limits, and the
coordinates Claude returns are scaled back up to your native screen resolution,
so clicks land in the right place even on high-DPI displays.

## Install

```bash
pip install -e ".[gui]"      # core + screenshot/input support
```

The `gui` extra pulls in `pyautogui` and `Pillow`, which are needed to capture
the screen and drive the mouse/keyboard. The core package only needs `anthropic`.

## Usage

Set your API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Run a one-off task:

```bash
alpaccaai "open a terminal and run 'uname -a'"
```

Or start the interactive REPL:

```bash
alpaccaai
```

REPL commands:

| Command          | Description                          |
| ---------------- | ------------------------------------ |
| `/help`          | Show help                            |
| `/reset`         | Clear the conversation history       |
| `/model <name>`  | Switch Claude model for this session |
| `/exit`, `/quit` | Leave alpaccaai                      |

## Configuration

Configuration comes from CLI flags, then environment variables, then defaults:

| Env var                    | Flag               | Default            |
| -------------------------- | ------------------ | ------------------ |
| `ANTHROPIC_API_KEY`        | —                  | *(required)*       |
| `ALPACCAAI_MODEL`          | `--model`          | `claude-opus-4-8`  |
| `ALPACCAAI_DISPLAY_WIDTH`  | `--width`          | `1280`             |
| `ALPACCAAI_DISPLAY_HEIGHT` | `--height`         | `800`              |
| `ALPACCAAI_MAX_ITERATIONS` | `--max-iterations` | `20`               |
| `ALPACCAAI_MAX_TOKENS`     | —                  | `4096`             |
| `ALPACCAAI_DISPLAY_NUMBER` | —                  | *(unset)*          |

The model must support the `computer_20251124` tool (Claude Opus 4.8 / 4.7 / 4.6,
Sonnet 4.6, Opus 4.5).

## Safety

Computer use carries real risks: Claude can take actions that are hard to undo,
and content on the screen (web pages, documents) may contain prompt-injection
attempts. alpaccaai's system prompt asks Claude to confirm before irreversible or
sensitive actions, and the agent loop is capped by a step limit — but these are
not substitutes for caution. Recommendations:

- Run inside a VM or container with minimal privileges.
- Don't leave sensitive accounts logged in.
- Supervise the session, especially when browsing the web.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The scaling/coordinate logic and action dispatch are unit-tested without
requiring a display (the screen backend is faked in tests).

## License

MIT
