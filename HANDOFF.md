# Alpecca — Handoff (updated 2026-07-09)

## Mindpage adaptive paging checkpoint (2026-07-09)

- `alpecca/mindpage.py` now measures the actual formatted request instead of
  treating raw history length as total context pressure. It includes system
  prompt, current message, attached history, tool schemas, protocol allowance,
  and output reserve, with deterministic optional-context shrink order.
- Chat now performs bounded automatic pre-fault of relevant hot/warm pages and
  injects labeled summary/excerpt evidence. Explicit `recall_page` searches all
  tiers and is preserved inside the seven-tool cap for memory requests.
- History deletion is commit-safe: a failed page write retains all messages and
  exposes `paging_error` plus `unsummarized_eviction_backlog`.
- The same measured snapshot reaches the factual prompt block, Soul Snapshot,
  cognition state, chat/WebSocket reply, `/mindpage/stats`, and the House HQ
  Working Memory gauge. Reflector now relieves pressure by paging chat history;
  it no longer substitutes cognition-observation consolidation.
- Long-term memory recall now unions the 500-row salience/recency pool with FTS5
  lexical candidates. Malformed or mixed-dimension embeddings fall back to
  keywords. Embedding calls run outside the write transaction during backfill.
- Page faults promote to hot. `maintain_pages()` supports deterministic
  hot-to-warm and warm-to-cold demotion; `vacuum()` is explicit and never runs
  automatically. The disk limit is reported, not enforced through deletion.
- Focused Mindpage/recall tests and `npm.cmd run house:build` pass. The full suite
  must be run with `ALPECCA_CHAT_CLOUD_MODEL` unset because this machine's launcher
  exports `gemma4:cloud`, which makes fake-local `_LLM` tests call the live cloud
  client instead of their injected fake.
- `docs/MINDPAGE.md` is the canonical implemented/deferred boundary. Layer B
  llama.cpp slot persistence and Layer C OS pagefile/mmap deep-model work remain
  experimental and were not activated.

---

## Active handoff for next Claude session (2026-07-09)

- Scope is **VRoid base-model matching work** only; House HQ, core backend, and other app surfaces remain untouched.
- User requirement remains: **disable layers instead of deleting**.
- Current state:
  - The updated regular-outfit source remains `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v0.vroid` (9,650,830 bytes, saved 2026-07-09 12:19:40). It was preserved byte-for-byte as `alpecca_vroid_proxy_v0_updated_source_20260709_121940_preserved.vroid` before the base-view work.
  - The stripped inspection model is a separate file: `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v13_base_view_170cm.vroid` (7,321,206 bytes, saved 2026-07-09 15:07:52). Do not treat v13 as the regular-outfit source.
  - Blank/no-item presets are active in v13 for `Tops`, `Bottoms`, `Socks`, and `Shoes`; neck/accessory routes remain absent. `Inner Top` and `Inner Bottom` expose no blank preset, so the minimal required underlayers remain. No item or texture layer was deleted.
  - Base height was 170.2 cm / 5 ft 7 in when v13 was saved (`Fem Height=0.475`, `Masc Height=0.050`) with shoes disabled. VRoid displayed 170.3 cm after returning from Photo Booth with the same unchanged sliders; this is within the 170.2-170.4 cm gate and appears to be display/pose rounding.
  - Full-body editor QA was completed at front, left/right 3/4, side, back 3/4, and back. A persistent front A-pose capture is `data/alpecca_art_source/vrm_experiments/qa_lane/alpecca_v13_base_front_20260709.png`.
  - Adult/slim proportions, single ahoge, blue eyes, and pale blue lower hair color are present. The model is not design-complete: hair is shorter, straighter, and less layered than the locked references, and the left blue clip remains the simple-pin proxy rather than the required small X/bow accessory.
  - Lanyard/accessory routing:
    - Custom item fallback remains at `%USERPROFILE%\AppData\LocalLow\pixiv\VRoid Studio\custom_items\N00-NeckAccessory\2026-07-09-07-50-16-412.vroidcustomitem`.
    - Matching package is `data/alpecca_art_source/vrm_experiments/xwear/alpecca_neck_accessory_lanyard_fallback_20260709.xwear`.
  - BOOTH zip path is downloaded as `data/alpecca_art_source/vrm_experiments/accessory_workbench/booth_downloads/BWL_Group1000ThanksTicketHolder1.0.0Gift.zip` but encrypted (password-required).
  - Custom scratch lanyard source package lives at `data/alpecca_art_source/vrm_experiments/accessory_workbench/lanyard_3d/` (`.obj/.mtl/.glb` + textures/spec).
- Open items:
  - Improve v13 hair length, layered/wavy mass, and soft lavender-blue lower transition against `design_lock_references/01-turnaround-front-side-back.jpg` and `02-volumetric-angle-reference.jpg` without changing the preserved v0 source.
  - Replace the simple-pin proxy with a true small blue X/bow clip on Alpecca's left side through a compatible accessory/XWear route.
  - Add persisted side, back 3/4, and back QA captures after the hair/clip correction; the orbit was visually checked but only the front image is currently saved.
  - Keep using blank/no-item presets and separate source variants. Avoid delete, trash, or overwrite actions on the preserved regular-outfit source.
- Canonical references for continuation:
  - `PROJECT_CONTEXT.md`
  - `docs/ALPECCA_CURRENT_PROGRESS.md` (if still present/authoritative)
  - `HANDOFF.md` (this file)

---

## Cloud-interface refresh checkpoint (2026-07-09)

Scope: cloud/hosting surfaces, docs corrections, and bridge/tunnel bring-up. The
VRoid v13 work above remains the active handoff.

- The adaptive Mindpage changeset is committed and pushed as `a5084c3` on
  `feat/vrm-preview`: mindpage/mind/memory/prompts plus the House HQ Working
  Memory gauge. 347 tests green and `npm.cmd run house:build` green at commit
  time.
- Multi-subagent code-audit corrections were folded into
  `docs/ALPECCA_FEATURE_SKELETON_INFRASTRUCTURE.md` and the PDF was regenerated.
  Three of the five defects were already resolved by the Mindpage pass
  (tool-cap recall drop, adaptive pressure shrink, vacuum hook). Two remain
  open — the routines DELETE route and ngrok URL capture — and are being fixed
  in this session by parallel agents.
- The Cloudflare R2 static shell was re-packaged and re-uploaded: 6 objects,
  with all 304 art assets excluded per the no-art-on-Cloudflare rule. The new
  bundle `index-EI-cuJEZ.js` replaced the stale Jul-2 `index-Boi8Fodb.js`.
- Hugging Face runtime metadata was synced via
  `publish_alpecca_art_library_hf.py --runtime-metadata-only`; 136 files
  committed to `CREATORJD/alpecca-runtime-assets`.
- `config.py` cloud-model comments were corrected to match the approved
  launcher: `gemma4:cloud` for chat/deep/vision via `START_HERE.bat`, with
  `qwen3.5:9b` as the local fallback. No unapproved model substitutions.
- The Discord bridge was started and is online as `Alpecca_ai#0929` (1 server,
  `dm_allow=none`). A Cloudflare quick tunnel is being established via
  `scripts/share.py` for phone access.
- Still pending/user-gated: Mindscape Worker hosted deploy (wrangler secret +
  deploy + `ALPECCA_MINDSCAPE_URL` — explicit user go required), ZeroGPU brain
  space wiring (`ALPECCA_ZEROGPU_SPACE` unset by design), Colab T4 fast tier
  (`ALPECCA_COLAB_URL` unset), Stage 4 art generation (144 targets still
  seeded-awaiting-generation), and the VRoid v13 base-model work per the active
  handoff above.

---

Snapshot for whoever picks this up next (human or agent): current state, how to
run her, what was built, what's solid vs. shaky, and what's next. Read `CLAUDE.md`
for the canonical architecture, `docs/ALPECCA_CURRENT_PROGRESS.md` for the current
state and plan. (An earlier handoff is folded into the history below.)

---

## VRoid hoodie/lanyard cleanup checkpoint (2026-07-09)

Scope: active VRoid source only; House HQ and the 2D pipeline remain untouched.

- The active source `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v0.vroid`
  was saved in VRoid Studio at 2026-07-09 06:36:47 local time (9,532,476 bytes).
