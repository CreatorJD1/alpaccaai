# Alventius Experimentus

Status: **standalone 3D playable vertical slice in active integration; MMO-scale systems remain future work**

Alventius Experimentus is a separate game Alpecca can play with Jason and, later,
other approved players. It is not Alpecca's brain, identity, or replacement
runtime.

`agentic-frontier` remains the internal app and API identifier so existing saves,
routes, and memory-boundary validation do not break during the title change.

## Current Slice

- Independent FastAPI process and web client at port `8870`.
- Independent `%LOCALAPPDATA%/AgenticFrontier/frontier.db` database.
- Explicit app manifest stating `coreMindEmbedded: false` and
  `houseHqEmbedded: false`.
- Server-authoritative SQLite world state.
- Jason and Alpecca are separate authenticated actors.
- Bounded perception; clients never receive hidden world state.
- Revision-checked, strictly validated, payload-bound idempotent actions.
- Actor-specific reconnect receipts.
- Tartarus Prime survival state: health, oxygen, sanity, pressure shielding,
  energy, resources, acid-rain exposure, shelter, and deterministic threat damage.
- First-person exploration actions and an orthographic colony-command terminal.
- Harvestable ferrite and lumen flora, shadow-smoke and corrupted-robot threats,
  weakness-aware combat, and player-built domes, turrets, oxygen beacons, and
  power conduits.
- A co-op relay-repair onboarding mission requiring both actors.
- VRM 1.0 avatar delivery from the standalone game process; the game does not
  embed House HQ or Alpecca CoreMind.
- Evidence-backed candidates for meaningful shared episodes.
- A narrow adapter rejecting raw telemetry, solo events, and malformed claims.

## Visual Direction

The client uses anime cel shading: stable toon-lighting ramps,
controlled outlines, clean futuristic materials, readable RTS-scale
silhouettes, and expressive character closeups. It should feel like a polished
futuristic RPG/RTS world, not photorealistic rendering or a flat dashboard.

## Design Contract

The source design is the Google document **Ventis experimentus**. The vertical
slice implements its Tartarus Prime setting, survival pressure, sanity,
exploration, command-terminal view switch, colony structures, native VRM avatar,
bounded agent perception, and durable action receipts. It does not claim the
document's full MMO, economy, governance, megadome endgame, iOS release, or
large-scale multiplayer are complete.

The life-simulation influence applies to pacing and systems: a readable daily
rhythm, gathering, crafting, relationships, individual routines, and settlement
growth. The world, characters, assets, interface, fiction, and 3D exploration
remain original to Alventius Experimentus.

## Next Gates

1. Add authenticated WebSocket room updates to the standalone HTTP API.
2. Deploy a durable cloud room using the existing singleton and identity boundaries.
3. Add Alpecca's action policy using only her bounded perception contract.
4. Expand dome power, oxygen routing, breach repair, and turret simulation.
5. Run latency, reconnect, cheating, mobile thermals, and memory-promotion soak.
6. Add approved players, economy, governance, and megadome progression only
   after the two-player proof is stable.
