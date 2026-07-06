"""Incremental helpers for streamed replies.

The streamed path shows her words as they generate, but qwen3.5 hybrids can
open a reply with a private <think>...</think> block -- and in a stream that
tag can arrive split across chunks ("<th" + "ink>..."). ThinkTagFilter is the
incremental twin of mind.strip_think: it drops think spans from a stream of
deltas without ever leaking a partial tag, and without holding back normal
text any longer than the length of one tag.

Pure string logic, no model imports, so it stays trivially unit-testable.
"""
from __future__ import annotations

_OPEN = "<think>"
_CLOSE = "</think>"


def _held_prefix_len(buf: str, tag: str) -> int:
    """Length of the longest suffix of `buf` that is a proper prefix of `tag`.
    That suffix might grow into the tag with the next delta, so it must be
    held back rather than emitted/dropped."""
    max_len = min(len(buf), len(tag) - 1)
    for n in range(max_len, 0, -1):
        if buf.endswith(tag[:n]):
            return n
    return 0


class ThinkTagFilter:
    """Feed streamed text deltas in; get displayable text out.

    Contract mirrors strip_think: everything inside <think>...</think> is
    dropped; an unclosed <think> at end-of-stream drops to the end; a partial
    tag that never completes (e.g. a literal "<thi" in prose) is emitted as
    ordinary text at flush().
    """

    def __init__(self) -> None:
        self._buf = ""
        self._inside = False

    def feed(self, delta: str) -> str:
        self._buf += delta or ""
        out: list[str] = []
        while True:
            if self._inside:
                end = self._buf.find(_CLOSE)
                if end < 0:
                    # Drop what can't be part of a forming close tag.
                    keep = _held_prefix_len(self._buf, _CLOSE)
                    self._buf = self._buf[len(self._buf) - keep:] if keep else ""
                    return "".join(out)
                self._buf = self._buf[end + len(_CLOSE):]
                self._inside = False
            else:
                start = self._buf.find(_OPEN)
                if start < 0:
                    keep = _held_prefix_len(self._buf, _OPEN)
                    cut = len(self._buf) - keep
                    out.append(self._buf[:cut])
                    self._buf = self._buf[cut:]
                    return "".join(out)
                out.append(self._buf[:start])
                self._buf = self._buf[start + len(_OPEN):]
                self._inside = True

    def flush(self) -> str:
        """End of stream: emit any held-back partial tag as literal text
        (it never became a real tag); an open think block drops to the end,
        exactly like strip_think."""
        if self._inside:
            self._buf = ""
            return ""
        out, self._buf = self._buf, ""
        return out