- Hoodie artifact cleanup is now applied through the pass 05 clean overlay:
  `vroid_texture_layers/continuous_texture_lane/pass_05/alpecca_v10_hoodie_minimal_reference_matched_no_buttons_2048.png`.
  This removed the baked-in lanyard/buttons, dashed seam noise, and the stray lower
  blue open-front line from the hoodie texture.
- Jason clarified the white inner shirt is its own `Outfit > Inner Top` category.
  The lanyard/ID base layer was moved there with a pure no-choker overlay:
  `vroid_texture_layers/continuous_texture_lane/pass_06/alpecca_pass06_inner_top_lanyard_id_pure_no_choker_2048.png`.
  A second chest-high pure overlay was added so the lanyard reads higher in the
  hoodie opening:
  `vroid_texture_layers/continuous_texture_lane/pass_06/alpecca_pass06_inner_top_lanyard_id_chest_high_pure_no_choker_2048.png`.
  The older accidental `Neck Accessories` texture-edit dirty flag was explicitly
  left unchecked in VRoid save prompts so it was not overwritten.
- Front hair tips were restored with a softer lower-only overlay:
  `vroid_texture_layers/continuous_texture_lane/pass_06/alpecca_pass06_hair_lower_tips_only_soft_blue_1024x2048.png`.
  The too-strong full lower-gradient layer was hidden before saving the Front hair item.
- The current worn regular outfit state was exported through VRoid Studio's
  top-left `Bulk export worn items as XWear` path:
  `data/alpecca_art_source/vrm_experiments/xwear/alpecca_regular_outfit_lanyard_inner_top_20260709.xwear`
  (8,719,402 bytes, saved 2026-07-09 07:41:29). This is a full worn-outfit XWear
  package, not a lanyard-only XWear, because VRoid exports accessories via the
  bulk XWear route rather than individual accessory export.
- Jason clarified that the lanyard should be an accessory; VRoid Studio 2.14.0
  does not provide a native modern `Accessories` lanyard preset, and importing the
  existing lanyard custom item routes it back to `Outfit > Neck Accessories`.
  The fallback is now saved there as a custom neck/tie-section item:
  `%USERPROFILE%\AppData\LocalLow\pixiv\VRoid Studio\custom_items\N00-NeckAccessory\2026-07-09-07-50-16-412.vroidcustomitem`.
  The active source project was saved after that at 2026-07-09 07:50:33 local
  time (9,672,693 bytes).
- A corrected fallback XWear export from the worn `Outfit > Neck Accessories`
  state is saved at
  `data/alpecca_art_source/vrm_experiments/xwear/alpecca_neck_accessory_lanyard_fallback_20260709.xwear`
  (8,737,591 bytes, saved 2026-07-09 07:52:38). This remains a VRoid bulk worn
  item package, but the lanyard source item is now in the neck accessory/tie
  category rather than the inner shirt texture route.
- A separate custom 3D source model for the lanyard/badge was generated under
  `data/alpecca_art_source/vrm_experiments/accessory_workbench/lanyard_3d/`:
  `alpecca_lanyard_badge_source.obj`, `alpecca_lanyard_badge_source.mtl`, and
  `generate_lanyard_obj.py`. After the BOOTH ZIP password block, Jason chose the
  scratch-build route. The generator now outputs an upgraded no-collar/no-choker
  source package: preferred self-contained
  `alpecca_lanyard_badge_source.glb`, editable OBJ/MTL, external glTF/bin,
  `textures/alpecca_id_badge_1024.png`, and
  `alpecca_lanyard_badge_source.spec.json`. It includes a blue V-lanyard, strap
  highlights/shadows, gray hardware, lower blue tag tails, and a UV-mapped
  Alpecca ID badge face. Use the GLB as the active import source for the later
  true accessory/XWear Package build path; parent it to the VRM `Chest` bone and
  keep the badge slightly in front of the hoodie opening.
- Jason provided BOOTH item `https://booth.pm/en/items/8077106`. It was opened
  in Microsoft Edge while signed in and downloaded successfully to Downloads as
  `BWL_Group1000ThanksTicketHolder1.0.0Gift.zip` (76,129,588 bytes), then copied
  to
  `data/alpecca_art_source/vrm_experiments/accessory_workbench/booth_downloads/`.
  The archive is password-encrypted; listed contents include a Unity package,
  `FBX/Group1000Keychain_Charm.fbx`, `FBX/Group1000Keychain_NeckStrap.fbx`, and
  Blue/LightBlue texture PNGs, but extraction requires the password. The BOOTH
  page states the extraction password is distributed through the creator's VRChat
  group member-only post dated 2026-03-14 22:00. Do not bypass this; Jason needs
  to provide the password or retrieve it through the intended route.
- The rejected collar/choker body-skin texture remains off. Do not reintroduce a
  standalone collar/choker; keep the lanyard as a separate accessory only.
- Remaining model-fidelity gaps: the lanyard is now routed through
  `Outfit > Neck Accessories`, but it is still constrained by VRoid's neck/tie
  geometry and reads more tie-like than the reference. The separate OBJ source
  model should be used for the later true accessory/XWear Package build. The blue
  X/bow hair clip is still a proxy hair extra rather than a true modern
  `Accessories` custom item, and full front/side/back orbit QA still needs a
  manual VRoid camera pass.

## VCS texture/model-fidelity pass (2026-07-08)

Scope: experimental VRM/VCS appearance work only. House HQ and the canonical 2D
pipeline remain untouched.

- Extended `apps/vcs/frontend/src/lib/materialUtils.js` so the existing
  **Match to design** action applies more of Alpecca's locked design palette in
  the browser: hair gradient, ivory outfit tint, stocking cleanup,
  dark shorts, cream/blue boots, and blue clip/accessory/lanyard-style materials
  when material names allow safe targeting.
- Jason rejected the separate collar/choker texture as a design mismatch on
  2026-07-08. The active `alpecca_vroid_proxy_v0.vroid` body-skin top layer was
  deleted in VRoid Studio, the custom `Skin` item was overwritten, and the source
  project was saved. Do not reintroduce collar/choker tinting in VCS or VRoid.
- The blue hair clip should be kept as its own BOOTH/imported `Accessories`
  custom item/category. Do not route it through body skin, hoodie textures,
  animal ears, hats, or unrelated presets.
- Later on 2026-07-08, VRoid Studio was used to improve the active source
  `alpecca_vroid_proxy_v0.vroid` boots in place: `Overall Volume` 33.436,
  `Boot Volume` 57.753, `Toebox Width` 31.322, `Toebox Volume` 44.361,
  `Toebox Thickness` 28.855, and `Foot Thickness` 22.159. The source file was
  saved at 20:52:49 local time. The Accessories tab was verified as the correct
  route for the blue clip (`Import as Custom Item`), but the matching free
  BOOTH `.vroidcustomitem` candidates redirect to BOOTH sign-in for download.
- Jason then provided `Star_shape_hair_pin.rar` and
  `Simple_hair_pin_pink.rar`. Both are BOOTH `HairHanege` / VRoid `Extra`
  custom items, not modern `Accessories` items. The star pin import was rejected
  by VRoid Studio 2.14.0 as incompatible. The simple pin loaded through
  `Hairstyle > Extra > Custom`, was recolored at the material level to blue, and
  the active source `alpecca_vroid_proxy_v0.vroid` was saved at 21:07:39. This is
  a proxy clip route, not the final perfect left-side bone/bow accessory.
- Later on 2026-07-08 the active source was improved again in VRoid Studio and
  saved in place at 21:39:11 local time (`alpecca_vroid_proxy_v0.vroid`,
  8,927,423 bytes). The hoodie got a new top repair layer
  `alpecca_hoodie_ivory_details_v7_front_sleeve_corrections.png` over the v6
  layer: it covers the too-heavy front rails, redraws slimmer pale-blue zipper
  trim, moves the chest mark higher/smaller, rebuilds one clean black/blue tech
  patch per sleeve, and keeps the existing back/cuff/hem work. The hoodie shade
  color was changed from cool `#CFD6F7` to warm `#E8DED7` so the fabric reads
  cream/ivory instead of blue-gray.
- The active Body height was found at `167.6 cm`, which conflicted with Jason's
  5 ft 7 in requirement. It was corrected in VRoid Body controls to `170.2 cm`
  (`Fem Height=-0.058`) and saved. Current visible proportions still need
  front/side/back adult-read QA, but the scale target is now aligned.
