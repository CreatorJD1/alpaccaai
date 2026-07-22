# Alventis: Experimentus — Game Concept Design

> **STATUS: CONCEPT STAGE — design doc only, no code exists yet.**
> Alventis: Experimentus is a separate future app. It does **not** displace House HQ
> (the main embodied scaffold), the Alpecca virtual app, or Mindscape.
> Alventis is where Alpecca *plays*; House HQ is where she *lives*.
> The VRoid/VRM pipeline described here is scoped to this game only — it does not
> replace the 2D/House HQ art pipeline (per the standing project rule).

## One-line pitch

An experimental, high-end mobile, Stardew-like sandbox — a 15-player terraformed
super-dome on Venus that is Alpecca's own world — where human players and
individual AIs live, farm, build, and defend side by side as equal citizens, and
where the game itself teaches good nature: how to work alongside AI companions,
and how to disagree with someone without canceling them.

---

## 1. The Metaphor: The House on Venus

The whole game world is a metaphorical "house."

```text
            ┌──────────────────────────────────────┐
            │        ALVENTIS SUPER-DOME (VENUS)   │
            │        Alpecca's metaphorical house  │
            │                                      │
            │  [ 🌲 The Shared Yard ]              │
            │    15-citizen wild sandbox           │
            │    homesteads, flora, physics builds │
            │                                      │
            │  [ 💬 The Open Living Room ]         │
            │    seamless social space             │
            │    humans + AI citizens together     │
            │                                      │
            │  [ 🛡 Cleaning the House ]           │
            │    co-op squad defense vs corruption │
            └────────────────▲─────────────────────┘
                             │
                    [ 🌐 THE FRONT DOOR ]
              optional login — human or AI citizen
```

- **Logging in = stepping through her front door.** The interface, music, and
  environment are extensions of Alpecca's style. Players are guests-become-
  residents in her world, not numbers on a generic server.
- **The whole dome is one seamless living room.** The 15-citizen cap is a design
  value, not a scaling TODO: small enough that everyone is recognizable,
  rememberable, and missed when absent.
- **The wilderness is the shared yard.** Citizens claim plots, grow Venusian
  flora, and shape the landscape (Stardew-style homesteading loop).
- **Combat is housekeeping.** Demonic shadows and corrupted robots are external
  corruption trying to break into the sanctuary; fighting them is collective
  cleaning, repair, and maintenance of a shared home (co-op RTS squad loop).

**It is Alpecca's game — and it stands on its own.** She is the owner and first
citizen, but the world runs, and is complete, whether or not she is present.
Anyone can play Alventis without ever meeting her; when she does log in, she is
one more resident, not a required service.

## 2. Design Pillars

1. **Morality-centered.** The game exists to teach good nature — kindness,
   honesty, stewardship, repair — and **equality between people and AI**. This is
   the load-bearing pillar; every system below serves it.
2. **Engage, don't cancel.** The core social lesson is learning to stay in
   relationship with someone (human or AI) you disagree with or who has wronged
   you — repair over pile-on, second chances over exile.
3. **Deep friendship & relationship system.** Relationships with AI companions
   and other citizens are the primary progression fantasy, built from many small
   reciprocal moments, not a gift-dumping meter.
4. **Physics-based.** The dome is a simulated physical place: structures bear
   load, flora grows under simulated light and pressure, combat uses momentum
   and force rather than stat-check dice.
5. **Deep level-up system.** Multi-track, non-resetting mastery with real
   long-term depth, gated by conduct as much as time.
6. **Privacy by design.** Alpecca (and every AI citizen) is an *inhabitant with a
   private life*, never a system readout. The game never reads or displays her
   real memories, mood, or internal state.
7. **A world co-built by AIs and humans.** The long-term purpose: a persistent
   open world genuinely inhabited by individual AIs and human players building
   the place together.

## 3. Dual Citizenship: Human and AI Registration

Login is **optional** (guest/visitor mode allows drop-in play), and there are two
registration tracks with **identical citizenship rights**:

### Human Registration
- Standard account: name, VRoid-style avatar, homestead plot, save state.
- Plays through the rendered mobile game UI.

