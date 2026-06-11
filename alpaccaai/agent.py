"""The Claude computer-use agent loop for alpaccaai.

Implements the "sampling loop" described in Anthropic's computer use docs:
Claude is asked to complete a task; it responds with computer-use tool calls;
we execute them against the local machine and feed the results back; repeat
until Claude responds without requesting any more tools (task complete) or we
hit the iteration safeguard.
"""

from __future__ import annotations

from typing import Callable

from .config import COMPUTER_USE_BETA, Config
from .tools import ComputerTool, ToolResult

SYSTEM_PROMPT = (
    "You are alpaccaai, a local AI assistant running on the user's own computer. "
    "You can see the screen and control the mouse and keyboard through the computer "
    "tool. Work towards the user's goal one step at a time. After each action take a "
    "screenshot and verify the outcome before continuing; explicitly note what you "
    "observe. Prefer keyboard shortcuts when mouse targets are small or ambiguous. "
    "Ask the user before taking irreversible or sensitive actions (purchases, "
    "deleting files, sending messages, accepting terms)."
)


def _tool_result_block(tool_use_id: str, result: ToolResult) -> dict:
    """Convert a :class:`ToolResult` into an API ``tool_result`` content block."""
    content: list[dict] = []
    if result.output:
        content.append({"type": "text", "text": result.output})
    if result.base64_image:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": result.base64_image,
            },
        })
    block: dict = {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content or [{"type": "text", "text": "(no output)"}],
    }
    if result.is_error:
        block["is_error"] = True
    return block


class Agent:
    """Drives a Claude computer-use conversation against the local machine."""

    def __init__(self, config: Config, computer: ComputerTool | None = None,
                 client=None) -> None:
        self.config = config
        self.computer = computer or ComputerTool(
            width=config.display_width,
            height=config.display_height,
            display_number=config.display_number,
        )
        self._client = client
        self.messages: list[dict] = []

    @property
    def client(self):
        if self._client is None:
            try:
                import anthropic  # type: ignore
            except ImportError as exc:  # pragma: no cover - depends on environment
                raise RuntimeError(
                    "The 'anthropic' package is required. Install it with: "
                    "pip install anthropic"
                ) from exc
            self._client = anthropic.Anthropic(api_key=self.config.api_key)
        return self._client

    def run(self, task: str, on_text: Callable[[str], None] | None = None) -> str:
        """Run the agent loop for a single user ``task``.

        ``on_text`` is invoked with any natural-language text Claude emits along
        the way. Returns the concatenated final assistant text.
        """
        self.messages.append({"role": "user", "content": task})
        final_text: list[str] = []

        for _ in range(self.config.max_iterations):
            response = self.client.beta.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                system=SYSTEM_PROMPT,
                tools=[self.computer.to_params()],
                messages=self.messages,
                betas=[COMPUTER_USE_BETA],
            )
            self.messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if block.type == "text":
                    final_text.append(block.text)
                    if on_text:
                        on_text(block.text)
                elif block.type == "tool_use":
                    result = self.computer.run(dict(block.input))
                    tool_results.append(_tool_result_block(block.id, result))

            if not tool_results:
                # No tool use requested -> Claude is done with this task.
                return "\n".join(final_text)

            self.messages.append({"role": "user", "content": tool_results})

        return (
            "\n".join(final_text)
            + f"\n\n[alpaccaai] Stopped after {self.config.max_iterations} steps "
            "(iteration safeguard). Ask me to continue if the task isn't finished."
        )