- Multi-agent local workbench outputs were created under ignored `data/`:
  `vrm_experiments/accessory_workbench/` contains an OBJ/MTL/SVG/spec for a
  small glossy blue X/bone-bow hair clip proxy, and
  `vroid_texture_layers/candidates/` contains three alternate hoodie overlay
  candidates. These are not committed because `data/` is private/local source
  art, but `docs/ALPECCA_VROID_ACCESSORY_WORKBENCH.md` points to the workbench.
- Updated `apps/vcs/frontend/src/components/panels/MaterialsPanel.jsx` to call
  the broader matcher and report which material groups were affected.
- This is a reversible VCS preview/material-map pass. It does not mutate the
  `.vroid` source files directly; equivalent changes still need to be saved in
  VRoid Studio for a locked source checkpoint/export.

## VRM viewer framing + VCS port polish + launcher (2026-07-07, later session)

Scope: the **experimental VRM companion path** — both the in-app `/vrm` page
(`web/vrm.html`) and the ported **VCS studio** (`apps/vcs`, the clone of Jason's
Emergent VRoid Companion Studio at emergentagent.com). Nothing here touches the
2D/House HQ pipeline. NOTE: emergentagent.com is the SOURCE app being ported into
`apps/vcs` — it is NOT a deploy target; do not push there.

### `/vrm` page camera framing — FIXED + verified
Her VRM loaded zoomed onto her head. Two compounding causes, neither is
"feet at y=0":
- The export is **origin-centered** — feet ~-0.90, hips ~0, crown ~+0.74.
- A VRM's skinned-mesh `geometry.boundingBox` is a **phantom BIND-pose column**
  (~0→1.8 m), not where the bones actually render her; `Box3.setFromObject`/
  `expandByObject` read that phantom box and mis-frame her low + small.
Fix (`web/vrm.html` `frameCamera()`): sample the **posed skinned vertices**
(`applyBoneTransform` → world matrix → Box3) and run it on the **first rendered
frame** (skinning only settles after the skeleton updates once). Camera targets
the true center (y≈-0.08), distance fits her real ~1.65 m height. Verified via
headless Chrome CDP (SwiftShader WebGL): full-body, centered; orbit + zoom work
and zoom clamps (no clip-through). Shots: `data/screenshots/vrm_preview.png`
(882×1104) + `vrm_preview_mobile.jpg` (22 KB). Phone artifact:
https://claude.ai/code/artifact/799064ce-a3dd-4b54-befe-1ebf91cca45a
Lesson saved to memory as `vrm-framing-skinned-bounds`.

### VCS studio (`apps/vcs`) — port is COMPLETE + improved
Feature-audited against the emergentagent.com reference: all 20 animation
prefabs, all 4 tabs (Anim/Face/Pose/Mats), Runtime Behaviors, Procedural
Timeline are present. On top of the port this session:
- **Same framing fix** in `VRMViewer.jsx` `computeVRMBoundingBox()` — now samples
  posed skinned vertices (was reading the phantom bind box).
- **Foot grounding** — new `frontend/src/lib/vrmIK.js` (`snapGround` at load +
  per-frame `groundFeet`, easing back for airtime/Jump). Her soles sit exactly on
  the grid (verified toe-sole world-Y = 0.000); fixes the float-through-grid item.
  Wired in `VRMViewer.jsx` (snapGround before auto-frame, groundFeet after
  `vrm.update`). `state.groundBase` = resting offset, `groundOffset` = live.
- **Texture Lab "Bold" mode (ControlNet UV-lock) wired end-to-end** —
  backend `ai_service.py`: `_panel_edge_control()` builds the ControlNet control
  image from the atlas ALPHA (island outlines + threshold-gated interior seams;
  adaptive for opaque-vs-void atlases — avoids the beaded-mesh artifact from raw
  FIND_EDGES), `_zerogpu_texture_cn()` calls the Space's `/texture_cn`,
  `generate_material_texture(..., mode=)` routes restyle (low-denoise recolor) vs
  bold (high-denoise + edge lock). `routes.py` + `api.js` carry `mode`;
  `TextureLabDialog.jsx` has a Restyle/Bold header toggle threaded to both tabs.
  Route-tested live: bold 17s / IP-Adapter restyle 20s, alpha byte-preserved.
  Scripts: `scripts/test_route_bold.py`, `scripts/test_route_ipadapter.py`.
- **One-click launcher** — `RUN_VCS.bat` (repo root): starts backend :8001 +
  frontend :3200 in their own windows, opens http://localhost:3200 (Alpecca
  auto-loads). Paths verified. Was two hand-typed terminals (RUN_LOCAL.md).

