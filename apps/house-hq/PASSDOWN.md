# AI Office HQ Passdown

Date: 2026-06-25

## Current Objective

Continue improving the character animation system so Alpecca fits better in the 3D space, while improving the house graphics without degrading Alpecca sprite art quality.

Do not mark the active goal complete yet. There has been strong progress, but the game still benefits from more rendered QA and further polish passes.

## Project Location

Game workspace:

`C:\Users\Jason\Documents\Codex\2026-06-15\create-3d-exploration-game-based-inside\outputs\house-exploration-game`

Main runtime:

`src/main.ts`

Local preview:

`http://127.0.0.1:5173/`

Scripts:

```bash
npm.cmd run dev
npm.cmd run build
npm.cmd run preview
```

Latest build verification:

```text
npm.cmd run build
Result: passed
Output bundle: dist/assets/index-Dgrtvpk2.js
Note: Vite still warns that the main chunk is larger than 500 kB.
```

## Current Gameplay State

- The game is a Vite + TypeScript + Three.js first-person 3D office-house exploration game.
- The house is organized into five functional rooms: HQ Control, Library, Observatory, Workshop, and Self Design.
- The player can move through the house, activate room systems, interact with terminals, and talk to Alpecca.
- Doors were removed in favor of door frames.
- Wall seams/gaps have been visually sealed with wall skins, seam caps, trim, and modern wall panels.
- The room layout has been cleaned up to reduce clutter and preserve walking lanes.

## Alpecca State

Alpecca is rendered as a sprite-billboard using atlas animations from:

`public/assets/alpecca-optimized`

Do not downgrade or resize her source-quality art. The current pipeline prefers lossless WebP and preserves PNG sources.

Important animation/runtime systems in `src/main.ts`:

- `AlpeccaAnimationName` includes idle, walk, wave, sleep, crouch, kneel, jump, climb, dash, and directional states.
- `calmAlpeccaMotionState()` maps run/dash states back into walk states so running is not a normal behavior.
- `setAlpeccaAnimation(name, force)` includes one-shot animation locks so wave/point/pickup/jump/climb can finish cleanly.
- `alpeccaInspectionAnimation()` prevents finished one-shot inspection poses from looping awkwardly.
- `walkSegmentTimer`, `walkPauseTimer`, and `dwellTimer` make Alpecca pause during longer autonomous movement.
- `directionalAlpeccaAnimation()` uses camera-relative movement direction for directional idle/walk sprite selection.
- `applyAlpeccaBillboardYaw()` keeps the sprite facing the player camera while preserving ground-facing movement direction separately.
- `updateAlpeccaHeadLook()` adds a small head-look/glint layer toward the player.

Recent grounding/3D presence pass:

- `Alpecca floor reflection anchor` mesh was added below her.
- `updateAlpeccaFloorReflection()` ties the subtle floor reflection to room color, direction, stride, and foot contact.
- `groundContactIntensity` and `floorReflectionIntensity` expose how grounded she is at runtime.
- Foot contact shadows are still separate for left/right feet.
- Existing contact shadow, chromatic occlusion, presence glow, depth silhouette, body lean, and mirror reflection systems remain intact.

Useful runtime diagnostics on `document.body.dataset`:

- `alpeccaReady`
- `alpeccaState`
- `alpeccaFolder`
- `alpeccaMoving`
- `alpeccaDirection`
- `alpeccaFootContact`
- `alpeccaGroundContact`
- `alpeccaFloorReflection`
- `alpeccaBodyLean`
- `alpeccaMirrorReflection`
- `alpeccaAnimationLock`
- `alpeccaDwell`
- `alpeccaWalkPause`
- `renderCalls`
- `renderPixelRatio`

## Alpecca AI Source Bridge

The game connects to the local Alpecca source app over WebSocket:

```text
ws://127.0.0.1:8765/ws
```

Related code:

- `alpeccaAiBaseUrl`
- `alpeccaAiWsBaseUrl`
- `connectAlpeccaAi()`
- `handleAlpeccaAiMessage()`
- `sendAlpeccaChat()`

Expected backend location provided by the user:

`C:\Users\Jason\Documents\GitHub\alpaccaai`

Fallback behavior:

- If the backend is offline, the game uses local scripted Alpecca dialogue.
- If an access token is required, the optional token field in the `?` menu is used.

## Current Graphics Passes

Modern clean-room graphics are primarily in:

- `addExteriorWallSealPanels()`
- `addInteriorWallSkins()`
- `addInteriorDividerTrim()`
- `addWallGapSeals()`
- `addModernWallPanels()`
- `addCeilingLightPanels()`
- `addModernDepthLighting()`

Recent visual depth additions:

- `addModernDepthLighting()` adds low-cost room floor/wall wash planes.
- `addFloorDepthWash()` and `addWallDepthWash()` add subtle room separation without heavy postprocessing.
- Materials were calmed down to avoid clutter and reduce strong one-color themes.

Known render cost:

- Recent browser probes showed roughly `121-135` draw calls after the grounding/depth pass.
- Keep future polish measurable and avoid heavy post-processing unless it is profiled.

## QA Hooks

Manual frame stepping:

```text
#house-step=<frames>&dt=<seconds>
```

Optional Alpecca placement for QA:

```text
&alpecca-x=<number>&alpecca-z=<number>
```

Examples:

```text
http://127.0.0.1:5173/?qa=ground-walk#house-step=180&dt=0.033
http://127.0.0.1:5173/?qa=mirror#house-step=160&dt=0.033&alpecca-x=-6.1&alpecca-z=0.65
```

Hash handling:

- `runManualFrameStep()`
- `consumeManualStepHash()`

Manual step frames are clamped to a maximum of `600`.

## Browser QA Notes

The in-app browser screenshot path has repeatedly timed out on this WebGL tab:

```text
Page.captureScreenshot timeout
```

Use runtime probes, DOM checks, console logs, and canvas size/render-call diagnostics when screenshots fail. Do not claim screenshot evidence unless a screenshot actually captures successfully.

Minimum browser smoke checklist:

- Page title is `AI Office HQ`.
- Canvas exists and is nonzero size.
- No Vite/framework overlay.
- `tab.dev.logs({ levels: ["error", "warn"] })` is clean or explained.
- `document.body.dataset.alpeccaReady === "true"`.
- Alpecca state is not a normal `run*`, `dash`, or `climb` state during patrol.
- `alpeccaGroundContact` and `alpeccaFloorReflection` become nonzero during walking.
- `renderCalls` remains in a reasonable range.

## Known Issues / Cautions

- The active goal is not complete; keep improving visual depth and animation fit.
- Main bundle is large; future work could split asset/runtime loading or defer rare Alpecca systems.
- Browser screenshots are unreliable in the current in-app WebGL tab.
- Avoid adding floor cables or decorative clutter. The user specifically disliked clutter and weird colored wires.
- Do not make Alpecca lower quality, blurry, or smaller. Preserve source art quality.
- Keep run/dash/climb/jump as rare contextual actions only, never normal idle/patrol loops.
- Talking to Alpecca should keep her facing the player.

## Recommended Next Pass

1. Add a small animation-state debug overlay or `?` menu line for current Alpecca animation, direction, and grounding.
2. Improve directional state selection further by factoring both route direction and player/camera relative facing.
3. Add more deliberate contextual use of crouch/kneel/point/pickup without making them loop.
4. Add lightweight room-based reflection/occlusion checks around furniture feet to make the house feel more grounded.
5. Profile draw calls after each visual addition; keep the scene responsive.