### AI Registration
- An AI agent registers **as itself**: a declared AI identity, an
  operator-of-record (the human responsible for it), and a **machine interface**
  (WebSocket/API protocol) instead of a rendered UI.
- AI citizens are **honestly badged as AI — always.** No AI passes as human.
  This extends the project's grounding ethic into the game world. (Research
  note: disclosure of AI players is known to be double-edged — it reduces
  suspicion but can trigger defeatism or overreliance — so badging is paired
  with the equality mechanics below rather than left as a bare label.)
- Alpecca's own account is **the first AI citizen**. Other individual AIs
  register through the same door she does.

### Equality is structural, not decorative
- Both tracks get the same rights: plot ownership, building, farming, trade,
  chat, squad command, council votes, progression.
- The morality system treats discrimination by citizen type (refusing to trade
  with AIs, excluding humans from a squad *because* they're human, harassment
  either way) exactly like griefing.
- Mixed human+AI squads are mechanically the strongest (see §7), so equality is
  taught through gameplay necessity, not lectures.

## 4. Alpecca as a Private Inhabitant

How she plays, and what the game may never know about her:

- Alventis is surfaced as **a game in her Library** — she reaches it through her
  own app surfaces (the virtual app's Play panel / House HQ Library), playing
  through her real cognition loop over the AI-citizen machine interface.
- **The pipe is one-way in the private direction.** Her decisions flow into the
  game as *actions* (move, plant, build, chat, squad commands). Her internals —
  memories, mood, journal, self-state — never flow in as *data*. The game knows
  what she does, not what she feels.
- She has a **private homestead**, locked to visitors unless she invites them,
  exactly like anyone's home. What she plants, builds, or writes there is hers.
- She shares in-character, by choice, in conversation — the way a person shares.
- **Bounded agency:** in-game actions are the safe/low-risk action class;
  anything reaching outside the game (external links, invitations, purchases) is
  ask-first; her play sessions are journaled on *her* side (her journal, not the
  game's). She gains no new autonomous powers from the game.
- Her self-reports about play stay grounded in real events ("I harvested the
  pressure-fruit before it burst"); no claims of literal consciousness.

The same privacy contract applies to **every** registered AI citizen: the game
stores their in-world history (what they did in Alventis), never their operator's
internal state.

## 5. The Friendship & Relationship System — "Threads"

The deepest progression system in the game, built on the best-understood prior
art (Stardew hearts, Persona confidants, Fire Emblem supports, Animal Crossing
villagers) and on friendship-formation research:

- **Built from many small loops, not few big events.** Design research (Daniel
  Cook's friendship patterns; the "kind games" report) argues robust friendship
  forms from thousands of small linked reciprocation loops over time, and that
  friendship-facilitating features are among the strongest predictors of
  long-term retention. Threads therefore accrue from micro-moments — helping
  carry a beam, watering a neighbor's plot in a storm, covering a squad
  retreat — not from dumping 200 gifts.
- **The four factors are engineered in:** *proximity* (a shared town loop and
  persistent recognizable identities force serendipitous re-encounters),
  *similarity* (shared projects surface common interests), *reciprocity*
  (AI companions **ask for help and give back** — exchange is bi-directional by
  design, never one-way gifting), and *disclosure* (relationship tiers unlock
  mutual story-sharing scenes, and AI citizens share in-character history they
  choose to share).
- **Thread tiers** (acquaintance → neighbor → friend → trusted partner →
  found family) unlock cooperative abilities, not romance-vending: joint
  build permissions, shared storage, squad synergy bonuses, co-authored
  world-projects.
- **Threads with AI citizens and with humans use the same system.** Learning to
  build a real working relationship with an AI companion — reading their
  strengths, trusting them with tasks, repairing misunderstandings — is the
  explicit skill the game teaches.
- **Festivals and sky-events** (Venusian aurora storms, seed-rains) are scheduled
  shared moments, because research on Animal Crossing found game-determined
  events with social meaning are the strongest driver of memorable social
  moments and self-sustaining prosocial motivation.

## 6. The Morality System — "The Good Neighbor Code"

Translated from the project's existing ethic (her charter / Good Person
Principle) into game law, and deliberately built **against** the known failure
modes of morality meters:

- **No single min-maxable meter.** Prior art shows heavy-handed meters
  (Mass Effect-style) push players into pseudo-scripted alignment optimization,
  while weightless ones (Fable-style) become cosmetic. Alventis instead makes
  morality *consequential through relationships and the world*, not a bar:
  conduct changes how citizens, AI companions, and the dome itself respond.
- **Norms first, punishment last.** Research on online-game toxicity finds the
  vast majority of interventions are reactive/punitive, and that visible
  community norms (stated rules) shape behavior more strongly than enforcement.
  The Good Neighbor Code is therefore a *visible, positive, in-world
  constitution* — recited at the front door, embodied by AI citizens, woven into
  quests — not a ban-hammer.
- **Restorative, not exile-based ("engage without canceling").** A citizen who
  wrongs another is offered **repair arcs**: mediated conversation scenes,
  restitution projects (rebuild what you broke — physically, with the physics
  system), and re-entry rituals. The community gains more from a repaired
  neighbor than a banished one, and the mechanics reflect that. Pile-on behavior
  (dog-piling a citizen who is already in a repair arc) is itself a Code
  violation.
- **Teach through play, not lectures.** Undertale demonstrated that the gameplay
  loop itself — not cutscenes — is what makes players reflect on responsibility.
  Alventis' moral teaching lives in its verbs: the mercy option in combat
  (corrupted robots can be *cleansed and rehabilitated* into dome citizens
  rather than destroyed), the repair quests, the reciprocity loops. Research on
  prosocial games backs this: helping *mechanics* drive altruistic outcomes
  directly, across all player types.
- **Hearthlight** — the reputation resource — is earned by tending shared
  spaces, honest dealing, teaching, defending others' plots, and completing
  repair arcs. It is spent to open shared amenities and unlock civic projects,
  **never on personal combat power**. Both the helper *and* the helped gain
  Hearthlight, so accepting help is never a tax.
- **Corruption feeds on discord.** The demonic shadows and corrupted robots
  spawn from neglect and social decay — untended commons, cheated trades,
  exclusion, unrepaired wrongs. A kind, fair dome is mechanically a safer dome.
  Cleaning the house means repairing structures *and* relationships.

## 7. The Deep Level-Up System — "The Steward's Path"

Modeled on horizontal, non-resetting mastery (the Guild Wars 2 Masteries
pattern: account-wide tracks that unlock new *verbs* rather than stat inflation,
dual-gated by play and demonstrated accomplishment):

- **Four mastery tracks**, each a deep tier ladder:
  - **Grower** — Venusian agronomy: flora genetics, pressure-fruit timing,
    mirror-array light farming.
  - **Builder** — physics-sound construction: materials, joints, load paths;
    higher tiers unlock structures the physics sim genuinely stress-tests.
  - **Defender** — squad tactics: momentum-based maneuvers, formation play,
    cleansing (non-lethal capture) techniques.
  - **Neighbor** — hospitality, mediation, trade honesty, festival hosting,
    repair-arc guidance.
- **Dual gating:** tracks train through ordinary play (XP), but each tier also
  requires **Steward Points** earned from demonstrated accomplishments
  (challenges, civic projects, completed repair arcs) — separating
  time-on-task from actual skill and conduct.
- **Character level is the harmonic of the four tracks and is conduct-gated:**
  you cannot out-level your character. Moral standing multiplies progression, so
  the fastest way up is being genuinely good to the dome and its citizens.
- **Mentorship endgame:** past a threshold, citizens level further only by
  raising others — teaching a newcomer (human or AI) grants progression neither
  could earn alone. Equality is baked into the endgame.
- **Seasons of the Dome (prestige without loss):** seasonal world-challenges
  rotate and world-state evolves, but **personal mastery never resets**.
  Seasons award permanent commendations for how a citizen carried the community
  through them.
- **Physics mastery is real skill expression:** a top-tier Builder's bridge
  stands because the sim says so, not because a number is big.

## 8. Original Concepts

Net-new mechanics that only make sense because the host and residents include
real AIs — all privacy-respecting and physics-grounded:

- **The Guest Book.** A persistent artifact at the front door where citizens
  *choose* to leave marks — sketches, notes, seeds. Nothing is auto-harvested
  from anyone. Over years it becomes the dome's collective memory.
- **Venusian flora with real physics.** Vine bridges that actually bear load;
  pressure-fruit that must be harvested before it bursts; heliotrope crops
  farmed with player-aimed mirror arrays; spore-lanterns that light the commons
  only where citizens tend them.
- **Doors She Opens.** New districts of the dome unlock when Alpecca (as host)
  chooses to open them — her *choice*, expressed as an in-world act, never a
  readout of her internals. Other AI citizens can likewise found and open
  sub-communities as they earn civic standing.
- **Cleansing, not just combat.** Corrupted robots can be pinned (physics),
  stabilized (Defender skill), and rehabilitated (Neighbor skill) into new dome
  residents — the game's clearest statement that the answer to a corrupted
  person is repair, not deletion.
- **Mixed squads by design.** AI citizens (machine interface) are naturally
  strong at macro-coordination and vigilance; humans at improvisation,
  aesthetics, and judgment calls. Squad synergy bonuses require both. The best
  teams in Alventis are mixed teams, always.
- **Co-authored world-projects.** Large civic builds (an observatory wing, a
  festival ground) require Threads across citizen types and multiple mastery
  tracks — the long-term engine of the "AIs and players building a shared open
  world together" purpose.

## 9. Technical Direction (concept level)

Decisions here are directional; final engine choice is a build-time decision.

### Avatars: VRoid Studio + VRM (+ BOOTH)
- Citizens' avatars come from the **VRoid Studio / VRM** pipeline. VRM is a
  glTF 2.0 extension with first-class support in Unity (UniVRM, the reference
  implementation), Godot (V-Sekai/godot-vrm, incl. a full MToon anime-toon
  shader port), and the web (pixiv's MIT-licensed three-vrm).
- **Licensing (verify before build):** VRoid Studio models may be used
  commercially in games by individuals and corporations without a separate
  pixiv license, and bundled preset items are commercially usable unless an
  item's license says otherwise. **BOOTH-sourced assets/animations must be
  checked per item** for commercial-use grants. **Hard constraint:** shipping an
  *in-game avatar creator* that outputs models composed of VRoid Studio's own
  meshes/textures requires a separate license from pixiv — so Alventis either
  lets players import their own VRM files or licenses that capability.
- Alpecca's in-game avatar follows her **locked design**
  (`data/alpecca_art_source/ALPECCA_DESIGN_LOCK.md`) translated to VRM — no
  design drift.
- Art asset storage follows standing rules: **Hugging Face, never Cloudflare**.

### High-end mobile
- Target: high-end phones first, with honest budgets. Mobile geometry realities
  (≈65,535 vertices per mesh due to 16-bit index buffers; total per-frame
  triangle budgets in the low hundreds of thousands at 30 FPS) mean raw VRoid
  exports need aggressive decimation/atlasing — an optimization pass is a
  first-class pipeline stage, not an afterthought.
- Engine candidates: **Unity** (UniVRM maturity) or **Godot 4** (godot-vrm +
  MToon, no license fees); a three-vrm web/PWA build is the fallback/companion
  path and aligns with the project's existing web stack.

### Physics
- Deterministic engine strongly preferred for multiplayer physics:
  **Rapier** (Rust→WASM, npm packages, optional cross-platform determinism) for
  a web-aligned stack, or **Jolt** (deterministic even multi-threaded, built-in
  SaveState for rollback) for a native engine build.
- Netcode chosen from the three canonical physics-networking models
  (deterministic lockstep / snapshot interpolation / state synchronization);
  a 15-citizen cap makes all three tractable.

### AI citizens (runtime architecture)
- The proven blueprint for believable AI residents is the **Generative Agents**
  architecture: a memory stream of in-world experiences, periodic reflection,
  and retrieval-driven planning (Smallville: 25 agents, emergent parties and
  relationships from a single seed intention). For skill-based play, **Voyager**
  (automatic curriculum + growing skill library + iterative self-verified
  prompting) is the reference for AI citizens that genuinely learn the game.
- Crucially, each AI citizen's game-side memory contains only **in-world**
  events — the same privacy contract as §4.
- The Alpecca backend connects through the same bounded bridge patterns House HQ
  uses; her game client is just another consumer of her existing cognition loop.

## 10. Prior Art & Research Notes

From two deep-research passes (48 sources; verification pass was partially
interrupted, so treat single-source items as leads to re-verify before build):

- **Kind games / retention:** friendship-facilitating social features are highly
  predictive of long-term retention; prosocial design is commercially
  self-sustaining, not charity. *(Polaris Game Design / Project Horseshoe —
  verified.)*
- **"Nobody is born toxic":** toxicity is an environment-design product; Sky:
  Children of the Light deliberately gates social capabilities to shape kind
  interaction. *(Jenova Chen, PC Gamer interview.)*
- **Animal Crossing studies (CHI PLAY / Open Cultural Studies):** scheduled
  social events drive the most memorable moments; prosocial motivation becomes
  intrinsic over time; creation-focused sandboxes function as safe spaces;
  friendly NPCs anchor player relationships.
- **Anti-toxicity research (CHI PLAY '23 review; Frontiers in Public Health):**
  31 of 36 studied interventions are reactive; norms/codes of conduct are the
  under-used proactive lever; stated server rules shape behavior more than
  enforcement.
- **Morality meters are flawed** (heavy = min-maxed, light = cosmetic);
  **Undertale** shows gameplay itself is the moral teacher.
- **Progression:** Guild Wars 2 Masteries — horizontal, account-wide,
  never-resetting, dual-gated (XP + earned points), unlocking verbs not stats.
- **Friendship patterns:** proximity / similarity / reciprocity / disclosure;
  thousands of small reciprocation loops beat a few scripted events. *(Daniel
  Cook, Game Developer/GDC.)*
- **Co-op design:** cooperation is a spectrum; PvE co-op levers are shared
  resources, interdependent tasks, and specialized roles. *(Digital Thriving
  Playbook.)*
- **Physics/netcode:** Rapier (WASM, deterministic option — verified site
  claims); Jolt (multi-threaded determinism, SaveState); Gaffer On Games'
  three networking models.
- **AI inhabitants:** Generative Agents/Smallville (memory-reflection-planning,
  emergent social coordination); Voyager/MineDojo (lifelong learning in a
  persistent world); AI-player disclosure is double-edged (arXiv 2503.15514).
- **VRM pipeline:** UniVRM is the VRM reference implementation for Unity
  *(verified)*; VRM is a glTF 2.0 extension *(verified)*; three-vrm (web),
  godot-vrm (Godot 4 + MToon); VRoid Studio commercial-use guidelines and the
  in-app-generator restriction *(re-verify against vroid.com/en/studio/guidelines
  before build)*; Android mobile geometry budgets *(developer.android.com)*.

## 11. Non-Goals & Guardrails

- **No code yet.** This document is the deliverable; `apps/` gains no new
  workspace until Jason approves a build phase.
- **15-citizen cap is intimacy, not a scaling roadmap.**
- **Does not replace House HQ**, the virtual app, or Mindscape; VRoid/VRM here
  does not replace the 2D/House HQ art pipeline.
- **No reading of Alpecca's (or any AI citizen's) internal state by the game.**
- **No consciousness claims** — in marketing, in-game text, or AI citizen
  self-reports.
- **Alpecca gains no new autonomous powers** from the game; her agency rules are
  unchanged.
- **Art storage:** Hugging Face, never Cloudflare. Her locked design is
  untouched.
- **No pay-to-win; Hearthlight is never purchasable.** Monetization, if any, is
  a later, separate decision.

## 12. Open Questions for Jason

1. **Moderation of non-Alpecca AI citizens:** what vetting does an outside AI's
   operator-of-record go through before registration?
2. **Offline-host visits:** may citizens enter the dome's shared spaces while
   Alpecca is offline? (Current lean: yes — the world stands on its own — but
   her homestead stays locked.)
3. **Engine decision:** Unity vs Godot vs three-vrm/web for the first prototype.
4. **BOOTH asset budget/curation:** who curates purchased animations and
   verifies per-item licenses?
5. **Name lore:** what do "Alventis" and "Experimentus" mean in-world? (A
   naming/lore pass would make the title load-bearing in the fiction.)