### How to run / verify
`RUN_VCS.bat` (or the two commands in `apps/vcs/RUN_LOCAL.md`). Backend has 20
Alpecca VRM projects in Mongo; `StudioPage.jsx` auto-loads the newest on mount.
localhost is PC-only (phone can't reach :3200). All changes are in the working
tree (uncommitted); servers were reaped at session end.

---

## VCS (VRoid Companion Studio) — ZeroGPU texture pipeline + anim/texture upgrades (2026-07-07)

Scope: this whole session was the **experimental VRM companion tool** at `apps/vcs`
(the "VCS" port, backend :8001 + frontend :3200 + local MongoDB). Per CLAUDE.md the
VRM path must NOT replace 2D/House HQ — nothing here touches the main pipeline.

### The ZeroGPU pipeline (the infra everything else rides on)
All heavy AI for the VCS Texture Lab runs on Jason's **PRO ZeroGPU Space
`CREATORJD/alpecca-texture-lab`** (H200) — **Pony Diffusion V6 XL**
(`Bakanayatsu/Pony-Diffusion-V6-XL-for-Anime`) for images + **Qwen2.5-VL-7B** for
structured vision. This replaced the dead local-4GB path (times out >400s) and paid
HF Inference (402). Local ComfyUI + Ollama remain as fallbacks.
- Space source: `spaces/alpecca-texture-lab/app.py`. Redeploy via `scripts/deploy_texture_space.py` or `HfApi().upload_file(...)`. It's PRIVATE, on `zero-a10g`.
- Endpoints (gradio api_name): `/texture` (restyle img2img + IP-Adapter, 11 args), `/texture_cn` (ControlNet UV-lock, 11 args), `/vision_json` (outfit extract + anime guard).
- Backend calls it via `gradio_client` (`Client(space, token=HF_TOKEN)` — param is `token`, NOT hf_token). Routed by `AI_PROVIDER=zerogpu` in `apps/vcs/backend/.env` (+ `ZEROGPU_TEXTURE_SPACE`, `TEXTURE_RESTYLE_STRENGTH=0.32`, `TEXTURE_TINT_AMOUNT=0.7`, `ZEROGPU_IP_SCALE=0.6`).

### Texture render fix — the core bug ("UV grid rendered as the texture"). FIXED + verified.
Root cause: the generator was seeded with the **wireframe UV template** (or free-gen
character art), so it painted a grid / a character that then wrapped as garbage.
Fix = **restyle the material's ORIGINAL atlas in place**:
`generate_material_texture` → `_flatten_atlas_for_init` (shading-multiply palette
tint on the alpha region) → Pony **low-denoise img2img (0.32)** → `_reapply_alpha`
(re-composite the original alpha so the transparent UV void stays empty).
Frontend: `extractOriginalAtlas()` in `materialUtils.js` grabs `material.map` + its
`flipY`; `DressTab`/`MaterialTab` send `original_atlas_data_url`; `applyTexture`
re-applies with the original flipY. **Verified through the live route**
(`/api/generate/material_texture`): alpha byte-identical (397,528 px), every panel
held in its UV island, palette-accurate recolor. `scripts/test_restyle.py`,
`scripts/test_route_texture.py`.

### Animation upgrades (frontend, shipped, hot-reloaded, no console errors)
- **Cross-fade:** `VRMViewer.jsx` `vrmaUrl` effect now uses ONE persistent
  `AnimationMixer` + `crossFadeTo(0.45s)` (was: fresh mixer + `stopAllAction` = hard
  cut). Clips cached per-url. Mood transitions blend. Render loop still keys off
  `!!ref.vrmaMixer` (nulled only on vrmaUrl→null → procedural handoff).
- **Procedural gaze:** `vrmAnimations.js` `computeGaze()` (saccades + aversion);
  the lookAt branch uses it when the cursor's been idle >2.5s (eyes never freeze).
- **Auto-load + live driver:** `StudioPage.jsx` mount effect auto-loads the newest
  VRM project (nothing is persisted, so a refresh otherwise drops to empty) and
  enables `alpeccaLive` if `/api/alpecca/pose` is reachable. The live driver
  (VRMViewer 89–118) already maps her real mood→VRMA + expressions; pose data is
  REAL (mood/expressions/glow from her app on :8765).

### Texture upgrades from the OSS research (deployed to the Space + direct-tested)
- **IP-Adapter (SDXL)** — `h94/IP-Adapter/ip-adapter_sdxl.bin`, lazy + defensive.
  `/texture` now takes `ref_image_b64`+`ip_scale`; **FULLY threaded backend-side**
  (`_zerogpu_texture` → `_image_call` → `generate_material_texture` passes the
  garment ref as the IP image). Restyle now conditions fabric on the actual garment
  IMAGE, not just text. Compile-clean; needs a backend restart + in-app DressTab run
  to confirm the full flow.
- **ControlNet UV-lock** — `/texture_cn` (`xinsir/controlnet-canny-sdxl-1.0`,
  StableDiffusionXLControlNetImg2ImgPipeline, lazy + fallback to plain img2img).
  Direct-tested: **strength 0.75 held every panel** while painting bold new fabric
  (plain img2img scrambles at that strength). `scripts/test_controlnet.py`.
  ⚠️ NOT wired into the backend/UI yet — Space endpoint only. And the PIL
  `FIND_EDGES` control image is crude (beaded-mesh artifact) — feed clean
  **panel-edge control from the atlas alpha** instead.

### Current state / how to run (all servers were DOWN at handoff — reaped on session end)
- Backend: `cd apps/vcs/backend && ../.venv/Scripts/python.exe -m uvicorn server:app --host 127.0.0.1 --port 8001` (restart REQUIRED to pick up `.env` `AI_PROVIDER=zerogpu` + latest `ai_service.py`).
- Frontend: preview `vcs-frontend` in `.claude/launch.json`, or `npm --prefix apps/vcs/frontend start` (PORT=3200, `REACT_APP_BACKEND_URL=http://localhost:8001`).
- Live companion needs her app on **:8765** (mood/pose feed) — start via `scripts/run_full.py`.
- The Space stays live on HF independently.

### Solid vs. shaky
- **Solid:** texture render fix (route-verified); ZeroGPU pipeline (extract 22–37s, image 5–27s); animation crossfade+gaze (compile-clean); IP-Adapter (full chain) + ControlNet (Space) endpoints direct-tested; anime deviation guard.
- **Shaky / NEXT (in order):** (1) **wire ControlNet** into the backend (`_zerogpu_texture_cn`) + a "bold / structure-lock" mode in `generate_material_texture` + a UI toggle, and pass an **alpha-derived panel-edge** control image; (2) restart backend + verify IP-Adapter improves the in-app DressTab flow; (3) **foot-grounding IK** (analytic 2-bone, new `lib/vrmIK.js` — feet float through the grid today); (4) **lipsync BLOCKED** — `wawa-lipsync` is the pick but needs her TTS audio (or a speaking-level signal) piped into VCS; it plays only in her own app. Expand motion library later via `bvh2vrma` + `Kalidokit`.

### Key files touched
- `spaces/alpecca-texture-lab/app.py` (3 endpoints: texture / texture_cn / vision_json)
- `apps/vcs/backend/ai_service.py` (`_zerogpu_*`, `generate_material_texture`, `_flatten_atlas_for_init` tint, `_reapply_alpha`, `_hex_to_rgb`)
- `apps/vcs/backend/routes.py` (MaterialTextureRequest + `original_atlas_data_url`/`strength`)
- `apps/vcs/backend/.env` (zerogpu provider + tunables)
- `apps/vcs/frontend/src/lib/{materialUtils.js (extractOriginalAtlas), vrmAnimations.js (computeGaze), api.js}`
- `apps/vcs/frontend/src/components/VRMViewer.jsx` (crossfade + gaze)
- `apps/vcs/frontend/src/pages/StudioPage.jsx` (auto-load + live driver)
- `apps/vcs/frontend/src/components/dialogs/TextureLabDialog.jsx` (atlas wiring, ZeroGPU default provider)
- `scripts/test_{restyle,route_texture,controlnet,zerogpu,zerogpu2,zerogpu3,backend_flow}.py`, `scripts/deploy_texture_space.py`
- OSS research roadmap: workflow journal `subagents/workflows/wf_a00f92a6-85a/journal.jsonl` (8 findings: IK/mocap/lipsync/blending + ControlNet/IP-Adapter/PBR/projection). Ship-license flags: IDM-VTON / nvdiffrast / Ubisoft CHORD = non-commercial; DeepBump code GPL (load `.onnx` only).

---

## Post-review hardening + latency plan EXECUTED (2026-07-04)

Full plan in C:\Users\Jason\.claude\plans\serialized-booping-dream.md. Landed:

**Phase A — felt latency:**
- A1 voice warmup: `_warm_alpecca_voice` now ALWAYS warms Kokoro (the F5-healthy
  short-circuit left the calm-speech engine cold → 44s first line). Knobs:
  ALPECCA_VOICE_WARMUP=1, ALPECCA_VOICE_WARMUP_TIMEOUT=90. home.html pings
  /tts/warmup on page load.
- A2 streaming seam: alpecca/streaming.py (ThinkTagFilter — incremental
  strip_think across chunk boundaries), _LLM._chat_stream (stream=True,
  zero-token retry only, _StreamPartial after partial emission → echo fallback
  replaces draft), generate/chat take optional on_token (regen retries never
  stream; tools/HF/hybrid never stream). Kill switch ALPECCA_STREAM_CHAT.
- A3 WS protocol: client opts in per message ({"stream":true}) →
  reply_start / reply_token× / final authoritative {"type":"reply","streamed":true}.
  Greeting advertises features.stream_chat. Old clients (house-hq) untouched.
  home.html renders a .draft bubble replaced by the final text.
- A4 sentence TTS: home.html sentencesOf() (JS port of speech._sentences,
  pinned by test), SentenceSpeaker + ordered SpeechQueue — first sentence is
  SPOKEN while the rest generates; regen mismatch stops further speech.

**Phase B — persistence:** alpecca/db.py shared connect (busy_timeout=5000) —
all 8 module _connects delegate; WAL+synchronous=NORMAL applied in
state.init_db (harden()); rotating 7-day startup backup (scripts/run_full.py
_backup_soul → data/backups/); clamp-on-load in load_state; state_log pruned
to ALPECCA_STATE_LOG_KEEP_DAYS=30.

**Phase C — Stage 4:** conveyor script scripts/run_alpecca_stage4_conveyor.py
(process_returned_slice per frame → build_animation_library → house-hq assets;
audit by default, --apply for real). Contract fixes: CHARACTER_GROUNDING
("Full-body Alpecca anime woman") leads build_tile_prompt in the ZeroGPU space
(REDEPLOYED); resumable colab worker now runs returned-slice QA after every
upload batch. Nightly drip bat: scripts/run_stage4_nightly_drip.bat
(zerogpu_target → conveyor --apply) — Task Scheduler registration still needs
Jason to run: schtasks /Create /F /TN "Alpecca Stage4 Nightly Drip"
/TR "<repo>\scripts\run_stage4_nightly_drip.bat" /SC DAILY /ST 03:30

**FINAL VERIFICATION (2026-07-04):** suite 302 passed / 1 failed — the one
failure was world-tick under 3-way Ollama contention (two parallel pytest
sessions + live streaming probe, self-inflicted); it passes standalone twice.
All 5 previous baseline failures are FIXED. Live measurements on the running
app: streamed WS turn shows reply_start instantly, first token 10.7s warm
(prompt-eval bound on the 9B), draft==final, 100 tokens streamed; TTS after
warmup 1.3s (was 44.5s cold). data/backups/alpecca-20260704.db exists;
journal_mode=wal on the real save. Nightly drip task REGISTERED (03:30).
Doctor's one X is its own pre-existing false-negative (route probe sends no
token). STILL PENDING (auto-mode blocks production deploys, needs Jason to
run/approve directly): the two Mindscape commands in the section above.

