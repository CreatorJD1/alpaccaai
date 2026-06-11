"""Command-line interface for alpaccaai.

Usage:
    alpaccaai                      # interactive REPL
    alpaccaai "open firefox"       # run a single task and exit
    alpaccaai --model claude-opus-4-8 ...
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .agent import Agent
from .config import Config

_REPL_HELP = """\
Commands:
  /help            show this help
  /reset           clear the conversation history
  /model <name>    switch the Claude model for this session
  /exit, /quit     leave alpaccaai
Anything else is sent to alpaccaai as a task to perform on this computer.
"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alpaccaai",
        description="A local AI assistant powered by Claude that can control your computer.",
    )
    parser.add_argument("task", nargs="*", help="Task to perform; omit for interactive mode.")
    parser.add_argument("--model", help="Claude model to use.")
    parser.add_argument("--max-iterations", type=int, help="Max agent steps per task.")
    parser.add_argument("--width", type=int, help="Display width in pixels.")
    parser.add_argument("--height", type=int, help="Display height in pixels.")
    parser.add_argument("--version", action="version", version=f"alpaccaai {__version__}")
    return parser


def _config_from_args(args: argparse.Namespace) -> Config:
    config = Config.from_env()
    if args.model:
        config.model = args.model
    if args.max_iterations:
        config.max_iterations = args.max_iterations
    if args.width:
        config.display_width = args.width
    if args.height:
        config.display_height = args.height
    return config


def _print_text(text: str) -> None:
    print(f"\nalpaccaai: {text}")


def _run_once(agent: Agent, task: str) -> None:
    agent.run(task, on_text=_print_text)


def _repl(agent: Agent) -> int:
    print(f"alpaccaai {__version__} — local AI assistant. Type /help for commands.\n")
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not line:
            continue
        if line in ("/exit", "/quit"):
            return 0
        if line == "/help":
            print(_REPL_HELP)
            continue
        if line == "/reset":
            agent.messages.clear()
            print("[conversation reset]")
            continue
        if line.startswith("/model"):
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                agent.config.model = parts[1].strip()
                print(f"[model set to {agent.config.model}]")
            else:
                print(f"[current model: {agent.config.model}]")
            continue

        try:
            _run_once(agent, line)
        except KeyboardInterrupt:
            print("\n[interrupted]")
        except Exception as exc:  # keep the REPL alive on errors
            print(f"[error] {exc}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    config = _config_from_args(args)

    if not config.api_key:
        print(
            "error: no Anthropic API key found. Set the ANTHROPIC_API_KEY "
            "environment variable.",
            file=sys.stderr,
        )
        return 2

    agent = Agent(config)

    if args.task:
        try:
            _run_once(agent, " ".join(args.task))
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0

    return _repl(agent)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
