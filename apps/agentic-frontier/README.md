# Alventius Experimentus

Alventius Experimentus is a separate game application. Its technical app ID is
`agentic-frontier` for API and save compatibility. It is not mounted in House HQ,
does not run inside Alpecca CoreMind, and owns its own process, port, 3D web client,
and SQLite database.

The current playable vertical slice is set in **Vesper Dome** on Tartarus Prime
and combines first-person exploration with an orthographic colony-command view.
The sealed habitat has a cel-shaded shell, warm perimeter lighting, a commons,
study, greenhouse, and fabrication area. It includes the VRM 1.0 avatar,
oxygen/sanity/pressure survival, harvesting, threats, combat, a command terminal,
and placeable colony structures. It is not yet the full MMO, economy, or
megadome endgame described by the design document.

Vesper Dome uses a fixed-step Rapier physics world with a collision floor,
habitat walls, and furniture colliders. Jason has physical walk/run/crawl/jump
controls. Alpecca's game actor has server-authoritative, revision-checked
`companion_move`, `companion_motion` (`walk`, `run`, `crawl`, `jump`), and
`companion_interact` actions. Those actions are game state only; they are not
Alpecca CoreMind actions and do not write companion memories.
Its progression takes inspiration from the readable daily rhythm, relationships,
gathering, crafting, and growing home of a cozy life simulation, translated into
an original futuristic 3D world rather than copying another game's assets or map.

## Run

Double-click `START_AGENTIC_FRONTIER.bat`, or run:

```powershell
cd apps\agentic-frontier
python -m agentic_frontier.app
```

The default address is `http://127.0.0.1:8870`. The game API is public when
`AGENTIC_FRONTIER_TOKEN` is unset; setting a token enables bearer-token access.
A direct non-loopback binding still requires a token. Its database defaults to
`%LOCALAPPDATA%\AgenticFrontier\frontier.db` and can be overridden with
`AGENTIC_FRONTIER_DB`.

## Build the 3D client

The distributable client is bundled into `web/index.html` so the Python process
serves one same-origin game surface without a second development server:

```powershell
cd apps\agentic-frontier
npm.cmd install
npm.cmd run build
```

The default avatar is served from `data\avatar\vrm\alpecca.vrm`. Set
`AGENTIC_FRONTIER_VRM` to another VRM 1.0 file when testing a different avatar.

## Boundary

- The game stores only world, action, event, and episode-candidate state.
- The game never imports companion memory, CoreMind, House HQ, or Mindscape.
- It exports evidence-backed episode candidates without writing memories.
- `alpecca/game_memory.py`, owned by the companion side, is the only supported
  promotion boundary.