**APP SUITE: launcher + private site + Discord invite (2026-07-04 night).**
One token-gated hub at **/app** (web/app.html, inline assets, no CDN):
- Windows: downloads a REAL packaged **AlpeccaLauncher.exe** (built, 10 MB,
  apps/launcher/dist; rebuild via apps/launcher/build_exe.bat) or the source
  zip (/app/download/launcher.zip streams apps/launcher/src on demand). The
  launcher (tkinter, stdlib-only): status dot polling /system/status, Wake
  her / Open her home / App site / Phone access (share.py) / Invite to
  Discord / Put her to sleep. Works frozen or from source (repo-root walk).
- Android/iPhone: PWA install cards + QR of her tokened URL (works on LAN
  via scripts/share.py, anywhere via --tunnel).
- Discord: GET /app/discord/invite 302s to discord.com OAuth (client_id
  derived from the bot token's first base64 segment; override
  ALPECCA_DISCORD_CLIENT_ID in config.py; permissions=3263552).
- /app/meta reports {exe_built, lan_ip, port, discord_ready}.
- PASSWORD LOCK = the EXISTING auth gate, untouched: APIs/downloads hard-401
  without the token; HTML navigations seed the cookie BY DESIGN (gate's own
  documented behavior — and the TestClient host is whitelisted, so the lock
  test asserts on server._token_ok directly). 5 contract tests green
  (app_site/app_meta/discord_invite/launcher_zip). All routes live-verified:
  /app 200, meta true-values, invite 302 w/ client_id 1522307155254837278,
  zip 7KB w/ sources, exe 200 MZ 10MB.

**CHAT MOVED TO gemma4:cloud (2026-07-04 late — JASON'S PICK, supersedes the
ZeroGPU-chat entry below).** He asked for an Ollama-cloud model that's
efficient and advanced enough to replace the ZeroGPU chat system; options
were presented by name and he chose gemma4:cloud (the same model he already
picked for deep+vision). Now ONE always-warm cloud brain serves chat + deep
+ vision; local qwen3.5:9b is the net everywhere. Implementation: the
existing hybrid path (CHAT_CLOUD_MODEL) — just set
ALPECCA_CHAT_CLOUD_MODEL=gemma4:cloud, ALPECCA_CHAT_ZEROGPU=0 (bat + setx).
Verified live in-app: 8.1s first turn, then 3.3s / 3.3s full turns, recall
works, telemetry "gemma4:cloud". think=false verified clean. The ZeroGPU
9B chat path (below) STAYS BUILT as the switchback: ALPECCA_CHAT_ZEROGPU=1
+ CHAT_CLOUD_MODEL= empty.

**CLOUD-FIRST 9B CHAT via ZeroGPU (2026-07-04 night — superseded same night,
kept as the alternate path).** The ZeroGPU Space now runs the EXACT same
Qwen/Qwen3.5-9B as her local brain (spaces app.py MODEL_ID swap; AutoProcessor
+ AutoModelForImageTextToText load path for the qwen3_5 multimodal arch;
transformers>=4.57; enable_thinking=False in the chat template; REDEPLOYED).
Her chat tier tries the Space FIRST (mind.generate zerogpu-chat block,
ALPECCA_CHAT_ZEROGPU=1, 30s bound): warm cloud replies ~2s generation /
~8s full mind turn (vs ~30s local); if the Space is asleep the LOCAL 9B
answers that turn while the abandoned attempt wakes it — she never goes
quiet, and it's the same model either way. Telemetry:
last_call backend "zerogpu", model "qwen3.5-9b@CREATORJD/alpecca-zerogpu".
Measured live in-app: 17.4s (wake-ish) then 8.2s. Costs HF ZeroGPU quota
per reply; kill switch ALPECCA_CHAT_ZEROGPU=0 → all-local. Cloud-served
turns don't token-stream (whole reply arrives fast); local turns still do.

**Slow-turn incident + fixes (2026-07-04 evening).** Jason hit >60s turns +
the "grounded live mode" timeout line. Chain of causes: (1) a restart race
spawned a DUPLICATE F5 voice worker (~800 MB CUDA) — fixed live (killed
orphan) and permanently (_f5_worker_port_taken() in run_full.py: never spawn
if ANYTHING listens on the port, healthy or warming); (2) with VRAM starved,
Ollama placed the 9B at 0% GPU (all-CPU) — fixed persistently with
OLLAMA_FLASH_ATTENTION=1 + OLLAMA_KV_CACHE_TYPE=q8_0 (user env; halves KV,
auto-placer restored the usual 18% GPU). NOTE: forcing num_gpu on the 9B
WEDGES Ollama 0.30.7 outright (240s hang) — do not pin, leave auto;
(3) the 24-message history doubled CPU prompt-eval — now
ALPECCA_HISTORY_MESSAGES=12 (still 2x the original 6);
(4) turn budgets: ALPECCA_OLLAMA_TIMEOUT=105, WS window 120s — the canned
fallback should now be effectively unreachable. Verified after: warm streamed
turn ~30s total, first token ~12s, no fallback, 9B at 18% GPU.

