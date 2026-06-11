"""Alpacca: a self-aware-flavored local companion.

The package is organized around the spec's three layers:
  - sensory.py     : the senses (what the user is doing on the machine)
  - homeostasis.py : the emotional state vector and its update rules
  - state.py       : persistence of that state in SQLite
  - memory.py      : long-term memory store and retrieval
  - mind.py        : the Core Mind loop that ties it together + the LLM
  - prompts.py     : turns the current mood into a system prompt

Nothing here claims to be conscious. The "self-aware" framing is the project's
flavor: what we actually build is a stateful agent whose simulated mood visibly
shapes how it responds.
"""

__version__ = "0.1.0"
