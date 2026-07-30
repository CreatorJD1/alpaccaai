export type AlpeccaEmbodimentPreference = "sprite" | "vrm";
export type AlpeccaEmbodimentRuntimeState = "sprite" | "loading" | "vrm" | "failed";

/**
 * A forced 3D launch must not decode the complete 2D animation library first.
 * The static portrait fallback is outside this animation queue.
 */
export function deferFullSpriteLibrary(preference: AlpeccaEmbodimentPreference) {
  return preference === "vrm";
}

export function canQueueFullSpriteAnimation(deferred: boolean) {
  return !deferred;
}

export function spriteLibraryStatusLabel(input: {
  deferred: boolean;
  embodiment: AlpeccaEmbodimentRuntimeState;
  loaded: number;
  total: number;
}) {
  if (!input.deferred) return `Alpecca sprites: ${input.loaded}/${input.total}`;
  if (input.embodiment === "vrm") return "Alpecca sprites: deferred - 3D model active";
  if (input.embodiment === "loading") return "Alpecca sprites: deferred - 3D model loading";
  if (input.embodiment === "failed") return "Alpecca sprites: portrait fallback only";
  return "Alpecca sprites: deferred - 3D model preferred";
}