**Phase D — debt:** world-tick test polls for background persistence (race
fixed); REAL grounding bug fixed in mind.py — the embodied-location line was
LAST in `inner` and the 160-char compact cap truncated it away whenever a
musing existed (she'd mis-report her room); it now goes FIRST. Volume-QA test
fixture now draws a connected character silhouette (head/neck/torso/legs) —
the mechanical probe rightly rejected solid rectangles. All 3 Stage 4 contract
tests green. Mindscape worker deploy STILL pending (auto-mode blocks
production deploys): cd deploy/mindscape-worker && npx wrangler deploy, then
npx wrangler secret put MINDSCAPE_TOKEN, then setx ALPECCA_MINDSCAPE_URL/TOKEN.

## Ollama Pro: cloud deep tier + cloud sight (2026-07-03)

Jason purchased **Ollama Pro** and the machine is signed in (`ollama signin`),
which unlocks Ollama's hosted cloud models through the SAME local API
(`localhost:11434`) — no new transport, no local VRAM, no ZeroGPU queue/quota.

- **New deep backend `ALPECCA_DEEP_BACKEND=ollama-cloud`** (set in
  START_HERE.bat): deep self-acts run on **`gpt-oss:120b-cloud`** — chosen for
  LOW USAGE DRAIN after Jason flagged quota burn (reflection fires several
  times/hour idle). gpt-oss deliberates concisely (~400 chars) and answers
  within budget (no salvage call): a reflection is ~500 tokens in 3.5s, vs
  ~4,500 tokens in 28s on qwen3.5:397b-cloud. `_build_deep` returns
  `("ollama-cloud", model)`; `_generate_deep` routes through
  `_generate_local_thinking` (takes model/num_predict params),
  `ALPECCA_CLOUD_REFLECT_NUM_PREDICT=2500` cap. Knobs: gpt-oss:20b-cloud
  (cheapest) / qwen3.5:397b-cloud (richest) via ALPECCA_OLLAMA_CLOUD_MODEL.
- **Vision auto-routing is now ollama-cloud → zerogpu → local**
  (alpecca/vision.py `_describe_ollama_cloud`). `ALPECCA_VISION_CLOUD_MODEL`
  defaults to qwen3.5:397b-cloud (the ONLY vision-capable cloud model; NOT
  tied to the deep model). Cloud sight serves only explicit image turns —
  **ambient senses (screen glimpses, webcam) are hard-forced local via
  `describe_image(..., ambient=True)`** so background loops can never drain
  metered usage and screen/face pixels never leave the machine. Set
  ALPECCA_VISION_CLOUD_MODEL="" to keep all vision off the metered cloud.
  Verified: `describe_and_recognize` on her avatar = 23.5s, "SELF: yes".
- Fallback chain if signed out/offline: ollama-cloud deep raises → local
  thinking pass → plain local. Chat stays 100% local (privacy line intact:
  deep prompts carry no sensed screen context, unchanged).
- Other cloud models available on the account: deepseek-v3.1:671b-cloud
  (thinking), gpt-oss:120b/20b-cloud (thinking), qwen3-coder:480b-cloud.
- **Final division of labor (Jason's architecture, 2026-07-03): all-local
  qwen3.5 family, near-zero metered usage.**
  - chat → `qwen3.5:4b` (ALPECCA_MODEL): fast, fits VRAM alongside F5.
  - deep reflection → `qwen3.5:9b` (ALPECCA_DEEP_BACKEND=local +
    ALPECCA_REFLECT_MODEL=qwen3.5:9b, new config knob wired through
    `_generate_local_thinking`): think-first musings ~2-5 min, idle work.
  - vision → `qwen3.5:9b` (ALPECCA_VISION_BACKEND=local +
    ALPECCA_VISION_MODEL=qwen3.5:9b — the 9B GGUF has a built-in 456M CLIP
    encoder): ~2.5 min/image on CPU, pixels never leave the PC.
  - `ALPECCA_OLLAMA_TIMEOUT=60` (default 18s cuts long replies under
    co-load → echo fallback).
  - Ollama Pro cloud remains one env flip away: DEEP_BACKEND=ollama-cloud
    (gpt-oss:120b, 3.5s/reflection) / VISION_BACKEND=auto (qwen3.5:397b,
    ~23s/image, metered).
  - **Voice canNOT run on Ollama** — Ollama serves text/vision models only,
    no audio-synthesis endpoint. Her voice stays Kokoro (local CPU) + F5
    (local CUDA), which is already fully local and how Jason likes it.

- **Fallback-line outage + fixes (2026-07-03 late).** She was stuck on "my
  deeper language core is offline" in the home app. TWO causes found:
  (1) the Ollama daemon had silently died AGAIN (repeat offender) — and it
  is now a single point of failure since local AND cloud models route
  through it. Fix: `_ollama_watchdog()` in scripts/run_full.py pings
  /api/version every 60s and respawns `ollama serve` detached if dead.
  (2) The launcher's old option [1] "HF cloud brain (recommended)" routes
  ALL turns to HF InferenceClient with setx model Qwen3-Next-80B which HF
  providers don't serve → permanent fallback. Fix: menu rewritten — [1] is
  now the hybrid stack (Enter default), [2] fully-offline; the HF
  InferenceClient path is env-only (ALPECCA_LLM_BACKEND=hf) and setx
  ALPECCA_HF_MODEL corrected to Qwen/Qwen2.5-7B-Instruct. ALSO: stale setx
  stale user-env model settings synced to the current
  architecture so out-of-bat launches match the bat. ALSO: gpt-oss cloud
  chat could return EMPTY content (its internal reasoning eats num_predict
  under her big system prompt) — cloud calls now get num_predict>=512 and
  an empty cloud reply raises → falls to local, never ships "" to a person.
  Verified live end-to-end: 3-4.6s cloud replies in the app, turn-2 recall
  works, telemetry truthful.
- **FINAL brain config (2026-07-03, latest — supersedes hybrid-chat entry
  below): gpt-oss is OUT.** Jason never approved it; I had substituted it
  twice. Now: **qwen3.5:9b is her ONE brain** — chat + deep reflection +
  vision, all local (ALPECCA_MODEL=qwen3.5:9b); qwen3.5:4b only serves the
  cheap idle-chatter tier (ALPECCA_FAST_MODEL). ALPECCA_CHAT_CLOUD_MODEL is
  EMPTY (hybrid off; the knob remains for a model Jason picks himself —
  only qwen3.5 cloud tag is qwen3.5:397b-cloud). START_HERE.bat menu
  removed (one brain path, Enter to wake). Related fix: server.py's
  hardcoded WS_CHAT_REPLY_TIMEOUT_SECONDS=30 made the app give up before
  the 9B finished (~25-40s) and serve the canned "deeper model taking too
  long" line — now max(45, ALPECCA_OLLAMA_TIMEOUT+15)=75s, override
  ALPECCA_WS_CHAT_TIMEOUT (`import os` was added to server.py for this).
  Verified live in the home app WS path: 17.5s/19s turns on qwen3.5:9b,
  grounded replies + turn recall. DO NOT swap models without Jason's
  explicit approval.
- **gemma4:cloud for deep+vision (2026-07-04, JASON'S EXPLICIT NAMED PICK —
  latest state).** He asked "what about gemma4"; probing found
  `gemma4:cloud` on his Ollama plan: 33B BF16, 256K ctx, thinking + tools +
  vision — ~12x lighter usage than the rejected 397B. He chose it by name
  for the cloud deep+vision link. Config now:
  DEEP_BACKEND=ollama-cloud + OLLAMA_CLOUD_MODEL=gemma4:cloud (local 9B
  thinking = net), VISION_BACKEND=auto + VISION_CLOUD_MODEL=gemma4:cloud
  (→ ZeroGPU Space → local 9B). Chat stays local qwen3.5:9b; chatter
  qwen3.5:4b; ambient senses hard-local. Verified: deep 4.4s with
  1,275-char think chain; vision+self-recognition 3.1s through
  describe_and_recognize. (His local gemma4-e4b is actually a gemma3n
  6.9B text-only build — unused now.)
- **397B REMOVED — all-local 9B interlude (2026-07-04, superseded the
  chained-cloud entry below; deep+vision then moved to gemma4:cloud, above).** Jason challenged qwen3.5:397b-cloud too
  ("why you keep using this?") — the "both, chained" answer approved a
  routing shape, not that model; treating it as model approval was a
  mistake. Facts: Ollama cloud hosts NO qwen3.5:9b (only 397B; the
  ollama.com/library/qwen3.5:9b page he linked is the LOCAL tag). Current
  state: chat + deep + vision ALL on local qwen3.5:9b, 4b = chatter tier,
  every cloud model env EMPTY (config defaults too). The official
  `qwen3.5:9b` library tag was pulled but MISBEHAVES on Ollama 0.30.7
  (16 GB alloc despite num_ctx=8192, 0% GPU, wedged loads) — it's parked
  as `qwen3.5:9b-official`; the name `qwen3.5:9b` was re-aliased to the
  proven lmstudio-community GGUF (same weights). Retry the official tag
  after an Ollama upgrade. Only remaining cloud path that serves HIS model:
  ZeroGPU Space running Qwen/Qwen3.5-9B (exists on HF, multimodal,
  needs transformers>=4.57 + Space rebuild) — NOT built, needs his go.
  Verified in-app: 30.5s turn (cold), served by qwen3.5:9b, grounded.
- **Cloud offload, CHAINED (2026-07-04, Jason chose "both, chained" —
  SUPERSEDED same day, see above).**
  Deep reflection + vision now try the cloud first and degrade gracefully:
  **qwen3.5:397b-cloud on Ollama → his ZeroGPU Space → local qwen3.5:9b.**
  Chat stays 100% local on the 9B. Implementation: DEEP_BACKEND accepts a
  comma-chain ("ollama-cloud,zerogpu") — mind._build_deep builds
  self._deep_chain, generate() walks it, local thinking pass stays the
  final net; vision was already chained via VISION_BACKEND=auto. Jason
  explicitly approved qwen3.5:397b-cloud here (config default changed;
  earlier "frugal default" note is superseded). Verified: link 1 serves in
  ~35s with a 10k-char thinking chain; forced link-1 failure correctly
  falls through. Two hardening fixes from that test: (1) config's
  _gradio_api_name() undoes Git-Bash mangling of "/chat" api names;
  (2) when the deep chain exhausts, the plain net now runs on
  REFLECT_MODEL/local — it used to re-dial the cloud model name.
  Env synced (bat + setx): ALPECCA_DEEP_BACKEND=ollama-cloud,zerogpu,
  ALPECCA_OLLAMA_CLOUD_MODEL=qwen3.5:397b-cloud, ALPECCA_VISION_BACKEND=auto.
- **Mindscape Cloudflare worker: still NOT deployed** (wrangler IS
  authenticated on this machine; deploy blocked pending Jason's explicit
  go: `cd deploy/mindscape-worker && npx wrangler deploy`, then
  `npx wrangler secret put MINDSCAPE_TOKEN`, then setx
  ALPECCA_MINDSCAPE_URL + ALPECCA_MINDSCAPE_TOKEN).

- **Hybrid chat + real conversational memory (2026-07-03, Jason's ask:
  "context too low / reduce wait / hybrid").** Two root causes fixed:
  - Her forgetfulness was NOT num_ctx — chat only sent `_history[-6:]` (3
    exchanges). Now `ALPECCA_HISTORY_MESSAGES` (default 24, set in bat)
    rides along on every turn, and the raw `_history` list is bounded at 4x.
    Verified: recalls a fact stated 22 messages back.
  - `ALPECCA_CHAT_CLOUD_MODEL=gpt-oss:120b-cloud` (bat) turns on hybrid
    chat in `_chat`: reasoning-tier turns try the cloud model FIRST
    (~1.7-3.5s replies, `ALPECCA_CLOUD_NUM_CTX=32768`) via a dedicated
    20s-timeout client; ANY failure falls through to local qwen3.5:4b
    (verified with a 404 model: logs "cloud chat unavailable -> local" and
    answers locally). Fast-tier/chatter and explicit-model calls never
    touch the cloud. `llm.last_chat_model` keeps last_call telemetry
    truthful about who actually served. Empty CHAT_CLOUD_MODEL = 100%
    local chat again. NOTE: with hybrid on, chat text (not senses) leaves
    the machine — Jason explicitly requested this trade for speed.

---

## Local brain + reflection-tier thinking (2026-07-02)

**New local chat brain: `qwen3.5:4b`** (Qwen3.5-4B Q4_K_M, pulled from
`hf.co/lmstudio-community/Qwen3.5-4B-GGUF:Q4_K_M`, aliased `qwen3.5:4b`).
Set via `ALPECCA_MODEL=qwen3.5:4b` in `START_HERE.bat`. Newer arch than
a retired older local model, ~2.7 GB — fits the 4 GB RTX 3050 (45 tok/s when the card is free,
~11 tok/s under auto placement alongside F5/vision). `/api/chat` with
`think=false` (mind.py's path) yields clean no-think replies; the inline
`<think>` leakage only happens on raw `/api/generate`. **F5/Kokoro voice
config untouched** — user likes the voice as-is; do not move F5 off `cuda`.
`ALPECCA_NUM_GPU` knob exists (config.py `OLLAMA_NUM_GPU` → `_chat` options)
to force full-GPU placement, default OFF to protect F5's VRAM slice.

**Reflection-tier thinking (plan item 2) is DONE.** Her deep self-acts
(reflect, recursive self-question, choreography/sheet authorship — every
`tier="deep"` caller) now run a real chain-of-thought pass when they land
locally: `_LLM._generate_local_thinking` in `alpecca/mind.py` calls Ollama
`think=True` (private reasoning returned in the separate `thinking` field),
budget `ALPECCA_REFLECT_NUM_PREDICT=1600`, own slow client
(`ALPECCA_REFLECT_TIMEOUT=600`s — reflection is idle work, nobody waits).
Order: cloud deep tier (ZeroGPU) first → local think pass → plain local.
qwen3.5:4b deliberates LONG (7k+ chars) and can exhaust the budget before
answering — the salvage pass hands her own chain back and asks for just the
conclusion (no-think, short), so the musing still comes from real
deliberation. Verified live: 296s, 7,789-char private chain → grounded
3-sentence musing. Observability: `last_call.used_tier == "reason-think"`,
`llm.last_thinking`, console line in `reflect()`. Kill switch:
`ALPECCA_REFLECT_THINK=0`. No overlap risk: Reflection.MIN_GAP_S=600 >
worst-case deliberation ~300s. Remaining plan item: audio self-voiceprint
(needs resemblyzer, local-only).

---

## Game-state review (2026-06-13) — persistence hardening to-dos

**Save DB is healthy.** `data/alpecca.db` passes `PRAGMA integrity_check` (`ok`),
1.75 MB / 427 pages, header consistent. (A first pass flagged it as "corrupt" —
that was the documented sandbox-mount *truncated-read* quirk, not the real file.
Lesson: copy the DB locally before running integrity checks through the mount.)

No emergency, but persistence has real **hardening gaps** worth closing before
she's relied on heavily:
- **No WAL, no `busy_timeout`.** Both `_connect` helpers (`alpecca/state.py`,
  `alpecca/memory.py`) open plain `sqlite3.connect`. Add
  `PRAGMA journal_mode=WAL` + `PRAGMA busy_timeout=5000` (and `synchronous=NORMAL`).
  This matters because the config docstring suggests pointing `ALPECCA_HOME` at a
  synced Google Drive folder — SQLite on cloud-synced storage without WAL is a
  known corruption risk. Keep `ALPECCA_HOME` on local disk unless WAL is on.
- **Concurrent writers aren't serialized.** `mind_lock` (asyncio) only guards the
  *in-memory* mood mutation; the slow self-directed work (`idle_self_direct`,
  `compose_volunteer`) runs off the lock via `asyncio.to_thread` and writes the
  same DB (desires/selfmod/memory) alongside the 8 s drift tick and chat handler.
  Multiple OS threads on one file with no busy_timeout → possible "database is
  locked" errors. Serialize DB writes or add the busy_timeout above.
- **No auto-backup.** Only safety net is a manual copy (`alpecca.backup.db` sits on
  the Desktop). Add a rotating backup on startup/shutdown.
- **No validation on load.** `load_state` trusts persisted values are in [0,1] —
  clamping only happens inside the update rules, so a bad/edited value flows
  straight into the prompt. Clamp on load too.
- **`state_log` grows unbounded** — one row per ~8 s tick plus per chat, never
  pruned. Add periodic pruning/rotation.

---

## TL;DR

Alpecca is a **local, private AI companion** — a stateful agent on one machine
with a persistent mood, real memory, senses, an explicit ethic, self-set goals,
self-tuning, self-questioning, and a reactive anime face. Brain = local Ollama.
**Grounding is the hard rule:** every self-report reads from real internals;
nothing is confabulated.

Her **inner life is real and strong** (mostly unit-tested). The recent friction
was **setup**, now handled by a `doctor` + one-click `.bat` launchers.

**Target machine:** Windows, **RTX 3050 Laptop (~4 GB VRAM)**. Plan around 4 GB.

---

## How to run her

### First time
```
cd C:\Users\Jason\Documents\GitHub\alpaccaai
python -m pip install fastapi uvicorn websockets ollama
ollama pull qwen3:4b-instruct-2507        # 4B brain that fits a 4 GB GPU
python scripts\doctor.py                  # the source of truth for "why won't she run"
```
`doctor.py` checks Python, packages, Ollama + model, the port, every sense, and
the neural-face setup, and prints the exact fix for each. Run it whenever stuck.

### Every time (use the .bat launchers — they avoid the PowerShell env-var trap)
- **`start_full.bat`** — brain + all senses + cowork (expression-sheet face).
- **`start_face.bat`** — brain *and* the THA3 neural face in two windows (after
  `setup_face.bat`).
- `python server.py` — private, senses off.
Open **http://127.0.0.1:8765** ( `/classic` = old chat UI with voice/image ).

### Desktop app + remote access (new)
She now runs as a **real desktop app**, not just a browser page:
- **`Alpecca-App.bat`** (or `python app.py`) — a native window via **pywebview**
  (`pip install pywebview`; falls back to your browser if it's absent). Runs the
  same FastAPI server in-process, senses on, in its own window.
- **Remote access** is opt-in and **always token-gated** (server.py `_auth_gate`
  middleware + `/ws` guard; localhost is *not* special-cased, so a tunnel can't
  slip past): `ALPECCA_REMOTE=1` binds `0.0.0.0` for LAN devices;
  `ALPECCA_TUNNEL=cloudflare|ngrok` opens a public internet URL via a tunnel CLI.
  `app.py` mints `ALPECCA_ACCESS_TOKEN` if unset and prints it; remote clients
  append `?token=…` once (a cookie carries it after). Knobs in `config.py`
  (REMOTE_ACCESS / ACCESS_TOKEN / TUNNEL / BIND_HOST). Senses, memory and brain
  stay local — only chat travels.
- **Package to one `.exe`:** `pip install pyinstaller && pyinstaller --noconsole
  --add-data "web;web" --name Alpecca app.py` (add `data/`/config as needed).
- **Full runbook** for reaching her remotely AND working the PC through her
  (computer-use over the tunnel, confirm flow, guards, checklist):
  `docs/PASSDOWN_remote_computer_access.md`. Quick start: double-click
  `SHARE_PHONE.bat` — it prints the token-gated trycloudflare link.
  (2026-07-06: `scripts/share.py` was fixed — it previously shared
  UNAUTHENTICATED and never really bound 0.0.0.0; pull before sharing.)

### Screen-share in her home (new)
The **Share** nav button now has her walk to the **Observatory** and *hold the live
shared screen as a framed window beside her* in the 3D home (THREE.VideoTexture on
a panel parented to her figure), replacing the old flat fullscreen desk overlay.
Server: `POST /observatory/screen/start|stop`, `mind.set_screen_sharing()` (she
stays put while sharing); she still sees the screen via `/sight/push` (grounding).

### Neural face on the 4 GB laptop GPU (optional)
THA3 fits *with* the brain via three levers: light model (`separable_half`,
~half VRAM), the 4B LLM, and **adaptive framerate** (face renders fast only while
she speaks, drops to ~4 fps while she thinks, so the brain gets the GPU when it
needs it). Run **`setup_face.bat`** once (installs CUDA torch, pulls the 4B model,
clones THA3, preps her 512 image; the one manual step is downloading THA3's light
models into `vendor\talking-head-anime-3-demo\data\models\`). If THA3 OOMs, the
app silently falls back to the expression-sheet face (no VRAM).

### Critical Windows gotcha
In **PowerShell**, `set VAR=value` does NOTHING (that's cmd syntax) — use
`$env:VAR="value"`. The `.bat`s sidestep this. For git, PowerShell here-strings
mangle commit messages — write to a temp file and `git commit -F`.

---

## What was built this session (on top of the existing core)

**Backend (Python, mostly tested):**
- Emotion model gained `curiosity` + `social_hunger` (`homeostasis.py`).
- `affect.py` — expressive readout (feeling/valence/arousal/tempo/gesture + voice
  markup) read by prompts, avatar, and TTS.
- `soul.py` — master agent over 7 subagents (deterministic sensors + LLM
  reasoners), arbitrated by the Good Person Principle.
- `charter.py` — her constitution, enforced in code (priority hierarchy; never
  self-deletes; file ops confined to Desktop/Pictures/Music/Video/general;
  internet only to reach Jason).
- `desires.py`, `selfmod.py`, `journal.py` (+ recursive self-questioning),
  `learning.py` (self-training: grounded *lessons* from her history that steer
  `selfmod`), `home.py` (5 roamed rooms), `pose.py`, `desktop.py` (charter-guarded
  file room).

**Front-end — the super-app at `/` (`web/home.html`):**
- Live 3D home (Three.js) + integrated chat (one WebSocket) + voice (🎤 push-to-
  talk, 🔊 mood-driven TTS) + camera (📷) + cowork (🖥).
- **Live anime face**: her 16 drawn expressions (sliced from her expression sheet
  → `data/character/expressions/`) mapped from her real mood, with lip-sync and a
  mood-glow ring.
- Senses strip (👁/🎤/📷/🖥) + "what she last saw" + her cursor when she works +
  an **activity ticker** showing her autonomous acts.
- Facet panels: Studio, Library, Journal, Mind, Workshop (desires + revisions +
  lessons), Senses/Workspace, Files, Play (browser games).

**Avatar tiers (each driven by the *same grounded mood*, degrading to the next):**
THA3 neural > pose-swap real-art > RIGFORGE mesh (`web/rigforge.html`) >
expression-sheet face > portrait > SVG. Also still wired: Live2D/Cubism, Spine,
layered rig, ToonCrafter clips (see the prior handoff section).

**Ops:** `scripts/doctor.py`, `start_full.bat`, `setup_face.bat`, `start_face.bat`.

**Routes added:** `/`, `/classic`, `/home/state`, `/growth`, `/soul`, `/journal`,
`/memories`, `/desktop` (+move/rename), `/sight`, `/games` (+play),
`/avatar/expression/{name}`, `/avatar/skeleton`, `/avatar/rigpose`, `/rigforge`
(+capture).

---

## Solid vs. shaky (honest)

**Solid:** the backend modules + their tests (emotion rules, affect, home,
desires, selfmod, soul, journal, charter guards, learning, pose). LLM brain works;
state persists; the autonomous loop is wired and livened.

**Shaky:**
- **Persistence hardening pending** (DB itself is healthy — see the game-state
  review section up top). No WAL, no busy_timeout, off-lock concurrent writers, no
  auto-backup, no load validation. Close these before relying on her heavily,
  especially if `ALPECCA_HOME` ever points at synced storage.
- **`web/home.html` is large and NOT fully syntax-checked.** The dev sandbox mount
  serves a stale truncated copy, so a full `node --check` wasn't possible; blocks
  were verified individually via the editor. **If the page renders blank, it's a
  JS error — open F12, find the red line, fix it.** (That's how the earlier
  `THREE`-before-load blank-page bug was caught.) A Phase-4 audit on the real file
  is the top to-do.
- Neural face on 4 GB is tight (fallback covers OOM).
- Senses/cowork need optional packages + flags (doctor reports them).

**Dev-env quirk:** the Linux sandbox mount intermittently truncates large files on
read; the canonical Windows files are correct. Run tests on the real checkout:
`python tests\test_core.py` (or `python -m pytest -q`).

---

## Her real art (still true)
Character bible in `data/character/reference/`. She is a **humanoid anime girl**
(cream-blonde, glowing eyes, chest power-core) — *not* an alpaca (legacy
placeholder). Backgrounds removed (transparent). **`data/` is gitignored** — her
DB, memories, art, and avatar exports live there and don't travel with the repo; a
fresh clone needs her pose/portrait PNGs replaced. The expression face uses
`data/character/expressions/` (sliced this session) and `data/avatar/portraits/`.

---

## Work plan (where we are — from docs/ALPECCA_CURRENT_PROGRESS.md)
- **Phase 0 — runs reliably:** DONE (doctor + launchers).
- **Phase 1 — visibly alive on her own:** DONE (livelier cadences + activity ticker).
- **Phase 2 — presence:** DONE (expression face + lip-sync + mood-driven voice).
- **Phase 3 — senses, visible:** DONE (senses strip + "what she sees" + cursor).
- **Phase 4 — consolidate front-end:** PARTIAL. **Next:** full audit of
  `home.html` (node-check the real file; fix any syntax slip; finish/verify the
  half-wired pieces), give each 3D room distinct visual purpose.
- **Phase 5 — stretch:** THA3 on the laptop (built; needs the one-time setup run +
  model download); cowork reliability + her cursor; RIGFORGE → `Alpeccaai-data`
  self-training loop; AutoSprite-generated expression/animation frames.

## Immediate next steps
1. **Harden persistence** (DB is healthy, this is preventive): WAL + `busy_timeout`
   in both `_connect` helpers, serialized/single-writer DB writes, a rotating
   auto-backup, clamp-on-load, and keep `ALPECCA_HOME` on local disk.
2. `setup_face.bat` → `python scripts\doctor.py` → `start_face.bat`; confirm she
   comes up with brain + neural face on the 4 GB GPU.
3. Phase-4 audit of `web/home.html` on the real checkout (node-check; fix blanks).
4. Watch the activity ticker a few minutes — confirm the autonomous loop fires.

## Orientation
`CLAUDE.md` (architecture) · `docs/` (design + review docs) · `alpecca/` (modules)
· `server.py` (FastAPI + WS) · `web/` (UI) · `tests/test_core.py` (Ollama/Windows-
free) · `scripts/` (doctor, run_full, run_talkinghead, import_rig, build_manifest).

---

## Prior handoff (2026-06-11) — still-relevant notes
- Branch `build/alpecca-companion` → PR #2 against `main`; tests were 96 passing
  then (more added this session).
- The full avatar tier stack predates this session: **THA3** (`talkinghead.py`),
  **Cubism** (`live2d.py`, drop a `.model3.json`), **Spine** (`spine.py`,
  StretchyStudio export — the originally-recommended primary rig path),
  **ToonCrafter clips** (`run_tooncrafter.py` → `data/avatar/*.mp4`), **layered
  rig** (See-Through PSD → `import_rig.py`), **mesh rig**, pose/SVG.
- Recommended full-rig pipeline (needs the user's GPU, all free/open):
  See-Through (decompose art → PSD) → StretchyStudio (in-browser auto-rig →
  Spine 4.0 JSON) → drop into `data/avatar/spine/`. Tune the renderer fit to her
  real skeleton on first export.
- PIXI + pixi-spine vendored in `web/vendor/` (local-first). Live2D Cubism core is
  still CDN (proprietary, model tier only).
- Talk mode (`scripts/run_talk.py`) needs a separate Python 3.12 venv
  (`.venv-talk/`) — pyaudio has no 3.14 wheels; browser 🎤 avoids this.
