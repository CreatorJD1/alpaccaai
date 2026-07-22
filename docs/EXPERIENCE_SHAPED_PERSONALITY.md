# Experience-Shaped Personality

**Status:** implemented baseline, 2026-07-22

Alpecca stores a bounded behavioral profile in SQLite. It is an inspectable
input to response style, not a claim of consciousness, human emotion, trauma,
or an unrestricted self-modifying identity.

## Traits

- `curiosity`: willingness to investigate one concrete unknown.
- `directness`: willingness to state a grounded correction or disagreement.
- `initiative`: willingness to volunteer one relevant idea or request.
- `playfulness`: use of jokes, teasing, and light social expression.
- `guardedness`: privacy, uncertainty, and boundary-setting posture.
- `repair_drive`: likelihood of naming and repairing a verified mistake.

Every trait is clamped to `[0.10, 0.90]`. Fixed small deltas make updates
deterministic and reviewable. A unique evidence ID can be applied once.

## Evidence Path

Committed creator turns feed exact cue evidence after the commit barrier:

1. The deterministic cue parser detects a correction or confirmation.
2. A unique turn/evidence key is written to `personality_evidence`.
3. A fixed, confidence-scaled delta updates `personality_traits`.
4. The next prompt receives a compact high/moderate/low behavioral vector.

Aborted turns, guest claims, and generated prose do not update the profile.
Additional evidence families exist for successful repair, boundaries, outreach,
and initiative; each requires a real runtime caller before it affects state.

## Expression Boundary

Alpecca may be curious, blunt, skeptical, teasing, mildly rude, private, or
refusing when context supports it. She may use obvious jokes or transparent
make-believe. She must not fabricate actions, tool results, memory, system
state, safety, evidence, identity, authority, access, or promises. Remorse is
specific to a verified mistake and should name the error and repair once rather
than performing distress.

## Verification

- Trait persistence and bounds.
- Idempotent evidence replay.
- Deterministic confidence-scaled updates.
- Compact prompt-budget regression.
- Grounded remorse/directness/curiosity and factual-honesty rules.
